"""Fixed 24 V test approaching the DP821A CH1 1 A input-current ceiling.

The output load is adaptive and bounded to 2 A. The current limit being
approached belongs to the supply feeding the converter, not its 12 V output.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

from .domain import TestDefinition
from .extended import ExtendedAbort, ExtendedRigol, _run_fixed, extended_plan
from .planning import _hash_payload, build_plan
from .storage import atomic_json

POLICY_ID = "supervised-24V-source1A-adaptive-v1"
SOURCE_CURRENT_LIMIT = 1.000
SOURCE_OCP = 1.05
ABSOLUTE_INPUT_CURRENT = 1.02
TARGET_INPUT_CURRENT = .98
HEADROOM_STOP_CURRENT = .995
FINE_THRESHOLD = .90
OUTPUT_CEILING = 2.0
OUTPUT_GUARD = 2.05
LIGHT_LOAD = .10
ACQUISITION_SECONDS = 10.
ENDPOINT_SECONDS = 30.


class BenchBoundary(ExtendedAbort):
    """A preserved, unqualified observation that ends the upward search."""

    def __init__(self, reason, values, modes, *, qualification="setup-limited"):
        super().__init__(reason)
        self.values, self.modes, self.qualification = values, modes, qualification


class SourceLimitRigol(ExtendedRigol):
    current_limit = SOURCE_CURRENT_LIMIT
    source_ocp = SOURCE_OCP
    output_current_limit = OUTPUT_GUARD
    initial_current = LIGHT_LOAD

    def mode(self):
        # CC is observable evidence here, never a qualified nominal-Vin result.
        mode = self.st.query(":OUTP:CVCC? CH1").strip().upper()
        if mode not in ("CV", "CC"):
            raise ExtendedAbort(f"Unexpected source mode {mode!r}")
        return mode


def source_limit_plan():
    base = extended_plan()
    dut, bench, recipe = (item.model_copy(deep=True) for item in (base.dut, base.bench, base.recipe))
    bench.bench_id, recipe.recipe_id = "rigol-supervised-source-limit", "12t12-24v-source-limit"
    dut.execution_approval.protective_policy_id = POLICY_ID
    bench.protective_controls.policy_id = recipe.authorization.protective_policy_id = POLICY_ID
    bench.source.max_current_A = bench.protective_controls.source_current_limit_A = SOURCE_CURRENT_LIMIT
    bench.source.max_power_W = 24.
    bench.load.max_current_A = bench.protective_controls.output_overcurrent_A = OUTPUT_GUARD
    bench.load.max_power_W = 30.
    bench.notes = [
        "User explicitly requested approaching the DP821A CH1 1 A source current limit, keeping the converter input at 24 V.",
        "77 output-load candidates from 0.100 to 2.000 A are conditional search requests, not promised operating points.",
        "Choose 0.100 A output increments while measured input current is below 0.90 A; then use 0.025 A increments.",
        "Target approximately 0.98 A input. Stop escalation at 0.995 A, source CC, input headroom loss, or a low-output boundary.",
        "One recovery to a separate 0.100 A return point is permitted; hard guards and protection/communication faults terminate the test.",
        "The planner's 100% efficiency is an ideal-power ceiling only. It is not expected efficiency or a claim that all candidates are achievable.",
        "Source regulation is programmed to 1.000 A; 1.05 A OCP and 1.02 A readback stop do not authorize a larger current setpoint.",
        "Independent source deadline 720 s, software deadline 660 s; local load sensing; uncertainty and physical full ratings remain unverified.",
        "This test does not characterize the DUT's 4 A rating, temperature, ripple, or load transients."]
    recipe.tests = [TestDefinition(id="increasing-load", input_voltage_targets_V=[24.],
                                 output_current_targets_A=[value / 1000 for value in range(100, 2001, 25)]),
                    TestDefinition(id="decreasing-load", input_voltage_targets_V=[24.],
                                   output_current_targets_A=[LIGHT_LOAD])]
    # Each candidate is below the *ideal* physical input-power envelope. The
    # separately reviewed worker decides whether to attempt the next candidate
    # from measured headroom, not from an optimistic efficiency prediction.
    recipe.planning.efficiency_estimate_fraction = 1.
    recipe.planning.source_current_budget_fraction = 1.
    recipe.acquisition.duration_s = ACQUISITION_SECONDS
    plan = build_plan(dut, bench, recipe)
    for point in plan.points:
        if point.status != "approval_blocked":
            raise ExtendedAbort(f"Conditional candidate violates absolute planning envelope: {point.reason}")
        point.status = "executable"
        point.reason = "Conditional fixed-policy search candidate; execution depends on measured source headroom"
    plan.warnings.append("Requested coverage is conditional: the worker intentionally skips fine-grid candidates during coarse stepping and stops at the measured source boundary.")
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan


class SourceLimitProcedure:
    adapter = SourceLimitRigol
    stage = "starting"
    plan = staticmethod(source_limit_plan)

    @staticmethod
    def record_attempt(run, point):
        if point["point_id"] not in run["executed_point_ids"]:
            point["execution_index"] = len(run["executed_point_ids"]) + 1
            run["executed_point_ids"].append(point["point_id"])

    @staticmethod
    def metadata():
        return {"scenario": "24 V converter test approaching the 1 A supply input limit", "executed_point_ids": [],
            "authorization": "User explicitly requested pushing the existing DP821A supply toward its 1 A limit; CH1, DUT, and polarity confirmed in this session",
            "method": {"source_current_limit_A": SOURCE_CURRENT_LIMIT, "source_OVP_V": 26., "source_OCP_A": SOURCE_OCP,
                "input_current_absolute_guard_A": ABSOLUTE_INPUT_CURRENT,
                "target_input_current_A": TARGET_INPUT_CURRENT, "headroom_stop_input_current_A": HEADROOM_STOP_CURRENT,
                "fine_step_threshold_input_current_A": FINE_THRESHOLD,
                "output_load_ceiling_A": OUTPUT_CEILING, "output_load_guard_A": OUTPUT_GUARD,
                "coarse_output_step_A": .10, "fine_output_step_A": .025,
                "candidate_window_s": ACQUISITION_SECONDS, "endpoint_window_s": ENDPOINT_SECONDS,
                "hardware_deadline_s": 720, "software_deadline_s": 660,
                "conditional_coverage": True, "maximum_recovery_attempts": 1,
                "return_load_A": LIGHT_LOAD, "separate_hold": False,
                "planning_efficiency_note": "100% is solely an ideal-power envelope; actual measured input current controls advancement",
                "source_limit_search": {"target_input_current_A": TARGET_INPUT_CURRENT,
                    "input_current_limit_A": SOURCE_CURRENT_LIMIT, "output_current_cap_A": OUTPUT_CEILING,
                    "selected_endpoint_point_id": None, "stop_reason": None}}}

    @staticmethod
    def guard(values, requested, *, loaded=True, startup=False, mode_before="CV", mode_after="CV"):
        modes = [mode_before, mode_after]
        if any(not math.isfinite(value) for value in values.values()):
            raise ExtendedAbort("Nonfinite measurement; no recovery is permitted")
        if not -.005 <= values["Iin_A"] <= ABSOLUTE_INPUT_CURRENT or not -.05 <= values["Vin_V"] <= 24.5:
            raise ExtendedAbort(f"Absolute input guard failed: {values}")
        if not -.05 <= values["Vout_V"] <= 13.2 or not -.02 <= values["Iout_A"] <= OUTPUT_GUARD:
            raise ExtendedAbort(f"Absolute output guard failed: {values}")
        if "CC" in modes or values["Vin_V"] < 23.5 or values["Iin_A"] >= HEADROOM_STOP_CURRENT:
            raise BenchBoundary("Supply current ceiling or nominal-input headroom reached; this is not a DUT failure verdict", values, modes)
        if not startup and values["Vout_V"] < 10.8:
            raise BenchBoundary("Output fell below the conservative stop threshold; cause is unclassified", values, modes,
                                qualification="inconclusive")
        if loaded and not startup and abs(values["Iout_A"] - requested) > .02:
            raise ExtendedAbort(f"Load did not establish its requested current: requested {requested:g} A; {values}")

    def execute(self, ctx):
        run, clock, method = ctx.run, ctx.clock, ctx.run["method"]
        candidates = [p for p in run["points"] if p["test_id"] == "increasing-load"]
        return_point = run["points"][-1]
        by_milliamps = {round(p["iout_target_A"] * 1000): p for p in candidates}
        requested_mA, previous_request = 100, LIGHT_LOAD
        successful, stop_reason, recovered = [], "Declared output-load ceiling reached", False

        def save(point):
            ctx.store.append("points", {**point, "event": "point_finalized", "monotonic_s": clock.monotonic() - ctx.began})
            atomic_json(ctx.directory / "run.json", run)

        def mark_attempt(point):
            self.record_attempt(run, point)

        def choose_load(point):
            nonlocal previous_request
            mark_attempt(point)
            ctx.set_active(point)
            atomic_json(ctx.directory / "run.json", run)
            if point["iout_target_A"] != previous_request:
                ctx.load.set_current(point["iout_target_A"])
                previous_request = point["iout_target_A"]
                ctx.event("load_request_changed", point_id=point["point_id"], requested_load_A=previous_request,
                          procedure_stage=self.stage)

        def qualify(point, *, extend_endpoint=False):
            ctx.set_active(point)
            settled_from, voltages = clock.monotonic(), []
            for _ in range(5):
                clock.sleep(1)
                _, values, _ = ctx.cycle(point, "settling")
                voltages.append(values["Vout_V"])
            if max(voltages) - min(voltages) > .05:
                raise ExtendedAbort("Output did not settle within a 50 mV span")
            acquisition_from = clock.monotonic()
            accepted, readings, skew_max = [], [], 0.
            duration, endpoint, endpoint_trigger = ACQUISITION_SECONDS, False, None
            while clock.monotonic() - acquisition_from < duration or len(accepted) < 5:
                cycle_id, values, skew = ctx.cycle(point, "acquiring")
                accepted.append(cycle_id)
                readings.append(values)
                skew_max = max(skew_max, skew)
                clock.sleep(1)
                if extend_endpoint and not endpoint and clock.monotonic() - acquisition_from >= ACQUISITION_SECONDS:
                    if mean(row["Iin_A"] for row in readings) >= TARGET_INPUT_CURRENT:
                        endpoint, duration = True, ENDPOINT_SECONDS
                        endpoint_trigger = {"input_current_mean_A": mean(row["Iin_A"] for row in readings),
                            "acquisition_cycle_ids": list(accepted),
                            "window_start_monotonic_s": acquisition_from - ctx.began,
                            "window_end_monotonic_s": clock.monotonic() - ctx.began}
                        ctx.event("endpoint_window_extended", point_id=point["point_id"], duration_s=duration,
                                  trigger=endpoint_trigger)
            ended = clock.monotonic()
            if max(row["Vout_V"] for row in readings) - min(row["Vout_V"] for row in readings) > .05:
                raise ExtendedAbort("Output voltage span exceeded 50 mV during acquisition")
            means = {key: mean(row[key] for row in readings) for key in readings[0]}
            point.update(qualification="valid", reason="Stable CV source and guarded DC readbacks; uncertainty unquantified",
                acquisition_cycle_ids=accepted, settled=True, settling_elapsed_s=acquisition_from - settled_from,
                acquisition_elapsed_s=ended - acquisition_from,
                acquisition_start_monotonic_s=acquisition_from - ctx.began, acquisition_end_monotonic_s=ended - ctx.began,
                maximum_interchannel_skew_s=skew_max, procedure_stage=self.stage,
                extended_endpoint_window=endpoint, endpoint_trigger=endpoint_trigger)
            save(point)
            ctx.set_active(None)
            print(json.dumps({"point": point["point_id"], "stage": self.stage, "requested_load_A": point["iout_target_A"],
                              "accepted_cycles": len(accepted), **means}), flush=True)
            return means, endpoint

        self.stage = "approaching-source-limit"
        while requested_mA <= round(OUTPUT_CEILING * 1000):
            point = by_milliamps[requested_mA]
            choose_load(point)
            try:
                values, endpoint = qualify(point, extend_endpoint=True)
            except BenchBoundary as exc:
                # Back off before writing explanatory metadata. The failed
                # cycle's actual readings are already durable in ctx.cycle().
                mark_attempt(return_point)
                backoff_started = clock.monotonic()
                ctx.load.set_current(LIGHT_LOAD)
                previous_request, recovered = LIGHT_LOAD, True
                ctx.set_active(return_point)
                self.stage = "return-to-light-load"
                point.update(qualification=exc.qualification, reason=str(exc), acquisition_cycle_ids=[])
                stop_reason = str(exc)
                method["boundary_observation"] = {"point_id": point["point_id"], "requested_output_A": point["iout_target_A"],
                    "values": exc.values, "source_modes": exc.modes, "reason": stop_reason}
                method["recovery_attempts"] = 1
                method["source_limit_search"]["stop_reason"] = stop_reason
                # Verify recovery before explanatory event/checkpoint fsyncs.
                # Raw boundary readings were persisted by cycle() already.
                clock.sleep(1)
                try:
                    ctx.cycle(return_point, "settling")
                    method["recovery_verified_cv"] = True
                finally:
                    method["backoff_to_recovery_observation_elapsed_s"] = clock.monotonic() - backoff_started
                ctx.event("boundary_then_light_load_backoff", point_id=point["point_id"], requested_load_A=LIGHT_LOAD,
                          source_modes=exc.modes, values=exc.values, reason=str(exc),
                          recovery_elapsed_s=method["backoff_to_recovery_observation_elapsed_s"])
                save(point)
                break
            successful.append({"point_id": point["point_id"], "requested_output_A": point["iout_target_A"],
                               "endpoint_trigger": point["endpoint_trigger"], **values})
            method["highest_qualified_ascent_point"] = max(successful, key=lambda item: item["Iin_A"])
            method["source_limit_search"]["selected_endpoint_point_id"] = successful[-1]["point_id"]
            if endpoint:
                stop_reason = "Target input current observed in the initial CV acquisition window; the same uninterrupted endpoint observation was extended to 30 s"
                break
            step_mA = 25 if values["Iin_A"] >= FINE_THRESHOLD else 100
            requested_mA += step_mA
        method["search_stop_reason"] = stop_reason
        method["target_reached_in_cv"] = bool(successful and successful[-1]["endpoint_trigger"] is not None)
        method["endpoint_final_mean_input_A"] = successful[-1]["Iin_A"] if successful else None
        method["highest_qualified_ascent_point"] = max(successful, key=lambda item: item["Iin_A"]) if successful else None
        method["source_limit_search"].update(
            selected_endpoint_point_id=successful[-1]["point_id"] if successful else None,
            stop_reason=stop_reason)
        method.setdefault("recovery_attempts", 0)
        for point in candidates:
            if point["qualification"] == "not-run":
                point["reason"] = "Conditional candidate not selected by coarse/fine stepping or not reached before the measured stop condition"
        self.stage = "return-to-light-load"
        choose_load(return_point)
        # Same separate requested point is used for planned descent or the
        # single recovery; its cycles are never merged into earlier ascent.
        qualify(return_point)
        method["return_completed"] = True
        method["boundary_backoff_used"] = recovered
        atomic_json(ctx.directory / "run.json", run)


def run_source_limit(config_path: Path, out: Path, *, arm: bool = False) -> Path:
    return _run_fixed(config_path, out, arm=arm, procedure=SourceLimitProcedure())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("runs/real-source-limit"))
    parser.add_argument("--arm", action="store_true")
    args = parser.parse_args()
    path = run_source_limit(args.config, args.out, arm=args.arm)
    run = json.loads((path / "run.json").read_text())
    return 0 if run["execution_status"] == "completed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
