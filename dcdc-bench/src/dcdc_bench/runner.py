"""Bounded, process-owned mock acquisition. No real-instrument backend exists here."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
import platform
import subprocess
import tempfile
import time
import uuid
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

from .adapters import MODEL_PARAMETERS, MODEL_VERSION, MockBench
from .domain import Plan, RawSample
from .storage import PersistenceError, RunStore, atomic_json

SCENARIOS = {"normal", "setup-limited", "aborted", "timeout", "stale", "overrange",
             "malformed", "diskfailure", "crash", "unsettled", "shutdown-failure"}
QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")


class CommunicationTimeout(TimeoutError):
    pass


class Clock:
    def __init__(self, origin: str, real_time: bool):
        self.origin = datetime.fromisoformat(origin)
        self.elapsed = 0.0
        self.real_time = real_time
        self.started = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self.started if self.real_time else self.elapsed

    def utc(self, elapsed: float | None = None) -> str:
        return (self.origin + timedelta(seconds=self.now() if elapsed is None else elapsed)).isoformat()

    def wait(self, seconds: float) -> None:
        if self.real_time:
            time.sleep(max(0.0, seconds))
        else:
            self.elapsed += max(0.0, seconds)


def _git_provenance(directory: Path) -> dict:
    """Read repository identity without changing the index or requiring Git.

    A commit does not describe local edits or new files. Keep that distinction
    explicit; source-file hashes below identify the acquired software snapshot.
    """
    try:
        commit = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=directory,
            check=True, capture_output=True, text=True, timeout=3).stdout.strip()
        status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain=v1",
                                 "--untracked-files=normal"], cwd=directory,
            check=True, capture_output=True, text=True, timeout=3).stdout
        return {"commit": commit, "dirty": bool(status.strip()), "status": "available"}
    except (OSError, subprocess.SubprocessError):
        # Source archives, fresh repositories without a commit, missing Git and
        # read failures do not become fabricated clean-tree or commit claims.
        return {"commit": None, "dirty": None, "status": "unavailable"}


def _provenance() -> dict:
    directory = Path(__file__).parent
    hashes = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(directory.rglob("*.py"))}
    packages = {}
    for name in ("pydantic", "filelock", "PyYAML"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    lock = directory.parent.parent / "requirements-tested.txt"
    return {"python": platform.python_version(), "platform": platform.platform(),
            "git": _git_provenance(directory),
            "source_files_sha256": hashes, "dependencies": packages,
            "dependency_lock_file": lock.name,
            "dependency_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None}


def _initial_points(plan: Plan) -> list[dict]:
    return [{"point_id": p.point_id, "test_id": p.test_id,
             "vin_target_V": p.vin_target_V, "iout_target_A": p.iout_target_A,
             "planning_status": p.status, "qualification": "not-run" if p.feasible else "unsupported",
             "reason": "not reached" if p.feasible else p.reason,
             "acquisition_cycle_ids": [], "requirement_result": "not-evaluated"}
            for p in plan.points]


def _lock_paths(plan: Plan) -> list[Path]:
    root = Path(tempfile.gettempdir()) / "dcdc-bench-mock-locks"
    root.mkdir(exist_ok=True)
    resources = ["source:" + plan.bench.source.instrument_id + f":{plan.bench.source.channel}",
                 "load:" + plan.bench.load.instrument_id]
    return sorted(root / (hashlib.sha256(r.encode()).hexdigest() + ".lock") for r in resources)


def run_mock(plan: Plan, out: Path, scenario: str = "normal", real_time: bool = False,
             *, worker_timeout_s: float | None = None, seed: int = 1,
             operator_observations: list[str] | None = None,
             attachment_descriptors: list[dict] | None = None) -> Path:
    """Spawn one instrument owner and return its finalized, possibly partial run.

    Ordinary failure scenarios return evidence with an error/aborted execution
    status. Persistent filesystem failures are raised rather than reporting a
    durable success. This function never creates or imports real instruments.
    """
    from .planning import verify_plan_hash

    if not verify_plan_hash(plan):
        raise ValueError("plan hash mismatch; regenerate the plan after changing any settings")
    if plan.bench.mode != "mock" or plan.recipe.execution_mode != "mock":
        raise ValueError("run_mock accepts mock profiles only; real execution is not implemented")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    if any(test.type != "steady_state_load_sweep" for test in plan.recipe.tests):
        # The generic loop cold-starts every point; a UVLO ramp needs its own
        # phase-scoped procedure (uvlo.run_uvlo_mock) so off-steps are never
        # settled and qualified as ordinary operating points.
        raise ValueError("run_mock executes steady_state_load_sweep tests only; use the test type's own procedure")
    if any(v not in plan.bench.measurements for v in QUANTITIES):
        raise ValueError("mock acquisition requires four declared electrical measurement bindings")
    if plan.bench.source.max_current_A is None:
        raise ValueError("mock source current capability is required")
    recipe = plan.recipe
    maximum_virtual = len(plan.points) * (recipe.settling.timeout_s + recipe.acquisition.duration_s + 2)
    # The worker fsyncs every JSONL record, so its wall time follows the record
    # count and host I/O, not model time; a flat deadline interrupted healthy
    # runs on a loaded SD card.
    records = len(plan.points) * len(QUANTITIES) * math.ceil(
        (recipe.settling.timeout_s + recipe.acquisition.duration_s) / max(recipe.acquisition.target_poll_interval_s, 1e-3))
    io_budget = 120.0 + 0.1 * records
    timeout = worker_timeout_s if worker_timeout_s is not None else (maximum_virtual + io_budget if real_time else io_budget)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("worker timeout must be finite and positive")
    created = datetime.now(timezone.utc)
    run_id = created.strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    path = Path(out) / run_id
    snapshot = plan.model_dump(mode="json")
    run = {"schema_version": "1.0", "run_id": run_id, "data_source": "simulated",
           "execution_status": "running", "lifecycle_state": "VALIDATING",
           "created_utc": created.isoformat(), "plan_hash": plan.plan_hash,
           "scenario": scenario, "points": _initial_points(plan),
           "shutdown": {"source": {"state": "UNKNOWN"}, "load": {"state": "UNKNOWN"}},
           "model": {"version": MODEL_VERSION, "seed": seed, "parameters": MODEL_PARAMETERS},
           "clock": {"mode": "wall" if real_time else "virtual",
                     "note": "simulated acquisition; virtual timestamps are model time, not hardware observations"},
           "software": _provenance(), "durability_policy": "flush and fsync every JSONL record",
           "measurement_boundary": plan.bench.measurement_boundary,
           "operator_observations": list(operator_observations or []),
           "attachment_descriptors": list(attachment_descriptors or []),
           "real_hardware_opened": False, "errors": []}
    store = RunStore(path)
    store.initialize({"dut": snapshot["dut"], "bench": snapshot["bench"],
                      "recipe": snapshot["recipe"]}, snapshot, run)
    context = multiprocessing.get_context("spawn")
    cancel = context.Event()
    worker = context.Process(target=_worker, args=(snapshot, str(path), scenario, real_time, seed, cancel))
    worker.start()
    try:
        worker.join(timeout)
    except KeyboardInterrupt:
        cancel.set()
        worker.join(3)
    if worker.is_alive():
        cancel.set()
        worker.join(1)
    if worker.is_alive():
        worker.terminate()
        worker.join(5)
    if worker.is_alive():
        worker.kill()
        worker.join(5)
    if worker.exitcode != 0 or not (path / "integrity.json").exists():
        saved = json.loads((path / "run.json").read_text())
        saved.update(execution_status="interrupted", lifecycle_state="INTERRUPTED")
        reason = f"worker stopped without final evidence (exit code {worker.exitcode}); no automatic restart"
        saved["errors"].append(reason)
        saved["shutdown"] = {role: {"state": "UNKNOWN", "reason": reason} for role in ("source", "load")}
        store.append("events", {"event": "worker_interrupted", "reason": reason,
                                "timestamp_utc": datetime.now(timezone.utc).isoformat()})
        store.finalize(saved)
    return path


def _worker(snapshot: dict, directory: str, scenario: str, real_time: bool, seed: int, cancel) -> None:
    plan = Plan.model_validate(snapshot)
    store = RunStore(Path(directory))
    run = json.loads((store.path / "run.json").read_text())
    clock = Clock(run["created_utc"], real_time)
    bench = MockBench(plan.dut.ratings.output_voltage_nominal_V,
                      plan.bench.protective_controls.source_current_limit_A or plan.bench.source.max_current_A,
                      plan.bench.load.min_voltage_V, seed)
    serial = 0
    cycle_serial = 0
    persisted_samples = 0
    active: dict | None = None
    owned = False
    state = "completed"

    def event(kind: str, **detail) -> None:
        store.append("events", {"event": kind, "run_id": run["run_id"],
                                "timestamp_utc": clock.utc(), "monotonic_s": clock.now(), **detail})

    def transition(name: str) -> None:
        run["lifecycle_state"] = name
        event("lifecycle", state=name)

    def checkpoint() -> None:
        atomic_json(store.path / "run.json", run)

    def read_cycle(point, phase: str, fault: bool) -> tuple[str, list[dict], str, float]:
        nonlocal serial, cycle_serial, persisted_samples
        cycle_serial += 1
        cycle_id = f"c{cycle_serial:07d}"
        readings = []
        source_mode = "CV"
        begin = clock.now()
        for quantity in QUANTITIES:
            serial += 1
            started = clock.now()
            clock.wait(0.002)
            value, physical = bench.read(quantity, clock.now(), force_limit=fault and scenario == "setup-limited")
            source_mode = physical.source_mode
            flags = []
            binding = plan.bench.measurements[quantity]
            raw_response = repr(value)
            device_time = clock.utc()
            if physical.source_mode == "CC":
                flags.append("source-current-limited")
            if not physical.load_compliance:
                flags.append("load-out-of-compliance")
            if fault and scenario == "stale":
                flags.append("stale")
                device_time = clock.utc(0)
            if fault and scenario == "unsettled" and quantity == "Vout_V":
                value += 0.2 * (-1 if cycle_serial % 2 else 1)
                raw_response = repr(value)
            if fault and quantity == "Iin_A":
                if scenario == "overrange":
                    value = (binding.measurement_range or plan.bench.source.max_current_A) * 1.1
                    raw_response = repr(value)
                    flags.append("overrange")
                elif scenario == "malformed":
                    value, raw_response = None, "not-a-number"
                    flags.append("malformed")
                elif scenario == "timeout":
                    clock.wait(0.25)
                    value, raw_response = None, None
                    flags.append("timeout")
            if value is not None and binding.measurement_range is not None and abs(value) > binding.measurement_range:
                if "overrange" not in flags:
                    flags.append("overrange")
            sample = RawSample(
                sample_id=f"s{serial:08d}", run_id=run["run_id"], test_id=point.test_id,
                point_id=point.point_id, channel_id=binding.instrument_id + ":" + quantity,
                instrument_id=binding.instrument_id, quantity=quantity, value=value,
                unit=binding.unit, location=binding.location, query_start_utc=clock.utc(started),
                query_end_utc=clock.utc(), query_start_monotonic_s=started,
                query_end_monotonic_s=clock.now(), device_timestamp=device_time,
                measurement_range=binding.measurement_range, resolution=binding.resolution,
                acquisition_settings={"source_mode": source_mode, "load_compliance": physical.load_compliance,
                                      "sense_enabled": bench.sense_enabled, "mock_model": MODEL_VERSION},
                raw_response=raw_response, status="ok" if not flags else "invalid",
                quality_flags=flags, acquisition_cycle_id=cycle_id, phase=phase,
            ).model_dump(mode="json")
            if scenario == "diskfailure" and persisted_samples >= 8:
                raise PersistenceError("injected sample persistence failure")
            store.append("samples", sample)
            persisted_samples += 1
            readings.append(sample)
            if "timeout" in flags:
                raise CommunicationTimeout("mock Iin query exceeded its 0.25 s timeout")
        skew = clock.now() - begin
        if scenario == "crash" and phase == "acquiring":
            event("injected_crash", point_id=point.point_id)
            os._exit(76)
        return cycle_id, readings, source_mode, skew

    locks = ExitStack()
    try:
        transition("PLAN_READY")
        transition("AWAITING_ARM")
        event("mock_authorized", detail="explicit run_mock call; never arms real equipment")
        for path in _lock_paths(plan):
            locks.enter_context(FileLock(str(path), timeout=0.1))
        owned = True
        transition("CONNECTING")
        event("identified", identities=bench.identify())
        transition("PREFLIGHT")
        event("preflight", source_output="OFF", load_input="OFF", mode="mock")
        run["shutdown"] = {role: {"state": "OFF", "verified": True} for role in ("source", "load")}
        transition("RUNNING")
        attempted = 0
        fault_used = False
        for point, result in zip(plan.points, run["points"]):
            active = result
            if not point.feasible:
                store.append("points", {**result, "event": "not_executed", "monotonic_s": clock.now()})
                continue
            if cancel.is_set() or scenario == "aborted" and attempted >= 3:
                state = "aborted"
                event("controlled_stop", reason="operator cancellation" if cancel.is_set() else "mock abort after three attempted points")
                break
            attempted += 1
            fault = not fault_used and point.iout_target_A > 0 and scenario not in {"normal", "aborted"}
            if fault:
                fault_used = True
            event("point_phase", point_id=point.point_id, phase="configuring")
            bench.load_off()
            bench.source_off()
            bench.configure(point.vin_target_V, point.iout_target_A, clock.now())
            bench.source_on()
            if point.iout_target_A > 0:
                bench.load_on()
            event("configured", point_id=point.point_id, vin_target_V=point.vin_target_V,
                  iout_target_A=point.iout_target_A, source_output="ON", load_input="ON" if bench.load_enabled else "OFF",
                  remote_sense_verified=bench.sense_enabled)
            run["shutdown"] = {"source": {"state": "ON"}, "load": {"state": "ON" if bench.load_enabled else "OFF"}}
            checkpoint()
            event("point_phase", point_id=point.point_id, phase="settling")
            started = clock.now()
            window: deque[tuple[float, float]] = deque()
            settled = False
            limiting = False
            max_skew = 0.0
            sample_flags = set()
            while clock.now() - started <= plan.recipe.settling.timeout_s:
                if cancel.is_set():
                    break
                cycle, readings, mode, skew = read_cycle(point, "settling", fault)
                max_skew = max(max_skew, skew)
                limiting |= mode == "CC"
                sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                good = all(r["status"] == "ok" for r in readings) and skew <= plan.recipe.acquisition.maximum_interchannel_skew_s
                if good:
                    voltage = next(r["value"] for r in readings if r["quantity"] == "Vout_V")
                    window.append((clock.now(), voltage))
                else:
                    window.clear()
                while window and clock.now() - window[0][0] > plan.recipe.settling.window_s + plan.recipe.acquisition.target_poll_interval_s:
                    window.popleft()
                span = max((v for _, v in window), default=0) - min((v for _, v in window), default=0)
                if (clock.now() - started >= plan.recipe.settling.minimum_dwell_s
                        and len(window) >= plan.recipe.settling.minimum_fresh_samples
                        and window[-1][0] - window[0][0] >= plan.recipe.settling.window_s
                        and span <= plan.recipe.settling.maximum_vout_span_V):
                    settled = True
                    break
                if limiting:
                    break
                clock.wait(plan.recipe.acquisition.target_poll_interval_s)
            accepted = []
            acquisition_start = clock.now()
            if settled and not cancel.is_set():
                event("point_phase", point_id=point.point_id, phase="acquiring")
                acquisition_voltages = []
                while clock.now() - acquisition_start < plan.recipe.acquisition.duration_s:
                    if cancel.is_set():
                        break
                    cycle, readings, mode, skew = read_cycle(point, "acquiring", fault)
                    max_skew = max(max_skew, skew)
                    limiting |= mode == "CC"
                    sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                    if all(r["status"] == "ok" for r in readings) and skew <= plan.recipe.acquisition.maximum_interchannel_skew_s:
                        accepted.append(cycle)
                        acquisition_voltages.append(next(r["value"] for r in readings if r["quantity"] == "Vout_V"))
                    clock.wait(plan.recipe.acquisition.target_poll_interval_s)
                if acquisition_voltages and max(acquisition_voltages) - min(acquisition_voltages) > plan.recipe.settling.maximum_vout_span_V:
                    sample_flags.add("unsettled-acquisition")
                    accepted = []
            if cancel.is_set():
                state = "aborted"
                qualification, reason = "not-run", "cancelled before a complete acquisition window"
                accepted = []
            elif limiting:
                qualification, reason = "setup-limited", "source entered current limiting; requested input condition not achieved"
                accepted = []
            elif not settled:
                qualification, reason = "inconclusive", "no complete fresh stable settling window before timeout"
            elif len(accepted) < plan.recipe.acquisition.minimum_complete_cycles:
                qualification, reason = "inconclusive", "insufficient qualified complete acquisition cycles"
            else:
                qualification, reason = "valid", "fresh complete cycles acquired after electrical settling"
            result.update(qualification=qualification, reason=reason, acquisition_cycle_ids=accepted,
                          settled=settled, settling_elapsed_s=acquisition_start-started,
                          acquisition_elapsed_s=clock.now()-acquisition_start, maximum_interchannel_skew_s=max_skew,
                          complete_acquisition_cycles=len(accepted), quality_flags=sorted(sample_flags),
                          settling_vout_span_V=span)
            store.append("points", {**result, "event": "point_finalized", "monotonic_s": clock.now()})
            checkpoint()
            if state == "aborted":
                break
    except (Exception, KeyboardInterrupt) as exc:
        state = "aborted" if isinstance(exc, KeyboardInterrupt) else "error"
        message = f"{type(exc).__name__}: {exc}"
        run["errors"].append(message)
        if active is not None:
            active.update(qualification="error", reason=message, acquisition_cycle_ids=[])
        try:
            event("fault", reason=message)
        except PersistenceError:
            pass
    finally:
        run["lifecycle_state"] = "STOPPING"
        try:
            event("lifecycle", state="STOPPING")
        except PersistenceError:
            pass
        # Each cleanup action is independent of logging and the other device.
        if owned:
            for role, action, readback in (("load", bench.load_off, lambda: bench.load_enabled),
                                            ("source", bench.source_off, lambda: bench.source_enabled)):
                record = {"command": "OFF", "acknowledged": False, "state": "UNKNOWN", "verified": False}
                try:
                    if scenario == "shutdown-failure" and role == "load":
                        raise CommunicationTimeout("injected load shutdown timeout")
                    action()
                    record.update(acknowledged=True, state="ON" if readback() else "OFF", verified=True)
                except Exception as exc:
                    record["error"] = str(exc)
                    state = "error"
                    run["errors"].append(f"{role} shutdown: {exc}")
                run["shutdown"][role] = record
                try:
                    event("shutdown", role=role, **record)
                except PersistenceError:
                    pass
            bench.close()
        else:
            run["shutdown"] = {role: {"state": "UNKNOWN", "reason": "resource not owned; no commands sent"}
                               for role in ("source", "load")}
        run.update(execution_status=state, lifecycle_state=state.upper(), completed_utc=clock.utc(),
                   duration_s=clock.now(), raw_sample_count=persisted_samples)
        try:
            event("lifecycle", state="FINALIZING")
            event("lifecycle", state=state.upper())
            store.finalize(run)
        finally:
            locks.close()
