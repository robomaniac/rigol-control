"""Rendering validates references, preserves analysis, and reports failures honestly."""
import contextlib
import copy
import csv
import hashlib
import io
import json
import os
import time
from pathlib import Path

import pytest

from dcdc_bench.reporting import ReportRenderError, render_report, validate_report_model
from dcdc_bench.reporting import renderer


@pytest.fixture
def model():
    return {
        "run_id": "synthetic-run", "analysis_id": "analysis-1", "report_revision": "r0001",
        "evidence_label": "SYNTHETIC", "boundary": "source-to-DUT-output path",
        "dut": {"model": "Different 5 V DUT", "sample_id": "sample-1"},
        "points": [{"point_id": "p1", "test_id": "load", "vin_target_V": 12,
                    "iout_target_A": .1, "Iout_A": .099, "efficiency_pct": 39.1575,
                    "qualification": "valid"},
                   {"point_id": "p2", "test_id": "load", "vin_target_V": 12,
                    "iout_target_A": .2, "Iout_A": .2, "efficiency_pct": None,
                    "qualification": "inconclusive"},
                   {"point_id": "p3", "test_id": "load", "vin_target_V": 12,
                    "iout_target_A": .3, "Iout_A": .3, "efficiency_pct": 81.23456789,
                    "qualification": "valid"}],
        "figures": [{"id": "fig-efficiency", "title": "Path efficiency",
                     "x_key": "Iout_A", "y_key": "efficiency_pct", "x_label": "Output current (A)",
                     "y_label": "Efficiency (%)", "caption": "Measured input conditions: 12 V.",
                     "series": [{"id": "vin-12", "label": "12 V", "vin_target_V": 12,
                                 "point_ids": ["p1", "p2", "p3"]}]}],
        "metrics": [{"id": "peak", "label": "Recorded peak", "value": 81.23456789,
                     "unit": "%", "conditions": "12 V input", "point_ids": ["p3"],
                     "figure_ids": ["fig-efficiency"]}], "raw_samples": {}, "summary": [],
    }


def test_missing_reference_blocks_report_before_writing(model, tmp_path):
    model["figures"][0]["series"][0]["point_ids"].append("not-present")
    with pytest.raises(ValueError, match="missing point"):
        render_report(model, tmp_path / "report")
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("bad", ["../report", "fig-ok\" onclick=alert(1)", "fig-<script>"])
def test_figure_ids_cannot_inject_markup_or_paths(model, bad):
    model["figures"][0]["id"] = bad
    with pytest.raises(ValueError, match="Unsafe figure"):
        validate_report_model(model)


def test_nonfinite_values_rejected_even_inside_raw_evidence(model):
    model["raw_samples"] = {"p1": [{"value": float("nan")} ]}
    with pytest.raises(ValueError, match="finite"):
        validate_report_model(model)


def test_embedded_data_cannot_close_script_and_preserves_evidence():
    original = {"caption": '</script><img src=x onerror="window.pwned=1">', "text": "a&b\u2028c"}
    encoded = renderer._embedded_json(original)
    assert "</script>" not in encoded
    assert "<img" not in encoded
    assert json.loads(encoded) == original


def test_static_plot_uses_supplied_results_keeps_gaps_and_full_auto_range(model):
    before = copy.deepcopy(model)
    figure = renderer._plot_figure(model, model["figures"][0], 1)
    assert list(figure.data[0].y) == [39.1575, None, 81.23456789]
    assert figure.data[0].connectgaps is False
    assert figure.layout.yaxis.range is None
    assert figure.data[0].type == "scatter"
    text = figure.layout.annotations[0].text
    for expected in ("SYNTHETIC", "Different 5 V DUT", "synthetic-run", "analysis-1", "fig-efficiency"):
        assert expected in text
    assert model == before


def test_dut_body_displays_declared_construction_and_attachment_references(model):
    model["dut"]["construction"] = {"topology": "buck", "controller_part_number": "fixture-controller",
                                    "isolation": "nonisolated"}
    model["provenance"] = {"attachment_descriptors": [{"purpose": "schematic", "filename": "example.pdf"}]}
    body = renderer._body(model)
    assert "buck / fixture-controller / nonisolated" in body
    assert "unknown — black-box characterization" not in body
    assert "Attachment references: 1 supplied with acquisition metadata" in body
    assert "References alone do not establish that a schematic or photograph is embedded" in body
    assert "Schematic and sample photographs: not supplied" not in body
    assert "Photographic sensor-placement documentation is included" not in body


def test_dut_body_distinguishes_rendered_sensor_documentation_from_default_absence(model):
    default = renderer._body(model)
    assert "unknown — black-box characterization" in default
    assert "Schematic and sample photographs: not supplied in this report model." in default
    with_photograph = renderer._body(model, sensor_placement_present=True)
    assert "Photographic sensor-placement documentation is included" in with_photograph
    assert "[Sensor placement section](#sensor-placement)" in with_photograph
    assert "Schematic and sample photographs: not supplied" not in with_photograph
    assert "Attachment references:" not in with_photograph


def test_dut_body_keeps_unknown_construction_fields_without_discarding_known_values(model):
    model["dut"]["construction"] = {"topology": "buck"}
    body = renderer._body(model)
    assert "buck / unknown / unknown" in body
    assert "unknown — black-box characterization" not in body


def test_equipment_report_separates_fields_and_escapes_instrument_replies(model):
    model["provenance"] = {"instrument_identities": {
        "source": {"model": "DP821A", "serial": 'DP8|<script>bad()</script>',
                   "firmware": "00.01.16", "manufacturer": "RIGOL TECHNOLOGIES"},
        "load": {"model": "DL3031A", "firmware": "  "},
    }}
    body = renderer._body(model)
    assert "| Role | Equipment Model | Serial Number | Firmware | Manufacturer |" in body
    assert "Verified reported identity" not in body
    assert r"| Source | DP821A | DP8\|\<script\>bad()\</script\> | 00.01.16 | RIGOL TECHNOLOGIES |" in body
    assert "| Load | DL3031A | not reported | not reported | not reported |" in body
    assert "<script>bad()" not in body


def test_dut_identity_and_ratings_share_explicit_column_widths(model):
    model["dut"]["ratings"] = {"input_voltage_min_V": 9., "input_voltage_max_V": 36.,
        "output_voltage_nominal_V": 12., "output_current_rated_A": 4., "output_power_rated_W": 48.}
    body = renderer._body(model)
    assert body.count("::: {.report-table .table-key-value}") == 2
    assert body.count('tbl-colwidths="[38,62]"') == 2
    assert "9.0–36.0 V" in body


def test_voltage_palette_is_shared_across_subsets_and_keeps_measurements(model):
    base = copy.deepcopy(model["figures"][0])
    model["points"] = []
    base["series"] = []
    for vin in (36., 12., 24.):
        pid = f"vin-{vin:g}-point"
        model["points"].append({"point_id": pid, "vin_target_V": vin, "Iout_A": .1,
                                "efficiency_pct": 80 + vin / 100, "qualification": "valid"})
        base["series"].append({"id": f"vin-{vin:g}", "label": f"{vin:g} V",
                               "vin_target_V": vin, "point_ids": [pid]})
    subset = copy.deepcopy(base)
    subset["id"] = "fig-subset"
    subset["series"] = [subset["series"][0]]
    model["figures"] = [subset, base]
    before = copy.deepcopy(model)
    palette = renderer._condition_colors(model)
    assert palette == {"12": "#0072B2", "24": "#D55E00", "36": "#CC33AA"}
    full = renderer._plot_figure(model, base, 2)
    small = renderer._plot_figure(model, subset, 1)
    assert {trace.name: trace.line.color for trace in full.data} == {
        "12 V": palette["12"], "24 V": palette["24"], "36 V": palette["36"]}
    assert small.data[0].line.color == palette["36"]
    assert [(trace.line.dash, trace.marker.symbol) for trace in full.data] == [
        ("dot", "diamond"), ("solid", "circle"), ("dash", "square")]
    assert small.data[0].line.dash == "dot"
    assert small.data[0].marker.symbol == "diamond"
    assert all(trace.marker.color == trace.line.color for trace in full.data)
    assert [trace.y[0] for trace in full.data] == [80.36, 80.12, 80.24]
    assert model == before


def test_continuation_preserves_voltage_colors_without_fabricating_missing_curve(model):
    model["execution"] = {"voltage_efficiency_sweep": {"nominal_input_voltages_V": [12., 24., 36.]}}
    series = model["figures"][0]["series"][0]
    series.update(vin_target_V=24., label="24 V input")
    palette = renderer._condition_colors(model)
    assert palette == {"12": renderer.COLORS[0], "24": renderer.COLORS[1], "36": renderer.COLORS[2]}
    plot = renderer._plot_figure(model, model["figures"][0], 1)
    assert len(plot.data) == 1
    assert plot.data[0].name == "24 V input" and plot.data[0].line.color == palette["24"]


