"""Pure feasibility planning: preserve each request and explain every exclusion."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_CEILING
from itertools import groupby
from pathlib import Path
from typing import TypeVar

import yaml

from .domain import (BEST_EFFORT_TEST_TYPES, LINE_INTERRUPTION_TEST_TYPE, MICRO_INTERRUPTION_TEST_TYPE, MOCK_THERMAL_ADAPTER,
                     MOMENTARY_DROP_TEST_TYPE, RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE, SUPPLY_PROFILE_TEST_TYPES,
                     TRANSIENT_HOLD_TEST_TYPE, UVLO_TEST_TYPE, BenchProfile, Contract, DutProfile, Plan, PlannedPoint, TestDefinition,
                     TestRecipe, staircase_level_kinds, uvlo_ramp_phases)

Profile = TypeVar("Profile", bound=Contract)
REQUIRED_MEASUREMENTS = {"Vin_V": "V", "Iin_A": "A", "Vout_V": "V", "Iout_A": "A"}
# Procedure types with an implemented executor. Any other type fails planning.
# The supply-profile and best-effort types exist on the synthetic plant only; a real bench refuses them.
MOCK_ONLY_TEST_TYPES = (*SUPPLY_PROFILE_TEST_TYPES, *BEST_EFFORT_TEST_TYPES)
IMPLEMENTED_TEST_TYPES = ("steady_state_load_sweep", UVLO_TEST_TYPE, *MOCK_ONLY_TEST_TYPES)
REAL_HARDWARE_NOT_APPROVED = ("is not yet approved for real hardware: the procedure exists on the synthetic plant only "
                              "and no real execution context exists in this release")
# The real path's run envelope (extended.SOFTWARE_DEADLINE_S / HARDWARE_DEADLINE_S; docs/configured-runs.md). A best-effort
# recipe whose longest source phase exceeds the source timer declares its own authorization.instrument_timed_bound_s and is
# approved with it (owner decision 1 of 2026-10-01); the planner then compares the phase with the declared bound instead.
REAL_SOFTWARE_DEADLINE_S = 660.0
REAL_SOURCE_TIMER_S = 720.0
# --- Simulated-run budget (docs/simulation-plant.md, "Run budget") -------------------------------------
# The mock worker fsyncs every JSONL record, so its wall time follows the record count and host I/O,
# not model time. The bench service runs it in a transient unit with RuntimeMaxSec=2700 and
# KillMode=control-group; a run must finish, including finalization, well inside that.
MOCK_RUN_BUDGET_S = 2400.0                    # 2700 s minus a 300 s margin for launch, finalization and the report hand-off
MOCK_DEADLINE_FIXED_S = 120.0                 # the runner's own hung-owner deadline: 120 s + 0.1 s per record ...
MOCK_DEADLINE_SECONDS_PER_RECORD = 0.1        # ... sized for a loaded SD card; the plan is refused when it cannot fit
MOCK_ESTIMATE_FIXED_S = 15.0                  # typical: spawn of the plant owner, provenance hashing, finalization
MOCK_ESTIMATE_SECONDS_PER_RECORD = 0.005      # typical: 2-3 ms per fsync'd record measured on the bench Pi 4 (idle, 2026-09-30), rounded up
MOCK_STARTUP_CYCLES = 5                       # source-only gate cycles per input-voltage phase, mirrored from real_backend
MOCK_LOAD_ENABLE_CYCLES = 5                   # loaded startup cycles after the load input is enabled


def load_profile(path: str | Path, model: type[Profile]) -> Profile:
    """Load data only. Safe YAML forbids executable constructors; size is bounded."""
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("Profile exceeds the 2 MB size limit")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Profile must be a mapping")
    return model.model_validate(data)


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def verify_plan_hash(plan: Plan) -> bool:
    """Any edit to configuration, point qualification, or warnings invalidates arming."""
    return plan.plan_hash == _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))


def missing_approvals(dut: DutProfile, bench: BenchProfile) -> list[str]:
    """Saved-profile approvals that must all be true before any real arming."""
    missing = []
    if not dut.execution_approval.real_hardware_enabled:
        missing.append("DUT profile execution_approval.real_hardware_enabled is false")
    if not dut.execution_approval.wiring_and_polarity_confirmed:
        missing.append("DUT profile execution_approval.wiring_and_polarity_confirmed is false")
    if not bench.protective_controls.approved:
        missing.append("bench profile protective_controls.approved is false")
    return missing


def uvlo_approval_gaps(bench: BenchProfile, recipe: TestRecipe) -> list[str]:
    """Policy gaps that block a UVLO input ramp in either execution mode.

    The ramp is refused unless the recipe carries the explicit approval block
    and names the bench's protective policy, and the bench declares the
    absolute limits the phase-scoped guard enforces at every step. Real
    execution additionally needs ``missing_approvals`` to be empty.
    """
    gaps = []
    authorization, controls = recipe.authorization, bench.protective_controls
    if not authorization.uvlo_approved:
        gaps.append("recipe authorization.uvlo_approved is false")
    if authorization.protective_policy_id is None:
        gaps.append("recipe authorization.protective_policy_id is not declared")
    elif controls.policy_id != authorization.protective_policy_id:
        gaps.append("bench protective_controls.policy_id does not name the recipe's protective policy")
    for field in ("source_current_limit_A", "dut_output_overvoltage_V", "output_overcurrent_A"):
        if getattr(controls, field) is None:
            gaps.append(f"bench protective_controls.{field} must be declared for the absolute UVLO guard")
    return gaps


def recipe_deviations_sha256(recipe: TestRecipe) -> str | None:
    """The hash a best-effort approval accepts: the single sheet's ``sha256()``, or for a recipe with several best-effort
    tests the SHA-256 of the JSON list of their sheet hashes in test order. None when the recipe carries no sheet."""
    digests = [test.best_effort.deviation_sheet.sha256() for test in recipe.tests if test.best_effort is not None]
    if not digests:
        return None
    if len(digests) == 1:
        return digests[0]
    return hashlib.sha256(json.dumps(digests, separators=(",", ":")).encode("utf-8")).hexdigest()


def best_effort_approval_gaps(bench: BenchProfile, recipe: TestRecipe) -> list[str]:
    """Policy gaps that block a best-effort ISO 16750-2 recipe in either execution mode (owner decision 4: the UVLO gate).

    The recipe is refused unless it carries ``best_effort_approved`` with an
    ``accepted_deviations_sha256`` equal to the hash of the deviation sheet(s)
    it declares now (an edited sheet invalidates the approval), names the
    bench's protective policy, and the bench declares the absolute limits and
    the input overvoltage guard. Levels never exceed the DUT's stated maximum;
    a level equal to it is allowed only with ``program_clause_level_exactly``
    (owner decision 6). A phase longer than the real path's source timer
    needs the recipe's own ``instrument_timed_bound_s`` (owner decision 1).
    Real execution additionally needs ``missing_approvals`` to be empty.
    """
    gaps = []
    authorization, controls = recipe.authorization, bench.protective_controls
    tests = [test for test in recipe.tests if test.type in BEST_EFFORT_TEST_TYPES and test.best_effort is not None]
    if not authorization.best_effort_approved:
        gaps.append("recipe authorization.best_effort_approved is false")
    declared = recipe_deviations_sha256(recipe)
    if authorization.accepted_deviations_sha256 is None:
        gaps.append("recipe authorization.accepted_deviations_sha256 is not declared")
    elif declared is None:
        gaps.append("recipe declares no deviation sheet to accept")
    elif authorization.accepted_deviations_sha256 != declared:
        gaps.append("recipe authorization.accepted_deviations_sha256 does not match the declared deviation sheet; the sheet "
                    "changed after approval, so review and approve it again")
    if authorization.protective_policy_id is None:
        gaps.append("recipe authorization.protective_policy_id is not declared")
    elif controls.policy_id != authorization.protective_policy_id:
        gaps.append("bench protective_controls.policy_id does not name the recipe's protective policy")
    for field in ("source_current_limit_A", "dut_input_overvoltage_V", "dut_output_overvoltage_V", "output_overcurrent_A"):
        if getattr(controls, field) is None:
            gaps.append(f"bench protective_controls.{field} must be declared for the best-effort guard")
    if any(test.best_effort.longest_phase_s(test.type) > REAL_SOURCE_TIMER_S for test in tests) and authorization.instrument_timed_bound_s is None:
        gaps.append(f"a declared phase exceeds the {REAL_SOURCE_TIMER_S:g} s source timer and the recipe declares no "
                    "authorization.instrument_timed_bound_s (owner decision 1)")
    return gaps


def best_effort_level_gaps(dut: DutProfile, recipe: TestRecipe) -> list[str]:
    """Levels a best-effort recipe may never request: above the DUT maximum, or equal to it without the exact-level flag."""
    gaps = []
    maximum, exact = dut.ratings.input_voltage_max_V, recipe.authorization.program_clause_level_exactly
    for test in recipe.tests:
        if test.type not in BEST_EFFORT_TEST_TYPES:
            continue
        for vin in test.input_voltage_targets_V:
            if vin > maximum:
                gaps.append(f"test {test.id} requests {vin:g} V above the DUT's stated {maximum:g} V maximum")
            elif vin == maximum and not exact:
                gaps.append(f"test {test.id} requests {vin:g} V, the converter's stated maximum, without "
                            "authorization.program_clause_level_exactly (owner decision 6)")
    return gaps


def phase_duration_bound_s(bench: BenchProfile, recipe: TestRecipe) -> float:
    """The per-phase bound in force: the recipe's approved ``instrument_timed_bound_s``, else the real path's source timer."""
    bound = recipe.authorization.instrument_timed_bound_s
    if bound is not None and not best_effort_approval_gaps(bench, recipe):
        return bound
    return REAL_SOURCE_TIMER_S


def best_effort_phase_reasons(recipe: TestRecipe, test: TestDefinition) -> list[str]:
    """Refuse a best-effort test whose longest source phase exceeds the bound it may use (declared, else the 720 s timer)."""
    policy = test.best_effort
    if policy is None:
        return []
    longest, declared = policy.longest_phase_s(test.type), recipe.authorization.instrument_timed_bound_s
    if declared is not None and longest > declared:
        return [f"The declared {longest:g} s phase of {test.id} exceeds the recipe's own instrument_timed_bound_s of {declared:g} s; "
                "request retained without clipping"]
    if declared is None and longest > REAL_SOURCE_TIMER_S:
        return [f"The declared {longest:g} s phase of {test.id} exceeds the {REAL_SOURCE_TIMER_S:g} s per-phase source timer of the "
                "real path's policy and the recipe declares no authorization.instrument_timed_bound_s (owner decision 1); "
                "request retained without clipping"]
    return []


def best_effort_level_kind(test: TestDefinition, level_index: int) -> str:
    """``base`` / ``hold level`` for a transient hold, ``start`` / ``drop level`` for a drop, ``base`` for an interruption."""
    if test.type == TRANSIENT_HOLD_TEST_TYPE:
        return "base" if level_index == 0 else "hold level"
    if test.type == MOMENTARY_DROP_TEST_TYPE:
        return "start" if level_index == 0 else "drop level"
    return "base"


def best_effort_needs_uvlo_approval(dut: DutProfile, test: TestDefinition) -> bool:
    """A drop level below the DUT's stated minimum, or an interruption (output OFF is 0 V), takes the approved UVLO-style path."""
    if test.type in (MICRO_INTERRUPTION_TEST_TYPE, LINE_INTERRUPTION_TEST_TYPE):
        return True
    return any(vin < dut.ratings.input_voltage_min_V for vin in test.input_voltage_targets_V)


