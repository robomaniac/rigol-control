"""Automated pagination check for issued PDF reports (acceptance PDF-02).

Every page of a finished PDF is inspected and findings are reported with page
numbers: an orphan heading at the bottom of a page, a caption separated from
its figure, a table row alone at the top of a page or a table header alone at
the bottom, text outside the page box, a missing page number or report/run
identity, and blank or nearly empty pages (brief section 12.6).

Two independent extractions feed the checks. Poppler's ``pdftohtml -xml``
supplies every text line with its position, size and weight. pypdf supplies
the page boxes, the tagged structure tree that Typst writes (headings, tables,
rows, figures and captions) and the geometry drawn under each marked-content
sequence, so a figure is recognised by its drawing, not by a file name. When
a document carries no structure tree the heading check falls back to a
font-size heuristic and the table/caption structure checks are reported as not
run. An extraction problem is itself a finding: a missing tool, an unreadable
file or a page that could not be scanned never counts as a pass.

This module renders nothing and never touches instruments.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SCHEMA_VERSION = "1.0"
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
EDGE_TOLERANCE_PT = 1.0
FOOTER_BAND = 0.15
HEADER_BAND = 0.12
SPARSE_PAGE_CHARACTERS = 40
DRAWING_MIN_WIDTH_PT = 40.0
DRAWING_MIN_HEIGHT_PT = 20.0
DRAWING_MIN_SEGMENTS = 4
HEADING_SIZE_RATIO = 1.15
PDFTOHTML_TIMEOUT_S = 120
HEADING_ROLE = re.compile(r"^H[1-6]?$")
CONTAINER_ROLES = {"Document", "Part", "Art", "Sect", "NonStruct", "Private"}
PAGE_NUMBER = re.compile(r"^\s*(?:page\s+)?\d+\s*(?:/\s*\d+|of\s+\d+)?\s*$", re.I)
# Quarto/Typst captions read "Figure N: …". A wrapped cross-reference such as
# "See Figure 3." can start a text line, so the period form is not a caption.
FIGURE_CAPTION = re.compile(r"^\s*(?:Figure|Fig\.)\s*\d+\s*:", re.I)


@dataclass(frozen=True)
class BBox:
    """Top-down page coordinates in points, relative to the crop box."""
    left: float
    top: float
    right: float
    bottom: float

    def union(self, other: "BBox | None") -> "BBox":
        if other is None:
            return self
        return BBox(min(self.left, other.left), min(self.top, other.top),
                    max(self.right, other.right), max(self.bottom, other.bottom))

    def as_list(self) -> list[float]:
        return [round(value, 2) for value in (self.left, self.top, self.right, self.bottom)]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    page: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "page": self.page,
                "message": self.message, "details": dict(self.details)}


@dataclass
class TextLine:
    """One positioned text line from pdftohtml (points, top-down)."""
    left: float
    top: float
    width: float
    height: float
    size: float
    bold: bool
    text: str

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height


@dataclass
class Region:
    """Geometry drawn under one marked-content key on one page."""
    bbox: BBox | None = None
    segments: int = 0
    images: int = 0
    texts: list[str] = field(default_factory=list)

    def include(self, left: float, top: float, right: float, bottom: float) -> None:
        self.bbox = BBox(min(left, right), min(top, bottom), max(left, right), max(top, bottom)).union(self.bbox)

    def merge(self, other: "Region") -> None:
        if other.bbox is not None:
            self.bbox = other.bbox.union(self.bbox)
        self.segments += other.segments
        self.images += other.images
        self.texts.extend(other.texts)

    @property
    def text(self) -> str:
        return " ".join(part.strip() for part in self.texts if part.strip())

    @property
    def is_drawing(self) -> bool:
        if self.images:
            return True
        if self.bbox is None or self.segments < DRAWING_MIN_SEGMENTS:
            return False
        return (self.bbox.right - self.bbox.left >= DRAWING_MIN_WIDTH_PT
                and self.bbox.bottom - self.bbox.top >= DRAWING_MIN_HEIGHT_PT)


@dataclass(eq=False)
class Element:
    """A structure-tree element; ``marks`` are (page, MCID) pairs it owns directly."""
    role: str
    parent: "Element | None" = field(default=None, repr=False)
    children: list["Element"] = field(default_factory=list, repr=False)
    marks: list[tuple[int | None, int]] = field(default_factory=list)

    def iter(self):
        yield self
        for child in self.children:
            yield from child.iter()


@dataclass
class Page:
    number: int
    width: float
    height: float
    lines: list[TextLine] = field(default_factory=list)
    regions: dict[Any, Region] = field(default_factory=dict)
    scan_error: str | None = None

    def region(self, key: Any) -> Region:
        return self.regions.setdefault(key, Region())

    def artifact_text(self, kind: str) -> str | None:
        region = self.regions.get(("artifact", kind))
        return region.text if region is not None and region.text else None

    def drawings(self) -> list[BBox]:
        return [region.bbox for key, region in sorted(self.regions.items(), key=lambda item: str(item[0]))
                if region.is_drawing and region.bbox is not None]

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)


@dataclass
class Document:
    """Everything extracted from one PDF, before any judgement."""
    path: str
    page_count: int = 0
    tagged: bool | None = None
    pages: list[Page] = field(default_factory=list)
    root: Element | None = None
    outline_items: int = 0
    tools: dict[str, Any] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)

    @property
    def text_available(self) -> bool:
        return self.tools.get("pdftohtml") is not None and not any(
            finding.code in ("pdftohtml-failed", "pdftohtml-xml-invalid") for finding in self.problems)


@dataclass
class Analysis:
    findings: list[Finding]
    pages: list[dict[str, Any]]


@dataclass
class PdfCheckResult:
    path: str
    page_count: int
    tagged: bool | None
    tools: dict[str, Any]
    findings: list[Finding]
    pages: list[dict[str, Any]]

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def status(self) -> str:
        if self.errors:
            return "fail"
        if any(finding.severity == "warning" for finding in self.findings):
            return "warning"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        counts = Counter(finding.severity for finding in self.findings)
        return {"schema_version": SCHEMA_VERSION, "path": self.path, "status": self.status,
                "page_count": self.page_count, "pages_inspected": len(self.pages), "tagged": self.tagged,
                "tools": dict(self.tools),
                "counts": {name: counts.get(name, 0) for name in SEVERITY_ORDER},
                "findings": [finding.to_dict() for finding in self.findings], "pages": list(self.pages)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)


def check_pdf(path: Path | str, model: dict | None = None) -> PdfCheckResult:
    """Inspect every page of ``path``; ``model`` enables run/DUT identity checks."""
    document = extract_document(Path(path))
    analysis = analyze(document, model)
    return PdfCheckResult(path=str(path), page_count=document.page_count, tagged=document.tagged,
                          tools=document.tools, findings=analysis.findings, pages=analysis.pages)


# --------------------------------------------------------------------------- extraction

def extract_document(path: Path) -> Document:
    document = Document(path=str(path))
    if not path.is_file() or path.stat().st_size == 0:
        document.problems.append(Finding("pdf-missing", "error", f"PDF file is missing or empty: {path}"))
        return document
    _scan_with_pypdf(document, path)
    _extract_text_lines(document, path)
    return document


def _multiply(m: Any, n: Any) -> tuple[float, ...]:
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5])


def _scan_with_pypdf(document: Document, path: Path) -> None:
    try:
        import pypdf
        from pypdf import PdfReader
    except ImportError as exc:
        document.tools["pypdf"] = None
        document.problems.append(Finding("pypdf-unavailable", "error",
            f"pypdf is not installed; page boxes, structure and drawing checks could not run ({exc})"))
        return
    document.tools["pypdf"] = getattr(pypdf, "__version__", "unknown")
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except Exception as exc:
        document.problems.append(Finding("pdf-unreadable", "error", f"pypdf could not read the PDF: {type(exc).__name__}: {exc}"))
        return
    document.page_count = len(pages)
    page_index: dict[int, int] = {}
    for number, page in enumerate(pages, 1):
        try:
            box = page.cropbox
            info = Page(number=number, width=float(box.width), height=float(box.height))
        except Exception as exc:
            info = Page(number=number, width=0.0, height=0.0, scan_error=f"page box unreadable: {exc}")
        reference = getattr(page, "indirect_reference", None)
        if reference is not None:
            page_index[reference.idnum] = number
        if info.scan_error is None:
            _scan_page(page, info)
        document.pages.append(info)
    try:
        document.outline_items = sum(1 for _ in _flatten_outline(reader.outline))
    except Exception:
        document.outline_items = 0
    try:
        root = reader.trailer["/Root"]
        tree = root.get("/StructTreeRoot")
        document.tagged = tree is not None
        if tree is not None:
            document.root = _structure(tree, page_index)
    except Exception as exc:
        document.problems.append(Finding("structure-unreadable", "error",
            f"The PDF structure tree could not be read: {type(exc).__name__}: {exc}"))
        document.root = None


def _flatten_outline(items: Any):
    for item in items or []:
        if isinstance(item, list):
            yield from _flatten_outline(item)
        else:
            yield item


def _scan_page(page: Any, info: Page) -> None:
    """Attribute text and drawing geometry to marked-content keys (top-down points)."""
    height = info.height
    try:
        origin_x, origin_y = float(page.cropbox.left), float(page.cropbox.bottom)
    except Exception:
        origin_x = origin_y = 0.0
    xobjects: dict[str, str] = {}
    try:
        resources = page.get("/Resources")
        for name, ref in ((resources or {}).get("/XObject") or {}).items():
            xobjects[str(name)] = str(ref.get_object().get("/Subtype"))
    except Exception:
        xobjects = {}
    stack: list[Any] = []

    def current() -> Region:
        return info.region(stack[-1] if stack else ("untagged", "content"))

    def key_for(operands: list) -> Any:
        tag = str(operands[0]).lstrip("/") if operands else "unknown"
        properties = operands[1] if len(operands) > 1 else None
        if hasattr(properties, "get"):
            mcid = properties.get("/MCID")
            if mcid is not None:
                return int(mcid)
            if tag == "Artifact":
                subtype = properties.get("/Subtype") or properties.get("/Type")
                return ("artifact", str(subtype).lstrip("/") if subtype is not None else "unknown")
        return ("tag", tag)

    def device(x: float, y: float, matrix: Any) -> tuple[float, float]:
        dx = matrix[0] * x + matrix[2] * y + matrix[4] - origin_x
        dy = matrix[1] * x + matrix[3] * y + matrix[5] - origin_y
        return dx, height - dy

    def include_points(region: Region, matrix: Any, points: list[tuple[float, float]]) -> None:
        for x, y in points:
            dx, dy = device(x, y, matrix)
            region.include(dx, dy, dx, dy)

    def before(operator: bytes, operands: list, cm: Any, tm: Any) -> None:
        if operator in (b"BDC", b"BMC"):
            stack.append(key_for(operands))
        elif operator == b"EMC":
            if stack:
                stack.pop()
        elif operator in (b"m", b"l", b"c", b"v", b"y", b"re", b"Do"):
            try:
                values = [float(value) for value in operands] if operator != b"Do" else []
            except (TypeError, ValueError):
                return
            region = current()
            if operator == b"m" and len(values) >= 2:
                include_points(region, cm, [(values[0], values[1])])
            elif operator == b"l" and len(values) >= 2:
                include_points(region, cm, [(values[0], values[1])])
                region.segments += 1
            elif operator in (b"c", b"v", b"y") and len(values) >= 4:
                include_points(region, cm, list(zip(values[0::2], values[1::2])))
                region.segments += 1
            elif operator == b"re" and len(values) >= 4:
                x, y, w, h = values[:4]
                include_points(region, cm, [(x, y), (x + w, y), (x, y + h), (x + w, y + h)])
                region.segments += 4
            elif operator == b"Do" and operands:
                include_points(region, cm, [(0, 0), (1, 0), (0, 1), (1, 1)])
                if xobjects.get(str(operands[0])) == "/Image":
                    region.images += 1

    def text(content: str, cm: Any, tm: Any, font: Any, size: Any) -> None:
        if not content or not content.strip():
            return
        matrix = _multiply(tm, cm)
        x, baseline = device(0.0, 0.0, matrix)
        scale = math.hypot(matrix[1], matrix[3]) or 1.0
        try:
            effective = abs(float(size or 0.0)) * scale
        except (TypeError, ValueError):
            effective = 0.0
        region = current()
        region.include(x, baseline - 0.85 * effective, x + 0.5 * effective * len(content.strip()), baseline + 0.25 * effective)
        region.texts.append(content.strip("\n"))

    try:
        page.extract_text(visitor_operand_before=before, visitor_text=text)
    except Exception as exc:
        info.scan_error = f"{type(exc).__name__}: {exc}"


def _structure(tree: Any, page_index: dict[int, int]) -> Element:
    tree = tree.get_object()
    role_map = {str(key): str(value) for key, value in (tree.get("/RoleMap") or {}).items()}

    def resolve_role(name: Any) -> str:
        name = str(name)
        seen: set[str] = set()
        while name in role_map and name not in seen:
            seen.add(name)
            name = role_map[name]
        return name.lstrip("/")

    def page_of(node: Any, inherited: int | None) -> int | None:
        try:
            raw = node.raw_get("/Pg")
        except (KeyError, AttributeError):
            return inherited
        idnum = getattr(raw, "idnum", None)
        if idnum is None:
            reference = getattr(getattr(raw, "get_object", lambda: raw)(), "indirect_reference", None)
            idnum = getattr(reference, "idnum", None)
        return page_index.get(idnum, inherited)

    root = Element(role="Root")

    def walk(node: Any, parent: Element, inherited: int | None, depth: int) -> None:
        if depth > 96 or node is None:
            return
        node = node.get_object() if hasattr(node, "get_object") else node
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            parent.marks.append((inherited, int(node)))
            return
        if isinstance(node, list):
            for kid in node:
                walk(kid, parent, inherited, depth + 1)
            return
        if not hasattr(node, "get"):
            return
        node_type = node.get("/Type")
        if node_type == "/MCR":
            parent.marks.append((page_of(node, inherited), int(node.get("/MCID"))))
            return
        if node_type == "/OBJR":
            return
        role = node.get("/S")
        if role is None:
            return
        element = Element(role=resolve_role(role), parent=parent)
        parent.children.append(element)
        page = page_of(node, inherited)
        kids = node.get("/K")
        if kids is not None:
            walk(kids, element, page, depth + 1)

    walk(tree.get("/K"), root, None, 0)
    return root


def _extract_text_lines(document: Document, path: Path) -> None:
    tool = shutil.which("pdftohtml")
    if not tool:
        document.tools["pdftohtml"] = None
        document.problems.append(Finding("pdftohtml-unavailable", "error",
            "poppler-utils pdftohtml is not installed; text positions, clipping, page-number and identity checks could not run"))
        return
    try:
        probe = subprocess.run([tool, "-v"], capture_output=True, text=True, timeout=30)
        match = re.search(r"version\s+(\S+)", probe.stderr + probe.stdout)
        document.tools["pdftohtml"] = match.group(1) if match else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        document.tools["pdftohtml"] = "unknown"
    with tempfile.TemporaryDirectory(prefix="dcdc-pdf-check-") as scratch:
        base = Path(scratch) / "text"
        try:
            result = subprocess.run([tool, "-xml", "-i", "-q", "-zoom", "1", str(path), str(base)],
                                    capture_output=True, text=True, timeout=PDFTOHTML_TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            document.problems.append(Finding("pdftohtml-failed", "error", f"pdftohtml did not complete: {type(exc).__name__}: {exc}"))
            return
        xml_path = base.with_suffix(".xml")
        if result.returncode or not xml_path.is_file():
            document.problems.append(Finding("pdftohtml-failed", "error",
                f"pdftohtml exited with status {result.returncode}: {(result.stderr or result.stdout).strip()[:500]}"))
            return
        try:
            tree = ElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError as exc:
            document.problems.append(Finding("pdftohtml-xml-invalid", "error", f"pdftohtml produced unparsable XML: {exc}"))
            return
    fonts = {spec.get("id"): float(spec.get("size") or 0) for spec in tree.iter("fontspec")}
    xml_pages = tree.findall("page")
    if not document.pages:
        document.page_count = len(xml_pages)
        document.pages = [Page(number=index, width=float(node.get("width") or 0), height=float(node.get("height") or 0))
                          for index, node in enumerate(xml_pages, 1)]
    elif len(xml_pages) != document.page_count:
        document.problems.append(Finding("page-count-mismatch", "error",
            f"pypdf reports {document.page_count} page(s) but pdftohtml extracted {len(xml_pages)}"))
    if not document.outline_items:
        document.outline_items = sum(1 for _ in tree.iter("item"))
    for index, node in enumerate(xml_pages, 1):
        try:
            number = int(node.get("number") or index)
        except ValueError:
            number = index
        if not 1 <= number <= len(document.pages):
            continue
        page = document.pages[number - 1]
        for text in node.findall("text"):
            content = "".join(text.itertext())
            if not content.strip():
                continue
            try:
                page.lines.append(TextLine(left=float(text.get("left")), top=float(text.get("top")),
                                           width=float(text.get("width")), height=float(text.get("height")),
                                           size=fonts.get(text.get("font"), 0.0), bold=text.find(".//b") is not None,
                                           text=content))
            except (TypeError, ValueError):
                document.problems.append(Finding("pdftohtml-xml-invalid", "warning",
                    f"A text element on page {number} lacks numeric coordinates and was ignored", number))


# --------------------------------------------------------------------------- analysis

class _Checker:
    def __init__(self, document: Document, model: dict | None):
        self.document = document
        self.model = model or {}
        self.findings: list[Finding] = list(document.problems)
        self._regions: dict[int, dict[int, Region]] = {}
        self.blocks: list[Element] | None = None
        if document.root is not None:
            self.blocks = self._flatten(document.root)
        self.elements = list(document.root.iter()) if document.root is not None else []
        self.structured = bool(document.tagged and self.blocks is not None)

    # -- structure helpers
    def _flatten(self, root: Element) -> list[Element]:
        blocks: list[Element] = []

        def visit(element: Element) -> None:
            nested_heading = any(HEADING_ROLE.match(node.role) for node in element.iter() if node is not element)
            if element.role in CONTAINER_ROLES or (element.role == "Div" and nested_heading):
                for child in element.children:
                    visit(child)
            else:
                blocks.append(element)

        for child in root.children:
            visit(child)
        return blocks

    def regions(self, element: Element) -> dict[int, Region]:
        cached = self._regions.get(id(element))
        if cached is not None:
            return cached
        merged: dict[int, Region] = {}
        for node in element.iter():
            for page_number, mcid in node.marks:
                if not page_number or page_number > len(self.document.pages):
                    continue
                region = self.document.pages[page_number - 1].regions.get(mcid)
                if region is None or region.bbox is None:
                    continue
                merged.setdefault(page_number, Region()).merge(region)
        self._regions[id(element)] = merged
        return merged

    @staticmethod
    def label(element: Element, regions: dict[int, Region]) -> str:
        text = " ".join(regions[page].text for page in sorted(regions)).strip()
        return text[:80]

    def add(self, code: str, severity: str, message: str, page: int | None = None, **details: Any) -> None:
        self.findings.append(Finding(code, severity, message, page, details))

    # -- page-level text checks
    def header_line(self, page: Page) -> str | None:
        artifact = page.artifact_text("Header")
        if artifact:
            return artifact
        band = [line for line in page.lines if line.top <= page.height * HEADER_BAND]
        return min(band, key=lambda line: line.top).text if band else None

    def page_number_line(self, page: Page) -> str | None:
        footer = page.artifact_text("Footer")
        if footer and PAGE_NUMBER.match(footer):
            return footer
        candidates = [line for line in page.lines
                      if line.top >= page.height * (1 - FOOTER_BAND) and PAGE_NUMBER.match(line.text)]
        return max(candidates, key=lambda line: line.top).text if candidates else None

    def body_lines(self, page: Page) -> list[TextLine]:
        header, number = self.header_line(page), self.page_number_line(page)
        return [line for line in page.lines if not (
            (header and line.text == header and line.top <= page.height * HEADER_BAND)
            or (number and line.text == number and line.top >= page.height * (1 - FOOTER_BAND)))]

    def check_text_extents(self) -> None:
        for page in self.document.pages:
            for line in page.lines:
                if (line.left < -EDGE_TOLERANCE_PT or line.top < -EDGE_TOLERANCE_PT
                        or line.right > page.width + EDGE_TOLERANCE_PT or line.bottom > page.height + EDGE_TOLERANCE_PT):
                    self.add("clipped-text", "error",
                             f"Text extends beyond the {page.width:.1f}×{page.height:.1f} pt page box on page {page.number}: "
                             f"{line.text.strip()[:80]!r} occupies x {line.left:.1f}–{line.right:.1f}, y {line.top:.1f}–{line.bottom:.1f}",
                             page.number, text=line.text.strip()[:200],
                             bbox=[round(line.left, 2), round(line.top, 2), round(line.right, 2), round(line.bottom, 2)])

    def check_page_numbers(self) -> None:
        for page in self.document.pages:
            if self.page_number_line(page) is None:
                self.add("page-number-missing", "error", f"No page number was found in the footer band of page {page.number}", page.number)

    def check_identity(self) -> None:
        run_id = self.model.get("run_id")
        dut = self.model.get("dut") or {}
        dut_identity = dut.get("identity", {}).get("model", dut.get("model", dut.get("name"))) if isinstance(dut, dict) else None
        headers: dict[int, str | None] = {}
        for page in self.document.pages:
            header = self.header_line(page)
            headers[page.number] = header
            text = page.text
            if run_id:
                if str(run_id) not in text:
                    self.add("identity-missing", "error", f"Run identifier {run_id!r} does not appear on page {page.number}", page.number)
                if dut_identity and str(dut_identity) not in text:
                    self.add("dut-identity-missing", "warning", f"DUT identity {dut_identity!r} does not appear on page {page.number}", page.number)
            elif not header:
                self.add("identity-missing", "error",
                         f"Page {page.number} has no running header carrying the report identity (no report model was supplied to verify a run identifier)",
                         page.number)
        if not run_id and len({value for value in headers.values() if value}) > 1:
            self.add("identity-inconsistent", "warning", "The running header differs between pages",
                     headers={str(number): value for number, value in headers.items()})

    def check_sparse_pages(self) -> None:
        for page in self.document.pages:
            characters = sum(len(line.text.strip()) for line in self.body_lines(page))
            drawings = page.drawings()
            if characters == 0 and not drawings:
                self.add("blank-page", "error", f"Page {page.number} carries no body text and no drawing", page.number)
            elif characters < SPARSE_PAGE_CHARACTERS and not drawings:
                self.add("sparse-page", "warning",
                         f"Page {page.number} carries only {characters} character(s) of body text and no drawing", page.number,
                         characters=characters)

    # -- tagged structure checks
    def page_items(self, page_number: int) -> list[tuple[Element, Region]]:
        items = []
        for element in self.blocks or []:
            region = self.regions(element).get(page_number)
            if region is not None and region.bbox is not None:
                items.append((element, region))
        return items

    def check_headings_tagged(self) -> None:
        for page in self.document.pages:
            items = self.page_items(page.number)
            for element, region in items:
                if not HEADING_ROLE.match(element.role):
                    continue
                followed = any(not HEADING_ROLE.match(other.role) and other_region.bbox.top > region.bbox.top
                               for other, other_region in items)
                if not followed:
                    self.add("orphan-heading", "error",
                             f"Heading {region.text[:80]!r} is the last content on page {page.number}; "
                             "its introductory content starts on a later page", page.number,
                             heading=region.text[:200], bbox=region.bbox.as_list())

    def check_headings_heuristic(self) -> None:
        weights: Counter = Counter()
        for page in self.document.pages:
            for line in self.body_lines(page):
                weights[round(line.size, 1)] += len(line.text)
        if not weights:
            return
        body_size = weights.most_common(1)[0][0]
        for page in self.document.pages:
            lines = self.body_lines(page)
            heading = [line for line in lines if line.bold and line.size >= body_size * HEADING_SIZE_RATIO and len(line.text) < 120]
            for line in heading:
                followed = any(other not in heading and other.top > line.top for other in lines)
                if not followed:
                    self.add("orphan-heading", "error",
                             f"Heading {line.text.strip()[:80]!r} (font-size heuristic) is the last text on page {page.number}",
                             page.number, heading=line.text.strip()[:200], method="font-size heuristic")

    def check_tables(self) -> None:
        for table in (element for element in self.elements if element.role == "Table"):
            header_rows, body_rows = [], []
            for node in table.iter():
                if node.role != "TR":
                    continue
                ancestors = []
                parent = node.parent
                while parent is not None and parent is not table:
                    ancestors.append(parent.role)
                    parent = parent.parent
                cells = [child for child in node.children if child.role in ("TH", "TD")]
                if "THead" in ancestors or (cells and all(child.role == "TH" for child in cells)):
                    header_rows.append(node)
                else:
                    body_rows.append(node)
            label = self.label(header_rows[0], self.regions(header_rows[0])) if header_rows and self.regions(header_rows[0]) else (
                self.label(body_rows[0], self.regions(body_rows[0])) if body_rows and self.regions(body_rows[0]) else "table")
            body_pages: Counter = Counter()
            for row in body_rows:
                for page_number in self.regions(row):
                    body_pages[page_number] += 1
            if not body_pages:
                continue
            ordered = sorted(body_pages)
            if len(ordered) > 1:
                last = ordered[-1]
                if body_pages[last] == 1:
                    self.add("lone-table-row", "error",
                             f"The last row of table {label!r} stands alone at the top of page {last}; "
                             f"the other {len(body_rows) - 1} row(s) end on page {ordered[-2]}", last,
                             table=label, rows_per_page={str(number): body_pages[number] for number in ordered})
                first = ordered[0]
                if body_pages[first] == 1 and len(body_rows) > 1:
                    self.add("table-split-after-first-row", "warning",
                             f"Table {label!r} starts with a single row at the bottom of page {first} and continues on page {ordered[1]}",
                             first, table=label, rows_per_page={str(number): body_pages[number] for number in ordered})
            header_pages: set[int] = set()
            for row in header_rows:
                header_pages.update(self.regions(row))
            for page_number in sorted(header_pages - set(body_pages)):
                self.add("table-header-alone", "error",
                         f"The header of table {label!r} is alone at the bottom of page {page_number}; its rows start on page {ordered[0]}",
                         page_number, table=label)

    def check_captions_tagged(self) -> None:
        for caption in (element for element in self.elements if element.role == "Caption"):
            caption_regions = self.regions(caption)
            if not caption_regions:
                continue
            container = caption.parent
            while container is not None and container.role in ("Caption", "Span"):
                container = container.parent
            if container is None:
                continue
            caption_nodes = set(id(node) for node in caption.iter())
            figure_pages: set[int] = set()
            for node in container.iter():
                if id(node) in caption_nodes or node is container:
                    continue
                figure_pages.update(self.regions(node))
            caption_pages = set(caption_regions)
            label = self.label(caption, caption_regions)
            first = min(caption_pages)
            if figure_pages:
                if caption_pages.isdisjoint(figure_pages):
                    self.add("caption-separated-from-figure", "error",
                             f"Caption {label!r} is on page {sorted(caption_pages)} but its figure is drawn on page {sorted(figure_pages)}",
                             first, caption=label, caption_pages=sorted(caption_pages), figure_pages=sorted(figure_pages))
                elif len(figure_pages) > 1:
                    self.add("figure-split-across-pages", "warning",
                             f"The figure captioned {label!r} is drawn across pages {sorted(figure_pages)}", first,
                             caption=label, figure_pages=sorted(figure_pages))
            elif not self.document.pages[first - 1].drawings():
                self.add("caption-without-figure", "error",
                         f"Caption {label!r} on page {first} has no figure drawing or image on that page", first, caption=label)
        for figure in (element for element in self.elements if element.role == "Figure"):
            figure_regions = self.regions(figure)
            if not figure_regions:
                continue
            container = figure.parent
            while container is not None and container.role in ("P", "Span"):
                container = container.parent
            has_caption = container is not None and any(
                node.role == "Caption" and self.regions(node) for node in container.iter())
            if not has_caption:
                first = min(figure_regions)
                self.add("figure-without-caption", "warning",
                         f"A figure drawn on page {first} has no caption in the document structure", first)

    def tagged_caption_texts(self, page_number: int) -> list[str]:
        texts = []
        if not self.structured:
            return texts
        for element in self.elements:
            if element.role == "Caption":
                region = self.regions(element).get(page_number)
                if region is not None:
                    texts.append(_normalize(region.text))
        return texts

    def figure_present(self, page: Page) -> bool:
        if page.drawings():
            return True
        return any(page.number in self.regions(element) for element in self.elements if element.role == "Figure")

    def check_caption_text(self) -> None:
        """Caption-like text on a page without any figure drawing (also covers untagged PDFs)."""
        for page in self.document.pages:
            tagged = self.tagged_caption_texts(page.number)
            for line in page.lines:
                if not FIGURE_CAPTION.match(line.text):
                    continue
                normalized = _normalize(line.text)[:24]
                if any(text.startswith(normalized) for text in tagged):
                    continue
                if not self.figure_present(page):
                    self.add("caption-without-figure", "error",
                             f"Caption text {line.text.strip()[:80]!r} on page {page.number} has no figure drawing or image on that page",
                             page.number, caption=line.text.strip()[:200])

    # -- summary
    def page_summary(self, page: Page) -> dict[str, Any]:
        items = self.page_items(page.number) if self.structured else []
        headings = [region.text[:120] for element, region in items if HEADING_ROLE.match(element.role)]
        if not self.structured and self.document.text_available:
            headings = [line.text.strip()[:120] for line in self.body_lines(page)
                        if line.bold and line.size >= self._heuristic_body_size() * HEADING_SIZE_RATIO and len(line.text) < 120]
        tables = sum(1 for element in self.elements if element.role == "Table" and page.number in self.regions(element))
        figures = sum(1 for element in self.elements if element.role == "Figure" and page.number in self.regions(element))
        captions = sum(1 for element in self.elements if element.role == "Caption" and page.number in self.regions(element))
        run_id = self.model.get("run_id")
        return {"number": page.number, "width_pt": round(page.width, 2), "height_pt": round(page.height, 2),
                "text_lines": len(page.lines), "characters": sum(len(line.text.strip()) for line in page.lines),
                "headings": headings, "tables": tables, "figures": figures, "captions": captions,
                "drawings": len(page.drawings()), "running_header": self.header_line(page),
                "page_number": (self.page_number_line(page) or "").strip() or None,
                "run_id_present": (str(run_id) in page.text) if run_id else None,
                "scan_error": page.scan_error,
                "findings": sum(1 for finding in self.findings if finding.page == page.number)}

    def _heuristic_body_size(self) -> float:
        weights: Counter = Counter()
        for page in self.document.pages:
            for line in self.body_lines(page):
                weights[round(line.size, 1)] += len(line.text)
        return weights.most_common(1)[0][0] if weights else 0.0

    def run(self) -> Analysis:
        document = self.document
        for page in document.pages:
            if page.scan_error:
                self.add("content-scan-failed", "error",
                         f"The content of page {page.number} could not be scanned: {page.scan_error}", page.number)
        if document.pages:
            if document.text_available:
                self.check_text_extents()
                self.check_page_numbers()
                self.check_identity()
                self.check_sparse_pages()
            if self.structured:
                self.check_headings_tagged()
                self.check_tables()
                self.check_captions_tagged()
            else:
                if document.tagged is False:
                    self.add("untagged-pdf", "warning",
                             "The PDF has no structure tree; headings are detected by font size and the table/caption structure checks did not run")
                if document.text_available:
                    self.check_headings_heuristic()
            if document.text_available:
                self.check_caption_text()
        findings = sorted(self.findings, key=lambda finding: (
            finding.page or 0, SEVERITY_ORDER.get(finding.severity, 9), finding.code, finding.message))
        self.findings = findings
        pages = [self.page_summary(page) for page in document.pages]
        return Analysis(findings=findings, pages=pages)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def analyze(document: Document, model: dict | None = None) -> Analysis:
    """Judge an extracted document; deterministic for identical input."""
    return _Checker(document, model).run()


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="PDF-02 pagination check for an issued report PDF")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--model", type=Path, help="report_model.json for identity checks (defaults to the sibling file)")
    args = parser.parse_args(argv)
    model_path = args.model
    if model_path is None and (args.pdf.parent / "report_model.json").is_file():
        model_path = args.pdf.parent / "report_model.json"
    model = json.loads(model_path.read_text(encoding="utf-8")) if model_path else None
    result = check_pdf(args.pdf, model)
    print(result.to_json())
    return 0 if result.status != "fail" else 4


if __name__ == "__main__":
    raise SystemExit(main())
