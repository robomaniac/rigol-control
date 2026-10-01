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


THEME_IDENTITY = {"title": "DC–DC converter characterization", "dut": "FIXTURE-DUT", "evidence": "SYNTHETIC",
                  "recorded": "Sep 29, 2026, 13:37 PDT", "subtitle": "SYNTHETIC evidence · Recorded Sep 29, 2026, 13:37 PDT",
                  "run": "run-fixture-lone-row", "revision": "r0001", "analysis": "a-1"}
# What Quarto emits after the header include: its page partial, then the typst-show.typ partial.
QUARTO_PAGE_AND_SHOW = """#set page(
  paper: "us-letter",
  margin: (x: 1.25in,y: 1.25in,),
  numbering: none,
  columns: 1,
)
#show: doc => dcdc-report(doc)
"""
THEME_BODY = """
#block[
#table(
  columns: (22%, 78%),
  align: (auto,auto,),
  table.header([About this report], [],),
  table.hline(),
  [Device tested], [FIXTURE-DUT — Sample: s1],
  [Traceability], [Run ID run-fixture-lone-row; analysis a-1; method version v; report revision r0001 — these match this document to its raw data files.],
)
]
= Summary
<summary>
#lorem(80)

== Coverage
<coverage>
#table(
  columns: 4,
  align: (auto,auto,auto,auto,),
  table.header([Test], [Requested], [Valid], [Other outcomes],),
  table.hline(),
  [load], [4], [1], [inconclusive: 3],
)
#pagebreak()
= Results
<results>
#lorem(900)

= Appendix
<appendix>
#lorem(40)
"""


def test_print_header_carries_identity_theme_and_table_rule():
    header = renderer._print_header(THEME_IDENTITY)
    assert header.startswith("#let dcdc-id = (\n")
    for line in ('  dut: "FIXTURE-DUT",', '  evidence: "SYNTHETIC",', '  run: "run-fixture-lone-row",',
                 '  revision: "r0001",', '  recorded: "Sep 29, 2026, 13:37 PDT",', '  paper: "us-letter",'):
        assert line in header
    assert '  paper: "a4",' in renderer._print_header(THEME_IDENTITY, "a4")
    with pytest.raises(ValueError, match="letter or a4"):
        renderer._print_header(THEME_IDENTITY, "legal")
    theme = (renderer.TEMPLATES / "theme/print-theme.typ").read_text(encoding="utf-8")
    assert theme in header and header.endswith(THEME.read_text(encoding="utf-8"))
    # Headings travel with the block after them; identity and page numbers sit on every page.
    assert "sticky: true" in theme
    assert "Run #dcdc-id.run · Report revision #dcdc-id.revision" in theme
    assert "Page #counter(page).display() of #counter(page).final().first()" in theme
    assert header.count("#show table: dcdc-paginate-table") == 1
    # The rule leaves tables that already carry a footer alone, so it cannot recurse on its own output.
    assert "table.footer) { return it }" in header
    # Identity strings are literals, never code.
    hostile = renderer._print_header(dict(THEME_IDENTITY, dut='x" + sys.inputs.at("y") + "', run="line\nbreak"))
    assert '  dut: "x\\" + sys.inputs.at(\\"y\\") + \\"",' in hostile and '  run: "line break",' in hostile


