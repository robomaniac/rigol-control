"""Editor page boundaries: upload → validate → save through JobService, no GUI server or hardware."""
import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from dcdc_bench import annotation_editor
from dcdc_bench.annotation_editor import (asset_summary, asset_url, eligible_jobs, existing_annotations,
                                          image_assets)
from dcdc_bench.annotations import (AnnotationError, annotation_document, marker_overlay_svg, nearest_marker,
                                    new_sensor_id, normalized_point, nudge_marker)
from dcdc_bench.attachments import AssetHashMismatch, AssetStore, AttachmentRejected
from dcdc_bench.job_service import JobService, worker
from dcdc_bench.storage import RunStore, atomic_json, verify_integrity


def png(width=40, height=30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 90, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))
    monkeypatch.setenv("DCDC_JOB_LAUNCHER", "detached")
    return JobService(tmp_path / "workspace")


def mock_preview(service):
    profiles = service.list_profiles()
    bench = next(name for name in profiles["bench"] if service.load_profile("bench", name)["mode"] == "mock")
    recipe = next(name for name in profiles["recipe"] if service.load_profile("recipe", name)["execution_mode"] == "mock")
    return service.preview(profiles["dut"][0], bench, recipe)


def finished_job(service, monkeypatch):
    """A job whose acquisition is finalized and verified OFF, without any worker or renderer."""
    preview = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(preview["plan_hash"])["job_id"]
    job = service._job(job_id)
    path = job / "runs" / "fixture"
    store = RunStore(path)
    run = {"run_id": "fixture", "created_utc": "2026-01-01T00:00:00+00:00", "duration_s": 1., "data_source": "simulated",
           "execution_status": "completed", "points": [],
           "shutdown": {role: {"state": "OFF", "verified": True} for role in ("source", "load")}}
    store.initialize({}, preview["plan"], run)
    store.finalize(run)
    state = json.loads((job / "job.json").read_text())
    state.update(state="completed", run_dir=str(path))
    atomic_json(job / "job.json", state)
    return job_id, job, path


def test_editor_module_imports_no_gui_server_at_module_level():
    tree = ast.parse(Path(annotation_editor.__file__).read_text())
    imported = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    names = {alias.name for node in imported for alias in node.names} | {
        node.module for node in imported if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.startswith("nicegui") for name in names)
    assert not any(name.startswith(("dcdc_bench.runner", "dcdc_bench.real_backend", "benchctl")) for name in names)


def test_only_finished_jobs_with_preserved_evidence_are_offered():
    jobs = [{"job_id": "a", "state": "completed", "run_dir": "/x"}, {"job_id": "b", "state": "acquiring", "run_dir": "/y"},
            {"job_id": "c", "state": "failed", "run_dir": None}, {"job_id": "d", "state": "aborted", "run_dir": "/z"},
            {"job_id": "e", "state": "reporting", "run_dir": "/w"}]
    assert [job["job_id"] for job in eligible_jobs(jobs)] == ["a", "d"]


