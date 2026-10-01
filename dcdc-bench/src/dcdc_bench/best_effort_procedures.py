"""Best-effort ISO 16750-2 procedures on the synthetic plant (mock only; proposal §6, owner decisions §8).

Four recipe test types share one phase-scoped procedure and the UVLO ramp's harness:

``transient_hold`` (4.3.1.2 jump start; 4.3.2 transient overvoltage as the same shape repeated)
    From the base level the source steps to ``level_V``, holds ``hold_s``, returns and rests
    ``recovery_s``; ``repeats`` times. No expected-off phase: a converter that shuts down at the
    level stops the run and the record says so.

``momentary_drop`` (4.6.1.1)
    Variant A: a LAN voltage step to ``drop_level_V`` for ``drop_s`` (100 ms commanded) and back.
    Variant B (the owner's default): the same drop timed by the supply's Timer in whole seconds.
    Output-off is expected during the drop and for ``recovery_s`` after the restore.

``micro_interruption`` (4.6.1.2) and ``line_interruption`` (4.9.1 method 1 / 4.9.2, positive line)
    Source output OFF for ``interruption_s`` then ON, recovery ``recovery_s``, ``repeats`` times.
    Whole-second interruptions may be timed by the supply's Delayer (exact to its clock); 100 ms uses
    two LAN writes. Output OFF is not a demonstrated open circuit; the sheet says so.

What is recorded (``run["method"]["best_effort"]``): the declared deviation sheet verbatim with an
``achieved`` block per row (host-clock intervals the Pi timestamps itself; ``measured_by: none`` for
every terminal-side quantity), every command's host-clock issue and acknowledgement instants, what
the polls saw (and that anything shorter than the poll interval is invisible to them), the plant's
hold-up model and the protective settings programmed first. The planner lists a hold or drop test as two points,
the base and the stimulus level (``input_voltage_targets_V`` as ``[base_V, level_V]`` or ``[from_V, drop_level_V]``):
a hold level long enough for the settling dwell plus an acquisition is acquired as a measured point; a shorter hold
or the expected-off drop level is finalized inconclusive with the reason stated. Approval gate (brief 7.5, proposal 4.4):
``authorization.best_effort_approved`` plus the accepted deviation sheet's hash; levels below the
DUT minimum (0 V during an interruption, a drop level) also need the UVLO-style approval.

Everything here runs against the synthetic plant with a virtual clock. The real bench refuses these
test types; no real procedure exists in this release.
"""
from __future__ import annotations

import math
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
from typing import Any, Callable

from .adapters import INSTRUMENT_TIMING_PARAMETERS, READBACK_MODEL_PARAMETERS, HoldUpModel, ReadbackModel, StartupModel
from .domain import BestEffortPolicy, DeviationSheet, Plan, TestDefinition, TestRecipe
from .mock_uvlo import SyntheticUvlo, UvloMockBench
from .planning import (MOCK_DEADLINE_FIXED_S, MOCK_DEADLINE_SECONDS_PER_RECORD, MOCK_ESTIMATE_FIXED_S,
                       MOCK_ESTIMATE_SECONDS_PER_RECORD, MOCK_RUN_BUDGET_S, REQUIRED_MEASUREMENTS,
                       best_effort_approval_gaps as planner_approval_gaps, recipe_deviations_sha256, uvlo_approval_gaps,
                       verify_plan_hash)
from .runner import OUTPUT_IN_BAND_FRACTION, STARTUP_CYCLES, STARTUP_FAILURE_REASON, STARTUP_INTERVAL_S
from .storage import atomic_json
from .uvlo import (LOAD_CURRENT_TOLERANCE_A, ProtectiveLimitFault, ReadingOverride, RegulationRuleStop, SourceBoundaryStop,
                   UvloInputRampProcedure, absolute_limits, run_phase_scoped_mock)

TRANSIENT_HOLD_TEST_TYPE = "transient_hold"
MOMENTARY_DROP_TEST_TYPE = "momentary_drop"
MICRO_INTERRUPTION_TEST_TYPE = "micro_interruption"
LINE_INTERRUPTION_TEST_TYPE = "line_interruption"
BEST_EFFORT_TEST_TYPES = (TRANSIENT_HOLD_TEST_TYPE, MOMENTARY_DROP_TEST_TYPE, MICRO_INTERRUPTION_TEST_TYPE,
                          LINE_INTERRUPTION_TEST_TYPE)
INTERRUPTION_TEST_TYPES = (MICRO_INTERRUPTION_TEST_TYPE, LINE_INTERRUPTION_TEST_TYPE)
METHOD_KEY = "best_effort"
LAN_MECHANISMS = ("lan_voltage_step", "lan_output_off")
INSTRUMENT_MECHANISMS = ("supply_timer", "supply_delayer")
STIMULUS: dict[str, dict[str, Any]] = {
    TRANSIENT_HOLD_TEST_TYPE: {"label": "transient hold (clause 4.3.1.2 jump start / 4.3.2 shape)", "mechanisms": ("lan_voltage_step", "supply_timer"),
                               "needs": ("level_V", "hold_s"), "active": "hold_s", "level_kind": "hold", "off_expected": False},
    MOMENTARY_DROP_TEST_TYPE: {"label": "momentary drop (clause 4.6.1.1)", "mechanisms": ("lan_voltage_step", "supply_timer"),
                               "needs": ("drop_level_V", "drop_s"), "active": "drop_s", "level_kind": "drop", "off_expected": True},
    MICRO_INTERRUPTION_TEST_TYPE: {"label": "micro interruption (clause 4.6.1.2)", "mechanisms": ("lan_output_off", "supply_delayer"),
                                   "needs": ("interruption_s",), "active": "interruption_s", "level_kind": "interruption", "off_expected": True},
    LINE_INTERRUPTION_TEST_TYPE: {"label": "line interruption (clause 4.9.1 method 1 / 4.9.2, positive line)",
                                  "mechanisms": ("lan_output_off", "supply_delayer"), "needs": ("interruption_s",),
                                  "active": "interruption_s", "level_kind": "interruption", "off_expected": True},
}
RUN_TAGS = {TRANSIENT_HOLD_TEST_TYPE: "hold", MOMENTARY_DROP_TEST_TYPE: "drop", MICRO_INTERRUPTION_TEST_TYPE: "microint",
            LINE_INTERRUPTION_TEST_TYPE: "lineint"}
# Project conventions reused here (sources named so the record can be traced):
ENDPOINT_MARGIN_V = 0.2            # endpoint margin below the DUT maximum (35.8 V against 36 V) unless program_clause_level_exactly
OVP_HEADROOM_V = 2.0               # source OVP above the top level; wider than the DP800 OVP accuracy band (0.5 % + 0.5 V) below 40 V
OCP_HEADROOM_A = 0.05              # source OCP above the current limit (1.0 A / 1.05 A as the existing procedures program)
DEFAULT_PROGRAM_BOUND_S = 720.0    # the real path's one-shot source timer bound when no per-recipe bound is approved (owner decision 1)
INSTRUMENT_SCHEDULE_TOLERANCE_S = 0.118 + 0.055   # program start uncertainty: command processing (DS5) + LAN transport (LAN)
MINIMUM_LAN_INTERVAL_S = 0.1       # the honest floor: shorter LAN-timed intervals are not offered (proposal §3, 4.6.1.2 note)
PRE_GROUP_S = 1                    # first program group: the base level held one whole second before the first stimulus
OUTPUT_OFF_FRACTION = 0.1          # accepted Vout mean at/below this fraction of nominal is "off"; in band at/above OUTPUT_IN_BAND_FRACTION
LAN_ROUND_TRIPS = {"set_voltage_live": 5, "output_off": 3, "output_on": 3, "program_start": 3, "program_group": 1}  # DRV
HOST_CLOCK_DIGITS = 6             # host-clock intervals are recorded to the microsecond (the Pi's monotonic clock has no better resolution)
HOST_INTERVAL_NOTE = ("host-clock interval between the two commands' issue instants (write to write); the terminal-side interval "
                      "additionally carries each command's LAN transport and the supply's processing time, which the host does "
                      "not observe")
TERMINAL_NOTE = ("terminal-side quantity: commanded, not measured on this bench (the supply readback refreshes about once per "
                 "second; no scope or DAQ channel is bound)")
INSTRUMENT_NOTE = ("instrument-timed group (whole seconds, exact to the supply's own clock per the programming guide; sub-second "
                   "acceptance and the boundary error unverified, bench check B1); the host timestamps only the program start")