@pytest.mark.parametrize("vin,color,dash,symbol", [
    (12., "#0072B2", "solid", "circle"),
    (24., "#D55E00", "dash", "square"),
    (36., "#CC33AA", "dot", "diamond"),
])
def test_standard_voltage_style_survives_standalone_report_without_sweep_metadata(model, vin, color, dash, symbol):
    """A single-voltage report must not silently reset every condition to blue."""
    for point in model["points"]:
        point["vin_target_V"] = vin
    series = model["figures"][0]["series"][0]
    series.update(vin_target_V=vin, label=f"{vin:g} V input")
    before = copy.deepcopy(model)
    trace = renderer._plot_figure(model, model["figures"][0], 1).data[0]
    assert (trace.line.color, trace.line.dash, trace.marker.symbol) == (color, dash, symbol)
    assert list(trace.y) == [39.1575, None, 81.23456789]
    assert trace.connectgaps is False
    assert model == before


def test_stage_styles_remain_distinct_when_hold_only_figure_comes_first(model):
    for point in model["points"]:
        point.update(qualification="valid", efficiency_pct=80., vin_target_V=24.)
    full = copy.deepcopy(model["figures"][0])
    full["series"] = [{"id": f"{stage}-v0", "selection_key": f"{stage}-v0",
        "label": label, "vin_target_V": 24., "point_ids": [point["point_id"]]}
        for stage, label, point in zip(("increasing-load", "sustained-load", "decreasing-load"),
            ("Increasing load · 24 V", "Hold · 24 V", "Decreasing load · 24 V"), model["points"])]
    hold = copy.deepcopy(full)
    hold.update(id="fig-hold", series=[copy.deepcopy(full["series"][1])])
    model["figures"] = [hold, full]
    before = copy.deepcopy(model)
    traces = renderer._plot_figure(model, full, 2).data
    assert [(trace.line.color, trace.line.dash, trace.marker.symbol) for trace in traces] == [
        ("#0072B2", "solid", "circle"), ("#D55E00", "dash", "square"), ("#CC33AA", "dot", "diamond")]
    isolated = renderer._plot_figure(model, hold, 1).data[0]
    assert (isolated.line.color, isolated.line.dash, isolated.marker.symbol) == (
        traces[1].line.color, traces[1].line.dash, traces[1].marker.symbol)
    assert model == before


def test_output_reference_includes_nominal_qualified_values_and_bands_without_changing_data(model):
    model["dut"]["ratings"] = {"output_voltage_nominal_V": 12.}
    spec = model["figures"][0]
    spec.update(id="fig-voltage", y_key="Vout_V", lower_key="Vout_min_V", upper_key="Vout_max_V")
    for point, voltage in zip(model["points"], (12.133, 999., 12.135)):
        point["Vout_V"] = voltage
    model["points"][2]["Vout_max_V"] = 12.2
    before = copy.deepcopy(model)
    reference = renderer._figure_references(model)["fig-voltage"]
    assert reference["value"] == 12. and reference["label"] == "Nominal 12 V"
    assert reference["y_range"] == pytest.approx([11.984, 12.216])
    plot = renderer._plot_figure(model, spec, 1)
    assert list(plot.data[-1].y) == [12.133, None, 12.135]
    assert list(plot.layout.yaxis.range) == pytest.approx(reference["y_range"])
    assert plot.layout.yaxis.autorange is False
    assert plot.layout.shapes[0].y0 == plot.layout.shapes[0].y1 == 12.
    assert plot.layout.shapes[0].line.dash == "dash"
    assert plot.layout.annotations[-1].text == "Nominal 12 V"
    assert model == before


@pytest.mark.parametrize("method", ["source_limit_search", "voltage_efficiency_sweep"])
def test_source_current_reference_uses_recorded_limit_and_covers_zero(model, method):
    model["execution"] = {method: {"input_current_limit_A": 1.}}
    spec = model["figures"][0]
    spec.update(id="fig-source-current", y_key="Iin_A")
    for point, current in zip(model["points"], (.3, 999., .95)):
        point["Iin_A"] = current
    before = copy.deepcopy(model)
    reference = renderer._figure_references(model)["fig-source-current"]
    assert reference == {"value": 1., "label": "Supply limit 1 A", "y_range": [-.08, 1.08]}
    plot = renderer._plot_figure(model, spec, 1)
    assert plot.layout.shapes[0].y0 == 1.
    assert list(plot.data[0].y) == [.3, None, .95]
    assert model == before


@pytest.mark.parametrize("value", [None, 0., -12., True, "12", float("nan"), float("inf")])
def test_missing_or_invalid_reference_does_not_invent_nominal_or_limit(model, value):
    model["dut"]["ratings"] = {"output_voltage_nominal_V": value}
    model["execution"] = {"voltage_efficiency_sweep": {"input_current_limit_A": value}}
    voltage = model["figures"][0]
    voltage.update(id="fig-voltage", y_key="Vout_V")
    current = copy.deepcopy(voltage)
    current.update(id="fig-source-current", y_key="Iin_A")
    model["figures"] = [voltage, current]
    assert renderer._figure_references(model) == {}