def test_upload_validate_and_save_flow_through_the_job_service(service, monkeypatch):
    job_id, job, path = finished_job(service, monkeypatch)
    before = (path / "integrity.json").read_bytes(), (path / "attachments/manifest.json").read_bytes()
    monkeypatch.setattr("dcdc_bench.runner.run_mock", lambda *a, **k: pytest.fail("the editor must never acquire"))
    data = png()
    entry = service.add_attachment(job_id, "Case top.png", data, caption="Case top, sensors under tape")
    assert entry["sha256"] == hashlib.sha256(data).hexdigest() and entry["added_in_revision"] == 1
    assert ((path / "integrity.json").read_bytes(), (path / "attachments/manifest.json").read_bytes()) == before
    verify_integrity(path)
    with pytest.raises(AttachmentRejected) as rejected:
        service.add_attachment(job_id, "evil.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                                                   b'<script>alert(1)</script></svg>')
    assert rejected.value.reason == "svg_active_content"
    with pytest.raises(AttachmentRejected) as rejected:
        service.add_attachment(job_id, "../escape.png", data)
    assert rejected.value.reason == "unsafe_filename"
    with pytest.raises(AttachmentRejected):
        service.add_attachment(job_id, "photo.png", b'<html><script>x</script></html>')
    assert not (path / "attachments/revisions/2.json").exists(), "rejected uploads leave no revision"
    # The served location goes through the existing artifact route and stays inside the job.
    url = asset_url(job_id, entry)
    assert url == f"/jobs/{job_id}/files/run/attachments/originals/{entry['sha256']}.png"
    assert service.resolve_file(job_id, url.split("/files/", 1)[1]).read_bytes() == data
    assert image_assets(AssetStore(path)) == [entry]
    assert "40×30 px" in asset_summary(entry) and "documentation revision 1" in asset_summary(entry)
    assert existing_annotations(path) is None
    document = annotation_document(entry["sha256"], [
        {"sensor_id": "TC1", "x_norm": 0.25, "y_norm": 0.5, "label": "Case top center", "selected": True},
        {"sensor_id": "AMB", "x_norm": 0.9, "y_norm": 0.1, "label": "Ambient reference"}])
    launched = []
    monkeypatch.setattr(service, "_launch", lambda directory, **kwargs: launched.append(kwargs))
    result = service.retry_report(job_id, document)
    # A retry is queued, never launched from the request path; the dispatcher launches it when idle.
    assert result["state"] == "report-queued" and launched == []
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"} and launched == [{"report_only": True}]
    request = job / "annotations.request.json"
    assert json.loads(request.read_text()) == document
    rendered = []

    def render(path, annotations=None):
        rendered.append((Path(path), Path(annotations) if annotations else None))
        return 1
    monkeypatch.setattr("dcdc_bench.job_service._render_process", render)
    worker(job, report_only=True)
    assert rendered == [(path.resolve(), request.resolve())]
    assert service.status(job_id)["state"] == "failed", "a failed document build is reported, not hidden"
    verify_integrity(path)
    state = json.loads((job / "job.json").read_text())
    state.update(state="completed")
    atomic_json(job / "job.json", state)
    service.retry_report(job_id)
    assert not request.exists(), "a plain retry never reuses stale annotations"
    state.update(state="completed")
    atomic_json(job / "job.json", state)
    with pytest.raises(AnnotationError):
        service.retry_report(job_id, {**document, "extra": True})
    AssetStore(path).path_for(entry).write_bytes(png(41, 30))
    with pytest.raises(AssetHashMismatch):
        service.retry_report(job_id, document)
    state.update(state="acquiring")
    atomic_json(job / "job.json", state)
    monkeypatch.setattr("dcdc_bench.job_service._pid_matches", lambda pid, job: True)
    with pytest.raises(ValueError, match="finish"):
        service.add_attachment(job_id, "late.png", data)


def test_existing_annotations_reads_the_newest_revision_and_reports_a_changed_photograph(tmp_path):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {})
    store.finalize({})
    assets = AssetStore(store.path)
    entry = assets.add(png(), "case.png")
    for name, content in (("r0001", {"schema_version": "1.0", "author_interpretation": [], "assets": []}),
                          ("r0002", annotation_document(entry["sha256"], [{"sensor_id": "TC1", "x_norm": .1, "y_norm": .2, "label": "a"}])),
                          ("r0003", {"schema_version": "1.0", "author_interpretation": [], "assets": []})):
        (store.path / "reports" / name).mkdir(parents=True)
        (store.path / "reports" / name / "annotations.json").write_text(json.dumps(content))
    loaded, asset = existing_annotations(store.path)
    assert loaded["markers"][0]["sensor_id"] == "TC1" and asset == entry
    assets.path_for(entry).write_bytes(png(41, 30))
    with pytest.raises(AssetHashMismatch):
        existing_annotations(store.path)
    assert existing_annotations(tmp_path / "nowhere") is None


