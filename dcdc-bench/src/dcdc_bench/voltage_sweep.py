"""Explicitly armed efficiency comparison at 12 V, 24 V and near 36 V.

The DP821A CH1 current setting remains 1 A. Each voltage has a bounded,
conditional output-load grid. Both outputs are verified OFF between voltages.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean

from .domain import Plan, RawSample, TestDefinition
from .extended import ExtendedAbort, _run_fixed, extended_plan
from .planning import _hash_payload, build_plan, verify_plan_hash
from .source_limit import BenchBoundary, SourceLimitRigol
from .storage import atomic_json, verify_integrity

POLICY_ID = "supervised-12-24-near36V-source1A-v1"
SOURCE_CURRENT_LIMIT, SOURCE_OCP = 1.000, 1.05
ABSOLUTE_INPUT_CURRENT, TARGET_INPUT_CURRENT, HEADROOM_STOP_CURRENT = 1.02, .98, .995
OUTPUT_CURRENT_GUARD, ACQUISITION_SECONDS = 2.55, 8.
LAST_PHASE_START_S, LAST_POINT_START_S = 590., 620.
COMMON_LOADS = tuple(n / 10 for n in range(1, 8))
PHASES = (
    {"nominal_input_V": 12., "programmed_input_V": 12., "source_OVP_V": 13.,
     "maximum_input_readback_V": 12.5, "loads_A": COMMON_LOADS + (.8,)},
    {"nominal_input_V": 24., "programmed_input_V": 24., "source_OVP_V": 26.,
     "maximum_input_readback_V": 24.5, "loads_A": COMMON_LOADS + (.9, 1.1, 1.3, 1.5, 1.65, 1.725)},
    {"nominal_input_V": 36., "programmed_input_V": 35.8, "source_OVP_V": 36.,
     "maximum_input_readback_V": 35.93, "loads_A": COMMON_LOADS + (.9, 1.2, 1.5, 1.8, 2.1, 2.3, 2.5)},
)


class VoltageSweepRigol(SourceLimitRigol):
    voltage, source_ovp = 12., 13.
    output_current_limit = OUTPUT_CURRENT_GUARD


class VoltageContinuationRigol(VoltageSweepRigol):
    voltage, source_ovp = 24., 26.


def voltage_sweep_plan():
    base = extended_plan()
    dut, bench, recipe = (item.model_copy(deep=True) for item in (base.dut, base.bench, base.recipe))
    bench.bench_id, recipe.recipe_id = "rigol-supervised-voltage-efficiency", "12t12-12-24-near36v-efficiency"
    dut.execution_approval.protective_policy_id = POLICY_ID
    bench.protective_controls.policy_id = recipe.authorization.protective_policy_id = POLICY_ID
    bench.source.max_current_A = bench.protective_controls.source_current_limit_A = SOURCE_CURRENT_LIMIT
    bench.source.max_voltage_V = bench.protective_controls.dut_input_overvoltage_V = 36.
    bench.source.max_power_W = 36.
    bench.load.max_current_A = bench.protective_controls.output_overcurrent_A = OUTPUT_CURRENT_GUARD
    bench.load.max_power_W = 34.
    bench.notes = [
        "User explicitly requested efficiency curves at 12 V, 24 V and 36 V on the confirmed CH1 converter wiring.",
        "The nominal 36 V condition is programmed to 35.8 V; the measured input voltage is retained without relabelling it as exactly 36 V.",
        "The upper-input readback stop is 35.93 V. Datasheet programming/readback accuracy motivated this margin; calibration and fast overshoot remain unverified.",
        "Source OVP is 13/26/36 V by phase. Its trip accuracy is not a precise 36 V transient clamp.",
        "Source current is programmed to 1.000 A; source OCP 1.05 A and absolute current readback stop 1.02 A do not authorize a higher current setting.",
        "All 35 requests are conditional. Stop a voltage phase at source CC, 0.995 A measured input, lost voltage headroom or low output voltage.",
        "A qualified window with mean input current at least 0.98 A ends that voltage phase; no additional hold or recovery load is attempted.",
        "Both outputs and the previous source timer are verified OFF before any input-voltage reconfiguration.",
        "Each phase has a verified independent 720 s source shutoff; one global 660 s software deadline covers the complete run.",
        "The planner's 100% efficiency is an ideal-power feasibility ceiling, not expected or measured efficiency.",
        "Source-to-load-terminal measurements include wiring; temperature, ripple, transient behavior and the 4 A rating are not evaluated.",
    ]
    recipe.tests = [TestDefinition(id=f"efficiency-{phase['nominal_input_V']:g}v",
        input_voltage_targets_V=[phase["nominal_input_V"]], output_current_targets_A=list(phase["loads_A"]))
        for phase in PHASES]
    recipe.planning.efficiency_estimate_fraction = recipe.planning.source_current_budget_fraction = 1.
    recipe.acquisition.duration_s = ACQUISITION_SECONDS
    plan = build_plan(dut, bench, recipe)
    for point in plan.points:
        if point.status != "approval_blocked":
            raise ExtendedAbort(f"Voltage sweep request violates its absolute planning envelope: {point.reason}")
        point.status = "executable"
        point.reason = "Conditional fixed-policy voltage comparison; execution requires measured source headroom"
    plan.warnings.append("Nominal 36 V is intentionally programmed to 35.8 V with actual input readbacks reported; exact 36 V and transient overvoltage qualification are outside this test.")
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan


class VoltageSweepProcedure:
    adapter = VoltageSweepRigol
    plan = staticmethod(voltage_sweep_plan)

    def __init__(self):
        self.phases = PHASES
        self.phase = PHASES[0]
        self.stage = "efficiency-12v"
        self.startup_source_cycles = 0

    @staticmethod
    def record_attempt(run, point):
        if point["point_id"] not in run["executed_point_ids"]:
            point["execution_index"] = len(run["executed_point_ids"]) + 1
            run["executed_point_ids"].append(point["point_id"])
        phase = next(p for p in run["method"]["voltage_efficiency_sweep"]["phases"]
                     if p["nominal_input_V"] == point["vin_target_V"])
        if point["point_id"] not in phase["executed_point_ids"]:
            phase["executed_point_ids"].append(point["point_id"])
        if phase["status"] == "not-run":
            phase["status"] = "starting"

    @staticmethod
    def metadata():
        return {"scenario": "Efficiency comparison at 12 V, 24 V and near 36 V", "executed_point_ids": [],
            "authorization": "User explicitly requested 12/24/36 V efficiency testing with the connected 12T12-4A and the previously authorized 1 A source current setting",
            "metrology_limitations": [
                "Source/load-terminal boundary includes input and output wiring losses.",
                "ADC freshness, calibration, and readback uncertainty are unquantified; no temperature sensor is present.",
                "Nominal 36 V is programmed to 35.8 V with an upper readback stop of 35.93 V; source OVP does not establish a precise transient clamp.",
                "The 9 V endpoint, no-load power, ripple, transients and full rated power are not evaluated."],
            "method": {"source_current_limit_A": SOURCE_CURRENT_LIMIT, "source_OVP_V": [13., 26., 36.],
                "source_OCP_A": SOURCE_OCP, "input_current_absolute_guard_A": ABSOLUTE_INPUT_CURRENT,
                "target_input_current_A": TARGET_INPUT_CURRENT, "headroom_stop_input_current_A": HEADROOM_STOP_CURRENT,
                "output_load_ceiling_A": 2.5, "output_load_guard_A": OUTPUT_CURRENT_GUARD,
                "candidate_window_s": ACQUISITION_SECONDS, "settling_cycles": 5,
                "hardware_deadline_s": 720, "hardware_deadline_scope": "Each independently started voltage phase",
                "software_deadline_s": 660, "last_phase_start_s": LAST_PHASE_START_S,
                "last_point_start_s": LAST_POINT_START_S, "conditional_coverage": True,
                "separate_hold": False, "maximum_recovery_attempts": 0,
                "planning_efficiency_note": "100% is only the ideal-power envelope; measured source headroom controls coverage",
                "voltage_efficiency_sweep": {
                    "nominal_input_voltages_V": [p["nominal_input_V"] for p in PHASES],
                    "programmed_input_voltages_V": [p["programmed_input_V"] for p in PHASES],
                    "input_current_limit_A": SOURCE_CURRENT_LIMIT, "target_input_current_A": TARGET_INPUT_CURRENT,
                    "headroom_stop_input_current_A": HEADROOM_STOP_CURRENT,
                    "common_output_loads_A": list(COMMON_LOADS), "reference_load_A": .5,
                    "phases": [{**p, "loads_A": list(p["loads_A"]), "status": "not-run", "stop_reason": None,
                        "highest_qualified_point": None, "executed_point_ids": [], "qualified_point_ids": []}
                        for p in PHASES]}}}

    def guard(self, values, requested, *, loaded=True, startup=False, mode_before="CV", mode_after="CV"):
        if any(not math.isfinite(value) for value in values.values()):
            raise ExtendedAbort("Nonfinite measurement; voltage sweep stopped")
        if not -.005 <= values["Iin_A"] <= ABSOLUTE_INPUT_CURRENT:
            raise ExtendedAbort(f"Absolute input-current guard failed: {values}")
        if not -.05 <= values["Vin_V"] <= self.phase["maximum_input_readback_V"]:
            raise ExtendedAbort(f"Absolute input-voltage guard failed for nominal {self.phase['nominal_input_V']:g} V: {values}")
        if not -.05 <= values["Vout_V"] <= 13.2 or not -.02 <= values["Iout_A"] <= OUTPUT_CURRENT_GUARD:
            raise ExtendedAbort(f"Absolute output guard failed: {values}")
        modes = [mode_before, mode_after]
        if "CC" in modes or values["Iin_A"] >= HEADROOM_STOP_CURRENT or values["Vin_V"] < self.phase["programmed_input_V"] - .5:
            raise BenchBoundary("Supply current ceiling or input-voltage headroom reached; excluded from efficiency results", values, modes)
        if not startup and values["Vout_V"] < 10.8:
            raise BenchBoundary("Output fell below the conservative stop threshold; cause unclassified", values, modes,
                                qualification="inconclusive")
        if startup and not loaded:
            self.startup_source_cycles += 1
            if self.startup_source_cycles >= 5 and values["Vout_V"] < 10.8:
                raise ExtendedAbort("Converter output did not reach 10.8 V during source-only startup; load was not enabled")
        if loaded and not startup and abs(values["Iout_A"] - requested) > .02:
            raise ExtendedAbort(f"Requested output current was not established: requested {requested:g} A; {values}")

    @staticmethod
    def stop_phase(ctx):
        """Keep the timer fallback until source OFF is verified; fail closed."""
        pilot = ctx.pilot
        pilot.supply.output_off(1)
        if pilot.supply.get_output_enabled(1):
            raise ExtendedAbort("Source OFF was not verified before voltage transition; timer left active")
        pilot.cancel_deadline()
        pilot.supply.output_off(1)
        if pilot.supply.get_output_enabled(1):
            raise ExtendedAbort("Source OFF was not verified after cancelling its timer")
        ctx.load.input_off()
        if ctx.load.get_input_enabled():
            raise ExtendedAbort("Load OFF was not verified before voltage transition")
        # Output OFF readback is a state confirmation, not a promise that the
        # source's output capacitor has already discharged. Poll only while
        # both outputs remain OFF; do not change voltage or rearm while high.
        off_started = ctx.clock.monotonic()
        while True:
            off_voltage = pilot.supply.measure_voltage(1)
            if not math.isfinite(off_voltage):
                raise ExtendedAbort("Nonfinite residual source voltage before voltage transition")
            if abs(off_voltage) <= .5:
                break
            if ctx.clock.monotonic() - off_started >= 2.:
                raise ExtendedAbort(f"Residual source voltage {off_voltage!r} V exceeds the OFF transition threshold")
            ctx.clock.sleep(.2)
        ctx.event("voltage_phase_outputs_off", source_verified_off=True, load_verified_off=True,
                  source_deadline_verified_off=True, residual_source_V=off_voltage,
                  source_off_decay_wait_s=ctx.clock.monotonic() - off_started)

    def execute(self, ctx):
        run, clock = ctx.run, ctx.clock
        sweep = run["method"]["voltage_efficiency_sweep"]

        def save(point):
            ctx.store.append("points", {**point, "event": "point_finalized", "monotonic_s": clock.monotonic() - ctx.began})
            atomic_json(ctx.directory / "run.json", run)

        def select(point):
            self.record_attempt(run, point)
            ctx.set_active(point)
            atomic_json(ctx.directory / "run.json", run)

        def qualify(point):
            settled_from, voltages = clock.monotonic(), []
            for _ in range(5):
                clock.sleep(1)
                _, values, _ = ctx.cycle(point, "settling")
                voltages.append(values["Vout_V"])
            if max(voltages) - min(voltages) > .05:
                raise ExtendedAbort("Output did not settle within a 50 mV span")
            acquired_from, accepted, readings, max_skew = clock.monotonic(), [], [], 0.
            while clock.monotonic() - acquired_from < ACQUISITION_SECONDS or len(accepted) < 5:
                cycle_id, values, skew = ctx.cycle(point, "acquiring")
                accepted.append(cycle_id)
                readings.append(values)
                max_skew = max(max_skew, skew)
                clock.sleep(1)
            ended = clock.monotonic()
            if max(row["Vout_V"] for row in readings) - min(row["Vout_V"] for row in readings) > .05:
                raise ExtendedAbort("Output voltage span exceeded 50 mV during acquisition")
            means = {key: mean(row[key] for row in readings) for key in readings[0]}
            point.update(qualification="valid", reason="Stable CV input and guarded DC readbacks; uncertainty unquantified",
                acquisition_cycle_ids=accepted, settled=True, settling_elapsed_s=acquired_from - settled_from,
                acquisition_elapsed_s=ended - acquired_from, acquisition_start_monotonic_s=acquired_from - ctx.began,
                acquisition_end_monotonic_s=ended - ctx.began, maximum_interchannel_skew_s=max_skew,
                programmed_input_V=self.phase["programmed_input_V"], procedure_stage=self.stage)
            return means

        for index, phase in enumerate(self.phases):
            phase_result = next(item for item in sweep["phases"] if item["nominal_input_V"] == phase["nominal_input_V"])
            points = [p for p in run["points"] if p["vin_target_V"] == phase["nominal_input_V"]]
            if index and clock.monotonic() - ctx.began >= LAST_PHASE_START_S:
                phase_result.update(stop_reason="Global time budget reserved for safe shutdown; phase not started")
                continue
            self.phase, self.stage = phase, f"efficiency-{phase['nominal_input_V']:g}v"
            self.startup_source_cycles = 0
            phase_result.update(status="running", started_monotonic_s=clock.monotonic() - ctx.began)
            active = points[0]
            try:
                if index:
                    # Previous phase already stopped. Recheck OFF before any
                    # voltage request, then configure and verify a new timer.
                    if ctx.pilot.supply.get_output_enabled(1) or ctx.load.get_input_enabled():
                        raise ExtendedAbort("Outputs were not both OFF before configuring the next voltage")
                    ctx.pilot.voltage, ctx.pilot.source_ovp = phase["programmed_input_V"], phase["source_OVP_V"]
                    ctx.pilot.configure()
                    select(active)
                    ctx.event("voltage_phase_protection_verified", nominal_input_V=phase["nominal_input_V"],
                              programmed_input_V=phase["programmed_input_V"], source_OVP_V=phase["source_OVP_V"],
                              source_current_limit_A=SOURCE_CURRENT_LIMIT, hardware_deadline_s=720)
                    ctx.pilot.start()
                    ctx.event("source_enabled_with_deadline", nominal_input_V=phase["nominal_input_V"],
                              programmed_input_V=phase["programmed_input_V"])
                    for _ in range(5):
                        clock.sleep(1)
                        ctx.cycle(active, "starting", loaded=False, startup=True)
                    ctx.load.input_on()
                    for _ in range(5):
                        clock.sleep(1)
                        ctx.cycle(active, "starting", startup=True)
                previous_request = .1
                stop_reason = "Declared load grid completed"
                for point in points:
                    if clock.monotonic() - ctx.began >= LAST_POINT_START_S:
                        stop_reason = "Global time budget reserved for safe shutdown; remaining loads not attempted"
                        break
                    active = point
                    select(point)
                    if point["iout_target_A"] != previous_request:
                        ctx.load.set_current(point["iout_target_A"])
                        previous_request = point["iout_target_A"]
                        ctx.event("load_request_changed", point_id=point["point_id"], requested_load_A=previous_request,
                                  nominal_input_V=phase["nominal_input_V"])
                    means = qualify(point)
                    phase_result["qualified_point_ids"].append(point["point_id"])
                    phase_result["highest_qualified_point"] = {"point_id": point["point_id"], **means}
                    save(point)
                    ctx.set_active(None)
                    print(json.dumps({"point": point["point_id"], "nominal_input_V": phase["nominal_input_V"],
                        "programmed_input_V": phase["programmed_input_V"], "requested_load_A": point["iout_target_A"],
                        "accepted_cycles": len(point["acquisition_cycle_ids"]), **means}), flush=True)
                    if means["Iin_A"] >= TARGET_INPUT_CURRENT:
                        stop_reason = "Target mean input current reached within a qualified CV acquisition window"
                        break
            except BenchBoundary as exc:
                # The raw boundary cycle is already durable. Remove source
                # power before extra checkpoint writes or trying another Vin.
                self.stop_phase(ctx)
                active.update(qualification=exc.qualification, reason=str(exc), acquisition_cycle_ids=[])
                phase_result["boundary_observation"] = {"point_id": active["point_id"], "values": exc.values,
                                                         "source_modes": exc.modes, "reason": str(exc)}
                stop_reason = str(exc)
                save(active)
                ctx.set_active(None)
            else:
                self.stop_phase(ctx)
            phase_result.update(status="completed", stop_reason=stop_reason,
                                finished_monotonic_s=clock.monotonic() - ctx.began)
            for point in points:
                if point["qualification"] == "not-run":
                    point["reason"] = "Conditional request not reached: " + stop_reason
            ctx.event("voltage_phase_complete", **phase_result)
            atomic_json(ctx.directory / "run.json", run)
        for point in run["points"]:
            if point["qualification"] == "not-run" and not point["reason"].startswith("Conditional request not reached"):
                point["reason"] = "Conditional request not reached before the global time budget reserve"
        atomic_json(ctx.directory / "run.json", run)


def _validated_12v_attempt(directory: Path, config_path: Path) -> dict:
    """Read-only prerequisite for one fixed 24/near36 continuation, not resume."""
    from benchctl.config import load_config
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "integrity.json").read_text())
    if not {"run.json", "plan.json", "raw/samples.jsonl", "request.json"} <= set(manifest.get("files", {})):
        raise ExtendedAbort("Prior integrity manifest does not cover the required continuation evidence")
    verify_integrity(directory)
    previous = json.loads((directory / "run.json").read_text())
    prior_plan = Plan.model_validate_json((directory / "plan.json").read_text())
    expected = voltage_sweep_plan()
    if (not verify_plan_hash(prior_plan) or prior_plan.plan_hash != expected.plan_hash
            or previous.get("plan_hash") != prior_plan.plan_hash):
        raise ExtendedAbort("Prior attempt does not match the fixed complete voltage-sweep plan")
    if (previous.get("data_source") != "measured" or previous.get("real_hardware_opened") is not True
            or previous.get("execution_status") != "aborted" or previous.get("lifecycle_state") != "FINALIZED"
            or previous.get("executed_point_ids") != [prior_plan.points[0].point_id]):
        raise ExtendedAbort("Continuation requires a finalized measured startup abort at the first 12 V point only")
    shutdown = previous.get("shutdown", {})
    if set(shutdown) != {"source", "load", "source_deadline"} or not all(
            state.get("state") == "OFF" and state.get("verified") is True for state in shutdown.values()):
        raise ExtendedAbort("Prior attempt does not prove source, load and deadline verified OFF")
    outcomes = previous.get("points", [])
    if (len(outcomes) != len(prior_plan.points) or any(p.get("acquisition_cycle_ids") or p.get("qualification") == "valid" for p in outcomes)
            or outcomes[0].get("qualification") != "inconclusive"
            or any(p.get("qualification") != "not-run" for p in outcomes[1:])):
        raise ExtendedAbort("Prior attempt contains accepted, later-phase, or unexpected point outcomes")
    if any(any(outcome.get(key) != getattr(request, key) for key in
               ("point_id", "test_id", "vin_target_V", "iout_target_A"))
           for outcome, request in zip(outcomes, prior_plan.points)):
        raise ExtendedAbort("Prior outcome identity does not match its fixed plan")
    errors = previous.get("errors", [])
    if len(errors) != 1 or not errors[0].startswith("BenchBoundary:"):
        raise ExtendedAbort("Only the recorded 12 V startup source-boundary abort permits this continuation")
    raw = [RawSample.model_validate_json(line).model_dump()
           for line in (directory / "raw/samples.jsonl").read_text().splitlines() if line]
    cycles = defaultdict(list)
    for row in raw:
        if (row["run_id"] != previous["run_id"] or row["point_id"] != prior_plan.points[0].point_id
                or row["test_id"] != "efficiency-12v" or row["phase"] != "starting"
                or row["status"] != "ok" or row["quality_flags"]):
            raise ExtendedAbort("Prior evidence must contain only intact 12 V startup observations")
        cycles[row["acquisition_cycle_id"]].append(row)
    if not cycles:
        raise ExtendedAbort("Prior startup boundary has no retained measurements")
    values_by_cycle = []
    for rows in cycles.values():
        if Counter(row["quantity"] for row in rows) != Counter(("Vin_V", "Iin_A", "Vout_V", "Iout_A")):
            raise ExtendedAbort("Prior startup boundary has an incomplete measurement cycle")
        values = {row["quantity"]: row["value"] for row in rows}
        if (any(value is None or not math.isfinite(value) for value in values.values())
                or not -.05 <= values["Vin_V"] <= 12.5 or not -.005 <= values["Iin_A"] <= ABSOLUTE_INPUT_CURRENT
                or not -.05 <= values["Vout_V"] <= 13.2 or not -.02 <= values["Iout_A"] <= OUTPUT_CURRENT_GUARD):
            raise ExtendedAbort("A prior absolute electrical fault does not permit continuation")
        values_by_cycle.append((max(row["query_end_monotonic_s"] for row in rows), values, rows))
    _, last, last_rows = max(values_by_cycle, key=lambda item: item[0])
    if (last["Vin_V"] >= 11.5 and last["Iin_A"] < HEADROOM_STOP_CURRENT
            and not any(row["acquisition_settings"].get("source_mode") == "CC" for row in last_rows)):
        raise ExtendedAbort("Prior startup readings do not establish the recorded source boundary")
    identities = previous.get("instrument_identities", {})
    config = load_config(config_path)
    for role, device_name, model in (("source", "psu_rigol_1", "DP821A"), ("load", "load_rigol_1", "DL3031A")):
        identity = identities.get(role, {})
        device = config.devices[device_name]
        if not device.expected_serial or identity.get("serial") != device.expected_serial or identity.get("model") != model:
            raise ExtendedAbort("Continuation inventory must match the prior verified source and load identities")
    return {"run_id": previous["run_id"], "directory": str(directory),
            "integrity_sha256": hashlib.sha256((directory / "integrity.json").read_bytes()).hexdigest(),
            "plan_hash": prior_plan.plan_hash, "nominal_input_V": 12., "execution_status": "aborted",
            "qualified_points": 0, "reason": errors[0], "last_startup_cycle": last}


class VoltageContinuationProcedure(VoltageSweepProcedure):
    adapter = VoltageContinuationRigol

    def __init__(self, prior):
        super().__init__()
        self.phases, self.phase, self.stage = PHASES[1:], PHASES[1], "efficiency-24v"
        self.prior = prior

    def plan(self):
        plan = voltage_sweep_plan()
        plan.recipe.recipe_id += "-continue-after-12v-startup"
        plan.recipe.tests = [test for test in plan.recipe.tests if test.id != "efficiency-12v"]
        plan.points = [point for point in plan.points if point.vin_target_V != 12.]
        plan.bench.notes = [note.replace("All 35 requests", "All 27 continuation requests")
                            .replace("Source OVP is 13/26/36 V by phase", "Source OVP is 26/36 V by continuation phase")
                            for note in plan.bench.notes]
        plan.bench.notes.append(f"12 V is not repeated: prior startup abort {self.prior['run_id']} is retained separately, with no qualified efficiency measurements.")
        plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
        return plan

    def metadata(self):
        metadata = super().metadata()
        metadata["scenario"] = "24 V and near 36 V efficiency continuation after an unqualified 12 V startup attempt"
        metadata["method"]["source_OVP_V"] = [26., 36.]
        sweep = metadata["method"]["voltage_efficiency_sweep"]
        sweep["prior_input_attempt"] = self.prior
        sweep["phases"][0].update(status="previous-attempt-unqualified",
            stop_reason=f"12 V not repeated after startup abort in {self.prior['run_id']}: {self.prior['reason']}")
        return metadata


def run_voltage_sweep(config_path: Path, out: Path, *, arm: bool = False,
                      continue_after_12v_startup: Path | None = None) -> Path:
    if not arm:
        raise ExtendedAbort("Explicit --arm is required; this command operates real equipment")
    procedure = (VoltageContinuationProcedure(_validated_12v_attempt(continue_after_12v_startup, config_path))
                 if continue_after_12v_startup is not None else VoltageSweepProcedure())
    return _run_fixed(config_path, out, arm=arm, procedure=procedure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("runs/real-voltage-sweep"))
    parser.add_argument("--arm", action="store_true")
    parser.add_argument("--continue-after-12v-startup", type=Path,
                        help="Prior finalized 12 V startup-boundary run; starts only the unchanged 24/near36 V phases")
    args = parser.parse_args()
    path = run_voltage_sweep(args.config, args.out, arm=args.arm,
                             continue_after_12v_startup=args.continue_after_12v_startup)
    return 0 if json.loads((path / "run.json").read_text())["execution_status"] == "completed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
