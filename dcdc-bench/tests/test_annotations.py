"""Sensor annotations: exact schema, hash binding, new report revisions, escaped rendering (WEB-11, WEB-12)."""
import copy
import hashlib
import io
import json
import math
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from dcdc_bench.annotations import (PLACEHOLDER, AnnotationError, annotation_document, annotations_file,
                                    load_annotations, validate_annotations)
from dcdc_bench.attachments import AssetHashMismatch, AssetNotFound, AssetStore
from dcdc_bench.reporting import ReportRenderError, render_report, renderer
from dcdc_bench.reporting.renderer import TEMPLATES, _md
from dcdc_bench.reporting.sensor_placement import (sensor_placement_html, static_overlay_svg,
                                                   with_sensor_placement)
from dcdc_bench.storage import RunStore, verify_integrity


def png(width=40, height=30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 130, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def document(sha, *markers):
    return {"schema_version": "1.0", "image_asset_sha256": sha,
            "markers": [{"sensor_id": sid, "x_norm": x, "y_norm": y, "label": label} for sid, x, y, label in markers]}


@pytest.fixture
def finalized(tmp_path):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {"execution_status": "running"})
    store.finalize({"execution_status": "completed"})
    return store.path


def test_schema_is_exact_and_values_are_bounded():
    sha = "a" * 64
    valid = document(sha, ("TC1", 0.25, 0.5, "Case top center"), ("TC2", 1, 0, ""))
    normalized = validate_annotations(valid)
    assert normalized == {"schema_version": "1.0", "image_asset_sha256": sha, "markers": [
        {"sensor_id": "TC1", "x_norm": 0.25, "y_norm": 0.5, "label": "Case top center"},
        {"sensor_id": "TC2", "x_norm": 1.0, "y_norm": 0.0, "label": ""}]}
    assert annotation_document(sha, [{**valid["markers"][0], "extra": "editor state"}]) == \
        {"schema_version": "1.0", "image_asset_sha256": sha, "markers": [normalized["markers"][0]]}
    rejected = [
        {**valid, "notes": []}, {k: v for k, v in valid.items() if k != "markers"},
        {**valid, "schema_version": "2.0"}, {**valid, "image_asset_sha256": sha.upper()},
        {**valid, "image_asset_sha256": "abc"}, {**valid, "markers": {}},
        document(sha, ("TC1", 1.5, 0.5, "")), document(sha, ("TC1", -0.1, 0.5, "")),
        document(sha, ("TC1", math.nan, 0.5, "")), document(sha, ("TC1", True, 0.5, "")),
        document(sha, ("TC1", 0.5, "0.5", "")), document(sha, ("TC1", 0.2, 0.2, ""), ("TC1", 0.3, 0.3, "")),
        document(sha, ("bad id!", 0.2, 0.2, "")), document(sha, ("", 0.2, 0.2, "")),
        document(sha, ("TC1", 0.2, 0.2, "x" * 201)), document(sha, ("TC1", 0.2, 0.2, "line\x00feed")),
        document(sha, ("TC1", 0.2, 0.2, None)),
        {**valid, "markers": [{**valid["markers"][0], "temperature_C": 40.0}]},
        {**valid, "markers": [{"sensor_id": "TC1", "x_norm": 0.1, "y_norm": 0.1}]},
    ]
    for value in rejected:
        with pytest.raises(AnnotationError):
            validate_annotations(value)