def test_voltage_comparison_uses_supplied_values_and_discloses_unreached_conditions(model):
    model["points"].append({"point_id": "unused", "test_id": "load", "vin_target_V": 35.8,
        "iout_target_A": 2., "qualification": "not-run", "reason": "boundary reached"})
    model["dut"]["ratings"] = {"input_voltage_min_V": 9., "input_voltage_max_V": 36., "output_voltage_nominal_V": 12.}
    model["execution"] = {
        "voltage_efficiency_sweep": {"input_current_limit_A": 1.},
        "executed_point_ids": ["p1", "p2", "p3"],
        "voltage_comparison": [
            {"label": "12 V input", "nominal_input_V": 12., "programmed_input_V": 12., "reference_load_A": .5,
             "reference_measured_input_V": 12.00234,
             "reference_efficiency_pct": 83.45678, "highest_load_A": .797123,
             "peak_efficiency_pct": 84.67891, "peak_efficiency_current_A": .69932,
             "qualified_points": 7, "phase_status": "completed", "stop_reason": "source headroom boundary"},
            {"label": "24 V input", "nominal_input_V": 24., "programmed_input_V": 24., "reference_load_A": .5,
             "qualified_points": 0, "phase_status": "not-run", "stop_reason": "not started"},
            {"label": "36 V nominal (35.8 V set)", "nominal_input_V": 36., "programmed_input_V": 35.8,
             "reference_load_A": .5, "qualified_points": 0, "phase_status": "not-run",
             "stop_reason": "earlier phase fault"},
        ]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "| 12 V input | 12.002 V | 83.46 % | 0.797 A | 84.68 % at 0.70 A |" in body
    assert "| 36 V nominal (35.8 V set) | not available | not available | not available | not available |" in body
    assert "same 0.5 A requested output load" in body
    assert "| Input condition | Simulated input at 0.5 A | Efficiency at 0.5 A |" in body
    assert "supply is limited to 1 A at its output" in body
    assert "Highest qualified load" in body and "Highest tested load" not in body
    assert "See @fig-efficiency." in body
    assert "The supply powers the converter input at three conditions: 12 V, 24 V and nominal 36 V." in body
    assert "from the converter's 12 V output" in body
    assert "The supply current limit is 1 A, so" in body
    assert "programmed at 35.8 V, 0.2 V below the stated 36 V input ceiling" in body
    assert "not an exact 36.000 V endpoint test" in body
    assert "The stated 9–36 V operating range is not fully verified by these three conditions." in body
    # No run evidence records the outputs being switched between conditions;
    # the renderer must not assert it on the recipe's behalf.
    assert "switched OFF" not in body
    assert "1 declared load conditions were not reached" in body
    assert "earlier phase fault" in body and "source headroom boundary" in body
    assert "coarse stepping" not in body
    assert "| unused |" not in body
    assert "No-load consumption was not measured" in body
    assert "| Result | Value | Conditions and evidence |" not in body
    assert model == before


def test_prior_startup_failure_is_separate_from_current_efficiency_evidence(model):
    model["execution"] = {"voltage_efficiency_sweep": {"prior_input_attempt": {
        "run_id": "earlier-aborted-run", "reason": "source current limit during startup",
        "last_startup_cycle": {"Vin_V": 7.125, "Iin_A": .9991, "Vout_V": .1, "Iout_A": .02}}},
        "voltage_comparison": [
            {"label": "12 V input", "nominal_input_V": 12., "programmed_input_V": 12., "qualified_points": 0,
             "phase_status": "previous-attempt-unqualified"},
            {"label": "24 V input", "nominal_input_V": 24., "programmed_input_V": 24., "qualified_points": 0,
             "phase_status": "not-run"},
            {"label": "36 V nominal (35.8 V set)", "nominal_input_V": 36., "programmed_input_V": 35.8,
             "qualified_points": 0, "phase_status": "not-run"}]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "The 12 V condition was attempted in an earlier run" in body
    assert "It therefore has no efficiency curve" in body
    assert "This run continues with 24 V and nominal 36 V." in body
    assert "The comparison covers the requested 12 V, 24 V and nominal 36 V conditions." in body
    assert "The earlier 12 V startup attempt produced no qualified efficiency result." in body
    assert "This acquisition continues at 24 V and nominal 36 V" in body
    assert "Earlier 12 V startup attempt {#prior-input-attempt}" in body
    assert "not a settled operating point" in body
    assert "| 7.125 V | 0.9991 A | 0.100 V | 0.0200 A |" in body
    assert "earlier-aborted-run" in body
    assert "Earlier startup stopped" in body and "previous-attempt-unqualified" not in body
    assert "No efficiency result; not repeated in this run" in body
    assert "The cause has not been established" in body
    assert "source current limit during startup" not in body
    assert model == before


def test_missing_pdf_tools_records_failure_and_removes_stale_outputs(model, tmp_path, monkeypatch):
    (tmp_path / "report.pdf").write_bytes(b"stale report from another build")
    # The renderer probes the browser (BROWSER_PATH, .tools/browser-path.txt,
    # PATH) and Quarto before rendering. Stubbing only _quarto once let a live
    # `chromium-headless-shell --version` run and exceed its 30 s budget under
    # host load, masking the intended Quarto failure. Nothing on this path may
    # reach a real process.
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.delenv("QUARTO_PATH", raising=False)
    monkeypatch.setattr(renderer, "_browser_path", lambda: None)
    monkeypatch.setattr(renderer.shutil, "which", lambda *args, **kwargs: None)
    launched = []

    def refuse_process(command, *args, **kwargs):
        launched.append(list(command))
        raise FileNotFoundError(f"unit test refused to launch {command[0]}")
    monkeypatch.setattr(renderer.subprocess, "run", refuse_process)

    def unavailable():
        raise ReportRenderError("Quarto unavailable for regression fixture")
    monkeypatch.setattr(renderer, "_quarto", unavailable)
    with pytest.raises(ReportRenderError, match="Quarto unavailable") as caught:
        render_report(model, tmp_path, formats=("pdf",))
    manifest = json.loads((tmp_path / "build_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["artifacts"]["pdf"]["status"] == "failed"
    assert caught.value.manifest == manifest
    assert not (tmp_path / "report.pdf").exists()
    assert launched == [], "renderer reached a subprocess on the missing-Quarto path"


def test_unknown_format_is_not_silently_ignored(model, tmp_path):
    with pytest.raises(ValueError, match="formats"):
        render_report(model, tmp_path, formats=("html", "imaginary"))
    assert not (tmp_path / "build_manifest.json").exists()


def test_large_evidence_bypasses_document_parser_without_losing_data(model, tmp_path, monkeypatch):
    """Prevent the Pi memory regression; the document parser receives no raw JSON.

    This isolates parser orchestration, not real browser/PDF acceptance.
    """
    import re
    from types import SimpleNamespace
    import plotly.offline
    raw = '</script>RAW-EVIDENCE-' + 'x' * (2 * 1024 * 1024)
    model["raw_samples"] = {"p1": [{"raw_response": raw}]}
    runtime = 'window.runtimeFixture=true;'
    monkeypatch.setattr(plotly.offline, "get_plotlyjs", lambda: runtime)
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-test-fixture")

    async def static_fixture(model, directory):
        for spec in model["figures"]:
            for extension in ("svg", "pdf"):
                (directory / (spec["id"] + '.' + extension)).write_text('unit-test fixture')
    monkeypatch.setattr(renderer, "_write_static_figures", static_fixture)

    def document_fixture(command, **kwargs):
        if command[-1] == '--version':
            return SimpleNamespace(stdout='1.10.18\n', stderr='', returncode=0)
        directory = Path(kwargs['cwd'])
        slot = (directory/'interactions.html').read_text()
        assert len(slot) < 100
        assert 'RAW-EVIDENCE' not in (directory/'report.qmd').read_text()
        assert runtime not in slot
        (directory/'report.html').write_text('<!doctype html><html><body>' + slot + '</body></html>')
        return SimpleNamespace(stdout='fixture conversion', stderr='', returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)
    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)
    result = render_report(model, tmp_path, formats=('html',))
    document = (tmp_path/'report.html').read_text()
    assert result['status'] == 'success'
    assert document.count(runtime) == 1
    payload = re.search(r'<script type="application/json" id="dcdc-report-data">(.*?)</script>',
                        document, flags=re.S).group(1)
    assert json.loads(payload)['model']['raw_samples']['p1'][0]['raw_response'] == raw
    assert json.loads(payload)['condition_colors'] == renderer._condition_colors(model)
    assert json.loads(payload)['condition_styles'] == renderer._condition_styles(model)
    assert json.loads(payload)['figure_references'] == renderer._figure_references(model)
    encoded_style = json.loads(payload)['condition_styles']['12']
    static_trace = renderer._plot_figure(model, model['figures'][0], 1).data[0]
    assert encoded_style == {"color": static_trace.line.color, "dash": static_trace.line.dash,
                             "symbol": static_trace.marker.symbol}
    assert '</script>RAW-EVIDENCE' not in document


def test_prior_attempt_without_recorded_conditions_names_no_voltage(model):
    """Absent evidence leaves the sentence out; it never falls back to a recipe."""
    model["execution"] = {"voltage_efficiency_sweep": {"prior_input_attempt": {
        "run_id": "earlier-aborted-run",
        "last_startup_cycle": {"Vin_V": 7.125, "Iin_A": .9991, "Vout_V": .1, "Iout_A": .02}}},
        "voltage_comparison": [{"label": "earlier input", "qualified_points": 0,
                                "phase_status": "previous-attempt-unqualified"}]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "### Earlier startup attempt {#prior-input-attempt}" in body
    assert "An earlier run attempted an input condition and produced no qualified efficiency result." in body
    assert "An earlier startup attempt produced no qualified efficiency result." in body
    assert "| Input condition | Simulated input at the reference load | Efficiency at the reference load |" in body
    for invented in ("The earlier ", "condition was attempted", "continues with", "continues at",
                     "covers the requested", "Earlier 12 V", "24 V", "36 V"):
        assert invented not in body, invented
    assert model == before


def test_voltage_narrative_follows_recorded_conditions_not_recipe_literals(model):
    """A 2 A supply with 18 V / near-28 V inputs must not tell the 1 A, 12/24/36 V story."""
    for point, vin in zip(model["points"], (18., 18., 28.)):
        point["vin_target_V"] = vin
    model["figures"][0]["series"] = [
        {"id": "vin-18", "label": "18 V input", "vin_target_V": 18., "point_ids": ["p1", "p2"]},
        {"id": "vin-28", "label": "28 V nominal (27.8 V set)", "vin_target_V": 28., "point_ids": ["p3"]}]
    model["dut"]["ratings"] = {"input_voltage_min_V": 9., "input_voltage_max_V": 28., "output_voltage_nominal_V": 5.}
    model["bench"] = {"protective_controls": {"source_current_limit_A": 2.}, "measurements": {
        name: {"instrument_id": "x", "quantity": name, "unit": name[-1], "location": "bench"}
        for name in ("Vin_V", "Iin_A", "Vout_V", "Iout_A")}}
    model["execution"] = {"voltage_efficiency_sweep": {"input_current_limit_A": 2.},
        "voltage_comparison": [
            {"label": "18 V input", "nominal_input_V": 18., "programmed_input_V": 18., "reference_load_A": .25,
             "qualified_points": 2, "phase_status": "completed", "stop_reason": "grid completed"},
            {"label": "28 V nominal (27.8 V set)", "nominal_input_V": 28., "programmed_input_V": 27.8,
             "reference_load_A": .25, "qualified_points": 1, "phase_status": "completed",
             "stop_reason": "grid completed"}]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "Compare the curves at the same 0.25 A requested output load." in body
    assert "supply is limited to 2 A at its output" in body
    assert "| Input condition | Simulated input at 0.25 A | Efficiency at 0.25 A |" in body
    assert "The supply powers the converter input at two conditions: 18 V and nominal 28 V." in body
    assert "from the converter's 5 V output" in body
    assert "The supply current limit is 2 A, so" in body
    assert "The nominal 28 V condition is programmed at 27.8 V, 0.2 V below the stated 28 V input ceiling." in body
    assert "not an exact 28.000 V endpoint test" in body
    assert "The stated 9–28 V operating range is not fully verified by these two conditions." in body
    assert "No temperature measurement channel is bound in this bench profile" in body
    for literal in ("0.5 A requested", "limited to 1 A", "current limit is 1 A", "35.8 V", "36.000 V",
                    "12 V, 24 V and nominal 36 V", "three conditions", "12 V output", "switched OFF",
                    "temperature probe"):
        assert literal not in body, literal
    assert model == before


def test_voltage_narrative_omits_every_condition_the_model_does_not_record(model):
    model["execution"] = {"voltage_efficiency_sweep": {"target_input_current_A": .98},
        "voltage_comparison": [{"label": "first input", "qualified_points": 1, "phase_status": "completed"},
                               {"label": "second input", "qualified_points": 1, "phase_status": "completed"}]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    controls = renderer._controls_html(model)
    assert "### Efficiency at each input voltage" in body
    assert "| Input condition | Simulated input at the reference load | Efficiency at the reference load |" in body
    assert "The supply powers the converter input at each requested condition." in body
    assert "from the converter's output." in body
    assert "A curve stops at the recorded source or measurement boundary." in body
    for absent in ("requested output load", "supply is limited to", "supply current limit is", "programmed at",
                   "endpoint test", "operating range is not fully verified", "temperature was not acquired",
                   "temperature probe", "switched OFF", "converter input at one", "converter input at two",
                   "converter input at three", "V input ceiling"):
        assert absent not in body, absent
    assert "Temperatures" not in controls
    assert model == before


@pytest.mark.parametrize("bindings,expected", [
    ({"Vin_V": {"unit": "V", "quantity": "Vin_V"}, "Iout_A": {"unit": "A", "quantity": "Iout_A"}}, True),
    ({"Vin_V": {"unit": "V", "quantity": "Vin_V"}, "Tcase_C": {"unit": "°C", "quantity": "Tcase_C"}}, False),
    ({"Vin_V": {"unit": "V", "quantity": "Vin_V"}, "board": {"unit": "C", "quantity": "board_temperature"}}, False),
    ({}, False),
    (None, False),
])
def test_temperature_absence_is_stated_only_when_bindings_show_no_temperature_channel(model, bindings, expected):
    for point in model["points"]:
        point["phase_label"] = "Increasing demand"
    if bindings is not None:
        model["bench"] = {"measurements": bindings}
    body = renderer._body(model)
    controls = renderer._controls_html(model)
    assert ("temperature was not acquired" in body) is expected
    assert ("Temperatures: not acquired; no temperature channel is bound" in controls) is expected
    assert "temperature probe" not in body


@pytest.mark.parametrize("limit", [2., None])
def test_adaptive_search_limit_sentence_uses_recorded_setting_or_is_omitted(model, limit):
    for point in model["points"]:
        point["phase_label"] = "Increasing demand"
    model["execution"] = {"source_limit_search": {"target_input_current_A": 1.96,
                                                  **({"input_current_limit_A": limit} if limit else {})},
                          "executed_point_ids": ["p1", "p2", "p3"]}
    body = renderer._body(model)
    assert ("limit belongs to the supply feeding the converter" in body) is (limit is not None)
    assert ("The 2 A limit belongs to the supply" in body) is (limit is not None)
    assert "The 1 A limit" not in body


def test_issued_exports_match_model_points_with_unique_unit_headers_and_empty_missing_values(model, tmp_path):
    model["points"][0].update(programmed_input_V=12., input_condition_label='12 V input, "set"',
                              reason="=SUM(A1) offset")
    model["points"][1].update(Vin_V=12.0, Iin_A=1e-05, Pin_W=None)
    model["provenance"] = {"formula_version": "settled-dc-1.1"}
    before = copy.deepcopy(model)
    recorded = renderer.write_exports(model, tmp_path)
    csv_path, meta_path = tmp_path / "exports/points.csv", tmp_path / "exports/points.meta.json"
    assert set(recorded) == {"points.csv", "points.meta.json"}
    for name, path in (("points.csv", csv_path), ("points.meta.json", meta_path)):
        assert recorded[name]["path"] == str(path)
        assert recorded[name]["bytes"] == path.stat().st_size > 0
        assert recorded[name]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    text = csv_path.open(encoding="utf-8", newline="").read()
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    header = text.split("\r\n")[0].split(",")
    assert header == list(renderer.EXPORT_FIELDS) and len(set(header)) == len(header)
    assert {"run_id", "analysis_id", "point_id", "Vin_V", "Iin_A", "Vout_V", "Iout_A", "Pin_W", "Pout_W",
            "loss_W", "efficiency_pct", "vout_error_pct"} <= set(header)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["point_id"] for row in rows] == ["p1", "p2", "p3"]
    assert all(row["run_id"] == "synthetic-run" and row["analysis_id"] == "analysis-1"
               and row["evidence_type"] == "SYNTHETIC" for row in rows)
    assert rows[0]["efficiency_pct"] == "39.1575" and rows[2]["efficiency_pct"] == "81.23456789"
    assert rows[1]["efficiency_pct"] == "" and rows[1]["Pin_W"] == "" and rows[2]["programmed_input_V"] == ""
    assert rows[0]["programmed_input_V"] == "12" and rows[1]["Vin_V"] == "12" and rows[1]["Iin_A"] == "0.00001"
    assert [row["Iout_A"] for row in rows] == ["0.099", "0.2", "0.3"]
    assert rows[0]["input_condition_label"] == '12 V input, "set"'
    assert rows[0]["reason"] == "'=SUM(A1) offset"
    meta = json.loads(meta_path.read_text())
    assert (meta["run_id"], meta["analysis_id"], meta["report_revision"]) == ("synthetic-run", "analysis-1", "r0001")
    assert meta["evidence_type"] == "SYNTHETIC" and meta["dut"] == "Different 5 V DUT"
    assert meta["kind"] == "canonical-issued-export" and "Canonical issued selection" in meta["selection"]
    assert [column["name"] for column in meta["columns"]] == header
    units = {column["name"]: column["unit"] for column in meta["columns"]}
    assert units["efficiency_pct"] == "%" and units["Vin_V"] == "V" and units["point_id"] is None
    assert meta["conditions"]["input_conditions"] == [
        {"vin_target_V": 12, "programmed_input_V": 12., "label": '12 V input, "set"'},
        {"vin_target_V": 12, "programmed_input_V": None, "label": None}]
    assert meta["conditions"]["requested_loads_A"] == [.1, .2, .3]
    assert meta["conditions"]["qualification_counts"] == {"valid": 2, "inconclusive": 1}
    assert meta["figure_ids"] == ["fig-efficiency"] and meta["formula_version"] == "settled-dc-1.1"
    assert meta["csv"]["sha256"] == recorded["points.csv"]["sha256"]
    assert meta["csv"]["missing_values"] == "empty field"
    assert model == before, "Writing exports must not alter the report model"


def test_timing_columns_are_exported_only_when_the_report_has_a_time_axis(model, tmp_path):
    model["figures"].append({**model["figures"][0], "id": "fig-demand-time", "x_key": "elapsed_s"})
    model["points"][0].update(phase_label="Increasing demand", elapsed_start_s=0., elapsed_s=4.5175, elapsed_end_s=9.035)
    renderer.write_exports(model, tmp_path)
    rows = list(csv.DictReader(io.StringIO((tmp_path / "exports/points.csv").open(encoding="utf-8", newline="").read())))
    assert list(rows[0]) == [*renderer.EXPORT_FIELDS, *renderer.EXPORT_TIMING_FIELDS]
    assert (rows[0]["phase_label"], rows[0]["elapsed_s"]) == ("Increasing demand", "4.5175")
    assert (rows[1]["phase_label"], rows[1]["elapsed_s"]) == ("", "")


def test_render_writes_issued_exports_before_documents_and_records_them(model, tmp_path, monkeypatch):
    """Renderer orchestration only; the browser/PDF suite covers real documents."""
    from types import SimpleNamespace
    import plotly.offline
    monkeypatch.setattr(plotly.offline, "get_plotlyjs", lambda: "window.runtimeFixture=true;")
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-test-fixture")

    async def static_fixture(model, directory):
        for spec in model["figures"]:
            for extension in ("svg", "pdf"):
                (directory / (spec["id"] + "." + extension)).write_text("unit-test fixture")
    monkeypatch.setattr(renderer, "_write_static_figures", static_fixture)

    def document_fixture(command, **kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="1.10.18\n", stderr="", returncode=0)
        directory = Path(kwargs["cwd"])
        assert (directory / "exports/points.csv").is_file(), "the issued export precedes the document build"
        (directory / "report.html").write_text("<!doctype html><html><body>"
                                               + (directory / "interactions.html").read_text() + "</body></html>")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)
    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)
    manifest = render_report(model, tmp_path, formats=("html",))
    assert manifest["status"] == "success"
    assert set(manifest["exports"]) == {"points.csv", "points.meta.json"}
    for name, record in manifest["exports"].items():
        path = Path(record["path"])
        assert path.resolve() == (tmp_path / "exports" / name).resolve() and path.is_file()
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert record["bytes"] == path.stat().st_size
    assert json.loads((tmp_path / "build_manifest.json").read_text())["exports"] == manifest["exports"]
    assert 'href="exports/points.csv"' in (tmp_path / "report.qmd").read_text()
    exported = list(csv.DictReader(io.StringIO((tmp_path / "exports/points.csv").open(encoding="utf-8", newline="").read())))
    assert [row["point_id"] for row in exported] == [point["point_id"] for point in model["points"]]


REAL_MODELS = sorted((Path(__file__).resolve().parents[1] / "runs").glob("*/*/reports/*/report_model.json"))


@pytest.mark.skipif(not REAL_MODELS, reason="no local issued report models (runs/ is not versioned)")
@pytest.mark.parametrize("model_path", REAL_MODELS, ids=lambda p: f"{p.parents[2].name}/{p.parent.name}")
def test_issued_real_models_still_render_and_export(model_path, tmp_path):
    """Every locally issued model must keep rendering from its own fields alone."""
    issued = json.loads(model_path.read_text(encoding="utf-8"))
    body = renderer._body(issued)
    assert isinstance(body, str) and issued["run_id"] in body
    exports = renderer.write_exports(issued, tmp_path)
    assert set(exports) == {"points.csv", "points.meta.json"}
    rows = list(csv.DictReader(io.StringIO((tmp_path / "exports/points.csv").open(encoding="utf-8", newline="").read())))
    assert len(rows) == len(issued["points"])
    assert len(rows[0]) == len(set(rows[0])) if rows else True


# --- Brief 9.1: flagged implausible points are drawn as flagged, never as nothing ---

def _flag(point: dict, efficiency: float) -> dict:
    point.update(qualification="inconclusive", quality_flags=["implausible_power_ratio"], efficiency_pct=efficiency,
                 reason="Implausible power ratio: computed efficiency 112.3 % exceeds 100 % (output power 1.191 W > "
                        "input power 1.061 W); readings preserved, point not qualified. Input and output current "
                        "readbacks differ by +11.0 mA.")
    return point


def test_static_plot_draws_flagged_points_open_and_unjoined_and_keeps_them_in_range(model):
    _flag(model["points"][1], 112.3)
    before = copy.deepcopy(model)
    figure = renderer._plot_figure(model, model["figures"][0], 1)
    qualified, flagged = figure.data
    assert list(qualified.y) == [39.1575, None, 81.23456789] and qualified.connectgaps is False
    assert qualified.marker.symbol == "circle" and qualified.showlegend is None  # default: shown
    assert list(flagged.y) == [None, 112.3, None] and list(flagged.x) == [.099, .2, .3]
    assert flagged.mode == "markers" and flagged.marker.symbol == "circle-open"
    assert flagged.marker.line.width == 2 and flagged.marker.color == qualified.marker.color
    assert flagged.showlegend is False and flagged.name.endswith("· flagged, not qualified")
    assert "Not qualified: implausible power ratio" in flagged.hovertemplate
    assert list(flagged.customdata) == ["p1", "p2", "p3"]
    assert "1 flagged point(s) drawn with open markers, not qualified" in figure.layout.annotations[0].text
    assert figure.layout.yaxis.range is None, "autorange spans both traces, so the 112.3 % marker stays visible"
    assert model == before
    # A nominal-voltage figure keeps the flagged reading inside its default range.
    model["dut"]["ratings"] = {"output_voltage_nominal_V": 12.}
    voltage = {**model["figures"][0], "id": "fig-voltage", "y_key": "Vout_V"}
    for point, vout in zip(model["points"], (12.01, 12.45, 11.99)):
        point["Vout_V"] = vout
    model["figures"] = [voltage]
    low, high = renderer._figure_references(model)["fig-voltage"]["y_range"]
    assert low < 11.99 and high > 12.45


def test_static_plot_with_only_flagged_points_names_them_and_states_no_qualified_condition(model):
    for point, efficiency in zip(model["points"], (112.3, 104.4, 101.9)):
        _flag(point, efficiency)
    figure = renderer._plot_figure(model, model["figures"][0], 1)
    assert len(figure.data) == 1
    (flagged,) = figure.data
    assert list(flagged.y) == [112.3, 104.4, 101.9] and flagged.marker.symbol == "circle-open"
    assert flagged.showlegend is True and flagged.name == "12 V · flagged, not qualified"
    footer = figure.layout.annotations[0].text
    assert "no qualified plotted conditions | 3 flagged point(s) drawn with open markers, not qualified" in footer
    assert figure.layout.xaxis.range is None, "three distinct currents keep ordinary autoscaling"


def test_static_plot_without_flags_is_unchanged(model):
    figure = renderer._plot_figure(model, model["figures"][0], 1)
    assert len(figure.data) == 1 and figure.data[0].marker.symbol == "circle"
    assert "flagged" not in figure.layout.annotations[0].text


def test_body_separates_readback_cross_check_and_lists_the_computed_reason(model):
    _flag(model["points"][1], 112.3)
    model["metrics"] += [
        {"id": "load-span-load-12", "label": "Load regulation span", "value": .1, "unit": "% of nominal",
         "conditions": "12 V requested input", "point_ids": ["p1", "p3"], "figure_ids": ["fig-efficiency"]},
        {"id": "readback-cross-check-current-difference-mean",
         "label": "Readback cross-check (pass-through, not calibration): mean current readback difference",
         "value": .011, "unit": "A", "conditions": "3 loaded points (p1, p2, p3); 12 V requested input",
         "point_ids": ["p1", "p2", "p3"], "figure_ids": []}]
    body = renderer._body(model)
    section = body.index("### Readback cross-check (pass-through, not calibration)")
    assert "not a calibration, their uncertainty is unquantified, and no stored value is corrected" in body[section:]
    # The heading carries the long label once; rows keep only the quantity.
    assert "| mean current readback difference | 0.011 A | 3 loaded points (p1, p2, p3); 12 V requested input |" in body[section:]
    regulation = body[body.index("## Regulation"):section]
    assert "Load regulation span" in regulation and "Readback cross-check" not in regulation
    assert "| p2 | load | 12 V / 0.2 A | inconclusive | Implausible power ratio: computed efficiency 112.3 % exceeds 100 %" in body
    assert "insufficient input-voltage and load coverage" not in body


def test_body_without_cross_check_metrics_has_no_cross_check_section(model):
    body = renderer._body(model)
    assert "Readback cross-check" not in body
    assert "insufficient input-voltage and load coverage" in body


def test_issued_export_carries_quality_flags_next_to_qualification(model, tmp_path):
    _flag(model["points"][1], 112.3)
    model["points"][2]["quality_flags"] = []
    renderer.write_exports(model, tmp_path)
    text = (tmp_path / "exports/points.csv").open(encoding="utf-8", newline="").read()
    header = text.split("\r\n")[0].split(",")
    assert header.index("quality_flags") == header.index("qualification") + 1
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["quality_flags"] for row in rows] == ["", "implausible_power_ratio", ""]
    assert rows[1]["qualification"] == "inconclusive" and rows[1]["reason"].startswith("Implausible power ratio")
    meta = json.loads((tmp_path / "exports/points.meta.json").read_text())
    column = next(column for column in meta["columns"] if column["name"] == "quality_flags")
    assert "implausible_power_ratio" in column["description"] and column["unit"] is None


# --- Page-1 identity in plain language, and the print theme's identity strings ---

@contextlib.contextmanager
def _local_zone(name):
    """Pin the bench computer's zone so ``datetime.astimezone()`` is reproducible."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _measured_bench(model):
    """A measured pass-through model as the services build it: profile bench, reported identities, run span."""
    model["title"] = "DC–DC converter characterization · Different 5 V DUT"
    model["dut"] = {"identity": {"model": "Different 5 V DUT", "sample_id": "sample-1"}}
    model["evidence_label"], model["report_revision"] = "MEASURED", "r0003"
    model["boundary"] = "source-to-load-terminal path (input and output wiring included)"
    model["bench"] = {"bench_id": "rigol-local-passthrough-12v",
                      "source": {"instrument_id": "source", "channel": 1, "physical_model": None, "reported_identity": None},
                      "load": {"instrument_id": "load", "physical_model": None, "reported_identity": None},
                      "measurements": {"Vin_V": {"instrument_id": "source", "quantity": "Vin_V", "unit": "V", "location": "source_terminals"},
                                       "Iin_A": {"instrument_id": "source", "quantity": "Iin_A", "unit": "A", "location": "source_output"},
                                       "Vout_V": {"instrument_id": "load", "quantity": "Vout_V", "unit": "V", "location": "load_input_terminals_local_sense"},
                                       "Iout_A": {"instrument_id": "load", "quantity": "Iout_A", "unit": "A", "location": "load_input"}}}
    model["provenance"] = {"formula_version": "settled-dc-1.3", "instrument_identities": {
        "source": {"model": "DP821A", "serial": "S1", "firmware": "1", "manufacturer": "RIGOL"},
        "load": {"model": "DL3031A", "serial": "S2", "firmware": "2", "manufacturer": "RIGOL"}}}
    model["execution"] = {"status": "completed", "created_utc": "2026-09-29T20:37:15.209079+00:00",
                          "finished_utc": "2026-09-29T20:38:24.124378+00:00"}
    return model


def test_page_one_about_table_reads_in_plain_words_with_identifiers_last(model):
    """The reader learns what was tested, with what, where and when before any identifier (brief §12.3, §8.2)."""
    with _local_zone("America/Los_Angeles"):
        body = renderer._body(_measured_bench(model))
    assert body.startswith("::: {.report-table .table-about}")
    assert body.index("About this report") < body.index("## Summary {#summary}")
    rows = ["| About this report |  |",
            "| Device tested | Different 5 V DUT — Sample: sample-1 |",
            "| Equipment | DP821A CH1 (supply), DL3031A (load); bench profile rigol-local-passthrough-12v |",
            "| Measurement points | Input measured at the supply terminals, output at the load terminals; "
            "wiring losses are included in the path. |",
            "| Recorded | Sep 29, 2026, 13:37–13:38 PDT (bench-computer local time; evidence files record UTC) |",
            "| Evidence | Measured — readings were acquired from the connected instruments during this run. |",
            "| Traceability | Run ID synthetic-run; analysis analysis-1; method version settled-dc-1.3; "
            "report revision r0003 — these match this document to its raw data files. |"]
    positions = [body.index(row) for row in rows]
    assert positions == sorted(positions), "rows keep their order; identifiers close the table"
    # Plain labels replace the jargon in the body; the computed content is unchanged.
    assert ("**MEASURED — Input measured at the supply terminals, output at the load terminals; "
            "wiring losses are included in the path.**") in body
    assert "## Device tested {#dut}" in body
    assert "**Equipment profile:** rigol-local-passthrough-12v" in body
    assert ("**Measurement points:** Input measured at the supply terminals, output at the load terminals; wiring losses "
            "are included in the path. Declared path: source-to-load-terminal path (input and output wiring included).") in body
    assert "**Traceability:** Run ID synthetic-run; analysis analysis-1; method version settled-dc-1.3; report revision r0003" in body
    for jargon in ("**bench id:**", "**Run:** ", "**Analysis:** ", "## Device under test", "Boundary:"):
        assert jargon not in body
    assert body.count("these match this document to its raw data files") == 2, "page 1 and the appendix"


def test_measurement_points_follow_the_recorded_bindings_and_declared_path(model):
    """The sentence is derived from the bindings and the path text, never fixed for one recipe."""
    dut_output = {"boundary": "source-to-DUT-output path", "bench": {"measurements": {
        "Vin_V": {"location": "source_terminals"}, "Iin_A": {"location": "source_output"},
        "Vout_V": {"location": "dut_output_sense"}, "Iout_A": {"location": "dut_output"}}}}
    assert renderer._measurement_points(dut_output) == (
        "Input measured at the supply terminals, output at the DUT output terminals through the remote-sense leads; "
        "input wiring losses are included in the path, output wiring is not.")
    bare = {"boundary": "source-to-DUT-output path", "bench": {"measurements": {
        "Vin_V": {"location": "source_terminals"}, "Vout_V": {"location": "dut_output"}}}}
    assert renderer._measurement_points(bare) == (
        "Input measured at the supply terminals, output at the DUT output terminals; "
        "input wiring losses are included in the path, output wiring is not.")
    unknown_vocabulary = {"boundary": "custom fixture", "bench": {"measurements": {
        "Vin_V": {"location": "jig_input"}, "Vout_V": {"location": "jig_output"}}}}
    assert renderer._measurement_points(unknown_vocabulary) == "Input measured at jig input, output at jig output."
    assert renderer._measurement_points(model) == "Measured across the declared path: source-to-DUT-output path."
    assert renderer._measurement_points({"bench": {}}) == "Measurement points not recorded in this report model."


def test_equipment_and_recorded_lines_never_invent_a_model_or_a_time(model):
    """Without reported identities the profile's own words are used; without run times, a plain notice."""
    assert renderer._equipment_text(model) == "Equipment not recorded in this report model"
    mock = {"bench": {"bench_id": "mock", "source": {"channel": 1, "reported_identity": "SYNTHETIC source with CH1 envelope"},
                      "load": {"reported_identity": None, "physical_model": None}}}
    assert renderer._equipment_text(mock) == ("SYNTHETIC source with CH1 envelope (supply), "
                                              "load instrument (model not reported) (load); bench profile mock")
    assert renderer._recorded(model) == ("", "Run time not recorded in this report model")
    with _local_zone("America/Los_Angeles"):
        spanning = {"execution": {"created_utc": "2026-09-29T23:37:15+00:00", "finished_utc": "2026-09-30T07:38:24Z"}}
        assert renderer._recorded(spanning) == ("Sep 29, 2026, 16:37 PDT",
            "Sep 29, 2026, 16:37 PDT to Sep 30, 2026, 00:38 PDT (bench-computer local time; evidence files record UTC)")
        start_only = {"execution": {"created_utc": "2026-09-29T20:37:15.209079+00:00"}}
        assert renderer._recorded(start_only)[1] == "Sep 29, 2026, 13:37 PDT (bench-computer local time; evidence files record UTC)"
    identity = renderer._report_identity(model)
    assert identity == {"title": "DC–DC converter characterization", "dut": "Different 5 V DUT", "evidence": "SYNTHETIC",
                        "recorded": "", "subtitle": "SYNTHETIC evidence", "run": "synthetic-run", "revision": "r0001",
                        "analysis": "analysis-1"}
    with _local_zone("America/Los_Angeles"):
        measured = renderer._report_identity(_measured_bench(model))
    assert measured["title"] == "DC–DC converter characterization"
    assert measured["recorded"] == "Sep 29, 2026, 13:37 PDT"
    assert measured["subtitle"] == "MEASURED evidence · Recorded Sep 29, 2026, 13:37 PDT"
    assert renderer._typst_string('x" + sys.inputs.at("y") + "\\ line\nbreak') == '"x\\" + sys.inputs.at(\\"y\\") + \\"\\\\ line break"'


def test_paper_selection_reaches_the_typst_template_partial_and_manifest(model, tmp_path, monkeypatch):
    """Letter by default, A4 on request, nothing else; the partial and identity include travel with the document."""
    from types import SimpleNamespace
    import plotly.offline
    monkeypatch.setattr(plotly.offline, "get_plotlyjs", lambda: "window.runtimeFixture=true;")
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-test-fixture")

    async def static_fixture(model, directory):
        for spec in model["figures"]:
            for extension in ("svg", "pdf"):
                (directory / (spec["id"] + "." + extension)).write_text("unit-test fixture")
    monkeypatch.setattr(renderer, "_write_static_figures", static_fixture)

    def document_fixture(command, **kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="1.10.18\n", stderr="", returncode=0)
        directory = Path(kwargs["cwd"])
        (directory / "report.html").write_text("<!doctype html><html><body>"
                                               + (directory / "interactions.html").read_text() + "</body></html>")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)

    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)

    manifest = render_report(model, tmp_path / "letter", formats=("html",))
    qmd = (tmp_path / "letter/report.qmd").read_text()
    assert "papersize: us-letter" in qmd and "template-partials:\n      - typst-show.typ" in qmd
    assert 'subtitle: "SYNTHETIC evidence"' in qmd and "number-sections: true" in qmd
    header = (tmp_path / "letter/print-header.typ").read_text()
    assert header.startswith("#let dcdc-id = (\n") and 'paper: "us-letter",' in header and 'run: "synthetic-run",' in header
    assert (tmp_path / "letter/typst-show.typ").read_text() == (renderer.TEMPLATES / "theme/typst-show.typ").read_text()
    assert manifest["paper"] == "letter"
    assert {"print-theme.typ", "typst-show.typ", "print-tables.typ"} <= set(manifest["render_sources_sha256"])
    metadata = (tmp_path / "letter/metadata.html").read_text()
    assert '<script id="dcdc-report-head">' in metadata
    assert (renderer.TEMPLATES / "web/report-head.js").read_text() in metadata
    manifest = render_report(model, tmp_path / "a4", formats=("html",), paper="a4")
    assert manifest["paper"] == "a4"
    assert "papersize: a4" in (tmp_path / "a4/report.qmd").read_text()
    assert 'paper: "a4",' in (tmp_path / "a4/print-header.typ").read_text()
    with pytest.raises(ValueError, match="letter or a4"):
        render_report(model, tmp_path / "legal", formats=("html",), paper="legal")
    assert not (tmp_path / "legal").exists()


