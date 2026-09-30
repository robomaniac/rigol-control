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
    recipe.tests[0].type = "unapproved_uvlo"
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" for p in plan.points)


def test_bench_decides_real_or_simulated_and_a_stale_recipe_mode_is_a_warning(profiles):
    """Real vs simulated comes from the bench only. A recipe that still carries a legacy
    execution_mode never raises; a disagreement is recorded in the plan (and its hash)."""
    dut, bench, recipe = profiles
    assert recipe.execution_mode == "mock"
    bench.mode = "real"
    plan = build_plan(dut, bench, recipe)
    assert plan.bench.mode == "real" and verify_plan_hash(plan)
    assert all(p.status in ("approval_blocked", "unsupported", "assumption_limited") for p in plan.points), \
        "the real bench, not the recipe's mock label, decides that approvals gate every point"
    assert any(p.status == "approval_blocked" and "real_hardware_enabled is false" in p.reason for p in plan.points)
    assert "Recipe mode 'mock' ignored; the bench decides (real)" in plan.warnings
    agreeing = build_plan(dut, bench, recipe.model_copy(update={"execution_mode": "real"}))
    assert not any("ignored" in w for w in agreeing.warnings)
    modeless = build_plan(dut, bench, recipe.model_copy(update={"execution_mode": None}))
    assert not any("ignored" in w for w in modeless.warnings)
    assert modeless.recipe.execution_mode is None
    assert len({plan.plan_hash, agreeing.plan_hash, modeless.plan_hash}) == 3, "the recipe snapshot and warning are hashed"
    bench.mode = "mock"
    assert all(p.status in ("executable", "assumption_limited") for p in build_plan(dut, bench, modeless.recipe).points)


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


def test_rigol_dp821a_dl3031a_profile_keeps_readback_and_programming_terms_apart():
    """The R1/R4 transcription: every bound channel carries a sourced readback term; programming terms stay programming."""
    bench = load_profile(PROFILES / "bench/rigol-dp821a-dl3031a.yaml", BenchProfile)
    assert bench.mode == "real"
    assert set(bench.measurements) == {"Vin_V", "Iin_A", "Vout_V", "Iout_A"}
    for name, binding in bench.measurements.items():
        assert binding.accuracy is not None, name
        assert binding.accuracy.applies_to == "readback", name
        assert binding.accuracy.source.strip() and binding.accuracy.conditions.strip(), name
        assert binding.measurement_range and binding.resolution, name
        assert binding.readback_specification.status == "datasheet_quoted", name
        assert binding.readback_specification.calibration.status == "unknown", name
        if binding.programming_accuracy is not None:
            assert binding.programming_accuracy.applies_to == "programming", name
    for instrument in (bench.source, bench.load):
        assert instrument.programming_accuracy
        assert all(spec.applies_to == "programming" and spec.source.strip() for spec in instrument.programming_accuracy.values())
        assert instrument.endpoint is None and instrument.reported_identity is None and instrument.physical_model is None
        assert not instrument.capabilities_confirmed
    assert not bench.protective_controls.approved and bench.protective_controls.policy_id is None
    # R1 printed p. 5: CH1 current readback (0.15 % + 10 mA) differs from programming (0.2 % + 10 mA).
    assert bench.measurements["Iin_A"].accuracy.reading_fraction == pytest.approx(0.0015)
    assert bench.measurements["Iin_A"].programming_accuracy.reading_fraction == pytest.approx(0.002)
    # R4 printed p. 4: current readback uses the documented 60 A readback full scale, not a CC programming range.
    assert bench.measurements["Iout_A"].accuracy.full_scale == 60.0
    assert bench.measurements["Iout_A"].programming_accuracy is None
    assert set(bench.load.programming_accuracy) == {"cc_current_range_0_6A", "cc_current_range_0_60A"}
    # The schema rejects a programming term offered as readback, so the file cannot be mislabeled silently.
    data = bench.model_dump()
    data["measurements"]["Vin_V"]["accuracy"]["applies_to"] = "programming"
    with pytest.raises(ValidationError, match="not a readback"):
        BenchProfile.model_validate(data)


# --- ISO 16750-2 supply profiles: mock-only test types and the generated clause 4.2 sweep ---------------

def _supply_profile_recipe(recipe, kind, levels, *, approved=True, policy_id="synthetic-uvlo-ramp-v1", **overrides):
    from dcdc_bench.domain import SupplyProfilePolicy, TestDefinition
    values = dict(floor_V=min(levels), startup_interval_s=1., output_on_minimum_V=10.8, output_off_maximum_V=1.2,
                  expected_off_below_V=9., expected_on_above_V=9.)
    if kind == "slow_supply_ramp":
        values.update(step_V=.5, step_interval_s=1.)
    else:
        values.update(low_hold_s=5., recovery_hold_s=10.)
    values.update(overrides)
    recipe = recipe.model_copy(deep=True)
    recipe.execution_mode = None
    recipe.tests = [TestDefinition(id="profile", type=kind, input_voltage_targets_V=list(levels), output_current_targets_A=[.1],
                                   supply_profile=SupplyProfilePolicy(**values))]
    recipe.authorization.uvlo_approved = approved
    recipe.authorization.protective_policy_id = policy_id if approved else None
    return recipe


