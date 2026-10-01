"""Best-effort ISO 16750-2 procedures (transient hold, momentary drop, micro and line interruption) on the synthetic plant only.

No test here opens an instrument or imports a real driver. The mock path is
in-process with a virtual clock; every run ends with a verified-OFF shutdown.
"""
from __future__ import annotations

import ast
import json
import signal
import uuid
from pathlib import Path

import pytest

from dcdc_bench import domain
from dcdc_bench.adapters import HoldUpModel, ReadbackModel, StartupModel
from dcdc_bench.best_effort_procedures import (BEST_EFFORT_TEST_TYPES, LINE_INTERRUPTION_TEST_TYPE, METHOD_KEY,
                                               MICRO_INTERRUPTION_TEST_TYPE, MOMENTARY_DROP_TEST_TYPE, TRANSIENT_HOLD_TEST_TYPE,
                                               BestEffortProcedure, best_effort_approval_gaps, best_effort_mock_estimate,
                                               declared_deviations_sha256, deviation_sheet_sha256, run_best_effort_mock)
from dcdc_bench.mock_uvlo import SyntheticUvlo, UvloMockBench
from dcdc_bench.planning import build_plan
from dcdc_bench.runner import run_mock
from dcdc_bench.services import acquire_mock, default_plan
from dcdc_bench.storage import verify_integrity

try:
    from dcdc_bench.domain import BestEffortPolicy, DeviationSheet
except ImportError:  # transitional: the shared contract is not in this checkout yet
    from dcdc_bench._best_effort_contract import BestEffortPolicy, DeviationSheet

POLICY_ID = "synthetic-best-effort-v1"
LOAD_A = .1
LAN_ROUND_TRIP_MAX_S = .055
EPS = 1e-6  # virtual-clock float accumulation
DEFAULTS = {
    TRANSIENT_HOLD_TEST_TYPE: dict(clause="4.3.1.2", variant="jump-start", level_V=26., hold_s=2., repeats=2, recovery_s=1., mechanism="lan_voltage_step"),
    MOMENTARY_DROP_TEST_TYPE: dict(clause="4.6.1.1", variant="A", drop_level_V=4.5, drop_s=.1, repeats=1, recovery_s=2., mechanism="lan_voltage_step"),
    MICRO_INTERRUPTION_TEST_TYPE: dict(clause="4.6.1.2", variant="1 s", interruption_s=1., repeats=2, recovery_s=2., mechanism="lan_output_off"),
    LINE_INTERRUPTION_TEST_TYPE: dict(clause="4.9.2", variant="method 1, positive line", interruption_s=10., repeats=1, recovery_s=2.,
                                      mechanism="lan_output_off"),
}
BASES = {TRANSIENT_HOLD_TEST_TYPE: 10.8, MOMENTARY_DROP_TEST_TYPE: 12., MICRO_INTERRUPTION_TEST_TYPE: 12., LINE_INTERRUPTION_TEST_TYPE: 12.}


def entry(parameter, unit, required, achievable, mechanism, measured_by, classification, note=None):
    return {"parameter": parameter, "unit": unit, "required": required, "achievable": achievable, "mechanism": mechanism,
            "measured_by": measured_by, "classification": classification, "note": note}


def make_sheet(kind, values) -> DeviationSheet:
    """A plausible declared sheet per test type (the standards work builds the real ones; the procedure takes any)."""
    mech = values["mechanism"]
    rows = []
    if kind == TRANSIENT_HOLD_TEST_TYPE:
        rows = [entry("level_V", "V", {"value": values["level_V"], "tolerance": .2, "basis": "ISO"}, {"value": values["level_V"], "bound": "0.1 % + 25 mV", "basis": "DS5"}, mech, "none", "met"),
                entry("hold_s", "s", {"value": values["hold_s"], "tolerance": .1 * values["hold_s"], "basis": "ISO"}, {"value": values["hold_s"], "bound": "+173 ms worst", "basis": "LAN"}, mech, "host_clock", "met"),
                entry("edge_max_s", "s", {"value": .01, "tolerance": None, "basis": "ISO"}, {"value": None, "bound": "< 110 ms loaded", "basis": "DS5"}, mech, "none", "not_met_but_documented", "supply slew, not an edge generator"),
                entry("repeats", "1", {"value": values["repeats"], "tolerance": None, "basis": "ISO"}, {"value": values["repeats"], "bound": None, "basis": "derived"}, mech, "host_clock", "met"),
                entry("rest_s", "s", {"value": values["recovery_s"], "tolerance": .05 * values["recovery_s"], "basis": "ISO"}, {"value": values["recovery_s"], "bound": "+173 ms worst", "basis": "LAN"}, mech, "host_clock", "met")]
    elif kind == MOMENTARY_DROP_TEST_TYPE:
        rows = [entry("drop_level_V", "V", {"value": values["drop_level_V"], "tolerance": .2, "basis": "ISO-fig"}, {"value": values["drop_level_V"], "bound": "fall < 800 ms unloaded", "basis": "DS5"}, mech, "none", "unknown_until_measured", "depth may not be reached before the restore"),
                entry("drop_s", "s", {"value": values["drop_s"], "tolerance": .005, "basis": "ISO-fig"}, {"value": values["drop_s"], "bound": "0-270 ms terminal side", "basis": "derived"}, mech, "host_clock", "unknown_until_measured"),
                entry("edge_max_s", "s", {"value": .01, "tolerance": None, "basis": "ISO"}, {"value": None, "bound": "< 110 ms loaded", "basis": "DS5"}, mech, "none", "not_met_but_documented"),
                entry("recovery_s", "s", {"value": values["recovery_s"], "tolerance": None, "basis": "ISO"}, {"value": values["recovery_s"], "bound": None, "basis": "LAN"}, mech, "host_clock", "met")]
    else:
        rows = [entry("interruption_s", "s", {"value": values["interruption_s"], "tolerance": .05 * values["interruption_s"], "basis": "ISO"}, {"value": values["interruption_s"], "bound": "+173 ms worst over LAN; exact by Delayer", "basis": "LAN"}, mech, "host_clock", "unknown_until_measured" if mech == "lan_output_off" else "met"),
                entry("recovery_s", "s", {"value": values["recovery_s"], "tolerance": None, "basis": "ISO"}, {"value": values["recovery_s"], "bound": None, "basis": "LAN"}, mech, "host_clock", "met"),
                entry("open_impedance_ohm", "ohm", {"value": 1e7, "tolerance": None, "basis": "ISO"}, {"value": None, "bound": "source output OFF; OFF-state impedance unverified", "basis": "UNV"}, mech, "none", "approximated"),
                entry("transition_s", "s", {"value": 1e-5, "tolerance": None, "basis": "ISO"}, {"value": None, "bound": "command acts within < 118 ms", "basis": "DS5"}, mech, "none", "unknown_until_measured"),
                entry("repeats", "1", {"value": values["repeats"], "tolerance": None, "basis": "ISO"}, {"value": values["repeats"], "bound": None, "basis": "derived"}, mech, "host_clock", "met")]
    return DeviationSheet.model_validate({"schema_version": "1.0", "standard": "ISO 16750-2:2023", "clause": values["clause"],
                                          "variant": values["variant"], "entries": rows,
                                          "statement": f"ISO 16750-2 clause {values['clause']} realised by {mech} on this bench; deviations recorded"})


