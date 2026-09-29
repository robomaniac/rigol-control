"""Explicit profile guards constrain plans; these checks never open hardware."""
from collections import Counter

import pytest

from dcdc_bench.planning import build_plan, verify_plan_hash
from dcdc_bench.services import default_plan


def _profiles():
    base = default_plan()
    base.recipe.tests[0].input_voltage_targets_V = [24.]
    base.recipe.tests[0].output_current_targets_A = [.1]
    return base.dut, base.bench, base.recipe


def test_input_guard_blocks_only_exceeding_requested_points_without_wiring_credit():
    dut, bench, recipe = _profiles()
    recipe.tests[0].input_voltage_targets_V = [24., 30.]
    recipe.planning.input_wiring_drop_allowance_V = 5.
    bench.protective_controls.dut_input_overvoltage_V = 26.
    plan = build_plan(dut, bench, recipe)
    assert [point.vin_target_V for point in plan.points] == [24., 30.]
    assert [point.status for point in plan.points] == ["executable", "unsupported"]
    assert "input voltage 30 V" in plan.points[1].reason
    assert "guard 26 V" in plan.points[1].reason
    assert "without clipping" in plan.points[1].reason
    assert verify_plan_hash(plan)


def test_output_voltage_guard_blocks_nominal_output_even_at_no_load():
    dut, bench, recipe = _profiles()
    recipe.tests[0].output_current_targets_A = [0., .1]
    bench.protective_controls.dut_output_overvoltage_V = 11.9
    plan = build_plan(dut, bench, recipe)
    assert all(point.status == "unsupported" for point in plan.points)
    assert all("nominal output voltage 12 V" in point.reason and "guard 11.9 V" in point.reason
               for point in plan.points)


def test_current_guard_blocks_exceeding_load_without_lowering_request():
    dut, bench, recipe = _profiles()
    recipe.tests[0].output_current_targets_A = [.1, .15]
    bench.protective_controls.output_overcurrent_A = .12
    plan = build_plan(dut, bench, recipe)
    assert [point.iout_target_A for point in plan.points] == [.1, .15]
    assert [point.status for point in plan.points] == ["executable", "unsupported"]
    assert "output current 0.15 A" in plan.points[1].reason
    assert "guard 0.12 A" in plan.points[1].reason


@pytest.mark.parametrize("mode, status", [("mock", "executable"), ("real", "approval_blocked")])
def test_explicit_guard_equality_is_inclusive_but_does_not_approve_real_operation(mode, status):
    dut, bench, recipe = _profiles()
    bench.mode = recipe.execution_mode = mode
    controls = bench.protective_controls
    controls.dut_input_overvoltage_V = 24.
    controls.dut_output_overvoltage_V = 12.
    controls.output_overcurrent_A = .1
    plan = build_plan(dut, bench, recipe)
    assert plan.points[0].status == status
    assert any("inclusive planning ceilings" in warning for warning in plan.warnings)
    assert any("does not establish physical operating headroom" in warning for warning in plan.warnings)


def test_real_plan_guard_conflict_is_unsupported_before_approval():
    dut, bench, recipe = _profiles()
    bench.mode = recipe.execution_mode = "real"
    bench.protective_controls.output_overcurrent_A = .05
    plan = build_plan(dut, bench, recipe)
    assert plan.points[0].status == "unsupported"
    assert "guard 0.05 A" in plan.points[0].reason


def test_default_mock_coverage_is_preserved_without_explicit_guards():
    plan = default_plan()
    assert Counter(point.status for point in plan.points) == {"executable": 19, "assumption_limited": 2}
    assert len(plan.points) == 21


@pytest.mark.parametrize("loaded_only", [False, True])
def test_fixed_authorized_pilot_plan_stays_within_declared_guards(loaded_only):
    # Pure plan construction; run_bringup and instrument drivers are not called.
    from dcdc_bench.bringup import pilot_plan
    plan = pilot_plan(loaded_only=loaded_only)
    assert all(point.status == "executable" and point.vin_target_V == 24.
               and point.iout_target_A <= .1 for point in plan.points)
    assert plan.bench.protective_controls.source_current_limit_A == .15
    assert verify_plan_hash(plan)
