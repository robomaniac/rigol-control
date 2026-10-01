"""Release gates requiring actual Quarto/Chromium, never fake renderer outputs.

Set DCDC_DEMO_DIR to a completed `dcdc-bench demo` directory to verify exactly
those artifacts. Otherwise the marked suite builds a fresh demo once.
"""
from __future__ import annotations
from contextlib import contextmanager
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def _open_report(page, path):
    page.goto(path.as_uri(), wait_until="load", timeout=120000)
    page.wait_for_function("window.dcdcReport !== undefined", timeout=60000)
    page.wait_for_function("document.documentElement.dataset.reportReady === 'true'", timeout=60000)


@contextmanager
def _report_variant(viewer, documents, tmp_path, change_model):
    """Exercise edge cases with the exact shipped runtime, one browser tab.

    Only the embedded evidence fixture changes. No alternate plotting library,
    fake DOM, extra browser process, or static-image rebuild is involved.
    """
    from dcdc_bench.reporting.renderer import _embedded_json
    page, _, _ = viewer
    original = documents[0] / "report.html"
    source = original.read_text(encoding="utf-8")
    marker = '<script type="application/json" id="dcdc-report-data">'
    assert marker in source, "The shipped report must embed its evidence payload"
    start = source.index(marker) + len(marker)
    end = source.index('</script>', start)
    payload = json.loads(source[start:end])
    change_model(payload["model"])
    source = source[:start] + _embedded_json(payload) + source[end:]
    path = tmp_path / "report-fixture.html"
    path.write_text(source, encoding="utf-8")
    try:
        _open_report(page, path)
        yield page, payload["model"]
    finally:
        _open_report(page, original)


def _hover_point(page, point_id, figure_id="fig-efficiency"):
    """Move the actual pointer onto a measured marker in Plotly's coordinates."""
    graph = page.locator("#plot-" + figure_id)
    graph.scroll_into_view_if_needed()
    coordinate = page.evaluate("""({figureId, pointId}) => {
        const graph = document.getElementById('plot-' + figureId);
        const point = dcdcReport.model.points.find(p => p.point_id === pointId);
        const spec = dcdcReport.model.figures.find(f => f.id === figureId);
        const horizontal = dcdcReport.state.x_key === 'default' ? spec.x_key : dcdcReport.state.x_key;
        const rect = graph.getBoundingClientRect();
        return {x: rect.x + graph._fullLayout.xaxis._offset + graph._fullLayout.xaxis.d2p(point[horizontal]),
                y: rect.y + graph._fullLayout.yaxis._offset + graph._fullLayout.yaxis.d2p(point[spec.y_key])};
    }""", {"figureId": figure_id, "pointId": point_id})
    page.mouse.move(coordinate["x"], coordinate["y"])
    page.wait_for_function("""figureId => document.querySelector('#plot-' + figureId + ' .hoverlayer .hovertext')
        ?.textContent.trim().length > 0""", arg=figure_id)
    return coordinate


@pytest.fixture(scope="session")
def documents(tmp_path_factory):
    specified = os.environ.get("DCDC_DEMO_DIR")
    if specified:
        root = Path(specified).resolve()
    else:
        from dcdc_bench.services import demo
        root = tmp_path_factory.mktemp("documents")
        demo(root)
    paths = []
    for name in ("normal", "setup-limited", "aborted"):
        reports = sorted((root / name).glob("*/reports/r*/report.html"))
        assert reports, f"No generated {name} report under {root}"
        paths.append(reports[-1].parent)
    return paths


@pytest.fixture(scope="module")
def viewer(documents):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        from dcdc_bench.reporting.renderer import _browser_path
        executable = _browser_path()
        browser = playwright.chromium.launch(executable_path=executable, headless=True,
            args=["--disable-dev-shm-usage", "--disable-gpu", "--no-sandbox", "--renderer-process-limit=1"])
        # Playwright's service_workers="block" injects an unguarded read of
        # navigator.serviceWorker, which itself throws in the served report's
        # opaque sandbox. Offline mode and request routing enforce isolation;
        # the served-report gate also checks native worker access is denied.
        context = browser.new_context(viewport={"width": 1365, "height": 980}, accept_downloads=True,
                                      offline=True)
        blocked = []
        def block(route):
            if route.request.url.startswith(("http:", "https:")):
                blocked.append(route.request.url)
                route.abort()
            else:
                route.continue_()
        # Intercept external traffic only. Sending embedded data URLs through
        # the Python protocol adds work without strengthening the offline gate.
        context.route(re.compile(r"^https?://"), block)
        page = context.new_page()
        errors=[]
        page.on("pageerror", lambda error: errors.append(str(error)))
        _open_report(page, documents[0] / "report.html")
        yield page, errors, blocked
        context.close()
        browser.close()


