"""WEB-11 in a real offline browser: marker positions survive resize and reload; keyboard access works.

Marked ``browser``: needs Playwright's Chromium and is excluded on the bench Pi.
"""
import io
import json
import math
from pathlib import Path

import pytest

from dcdc_bench.reporting.renderer import TEMPLATES
from dcdc_bench.reporting.sensor_placement import sensor_placement_html

pytestmark = pytest.mark.browser

MARKERS = [{"sensor_id": "TC1", "x_norm": 0.25, "y_norm": 0.5, "label": "Case top center <b>not markup</b>"},
           {"sensor_id": "TC2", "x_norm": 0.9, "y_norm": 0.1, "label": "Right edge"},
           {"sensor_id": "AMB", "x_norm": 0.05, "y_norm": 0.95, "label": "Ambient reference"}]


def _fixture(tmp_path: Path) -> Path:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (110, 120, 130)).save(buffer, format="PNG")
    (tmp_path / "photo.png").write_bytes(buffer.getvalue())
    annotations = {"schema_version": "1.0", "image_asset_sha256": "f" * 64, "markers": MARKERS}
    asset = {"media_type": "image/png", "width": 400, "height": 300, "original_name": "photo.png", "caption": "Fixture"}
    payload = {"model": {"run_id": "fixture", "analysis_id": "a", "report_revision": "r0001", "dut": {},
                         "figures": [], "points": [], "evidence_label": "SYNTHETIC"}, "colors": ["#0072B2"],
               "plotly_js_version": "none"}
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<style>' + (TEMPLATES / "theme/report.css").read_text() + '</style></head><body><main>'
            + sensor_placement_html(annotations, asset, "photo.png")
            + '<p id="report-error"></p><script type="application/json" id="dcdc-report-data">' + json.dumps(payload)
            + '</script><script>' + (TEMPLATES / "web/report.js").read_text() + '</script></main></body></html>')
    page = tmp_path / "sensor.html"
    page.write_text(html, encoding="utf-8")
    return page


RATIOS = """() => {
  const rect = document.querySelector('img.sensor-image').getBoundingClientRect();
  return [...document.querySelectorAll('.sensor-marker')].map(marker => {
    const box = marker.getBoundingClientRect();
    return [(box.left + box.width / 2 - rect.left) / rect.width, (box.top + box.height / 2 - rect.top) / rect.height];
  });
}"""


def _assert_on_spot(ratios):
    assert len(ratios) == len(MARKERS)
    for (x, y), marker in zip(ratios, MARKERS):
        assert math.isclose(x, marker["x_norm"], abs_tol=0.01) and math.isclose(y, marker["y_norm"], abs_tol=0.01)


def test_WEB11_markers_stay_on_the_same_physical_spot_across_resize_and_reload(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    fixture = _fixture(tmp_path)
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith("file://") else route.abort())
        page.goto(fixture.as_uri())
        page.wait_for_selector('.sensor-placement-block[data-sensor-ready="true"]')
        wide_image = page.evaluate("() => document.querySelector('img.sensor-image').getBoundingClientRect().width")
        _assert_on_spot(page.evaluate(RATIOS))
        page.set_viewport_size({"width": 420, "height": 800})
        page.wait_for_timeout(400)
        narrow_image = page.evaluate("() => document.querySelector('img.sensor-image').getBoundingClientRect().width")
        assert narrow_image < wide_image, "the photograph actually shrank with the viewport"
        _assert_on_spot(page.evaluate(RATIOS))
        page.reload()
        page.wait_for_selector('.sensor-placement-block[data-sensor-ready="true"]')
        _assert_on_spot(page.evaluate(RATIOS))
        # Keyboard access: focus the first marker, arrow to the next, Enter selects and describes it.
        page.focus(".sensor-marker")
        page.keyboard.press("ArrowRight")
        assert page.evaluate("() => document.activeElement.dataset.sensorId") == "TC2"
        page.keyboard.press("Enter")
        detail = page.inner_text(".sensor-marker-detail")
        assert "TC2" in detail and "Right edge" in detail and "x=0.9000" in detail
        assert page.get_attribute(".sensor-marker[data-sensor-id='TC2']", "aria-pressed") == "true"
        # WEB-12: untrusted label text renders as text, never as markup.
        assert page.evaluate("() => document.querySelectorAll('.sensor-marker-table b').length") == 0
        assert "<b>not markup</b>" in page.inner_text(".sensor-marker-table")
        browser.close()