def best_effort_step_reasons(dut: DutProfile, recipe: TestRecipe, test: TestDefinition, vin: float, level_kind: str) -> list[str]:
    """Refuse (never clip) best-effort levels above the DUT rating, at its maximum without the exact flag, below the declared
    drop level, or below the DUT minimum where the recipe declares no drop there."""
    ratings, authorization, policy = dut.ratings, recipe.authorization, test.best_effort
    reasons = []
    if vin > ratings.input_voltage_max_V:
        reasons.append("Requested input voltage is above the DUT maximum input rating")
    elif vin == ratings.input_voltage_max_V and not authorization.program_clause_level_exactly:
        reasons.append(f"Requested input voltage {vin:g} V equals the converter's stated maximum and is programmed exactly only with "
                       "authorization.program_clause_level_exactly (owner decision 6); request retained without clipping")
    if vin < ratings.input_voltage_min_V and not (level_kind == "drop level" and policy is not None and vin == policy.drop_level_V):
        reasons.append(f"Requested input voltage {vin:g} V is below the DUT's stated {ratings.input_voltage_min_V:g} V minimum and is "
                       "not the declared drop level; request retained without clipping")
    if test.supply_profile is not None and vin < test.supply_profile.floor_V:
        reasons.append(f"Requested input voltage {vin:g} V is below the declared supply-profile floor {test.supply_profile.floor_V:g} V; "
                       "request retained without clipping")
    return reasons


