"""ISO 16750-2 supply profiles (slow ramp, reset staircase) on the synthetic plant only.

No test here opens an instrument or imports a real driver. The mock path is
in-process with a virtual clock; every run ends with a verified-OFF shutdown.
"""
from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest

from dcdc_bench import domain
from dcdc_bench.analysis import analyze_run, build_report_model, level_observation
from dcdc_bench.domain import RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE, Plan
from dcdc_bench.mock_uvlo import SyntheticUvlo
from dcdc_bench.planning import build_plan
from dcdc_bench.services import acquire_mock, default_plan
from dcdc_bench.storage import verify_integrity
from dcdc_bench.supply_profiles import SupplyProfileProcedure, live_steps, run_supply_profile_mock

POLICY_ID = "synthetic-uvlo-ramp-v1"
RAMP_LEVELS = [12., 11., 10., 9., 8., 9., 10., 11., 12.]
STAIRCASE_LEVELS = [10., 9.5, 10., 9., 10., 8.5, 10., 8., 10.]
LOAD_A = .1


def profiles(kind, levels, *, approved=True, mode="mock", **policy_overrides):
    """Copies of the saved mock profiles with one supply-profile test; unique instrument ids keep the mock locks apart."""
    base = default_plan()
    dut, bench, recipe = (item.model_copy(deep=True) for item in (base.dut, base.bench, base.recipe))
    suffix = uuid.uuid4().hex
    bench.source.instrument_id += suffix
    bench.load.instrument_id += suffix
    for quantity, binding in bench.measurements.items():
        binding.instrument_id = bench.source.instrument_id if quantity in ("Vin_V", "Iin_A") else bench.load.instrument_id
    bench.mode, recipe.execution_mode = mode, None
    bench.protective_controls.policy_id = POLICY_ID
    bench.protective_controls.source_current_limit_A = .5
    bench.protective_controls.dut_output_overvoltage_V = 13.2
    bench.protective_controls.output_overcurrent_A = .15
    values = dict(floor_V=min(levels), startup_interval_s=.3, output_on_minimum_V=10.8, output_off_maximum_V=1.2,
                  expected_off_below_V=9., expected_on_above_V=10.)
    if kind == SLOW_SUPPLY_RAMP_TEST_TYPE:
        values.update(step_V=.5, step_interval_s=1.)
    else:
        values.update(low_hold_s=1., recovery_hold_s=1.5)
    values.update(policy_overrides)
    recipe.tests = [domain.TestDefinition(id="profile", type=kind, input_voltage_targets_V=list(levels),
                                          output_current_targets_A=[LOAD_A], supply_profile=domain.SupplyProfilePolicy(**values))]
    recipe.standard_clause = "ISO 16750-2:2023 §4.5" if kind == SLOW_SUPPLY_RAMP_TEST_TYPE else "ISO 16750-2:2023 §4.6.2"
    recipe.authorization.uvlo_approved = approved
    recipe.authorization.protective_policy_id = POLICY_ID if approved else None
    recipe.settling.minimum_dwell_s = 1.
    recipe.acquisition.duration_s = .3
    recipe.acquisition.target_poll_interval_s = .25
    recipe.acquisition.minimum_complete_cycles = 3
    return dut, bench, recipe


def evidence(path):
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines() if line]
    return run, samples


def verified_off(run):
    return all(record.get("state") == "OFF" and record.get("verified") is True for record in run["shutdown"].values())


def report(path, run, samples):
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    plan = Plan.model_validate_json((path / "plan.json").read_text())
    return analysis, build_report_model(plan, run, analysis, samples)


@pytest.fixture(scope="module")
def ramp_run(tmp_path_factory):
    plan = build_plan(*profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS))
    path = run_supply_profile_mock(plan, tmp_path_factory.mktemp("ramp"))
    run, samples = evidence(path)
    return plan, path, run, samples


@pytest.fixture(scope="module")
def staircase_run(tmp_path_factory):
    plan = build_plan(*profiles(RESET_STAIRCASE_TEST_TYPE, STAIRCASE_LEVELS))
    path = run_supply_profile_mock(plan, tmp_path_factory.mktemp("staircase"))
    run, samples = evidence(path)
    return plan, path, run, samples


