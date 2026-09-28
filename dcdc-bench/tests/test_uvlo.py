"""Approved UVLO input ramp (RUN-09, DATA-04, DATA-05) against the synthetic plant only.

No test here opens an instrument or imports a real driver. The mock path is
in-process with a virtual clock; every run ends with a verified-OFF shutdown.
"""
from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from dcdc_bench import domain
from dcdc_bench.analysis import analyze_run, build_report_model, coverage_by_test, uvlo_ramp_brackets
from dcdc_bench.domain import UVLO_TEST_TYPE, BenchProfile, DutProfile, Plan, TestRecipe, UvloRampPolicy, uvlo_ramp_phases
from dcdc_bench.mock_uvlo import SyntheticUvlo, UvloMockBench
from dcdc_bench.planning import build_plan, load_profile, uvlo_approval_gaps, verify_plan_hash
from dcdc_bench.runner import run_mock
from dcdc_bench.services import default_plan
from dcdc_bench.storage import verify_integrity
from dcdc_bench.uvlo import (ProtectiveLimitFault, RegulationRuleStop, SourceBoundaryStop, UvloInputRampProcedure,
                             run_uvlo_mock)

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
POLICY_ID = "synthetic-uvlo-ramp-v1"
STEPS = [12., 10., 9., 8.75, 8.5, 8., 8.5, 8.75, 9., 9.5, 10., 12.]
LOAD_A = .1


def policy(**overrides) -> UvloRampPolicy:
    values = dict(floor_V=8., startup_interval_s=.3, output_on_minimum_V=10.8, output_off_maximum_V=1.,
                  expected_off_below_V=9., expected_on_above_V=10.)
    values.update(overrides)
    return UvloRampPolicy(**values)


def profiles(*, steps=STEPS, approved=True, mode="mock", declare_limits=True, **policy_overrides):
    """Copies of the saved mock profiles with a UVLO ramp test; instrument ids are unique per call for lock isolation."""
    base = default_plan()
    dut, bench, recipe = (item.model_copy(deep=True) for item in (base.dut, base.bench, base.recipe))
    suffix = uuid.uuid4().hex
    bench.source.instrument_id += suffix
    bench.load.instrument_id += suffix
    for quantity, binding in bench.measurements.items():
        binding.instrument_id = bench.source.instrument_id if quantity in ("Vin_V", "Iin_A") else bench.load.instrument_id
    bench.mode = recipe.execution_mode = mode
    if declare_limits:
        bench.protective_controls.policy_id = POLICY_ID
        bench.protective_controls.source_current_limit_A = .5
        bench.protective_controls.dut_output_overvoltage_V = 13.2
        bench.protective_controls.output_overcurrent_A = .15
    recipe.tests = [domain.TestDefinition(id="uvlo-ramp", type=UVLO_TEST_TYPE, input_voltage_targets_V=list(steps),
                                   output_current_targets_A=[LOAD_A], uvlo=policy(**policy_overrides))]
    recipe.authorization.uvlo_approved = approved
    recipe.authorization.protective_policy_id = POLICY_ID if approved else None
    # The synthetic load current follows a 0.55 s time constant; the dwell must cover it before acquisition.
    recipe.settling.minimum_dwell_s = 1.
    recipe.acquisition.duration_s = .3
    recipe.acquisition.target_poll_interval_s = .25
    recipe.acquisition.minimum_complete_cycles = 3
    return dut, bench, recipe


def approved_plan(**options) -> Plan:
    return build_plan(*profiles(**options))


def evidence(path):
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines() if line]
    return run, samples


def verified_off(run):
    return all(record.get("state") == "OFF" and record.get("verified") is True for record in run["shutdown"].values())


