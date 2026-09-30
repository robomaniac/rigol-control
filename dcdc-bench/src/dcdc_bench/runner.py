"""Bounded, process-owned mock acquisition. No real-instrument backend exists here.

The generic steady-state loop mirrors the real configured procedure
(``real_backend.ConfiguredProcedure``): every input-voltage phase cold-starts
from both outputs OFF, passes a five-cycle source-only startup gate before the
load input is enabled, stops on the source boundary (CC, or Iin at 99.5 % of
the limit) with the remaining loads of that phase left not-run, and refuses to
enable the load when the output is not in band after the gate. The plant it
drives is ``adapters.MockBench.for_plan`` (synthetic, documented in
docs/simulation-plant.md).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
import platform
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock

from .adapters import MODEL_VERSION, MockBench
from .domain import Plan, RawSample
from .mock_thermal import MockThermalProvider
from .planning import MOCK_DEADLINE_FIXED_S, MOCK_DEADLINE_SECONDS_PER_RECORD, mock_run_estimate
from .storage import PersistenceError, RunStore, atomic_json
from .thermal import THERMAL_PHASE, evaluate_thermal_window, thermal_policy_for

SCENARIOS = {"normal", "setup-limited", "aborted", "timeout", "stale", "overrange",
             "malformed", "diskfailure", "crash", "unsettled", "shutdown-failure"}
QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")
# Startup gate and boundary rules, mirrored from real_backend.ConfiguredProcedure.
STARTUP_CYCLES = 5
STARTUP_INTERVAL_S = 1.0
OUTPUT_IN_BAND_FRACTION = 0.9
NEAR_LIMIT_FRACTION = 0.995
BOUNDARY_CONFIRMATION_S = 1.2  # longer than the source's readback hold, so the retained boundary observation is fresh
STARTUP_FAILURE_REASON = "Output below startup/operating threshold; load will not be enabled or increased"
BOUNDARY_REASON = "Source headroom/current boundary reached; nominal-input efficiency is unqualified"
LIMITED_REASON = "source entered current limiting; requested input condition not achieved"
TERMINATED_REASON = ("SIGTERM received (service stop or RuntimeMaxSec): simulated acquisition finalized as interrupted "
                     "with outputs verified OFF; no automatic restart")


class CommunicationTimeout(TimeoutError):
    pass


class WorkerTerminated(BaseException):
    """Raised inside the plant owner by its SIGTERM handler so the run is finalized, never killed mid-record."""


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
             attachment_descriptors: list[dict] | None = None,
             thermal_parameters: dict | None = None) -> Path:
    """Spawn one instrument owner and return its finalized, possibly partial run.

    Ordinary failure scenarios return evidence with an error/aborted execution
    status. Persistent filesystem failures are raised rather than reporting a
    durable success. A plan whose record volume cannot fit the simulated-run
    budget is refused before any directory is created. SIGTERM (a service stop
    or the unit's RuntimeMaxSec) is trapped in both processes: the plant owner
    finalizes the run as ``interrupted`` with ``integrity.json`` written. This
    function never creates or imports real instruments.
    """
    from .planning import verify_plan_hash

    if not verify_plan_hash(plan):
        raise ValueError("plan hash mismatch; regenerate the plan after changing any settings")
    if plan.bench.mode != "mock":  # the bench decides; a legacy recipe mode is metadata
        raise ValueError("run_mock accepts mock profiles only; real execution is not implemented")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    if any(test.type != "steady_state_load_sweep" for test in plan.recipe.tests):
        # The generic loop cold-starts every input-voltage phase; a UVLO ramp needs its own
        # phase-scoped procedure (uvlo.run_uvlo_mock) so off-steps are never
        # settled and qualified as ordinary operating points.
        raise ValueError("run_mock executes steady_state_load_sweep tests only; use the test type's own procedure")
    if any(v not in plan.bench.measurements for v in QUANTITIES):
        raise ValueError("mock acquisition requires four declared electrical measurement bindings")
    if plan.bench.source.max_current_A is None:
        raise ValueError("mock source current capability is required")
    if worker_timeout_s is not None and (not math.isfinite(worker_timeout_s) or worker_timeout_s <= 0):
        raise ValueError("worker timeout must be finite and positive")
    estimate = mock_run_estimate(plan)
    if not estimate["within_budget"]:
        raise ValueError("Simulated run refused: " + estimate["reason"])
    recipe = plan.recipe
    thermal_timeout = max((t.thermal_settling.timeout_s for t in recipe.tests if t.thermal_settling), default=0.)
    phases = estimate["phases"]
    maximum_virtual = (len(plan.points) * (recipe.settling.timeout_s + thermal_timeout + recipe.acquisition.duration_s + 2)
                       + phases * 2 * STARTUP_CYCLES * STARTUP_INTERVAL_S)
    # The worker fsyncs every JSONL record, so its wall time follows the record
    # count and host I/O, not model time; a flat deadline interrupted healthy
    # runs on a loaded SD card. planning.mock_run_estimate is the single source
    # of the record arithmetic and of the budget the plan was checked against.
    io_budget = MOCK_DEADLINE_FIXED_S + MOCK_DEADLINE_SECONDS_PER_RECORD * estimate["records"]
    timeout = worker_timeout_s if worker_timeout_s is not None else (maximum_virtual + io_budget if real_time else io_budget)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("worker timeout must be finite and positive")
    plant = MockBench.for_plan(plan, seed)
    created = datetime.now(timezone.utc)
    run_id = created.strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8]
    path = Path(out) / run_id
    snapshot = plan.model_dump(mode="json")
    run = {"schema_version": "1.0", "run_id": run_id, "data_source": "simulated",
           "execution_status": "running", "lifecycle_state": "VALIDATING",
           "created_utc": created.isoformat(), "plan_hash": plan.plan_hash,
           "scenario": scenario, "points": _initial_points(plan),
           "shutdown": {"source": {"state": "UNKNOWN"}, "load": {"state": "UNKNOWN"}},
           "model": {"version": MODEL_VERSION, "seed": seed, "parameters": plant.parameters()},
           "method": {"startup_gate": {"source_only_cycles": STARTUP_CYCLES, "interval_s": STARTUP_INTERVAL_S,
                                       "output_in_band_required_from_cycle": STARTUP_CYCLES,
                                       "lower_output_V": OUTPUT_IN_BAND_FRACTION * plan.dut.ratings.output_voltage_nominal_V,
                                       "load_enabled_only_after_gate": True, "loaded_startup_cycles": STARTUP_CYCLES},
                      "phase_stop": {"on": ["source not in CV", f"Iin >= {NEAR_LIMIT_FRACTION:g} x source current limit",
                                            "output below the startup/operating threshold after the gate"],
                                     "remaining_loads_of_the_phase": "not-run", "mirrors": "real_backend.ConfiguredProcedure.guard",
                                     "boundary_confirmation_s": BOUNDARY_CONFIRMATION_S},
                      "run_budget": {key: estimate[key] for key in ("records", "typical_s", "deadline_s", "budget_s")}},
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
    terminate = context.Event()
    worker = context.Process(target=_worker, args=(snapshot, str(path), scenario, real_time, seed, cancel, terminate,
                                                   thermal_parameters))
    previous_handler = None
    if threading.current_thread() is threading.main_thread():
        # KillMode=control-group delivers SIGTERM to this process and to the plant owner at once. The owner
        # finalizes itself; this side only records the request and keeps waiting for that finalization.
        def on_terminate(signum, frame):
            terminate.set()
            cancel.set()
        previous_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, on_terminate)
    worker.start()
    try:
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
    finally:
        if previous_handler is not None:
            signal.signal(signal.SIGTERM, previous_handler)
        elif threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
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


def _worker(snapshot: dict, directory: str, scenario: str, real_time: bool, seed: int, cancel, terminate,
            thermal_parameters: dict | None = None) -> None:
    terminating: list[float] = []

    def on_sigterm(signum, frame):
        terminate.set()
        if terminating:
            return  # a second signal never interrupts the best-effort shutdown and finalization
        terminating.append(time.monotonic())
        raise WorkerTerminated(TERMINATED_REASON)

    signal.signal(signal.SIGTERM, on_sigterm)
    plan = Plan.model_validate(snapshot)
    store = RunStore(Path(directory))
    run = json.loads((store.path / "run.json").read_text())
    clock = Clock(run["created_utc"], real_time)
    bench = MockBench.for_plan(plan, seed)
    # Synthetic temperature channels exist only for a mock bench profile; the
    # provider is attached to the plant so bench.read serves every bound role.
    thermal = (MockThermalProvider.attach(plan.bench, bench, seed, thermal_parameters)
               if plan.bench.temperature_sensors else None)
    if thermal is not None:
        run["thermal_model"] = thermal.identify()
    lower_output = OUTPUT_IN_BAND_FRACTION * plan.dut.ratings.output_voltage_nominal_V
    serial = 0
    cycle_serial = 0
    persisted_samples = 0
    active: dict | None = None
    owned = False
    state = "completed"

    def stopping() -> bool:
        return cancel.is_set() or terminate.is_set()

    def event(kind: str, **detail) -> None:
        store.append("events", {"event": kind, "run_id": run["run_id"],
                                "timestamp_utc": clock.utc(), "monotonic_s": clock.now(), **detail})

    def transition(name: str) -> None:
        run["lifecycle_state"] = name
        event("lifecycle", state=name)

    def checkpoint() -> None:
        atomic_json(store.path / "run.json", run)

    def read_cycle(point, phase: str, fault: bool) -> tuple[str, list[dict], str, float, bool]:
        """One quartet of queries; the last flag says whether the source boundary was reached in it."""
        nonlocal serial, cycle_serial, persisted_samples
        cycle_serial += 1
        cycle_id = f"c{cycle_serial:07d}"
        readings = []
        source_mode = "CV"
        boundary = False
        begin = clock.now()
        for quantity in QUANTITIES:
            serial += 1
            started = clock.now()
            clock.wait(bench.query_round_trip_s())
            value, physical = bench.read(quantity, clock.now(), force_limit=fault and scenario == "setup-limited")
            source_mode = physical.source_mode
            flags = []
            binding = plan.bench.measurements[quantity]
            raw_response = repr(value)
            device_time = clock.utc()
            if physical.source_mode == "CC":
                flags.append("source-current-limited")
                boundary = True
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
            if quantity == "Iin_A" and value is not None and not flags and value >= NEAR_LIMIT_FRACTION * bench.current_limit:
                boundary = True  # the real guard stops the phase at 99.5 % of the source current setting (clean readings only)
            sample = RawSample(
                sample_id=f"s{serial:08d}", run_id=run["run_id"], test_id=point.test_id,
                point_id=point.point_id, channel_id=binding.instrument_id + ":" + quantity,
                instrument_id=binding.instrument_id, quantity=quantity, value=value,
                unit=binding.unit, location=binding.location, query_start_utc=clock.utc(started),
                query_end_utc=clock.utc(), query_start_monotonic_s=started,
                query_end_monotonic_s=clock.now(), device_timestamp=device_time,
                measurement_range=binding.measurement_range, resolution=binding.resolution,
                acquisition_settings={"source_mode": source_mode, "load_compliance": physical.load_compliance,
                                      "load_enabled": bench.load_enabled,
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
        return cycle_id, readings, source_mode, skew, boundary

    def read_thermal(point, phase: str) -> list[dict]:
        """Log every bound temperature channel; thermal cycles carry their own ids."""
        nonlocal serial, cycle_serial, persisted_samples
        if thermal is None:
            return []
        cycle_serial += 1
        cycle_id = f"t{cycle_serial:07d}"
        readings = []
        for quantity in thermal.quantities:
            serial += 1
            started = clock.now()
            clock.wait(bench.query_round_trip_s())
            value, state = bench.read(quantity, clock.now())
            binding = plan.bench.measurements[quantity]
            sample = RawSample(
                sample_id=f"s{serial:08d}", run_id=run["run_id"], test_id=point.test_id,
                point_id=point.point_id, channel_id=binding.instrument_id + ":" + quantity,
                instrument_id=binding.instrument_id, quantity=quantity, value=value,
                unit=binding.unit, location=binding.location, query_start_utc=clock.utc(started),
                query_end_utc=clock.utc(), query_start_monotonic_s=started,
                query_end_monotonic_s=clock.now(), device_timestamp=clock.utc(),
                measurement_range=binding.measurement_range, resolution=binding.resolution,
                acquisition_settings={"data_source": state.data_source, "thermal_model": state.model_version,
                                      "sensor_id": state.sensor_id, "sensor_role": state.role},
                raw_response=repr(value), status="ok", quality_flags=[], acquisition_cycle_id=cycle_id, phase=phase,
            ).model_dump(mode="json")
            store.append("samples", sample)
            persisted_samples += 1
            readings.append(sample)
        return readings

    def startup_cycles(point, fault: bool, *, loaded: bool) -> tuple[float | None, float, bool, set[str]]:
        """Five guarded startup cycles at 1 s: (last Vout, max skew, boundary reached, flags)."""
        last_vout, max_skew, boundary, flags = None, 0.0, False, set()
        for _ in range(STARTUP_CYCLES):
            if stopping():
                break
            clock.wait(STARTUP_INTERVAL_S)
            cycle, readings, mode, skew, hit = read_cycle(point, "starting", fault)
            max_skew = max(max_skew, skew)
            flags.update(flag for r in readings for flag in r["quality_flags"])
            vout = next((r["value"] for r in readings if r["quantity"] == "Vout_V"), None)
            if vout is not None:
                last_vout = vout
            if hit:
                boundary = True
                break
        return last_vout, max_skew, boundary, flags

    def end_phase(reason: str | None = None) -> None:
        bench.load_off()
        bench.source_off()
        run["shutdown"] = {role: {"state": "OFF", "verified": True} for role in ("source", "load")}
        event("phase_complete", vin_target_V=bench.source_voltage, source_output="OFF", load_input="OFF",
              **({"stop_reason": reason} if reason else {}))

    locks = ExitStack()
    try:
        transition("PLAN_READY")
        transition("AWAITING_ARM")
        event("mock_authorized", detail="explicit run_mock call; never arms real equipment")
        for path in _lock_paths(plan):
            locks.enter_context(FileLock(str(path), timeout=0.1))
        owned = True
        transition("CONNECTING")
        event("identified", identities={**bench.identify(), **({"thermal": thermal.identify()} if thermal else {})})
        transition("PREFLIGHT")
        event("preflight", source_output="OFF", load_input="OFF", mode="mock")
        run["shutdown"] = {role: {"state": "OFF", "verified": True} for role in ("source", "load")}
        transition("RUNNING")
        attempted = 0
        fault_used = False
        phase_key: tuple[str, float] | None = None
        phase_open = False
        phase_dead_reason: str | None = None
        for point, result in zip(plan.points, run["points"]):
            active = result
            if not point.feasible:
                store.append("points", {**result, "event": "not_executed", "monotonic_s": clock.now()})
                continue
            key = (point.test_id, point.vin_target_V)
            if key == phase_key and phase_dead_reason is not None:
                # The phase stopped at a lower load: the real guard never tries a higher load at this input.
                result.update(qualification="not-run", acquisition_cycle_ids=[],
                              reason=f"not reached: the {point.vin_target_V:g} V input-voltage phase ended — {phase_dead_reason}")
                store.append("points", {**result, "event": "not_executed", "monotonic_s": clock.now()})
                continue
            if stopping() or scenario == "aborted" and attempted >= 3:
                state = "interrupted" if terminate.is_set() else "aborted"
                event("controlled_stop", reason=TERMINATED_REASON if terminate.is_set() else
                      "operator cancellation" if cancel.is_set() else "mock abort after three attempted points")
                break
            attempted += 1
            fault = not fault_used and point.iout_target_A > 0 and scenario not in {"normal", "aborted"}
            if fault:
                fault_used = True
            started = clock.now()
            max_skew = 0.0
            sample_flags: set[str] = set()
            boundary = False
            gate_failed = False
            if key != phase_key:
                # Cold start of a new input-voltage phase from both outputs OFF, as the real bench does.
                if phase_open:
                    end_phase()
                phase_key, phase_dead_reason = key, None
                first_loaded = next((p.iout_target_A for p in plan.points if p.feasible
                                     and (p.test_id, p.vin_target_V) == key and p.iout_target_A > 0), 0.05)
                event("point_phase", point_id=point.point_id, phase="configuring")
                bench.configure(point.vin_target_V, first_loaded, clock.now())
                bench.source_on(clock.now())
                phase_open = True
                event("configured", point_id=point.point_id, vin_target_V=point.vin_target_V,
                      iout_target_A=point.iout_target_A, source_output="ON", load_input="OFF",
                      remote_sense_verified=bench.sense_enabled, startup="source-only gate")
                run["shutdown"] = {"source": {"state": "ON"}, "load": {"state": "OFF"}}
                checkpoint()
                event("point_phase", point_id=point.point_id, phase="starting")
                vout, max_skew, boundary, flags = startup_cycles(point, fault, loaded=False)
                sample_flags.update(flags)
                if not boundary and not stopping() and (vout is None or vout < lower_output):
                    gate_failed = True
                    result["startup_gate"] = (f"failed: output {vout if vout is None else round(vout, 3)} V below "
                                              f"{lower_output:g} V after {STARTUP_CYCLES} source-only cycles")
                elif not boundary and not stopping():
                    result["startup_gate"] = (f"passed: {STARTUP_CYCLES} source-only cycles with output in band "
                                              "before the load was enabled")
            if not gate_failed and not boundary and not stopping():
                if point.iout_target_A == 0:
                    # Enabled no-load observation: the load input stays OFF (input disabled, not CC 0 A).
                    bench.load_off()
                else:
                    bench.set_load_current(point.iout_target_A, clock.now())
                    if not bench.load_enabled:
                        bench.load_on(clock.now())
                        run["shutdown"]["load"] = {"state": "ON"}
                        event("load_enabled", point_id=point.point_id, requested_load_A=point.iout_target_A)
                        _, skew, boundary, flags = startup_cycles(point, fault, loaded=True)
                        max_skew = max(max_skew, skew)
                        sample_flags.update(flags)
                event("configured", point_id=point.point_id, vin_target_V=point.vin_target_V,
                      iout_target_A=point.iout_target_A, source_output="ON", load_input="ON" if bench.load_enabled else "OFF",
                      remote_sense_verified=bench.sense_enabled)
                checkpoint()
            settled = False
            window: deque[tuple[float, float]] = deque()
            span = 0.0
            if not gate_failed and not boundary and not stopping():
                event("point_phase", point_id=point.point_id, phase="settling")
                settling_started = clock.now()
                while clock.now() - settling_started <= plan.recipe.settling.timeout_s:
                    if stopping():
                        break
                    cycle, readings, mode, skew, hit = read_cycle(point, "settling", fault)
                    read_thermal(point, "settling")
                    max_skew = max(max_skew, skew)
                    boundary |= hit
                    sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                    good = all(r["status"] == "ok" for r in readings) and skew <= plan.recipe.acquisition.maximum_interchannel_skew_s
                    if good:
                        voltage = next(r["value"] for r in readings if r["quantity"] == "Vout_V")
                        window.append((clock.now(), voltage))
                    else:
                        window.clear()
                    # A retained sample is fresh for the window plus one poll plus the longest cycle the recipe allows.
                    while window and clock.now() - window[0][0] > (plan.recipe.settling.window_s
                                                                    + plan.recipe.acquisition.target_poll_interval_s
                                                                    + plan.recipe.acquisition.maximum_interchannel_skew_s):
                        window.popleft()
                    span = max((v for _, v in window), default=0) - min((v for _, v in window), default=0)
                    if (clock.now() - settling_started >= plan.recipe.settling.minimum_dwell_s
                            and len(window) >= plan.recipe.settling.minimum_fresh_samples
                            and window[-1][0] - window[0][0] >= plan.recipe.settling.window_s
                            and span <= plan.recipe.settling.maximum_vout_span_V):
                        settled = True
                        break
                    if boundary:
                        break
                    clock.wait(plan.recipe.acquisition.target_poll_interval_s)
            electrical_settled_at = clock.now()
            # Thermal settling (brief section 10) is separate from the electrical
            # criterion above: it starts only after electrical validity, needs the
            # ambient channel, and a timeout never becomes an assumed equilibrium.
            thermal_policy = thermal_policy_for(plan, point.test_id)
            thermal_outcome: dict | None = None
            if settled and not boundary and not stopping() and thermal_policy is not None and thermal is not None:
                event("point_phase", point_id=point.point_id, phase=THERMAL_PHASE)
                thermal_started = clock.now()
                rise_window: deque[tuple[float, float]] = deque()
                verdict = None
                while clock.now() - thermal_started <= thermal_policy.timeout_s:
                    if stopping():
                        break
                    cycle, readings, mode, skew, hit = read_cycle(point, THERMAL_PHASE, fault)
                    max_skew = max(max_skew, skew)
                    boundary |= hit
                    sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                    temperatures = {r["quantity"]: r for r in read_thermal(point, THERMAL_PHASE)}
                    surface = temperatures.get(thermal_policy.surface_quantity)
                    ambient = temperatures.get(thermal_policy.ambient_quantity)
                    electrically_valid = (all(r["status"] == "ok" for r in readings)
                                          and skew <= plan.recipe.acquisition.maximum_interchannel_skew_s)
                    if (electrically_valid and surface and ambient and surface["status"] == "ok" and ambient["status"] == "ok"
                            and surface["value"] is not None and ambient["value"] is not None):
                        rise_window.append((surface["query_end_monotonic_s"], surface["value"] - ambient["value"]))
                    else:
                        rise_window.clear()
                    while rise_window and clock.now() - rise_window[0][0] > thermal_policy.window_s + thermal_policy.poll_interval_s:
                        rise_window.popleft()
                    verdict = evaluate_thermal_window(list(rise_window), thermal_policy, clock.now() - thermal_started)
                    if verdict.met or boundary:
                        break
                    clock.wait(thermal_policy.poll_interval_s)
                thermal_outcome = {"policy": thermal_policy.policy, "surface_quantity": thermal_policy.surface_quantity,
                                   "ambient_quantity": thermal_policy.ambient_quantity,
                                   "status": "met" if verdict is not None and verdict.met else "timeout",
                                   "elapsed_s": clock.now() - thermal_started,
                                   "final_slope_C_per_min": verdict.slope_C_per_min if verdict else None,
                                   "window_span_s": verdict.window_span_s if verdict else 0.0,
                                   "window_samples": verdict.samples if verdict else 0,
                                   "reason": verdict.reason if verdict else "no thermal observation cycle completed"}
                if stopping():
                    thermal_outcome["status"] = "cancelled"
                elif boundary:
                    thermal_outcome["status"] = "setup-limited"
            thermally_qualified = thermal_policy is None or (thermal_outcome is not None and thermal_outcome["status"] == "met")
            accepted = []
            acquisition_start = clock.now()
            if settled and thermally_qualified and not boundary and not stopping():
                event("point_phase", point_id=point.point_id, phase="acquiring")
                acquisition_voltages = []
                while clock.now() - acquisition_start < plan.recipe.acquisition.duration_s:
                    if stopping():
                        break
                    cycle, readings, mode, skew, hit = read_cycle(point, "acquiring", fault)
                    read_thermal(point, "acquiring")
                    max_skew = max(max_skew, skew)
                    boundary |= hit
                    sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                    if all(r["status"] == "ok" for r in readings) and skew <= plan.recipe.acquisition.maximum_interchannel_skew_s:
                        accepted.append(cycle)
                        acquisition_voltages.append(next(r["value"] for r in readings if r["quantity"] == "Vout_V"))
                    clock.wait(plan.recipe.acquisition.target_poll_interval_s)
                if acquisition_voltages and max(acquisition_voltages) - min(acquisition_voltages) > plan.recipe.settling.maximum_vout_span_V:
                    sample_flags.add("unsettled-acquisition")
                    accepted = []
            if boundary and not stopping():
                # The real guard removes source power on its first non-CV reading, which at its >= 1 s cadence is a
                # fresh conversion. The mock's held source readbacks may lag that first reading, so one confirming
                # cycle is taken after the hold-out; it is the retained boundary observation.
                clock.wait(BOUNDARY_CONFIRMATION_S)
                _, readings, mode, skew, _ = read_cycle(point, "boundary", fault)
                max_skew = max(max_skew, skew)
                sample_flags.update(flag for r in readings for flag in r["quality_flags"])
                result["boundary_observation"] = {"values": {r["quantity"]: r["value"] for r in readings},
                                                  "source_mode": mode, "monotonic_s": clock.now(),
                                                  "note": f"confirming cycle {BOUNDARY_CONFIRMATION_S:g} s after the first boundary reading"}
            if stopping():
                state = "interrupted" if terminate.is_set() else "aborted"
                qualification, reason = "not-run", ("interrupted before a complete acquisition window"
                                                    if terminate.is_set() else "cancelled before a complete acquisition window")
                accepted = []
            elif boundary:
                qualification = "setup-limited"
                reason = LIMITED_REASON + f"; {BOUNDARY_REASON}; higher loads at {point.vin_target_V:g} V were not attempted"
                accepted = []
                phase_dead_reason = BOUNDARY_REASON
            elif gate_failed:
                qualification, reason = "inconclusive", STARTUP_FAILURE_REASON
                accepted = []
                phase_dead_reason = STARTUP_FAILURE_REASON
            elif not settled:
                qualification, reason = "inconclusive", "no complete fresh stable settling window before timeout"
            elif not thermally_qualified:
                qualification, reason = "inconclusive", ("thermal settling slope criterion not met before timeout; electrical "
                                                         "acquisition not performed; temperature time series retained")
            elif len(accepted) < plan.recipe.acquisition.minimum_complete_cycles:
                qualification, reason = "inconclusive", "insufficient qualified complete acquisition cycles"
            else:
                qualification, reason = "valid", "fresh complete cycles acquired after electrical settling"
            result.update(qualification=qualification, reason=reason, acquisition_cycle_ids=accepted,
                          settled=settled, settling_elapsed_s=electrical_settled_at-started,
                          acquisition_elapsed_s=clock.now()-acquisition_start, maximum_interchannel_skew_s=max_skew,
                          complete_acquisition_cycles=len(accepted), quality_flags=sorted(sample_flags),
                          settling_vout_span_V=span, observation="enabled_no_load" if point.iout_target_A == 0 else "loaded",
                          load_input_state="OFF" if point.iout_target_A == 0 else "ON")
            if thermal_policy is not None:
                result["thermal_settling"] = thermal_outcome or {
                    "policy": thermal_policy.policy, "status": "not-started",
                    "reason": "electrical settling did not qualify, so thermal observation was not started"}
            store.append("points", {**result, "event": "point_finalized", "monotonic_s": clock.now()})
            checkpoint()
            if phase_dead_reason is not None and phase_open:
                # Remove source power before trying another input, as the real phase stop does.
                end_phase(phase_dead_reason)
                phase_open = False
            if state != "completed":
                break
    except (Exception, KeyboardInterrupt, WorkerTerminated) as exc:
        if isinstance(exc, WorkerTerminated) or terminate.is_set():
            state = "interrupted"
        else:
            state = "aborted" if isinstance(exc, KeyboardInterrupt) else "error"
        message = f"{type(exc).__name__}: {exc}"
        run["errors"].append(message)
        if active is not None and active.get("qualification") in ("not-run", None):
            active.update(qualification="not-run" if state == "interrupted" else "error", reason=message, acquisition_cycle_ids=[])
        elif active is not None and state != "interrupted":
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
        run["synthetic_transitions"] = list(bench.uvlo.transitions)
        run.update(execution_status=state, lifecycle_state=state.upper(), completed_utc=clock.utc(),
                   duration_s=clock.now(), raw_sample_count=persisted_samples)
        try:
            event("lifecycle", state="FINALIZING")
            event("lifecycle", state=state.upper())
            store.finalize(run)
        finally:
            locks.close()
