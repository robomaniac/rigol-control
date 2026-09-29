"""RUN-02 — a browser refresh never restarts, duplicates, aborts or rearms a job.

Governing spec (docs/implementation-brief.md): §14.1 RUN-02 "Does not restart,
duplicate, or automatically abort/rearm the hardware sequence"; §7.1 "A UI
refresh cannot create a second instrument owner or restart a sweep"; §7.4
"Never auto-resume hardware output on UI reload, process restart, or opening an
old run".

No browser is involved. ``ui.bench_page`` reaches the bench only through
JobService, so the page-load sequence it performs on every (re)load is replayed
here with the same calls: ``list_profiles``/``load_profile`` (forms),
``list_jobs`` (``refresh_reports`` -> ``remember_jobs``), ``status`` (``poll``),
``resolve_file`` (artifact links), and ``preview``/``start``/``retry_report``
for the buttons an operator might press again after refreshing. The job is the
real detached ``dcdc_bench.job_service --worker`` process, in mock mode.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import signal
import time
from types import SimpleNamespace
import uuid

import pytest

import dcdc_bench
from dcdc_bench.job_service import ACTIVE, JobService, worker
from dcdc_bench.storage import verify_integrity

ARMING_SEQUENCE = ["PLAN_READY", "AWAITING_ARM", "CONNECTING", "PREFLIGHT", "RUNNING"]
NORMAL_LIFECYCLE = ARMING_SEQUENCE + ["STOPPING", "FINALIZING", "COMPLETED"]


def write_stub_report(run_dir):
    """Stand-in for the report renderer process; RUN-02 is about acquisition ownership.

    Reporting is a separate process that starts only after every output is
    verified OFF, and rendering HTML/PDF needs Plotly/Quarto and far more memory
    than the Raspberry Pi test host can spare. The marker proves the real
    renderer did not run.
    """
    import json
    from pathlib import Path
    directory = Path(run_dir) / "reports" / "r0001"
    directory.mkdir(parents=True)
    manifest = {"schema_version": "1.0", "status": "success", "requested_formats": ["html", "pdf"],
                "artifacts": {fmt: {"status": "skipped", "error": "RUN-02 test stub"} for fmt in ("html", "pdf")},
                "renderer": "test_run02_reconnect stub"}
    (directory / "build_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return directory


# Loaded through PYTHONPATH only inside the detached worker's process tree; it
# never ships with the package. In the worker it puts the mock acquisition on
# the wall clock so a refresh can happen while the sequence is RUNNING; in the
# report subprocess it replaces rendering with write_stub_report above.
WORKER_SHIM = '"""RUN-02 test-only sitecustomize shim (see tests/test_run02_reconnect.py)."""\n' \
    "import os\nimport sys\n\n" + inspect.getsource(write_stub_report) + '''

try:
    _argv = list(sys.orig_argv)
    if _argv[1:4] == ["-m", "dcdc_bench", "report"]:
        import dcdc_bench.cli as _cli
        _cli.report_run = lambda run_dir, **kwargs: write_stub_report(run_dir)
    elif "dcdc_bench.job_service" in _argv:
        import dcdc_bench.runner as _runner
        _original_run_mock = _runner.run_mock

        def _wall_clock_run_mock(plan, out, scenario="normal", real_time=False, **kwargs):
            return _original_run_mock(plan, out, scenario, True, **kwargs)

        _runner.run_mock = _wall_clock_run_mock
except BaseException as exc:  # never fall through to the real renderer on this host
    sys.stderr.write(f"RUN-02 shim failed: {type(exc).__name__}: {exc}\\n")
    os._exit(70)
'''


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))
    monkeypatch.setenv("DCDC_JOB_LAUNCHER", "detached")
    shim = tmp_path / "worker-shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(WORKER_SHIM)
    # The worker must import the same package under test, not another checkout
    # the shared virtualenv happens to have installed.
    package_root = Path(dcdc_bench.__file__).resolve().parents[1]
    inherited = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(shim), str(package_root), *inherited]))
    return JobService(tmp_path / "workspace")


@pytest.fixture
def detached(service):
    """Never leave a detached worker behind when an assertion fails mid-run."""
    jobs = []
    yield jobs
    for job_id in jobs:
        if service.status(job_id)["state"] in ACTIVE:
            service.cancel(job_id)
            wait_until(lambda: service.status(job_id)["state"] not in ACTIVE, 15, "worker ignored cancel", strict=False)
        for pid in worker_pids(service._job(job_id)):
            os.killpg(pid, signal.SIGKILL)  # start_new_session=True: the worker leads its own group


def unique_mock_profiles(service, currents):
    """Save a bench/recipe pair the way the UI forms do; unique instrument ids keep
    the mock resource locks apart from other suites running on the same host."""
    catalog = service.list_profiles()
    bench_name = next(n for n in catalog["bench"] if service.load_profile("bench", n)["mode"] == "mock")
    recipe_name = next(n for n in catalog["recipe"] if service.load_profile("recipe", n)["execution_mode"] == "mock")
    suffix = uuid.uuid4().hex[:8]
    bench = service.load_profile("bench", bench_name)
    bench["bench_id"] = "run02-bench-" + suffix
    bench["source"]["instrument_id"] += suffix
    bench["load"]["instrument_id"] += suffix
    for quantity, binding in bench["measurements"].items():
        binding["instrument_id"] = bench["source"]["instrument_id"] if quantity in ("Vin_V", "Iin_A") else bench["load"]["instrument_id"]
    recipe = service.load_profile("recipe", recipe_name)
    recipe["recipe_id"] = "run02-recipe-" + suffix
    recipe["tests"] = [recipe["tests"][0]]
    recipe["tests"][0].update(input_voltage_targets_V=[24.], output_current_targets_A=list(currents))
    recipe["settling"].update(minimum_dwell_s=1., window_s=.3, minimum_fresh_samples=3, timeout_s=3.)
    recipe["acquisition"].update(duration_s=1., target_poll_interval_s=.1, minimum_complete_cycles=3)
    return catalog["dut"][0], service.save_profile("bench", bench), service.save_profile("recipe", recipe)


def page_load(ui_service):
    """The JobService calls ui.bench_page() makes when a browser (re)loads '/'."""
    catalog = ui_service.list_profiles()
    for kind, names in catalog.items():
        ui_service.load_profile(kind, names[0])
    jobs = ui_service.list_jobs()                                     # refresh_reports -> remember_jobs
    active = next((job for job in jobs if job.get("state") in ACTIVE), None)
    snapshot = ui_service.status(active["job_id"]) if active else None  # reattach -> poll()
    return jobs, snapshot


def wait_until(predicate, timeout_s, message, *, strict=True):
    deadline = time.monotonic() + timeout_s
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            if strict:
                pytest.fail(message() if callable(message) else message)
            return value
        time.sleep(.2)


def worker_pids(job):
    """Live processes whose command line is this job's detached worker."""
    found = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"dcdc_bench.job_service" in command and b"--worker" in command and os.fsencode(str(job)) in command:
            found.add(int(entry.name))
    return found