def uvlo_step_reasons(dut: DutProfile, test: TestDefinition, vin: float) -> list[str]:
    """Refuse (never clip) UVLO steps below the declared floor, above the DUT rating, or a start outside it.

    Steps between the floor and the DUT minimum are the authorized excursion the
    approval block exists for; the generic DUT-range rule is replaced here.
    """
    ratings, policy = dut.ratings, test.uvlo
    reasons = []
    if policy is not None and vin < policy.floor_V:
        reasons.append(f"Requested input voltage {vin:g} V is below the declared UVLO floor {policy.floor_V:g} V; "
                       "request retained without clipping")
    if vin > ratings.input_voltage_max_V:
        reasons.append("Requested input voltage is above the DUT maximum input rating")
    if vin == test.input_voltage_targets_V[0] and not ratings.input_voltage_min_V <= vin <= ratings.input_voltage_max_V:
        reasons.append("A UVLO ramp must start inside the DUT's stated input range")
    return reasons


def supply_profile_level_kinds(test: TestDefinition) -> list[str]:
    """``down``/``up`` for a slow ramp's observation levels, ``recovery``/``low`` for a staircase's levels."""
    if test.type == SLOW_SUPPLY_RAMP_TEST_TYPE:
        return uvlo_ramp_phases(test.input_voltage_targets_V)
    if test.type == RESET_STAIRCASE_TEST_TYPE:
        return staircase_level_kinds(test.input_voltage_targets_V)
    raise ValueError(f"{test.type!r} is not a supply-profile test type")


def supply_profile_needs_approval(dut: DutProfile, test: TestDefinition) -> bool:
    """A profile that steps below the DUT's stated minimum takes the approved UVLO-style path (brief 7.5)."""
    return any(vin < dut.ratings.input_voltage_min_V for vin in test.input_voltage_targets_V)


def supply_profile_step_reasons(dut: DutProfile, test: TestDefinition, vin: float, level_kind: str) -> list[str]:
    """Refuse (never clip) supply-profile levels below the declared floor, above the DUT rating, or a start outside it."""
    ratings, policy = dut.ratings, test.supply_profile
    reasons = []
    if policy is not None and vin < policy.floor_V:
        reasons.append(f"Requested input voltage {vin:g} V is below the declared supply-profile floor {policy.floor_V:g} V; "
                       "request retained without clipping")
    if vin > ratings.input_voltage_max_V:
        reasons.append("Requested input voltage is above the DUT maximum input rating")
    inside = ratings.input_voltage_min_V <= vin <= ratings.input_voltage_max_V
    if test.type == SLOW_SUPPLY_RAMP_TEST_TYPE and vin == test.input_voltage_targets_V[0] and not inside:
        reasons.append("A slow supply ramp must start inside the DUT's stated input range")
    if test.type == RESET_STAIRCASE_TEST_TYPE and level_kind == "recovery" and not inside:
        reasons.append("The reset-staircase recovery level must lie inside the DUT's stated input range")
    return reasons