def test_live_steps_are_bounded_and_land_exactly_on_the_target():
    assert live_steps(12., 11., .5) == [11.5, 11.]
    assert live_steps(11., 12., .5) == [11.5, 12.]
    assert live_steps(9., 8.3, .5) == [8.5, 8.3], "the last step is shortened, never overshot"
    assert live_steps(14., 13., .02)[:3] == [13.98, 13.96, 13.94] and len(live_steps(14., 13., .02)) == 50
    assert live_steps(9., 9., .5) == []


def test_procedure_refuses_what_the_planner_did_not_approve(tmp_path):
    dut, bench, recipe = profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS, approved=False)
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "approval_blocked" for p in plan.points)
    with pytest.raises(ValueError, match="approved UVLO-style path"):
        SupplyProfileProcedure(plan)
    with pytest.raises(ValueError, match="not executable"):
        SupplyProfileProcedure(build_plan(*profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, [12., 9., 7., 9., 12.], floor_V=8.)))
    real = build_plan(*profiles(RESET_STAIRCASE_TEST_TYPE, STAIRCASE_LEVELS, mode="real"))
    assert all(p.status == "unsupported" and "not yet approved for real hardware" in p.reason for p in real.points)
    with pytest.raises(ValueError, match="mock profiles only"):
        run_supply_profile_mock(real, tmp_path)
    assert not list(tmp_path.iterdir())
    procedure = SupplyProfileProcedure(build_plan(*profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS)))
    assert isinstance(procedure, domain.TestProcedure)
    method = procedure.metadata()["method"]["supply_profile"]
    assert method["type"] == SLOW_SUPPLY_RAMP_TEST_TYPE and method["cadence"]["rate_V_per_min"] == pytest.approx(30.)
    assert method["tests"]["profile"]["live_steps_between_levels"] == 16
    assert "ignore_safety" not in json.dumps(procedure.metadata())
    assert any("not approved for real hardware" in note for note in procedure.metadata()["metrology_limitations"])


def test_slow_ramp_runs_end_to_end_with_every_level_qualified_and_live_steps_guarded(ramp_run):
    plan, path, run, samples = ramp_run
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["real_hardware_opened"] is False and run["data_source"] == "simulated" and run["clock"]["mode"] == "virtual"
    assert run["scenario"] == "ISO 16750-2 slow supply ramp (clause 4.5 profile) as bounded DC steps (synthetic plant)"
    assert run["run_id"].split("_")[1] == "ramp"
    observed = [(p["vin_target_V"], p["level_kind"], p["output_state"]) for p in run["points"]]
    assert observed == [(12., "down", "on"), (11., "down", "on"), (10., "down", "on"), (9., "down", "on"), (8., "down", "off"),
                        (9., "up", "off"), (10., "up", "on"), (11., "up", "on"), (12., "up", "on")]
    assert all(p["qualification"] == "valid" for p in run["points"])
    assert [p["observation"] for p in run["points"]][4:7] == [
        "reset: output off (documented expectation below the declared boundary)",
        "output still off on the increase (documented expectation below the declared boundary)",
        "recovered: output back in band"]
    assert all(p["hold_s"] == 1. for p in run["points"]) and [p["live_steps_from_previous_level"] for p in run["points"]] == [0] + [2] * 8
    assert run["method"]["supply_profile"]["tests"]["profile"]["live_steps_commanded"] == 16
    ramping = [s for s in samples if s["phase"] == "ramping"]
    assert len(ramping) == 16 * 4, "one guarded cycle per live step, preserved as raw evidence"
    accepted = {c for p in run["points"] for c in p["acquisition_cycle_ids"]}
    assert not {s["acquisition_cycle_id"] for s in ramping} & accepted, "live-step readings are never qualified points"
    assert {s["acquisition_settings"]["procedure_stage"] for s in ramping} == {"ramp-down", "ramp-up"}
    off = next(p for p in run["points"] if p["output_state"] == "off")
    assert off["output_off_expected"] and not off["minimum_vout_rule_applied"] and not off["load_current_established"]
    assert run["executed_point_ids"] == [p["point_id"] for p in run["points"]] and verified_off(run)
    assert run["raw_sample_count"] == len(samples)
    # Deterministic under the virtual clock and seeded plant: a second run reproduces every accepted mean.
    again = run_supply_profile_mock(plan, path.parent)
    other, _ = evidence(again)
    assert [p["accepted_means"] for p in other["points"]] == [p["accepted_means"] for p in run["points"]]
    assert other["duration_s"] == run["duration_s"]