POLL_NOTE = "Observed output states come from polling at the recipe's interval; states shorter than the poll interval are not visible to this bench."
_PARAMETER_ALIASES = {
    "hold": "hold_s", "hold_time": "hold_s", "t_hold": "hold_s", "level_hold": "hold_s", "plateau": "hold_s",
    "interruption": "interruption_s", "interruption_time": "interruption_s", "t_interruption": "interruption_s",
    "open_time": "interruption_s", "t_open": "interruption_s", "interrupt": "interruption_s",
    "drop": "drop_s", "drop_time": "drop_s", "drop_duration": "drop_s", "t_drop": "drop_s", "pulse_width": "drop_s",
    "pulse_duration": "drop_s", "pulse": "drop_s",
    "recovery": "recovery_s", "recovery_time": "recovery_s", "t_recovery": "recovery_s", "rest": "recovery_s",
    "rest_time": "recovery_s", "t_rest": "recovery_s", "pause": "recovery_s", "interval": "recovery_s",
    "repeats": "repeats", "repetitions": "repeats", "repeat": "repeats", "pulses": "repeats", "cycles": "repeats",
    "count": "repeats", "number_of_pulses": "repeats", "number_of_interruptions": "repeats",
}


# -- declared repeats and windows -----------------------------------------------------------------------
def _repeats(policy: BestEffortPolicy) -> int:
    """Declared repeats; one when the clause declares none (a single drop)."""
    return policy.repeats or 1


def _recovery_s(policy: BestEffortPolicy) -> float:
    """Declared rest or recovery window; zero when the clause declares none."""
    return float(policy.recovery_s or 0.0)


# -- hashes and approvals (the planner's functions: Preview and the worker apply one rule) --------------
def deviation_sheet_sha256(sheet: DeviationSheet) -> str:
    """Hash of one declared deviation sheet (canonical JSON, ``DeviationSheet.sha256``); any changed parameter or bound changes it."""
    return sheet.sha256()


def declared_deviations_sha256(recipe: TestRecipe) -> str:
    """The hash an approval must carry: the single sheet's hash, or ``planning.recipe_deviations_sha256`` over several tests."""
    digest = recipe_deviations_sha256(recipe)
    if digest is None:
        raise ValueError("The recipe declares no best_effort block")
    return digest


def best_effort_approval_gaps(bench: Any, recipe: TestRecipe) -> list[str]:
    """Why a best-effort recipe is refused (``planning.best_effort_approval_gaps``): the approval flag, the accepted sheet
    hash, the protective policy with its declared limits, and the per-phase bound where a phase exceeds the source timer."""
    return planner_approval_gaps(bench, recipe)


def stimulus_levels_V(test: TestDefinition) -> list[float]:
    """Source levels the stimulus visits besides the base: the hold level, the drop level, or 0 V for an interruption."""
    policy = test.best_effort
    if test.type == TRANSIENT_HOLD_TEST_TYPE:
        return [policy.level_V] if policy.level_V is not None else []
    if test.type == MOMENTARY_DROP_TEST_TYPE:
        return [policy.drop_level_V] if policy.drop_level_V is not None else []
    return [0.0]


def needs_uvlo_approval(dut: Any, test: TestDefinition) -> bool:
    """A stimulus below the DUT's stated minimum input takes the approved UVLO-style path (proposal §4.1)."""
    return any(level < dut.ratings.input_voltage_min_V for level in stimulus_levels_V(test))


# -- sequence and budget ---------------------------------------------------------------------------------
def _ceil_polls(duration_s: float, poll_s: float) -> int:
    return int((Decimal(str(duration_s)) / Decimal(str(poll_s))).to_integral_value(rounding=ROUND_CEILING))


def observation_window_s(recipe: TestRecipe) -> float:
    """Upper bound of one observation acquisition (duration or minimum cycles, plus a two-poll margin)."""
    acquisition = recipe.acquisition
    return max(acquisition.duration_s, acquisition.minimum_complete_cycles * acquisition.target_poll_interval_s) \
        + 2 * acquisition.target_poll_interval_s


def stimulus_plan(test: TestDefinition, recipe: TestRecipe) -> dict[str, Any]:
    """Durations of one test's stimulus sequence: per repeat and in total, LAN-timed or as instrument groups."""
    policy, spec = test.best_effort, STIMULUS[test.type]
    active_s = float(getattr(policy, spec["active"]))
    rest_s = float(_recovery_s(policy))
    observation_s = observation_window_s(recipe)
    instrument = policy.mechanism in INSTRUMENT_MECHANISMS
    if instrument:
        active_group = int(math.ceil(active_s))
        rest_group = int(math.ceil(rest_s + 2 * INSTRUMENT_SCHEDULE_TOLERANCE_S + observation_s))
        per_repeat = active_group + rest_group
        total = PRE_GROUP_S + _repeats(policy) * per_repeat
        groups = {"pre_group_s": PRE_GROUP_S, "active_group_s": active_group, "rest_group_s": rest_group}
    else:
        per_repeat = active_s + rest_s + observation_s
        total = _repeats(policy) * per_repeat
        groups = {}
    return {"mechanism": policy.mechanism, "instrument_timed": instrument, "active_s": active_s, "rest_s": rest_s,
            "observation_window_s": observation_s, "repeats": _repeats(policy), "per_repeat_s": per_repeat,
            "stimulus_total_s": total, **groups}


def program_bound_s(recipe: TestRecipe) -> float:
    bound = getattr(recipe.authorization, "instrument_timed_bound_s", None)
    return float(bound) if bound is not None else DEFAULT_PROGRAM_BOUND_S


def best_effort_mock_estimate(plan: Plan) -> dict[str, Any]:
    """Record count and wall-time estimate of the simulated best-effort run against the shared mock budget."""
    recipe = plan.recipe
    poll = recipe.acquisition.target_poll_interval_s
    acquisition = max(_ceil_polls(recipe.acquisition.duration_s, poll), recipe.acquisition.minimum_complete_cycles)
    cycles = commands = levels = repeats_total = 0
    for test in recipe.tests:
        plan_ = stimulus_plan(test, recipe)
        repeats, spec = plan_["repeats"], STIMULUS[test.type]
        levels += len(test.input_voltage_targets_V)
        repeats_total += repeats
        cycles += STARTUP_CYCLES + _ceil_polls(recipe.settling.minimum_dwell_s, poll) + acquisition
        cycles += _ceil_polls(plan_["stimulus_total_s"] + 2 * INSTRUMENT_SCHEDULE_TOLERANCE_S, poll) + repeats * acquisition + 2
        if (len(test.input_voltage_targets_V) == 2 and not spec["off_expected"]
                and plan_["active_s"] >= recipe.settling.minimum_dwell_s + observation_window_s(recipe)):
            cycles += repeats * acquisition  # the settled acquisition at the hold level, once per repeat
        commands += 2 * repeats + 4
    records = len(REQUIRED_MEASUREMENTS) * cycles + commands + 2 * levels + 12 * len(recipe.tests)
    deadline = MOCK_DEADLINE_FIXED_S + MOCK_DEADLINE_SECONDS_PER_RECORD * records
    typical = MOCK_ESTIMATE_FIXED_S + MOCK_ESTIMATE_SECONDS_PER_RECORD * records
    within = deadline <= MOCK_RUN_BUDGET_S
    reason = None if within else (
        f"the simulated best-effort run would write about {records} fsync'd records; its worst-case deadline {deadline:.0f} s "
        f"exceeds the {MOCK_RUN_BUDGET_S:.0f} s simulated-run budget (RuntimeMaxSec 2700 s minus margin); increase the poll "
        "interval, shorten the holds or the recovery windows, or reduce the repeats")
    return {"records": records, "cycles": cycles, "declared_repeats": repeats_total, "observation_levels": levels,
            "typical_s": typical, "deadline_s": deadline, "budget_s": MOCK_RUN_BUDGET_S, "within_budget": within, "reason": reason}


def host_interval(first: dict[str, Any], second: dict[str, Any]) -> float:
    """Write-to-write host-clock interval between two command records, to the microsecond."""
    return round(second["commanded_at_s"] - first["commanded_at_s"], HOST_CLOCK_DIGITS)


def _parameter_key(name: str, kind: str) -> str | None:
    """Map a sheet row's parameter name onto the quantity the host can time, or None for a terminal-side row."""
    normalised = name.strip().lower().replace("-", "_").replace(" ", "_")
    for suffix in ("_seconds", "_sec", "_ms", "_s"):
        if normalised.endswith(suffix) and normalised[:-len(suffix)] in _PARAMETER_ALIASES:
            normalised = normalised[:-len(suffix)]
            break
    if normalised in ("hold_s", "interruption_s", "drop_s", "recovery_s", "repeats"):
        return normalised
    if normalised in ("duration", "duration_s", "time", "t", "t_active", "active_time", "pulse", "pulse_width", "pulse_duration"):
        return STIMULUS[kind]["active"]  # a 4.3.2 pulse is the hold of a transient_hold, a 4.6.1.1 pulse the drop
    return _PARAMETER_ALIASES.get(normalised)


