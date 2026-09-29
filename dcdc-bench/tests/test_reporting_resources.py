"""Static rendering uses bounded, sequential offline work; no browser is started."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from dcdc_bench.reporting import renderer


def test_static_exports_use_one_offline_session_and_sequential_images(tmp_path, monkeypatch):
    events = []
    options = []

    class Browser:
        def __init__(self, **kwargs):
            options.append(kwargs)

        async def open(self):
            events.append("open")

        async def write_fig(self, figure, *, path, opts, cancel_on_error):
            assert cancel_on_error is True
            assert opts["format"] == path.suffix[1:]
            events.append(("begin", figure, path.name))
            await asyncio.sleep(0)
            path.write_text("vector test fixture")
            events.append(("end", figure, path.name))

        async def close(self):
            events.append("close")

    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace(Kaleido=Browser))
    monkeypatch.setattr(renderer, "_plot_figure", lambda model, spec, number: spec["id"])
    model = {"figures": [{"id": "fig-one"}, {"id": "fig-two"}]}
    asyncio.run(renderer._write_static_figures(model, tmp_path))

    assert len(options) == 1
    assert options[0]["n"] == 1
    assert options[0]["mathjax"] is False
    assert options[0]["enable_gpu"] is False
    assert options[0]["enable_extensions"] is False
    assert options[0]["plotlyjs"].startswith("file:")
    assert events == ["open",
        ("begin", "fig-one", "fig-one.svg"), ("end", "fig-one", "fig-one.svg"),
        ("begin", "fig-one", "fig-one.pdf"), ("end", "fig-one", "fig-one.pdf"),
        ("begin", "fig-two", "fig-two.svg"), ("end", "fig-two", "fig-two.svg"),
        ("begin", "fig-two", "fig-two.pdf"), ("end", "fig-two", "fig-two.pdf"), "close"]


@pytest.mark.parametrize("failure", ["open", "image", "empty", "timeout"])
def test_static_failure_is_raised_and_browser_close_is_attempted(tmp_path, monkeypatch, failure):
    events = []

    class Browser:
        def __init__(self, **kwargs):
            pass

        async def open(self):
            if failure == "open":
                raise RuntimeError("startup failed")

        async def write_fig(self, *args, **kwargs):
            if failure == "image":
                raise RuntimeError("image failed")
            if failure == "timeout":
                await asyncio.sleep(1)

        async def close(self):
            events.append("close")

    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace(Kaleido=Browser))
    monkeypatch.setattr(renderer, "_plot_figure", lambda *args: {})
    monkeypatch.setattr(renderer, "STATIC_IMAGE_TIMEOUT_S", .01)
    error = {"open": RuntimeError, "image": RuntimeError,
             "empty": renderer.ReportRenderError, "timeout": TimeoutError}[failure]
    with pytest.raises(error):
        asyncio.run(renderer._write_static_figures({"figures": [{"id": "fig-one"}]}, tmp_path))
    assert events == ["close"]


def test_empty_figure_registry_does_not_construct_browser(tmp_path, monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("An empty registry must not start a browser")

    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace(Kaleido=unexpected))
    asyncio.run(renderer._write_static_figures({"figures": []}, tmp_path))
