"""M0 acceptance cases: no test opens an instrument or imports its driver."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from dcdc_bench.domain import AccuracySpec, BenchProfile, DutProfile, MeasurementBinding, RawSample, ReportProfile, TestRecipe
from dcdc_bench.planning import build_plan, load_profile, verify_plan_hash

PROFILES = Path(__file__).resolve().parents[1] / "profiles"


@pytest.fixture
def profiles():
    return (
        load_profile(PROFILES / "dut/12t12-4a.yaml", DutProfile),
        load_profile(PROFILES / "bench/mock.yaml", BenchProfile),
        load_profile(PROFILES / "recipes/12t12-4a-quick.yaml", TestRecipe),
    )


def test_CORE01_owner_facts_are_separate_from_synthetic_fixtures(profiles):
    dut, bench, recipe = profiles
    assert dut.identity.model == "12T12-4A"
    assert dut.identity.brand_aliases == ["Cocar", "Ekylin", "Bgoodvision"]
    assert dut.ratings.origin == "user_supplied"
    assert not dut.ratings.verified_from_sample_label
    assert (dut.ratings.input_voltage_min_V, dut.ratings.input_voltage_max_V) == (9, 36)
    assert (dut.ratings.output_voltage_nominal_V, dut.ratings.output_current_rated_A, dut.ratings.output_power_rated_W) == (12, 4, 48)
    assert dut.construction.topology == "unknown"
    assert dut.construction.controller_part_number is None
    assert dut.acceptance.minimum_efficiency_pct is None
    assert not dut.execution_approval.real_hardware_enabled
    assert "SB60" not in dut.model_dump_json()
    assert not {"temperature_C", "case_temperature_C"}.intersection(bench.measurements)
    assert bench.source.physical_model is None
    assert recipe.execution_mode == "mock"


def test_CORE02_48w_rejected_at_every_requested_voltage_even_ideal_efficiency(profiles):
    dut, bench, _ = profiles
    recipe = load_profile(PROFILES / "recipes/12t12-4a-rated-grid.yaml", TestRecipe)
    recipe.planning.efficiency_estimate_fraction = 1.0
    recipe.planning.source_current_budget_fraction = 1.0
    recipe.tests[0].output_current_targets_A = [4.0]
    plan = build_plan(dut, bench, recipe)
    assert len(plan.points) == 12
    assert all(p.status == "unsupported" for p in plan.points)
    assert all("even at 100% efficiency" in p.reason for p in plan.points)
    assert max(p.physical_input_power_limit_W for p in plan.points) == 36
    assert all(p.iout_target_A == 4 for p in plan.points)


def test_CORE03_ch2_below_dut_minimum(profiles):
    dut, bench, recipe = profiles
    bench.source.channel = 2
    bench.source.max_voltage_V = 8.0
    bench.source.max_current_A = 10.0
    bench.source.max_power_W = 80.0
    bench.source.remote_sense_supported = True
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" for p in plan.points)
    assert all("below the DUT minimum" in p.reason for p in plan.points)


def test_CORE04_ch1_sense_rejected_but_load_sense_independent(profiles):
    dut, bench, recipe = profiles
    assert bench.source.remote_sense_supported is False
    assert bench.load.remote_sense_supported is True
    assert bench.load.remote_sense_required is True
    assert any(p.feasible for p in build_plan(dut, bench, recipe).points)
    bench.source.remote_sense_required = True
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" for p in plan.points)
    assert all("Source remote sense is required but unsupported" in p.reason for p in plan.points)


def test_CORE05_full_requests_retained_with_physical_and_assumption_reasons(profiles):
    dut, bench, recipe = profiles
    recipe.tests[0].input_voltage_targets_V = [12.0]
    recipe.tests[0].output_current_targets_A = [.5, .75, 1., 4.]
    plan = build_plan(dut, bench, recipe)
    assert [p.iout_target_A for p in plan.points] == [.5, .75, 1., 4.]
    assert [p.status for p in plan.points] == ["executable", "assumption_limited", "assumption_limited", "unsupported"]
    assert all(p.reason for p in plan.points)
    assert [p.point_id for p in plan.points] == ["p0001", "p0002", "p0003", "p0004"]


def test_CORE06_programming_accuracy_cannot_become_readback_accuracy():
    spec = AccuracySpec(applies_to="programming", reading_fraction=.001, offset=.01,
                        unit="A", source="example-only", conditions="CC programming range")
    with pytest.raises(ValidationError, match="not a readback"):
        MeasurementBinding(instrument_id="load", quantity="Iout_A", unit="A", location="dut_output", accuracy=spec)
    binding = MeasurementBinding(instrument_id="load", quantity="Iout_A", unit="A", location="dut_output", programming_accuracy=spec)
    assert binding.accuracy is None


def test_CORE07_second_dut_and_source_need_only_profiles(profiles):
    dut, bench, recipe = profiles
    dut.profile_id = "other-converter"
    dut.identity.model = "Different 5 V converter"
    dut.ratings.output_voltage_nominal_V = 5.0
    dut.ratings.output_current_rated_A = 3.0
    dut.ratings.output_power_rated_W = 15.0
    recipe.dut_profile_id = dut.profile_id
    recipe.tests[0].input_voltage_targets_V = [12.0, 24.0]
    recipe.tests[0].output_current_targets_A = [0., .5, 1., 3.]
    bench.source.instrument_id = "alternate-synthetic-source"
    bench.source.max_current_A = 3.0
    bench.source.max_power_W = 90.0
    for quantity in ("Vin_V", "Iin_A"):
        bench.measurements[quantity].instrument_id = bench.source.instrument_id
    plan = build_plan(dut, bench, recipe)
    assert all(p.feasible for p in plan.points)
    assert plan.points[-1].estimated_input_current_A == pytest.approx(15 / (.8 * 24))
    assert plan.dut.identity.model == "Different 5 V converter"


def test_RUN07_required_temperature_missing_is_unsupported_optional_not_invented(profiles):
    dut, bench, recipe = profiles
    recipe.tests[0].required_quantities.append("case_temperature_C")
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" for p in plan.points)
    assert all("Required measurement case_temperature_C is unavailable" in p.reason for p in plan.points)
    recipe.tests[0].required_quantities.remove("case_temperature_C")
    recipe.tests[0].optional_quantities.append("case_temperature_C")
    plan = build_plan(dut, bench, recipe)
    assert sum(p.feasible for p in plan.points) == 19
    assert "case_temperature_C" not in plan.bench.measurements


def test_quick_grid_and_planning_limits(profiles):
    dut, bench, recipe = profiles
    plan = build_plan(dut, bench, recipe)
    assert len(plan.points) == 21
    assert sum(p.feasible for p in plan.points) == 19
    assert all(p.estimated_input_current_A is None for p in plan.points if p.iout_target_A == 0)
    recipe.tests[0].input_voltage_targets_V = [9., 12., 24., 36.]
    recipe.tests[0].output_current_targets_A = [0.]
    plan = build_plan(dut, bench, recipe)
    assert [p.planning_output_current_limit_A for p in plan.points] == pytest.approx([.54, .72, 1.44, 2.16])


def test_plan_hash_covers_snapshots_and_decisions(profiles):
    plan = build_plan(*profiles)
    assert verify_plan_hash(plan)
    assert plan.plan_hash == build_plan(*profiles).plan_hash
    restored = type(plan).model_validate_json(plan.model_dump_json())
    assert verify_plan_hash(restored)
    restored.points[0].reason = "changed after arming"
    assert not verify_plan_hash(restored)
    profiles[0].identity.model = "change original after snapshot"
    assert plan.dut.identity.model == "12T12-4A"
    assert verify_plan_hash(plan)


def test_real_execution_never_claimed_ready_and_example_has_no_ratings_for_unknown_load(profiles):
    dut, bench, recipe = profiles
    bench.mode = "real"
    recipe.execution_mode = "real"
    plan = build_plan(dut, bench, recipe)
    assert not any(p.feasible for p in plan.points)
    blocked = [p for p in plan.points if p.status == "approval_blocked"]
    assert blocked
    for field in ("real_hardware_enabled", "wiring_and_polarity_confirmed", "protective_controls.approved"):
        assert all(f"{field} is false" in p.reason for p in blocked)
    dut.execution_approval.real_hardware_enabled = dut.execution_approval.wiring_and_polarity_confirmed = True
    bench.protective_controls.approved = True
    approved = [p for p in build_plan(dut, bench, recipe).points if p.status == "approval_blocked"]
    assert approved and all("fresh operator arming" in p.reason and "is false" not in p.reason for p in approved)
    example = load_profile(PROFILES / "bench/rigol.example.yaml", BenchProfile)
    assert example.load.physical_model is None
    assert example.load.max_current_A is None
    assert example.load.max_power_W is None
    assert example.source.endpoint is None


def test_mismatched_configuration_and_unsupported_test_fail_closed(profiles):
    dut, bench, recipe = profiles
    recipe.dut_profile_id = "wrong"
    with pytest.raises(ValueError, match="identity"):
        build_plan(dut, bench, recipe)
    recipe.dut_profile_id = dut.profile_id
    bench.mode = "real"
    with pytest.raises(ValueError, match="modes"):
        build_plan(dut, bench, recipe)
    bench.mode = "mock"
    recipe.tests[0].type = "unapproved_uvlo"
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" for p in plan.points)


def test_unknown_configuration_nonfinite_numbers_and_yaml_objects_rejected(profiles, tmp_path):
    dut, bench, recipe = profiles
    data = dut.model_dump()
    data["run_python"] = "untrusted"
    with pytest.raises(ValidationError, match="Extra inputs"):
        DutProfile.model_validate(data)
    with pytest.raises(ValidationError):
        recipe.tests[0].input_voltage_targets_V = [float("nan")]
    malicious = tmp_path / "evil.yaml"
    malicious.write_text("!!python/object/apply:os.system ['touch sentinel']")
    with pytest.raises(Exception, match="constructor"):
        load_profile(malicious, DutProfile)
    report = load_profile(PROFILES / "report/engineering.yaml", ReportProfile)
    assert not report.publication_enabled


def test_missing_raw_values_require_quality_reason():
    values = dict(sample_id="s1", run_id="r1", test_id="t1", point_id="p1", channel_id="CH1",
                  instrument_id="source", quantity="Vin_V", value=None, unit="V", location="source_terminals",
                  query_start_utc="2026-01-01T00:00:00Z", query_end_utc="2026-01-01T00:00:01Z",
                  query_start_monotonic_s=0., query_end_monotonic_s=1., acquisition_cycle_id="c1")
    with pytest.raises(ValidationError, match="quality reason"):
        RawSample(**values)
    assert RawSample(**values, quality_flags=["timeout"]).value is None