@pytest.fixture(scope="module")
def normal_run(tmp_path_factory):
    plan = approved_plan()
    path = run_uvlo_mock(plan, tmp_path_factory.mktemp("uvlo-normal"))
    run, samples = evidence(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    return plan, path, run, samples, analysis


# --- contracts and planning -----------------------------------------------------------------------

def test_ramp_shape_and_policy_contracts_are_validated():
    assert uvlo_ramp_phases([12., 9., 8., 9., 12.]) == ["down", "down", "down", "up", "up"]
    for bad in ([12., 9.], [12., 9., 9.], [9., 12., 8.], [12., 8., 10., 9.], [12., 8., 12., 8.]):
        with pytest.raises(ValueError):
            uvlo_ramp_phases(bad)
    with pytest.raises(ValidationError, match="requires a declared uvlo block"):
        domain.TestDefinition(id="t", type=UVLO_TEST_TYPE, input_voltage_targets_V=STEPS, output_current_targets_A=[.1])
    with pytest.raises(ValidationError, match="one fixed light load"):
        domain.TestDefinition(id="t", type=UVLO_TEST_TYPE, input_voltage_targets_V=STEPS, output_current_targets_A=[.1, .2], uvlo=policy())
    with pytest.raises(ValidationError, match="only valid for the uvlo_input_ramp"):
        domain.TestDefinition(id="t", input_voltage_targets_V=[24.], output_current_targets_A=[.1], uvlo=policy())
    with pytest.raises(ValidationError, match="off ceiling must lie below"):
        policy(output_off_maximum_V=11.)
    with pytest.raises(ValidationError, match="floor must not exceed"):
        policy(floor_V=9.5)
    assert policy().off_expected(8.5, "down") and not policy().off_expected(9., "down")
    assert policy().off_expected(9.5, "up") and not policy().off_expected(10., "up")
    assert [policy().classify_output(v) for v in (12., 5., .2, None)] == ["on", "indeterminate", "off", None]


def test_procedure_satisfies_the_test_procedure_contract():
    procedure = UvloInputRampProcedure(approved_plan())
    assert isinstance(procedure, domain.TestProcedure)
    assert isinstance(procedure.plan(), Plan) and isinstance(procedure.metadata(), dict)
    assert procedure.adapter is UvloMockBench and isinstance(procedure.stage, str)
    method = procedure.metadata()["method"]["uvlo_input_ramp"]
    assert method["guard"]["absolute_limits_every_step"]["output_current_A"] == .15
    assert "ignore_safety" not in json.dumps(procedure.metadata())


def test_planning_refuses_unapproved_uvlo_and_unknown_types_but_allows_approved_mock():
    dut, bench, recipe = profiles(approved=False)
    plan = build_plan(dut, bench, recipe)
    assert plan.points and all(p.status == "approval_blocked" for p in plan.points)
    assert all("uvlo_approved is false" in p.reason and "protective_policy_id is not declared" in p.reason for p in plan.points)
    recipe.authorization.uvlo_approved = True
    recipe.authorization.protective_policy_id = "some-other-policy"
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "approval_blocked" and "does not name the recipe's protective policy" in p.reason for p in plan.points)
    recipe.authorization.protective_policy_id = POLICY_ID
    assert all(p.status == "executable" for p in build_plan(dut, bench, recipe).points)
    with pytest.raises(ValueError, match="refused"):
        UvloInputRampProcedure(build_plan(*profiles(approved=False)))
    dut, bench, recipe = profiles(declare_limits=False)
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "approval_blocked" and "output_overcurrent_A must be declared" in p.reason for p in plan.points)
    dut, bench, recipe = profiles()
    recipe.tests[0] = domain.TestDefinition(id="mystery", type="unapproved_uvlo", input_voltage_targets_V=[24.],
                                     output_current_targets_A=[.1])
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "unsupported" and "not an implemented procedure" in p.reason for p in plan.points)


def test_real_uvlo_needs_hardware_approvals_too_and_mock_runner_refuses_real_profiles(tmp_path):
    dut, bench, recipe = profiles(mode="real")
    plan = build_plan(dut, bench, recipe)
    assert all(p.status == "approval_blocked" for p in plan.points)
    for text in ("real_hardware_enabled is false", "wiring_and_polarity_confirmed is false", "protective_controls.approved is false"):
        assert all(text in p.reason for p in plan.points)
    assert not uvlo_approval_gaps(bench, recipe)
    with pytest.raises(ValueError, match="mock profiles only"):
        run_uvlo_mock(plan, tmp_path)
    assert not list(tmp_path.iterdir())