def test_slow_ramp_report_states_each_level_and_is_honest_about_the_cadence(ramp_run):
    plan, path, run, samples = ramp_run
    analysis, model = report(path, run, samples)
    detail = analysis["supply_profiles"]["profile"]
    assert detail["type"] == SLOW_SUPPLY_RAMP_TEST_TYPE and detail["synthetic"] is True and detail["clause"] == "ISO 16750-2:2023 §4.5"
    assert [level["observation"] for level in detail["levels"]][3:7] == [
        "output in band", "reset: output off (documented expectation below the declared boundary)",
        "output still off on the increase (documented expectation below the declared boundary)", "recovered: output back in band"]
    statements = detail["statements"]
    assert statements[0] == "Synthetic plant: decreasing from 12 V, the output was in band from 12 V to 9 V; off (reset) at 8 V."
    assert statements[1] == "Increasing to 12 V, the output was off (reset) at 9 V; in band from 10 V to 12 V."
    assert any(s.startswith("The output was back in band at 10 V on the increase") for s in statements)
    assert any("500 mV live steps held 1 s (30 V/min)" in s and "~1 s command cadence" in s and "no edge, drop or transient is measured" in s
               for s in statements)
    assert any("continues to 0 V, which is not a positive source setpoint" in s for s in statements)
    assert (detail["turn_off"]["upper_V"], detail["turn_off"]["lower_V"]) == (9., 8.) and detail["exact_threshold_V"] is None
    assert (detail["turn_on"]["lower_V"], detail["turn_on"]["upper_V"]) == (9., 10.)
    for point in analysis["points"]:
        if point["output_state"] == "off":
            assert point["efficiency_pct"] is None and "not an efficiency point" in point["efficiency_reason"]
            assert point["requirements"]["output_voltage"] == "not-applicable" and point["level_observation"].startswith(("reset", "output still off"))
        else:
            assert point["efficiency_pct"] is not None and 0 < point["efficiency_pct"] < 100
    assert model.evidence_label == "SYNTHETIC"
    figure = next(f for f in model.figures if f.id == "fig-profile-profile")
    assert figure.x_key == "Vin_V" and len(figure.series[0].point_ids) == 9 and "SYNTHETIC" in figure.caption
    assert any(text.startswith("ISO 16750-2 slow supply ramp (clause 4.5 profile) 'profile' at 100 mA. Synthetic plant:") for text in model.summary)
    assert any("went off between 9 V (last in band) and 8 V (first off)" in text and "no threshold value is claimed" in text
               for text in model.summary)
    assert any("a staircase, not a linear ramp" in note for note in model.method.procedure_notes)
    assert any("simulation parameters, not characteristics of the DUT" in note for note in model.method.procedure_notes)
    assert not any(m.id.startswith(("line-span", "load-span")) for m in model.metrics)
    assert model.execution["supply_profiles"]["profile"]["turn_off"] == detail["turn_off"]
    assert analysis["coverage"] == {"profile": {"requested": 9, "valid": 9}}


