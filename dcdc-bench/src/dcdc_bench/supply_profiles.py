"""ISO 16750-2 supply profiles as bounded DC steps on the synthetic plant (mock only; brief 7.5).

Two recipe test types share one procedure and the UVLO ramp's harness:

``slow_supply_ramp`` (ISO 16750-2:2023, clause 4.5)
    The declared levels are observation levels of a V-shaped ramp (start,
    down to the floor, back up). Between observation levels the source is
    walked in ``supply_profile.step_V`` live steps held ``step_interval_s``
    each (20 mV every 2.4 s is 0.5 V/min), every live step guarded and
    preserved as raw samples; each observation level waits the recipe's
    settling dwell, acquires, and is qualified as a point.

``reset_staircase`` (ISO 16750-2:2023, clause 4.6.2)
    The declared levels alternate the recovery level with strictly decreasing
    low levels; each low is held ``low_hold_s`` and each recovery
    ``recovery_hold_s`` before acquisition; every level is a qualified point.

At every level the output is classified from the accepted Vout mean as ``on``
(in band), ``off`` (reset) or ``indeterminate``. Output-off is an expected,
recorded state only where the recipe's policy documents it (descending/low
levels below ``expected_off_below_V``, ascending/recovery levels below
``expected_on_above_V``); elsewhere the normal minimum-output rule stops the
run with the cause unclassified, exactly as the UVLO ramp does. Absolute
input-current, voltage and output-current limits apply at every observation of
every phase. There is no global ``ignore_safety`` flag.

Everything here runs against the synthetic plant with a virtual clock. The
real bench refuses these test types at planning (``planning.py``) and in
``real_backend.prepare_real_plan``; no real procedure exists in this release.
The levels are commanded at the ~1 s LAN cadence: the source's own slew
between steps is not characterised and nothing here is a transient
measurement.
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import mean
from typing import Any

from .analysis import level_observation
from .domain import RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE, SUPPLY_PROFILE_TEST_TYPES, Plan, TestDefinition
from .mock_uvlo import SyntheticUvlo, UvloMockBench
from .planning import supply_profile_level_kinds, supply_profile_needs_approval, uvlo_approval_gaps, verify_plan_hash
from .storage import atomic_json
from .uvlo import (LOAD_CURRENT_TOLERANCE_A, ProtectiveLimitFault, ReadingOverride, RegulationRuleStop, SourceBoundaryStop,
                   UvloInputRampProcedure, absolute_limits, run_phase_scoped_mock)

METHOD_KEY = "supply_profile"
COMMAND_CADENCE_NOTE = ("levels are commanded as bounded DC steps at the ~1 s LAN command cadence; the source's own slew "
                        "between steps is not characterised and no edge, drop or transient is measured")
TYPE_LABELS = {SLOW_SUPPLY_RAMP_TEST_TYPE: "slow supply ramp (clause 4.5 profile)",
               RESET_STAIRCASE_TEST_TYPE: "reset staircase (clause 4.6.2 profile)"}
RUN_TAGS = {SLOW_SUPPLY_RAMP_TEST_TYPE: "ramp", RESET_STAIRCASE_TEST_TYPE: "staircase"}
STAGES = {"down": "ramp-down", "up": "ramp-up", "low": "staircase-low", "recovery": "staircase-recovery"}


def live_steps(start_V: float, target_V: float, step_V: float) -> list[float]:
    """The bounded live steps from ``start_V`` to ``target_V`` (exclusive of the start, ending exactly on the target).

    Steps are at most ``step_V`` apart; the last one lands on the target so a
    non-integer span never overshoots. Values are rounded to 0.1 mV, well
    inside the 10 mV programming resolution the real supply would need.
    """
    span = target_V - start_V
    if span == 0:
        return []
    count = max(1, math.ceil(abs(span) / step_V - 1e-9))
    direction = 1.0 if span > 0 else -1.0
    steps = [round(start_V + direction * k * step_V, 4) for k in range(1, count)]
    return steps + [target_V]


class SupplyProfileProcedure(UvloInputRampProcedure):
    """Plan-driven ISO 16750-2 supply profile. Construction refuses anything the planner did not approve outright.

    Reuses the UVLO ramp's guard (absolute limits first and always; the
    minimum-output and load-established rules only where output-off is not
    expected), its attempt bookkeeping and its plan snapshot; the level
    sequencing, holds and live steps are this class's own.
    """

    adapter = UvloMockBench

    def __init__(self, plan: Plan):  # noqa: D107 - the base initialiser is UVLO-specific; the checks here replace it
        if not verify_plan_hash(plan):
            raise ValueError("Plan hash mismatch; regenerate the plan after changing any settings")
        tests = plan.recipe.tests
        types = {test.type for test in tests}
        if not tests or len(types) != 1 or not types <= set(SUPPLY_PROFILE_TEST_TYPES) \
                or any(test.supply_profile is None for test in tests):
            raise ValueError("SupplyProfileProcedure executes one supply-profile test type (slow_supply_ramp or reset_staircase) "
                             "with a declared supply_profile block only")
        if plan.bench.mode != "mock":
            raise ValueError(f"{tests[0].type} is not yet approved for real hardware; the procedure exists on the synthetic plant only")
        if any(supply_profile_needs_approval(plan.dut, test) for test in tests):
            gaps = uvlo_approval_gaps(plan.bench, plan.recipe)
            if gaps:
                raise ValueError("Supply profile below the DUT's stated minimum refused (approved UVLO-style path, brief 7.5): "
                                 + "; ".join(gaps))
        blocked = [point for point in plan.points if point.status != "executable"]
        if blocked:
            raise ValueError(f"Supply profile refused: {len(blocked)} declared level(s) are not executable and a profile is "
                             f"never run with levels skipped or clipped. First: {blocked[0].point_id} — {blocked[0].reason}")
        self.snapshot = plan.model_copy(deep=True)
        self.kind = tests[0].type
        self.stage = "idle"
        self.policy = None
        self.step: dict[str, Any] | None = None
        self.acquiring = False
        self.limits = absolute_limits(plan)

    # -- contract surface -------------------------------------------------------------------------
    def metadata(self) -> dict[str, Any]:
        recipe = self.snapshot.recipe
        tests: dict[str, Any] = {}
        for test in recipe.tests:
            policy = test.supply_profile
            kinds = supply_profile_level_kinds(test)
            tests[test.id] = {"levels_V": list(test.input_voltage_targets_V), "level_kinds": kinds,
                              "load_A": test.output_current_targets_A[0], "policy": policy.model_dump(),
                              "clause": recipe.standard_clause,
                              "live_steps_between_levels": sum(len(live_steps(a, b, policy.step_V))
                                                               for a, b in zip(test.input_voltage_targets_V,
                                                                               test.input_voltage_targets_V[1:]))
                              if policy.step_V else 0}
        policy = recipe.tests[0].supply_profile
        cadence: dict[str, Any] = {"command_cadence_s": "about 1 (LAN); the virtual clock reproduces the declared holds",
                                   "observation_dwell_s": recipe.settling.minimum_dwell_s,
                                   "acquisition_s": recipe.acquisition.duration_s}
        if self.kind == SLOW_SUPPLY_RAMP_TEST_TYPE:
            cadence.update(live_step_V=policy.step_V, live_step_interval_s=policy.step_interval_s,
                           rate_V_per_min=policy.ramp_rate_V_per_min,
                           realisation="a staircase of live steps, not a linear ramp; intermediate readings are guarded, "
                                       "preserved as raw samples and not qualified")
        else:
            cadence.update(low_hold_s=policy.low_hold_s, recovery_hold_s=policy.recovery_hold_s,
                           realisation="each level is one live step held for its declared time before acquisition")
        return {"scenario": f"ISO 16750-2 {TYPE_LABELS[self.kind]} as bounded DC steps (synthetic plant)",
                "executed_point_ids": [],
                "authorization": (f"recipe authorization under protective policy {recipe.authorization.protective_policy_id}; "
                                  "mock execution never energizes equipment"),
                "method": {METHOD_KEY: {
                    "type": self.kind, "policy_id": recipe.authorization.protective_policy_id, "tests": tests,
                    "cadence": cadence,
                    "guard": {"absolute_limits_every_level": self.limits,
                              "scoped_to_normal_phase": [
                                  "output voltage at or above output_on_minimum_V (every live step, settling and acquisition cycle)",
                                  f"requested load current established within {LOAD_CURRENT_TOLERANCE_A:g} A (acquisition cycles)"],
                              "expected_off_phase": "descending/low levels below expected_off_below_V and ascending/recovery levels "
                                                    "below expected_on_above_V: output-off is recorded, not faulted",
                              "always": ["finite readings", "absolute limits", "source stays in CV",
                                         "interchannel skew within the recipe bound"]},
                    "synthetic_model": None}},
                "metrology_limitations": [
                    f"ISO 16750-2 supply profile: {COMMAND_CADENCE_NOTE}.",
                    "Output states are established at the declared levels only; a slow ramp's intermediate live steps are "
                    "guarded and preserved as raw samples, not qualified points, so any transition is bracketed between "
                    "observation levels, not resolved.",
                    "Source-terminal input voltage includes lead drop; the DUT-pin voltage at each level is not measured.",
                    "This procedure exists on the synthetic plant only. It is not approved for real hardware and no real "
                    "execution context exists in this release."]}

    def begin_test(self, test: TestDefinition) -> None:
        if test.type not in SUPPLY_PROFILE_TEST_TYPES or test.supply_profile is None:
            raise ValueError("begin_test requires a supply-profile test")
        self.policy, self.step = test.supply_profile, None

    def begin_step(self, vin_target_V: float, level_kind: str) -> None:
        if self.policy is None:
            raise RuntimeError("begin_step requires an active test policy")
        self.step = {"vin_target_V": vin_target_V, "level_kind": level_kind,
                     "ramp_phase": level_kind if level_kind in ("down", "up") else None,
                     "output_off_expected": self.policy.off_expected(vin_target_V, level_kind)}
        self.acquiring = False

    # -- execution against a context ---------------------------------------------------------------
    def execute(self, ctx: Any) -> None:
        run, clock, recipe = ctx.run, ctx.clock, self.snapshot.recipe
        poll = recipe.acquisition.target_poll_interval_s

        def checkpoint() -> None:
            atomic_json(ctx.directory / "run.json", run)

        for test in recipe.tests:
            self.begin_test(test)
            policy, load = test.supply_profile, test.output_current_targets_A[0]
            points = [p for p in run["points"] if p["test_id"] == test.id]
            kinds = supply_profile_level_kinds(test)
            detail = run["method"][METHOD_KEY]["tests"][test.id]
            detail.update(startup=None, levels=[], live_steps_commanded=0, completed=False)
            first = points[0]
            first["level_kind"] = kinds[0]
            first["ramp_phase"] = kinds[0] if kinds[0] in ("down", "up") else None
            self.record_attempt(run, first)
            ctx.set_active(first)
            self.begin_step(first["vin_target_V"], kinds[0])
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
            previous_state: str | None = None
            for point, kind in zip(points, kinds):
                point["level_kind"] = kind
                point["ramp_phase"] = kind if kind in ("down", "up") else None
                self.record_attempt(run, point)
                ctx.set_active(point)
                self.stage = STAGES[kind]
                target, current = point["vin_target_V"], ctx.current_input()
                commanded = 0
                if target != current:
                    if self.kind == SLOW_SUPPLY_RAMP_TEST_TYPE:
                        # Bounded live steps at the declared rate; every step is guarded with the
                        # expectation that applies at its own voltage, and preserved as raw samples.
                        for level in live_steps(current, target, policy.step_V):
                            self.begin_step(level, kind)
                            ctx.step_input(level)
                            clock.sleep(policy.step_interval_s)
                            ctx.cycle(point, "ramping")
                            commanded += 1
                        detail["live_steps_commanded"] += commanded
                        ctx.event("input_ramped", point_id=point["point_id"], from_V=current, to_V=target, live_steps=commanded,
                                  step_V=policy.step_V, step_interval_s=policy.step_interval_s, level_kind=kind,
                                  procedure_stage=self.stage)
                    else:
                        ctx.step_input(target)
                        commanded = 1
                        ctx.event("input_stepped", point_id=point["point_id"], to_V=target, level_kind=kind,
                                  output_off_expected=policy.off_expected(target, kind), procedure_stage=self.stage)
                self.begin_step(target, kind)
                off_expected = self.step["output_off_expected"]
                checkpoint()
                if self.kind == RESET_STAIRCASE_TEST_TYPE:
                    hold = policy.low_hold_s if kind == "low" else policy.recovery_hold_s
                else:
                    hold = recipe.settling.minimum_dwell_s
                dwell_started, settling_ids = clock.monotonic(), []
                while clock.monotonic() - dwell_started < hold:
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
                    reason = (f"output unsettled (span {span:.3f} V) during an expected-off-permitted level; "
                              "state not classified")
                    accepted = []
                else:
                    qualification = "valid"
                    reason = (f"output {state} at {target:g} V ({kind} level): "
                              + ("expected-off phase, recorded as a state, not a fault"
                                 if off_expected else "normal-range phase; minimum-output rule applied")
                              + "; uncertainty unquantified")
                observation = level_observation(kind, state, previous_state, off_expected)
                point.update(qualification=qualification, reason=reason, output_state=state, observation=observation,
                             output_off_expected=off_expected, minimum_vout_rule_applied=not off_expected,
                             load_current_established=abs(means["Iout_A"] - load) <= LOAD_CURRENT_TOLERANCE_A,
                             hold_s=hold, live_steps_from_previous_level=commanded,
                             acquisition_cycle_ids=accepted, settling_cycle_ids=settling_ids, settled=qualification == "valid",
                             settling_elapsed_s=acquisition_started - dwell_started,
                             acquisition_elapsed_s=ended - acquisition_started,
                             acquisition_start_monotonic_s=acquisition_started - ctx.began,
                             acquisition_end_monotonic_s=ended - ctx.began, maximum_interchannel_skew_s=skew_max,
                             procedure_stage=self.stage, accepted_means=means)
                detail["levels"].append({"point_id": point["point_id"], "vin_target_V": target, "level_kind": kind,
                                         "output_state": state, "observation": observation,
                                         "output_off_expected": off_expected, "qualification": qualification, "hold_s": hold})
                ctx.store.append("points", {**point, "event": "point_finalized", "monotonic_s": ended - ctx.began})
                checkpoint()
                ctx.set_active(None)
                if state is not None:
                    previous_state = state
            self.stage = "de-energize"
            ctx.de_energize()
            ctx.event("de_energized", test_id=test.id, source_output="OFF", load_input="OFF")
            detail["completed"] = True
            checkpoint()
        self.stage = "completed"


def run_supply_profile_mock(plan: Plan, out: Path, *, seed: int = 1, synthetic: SyntheticUvlo | None = None,
                            reading_override: ReadingOverride | None = None, operator_observations: list[str] | None = None,
                            attachment_descriptors: list[dict] | None = None) -> Path:
    """Execute an ISO 16750-2 supply profile against the synthetic plant; return the finalized run directory.

    Refuses real profiles, hash mismatches, other test types, a below-minimum
    profile without the approved UVLO-style authorization, and any
    non-executable level before anything is written. This function never
    creates or imports real instruments.
    """
    if plan.bench.mode != "mock":  # the bench decides; a legacy recipe mode is metadata
        raise ValueError("run_supply_profile_mock accepts mock profiles only; the ISO 16750-2 supply profiles are not yet "
                         "approved for real hardware")
    kind = plan.recipe.tests[0].type if plan.recipe.tests else "supply_profile"
    return run_phase_scoped_mock(plan, out, procedure_factory=SupplyProfileProcedure, method_key=METHOD_KEY,
                                 run_tag=RUN_TAGS.get(kind, "profile"), scenario=f"iso16750-2-{kind.replace('_', '-')}",
                                 authorization_note="explicit run_supply_profile_mock call under the recipe's authorization "
                                                    "block; never arms real equipment",
                                 seed=seed, synthetic=synthetic, reading_override=reading_override,
                                 operator_observations=operator_observations, attachment_descriptors=attachment_descriptors)


__all__ = ["METHOD_KEY", "ProtectiveLimitFault", "RegulationRuleStop", "SourceBoundaryStop", "SupplyProfileProcedure",
           "level_observation", "live_steps", "run_supply_profile_mock"]