def test_steps_below_floor_or_outside_dut_range_are_refused_not_clipped(tmp_path):
    plan = approved_plan(steps=[12., 9., 8.5, 7.5, 8.5, 12.])
    below = plan.points[3]
    assert below.vin_target_V == 7.5 and below.status == "unsupported"
    assert "below the declared UVLO floor 8 V" in below.reason and "without clipping" in below.reason
    assert [p.status for p in plan.points] == ["executable"] * 3 + ["unsupported"] + ["executable"] * 2
    excursion = plan.points[2]
    assert excursion.status == "executable" and "below the DUT's stated minimum input" in excursion.reason
    with pytest.raises(ValueError, match="not executable"):
        UvloInputRampProcedure(plan)
    high = approved_plan(steps=[12., 9., 8.5, 9., 37.])
    assert high.points[-1].status == "unsupported" and "above the DUT maximum input rating" in high.points[-1].reason
    low_start = approved_plan(steps=[8.9, 8.5, 8., 8.5, 8.9], expected_off_below_V=8.5)
    assert low_start.points[0].status == "unsupported" and "must start inside the DUT's stated input range" in low_start.points[0].reason
    with pytest.raises(ValueError, match="steady_state_load_sweep tests only"):
        run_mock(approved_plan(), tmp_path)
    assert not list(tmp_path.iterdir())


def test_example_recipe_is_approval_blocked_until_reviewed():
    dut = load_profile(PROFILES / "dut/12t12-4a.yaml", DutProfile)
    bench = load_profile(PROFILES / "bench/mock.yaml", BenchProfile)
    recipe = load_profile(PROFILES / "recipes/12t12-4a-uvlo.example.yaml", TestRecipe)
    assert recipe.execution_mode == "mock" and recipe.authorization.uvlo_approved is False
    assert recipe.tests[0].type == UVLO_TEST_TYPE and recipe.tests[0].uvlo.floor_V == 8.
    assert "reviewed protective policy" in (PROFILES / "recipes/12t12-4a-uvlo.example.yaml").read_text()
    plan = build_plan(dut, bench, recipe)
    assert len(plan.points) == 17 and verify_plan_hash(plan)
    assert all(p.status == "approval_blocked" and "uvlo_approved is false" in p.reason for p in plan.points)
    assert all(p.vin_target_V == v for p, v in zip(plan.points, recipe.tests[0].input_voltage_targets_V))
    bench.mode = recipe.execution_mode = "real"
    real = build_plan(dut, bench, recipe)
    assert all(p.status == "approval_blocked" and "real_hardware_enabled is false" in p.reason for p in real.points)


# --- synthetic plant --------------------------------------------------------------------------------

def test_synthetic_plant_latches_off_below_threshold_and_on_above_threshold_plus_hysteresis():
    bench = UvloMockBench(12., .5, .15, uvlo=SyntheticUvlo(turn_off_below_V=8.6, hysteresis_V=.5, standby_current_A=.004))
    with pytest.raises(RuntimeError, match="requires an ON source"):
        bench.set_live_voltage(10., 0.)
    bench.configure(12., LOAD_A, 0.)
    bench.source_on()
    bench.load_on()
    assert bench.state(10.).output_voltage_V > 11.9
    bench.set_live_voltage(8.75, 10.)
    assert bench.state(10.1).output_voltage_V > 11.9
    bench.set_live_voltage(8.5, 20.)
    off = bench.state(20.1)
    assert (off.output_voltage_V, off.output_current_A, off.input_current_A) == (0., 0., .004)
    assert off.load_compliance and off.source_mode == "CV"
    assert off.source_voltage_V * off.input_current_A == pytest.approx(off.module_loss_W + off.input_current_A**2 * .2)
    bench.set_live_voltage(9., 30.)
    assert bench.state(30.1).output_voltage_V == 0.
    bench.set_live_voltage(9.2, 40.)
    assert bench.state(40.1).output_voltage_V > 11.9
    assert [t["to"] for t in bench.uvlo.transitions] == ["on", "off", "on"]
    assert bench.identify()["data_source"] == "simulated"
    assert "synthetic" in SyntheticUvlo().parameters()["label"]


# --- RUN-09 -----------------------------------------------------------------------------------------

