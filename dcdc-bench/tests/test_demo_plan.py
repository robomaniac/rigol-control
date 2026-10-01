"""The demonstration set's fourth plan: the best-effort jump start, approved for the demonstration only."""
from dcdc_bench.planning import best_effort_approval_gaps, prepare_mock_plan
from dcdc_bench.services import BEST_EFFORT_DEMO_POLICY_ID, best_effort_demo_plan, default_plan


def test_best_effort_demo_plan_is_approved_for_the_demonstration_only():
    plan = best_effort_demo_plan()
    test = plan.recipe.tests[0]
    assert plan.bench.mode == "mock" and [t.type for t in plan.recipe.tests] == ["transient_hold"]
    assert test.best_effort.clause == "4.3.1.2" and test.input_voltage_targets_V == [10.8, 26.0]
    assert test.best_effort.hold_s == 60.0 and test.best_effort.recovery_s == 120.0 and test.best_effort.repeats == 1
    assert all(point.status == "executable" for point in plan.points), [(p.point_id, p.status, p.reason) for p in plan.points]
    assert not best_effort_approval_gaps(plan.bench, plan.recipe)
    _, errors, seconds = prepare_mock_plan(plan)
    assert not errors and seconds > 0
    # A copy is approved; the saved mock bench and the generated recipe on disk stay as they are.
    saved = default_plan()
    assert saved.bench.protective_controls.policy_id != BEST_EFFORT_DEMO_POLICY_ID
    assert saved.recipe.authorization.best_effort_approved is False