def test_loading_binds_markers_to_the_stored_original_and_detects_changed_bytes(finalized):
    store = AssetStore(finalized)
    entry = store.add(png(), "case.png", caption="Case top")
    doc = document(entry["sha256"], ("TC1", 0.25, 0.5, "Case top center"))
    report_dir = finalized / "reports/r0001"
    report_dir.mkdir(parents=True)
    (report_dir / "annotations.json").write_text(json.dumps(annotations_file(finalized, doc)))
    annotations, asset = load_annotations(report_dir)
    assert annotations == validate_annotations(doc) and asset == entry
    assert json.loads((report_dir / "annotations.json").read_text()) == validate_annotations(doc)
    # A revision without sensor markers is the empty placeholder: nothing to load.
    other = finalized / "reports/r0002"
    other.mkdir()
    (other / "annotations.json").write_text(json.dumps(annotations_file(finalized, None)))
    assert annotations_file(finalized, None) == PLACEHOLDER and load_annotations(other) is None
    assert load_annotations(finalized / "reports/r0003") is None
    with pytest.raises(AssetNotFound):
        annotations_file(finalized, document("0" * 64, ("TC1", 0.1, 0.1, "")))
    pdf_like = store.add(b"%PDF-1.4\n" + _minimal_pdf(), "page.pdf")
    with pytest.raises(AnnotationError, match="photograph"):
        annotations_file(finalized, document(pdf_like["sha256"], ("TC1", 0.1, 0.1, "")))
    # WEB-11: the current image hash differs from the saved reference.
    store.path_for(entry).write_bytes(png(41, 30))
    with pytest.raises(AssetHashMismatch):
        load_annotations(report_dir)
    with pytest.raises(AssetHashMismatch):
        annotations_file(finalized, doc)


def _minimal_pdf() -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    return data[data.index(b"\n") + 1:]


def test_saving_annotations_creates_a_new_report_revision_and_preserves_acquisition(tmp_path, monkeypatch):
    import dcdc_bench.reporting
    from dcdc_bench.planning import build_plan
    from dcdc_bench.runner import run_mock
    from dcdc_bench.services import default_plan, report_run
    plan = default_plan()
    plan.recipe.tests[0].input_voltage_targets_V = [24.]
    plan.recipe.tests[0].output_current_targets_A = [.1]
    run_dir = run_mock(build_plan(plan.dut, plan.bench, plan.recipe), tmp_path)
    rendered = []
    # Revision orchestration only; renderer behavior has its own tests.
    monkeypatch.setattr(dcdc_bench.reporting, "render_report", lambda model, output, **kw: rendered.append(output))
    integrity = json.loads((run_dir / "integrity.json").read_text())
    before = {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in integrity["files"]}
    before_integrity = (run_dir / "integrity.json").read_bytes()
    first = report_run(run_dir, formats=("html",))
    assert json.loads((first / "annotations.json").read_text()) == PLACEHOLDER
    entry = AssetStore(run_dir).add(png(), "case.png", caption="Case top")
    doc = document(entry["sha256"], ("TC1", 0.25, 0.5, "Case top center"), ("AMB", 0.9, 0.1, "Ambient reference"))
    second = report_run(run_dir, formats=("html",), annotations=doc)
    assert second != first and second.name > first.name and rendered == [first, second]
    saved = json.loads((second / "annotations.json").read_text())
    assert saved == validate_annotations(doc) and set(saved) == {"schema_version", "image_asset_sha256", "markers"}
    models = [json.loads((path / "report_model.json").read_text()) for path in (first, second)]
    assert models[0]["analysis_id"] == models[1]["analysis_id"] and models[0]["run_id"] == models[1]["run_id"]
    assert [m["report_revision"] for m in models] == [first.name, second.name]
    assert {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in integrity["files"]} == before
    assert (run_dir / "integrity.json").read_bytes() == before_integrity
    verify_integrity(run_dir)
    revisions = sorted((run_dir / "reports").glob("r*"))
    with pytest.raises(AnnotationError):
        report_run(run_dir, formats=("html",), annotations={**doc, "extra": 1})
    with pytest.raises(AssetNotFound):
        report_run(run_dir, formats=("html",), annotations=document("0" * 64, ("TC1", 0.1, 0.1, "")))
    assert sorted((run_dir / "reports").glob("r*")) == revisions, "a refused annotation set creates no revision"