def _voltage_key(name: str) -> str | None:
    """Map a sheet row's parameter onto the level the supply readback observes: ``level`` (hold or drop) or ``base``."""
    normalised = name.strip().lower().replace("-", "_").replace(" ", "_")
    if normalised.endswith("_v"):
        normalised = normalised[:-2]
    if normalised in ("level", "hold_level", "drop_level", "overvoltage_level", "jump_start_level", "stimulus_level", "pulse_level"):
        return "level"
    if normalised in ("base", "start", "from", "base_level", "start_level", "supply", "nominal"):
        return "base"
    return None


class BestEffortProcedure(UvloInputRampProcedure):
    """Plan-driven best-effort ISO 16750-2 stimulus. Construction refuses anything not approved (brief 7.5, proposal 4.4).

    Reuses the UVLO ramp's bookkeeping and plan snapshot; the guard is its own
    (a commanded source-output OFF is accepted only inside the commanded or
    predicted interruption window; absolute limits always apply).
    """

    adapter = UvloMockBench

    def __init__(self, plan: Plan):  # noqa: D107 - the base initialiser is UVLO-specific; the checks here replace it
        if not verify_plan_hash(plan):
            raise ValueError("Plan hash mismatch; regenerate the plan after changing any settings")
        tests = plan.recipe.tests
        types = {test.type for test in tests}
        if (not tests or len(types) != 1 or not types <= set(BEST_EFFORT_TEST_TYPES)
                or any(getattr(test, "best_effort", None) is None for test in tests)):
            raise ValueError("BestEffortProcedure executes one best-effort test type (transient_hold, momentary_drop, "
                             "micro_interruption or line_interruption) with a declared best_effort block only")
        kind = tests[0].type
        if plan.bench.mode != "mock":
            raise ValueError(f"{kind} is not approved for real hardware; the best-effort procedure exists on the synthetic plant only")
        gaps = best_effort_approval_gaps(plan.bench, plan.recipe)
        if gaps:
            raise ValueError("Best-effort ISO 16750-2 procedure refused (approval gate, brief 7.5 / proposal 4.4): " + "; ".join(gaps))
        if any(needs_uvlo_approval(plan.dut, test) for test in tests):
            uvlo_gaps = uvlo_approval_gaps(plan.bench, plan.recipe)
            if uvlo_gaps:
                raise ValueError("Best-effort stimulus reaches below the DUT's stated minimum input (0 V during an interruption, "
                                 "or the drop level) and takes the approved UVLO-style path (brief 7.5); refused: " + "; ".join(uvlo_gaps))
        self.limits = absolute_limits(plan)
        for test in tests:
            self._validate_stimulus(plan, test)
        blocked = [point for point in plan.points if point.status != "executable"]
        if blocked:
            raise ValueError(f"Best-effort procedure refused: {len(blocked)} declared point(s) are not executable and a stimulus is "
                             f"never run with its base level skipped or clipped. First: {blocked[0].point_id} — {blocked[0].reason}")
        self.estimate = best_effort_mock_estimate(plan)
        if not self.estimate["within_budget"]:
            raise ValueError("Simulated run refused: " + self.estimate["reason"])
        self.snapshot = plan.model_copy(deep=True)
        self.kind = kind
        self.stage = "idle"
        self.policy = None
        self.step: dict[str, Any] | None = None
        self.acquiring = False
        nominal = plan.dut.ratings.output_voltage_nominal_V
        self.on_minimum_V = round(OUTPUT_IN_BAND_FRACTION * nominal, 6)
        self.off_maximum_V = round(OUTPUT_OFF_FRACTION * nominal, 6)
        self.programmed = {test.id: self._programmed_settings(plan, test) for test in tests}
        self.plant_record: dict[str, Any] | None = None

    # -- construction-time checks ---------------------------------------------------------------------
    def _validate_stimulus(self, plan: Plan, test: TestDefinition) -> None:
        policy, spec, kind = test.best_effort, STIMULUS[test.type], test.type
        expected = 2 if kind in (TRANSIENT_HOLD_TEST_TYPE, MOMENTARY_DROP_TEST_TYPE) else 1
        if len(test.input_voltage_targets_V) != expected or len(test.output_current_targets_A) != 1:
            shape = ("[base_V, level_V]" if kind == TRANSIENT_HOLD_TEST_TYPE else "[from_V, drop_level_V]"
                     if kind == MOMENTARY_DROP_TEST_TYPE else "[base_V]")
            raise ValueError(f"{kind} declares input_voltage_targets_V as {shape} and one load; the timings live in best_effort")
        if policy.mechanism not in spec["mechanisms"]:
            if policy.mechanism == "switch_box":
                raise ValueError(f"{kind} by switch_box needs the series switch box, which this bench does not have (design pending); "
                                 f"this bench offers {', '.join(spec['mechanisms'])}")
            raise ValueError(f"{kind} cannot be realised by {policy.mechanism!r} on this bench; it offers {', '.join(spec['mechanisms'])}")
        missing = [field for field in spec["needs"] if getattr(policy, field) is None]
        if missing:
            raise ValueError(f"{kind} requires best_effort.{', best_effort.'.join(missing)}")
        active = float(getattr(policy, spec["active"]))
        if policy.mechanism in INSTRUMENT_MECHANISMS:
            limits = INSTRUMENT_TIMING_PARAMETERS["group_seconds"]
            for name, value in ((spec["active"], active),):
                if value != int(value) or not limits["min"] <= value <= limits["max"]:
                    raise ValueError(f"{policy.mechanism} times {name} in whole seconds ({limits['min']} s to {limits['max']} s); "
                                     f"{value:g} s is not representable (use a LAN mechanism for sub-second intervals)")
        elif active < MINIMUM_LAN_INTERVAL_S:
            raise ValueError(f"LAN-timed intervals below {MINIMUM_LAN_INTERVAL_S:g} s are not offered: two LAN writes cannot be spaced "
                             "reliably below the recorded round-trip spread, and nothing here measures the result")
        base, ratings = test.input_voltage_targets_V[0], plan.dut.ratings
        if kind == TRANSIENT_HOLD_TEST_TYPE:
            if policy.level_V == base:
                raise ValueError("transient_hold needs a hold level different from the base level")
            top = max(base, policy.level_V)
            exact = getattr(plan.recipe.authorization, "program_clause_level_exactly", False)
            if top > ratings.input_voltage_max_V:
                raise ValueError(f"Hold level {top:g} V exceeds the DUT maximum input {ratings.input_voltage_max_V:g} V; request retained without clipping")
            if not exact and top > ratings.input_voltage_max_V - ENDPOINT_MARGIN_V:
                raise ValueError(f"Hold level {top:g} V is within the {ENDPOINT_MARGIN_V:g} V endpoint margin of the DUT maximum; "
                                 "declare authorization.program_clause_level_exactly to program the clause level there (owner decision 6)")
            if top > self.limits["input_voltage_V"]:
                raise ValueError(f"Hold level {top:g} V exceeds the absolute input-voltage limit {self.limits['input_voltage_V']:g} V "
                                 f"({self.limits['input_voltage_ceiling_source']}); a reviewed protective policy with a higher guard is needed first")
            if top + OVP_HEADROOM_V > (plan.bench.source.max_voltage_V or math.inf):
                raise ValueError("The source OVP for this hold level would exceed the source's voltage capability")
        elif kind == MOMENTARY_DROP_TEST_TYPE and policy.drop_level_V >= base:
            raise ValueError("momentary_drop needs a drop level below the base level")
        total = stimulus_plan(test, plan.recipe)["stimulus_total_s"] + STARTUP_CYCLES * STARTUP_INTERVAL_S \
            + plan.recipe.settling.minimum_dwell_s + observation_window_s(plan.recipe)
        bound = program_bound_s(plan.recipe)
        if total > bound:
            raise ValueError(f"The {kind} sequence needs about {total:.0f} s, above the {bound:.0f} s bound in force; declare a longer "
                             "authorization.instrument_timed_bound_s for this recipe (owner decision 1) or shorten it")

    def _programmed_settings(self, plan: Plan, test: TestDefinition) -> dict[str, Any]:
        controls, policy = plan.bench.protective_controls, test.best_effort
        base = test.input_voltage_targets_V[0]
        top = max(base, policy.level_V) if test.type == TRANSIENT_HOLD_TEST_TYPE else base
        limit = controls.source_current_limit_A or plan.bench.source.max_current_A
        return {"source_voltage_setpoint_V": base, "top_level_V": top,
                "program_clause_level_exactly": bool(getattr(plan.recipe.authorization, "program_clause_level_exactly", False)),
                "endpoint_margin_V": ENDPOINT_MARGIN_V, "source_current_limit_A": limit, "source_ocp_A": limit + OCP_HEADROOM_A,
                "source_ovp_V": top + OVP_HEADROOM_V, "load_voltage_limit_V": controls.dut_output_overvoltage_V,
                "load_current_limit_A": controls.output_overcurrent_A,
                "order": "identity, outputs verified OFF, protections programmed and read back, source ON, source-only startup gate, "
                         "load ON, stimulus; absolute limits at every poll (brief §7, proposal §4)",
                "note": "mock: recorded, nothing is energised; the real path writes and reads these back before enabling the source"}

    # -- contract surface -------------------------------------------------------------------------
    def metadata(self) -> dict[str, Any]:
        recipe = self.snapshot.recipe
        tests: dict[str, Any] = {}
        for test in recipe.tests:
            policy = test.best_effort
            sheet = policy.deviation_sheet
            tests[test.id] = {
                "test_id": test.id, "clause": policy.clause, "variant": policy.variant, "mechanism": policy.mechanism,
                "base_V": test.input_voltage_targets_V[0], "load_A": test.output_current_targets_A[0],
                "stimulus": policy.model_dump(mode="json", exclude={"deviation_sheet"}),
                "sequence": stimulus_plan(test, recipe), "programmed": self.programmed[test.id],
                "declared_sheet_sha256": deviation_sheet_sha256(sheet),
                "deviations": [{**entry.model_dump(mode="json"), "achieved": self._achieved_default(entry)} for entry in sheet.entries],
                "statement": sheet.statement, "commands": [], "repeats": [], "startup": None, "baseline": None, "completed": False,
                **({"line": "positive line only (source output OFF); the return line cannot be opened on this bench"}
                   if test.type == LINE_INTERRUPTION_TEST_TYPE else {})}
        first = recipe.tests[0].best_effort
        authorization = recipe.authorization
        spec = STIMULUS[self.kind]
        poll = recipe.acquisition.target_poll_interval_s
        limitations = [
            "ISO 16750-2 best-effort procedure: the stimulus is commanded over LAN or programmed into the supply and timed by the "
            "host clock; every terminal-side timing, edge and level transition is commanded, not measured (no scope or DAQ "
            "channel is bound in this bench profile).",
            POLL_NOTE.replace("the recipe's interval", f"a {poll:g} s interval"),
            "Source-terminal input voltage includes lead drop; the DUT-pin voltage during the stimulus is not measured.",
            "This procedure exists on the synthetic plant only. It is not approved for real hardware and no real execution "
            "context exists in this release."]
        if self.kind in INTERRUPTION_TEST_TYPES:
            limitations.insert(2, "Source output OFF stops the supply from sourcing; it is not a demonstrated >= 10 MOhm open and "
                                  "the OFF-state impedance of the supply is unverified.")
        for test in recipe.tests:
            for entry in test.best_effort.deviation_sheet.entries:
                if entry.classification in ("not_met_but_documented", "unknown_until_measured"):
                    limitations.append(f"Deviation sheet, ISO 16750-2 clause {test.best_effort.clause}, {entry.parameter}: "
                                       f"{entry.classification.replace('_', ' ')}" + (f" ({entry.note})" if entry.note else "") + ".")
        method = {
            "type": self.kind, "test_type": self.kind, "clause": first.clause, "variant": first.variant,
            "variants": [test.best_effort.variant for test in recipe.tests], "policy_id": authorization.protective_policy_id,
            "approval": {"best_effort_approved": bool(getattr(authorization, "best_effort_approved", False)),
                         "accepted_deviations_sha256": getattr(authorization, "accepted_deviations_sha256", None),
                         "declared_deviations_sha256": declared_deviations_sha256(recipe),
                         "uvlo_approved": authorization.uvlo_approved,
                         "uvlo_style_path_required": any(needs_uvlo_approval(self.snapshot.dut, test) for test in recipe.tests),
                         "instrument_timed_bound_s": program_bound_s(recipe),
                         "bound_declared_by_recipe": getattr(authorization, "instrument_timed_bound_s", None) is not None,
                         "program_clause_level_exactly": bool(getattr(authorization, "program_clause_level_exactly", False))},
            "deviations": [], "statement": "", "tests": tests,
            "conventions": {"output_on_minimum_V": self.on_minimum_V, "output_off_maximum_V": self.off_maximum_V,
                            "classification": "accepted Vout mean at/above output_on_minimum_V is on, at/below output_off_maximum_V is off, "
                                              "between is indeterminate (fractions of the DUT nominal output, as the sweep runner's gate)",
                            "startup_gate": {"source_only_cycles": STARTUP_CYCLES, "interval_s": STARTUP_INTERVAL_S,
                                             "lower_output_V": self.on_minimum_V, "load_enabled_only_after_gate": True},
                            "poll_interval_s": poll, "observation": "after each recovery window: settling-bound acquisition, state classified",
                            "expected_off": ("none: the converter must stay in band at the level and after the return"
                                             if not spec["off_expected"] else
                                             "during the commanded stimulus and for recovery_s after the restore or ON command: "
                                             "output-off is recorded, not faulted; afterwards the minimum-output rule applies"),
                            "uncommanded_off": "a source output OFF outside the commanded or schedule-predicted window stops the run",
                            "instrument_schedule_tolerance_s": INSTRUMENT_SCHEDULE_TOLERANCE_S},
            "host_clock": {"mode": "virtual", "note": "command instants are the mock's virtual monotonic clock; on the real path they "
                                                      "would be the Pi's monotonic clock around each write and its acknowledgement"},
            "guard": {"absolute_limits_every_poll": self.limits,
                      "scoped_to_normal_phase": [
                          "output voltage at or above output_on_minimum_V (every poll outside the expected-off window)",
                          f"requested load current established within {LOAD_CURRENT_TOLERANCE_A:g} A (observation cycles)"],
                      "always": ["finite readings", "absolute limits", "source in CV, or OFF only inside the commanded window",
                                 "interchannel skew within the recipe bound"]},
            "run_budget": {key: self.estimate[key] for key in ("records", "typical_s", "deadline_s", "budget_s")},
            "plant": self.plant_record, "synthetic_model": None}
        self._refresh_deviations(method)
        return {"scenario": f"ISO 16750-2 best-effort {spec['label']} on the synthetic plant (deviations recorded)",
                "executed_point_ids": [],
                "authorization": (f"recipe authorization.best_effort_approved with the accepted deviation sheet under protective policy "
                                  f"{authorization.protective_policy_id}; mock execution never energizes equipment"),
                "method": {METHOD_KEY: method}, "metrology_limitations": limitations}

    def begin_test(self, test: TestDefinition) -> None:
        if test.type not in BEST_EFFORT_TEST_TYPES or getattr(test, "best_effort", None) is None:
            raise ValueError("begin_test requires a best-effort test")
        self.policy, self.step = test.best_effort, None

    def begin_step(self, vin_target_V: float, level_kind: str, *, off_expected: bool = False,  # type: ignore[override]
                   interruption_commanded: bool = False) -> None:
        if self.policy is None:
            raise RuntimeError("begin_step requires an active test policy")
        self.step = {"vin_target_V": vin_target_V, "level_kind": level_kind, "ramp_phase": None,
                     "output_off_expected": off_expected, "interruption_commanded": interruption_commanded}
        self.acquiring = False

    def classify_output(self, vout_V: float | None) -> str | None:
        if vout_V is None:
            return None
        if vout_V >= self.on_minimum_V:
            return "on"
        if vout_V <= self.off_maximum_V:
            return "off"
        return "indeterminate"

    def guard(self, values: dict[str, float], requested: float, *, loaded: bool = True, startup: bool = False,
              mode_before: str = "CV", mode_after: str = "CV") -> None:
        """Absolute limits first and always; a source OFF only inside the commanded window; normal rules only where output-off is not expected."""
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
        commanded_off = bool(self.step and self.step.get("interruption_commanded"))
        for mode in (mode_before, mode_after):
            if mode == "OFF" and not commanded_off:
                raise SourceBoundaryStop("Source output OFF outside the commanded interruption window; the stimulus was not "
                                         "produced as commanded", values=values)
            if mode not in ("CV", "OFF"):
                raise SourceBoundaryStop("Source left CV regulation; the requested input condition was not achieved", values=values)
        if startup:
            return  # bounded startup gate: no steady-state minimum-output check yet (brief 7.3)
        if self.policy is None or self.step is None:
            raise RuntimeError("guard requires an active test policy and step")
        if self.step["output_off_expected"]:
            return  # expected-off window: normal regulation rules are scoped out; absolute limits already applied
        if values["Vout_V"] < self.on_minimum_V:
            raise RegulationRuleStop(f"Output {values['Vout_V']:.3f} V is below the {self.on_minimum_V:g} V minimum outside the "
                                     f"expected-off window ({self.step['level_kind']}); cause unclassified", values=values)
        if loaded and self.acquiring and abs(values["Iout_A"] - requested) > limits["load_current_tolerance_A"]:
            raise RegulationRuleStop(f"Requested load {requested:g} A was not established outside the expected-off window", values=values)

    # -- the deviation sheet's achieved column ------------------------------------------------------
    @staticmethod
    def _achieved_default(entry: Any) -> dict[str, Any]:
        measured_by = getattr(entry, "measured_by", None) if not isinstance(entry, dict) else entry.get("measured_by")
        note = TERMINAL_NOTE if measured_by != "scope" else "no scope or DAQ channel is bound in this bench profile; " + TERMINAL_NOTE
        return {"value": None, "measured_by": "none", "note": note}

    @staticmethod
    def _readback_level(detail: dict[str, Any], which: str) -> dict[str, Any]:
        """Source-terminal readback of a level the sheet marks ``supply_readback``: the stimulus level from the polls inside
        the window(s), the base from the baseline and the observations; never the DUT-pin voltage."""
        if which == "level":
            means = [r["polls_during_stimulus"]["Vin_mean_V"] for r in detail["repeats"] if r["polls_during_stimulus"]["cycles"]]
            where = "inside the stimulus window(s)"
        else:
            means = [r["observation"]["means"]["Vin_V"] for r in detail["repeats"]]
            if detail.get("baseline"):
                means.insert(0, detail["baseline"]["means"]["Vin_V"])
            where = "at the base level (the baseline and the observation after each window)"
        if not means:
            return {"value": None, "measured_by": "none",
                    "note": "no poll fell inside the stimulus window at the poll interval; the level is commanded, not observed"}
        return {"value": mean(means), "min": min(means), "max": max(means), "measured_by": "supply_readback",
                "note": f"source-terminal readback mean of the polls {where} (about 1 s refresh); lead drop not subtracted, "
                        "not the DUT-pin voltage"}

    def _refresh_deviations(self, method: dict[str, Any]) -> None:
        combined, statements = [], []
        for test in self.snapshot.recipe.tests:
            detail = method["tests"][test.id]
            policy = test.best_effort
            instrument = policy.mechanism in INSTRUMENT_MECHANISMS
            intervals: dict[str, list[float]] = {}
            for repeat in detail["repeats"]:
                for key, value in (repeat.get("intervals_host_s") or {}).items():
                    if value is not None:
                        intervals.setdefault(key, []).append(value)
            for entry in detail["deviations"]:
                key = _parameter_key(entry["parameter"], test.type)
                if key == "repeats" and detail["repeats"]:
                    achieved = {"value": len(detail["repeats"]), "measured_by": "host_clock",
                                "note": f"repeats completed, counted by the host ({_repeats(policy)} declared)"}
                elif key is not None and instrument and detail["repeats"]:
                    programmed = detail["sequence"]["active_group_s"] if key == STIMULUS[test.type]["active"] else _recovery_s(policy)
                    achieved = {"value": None, "measured_by": "none", "programmed": programmed, "note": INSTRUMENT_NOTE}
                elif key is not None and intervals.get(key):
                    values = intervals[key]
                    achieved = {"value": mean(values), "min": min(values), "max": max(values), "values": list(values),
                                "measured_by": "host_clock", "note": HOST_INTERVAL_NOTE}
                elif key is None and entry.get("measured_by") == "supply_readback" and _voltage_key(entry["parameter"]) is not None:
                    achieved = self._readback_level(detail, _voltage_key(entry["parameter"]))
                else:
                    achieved = self._achieved_default(entry)
                entry["achieved"] = achieved
                combined.append({**entry, "test_id": test.id})
            statements.append(detail["statement"] if len(self.snapshot.recipe.tests) == 1
                              else f"{policy.variant or test.id}: {detail['statement']}")
        method["deviations"] = combined
        method["statement"] = " ".join(statements)

    def _finalize_level_point(self, ctx: Any, test: TestDefinition, level_point: dict[str, Any], detail: dict[str, Any],
                              spec: dict[str, Any], load: float) -> None:
        """Finalize the planner's second point of a hold or drop test: the stimulus level itself.

        A hold level that lasted the settling dwell plus an acquisition window in at least
        one repeat is a valid point with the accepted means of those acquisitions. A shorter
        hold, or the expected-off drop level, is inconclusive with the reason stated (its
        polls live in the stimulus record); it is never left as "not reached".
        """
        policy, recipe = test.best_effort, self.snapshot.recipe
        level = policy.level_V if test.type == TRANSIENT_HOLD_TEST_TYPE else policy.drop_level_V
        active_s = float(getattr(policy, spec["active"]))
        repeats = detail["repeats"]
        acquisitions = [r["level_acquisition"] for r in repeats if r.get("level_acquisition")]
        settled = [a for a in acquisitions if a["settled"]]
        common = {"output_off_expected": spec["off_expected"], "minimum_vout_rule_applied": not spec["off_expected"],
                  "procedure_stage": self.stage, "repeats_completed": len(repeats), "stimulus_level_V": level,
                  "settling_elapsed_s": recipe.settling.minimum_dwell_s if settled else None}
        if settled:
            cycle_ids = [cid for a in settled for cid in a["cycle_ids"]]
            means = {key: mean(a["means"][key] for a in settled) for key in settled[0]["means"]}
            state = self.classify_output(means["Vout_V"])
            level_point.update(
                qualification="valid", output_state=state,
                reason=(f"output {state} at the {level:g} V {spec['level_kind']} level: {len(settled)} settled acquisition(s) after the "
                        f"{recipe.settling.minimum_dwell_s:g} s dwell inside the {active_s:g} s window(s) ({policy.mechanism}); "
                        "minimum-output rule applied; the level is the source readback, terminal-side edges not measured; "
                        "uncertainty unquantified"),
                load_current_established=abs(means["Iout_A"] - load) <= LOAD_CURRENT_TOLERANCE_A,
                acquisition_cycle_ids=cycle_ids, settling_cycle_ids=[cid for a in settled for cid in a["settling_cycle_ids"]],
                settled=True, acquisition_elapsed_s=sum(a["ended_s"] - a["started_s"] for a in settled),
                acquisition_start_monotonic_s=settled[0]["started_s"] - ctx.began,
                acquisition_end_monotonic_s=settled[-1]["ended_s"] - ctx.began,
                maximum_interchannel_skew_s=max(a["skew_max_s"] for a in settled), accepted_means=means,
                acquisitions_at_level=len(settled), **common)
            ended = settled[-1]["ended_s"]
        else:
            polls = sum(r["polls_during_stimulus"]["cycles"] for r in repeats)
            if acquisitions:
                reason = (f"output unsettled at the {level:g} V {spec['level_kind']} level (span up to "
                          f"{max(a['span_V'] for a in acquisitions):.3f} V in {len(acquisitions)} acquisition(s) inside the window); "
                          "state not classified")
            elif spec["off_expected"]:
                reason = (f"{level:g} V {spec['level_kind']} level commanded for {len(repeats)} x {active_s:g} s with the converter expected "
                          f"off: no settled acquisition is taken there; {polls} poll(s) inside the window are in the stimulus record "
                          "(method.best_effort); the level is commanded, not measured")
            else:
                reason = (f"{level:g} V {spec['level_kind']} level commanded for {len(repeats)} x {active_s:g} s: shorter than the "
                          f"{recipe.settling.minimum_dwell_s:g} s settling dwell plus the {observation_window_s(recipe):g} s acquisition "
                          f"window, so no settled acquisition at the level; {polls} poll(s) inside the window are in the stimulus record "
                          "(method.best_effort); the level is commanded, not measured")
            level_point.update(qualification="inconclusive", output_state=None, reason=reason, acquisition_cycle_ids=[],
                               settling_cycle_ids=[], settled=False, **common)
            ended = ctx.clock.monotonic()
        ctx.store.append("points", {**level_point, "event": "point_finalized", "monotonic_s": ended - ctx.began})

    # -- execution against a context ---------------------------------------------------------------
    def execute(self, ctx: Any) -> None:
        run, clock, recipe = ctx.run, ctx.clock, self.snapshot.recipe
        bench, poll = ctx.bench, recipe.acquisition.target_poll_interval_s
        method = run["method"][METHOD_KEY]
        now = clock.monotonic

        def checkpoint() -> None:
            atomic_json(ctx.directory / "run.json", run)

        def poll_until(deadline: float, point: dict[str, Any], phase: str) -> tuple[list[str], list[tuple[float, dict[str, float]]]]:
            """Poll at the recipe cadence while a full interval fits, then sleep to the deadline exactly."""
            ids, readings = [], []
            while now() + poll <= deadline:
                clock.sleep(poll)
                cycle_id, values, _ = ctx.cycle(point, phase)
                ids.append(cycle_id)
                readings.append((now(), values))
            remaining = deadline - now()
            if remaining > 0:
                clock.sleep(remaining)
            return ids, readings

        def command(detail: dict[str, Any], name: str, action: Callable[[float, float], Any], *, round_trips: int, **extra: Any) -> dict[str, Any]:
            """One host-timestamped LAN write: pre-check queries, the write (effective after its transport), drain and readback."""
            pre_checks = 2 if name == "set_voltage_live" else 0
            for _ in range(pre_checks):
                clock.sleep(bench.query_round_trip_s())
            commanded_at = now()
            latency = bench.command_latency_s()
            action(commanded_at, commanded_at + latency)
            clock.sleep(latency)
            for _ in range(max(0, round_trips - pre_checks - 1)):
                clock.sleep(bench.query_round_trip_s())
            record = {"command": name, "commanded_at_s": commanded_at, "acknowledged_at_s": now(), "round_trips": round_trips,
                      "host_clock": "virtual monotonic", **extra}
            detail["commands"].append(record)
            ctx.event("command", test_id=detail["test_id"], **record)
            return record

        def acquire(point: dict[str, Any], phase: str = "acquiring", *, with_readings: bool = False) -> dict[str, Any]:
            started, accepted, readings, skew_max = now(), [], [], 0.
            self.acquiring = True
            while (now() - started < recipe.acquisition.duration_s or len(accepted) < recipe.acquisition.minimum_complete_cycles):
                cycle_id, values, skew = ctx.cycle(point, phase)
                accepted.append(cycle_id)
                readings.append((now(), values))
                skew_max = max(skew_max, skew)
                clock.sleep(poll)
            self.acquiring = False
            means = {key: mean(values[key] for _, values in readings) for key in readings[0][1]}
            span = max(values["Vout_V"] for _, values in readings) - min(values["Vout_V"] for _, values in readings)
            result = {"cycle_ids": accepted, "means": means, "span_V": span, "started_s": started, "ended_s": now(),
                      "skew_max_s": skew_max, "state": self.classify_output(means["Vout_V"])}
            if with_readings:
                result["readings"] = readings
            return result

        def active_window(deadline: float, phase: str, point: dict[str, Any], level_point: dict[str, Any] | None):
            """Poll a stimulus window at the recipe cadence, attributing the polls to the level point when the planner lists
            one. A hold level that lasts the settling dwell plus an acquisition window is also acquired there as a settled
            point; an expected-off level (a drop) is recorded by its polls only."""
            target = level_point if level_point is not None else point
            off_expected = bool((self.step or {}).get("output_off_expected"))
            if (level_point is None or off_expected
                    or deadline - now() < recipe.settling.minimum_dwell_s + observation_window_s(recipe)):
                ids, readings = poll_until(deadline, target, phase)
                return ids, readings, None
            settling_ids, settling_readings = poll_until(now() + recipe.settling.minimum_dwell_s, target, phase)
            acquisition = acquire(target, with_readings=True)
            acquired = acquisition.pop("readings")
            ids, readings = poll_until(deadline, target, phase)
            settled = acquisition["span_V"] <= recipe.settling.maximum_vout_span_V
            acquisition.update(settling_cycle_ids=settling_ids, settled=settled,
                               note=("settled acquisition at the stimulus level after the settling dwell" if settled else
                                     f"output span {acquisition['span_V']:.3f} V exceeded the settling bound at the stimulus level; "
                                     "not accepted"))
            return settling_ids + acquisition["cycle_ids"] + ids, settling_readings + acquired + readings, acquisition

        def recovered_after(readings: list[tuple[float, dict[str, float]]], since: float) -> float | None:
            for at, values in readings:
                if values["Vout_V"] >= self.on_minimum_V:
                    return at - since
            return None

        def plant_truth(before: int) -> dict[str, Any]:
            transitions = list(bench.uvlo.transitions[before:])
            return {"uvlo_transitions": transitions, "tripped": any(t["to"] == "off" for t in transitions),
                    "restarted": any(t["to"] == "on" for t in transitions),
                    "label": "what the synthetic plant did; no instrument on this bench observes it"}

        helpers = SimpleNamespace(poll_until=poll_until, command=command, acquire=acquire, recovered_after=recovered_after,
                                  plant_truth=plant_truth, checkpoint=checkpoint, active_window=active_window, level_point=None)
        for test in recipe.tests:
            self.begin_test(test)
            policy, spec = test.best_effort, STIMULUS[test.type]
            load, base = test.output_current_targets_A[0], test.input_voltage_targets_V[0]
            points = [p for p in run["points"] if p["test_id"] == test.id]
            point, level_point = points[0], (points[1] if len(points) > 1 else None)
            detail = method["tests"][test.id]
            detail.update(startup=None, baseline=None, repeats=[], commands=[], completed=False)
            point["level_kind"], point["ramp_phase"] = "base", None
            self.record_attempt(run, point)
            if level_point is not None:  # the hold or drop level the planner lists as the test's second point
                level_point["level_kind"], level_point["ramp_phase"] = spec["level_kind"], None
                self.record_attempt(run, level_point)
            helpers.level_point = level_point
            ctx.set_active(point)
            self.begin_step(base, "startup")
            self.stage = "protective-settings"
            ctx.event("protections_programmed", test_id=test.id, **self.programmed[test.id])
            if policy.mechanism in INSTRUMENT_MECHANISMS:
                # The program's groups are written and read back before anything is energised; only its start needs the output ON.
                sequence = detail["sequence"]
                groups = 1 + 2 * _repeats(policy)
                for _ in range(groups * 2):
                    clock.sleep(bench.query_round_trip_s())
                ctx.event("program_written", test_id=test.id, mechanism=policy.mechanism, groups=groups, end_state="OFF",
                          pre_group_s=sequence["pre_group_s"], active_group_s=sequence["active_group_s"],
                          rest_group_s=sequence["rest_group_s"], total_s=sequence["stimulus_total_s"], written_at_s=now())
            checkpoint()
            self.stage = "unloaded-startup"
            ctx.energize(base, load)
            ctx.event("energized", test_id=test.id, point_id=point["point_id"], vin_target_V=base, requested_load_A=load,
                      load_input="OFF", procedure_stage=self.stage)
            gate_ids, values = [], None
            for _ in range(STARTUP_CYCLES):
                clock.sleep(STARTUP_INTERVAL_S)
                cycle_id, values, _ = ctx.cycle(point, "starting", loaded=False, startup=True)
                gate_ids.append(cycle_id)
            detail["startup"] = {"cycle_ids": gate_ids, "source_only_cycles": STARTUP_CYCLES, "interval_s": STARTUP_INTERVAL_S,
                                 "lower_output_V": self.on_minimum_V, "status": "output-on-before-load"}
            if values is None or values["Vout_V"] < self.on_minimum_V:
                detail["startup"]["status"] = "output-not-on"
                raise RegulationRuleStop(f"{STARTUP_FAILURE_REASON} (output below {self.on_minimum_V:g} V after {STARTUP_CYCLES} "
                                         "source-only startup cycles)", values=values)
            ctx.enable_load()
            ctx.event("load_enabled", test_id=test.id, requested_load_A=load)
            self.stage = "loaded-settling"
            self.begin_step(base, "base")
            settle_started = now()
            settling_ids, _ = poll_until(settle_started + recipe.settling.minimum_dwell_s, point, "settling")
            self.stage = "baseline"
            baseline = acquire(point)
            detail["baseline"] = {**baseline, "note": "the base level before the stimulus"}
            if baseline["state"] != "on":
                raise RegulationRuleStop(f"Output {baseline['means']['Vout_V']:.3f} V not in band at the {base:g} V base level before "
                                         "the stimulus; nothing was stimulated", values=baseline["means"])
            checkpoint()
            if policy.mechanism in INSTRUMENT_MECHANISMS:
                self._program_sequence(ctx, test, point, detail, helpers)
            else:
                self._lan_sequence(ctx, test, point, detail, helpers)
            last = detail["repeats"][-1]
            observation = last["observation"]
            repeats = len(detail["repeats"])
            point.update(qualification="valid", output_state=observation["state"],
                         reason=(f"output {observation['state']} at {base:g} V after {repeats} {spec['level_kind']} repeat(s) "
                                 f"({policy.mechanism}); host-clock command intervals recorded, terminal-side timings not measured; "
                                 "uncertainty unquantified"),
                         observation=last["observation_text"], output_off_expected=False, minimum_vout_rule_applied=True,
                         load_current_established=abs(observation["means"]["Iout_A"] - load) <= LOAD_CURRENT_TOLERANCE_A,
                         acquisition_cycle_ids=observation["cycle_ids"], settling_cycle_ids=settling_ids, settled=True,
                         settling_elapsed_s=baseline["started_s"] - settle_started,
                         acquisition_elapsed_s=observation["ended_s"] - observation["started_s"],
                         acquisition_start_monotonic_s=observation["started_s"] - ctx.began,
                         acquisition_end_monotonic_s=observation["ended_s"] - ctx.began,
                         maximum_interchannel_skew_s=observation["skew_max_s"], procedure_stage=self.stage,
                         accepted_means=observation["means"], baseline_means=baseline["means"], repeats_completed=repeats,
                         plant_tripped_any_repeat=any(r["plant_truth"]["tripped"] for r in detail["repeats"]))
            ctx.store.append("points", {**point, "event": "point_finalized", "monotonic_s": observation["ended_s"] - ctx.began})
            if level_point is not None:
                self._finalize_level_point(ctx, test, level_point, detail, spec, load)
            self.stage = "de-energize"
            ctx.de_energize()
            ctx.event("de_energized", test_id=test.id, source_output="OFF", load_input="OFF")
            detail["completed"] = True
            detail["synthetic_plant_truth"] = {"applied_transitions": list(bench.applied_transitions),
                                               "label": "effective instants of every live command inside the synthetic plant; "
                                                        "not observable on this bench"}
            self._refresh_deviations(method)
            checkpoint()
            ctx.set_active(None)
        self.stage = "completed"

    def _lan_sequence(self, ctx, test, point, detail, h: SimpleNamespace) -> None:
        bench, policy, spec = ctx.bench, test.best_effort, STIMULUS[test.type]
        poll_until, command, acquire, recovered_after, plant_truth, checkpoint = (h.poll_until, h.command, h.acquire, h.recovered_after,
                                                                                 h.plant_truth, h.checkpoint)
        base = test.input_voltage_targets_V[0]
        kind = test.type
        for index in range(_repeats(policy)):
            transitions_before = len(bench.uvlo.transitions)
            if kind == TRANSIENT_HOLD_TEST_TYPE:
                level = policy.level_V
                self.stage = "hold"
                self.begin_step(level, "hold")
                step = command(detail, "set_voltage_live", lambda c, e: bench.set_live_voltage(level, c, effective_at=e),
                               round_trips=LAN_ROUND_TRIPS["set_voltage_live"], to_V=level, repeat=index + 1)
                active_ids, active_readings, level_acquisition = h.active_window(step["commanded_at_s"] + policy.hold_s, "hold", point, h.level_point)
                back = command(detail, "set_voltage_live", lambda c, e: bench.set_live_voltage(base, c, effective_at=e),
                               round_trips=LAN_ROUND_TRIPS["set_voltage_live"], to_V=base, repeat=index + 1)
                self.stage = "rest"
                self.begin_step(base, "rest")
                window_ids, window_readings = poll_until(back["commanded_at_s"] + _recovery_s(policy), point, "rest")
                intervals = {"hold_s": host_interval(step, back)}
                first, second = step, back
            elif kind == MOMENTARY_DROP_TEST_TYPE:
                level = policy.drop_level_V
                self.stage = "drop"
                self.begin_step(level, "drop", off_expected=True)
                down = command(detail, "set_voltage_live", lambda c, e: bench.set_live_voltage(level, c, effective_at=e),
                               round_trips=LAN_ROUND_TRIPS["set_voltage_live"], to_V=level, repeat=index + 1)
                active_ids, active_readings, level_acquisition = h.active_window(down["commanded_at_s"] + policy.drop_s, "drop", point, h.level_point)
                up = command(detail, "set_voltage_live", lambda c, e: bench.set_live_voltage(base, c, effective_at=e),
                             round_trips=LAN_ROUND_TRIPS["set_voltage_live"], to_V=base, repeat=index + 1)
                self.stage = "recovery"
                self.begin_step(base, "recovery", off_expected=True)
                window_ids, window_readings = poll_until(up["commanded_at_s"] + _recovery_s(policy), point, "recovery")
                intervals = {"drop_s": host_interval(down, up)}
                first, second = down, up
            else:
                self.stage = "interruption"
                self.begin_step(0.0, "interruption", off_expected=True, interruption_commanded=True)
                off = command(detail, "output_off", lambda c, e: bench.set_output(False, c, effective_at=e),
                              round_trips=LAN_ROUND_TRIPS["output_off"], repeat=index + 1)
                active_ids, active_readings, level_acquisition = h.active_window(off["commanded_at_s"] + policy.interruption_s, "interruption", point, None)
                on = command(detail, "output_on", lambda c, e: bench.set_output(True, c, effective_at=e),
                             round_trips=LAN_ROUND_TRIPS["output_on"], repeat=index + 1)
                self.stage = "recovery"
                self.begin_step(base, "recovery", off_expected=True)
                window_ids, window_readings = poll_until(on["commanded_at_s"] + _recovery_s(policy), point, "recovery")
                intervals = {"interruption_s": host_interval(off, on)}
                first, second = off, on
            self.stage = "observation"
            self.begin_step(base, "recovery")
            observation = acquire(point)
            intervals["recovery_s"] = round(observation["started_s"] - second["commanded_at_s"], HOST_CLOCK_DIGITS)
            if observation["span_V"] > self.snapshot.recipe.settling.maximum_vout_span_V:
                raise RegulationRuleStop(f"Output voltage span {observation['span_V']:.3f} V exceeded the settling bound during the "
                                         "observation after the recovery window", values=observation["means"])
            record = self._repeat_record(index, policy, spec, intervals, active_readings, active_ids, window_readings, window_ids,
                                         observation, recovered_after(window_readings, second["commanded_at_s"]) if spec["off_expected"] else None,
                                         plant_truth(transitions_before), commands=[first["command"], second["command"]],
                                         commanded_window_s=(first["commanded_at_s"], second["commanded_at_s"]),
                                         level_acquisition=level_acquisition)
            detail["repeats"].append(record)
            ctx.event("repeat_completed", test_id=test.id, repeat=index + 1, intervals_host_s=intervals, observation=record["observation_text"])
            self._refresh_deviations(ctx.run["method"][METHOD_KEY])
            checkpoint()

    def _program_sequence(self, ctx, test, point, detail, h: SimpleNamespace) -> None:
        bench, policy, spec = ctx.bench, test.best_effort, STIMULUS[test.type]
        poll_until, command, acquire, recovered_after, plant_truth, checkpoint = (h.poll_until, h.command, h.acquire, h.recovered_after,
                                                                                 h.plant_truth, h.checkpoint)
        base, load = test.input_voltage_targets_V[0], test.output_current_targets_A[0]
        sequence = detail["sequence"]
        pre, active, rest = sequence["pre_group_s"], sequence["active_group_s"], sequence["rest_group_s"]
        tolerance = INSTRUMENT_SCHEDULE_TOLERANCE_S
        limit = self.programmed[test.id]["source_current_limit_A"]
        delayer = policy.mechanism == "supply_delayer"
        if delayer:
            groups = [("ON", pre)] + [("OFF", active), ("ON", rest)] * _repeats(policy)
            start = command(detail, "program_start", lambda c, e: bench.program_delayer(groups, c, start_latency_s=e - c, end_state="OFF"),
                            round_trips=LAN_ROUND_TRIPS["program_start"], mechanism="supply_delayer", groups=len(groups), end_state="OFF")
        else:
            level = policy.level_V if test.type == TRANSIENT_HOLD_TEST_TYPE else policy.drop_level_V
            groups = [(base, limit, pre)] + [(level, limit, active), (base, limit, rest)] * _repeats(policy)
            start = command(detail, "program_start", lambda c, e: bench.program_timer(groups, c, start_latency_s=e - c, end_state="OFF"),
                            round_trips=LAN_ROUND_TRIPS["program_start"], mechanism="supply_timer", groups=len(groups), end_state="OFF")
        t0 = start["commanded_at_s"]
        detail["program"] = {"mechanism": policy.mechanism, "groups": [list(group) for group in groups], "end_state": "OFF",
                             "predicted_from_host_s": t0, "schedule_tolerance_s": tolerance,
                             "predicted_boundaries_s": [t0 + pre + k * (active + rest) + offset
                                                        for k in range(_repeats(policy)) for offset in (0, active)] + [t0 + sequence["stimulus_total_s"]],
                             "note": "the host predicts every boundary from its own program-start instant and the programmed whole seconds; "
                                     "an output OFF outside a predicted window stops the run"}
        self.stage = "programmed-base"
        self.begin_step(base, "base")
        poll_until(t0 + pre - tolerance, point, "programmed")
        stimulus_level = 0.0 if delayer else (policy.level_V if test.type == TRANSIENT_HOLD_TEST_TYPE else policy.drop_level_V)
        for index in range(_repeats(policy)):
            transitions_before = len(bench.uvlo.transitions)
            t_active = t0 + pre + index * (active + rest)
            t_rest, t_next = t_active + active, t_active + active + rest
            self.stage = spec["level_kind"]
            self.begin_step(stimulus_level, spec["level_kind"], off_expected=spec["off_expected"], interruption_commanded=delayer)
            active_ids, active_readings, level_acquisition = h.active_window(t_rest + tolerance, spec["level_kind"], point, h.level_point)
            self.stage = "recovery" if spec["off_expected"] else "rest"
            self.begin_step(base, "recovery" if spec["off_expected"] else "rest", off_expected=spec["off_expected"])
            window_ids, window_readings = poll_until(t_rest + tolerance + _recovery_s(policy), point, "recovery" if spec["off_expected"] else "rest")
            self.stage = "observation"
            self.begin_step(base, "recovery")
            observation = acquire(point)
            if observation["span_V"] > self.snapshot.recipe.settling.maximum_vout_span_V:
                raise RegulationRuleStop(f"Output voltage span {observation['span_V']:.3f} V exceeded the settling bound during the "
                                         "observation after the recovery window", values=observation["means"])
            intervals = {spec["active"]: None, "recovery_s": None}
            record = self._repeat_record(index, policy, spec, intervals, active_readings, active_ids, window_readings, window_ids,
                                         observation, recovered_after(window_readings, t_rest) if spec["off_expected"] else None,
                                         plant_truth(transitions_before), commands=["program_start"],
                                         commanded_window_s=(t_active, t_rest), predicted=True, level_acquisition=level_acquisition)
            detail["repeats"].append(record)
            ctx.event("repeat_completed", test_id=test.id, repeat=index + 1, predicted_window_s=[t_active, t_rest],
                      observation=record["observation_text"])
            self._refresh_deviations(ctx.run["method"][METHOD_KEY])
            checkpoint()
            self.stage = "programmed-base"
            self.begin_step(base, "base")
            poll_until(t_next - tolerance, point, "programmed")
        # The program ends with the output OFF (its own end state): predicted, so expected; then the procedure de-energises.
        self.stage = "program-end"
        self.begin_step(0.0, "program-end", off_expected=True, interruption_commanded=True)
        poll_until(t0 + sequence["stimulus_total_s"] + tolerance, point, "program-end")
        state = bench.state(ctx.clock.monotonic())
        detail["program"]["end_state_observed"] = "OFF" if not bench.output_live else "ON"
        detail["program"]["status_at_end"] = bench.program_status(ctx.clock.monotonic())
        if bench.output_live:
            raise SourceBoundaryStop("The program did not end with the source output OFF as programmed",
                                     values={"Vin_V": state.source_voltage_V, "Iin_A": state.input_current_A,
                                             "Vout_V": state.output_voltage_V, "Iout_A": state.output_current_A})

    def _repeat_record(self, index, policy, spec, intervals, active_readings, active_ids, window_readings, window_ids, observation,
                       recovered_after_s, truth, *, commands, commanded_window_s, predicted=False,
                       level_acquisition=None) -> dict[str, Any]:
        poll = self.snapshot.recipe.acquisition.target_poll_interval_s
        during, window = summary_of(active_readings, self), summary_of(window_readings, self)
        active_s = float(getattr(policy, spec["active"]))
        if during["cycles"] == 0:
            seen = (f"no poll fell inside the {'predicted' if predicted else 'commanded'} {active_s:g} s {spec['level_kind']} at the "
                    f"{poll:g} s poll interval: invisible to polling; what happened at the converter is not observed")
        elif spec["off_expected"]:
            seen = (f"{during['off']} of {during['cycles']} polls inside the {spec['level_kind']} saw the output off "
                    f"(expected-off window, recorded not faulted)")
        else:
            seen = f"{during['on']} of {during['cycles']} polls inside the {spec['level_kind']} saw the output in band"
        if spec["off_expected"]:
            if recovered_after_s is not None:
                recovery = f"; back in band {recovered_after_s:.2f} s after the restore (poll cadence {poll:g} s, so bounded, not resolved)"
            elif window["cycles"] == 0:
                recovery = "; no poll fell inside the recovery window"
            else:
                recovery = f"; not back in band within the {_recovery_s(policy):g} s recovery window polls"
        else:
            recovery = ""
        text = f"repeat {index + 1}: {seen}{recovery}; output {observation['state']} at the observation after the window"
        return {"index": index + 1, "commands": commands, "commanded_window_host_s": list(commanded_window_s), "predicted_window": predicted,
                "intervals_host_s": intervals, "polls_during_stimulus": {**during, "cycle_ids": active_ids},
                "polls_during_window": {**window, "cycle_ids": window_ids}, "recovered_after_host_s": recovered_after_s,
                "level_acquisition": level_acquisition, "observation": observation, "observation_text": text, "plant_truth": truth}


