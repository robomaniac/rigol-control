"""Rendering is queued after verified OFF and dispatched only when the bench is idle and memory allows.

No Quarto or Chromium runs here: document tools are tiny shell scripts and the
browser is a fake whose process is a ``sleep``.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from dcdc_bench import resources
from dcdc_bench.cli import main
from dcdc_bench.job_service import ACTIVE, REPORT_QUEUED, JobService, _render_process, worker
from dcdc_bench.reporting import renderer
from dcdc_bench.resources import ENV_MIN_AVAILABLE_MIB, ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, MemoryGate
from dcdc_bench.storage import atomic_json
from test_job_service import finalized_fixture, mock_preview
from test_run02_reconnect import unique_mock_profiles

MEMINFO = "MemTotal: 926820 kB\nMemAvailable: {available} kB\nSwapTotal: 1713144 kB\nSwapFree: {swap_free} kB\n"
LOW = (40960, 102400)      # 40 MiB available, 100 MiB swap free
OK = (409600, 1024000)     # 400 MiB available, 1000 MiB swap free


def fake_reader(available_kib, swap_free_kib):
    def read(relative):
        if relative == "meminfo":
            return MEMINFO.format(available=available_kib, swap_free=swap_free_kib)
        if relative == "loadavg":
            return "0.5 0.4 0.3 1/100 999\n"
        return "VmRSS:\t20480 kB\n"
    return read


def alive(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def record(job):
    return json.loads((job / "job.json").read_text())


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))
    monkeypatch.setenv("DCDC_JOB_LAUNCHER", "detached")
    return JobService(tmp_path / "workspace")


def queued_job(service):
    """A finalized, verified-OFF job whose report has been queued (retry path)."""
    preview = mock_preview(service)
    with pytest.MonkeyPatch.context() as launch:
        launch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
        job_id = service.start(preview["plan_hash"])["job_id"]
    job = service._job(job_id)
    path = finalized_fixture(job, preview["plan"])
    state = record(job)
    state.update(state="failed", run_dir=str(path), pid=None)
    atomic_json(job / "job.json", state)
    assert service.retry_report(job_id) == {"job_id": job_id, "state": REPORT_QUEUED}
    return job_id


def capture_launches(service, monkeypatch):
    launched = []
    monkeypatch.setattr(service, "_launch", lambda directory, **kwargs: launched.append((directory.name, kwargs)))
    return launched


# (b) acquisition worker exits with the report queued -----------------------------------------

def test_acquisition_worker_queues_the_report_and_exits_without_rendering(service, monkeypatch):
    names = unique_mock_profiles(service, currents=(.05, .1))
    preview = service.preview(*names)
    with pytest.MonkeyPatch.context() as launch:  # no detached process; the worker runs below, in this process
        launch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
        job_id = service.start(preview["plan_hash"])["job_id"]
    job = service._job(job_id)
    monkeypatch.setattr("dcdc_bench.job_service._render_process",
                        lambda *args, **kwargs: pytest.fail("the acquisition worker must not spawn a report process"))
    worker(job)
    snapshot = service.status(job_id)
    assert snapshot["state"] == REPORT_QUEUED and snapshot["state"] not in ACTIVE
    assert snapshot["pid"] is None and snapshot["report_pending"] is True and snapshot["deferred_reason"] is None
    state = record(job)
    assert state["pid"] is None and state["queued_utc"] and state["acquisition_cancelled"] is False
    assert Path(state["run_dir"]).is_dir() and not (Path(state["run_dir"]) / "reports").exists()
    assert list((job / "runs").glob("*/reports")) == []
    for log in (job / "resources.jsonl", service.root / "resource-log.jsonl"):
        events = lines(log)
        assert [(e["task"], e["phase"]) for e in events] == [("acquisition", "start"), ("acquisition", "end")]
        end = events[-1]
        for key in ("utc", "monotonic_s", "pid", "task", "phase", "duration_s", "mem_available_mib", "swap_used_mib", "rss_mib"):
            assert key in end, key
        assert end["pid"] == os.getpid() and end["state"] == REPORT_QUEUED and end["job_id"] == job_id
        assert end["duration_s"] >= 0 and "duration_s" not in events[0]


# (c) the dispatcher ------------------------------------------------------------------------------

def test_dispatch_launches_exactly_one_report_worker_when_idle(service, monkeypatch):
    first, second = queued_job(service), queued_job(service)
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    assert service.dispatch_reports() == {"job_id": first, "state": "queued"}
    assert launched == [(first, {"report_only": True})]
    state = record(service._job(first))
    assert state["state"] == "queued" and state["action"] == "report-only" and state["deferred_reason"] is None
    assert state["dispatched_utc"] and not (service._job(first) / "cancel.request").exists()
    logged = [e for e in lines(service._job(first) / "resources.jsonl") if e["task"] == "dispatch"]
    assert [e["phase"] for e in logged] == ["start"] and logged[0]["mem_available_mib"] == 400.0
    # The launched job is active (queued): the second one waits.
    assert service.dispatch_reports() is None and len(launched) == 1
    assert service.status(second)["state"] == REPORT_QUEUED
    # A live report-only worker keeps the queue closed.
    state.update(state="reporting", pid=4242)
    atomic_json(service._job(first) / "job.json", state)
    monkeypatch.setattr("dcdc_bench.job_service._pid_matches", lambda pid, job: pid == 4242)
    assert service.status(first)["state"] == "reporting"
    assert service.dispatch_reports() is None and len(launched) == 1
    # When it finishes, the next queued job is dispatched.
    state.update(state="completed", pid=None)
    atomic_json(service._job(first) / "job.json", state)
    assert service.dispatch_reports() == {"job_id": second, "state": "queued"}
    assert [name for name, _ in launched] == [first, second]
    assert service.dispatch_reports() is None


def test_dispatch_does_nothing_while_a_job_is_acquiring(service, monkeypatch):
    queued = queued_job(service)
    preview = mock_preview(service)
    monkeypatch.setattr("dcdc_bench.job_service.subprocess.Popen", lambda *a, **k: SimpleNamespace(pid=None))
    acquiring = service.start(preview["plan_hash"])["job_id"]  # allowed: only report-queued jobs exist
    state = record(service._job(acquiring))
    state.update(state="acquiring", pid=777)
    atomic_json(service._job(acquiring) / "job.json", state)
    monkeypatch.setattr("dcdc_bench.job_service._pid_matches", lambda pid, job: pid == 777)
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    assert service.dispatch_reports() is None and launched == []
    assert service.status(queued)["state"] == REPORT_QUEUED and service.status(acquiring)["state"] == "acquiring"


def test_dispatch_defers_with_a_logged_reason_when_the_gate_fails(service, monkeypatch):
    job_id = queued_job(service)
    job = service._job(job_id)
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*LOW))
    outcome = service.dispatch_reports()
    assert outcome == {"job_id": job_id, "state": REPORT_QUEUED,
                       "deferred_reason": "MemAvailable below 150 MiB; MemAvailable+SwapFree below 600 MiB"}
    assert launched == []
    snapshot = service.status(job_id)
    assert snapshot["state"] == REPORT_QUEUED and snapshot["deferred_reason"] == outcome["deferred_reason"]
    assert snapshot["report_pending"] is True and record(job)["deferred_utc"]
    for log in (job / "resources.jsonl", service.root / "resource-log.jsonl"):
        deferred = [e for e in lines(log) if e["phase"] == "deferred"]
        assert len(deferred) == 1 and deferred[0]["task"] == "dispatch" and deferred[0]["job_id"] == job_id
        assert deferred[0]["reason"] == outcome["deferred_reason"] and deferred[0]["mem_available_mib"] == 40.0
    # The same verdict on the next tick neither rewrites job.json nor appends a line.
    before = (job / "job.json").read_bytes(), len(lines(job / "resources.jsonl"))
    assert service.dispatch_reports() == outcome
    assert ((job / "job.json").read_bytes(), len(lines(job / "resources.jsonl"))) == before
    # Memory returns: the deferral clears and one worker launches.
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}
    assert launched == [(job_id, {"report_only": True})]
    assert record(job)["deferred_reason"] is None and record(job)["deferred_utc"] is None


def test_dispatch_defers_while_the_bench_lease_is_held_elsewhere(service, monkeypatch):
    import signal
    from dcdc_bench.activity import activity_path
    job_id = queued_job(service)
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    # Another process (e.g. a CLI acquisition) holds the lease: flock(1) uses the
    # same flock(2) primitive as the lease's Unix backend.
    holder = subprocess.Popen(["flock", str(activity_path()), "sh", "-c", "echo held; exec sleep 30"],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        outcome = service.dispatch_reports()
    finally:
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait(timeout=5)
    assert outcome["state"] == REPORT_QUEUED and outcome["deferred_reason"].startswith("bench lease held")
    assert launched == [] and service.status(job_id)["state"] == REPORT_QUEUED
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}


def test_cancel_removes_a_queued_report_without_signalling(service, monkeypatch):
    job_id = queued_job(service)
    monkeypatch.setattr("dcdc_bench.job_service.os.pidfd_open", lambda pid: pytest.fail("nothing to signal"))
    monkeypatch.setattr("dcdc_bench.job_service.signal.pidfd_send_signal", lambda *a: pytest.fail("nothing to signal"))
    snapshot = service.cancel(job_id)
    assert snapshot["state"] == "cancelled" and "queue" in snapshot["error"] and snapshot["run_dir"]
    assert not (service._job(job_id) / "cancel.request").exists()
    launched = capture_launches(service, monkeypatch)
    assert service.dispatch_reports() is None and launched == []


def test_cancel_racing_dispatch_leaves_the_job_cancelled_and_launches_nothing(service, monkeypatch):
    """M1 scenario A: the operator's cancel lands after the dispatcher's queue scan and before the launch."""
    job_id = queued_job(service)
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    original = service._report_queue

    def racing(records=None):
        queue = original(records)
        service.cancel(job_id)  # in-process: the service lock is reentrant, so the record changes under the dispatcher
        return queue
    monkeypatch.setattr(service, "_report_queue", racing)
    assert service.dispatch_reports() is None
    assert launched == []
    state = record(service._job(job_id))
    assert state["state"] == "cancelled" and state.get("dispatched_utc") is None and "queue" in state["error"]
    assert service.status(job_id)["state"] == "cancelled"
    assert service.dispatch_reports() is None and launched == []


def test_cancel_during_a_deferral_never_resurrects_the_job(service, monkeypatch):
    """M1 scenario B: _defer re-reads the record before writing a deferral reason into it."""
    job_id = queued_job(service)
    launched = capture_launches(service, monkeypatch)

    class CancellingGate:
        def check(self):
            service.cancel(job_id)
            return False, "MemAvailable below 150 MiB", {"mem_available_mib": 40.0}
    service.gate = CancellingGate()
    outcome = service.dispatch_reports()
    assert outcome["state"] == "cancelled" and outcome["deferred_reason"] is None
    state = record(service._job(job_id))
    assert state["state"] == "cancelled" and state["deferred_reason"] is None and state.get("deferred_utc") is None
    assert launched == [] and service.dispatch_reports() is None
    log = service._job(job_id) / "resources.jsonl"
    assert not log.exists() or not [e for e in lines(log) if e["phase"] == "deferred"]


def test_malformed_gate_variable_defers_with_a_recorded_reason(service, monkeypatch):
    """m2: a non-numeric threshold must not stall the queue with nothing recorded on the job."""
    job_id = queued_job(service)
    launched = capture_launches(service, monkeypatch)
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "lots")
    service.gate = None  # thresholds come from the environment at each dispatch
    outcome = service.dispatch_reports()
    assert outcome["state"] == REPORT_QUEUED and outcome["deferred_reason"].startswith("memory gate misconfigured")
    assert ENV_MIN_AVAILABLE_MIB in outcome["deferred_reason"] and "'lots'" in outcome["deferred_reason"]
    assert launched == [] and service.status(job_id)["deferred_reason"] == outcome["deferred_reason"]
    deferred = [e for e in lines(service._job(job_id) / "resources.jsonl") if e["phase"] == "deferred"]
    assert len(deferred) == 1 and deferred[0]["reason"] == outcome["deferred_reason"]
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "0")
    monkeypatch.setenv(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, "0")
    assert service.dispatch_reports() == {"job_id": job_id, "state": "queued"}
    assert launched == [(job_id, {"report_only": True})]


def test_idle_dispatch_reads_job_records_only(service, monkeypatch):
    """m3: while deferred with no active job, the 2 s tick reads job.json files, never run.json or sample tails."""
    job_id = queued_job(service)
    capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*LOW))
    monkeypatch.setattr(service, "status", lambda job: pytest.fail("idle dispatch must not derive full job status"))
    monkeypatch.setattr("dcdc_bench.job_service._latest_cycle", lambda path: pytest.fail("idle dispatch must not read sample tails"))
    assert service.dispatch_reports()["state"] == REPORT_QUEUED
    assert service.dispatch_reports()["state"] == REPORT_QUEUED
    assert record(service._job(job_id))["deferred_reason"].startswith("MemAvailable below")


# (d) retry queues; acquisition keeps priority ----------------------------------------------------

def test_retry_queues_instead_of_refusing_and_acquisition_keeps_priority(service, monkeypatch):
    first, second = queued_job(service), queued_job(service)
    assert [service.status(job)["state"] for job in (first, second)] == [REPORT_QUEUED, REPORT_QUEUED]
    assert record(service._job(first))["queued_utc"] < record(service._job(second))["queued_utc"]
    launched = capture_launches(service, monkeypatch)
    service.gate = MemoryGate(150, 600, reader=fake_reader(*OK))
    # Acquisition may start while only report-queued jobs exist.
    preview = mock_preview(service)
    acquisition = service.start(preview["plan_hash"])["job_id"]
    assert launched == [(acquisition, {})] and service.status(acquisition)["state"] == "queued"
    # Neither queued report is started while acquisition is pending or running.
    assert service.dispatch_reports() is None and len(launched) == 1
    state = record(service._job(acquisition))
    state.update(state="reporting", pid=999)
    atomic_json(service._job(acquisition) / "job.json", state)
    monkeypatch.setattr("dcdc_bench.job_service._pid_matches", lambda pid, job: pid == 999)
    with pytest.raises(ValueError, match="already acquiring or reporting"):
        service.start(preview["plan_hash"])
    with pytest.raises(ValueError, match="already active"):
        service.retry_report(acquisition)
    assert service.dispatch_reports() is None and len(launched) == 1
    # Re-queuing an already queued job is harmless and never launches anything.
    assert service.retry_report(first) == {"job_id": first, "state": REPORT_QUEUED}
    assert len(launched) == 1
    assert [service.status(job)["state"] for job in (first, second)] == [REPORT_QUEUED, REPORT_QUEUED]


# (e) the report process session is swept on the normal path -------------------------------------

def test_render_process_sweeps_survivors_of_the_report_session(tmp_path, monkeypatch):
    monkeypatch.setattr("dcdc_bench.job_service._report_command", lambda path, annotations=None: ["sh", "-c", "sleep 300 & exit 0"])
    log = tmp_path / "resources.jsonl"
    assert _render_process(tmp_path, log_path=log) == 0
    events = lines(log)
    assert [e["phase"] for e in events] == ["start", "survivors", "survivors", "end"]
    assert all(e["task"] == "report-process" for e in events)
    first, last = events[1], events[2]
    assert first["count"] >= 1 and last["count"] == 0 and last["terminated"]
    survivor = first["processes"][0]
    assert survivor["comm"] in ("sh", "sleep") and survivor["pgrp"] == events[0]["child_pid"]
    assert not alive(survivor["pid"])
    assert resources.session_survivors(events[0]["child_pid"]) == []
    end = events[-1]
    assert end["returncode"] == 0 and end["child_pid"] == events[0]["child_pid"]
    assert end["duration_s"] >= 0 and end["child_peak_rss_mib"] >= 0


def test_render_process_logs_into_the_job_directory_by_default(tmp_path, monkeypatch):
    job = tmp_path / "jobs" / "job-1"
    run_dir = job / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    atomic_json(job / "job.json", {"job_id": "job-1"})
    monkeypatch.setattr("dcdc_bench.job_service._report_command", lambda path, annotations=None: ["true"])
    assert _render_process(run_dir) == 0
    events = lines(job / "resources.jsonl")
    assert [e["phase"] for e in events] == ["start", "survivors", "end"] and events[1]["count"] == 0


# (f) document tools run in their own group; timeouts kill grandchildren --------------------------

def test_run_tool_timeout_kills_the_grandchild_and_records_usage(tmp_path):
    log = tmp_path / "resources.jsonl"
    result = renderer._run_tool(["sh", "-c", "sleep 300 & echo $! > bg.pid; exec sleep 300"],
                                cwd=tmp_path, timeout_s=.5, log_path=log, task="quarto-html")
    usage = result.usage
    assert usage["timed_out"] is True and result.returncode is not None and result.returncode != 0
    grandchild = int((tmp_path / "bg.pid").read_text())
    assert not alive(grandchild) and not alive(usage["pid"])
    assert usage["pid"] > 1 and usage["duration_s"] >= .5 and usage["survivors_remaining"] == []
    assert usage["peak_child_rss_mib"] >= 0 and usage["command"][0] == "sh"
    events = lines(log)
    assert [(e["task"], e["phase"]) for e in events] == [("quarto-html", "start"), ("quarto-html", "survivors"), ("quarto-html", "end")]
    assert events[-1]["timed_out"] is True and events[-1]["child_pid"] == usage["pid"]


def test_render_report_manifest_records_tool_survivors_and_stops_them(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))
    tool = tmp_path / "quarto-fixture.sh"
    tool.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "fixture 0.0"; exit 0; fi\n'
                    'sleep 300 >/dev/null 2>&1 &\necho $! > "survivor-$4.pid"\n'
                    'printf \'<html><script id="dcdc-plotly-runtime"></script></html>\' > report.html\n')
    tool.chmod(0o755)
    monkeypatch.setattr(renderer, "_quarto", lambda: str(tool))
    monkeypatch.setattr(renderer, "_browser_path", lambda: None)
    monkeypatch.setattr(renderer, "_static_figures", lambda *args: {"reused": False})
    out = tmp_path / "r0001"
    out.mkdir()
    atomic_json(out / "memory_gate.json", {"ok": True, "reason": "memory thresholds met", "thresholds": {}, "snapshot": {}})
    model = {"run_id": "queue-test", "analysis_id": "a-test", "dut": {}, "points": [], "figures": [], "metrics": [], "summary": []}
    manifest = renderer.render_report(model, out, formats=("html",))
    assert manifest["artifacts"]["html"]["status"] == "success" and manifest["memory_gate"]["ok"] is True
    usage = manifest["resource_usage"]["html"]
    survivor = int((out / "survivor-html.pid").read_text())
    assert [p["pid"] for p in usage["survivors"]] == [survivor] and usage["survivors_remaining"] == []
    assert not alive(survivor) and usage["timed_out"] is False and usage["returncode"] == 0
    assert usage["pid"] > 1 and usage["duration_s"] >= 0 and usage["peak_child_rss_mib"] > 0
    written = json.loads((out / "build_manifest.json").read_text())
    assert written["resource_usage"]["html"]["survivors"] == usage["survivors"]
    events = lines(out / "resources.jsonl")
    assert [(e["task"], e["phase"]) for e in events] == [("static-figures", "start"), ("static-figures", "end"),
        ("quarto-html", "start"), ("quarto-html", "survivors"), ("quarto-html", "end")]
    assert events[3]["count"] == 1 and events[1]["reused"] is False


# Chromium hygiene when Kaleido's close() hangs -----------------------------------------------------

def test_browser_pid_comes_from_the_choreographer_subprocess_handle():
    assert renderer._browser_pid(SimpleNamespace(subprocess=SimpleNamespace(pid=1234))) == 1234
    assert renderer._browser_pid(SimpleNamespace(subprocess=None)) is None
    assert renderer._browser_pid(object()) is None
    assert renderer._browser_pid(SimpleNamespace(subprocess=SimpleNamespace(pid=0))) is None


def test_static_close_timeout_terminates_the_browser_group(tmp_path, monkeypatch):
    sleeper = subprocess.Popen(["sleep", "300"], start_new_session=True, stdin=subprocess.DEVNULL)

    class Browser:
        def __init__(self, **kwargs):
            self.subprocess = sleeper

        async def open(self):
            pass

        async def write_fig(self, figure, *, path, opts, cancel_on_error):
            path.write_text("vector fixture")

        async def close(self):
            await asyncio.sleep(1)

    monkeypatch.setitem(sys.modules, "kaleido", SimpleNamespace(Kaleido=Browser))
    monkeypatch.setattr(renderer, "_plot_figure", lambda *args: {})
    monkeypatch.setattr(renderer, "STATIC_CLOSE_TIMEOUT_S", .05)
    log = tmp_path / "resources.jsonl"
    with pytest.raises(TimeoutError):
        asyncio.run(renderer._write_static_figures({"figures": [{"id": "fig-one"}]}, tmp_path, log_path=log))
    assert sleeper.wait(timeout=5) < 0
    event = lines(log)[-1]
    assert event["task"] == "static-figures" and event["phase"] == "survivors"
    assert event["child_pid"] == sleeper.pid and event["count"] == 1 and event["remaining"] == []


# (h) the CLI/service path refuses without free memory ----------------------------------------------

@pytest.fixture(scope="module")
def mock_run(tmp_path_factory):
    from dcdc_bench.runner import run_mock
    from dcdc_bench.services import default_plan
    return run_mock(default_plan(), tmp_path_factory.mktemp("queue-gate"))


def test_report_run_refuses_when_the_gate_fails_and_writes_nothing(mock_run, monkeypatch, capsys):
    from dcdc_bench.services import report_run
    before = sorted(str(p.relative_to(mock_run)) for p in mock_run.rglob("*"))
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "150")
    monkeypatch.setenv(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, "600")
    monkeypatch.setattr(resources, "read_proc", fake_reader(*LOW))
    monkeypatch.setattr("dcdc_bench.reporting.render_report", lambda *a, **k: pytest.fail("nothing must render"))
    with pytest.raises(renderer.ReportRenderError, match="MemAvailable below 150 MiB") as excinfo:
        report_run(mock_run, formats=("html",))
    message = str(excinfo.value)
    for expected in ("nothing was rendered", '"min_available_mib": 150.0', '"mem_available_mib": 40.0',
                     ENV_MIN_AVAILABLE_MIB, ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB):
        assert expected in message, expected
    assert sorted(str(p.relative_to(mock_run)) for p in mock_run.rglob("*")) == before
    assert not (mock_run / "reports").exists()
    assert main(["report", str(mock_run), "--formats", "html"]) == 3
    assert "MemAvailable below 150 MiB" in capsys.readouterr().err
    assert not (mock_run / "reports").exists()


def test_report_run_records_the_passing_gate_for_the_manifest(mock_run, monkeypatch):
    from dcdc_bench.services import report_run
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "150")
    monkeypatch.setenv(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, "600")
    monkeypatch.setattr(resources, "read_proc", fake_reader(*OK))
    rendered = []
    monkeypatch.setattr("dcdc_bench.reporting.render_report", lambda model, out, **kw: rendered.append(Path(out)))
    directory = report_run(mock_run, formats=("html",))
    assert rendered == [directory]
    verdict = json.loads((directory / "memory_gate.json").read_text())
    assert verdict["ok"] is True and verdict["reason"] == "memory thresholds met"
    assert verdict["thresholds"]["min_available_mib"] == 150 and verdict["thresholds"]["enabled"] is True
    assert verdict["snapshot"]["mem_available_mib"] == 400.0 and verdict["snapshot"]["swap_used_mib"] > 0