def test_run09_expected_off_steps_are_recorded_states_not_faults(normal_run):
    plan, path, run, samples, analysis = normal_run
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["real_hardware_opened"] is False and run["data_source"] == "simulated"
    assert run["model"]["parameters"]["uvlo"]["label"].startswith("synthetic")
    states = [(p["vin_target_V"], p["ramp_phase"], p["output_state"]) for p in run["points"]]
    assert states == [(12., "down", "on"), (10., "down", "on"), (9., "down", "on"), (8.75, "down", "on"),
                      (8.5, "down", "off"), (8., "down", "off"), (8.5, "up", "off"), (8.75, "up", "off"),
                      (9., "up", "off"), (9.5, "up", "on"), (10., "up", "on"), (12., "up", "on")]
    assert all(p["qualification"] == "valid" for p in run["points"])
    off_steps = [p for p in run["points"] if p["output_state"] == "off"]
    assert off_steps and all(p["output_off_expected"] and not p["minimum_vout_rule_applied"] for p in off_steps)
    assert all(not p["load_current_established"] for p in off_steps)
    assert all("recorded as a state, not a fault" in p["reason"] for p in off_steps)
    normal = [p for p in run["points"] if not p["output_off_expected"]]
    assert [p["vin_target_V"] for p in normal] == [12., 10., 9., 10., 12.]
    assert all(p["minimum_vout_rule_applied"] and p["output_state"] == "on" for p in normal)
    assert run["executed_point_ids"] == [p["point_id"] for p in run["points"]]
    assert "stop" not in run
    off_samples = [s for s in samples if s["point_id"] == off_steps[0]["point_id"] and s["phase"] == "acquiring"]
    assert off_samples and all(s["status"] == "ok" and s["acquisition_settings"]["output_off_expected"] for s in off_samples)
    assert all(s["acquisition_settings"]["requested_load_A"] == LOAD_A for s in off_samples)
    starting = [s for s in samples if s["phase"] == "starting"]
    assert starting and all(not s["acquisition_settings"]["load_enabled"] for s in starting)
    assert not {s["acquisition_cycle_id"] for s in starting} & {c for p in run["points"] for c in p["acquisition_cycle_ids"]}
    assert verified_off(run)
    assert run["raw_sample_count"] == len(samples)


def test_run09_absolute_limit_stops_the_run_even_inside_the_expected_off_phase(tmp_path):
    plan = approved_plan()

    def overcurrent(quantity, value, point, phase):
        return .2 if quantity == "Iout_A" and point["vin_target_V"] == 8.5 and point["ramp_phase"] == "down" else value

    run, samples = evidence(run_uvlo_mock(plan, tmp_path, reading_override=overcurrent))
    assert run["execution_status"] == "aborted"
    assert run["stop"]["classification"] == "absolute-protective-limit"
    assert run["stop"]["output_off_expected"] is True and run["stop"]["ramp_phase"] == "down"
    assert "Absolute output-current limit 0.15 A exceeded" in run["errors"][0]
    stopped = next(p for p in run["points"] if p["point_id"] == run["stop"]["point_id"])
    assert stopped["vin_target_V"] == 8.5 and stopped["qualification"] == "inconclusive"
    assert not stopped["acquisition_cycle_ids"]
    assert [p["qualification"] for p in run["points"]] == ["valid"] * 4 + ["inconclusive"] + ["not-run"] * 7
    injected = [s for s in samples if s.get("acquisition_settings", {}).get("injected_override")]
    assert injected and all(s["quantity"] == "Iout_A" and s["value"] == .2 for s in injected)
    assert verified_off(run)


def test_run09_normal_phase_minimum_vout_rule_still_trips(tmp_path):
    plan = approved_plan()
    early = SyntheticUvlo(turn_off_below_V=9.4, hysteresis_V=.5)
    run, _ = evidence(run_uvlo_mock(plan, tmp_path, synthetic=early))
    assert run["execution_status"] == "aborted"
    assert run["stop"]["classification"] == "normal-regulation-rule"
    assert run["stop"]["output_off_expected"] is False
    stopped = next(p for p in run["points"] if p["point_id"] == run["stop"]["point_id"])
    assert stopped["vin_target_V"] == 9. and stopped["qualification"] == "inconclusive"
    assert "outside the declared expected-off phase" in run["errors"][0]
    assert [p["qualification"] for p in run["points"]][:3] == ["valid", "valid", "inconclusive"]
    assert all(p["qualification"] == "not-run" for p in run["points"][3:])
    assert verified_off(run)