@pytest.mark.integration
@pytest.mark.parametrize("paper, size", [("letter", (612, 792)), ("a4", (595, 842))])
def test_datasheet_theme_pages_carry_identity_numbers_and_flow_continuously(tmp_path, paper, size):
    """The theme applied exactly as Quarto assembles it: Letter/A4, identity and page number on every page,
    numbered sections, the body's hard page breaks collapsed, and no pagination finding."""
    from pypdf import PdfReader
    pdf = _compile(tmp_path, paper, renderer._print_header(THEME_IDENTITY, paper) + QUARTO_PAGE_AND_SHOW + THEME_BODY)
    reader = PdfReader(str(pdf))
    assert {(round(float(page.mediabox.width)), round(float(page.mediabox.height))) for page in reader.pages} == {size}
    pages = _page_texts(pdf)
    assert len(pages) >= 2
    for number, text in enumerate(pages, 1):
        assert "run-fixture-lone-row" in text and "Report revision r0001" in text
        assert f"Page {number} of {len(pages)}" in text
        assert "SYNTHETIC · Recorded Sep 29, 2026, 13:37 PDT" in text
    assert "About this report" in pages[0] and "Device tested FIXTURE-DUT" in pages[0]
    result = check_pdf(pdf, MODEL)
    assert [finding.code for finding in result.findings if finding.severity == "error"] == []
    first = result.to_dict()["pages"][0]
    assert first["page_number"] == f"Page 1 of {len(pages)}" and first["run_id_present"]
    assert {"1 Summary", "1.1 Coverage", "2 Results"} <= set(first["headings"]), "numbered; the page break became a gap"


# The Device tested section as Quarto emits it from the renderer's Markdown: two key-value tables (each inside
# Quarto's own #block) and the documentation note, between the renderer's raw Typst block delimiters.
DUT_TABLES = """#block[
#table(
  columns: (28%, 72%),
  align: (auto,auto,),
  table.header([Identity], [Recorded value],),
  table.hline(),
  [Model], [FIXTURE-DUT],
  [Sample], [sample-1],
  [Brand on sample label], [unknown],
  [Owner-provided aliases], [none],
  [Topology / controller / isolation], [unknown — black-box characterization],
)
]
#block[
#table(
  columns: (28%, 72%),
  align: (auto,auto,),
  table.header([Rating / evidence], [Recorded value],),
  table.hline(),
  [Input operating range], [9–36 V],
  [Nominal output], [12 V],
  [Rated output], [4 A / 48 W],
  [Rating origin], [datasheet],
  [Sample-label verification], [yes],
)
]
"""
DUT_NOTE = ("Schematic and sample photographs: not supplied in this report model. "
            "No internal topology or component identity is inferred.")


def _dut_body(filler_pt: int, guarded: bool) -> str:
    opening, closing = ("#block(breakable: false)[\n", "]\n") if guarded else ("", "")
    return (f"= Summary\n<summary>\n#block(height: 100% - {filler_pt}pt)[Filler that leaves part of the page free.]\n"
            "= Device tested\n<dut>\n" + opening + DUT_TABLES + DUT_NOTE + "\n" + closing
            + "= Test method\n<method>\nAfter the device section.\n")


@pytest.mark.integration
def test_dut_documentation_note_shares_its_page_with_its_tables(tmp_path):
    """Codex review item 8, compiled with the issued theme: wherever the section starts on the page, the
    documentation note is on the same page as both Device tested tables and no pagination error results.
    The unguarded layout (the control) separates the note from its tables for at least one of these positions,
    which is what the review observed."""
    header = renderer._print_header(THEME_IDENTITY, "letter") + QUARTO_PAGE_AND_SHOW
    separated = []
    for filler in (200, 230, 260, 290, 320):
        for guarded in (False, True):
            pdf = _compile(tmp_path, f"dut-{filler}-{'guarded' if guarded else 'control'}", header + _dut_body(filler, guarded))
            pages = _page_texts(pdf)
            note_page = next(index for index, text in enumerate(pages) if "No internal topology" in text)
            together = all(text in pages[note_page] for text in ("Identity Recorded value", "Rating / evidence", "Owner-provided aliases"))
            if guarded:
                assert together, f"filler {filler}pt: the note left its tables"
                assert "Device tested" in pages[note_page], "the sticky heading travels with the block"
                assert _errors(pdf) == []
            else:
                separated.append(not together)
    assert any(separated), "the control must separate the note for at least one position, or the test proves nothing"