def test_figure_footer_wraps_a_long_measurement_boundary_onto_its_own_line():
    """PDF-02 on CI: a long boundary description made the exported figure's footer run past the page edge."""
    figure = {"id": "fig-efficiency"}
    base = {"evidence_label": "SYNTHETIC", "run_id": "run-1", "analysis_id": "a-1", "dut": {"model": "X"}}
    short = renderer._footer({**base, "boundary": "source-to-DUT-output path"}, figure)
    long = renderer._footer({**base, "boundary": "source-to-load-terminal path (input and output wiring included; load in local sense)"}, figure)
    assert short.count("<br>") == 2 and "path | Aggregated settled DC points" in short
    assert long.count("<br>") == 3 and "load in local sense)<br>Aggregated settled DC points" in long
    assert all(len(line) <= renderer.FOOTER_LINE_CHARS for line in long.split("<br>")[2:])


def test_generic_wording_follows_the_evidence_label(model):
    """Codex review item 4: the axis options, hover modes, table headers and method sentences never call a
    SYNTHETIC run's values "Measured"; a MEASURED run keeps the measured wording. Captions and numbers that
    come from the model are left exactly as supplied."""
    model["points"].append({"point_id": "p0", "test_id": "load", "vin_target_V": 12, "iout_target_A": 0, "Iout_A": 0.,
                            "Iin_A": .01, "Pin_W": .12, "Vout_V": 5., "efficiency_pct": None, "qualification": "valid"})
    model["method"] = {"declared_acquisition": {"duration_s": 3, "target_poll_interval_s": .5, "minimum_complete_cycles": 2,
                                                "maximum_interchannel_skew_s": .05},
                       "declared_settling": {"minimum_dwell_s": 2, "window_s": 3, "minimum_fresh_samples": 5,
                                             "maximum_vout_span_V": .01, "timeout_s": 20},
                       "achieved_points": [], "clock_mode": "monotonic"}
    model["execution"] = {"voltage_efficiency_sweep": {"prior_input_attempt": {
        "run_id": "earlier-aborted-run", "last_startup_cycle": {"Vin_V": 7.125, "Iin_A": .9991, "Vout_V": .1, "Iout_A": .02}}},
        "voltage_comparison": [{"label": "earlier input", "qualified_points": 0, "phase_status": "previous-attempt-unqualified"}]}
    synthetic_body, synthetic_controls = renderer._body(model), renderer._controls_html(model)
    assert "Simulated values are aggregated settled DC point results." in synthetic_body
    assert "| Requested input (V) | Simulated input current (A) | Input power (W) | Output voltage (V) |" in synthetic_body
    assert "3 s window with 5 queried synthetic readings;" in synthetic_body
    assert "These synthetic readings belong to the last recorded startup cycle" in synthetic_body
    assert "Measured values are" not in synthetic_body and "Measured input current" not in synthetic_body
    assert "Measured input conditions: 12 V." in synthetic_body, "the model's own caption is not rewritten"
    for option in ('<option value="Iout_A">Simulated output current (A)</option>', '<option value="Pout_W">Simulated output power (W)</option>',
                   '<option value="Vin_V">Simulated input voltage (V)</option>', '<option value="closest">Nearest simulated point</option>',
                   '<option value="x unified">Values at simulated x</option>'):
        assert option in synthetic_controls, option
    assert "Measured" not in synthetic_controls and "measured" not in synthetic_controls
    measured = _measured_bench(copy.deepcopy(model))
    measured["execution"].update(copy.deepcopy(model["execution"]))  # the helper replaces execution; keep the startup attempt
    measured_body, measured_controls = renderer._body(measured), renderer._controls_html(measured)
    assert "Measured values are aggregated settled DC point results." in measured_body
    assert "| Requested input (V) | Measured input current (A) | Input power (W) | Output voltage (V) |" in measured_body
    assert "3 s window with 5 queried readings;" in measured_body
    assert "These readings belong to the last recorded startup cycle" in measured_body
    for option in ('<option value="Iout_A">Measured output current (A)</option>', '<option value="closest">Nearest measured point</option>',
                   '<option value="x unified">Values at measured x</option>'):
        assert option in measured_controls, option
    assert "Simulated" not in measured_controls and "simulated" not in measured_controls


