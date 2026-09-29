"""Small shipped-JavaScript fixtures; no browser, instruments or report build."""
import csv
import io
import json
from pathlib import Path
import subprocess

import pytest

from dcdc_bench.reporting.renderer import TEMPLATES


def _node() -> Path:
    playwright = pytest.importorskip("playwright")
    node = Path(playwright.__file__).parent / "driver/node"
    if not node.is_file():
        pytest.skip("Playwright's bundled Node runtime is unavailable")
    return node


def _run_node(harness: str, payload: dict) -> dict:
    result = subprocess.run([str(_node()), "-e", harness], input=json.dumps(payload),
                            capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


# Slices of the shipped script, taken between stable function boundaries, run
# against a minimal document/Plotly stand-in. A moved boundary fails loudly.
SLICE_SUPPORT = r"""
const slice = (from, to) => {
  const start = script.indexOf(from), end = script.indexOf(to, start);
  if (start < 0 || end < 0) throw new Error('shipped script no longer contains ' + JSON.stringify([from, to]));
  return script.slice(start, end);
};
const helpers = ['clone', 'safe', 'keyOf', 'finite', 'number'].map(name =>
  script.match(new RegExp('^  const ' + name + ' = .*;$', 'm'))[0]).join('\n');
"""


def _current_fixture() -> dict:
    """An input-current figure with a no-load point and a load-off offset reading."""
    common = {"test_id": "load", "vin_target_V": 24., "Vin_V": 24.01, "Vout_V": 12.1, "qualification": "valid"}
    points = [
        {**common, "point_id": "no-load", "iout_target_A": 0., "Iout_A": 0., "Iin_A": .0123, "efficiency_pct": None,
         "reason": "not applicable: enabled with no external load"},
        {**common, "point_id": "load-off-offset", "iout_target_A": 0., "Iout_A": -.0004, "Iin_A": .0125,
         "efficiency_pct": None},
        {**common, "point_id": "light", "iout_target_A": .1, "Iout_A": .099249, "Iin_A": .069075,
         "efficiency_pct": 72.64106172694521},
        {**common, "point_id": "half", "iout_target_A": .5, "Iout_A": .499, "Iin_A": .2915, "efficiency_pct": 86.2},
    ]
    return {"run_id": "run", "analysis_id": "analysis", "report_revision": "r0001", "evidence_label": "MEASURED",
            "boundary": "source-to-load path", "dut": {"model": "DUT"}, "points": points,
            "figures": [{"id": "fig-source-current", "title": "Input Current", "x_key": "Iout_A", "y_key": "Iin_A",
                         "x_label": "Output Current (A)", "y_label": "Input Current (A)", "caption": "fixture",
                         "series": [{"id": "load-v0", "label": "24 V input", "vin_target_V": 24.,
                                     "point_ids": [point["point_id"] for point in points]}]}],
            "metrics": [], "raw_samples": {}, "summary": []}


def test_nominal_input_label_and_programmed_voltage_survive_hover_and_csv():
    node = _node()
    script = (TEMPLATES / "web/report.js").read_text()
    # Exercise the actual formatting/export functions without constructing a
    # DOM or plotting synthetic browser traces. The browser suite checks UI.
    harness = r"""
const {script, rows} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const helpers = ['safe', 'finite', 'number'].map(name =>
  script.match(new RegExp('^  const ' + name + ' = .*;$', 'm'))[0]).join('\n');
const hover = script.slice(script.indexOf('  const hoverLabels'), script.indexOf('  function stageTransitions'));
const csv = script.slice(script.indexOf('  const csvFields'), script.indexOf('  function download'));
const execute = new Function('rows', helpers + `
  const model = {run_id:'run',analysis_id:'analysis',evidence_label:'MEASURED'};
  const spec = {id:'fig-efficiency',x_key:'Iout_A',y_key:'efficiency_pct'};
  const specs = [spec], state = {}, identity = 'DUT';
  const xKey = spec => spec.x_key;
  const clone = value => JSON.parse(JSON.stringify(value));
  const getSelectedPoints = () => rows;
` + hover + csv + `return {hover: rows.map(row => hoverText(spec, row)), csv:exportCSV().csv};`);
process.stdout.write(JSON.stringify(execute(rows)));
"""
    rows = [
        {"point_id": "nominal", "vin_target_V": 36., "programmed_input_V": 35.8,
         "input_condition_label": "36 V nominal (35.8 V set)", "Iout_A": .499923,
         "efficiency_pct": 84.12345678},
        {"point_id": "escaped", "vin_target_V": 24., "programmed_input_V": 24.,
         "input_condition_label": '<img src=x>, "reported label"', "Iout_A": .1,
         "efficiency_pct": 80.},
        {"point_id": "legacy", "vin_target_V": 24., "Iout_A": .2, "efficiency_pct": 81.},
    ]
    result = subprocess.run([str(node), "-e", harness], input=json.dumps({"script": script, "rows": rows}),
                            capture_output=True, text=True, check=True, timeout=30)
    observed = json.loads(result.stdout)
    assert observed["hover"][0].startswith("<b>36 V nominal (35.8 V set)</b>")
    assert observed["hover"][0].count("<br>") == 2
    assert "&lt;img src=x&gt;" in observed["hover"][1] and "<img" not in observed["hover"][1]
    assert observed["hover"][2].startswith("<b>Measured · 24 V</b>")
    exported = list(csv.DictReader(io.StringIO(observed["csv"])))
    assert exported[0]["programmed_input_V"] == "35.8"
    assert exported[0]["input_condition_label"] == rows[0]["input_condition_label"]
    assert exported[0]["efficiency_pct"] == "84.12345678"
    assert exported[1]["input_condition_label"] == rows[1]["input_condition_label"]
    assert exported[2]["programmed_input_V"] == exported[2]["input_condition_label"] == ""


def test_log_current_view_omits_nonpositive_points_without_substituting_values():
    """WEB-08: log-current mode excludes nonpositive x points from the drawn view only.

    The shipped draw path runs against a stand-in document and Plotly; the
    zero and negative points must stay in the point list and CSV export, and
    no value may be replaced by a small positive number.
    """
    script = (TEMPLATES / "web/report.js").read_text()
    harness = r"""
const {script, model} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
""" + SLICE_SUPPORT + r"""
const shipped = [
  slice('  const quantityLabels', '  const hoverLabels'),          // xKey, isLog, plottedValue, conditionRows
  slice('  const hoverLabels', '  function stageTransitions'),     // hover text used by traces()
  slice('  function stageTransitions', '  function syncControls'), // stageTransitions, traces, layout
  slice('  function draw()', '  function setView'),                // status text and Plotly.react call
  slice('  function setView', '  function resetZoom'),             // zoom bounds validation and log-range policy
  slice('  function bounds(spec)', '  function download'),         // bounds, getSelectedPoints, CSV export
].join('\n');
const picker = slice("    const picker=document.getElementById('point-picker');", '    picker.addEventListener');
const execute = new Function('model', "'use strict';\n" + helpers + `
  const payload = {model, colors: ['#0072B2'], figure_references: {}};
  const specs = model.figures;
  const points = new Map(model.points.map(p => [p.point_id, p]));
  const graphs = new Map(), conditions = new Map(), identity = 'DUT';
  specs.forEach(spec => spec.series.forEach(series => { const key = keyOf(series);
    if (!conditions.has(key)) conditions.set(key, {label: series.label, color: '#0072B2', dash: 'solid', symbol: 'circle'}); }));
  let state = {selected_series: [...conditions.keys()], metric: 'all', x_key: 'default', log_current: false,
    hovermode: 'closest', ranges: {}};
  let updating = false, pending = Promise.resolve();
  const elements = new Map();
  const document = {
    getElementById: id => { if (!elements.has(id)) elements.set(id, {id, textContent: '', style: {}, hidden: false,
      children: [], append(...items) { this.children.push(...items); }}); return elements.get(id); },
    createElement: () => ({})};
  const drawn = new Map();
  const Plotly = {react: async (graph, traces, layout) => { drawn.set(graph.id, {traces, layout}); }, Plots: {resize() {}}};
  function syncControls() {}
  for (const spec of specs) graphs.set(spec.id, {id: 'plot-' + spec.id, style: {}});
` + shipped + `
  const figure = specs[0].id;
  const snapshot = () => ({
    plotted: model.points.map(p => plottedValue(specs[0], p)),
    x: drawn.get('plot-' + figure).traces.filter(t => !t.meta?.isTransition).map(t => t.x),
    axis_type: drawn.get('plot-' + figure).layout.xaxis.type,
    axis_range: drawn.get('plot-' + figure).layout.xaxis.range ?? null,
    saved_range: state.ranges[figure]?.x ?? null,
    status: document.getElementById('status-' + figure).textContent,
    selected: getSelectedPoints('selected', figure).map(p => p.point_id),
    visible: getSelectedPoints('visible', figure).map(p => p.point_id),
    csv: exportCSV('selected', figure).csv,
    visible_export: exportCSV('visible', figure),
  });
  return (async () => {
    await draw();
    const linear = snapshot();
    state.log_current = true;
    await draw();
    const log = snapshot();
    await setView({ranges: {[figure]: {x: [0.05, 1]}}});
    const zoomed = snapshot();
    await setView({ranges: {[figure]: {x: [-0.001, 1]}}});
    const crossing = snapshot();
    ` + picker + `
    return {linear, log, zoomed, crossing, picker: document.getElementById('point-picker').children.map(option => option.textContent),
      points: model.points.map(p => p.Iout_A)};
  })();
`);
execute(model).then(result => process.stdout.write(JSON.stringify(result)));
"""
    model = _current_fixture()
    observed = _run_node(harness, {"script": script, "model": model})
    linear, log = observed["linear"], observed["log"]
    assert linear["plotted"] == [True, True, True, True]
    assert linear["axis_type"] == "linear"
    assert linear["x"] == [[0, -.0004, .099249, .499]]
    assert "omitted" not in linear["status"]
    assert linear["visible"] == ["no-load", "load-off-offset", "light", "half"]

    assert log["plotted"] == [False, False, True, True]
    assert log["axis_type"] == "log"
    # Gaps, not substituted small positive numbers: the zero and negative
    # readings become null in the drawn trace and nothing else moves.
    assert log["x"] == [[None, None, .099249, .499]]
    assert log["status"] == ("2 nonpositive-current point(s) omitted from this log view. "
                             "4 point result(s) in selected test curves. Raw observations remain unchanged.")
    assert log["selected"] == ["no-load", "load-off-offset", "light", "half"]
    assert log["visible"] == ["light", "half"]
    rows = list(csv.DictReader(io.StringIO(log["csv"])))
    assert [row["point_id"] for row in rows] == log["selected"]
    assert [row["Iout_A"] for row in rows] == ["0", "-0.0004", "0.099249", "0.499"]
    assert log["visible_export"]["metadata"]["point_count"] == 2
    assert "nonpositive points excluded for log current" in log["visible_export"]["metadata"]["scope_description"]
    # A positive zoom is drawn in log10 units but exported in physical units;
    # a zoom crossing zero cannot exist on a log axis and is dropped, never
    # transformed into NaN or -Infinity bounds.
    zoomed, crossing = observed["zoomed"], observed["crossing"]
    assert zoomed["saved_range"] == [.05, 1]
    assert zoomed["axis_range"] == [pytest.approx(-1.3010299956639813), 0]
    assert zoomed["visible"] == ["light", "half"]
    assert zoomed["visible_export"]["metadata"]["axis_bounds"]["x"] == [.05, 1]
    assert crossing["saved_range"] is None and crossing["axis_range"] is None
    assert crossing["x"] == [[None, None, .099249, .499]]
    assert crossing["visible_export"]["metadata"]["axis_bounds"]["x"] is None
    assert observed["points"] == [0, -.0004, .099249, .499], "the embedded evidence is never rewritten"
    assert observed["picker"] == ["no-load · 24 V / 0 A · valid", "load-off-offset · 24 V / 0 A · valid",
                                  "light · 24 V / 0.1 A · valid", "half · 24 V / 0.5 A · valid"]


def test_issued_csv_export_matches_interactive_export_byte_for_byte(tmp_path):
    """reports/<rev>/exports/points.csv and the HTML 'Export selected curves' agree exactly."""
    from dcdc_bench.reporting import renderer
    script = (TEMPLATES / "web/report.js").read_text()
    model = _current_fixture()
    # Awkward values on purpose: integral floats, values below 1e-4, exponent
    # notation, quotes and commas, and text that spreadsheets would execute.
    model["points"][0].update(programmed_input_V=24., input_condition_label='24 V input, "set"',
                              vout_error_pct=1e-05, Pin_W=None)
    model["points"][1].update(reason='=HYPERLINK("x") load-off offset', loss_W=2.5e-7, Vin_V=123456789012.5)
    model["points"][2].update(reason="-0.4 mA offset noted", Pout_W=1.2045445821896251)
    model["points"][3].update(phase_label="Increasing demand", elapsed_start_s=0., elapsed_s=4.5175, elapsed_end_s=9.035)
    model["figures"].append({**model["figures"][0], "id": "fig-demand-time", "x_key": "elapsed_s"})
    renderer.write_exports(model, tmp_path)
    issued = (tmp_path / "exports/points.csv").read_text(encoding="utf-8", newline="")
    harness = r"""
const {script, model} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
""" + SLICE_SUPPORT + r"""
const shipped = [slice('  const quantityLabels', '  const hoverLabels'),
                 slice('  function bounds(spec)', '  function download')].join('\n');
const execute = new Function('model', "'use strict';\n" + helpers + `
  const payload = {model}; const specs = model.figures;
  const points = new Map(model.points.map(p => [p.point_id, p]));
  const graphs = new Map(), conditions = new Map(), identity = 'DUT';
  specs.forEach(spec => spec.series.forEach(series => conditions.set(keyOf(series), {label: series.label})));
  let state = {selected_series: [...conditions.keys()], metric: 'all', x_key: 'default', log_current: true,
    hovermode: 'closest', ranges: {}};
` + shipped + `
  return {csv: exportCSV('selected', specs[0].id).csv, fields: csvFields};
`);
process.stdout.write(JSON.stringify(execute(model)));
"""
    interactive = _run_node(harness, {"script": script, "model": model})
    assert issued.split("\r\n")[0].split(",") == interactive["fields"]
    assert issued == interactive["csv"]
    rows = list(csv.DictReader(io.StringIO(issued)))
    assert [row["point_id"] for row in rows] == ["no-load", "load-off-offset", "light", "half"]
    assert rows[0]["programmed_input_V"] == "24" and rows[0]["vout_error_pct"] == "0.00001"
    assert rows[1]["loss_W"] == "2.5e-7" and rows[1]["Vin_V"] == "123456789012.5"
    assert rows[1]["reason"].startswith("'=") and rows[2]["reason"] == "'-0.4 mA offset noted"
    assert rows[0]["input_condition_label"] == '24 V input, "set"'
    assert rows[0]["Pin_W"] == "" and rows[3]["elapsed_s"] == "4.5175" and rows[0]["elapsed_s"] == ""