def policy(kind, **overrides) -> BestEffortPolicy:
    values = {**DEFAULTS[kind], **overrides}
    return BestEffortPolicy(**values, deviation_sheet=make_sheet(kind, values))


def profiles(kind, *, approved=True, mode="mock", accepted="declared", uvlo_approved=True, base_V=None, bound_s=60., exact=False,
             poll_s=.25, tests=None, **overrides):
    """Copies of the saved mock profiles with best-effort test(s); unique instrument ids keep the mock locks apart."""
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
    if tests is None:
        tests = [("stimulus", kind, overrides)]
    recipe.tests = [domain.TestDefinition(id=test_id, type=test_kind, input_voltage_targets_V=[base_V or BASES[test_kind]],
                                          output_current_targets_A=[LOAD_A], best_effort=policy(test_kind, **test_overrides))
                    for test_id, test_kind, test_overrides in tests]
    recipe.standard_clause = f"ISO 16750-2:2023 §{recipe.tests[0].best_effort.clause}"
    recipe.authorization.protective_policy_id = POLICY_ID
    recipe.authorization.best_effort_approved = approved
    recipe.authorization.uvlo_approved = uvlo_approved
    recipe.authorization.instrument_timed_bound_s = bound_s
    recipe.authorization.program_clause_level_exactly = exact
    if accepted == "declared":
        recipe.authorization.accepted_deviations_sha256 = declared_deviations_sha256(recipe)
    elif accepted == "wrong":
        recipe.authorization.accepted_deviations_sha256 = "0" * 64
    recipe.settling.minimum_dwell_s = 1.
    recipe.acquisition.duration_s = .3
    recipe.acquisition.target_poll_interval_s = poll_s
    recipe.acquisition.minimum_complete_cycles = 3
    return dut, bench, recipe


def evidence(path):
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines() if line]
    return run, samples


def verified_off(run):
    return all(record.get("state") == "OFF" and record.get("verified") is True for record in run["shutdown"].values())


def achieved(run, parameter, test_id="stimulus"):
    return next(e for e in run["method"][METHOD_KEY]["tests"][test_id]["deviations"] if e["parameter"] == parameter)["achieved"]


# --- contracts, hashes and the approval gate -----------------------------------------------------------------

def test_sheet_hash_is_canonical_and_changes_with_any_parameter():
    first, again = make_sheet(TRANSIENT_HOLD_TEST_TYPE, DEFAULTS[TRANSIENT_HOLD_TEST_TYPE]), make_sheet(TRANSIENT_HOLD_TEST_TYPE, DEFAULTS[TRANSIENT_HOLD_TEST_TYPE])
    assert deviation_sheet_sha256(first) == deviation_sheet_sha256(again) and len(deviation_sheet_sha256(first)) == 64
    changed = make_sheet(TRANSIENT_HOLD_TEST_TYPE, {**DEFAULTS[TRANSIENT_HOLD_TEST_TYPE], "hold_s": 60.})
    assert deviation_sheet_sha256(changed) != deviation_sheet_sha256(first)
    with pytest.raises(ValueError, match="needs a mechanism"):
        policy(TRANSIENT_HOLD_TEST_TYPE, mechanism="none")