def _declare_policy(bench, policy_id="synthetic-uvlo-ramp-v1"):
    bench = bench.model_copy(deep=True)
    bench.protective_controls.policy_id = policy_id
    bench.protective_controls.source_current_limit_A = .5
    bench.protective_controls.dut_output_overvoltage_V = 13.2
    bench.protective_controls.output_overcurrent_A = .15
    return bench


def test_supply_profile_contracts_validate_their_shape_and_policy():
    from dcdc_bench.domain import SupplyProfilePolicy, TestDefinition, staircase_level_kinds
    assert staircase_level_kinds([10., 9.5, 10., 9., 10.]) == ["recovery", "low", "recovery", "low", "recovery"]
    for bad in ([10., 9.5], [10., 9.5, 10., 9.], [10., 9.5, 9.9, 9., 10.], [10., 9., 10., 9.5, 10.], [10., 10.5, 10.]):
        with pytest.raises(ValueError):
            staircase_level_kinds(bad)
    policy = SupplyProfilePolicy(floor_V=1., startup_interval_s=5., output_on_minimum_V=10.8, output_off_maximum_V=1.2,
                                 expected_off_below_V=9., expected_on_above_V=9., step_V=.02, step_interval_s=2.4)
    assert policy.ramp_rate_V_per_min == pytest.approx(.5)
    assert policy.off_expected(8.5, "down") and policy.off_expected(8.5, "low") and not policy.off_expected(9., "up")
    with pytest.raises(ValidationError, match="declared together"):
        SupplyProfilePolicy(floor_V=1., startup_interval_s=5., output_on_minimum_V=10.8, output_off_maximum_V=1.2,
                            expected_off_below_V=9., expected_on_above_V=9., step_V=.02)
    with pytest.raises(ValidationError, match="requires a declared supply_profile block"):
        TestDefinition(id="t", type="slow_supply_ramp", input_voltage_targets_V=[12., 9., 12.], output_current_targets_A=[.1])
    with pytest.raises(ValidationError, match="step_V and step_interval_s"):
        TestDefinition(id="t", type="slow_supply_ramp", input_voltage_targets_V=[12., 9., 12.], output_current_targets_A=[.1],
                       supply_profile=policy.model_copy(update={"step_V": None, "step_interval_s": None}))
    with pytest.raises(ValidationError, match="odd number of levels"):
        TestDefinition(id="t", type="reset_staircase", input_voltage_targets_V=[10., 9.5], output_current_targets_A=[.1],
                       supply_profile=policy.model_copy(update={"step_V": None, "step_interval_s": None, "low_hold_s": 5., "recovery_hold_s": 10.}))
    with pytest.raises(ValidationError, match="only valid for the slow_supply_ramp"):
        TestDefinition(id="t", input_voltage_targets_V=[24.], output_current_targets_A=[.1], supply_profile=policy)
    # An existing DUT profile validates unchanged and simply gains the optional class.
    dut = DutProfile.model_validate(load_profile(PROFILES / "dut/12t12-4a.yaml", DutProfile).model_dump(exclude={"system_voltage_class"}))
    assert dut.system_voltage_class is None and "system_voltage_class" in dut.model_dump()