def summary_of(readings: list[tuple[float, dict[str, float]]], procedure: BestEffortProcedure) -> dict[str, Any]:
    states = [procedure.classify_output(values["Vout_V"]) for _, values in readings]
    return {"cycles": len(readings), "on": states.count("on"), "off": states.count("off"), "indeterminate": states.count("indeterminate"),
            "Vin_mean_V": mean(values["Vin_V"] for _, values in readings) if readings else None,
            "Vout_mean_V": mean(values["Vout_V"] for _, values in readings) if readings else None}


def run_best_effort_mock(plan: Plan, out: Path, *, seed: int = 1, synthetic: SyntheticUvlo | None = None,
                         hold_up: HoldUpModel | None = None, startup: StartupModel | None = None,
                         reading_override: ReadingOverride | None = None, operator_observations: list[str] | None = None,
                         attachment_descriptors: list[dict] | None = None) -> Path:
    """Execute a best-effort ISO 16750-2 recipe against the synthetic plant; return the finalized run directory.

    The plant is the UVLO bench with the generic soft start (1 s cold-start delay, 0.3 s time constant),
    clean readbacks, command latencies drawn from the recorded LAN round trips and the input hold-up
    model (``hold_up``, default 470 µF). Refuses real profiles, hash mismatches, other test types, a
    missing approval or a stale accepted sheet, and any non-executable point before anything is written.
    This function never creates or imports real instruments.
    """
    if plan.bench.mode != "mock":  # the bench decides; a legacy recipe mode is metadata
        raise ValueError("run_best_effort_mock accepts mock profiles only; the best-effort ISO 16750-2 procedures are not approved "
                         "for real hardware")
    hold_up = hold_up if hold_up is not None else HoldUpModel()
    startup = startup if startup is not None else StartupModel()
    kind = plan.recipe.tests[0].type if plan.recipe.tests else "best_effort"
    latency = {key: READBACK_MODEL_PARAMETERS[key] for key in ("round_trip_min_s", "round_trip_scale_s", "round_trip_max_s")}
    plant_record = {"hold_up": hold_up.parameters(), "startup": startup.parameters(),
                    "command_latency": {**latency, "distribution": "each LAN write takes effect its own round trip after it is issued: "
                                                                  "min + Exp(scale), capped (recorded 4-55 ms); the supply's processing "
                                                                  "time (< 118 ms, DS5) is not modelled"},
                    "instrument_timing": dict(INSTRUMENT_TIMING_PARAMETERS),
                    "label": "SYNTHETIC plant parameters of this run; not DUT characteristics and not measurements"}

    def bench_factory(plan_: Plan, uvlo: SyntheticUvlo, seed_: int) -> UvloMockBench:
        return UvloMockBench(plan_.dut.ratings.output_voltage_nominal_V,
                             plan_.bench.protective_controls.source_current_limit_A or plan_.bench.source.max_current_A,
                             plan_.bench.load.min_voltage_V, seed_, uvlo=uvlo, startup=startup,
                             readback=ReadbackModel.clean(**ReadbackModel.recorded_round_trips()), hold_up=hold_up)

    def procedure_factory(plan_: Plan) -> BestEffortProcedure:
        procedure = BestEffortProcedure(plan_)
        procedure.plant_record = plant_record
        return procedure

    return run_phase_scoped_mock(plan, out, procedure_factory=procedure_factory, method_key=METHOD_KEY,
                                 run_tag=RUN_TAGS.get(kind, "besteffort"), scenario=f"iso16750-2-best-effort-{kind.replace('_', '-')}",
                                 authorization_note="explicit run_best_effort_mock call under the recipe's best-effort approval block "
                                                    "(accepted deviation sheet); never arms real equipment",
                                 seed=seed, synthetic=synthetic, reading_override=reading_override,
                                 operator_observations=operator_observations, attachment_descriptors=attachment_descriptors,
                                 bench_factory=bench_factory)


__all__ = ["BEST_EFFORT_TEST_TYPES", "BestEffortProcedure", "INTERRUPTION_TEST_TYPES", "LINE_INTERRUPTION_TEST_TYPE", "METHOD_KEY",
           "MICRO_INTERRUPTION_TEST_TYPE", "MOMENTARY_DROP_TEST_TYPE", "TRANSIENT_HOLD_TEST_TYPE", "best_effort_approval_gaps",
           "best_effort_mock_estimate", "declared_deviations_sha256", "deviation_sheet_sha256", "needs_uvlo_approval",
           "run_best_effort_mock", "stimulus_levels_V", "stimulus_plan"]
