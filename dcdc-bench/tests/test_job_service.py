"""Durable local job orchestration; no hardware or document renderer is run."""
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

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
    # M7: the memory-gate thresholds (and every DCDC_* variable) reach the worker,
    # so services.report_run applies the same gate the dispatcher passed.
    monkeypatch.setenv("DCDC_RENDER_MIN_AVAILABLE_MIB", "0")
    monkeypatch.setenv("DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB", "0")
    monkeypatch.setenv("PYTHONPATH", "/srv/dcdc/src")
    seen = []
    def launched(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.run", launched)
    job_id = service.start(mock_preview(service)["plan_hash"])["job_id"]
    import os
    assert "--setenv=DCDC_ACTIVITY_LOCK="+os.environ["DCDC_ACTIVITY_LOCK"] in seen[0]
    assert "--setenv=QUARTO_PATH=/opt/quarto with spaces/bin/quarto" in seen[0]
    assert "--setenv=DCDC_RENDER_MIN_AVAILABLE_MIB=0" in seen[0]
    assert "--setenv=DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB=0" in seen[0]
    assert "--setenv=DCDC_JOB_LAUNCHER=systemd" in seen[0]
    assert "--setenv=PYTHONPATH=/srv/dcdc/src" in seen[0]
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


# --- M3: dispatch by test type ------------------------------------------------------------------------

def uvlo_mock_profiles(service, *, steps=(12., 9., 8.5, 9., 12.), extra_sweep=False):
    """Save an approved mock UVLO bench/recipe pair the way the UI forms do; unique instrument ids keep the mock locks apart."""
    catalog = service.list_profiles()
    bench_name = next(n for n in catalog["bench"] if service.load_profile("bench", n)["mode"] == "mock")
    recipe_name = next(n for n in catalog["recipe"] if service.load_profile("recipe", n)["execution_mode"] == "mock")
    suffix = uuid.uuid4().hex[:8]
    bench = service.load_profile("bench", bench_name)
    bench["bench_id"] = "uvlo-bench-" + suffix
    bench["source"]["instrument_id"] += suffix
    bench["load"]["instrument_id"] += suffix
    for quantity, binding in bench["measurements"].items():
        binding["instrument_id"] = bench["source"]["instrument_id"] if quantity in ("Vin_V", "Iin_A") else bench["load"]["instrument_id"]
    bench["protective_controls"].update(policy_id="synthetic-uvlo-ramp-v1", source_current_limit_A=.5,
                                        dut_output_overvoltage_V=13.2, output_overcurrent_A=.15)
    recipe = service.load_profile("recipe", recipe_name)
    recipe["recipe_id"] = "uvlo-recipe-" + suffix
    sweep = recipe["tests"][0]
    ramp = {"id": "uvlo-ramp", "type": "uvlo_input_ramp", "input_voltage_targets_V": list(steps), "output_current_targets_A": [.1],
            "uvlo": {"floor_V": 8., "startup_interval_s": .3, "output_on_minimum_V": 10.8, "output_off_maximum_V": 1.,
                     "expected_off_below_V": 9., "expected_on_above_V": 10.}}
    recipe["tests"] = [ramp, sweep] if extra_sweep else [ramp]
    recipe["settling"].update(minimum_dwell_s=1.)
    recipe["acquisition"].update(duration_s=.3, target_poll_interval_s=.25, minimum_complete_cycles=3)
    recipe["authorization"].update(uvlo_approved=True, protective_policy_id="synthetic-uvlo-ramp-v1")
    return catalog["dut"][0], service.save_profile("bench", bench), service.save_profile("recipe", recipe)


def test_armed_mock_uvlo_job_runs_the_ramp_procedure_to_report_queued(service, monkeypatch):
    """M3: an approved all-UVLO mock plan is dispatched to uvlo.run_uvlo_mock, never to runner.run_mock."""
    preview = service.preview(*uvlo_mock_profiles(service))
    assert preview["supported"] and preview["counts"] == {"executable": 5}, preview["errors"]
    assert all(p["test_id"] == "uvlo-ramp" for p in preview["points"])
    with pytest.MonkeyPatch.context() as launch:  # the worker runs below, in this process, and needs the real Popen
        launch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
        job_id = service.start(preview["plan_hash"], notes="synthetic ramp")["job_id"]
    job = service._job(job_id)
    monkeypatch.setattr("dcdc_bench.runner.run_mock", lambda *a, **k: pytest.fail("a UVLO plan must not run the load-sweep loop"))
    monkeypatch.setattr("dcdc_bench.job_service._render_process", lambda *a, **k: pytest.fail("the acquisition worker must not render"))
    worker(job)
    snapshot = service.status(job_id)
    assert snapshot["state"] == "report-queued", snapshot["error"]
    assert snapshot["error"] is None and Path(snapshot["run_dir"]).is_dir()
    run = json.loads((Path(snapshot["run_dir"]) / "run.json").read_text())
    assert "uvlo_input_ramp" in run["method"] and run["scenario"].startswith("Approved UVLO input ramp")
    assert run["execution_status"] == "completed", run["errors"]
    assert run["operator_observations"] == ["synthetic ramp"] and run["real_hardware_opened"] is False
    assert [p["output_state"] for p in run["points"]] == ["on", "on", "off", "off", "on"]
    assert all(s["state"] == "OFF" and s["verified"] is True for s in run["shutdown"].values())


def test_mixed_uvlo_and_sweep_recipe_is_unsupported_at_planning(service, tmp_path):
    """M3: a recipe mixing the ramp with a load sweep has no executor; every point is refused with the reason."""
    from dcdc_bench.domain import Plan
    from dcdc_bench.services import acquire_mock
    preview = service.preview(*uvlo_mock_profiles(service, extra_sweep=True))
    assert not preview["supported"] and "No feasible point is available" in preview["errors"]
    assert preview["counts"] == {"unsupported": len(preview["points"])}
    assert all("mixes uvlo_input_ramp" in p["reason"] for p in preview["points"])
    with pytest.raises(ValueError, match="Unsupported plan"):
        service.start(preview["plan_hash"])
    with pytest.raises(ValueError, match="mixes uvlo_input_ramp"):
        acquire_mock(Plan.model_validate(preview["plan"]), tmp_path / "mixed-out")
    assert not (tmp_path / "mixed-out").exists()


# --- M5: an unverified PDF completes the job with a visible note; a failed layout check still fails it ----

def report_only_job(service, monkeypatch):
    """A finalized, verified-OFF job whose report-only worker is about to run in this process."""
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)
    path = finalized_fixture(job, p["plan"])
    state = json.loads((job / "job.json").read_text())
    state.update(state="queued", run_dir=str(path), action="report-only")
    atomic_json(job / "job.json", state)
    return job_id, job