def test_reset_staircase_runs_end_to_end_and_reports_reset_and_recovery_per_level(staircase_run):
    plan, path, run, samples = staircase_run
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["scenario"] == "ISO 16750-2 reset staircase (clause 4.6.2 profile) as bounded DC steps (synthetic plant)"
    assert run["run_id"].split("_")[1] == "staircase"
    observed = [(p["vin_target_V"], p["level_kind"], p["output_state"]) for p in run["points"]]
    assert observed == [(10., "recovery", "on"), (9.5, "low", "on"), (10., "recovery", "on"), (9., "low", "on"), (10., "recovery", "on"),
                        (8.5, "low", "off"), (10., "recovery", "on"), (8., "low", "off"), (10., "recovery", "on")]
    assert [p["hold_s"] for p in run["points"]] == [1.5, 1., 1.5, 1., 1.5, 1., 1.5, 1., 1.5], "declared low and recovery holds"
    assert all(p["ramp_phase"] is None for p in run["points"]) and all(p["qualification"] == "valid" for p in run["points"])
    assert [p["observation"] for p in run["points"]][5:7] == [
        "reset: output off (documented expectation below the declared boundary)", "recovered: output back in band"]
    assert not [s for s in samples if s["phase"] == "ramping"], "a staircase level is one live step, no intermediate walk"
    assert verified_off(run)
    analysis, model = report(path, run, samples)
    detail = analysis["supply_profiles"]["profile"]
    assert detail["type"] == RESET_STAIRCASE_TEST_TYPE and "turn_off" not in detail
    statements = detail["statements"]
    assert statements[0] == "Synthetic plant: at the low levels the output was in band at the 9.5 V, 9 V lows; off (reset) at the 8.5 V, 8 V lows."
    assert statements[1] == "At the 10 V recovery level after a low the output was back in band 4 of 4 times."
    assert any("Each low was held 1 s and each recovery 1.5 s before acquisition" in s and "~1 s command cadence" in s for s in statements)
    assert any(text.startswith("ISO 16750-2 reset staircase (clause 4.6.2 profile) 'profile' at 100 mA.") for text in model.summary)
    assert any("Each low level is held 1 s and each recovery level 1.5 s" in note for note in model.method.procedure_notes)
    assert analysis["coverage"] == {"profile": {"requested": 9, "valid": 9}}


def test_staircase_that_does_not_recover_stops_at_the_recovery_level_with_the_cause_unclassified(tmp_path):
    """An output that stays off at a recovery level, where the policy expects it on, stops the run (brief 7.5): the level is
    inconclusive with the cause unclassified, later levels are not run, and the report says so."""
    dut, bench, recipe = profiles(RESET_STAIRCASE_TEST_TYPE, [9.5, 8.55, 9.5, 8.1, 9.5], expected_off_below_V=9., expected_on_above_V=9.)
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "executable" for p in plan.points)

    def output_stays_off_after_the_first_low(quantity, value, point, phase):
        return 0. if quantity == "Vout_V" and point["point_id"] == "p0003" else value

    path = run_supply_profile_mock(plan, tmp_path, reading_override=output_stays_off_after_the_first_low)
    run, samples = evidence(path)
    assert run["execution_status"] == "aborted" and run["stop"]["classification"] == "normal-regulation-rule"
    assert run["stop"]["level_kind"] == "recovery" and run["stop"]["output_off_expected"] is False
    stopped = next(p for p in run["points"] if p["point_id"] == run["stop"]["point_id"])
    assert stopped["vin_target_V"] == 9.5 and stopped["level_kind"] == "recovery" and stopped["qualification"] == "inconclusive"
    assert "below the 10.8 V minimum outside the declared expected-off phase; cause unclassified" in stopped["reason"]
    assert [p["qualification"] for p in run["points"]] == ["valid", "valid", "inconclusive", "not-run", "not-run"]
    assert run["points"][1]["output_state"] == "off" and run["points"][1]["observation"].startswith("reset: output off")
    assert verified_off(run)
    analysis, model = report(path, run, samples)
    statements = analysis["supply_profiles"]["profile"]["statements"]
    assert any(s.startswith("The run stopped at the 9.5 V recovery level (normal-regulation-rule)") and "Later levels were not run" in s
               for s in statements)
    assert "not qualified at 8.1 V" in statements[0] and "back in band 0 of 0 times" in statements[1]
    assert any("The run stopped at the 9.5 V recovery level" in text for text in model.summary)
    # The same staircase without the injected reading completes: the synthetic plant restarts at 9.5 V (its turn-on is 9.1 V).
    run2, _ = evidence(run_supply_profile_mock(plan, tmp_path))
    assert run2["execution_status"] == "completed"
    assert [p["observation"] for p in run2["points"]] == ["output in band", "reset: output off (documented expectation below the declared boundary)",
                                                          "recovered: output back in band", "reset: output off (documented expectation below the declared boundary)",
                                                          "recovered: output back in band"]
    # A recovery level the synthetic plant cannot restart at (9 V is below its 9.1 V turn-on) never gets past the unloaded startup.
    cold = build_plan(*profiles(RESET_STAIRCASE_TEST_TYPE, [9., 8.55, 9.], expected_off_below_V=9., expected_on_above_V=9.))
    run3, _ = evidence(run_supply_profile_mock(cold, tmp_path, synthetic=SyntheticUvlo(turn_off_below_V=8.6, hysteresis_V=.5)))
    assert run3["execution_status"] == "aborted" and "did not reach 10.8 V within the 0.3 s startup interval" in run3["errors"][0]
    assert run3["method"]["supply_profile"]["tests"]["profile"]["startup"]["status"] == "output-not-on" and verified_off(run3)


