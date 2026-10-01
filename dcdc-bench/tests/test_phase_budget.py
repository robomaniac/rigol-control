"""Implicit ramp commands and long observation windows obey the mock worker budget."""
import pytest

from dcdc_bench.domain import SLOW_SUPPLY_RAMP_TEST_TYPE, TestRecipe
from dcdc_bench.planning import (MOCK_RUN_BUDGET_S, build_plan, phase_scoped_mock_estimate,
                                 prepare_mock_plan)
from dcdc_bench.services import default_plan
from dcdc_bench.standard_recipes import build_recipe
from dcdc_bench.supply_profiles import SupplyProfileProcedure, run_supply_profile_mock
from dcdc_bench.uvlo import UvloInputRampProcedure, run_uvlo_mock
from test_supply_profiles import RAMP_LEVELS, profiles
from test_uvlo import approved_plan


def test_small_ramp_step_is_refused_before_sequence_allocation_or_run_folder(tmp_path, monkeypatch):
    plan = build_plan(*profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS, step_V=1e-6))
    estimate = phase_scoped_mock_estimate(plan)
    assert estimate["live_steps"] == 8_000_000
    assert estimate["records"] > 32_000_000
    assert estimate["deadline_s"] > MOCK_RUN_BUDGET_S and not estimate["within_budget"]
    _, errors, seconds = prepare_mock_plan(plan)
    assert errors and "8000000 intermediate ramp steps" in errors[0]
    assert seconds == estimate["typical_s"] > 0

    def never_allocate(*args):
        raise AssertionError("An over-budget sequence must not be materialized")

    monkeypatch.setattr("dcdc_bench.supply_profiles.live_steps", never_allocate)
    with pytest.raises(ValueError, match="Simulated run refused"):
        SupplyProfileProcedure(plan)
    with pytest.raises(ValueError, match="Simulated run refused"):
        run_supply_profile_mock(plan, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_uvlo_acquisition_poll_count_is_budgeted_before_run_folder(tmp_path):
    base = approved_plan()
    base.recipe.acquisition.duration_s = 60.
    base.recipe.acquisition.target_poll_interval_s = .001
    plan = build_plan(base.dut, base.bench, base.recipe)
    _, errors, seconds = prepare_mock_plan(plan)
    assert errors and seconds > 0
    with pytest.raises(ValueError, match="Simulated run refused"):
        UvloInputRampProcedure(plan)
    with pytest.raises(ValueError, match="Simulated run refused"):
        run_uvlo_mock(plan, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("system", ["12V", "24V"])
@pytest.mark.parametrize("clause", ["4.5", "4.6.2"])
def test_standard_profile_defaults_fit_existing_mock_budget(system, clause):
    base = default_plan()
    recipe = TestRecipe.model_validate(build_recipe(clause, system, base.dut, base.bench))
    plan = build_plan(base.dut, base.bench, recipe)
    estimate = phase_scoped_mock_estimate(plan)
    _, errors, seconds = prepare_mock_plan(plan)
    assert not errors
    assert 0 < seconds == estimate["typical_s"]
    assert estimate["deadline_s"] < MOCK_RUN_BUDGET_S


def test_minimum_acquisition_cycle_count_is_part_of_phase_budget():
    base = approved_plan()
    before = phase_scoped_mock_estimate(base)
    base.recipe.acquisition.minimum_complete_cycles = 10_000
    plan = build_plan(base.dut, base.bench, base.recipe)
    after = phase_scoped_mock_estimate(plan)
    assert after["records"] >= 4 * len(plan.points) * 10_000
    assert after["records"] > before["records"]
    assert prepare_mock_plan(plan)[1]