def test_rendered_section_escapes_untrusted_text_and_positions_markers_from_normalized_coordinates(finalized):
    store = AssetStore(finalized)
    caption = 'Case top <img src=x onerror="alert(1)"> & "quoted"'
    entry = store.add(png(), "case.png", caption=caption)
    label = '<script>alert("label")</script> | pipe & ampersand'
    doc = document(entry["sha256"], ("TC1", 0.25, 0.5, label), ("TC2", 0.9, 0.1, "right edge"))
    report_dir = finalized / "reports/r0002"
    report_dir.mkdir(parents=True)
    (report_dir / "annotations.json").write_text(json.dumps(annotations_file(finalized, doc)))
    body = "## Summary\n\nissued text\n\n**Traceability:** Run ID fixture; analysis a-1\n"
    result = with_sensor_placement(body, report_dir, _md)
    assert result.index("## Sensor placement") < result.index("**Traceability:** Run ID fixture")
    assert result.startswith("## Summary")
    html_block = result.split("```{=html}", 1)[1].split("```", 1)[0]
    for forbidden in ("<script>", "<img src=x", 'onerror="alert', "</script>"):
        assert forbidden not in html_block
    # Outside the HTML block the same text only appears Markdown-escaped (literal, not markup).
    assert re.search(r"(?<![\\&])<(script|img)", result.replace(html_block, "")) is None
    assert "&lt;script&gt;alert(&quot;label&quot;)&lt;/script&gt;" in result
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in result
    assert 'data-x-norm="0.250000" data-y-norm="0.500000"' in result
    assert 'style="left:25.0000%;top:50.0000%"' in result
    assert 'class="sensor-marker"' in result and 'type="button"' in result and 'aria-pressed="false"' in result
    assert '::: {.content-visible when-format="html"}' in result and 'unless-format="html"' in result
    assert "| 1 | TC1 | " in result and r"\<script\>" in result, "print table cells are Markdown-escaped"
    assert "temperature" in result.lower() and "no temperature field is inferred" in result
    copy_path = report_dir / "assets" / (entry["sha256"] + ".png")
    assert hashlib.sha256(copy_path.read_bytes()).hexdigest() == entry["sha256"]
    assert f'src="assets/{entry["sha256"]}.png"' in result
    svg = (report_dir / "figures/sensor-placement.svg").read_text()
    assert svg.count("<circle") == 2 and "data:image/png;base64," in svg and "<script" not in svg
    assert 'cx="10.00" cy="15.00"' in svg, "0.25 × 40 px and 0.5 × 30 px"
    assert 'text-anchor="end"' in svg, "labels near the right edge flip inward"
    # No markers: the body is untouched. Changed image bytes: an error, never a silent skip.
    plain = finalized / "reports/r0003"
    plain.mkdir()
    (plain / "annotations.json").write_text(json.dumps(PLACEHOLDER))
    assert with_sensor_placement(body, plain, _md) == body
    store.path_for(entry).write_bytes(png(41, 30))
    with pytest.raises(AssetHashMismatch):
        with_sensor_placement(body, report_dir, _md)


def test_static_overlay_requires_known_dimensions_and_escapes_names():
    asset = {"media_type": "image/png", "width": 100, "height": 50, "original_name": 'a"b<c>.png'}
    doc = document("b" * 64, ("TC1", 0.5, 0.5, ""))
    svg = static_overlay_svg(b"x", asset, doc)
    assert "a&quot;b&lt;c&gt;.png" in svg and '<title>Sensor placement on a&quot;b&lt;c&gt;.png</title>' in svg
    with pytest.raises(ValueError, match="dimensions"):
        static_overlay_svg(b"x", {**asset, "width": None}, doc)
    html = sensor_placement_html(doc, {**asset, "width": None, "height": None}, "assets/x.png")
    assert ' width="' not in html.split("<img", 1)[1].split(">", 1)[0]


@pytest.fixture
def model():
    return {
        "run_id": "synthetic-run", "analysis_id": "analysis-1", "report_revision": "r0001",
        "evidence_label": "SYNTHETIC", "boundary": "source-to-DUT-output path",
        "dut": {"model": "Fixture DUT", "sample_id": "sample-1"},
        "points": [{"point_id": "p1", "test_id": "load", "vin_target_V": 12, "iout_target_A": .1, "Iout_A": .099,
                    "efficiency_pct": 39.1575, "qualification": "valid"}],
        "figures": [{"id": "fig-efficiency", "title": "Path efficiency", "x_key": "Iout_A", "y_key": "efficiency_pct",
                     "x_label": "Output current (A)", "y_label": "Efficiency (%)", "caption": "Fixture.",
                     "series": [{"id": "vin-12", "label": "12 V", "vin_target_V": 12, "point_ids": ["p1"]}]}],
        "metrics": [], "raw_samples": {}, "summary": [],
    }