def test_dut_section_is_one_pdf_block_so_its_documentation_note_stays_with_its_tables(model):
    """Codex review item 8: in a rendered ISO subset the DUT documentation note opened page 2 alone, away from its
    table. The Device tested tables and the note are now one unbreakable Typst block, the pattern already used for
    the acquisition outcome, so the note travels with its tables (and the sticky heading with the block)."""
    model["dut"]["ratings"] = {"input_voltage_min_V": 9, "input_voltage_max_V": 36, "output_voltage_nominal_V": 12,
                               "output_current_rated_A": 4, "output_power_rated_W": 48, "origin": "datasheet",
                               "verified_from_sample_label": True}
    body = renderer._body(model, sensor_placement_present=True)
    start = body.index("## Device tested {#dut}")
    section = body[start:body.index("\n## ", start + 1)]
    open_block, close_block = "```{=typst}\n#block(breakable: false)[\n```", "```{=typst}\n]\n```"
    assert section.count(open_block) == 1 and section.count(close_block) == 1
    order = [section.index(text) for text in (open_block, "| Identity | Recorded value |", "| Rating / evidence | Recorded value |",
                                              "[Sensor placement section](#sensor-placement)",
                                              "No internal topology or component identity is inferred.", close_block)]
    assert order == sorted(order), "heading, open, both tables, the note, close"
    assert section.index("#pagebreak()") > section.index(close_block), "the section's own page break follows the block"
    without_ratings = renderer._body({**model, "dut": {"model": "Different 5 V DUT"}})
    start = without_ratings.index("## Device tested {#dut}")
    section = without_ratings[start:without_ratings.index("\n## ", start + 1)]
    assert section.count(open_block) == 1 and section.count(close_block) == 1 and "Rating / evidence" not in section
    assert body.count(open_block) == 2, "the DUT block and the acquisition-outcome block"