@pytest.mark.browser
def test_web01_web02_offline_exact_shipped_runtime(viewer, documents):
    page, errors, blocked = viewer
    for directory in documents:
        _open_report(page, directory / "report.html")
        manifest = json.loads((directory / "build_manifest.json").read_text())
        assert page.evaluate("Plotly.version") == manifest["versions"]["plotly_js"]
        assert page.locator('.js-plotly-plot').count() == 3
        assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex,nofollow"
        assert "SYNTHETIC" in page.locator("body").inner_text()
        # Every legend entry must represent at least one plotted observation.
        assert page.evaluate("""() => [...document.querySelectorAll('.js-plotly-plot')]
            .every(graph => graph.data.filter(trace => trace.showlegend !== false)
                .every(trace => trace.x.some((x,i) => Number.isFinite(x) && Number.isFinite(trace.y[i]))))""")
    assert not errors
    assert not blocked, f"Report attempted external requests: {blocked}"
    _open_report(page, documents[0] / "report.html")



def _browser_dispatches_print_events(context) -> bool:
    """Probe on a blank page whether window.print() raises beforeprint/afterprint in this browser.

    Headless Chrome for Testing (CI) does not; the system Chromium on the bench Pi does. The probe
    decides a skip for the environment, never for the report under test.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    probe = context.new_page()
    try:
        probe.goto("about:blank")
        probe.evaluate("""() => { window.__probe = [];
            addEventListener('beforeprint', () => __probe.push('b')); addEventListener('afterprint', () => __probe.push('a'));
            setTimeout(() => window.print(), 0); }""")
        try:
            probe.wait_for_function("window.__probe.length === 2", timeout=5000)
            return True
        except PlaywrightTimeoutError:
            return False
    finally:
        probe.close()


@pytest.mark.browser
def test_served_report_opaque_origin_draws_and_prints_without_page_errors(viewer, documents):
    """The real artifact headers add restrictions absent from a file:// view.

    Reuse the release-gate browser; allow only this loopback URL through its
    existing external-request block. A native print event verifies the modal
    permission without substituting window.print or dispatching fake events.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from dcdc_bench.ui import file_headers

    page, errors, blocked = viewer
    artifact = documents[0] / "report.html"
    document = artifact.read_bytes()
    headers = file_headers(artifact)
    assert "allow-same-origin" not in headers["Content-Security-Policy"]

    class ReportHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/report.html":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(document)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(document)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/report.html"
    allow_loopback = lambda route: route.continue_()
    page.route(url, allow_loopback)
    page.context.set_offline(False)
    initial_errors = len(errors)
    try:
        response = page.goto(url, wait_until="load", timeout=120000)
        assert response.status == 200
        assert response.headers["content-security-policy"] == headers["Content-Security-Policy"]
        page.wait_for_function("document.documentElement.dataset.reportReady === 'true'", timeout=60000)
        assert page.locator('.js-plotly-plot').count() == 3
        assert page.evaluate("window.origin") == "null"
        assert page.evaluate("""() => {
            try { void window.sessionStorage; return false; }
            catch (error) { return error.name === 'SecurityError'; }
        }"""), "The report must retain an opaque origin with native storage denied"
        assert page.evaluate("""() => {
            try { void navigator.serviceWorker; return false; }
            catch (error) { return error.name === 'SecurityError'; }
        }"""), "The opaque report sandbox must deny service worker access"
        assert page.locator('head #dcdc-report-head').count() == 1
        page.evaluate("""() => {
            localStorage.setItem('report-gate', 'document only');
            window.__printEvents = [];
            addEventListener('beforeprint', () => __printEvents.push('before'));
            addEventListener('afterprint', () => __printEvents.push('after'));
        }""")
        assert page.evaluate("localStorage.getItem('report-gate')") == "document only"
        # Quarto also reads storage in its resize/reader-mode handlers.
        page.set_viewport_size({"width": 1000, "height": 850})
        if not _browser_dispatches_print_events(page.context):
            pytest.skip("this headless browser never dispatches beforeprint/afterprint, so the print permission "
                        "cannot be observed here (Chrome for Testing on CI); the Pi's Chromium does dispatch them")
        page.locator('#print-view').click()
        page.wait_for_function("window.__printEvents.join(',') === 'before,after'", timeout=30000)
        assert errors[initial_errors:] == []
        assert not blocked, f"Served report attempted external requests: {blocked}"
    finally:
        page.unroute(url, allow_loopback)
        page.context.set_offline(True)
        page.set_viewport_size({"width": 1365, "height": 980})
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _open_report(page, artifact)


@pytest.mark.browser
def test_web03_web04_state_visibility_resets(viewer):
    page, _, _ = viewer
    page.evaluate("dcdcReport.restoreDefaults()")
    original = page.evaluate("JSON.stringify(dcdcReport.state)")
    page.evaluate("dcdcReport.setView({selected_series:['24'],log_current:true,ranges:{'fig-efficiency':{x:[0.5,1]}}})")
    assert page.locator('#trace-options input:checked').count() == 1
    selected=page.evaluate("dcdcReport.getSelectedPoints('selected','fig-efficiency')")
    assert selected and all(p["vin_target_V"] == 24 for p in selected)
    page.evaluate("dcdcReport.resetZoom()")
    state=page.evaluate("dcdcReport.state")
    assert state["selected_series"] == ["24"]
    assert state["log_current"] is True
    page.evaluate("dcdcReport.restoreDefaults()")
    assert page.evaluate("JSON.stringify(dcdcReport.state)") == original


