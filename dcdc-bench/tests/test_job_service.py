"""Durable local job orchestration; no hardware or document renderer is run."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dcdc_bench.job_service import JobService, worker, _latest_cycle
from dcdc_bench.storage import atomic_json, RunStore


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


def test_saved_edit_invalidates_old_preview_before_launch(service, monkeypatch):
    p = mock_preview(service)
    data = service.load_profile("dut", p["profiles"]["dut"])
    data["identity"]["revision"] = "new"
    service.save_profile("dut", data)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="changed"):
        service.start(p["plan_hash"])


def test_launch_is_detached_and_failure_is_durable(service, monkeypatch):
    p = mock_preview(service)
    def failed(command, **kwargs):
        assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
        raise OSError("process unavailable")
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", failed)
    with pytest.raises(RuntimeError, match="could not start"):
        service.start(p["plan_hash"])
    jobs = service.list_jobs()
    assert len(jobs) == 1 and jobs[0]["state"] == "failed"


def test_cancel_queued_job_never_acquires(service, monkeypatch):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job = service.start(p["plan_hash"])["job_id"]
    service.cancel(job)
    worker(service._job(job))
    assert service.status(job)["state"] == "cancelled"
    assert not (service._job(job) / "runs").exists()


def finalized_fixture(job, plan, *, off=True):
    path = job / "runs" / "fixture"
    store = RunStore(path)
    run = {"run_id": "fixture", "created_utc": "2026-01-01T00:00:00+00:00", "duration_s": 1.,
           "data_source": "simulated", "execution_status": "completed", "points": [],
           "shutdown": {role: {"state": "OFF" if off else "UNKNOWN", "verified": off} for role in ("source", "load")}}
    store.initialize({}, plan, run)
    store.finalize(run)
    return path


def test_report_retry_never_calls_acquisition_and_requires_off(service, monkeypatch):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)
    path = finalized_fixture(job, p["plan"])
    state = json.loads((job / "job.json").read_text())
    state.update(state="failed", run_dir=str(path))
    atomic_json(job / "job.json", state)
    launched = []
    monkeypatch.setattr(service, "_launch", lambda directory, **kwargs: launched.append(kwargs))
    # A retry only queues; the UI's dispatcher launches the report-only worker.
    assert service.retry_report(job_id) == {"job_id": job_id, "state": "report-queued"}
    assert launched == [] and service.status(job_id)["state"] == "report-queued"
    service.dispatch_reports()
    assert launched == [{"report_only": True}]
    monkeypatch.setattr("dcdc_bench.runner.run_mock", lambda *a, **k: pytest.fail("retry must not acquire"))
    monkeypatch.setattr("dcdc_bench.job_service._render_process", lambda path: 1)
    worker(job, report_only=True)
    assert service.status(job_id)["state"] == "failed"
    run = json.loads((path / "run.json").read_text())
    run["shutdown"]["load"]["verified"] = False
    RunStore(path).finalize(run)
    with pytest.raises(RuntimeError, match="OFF"):
        service.retry_report(job_id)


def test_artifact_paths_cannot_escape_job(service, monkeypatch, tmp_path):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)
    path = finalized_fixture(job, p["plan"])
    with pytest.raises(ValueError, match="escape"):
        service.resolve_file(job_id, "run/../../../../secret")
    with pytest.raises(ValueError):
        service.load_profile("dut", "../../secret")


def test_readonly_live_values_use_a_complete_bounded_cycle(tmp_path):
    path = tmp_path / "samples"
    lines = [json.dumps({"acquisition_cycle_id": "c1", "quantity": quantity, "value": value,
        "status": "ok", "quality_flags": [], "query_end_utc": "2026-01-01T00:00:00+00:00"})
        for quantity, value in (("Vin_V", 24), ("Iin_A", .1), ("Vout_V", 12), ("Iout_A", .15))]
    path.write_text("\n".join(lines)+"\n{incomplete")
    values, timestamp = _latest_cycle(path)
    assert values["Vin_V"] == 24 and len(values) == 4 and timestamp


def test_worker_import_failure_is_not_permanently_queued(service, monkeypatch):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=999999))
    job_id = service.start(p["plan_hash"])["job_id"]
    assert service.status(job_id)["state"] == "failed"
    assert "unexpectedly" in service.status(job_id)["error"]


def test_expired_worker_cannot_energize_after_ui_reports_failure(service, monkeypatch):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)
    atomic_json(job / "launch.json", {"requested_utc": "2020-01-01T00:00:00+00:00", "pid": None})
    assert service.status(job_id)["state"] == "failed"
    worker(job)
    assert not (job / "runs").exists()
    assert "expired" in service.status(job_id)["error"]


def test_systemd_launcher_failure_marks_late_worker_cancelled(service, monkeypatch):
    import subprocess
    monkeypatch.setenv("DCDC_JOB_LAUNCHER", "systemd")
    def failed(command, **kwargs):
        assert "--property=Restart=no" in command
        assert "--property=RuntimeMaxSec=2700" in command
        assert "--property=KillMode=control-group" in command
        raise subprocess.TimeoutExpired(command, 15)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.run", failed)
    p = mock_preview(service)
    with pytest.raises(RuntimeError, match="could not start"):
        service.start(p["plan_hash"])
    job_id = service.list_jobs()[0]["job_id"]
    job = service._job(job_id)
    assert (job / "cancel.request").exists()
    worker(job)
    assert service.status(job_id)["state"] == "cancelled" and not (job / "runs").exists()


def test_seeded_real_profile_requires_saved_approvals_then_is_feasible(service, monkeypatch, tmp_path):
    from test_voltage_sweep import bench
    fake = bench(tmp_path, monkeypatch)
    fake.config.write_text("# fake inventory; parsed through the fixture's config loader\n")
    service.inventory_path = fake.config
    dut_name = service.list_profiles()["dut"][0]
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    p = service.preview(dut_name, "rigol-local-limited", "real-24v-small-grid")
    assert not p["supported"]
    assert any("real_hardware_enabled is false" in e for e in p["errors"])
    assert any("wiring_and_polarity_confirmed is false" in e for e in p["errors"])
    assert any("protective_controls.approved is false" in e for e in p["errors"])
    with pytest.raises(ValueError, match="Unsupported plan"):
        service.start(p["plan_hash"])
    dut = service.load_profile("dut", dut_name)
    dut["execution_approval"].update(real_hardware_enabled=True, wiring_and_polarity_confirmed=True)
    service.save_profile("dut", dut)
    bench_profile = service.load_profile("bench", "rigol-local-limited")
    bench_profile["protective_controls"]["approved"] = True
    service.save_profile("bench", bench_profile)
    p = service.preview(dut_name, "rigol-local-limited", "real-24v-small-grid")
    assert p["supported"] and p["counts"]["executable"] == 3
    assert p["confirmation_required"] and p["inventory"]["source"]["serial"] == "FAKE-source"
    assert fake.commands == []
    with pytest.raises(ValueError, match="Confirm"):
        service.start(p["plan_hash"])
    assert fake.commands == []


def test_stale_supported_preview_cannot_start_an_unapproved_real_job(service, monkeypatch, tmp_path):
    import json
    from test_voltage_sweep import bench
    fake = bench(tmp_path, monkeypatch)
    fake.config.write_text("# fake inventory; parsed through the fixture's config loader\n")
    service.inventory_path = fake.config
    dut_name = service.list_profiles()["dut"][0]
    p = service.preview(dut_name, "rigol-local-limited", "real-24v-small-grid")
    assert not p["supported"]
    cached = service.root / "previews" / (p["plan_hash"] + ".json")
    stale = json.loads(cached.read_text())
    stale.update(supported=True, errors=[])
    atomic_json(cached, stale)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    confirmation = {"plan_hash": p["plan_hash"], "wiring_and_polarity": True, "channel1": True,
                    "protections_reviewed": True, "source_serial": "FAKE-source", "load_serial": "FAKE-load"}
    with pytest.raises(ValueError, match="real_hardware_enabled is false"):
        service.start(p["plan_hash"], confirmation=confirmation)
    assert service.list_jobs() == [] and fake.commands == []
    assert not any((service.root / "jobs").iterdir())


def test_systemd_launch_preserves_shared_lease_and_render_paths(service, monkeypatch):
    monkeypatch.setenv("DCDC_JOB_LAUNCHER", "systemd")
    monkeypatch.setenv("QUARTO_PATH", "/opt/quarto with spaces/bin/quarto")
    seen = []
    def launched(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.run", launched)
    job_id = service.start(mock_preview(service)["plan_hash"])["job_id"]
    import os
    assert "--setenv=DCDC_ACTIVITY_LOCK="+os.environ["DCDC_ACTIVITY_LOCK"] in seen[0]
    assert "--setenv=QUARTO_PATH=/opt/quarto with spaces/bin/quarto" in seen[0]
    assert json.loads((service._job(job_id) / "launch.json").read_text())["unit"].startswith("dcdc-job-")


def test_report_cancellation_terminates_only_owned_report_group(monkeypatch, tmp_path):
    from dcdc_bench.job_service import _render_process
    import signal
    waits, kills = [], []
    class Child:
        pid = 42424
        def wait(self, *, timeout):
            waits.append(timeout)
            if len(waits) == 1:
                raise KeyboardInterrupt()
            return -15
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: Child())
    monkeypatch.setattr("dcdc_bench.job_service.os.killpg", lambda pid, sig: kills.append((pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        _render_process(tmp_path)
    assert kills == [(42424, signal.SIGTERM), (42424, signal.SIGKILL)]
    assert waits == [1800, 10, 10]