def test_approval_gate_refuses_until_the_sheet_is_accepted_and_grants_an_approved_recipe(tmp_path):
    dut, bench, recipe = profiles(MICRO_INTERRUPTION_TEST_TYPE, approved=False, accepted=None)
    gaps = best_effort_approval_gaps(bench, recipe)
    assert "recipe authorization.best_effort_approved is false" in gaps and any("accepted_deviations_sha256 is not declared" in gap for gap in gaps)
    with pytest.raises(ValueError, match="approval gate.*best_effort_approved is false"):
        BestEffortProcedure(build_plan(dut, bench, recipe))
    with pytest.raises(ValueError, match="accepted deviation sheet hash does not match"):
        BestEffortProcedure(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, accepted="wrong")))
    # Levels below the DUT minimum (0 V during an interruption, the 4.5 V drop) need the UVLO-style approval as well.
    with pytest.raises(ValueError, match="approved UVLO-style path.*uvlo_approved is false"):
        BestEffortProcedure(build_plan(*profiles(LINE_INTERRUPTION_TEST_TYPE, uvlo_approved=False)))
    with pytest.raises(ValueError, match="approved UVLO-style path"):
        BestEffortProcedure(build_plan(*profiles(MOMENTARY_DROP_TEST_TYPE, uvlo_approved=False)))
    # A jump start never leaves the DUT range: no UVLO approval needed.
    BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, uvlo_approved=False)))
    # Mechanisms this bench does not have, or cannot time, are refused before anything is written.
    with pytest.raises(ValueError, match="switch box, which this bench does not have"):
        BestEffortProcedure(build_plan(*profiles(LINE_INTERRUPTION_TEST_TYPE, mechanism="switch_box")))
    with pytest.raises(ValueError, match="cannot be realised by 'lan_output_off'"):
        BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, mechanism="lan_output_off")))
    with pytest.raises(ValueError, match="whole seconds"):
        BestEffortProcedure(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, mechanism="supply_delayer", interruption_s=.5)))
    with pytest.raises(ValueError, match="below 0.1 s are not offered"):
        BestEffortProcedure(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, interruption_s=.01)))
    with pytest.raises(ValueError, match="above the 5 s bound in force.*instrument_timed_bound_s"):
        BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, bound_s=5.)))
    with pytest.raises(ValueError, match="Simulated run refused"):
        BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, hold_s=3000., repeats=1, bound_s=5000., recovery_s=1.)))
    # Owner decision 6: the clause level at the DUT ceiling only with program_clause_level_exactly.
    with pytest.raises(ValueError, match="endpoint margin.*program_clause_level_exactly"):
        BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, level_V=36., base_V=24.)))
    exact = BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, level_V=36., base_V=24., exact=True)))
    assert exact.programmed["stimulus"]["program_clause_level_exactly"] is True and exact.programmed["stimulus"]["source_ovp_V"] == 38.
    with pytest.raises(ValueError, match="exceeds the DUT maximum"):
        BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, level_V=37., exact=True)))
    # Granted: the procedure is a TestProcedure with a populated method block and no global safety switch.
    procedure = BestEffortProcedure(build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE)))
    assert isinstance(procedure, domain.TestProcedure) and procedure.adapter is UvloMockBench
    method = procedure.metadata()["method"][METHOD_KEY]
    assert method["test_type"] == TRANSIENT_HOLD_TEST_TYPE and method["clause"] == "4.3.1.2" and method["variant"] == "jump-start"
    assert method["approval"]["best_effort_approved"] and method["approval"]["accepted_deviations_sha256"] == method["approval"]["declared_deviations_sha256"]
    assert [e["parameter"] for e in method["deviations"]] == ["level_V", "hold_s", "edge_max_s", "repeats", "rest_s"]
    assert all(e["achieved"] == {"value": None, "measured_by": "none", "note": e["achieved"]["note"]} for e in method["deviations"]), "nothing achieved before the run"
    assert method["tests"]["stimulus"]["programmed"]["source_ovp_V"] == 28. and method["tests"]["stimulus"]["programmed"]["source_ocp_A"] == .55
    assert "ignore_safety" not in json.dumps(procedure.metadata())
    assert any("not approved for real hardware" in note for note in procedure.metadata()["metrology_limitations"])
    assert any(note.startswith("Deviation sheet, ISO 16750-2 clause 4.3.1.2, edge_max_s: not met but documented") for note in procedure.metadata()["metrology_limitations"])
    estimate = best_effort_mock_estimate(procedure.plan())
    assert estimate["within_budget"] and estimate["records"] == method["run_budget"]["records"]


# --- the four procedures ----------------------------------------------------------------------------------------

