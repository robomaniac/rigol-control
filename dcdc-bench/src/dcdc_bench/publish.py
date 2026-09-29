"""Approval-gated, redacted static publication copy of one issued report revision.

Publication is an explicit choice recorded in an approval file; the existence
of a run folder never publishes anything. This module only reads the source
run folder and writes a new folder elsewhere. It never invokes git, gh, a
browser or the network, and it never writes into the run folder. The copy is
a traceable redacted derivative: ``publication_manifest.json`` records the
source hashes and what was redacted (categories, counts and field names, not
the removed values). ``noindex`` is retained unless the approval says
``public: true``; a robots tag is not access control.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .attachments import MEDIA_TYPES, AssetStore
from .storage import atomic_json

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
# Private, link-local and loopback ranges only: a generic IPv4 pattern would
# corrupt numeric evidence such as "003.371.214.673" inside report tables.
PRIVATE_IPV4 = re.compile(
    rf"(?<![\w.])(?:10\.{_OCTET}\.{_OCTET}\.{_OCTET}|172\.(?:1[6-9]|2\d|3[01])\.{_OCTET}\.{_OCTET}"
    rf"|192\.168\.{_OCTET}\.{_OCTET}|169\.254\.{_OCTET}\.{_OCTET}|127\.{_OCTET}\.{_OCTET}\.{_OCTET})(?!\w|\.\d)")
VISA_RESOURCE = re.compile(r"\b(?:TCPIP|USB|GPIB|ASRL|VXI)\d*::[^\s\"'<>:]+(?:::[^\s\"'<>:]+)*::(?:INSTR|SOCKET)\b")
# A label chain ending in a local-network suffix, only where prose or markup
# delimits it: not JavaScript member access such as ``ua.local.x``,
# ``this.local=``, ``$m.local`` or ``z.local?a:b``. The inline Plotly runtime
# is additionally left byte-identical when its hash is verified (publish_run).
LOCAL_HOSTNAME = re.compile(
    r"(?<![\w.$\-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?:local|lan|home|internal|localdomain)"
    r"(?![\w$\-]|\.[\w$]|[=(\[]|\?\S)")
POSIX_PATH = re.compile(r"(?<![\w/])/(?:home|Users|root|mnt|media|srv)/[^\s\"'<>`)\]},;]*")
WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s\"'<>|]+\\)*[^\\\s\"'<>|]*")
NOINDEX_TAG = '<meta name="robots" content="noindex,nofollow">'
ROBOTS_META = re.compile(r"<meta\s+name=[\"']robots[\"'][^>]*>\s*", re.IGNORECASE)
TEXT_SUFFIXES = {".html", ".json", ".csv", ".svg", ".css", ".txt", ".md"}
PUBLISHED_REPORT_FILES = ("report.html", "report_model.json", "build_manifest.json", "annotations.json",
                          "report_profile.json", "report.css")
NEVER_PUBLISHED = ("raw/", "scpi.jsonl", "request.json", "plan.json", "run.json", "analysis/",
                   "reports/<revision>/report.qmd", "reports/<revision>/report.typ", "reports/<revision>/render-*.log",
                   "reports/<revision>/interactions.html", "reports/<revision>/metadata.html",
                   "reports/<revision>/print-header.typ")
MAX_APPROVAL_BYTES = 200_000
MAX_APPROVAL_DEPTH = 8
MAX_APPROVAL_ATTACHMENTS = 100
# Photographs travel inside text artifacts too: the print figure embeds the
# original as a data: URI and the HTML links the assets/ copy by hash.
DATA_IMAGE_URI = re.compile(r"data:(image/(?:png|jpeg|svg\+xml));base64,([A-Za-z0-9+/=]+)")
ASSET_FILE_NAME = re.compile(r"^([0-9a-f]{64})\.(png|jpg|jpeg|svg|pdf)$")
PLOTLY_RUNTIME = re.compile(r'<script id="dcdc-plotly-runtime">(.*?)</script>', re.S)
WITHHELD_TEXT = "Photograph withheld from publication: this attachment is not on the approval allowlist."
METADATA_POLICY = ("published PNG/JPEG copies are re-encoded without EXIF, GPS, ICC, comment or text metadata "
                   "(pixels unchanged); the originals in the run folder are untouched")


class _ApprovalLoader(yaml.SafeLoader):
    """SafeLoader that refuses anchors, aliases and deep nesting: a flat approval record needs none."""

    def __init__(self, stream):
        super().__init__(stream)
        self._depth = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases (*name) are not accepted in an approval record")
        if getattr(self.peek_event(), "anchor", None) is not None:
            raise ValueError("YAML anchors (&name) are not accepted in an approval record")
        self._depth += 1
        try:
            if self._depth > MAX_APPROVAL_DEPTH:
                raise ValueError(f"approval record nests deeper than {MAX_APPROVAL_DEPTH} levels")
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


class PublicationApproval(BaseModel):
    """The approval record; every field is required to be explicit."""
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    report_revision: str = Field(pattern=r"^r\d{4}$")
    approver: str = Field(min_length=1)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    public: bool
    attachments: list[str] = Field(default_factory=list)
    keep_serials: bool = False
    include_pdf: bool = False
    # Publish a revision whose build_manifest.json status is not "success"
    # (failed-validation, unverified, failed or missing). Recorded in the
    # publication manifest; never implied.
    allow_unverified: bool = False
    statement: str | None = None

    @field_validator("approver")
    @classmethod
    def approver_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approver must not be blank")
        return value.strip()

    @field_validator("date", mode="before")
    @classmethod
    def date_text(cls, value: Any) -> Any:
        # YAML resolves an unquoted ``2026-09-27`` to a date object; the documented
        # example writes it that way, so accept it as its ISO text (a datetime is
        # still refused by the pattern: an approval names a calendar day).
        return value.isoformat() if isinstance(value, date) and not isinstance(value, datetime) else value

    @field_validator("date")
    @classmethod
    def calendar_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


def load_approval(path: Path) -> PublicationApproval:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Publication requires an approval record; {path} does not exist. "
                         "A run folder alone never authorizes publication.")
    if path.stat().st_size > MAX_APPROVAL_BYTES:
        raise ValueError("Approval record exceeds the 200 kB size limit")
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_ApprovalLoader)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise ValueError(f"Approval record {path} is not acceptable YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("Approval record must be a mapping")
    attachments = data.get("attachments")
    if attachments is not None and (not isinstance(attachments, list) or len(attachments) > MAX_APPROVAL_ATTACHMENTS
                                    or any(not isinstance(item, str) or len(item) > 200 for item in attachments)):
        raise ValueError(f"Approval record {path} is invalid: attachments must list at most "
                         f"{MAX_APPROVAL_ATTACHMENTS} short attachment IDs")
    try:
        return PublicationApproval.model_validate(data)
    except ValueError as exc:
        raise ValueError(f"Approval record {path} is invalid: {exc}") from None


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _build_status(report_dir: Path) -> str | None:
    """The renderer's verdict for the revision; None when the manifest is missing or unreadable."""
    manifest = report_dir / "build_manifest.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return None
    status = payload.get("status") if isinstance(payload, dict) else None
    return str(status) if status is not None else None


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _regular_file(source: Path, root: Path) -> bool:
    """True for a regular file inside ``root``; a symbolic link is refused, never followed."""
    if source.is_symlink():
        raise ValueError(f"{source} is a symbolic link; publication never follows links out of the report folder")
    return source.is_file() and _inside(source, root)