def fake_render(manifest_status, pdf_status, **pdf_fields):
    def render(path, annotations=None):
        revision = Path(path) / "reports" / "r0001"
        revision.mkdir(parents=True)
        (revision / "report.html").write_text("<html></html>")
        (revision / "report.pdf").write_bytes(b"%PDF-1.7 fixture")
        atomic_json(revision / "build_manifest.json", {"status": manifest_status, "artifacts": {
            "html": {"status": "success"}, "pdf": {"status": pdf_status, **pdf_fields}}})
        return 0
    return render


def test_unverified_pdf_check_completes_the_job_with_a_visible_note(service, monkeypatch):
    from dcdc_bench.ui_models import report_link_rows
    job_id, job = report_only_job(service, monkeypatch)
    monkeypatch.setattr("dcdc_bench.job_service._render_process",
                        fake_render("unverified", "unverified", note="PDF not verified: tool missing (pdftohtml-unavailable)"))
    worker(job, report_only=True)
    snapshot = service.status(job_id)
    assert snapshot["state"] == "completed" and snapshot["error"] is None
    assert snapshot["report_note"].startswith("PDF not verified: tool missing")
    assert snapshot["report_artifacts"]["pdf"]["status"] == "unverified"
    assert snapshot["report_artifacts"]["html"]["status"] == "success"
    rows = report_link_rows(snapshot)
    assert [relative for _, relative in rows] == ["report/report.html", "report/report.pdf"]
    assert rows[1][0] == "Open PDF (not verified: checker tool missing)"