def test_supply_profile_types_plan_on_the_mock_and_are_refused_on_a_real_bench(profiles):
    dut, bench, recipe = profiles
    bench = _declare_policy(bench)
    ramp = _supply_profile_recipe(recipe, "slow_supply_ramp", [12., 11., 10., 9., 8., 9., 10., 11., 12.])
    plan = build_plan(dut, bench, ramp)
    assert [p.status for p in plan.points] == ["executable"] * 9 and verify_plan_hash(plan)
    low = plan.points[4]
    assert low.vin_target_V == 8. and "down level of the slow supply ramp" in low.reason
    assert "output-off is the DUT's documented expectation" in low.reason and low.planning_output_current_limit_A is None
    assert low.estimated_input_current_A is None, "a standby draw is unknown, not estimated from the output"
    assert "up level" in plan.points[6].reason and plan.points[6].planning_output_current_limit_A is not None
    stair = _supply_profile_recipe(recipe, "reset_staircase", [10., 9.5, 10., 9., 10., 8.5, 10., 8., 10.])
    plan = build_plan(dut, bench, stair)
    assert all(p.status == "executable" for p in plan.points)
    assert "recovery level of the reset staircase" in plan.points[0].reason and "low level" in plan.points[1].reason
    # Below the declared floor: refused, never clipped. Above the DUT maximum: refused.
    plan = build_plan(dut, bench, _supply_profile_recipe(recipe, "slow_supply_ramp", [12., 9., 7., 9., 12.], floor_V=8.))
    assert plan.points[2].status == "unsupported" and "below the declared supply-profile floor 8 V" in plan.points[2].reason
    assert [p.status for p in plan.points] == ["executable"] * 2 + ["unsupported"] + ["executable"] * 2
    plan = build_plan(dut, bench, _supply_profile_recipe(recipe, "reset_staircase", [37., 9., 37.]))
    assert all(p.status == "unsupported" and "recovery level must lie inside" in p.reason for p in plan.points[0::2])
    # Below the DUT minimum without the approved UVLO-style authorization: every level is approval_blocked.
    unapproved = build_plan(dut, bench, _supply_profile_recipe(recipe, "slow_supply_ramp", [12., 9., 8., 9., 12.], approved=False))
    assert all(p.status == "approval_blocked" for p in unapproved.points)
    assert all("approved UVLO-style path" in p.reason and "uvlo_approved is false" in p.reason for p in unapproved.points)
    inside = build_plan(dut, bench, _supply_profile_recipe(recipe, "slow_supply_ramp", [12., 10., 9., 10., 12.], approved=False))
    assert all(p.status == "executable" for p in inside.points), "a profile that stays inside the DUT rating needs no excursion approval"
    # Mixed with another test type: no executor; every point says so.
    mixed = ramp.model_copy(deep=True)
    mixed.tests = mixed.tests + [recipe.tests[0]]
    plan = build_plan(dut, bench, mixed)
    assert all(p.status == "unsupported" and "mixes slow_supply_ramp with other test types" in p.reason for p in plan.points)
    # Real bench: not yet approved for real hardware, in the planner and in the real backend's preview.
    real = bench.model_copy(deep=True)
    real.mode = "real"
    plan = build_plan(dut, real, ramp)
    assert all(p.status == "unsupported" for p in plan.points)
    assert all("'slow_supply_ramp' is not yet approved for real hardware" in p.reason for p in plan.points)
    from dcdc_bench.real_backend import prepare_real_plan
    _, errors, _ = prepare_real_plan(plan)
    assert any("not yet approved for real hardware" in error for error in errors)
    from dcdc_bench.runner import run_mock
    with pytest.raises(ValueError, match="steady_state_load_sweep tests only"):
        run_mock(build_plan(dut, bench, ramp), PROFILES.parent / "never-created")


def test_iso16750_2_clause_4_2_recipe_keeps_out_of_envelope_levels_as_unsupported(profiles):
    """The generated 4.2 sweep requests UA, Usmin and Usmax; a level above the guard stays in the plan with the planner's reason."""
    from dcdc_bench.standard_recipes import build_recipe
    dut, bench, _ = profiles
    guarded = bench.model_copy(deep=True)
    guarded.protective_controls.dut_input_overvoltage_V = 26.
    recipe = TestRecipe.model_validate(build_recipe("4.2", "24V", dut, guarded))
    assert recipe.tests[0].type == "steady_state_load_sweep" and recipe.tests[0].input_voltage_targets_V == [28., 10., 32.]
    assert recipe.title == "ISO 16750-2 §4.2 — supply voltage range (24 V system)"
    assert recipe.category == "ISO 16750-2 supply profiles" and recipe.standard_clause == "ISO 16750-2:2023 §4.2"
    plan = build_plan(dut, guarded, recipe)
    assert len(plan.points) == 9, "every requested level x load stays in the plan"
    above = [p for p in plan.points if p.vin_target_V in (28., 32.)]
    assert len(above) == 6 and all(p.status == "unsupported" for p in above), "UA and Usmax of a 24 V system both exceed a 26 V guard"
    assert all(f"Requested input voltage {p.vin_target_V:g} V exceeds the configured input voltage guard 26 V; request retained "
               "without clipping" in p.reason for p in above)
    assert all(p.status == "executable" for p in plan.points if p.vin_target_V == 10.)
    twelve = TestRecipe.model_validate(build_recipe("4.2", "12V", dut, bench))
    assert twelve.tests[0].input_voltage_targets_V == [14., 9., 16.]
    assert all(p.status == "executable" for p in build_plan(dut, bench, twelve).points)
    # The mock-only profiles ship unapproved: below-minimum levels plan as approval_blocked until the owner approves.
    staircase = TestRecipe.model_validate(build_recipe("4.6.2", "12V", dut, bench))
    assert staircase.tests[0].type == "reset_staircase" and staircase.tests[0].input_voltage_targets_V[:4] == [9., 8.55, 9., 8.1]
    assert staircase.tests[0].input_voltage_targets_V[-2:] == [.45, 9.] and 0. not in staircase.tests[0].input_voltage_targets_V
    assert staircase.authorization.uvlo_approved is False and staircase.authorization.protective_policy_id is None
    assert {p.status for p in build_plan(dut, bench, staircase).points} == {"approval_blocked"}
    ramp = TestRecipe.model_validate(build_recipe("4.5", "24V", dut, bench))
    levels = ramp.tests[0].input_voltage_targets_V
    assert levels[0] == levels[-1] == 28. and min(levels) == 1. and len(levels) == 55
    assert ramp.tests[0].supply_profile.step_V == .02 and ramp.tests[0].supply_profile.step_interval_s == 2.4
    assert ramp.tests[0].supply_profile.expected_off_below_V == 9. == ramp.tests[0].supply_profile.expected_on_above_V