def _stub_document_tools(monkeypatch, seen):
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
        seen.append((directory / "report.qmd").read_text())
        (directory / "report.html").write_text("<!doctype html><html><body>"
                                               + (directory / "interactions.html").read_text() + "</body></html>")
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    monkeypatch.setattr(renderer.subprocess, "run", document_fixture)
    def tool_fixture(command, **kwargs):
        result = document_fixture(command, cwd=kwargs["cwd"])
        result.usage = {"timed_out": False, "survivors": [], "command": command}
        return result
    monkeypatch.setattr(renderer, "_run_tool", tool_fixture)


def test_render_report_adds_the_section_only_for_revisions_with_markers_and_fails_on_hash_mismatch(model, finalized, monkeypatch):
    seen = []
    _stub_document_tools(monkeypatch, seen)
    store = AssetStore(finalized)
    entry = store.add(png(), "case.png")
    plain = finalized / "reports/r0001"
    plain.mkdir(parents=True)
    (plain / "annotations.json").write_text(json.dumps(PLACEHOLDER))
    assert render_report(model, plain, formats=("html",))["status"] == "success"
    assert "Sensor placement" not in seen[-1]
    annotated = finalized / "reports/r0002"
    annotated.mkdir()
    doc = document(entry["sha256"], ("TC1", 0.25, 0.5, "Case <b>top</b>"))
    (annotated / "annotations.json").write_text(json.dumps(annotations_file(finalized, doc)))
    marked = copy.deepcopy(model)
    marked["report_revision"] = "r0002"
    assert render_report(marked, annotated, formats=("html",))["status"] == "success"
    assert "## Sensor placement" in seen[-1] and "Case &lt;b&gt;top&lt;/b&gt;" in seen[-1]
    assert (annotated / "assets" / (entry["sha256"] + ".png")).is_file()
    assert (annotated / "figures/sensor-placement.svg").is_file()
    store.path_for(entry).write_bytes(png(41, 30))
    tampered = finalized / "reports/r0003"
    tampered.mkdir()
    (tampered / "annotations.json").write_text(json.dumps(validate_annotations(doc)))
    with pytest.raises(ReportRenderError, match="hash"):
        render_report({**marked, "report_revision": "r0003"}, tampered, formats=("html",))
    manifest = json.loads((tampered / "build_manifest.json").read_text())
    assert manifest["status"] == "failed" and "AssetHashMismatch" in manifest["artifacts"]["html"]["error"]
    assert not (tampered / "report.html").exists()


def _node() -> Path:
    playwright = pytest.importorskip("playwright")
    node = Path(playwright.__file__).parent / "driver/node"
    if not node.is_file():
        pytest.skip("Playwright's bundled Node runtime is unavailable")
    return node


