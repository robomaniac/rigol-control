"""Rendering validates references, preserves analysis, and reports failures honestly."""
import copy
import json
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
    model["execution"] = {
        "voltage_efficiency_sweep": {"input_current_limit_A": 1.},
        "executed_point_ids": ["p1", "p2", "p3"],
        "voltage_comparison": [
            {"label": "12 V input", "reference_measured_input_V": 12.00234,
             "reference_efficiency_pct": 83.45678, "highest_load_A": .797123,
             "peak_efficiency_pct": 84.67891, "peak_efficiency_current_A": .69932,
             "qualified_points": 7, "phase_status": "completed", "stop_reason": "source headroom boundary"},
            {"label": "36 V nominal (35.8 V set)", "nominal_input_V": 36.,
             "qualified_points": 0, "phase_status": "not-run", "stop_reason": "earlier phase fault"},
        ]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "| 12 V input | 12.002 V | 83.46 % | 0.797 A | 84.68 % at 0.70 A |" in body
    assert "| 36 V nominal (35.8 V set) | not available | not available | not available | not available |" in body
    assert "same 0.5 A requested output load" in body
    assert "Highest qualified load" in body and "Highest tested load" not in body
    assert "See @fig-efficiency." in body
    assert "Both outputs are switched OFF before changing" in body
    assert "not an exact 36.000 V endpoint test" in body
    assert "not fully verified by these three conditions" in body
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
        "voltage_comparison": [{"label": "12 V input", "qualified_points": 0,
                                "phase_status": "previous-attempt-unqualified"}]}
    before = copy.deepcopy(model)
    body = renderer._body(model)
    assert "It therefore has no efficiency curve" in body
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