def test_editor_geometry_helpers_clamp_nudge_and_escape():
    assert normalized_point(20, 15, 40, 30) == (0.5, 0.5)
    assert normalized_point(-5, 99, 40, 30) == (0.0, 1.0)
    with pytest.raises(AnnotationError):
        normalized_point(1, 1, None, 30)
    marker = {"sensor_id": "TC1", "x_norm": 0.5, "y_norm": 0.002, "label": ""}
    assert nudge_marker(marker, "ArrowUp") == {**marker, "y_norm": 0.0}
    assert nudge_marker(marker, "ArrowRight", large=True)["x_norm"] == 0.52
    assert nudge_marker(marker, "Enter") == marker
    markers = [marker, {"sensor_id": "S2", "x_norm": 0.9, "y_norm": 0.9, "label": ""}]
    assert nearest_marker(markers, 0.505, 0.0) == 0 and nearest_marker(markers, 0.7, 0.7) is None
    assert new_sensor_id(markers) == "S3" and new_sensor_id([]) == "S1"
    svg = marker_overlay_svg(markers, 400, 300, selected=1)
    assert svg.count("<circle") == 2 and svg.count("<text") == 2 and 'fill="#15608f"' in svg
    assert 'cx="200.00" cy="0.60"' in svg and 'pointer-events="none"' in svg
    assert 'text-anchor="end"' in svg, "labels near the right edge are drawn inward"