def test_transient_hold_completes_with_host_clock_intervals_and_the_converter_on_at_the_level(tmp_path):
    plan = build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE))
    path = run_best_effort_mock(plan, tmp_path)
    run, samples = evidence(path)
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["real_hardware_opened"] is False and run["data_source"] == "simulated" and run["clock"]["mode"] == "virtual"
    assert run["run_id"].split("_")[1] == "hold" and run["scenario"].startswith("ISO 16750-2 best-effort transient hold")
    assert verified_off(run) and run["raw_sample_count"] == len(samples)
    method = run["method"][METHOD_KEY]
    assert {"clause", "variant", "test_type", "deviations", "statement", "plant", "tests"} <= set(method)
    assert method["plant"]["hold_up"]["input_capacitance_F"] == pytest.approx(470e-6) and "SYNTHETIC" in method["plant"]["label"]
    assert method["plant"]["startup"]["soft_start_time_constant_s"] == .3 and method["synthetic_model"]["turn_off_below_dut_input_V"] == 8.6
    detail = method["tests"]["stimulus"]
    assert detail["completed"] and detail["startup"]["status"] == "output-on-before-load" and len(detail["startup"]["cycle_ids"]) == 5
    assert detail["baseline"]["state"] == "on" and len(detail["repeats"]) == 2
    # Every command carries host-clock issue and acknowledgement instants, monotonic and in order.
    commands = detail["commands"]
    assert [c["command"] for c in commands] == ["set_voltage_live"] * 4 and [c["to_V"] for c in commands] == [26., 10.8, 26., 10.8]
    instants = [t for c in commands for t in (c["commanded_at_s"], c["acknowledged_at_s"])]
    assert instants == sorted(instants) and all(c["acknowledged_at_s"] > c["commanded_at_s"] for c in commands)
    events = [json.loads(line) for line in (path / "raw/events.jsonl").read_text().splitlines() if line]
    assert [e["event"] for e in events if e["event"] in ("protections_programmed", "energized", "load_enabled")] == ["protections_programmed", "energized", "load_enabled"], "protections first, then the gate, then the load"
    assert sum(e["event"] == "command" for e in events) == 4
    # Achieved: the hold interval is host-timed (write to write, the driver's two pre-checks included) within the LAN spread.
    hold = achieved(run, "hold_s")
    assert hold["measured_by"] == "host_clock" and 2. - EPS <= hold["min"] <= hold["max"] <= 2. + 2 * LAN_ROUND_TRIP_MAX_S + EPS and len(hold["values"]) == 2
    rest = achieved(run, "rest_s")
    assert rest["measured_by"] == "host_clock" and 1. - EPS <= rest["min"] and rest["max"] < 1.1
    assert achieved(run, "repeats") == {"value": 2, "measured_by": "host_clock", "note": "repeats completed, counted by the host (2 declared)"}
    assert achieved(run, "level_V")["measured_by"] == "none" and achieved(run, "edge_max_s")["value"] is None
    assert all(e["test_id"] == "stimulus" for e in method["deviations"]) and method["statement"] == detail["statement"]
    # The converter stayed on at 26 V: every poll inside the hold saw the output in band and nothing tripped.
    for repeat in detail["repeats"]:
        polls = repeat["polls_during_stimulus"]
        assert polls["cycles"] >= 6 and polls["on"] == polls["cycles"] and polls["Vin_mean_V"] == pytest.approx(26., abs=.05)
        assert repeat["plant_truth"] == {"uvlo_transitions": [], "tripped": False, "restarted": False, "label": repeat["plant_truth"]["label"]}
        assert repeat["observation"]["state"] == "on" and repeat["observation_text"].endswith("output on at the observation after the window")
    point = run["points"][0]
    assert point["qualification"] == "valid" and point["output_state"] == "on" and point["repeats_completed"] == 2 and not point["plant_tripped_any_repeat"]
    assert point["acquisition_cycle_ids"] == detail["repeats"][-1]["observation"]["cycle_ids"] and point["accepted_means"]["Vin_V"] == pytest.approx(10.8, abs=.01)
    hold_samples = [s for s in samples if s["phase"] == "hold"]
    assert hold_samples and {s["acquisition_settings"]["procedure_stage"] for s in hold_samples} == {"hold"}
    assert all(s["acquisition_settings"]["output_off_expected"] is False for s in hold_samples), "no expected-off phase in a hold"
    # Deterministic under the virtual clock and seeded plant.
    other, _ = evidence(run_best_effort_mock(plan, tmp_path))
    assert other["method"][METHOD_KEY]["tests"]["stimulus"]["commands"] == commands and other["duration_s"] == run["duration_s"]
    # The 4.3.2 shape: five short holds at 18 V from 16 V, one second apart (owner decision 7).
    transient = build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, clause="4.3.2", variant="400 ms plateau", level_V=18., hold_s=.4, repeats=5, recovery_s=1., base_V=16.))
    run2, _ = evidence(run_best_effort_mock(transient, tmp_path))
    assert run2["execution_status"] == "completed" and len(run2["method"][METHOD_KEY]["tests"]["stimulus"]["repeats"]) == 5
    assert all(r["polls_during_stimulus"]["cycles"] == 1 for r in run2["method"][METHOD_KEY]["tests"]["stimulus"]["repeats"]), "one 0.25 s poll fits a 0.4 s hold"
    assert achieved(run2, "hold_s")["min"] >= .4 - EPS and achieved(run2, "repeats")["value"] == 5