def _strip_raster_metadata(data: bytes) -> bytes:
    """Re-encode a PNG/JPEG without EXIF, GPS, ICC, comments or text chunks; pixels unchanged."""
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.format not in ("PNG", "JPEG"):
            raise ValueError(f"published rasters must be PNG or JPEG, not {image.format}")
        # Transparency is picture content, not metadata; everything else in
        # ``info`` (exif, icc_profile, comment, dpi, text chunks) is dropped.
        image.info = {"transparency": image.info["transparency"]} if "transparency" in image.info else {}
        out = io.BytesIO()
        if image.format == "JPEG":
            image.save(out, format="JPEG", quality="keep")
        else:
            image.save(out, format="PNG")
    return out.getvalue()


def _embedded_images(text: str) -> list[tuple[str, str, str]]:
    """(base64 payload, media type, SHA-256 of the decoded bytes) for every data: image in a text file."""
    found, seen = [], set()
    for match in DATA_IMAGE_URI.finditer(text):
        payload = match.group(2)
        if payload in seen:
            continue
        seen.add(payload)
        try:
            decoded = base64.b64decode(payload, validate=True)
        except ValueError:
            decoded = b""
        found.append((payload, match.group(1), hashlib.sha256(decoded).hexdigest()))
    return found


def _publish_asset(source: Path, destination: Path, redactor: Redactor, record: dict) -> None:
    """Publish one allowlisted photograph or document.

    SVG becomes redacted text; PNG/JPEG are re-encoded without metadata (a
    copy that cannot be re-encoded is refused rather than shipped verbatim);
    anything else is copied verbatim with the retention recorded.
    """
    suffix = source.suffix.lower()
    if suffix == ".svg":
        _publish_text(source, destination, redactor, record)
        record.update(metadata_stripped=False, warning="SVG attachment published as redacted text")
    elif suffix in (".png", ".jpg", ".jpeg"):
        try:
            destination.write_bytes(_strip_raster_metadata(source.read_bytes()))
        except Exception as exc:  # Pillow raises several unrelated types; never fall back to a verbatim copy.
            raise ValueError(f"{source.name} could not be re-encoded without metadata; refusing to publish it: {exc}") from exc
        record.update(redactions={}, metadata_stripped=True,
                      warning="binary copied under attachment allowlist; EXIF/GPS/ICC/text metadata stripped, "
                              "pixels unchanged; not text-redacted")
    else:
        shutil.copyfile(source, destination)
        record.update(redactions={}, metadata_stripped=False,
                      warning="binary copied verbatim under attachment allowlist; document metadata retained; "
                              "not text-redacted")


