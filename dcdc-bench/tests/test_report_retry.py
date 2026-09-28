"""Report retries preserve evidence and independent document outcomes."""
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from dcdc_bench.reporting import renderer


def test_vector_retry_checks_hashes_and_reuses_only_same_model(tmp_path, monkeypatch):
    calls = []

    async def render(model, directory):
        calls.append(copy.deepcopy(model))
        for extension in ("svg", "pdf"):
            (directory / ("fig-one." + extension)).write_text(str(model["value"]))

    monkeypatch.setattr(renderer, "_write_static_figures", render)
    model = {"figures": [{"id": "fig-one"}], "report_revision": "r0001", "value": 12.34}

    def revision(number):
        model["report_revision"] = f"r{number:04d}"
        directory = tmp_path / "reports" / model["report_revision"] / "figures"
        directory.mkdir(parents=True)
        return renderer._static_figures(model, directory), directory

    first, original = revision(1)
    second, retried = revision(2)
    assert not first["reused"] and second["reused"] and len(calls) == 1
    assert (original / "fig-one.svg").read_bytes() == (retried / "fig-one.svg").read_bytes()
    cache = tmp_path / "reports/.figure-cache" / first["key"]
    (cache / "fig-one.pdf").write_text("damaged cache")
    third, _ = revision(3)
    assert not third["reused"] and len(calls) == 2
    model["value"] = 11.11
    fourth, _ = revision(4)
    assert fourth["key"] != first["key"] and not fourth["reused"] and len(calls) == 3
    assert (original / "fig-one.svg").read_text() == "12.34"


def test_html_timeout_still_builds_pdf_and_never_claims_html_success(tmp_path, monkeypatch):
    model = {"run_id": "retry-test", "analysis_id": "a-test", "dut": {},
             "points": [], "figures": [], "metrics": [], "summary": []}
    calls = []
    monkeypatch.setattr(renderer, "_quarto", lambda: "quarto-fixture")
    monkeypatch.setattr(renderer, "_browser_path", lambda: None)
    monkeypatch.setattr(renderer, "_static_figures", lambda *args: {"reused": False})

    def compile(command, **kwargs):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="fixture", stderr="", returncode=0)
        fmt = command[-1]
        calls.append(fmt)
        if fmt == "html":
            (Path(kwargs["cwd"]) / "report.html").write_text("incomplete")
            raise subprocess.TimeoutExpired(command, 1)
        (Path(kwargs["cwd"]) / "report.pdf").write_bytes(b"PDF fixture only")
        return SimpleNamespace(stdout="fixture", stderr="", returncode=0)

    monkeypatch.setattr(renderer.subprocess, "run", compile)
    with pytest.raises(renderer.ReportRenderError, match="html"):
        renderer.render_report(model, tmp_path)
    manifest = json.loads((tmp_path / "build_manifest.json").read_text())
    assert calls == ["html", "typst"]
    assert manifest["artifacts"]["html"]["status"] == "failed"
    assert manifest["artifacts"]["pdf"]["status"] == "success"
    assert not (tmp_path / "report.html").exists()
    assert (tmp_path / "report.pdf").is_file()