def test_momentary_drop_variant_a_over_lan_and_variant_b_by_the_supply_timer(tmp_path):
    # Variant A: 4.5 V commanded for 100 ms over LAN; no 0.25 s poll can fall inside it, yet the plant's latch sees it.
    run, samples = evidence(run_best_effort_mock(build_plan(*profiles(MOMENTARY_DROP_TEST_TYPE)), tmp_path))
    assert run["execution_status"] == "completed" and not run["errors"] and verified_off(run) and run["run_id"].split("_")[1] == "drop"
    detail = run["method"][METHOD_KEY]["tests"]["stimulus"]
    repeat = detail["repeats"][0]
    assert repeat["polls_during_stimulus"]["cycles"] == 0 and "invisible to polling" in repeat["observation_text"]
    assert repeat["plant_truth"]["tripped"] and repeat["plant_truth"]["restarted"], "4.5 V is below the synthetic UVLO: trip and restart through the soft start"
    assert repeat["recovered_after_host_s"] is not None and .5 < repeat["recovered_after_host_s"] < 1.5, "soft start (0.3 s) reaches 90 % within about 0.7 s, seen at the poll cadence"
    assert repeat["observation"]["state"] == "on" and run["points"][0]["qualification"] == "valid" and run["points"][0]["plant_tripped_any_repeat"]
    drop = achieved(run, "drop_s")
    assert drop["measured_by"] == "host_clock" and .1 - EPS <= drop["value"] <= .1 + 5 * LAN_ROUND_TRIP_MAX_S + EPS
    assert achieved(run, "drop_level_V")["measured_by"] == "none" and achieved(run, "recovery_s")["value"] >= 2. - EPS
    recovery = [s for s in samples if s["phase"] == "recovery"]
    assert recovery and all(s["acquisition_settings"]["output_off_expected"] is True for s in recovery), "output-off is expected during the recovery window"
    assert any(s["quantity"] == "Vout_V" and s["value"] < 10.8 for s in recovery), "the first recovery poll saw the output still below band (soft start under way)"
    assert any("not visible to this bench" in note for note in run["metrology_limitations"])
    # Variant B: the Timer times a 1 s drop; the host cannot timestamp the instrument's transitions, so nothing is 'achieved'.
    plan_b = build_plan(*profiles(MOMENTARY_DROP_TEST_TYPE, variant="B", drop_s=1., mechanism="supply_timer"))
    path_b = run_best_effort_mock(plan_b, tmp_path)
    run_b, samples_b = evidence(path_b)
    assert run_b["execution_status"] == "completed" and not run_b["errors"], run_b["errors"]
    detail_b = run_b["method"][METHOD_KEY]["tests"]["stimulus"]
    assert detail_b["sequence"] == {"mechanism": "supply_timer", "instrument_timed": True, "active_s": 1., "rest_s": 2., "observation_window_s": pytest.approx(1.25),
                                    "repeats": 1, "per_repeat_s": 5, "stimulus_total_s": 6, "pre_group_s": 1, "active_group_s": 1, "rest_group_s": 4}
    assert [c["command"] for c in detail_b["commands"]] == ["program_start"] and detail_b["program"]["groups"] == [[12., .5, 1], [4.5, .5, 1], [12., .5, 4]]
    assert detail_b["program"]["end_state_observed"] == "OFF" and detail_b["program"]["status_at_end"]["running"] is False
    repeat_b = detail_b["repeats"][0]
    assert repeat_b["predicted_window"] and repeat_b["polls_during_stimulus"]["cycles"] >= 3 and repeat_b["polls_during_stimulus"]["off"] >= 1
    assert repeat_b["plant_truth"]["tripped"] and repeat_b["observation"]["state"] == "on"
    drop_b = achieved(run_b, "drop_s")
    assert drop_b["value"] is None and drop_b["measured_by"] == "none" and drop_b["programmed"] == 1 and "instrument-timed" in drop_b["note"]
    assert {s["phase"] for s in samples_b} >= {"programmed", "drop", "recovery", "acquiring", "program-end"}
    events = [json.loads(line) for line in (path_b / "raw/events.jsonl").read_text().splitlines() if line]
    assert any(e["event"] == "program_written" and e["groups"] == 3 for e in events), "the program is written before the source is energised"