def test_failed_pdf_validation_still_fails_the_job_but_keeps_the_pdf_reachable(service, monkeypatch):
    from dcdc_bench.ui_models import report_link_rows
    job_id, job = report_only_job(service, monkeypatch)
    monkeypatch.setattr("dcdc_bench.job_service._render_process",
                        fake_render("failed-validation", "failed-validation",
                                    error="PDF pagination check (PDF-02) reported 1 error finding(s): p1: orphan-heading"))
    worker(job, report_only=True)
    snapshot = service.status(job_id)
    assert snapshot["state"] == "failed" and "report generation failed" in snapshot["error"]
    assert snapshot.get("report_note") is None
    rows = report_link_rows(snapshot)
    assert [relative for _, relative in rows] == ["report/report.html", "report/report.pdf"]
    assert "failed the layout check" in rows[1][0]


def test_operator_stop_during_acquisition_survives_into_the_cancelled_record(service, monkeypatch):
    """Job 20260929T213318Z_6290205b ended 'cancelled' with error None and nothing saying when or why:
    run_mock swallows the SIGINT that cancel() sends, so the worker's 'Operator cancelled' message never
    lands for a mock job, and dispatch_reports deletes cancel.request before the report worker runs.
    The stop request time must reach job.json in the acquisition worker and survive both later workers."""
    from dcdc_bench.resources import MemoryGate
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)

    def acquire_then_stop(plan, out, **kwargs):
        # The worker has published its pid and 'acquiring' by now; the operator presses Stop.
        assert service.status(job_id)["state"] == "acquiring"
        assert service.cancel(job_id)["cancel_requested"] is True
        return finalized_fixture(job, p["plan"])  # verified OFF, as an interrupted mock run still ends

    monkeypatch.setattr("dcdc_bench.services.acquire_mock", acquire_then_stop)
    worker(job)
    queued = service.status(job_id)
    assert queued["state"] == "report-queued" and queued["acquisition_cancelled"] is True and queued["error"] is None
    stamp = queued["acquisition_cancelled_utc"]
    assert stamp == (job / "cancel.request").read_text().strip()
    assert datetime.fromisoformat(stamp) >= datetime.fromisoformat(queued["created_utc"])
    service.gate = MemoryGate(0, 0)
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}
    assert not (job / "cancel.request").exists(), "the dispatcher clears the marker; the time must already be in job.json"
    monkeypatch.setattr("dcdc_bench.job_service._render_process", fake_render("success", "success"))
    worker(job, report_only=True)
    final = service.status(job_id)
    assert final["state"] == "cancelled" and final["error"] is None
    assert final["acquisition_cancelled_utc"] == stamp


# --- One-page bench: plain names, card planning, delete/rename ------------------------------------------