@pytest.mark.browser
def test_web_chart_captions_remain_below_svg_on_desktop_and_mobile(viewer):
    page, _, _ = viewer
    page.evaluate("dcdcReport.restoreDefaults()")
    try:
        for width, height in ((390, 844), (1365, 980)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("""async () => {
                await dcdcReport.whenIdle();
                await Promise.all([...dcdcReport.graphs.values()].map(graph => Plotly.Plots.resize(graph)));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            }""")
            boxes = page.evaluate("""() => [...document.querySelectorAll('.figure-view')].map(view => {
                const graph = view.querySelector('.js-plotly-plot');
                return {figure: graph.id, svgBottom: graph.querySelector('.main-svg').getBoundingClientRect().bottom,
                    captionTop: view.querySelector('figcaption').getBoundingClientRect().top};
            })""")
            assert boxes and all(box["captionTop"] >= box["svgBottom"] - 1 for box in boxes), boxes
            # No horizontal overflow: the document is no wider than the layout viewport.
            # `clientWidth` excludes a classic (non-overlay) scrollbar, which CI's Chromium
            # draws and the bench Pi's does not; 2 px absorbs fractional layout rounding.
            # On failure, name the elements that stick out so the offender is known.
            overflow = page.evaluate("""() => {
                const limit = document.documentElement.clientWidth + 2;
                const wide = document.documentElement.scrollWidth > limit;
                const offenders = wide ? [...document.body.querySelectorAll('*')]
                    .filter(el => el.getBoundingClientRect().right > limit && el.getClientRects().length)
                    .slice(0, 12).map(el => (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
                        (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
                        + ' right=' + Math.round(el.getBoundingClientRect().right))) : [];
                return {viewport: innerWidth, layout: document.documentElement.clientWidth,
                        document: document.documentElement.scrollWidth, offenders};
            }""")
            assert overflow["document"] <= overflow["layout"] + 2, (width, overflow)
    finally:
        page.set_viewport_size({"width": 1365, "height": 980})


@pytest.mark.browser
def test_web_time_stage_guides_follow_filters_without_creating_observations(viewer):
    """Run against a generated sequence report; legacy M0/M1 demos have no time figure."""
    import base64
    import copy
    from urllib.parse import unquote
    from xml.etree import ElementTree
    from dcdc_bench.reporting.renderer import _stage_transition_pairs

    page, errors, blocked = viewer
    page.evaluate("dcdcReport.restoreDefaults()")
    model = page.evaluate("({points:dcdcReport.model.points,figures:dcdcReport.model.figures,execution:dcdcReport.model.execution})")
    spec = next((figure for figure in model["figures"] if figure["id"] == "fig-demand-time"), None)
    if spec is None:
        pytest.skip("This report does not contain a chronological demand sequence")
    expected = _stage_transition_pairs(model, spec)
    assert expected, "A complete sequence fixture needs at least one qualified stage boundary"
    page.evaluate("window.__transitionModelBefore = JSON.stringify(dcdcReport.model); undefined")
    csv_before = page.evaluate("dcdcReport.exportCSV('selected','fig-demand-time')")

    def guides():
        return page.evaluate("""() => dcdcReport.graphs.get('fig-demand-time').data
            .filter(trace => trace.meta?.isTransition).map(trace => ({x:trace.x,y:trace.y,
                mode:trace.mode,dash:trace.line.dash,legend:trace.showlegend,hover:trace.hoverinfo,
                ids:trace.customdata ?? null,connectgaps:trace.connectgaps}))""")

    def check_pairs(pairs):
        actual = guides()
        assert len(actual) == len(pairs)
        for guide, pair in zip(actual, pairs):
            assert guide["x"] == [point["elapsed_s"] for point in pair]
            assert guide["y"] == [point["Iout_A"] for point in pair]
            assert guide["mode"] == "lines" and guide["dash"] == "dot"
            assert guide["legend"] is False and guide["hover"] == "skip"
            assert guide["ids"] is None and guide["connectgaps"] is False

    try:
        check_pairs(expected)
        # The actual checkbox removes guides incident on that stage; it must
        # never invent a direct connection around the hidden stage.
        middle = spec["series"][1]
        key = str(middle.get("selection_key") or middle["vin_target_V"])
        checkbox = page.locator('#trace-options input[data-series="' + key + '"]')
        checkbox.uncheck()
        page.evaluate("dcdcReport.whenIdle()")
        filtered = copy.deepcopy(spec)
        filtered["series"] = [series for series in spec["series"]
                              if str(series.get("selection_key") or series["vin_target_V"]) != key]
        check_pairs(_stage_transition_pairs(model, filtered))
        checkbox.check()
        page.evaluate("dcdcReport.whenIdle()")
        check_pairs(expected)
        page.locator('#x-select').select_option('Pout_W')
        page.evaluate("dcdcReport.whenIdle()")
        assert not guides(), "Stage transitions belong only to the elapsed-time view"
        page.locator('#x-select').select_option('default')
        page.evaluate("dcdcReport.whenIdle()")
        check_pairs(expected)
        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-demand-time')")
        assert exported["csv"] == csv_before["csv"]
        rows = list(csv.DictReader(io.StringIO(exported["csv"])))
        assert len(rows) == len({pid for series in spec["series"] for pid in series["point_ids"]})
        assert set(row["point_id"] for row in rows) <= {point["point_id"] for point in model["points"]}
        # Exported SVG keeps the guides as dotted paths, with no marker symbols.
        uri = page.evaluate("dcdcReport.exportFigure('fig-demand-time','svg')")
        encoded = uri.split(',', 1)[1]
        svg = base64.b64decode(encoded).decode() if ';base64,' in uri else unquote(encoded)
        paths = [node for node in ElementTree.fromstring(svg).iter()
                 if node.tag.endswith('path') and 'js-line' in node.get('class', '').split()]
        neutral = [node for node in paths if 'rgb(145, 161, 173)' in node.get('style', '')]
        assert len(neutral) == len(expected)
        assert all('stroke-dasharray' in node.get('style', '') for node in neutral)
        assert page.evaluate("JSON.stringify(dcdcReport.model) === window.__transitionModelBefore")
        assert not errors and not blocked
    finally:
        page.evaluate("delete window.__transitionModelBefore")
        page.evaluate("dcdcReport.restoreDefaults()")


def _richest_series(model, spec):
    """The series with the most valid, finite points on this figure.

    The simulated demo's first series is an input phase that can end at the
    cold-start gate with no valid point; fixtures must not assume series[0]
    has data to toggle or edit.
    """
    def valid_count(series):
        ids = set(series["point_ids"])
        return sum(1 for point in model["points"] if point["point_id"] in ids and point["qualification"] == "valid"
                   and point.get(spec["y_key"]) is not None)
    return max(spec["series"], key=valid_count)


@pytest.mark.browser
def test_web03_real_legend_checkbox_and_band_share_export_selection(viewer, documents, tmp_path):
    def add_fixture_bands(model):
        spec = model["figures"][0]
        spec["lower_key"], spec["upper_key"] = "fixture_lower", "fixture_upper"
        for point in model["points"]:
            value = point.get(spec["y_key"])
            if value is not None:
                point["fixture_lower"], point["fixture_upper"] = value - .5, value + .5

    with _report_variant(viewer, documents, tmp_path, add_fixture_bands) as (page, model):
        spec = model["figures"][0]
        series = _richest_series(model, spec)
        key = format(series["vin_target_V"], "g")
        graph_id = "plot-" + spec["id"]
        selector = '#trace-options input[data-series="' + key + '"]'
        graph = page.locator("#" + graph_id)
        # Actual Plotly legend event, including its click-delay behavior, on the entry of a series that has points.
        graph.locator('.legend .traces').filter(has_text=series["label"]).first.locator('.legendtoggle').click()
        page.wait_for_function("key => !dcdcReport.state.selected_series.includes(key)", arg=key)
        page.evaluate("dcdcReport.whenIdle()")
        assert not page.locator(selector).is_checked()
        traces = page.evaluate("""({id,key}) => document.getElementById(id).data
            .filter(trace => trace.meta.conditionKey === key)
            .map(trace => ({band: !!trace.meta.isBand, visible: trace.visible}))""",
            {"id": graph_id, "key": key})
        assert len(traces) == 3 and sum(t["band"] for t in traces) == 2
        assert all(t["visible"] == "legendonly" for t in traces)
        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        assert all(row["vin_target_V"] != key for row in csv.DictReader(io.StringIO(exported["csv"])))
        # The ordinary checkbox restores both bounds and the measured line.
        page.locator(selector).check()
        page.wait_for_function("key => dcdcReport.state.selected_series.includes(key)", arg=key)
        page.evaluate("dcdcReport.whenIdle()")
        assert page.evaluate("""({id,key}) => document.getElementById(id).data
            .filter(trace => trace.meta.conditionKey === key).every(trace => trace.visible === true)""",
            {"id": graph_id, "key": key})
        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        assert any(row["vin_target_V"] == key for row in csv.DictReader(io.StringIO(exported["csv"])))


@pytest.mark.browser
def test_web05_web06_web08_scope_csv_and_log_bounds(viewer):
    page, _, _ = viewer
    page.evaluate("dcdcReport.restoreDefaults()")
    page.evaluate("dcdcReport.setView({selected_series:['24'],ranges:{'fig-efficiency':{x:[0.5,1]}}})")
    selected=page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
    visible=page.evaluate("dcdcReport.exportCSV('visible','fig-efficiency')")
    all_rows=list(csv.DictReader(io.StringIO(selected["csv"])))
    visible_rows=list(csv.DictReader(io.StringIO(visible["csv"])))
    assert len(all_rows) > len(visible_rows) > 0
    assert all(.5 <= float(p["Iout_A"]) <= 1 for p in visible_rows)
    headers=next(csv.reader(io.StringIO(selected["csv"])))
    assert len(headers) == len(set(headers))
    assert {"run_id","analysis_id","point_id","efficiency_pct","loss_W"} <= set(headers)
    assert "SYNTHETIC" in json.dumps(selected["metadata"])
    page.evaluate("dcdcReport.setView({log_current:true})")
    assert page.evaluate("dcdcReport.state.ranges['fig-efficiency'].x") == [.5, 1]
    log_rows=page.evaluate("dcdcReport.getSelectedPoints('visible','fig-efficiency')")
    assert log_rows and all(.5 <= p["Iout_A"] <= 1 for p in log_rows)
    log_export=page.evaluate("dcdcReport.exportCSV('visible','fig-efficiency')")
    assert log_export["metadata"]["axis_bounds"]["x"] == [.5, 1]
    page.evaluate("dcdcReport.setView({log_current:false})")
    assert page.evaluate("dcdcReport.state.ranges['fig-efficiency'].x") == [.5, 1]
    page.evaluate("dcdcReport.restoreDefaults()")


@pytest.mark.browser
def test_web08_log_mode_excludes_zero_and_negative_current_points_explicitly(viewer, documents, tmp_path):
    """WEB-08: a 0 A point and a negative-current point leave the log view explicitly.

    They are never replaced by a small positive number, the visible-range
    export bounds stay finite physical values, and both readings return in
    linear mode and remain reachable in the point explorer.
    """
    chosen = {}

    def nonpositive_fixture(model):
        spec = next(f for f in model["figures"] if f["id"] == "fig-efficiency")
        series = _richest_series(model, spec)
        rows = [p for p in model["points"] if p["point_id"] in series["point_ids"] and p["qualification"] == "valid"
                and p.get("efficiency_pct") is not None and (p.get("Iout_A") or 0) > 0]
        assert len(rows) >= 4, "the fixture needs positive points left after the two edits"
        zero, negative = rows[0], rows[1]
        zero.update(Iout_A=0., iout_target_A=0.)
        negative.update(Iout_A=-.0004)
        chosen.update(zero=zero["point_id"], negative=negative["point_id"], key=format(series["vin_target_V"], "g"),
                      positive=sorted(p["Iout_A"] for p in rows[2:]))

    with _report_variant(viewer, documents, tmp_path, nonpositive_fixture) as (page, model):
        graph = "document.getElementById('plot-fig-efficiency')"

        def trace_x():
            return page.evaluate(f"key => {graph}.data.find(t => t.meta.conditionKey === key && !t.meta.isBand).x", chosen["key"])

        def visible_ids():
            return {p["point_id"] for p in page.evaluate("dcdcReport.getSelectedPoints('visible','fig-efficiency')")}

        excluded = {chosen["zero"], chosen["negative"]}
        page.evaluate("dcdcReport.setView({selected_series:[arguments[0]]})".replace("arguments[0]", json.dumps(chosen["key"])))
        page.evaluate("dcdcReport.whenIdle()")
        assert page.evaluate(f"{graph}._fullLayout.xaxis.type") == "linear"
        assert 0 in trace_x() and -.0004 in trace_x()
        assert page.evaluate(f"{graph}._fullLayout.xaxis.range")[0] <= -.0004, "default limits include the negative reading"
        assert excluded <= visible_ids()
        # Invalid or unmeasured points are gaps in every mode; only the two
        # nonpositive readings may be added to them by the log view.
        linear_gaps = trace_x().count(None)

        page.evaluate("dcdcReport.setView({log_current:true})")
        page.evaluate("dcdcReport.whenIdle()")
        assert page.evaluate(f"{graph}._fullLayout.xaxis.type") == "log"
        xs = trace_x()
        assert xs.count(None) == linear_gaps + 2, "the two nonpositive readings become gaps"
        assert sorted(x for x in xs if x is not None) == chosen["positive"], "no value is substituted or shifted"
        assert "2 nonpositive-current point(s) omitted from this log view" in page.locator("#status-fig-efficiency").inner_text()
        assert not (excluded & visible_ids())
        selected = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        rows = {row["point_id"]: row for row in csv.DictReader(io.StringIO(selected["csv"]))}
        assert rows[chosen["zero"]]["Iout_A"] == "0" and rows[chosen["negative"]]["Iout_A"] == "-0.0004"
        visible = page.evaluate("dcdcReport.exportCSV('visible','fig-efficiency')")
        bounds = visible["metadata"]["axis_bounds"]["x"]
        assert len(bounds) == 2 and all(math.isfinite(b) for b in bounds) and 0 < bounds[0] < bounds[1]
        assert bounds[0] <= chosen["positive"][0] and bounds[1] >= chosen["positive"][-1]
        assert visible["metadata"]["point_count"] == len(list(csv.DictReader(io.StringIO(visible["csv"]))))
        assert not (excluded & {row["point_id"] for row in csv.DictReader(io.StringIO(visible["csv"]))})
        assert "nonpositive points excluded for log current" in visible["metadata"]["scope_description"]
        # A zoom crossing zero cannot exist on a log axis: it is dropped, never turned into NaN bounds.
        page.evaluate("dcdcReport.setView({ranges:{'fig-efficiency':{x:[-0.001,1]}}})")
        page.evaluate("dcdcReport.whenIdle()")
        assert page.evaluate("dcdcReport.state.ranges['fig-efficiency']?.x ?? null") is None
        assert all(math.isfinite(v) for v in page.evaluate(f"{graph}._fullLayout.xaxis.range"))

        page.evaluate("dcdcReport.setView({log_current:false})")
        page.evaluate("dcdcReport.whenIdle()")
        assert 0 in trace_x() and -.0004 in trace_x()
        assert excluded <= visible_ids()
        page.evaluate("id => dcdcReport.showPoint(id)", chosen["negative"])
        assert page.locator("#point-picker").input_value() == chosen["negative"]
        assert "-0.4 mA" in page.locator("#point-measurements").inner_text()
        page.evaluate("id => dcdcReport.showPoint(id)", chosen["zero"])
        assert "0 mA" in page.locator("#point-measurements").inner_text()
        assert page.evaluate("id => dcdcReport.model.points.find(p => p.point_id === id).Iout_A", chosen["zero"]) == 0
        page.evaluate("dcdcReport.restoreDefaults()")


@pytest.mark.browser
def test_web07_low_efficiency_visible_and_hover_rounding_keeps_csv_precision(viewer, documents, tmp_path):
    chosen = {}
    def low_efficiency_fixture(model):
        spec = next(f for f in model["figures"] if f["id"] == "fig-efficiency")
        candidates = {pid for series in spec["series"] for pid in series["point_ids"]}
        point = next(p for p in model["points"] if p["point_id"] in candidates
                     and p["qualification"] == "valid" and p.get("Iout_A", 0) > 0)
        point.update(efficiency_pct=39.1575, Iout_A=.123456789, Pin_W=1000000)
        chosen["point_id"] = point["point_id"]

    with _report_variant(viewer, documents, tmp_path, low_efficiency_fixture) as (page, _):
        bounds = page.evaluate("document.getElementById('plot-fig-efficiency')._fullLayout.yaxis.range")
        assert bounds[0] < 39.1575 < bounds[1], "Default range must include the measured low-efficiency point"
        coordinate = _hover_point(page, chosen["point_id"])
        hover = page.locator('#plot-fig-efficiency .hoverlayer').text_content()
        assert 'Path efficiency: 39.16%' in hover
        assert 'Output current: 123.5 mA' in hover
        assert 'Input power' not in hover and 'Aggregated point result' not in hover
        page.mouse.click(coordinate["x"], coordinate["y"])
        assert page.locator('#point-picker').input_value() == chosen["point_id"]
        detail = page.locator('#point-measurements').inner_text()
        assert '123.457 mA' in detail and '1000000 W' in detail
        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        row = next(p for p in csv.DictReader(io.StringIO(exported["csv"]))
                   if p["point_id"] == chosen["point_id"])
        assert row["Iout_A"] == '0.123456789'
        assert row["efficiency_pct"] == '39.1575'


@pytest.mark.browser
def test_web_compact_hover_desktop_mobile_and_alternate_axis(viewer):
    """Real pointer hover stays compact; detail access and exported evidence survive."""
    page, _, _ = viewer
    page.evaluate("dcdcReport.restoreDefaults()")
    chosen = page.evaluate("""() => {
        const spec = dcdcReport.model.figures.find(f => f.id === 'fig-efficiency');
        const series = spec.series.find(s => s.point_ids.some(id => {
            const p = dcdcReport.model.points.find(row => row.point_id === id);
            return p.qualification === 'valid' && p.Iout_A > 0 && Number.isFinite(p.efficiency_pct);
        }));
        const rows = series.point_ids.map(id => dcdcReport.model.points.find(p => p.point_id === id))
            .filter(p => p.qualification === 'valid' && p.Iout_A > 0 && Number.isFinite(p.efficiency_pct));
        return {point: rows[Math.floor(rows.length / 2)], key: String(series.selection_key ?? series.vin_target_V ?? series.id)};
    }""")
    point = chosen["point"]
    page.evaluate("key => dcdcReport.setView({selected_series:[key]})", chosen["key"])
    try:
        for width, height in ((1365, 980), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("""async () => {
                await dcdcReport.whenIdle();
                await Promise.all([...dcdcReport.graphs.values()].map(graph => Plotly.Plots.resize(graph)));
            }""")
            coordinate = _hover_point(page, point["point_id"])
            tooltip = page.locator('#plot-fig-efficiency .hoverlayer .hovertext')
            box = tooltip.bounding_box()
            # Compact: at most four 12 px lines, none longer than 60 characters, in the report's
            # hover type size. A pixel width would measure the fallback font, not the label: CI's
            # Chromium (DejaVu Sans) drew the same text 347 px wide where the bench Pi's UI font
            # gave 300 px. Chromium reports fractional layout boxes; allow sub-pixel rounding.
            texts = tooltip.locator('tspan.line').all_text_contents()
            font_size = tooltip.evaluate("el => parseFloat(getComputedStyle(el.querySelector('text')).fontSize)")
            assert box and box["height"] <= 101 and font_size <= 13, (box, font_size)
            assert texts and max(len(text) for text in texts) <= 60, texts
            assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1, box
            assert box["y"] >= -1 and box["y"] + box["height"] <= height + 1, box
            # Condition, x, y — plus one labeled line only where a readback budget was evaluated (UNC-02).
            lines = tooltip.locator('tspan.line').count()
            has_band = "Expanded uncertainty:" in tooltip.text_content()
            assert lines == (4 if has_band else 3), (lines, tooltip.text_content())
            assert tooltip.locator('.name').count() == 0, "Duplicate series bubble must be absent"
            colors = tooltip.evaluate("""el => ({background: getComputedStyle(el.querySelector('path')).fill,
                text: getComputedStyle(el.querySelector('text')).fill})""")
            assert colors == {"background": "rgb(255, 255, 255)", "text": "rgb(24, 48, 71)"}
            assert 'Output current:' in tooltip.text_content()
            assert 'Path efficiency:' in tooltip.text_content()
            page.mouse.click(coordinate["x"], coordinate["y"])
            assert page.locator('#point-picker').input_value() == point["point_id"]
            assert page.locator('#point-measurements tbody tr').count() == 9

        page.select_option('#x-select', 'Pout_W')
        page.evaluate("dcdcReport.whenIdle()")
        _hover_point(page, point["point_id"])
        hover = page.locator('#plot-fig-efficiency .hoverlayer').text_content()
        assert 'Output power:' in hover and 'Output current:' not in hover
        assert 'Path efficiency:' in hover
        displayed_power = re.search(r'Output power:\s*(-?\d+(?:\.\d+)?)\s*W', hover)
        assert displayed_power and abs(float(displayed_power.group(1)) - point['Pout_W']) <= .000501

        page.locator('#point-picker').focus()
        page.keyboard.press('End')
        page.keyboard.press('Enter')
        selected = page.locator('#point-picker').input_value()
        assert selected == page.locator('#point-picker option').last.get_attribute('value')
        assert selected in page.locator('#point-detail').inner_text()
        assert 'Input voltage' in page.locator('#point-measurements').inner_text()
        assert 'Input current' in page.locator('#point-measurements').inner_text()

        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        row = next(row for row in csv.DictReader(io.StringIO(exported["csv"])) if row["point_id"] == point["point_id"])
        for field in ('Iout_A', 'efficiency_pct', 'Pin_W', 'Pout_W', 'Vin_V', 'Iin_A'):
            assert float(row[field]) == point[field]
        assert page.evaluate("id => dcdcReport.model.points.find(p => p.point_id === id)", point["point_id"]) == point
    finally:
        page.set_viewport_size({"width": 1365, "height": 980})
        page.evaluate("dcdcReport.restoreDefaults()")


@pytest.mark.browser
def test_web09_web10_evidence_and_issued_summary(viewer):
    page, _, _ = viewer
    summary=page.locator('#summary').inner_text()
    page.evaluate("dcdcReport.setView({selected_series:['30'],metric:'fig-loss'})")
    assert page.locator('#summary').inner_text() == summary
    assert page.locator('a[href="#fig-efficiency"]').count() >= 1
    page.select_option('#point-picker', index=1)
    assert page.locator('#raw-evidence').inner_text().strip()
    assert "p0002" in page.locator('#point-picker').input_value()
    view=page.evaluate("dcdcReport.saveView()")
    assert view["analysis_id"] and view["run_id"]
    page.evaluate("dcdcReport.restoreDefaults()")


@pytest.mark.browser
def test_web12_imported_text_markdown_and_embedded_json_cannot_execute(viewer, documents, tmp_path):
    """M1 text paths only; rich asset upload/editing remains an M4 gate."""
    from dcdc_bench.reporting import renderer
    attack = ('</script><img src="missing" onerror="window.__dcdcInjected=true">'
              '<svg onload="window.__dcdcInjected=true"></svg>'
              '[execute](javascript:window.__dcdcInjected=true)')
    selected = {}
    def hostile_model(model):
        model["dut"].setdefault("identity", {})["model"] = attack
        model["summary"] = [attack]
        model.setdefault("bench", {}).setdefault("source", {})["instrument_id"] = attack
        for spec in model["figures"]:
            spec["title"] = attack
            spec["caption"] = attack
            for series in spec["series"]:
                series["label"] = attack
        point = model["points"][0]
        selected["point_id"] = point["point_id"]
        point["reason"] = attack
        model.setdefault("raw_samples", {})[point["point_id"]] = [
            {"raw_response": attack, "asset_name": attack, "value": None}]

    page, errors, blocked = viewer
    original = documents[0] / "report.html"
    model = json.loads((documents[0] / "report_model.json").read_text())
    hostile_model(model)
    # Run the production Markdown escaper through the actual document parser.
    # Reuse the same browser tab; no duplicate Chrome/static-render process.
    parsed = subprocess.run([renderer._quarto(), "pandoc", "--from", "markdown", "--to", "html"],
        input=renderer._body(model), capture_output=True, text=True, timeout=60, check=True)
    fragment = tmp_path / "escaped-document-text.html"
    fragment.write_text('<!doctype html><meta charset="utf-8"><body>' + parsed.stdout + '</body>',
                        encoding="utf-8")
    try:
        page.goto(fragment.as_uri(), wait_until="load", timeout=60000)
        assert page.evaluate("window.__dcdcInjected === undefined")
        assert page.locator('img[onerror], svg[onload], a[href^="javascript:"]').count() == 0
        assert attack in page.locator('body').inner_text()
    finally:
        _open_report(page, original)

    with _report_variant(viewer, documents, tmp_path, hostile_model) as (page, _):
        page.select_option('#point-picker', selected["point_id"])
        assert attack in page.locator('#raw-evidence').inner_text()
        assert attack in page.locator('#trace-options').inner_text()
        assert page.evaluate("window.__dcdcInjected === undefined")
        assert page.locator('img[onerror], svg[onload], a[href^="javascript:"]').count() == 0
        exported = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
        assert exported["metadata"]["dut"] == attack
        # Text stays evidence; encoding prevents script termination instead of
        # deleting or rewriting user-supplied observations.
        assert attack == page.evaluate("dcdcReport.model.dut.identity.model")
    assert not errors
    assert not blocked


@pytest.mark.browser
def test_exp01_exported_svg_png_context(viewer, tmp_path):
    page, _, _ = viewer
    import base64
    from urllib.parse import unquote
    svg_url=page.evaluate("dcdcReport.exportFigure('fig-efficiency','svg')")
    encoded=svg_url.split(',',1)[1]
    svg=base64.b64decode(encoded).decode() if ';base64,' in svg_url else unquote(encoded)
    assert 'SYNTHETIC' in svg and '12T12-4A' in svg and 'fig-efficiency' in svg
    assert 'source-to-load-terminal' in svg  # the demo mock bench mirrors the physical bench's local-sense boundary
    png=page.evaluate("dcdcReport.exportFigure('fig-efficiency','png')")
    assert png.startswith('data:image/png;base64,')
    assert len(base64.b64decode(png.split(',',1)[1])) > 10000
    # Exercise the actual button and both saved files, including the metadata
    # sidecar, rather than only inspecting the export API's return value.
    expected = page.evaluate("dcdcReport.exportCSV('selected','fig-efficiency')")
    with page.expect_download(predicate=lambda item: item.suggested_filename.endswith('-metadata.json')) as metadata:
        with page.expect_download(predicate=lambda item: item.suggested_filename.endswith('.csv')) as data:
            page.locator('#view-fig-efficiency button[data-action="selected"]').click()
    data.value.save_as(tmp_path / 'selected.csv')
    metadata.value.save_as(tmp_path / 'metadata.json')
    assert (tmp_path / 'selected.csv').read_bytes().decode('utf-8') == expected['csv']
    assert json.loads((tmp_path / 'metadata.json').read_text()) == expected['metadata']


@pytest.mark.pdf
def test_pdf01_pdf03_vector_text_and_shared_identity(documents):
    from pypdf import PdfReader
    for directory in documents:
        model=json.loads((directory/'report_model.json').read_text())
        reader=PdfReader(directory/'report.pdf')
        text='\n'.join(page.extract_text() for page in reader.pages)
        assert 'SYNTHETIC' in text and model['run_id'] in text and model['analysis_id'] in text
        assert '12T12-4A' in text
        for number, spec in enumerate(model['figures'],1):
            assert re.search(r'Figure\s+'+str(number),text), spec['id']
        for page in reader.pages:
            assert len(page.extract_text().strip()) > 60
            # This fixture contains only line figures and text; any raster is a regression.
            assert not list(page.images)
        for figure in (directory/'figures').glob('*.pdf'):
            pdf=PdfReader(figure)
            assert not list(pdf.pages[0].images)
            content=pdf.pages[0].get_contents().get_data()
            assert re.search(rb'\s[mlc]\s',content), 'Expected vector drawing operators'


@pytest.mark.pdf
def test_pdf_build_manifest_reports_real_success(documents):
    import hashlib
    for directory in documents:
        manifest=json.loads((directory/'build_manifest.json').read_text())
        assert manifest['status'] == 'success'
        assert manifest['versions']['quarto'] == '1.10.18'
        for fmt in ('html','pdf'):
            artifact=directory/f'report.{fmt}'
            assert manifest['artifacts'][fmt]['sha256'] == hashlib.sha256(artifact.read_bytes()).hexdigest()


@pytest.mark.pdf
def test_pdf_letter_pages_carry_identity_and_page_one_reads_in_plain_words(documents):
    """Brief §12.6: page numbers and run identity on every page; §12.3: the first page is a summary
    whose identity block reads in plain words, with the local recording time and identifiers last."""
    from pypdf import PdfReader
    for directory in documents:
        model = json.loads((directory / 'report_model.json').read_text())
        reader = PdfReader(directory / 'report.pdf')
        assert json.loads((directory / 'build_manifest.json').read_text())['paper'] == 'letter'
        for page in reader.pages:
            assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == (612, 792)
        pages = [' '.join((page.extract_text() or '').split()) for page in reader.pages]
        for number, text in enumerate(pages, 1):
            assert model['run_id'] in text and f"Report revision {model['report_revision']}" in text
            assert f'Page {number} of {len(pages)}' in text
            assert model['evidence_label'] in text
        first = pages[0]
        for label in ('About this report', 'Device tested', 'Equipment', 'Measurement points', 'Recorded',
                      'Evidence', 'Traceability', 'these match this document to its raw data files'):
            assert label in first, label
        # The header band converts the run's UTC start to the bench computer's zone and names it.
        assert re.search(r'Recorded [A-Z][a-z]{2} \d{1,2}, \d{4}, \d{2}:\d{2} \S+', first), first[:400]
        assert 'bench-computer local time; evidence files record UTC' in first
        assert 'Summary' in first and 'Device tested' in first
        assert re.search(r'Figure 1\. ', '\n'.join(pages)), 'captions read "Figure N." and sit below the figure'
        assert model['analysis_id'] in first and 'settled-dc' in first