# --- Best-effort ISO 16750-2 runs: the deviation sheet (docs/standards/best-effort-proposal.md §2.3) -------------
BEST_EFFORT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "best_effort_sheet_4_6_1_1_A.json"
DEVIATION_HEADER = "| Parameter | Clause asks | This bench | Mechanism | Measured by | Classification | Note |"


def _with_deviation_sheet(model, entries=None):
    """The model as analysis.build_report_model issues it for a best-effort run: sheet, sentence, statement, bullets."""
    from dcdc_bench.analysis import best_effort_limitations, build_best_effort_sheet
    recorded = json.loads(BEST_EFFORT_FIXTURE.read_text(encoding="utf-8"))
    if entries is not None:
        recorded["deviations"] = entries
    sheet = build_best_effort_sheet(recorded)
    model["best_effort"] = sheet
    model["summary"] = [sheet["summary_sentence"], sheet["statement"]]
    model["limitations"] = best_effort_limitations(sheet)
    return model


def test_deviation_sheet_follows_the_results_as_a_seven_column_table_with_numbered_notes_legend_and_statement(model):
    from dcdc_bench.analysis import BEST_EFFORT_STATEMENT
    body = renderer._body(_with_deviation_sheet(model))
    heading = "### Deviations from ISO 16750-2 clause 4.6.1.1, variant A {#deviations}"
    start = body.index(heading)
    raw_evidence = body.index('<section class="raw-evidence"')
    assert body.index("### Path efficiency") < start < raw_evidence < body.index("## Regulation"), "under the test's results"
    section = body[start:raw_evidence]
    assert "::: {.report-table .table-deviations}" in section and 'tbl-colwidths="[12,15,29,12,12,14,6]"' in section
    assert DEVIATION_HEADER in section
    rows = [line for line in section.splitlines() if line.startswith("| ") and line not in (DEVIATION_HEADER,) and "---" not in line]
    assert len(rows) == 5
    assert rows[1].startswith("| drop duration (s) | 100 ± 5 ms (ISO) | commanded 100 ms; host-timed 103 ms; bounded 0–270 ms (derived) | "
                              "LAN voltage step | host clock (write timestamps) | unknown until measured | ")
    note_number = rows[1].rstrip("| ").rsplit("| ", 1)[-1].strip()
    assert note_number.isdigit(), "the last column numbers the row's note instead of carrying its text"
    assert (f"{note_number}. drop duration (s): Two LAN writes, each 4–55 ms transport (LAN) and up to 118 ms processing (DS5); "
            "interval between the two write timestamps on the Pi.") in section, "the note follows the table in the numbered list"
    assert rows[2].startswith("| edge max (s) | at most 10 ms (ISO) | \\< 110 ms loaded (DS5); not measured at the converter | supply slew |")
    assert ("Basis tags: ISO = ISO 16750-2 clause text or figure; DS5 = supply datasheet bound; derived = derived from the tagged "
            "bounds; SEED = seeded bench profile or protective policy." in section)
    assert "Observed output states come from about 1 s polling; states shorter than the poll interval are not visible to this bench." in section
    assert "Recorded by the procedure: Variant A commanded over LAN; nothing at the converter terminals is measured." in section
    assert f"**{BEST_EFFORT_STATEMENT}**" in section
    open_block = "```{=typst}\n#block(breakable: false)[\n```"
    assert open_block not in section, "the sheet is left to the theme's measured pagination rule, never forced into one block"
    order = [section.index(text) for text in (heading, DEVIATION_HEADER, "Notes, numbered in the table's last column:", "Basis tags:",
                                              "Observed output states", "Recorded by the procedure", f"**{BEST_EFFORT_STATEMENT}**")]
    assert order == sorted(order), "heading, table, notes, legend, poll note, procedure statement, statement"
    assert body.count(open_block) == 2, "the DUT block and the acquisition-outcome block only"
    lowered = section.lower()
    for forbidden in ("achieved", " pass", "fail", "compliant"):
        assert forbidden not in lowered, forbidden
    summary = body[body.index("## Summary"):body.index("## Device tested")]
    assert renderer._md(model["best_effort"]["summary_sentence"]) in summary and BEST_EFFORT_STATEMENT in summary
    appendix = body[body.index("## Appendix: qualification and provenance"):]
    assert "- " + renderer._md(model["limitations"][0]) in appendix and f"- {BEST_EFFORT_STATEMENT}" in appendix
    assert '· <a href="exports/deviations.json">deviation sheet JSON</a> ' in body