def test_one_second_interruption_restarts_through_soft_start_and_a_short_one_with_hold_up_does_not_trip(tmp_path):
    run, samples = evidence(run_best_effort_mock(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE)), tmp_path))
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["run_id"].split("_")[1] == "microint" and verified_off(run)
    detail = run["method"][METHOD_KEY]["tests"]["stimulus"]
    assert [c["command"] for c in detail["commands"]] == ["output_off", "output_on"] * 2
    for repeat in detail["repeats"]:
        assert repeat["plant_truth"]["tripped"] and repeat["plant_truth"]["restarted"]
        trip = next(t for t in repeat["plant_truth"]["uvlo_transitions"] if t["to"] == "off")
        off_at = detail["commands"][2 * (repeat["index"] - 1)]["commanded_at_s"]
        assert 0. < trip["monotonic_s"] - off_at < .1, "the trip is placed at the solved hold-up crossing, milliseconds after OFF took effect"
        assert repeat["polls_during_stimulus"]["cycles"] == 3 and repeat["polls_during_stimulus"]["off"] == 3, "three 0.25 s polls saw the output off"
        assert .5 < repeat["recovered_after_host_s"] < 1.5 and repeat["observation"]["state"] == "on"
    interruption = achieved(run, "interruption_s")
    assert interruption["measured_by"] == "host_clock" and 1. - EPS <= interruption["min"] <= interruption["max"] <= 1. + 3 * LAN_ROUND_TRIP_MAX_S + EPS
    assert achieved(run, "open_impedance_ohm")["measured_by"] == "none" and achieved(run, "transition_s")["value"] is None
    interrupted = [s for s in samples if s["phase"] == "interruption"]
    assert interrupted and all(s["acquisition_settings"]["source_mode"] == "OFF" and s["acquisition_settings"]["output_off_expected"] for s in interrupted)
    assert all(abs(s["value"]) < .01 for s in interrupted if s["quantity"] in ("Vin_V", "Iin_A")), "the supply reports its disabled output as 0 V / 0 A (plus the synthetic readback offset)"
    assert any("not a demonstrated >= 10 MOhm open" in note for note in run["metrology_limitations"])
    # The same interruptions timed by the Delayer: exact whole seconds on the instrument's clock, nothing host-timed.
    run_d, _ = evidence(run_best_effort_mock(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, mechanism="supply_delayer")), tmp_path))
    assert run_d["execution_status"] == "completed" and not run_d["errors"], run_d["errors"]
    detail_d = run_d["method"][METHOD_KEY]["tests"]["stimulus"]
    assert detail_d["program"]["groups"] == [["ON", 1], ["OFF", 1], ["ON", 4], ["OFF", 1], ["ON", 4]] and detail_d["program"]["end_state_observed"] == "OFF"
    assert all(r["plant_truth"]["tripped"] and r["observation"]["state"] == "on" and r["polls_during_stimulus"]["off"] >= 3 for r in detail_d["repeats"])
    truth = detail_d["synthetic_plant_truth"]["applied_transitions"]
    offs = [t["at"] for t in truth if t["origin"] == "delayer" and t["kind"] == "output" and t["value"] is False and t.get("group") is not None]
    ons = [t["at"] for t in truth if t["origin"] == "delayer" and t["kind"] == "output" and t["value"] is True and t.get("group")]
    assert len(offs) == 2 and all(abs((on - off) - 1.) <= .001 for off, on in zip(offs, ons)), "Delayer OFF groups last 1 s within 1 ms"
    assert achieved(run_d, "interruption_s") == {"value": None, "measured_by": "none", "programmed": 1, "note": achieved(run_d, "interruption_s")["note"]}
    # 100 ms over LAN: with the default 470 uF the converter trips; with 10 mF it rides through and nothing on the bench sees the event.
    short = build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, variant="100 ms", interruption_s=.1, repeats=1))
    tripped, _ = evidence(run_best_effort_mock(short, tmp_path))
    repeat = tripped["method"][METHOD_KEY]["tests"]["stimulus"]["repeats"][0]
    assert tripped["execution_status"] == "completed" and repeat["plant_truth"]["tripped"] and repeat["polls_during_stimulus"]["cycles"] == 0
    rode_through, _ = evidence(run_best_effort_mock(short, tmp_path, hold_up=HoldUpModel(input_capacitance_F=.01)))
    repeat = rode_through["method"][METHOD_KEY]["tests"]["stimulus"]["repeats"][0]
    assert rode_through["execution_status"] == "completed" and rode_through["method"][METHOD_KEY]["plant"]["hold_up"]["input_capacitance_F"] == .01
    assert repeat["plant_truth"] == {"uvlo_transitions": [], "tripped": False, "restarted": False, "label": repeat["plant_truth"]["label"]}
    assert repeat["polls_during_stimulus"]["cycles"] == 0 and "invisible to polling" in repeat["observation_text"]
    assert repeat["polls_during_window"]["on"] == repeat["polls_during_window"]["cycles"] and repeat["recovered_after_host_s"] < .3
    interval = achieved(rode_through, "interruption_s")
    assert .1 - EPS <= interval["value"] <= .1 + 3 * LAN_ROUND_TRIP_MAX_S + EPS


def test_line_interruption_holds_the_positive_line_open_ten_seconds_with_output_off_recorded_not_faulted(tmp_path):
    plan = build_plan(*profiles(LINE_INTERRUPTION_TEST_TYPE, poll_s=.5))
    run, samples = evidence(run_best_effort_mock(plan, tmp_path))
    assert run["execution_status"] == "completed" and not run["errors"], run["errors"]
    assert run["run_id"].split("_")[1] == "lineint" and verified_off(run)
    detail = run["method"][METHOD_KEY]["tests"]["stimulus"]
    assert detail["line"].startswith("positive line only") and detail["clause"] == "4.9.2"
    repeat = detail["repeats"][0]
    assert repeat["polls_during_stimulus"]["cycles"] >= 18 and repeat["polls_during_stimulus"]["off"] == repeat["polls_during_stimulus"]["cycles"]
    assert repeat["plant_truth"]["tripped"] and repeat["observation"]["state"] == "on"
    interruption = achieved(run, "interruption_s")
    assert 10. - EPS <= interruption["value"] <= 10. + 3 * LAN_ROUND_TRIP_MAX_S + EPS and interruption["measured_by"] == "host_clock"
    off_polls = [s for s in samples if s["phase"] == "interruption" and s["quantity"] == "Vout_V"]
    assert off_polls and all(abs(s["value"]) < .01 for s in off_polls) and all(s["status"] == "invalid" and "load-out-of-compliance" in s["quality_flags"] for s in off_polls)
    assert run["points"][0]["qualification"] == "valid" and run["points"][0]["output_state"] == "on"


