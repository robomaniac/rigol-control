"""Approved UVLO input-ramp procedure with a phase-scoped guard policy (brief 7.5, RUN-09).

At a fixed light load the input steps down from a start inside the normal
range to the declared floor and back up. Each step waits the declared dwell,
acquires, and records the output state (on / off / indeterminate). Output-off
is an expected, recorded state only inside the declared expected-off phases;
there the normal minimum-Vout and load-established rules are scoped out. The
absolute input-current, voltage and output-current limits are enforced at
every observation of every phase. There is no global ``ignore_safety`` flag.

Mock execution only: ``run_uvlo_mock`` drives the synthetic plant in-process
with a virtual clock and never imports a real instrument driver. The
``TestProcedure`` surface is kept so a future, separately reviewed real
context can drive ``execute``; that context does not exist here.
"""
from __future__ import annotations

import math
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any, Callable

from filelock import FileLock

from .adapters import MODEL_PARAMETERS, MODEL_VERSION
from .domain import UVLO_TEST_TYPE, Plan, RawSample, TestDefinition, uvlo_ramp_phases
from .mock_uvlo import UVLO_MODEL_VERSION, SyntheticUvlo, UvloMockBench
from .planning import uvlo_approval_gaps, verify_plan_hash
from .runner import QUANTITIES, Clock, _lock_paths, _provenance
from .storage import PersistenceError, RunStore, atomic_json

LOAD_CURRENT_TOLERANCE_A = .02
ReadingOverride = Callable[[str, float, dict[str, Any], str], float]


class UvloStop(Exception):
    """A guarded stop. ``classification`` names the rule family; ``qualification`` is the active step's outcome."""
    classification = "procedure"
    qualification = "inconclusive"

    def __init__(self, reason: str, *, values: dict[str, float] | None = None):
        super().__init__(reason)
        self.values = dict(values or {})


class ProtectiveLimitFault(UvloStop):
    """An absolute protective limit was exceeded; never scoped by phase."""
    classification = "absolute-protective-limit"


class RegulationRuleStop(UvloStop):
    """A normal-operation rule tripped where output-off is not an expected state."""
    classification = "normal-regulation-rule"


class SourceBoundaryStop(UvloStop):
    """The source left CV regulation; the requested input condition was not achieved."""
    classification = "source-boundary"
    qualification = "setup-limited"