def test_seeded_profiles_carry_plain_names_and_saved_ones_are_migrated_once(tmp_path, monkeypatch):
    """The owner's benches and recipes predate titles; _seed fills the known ones in, idempotently, and
    never invents a bench name (the page falls back to the identifier) or overwrites a saved title."""
    from dcdc_bench.job_service import DEFAULT_CATEGORY, PLAIN_TITLES
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))
    root = tmp_path / "workspace"
    first = JobService(root)
    quick, bench = first.load_profile("recipe", "12t12-4a-quick"), first.load_profile("bench", "rigol-local-limited")
    assert quick["title"] == "Quick sweep — 12 / 24 / 30 V × 0–1 A" and quick["category"] == DEFAULT_CATEGORY
    assert bench["title"] == "24 V converter tests" and first.load_profile("bench", "mock-dp821-envelope")["title"] == "Simulated DP821A envelope"
    assert first.load_profile("recipe", "real-24v-small-grid")["title"] == PLAIN_TITLES["recipe"]["real-24v-small-grid"]
    # Profiles written before titles existed: the owner's no-load recipe, pass-through check and wide-input bench.
    legacy_recipe = {k: v for k, v in first.load_profile("recipe", "real-24v-small-grid").items() if k not in ("title", "category", "description", "standard_clause")}
    legacy_recipe.update(recipe_id="real-24v-noload-then-0p1A", execution_mode="real")
    legacy_recipe["tests"][0]["output_current_targets_A"] = [0., .1]
    passthrough = {**legacy_recipe, "recipe_id": "passthrough-12v-check"}
    unknown = {**legacy_recipe, "recipe_id": "my-own-grid"}
    legacy_bench = {k: v for k, v in bench.items() if k != "title"}
    legacy_bench["bench_id"] = "rigol-local-wide-input"
    unknown_bench = {**legacy_bench, "bench_id": "somebody-elses-bench"}
    for kind, data in (("recipe", legacy_recipe), ("recipe", passthrough), ("recipe", unknown), ("bench", legacy_bench), ("bench", unknown_bench)):
        atomic_json(root / "profiles" / kind / (data[{"recipe": "recipe_id", "bench": "bench_id"}[kind]] + ".json"), data)
    titled = first.load_profile("recipe", "12t12-4a-quick")
    titled["title"] = "My renamed sweep"
    first.save_profile("recipe", titled)
    second = JobService(root)
    assert second.load_profile("recipe", "real-24v-noload-then-0p1A")["title"] == "24 V — no-load window, then 0.1 A"
    assert second.load_profile("recipe", "real-24v-noload-then-0p1A")["execution_mode"] == "real", "the migration touches names only"
    wire = second.load_profile("recipe", "passthrough-12v-check")
    assert wire["title"] == "Pass-through wire check — 12 V × 0 / 0.1 / 0.25 / 0.5 A" and wire["category"] == "Bench checks"
    own = second.load_profile("recipe", "my-own-grid")
    assert own["title"] is None and own["category"] == DEFAULT_CATEGORY, "unknown recipes get a category; the page titles them from the grid"
    assert second.load_profile("bench", "rigol-local-wide-input")["title"] == "Wide input up to 36 V"
    assert second.load_profile("bench", "somebody-elses-bench")["title"] is None, "a bench name is not derivable"
    assert second.load_profile("recipe", "12t12-4a-quick")["title"] == "My renamed sweep", "a saved title is never overwritten"
    before = {kind: {name: (root / "profiles" / kind / (name + ".json")).read_bytes() for name in names}
              for kind, names in second.list_profiles().items()}
    JobService(root)
    after = {kind: {name: (root / "profiles" / kind / (name + ".json")).read_bytes() for name in names}
             for kind, names in second.list_profiles().items()}
    assert after == before, "idempotent: a second start rewrites nothing"
    catalog = second.catalog()
    assert set(catalog) == {"dut", "bench", "recipe"} and "my-own-grid" in catalog["recipe"] and catalog["dut"]["12t12-4a"]["identity"]["model"] == "12T12-4A"


def test_feasibility_plans_a_card_on_each_bench_without_approvals_or_the_inventory(service):
    from dcdc_bench.real_backend import acquisition_seconds
    from dcdc_bench.domain import PlannedPoint, TestRecipe
    dut = service.list_profiles()["dut"][0]
    simulated = service.feasibility(dut, "mock-dp821-envelope", "12t12-4a-quick")
    assert simulated == {"points": 21, "executable": 19, "runnable": True, "reason": None, "estimated_seconds": None, "mode": "mock"}
    real = service.feasibility(dut, "rigol-local-limited", "real-24v-small-grid")
    assert real["runnable"] and real["executable"] == 3 and real["mode"] == "real", "saved approvals gate Start, not the card"
    recipe = TestRecipe.model_validate(service.load_profile("recipe", "real-24v-small-grid"))
    eligible = [PlannedPoint(point_id=f"p{i}", test_id="increasing-load", vin_target_V=24., iout_target_A=a, status="executable", reason="")
                for i, a in enumerate((.1, .25, .5))]
    assert real["estimated_seconds"] == acquisition_seconds(recipe, eligible) == 62., "3 x (5 s dwell + 8 s acquisition + 3 s) + 14 s startup"
    # The card recipe is planned against the selected converter even when its saved dut_profile_id differs.
    other = service.load_profile("dut", dut)
    other.update(profile_id="other-board")
    other["identity"]["model"] = "Other"
    service.save_profile("dut", other)
    assert service.feasibility("other-board", "mock-dp821-envelope", "12t12-4a-quick")["runnable"]
    # Not runnable: the planner's first reason, one clause, no clipping.
    hundred = service.load_profile("recipe", "12t12-4a-quick")
    hundred.update(recipe_id="hundred", execution_mode=None)
    hundred["tests"][0]["input_voltage_targets_V"] = [100.]
    service.save_profile("recipe", hundred)
    greyed = service.feasibility(dut, "mock-dp821-envelope", "hundred")
    assert not greyed["runnable"] and greyed["executable"] == 0 and greyed["estimated_seconds"] is None
    assert greyed["reason"] == "Requested input voltage is outside the DUT operating rating"
    slow = service.load_profile("recipe", "real-24v-small-grid")
    slow.update(recipe_id="slow-poll")
    slow["acquisition"]["target_poll_interval_s"] = .5
    service.save_profile("recipe", slow)
    on_real = service.feasibility(dut, "rigol-local-limited", "slow-poll")
    assert not on_real["runnable"] and on_real["reason"].startswith("Acquisition requires 5–15 s, 1–2 s polling")
    assert service.feasibility(dut, "mock-dp821-envelope", "slow-poll")["runnable"], "the same test is fine on the simulated bench"