class Widget:
    """Permissive stand-in for a NiceGUI element: records construction, supports the calls the page makes."""

    def __init__(self, kind, args, kwargs, registry):
        self.kind, self.args, self.kwargs = kind, args, kwargs
        self.text = args[0] if args and isinstance(args[0], str) else ""
        self.value, self.content, self.options, self.enabled = kwargs.get("value"), kwargs.get("content"), None, True
        registry.append(self)

    def classes(self, *args, **kwargs):
        return self

    def props(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def clear(self):
        pass

    def delete(self):
        pass

    def set_text(self, text):
        self.text = text

    def set_content(self, content):
        self.content = content

    def set_options(self, options, value=None):
        self.options, self.value = options, value

    def set_value(self, value):
        self.value = value

    def set_enabled(self, enabled):
        self.enabled = enabled

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def set_visibility(self, visible):
        self.visible = visible

    def tooltip(self, text):
        return self


class FakeUI:
    def __init__(self):
        self.widgets, self.pages, self.notifications = [], {}, []

        async def connected():
            return None
        self.context = SimpleNamespace(client=SimpleNamespace(connected=connected, is_deleted=False))

    def page(self, path, **kwargs):
        def decorate(fn):
            self.pages[path] = fn
            return fn
        return decorate

    def add_css(self, css):
        pass

    def colors(self, **kwargs):
        pass

    def notify(self, message, **kwargs):
        self.notifications.append((str(message), kwargs.get("type")))

    def __getattr__(self, name):
        return lambda *args, **kwargs: Widget(name, args, kwargs, self.widgets)

    def last(self, kind, text=None):
        return [w for w in self.widgets if w.kind == kind and (text is None or w.text == text)][-1]


class FakeRun:
    @staticmethod
    async def io_bound(fn, *args, **kwargs):
        return fn(*args, **kwargs)


class FakeFile:
    def __init__(self, name, data):
        self.name, self._data = name, data

    async def read(self):
        return self._data


class SizedFile(FakeFile):
    """Upload object that also reports its size and streams chunks, like NiceGUI's FileUpload."""

    def __init__(self, name, data, size=None, chunk=1024):
        super().__init__(name, data)
        self._size, self._chunk = size, chunk

    def size(self):
        return len(self._data) if self._size is None else self._size

    def iterate(self, *, chunk_size=None):
        step = chunk_size or self._chunk

        async def chunks():
            for start in range(0, len(self._data), step):
                yield self._data[start:start + step]
        return chunks()


def test_editor_page_drives_select_upload_place_nudge_and_save_without_a_server(service, monkeypatch):
    """The page's callbacks against the real JobService; NiceGUI is replaced by a recording stub."""
    import asyncio
    from dcdc_bench.annotation_editor import register_annotation_editor
    job_id, job, path = finished_job(service, monkeypatch)
    monkeypatch.setattr(service, "_launch", lambda directory, **kwargs: None)
    monkeypatch.setattr("dcdc_bench.runner.run_mock", lambda *a, **k: pytest.fail("the editor must never acquire"))
    ui = FakeUI()
    register_annotation_editor(ui, FakeRun, service, "body{}")
    assert set(ui.pages) == {"/annotations"}

    async def drive():
        await ui.pages["/annotations"]()
        jobs = [w for w in ui.widgets if w.kind == "select" and w.kwargs.get("label") == "Finished run"][-1]
        assert job_id in jobs.args[0]
        # UX M11: every option says whether the run is simulated; the uploader waits for a chosen run; no empty notice box.
        assert jobs.args[0][job_id].count("Simulation · synthetic data") == 1 and jobs.args[0][job_id].endswith("Complete")
        notice_box = [w for w in ui.widgets if w.kind == "label" and w.text == ""][-1]
        assert notice_box.visible is False and ui.last("upload").enabled is False
        await jobs.kwargs["on_change"](SimpleNamespace(value=job_id))
        assert ui.last("upload").enabled is True
        assert notice_box.visible is True and notice_box.text.startswith("Simulation run — photographs describe a physical setup")
        assert "No saved sensor markers" in notice_box.text
        assert ui.last("button", "Save as new report revision").enabled is False
        # Upload: validated by content, stored by hash, offered in the photograph list.
        await ui.last("upload").kwargs["on_upload"](SimpleNamespace(file=FakeFile("Case top.PNG", png())))
        picker = [w for w in ui.widgets if w.kind == "select" and w.kwargs.get("label") == "Photograph for markers"][-1]
        assert len(picker.options) == 1 and picker.value in picker.options
        await ui.last("upload").kwargs["on_upload"](SimpleNamespace(file=FakeFile("evil.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg" width="9" height="9"><script>1</script></svg>')))
        assert ui.notifications[-1][1] == "negative" and "svg_active_content" in ui.notifications[-1][0]
        # The byte limit is enforced on the server before the body is assembled; a rejected upload leaves no revision.
        monkeypatch.setattr(annotation_editor, "UPLOAD_LIMIT", 64)
        await ui.last("upload").kwargs["on_upload"](SimpleNamespace(file=SizedFile("huge.png", png(), size=10 ** 9)))
        assert ui.notifications[-1][1] == "negative" and "too_large" in ui.notifications[-1][0]
        monkeypatch.setattr(annotation_editor, "UPLOAD_LIMIT", 4 * len(png()))
        assert not (path / "attachments/revisions/2.json").exists()
        picker.kwargs["on_change"](SimpleNamespace(value=picker.value))
        image = ui.last("interactive_image")
        assert image.args[0].startswith(f"/jobs/{job_id}/files/run/attachments/originals/")
        assert ui.last("button", "Save as new report revision").enabled is True
        mouse = image.kwargs["on_mouse"]
        # Click adds a marker at 10/40, 15/30; dragging moves it; a second click near it re-selects.
        mouse(SimpleNamespace(type="mousedown", image_x=10, image_y=15, buttons=1))
        mouse(SimpleNamespace(type="mousemove", image_x=12, image_y=15, buttons=1))
        mouse(SimpleNamespace(type="mouseup", image_x=12, image_y=15, buttons=0))
        mouse(SimpleNamespace(type="mousedown", image_x=12.2, image_y=15, buttons=1))
        mouse(SimpleNamespace(type="mouseup", image_x=12.2, image_y=15, buttons=0))
        mouse(SimpleNamespace(type="mousedown", image_x=36, image_y=3, buttons=1))
        mouse(SimpleNamespace(type="mouseup", image_x=36, image_y=3, buttons=0))
        overlay = ui.last("interactive_image").content
        assert overlay.count("<circle") == 2 and "2 S2" in overlay
        note = [w for w in ui.widgets if w.kind == "input" and w.args[0] == "Location note"][-1]
        note.kwargs["on_change"](SimpleNamespace(value="Ambient <reference>"))
        key = ui.last("keyboard").kwargs["on_key"]
        press = lambda name, shift=False: key(SimpleNamespace(action=SimpleNamespace(keydown=True),
                                                              key=SimpleNamespace(name=name), modifiers=SimpleNamespace(shift=shift)))
        press("ArrowLeft", shift=True)
        press("ArrowDown")
        press("Enter")
        await ui.last("button", "Save as new report revision").kwargs["on_click"]()
        return json.loads((job / "annotations.request.json").read_text())
    saved = asyncio.run(drive())
    assert saved["schema_version"] == "1.0" and set(saved) == {"schema_version", "image_asset_sha256", "markers"}
    assert saved["image_asset_sha256"] == hashlib.sha256(png()).hexdigest()
    assert saved["markers"] == [
        {"sensor_id": "S1", "x_norm": 0.3, "y_norm": 0.5, "label": ""},
        {"sensor_id": "S2", "x_norm": 0.88, "y_norm": 0.105, "label": "Ambient <reference>"}]
    assert ui.notifications[-1][1] == "positive" and "no acquisition" in ui.notifications[-1][0]
    assert service.status(job_id)["state"] == "report-queued"
    service.dispatch_reports()
    assert service.status(job_id)["state"] == "queued" and service.status(job_id).get("action") == "report-only"
    verify_integrity(path)


def test_upload_size_is_enforced_server_side_before_the_body_is_assembled():
    import asyncio
    from dcdc_bench.annotation_editor import read_upload
    data = png()

    class Untouchable(SizedFile):
        async def read(self):
            pytest.fail("read() must not run for an upload that declares an oversized body")

        def iterate(self, **kwargs):
            pytest.fail("iterate() must not run for an upload that declares an oversized body")

    with pytest.raises(AttachmentRejected) as info:
        asyncio.run(read_upload(Untouchable("big.png", data, size=len(data) + 1), limit=len(data)))
    assert info.value.reason == "too_large"
    delivered = []

    class Streaming(SizedFile):
        def size(self):
            return 0  # an untrustworthy size: the stream itself is bounded

        def iterate(self, *, chunk_size=None):
            async def chunks():
                for index in range(100):
                    delivered.append(index)
                    yield b"x" * 1024
            return chunks()

    with pytest.raises(AttachmentRejected) as info:
        asyncio.run(read_upload(Streaming("big.png", b""), limit=4096))
    assert info.value.reason == "too_large" and len(delivered) == 5, "aborted at the first chunk past the limit"
    assert asyncio.run(read_upload(SizedFile("ok.png", data, chunk=7), limit=len(data))) == data
    assert asyncio.run(read_upload(FakeFile("plain.png", data), limit=len(data))) == data
    with pytest.raises(AttachmentRejected):
        asyncio.run(read_upload(FakeFile("plain.png", data), limit=len(data) - 1))
    assert asyncio.run(read_upload(FakeFile("plain.png", data))) == data, "the default limit is the attachment ceiling"


def test_attachment_validation_runs_outside_the_service_lock(service, monkeypatch):
    from dcdc_bench import attachments
    job_id, job, path = finished_job(service, monkeypatch)
    observed, real = [], attachments.validate_asset

    def spy(data, name):
        observed.append(service.lock.is_locked)
        return real(data, name)
    monkeypatch.setattr(attachments, "validate_asset", spy)
    entry = service.add_attachment(job_id, "photo.png", png())
    assert observed == [False], "validated exactly once, before the service lock is taken"
    assert entry["added_in_revision"] == 1 and (path / "attachments/revisions/1.json").exists()
    verify_integrity(path)
    # The store re-binds a pre-validated result by hash: a result for other bytes is ignored and re-validated.
    other = png(41, 30)
    observed.clear()
    second = AssetStore(path).add(other, "other.png", validated={**entry, "original_name": "other.png"})
    assert observed == [False] and second["sha256"] == hashlib.sha256(other).hexdigest()
    observed.clear()
    again = AssetStore(path).add(other, "other.png", validated=dict(second))
    assert observed == [] and again == second, "a matching pre-validation is trusted without a second parse"