class UvloInputRampProcedure:
    """Plan-driven UVLO ramp. Construction refuses anything the planner did not approve outright."""

    adapter = UvloMockBench

    def __init__(self, plan: Plan):
        if not verify_plan_hash(plan):
            raise ValueError("Plan hash mismatch; regenerate the plan after changing any settings")
        tests = plan.recipe.tests
        if not tests or any(test.type != UVLO_TEST_TYPE or test.uvlo is None for test in tests):
            raise ValueError("UvloInputRampProcedure executes uvlo_input_ramp tests only")
        gaps = uvlo_approval_gaps(plan.bench, plan.recipe)
        if gaps:
            raise ValueError("UVLO input ramp refused: " + "; ".join(gaps))
        blocked = [point for point in plan.points if point.status != "executable"]
        if blocked:
            raise ValueError(f"UVLO input ramp refused: {len(blocked)} declared step(s) are not executable and a ramp is "
                             f"never run with steps skipped or clipped. First: {blocked[0].point_id} — {blocked[0].reason}")
        self.snapshot = plan.model_copy(deep=True)
        self.stage = "idle"
        self.policy = None
        self.step: dict[str, Any] | None = None
        self.acquiring = False  # the load-established rule judges acquisition cycles, not the settling transient
        controls, ratings = plan.bench.protective_controls, plan.dut.ratings
        self.limits = {
            "input_current_A": controls.source_current_limit_A,
            "input_voltage_V": controls.dut_input_overvoltage_V if controls.dut_input_overvoltage_V is not None
                               else ratings.input_voltage_max_V,
            "input_voltage_ceiling_source": ("bench protective_controls.dut_input_overvoltage_V"
                                             if controls.dut_input_overvoltage_V is not None
                                             else "DUT input_voltage_max_V (no bench input OVP declared)"),
            "output_voltage_V": controls.dut_output_overvoltage_V,
            "output_current_A": controls.output_overcurrent_A,
            "load_current_tolerance_A": LOAD_CURRENT_TOLERANCE_A,
        }

    # -- contract surface -------------------------------------------------------------------------
    def plan(self) -> Plan:
        return self.snapshot.model_copy(deep=True)

    def metadata(self) -> dict[str, Any]:
        recipe = self.snapshot.recipe
        tests = {test.id: {"steps_V": list(test.input_voltage_targets_V),
                           "phases": uvlo_ramp_phases(test.input_voltage_targets_V),
                           "load_A": test.output_current_targets_A[0], "policy": test.uvlo.model_dump()}
                 for test in recipe.tests}
        return {"scenario": "Approved UVLO input ramp at fixed light load (synthetic plant)", "executed_point_ids": [],
            "authorization": f"recipe authorization.uvlo_approved under protective policy "
                             f"{recipe.authorization.protective_policy_id}; mock execution never energizes equipment",
            "method": {"uvlo_input_ramp": {
                "policy_id": recipe.authorization.protective_policy_id, "tests": tests,
                "step_dwell_s": recipe.settling.minimum_dwell_s,
                "guard": {"absolute_limits_every_step": self.limits,
                          "scoped_to_normal_phase": [
                              "output voltage at or above output_on_minimum_V (every settling and acquisition cycle)",
                              f"requested load current established within {LOAD_CURRENT_TOLERANCE_A:g} A (acquisition cycles)"],
                          "expected_off_phase": "descending steps below expected_off_below_V and ascending steps below "
                                                "expected_on_above_V: output-off is recorded, not faulted",
                          "always": ["finite readings", "absolute limits", "source stays in CV",
                                     "interchannel skew within the recipe bound"]},
                "synthetic_model": None}},
            "metrology_limitations": [
                "Brackets are limited by the declared step size; no exact threshold or hysteresis value is established.",
                "Source-terminal input voltage includes lead drop; the DUT-pin voltage at each transition is not measured.",
                "This procedure has not been exercised on hardware. Real execution requires a reviewed protective "
                "policy, saved DUT/bench approvals and a real execution context that does not exist yet."]}

    def record_attempt(self, run: dict[str, Any], point: dict[str, Any]) -> None:
        if point["point_id"] not in run["executed_point_ids"]:
            point["execution_index"] = len(run["executed_point_ids"]) + 1
            run["executed_point_ids"].append(point["point_id"])

    def begin_test(self, test: TestDefinition) -> None:
        if test.type != UVLO_TEST_TYPE or test.uvlo is None:
            raise ValueError("begin_test requires a uvlo_input_ramp test")
        self.policy, self.step = test.uvlo, None

    def begin_step(self, vin_target_V: float, ramp_phase: str) -> None:
        if self.policy is None:
            raise RuntimeError("begin_step requires an active test policy")
        self.step = {"vin_target_V": vin_target_V, "ramp_phase": ramp_phase,
                     "output_off_expected": self.policy.off_expected(vin_target_V, ramp_phase)}
        self.acquiring = False

    def guard(self, values: dict[str, float], requested: float, *, loaded: bool = True, startup: bool = False,
              mode_before: str = "CV", mode_after: str = "CV") -> None:
        """Absolute limits first and always; normal rules only where output-off is not expected."""
        limits = self.limits
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values.values()):
            raise ProtectiveLimitFault("Nonfinite or missing measurement; no recovery is permitted", values=values)
        if not -.005 <= values["Iin_A"] <= limits["input_current_A"]:
            raise ProtectiveLimitFault(f"Absolute input-current limit {limits['input_current_A']:g} A exceeded", values=values)
        if not -.05 <= values["Vin_V"] <= limits["input_voltage_V"]:
            raise ProtectiveLimitFault(f"Absolute input-voltage limit {limits['input_voltage_V']:g} V exceeded", values=values)
        if not -.05 <= values["Vout_V"] <= limits["output_voltage_V"]:
            raise ProtectiveLimitFault(f"Absolute output-voltage limit {limits['output_voltage_V']:g} V exceeded", values=values)
        if not -.02 <= values["Iout_A"] <= limits["output_current_A"]:
            raise ProtectiveLimitFault(f"Absolute output-current limit {limits['output_current_A']:g} A exceeded", values=values)
        if mode_before != "CV" or mode_after != "CV":
            raise SourceBoundaryStop("Source left CV regulation; the requested input condition was not achieved", values=values)
        if startup:
            return  # bounded startup interval: no steady-state minimum-output check yet (brief 7.3)
        if self.policy is None or self.step is None:
            raise RuntimeError("guard requires an active test policy and step")
        if self.step["output_off_expected"]:
            return  # expected-off phase: normal regulation rules are scoped out; absolute limits already applied
        if values["Vout_V"] < self.policy.output_on_minimum_V:
            raise RegulationRuleStop(f"Output {values['Vout_V']:.3f} V is below the {self.policy.output_on_minimum_V:g} V "
                                     "minimum outside the declared expected-off phase; cause unclassified", values=values)
        if loaded and self.acquiring and abs(values["Iout_A"] - requested) > limits["load_current_tolerance_A"]:
            raise RegulationRuleStop(f"Requested load {requested:g} A was not established outside the declared "
                                     "expected-off phase", values=values)

    # -- execution against a context ---------------------------------------------------------------
    def execute(self, ctx: Any) -> None:
        run, clock, recipe = ctx.run, ctx.clock, self.snapshot.recipe
        poll = recipe.acquisition.target_poll_interval_s

        def checkpoint() -> None:
            atomic_json(ctx.directory / "run.json", run)

        for test in recipe.tests:
            self.begin_test(test)
            policy, load = test.uvlo, test.output_current_targets_A[0]
            points = [p for p in run["points"] if p["test_id"] == test.id]
            phases = uvlo_ramp_phases([p["vin_target_V"] for p in points])
            detail = run["method"]["uvlo_input_ramp"]["tests"][test.id]
            detail.update(startup=None, steps=[], completed=False)
            first = points[0]
            first["ramp_phase"] = phases[0]
            self.record_attempt(run, first)
            ctx.set_active(first)
            self.begin_step(first["vin_target_V"], phases[0])
            self.stage = "unloaded-startup"
            checkpoint()
            ctx.energize(first["vin_target_V"], load)
            ctx.event("energized", test_id=test.id, point_id=first["point_id"], vin_target_V=first["vin_target_V"],
                      requested_load_A=load, load_input="OFF", procedure_stage=self.stage)
            started, startup_ids, values = clock.monotonic(), [], None
            while clock.monotonic() - started < policy.startup_interval_s:
                clock.sleep(poll)
                cycle_id, values, _ = ctx.cycle(first, "starting", loaded=False, startup=True)
                startup_ids.append(cycle_id)
            detail["startup"] = {"cycle_ids": startup_ids, "elapsed_s": clock.monotonic() - started,
                                 "status": "output-on-before-load"}
            if values is None or values["Vout_V"] < policy.output_on_minimum_V:
                detail["startup"]["status"] = "output-not-on"
                raise RegulationRuleStop(f"Output did not reach {policy.output_on_minimum_V:g} V within the "
                                         f"{policy.startup_interval_s:g} s startup interval; load was not enabled",
                                         values=values)
            ctx.enable_load()
            ctx.event("load_enabled", test_id=test.id, requested_load_A=load)
            for point, phase in zip(points, phases):
                point["ramp_phase"] = phase
                self.record_attempt(run, point)
                ctx.set_active(point)
                self.begin_step(point["vin_target_V"], phase)
                self.stage = "ramp-down" if phase == "down" else "ramp-up"
                off_expected = self.step["output_off_expected"]
                if point["vin_target_V"] != ctx.current_input():
                    ctx.step_input(point["vin_target_V"])
                    ctx.event("input_stepped", point_id=point["point_id"], to_V=point["vin_target_V"], ramp_phase=phase,
                              output_off_expected=off_expected, procedure_stage=self.stage)
                checkpoint()
                dwell_started, settling_ids = clock.monotonic(), []
                while clock.monotonic() - dwell_started < recipe.settling.minimum_dwell_s:
                    clock.sleep(poll)
                    cycle_id, _, _ = ctx.cycle(point, "settling")
                    settling_ids.append(cycle_id)
                acquisition_started, accepted, readings, skew_max = clock.monotonic(), [], [], 0.
                self.acquiring = True
                while (clock.monotonic() - acquisition_started < recipe.acquisition.duration_s
                       or len(accepted) < recipe.acquisition.minimum_complete_cycles):
                    cycle_id, values, skew = ctx.cycle(point, "acquiring")
                    accepted.append(cycle_id)
                    readings.append(values)
                    skew_max = max(skew_max, skew)
                    clock.sleep(poll)
                self.acquiring = False
                ended = clock.monotonic()
                means = {key: mean(row[key] for row in readings) for key in readings[0]}
                span = max(row["Vout_V"] for row in readings) - min(row["Vout_V"] for row in readings)
                state = policy.classify_output(means["Vout_V"])
                if span > recipe.settling.maximum_vout_span_V:
                    if not off_expected:
                        raise RegulationRuleStop(f"Output voltage span {span:.3f} V exceeded the settling bound during "
                                                 "acquisition outside the declared expected-off phase", values=means)
                    qualification, state = "inconclusive", None
                    reason = (f"output unsettled (span {span:.3f} V) during an expected-off-permitted step; "
                              "state not classified")
                    accepted = []
                else:
                    qualification = "valid"
                    reason = (f"output {state} at {point['vin_target_V']:g} V ({phase} ramp): "
                              + ("expected-off phase, recorded as a state, not a fault"
                                 if off_expected else "normal-range phase; minimum-output rule applied")
                              + "; uncertainty unquantified")
                point.update(qualification=qualification, reason=reason, output_state=state,
                             output_off_expected=off_expected, minimum_vout_rule_applied=not off_expected,
                             load_current_established=abs(means["Iout_A"] - load) <= LOAD_CURRENT_TOLERANCE_A,
                             acquisition_cycle_ids=accepted, settling_cycle_ids=settling_ids, settled=qualification == "valid",
                             settling_elapsed_s=acquisition_started - dwell_started,
                             acquisition_elapsed_s=ended - acquisition_started,
                             acquisition_start_monotonic_s=acquisition_started - ctx.began,
                             acquisition_end_monotonic_s=ended - ctx.began, maximum_interchannel_skew_s=skew_max,
                             procedure_stage=self.stage, accepted_means=means)
                detail["steps"].append({"point_id": point["point_id"], "vin_target_V": point["vin_target_V"],
                                        "ramp_phase": phase, "output_state": state, "output_off_expected": off_expected,
                                        "qualification": qualification})
                ctx.store.append("points", {**point, "event": "point_finalized", "monotonic_s": ended - ctx.began})
                checkpoint()
                ctx.set_active(None)
            self.stage = "de-energize"
            ctx.de_energize()
            ctx.event("de_energized", test_id=test.id, source_output="OFF", load_input="OFF")
            detail["completed"] = True
            checkpoint()
        self.stage = "completed"