def test_delete_and_rename_profiles_are_atomic_and_refuse_active_jobs(service, monkeypatch):
    dut = service.list_profiles()["dut"][0]
    with pytest.raises(ValueError, match="No saved recipe"):
        service.delete_profile("recipe", "missing")
    with pytest.raises(ValueError, match="Invalid local identifier"):
        service.rename_profile("recipe", "12t12-4a-quick", "no spaces allowed")
    with pytest.raises(ValueError, match="already exists"):
        service.rename_profile("recipe", "12t12-4a-quick", "real-24v-small-grid")
    p = service.preview(dut, "mock-dp821-envelope", "12t12-4a-quick")
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    record = json.loads((service._job(job_id) / "job.json").read_text())
    assert record["recipe_id"] == "12t12-4a-quick" and record["recipe_title"] == "Quick sweep — 12 / 24 / 30 V × 0–1 A"
    assert record["profiles"] == {"dut": dut, "bench": "mock-dp821-envelope", "recipe": "12t12-4a-quick"}
    assert service.status(job_id)["state"] == "queued"
    for kind, name in record["profiles"].items():
        with pytest.raises(ValueError, match="active job"):
            service.delete_profile(kind, name)
        with pytest.raises(ValueError, match="active job"):
            service.rename_profile(kind, name, "renamed-" + kind)
    assert service.load_profile("recipe", "12t12-4a-quick")["recipe_id"] == "12t12-4a-quick", "nothing moved"
    service.cancel(job_id)
    worker(service._job(job_id))
    assert service.status(job_id)["state"] == "cancelled"
    assert service.rename_profile("recipe", "12t12-4a-quick", "quick-sweep") == "quick-sweep"
    names = service.list_profiles()["recipe"]
    assert "quick-sweep" in names and "12t12-4a-quick" not in names
    renamed = service.load_profile("recipe", "quick-sweep")
    assert renamed["recipe_id"] == "quick-sweep" and renamed["title"] == "Quick sweep — 12 / 24 / 30 V × 0–1 A"
    # Renaming a converter re-points the saved recipes that reference it.
    assert service.rename_profile("dut", dut, "board-a") == "board-a"
    assert service.list_profiles()["dut"] == ["board-a"]
    assert all(service.load_profile("recipe", name)["dut_profile_id"] == "board-a" for name in service.list_profiles()["recipe"])
    assert service.delete_profile("recipe", "quick-sweep") == "quick-sweep"
    assert "quick-sweep" not in service.list_profiles()["recipe"]
    assert not (service.root / "profiles" / "recipe" / "quick-sweep.json").exists()
    # The finished job keeps its own plan snapshot and stays listed.
    assert service.status(job_id)["recipe_id"] == "12t12-4a-quick" and (service._job(job_id) / "plan.json").is_file()
    with pytest.raises(ValueError, match="renamed or deleted"):
        service.start(p["plan_hash"]), "a cached preview of a renamed profile is a clear refusal, not a missing-file error"


def test_uncancelled_job_records_no_stop_time_and_an_empty_marker_is_tolerated(service, monkeypatch):
    p = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    job_id = service.start(p["plan_hash"])["job_id"]
    job = service._job(job_id)
    monkeypatch.setattr("dcdc_bench.services.acquire_mock", lambda plan, out, **kwargs: finalized_fixture(job, p["plan"]))
    worker(job)
    assert service.status(job_id)["acquisition_cancelled_utc"] is None
    from dcdc_bench.job_service import _stop_requested_utc
    (job / "empty").touch()
    (job / "junk").write_text("not a time")
    assert _stop_requested_utc(job / "empty") is None and _stop_requested_utc(job / "junk") is None
    assert _stop_requested_utc(job / "missing") is None