def _unsupported_capabilities(dut: DutProfile, bench: BenchProfile, test: TestDefinition) -> list[str]:
    reasons: list[str] = []
    if test.type not in IMPLEMENTED_TEST_TYPES:
        reasons.append(f"Test type {test.type!r} is not an implemented procedure")
    elif test.type in MOCK_ONLY_TEST_TYPES and bench.mode == "real":
        reasons.append(f"Test type {test.type!r} {REAL_HARDWARE_NOT_APPROVED}")
    for name, instrument in (("Source", bench.source), ("Load", bench.load)):
        if not instrument.capabilities_confirmed:
            reasons.append(f"{name} capabilities have not been confirmed for this profile")
        if any(value is None for value in (instrument.max_voltage_V, instrument.max_current_A, instrument.max_power_W)):
            reasons.append(f"{name} voltage, current, and power limits must be supplied")
        if instrument.remote_sense_required and not instrument.remote_sense_supported:
            reasons.append(f"{name} remote sense is required but unsupported")
    if bench.source.max_voltage_V is not None and bench.source.max_voltage_V < dut.ratings.input_voltage_min_V:
        reasons.append("Source voltage capability is below the DUT minimum input; this channel cannot power this DUT")
    if bench.load.max_voltage_V is not None and not (bench.load.min_voltage_V <= dut.ratings.output_voltage_nominal_V <= bench.load.max_voltage_V):
        reasons.append("DUT nominal output voltage is outside the load operating envelope")
    for quantity in set(REQUIRED_MEASUREMENTS).union(test.required_quantities):
        binding = bench.measurements.get(quantity)
        if binding is None:
            reasons.append(f"Required measurement {quantity} is unavailable; no substitute value is permitted")
        elif quantity in REQUIRED_MEASUREMENTS and binding.unit != REQUIRED_MEASUREMENTS[quantity]:
            reasons.append(f"Measurement {quantity} has an incompatible unit")
        elif quantity in REQUIRED_MEASUREMENTS and binding.quantity != quantity:
            reasons.append(f"Measurement role {quantity} is bound to a different quantity")
    # Section 10: a thermal test requires real configured channels with sensor
    # metadata; a missing sensor is never replaced by a model value.
    if test.thermal_settling is not None:
        sensors = {sensor.quantity: sensor for sensor in bench.temperature_sensors}
        for role, quantity in (("surface", test.thermal_settling.surface_quantity),
                               ("ambient", test.thermal_settling.ambient_quantity)):
            if quantity not in bench.measurements:
                reasons.append(f"Thermal settling requires a bound {role} temperature channel {quantity}; "
                               "none is declared and no model value is substituted")
            elif quantity not in sensors:
                reasons.append(f"Temperature channel {quantity} has no sensor record (surface, attachment, ambient reference)")
            elif sensors[quantity].role != role:
                reasons.append(f"Temperature channel {quantity} is declared as a {sensors[quantity].role} sensor, not {role}")
        if bench.mode == "mock" and any(sensor.adapter != MOCK_THERMAL_ADAPTER for sensor in bench.temperature_sensors):
            reasons.append("Mock execution provides only the synthetic temperature adapter; other adapters are not implemented")
    return sorted(reasons)


