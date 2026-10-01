"""PDF-02 pagination checker: Typst-compiled fixtures and hand-built documents.

The integration tests compile the committed ``tests/fixtures/pdf/*.typ``
sources with the bundled Typst binary (no Quarto, no browser) and read them
back with poppler's pdftohtml and pypdf; they skip with a reason when a tool
is unavailable. The remaining tests judge hand-built extractions and the
renderer's manifest handling without any document toolchain.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dcdc_bench.reporting import pdf_check
from dcdc_bench.reporting.pdf_check import (BBox, Document, Element, Page, Region, TextLine, analyze,
                                            check_pdf)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdf"
PROJECT = Path(__file__).resolve().parents[1]
FIXTURE_NAMES = ("clean", "orphan-heading", "lone-table-row", "clipped-text", "caption-without-figure",
                 "split-table-unguarded", "split-table-guarded", "deviation-sheet-keep-together")
MODELS = {name: {"run_id": f"run-fixture-{suffix}", "dut": {"model": "FIXTURE-DUT"}} for name, suffix in (
    ("clean", "clean"), ("orphan-heading", "orphan"), ("lone-table-row", "lone-row"),
    ("clipped-text", "clipped"), ("caption-without-figure", "caption"),
    ("split-table-unguarded", "split-unguarded"), ("split-table-guarded", "split-guarded"),
    ("deviation-sheet-keep-together", "deviation-sheet"))}
# The guarded fixture imports the print theme's table rule from the templates.
THEME_TABLES = PROJECT / "templates" / "theme" / "print-tables.typ"


def _typst() -> Path | None:
    candidates = [os.environ.get("TYPST_PATH"), shutil.which("typst")]
    candidates.extend(str(path) for path in sorted(PROJECT.glob(".tools/quarto-*/bin/tools/*/typst"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _codes(result, severity: str | None = None, page: int | None = None) -> list[str]:
    return [finding.code for finding in result.findings
            if (severity is None or finding.severity == severity) and (page is None or finding.page == page)]


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    pytest.importorskip("pypdf")
    typst = _typst()
    if typst is None:
        pytest.skip("Typst binary unavailable (set TYPST_PATH or install the bundled Quarto tools)")
    if not shutil.which("pdftohtml"):
        pytest.skip("poppler-utils pdftohtml unavailable")
    out = tmp_path_factory.mktemp("pdf-fixtures")
    for source in FIXTURES.iterdir():
        if source.suffix in (".typ", ".svg"):
            shutil.copyfile(source, out / source.name)
    shutil.copyfile(THEME_TABLES, out / THEME_TABLES.name)
    pdfs = {}
    for name in FIXTURE_NAMES:
        subprocess.run([str(typst), "compile", f"{name}.typ", f"{name}.pdf"], cwd=out, check=True,
                       capture_output=True, text=True, timeout=180)
        pdfs[name] = out / f"{name}.pdf"
    return pdfs


@pytest.mark.integration
def test_clean_fixture_passes_with_every_page_inspected(compiled):
    result = check_pdf(compiled["clean"], MODELS["clean"])
    assert _codes(result, "error") == [], [finding.message for finding in result.errors]
    assert result.status in ("pass", "warning")
    assert result.tagged is True
    assert result.page_count == 3 == len(result.pages)
    assert [page["number"] for page in result.pages] == [1, 2, 3]
    assert all(page["page_number"] == str(page["number"]) for page in result.pages)
    assert all(page["run_id_present"] for page in result.pages)
    assert all("run-fixture-clean" in page["running_header"] for page in result.pages)
    assert result.pages[0]["headings"][:2] == ["Summary", "Coverage"]
    figure_page = next(page for page in result.pages if page["figures"])
    assert figure_page["captions"] == 1 and figure_page["drawings"] >= 1
    # The long appendix table splits with several rows on each page: allowed.
    assert sum(page["tables"] for page in result.pages) >= 3
    encoded = result.to_json()
    assert json.loads(encoded) == check_pdf(compiled["clean"], MODELS["clean"]).to_dict(), "deterministic"
    assert json.loads(encoded)["pages_inspected"] == 3


@pytest.mark.integration
def test_orphan_heading_is_reported_on_its_page(compiled):
    result = check_pdf(compiled["orphan-heading"], MODELS["orphan-heading"])
    orphans = [finding for finding in result.findings if finding.code == "orphan-heading"]
    assert [(finding.page, finding.details["heading"]) for finding in orphans] == [(1, "Setup and method")]
    assert result.status == "fail"
    assert "clipped-text" not in _codes(result)


@pytest.mark.integration
def test_lone_last_table_row_is_reported(compiled):
    result = check_pdf(compiled["lone-table-row"], MODELS["lone-table-row"])
    lone = [finding for finding in result.findings if finding.code == "lone-table-row"]
    assert len(lone) == 1 and lone[0].page == 2 and lone[0].severity == "error"
    assert lone[0].details["rows_per_page"] == {"1": 37, "2": 1}
    assert "Point" in lone[0].details["table"]
    assert "table-header-alone" not in _codes(result)


@pytest.mark.integration
def test_table_opening_with_a_single_row_at_a_page_bottom_is_reported_once(compiled):
    """Control case: without the theme rule the nine-row table splits 1 + 8 under its sticky heading."""
    result = check_pdf(compiled["split-table-unguarded"], MODELS["split-table-unguarded"])
    split = [finding for finding in result.findings if finding.code == "table-split-after-first-row"]
    assert len(split) == 1 and split[0].page == 1 and split[0].severity == "warning"
    assert split[0].details["rows_per_page"] == {"1": 1, "2": 8}
    assert "Metric" in split[0].details["table"]
    assert result.status == "warning"
    assert {"orphan-heading", "lone-table-row", "table-header-alone"}.isdisjoint(_codes(result))
    assert [page["tables"] for page in result.pages] == [1, 1]


@pytest.mark.integration
def test_theme_table_rule_moves_a_table_whose_head_would_not_fit_together_with_its_heading(compiled):
    """templates/theme/print-tables.typ: the same layout with the rule applied paginates cleanly (PDF-02)."""
    result = check_pdf(compiled["split-table-guarded"], MODELS["split-table-guarded"])
    assert _codes(result, "error") == [], [finding.message for finding in result.errors]
    assert "table-split-after-first-row" not in _codes(result), [finding.message for finding in result.findings]
    assert result.status == "pass"
    assert result.page_count == 2
    # The whole table left page 1 and its heading travelled with it: neither an
    # orphan heading nor a lone row, and the re-emitted table is counted once.
    assert [page["tables"] for page in result.pages] == [0, 1]
    assert "Regulation" not in result.pages[0]["headings"]
    assert "Regulation" in result.pages[1]["headings"]


@pytest.mark.integration
def test_deviation_sheet_block_moves_whole_to_the_next_page_with_its_heading(compiled):
    """renderer._deviation_sheet_section: the best-effort sheet, its basis legend and its statement are one
    unbreakable Typst block (the DUT-section pattern). Where only the heading and about one row would fit at the
    bottom of a page, the whole block moves to the next page and the sticky heading travels with it (PDF-02)."""
    result = check_pdf(compiled["deviation-sheet-keep-together"], MODELS["deviation-sheet-keep-together"])
    assert _codes(result, "error") == [], [finding.message for finding in result.errors]
    assert {"table-split-after-first-row", "orphan-heading", "lone-table-row", "table-header-alone"}.isdisjoint(_codes(result)), \
        [finding.message for finding in result.findings]
    assert result.status == "pass"
    assert result.page_count == 2
    assert [page["tables"] for page in result.pages] == [0, 1]
    heading = "Deviations from ISO 16750-2 clause 4.6.1.1, variant A"
    assert heading not in result.pages[0]["headings"] and heading in result.pages[1]["headings"]


@pytest.mark.integration
def test_text_beyond_the_page_edge_is_reported(compiled):
    result = check_pdf(compiled["clipped-text"], MODELS["clipped-text"])
    clipped = sorted(finding.details["text"] for finding in result.findings if finding.code == "clipped-text")
    assert clipped == ["Text placed beyond the bottom page edge", "Text placed beyond the right page edge"]
    assert all(finding.page == 1 for finding in result.findings if finding.code == "clipped-text")
    right = next(finding for finding in result.findings if "right page edge" in finding.message)
    assert right.details["bbox"][2] > result.pages[0]["width_pt"]
    bottom = next(finding for finding in result.findings if "bottom page edge" in finding.message)
    assert bottom.details["bbox"][3] > result.pages[0]["height_pt"]


@pytest.mark.integration
def test_caption_text_without_any_figure_is_reported(compiled):
    result = check_pdf(compiled["caption-without-figure"], MODELS["caption-without-figure"])
    captions = [finding for finding in result.findings if finding.code == "caption-without-figure"]
    assert [finding.page for finding in captions] == [2]
    assert captions[0].details["caption"].startswith("Figure 1:")


@pytest.mark.integration
def test_untagged_or_blank_pdf_reports_missing_structure_numbering_and_identity(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    if not shutil.which("pdftohtml"):
        pytest.skip("poppler-utils pdftohtml unavailable")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595.28, height=841.89)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    result = check_pdf(path, {"run_id": "run-blank", "dut": {"model": "DUT"}})
    assert result.tagged is False
    assert result.status == "fail"
    assert "untagged-pdf" in _codes(result, "warning")
    assert {"page-number-missing", "identity-missing", "blank-page"} <= set(_codes(result, "error", page=1))
    assert result.pages[0]["characters"] == 0


@pytest.mark.integration
def test_cli_pdf_check_prints_json_and_signals_failures(compiled, capsys):
    from dcdc_bench.cli import main
    assert main(["pdf-check", str(compiled["clean"]), "--model", str(_model_file(compiled["clean"], MODELS["clean"]))]) == 0
    clean = json.loads(capsys.readouterr().out)
    assert clean["status"] in ("pass", "warning") and clean["pages_inspected"] == 3
    assert main(["pdf-check", str(compiled["orphan-heading"])]) == 4
    orphan = json.loads(capsys.readouterr().out)
    assert orphan["status"] == "fail"
    assert [finding["code"] for finding in orphan["findings"] if finding["severity"] == "error"] == ["orphan-heading"]


def _model_file(pdf: Path, model: dict) -> Path:
    path = pdf.with_name(pdf.stem + "-model.json")
    path.write_text(json.dumps(model), encoding="utf-8")
    return path


def test_missing_pdf_is_a_finding_not_an_exception(tmp_path):
    result = check_pdf(tmp_path / "absent.pdf")
    assert result.status == "fail" and result.page_count == 0
    assert _codes(result) == ["pdf-missing"]
    assert json.loads(result.to_json())["counts"] == {"error": 1, "unverified": 0, "warning": 0, "info": 0}


def test_missing_pdftohtml_leaves_the_document_unverified_not_failed(tmp_path, monkeypatch):
    """M5: an unavailable checker tool is not a layout defect; the verdict is "unverified"."""
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595.28, height=841.89)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    monkeypatch.setattr(pdf_check.shutil, "which", lambda name: None)
    launched = []
    monkeypatch.setattr(pdf_check.subprocess, "run", lambda *args, **kwargs: launched.append(args) or None)
    result = check_pdf(path)
    assert result.status == "unverified"
    assert "pdftohtml-unavailable" in _codes(result, "unverified") and _codes(result, "error") == []
    assert [finding.code for finding in result.unverified] == ["pdftohtml-unavailable"]
    assert json.loads(result.to_json())["counts"]["unverified"] == 1
    assert pdf_check.main([str(path)]) == 4, "the CLI still signals a document that was not verified"
    assert result.tools["pdftohtml"] is None and result.tools["pypdf"]
    assert launched == [], "no process may run when the tool is absent"
    assert result.page_count == 1 and len(result.pages) == 1


# --- hand-built extractions: structure judgements without any toolchain

def _page(number: int, run_id: str = "run-x") -> Page:
    page = Page(number=number, width=595.28, height=841.89)
    page.lines = [TextLine(51, 40, 200, 8, 7, False, f"MEASURED · DUT · {run_id}"),
                  TextLine(290, 790, 8, 10, 9.5, False, str(number))]
    page.region(("artifact", "Header")).texts.append(f"MEASURED · DUT · {run_id}")
    page.region(("artifact", "Footer")).texts.append(str(number))
    return page


def _document(pages: list[Page], root: Element) -> Document:
    document = Document(path="hand-built.pdf", page_count=len(pages), tagged=True, pages=pages, root=root,
                        tools={"pypdf": "test", "pdftohtml": "test"})
    return document


def _element(role: str, parent: Element | None = None, marks=()) -> Element:
    element = Element(role=role, parent=parent, marks=list(marks))
    if parent is not None:
        parent.children.append(element)
    return element


def _text_region(page: Page, mcid: int, top: float, text: str, height: float = 12.0) -> None:
    region = page.region(mcid)
    region.include(51, top, 400, top + height)
    region.texts.append(text)
    page.lines.append(TextLine(51, top, 300, height, 9.5, False, text))


def test_caption_on_a_later_page_than_its_figure_is_an_error():
    first, second = _page(1), _page(2)
    figure_region = first.region(7)
    figure_region.include(60, 120, 540, 400)
    figure_region.segments = 120
    _text_region(second, 0, 60, "Figure 1: MEASURED. Efficiency against output current.")
    root = Element(role="Root")
    document_element = _element("Document", root)
    _element("H1", document_element, [(1, 3)])
    _text_region(first, 3, 90, "Results", 14)
    div = _element("Div", document_element)
    caption = _element("Caption", div)
    _element("Span", caption, [(2, 0)])
    paragraph = _element("P", div)
    _element("Figure", paragraph, [(1, 7)])
    _element("P", document_element, [(2, 1)])
    _text_region(second, 1, 90, "Measured values are aggregated settled DC point results.")
    analysis = analyze(_document([first, second], root), {"run_id": "run-x", "dut": {"model": "DUT"}})
    separated = [finding for finding in analysis.findings if finding.code == "caption-separated-from-figure"]
    assert len(separated) == 1
    assert separated[0].page == 2 and separated[0].details == {
        "caption": "Figure 1: MEASURED. Efficiency against output current.", "caption_pages": [2], "figure_pages": [1]}
    assert "caption-without-figure" not in [finding.code for finding in analysis.findings]
    assert [finding.code for finding in analysis.findings if finding.severity == "error"] == ["caption-separated-from-figure"]
    assert analysis.pages[0]["figures"] == 1 and analysis.pages[1]["captions"] == 1


def test_table_header_alone_at_the_bottom_and_lone_row_are_errors():
    first, second, third = _page(1), _page(2), _page(3)
    root = Element(role="Root")
    document_element = _element("Document", root)
    _element("H1", document_element, [(1, 0)])
    _text_region(first, 0, 90, "Appendix", 14)
    table = _element("Table", document_element)
    head_row = _element("TR", _element("THead", table))
    _element("TH", head_row, [(1, 1)])
    _text_region(first, 1, 780, "Point")
    body = _element("TBody", table)
    for index, (page, mcid, top) in enumerate([(second, 0, 80), (second, 1, 100), (second, 2, 120), (third, 0, 80)]):
        row = _element("TR", body)
        _element("TD", row, [(page.number, mcid)])
        _text_region(page, mcid, top, f"p{index + 1}")
    _element("P", document_element, [(3, 1)])
    _text_region(third, 1, 120, "Uncertainty: no applicable validated uncertainty budget is supplied.")
    analysis = analyze(_document([first, second, third], root), {"run_id": "run-x"})
    by_code = {finding.code: finding for finding in analysis.findings if finding.severity == "error"}
    assert set(by_code) == {"table-header-alone", "lone-table-row"}
    assert by_code["table-header-alone"].page == 1
    assert by_code["lone-table-row"].page == 3
    assert by_code["lone-table-row"].details["rows_per_page"] == {"2": 3, "3": 1}


def test_a_table_wrapping_the_same_rows_twice_yields_one_finding_and_one_table():
    """Typst tags a table re-emitted by a show rule as a Table around a Table with the same rows."""
    first, second = _page(1), _page(2)
    root = Element(role="Root")
    document_element = _element("Document", root)
    _element("H1", document_element, [(1, 0)])
    _text_region(first, 0, 90, "Results", 14)
    wrapper = _element("Table", document_element)
    table = _element("Table", wrapper)
    head_row = _element("TR", _element("THead", table))
    _element("TH", head_row, [(1, 1)])
    _text_region(first, 1, 760, "Metric")
    body = _element("TBody", table)
    for page, mcid, top in [(first, 2, 780), (second, 0, 80), (second, 1, 100), (second, 2, 120)]:
        row = _element("TR", body)
        _element("TD", row, [(page.number, mcid)])
        _text_region(page, mcid, top, "row")
    _element("P", document_element, [(2, 3)])
    _text_region(second, 3, 150, "Uncertainty: no applicable validated uncertainty budget is supplied.")
    analysis = analyze(_document([first, second], root), {"run_id": "run-x"})
    split = [finding for finding in analysis.findings if finding.code == "table-split-after-first-row"]
    assert len(split) == 1, [finding.message for finding in analysis.findings]
    assert split[0].page == 1 and split[0].details["rows_per_page"] == {"1": 1, "2": 3}
    assert [page["tables"] for page in analysis.pages] == [1, 1], "the wrapper is not a second table"
    assert [finding.code for finding in analysis.findings if finding.severity == "error"] == []


def test_findings_repeating_code_page_and_message_are_reported_once():
    """Two identical findings (same code, page and message) collapse to the first, keeping its details."""
    duplicate = pdf_check.Finding("table-split-after-first-row", "warning", "Table 'Metric' starts with a single row", 4,
                                  {"rows_per_page": {"4": 1, "5": 11}})
    repeated = pdf_check.Finding("table-split-after-first-row", "warning", "Table 'Metric' starts with a single row", 4,
                                 {"rows_per_page": {"4": 1, "5": 11}, "extra": True})
    other_page = pdf_check.Finding("table-split-after-first-row", "warning", "Table 'Metric' starts with a single row", 6)
    other_code = pdf_check.Finding("lone-table-row", "error", "Table 'Metric' starts with a single row", 4)
    unique = pdf_check._unique([duplicate, repeated, other_page, other_code])
    assert unique == [duplicate, other_page, other_code]
    assert unique[0].details == {"rows_per_page": {"4": 1, "5": 11}}
    payload = pdf_check.PdfCheckResult("hand-built.pdf", 6, True, {}, unique, []).to_dict()
    assert payload["counts"] == {"error": 1, "unverified": 0, "warning": 2, "info": 0}


def test_heading_followed_by_content_on_the_same_page_is_not_an_orphan():
    page = _page(1)
    root = Element(role="Root")
    document_element = _element("Document", root)
    _element("H1", document_element, [(1, 0)])
    _text_region(page, 0, 90, "Summary", 14)
    _element("H2", document_element, [(1, 1)])
    _text_region(page, 1, 120, "Coverage", 12)
    paragraph = _element("P", document_element)
    _element("Strong", paragraph, [(1, 2)])
    _text_region(page, 2, 150, "Qualification: measured observations; uncertainty unquantified.")
    analysis = analyze(_document([page], root), {"run_id": "run-x"})
    assert [finding.code for finding in analysis.findings] == []
    assert analysis.pages[0]["headings"] == ["Summary", "Coverage"]
    assert analysis.pages[0]["page_number"] == "1" and analysis.pages[0]["run_id_present"] is True


def test_findings_are_sorted_and_serializable():
    page = _page(1, run_id="other-run")
    page.lines.append(TextLine(600, 100, 50, 10, 9.5, False, "beyond the edge"))
    root = Element(role="Root")
    document_element = _element("Document", root)
    _element("H1", document_element, [(1, 0)])
    _text_region(page, 0, 90, "Alone", 14)
    analysis = analyze(_document([page], root), {"run_id": "run-x"})
    codes = [(finding.page, finding.severity, finding.code) for finding in analysis.findings]
    assert codes == sorted(codes, key=lambda item: (item[0] or 0, pdf_check.SEVERITY_ORDER[item[1]], item[2]))
    assert {"clipped-text", "identity-missing", "orphan-heading"} <= {code for _, _, code in codes}
    payload = pdf_check.PdfCheckResult("hand-built.pdf", 1, True, {}, analysis.findings, analysis.pages).to_dict()
    assert json.loads(json.dumps(payload, allow_nan=False))["status"] == "fail"


# --- renderer integration: the manifest records the check and fails validation honestly

@pytest.fixture
def model():
    return {
        "run_id": "synthetic-run", "analysis_id": "analysis-1", "report_revision": "r0001",
        "evidence_label": "SYNTHETIC", "boundary": "source-to-DUT-output path",
        "dut": {"model": "Different 5 V DUT", "sample_id": "sample-1"},
        "points": [{"point_id": "p1", "test_id": "load", "vin_target_V": 12, "iout_target_A": .1, "Iout_A": .099,
                    "efficiency_pct": 39.1575, "qualification": "valid"}],
        "figures": [{"id": "fig-efficiency", "title": "Path efficiency", "x_key": "Iout_A", "y_key": "efficiency_pct",
                     "x_label": "Output current (A)", "y_label": "Efficiency (%)", "caption": "12 V.",
                     "series": [{"id": "vin-12", "label": "12 V", "vin_target_V": 12, "point_ids": ["p1"]}]}],
        "metrics": [], "raw_samples": {}, "summary": [],
    }


def _stub_document_toolchain(monkeypatch, renderer):
    import plotly.offline
    monkeypatch.setattr(plotly.offline, "get_plotlyjs", lambda: "window.runtimeFixture=true;")
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-test-fixture")
    monkeypatch.setattr(renderer, "_browser_path", lambda: None)

    async def static_fixture(model, directory):
        for spec in model["figures"]:
            for extension in ("svg", "pdf"):
                (directory / (spec["id"] + "." + extension)).write_text("unit-test fixture")
    monkeypatch.setattr(renderer, "_write_static_figures", static_fixture)

    def document_fixture(command, **kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="1.10.18\n", stderr="", returncode=0)
        (Path(kwargs["cwd"]) / "report.pdf").write_bytes(b"%PDF-1.7 unit-test fixture")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)
    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)


def test_renderer_records_the_check_and_fails_validation_while_keeping_the_pdf(model, tmp_path, monkeypatch):
    from dcdc_bench.reporting import ReportRenderError, render_report, renderer
    _stub_document_toolchain(monkeypatch, renderer)
    canned = {"schema_version": "1.0", "status": "fail", "page_count": 2, "pages_inspected": 2,
              "findings": [{"code": "orphan-heading", "severity": "error", "page": 1, "message": "fixture", "details": {}},
                           {"code": "sparse-page", "severity": "warning", "page": 2, "message": "fixture", "details": {}}],
              "pages": [{"number": 1}, {"number": 2}]}
    checked = []
    monkeypatch.setattr(renderer, "_check_pdf", lambda artifact, model: checked.append((artifact, model["run_id"])) or canned)
    with pytest.raises(ReportRenderError, match="PDF pagination check \\(PDF-02\\) reported 1 error finding") as caught:
        render_report(model, tmp_path, formats=("pdf",))
    manifest = json.loads((tmp_path / "build_manifest.json").read_text())
    assert checked == [(tmp_path / "report.pdf", "synthetic-run")]
    assert manifest["pdf_check"] == canned
    assert manifest["artifacts"]["pdf"]["status"] == "failed-validation"
    assert "p1: orphan-heading" in manifest["artifacts"]["pdf"]["error"]
    assert manifest["artifacts"]["pdf"]["sha256"] and manifest["artifacts"]["pdf"]["bytes"] > 0
    assert manifest["status"] == "failed-validation"
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1.7 unit-test fixture", "the document stays for inspection"
    assert caught.value.manifest == manifest


def test_renderer_records_a_passing_check_as_success(model, tmp_path, monkeypatch):
    from dcdc_bench.reporting import render_report, renderer
    _stub_document_toolchain(monkeypatch, renderer)
    canned = {"schema_version": "1.0", "status": "pass", "page_count": 1, "pages_inspected": 1, "findings": [],
              "pages": [{"number": 1}]}
    monkeypatch.setattr(renderer, "_check_pdf", lambda artifact, model: canned)
    manifest = render_report(model, tmp_path, formats=("pdf",))
    assert manifest["status"] == "success"
    assert manifest["artifacts"]["pdf"]["status"] == "success"
    assert manifest["pdf_check"] == canned
    assert json.loads((tmp_path / "build_manifest.json").read_text())["pdf_check"] == canned


def test_renderer_records_a_checker_crash_as_failed_validation(model, tmp_path, monkeypatch):
    from dcdc_bench.reporting import ReportRenderError, render_report, renderer
    _stub_document_toolchain(monkeypatch, renderer)

    def crash(artifact, model):
        raise RuntimeError("checker exploded")
    monkeypatch.setattr(renderer, "_check_pdf", crash)
    with pytest.raises(ReportRenderError, match="checker-error"):
        render_report(model, tmp_path, formats=("pdf",))
    manifest = json.loads((tmp_path / "build_manifest.json").read_text())
    assert manifest["pdf_check"]["status"] == "fail"
    assert manifest["pdf_check"]["findings"][0]["message"] == "RuntimeError: checker exploded"
    assert manifest["artifacts"]["pdf"]["status"] == "failed-validation"
    assert (tmp_path / "report.pdf").exists()


def test_renderer_keeps_an_unverified_pdf_without_failing_the_build(model, tmp_path, monkeypatch):
    """M5: a missing checker tool leaves the PDF kept, linked and named as unverified; the build does not fail."""
    from dcdc_bench.reporting import render_report, renderer
    _stub_document_toolchain(monkeypatch, renderer)
    canned = {"schema_version": "1.0", "status": "unverified", "page_count": 0, "pages_inspected": 0,
              "findings": [{"code": "pdftohtml-unavailable", "severity": "unverified", "page": None,
                            "message": "fixture", "details": {}}], "pages": []}
    monkeypatch.setattr(renderer, "_check_pdf", lambda artifact, model: canned)
    manifest = render_report(model, tmp_path, formats=("pdf",))
    assert manifest["status"] == "unverified"
    assert manifest["artifacts"]["pdf"]["status"] == "unverified"
    assert manifest["artifacts"]["pdf"]["note"].startswith("PDF not verified: tool missing (pdftohtml-unavailable)")
    assert "error" not in manifest["artifacts"]["pdf"] and manifest["artifacts"]["pdf"]["sha256"]
    assert manifest["pdf_check"] == canned
    assert (tmp_path / "report.pdf").read_bytes() == b"%PDF-1.7 unit-test fixture"
    assert json.loads((tmp_path / "build_manifest.json").read_text())["status"] == "unverified"
