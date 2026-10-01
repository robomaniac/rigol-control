"""Best-effort ISO 16750-2 runs: the deviation sheet in the report (docs/standards/best-effort-proposal.md §2.2–2.3, §8).

The procedure records ``run["method"]["best_effort"]``; the analysis carries it
verbatim and derives the first-page sentence, the appendix bullets and the
mandatory no-compliance statement from the entries by template, never from free
text. No instrument, document toolchain or browser is involved here.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from dcdc_bench.analysis import (BEST_EFFORT_CLASSIFICATIONS, BEST_EFFORT_POLL_NOTE, BEST_EFFORT_STATEMENT, ReportModel,
                                 analyze_evidence, best_effort_limitations, best_effort_summary_sentence,
                                 build_best_effort_sheet, build_report_model, deviation_display, deviation_sheet_rows)
from dcdc_bench.reporting import renderer
from dcdc_bench.services import default_plan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "best_effort_sheet_4_6_1_1_A.json"
# The template's output for the 4.6.1.1 variant A fixture: a golden string, changed only on purpose.
GOLDEN_SENTENCE = (
    "ISO 16750-2 clause 4.6.1.1 asks for drop level 4.5 ± 0.2 V, drop duration 100 ± 5 ms, edge max at most 10 ms, "
    "recovery 10 ± 0.5 s and operating mode 3.4; this bench commanded drop level 4.5 V, drop duration 100 ms and "
    "recovery 10 s as a voltage step over LAN and operating mode bounded light load as a steady level (variant A; "
    "drop level not measured at the converter; drop duration host-timed 103 ms, not measured at the converter; "
    "edge max not met, < 110 ms loaded (DS5); recovery met, host-timed 10.021 s; operating mode approximated; "
    "1 met, 1 approximated, 1 not met, 2 not measured; see the deviation sheet).")
GOLDEN_BULLET = ("ISO 16750-2 clause 4.6.1.1: variant A; drop level not measured at the converter (commanded 4.5 V); "
                 "drop duration not measured at the converter (commanded 100 ms, host-timed 103 ms); "
                 "edge max not met, documented: < 110 ms loaded (DS5) against at most 10 ms.")


def recorded_sheet() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_variant_a_sentence_title_counts_and_legend_come_from_the_entries_by_template():
    sheet = build_best_effort_sheet(recorded_sheet())
    assert sheet["summary_sentence"] == GOLDEN_SENTENCE == best_effort_summary_sentence(sheet)
    assert sheet["title"] == "Deviations from ISO 16750-2 clause 4.6.1.1, variant A"
    assert (sheet["standard"], sheet["clause"], sheet["variant"], sheet["test_type"]) == ("ISO 16750-2", "4.6.1.1", "A", "momentary_drop")
    assert sheet["counts"] == {"met": 1, "approximated": 1, "not_met_but_documented": 1, "unknown_until_measured": 2}
    assert list(sheet["bases"]) == ["ISO", "DS5", "derived", "SEED"], "legend in first-use order, only the tags the sheet uses"
    assert sheet["bases"]["DS5"] == "supply datasheet bound"
    assert sheet["statement"] == BEST_EFFORT_STATEMENT == "No clause-compliance result is claimed; the sheet records deviations."
    assert sheet["poll_note"] == BEST_EFFORT_POLL_NOTE
    assert sheet["procedure_statement"] == "Variant A commanded over LAN; nothing at the converter terminals is measured."
    assert sheet["columns"] == ["Parameter", "Clause asks", "This bench", "Mechanism", "Measured by", "Classification", "Note"]
    # The recorded entries survive verbatim; the report's cells sit beside them.
    for recorded, carried in zip(recorded_sheet()["deviations"], sheet["deviations"]):
        assert {key: carried[key] for key in recorded} == recorded
        assert set(carried["display"]) == {"parameter", "clause_asks", "this_bench", "mechanism", "measured_by", "classification", "note"}


def test_table_rows_say_commanded_host_timed_or_not_measured_and_never_achieved_or_pass_fail():
    rows = deviation_sheet_rows(build_best_effort_sheet(recorded_sheet()))
    assert rows[0] == ["drop level (V)", "4.5 ± 0.2 V (ISO)",
                       "commanded 4.5 V; may not be reached before the restore command; unloaded fall < 800 ms (DS5); not measured at the converter",
                       "LAN voltage step", "not measured", "unknown until measured",
                       "The converter drops out below 9 V and draws standby current, so the fall approaches the unloaded case; "
                       "depth at the converter not measured"]
    assert rows[1] == ["drop duration (s)", "100 ± 5 ms (ISO)", "commanded 100 ms; host-timed 103 ms; bounded 0–270 ms (derived)",
                       "LAN voltage step", "host clock (write timestamps)", "unknown until measured",
                       "Two LAN writes, each 4–55 ms transport (LAN) and up to 118 ms processing (DS5); "
                       "interval between the two write timestamps on the Pi"]
    assert rows[2] == ["edge max (s)", "at most 10 ms (ISO)", "< 110 ms loaded (DS5); not measured at the converter",
                       "supply slew", "not measured", "not met, documented", "The supply's loaded fall and rise bound exceeds the clause edge"]
    assert rows[3] == ["recovery (s)", "10 ± 0.5 s (ISO)", "commanded 10 s; host-timed 10.021 s; bounded 10–10.173 s (derived)",
                       "LAN voltage step", "host clock (write timestamps)", "met", "LAN worst case +173 ms lies inside ± 0.5 s"]
    assert rows[4] == ["operating mode", "3.4 (ISO)", "bounded light load; not measured at the converter", "steady level",
                       "not measured", "approximated", "Operating mode 3.4 realised as a fixed light load within the bench envelope"]
    text = " ".join(cell.lower() for row in rows for cell in row) + " " + GOLDEN_SENTENCE.lower()
    for forbidden in ("achieved", "pass", "fail", "compliant"):
        assert forbidden not in text, forbidden
    # Rows derived on the fly (no stored display block) are identical.
    assert deviation_sheet_rows({"deviations": recorded_sheet()["deviations"]}) == rows


def test_appendix_bullets_list_every_not_met_and_not_measured_row_then_the_statement():
    sheet = build_best_effort_sheet(recorded_sheet())
    assert best_effort_limitations(sheet) == [GOLDEN_BULLET, BEST_EFFORT_STATEMENT]
    all_met = build_best_effort_sheet({"clause": "4.9.1", "deviations": [
        {"parameter": "interruption_s", "unit": "s", "required": {"value": 10, "tolerance": 1, "basis": "ISO"},
         "achievable": {"value": 10, "bound": [10, 10.173], "basis": "derived"}, "mechanism": "lan_output_off_on",
         "measured_by": "host_clock", "classification": "met", "note": None,
         "achieved": {"value": 10.04, "measured_by": "host_clock", "note": None}},
        {"parameter": "open_circuit_ohm", "unit": "ohm", "required": {"value": 1e7, "tolerance": "min", "basis": "ISO"},
         "achievable": {"value": "source output OFF", "bound": None, "basis": "UNV"}, "mechanism": "lan_output_off_on",
         "measured_by": "none", "classification": "approximated", "note": "OFF-state impedance is not stated by any document read.",
         "achieved": None}]})
    assert best_effort_limitations(all_met) == [
        "ISO 16750-2 clause 4.9.1: every recorded parameter is met or approximated; see the deviation sheet.", BEST_EFFORT_STATEMENT]
    assert all_met["summary_sentence"] == (
        "ISO 16750-2 clause 4.9.1 asks for interruption 10 ± 1 s and open circuit at least 1e+07 ohm; this bench commanded "
        "interruption 10 s and open circuit source output OFF as an output OFF/ON interruption over LAN (interruption met, "
        "host-timed 10.04 s; open circuit approximated; 1 met, 1 approximated, 0 not met, 0 not measured; see the deviation sheet).")
    assert all_met["title"] == "Deviations from ISO 16750-2 clause 4.9.1" and all_met["variant"] is None
    assert all_met["bases"] == {"ISO": "ISO 16750-2 clause text or figure", "derived": "derived from the tagged bounds",
                                "UNV": "unverified; stated by no document read"}


def test_display_handles_unknown_tags_mechanisms_and_bounds_as_recorded():
    entry = {"parameter": "rest_s", "unit": "s", "required": {"value": 120, "tolerance": "+/- 5 %", "basis": "ISO-fig"},
             "achievable": {"value": 120, "bound": {"lower": 120, "upper": 120.2}, "basis": "bench-note"},
             "mechanism": "relay_box", "measured_by": "scope", "classification": "met", "note": None, "achieved": None}
    display = deviation_display(entry)
    assert display == {"parameter": "rest (s)", "clause_asks": "120 s +/- 5 % (ISO-fig)",
                       "this_bench": "commanded 120 s; bounded 120–120.2 s (bench-note)", "mechanism": "relay box",
                       "measured_by": "scope", "classification": "met", "note": "—"}
    sheet = build_best_effort_sheet({"clause": "4.3.1.2", "deviations": [entry]})
    assert sheet["bases"] == {"ISO-fig": "as recorded", "bench-note": "as recorded"}
    assert deviation_display({"parameter": "edge_max_s", "unit": "s", "required": {"value": .01, "tolerance": .001, "basis": "ISO"},
                              "achievable": {"value": None, "bound": .11, "basis": "DS5"}, "mechanism": None, "measured_by": None,
                              "classification": "not_met_but_documented"})["this_bench"] == "bounded ≤ 110 ms (DS5); not measured at the converter"


@pytest.mark.parametrize("corrupt, message", [
    (lambda raw: raw.pop("clause"), "name its clause"),
    (lambda raw: raw.update(deviations=[]), "at least one deviation"),
    (lambda raw: raw.update(variant=2), "variant must be text"),
    (lambda raw: raw["deviations"][0].update(classification="pass"), "no classification among"),
    (lambda raw: raw["deviations"][0].pop("parameter"), "name its parameter"),
    (lambda raw: raw["deviations"][1].update(required="100 ms"), "required must be a mapping"),
    (lambda raw: raw["deviations"][1]["achieved"].update(value=math.nan), "is not finite"),
    (lambda raw: raw["deviations"][3].update(achievable={"value": 10, "bound": None, "basis": None},
                                             achieved={"value": None, "measured_by": "none", "note": None}),
     "met without a bound or host-timed value"),
])
def test_malformed_sheets_are_refused_rather_than_guessed_at(corrupt, message):
    raw = recorded_sheet()
    corrupt(raw)
    with pytest.raises(ValueError, match=message):
        build_best_effort_sheet(raw)


def _fixture_run(method: dict | None) -> dict:
    run = {"run_id": "best-effort-fixture", "execution_status": "completed"}
    if method is not None:
        run["method"] = method
    return run


def test_report_model_carries_the_sheet_sentence_statement_bullets_section_and_export(tmp_path):
    plan = default_plan()
    run = _fixture_run({"best_effort": recorded_sheet()})
    analysis = analyze_evidence(plan, run, [])
    assert analysis["best_effort"] == recorded_sheet(), "carried verbatim into the analysis"
    analysis["analysis_id"] = "fixture-only"
    model = build_report_model(plan, run, analysis, [])
    assert isinstance(model, ReportModel) and model.best_effort["summary_sentence"] == GOLDEN_SENTENCE
    assert model.best_effort["deviations"][1]["display"]["this_bench"] == "commanded 100 ms; host-timed 103 ms; bounded 0–270 ms (derived)"
    index = model.summary.index(GOLDEN_SENTENCE)
    assert model.summary[index + 1] == BEST_EFFORT_STATEMENT, "the statement follows the sentence on page one"
    assert model.limitations[-2:] == [GOLDEN_BULLET, BEST_EFFORT_STATEMENT]
    dumped = model.model_dump()
    renderer.validate_report_model(dumped)
    body = renderer._body(dumped)
    assert "### Deviations from ISO 16750-2 clause 4.6.1.1, variant A {#deviations}" in body
    assert renderer._md(GOLDEN_SENTENCE) in body and body.count(renderer._md(BEST_EFFORT_STATEMENT)) >= 3
    exports = renderer.write_exports(dumped, tmp_path)
    assert set(exports) == {"points.csv", "points.meta.json", "deviations.json"}
    payload = json.loads((tmp_path / "exports/deviations.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "best-effort-deviation-sheet" and payload["run_id"] == "best-effort-fixture"
    assert payload["summary_sentence"] == GOLDEN_SENTENCE and payload["statement"] == BEST_EFFORT_STATEMENT
    assert payload["deviations"] == model.best_effort["deviations"]
    # An analysis issued before the sheet was carried still reaches the report from the method block.
    older = {key: value for key, value in analysis.items() if key != "best_effort"}
    assert build_report_model(plan, run, older, []).best_effort == model.best_effort


def test_without_a_recorded_sheet_nothing_is_added():
    plan = default_plan()
    run = _fixture_run(None)
    analysis = analyze_evidence(plan, run, [])
    assert "best_effort" not in analysis
    analysis["analysis_id"] = "fixture-only"
    model = build_report_model(plan, run, analysis, [])
    assert model.best_effort is None
    assert not any("ISO 16750-2 clause" in text for text in [*model.summary, *model.limitations])
    body = renderer._body(model.model_dump())
    assert "Deviations from" not in body and "deviations.json" not in body and BEST_EFFORT_STATEMENT not in body
    assert set(BEST_EFFORT_CLASSIFICATIONS) == {"met", "approximated", "not_met_but_documented", "unknown_until_measured"}


def test_building_the_sheet_leaves_the_recorded_block_untouched():
    raw = recorded_sheet()
    before = copy.deepcopy(raw)
    build_best_effort_sheet(raw)
    assert raw == before