def test_long_deviation_sheet_is_left_to_the_table_pagination_rule(model):
    recorded = json.loads(BEST_EFFORT_FIXTURE.read_text(encoding="utf-8"))["deviations"]
    entries = [{**copy.deepcopy(recorded[index % len(recorded)]), "parameter": f"parameter_{index}_s"} for index in range(9)]
    body = renderer._body(_with_deviation_sheet(model, entries))
    start = body.index("### Deviations from ISO 16750-2 clause 4.6.1.1, variant A {#deviations}")
    section = body[start:body.index('<section class="raw-evidence"')]
    assert section.count("```{=typst}\n#block(breakable: false)[\n```") == 0 and DEVIATION_HEADER in section
    assert sum(1 for line in section.splitlines() if line.startswith("| parameter ")) == 9
    assert body.count("```{=typst}\n#block(breakable: false)[\n```") == 2


def test_model_without_a_deviation_sheet_renders_no_sheet_section_or_export_link(model):
    body = renderer._body(model)
    assert "Deviations from" not in body and "{#deviations}" not in body and "deviations.json" not in body
    assert "No clause-compliance result is claimed" not in body
    assert validate_report_model({**model, "best_effort": None}) is not None


@pytest.mark.parametrize("sheet, message", [
    ("4.6.1.1", "must record a clause"),
    ({"clause": "4.6.1.1", "deviations": {"parameter": "edge_max_s"}}, "must record a clause and a list"),
    ({"clause": "4.6.1.1", "deviations": [{"classification": "met"}]}, "must name its parameter"),
    ({"clause": "4.6.1.1", "deviations": [{"parameter": "edge_max_s", "classification": "pass"}]}, "unknown classification"),
])
def test_validation_accepts_a_recorded_sheet_and_refuses_a_malformed_one(model, sheet, message):
    assert validate_report_model(_with_deviation_sheet(copy.deepcopy(model)))["best_effort"]["clause"] == "4.6.1.1"
    with pytest.raises(ValueError, match=message):
        validate_report_model({**model, "best_effort": sheet})