def _publish_html(source: Path, target: Path, redactor: Redactor, record: dict, runtime_sha256: str | None) -> str:
    """Redact the report HTML but leave a hash-verified inline Plotly runtime byte-identical.

    The vendor library is full of ``this.local``/``ua.home`` member accesses;
    redacting inside it would break the published report's JavaScript and
    inflate the hostname totals. It is exempted only when its SHA-256 equals
    ``plotly_js_sha256`` recorded by the renderer in build_manifest.json.
    """
    text = source.read_text(encoding="utf-8")
    match = PLOTLY_RUNTIME.search(text)
    runtime = match.group(1) if match else None
    if runtime is not None and runtime_sha256 and hashlib.sha256(runtime.encode("utf-8")).hexdigest() == runtime_sha256:
        head, counts = redactor.text(text[:match.start(1)])
        tail, tail_counts = redactor.text(text[match.end(1):])
        for key, n in tail_counts.items():
            counts[key] = counts.get(key, 0) + n
        cleaned = head + runtime + tail
        record.update(redactions=counts, plotly_runtime={"sha256": runtime_sha256, "verified": True, "redacted": False})
    else:
        cleaned, counts = redactor.text(text)
        record.update(redactions=counts)
        if runtime is not None:
            record["plotly_runtime"] = {"verified": False, "redacted": True,
                                        "warning": "inline Plotly runtime hash does not match build_manifest.json "
                                                   "plotly_js_sha256; it was text-redacted like any other content"}
    target.write_text(cleaned, encoding="utf-8")
    return cleaned