def _point(dut: DutProfile, bench: BenchProfile, recipe: TestRecipe, test: TestDefinition,
           point_id: str, vin: float, iout: float, level_index: int = 0) -> PlannedPoint:
    ratings, source, load, policy = dut.ratings, bench.source, bench.load, recipe.planning
    reasons = _unsupported_capabilities(dut, bench, test)
    types = {t.type for t in recipe.tests}
    if UVLO_TEST_TYPE in types and len(types) > 1:
        # The ramp is its own phase-scoped procedure; no executor runs it inside a load sweep.
        reasons.append("Recipe mixes uvlo_input_ramp with other test types; plan the UVLO ramp as a separate recipe")
    elif types & set(SUPPLY_PROFILE_TEST_TYPES) and len(types) > 1:
        mixed = sorted(types & set(SUPPLY_PROFILE_TEST_TYPES))[0]
        reasons.append(f"Recipe mixes {mixed} with other test types; plan the supply profile as a separate recipe")
    elif types & set(BEST_EFFORT_TEST_TYPES) and len(types) > 1:
        # Several tests of one best-effort type (the variants of a clause) share a recipe; two types never do.
        mixed = sorted(types & set(BEST_EFFORT_TEST_TYPES))[0]
        reasons.append(f"Recipe mixes {mixed} with other test types; plan the best-effort procedure as a separate recipe")
    # Supply profiles: the level's kind decides where output-off is an expected, recorded state.
    profile_kind, off_expected, best_effort_kind = None, False, None
    if test.type in SUPPLY_PROFILE_TEST_TYPES and test.supply_profile is not None:
        profile_kind = supply_profile_level_kinds(test)[level_index]
        off_expected = test.supply_profile.off_expected(vin, profile_kind)
    elif test.type in BEST_EFFORT_TEST_TYPES:
        # Output-off is expected only at a declared drop level below the recipe's expected-off boundary; the interruption
        # itself is output OFF, not a level, and the procedure scopes it by time.
        best_effort_kind = best_effort_level_kind(test, level_index)
        off_expected = (best_effort_kind == "drop level" and test.supply_profile is not None
                        and test.supply_profile.off_expected(vin, "low"))
    physical_power = None
    if source.max_current_A is not None and source.max_power_W is not None:
        physical_power = min(vin * source.max_current_A, source.max_power_W)
    assumed_dut_vin = vin - policy.input_wiring_drop_allowance_V
    estimated_iin = None
    planning_limit = None
    if assumed_dut_vin > 0 and source.max_current_A is not None and source.max_power_W is not None:
        usable_current = source.max_current_A * policy.source_current_budget_fraction
        if bench.protective_controls.source_current_limit_A is not None:
            usable_current = min(usable_current, bench.protective_controls.source_current_limit_A)
        available_input_power = min(assumed_dut_vin * usable_current, source.max_power_W * policy.source_current_budget_fraction)
        planning_limit = max(0., (available_input_power - policy.auxiliary_input_power_estimate_W) * policy.efficiency_estimate_fraction / ratings.output_voltage_nominal_V)
        if iout > 0 and not off_expected:
            estimated_iin = ((ratings.output_voltage_nominal_V * iout) / policy.efficiency_estimate_fraction + policy.auxiliary_input_power_estimate_W) / assumed_dut_vin
    else:
        reasons.append("Planning input voltage after wiring allowance must be positive, and source capabilities must be known")
    if off_expected:
        # Output-off is the documented state here: the load draws nothing, so the
        # efficiency-based budget does not describe the point. The source-CV guard
        # governs at run time; a standby draw is unknown, not estimated.
        planning_limit = None
    pout = ratings.output_voltage_nominal_V * iout
    if test.type == UVLO_TEST_TYPE:
        reasons.extend(uvlo_step_reasons(dut, test, vin))
    elif profile_kind is not None:
        reasons.extend(supply_profile_step_reasons(dut, test, vin, profile_kind))
    elif best_effort_kind is not None:
        reasons.extend(best_effort_step_reasons(dut, recipe, test, vin, best_effort_kind))
        reasons.extend(best_effort_phase_reasons(recipe, test))
    elif not ratings.input_voltage_min_V <= vin <= ratings.input_voltage_max_V:
        reasons.append("Requested input voltage is outside the DUT operating rating")
    if iout > ratings.output_current_rated_A + 1e-12 or pout > ratings.output_power_rated_W + 1e-12:
        reasons.append("Requested nominal output exceeds the DUT current or power rating")
    # Explicit guards are inclusive planning ceilings: target <= guard.
    # Equality is not proof of operating headroom, instrument accuracy, or
    # transient safety. Those require the separately approved physical method.
    # Compare input against the requested source voltage, without assuming an
    # estimated wiring drop will provide reliable protection at the DUT.
    controls = bench.protective_controls
    for value, limit, description in (
        (vin, controls.dut_input_overvoltage_V, "input voltage"),
        (ratings.output_voltage_nominal_V, controls.dut_output_overvoltage_V, "nominal output voltage"),
        (iout, controls.output_overcurrent_A, "output current"),
    ):
        if limit is not None and value > limit:
            unit = "A" if description == "output current" else "V"
            reasons.append(f"Requested {description} {value:g} {unit} exceeds the configured "
                           f"{description} guard {limit:g} {unit}; request retained without clipping")
    if vin < source.min_voltage_V or (source.max_voltage_V is not None and vin > source.max_voltage_V):
        reasons.append("Requested input voltage is outside the source capability")
    if load.max_current_A is not None and iout > load.max_current_A:
        reasons.append("Requested output current exceeds the load current capability")
    if 0 < iout < load.min_current_A:
        reasons.append("Requested output current is below the load controllable current envelope")
    if load.max_power_W is not None and pout > load.max_power_W:
        reasons.append("Requested nominal output power exceeds the load power capability")
    if physical_power is not None and pout > physical_power + 1e-12 and not off_expected:
        # At an expected-off level no output power is delivered; if the output stays on and the
        # source leaves CV, the procedure's source-boundary guard stops the run instead.
        reasons.append("Requested nominal output exceeds the source physical input-power capability even at 100% efficiency")
    expected = {"Vin_V": vin, "Iin_A": estimated_iin, "Vout_V": ratings.output_voltage_nominal_V, "Iout_A": iout}
    for quantity, value in expected.items():
        binding = bench.measurements.get(quantity)
        if binding and binding.measurement_range is not None and value is not None and value > binding.measurement_range:
            reasons.append(f"Expected {quantity} exceeds its declared measurement range")
    if reasons:
        status = "unsupported"
        reason = "; ".join(reasons)
    elif planning_limit is not None and iout > planning_limit + 1e-12:
        status = "assumption_limited"
        reason = (f"Requested load exceeds the planning budget ({planning_limit:.6g} A output at "
                  f"assumed efficiency {policy.efficiency_estimate_fraction:.0%} and source-current budget "
                  f"{policy.source_current_budget_fraction:.0%}); request retained without clipping")
    elif test.type == UVLO_TEST_TYPE and (gaps := uvlo_approval_gaps(bench, recipe)):
        status = "approval_blocked"
        missing = gaps + (missing_approvals(dut, bench) if bench.mode == "real" else [])
        reason = "UVLO input ramp is blocked by approvals: " + "; ".join(missing)
    elif (profile_kind is not None and supply_profile_needs_approval(dut, test)
          and (gaps := uvlo_approval_gaps(bench, recipe))):
        status = "approval_blocked"
        reason = (f"Supply profile {test.type} steps below the DUT's stated {ratings.input_voltage_min_V:g} V minimum and "
                  "takes the approved UVLO-style path (brief 7.5); blocked by approvals: " + "; ".join(gaps))
    elif best_effort_kind is not None and (gaps := best_effort_approval_gaps(bench, recipe) + best_effort_level_gaps(dut, recipe)
                                           + (uvlo_approval_gaps(bench, recipe) if best_effort_needs_uvlo_approval(dut, test) else [])):
        status = "approval_blocked"
        reason = (f"Best-effort {test.type} (ISO 16750-2 clause {test.best_effort.clause}) is blocked by approvals: "
                  + "; ".join(dict.fromkeys(gaps)))
    elif bench.mode == "real":
        status = "approval_blocked"
        missing = missing_approvals(dut, bench)
        reason = ("Real execution is blocked by saved-profile approvals: " + "; ".join(missing) if missing else
                  "Real execution requires confirmed identity, protective policy, wiring, and fresh operator arming bound to this plan")
    else:
        status = "executable"
        reason = "Executable with the synthetic bench; feasibility remains a planning assumption"
        if iout == 0:
            reason += "; no-load input draw is unknown, not zero"
        if test.type == UVLO_TEST_TYPE and vin < ratings.input_voltage_min_V:
            reason += ("; below the DUT's stated minimum input, inside the declared UVLO floor: "
                       "output-off is a recorded state here, not a fault")
        if profile_kind is not None:
            reason += f"; {profile_kind} level of the {test.type.replace('_', ' ')}"
            if off_expected:
                reason += (" where output-off is the DUT's documented expectation: recorded as a state, not a fault; "
                           "the planning load budget does not apply to an off output")
            elif vin < ratings.input_voltage_min_V:
                reason += "; below the DUT's stated minimum input, inside the declared floor"
        if best_effort_kind is not None:
            reason += (f"; {best_effort_kind} of the best-effort {test.type.replace('_', ' ')} (ISO 16750-2 clause "
                       f"{test.best_effort.clause}{', variant ' + test.best_effort.variant if test.best_effort.variant else ''}); "
                       "the deviation sheet travels with the plan")
            if off_expected:
                reason += ("; output-off at the drop level is the recipe's documented expectation: recorded as a state, not a "
                           "fault; the planning load budget does not apply to an off output")
    return PlannedPoint(point_id=point_id, test_id=test.id, vin_target_V=vin, iout_target_A=iout,
                        status=status, reason=reason, estimated_input_current_A=estimated_iin,
                        physical_input_power_limit_W=physical_power, planning_output_current_limit_A=planning_limit)