# --- stops ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("stop_signal,expected_status", [(signal.SIGINT, "aborted"), (signal.SIGTERM, "interrupted")])
def test_stop_signals_preserve_the_completed_test_and_the_partial_cycle(tmp_path, stop_signal, expected_status):
    plan = build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, tests=[("hold-1", TRANSIENT_HOLD_TEST_TYPE, dict(repeats=1)),
                                                               ("hold-2", TRANSIENT_HOLD_TEST_TYPE, dict(repeats=1))]))
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    sent = []

    def interrupt_second_test(quantity, value, point, phase):
        if point["point_id"] == "p0002" and phase == "acquiring" and quantity == "Iin_A":
            sent.append(stop_signal)
            signal.raise_signal(stop_signal)
        return value

    path = run_best_effort_mock(plan, tmp_path, reading_override=interrupt_second_test)
    run, samples = evidence(path)
    assert sent == [stop_signal] and run["execution_status"] == expected_status and run["errors"]
    assert run["points"][0]["qualification"] == "valid" and run["points"][0]["acquisition_cycle_ids"]
    assert run["points"][1]["qualification"] == "inconclusive" and run["points"][1]["acquisition_cycle_ids"] == []
    assert run["method"][METHOD_KEY]["tests"]["hold-1"]["completed"] and not run["method"][METHOD_KEY]["tests"]["hold-2"]["completed"]
    partial = [row for row in samples if row["point_id"] == "p0002" and row["phase"] == "acquiring"]
    assert [row["quantity"] for row in partial] == ["Vin_V"]
    assert verified_off(run)
    assert {number: signal.getsignal(number) for number in previous} == previous


def test_absolute_limit_stops_the_run_even_inside_the_expected_off_interruption(tmp_path):
    plan = build_plan(*profiles(LINE_INTERRUPTION_TEST_TYPE, poll_s=.5))

    def overcurrent_during_the_interruption(quantity, value, point, phase):
        return .2 if quantity == "Iout_A" and phase == "interruption" else value

    run, _ = evidence(run_best_effort_mock(plan, tmp_path, reading_override=overcurrent_during_the_interruption))
    assert run["execution_status"] == "aborted" and run["stop"]["classification"] == "absolute-protective-limit"
    assert run["stop"]["output_off_expected"] is True and run["stop"]["level_kind"] == "interruption" and run["stop"]["procedure_stage"] == "interruption"
    assert "Absolute output-current limit 0.15 A exceeded" in run["errors"][0]
    assert run["points"][0]["qualification"] == "inconclusive" and verified_off(run)
    assert not run["method"][METHOD_KEY]["tests"]["stimulus"]["completed"] and run["method"][METHOD_KEY]["tests"]["stimulus"]["repeats"] == []


def test_output_still_off_after_the_recovery_window_stops_with_the_cause_unclassified(tmp_path):
    seen_recovery = []

    def output_stays_off(quantity, value, point, phase):
        if phase == "recovery":
            seen_recovery.append(phase)
        if quantity == "Vout_V" and seen_recovery and phase in ("recovery", "acquiring"):
            return 0.
        return value

    run, _ = evidence(run_best_effort_mock(build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE, repeats=1)), tmp_path, reading_override=output_stays_off))
    assert run["execution_status"] == "aborted" and run["stop"]["classification"] == "normal-regulation-rule"
    assert run["stop"]["output_off_expected"] is False and run["stop"]["procedure_stage"] == "observation"
    assert "below the 10.8 V minimum outside the expected-off window (recovery); cause unclassified" in run["errors"][0]
    assert verified_off(run)


# --- dispatch and refusals ------------------------------------------------------------------------------------------

def test_real_path_refuses_and_the_generic_mock_loop_refuses_the_types(tmp_path):
    for kind in BEST_EFFORT_TEST_TYPES:
        real = build_plan(*profiles(kind, mode="real"))
        assert all(p.status != "executable" for p in real.points)
        with pytest.raises(ValueError, match="mock profiles only"):
            run_best_effort_mock(real, tmp_path)
        with pytest.raises(ValueError, match="not approved for real hardware"):
            BestEffortProcedure(real)
        with pytest.raises(ValueError):
            acquire_mock(real, tmp_path)
    assert not list(tmp_path.iterdir())
    mock = build_plan(*profiles(MICRO_INTERRUPTION_TEST_TYPE))
    with pytest.raises(ValueError, match="steady_state_load_sweep tests only"):
        run_mock(mock, tmp_path)
    assert not list(tmp_path.iterdir())


def test_acquire_mock_dispatches_the_four_types_and_refuses_mixtures_and_scenarios(tmp_path):
    plan = build_plan(*profiles(TRANSIENT_HOLD_TEST_TYPE, repeats=1))
    run, _ = evidence(acquire_mock(plan, tmp_path, operator_observations=["synthetic jump start"]))
    assert METHOD_KEY in run["method"] and run["operator_observations"] == ["synthetic jump start"]
    with pytest.raises(ValueError, match="no failure-injection scenarios"):
        acquire_mock(plan, tmp_path, scenario="aborted")
    dut, bench, recipe = profiles(TRANSIENT_HOLD_TEST_TYPE)
    recipe.tests = recipe.tests + [default_plan().recipe.tests[0]]
    with pytest.raises(ValueError, match="mixes a best-effort"):
        acquire_mock(build_plan(dut, bench, recipe), tmp_path / "mixed")
    assert not (tmp_path / "mixed").exists()


# --- the plant ------------------------------------------------------------------------------------------------------