@pytest.mark.parametrize("values,phase,expected", [
    ({"Vin_V": 8.5, "Iin_A": .004, "Vout_V": 0., "Iout_A": 0.}, (8.5, "down"), None),
    ({"Vin_V": 9.5, "Iin_A": .004, "Vout_V": 0., "Iout_A": 0.}, (9.5, "up"), None),
    ({"Vin_V": 10., "Iin_A": .004, "Vout_V": 0., "Iout_A": 0.}, (10., "up"), RegulationRuleStop),
    ({"Vin_V": 12., "Iin_A": .15, "Vout_V": 12., "Iout_A": .05}, (12., "down"), RegulationRuleStop),
    ({"Vin_V": 8.5, "Iin_A": .004, "Vout_V": 0., "Iout_A": .16}, (8.5, "down"), ProtectiveLimitFault),
    ({"Vin_V": 8.5, "Iin_A": .51, "Vout_V": 0., "Iout_A": 0.}, (8.5, "down"), ProtectiveLimitFault),
    ({"Vin_V": 8.5, "Iin_A": .004, "Vout_V": 13.3, "Iout_A": 0.}, (8.5, "down"), ProtectiveLimitFault),
    ({"Vin_V": 8.5, "Iin_A": math.nan, "Vout_V": 0., "Iout_A": 0.}, (8.5, "down"), ProtectiveLimitFault),
])
def test_guard_scopes_normal_rules_by_phase_but_never_absolute_limits(values, phase, expected):
    plan = approved_plan()
    procedure = UvloInputRampProcedure(plan)
    procedure.begin_test(plan.recipe.tests[0])
    procedure.begin_step(*phase)
    procedure.acquiring = True
    if expected is None:
        procedure.guard(values, LOAD_A)
    else:
        with pytest.raises(expected):
            procedure.guard(values, LOAD_A)
    with pytest.raises(SourceBoundaryStop):
        procedure.guard({"Vin_V": 8.5, "Iin_A": .004, "Vout_V": 0., "Iout_A": 0.}, LOAD_A, mode_after="CC")
    procedure.guard({"Vin_V": 12., "Iin_A": .004, "Vout_V": 2., "Iout_A": 0.}, LOAD_A, loaded=False, startup=True)
    procedure.begin_step(12., "down")  # settling transient: the load rule waits for acquisition, the Vout rule does not
    procedure.guard({"Vin_V": 12., "Iin_A": .1, "Vout_V": 12., "Iout_A": .04}, LOAD_A)
    with pytest.raises(RegulationRuleStop):
        procedure.guard({"Vin_V": 12., "Iin_A": .1, "Vout_V": 9., "Iout_A": .04}, LOAD_A)


# --- DATA-04 / DATA-05 ------------------------------------------------------------------------------

def test_data04_analysis_reports_brackets_not_exact_thresholds(normal_run):
    plan, path, run, samples, analysis = normal_run
    ramp = analysis["uvlo_input_ramp"]["uvlo-ramp"]
    off, on, hysteresis = ramp["turn_off"], ramp["turn_on"], ramp["hysteresis"]
    assert (off["lower_V"], off["upper_V"], off["exact_threshold_V"], off["direction"]) == (8.5, 8.75, None, "descending")
    assert (on["lower_V"], on["upper_V"], on["exact_threshold_V"], on["direction"]) == (9., 9.5, None, "ascending")
    assert hysteresis["lower_V"] == pytest.approx(.25) and hysteresis["upper_V"] == pytest.approx(1.)
    assert hysteresis["exact_V"] is None and ramp["exact_threshold_V"] is None
    assert not ramp["notes"] and "not a measured value" in ramp["convention"]["hysteresis"]
    assert off["unresolved_steps_inside"] == [] and on["unresolved_steps_inside"] == []
    points = {p["point_id"]: p for p in analysis["points"]}
    assert points[off["last_on_point_id"]]["vin_target_V"] == 8.75 and points[off["first_off_point_id"]]["vin_target_V"] == 8.5
    for point in analysis["points"]:
        if point["output_state"] == "off":
            assert point["efficiency_pct"] is None and "not an efficiency point" in point["efficiency_reason"]
            assert point["requirements"]["output_voltage"] == "not-applicable"
            assert point["Vout_V"] is not None and point["Vout_V"] < .1
        else:
            assert point["efficiency_pct"] is not None and 0 < point["efficiency_pct"] < 100
    model = build_report_model(plan, run, analysis, samples)
    figure = next(f for f in model.figures if f.id == "fig-uvlo-uvlo-ramp")
    assert figure.x_key == "Vin_V" and len(figure.series[0].point_ids) == 12
    assert "no exact threshold is claimed" in figure.caption
    assert not any(m.id.startswith(("line-span", "load-span")) for m in model.metrics)
    assert any("turn-off is bracketed between 8.5 and 8.75 V" in text for text in model.summary)
    assert any("Hysteresis lies between 0.25 and 1 V" in text for text in model.summary)
    assert any("output-off is recorded, not faulted" in note for note in model.method.procedure_notes)
    assert model.evidence_label == "SYNTHETIC" and model.execution["uvlo_input_ramp"]["uvlo-ramp"]["turn_off"] == off