def _withhold_images(html: str, withheld: set[str]) -> tuple[str, int]:
    """Replace every <img> whose src names a withheld file with an explicit placeholder; no broken link remains."""
    count = 0
    for relative in sorted(withheld):
        def placeholder(match: re.Match) -> str:
            nonlocal count
            count += 1
            tag = match.group(0)
            width, height = re.search(r'\swidth="(\d+)"', tag), re.search(r'\sheight="(\d+)"', tag)
            size = (f"width:{width.group(1)}px;max-width:100%;aspect-ratio:{width.group(1)}/{height.group(1)};"
                    if width and height else "min-height:6em;")
            return (f'<div class="sensor-image sensor-image-withheld" role="img" aria-label="{WITHHELD_TEXT}" '
                    f'data-withheld="attachment" style="{size}box-sizing:border-box;display:flex;align-items:center;'
                    'justify-content:center;padding:1em;border:1px dashed #9aa;background:#eef2f5;color:#526879;'
                    f'font:.9em/1.4 system-ui,sans-serif;text-align:center">{WITHHELD_TEXT}</div>')
        html = re.sub(rf'<img\b[^>]*\bsrc="{re.escape(relative)}"[^>]*>', placeholder, html)
        html = html.replace(relative, "#withheld-attachment")
    return html, count


class Redactor:
    """Exact known values first, then bounded patterns; counts only, never values."""

    def __init__(self, *, endpoints: set[str], serials: set[str], paths: set[str]):
        def alternation(values):
            return re.compile("|".join(re.escape(v) for v in sorted(values, key=len, reverse=True))) if values else None
        # Whole VISA resource strings first (one token per endpoint), then the
        # exact known values, then the bounded generic patterns.
        self.order = [("endpoint", VISA_RESOURCE),
                      ("endpoint", alternation({v for v in endpoints if v})),
                      ("serial", alternation({v for v in serials if v})),
                      ("path", alternation({v for v in paths if v})),
                      ("endpoint", PRIVATE_IPV4), ("hostname", LOCAL_HOSTNAME),
                      ("path", POSIX_PATH), ("path", WINDOWS_PATH)]

    def text(self, text: str) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        for category, pattern in self.order:
            if pattern is None:
                continue
            text, n = pattern.subn(f"[REDACTED:{category}]", text)
            if n:
                counts[category] = counts.get(category, 0) + n
        return text, counts

    def json(self, value: Any, path: str = "") -> tuple[Any, dict[str, int], list[str]]:
        counts: dict[str, int] = {}
        fields: list[str] = []
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                cleaned, c, f = self.json(item, f"{path}.{key}" if path else str(key))
                out[key] = cleaned
                for k, n in c.items():
                    counts[k] = counts.get(k, 0) + n
                fields += f
            return out, counts, fields
        if isinstance(value, list):
            out = []
            for item in value:
                cleaned, c, f = self.json(item, f"{path}[]")
                out.append(cleaned)
                for k, n in c.items():
                    counts[k] = counts.get(k, 0) + n
                fields += f
            return out, counts, sorted(set(fields))
        if isinstance(value, str):
            cleaned, c = self.text(value)
            return cleaned, c, ([path] if c else [])
        return value, counts, fields


def _known_values(run_dir: Path, run: dict, keep_serials: bool) -> tuple[set[str], set[str], set[str]]:
    endpoints, serials, paths = set(), set(), {str(run_dir), str(run_dir.resolve())}
    for identity in (run.get("instrument_identities") or {}).values():
        if isinstance(identity, dict) and identity.get("serial"):
            serials.add(str(identity["serial"]))
    transcript = run_dir / "scpi.jsonl"
    if transcript.is_file():
        for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            resource = str(entry.get("resource", ""))
            if resource:
                endpoints.add(resource)
                parts = resource.split("::")
                if len(parts) >= 3 and parts[1]:
                    endpoints.add(parts[1])
            if entry.get("command") == "*IDN?" and entry.get("response"):
                fields = [f.strip() for f in str(entry["response"]).split(",")]
                if len(fields) >= 3 and fields[2]:
                    serials.add(fields[2])
    for name in ("plan.json", "request.json"):
        file = run_dir / name
        if file.is_file():
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            bench = payload.get("bench") if isinstance(payload, dict) else None
            for role in ("source", "load"):
                endpoint = ((bench or {}).get(role) or {}).get("endpoint") if isinstance(bench, dict) else None
                if endpoint:
                    endpoints.add(str(endpoint))
    return endpoints, (set() if keep_serials else serials), paths


