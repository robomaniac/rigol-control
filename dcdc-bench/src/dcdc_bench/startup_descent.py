"""Fixed 15 V unloaded startup followed by energized light-load input descent.

This experiment observes one startup and one descending operating sequence.
It does not establish a startup threshold, UVLO hysteresis or a DUT rating.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

from .domain import TestDefinition
from .extended import ExtendedAbort, _number, _run_fixed, extended_plan
from .planning import _hash_payload, build_plan
from .source_limit import BenchBoundary, SourceLimitRigol
from .storage import atomic_json

POLICY_ID = "supervised-15v-startup-light-load-descent-v1"
NOMINAL_INPUTS = (15., 14., 13., 12., 11., 10., 9.)
PROGRAMMED_INPUTS = (15., 14., 13., 12., 11., 10., 9.1)
LOAD_A, OUTPUT_GUARD_A = .1, .15
STARTUP_TIMEOUT_S, TRANSITION_TIMEOUT_S, ACQUISITION_S = 30., 5., 8.
INPUT_MIN_READBACK_V, INPUT_MAX_READBACK_V = 9.03, 15.5
INPUT_TARGET_TOLERANCE_V = .15


class StartupDescentRigol(SourceLimitRigol):
    voltage, source_ovp = 15., 16.
    output_current_limit, initial_current = OUTPUT_GUARD_A, LOAD_A

    def set_live_voltage(self, target):
        """Only the next authorized descending step may change an ON source.

        The driver's ordinary set_voltage keeps its output-OFF interlock; the
        bounded set_voltage_live is its single sanctioned exception.
        """
        if self.voltage not in PROGRAMMED_INPUTS[:-1] or target != PROGRAMMED_INPUTS[PROGRAMMED_INPUTS.index(self.voltage)+1]:
            raise ExtendedAbort("Live voltage change is not the next fixed descending step")
        if self.verify_running(True)[0] != "CV":
            raise ExtendedAbort("Source must be in CV before a live voltage change")
        _number(self.supply.get_current_limit(1), 1., "Live source current limit", .0005)
        _number(self.load.get_current_setpoint(), LOAD_A, "Live load current request", .0005)
        try:
            self.supply.set_voltage_live(1, target, max_step_v=1.)
        except (RuntimeError, ValueError) as exc:
            raise ExtendedAbort(f"Live voltage change refused by the driver: {exc}") from exc
        self.supply.check_errors()
        self.voltage = target


def startup_descent_plan():
    base = extended_plan()
    dut, bench, recipe = (p.model_copy(deep=True) for p in (base.dut, base.bench, base.recipe))
    bench.bench_id, recipe.recipe_id = "rigol-supervised-startup-descent", "12t12-15v-startup-descent"
    dut.execution_approval.protective_policy_id = POLICY_ID
    bench.protective_controls.policy_id = recipe.authorization.protective_policy_id = POLICY_ID
    bench.source.max_current_A = bench.protective_controls.source_current_limit_A = 1.
    bench.source.max_voltage_V, bench.source.max_power_W = 16., 16.
    bench.protective_controls.dut_input_overvoltage_V = 16.
    bench.load.max_current_A = bench.protective_controls.output_overcurrent_A = OUTPUT_GUARD_A
    bench.load.max_power_W = 2.
    bench.notes = [
        "User explicitly requested checking the observed 15 V startup followed by operation near 9 V without restarting the DUT.",
        "Unloaded 15 V startup must reach five consecutive stable 10.8–13.2 V output observations within 30 s before enabling the 100 mA load.",
        "Source CH1 remains set to 1.000 A, OCP 1.05 A and OVP 16 V. Load CC guard is 0.15 A.",
        "Both outputs stay energized during the authorized descending voltage changes; source deadline remains continuously active.",
        "Nominal 9 V is programmed to 9.1 V with a 9.03 V minimum source-terminal readback guard; wiring drop and absolute calibration remain unquantified.",
        "Transition samples are retained but never accepted into settled point means. Each step must reach its new source-voltage window within 5 s.",
        "One verified 720 s source deadline and the shared 660 s software deadline bound the entire experiment.",
        "The observation does not establish a startup threshold, UVLO hysteresis, thermal equilibrium, minimum rated input voltage or full output rating.",
    ]
    recipe.tests = [TestDefinition(id="startup-descent", input_voltage_targets_V=list(NOMINAL_INPUTS),
                                   output_current_targets_A=[LOAD_A])]
    recipe.acquisition.duration_s = ACQUISITION_S
    plan = build_plan(dut, bench, recipe)
    for point in plan.points:
        if point.status != "approval_blocked":
            raise ExtendedAbort(f"Startup descent violates fixed planning envelope: {point.reason}")
        point.status = "executable"
        point.reason = "Conditional fixed startup/descent policy with measured source headroom"
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan


class StartupDescentProcedure:
    adapter = StartupDescentRigol
    plan = staticmethod(startup_descent_plan)

    def __init__(self):
        self.stage, self.target, self.transition_from = "unloaded-startup", 15., None

    @staticmethod
    def metadata():
        return {"scenario": "Start at 15 V, then reduce input toward 9 V without restarting",
            "authorization": "User explicitly requested reproducing 15 V startup then continued operation toward 9 V on the connected DUT",
            "executed_point_ids": [],
            "metrology_limitations": [
                "Source/load-terminal measurements include input and output wiring losses.",
                "ADC freshness, calibration and uncertainty are unquantified; no temperature sensor is present.",
                "One unloaded startup and one energized descent do not establish startup threshold, UVLO hysteresis or full output rating.",
                "Nominal 9 V is programmed to 9.1 V; minimum DUT-pin voltage and transient behavior are not measured."],
            "method": {"source_current_limit_A":1., "source_OVP_V":16., "source_OCP_A":1.05,
                "input_current_absolute_guard_A":1.02,"headroom_stop_input_current_A":.995,
                "output_load_ceiling_A":LOAD_A,"output_load_guard_A":OUTPUT_GUARD_A,
                "hardware_deadline_s":720,"software_deadline_s":660,"candidate_window_s":ACQUISITION_S,
                "conditional_coverage":True,"separate_hold":False,
                "startup_descent": {"nominal_input_voltages_V":list(NOMINAL_INPUTS),
                    "programmed_input_voltages_V":list(PROGRAMMED_INPUTS),"load_current_A":LOAD_A,
                    "startup_timeout_s":STARTUP_TIMEOUT_S,"startup_stable_sample_count":5,
                    "startup_minimum_stable_span_s":4.,"startup_status":"not-started",
                    "startup_cycle_ids":[],"startup_stable_cycle_ids":[],
                    "transition_timeout_s":TRANSITION_TIMEOUT_S,"input_target_tolerance_V":INPUT_TARGET_TOLERANCE_V,
                    "minimum_input_readback_V":INPUT_MIN_READBACK_V,"transitions":[]}}}

    @staticmethod
    def record_attempt(run, point):
        if point["point_id"] not in run["executed_point_ids"]:
            point["execution_index"] = len(run["executed_point_ids"])+1
            run["executed_point_ids"].append(point["point_id"])
        point["programmed_input_V"] = PROGRAMMED_INPUTS[NOMINAL_INPUTS.index(point["vin_target_V"])]

    def guard(self, values, requested, *, loaded=True, startup=False, mode_before="CV", mode_after="CV"):
        if any(not math.isfinite(v) for v in values.values()):
            raise ExtendedAbort("Nonfinite startup/descent measurement")
        if not -.005 <= values["Iin_A"] <= 1.02:
            raise ExtendedAbort("Absolute input-current guard failed")
        if not -.05 <= values["Vin_V"] <= INPUT_MAX_READBACK_V:
            raise ExtendedAbort("Absolute input-voltage guard failed")
        if not -.05 <= values["Vout_V"] <= 13.2 or not -.02 <= values["Iout_A"] <= OUTPUT_GUARD_A:
            raise ExtendedAbort("Absolute output guard failed")
        lower = max(INPUT_MIN_READBACK_V, self.target-INPUT_TARGET_TOLERANCE_V)
        upper = (self.target if self.transition_from is None else self.transition_from)+INPUT_TARGET_TOLERANCE_V
        if (mode_before != "CV" or mode_after != "CV" or values["Iin_A"] >= .995
                or not lower <= values["Vin_V"] <= upper):
            raise BenchBoundary("Source mode, current ceiling or input-voltage window stopped startup/descent",
                                values, [mode_before,mode_after])
        if not startup and values["Vout_V"] < 10.8:
            raise BenchBoundary("Output fell below 10.8 V during energized descent; cause unclassified",
                                values,[mode_before,mode_after],qualification="inconclusive")
        if loaded and not startup and abs(values["Iout_A"]-requested) > .02:
            raise ExtendedAbort("Requested 100 mA output load was not established")

    def startup(self, ctx):
        """Retain every unloaded startup quartet; qualify none for efficiency."""
        detail, clock = ctx.run["method"]["startup_descent"], ctx.clock
        point = ctx.run["points"][0]
        detail["startup_status"] = "waiting-for-stable-output"
        began, stable = clock.monotonic(), []
        while clock.monotonic()-began < STARTUP_TIMEOUT_S:
            clock.sleep(1)
            cid, values, _ = ctx.cycle(point,"starting",loaded=False,startup=True)
            detail["startup_cycle_ids"].append(cid)
            now = clock.monotonic()
            if now-began > STARTUP_TIMEOUT_S:
                break
            if 10.8 <= values["Vout_V"] <= 13.2:
                stable.append((cid,now,values["Vout_V"]))
                stable = stable[-5:]
            else:
                stable.clear()
            if len(stable)==5 and stable[-1][1]-stable[0][1] >= 4. and max(p[2] for p in stable)-min(p[2] for p in stable) <= .05:
                detail.update(startup_status="stable-before-load", startup_stable_cycle_ids=[p[0] for p in stable],
                    startup_elapsed_s=now-began,startup_stable_span_s=stable[-1][1]-stable[0][1])
                ctx.event("unloaded_startup_stable", **detail)
                atomic_json(ctx.directory/"run.json",ctx.run)
                break
        else:
            detail["startup_status"] = "timeout"
            raise ExtendedAbort("15 V unloaded startup did not establish stable output within 30 s; load was not enabled")
        if detail["startup_status"] != "stable-before-load":
            detail["startup_status"] = "timeout"
            raise ExtendedAbort("15 V unloaded startup timeout; load was not enabled")
        ctx.load.input_on()
        self.stage = "loaded-startup"
        ctx.event("startup_load_enabled", requested_load_A=LOAD_A)
        for _ in range(5):
            clock.sleep(1)
            ctx.cycle(point,"starting",startup=False)

    def execute(self, ctx):
        clock, run = ctx.clock, ctx.run
        detail = run["method"]["startup_descent"]
        for point in run["points"]:
            self.record_attempt(run,point)
            ctx.set_active(point)
            atomic_json(ctx.directory/"run.json",run)
            target = point["programmed_input_V"]
            if target != self.target:
                previous = self.target
                self.transition_from, self.target, self.stage = previous,target,"input-transition"
                transition = {"point_id":point["point_id"],"from_programmed_V":previous,"to_programmed_V":target,
                              "cycle_ids":[],"status":"commanding"}
                detail["transitions"].append(transition)
                ctx.pilot.set_live_voltage(target)
                transition["status"] = "waiting-for-input-readback"
                ctx.event("live_input_voltage_changed",point_id=point["point_id"],from_programmed_V=previous,to_programmed_V=target)
                changed = clock.monotonic()
                while clock.monotonic()-changed < TRANSITION_TIMEOUT_S:
                    clock.sleep(.25)
                    cid, values, _ = ctx.cycle(point,"settling")
                    transition["cycle_ids"].append(cid)
                    if clock.monotonic()-changed > TRANSITION_TIMEOUT_S:
                        break
                    if abs(values["Vin_V"]-target) <= INPUT_TARGET_TOLERANCE_V:
                        transition.update(status="new-input-established",elapsed_s=clock.monotonic()-changed,
                                          measured_input_V=values["Vin_V"])
                        self.transition_from = None
                        break
                if self.transition_from is not None:
                    transition["status"] = "timeout"
                    raise ExtendedAbort("New input-voltage readback did not establish within 5 s; descent stopped")
            self.stage = "settled-input-descent"
            settle_start, settling = clock.monotonic(), []
            for _ in range(5):
                clock.sleep(1)
                _,values,_ = ctx.cycle(point,"settling")
                settling.append(values["Vout_V"])
            if max(settling)-min(settling) > .05:
                raise ExtendedAbort("Output did not settle within a 50 mV span")
            began, ids, readings, maximum_skew = clock.monotonic(), [], [], 0.
            while clock.monotonic()-began < ACQUISITION_S or len(ids)<5:
                cid,values,skew = ctx.cycle(point,"acquiring")
                ids.append(cid)
                readings.append(values)
                maximum_skew = max(maximum_skew,skew)
                clock.sleep(1)
            ended = clock.monotonic()
            if max(v["Vout_V"] for v in readings)-min(v["Vout_V"] for v in readings) > .05:
                raise ExtendedAbort("Output voltage span exceeded 50 mV during acquisition")
            point.update(qualification="valid",reason="Stable energized light-load operation after the recorded 15 V startup; uncertainty unquantified",
                acquisition_cycle_ids=ids,settled=True,settling_elapsed_s=began-settle_start,
                acquisition_elapsed_s=ended-began,acquisition_start_monotonic_s=began-ctx.began,
                acquisition_end_monotonic_s=ended-ctx.began,maximum_interchannel_skew_s=maximum_skew,procedure_stage=self.stage)
            ctx.store.append("points",{**point,"event":"point_finalized","monotonic_s":clock.monotonic()-ctx.began})
            atomic_json(ctx.directory/"run.json",run)
            print(json.dumps({"point":point["point_id"],"nominal_input_V":point["vin_target_V"],
                "programmed_input_V":target,"accepted_cycles":len(ids),
                **{key:mean(v[key] for v in readings) for key in readings[0]}}),flush=True)
            ctx.set_active(None)
        detail["descent_completed"] = True
        atomic_json(ctx.directory/"run.json",run)


def run_startup_descent(config_path: Path,out: Path,*,arm=False):
    return _run_fixed(config_path,out,arm=arm,procedure=StartupDescentProcedure())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=Path("runs/real-startup-descent"))
    parser.add_argument("--arm",action="store_true")
    args = parser.parse_args()
    path = run_startup_descent(args.config,args.out,arm=args.arm)
    return 0 if json.loads((path/"run.json").read_text())["execution_status"] == "completed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
