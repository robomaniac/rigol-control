"""Small shipped-JavaScript fixtures; no browser, instruments or report build."""
import csv
import io
import json
from pathlib import Path
import subprocess

import pytest

from dcdc_bench.reporting.renderer import TEMPLATES


def test_nominal_input_label_and_programmed_voltage_survive_hover_and_csv():
    playwright = pytest.importorskip("playwright")
    node = Path(playwright.__file__).parent / "driver/node"
    if not node.is_file():
        pytest.skip("Playwright's bundled Node runtime is unavailable")
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