def _publish_text(source: Path, target: Path, redactor: Redactor, record: dict) -> str:
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".json":
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if payload is not None:
            cleaned, counts, fields = redactor.json(payload)
            record.update(redactions=counts, redacted_fields=fields)
            text = json.dumps(cleaned, indent=2, sort_keys=True, allow_nan=False) + "\n"
            target.write_text(text, encoding="utf-8")
            return text
    cleaned, counts = redactor.text(text)
    record.update(redactions=counts)
    target.write_text(cleaned, encoding="utf-8")
    return cleaned


def _html_publication_marks(html: str, *, public: bool, run_id: str, revision: str) -> tuple[str, bool]:
    html, _ = ROBOTS_META.subn("", html) if public else (html, 0)
    if not public and "noindex" not in html:
        html = html.replace("<head>", "<head>\n" + NOINDEX_TAG, 1) if "<head>" in html else NOINDEX_TAG + "\n" + html
    marker = (f'<meta name="dcdc-publication" content="redacted publication copy; run {run_id}; revision {revision}; '
              'not complete raw evidence">')
    notice = ('<p class="dcdc-publication-notice" style="border:1px solid #9aa;padding:.5em;margin:.5em 0;font-size:.9em">'
              f'Redacted publication copy of run {run_id}, report revision {revision}. Instrument endpoints, internal '
              'paths and non-allowlisted identifiers and attachments were removed under a recorded approval. This copy '
              'is not complete raw evidence; the internal record is identified by hash in publication_manifest.json.</p>')
    if "<head>" in html:
        html = html.replace("<head>", "<head>\n" + marker, 1)
    else:
        html = marker + "\n" + html
    body = re.search(r"<body[^>]*>", html, re.IGNORECASE)
    html = html[:body.end()] + "\n" + notice + html[body.end():] if body else notice + "\n" + html
    return html, not public