def run_uvlo_mock(plan: Plan, out: Path, *, seed: int = 1, synthetic: SyntheticUvlo | None = None,
                  reading_override: ReadingOverride | None = None, operator_observations: list[str] | None = None,
                  attachment_descriptors: list[dict] | None = None) -> Path:
    """Execute the approved UVLO ramp against the synthetic plant; return the finalized run directory.

    In-process, virtual clock, OS file locks on the mock resources, fsync per
    record. Refuses real profiles, hash mismatches, non-UVLO tests, missing
    approvals and any non-executable step before anything is written.
    ``reading_override(quantity, value, point, phase)`` lets tests inject a
    reading; injected samples are flagged in their acquisition settings.
    This function never creates or imports real instruments.
    """
    if plan.bench.mode != "mock":  # the bench decides; a legacy recipe mode is metadata
        raise ValueError("run_uvlo_mock accepts mock profiles only; real UVLO execution is not implemented and requires review")
    procedure = UvloInputRampProcedure(plan)
    if plan.bench.source.max_current_A is None:
        raise ValueError("mock source current capability is required")
    if any(quantity not in plan.bench.measurements for quantity in QUANTITIES):
        raise ValueError("mock acquisition requires four declared electrical measurement bindings")
    synthetic = synthetic if synthetic is not None else SyntheticUvlo()
    bench = UvloMockBench(plan.dut.ratings.output_voltage_nominal_V,
                          plan.bench.protective_controls.source_current_limit_A or plan.bench.source.max_current_A,
                          plan.bench.load.min_voltage_V, seed, uvlo=synthetic)
    created = datetime.now(timezone.utc)
    run_id = created.strftime("%Y%m%dT%H%M%S.%fZ") + "_uvlo_" + uuid.uuid4().hex[:8]
    directory = Path(out) / run_id
    snapshot = plan.model_dump(mode="json")
    run: dict[str, Any] = {
        "schema_version": "1.0", "run_id": run_id, "data_source": "simulated", "execution_status": "running",
        "lifecycle_state": "VALIDATING", "created_utc": created.isoformat(), "plan_hash": plan.plan_hash,
        "scenario": "uvlo-input-ramp",
        "points": [{**p.model_dump(), "planning_status": p.status, "qualification": "not-run", "reason": "not reached",
                    "acquisition_cycle_ids": [], "requirement_result": "not-evaluated"} for p in plan.points],
        "shutdown": {"source": {"state": "UNKNOWN"}, "load": {"state": "UNKNOWN"}},
        "model": {"version": f"{MODEL_VERSION}+{UVLO_MODEL_VERSION}", "seed": seed,
                  "parameters": {**MODEL_PARAMETERS, "uvlo": synthetic.parameters()}},
        "clock": {"mode": "virtual",
                  "note": "simulated acquisition; virtual timestamps are model time, not hardware observations"},
        "software": _provenance(), "durability_policy": "flush and fsync every JSONL record",
        "measurement_boundary": plan.bench.measurement_boundary,
        "operator_observations": list(operator_observations or []),
        "attachment_descriptors": list(attachment_descriptors or []), "real_hardware_opened": False, "errors": []}
    run.update(procedure.metadata())
    run["method"]["uvlo_input_ramp"]["synthetic_model"] = synthetic.parameters()
    store = RunStore(directory)
    store.initialize({"dut": snapshot["dut"], "bench": snapshot["bench"], "recipe": snapshot["recipe"],
                      "authorization": run["authorization"]}, snapshot, run)
    clock = Clock(run["created_utc"], real_time=False)
    serial = cycle_serial = persisted = 0
    active: dict[str, Any] | None = None
    owned, state = False, "completed"

    def event(kind: str, **detail: Any) -> None:
        store.append("events", {"event": kind, "run_id": run_id, "timestamp_utc": clock.utc(),
                                "monotonic_s": clock.now(), **detail})

    def transition(name: str) -> None:
        run["lifecycle_state"] = name
        event("lifecycle", state=name)

    def set_active(point: dict[str, Any] | None) -> None:
        nonlocal active
        active = point

    def cycle(point: dict[str, Any], phase: str, *, loaded: bool = True, startup: bool = False):
        nonlocal serial, cycle_serial, persisted
        cycle_serial += 1
        cycle_id = f"c{cycle_serial:07d}"
        rows, modes = [], []
        begin = clock.now()
        for quantity in QUANTITIES:
            serial += 1
            started = clock.now()
            clock.wait(.002)
            value, physical = bench.read(quantity, clock.now())
            injected = False
            if reading_override is not None:
                replaced = reading_override(quantity, value, point, phase)
                injected, value = replaced != value, replaced
            modes.append(physical.source_mode)
            flags = []
            if physical.source_mode == "CC":
                flags.append("source-current-limited")
            if not physical.load_compliance:
                flags.append("load-out-of-compliance")
            binding = plan.bench.measurements[quantity]
            sample = RawSample(
                sample_id=f"s{serial:08d}", run_id=run_id, test_id=point["test_id"], point_id=point["point_id"],
                channel_id=binding.instrument_id + ":" + quantity, instrument_id=binding.instrument_id,
                quantity=quantity, value=value, unit=binding.unit, location=binding.location,
                query_start_utc=clock.utc(started), query_end_utc=clock.utc(), query_start_monotonic_s=started,
                query_end_monotonic_s=clock.now(), device_timestamp=clock.utc(),
                measurement_range=binding.measurement_range, resolution=binding.resolution,
                acquisition_settings={"source_mode": physical.source_mode, "load_compliance": physical.load_compliance,
                                      "sense_enabled": bench.sense_enabled, "load_enabled": bench.load_enabled,
                                      "requested_load_A": point["iout_target_A"], "procedure_stage": procedure.stage,
                                      "ramp_phase": point.get("ramp_phase"),
                                      "output_off_expected": (procedure.step or {}).get("output_off_expected"),
                                      "mock_model": run["model"]["version"],
                                      **({"injected_override": True} if injected else {})},
                raw_response=repr(value), status="ok" if not flags else "invalid", quality_flags=flags,
                acquisition_cycle_id=cycle_id, phase=phase).model_dump(mode="json")
            store.append("samples", sample)
            persisted += 1
            rows.append(sample)
        values = {row["quantity"]: row["value"] for row in rows}
        skew = clock.now() - begin
        if skew > plan.recipe.acquisition.maximum_interchannel_skew_s:
            raise UvloStop(f"Interchannel query span {skew:.3f} s exceeds the recipe bound", values=values)
        procedure.guard(values, point["iout_target_A"], loaded=loaded, startup=startup,
                        mode_before=modes[0], mode_after=modes[-1])
        return cycle_id, values, skew

    def energize(vin: float, iout: float) -> None:
        bench.load_off()
        bench.source_off()
        bench.configure(vin, iout, clock.now())
        bench.source_on()
        run["shutdown"] = {"source": {"state": "ON"}, "load": {"state": "OFF"}}

    def enable_load() -> None:
        bench.load_on()
        run["shutdown"]["load"] = {"state": "ON"}

    def step_input(vin: float) -> None:
        bench.set_live_voltage(vin, clock.now())

    def de_energize() -> None:
        bench.load_off()
        bench.source_off()
        run["shutdown"] = {role: {"state": "OFF", "verified": True} for role in ("source", "load")}

    locks = ExitStack()
    try:
        transition("PLAN_READY")
        transition("AWAITING_ARM")
        event("mock_authorized", detail="explicit run_uvlo_mock call under the recipe's UVLO approval block; "
                                        "never arms real equipment")
        for path in _lock_paths(plan):
            locks.enter_context(FileLock(str(path), timeout=.1))
        owned = True
        transition("CONNECTING")
        event("identified", identities=bench.identify())
        transition("PREFLIGHT")
        event("preflight", source_output="OFF", load_input="OFF", mode="mock",
              absolute_limits=procedure.limits, synthetic_uvlo=synthetic.parameters())
        run["shutdown"] = {role: {"state": "OFF", "verified": True} for role in ("source", "load")}
        transition("RUNNING")
        context = SimpleNamespace(plan=plan, run=run, directory=directory, began=0., bench=bench,
                                  clock=SimpleNamespace(monotonic=clock.now, sleep=clock.wait),
                                  cycle=cycle, event=event, store=store, set_active=set_active,
                                  energize=energize, enable_load=enable_load, step_input=step_input,
                                  de_energize=de_energize, current_input=lambda: bench.source_voltage)
        procedure.execute(context)
    except UvloStop as stop:
        state = "aborted"
        message = f"{type(stop).__name__}: {stop}"
        run["errors"].append(message)
        run["stop"] = {"classification": stop.classification, "point_id": active["point_id"] if active else None,
                       "procedure_stage": procedure.stage, "ramp_phase": (procedure.step or {}).get("ramp_phase"),
                       "output_off_expected": (procedure.step or {}).get("output_off_expected"), "values": stop.values,
                       "reason": str(stop)}
        if active is not None:
            active.update(qualification=stop.qualification, reason=message, acquisition_cycle_ids=[])
        try:
            event("fault", classification=stop.classification, reason=message)
        except PersistenceError:
            pass
    except Exception as exc:
        state = "error"
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
        if owned:
            # Each protective action is attempted independently and verified by readback.
            for role, action, readback in (("load", bench.load_off, lambda: bench.load_enabled),
                                            ("source", bench.source_off, lambda: bench.source_enabled)):
                record: dict[str, Any] = {"command": "OFF", "acknowledged": False, "state": "UNKNOWN", "verified": False}
                try:
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
        run["method"]["uvlo_input_ramp"]["synthetic_transitions"] = list(synthetic.transitions)
        run.update(execution_status=state, lifecycle_state=state.upper(), completed_utc=clock.utc(),
                   duration_s=clock.now(), raw_sample_count=persisted)
        try:
            event("lifecycle", state="FINALIZING")
            event("lifecycle", state=state.upper())
            store.finalize(run)
        finally:
            locks.close()
    return directory