def test_absolute_limit_stops_the_ramp_even_where_output_off_is_expected(tmp_path):
    plan = build_plan(*profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS))

    def overcurrent(quantity, value, point, phase):
        return .2 if quantity == "Iout_A" and point["vin_target_V"] == 8. and phase == "acquiring" else value

    run, _ = evidence(run_supply_profile_mock(plan, tmp_path, reading_override=overcurrent))
    assert run["execution_status"] == "aborted" and run["stop"]["classification"] == "absolute-protective-limit"
    assert run["stop"]["output_off_expected"] is True and run["stop"]["level_kind"] == "down"
    assert "Absolute output-current limit 0.15 A exceeded" in run["errors"][0]
    assert [p["qualification"] for p in run["points"]] == ["valid"] * 4 + ["inconclusive"] + ["not-run"] * 4
    assert verified_off(run)


def test_acquire_mock_dispatches_supply_profiles_to_their_own_procedure(tmp_path):
    plan = build_plan(*profiles(RESET_STAIRCASE_TEST_TYPE, STAIRCASE_LEVELS))
    path = acquire_mock(plan, tmp_path, operator_observations=["synthetic staircase"])
    run, _ = evidence(path)
    assert "supply_profile" in run["method"] and run["operator_observations"] == ["synthetic staircase"]
    with pytest.raises(ValueError, match="no failure-injection scenarios"):
        acquire_mock(plan, tmp_path, scenario="aborted")
    mixed_dut, mixed_bench, mixed = profiles(SLOW_SUPPLY_RAMP_TEST_TYPE, RAMP_LEVELS)
    mixed.tests = mixed.tests + [default_plan().recipe.tests[0]]
    with pytest.raises(ValueError, match="mixes a supply profile"):
        acquire_mock(build_plan(mixed_dut, mixed_bench, mixed), tmp_path / "mixed")
    assert not (tmp_path / "mixed").exists()


def test_level_observation_phrases_are_computed_from_states_only():
    assert level_observation("down", "on", None, False) == "output in band"
    assert level_observation("up", "on", "off", False) == "recovered: output back in band"
    assert level_observation("recovery", "off", "off", False) == "not recovered: output off at a recovery level where the policy expects it on; cause unclassified"
    assert level_observation("low", "off", "on", True) == "reset: output off (documented expectation below the declared boundary)"
    assert level_observation("low", "indeterminate", "on", True).startswith("output indeterminate")
    assert level_observation("low", None, "on", True) == "no qualified observation"


def test_mock_supply_profile_path_imports_no_real_driver_modules():
    forbidden = {"benchctl", "pyvisa", "dcdc_bench.bringup", "dcdc_bench.extended", "dcdc_bench.real_backend",
                 "dcdc_bench.source_limit", "dcdc_bench.startup_descent", "dcdc_bench.voltage_sweep"}
    source_dir = Path(domain.__file__).parent
    for name in ("supply_profiles.py", "standard_recipes.py"):
        tree = ast.parse((source_dir / name).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.add("dcdc_bench." + module.lstrip(".") if node.level else module)
        assert not imported & forbidden, (name, imported & forbidden)