def publish_run(run_dir: Path, revision: str, out_dir: Path, approval_path: Path) -> Path:
    """Create ``out_dir/<run_id>/<revision>/`` from one issued revision; refuse anything ambiguous."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if not re.fullmatch(r"r\d{4}", revision or ""):
        raise ValueError("Report revision must look like r0001")
    approval = load_approval(approval_path)
    if not (run_dir / "run.json").is_file() or not (run_dir / "integrity.json").is_file():
        raise ValueError(f"{run_dir} is not a finalized run folder (run.json and integrity.json are required)")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run_id = str(run.get("run_id", ""))
    if not run_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError("run.json has no usable run_id")
    if approval.run_id != run_id:
        raise ValueError(f"Approval names run {approval.run_id!r}; the folder is run {run_id!r}")
    if approval.report_revision != revision:
        raise ValueError(f"Approval covers revision {approval.report_revision}; {revision} was requested")
    report_dir = run_dir / "reports" / revision
    if not (report_dir / "report.html").is_file():
        raise ValueError(f"Revision {revision} has no issued report.html in {run_dir}")
    build_status = _build_status(report_dir)
    if build_status != "success" and not approval.allow_unverified:
        raise ValueError(f"Revision {revision} build_manifest.json status is {build_status!r}, not 'success'; a report "
                         "validation error blocks an ordinary issued publication. To publish it knowingly, set "
                         "allow_unverified: true in the approval record; the publication manifest records both.")
    store = AssetStore(run_dir)
    manifest_path = store.root / "manifest.json"
    revision_paths = store.revision_paths()
    latest_revision = store.latest_revision()
    # Allowlist universe: the acquisition manifest plus the current documentation
    # revision, so a photograph added through the editor can be allowlisted too.
    origins = [("attachments/manifest.json", store.acquisition_assets())]
    if latest_revision is not None:
        origins.append((f"attachments/revisions/{revision_paths[-1].name}", list(latest_revision.get("assets", []))))
    by_id, listed_in = {}, {}
    for origin, listed in origins:
        for asset in listed:
            identifier = asset.get("asset_id") or asset.get("id")
            if identifier and str(identifier) not in by_id:
                by_id[str(identifier)] = asset
                listed_in[str(identifier)] = origin
    unknown = sorted(set(approval.attachments) - set(by_id))
    if unknown:
        raise ValueError("Approval allowlists attachment IDs that are not in the run: " + ", ".join(unknown))
    attachment_shas = {str(asset["sha256"]) for asset in by_id.values() if asset.get("sha256")}
    allowlisted_shas = {str(by_id[i]["sha256"]) for i in approval.attachments if by_id[i].get("sha256")}
    target = out_dir / run_id / revision
    if _inside(target, run_dir) or _inside(out_dir, run_dir):
        raise ValueError("The publication copy must not be written inside the run folder")
    if target.exists():
        raise ValueError(f"{target} already exists; publication copies are immutable, choose a new output folder")

    endpoints, serials, paths = _known_values(run_dir, run, approval.keep_serials)
    redactor = Redactor(endpoints=endpoints, serials=serials, paths=paths)
    source_hashes = {"integrity.json": _sha(run_dir / "integrity.json"), "run.json": _sha(run_dir / "run.json")}
    if manifest_path.is_file():
        source_hashes["attachments/manifest.json"] = _sha(manifest_path)
    if revision_paths:
        source_hashes[f"attachments/revisions/{revision_paths[-1].name}"] = _sha(revision_paths[-1])
    runtime_sha256 = None
    if (report_dir / "build_manifest.json").is_file():
        try:
            built = json.loads((report_dir / "build_manifest.json").read_text(encoding="utf-8"))
            runtime_sha256 = built.get("plotly_js_sha256") if isinstance(built, dict) else None
        except ValueError:
            runtime_sha256 = None
    files, excluded, totals, withheld = {}, [], {}, set()

    def add_counts(counts):
        for k, n in counts.items():
            totals[k] = totals.get(k, 0) + n

    target.mkdir(parents=True, exist_ok=False)
    noindex = True
    for name in PUBLISHED_REPORT_FILES:
        source = report_dir / name
        if not _regular_file(source, report_dir):
            continue
        source_hashes[f"reports/{revision}/{name}"] = _sha(source)
        record = {"source": f"reports/{revision}/{name}", "sha256_source": source_hashes[f"reports/{revision}/{name}"]}
        if name == "report.html":
            text = _publish_html(source, target / name, redactor, record, runtime_sha256)
            text, noindex = _html_publication_marks(text, public=approval.public, run_id=run_id, revision=revision)
            (target / name).write_text(text, encoding="utf-8")
        else:
            _publish_text(source, target / name, redactor, record)
        record["sha256_published"] = _sha(target / name)
        add_counts(record.get("redactions", {}))
        files[name] = record
    for folder in ("exports", "figures"):
        source_folder = report_dir / folder
        if not source_folder.is_dir():
            continue
        for source in sorted(source_folder.iterdir()):
            if not _regular_file(source, report_dir):
                continue
            relative = f"{folder}/{source.name}"
            if source.suffix.lower() not in TEXT_SUFFIXES:
                excluded.append({"file": f"reports/{revision}/{relative}", "reason": "binary artifact; cannot be text-redacted"})
                continue
            text = source.read_text(encoding="utf-8")
            # A print figure that embeds one of the run's photographs is that
            # photograph: it follows the attachment allowlist, not the text rule.
            embedded = [item for item in _embedded_images(text) if item[2] in attachment_shas]
            if any(digest not in allowlisted_shas for _, _, digest in embedded):
                excluded.append({"file": f"reports/{revision}/{relative}",
                                 "reason": "embeds a photograph whose attachment is not in the approval allowlist"})
                withheld.add(relative)
                continue
            (target / folder).mkdir(exist_ok=True)
            source_hashes[f"reports/{revision}/{relative}"] = _sha(source)
            record = {"source": f"reports/{revision}/{relative}", "sha256_source": source_hashes[f"reports/{revision}/{relative}"]}
            if embedded:
                stripped = []
                for payload, media_type, digest in embedded:
                    if media_type in ("image/png", "image/jpeg"):
                        clean = _strip_raster_metadata(base64.b64decode(payload, validate=True))
                        text = text.replace(payload, base64.b64encode(clean).decode("ascii"))
                        stripped.append(digest)
                cleaned, counts = redactor.text(text)
                (target / relative).write_text(cleaned, encoding="utf-8")
                record.update(redactions=counts, embedded_attachments=sorted({d for _, _, d in embedded}),
                              metadata_stripped=bool(stripped),
                              warning="embeds allowlisted photograph(s); raster metadata stripped, pixels unchanged")
            else:
                _publish_text(source, target / relative, redactor, record)
            record["sha256_published"] = _sha(target / relative)
            add_counts(record.get("redactions", {}))
            files[relative] = record
    assets_folder = report_dir / "assets"
    if assets_folder.is_dir():
        # Sensor-placement image copies: named by their attachment hash, verified,
        # and published only under the attachment allowlist.
        for source in sorted(assets_folder.iterdir()):
            if not _regular_file(source, report_dir):
                continue
            relative = f"assets/{source.name}"
            digest = _sha(source)
            match = ASSET_FILE_NAME.match(source.name)
            if not match or match.group(1) != digest or digest not in attachment_shas:
                raise ValueError(f"reports/{revision}/{relative} is not a hash-named copy of one of the run's attachments; "
                                 "refusing to publish an unverifiable image")
            if digest not in allowlisted_shas:
                excluded.append({"file": f"reports/{revision}/{relative}",
                                 "reason": "photograph copy whose attachment is not in the approval allowlist"})
                withheld.add(relative)
                continue
            (target / "assets").mkdir(exist_ok=True)
            source_hashes[f"reports/{revision}/{relative}"] = digest
            record = {"source": f"reports/{revision}/{relative}", "sha256_source": digest}
            _publish_asset(source, target / relative, redactor, record)
            record["sha256_published"] = _sha(target / relative)
            add_counts(record.get("redactions", {}))
            files[relative] = record
    if withheld:
        html_path = target / "report.html"
        html, replaced = _withhold_images(html_path.read_text(encoding="utf-8"), withheld)
        html_path.write_text(html, encoding="utf-8")
        files["report.html"].update(sha256_published=_sha(html_path), images_withheld=replaced)
    pdf = report_dir / "report.pdf"
    if _regular_file(pdf, report_dir):
        if approval.include_pdf:
            shutil.copyfile(pdf, target / "report.pdf")
            source_hashes[f"reports/{revision}/report.pdf"] = _sha(pdf)
            files["report.pdf"] = {"source": f"reports/{revision}/report.pdf", "sha256_source": source_hashes[f"reports/{revision}/report.pdf"],
                                   "sha256_published": source_hashes[f"reports/{revision}/report.pdf"], "redactions": {},
                                   "warning": "binary copied verbatim under include_pdf approval; not text-redacted"}
        else:
            excluded.append({"file": f"reports/{revision}/report.pdf", "reason": "binary; excluded unless approval sets include_pdf: true"})
    published_assets = []
    for identifier, asset in by_id.items():
        if identifier not in approval.attachments:
            excluded.append({"attachment_id": identifier, "reason": "not in the approval allowlist", "listed_in": listed_in[identifier]})
            continue
        relative = Path(str(asset.get("path") or asset.get("filename") or ""))
        if not relative.parts and asset.get("sha256") and asset.get("media_type") in MEDIA_TYPES:
            # Documentation revisions list originals by hash and media type only.
            relative = Path(f"{asset['sha256']}.{MEDIA_TYPES[asset['media_type']]}")
        source = (run_dir / "attachments" / relative) if relative.parts and relative.parts[0] == "originals" else run_dir / "attachments" / "originals" / relative
        if (not relative.parts or relative.is_absolute() or ".." in relative.parts or source.is_symlink()
                or not _inside(source, run_dir / "attachments" / "originals") or not source.is_file()):
            raise ValueError(f"Attachment {identifier!r} has an unsafe or missing path in {listed_in[identifier]}")
        digest = _sha(source)
        if asset.get("sha256") and asset["sha256"] != digest:
            raise ValueError(f"Attachment {identifier!r} does not match its manifest hash; refusing to publish altered evidence")
        destination = target / "attachments" / source.name
        destination.parent.mkdir(exist_ok=True)
        record = {"source": f"attachments/originals/{source.name}", "sha256_source": digest, "listed_in": listed_in[identifier]}
        _publish_asset(source, destination, redactor, record)
        record["sha256_published"] = _sha(destination)
        add_counts(record.get("redactions", {}))
        cleaned, counts, fields = redactor.json({k: v for k, v in asset.items() if k not in ("path", "filename")})
        add_counts(counts)
        record.update(manifest_entry_redactions=counts, redacted_fields=fields)
        published_assets.append({**cleaned, "path": f"attachments/{source.name}", "listed_in": listed_in[identifier],
                                 "sha256_published": record["sha256_published"],
                                 "metadata_stripped": record.get("metadata_stripped", False)})
        source_hashes[f"attachments/originals/{source.name}"] = digest
        files[f"attachments/{source.name}"] = record
    if published_assets:
        atomic_json(target / "attachments" / "manifest.json", {"assets": published_assets, "scope": "allowlisted attachments only",
                                                               "metadata_policy": METADATA_POLICY})
    manifest = {
        "schema_version": "1.0", "kind": "publication_copy", "run_id": run_id, "report_revision": revision,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "approval": {"file_sha256": _sha(approval_path), "approver": approval.approver, "date": approval.date,
                     "public": approval.public, "attachments_allowlisted": list(approval.attachments),
                     "keep_serials": approval.keep_serials, "include_pdf": approval.include_pdf,
                     "allow_unverified": approval.allow_unverified, "statement": approval.statement},
        "build_status": build_status,
        "noindex": noindex,
        "noindex_is_not_access_control": "noindex is not access control: a robots tag only asks crawlers not to index; "
                                         "confidential data need an access-controlled destination, not a publicly reachable file.",
        "completeness": "Redacted publication copy, not complete raw evidence. Raw samples, the SCPI transcript, "
                        "request/plan/run records, analysis folders and non-allowlisted attachments are not included; "
                        "the internal full record is identified by source_hashes and source_integrity.",
        "redaction": {"categories": sorted({"endpoint", "serial", "path", "hostname"}), "totals": totals,
                      "known_value_counts": {"endpoints": len(endpoints), "serials": len(serials), "paths": len(paths)},
                      "policy": "exact known endpoints/serials/run path, VISA resource strings, private/link-local/loopback "
                                "IPv4, .local/.lan/.home/.internal hostnames, /home /Users /root /mnt /media /srv and "
                                "Windows drive paths. Public IPv4 addresses and arbitrary hostnames are not pattern-redacted.",
                      "plotly_runtime": "left byte-identical only when its SHA-256 matches build_manifest.json "
                                        "plotly_js_sha256; otherwise redacted like any other text"},
        "attachments": {"policy": "photographs travel as attachments/, reports/<revision>/assets/ copies and the print "
                                  "figure's embedded image; all three follow the approval allowlist",
                        "metadata_policy": METADATA_POLICY, "withheld_images": sorted(withheld)},
        "files": files, "excluded": excluded, "never_published": list(NEVER_PUBLISHED),
        "source_hashes": source_hashes,
        "source_integrity": json.loads((run_dir / "integrity.json").read_text(encoding="utf-8")),
    }
    atomic_json(target / "publication_manifest.json", manifest)
    return target