def lifecycle(run_dir):
    """(lifecycle states in order, arming-event count) from the append-only event log."""
    states, authorized = [], 0
    for line in (Path(run_dir) / "raw/events.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:  # a record still being appended
            continue
        if event.get("event") == "lifecycle":
            states.append(event["state"])
        authorized += event.get("event") == "mock_authorized"
    return states, authorized


def tree_digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def forbid_new_owners(monkeypatch):
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: pytest.fail("a refresh must not launch a worker"))
    monkeypatch.setattr("dcdc_bench.runner.run_mock", lambda *a, **k: pytest.fail("a refresh must not acquire in the UI process"))


@pytest.mark.integration
def test_run02_refresh_while_running_reattaches_to_the_single_worker(service, monkeypatch, detached):
    names = unique_mock_profiles(service, currents=(.05, .1, .15, .2, .25))
    preview = service.preview(*names)                               # "Preview test and limits"
    assert preview["supported"] and preview["mode"] == "mock" and preview["counts"]["executable"] == 5
    confirmation = {"plan_hash": preview["plan_hash"]}
    job_id = service.start(preview["plan_hash"], confirmation=confirmation, notes="RUN-02")["job_id"]  # "Start simulated test"
    detached.append(job_id)
    job = service._job(job_id)
    worker_log = lambda: (job / "worker.log").read_text(errors="replace")
    launch_pid = service.status(job_id)["pid"]
    assert launch_pid and worker_pids(job) == {launch_pid}

    def running():
        snapshot = service.status(job_id)
        return snapshot if (snapshot["state"] == "acquiring" and snapshot.get("execution_status") == "running"
                            and snapshot["progress"]["completed"] >= 1) else None
    before = wait_until(running, 40, lambda: f"sequence never reached RUNNING with a finished point: {service.status(job_id)}\n{worker_log()}")
    run_dir = Path(before["run_dir"])
    assert json.loads((run_dir / "run.json").read_text())["lifecycle_state"] == "RUNNING"
    runs_before = sorted(p.name for p in (job / "runs").iterdir())
    assert runs_before == [run_dir.name]
    pinned = {name: hashlib.sha256((job / name).read_bytes()).hexdigest() for name in ("plan.json", "request.json", "launch.json")}
    events_before = len(lifecycle(run_dir)[0])
    guard = pytest.MonkeyPatch()
    forbid_new_owners(guard)

    # Refresh #1: the same UI server gets a new client (F5).
    # Refresh #2: the UI process itself restarts on the same workspace.
    for ui_service in (service, JobService(service.root)):
        jobs, snapshot = page_load(ui_service)
        assert [j["job_id"] for j in jobs] == [job_id]
        assert snapshot["job_id"] == job_id and snapshot["state"] == "acquiring" and snapshot["execution_status"] == "running"
        assert snapshot["run_dir"] == str(run_dir) and snapshot["pid"] == launch_pid and snapshot["cancel_requested"] is False
        assert snapshot["progress"]["completed"] >= before["progress"]["completed"]
        assert snapshot["progress"]["total"] == 5
        # The operator previews and presses Start again after the refresh.
        again = ui_service.preview(*names)
        assert again["plan_hash"] == preview["plan_hash"]
        with pytest.raises(ValueError, match="already acquiring or reporting"):
            ui_service.start(again["plan_hash"], confirmation=confirmation, notes="")
        with pytest.raises(ValueError, match="already active"):
            ui_service.retry_report(job_id)

    # Still exactly one owner, one run directory, one job; nothing aborted or rearmed.
    assert worker_pids(job) == {launch_pid}
    assert sorted(p.name for p in (job / "runs").iterdir()) == runs_before
    assert sorted(p.name for p in (service.root / "jobs").iterdir()) == [job_id]
    assert {name: hashlib.sha256((job / name).read_bytes()).hexdigest() for name in pinned} == pinned
    assert not (job / "cancel.request").exists()
    live = service.status(job_id)
    assert live["state"] == "acquiring" and live["execution_status"] == "running" and live["pid"] == launch_pid, live
    states, authorized = lifecycle(run_dir)
    assert states[:5] == ARMING_SEQUENCE and len(states) >= events_before and authorized == 1

    # The untouched sequence then finishes on its own, with a single arming. The
    # acquisition worker exits with the report queued (drivers leave RAM first);
    # the UI's periodic dispatcher, called directly here, launches a fresh
    # report-only worker once nothing is active.
    wait_until(lambda: service.status(job_id)["state"] not in ACTIVE, 60,
               lambda: f"job did not finish: {service.status(job_id)}\n{worker_log()}")
    queued = JobService(service.root).status(job_id)
    assert queued["state"] == "report-queued" and queued["pid"] is None and queued["run_dir"] == str(run_dir), queued
    wait_until(lambda: not worker_pids(job), 10, lambda: f"acquisition worker outlived its queued job: {worker_pids(job)}")
    guard.undo()  # the dispatcher is the one place a report-only worker may be launched
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}
    wait_until(lambda: service.status(job_id)["state"] not in ACTIVE, 60,
               lambda: f"report did not finish: {service.status(job_id)}\n{worker_log()}")
    final = JobService(service.root).status(job_id)
    assert final["state"] == "completed", (final, worker_log())
    assert final["execution_status"] == "completed" and final["run_dir"] == str(run_dir)
    assert final["progress"]["completed"] == 5 and final["cancel_requested"] is False
    assert sorted(p.name for p in (job / "runs").iterdir()) == runs_before
    verify_integrity(run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    assert run["run_id"] == run_dir.name and run["clock"]["mode"] == "wall" and run["real_hardware_opened"] is False
    assert all(s["state"] == "OFF" and s["verified"] for s in run["shutdown"].values())
    assert lifecycle(run_dir) == (NORMAL_LIFECYCLE, 1)
    # job.json is written just before the worker exits; allow that exit to land.
    wait_until(lambda: not worker_pids(job), 10, lambda: f"worker outlived its completed job: {worker_pids(job)}")
    manifest = json.loads((Path(final["report_dir"]) / "build_manifest.json").read_text())
    assert manifest["renderer"] == "test_run02_reconnect stub", "the real renderer must not run in this test"
    assert "Traceback" not in worker_log(), worker_log()


def test_run02_opening_an_old_completed_job_starts_nothing_and_changes_nothing(service, monkeypatch):
    names = unique_mock_profiles(service, currents=(.05, .1))
    preview = service.preview(*names)
    with pytest.MonkeyPatch.context() as launch:  # no detached process; the worker runs below, in this process
        launch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
        job_id = service.start(preview["plan_hash"], confirmation={"plan_hash": preview["plan_hash"]})["job_id"]
    job = service._job(job_id)
    monkeypatch.setattr("dcdc_bench.job_service._render_process", lambda path: (write_stub_report(path), 0)[1])
    worker(job)  # in-process, virtual clock: acquisition ends with the report queued, no process left
    assert service.status(job_id)["state"] == "report-queued"
    with pytest.MonkeyPatch.context() as launch:  # the dispatcher's launch is replaced by the in-process worker below
        launch.setattr(service, "_launch", lambda directory, **kwargs: None)
        assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}
    worker(job, report_only=True)  # a finished job on disk without a detached process
    completed = service.status(job_id)
    assert completed["state"] == "completed" and completed["execution_status"] == "completed", completed
    run_dir = Path(completed["run_dir"])
    before = tree_digest(job)
    jobs_before = sorted(p.name for p in (service.root / "jobs").iterdir())
    forbid_new_owners(monkeypatch)

    # Reload the page, then open the saved run from Reports: select_job -> poll -> report_links.
    fresh = JobService(service.root)
    jobs, attached = page_load(fresh)
    assert [j["job_id"] for j in jobs] == [job_id] and attached is None  # nothing active to reattach to
    snapshot = fresh.status(job_id)
    assert snapshot["state"] == "completed" and snapshot["execution_status"] == "completed"
    assert snapshot["run_dir"] == str(run_dir) and snapshot["report_dir"] == completed["report_dir"]
    assert snapshot["cancel_requested"] is False and snapshot["report_artifacts"]["html"]["status"] == "skipped"
    assert fresh.resolve_file(job_id, "run/run.json") == run_dir / "run.json"
    assert fresh.resolve_file(job_id, "report/build_manifest.json").is_file()
    with pytest.raises(ValueError, match="No matching job artifact"):
        fresh.resolve_file(job_id, "run/")

    # Opening an old run resumed nothing: no process, no new job or run, no changed byte.
    assert worker_pids(job) == set()
    assert sorted(p.name for p in (service.root / "jobs").iterdir()) == jobs_before
    assert sorted(p.name for p in (job / "runs").iterdir()) == [run_dir.name]
    assert tree_digest(job) == before
    verify_integrity(run_dir)
    assert lifecycle(run_dir) == (NORMAL_LIFECYCLE, 1)
    assert all(s["state"] == "OFF" and s["verified"] for s in json.loads((run_dir / "run.json").read_text())["shutdown"].values())