def test_hold_up_model_and_live_output_commands_on_the_plant():
    hold_up = HoldUpModel(input_capacitance_F=.01)
    assert hold_up.hold_up_s(12., 8.6, 1.838) == pytest.approx(.01 * (144. - 73.96) / (2 * 1.838))
    assert hold_up.voltage_after_constant_power(12., 1.838, 0.) == 12. and hold_up.constant_power_decay_s(8., 8.6, 1.) == 0.
    assert hold_up.constant_current_decay_s(8.6, 4.5, .004) == pytest.approx((8.6 - 4.5) * .01 / .004)
    with pytest.raises(ValueError):
        HoldUpModel(input_capacitance_F=0.)
    assert ReadbackModel.clean(**ReadbackModel.recorded_round_trips()).round_trip_max_s == .055 and ReadbackModel.clean().round_trip_max_s == .002
    bench = UvloMockBench(12., .5, .15, uvlo=SyntheticUvlo(), startup=StartupModel(), readback=ReadbackModel.clean(), hold_up=hold_up)
    bench.configure(12., LOAD_A, 0.)
    bench.source_on()
    assert bench.state(3.).output_voltage_V > 11.9, "generic soft start: 1 s delay, 0.3 s time constant"
    bench.load_on(3.)
    assert bench.state(3.5).output_voltage_V > 11.9 and bench.status()["source_output"] == "ON"
    bench.set_output(False, 4., effective_at=4.01)
    riding = bench.state(4.05)
    assert riding.output_voltage_V > 11.9 and riding.source_mode == "OFF" and riding.source_voltage_V == 0. and riding.input_current_A == 0.
    assert 8.6 < riding.dut_input_voltage_V < 12. and bench.status()["source_output"] == "OFF"
    assert bench.state(4.15).output_voltage_V > 11.9, "10 mF rides through 140 ms at light load"
    tripped = bench.state(4.4)
    assert tripped.output_voltage_V == 0. and not tripped.load_compliance
    trip = bench.uvlo.transitions[-1]
    assert trip["to"] == "off" and 4.15 < trip["monotonic_s"] < 4.25, "placed at the solved crossing, not at the query time"
    bench.set_output(True, 5., effective_at=5.02)
    restarting = bench.state(5.1)
    assert 0. < restarting.output_voltage_V < 6. and restarting.source_mode == "CV" and restarting.source_voltage_V == 12.
    assert bench.state(6.).output_voltage_V > 10.8 and bench.uvlo.transitions[-1]["to"] == "on"
    # A setpoint below the node: the supply cannot sink, so the node decays through the converter's draw and trips.
    bench.set_live_voltage(4.5, 7., effective_at=7.01)
    assert bench.state(7.05).output_voltage_V > 11.9 and bench.state(7.05).source_voltage_V > 4.5, "still riding on the capacitor"
    after_trip = bench.state(9.)
    assert after_trip.output_voltage_V == 0. and 4.5 < after_trip.dut_input_voltage_V < 8.6, "standby current discharges 10 mF at 0.4 V/s"
    assert after_trip.source_voltage_V == after_trip.dut_input_voltage_V and after_trip.source_mode == "CV", "the supply is back-driven by the node"
    assert bench.state(20.).dut_input_voltage_V == pytest.approx(4.5 - .004 * .06, abs=1e-6), "the node settles on the setpoint (minus the standby lead drop) once the supply holds it"
    bench.set_live_voltage(12., 20., effective_at=20.01)
    assert bench.state(21.).output_voltage_V > 10.8
    # Programs: whole seconds only, never both at once; the end state turns the output off.
    with pytest.raises(ValueError, match="whole number of seconds"):
        bench.program_delayer([("OFF", .5)], 22.)
    program = bench.program_delayer([("ON", 1), ("OFF", 1), ("ON", 2)], 22., start_latency_s=.01)
    assert program["ends_at"] == pytest.approx(26.01) and bench.program_status(23.)["running"]
    with pytest.raises(RuntimeError, match="cannot be enabled together"):
        bench.program_timer([(12., .5, 1)], 23.)
    assert bench.state(23.5).source_mode == "OFF" and bench.state(24.5).source_mode == "CV"
    assert bench.state(26.5).source_mode == "OFF" and not bench.output_live and bench.program_status(26.5)["running"] is False
    # Legacy plant (no hold-up): a live OFF trips at once, and set_live_voltage keeps its immediate behaviour.
    legacy = UvloMockBench(12., .5, .15)
    legacy.configure(12., LOAD_A, 0.)
    legacy.source_on()
    legacy.load_on()
    assert legacy.state(1.).output_voltage_V > 11.9
    legacy.set_live_voltage(11., 2.)
    assert legacy.source_voltage == 11. and legacy.live_changes == [{"monotonic_s": 2., "from_V": 12., "to_V": 11.}]
    legacy.set_output(False, 3.)
    assert legacy.state(3.).output_voltage_V == 0. and legacy.uvlo.transitions[-1] == {"monotonic_s": 3., "to": "off", "dut_input_V": 0.}


def test_mock_best_effort_path_imports_no_real_driver_modules():
    forbidden = {"benchctl", "pyvisa", "dcdc_bench.bringup", "dcdc_bench.extended", "dcdc_bench.real_backend",
                 "dcdc_bench.source_limit", "dcdc_bench.startup_descent", "dcdc_bench.voltage_sweep"}
    source_dir = Path(domain.__file__).parent
    for name in ("best_effort_procedures.py", "_best_effort_contract.py", "mock_uvlo.py", "adapters.py"):
        if not (source_dir / name).exists():
            continue
        tree = ast.parse((source_dir / name).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.add("dcdc_bench." + module.lstrip(".") if node.level else module)
        assert not imported & forbidden, (name, imported & forbidden)