def known_behaviour_warnings(dut: DutProfile, recipe: TestRecipe) -> list[str]:
    """One warning per recorded failed cold-start level that a requested input is at or below (both modes)."""
    behaviours = dut.known_behaviours
    if behaviours is None or not behaviours.cold_start_failed_at_V:
        return []
    failed = max(behaviours.cold_start_failed_at_V)
    affected = sorted({vin for test in recipe.tests for vin in test.input_voltage_targets_V if vin <= failed})
    if not affected:
        return []
    levels = ", ".join(f"{vin:g} V" for vin in affected)
    return [f"Recorded behaviour of {dut.identity.model}: a direct cold start at {failed:g} V input failed on the "
            f"physical sample; requested input {levels} {'is' if len(affected) == 1 else 'are'} at or below that level. "
            "On the real bench the source-only startup gate refuses to enable the load unless the output is in band; "
            "the simulated bench reproduces the recorded failed start (DUT profile known_behaviours)."]


def mock_run_estimate(plan: Plan) -> dict:
    """Record count and wall-time estimate of ``runner.run_mock`` for this plan, and whether it fits the budget.

    Records are an upper estimate: every executable point settles to its timeout and acquires for
    its duration at the target poll interval on the four electrical channels (plus bound temperature
    channels and the thermal-settling polls), every input-voltage phase adds the five source-only
    startup cycles and, when it has a loaded point, the five loaded startup cycles. ``deadline_s``
    is the runner's own worst-case deadline for that volume; the plan is within budget only when
    that deadline fits ``MOCK_RUN_BUDGET_S``. ``typical_s`` is what an idle bench computer needs.
    """
    r = plan.recipe
    poll = max(r.acquisition.target_poll_interval_s, 1e-3)
    executable = [p for p in plan.points if p.status == "executable"]
    phases = [list(group) for _, group in groupby(executable, key=lambda p: (p.test_id, p.vin_target_V))]
    loaded_phases = sum(any(p.iout_target_A > 0 for p in group) for group in phases)
    channels = len(plan.bench.temperature_sensors)
    polls_per_point = math.ceil((r.settling.timeout_s + r.acquisition.duration_s) / poll)
    thermal_polls = max((math.ceil(t.thermal_settling.timeout_s / t.thermal_settling.poll_interval_s)
                         for t in r.tests if t.thermal_settling), default=0)
    records = (len(executable) * ((len(REQUIRED_MEASUREMENTS) + channels) * polls_per_point
                                  + (len(REQUIRED_MEASUREMENTS) + channels) * thermal_polls)
               + len(phases) * MOCK_STARTUP_CYCLES * len(REQUIRED_MEASUREMENTS)
               + loaded_phases * MOCK_LOAD_ENABLE_CYCLES * len(REQUIRED_MEASUREMENTS)
               + (len(plan.points) - len(executable)))
    deadline = MOCK_DEADLINE_FIXED_S + MOCK_DEADLINE_SECONDS_PER_RECORD * records
    typical = MOCK_ESTIMATE_FIXED_S + MOCK_ESTIMATE_SECONDS_PER_RECORD * records
    within = deadline <= MOCK_RUN_BUDGET_S
    reason = None if within else (
        f"the simulated run would write about {records} fsync'd records; its worst-case deadline {deadline:.0f} s "
        f"exceeds the {MOCK_RUN_BUDGET_S:.0f} s simulated-run budget (RuntimeMaxSec 2700 s minus margin); "
        "split the recipe or shorten its settling/acquisition windows")
    return {"records": records, "executable_points": len(executable), "phases": len(phases),
            "typical_s": typical, "deadline_s": deadline, "budget_s": MOCK_RUN_BUDGET_S,
            "within_budget": within, "reason": reason}