def test_shipped_script_positions_markers_from_normalized_coordinates_on_load_and_resize():
    """WEB-11 without a browser: the shipped placement code against a stand-in document."""
    script = (TEMPLATES / "web/report.js").read_text()
    for anchor in ("  function sensorMarkerPosition(", "  function initSensorPlacement()", "  let sensorPlacement = "):
        assert anchor in script
    harness = r"""
const {script, markers} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const slice = (from, to) => {
  const start = script.indexOf(from), end = script.indexOf(to, start);
  if (start < 0 || end < 0) throw new Error('shipped script no longer contains ' + JSON.stringify([from, to]));
  return script.slice(start, end);
};
const finite = script.match(/^  const finite = .*;$/m)[0];
const shipped = slice('  function sensorMarkerPosition(', '  let sensorPlacement = ');
const execute = new Function('markers', "'use strict';\n" + finite + `
  const listeners = {};
  const element = (props) => ({...props, style: {}, dataset: props.dataset ?? {}, attributes: {}, focused: false,
    classes: new Set(), handlers: {},
    addEventListener(type, fn) { this.handlers[type] = fn; },
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name] ?? null; },
    focus() { this.focused = true; focusLog.push(this.dataset.sensorId); },
    classList: {add: (c) => {}, remove: (c) => {}}});
  const focusLog = [];
  const image = element({clientWidth: 800, clientHeight: 600, complete: true});
  const buttons = markers.map(m => { const b = element({dataset: {xNorm: String(m.x), yNorm: String(m.y), sensorId: m.id}});
    b.attributes['aria-label'] = 'Sensor ' + m.id + '. ' + m.label; return b; });
  const rows = markers.map(m => { const r = element({dataset: {sensorId: m.id}}); r.selected = false;
    r.classList = {add: () => { r.selected = true; }, remove: () => { r.selected = false; }}; return r; });
  const detail = element({textContent: ''});
  const block = {dataset: {}, querySelector: (sel) => sel === 'img.sensor-image' ? image : sel === '.sensor-marker-detail' ? detail : null,
    querySelectorAll: (sel) => sel === '.sensor-marker' ? buttons : sel.includes('tbody tr') ? rows : []};
  const document = {querySelectorAll: (sel) => sel === '.sensor-placement-block' ? [block] : [], getElementById: () => null};
  const window = {addEventListener(type, fn) { listeners[type] = fn; }};
` + shipped + `
  const api = initSensorPlacement();
  const positions = () => buttons.map(b => [b.style.left, b.style.top]);
  const initial = positions();
  image.clientWidth = 400; image.clientHeight = 300;
  listeners.resize();
  const resized = positions();
  buttons[0].handlers.click();
  const afterClick = {pressed: buttons.map(b => b.attributes['aria-pressed']), detail: detail.textContent,
    rows: rows.map(r => r.selected)};
  buttons[0].handlers.keydown({key: 'ArrowRight', preventDefault() {}});
  buttons[1].handlers.keydown({key: 'End', preventDefault() {}});
  buttons[2].handlers.keydown({key: 'x', preventDefault() {}});
  return {blocks: api.blocks, ready: block.dataset.sensorReady, initial, resized, afterClick, focusLog,
    invalid: sensorMarkerPosition('nan', 0.5, 800, 600), clamped: sensorMarkerPosition(1.7, -2, 100, 100)};
`);
process.stdout.write(JSON.stringify(execute(markers)));
"""
    markers = [{"id": "TC1", "x": 0.25, "y": 0.5, "label": "Case top center"},
               {"id": "TC2", "x": 0.9, "y": 0.1, "label": "Right edge"},
               {"id": "AMB", "x": 0.0, "y": 1.0, "label": "Ambient"}]
    result = subprocess.run([str(_node()), "-e", harness], input=json.dumps({"script": script, "markers": markers}),
                            capture_output=True, text=True, check=True, timeout=30)
    observed = json.loads(result.stdout)
    assert observed["blocks"] == 1 and observed["ready"] == "true"
    assert observed["initial"] == [["200.00px", "300.00px"], ["720.00px", "60.00px"], ["0.00px", "600.00px"]]
    assert observed["resized"] == [["100.00px", "150.00px"], ["360.00px", "30.00px"], ["0.00px", "300.00px"]]
    for (left, top), marker in zip(observed["resized"], markers):
        assert math.isclose(float(left[:-2]) / 400, marker["x"]) and math.isclose(float(top[:-2]) / 300, marker["y"])
    assert observed["afterClick"]["pressed"] == ["true", "false", "false"]
    assert observed["afterClick"]["rows"] == [True, False, False]
    assert observed["afterClick"]["detail"].startswith("Sensor TC1. Case top center Normalized position x=0.2500, y=0.5000.")
    assert observed["focusLog"] == ["TC2", "AMB"], "arrow keys and End move focus between markers"
    assert observed["invalid"] is None and observed["clamped"] == {"left": "100.00px", "top": "0.00px"}


def test_report_styles_and_script_ship_the_sensor_placement_hooks():
    css = (TEMPLATES / "theme/report.css").read_text()
    assert ".sensor-image-frame{position:relative" in css and ".sensor-marker{position:absolute" in css
    script = (TEMPLATES / "web/report.js").read_text()
    assert "window.dcdcReport.sensorPlacement=sensorPlacement;" in script
    assert re.search(r"restore-view'\)\?\.addEventListener\('click'", script), "Restore default view clears sensor highlighting"
