"""PDF-02 print theme: no table leaves a lone last row at a page break.

The integration tests compile small Typst documents with the bundled Typst
binary (no Quarto, no browser) using the same page geometry as the issued
PDF, then judge them with the project's own pagination checker. Each case
compiles a control document without the theme rule to show that the layout
would otherwise fail. The remaining test reads the generated header include
without any document toolchain.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dcdc_bench.reporting import renderer
from dcdc_bench.reporting.pdf_check import check_pdf

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdf"
THEME = renderer.TEMPLATES / "theme" / "print-tables.typ"
MODEL = {"run_id": "run-fixture-lone-row", "dut": {"model": "FIXTURE-DUT"}}
PAGE_SETUP = """#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-lone-row])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#set table(inset: 6pt, stroke: none)
#set par(justify: false)
"""
# The heading rule of the generated header include, for the sticky-heading case.
HEADING_RULE = "#show heading: it => { block(above: 1.2em, below: 0.5em, sticky: true, it) }\n"
SHORT_TABLE_BODY = """
= Results
#block(height: 100% - 115pt)[Filler that leaves room for the heading, the table header and two of the three rows.]
=== Enabled with no external load
#table(
  columns: (25%, 25%, 25%, 25%),
  table.header([Requested input (V)], [Measured input current (A)], [Input power (W)], [Output voltage (V)]),
  table.hline(),
  [12], [0.012695], [0.152379], [12.0009],
  [24], [0.00895548], [0.214958], [12.001],
  [30], [0.00819761], [0.245952], [12.001],
)
After the table.
"""


def _typst() -> Path | None:
    candidates = [os.environ.get("TYPST_PATH"), shutil.which("typst")]
    candidates.extend(str(path) for path in sorted(PROJECT.glob(".tools/quarto-*/bin/tools/*/typst"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _compile(directory: Path, name: str, source: str) -> Path:
    typst = _typst()
    if typst is None:
        pytest.skip("Typst binary unavailable (set TYPST_PATH or install the bundled Quarto tools)")
    if not shutil.which("pdftohtml"):
        pytest.skip("poppler-utils pdftohtml unavailable")
    pytest.importorskip("pypdf")
    (directory / f"{name}.typ").write_text(source, encoding="utf-8")
    subprocess.run([str(typst), "compile", f"{name}.typ", f"{name}.pdf"], cwd=directory, check=True,
                   capture_output=True, text=True, timeout=180)
    return directory / f"{name}.pdf"


def _page_texts(pdf: Path) -> list[str]:
    from pypdf import PdfReader
    return [" ".join(page.extract_text().split()) for page in PdfReader(str(pdf)).pages]


def _errors(pdf: Path) -> list[str]:
    return [finding.code for finding in check_pdf(pdf, MODEL).findings if finding.severity == "error"]


@pytest.mark.integration
def test_tall_table_keeps_its_last_two_rows_together(tmp_path):
    # The committed fixture spills exactly its last row (p38) onto page 2 without the theme.
    fixture = (FIXTURES / "lone-table-row.typ").read_text(encoding="utf-8")
    assert "#set par(justify: false)" in fixture
    assert _errors(_compile(tmp_path, "control", fixture)) == ["lone-table-row"]
    guarded = _compile(tmp_path, "guarded", fixture.replace(
        "#set par(justify: false)", "#set par(justify: false)\n" + THEME.read_text(encoding="utf-8")))
    assert _errors(guarded) == []
    pages = _page_texts(guarded)
    assert len(pages) == 2
    assert "p36" in pages[0] and "p37" not in pages[0], "the table still breaks; only the last two rows move"
    assert "p37" in pages[1] and "p38" in pages[1]
    assert pages[1].startswith("SYNTHETIC · FIXTURE-DUT · run-fixture-lone-row Point Requested load"), "header repeated"
    assert "Uncertainty:" in pages[1]


@pytest.mark.integration
def test_short_table_moves_whole_to_the_next_page_with_its_heading(tmp_path):
    control = _compile(tmp_path, "control", PAGE_SETUP + HEADING_RULE + SHORT_TABLE_BODY)
    assert set(_errors(control)) & {"lone-table-row", "table-header-alone", "orphan-heading"}, \
        "the control layout must split the table or strand its heading for this test to mean anything"
    guarded = _compile(tmp_path, "guarded", PAGE_SETUP + HEADING_RULE + THEME.read_text(encoding="utf-8") + SHORT_TABLE_BODY)
    assert _errors(guarded) == []
    pages = _page_texts(guarded)
    assert len(pages) == 2
    assert "Filler" in pages[0] and "Enabled with no external load" not in pages[0]
    assert all(value in pages[1] for value in ("Enabled with no external load", "Requested input (V)", "12.0009", "0.214958", "0.245952"))
    assert "After the table." in pages[1]


def test_print_header_carries_the_table_rule_and_sticky_headings():
    header = renderer._print_header("SYNTHETIC · 12T12-4A · run-1")
    assert 'header: text(size: 7pt, fill: rgb("516677"), "SYNTHETIC · 12T12-4A · run-1")' in header
    assert HEADING_RULE in header
    assert header.endswith(THEME.read_text(encoding="utf-8"))
    assert header.count("#show table: dcdc-paginate-table") == 1
    # The rule leaves tables that already carry a footer alone, so it cannot recurse on its own output.
    assert "table.footer) { return it }" in header