def mock_acquisition_seconds(plan: Plan) -> float:
    """Typical wall time of the simulated run (the counterpart of ``real_backend.acquisition_seconds``)."""
    return mock_run_estimate(plan)["typical_s"]


def live_step_count(start_V: float, target_V: float, step_V: float) -> int:
    """Count implicit ramp commands without constructing the requested list.

    Decimal keeps even a very small positive step from overflowing a float
    division. The tolerance matches the live-step sequence's endpoint rule.
    """
    span = abs(Decimal(str(target_V)) - Decimal(str(start_V)))
    if not span:
        return 0
    return max(1, int((span / Decimal(str(step_V)) - Decimal("1e-9")).to_integral_value(rounding=ROUND_CEILING)))


def phase_scoped_mock_estimate(plan: Plan) -> dict:
    """Budget UVLO/ramp/staircase evidence, including commands between observation levels.

    Every cycle writes the four electrical readings. Count polls without
    subtracting query time, so this is an upper estimate; each procedure
    also records one point event per level and its lifecycle events.
    """
    poll = Decimal(str(plan.recipe.acquisition.target_poll_interval_s))
    def polls(duration):
        return int((Decimal(str(duration)) / poll).to_integral_value(rounding=ROUND_CEILING))

    cycles, steps, levels = 0, 0, 0
    acquisition = max(polls(plan.recipe.acquisition.duration_s), plan.recipe.acquisition.minimum_complete_cycles)
    for test in plan.recipe.tests:
        policy = test.uvlo if test.type == UVLO_TEST_TYPE else test.supply_profile
        if policy is None or test.type not in (UVLO_TEST_TYPE, *SUPPLY_PROFILE_TEST_TYPES):
            raise ValueError("Phase-scoped budget requires UVLO or supply-profile tests")
        count = len(test.input_voltage_targets_V)
        levels += count
        cycles += polls(policy.startup_interval_s) + count * acquisition
        if test.type == RESET_STAIRCASE_TEST_TYPE:
            cycles += ((count + 1) // 2) * polls(policy.recovery_hold_s) + (count // 2) * polls(policy.low_hold_s)
        else:
            cycles += count * polls(plan.recipe.settling.minimum_dwell_s)
        if test.type == SLOW_SUPPLY_RAMP_TEST_TYPE:
            steps += sum(live_step_count(a, b, policy.step_V)
                         for a, b in zip(test.input_voltage_targets_V, test.input_voltage_targets_V[1:]))
    records = len(REQUIRED_MEASUREMENTS) * (cycles + steps) + 2 * levels + 12 * len(plan.recipe.tests)
    deadline = Decimal(str(MOCK_DEADLINE_FIXED_S)) + Decimal(str(MOCK_DEADLINE_SECONDS_PER_RECORD)) * records
    typical = Decimal(str(MOCK_ESTIMATE_FIXED_S)) + Decimal(str(MOCK_ESTIMATE_SECONDS_PER_RECORD)) * records
    # Avoid publishing nonfinite JSON values even for an extreme finite input.
    if not math.isfinite(float(deadline)) or not math.isfinite(float(typical)):
        raise ValueError("Simulated phase-scoped run volume exceeds the finite run budget; increase the step or poll interval")
    within = deadline <= MOCK_RUN_BUDGET_S
    reason = None if within else (
        f"the simulated phase-scoped run would write about {records} fsync'd records "
        f"({steps} intermediate ramp steps); its worst-case deadline {deadline:.0f} s exceeds the "
        f"{MOCK_RUN_BUDGET_S:.0f} s simulated-run budget (RuntimeMaxSec 2700 s minus margin); "
        "split the recipe, increase the ramp step or poll interval, or shorten its observation windows")
    return {"records": records, "live_steps": steps, "observation_levels": levels,
            "typical_s": float(typical), "deadline_s": float(deadline), "budget_s": MOCK_RUN_BUDGET_S,
            "within_budget": within, "reason": reason}


def require_phase_scoped_mock_budget(plan: Plan) -> dict:
    estimate = phase_scoped_mock_estimate(plan)
    if not estimate["within_budget"]:
        raise ValueError("Simulated run refused: " + estimate["reason"])
    return estimate


def best_effort_mock_estimate(plan: Plan) -> dict:
    """Budget a best-effort recipe's evidence conservatively: every second of declared stimulus is polled.

    Per test: the startup interval, then ``repeats`` times the whole declared
    stimulus (hold plus rest, drop plus recovery window, interruption plus
    recovery window) at the acquisition poll interval, plus a settling dwell
    and an acquisition window per declared level. Every cycle writes the four
    electrical readings; each level adds its point events, each repeat its
    command events, each test its lifecycle events.
    """
    poll = Decimal(str(plan.recipe.acquisition.target_poll_interval_s))

    def polls(duration):
        return int((Decimal(str(duration)) / poll).to_integral_value(rounding=ROUND_CEILING))

    cycles, levels, repeats_total = 0, 0, 0
    acquisition = max(polls(plan.recipe.acquisition.duration_s), plan.recipe.acquisition.minimum_complete_cycles)
    for test in plan.recipe.tests:
        policy = test.best_effort
        if policy is None or test.type not in BEST_EFFORT_TEST_TYPES:
            raise ValueError("Best-effort budget requires best-effort tests with their declared block")
        repeats = policy.repeats or 1
        if test.type == TRANSIENT_HOLD_TEST_TYPE:
            stimulus = (policy.hold_s or 0.0) + (policy.recovery_s or 0.0)
        elif test.type == MOMENTARY_DROP_TEST_TYPE:
            stimulus = (policy.drop_s or 0.0) + (policy.recovery_s or 0.0)
        else:
            stimulus = (policy.interruption_s or 0.0) + (policy.recovery_s or 0.0)
        count = len(test.input_voltage_targets_V)
        levels += count
        repeats_total += repeats
        startup = test.supply_profile.startup_interval_s if test.supply_profile is not None else 5.0
        cycles += polls(startup) + repeats * polls(stimulus) + count * (acquisition + polls(plan.recipe.settling.minimum_dwell_s))
    records = len(REQUIRED_MEASUREMENTS) * cycles + 2 * levels + 4 * repeats_total + 12 * len(plan.recipe.tests)
    deadline = Decimal(str(MOCK_DEADLINE_FIXED_S)) + Decimal(str(MOCK_DEADLINE_SECONDS_PER_RECORD)) * records
    typical = Decimal(str(MOCK_ESTIMATE_FIXED_S)) + Decimal(str(MOCK_ESTIMATE_SECONDS_PER_RECORD)) * records
    if not math.isfinite(float(deadline)) or not math.isfinite(float(typical)):
        raise ValueError("Simulated best-effort run volume exceeds the finite run budget; increase the poll interval")
    within = deadline <= MOCK_RUN_BUDGET_S
    reason = None if within else (
        f"the simulated best-effort run would write about {records} fsync'd records ({repeats_total} declared repeats polled "
        f"for their whole stimulus); its worst-case deadline {deadline:.0f} s exceeds the {MOCK_RUN_BUDGET_S:.0f} s simulated-run "
        "budget (RuntimeMaxSec 2700 s minus margin); split the recipe or increase the poll interval")
    return {"records": records, "declared_repeats": repeats_total, "observation_levels": levels,
            "typical_s": float(typical), "deadline_s": float(deadline), "budget_s": MOCK_RUN_BUDGET_S,
            "within_budget": within, "reason": reason}


def prepare_mock_plan(plan: Plan) -> tuple[Plan, list[str], float]:
    """Preview counterpart of ``real_backend.prepare_real_plan`` for a mock bench: the plan is returned
    unchanged (its hash stands), ``errors`` names why the simulated worker would refuse it, and the
    seconds are the typical wall-time estimate. Phase-scoped procedures include their intermediate
    commands and observation polls in the same evidence-volume budget."""
    if not verify_plan_hash(plan):
        raise ValueError("Plan hash mismatch")
    if plan.bench.mode != "mock":
        raise ValueError("prepare_mock_plan accepts mock bench profiles only")
    types = {test.type for test in plan.recipe.tests}
    if types <= {UVLO_TEST_TYPE, *SUPPLY_PROFILE_TEST_TYPES}:
        estimate = phase_scoped_mock_estimate(plan)
    elif types <= set(BEST_EFFORT_TEST_TYPES):
        estimate = best_effort_mock_estimate(plan)
    elif types == {"steady_state_load_sweep"}:
        estimate = mock_run_estimate(plan)
    else:
        return plan, [], 0.0
    errors = [] if estimate["within_budget"] else [f"Simulated run refused: {estimate['reason']}"]
    return plan, errors, estimate["typical_s"]


def build_plan(dut: DutProfile, bench: BenchProfile, recipe: TestRecipe) -> Plan:
    """Expand every requested point without opening connections or changing targets."""
    if recipe.dut_profile_id != dut.profile_id:
        raise ValueError("Recipe DUT identity does not match the selected DUT profile")
    # Real vs simulated is the bench's decision. A recipe that still carries a
    # (legacy) mode never changes it; a disagreement is recorded, not raised.
    mode_warnings = ([f"Recipe mode {recipe.execution_mode!r} ignored; the bench decides ({bench.mode})"]
                     if recipe.execution_mode not in (None, bench.mode) else [])
    points = []
    for test in recipe.tests:
        for index, vin in enumerate(test.input_voltage_targets_V):
            for iout in test.output_current_targets_A:
                points.append(_point(dut, bench, recipe, test, f"p{len(points)+1:04d}", vin, iout, index))
    plan = Plan(dut=dut.model_copy(deep=True), bench=bench.model_copy(deep=True),
                recipe=recipe.model_copy(deep=True), points=points, plan_hash="",
                warnings=["Planning estimates are not measurements or validated safety limits.",
                          "Unknown acceptance requirements remain not evaluated.",
                          "No-load input consumption must be measured; it is not inferred from output current.",
                          "Input voltage is measured at source terminals; input-lead losses are inside the reported path boundary."]
                         + mode_warnings)
    controls = bench.protective_controls
    if any(limit is not None for limit in (controls.dut_input_overvoltage_V,
            controls.dut_output_overvoltage_V, controls.output_overcurrent_A)):
        plan.warnings.append("Explicit voltage/current guards are inclusive planning ceilings (target <= guard); "
                             "this check does not establish physical operating headroom or transient protection.")
    plan.warnings.extend(known_behaviour_warnings(dut, recipe))
    if bench.mode == "mock" and all(test.type == "steady_state_load_sweep" for test in recipe.tests):
        estimate = mock_run_estimate(plan)
        text = (f"Simulated run estimate: about {estimate['records']} fsync'd records over {estimate['phases']} "
                f"input-voltage phase(s); roughly {estimate['typical_s']:.0f} s on an idle bench computer, "
                f"{estimate['deadline_s']:.0f} s worst-case deadline against the {estimate['budget_s']:.0f} s simulated-run budget.")
        if not estimate["within_budget"]:
            text += " The simulated worker refuses this plan: " + estimate["reason"] + "."
        plan.warnings.append(text)
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan
