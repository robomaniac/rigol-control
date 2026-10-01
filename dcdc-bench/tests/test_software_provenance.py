"""Software identity remains explicit across edited trees and later rendering."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dcdc_bench.runner import _git_provenance, _provenance


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is optional for source archives")
def test_git_commit_distinguishes_clean_modified_and_untracked_software(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-c", "user.name=Provenance fixture",
            "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null", *args], cwd=tmp_path,
            capture_output=True, text=True, check=True, timeout=3)

    git("init", "--quiet")
    source = tmp_path / "source.py"
    source.write_text("version = 1\n")
    git("add", "source.py")
    git("commit", "--quiet", "-m", "Synthetic test fixture")
    expected = git("rev-parse", "HEAD").stdout.strip()
    assert _git_provenance(tmp_path) == {"commit": expected, "dirty": False, "status": "available"}

    source.write_text("version = 2\n")
    assert _git_provenance(tmp_path) == {"commit": expected, "dirty": True, "status": "available"}
    source.write_text("version = 1\n")
    (tmp_path / "new-adapter.py").write_text("# Untracked source must not look like a clean commit.\n")
    assert _git_provenance(tmp_path)["dirty"] is True
    assert git("status", "--porcelain=v1").stdout == "?? new-adapter.py\n"


@pytest.mark.parametrize("error", [FileNotFoundError("git"),
    subprocess.TimeoutExpired("git", 3), subprocess.CalledProcessError(128, "git")])
def test_git_unavailable_is_unknown_not_clean(monkeypatch, tmp_path, error):
    def unavailable(*args, **kwargs):
        raise error
    monkeypatch.setattr(subprocess, "run", unavailable)
    assert _git_provenance(tmp_path) == {"commit": None, "dirty": None, "status": "unavailable"}


def test_acquisition_provenance_keeps_git_and_exact_source_snapshot(monkeypatch):
    import dcdc_bench.runner as runner
    identity = {"commit": "a" * 40, "dirty": True, "status": "available"}
    monkeypatch.setattr(runner, "_git_provenance", lambda directory: identity)
    record = _provenance()
    assert record["git"] == identity
    assert record["source_files_sha256"]["runner.py"] == hashlib.sha256(
        Path(runner.__file__).read_bytes()).hexdigest()


def test_render_manifest_hashes_actual_renderer_theme_and_interaction_source(tmp_path, monkeypatch):
    """Failure metadata still identifies the intended build without fake outputs."""
    from dcdc_bench.reporting import renderer
    templates = tmp_path / "templates"
    (templates / "theme").mkdir(parents=True)
    (templates / "web").mkdir()
    (templates / "characterization.qmd").write_text("fixture template\n")
    theme = templates / "theme/report.css"
    tables = templates / "theme/print-tables.typ"
    print_theme = templates / "theme/print-theme.typ"
    partial = templates / "theme/typst-show.typ"
    script = templates / "web/report.js"
    head_script = templates / "web/report-head.js"
    theme.write_text("body { color: blue; }\n")
    tables.write_text("#show table: it => it\n")
    print_theme.write_text("#let dcdc-report(doc) = doc\n")
    partial.write_text("#show: doc => dcdc-report(doc)\n")
    script.write_text("/* first interaction source */\n")
    head_script.write_text("/* first report-head source */\n")
    monkeypatch.setattr(renderer, "TEMPLATES", templates)
    monkeypatch.setattr(renderer, "_browser_path", lambda: None)
    monkeypatch.setitem(sys.modules, "plotly.offline", SimpleNamespace(
        get_plotlyjs=lambda: "/* No browser or actual plotting runtime in this test. */",
        get_plotlyjs_version=lambda: "test-only"))
    def unavailable():
        raise renderer.ReportRenderError("No renderer binaries in provenance test")
    monkeypatch.setattr(renderer, "_quarto", unavailable)
    model = {"run_id": "synthetic-fixture", "analysis_id": "test-only",
             "dut": {}, "points": [], "figures": [], "metrics": []}

    def record(directory):
        with pytest.raises(renderer.ReportRenderError, match="No renderer binaries"):
            renderer.render_report(model, directory, formats=("html",))
        manifest = json.loads((directory / "build_manifest.json").read_text())
        assert manifest["status"] == "failed"
        assert not (directory / "report.html").exists()
        return manifest["render_sources_sha256"]

    first = record(tmp_path / "r0001")
    expected = {"renderer.py": Path(renderer.__file__), "report.css": theme, "print-theme.typ": print_theme,
                "print-tables.typ": tables, "typst-show.typ": partial, "report.js": script,
                "report-head.js": head_script}
    assert first == {name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for name, path in expected.items()}
    theme.write_text("body { color: purple; }\n")
    tables.write_text("#show table: it => block(breakable: false, it)\n")
    print_theme.write_text("#let dcdc-report(doc) = { set page(paper: \"a4\"); doc }\n")
    script.write_text("/* second interaction source */\n")
    head_script.write_text("/* second report-head source */\n")
    second = record(tmp_path / "r0002")
    assert first["renderer.py"] == second["renderer.py"]
    assert first["typst-show.typ"] == second["typst-show.typ"]
    assert first["report.css"] != second["report.css"]
    assert first["print-tables.typ"] != second["print-tables.typ"]
    assert first["print-theme.typ"] != second["print-theme.typ"]
    assert first["report.js"] != second["report.js"]
    assert first["report-head.js"] != second["report-head.js"]