def test_deviation_sheet_export_holds_the_recorded_entries_sentence_statement_counts_and_legend(model, tmp_path):
    from dcdc_bench.analysis import BEST_EFFORT_STATEMENT
    issued = _with_deviation_sheet(model)
    before = copy.deepcopy(issued)
    recorded = renderer.write_exports(issued, tmp_path)
    assert set(recorded) == {"points.csv", "points.meta.json", "deviations.json"}
    path = tmp_path / "exports/deviations.json"
    assert recorded["deviations.json"] == {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                           "bytes": path.stat().st_size}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0" and payload["kind"] == "best-effort-deviation-sheet"
    assert (payload["run_id"], payload["analysis_id"], payload["report_revision"], payload["evidence_type"], payload["dut"]) == (
        "synthetic-run", "analysis-1", "r0001", "SYNTHETIC", "Different 5 V DUT")
    assert (payload["standard"], payload["clause"], payload["variant"], payload["test_type"]) == ("ISO 16750-2", "4.6.1.1", "A", "momentary_drop")
    assert payload["summary_sentence"] == issued["best_effort"]["summary_sentence"]
    assert payload["statement"] == BEST_EFFORT_STATEMENT
    assert payload["procedure_statement"] == "Variant A commanded over LAN; nothing at the converter terminals is measured."
    assert payload["classification_counts"] == {"met": 1, "approximated": 1, "not_met_but_documented": 1, "unknown_until_measured": 2}
    assert payload["bases"] == issued["best_effort"]["bases"]
    assert [column["name"] for column in payload["columns"]] == ["parameter", "clause_asks", "this_bench", "mechanism",
                                                                  "measured_by", "classification", "note"]
    assert [column["header"] for column in payload["columns"]] == ["Parameter", "Clause asks", "This bench", "Mechanism",
                                                                    "Measured by", "Classification", "Note"]
    assert payload["deviations"] == issued["best_effort"]["deviations"]
    assert payload["deviations"][1]["achieved"] == {"value": .103, "measured_by": "host_clock",
                                                    "note": "interval between the two write timestamps on the Pi"}
    assert issued == before, "Writing exports must not alter the report model"


def test_render_lists_the_deviation_sheet_export_in_the_manifest_and_links_it(model, tmp_path, monkeypatch):
    """Renderer orchestration only, as for the point exports; the browser/PDF suite covers real documents."""
    from types import SimpleNamespace
    import plotly.offline
    monkeypatch.setattr(plotly.offline, "get_plotlyjs", lambda: "window.runtimeFixture=true;")
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-test-fixture")

    async def static_fixture(model, directory):
        for spec in model["figures"]:
            for extension in ("svg", "pdf"):
                (directory / (spec["id"] + "." + extension)).write_text("unit-test fixture")
    monkeypatch.setattr(renderer, "_write_static_figures", static_fixture)

    def document_fixture(command, **kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="1.10.18\n", stderr="", returncode=0)
        directory = Path(kwargs["cwd"])
        assert (directory / "exports/deviations.json").is_file(), "the sheet export precedes the document build"
        (directory / "report.html").write_text("<!doctype html><html><body>"
                                               + (directory / "interactions.html").read_text() + "</body></html>")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)

    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)
    manifest = render_report(_with_deviation_sheet(model), tmp_path, formats=("html",))
    assert manifest["status"] == "success"
    assert set(manifest["exports"]) == {"points.csv", "points.meta.json", "deviations.json"}
    record = manifest["exports"]["deviations.json"]
    assert Path(record["path"]).resolve() == (tmp_path / "exports/deviations.json").resolve()
    assert record["sha256"] == hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest()
    assert json.loads((tmp_path / "build_manifest.json").read_text())["exports"] == manifest["exports"]
    source = (tmp_path / "report.qmd").read_text()
    assert 'href="exports/deviations.json"' in source and "{#deviations}" in source
    assert json.loads((tmp_path / "report_model.json").read_text())["best_effort"]["clause"] == "4.6.1.1"