def test_data04_bracket_helper_on_the_brief_fixture_and_unresolved_ramps():
    def step(pid, vin, phase, state):
        return {"point_id": pid, "vin_target_V": vin, "ramp_phase": phase, "output_state": state}

    fixture = [step("a", 9.2, "down", "on"), step("b", 9.1, "down", "on"), step("c", 9., "down", "off"),
               step("d", 9.1, "up", "off"), step("e", 9.2, "up", "on")]
    result = uvlo_ramp_brackets(fixture)
    assert result["turn_off"]["lower_V"] == 9. and result["turn_off"]["upper_V"] == 9.1
    assert result["turn_off"]["exact_threshold_V"] is None and result["exact_threshold_V"] is None
    assert result["turn_on"]["lower_V"] == 9.1 and result["turn_on"]["upper_V"] == 9.2
    assert result["hysteresis"]["lower_V"] == pytest.approx(0.) and result["hysteresis"]["upper_V"] == pytest.approx(.2)
    assert any("not resolved by the declared step size" in note for note in result["notes"])
    stayed_on = uvlo_ramp_brackets([step("a", 12., "down", "on"), step("b", 9., "down", "on"), step("c", 12., "up", "on")])
    assert stayed_on["turn_off"] is None and stayed_on["turn_on"] is None and stayed_on["hysteresis"] is None
    assert any("turn-off is not bracketed" in note for note in stayed_on["notes"])
    never_back = uvlo_ramp_brackets([step("a", 12., "down", "on"), step("b", 9., "down", "off"), step("c", 12., "up", "off")])
    assert never_back["turn_off"]["lower_V"] == 9. and never_back["turn_on"] is None
    assert any("had not returned" in note for note in never_back["notes"])
    widened = uvlo_ramp_brackets([step("a", 12., "down", "on"), step("b", 10., "down", None), step("c", 9., "down", "off"),
                                  step("d", 10., "up", "indeterminate"), step("e", 12., "up", "on")])
    assert (widened["turn_off"]["lower_V"], widened["turn_off"]["upper_V"]) == (9., 12.)
    assert widened["turn_off"]["unresolved_steps_inside"] == ["b"] and widened["turn_on"]["unresolved_steps_inside"] == ["d"]


def test_data05_coverage_is_counted_per_test(normal_run):
    plan, path, run, samples, analysis = normal_run
    assert analysis["coverage"] == {"uvlo-ramp": {"requested": 12, "valid": 12}}
    load_grid = [{"test_id": "steady-load", "qualification": "valid"}] * 37 + [{"test_id": "steady-load", "qualification": "setup-limited"}] * 2
    combined = coverage_by_test(load_grid + [{"test_id": p["test_id"], "qualification": p["qualification"]} for p in analysis["points"]])
    assert combined["steady-load"] == {"requested": 39, "valid": 37, "setup-limited": 2}
    assert combined["uvlo-ramp"] == {"requested": 12, "valid": 12}
    assert sum(v["requested"] for v in combined.values()) == 51


# --- RUN-10: mock path imports no real driver --------------------------------------------------------

def test_mock_uvlo_path_imports_no_real_driver_modules():
    forbidden = {"benchctl", "pyvisa", "dcdc_bench.bringup", "dcdc_bench.extended", "dcdc_bench.real_backend",
                 "dcdc_bench.source_limit", "dcdc_bench.startup_descent", "dcdc_bench.voltage_sweep"}
    source_dir = Path(domain.__file__).parent
    for name in ("uvlo.py", "mock_uvlo.py"):
        tree = ast.parse((source_dir / name).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.add("dcdc_bench." + module.lstrip(".") if node.level else module)
        assert not imported & forbidden, (name, imported & forbidden)
    # Transitive check in a fresh interpreter: importing the mock UVLO path pulls in no driver package.
    probe = ("import sys, dcdc_bench.uvlo, dcdc_bench.mock_uvlo; "
             "print(sorted(m for m in sys.modules if m.split('.')[0] in ('benchctl', 'pyvisa') "
             "or m in ('dcdc_bench.bringup', 'dcdc_bench.extended', 'dcdc_bench.real_backend')))")
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120,
                            env={"PYTHONPATH": str(source_dir.parent), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout
