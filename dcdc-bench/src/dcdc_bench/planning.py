"""Pure feasibility planning: preserve each request and explain every exclusion."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypeVar

import yaml

from .domain import (MOCK_THERMAL_ADAPTER, UVLO_TEST_TYPE, BenchProfile, Contract, DutProfile, Plan, PlannedPoint, TestDefinition,
                     TestRecipe)

Profile = TypeVar("Profile", bound=Contract)
REQUIRED_MEASUREMENTS = {"Vin_V": "V", "Iin_A": "A", "Vout_V": "V", "Iout_A": "A"}
# Procedure types with an implemented executor. Any other type fails planning.
IMPLEMENTED_TEST_TYPES = ("steady_state_load_sweep", UVLO_TEST_TYPE)


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


def _unsupported_capabilities(dut: DutProfile, bench: BenchProfile, test: TestDefinition) -> list[str]:
    reasons: list[str] = []
    if test.type not in IMPLEMENTED_TEST_TYPES:
        reasons.append(f"Test type {test.type!r} is not an implemented procedure")
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
           point_id: str, vin: float, iout: float) -> PlannedPoint:
    ratings, source, load, policy = dut.ratings, bench.source, bench.load, recipe.planning
    reasons = _unsupported_capabilities(dut, bench, test)
    types = {t.type for t in recipe.tests}
    if UVLO_TEST_TYPE in types and len(types) > 1:
        # The ramp is its own phase-scoped procedure; no executor runs it inside a load sweep.
        reasons.append("Recipe mixes uvlo_input_ramp with other test types; plan the UVLO ramp as a separate recipe")
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
        if iout > 0:
            estimated_iin = ((ratings.output_voltage_nominal_V * iout) / policy.efficiency_estimate_fraction + policy.auxiliary_input_power_estimate_W) / assumed_dut_vin
    else:
        reasons.append("Planning input voltage after wiring allowance must be positive, and source capabilities must be known")
    pout = ratings.output_voltage_nominal_V * iout
    if test.type == UVLO_TEST_TYPE:
        reasons.extend(uvlo_step_reasons(dut, test, vin))
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
    if physical_power is not None and pout > physical_power + 1e-12:
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
        missing = gaps + (missing_approvals(dut, bench) if recipe.execution_mode == "real" else [])
        reason = "UVLO input ramp is blocked by approvals: " + "; ".join(missing)
    elif recipe.execution_mode == "real":
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
    return PlannedPoint(point_id=point_id, test_id=test.id, vin_target_V=vin, iout_target_A=iout,
                        status=status, reason=reason, estimated_input_current_A=estimated_iin,
                        physical_input_power_limit_W=physical_power, planning_output_current_limit_A=planning_limit)


def build_plan(dut: DutProfile, bench: BenchProfile, recipe: TestRecipe) -> Plan:
    """Expand every requested point without opening connections or changing targets."""
    if recipe.dut_profile_id != dut.profile_id:
        raise ValueError("Recipe DUT identity does not match the selected DUT profile")
    if recipe.execution_mode != bench.mode:
        raise ValueError("Recipe and bench execution modes must match")
    points = []
    for test in recipe.tests:
        for vin in test.input_voltage_targets_V:
            for iout in test.output_current_targets_A:
                points.append(_point(dut, bench, recipe, test, f"p{len(points)+1:04d}", vin, iout))
    plan = Plan(dut=dut.model_copy(deep=True), bench=bench.model_copy(deep=True),
                recipe=recipe.model_copy(deep=True), points=points, plan_hash="",
                warnings=["Planning estimates are not measurements or validated safety limits.",
                          "Unknown acceptance requirements remain not evaluated.",
                          "No-load input consumption must be measured; it is not inferred from output current.",
                          "Input voltage is measured at source terminals; input-lead losses are inside the reported path boundary."])
    controls = bench.protective_controls
    if any(limit is not None for limit in (controls.dut_input_overvoltage_V,
            controls.dut_output_overvoltage_V, controls.output_overcurrent_A)):
        plan.warnings.append("Explicit voltage/current guards are inclusive planning ceilings (target <= guard); "
                             "this check does not establish physical operating headroom or transient protection.")
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan
