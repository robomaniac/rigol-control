"""Process ownership, qualification and retained evidence under injected faults."""
from __future__ import annotations

import json
import math
import multiprocessing
import os
import signal
import time
import uuid
from collections import defaultdict
from pathlib import Path

import pytest
from filelock import FileLock

from dcdc_bench.adapters import MODEL_PARAMETERS, MockBench, ReadbackModel, StartupModel
from dcdc_bench.domain import Plan, RawSample
from dcdc_bench.mock_uvlo import UvloMockBench
from dcdc_bench.planning import build_plan, mock_run_estimate, prepare_mock_plan
from dcdc_bench.runner import BOUNDARY_REASON, STARTUP_FAILURE_REASON, _lock_paths, run_mock
from dcdc_bench.services import default_plan
from dcdc_bench.storage import PersistenceError, atomic_json, verify_integrity


def small_plan(currents=(0., .05, .1, .2, .25)):
    original = default_plan()
    bench, recipe = original.bench.model_copy(deep=True), original.recipe.model_copy(deep=True)
    # Independent fixtures may execute alongside the human-facing demo.
    suffix = uuid.uuid4().hex
    bench.source.instrument_id += suffix
    bench.load.instrument_id += suffix
    for quantity, binding in bench.measurements.items():
        binding.instrument_id = bench.source.instrument_id if quantity in ("Vin_V", "Iin_A") else bench.load.instrument_id
    recipe.tests[0].input_voltage_targets_V = [24.]
    recipe.tests[0].output_current_targets_A = list(currents)
    recipe.settling.minimum_dwell_s = .3
    recipe.settling.window_s = .1
    recipe.settling.minimum_fresh_samples = 3
    recipe.settling.timeout_s = 1.
    recipe.acquisition.duration_s = .25
    recipe.acquisition.target_poll_interval_s = .05
    recipe.acquisition.minimum_complete_cycles = 3
    return build_plan(original.dut, bench, recipe)


def evidence(path):
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [RawSample.model_validate_json(line).model_dump() for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    return run, samples


def test_coupled_plant_conserves_power_and_models_source_limit():
    bench = MockBench(12., 1., .15)
    bench.configure(24., 1., 0.)
    bench.source_on()
    bench.load_on()
    # coupled-dc-2.0: the load steps in 10 ms and the converter carries the dynamics (cold-start delay
    # then soft start), so the early observation is the rising output voltage, not a rising load current.
    early, steady = bench.state(1.2), bench.state(20.)
    assert 0 < early.output_voltage_V < steady.output_voltage_V
    assert early.output_current_A == steady.output_current_A == 1.
    for state in (early, steady, bench.state(20., force_limit=True)):
        lead_loss = state.input_current_A**2 * MODEL_PARAMETERS["input_lead_resistance_ohm"]
        assert state.source_voltage_V * state.input_current_A == pytest.approx(
            state.output_voltage_V * state.output_current_A + state.module_loss_W + lead_loss)
    limited = bench.state(20., force_limit=True)
    assert limited.source_mode == "CC" and limited.source_voltage_V < 24.
    assert limited.output_voltage_V < steady.output_voltage_V
    with pytest.raises(RuntimeError, match="OFF"):
        bench.configure(30., 1., 30.)


def test_refit_plant_reproduces_the_recorded_losses_wiring_and_output_offset():
    """M1/m3/m5: 86-87 % above 0.9 A at 24 V, more loss at 36 V, +1 % output with 0.1 ohm path (docs/simulation-plant.md)."""
    def operating_point(vin, iout):
        bench = MockBench(12., 3., 1.3, seed=1)
        bench.configure(vin, iout, 0.)
        bench.source_on(0.)
        bench.load_on(6.)
        state = bench.state(30.)
        assert state.source_mode == "CV"
        pin, pout = state.source_voltage_V * state.input_current_A, state.output_voltage_V * state.output_current_A
        return state, 100 * pout / pin, pin - pout
    _, eta_09, loss_09 = operating_point(24., .9)
    _, eta_1725, loss_1725 = operating_point(24., 1.725)
    _, eta_25_36, loss_25_36 = operating_point(35.8, 2.5)
    state_1, eta_1, loss_1 = operating_point(24., 1.)
    _, eta_1_36, loss_1_36 = operating_point(35.8, 1.)
    assert 85.5 < eta_09 < 87.5 and 86.5 < eta_1725 < 88. and 86. < eta_1 < 87.5   # recorded 86.5 / 87.1 % (eb3bcd)
    assert loss_1725 == pytest.approx(3.05, abs=.15) and loss_25_36 == pytest.approx(4.81, abs=.25)
    assert loss_1_36 - loss_1 == pytest.approx(.2, abs=.1), "about 0.3 W more loss at 36 V than at 24 V"
    assert eta_1_36 < eta_1
    assert state_1.output_voltage_V == pytest.approx(1.01 * 12. - .1 * 1., abs=1e-9)
    assert state_1.dut_input_voltage_V == pytest.approx(24. - state_1.input_current_A * .06)
    assert MODEL_PARAMETERS["input_lead_resistance_ohm"] == .06 and MODEL_PARAMETERS["output_path_resistance_ohm"] == .1


def test_source_current_limit_collapses_to_the_recorded_signature_and_hiccups():
    """B1: a constant-power converter on a current-limited source has no reduced operating point."""
    bench = MockBench(12., 1., 1.3, seed=1)
    bench.configure(12., .9, 0.)
    bench.source_on(0.)
    bench.load_on(6.)
    collapsed = bench.state(30.)
    assert collapsed.source_mode == "CC" and collapsed.output_voltage_V == 0. and not collapsed.load_compliance
    assert collapsed.input_current_A == pytest.approx(1.0005) and collapsed.source_voltage_V == pytest.approx(2.661, abs=1e-3)
    lead_loss = collapsed.input_current_A**2 * MODEL_PARAMETERS["input_lead_resistance_ohm"]
    assert collapsed.source_voltage_V * collapsed.input_current_A == pytest.approx(collapsed.module_loss_W + lead_loss)
    samples = [bench.state(30. + .01 * i) for i in range(1, 60)]
    assert all(s.source_mode == "CC" and s.output_voltage_V == 0. for s in samples), "no benign 90 % plateau"
    assert any(s.source_voltage_V > 5. for s in samples), "the periodic re-fire attempt is visible on Vin"
    assert [t["to"] for t in bench.uvlo.transitions] == ["on", "off"]
    # Lowering the load below the boundary lets the converter restart; a reduced load at 12 V runs in CV.
    bench.set_load_current(.5, 31.)
    assert bench.state(33.).source_mode == "CV" and bench.state(33.).output_voltage_V > 11.9
    # Injected 20 mA limit (setup-limited scenario): same shape at a lower current.
    bench.configure(24., .05, 0.) if False else None
    forced = MockBench(12., 1., .15, seed=1)
    forced.configure(24., .05, 0.)
    forced.source_on(0.)
    forced.load_on(6.)
    limited = forced.state(7., force_limit=True)
    assert limited.source_mode == "CC" and limited.input_current_A == pytest.approx(.0205) and limited.output_voltage_V == 0.


def test_startup_model_stalls_a_12v_cold_start_and_starts_at_15v():
    """M2: recorded plateau near 8 V at 12 V with the load OFF, collapse after load enable, normal start at 15 V."""
    dut = default_plan().dut
    startup = StartupModel.for_dut(dut)
    assert startup.start_threshold_dut_input_V == pytest.approx(12.5), "0.5 V above the recorded failed 12 V start"
    assert StartupModel.for_dut(dut.model_copy(update={"known_behaviours": None})).start_threshold_dut_input_V is None
    for vin, in_band in ((12., False), (15., True), (24., True)):
        bench = MockBench(12., 1., .15, seed=1, startup=startup)
        bench.configure(vin, .05, 0.)
        bench.source_on(0.)
        outputs = [bench.state(float(t)).output_voltage_V for t in range(1, 6)]
        assert outputs == sorted(outputs) and outputs[0] == 0.
        assert (outputs[-1] >= .9 * 12.) is in_band, (vin, outputs)
        if not in_band:
            assert outputs[-1] == pytest.approx(7.98, abs=.01) and bench.state(5.).input_current_A == pytest.approx(.004)
            bench.load_on(5.)
            after_enable = bench.state(6.)
            assert after_enable.source_mode == "CC" and after_enable.source_voltage_V == pytest.approx(2.661, abs=1e-3)
    # Started at 15 V, the converter runs down to the UVLO turn-on level and trips below turn-off.
    bench = UvloMockBench(12., 1., .15, startup=startup)
    bench.configure(15., .1, 0.)
    bench.source_on(0.)
    bench.load_on(0.)
    assert bench.state(5.).output_voltage_V > 11.9
    bench.set_live_voltage(9.2, 10.)
    assert bench.state(12.).output_voltage_V > 11.9
    bench.set_live_voltage(8.5, 20.)
    assert bench.state(22.).output_voltage_V == 0.


def test_readbacks_are_quantised_held_offset_and_realistically_timed():
    """M4/M5/m8: displayed digits, per-channel refresh, +11 mA load offset, 0/11 mA off-state, 4-55 ms round trips."""
    bench = MockBench(12., 1., .15, seed=1)
    bench.configure(24., .5, 0.)
    bench.source_on(0.)
    vin_a, _ = bench.read("Vin_V", 6.)
    vin_b, _ = bench.read("Vin_V", 6.5)
    vin_c, _ = bench.read("Vin_V", 7.2)
    assert vin_a == vin_b, "the source holds its conversion for about 1.1 s"
    assert all(round(v, 3) == v for v in (vin_a, vin_c)), "1 mV displayed digit"
    off_readings = [bench.read("Iout_A", 6. + .5 * i)[0] for i in range(6)]
    assert set(off_readings) <= {0., .011} or all(r == 0. or abs(r - .011) < .001 for r in off_readings)
    assert 0. in off_readings and any(r > .01 for r in off_readings), "bistable 0 / 11 mA with the load input OFF"
    bench.load_on(8.)
    state = bench.state(10.)
    iout, _ = bench.read("Iout_A", 10.)
    assert iout - state.output_current_A == pytest.approx(.011, abs=.001), "recorded +11 mA load current readback offset"
    assert round(iout, 4) == iout
    vout_a, _ = bench.read("Vout_V", 10.)
    vout_b, _ = bench.read("Vout_V", 10.02)
    vout_c, _ = bench.read("Vout_V", 10.06)
    assert vout_a == vout_b and round(vout_c, 4) == vout_c, "the load refreshes every 50 ms at a 0.1 mV digit"
    trips = [bench.query_round_trip_s() for _ in range(200)]
    assert min(trips) >= .004 and max(trips) <= .055 and .004 < sorted(trips)[100] < .015
    clean = MockBench(12., 1., .15, seed=1, readback=ReadbackModel.clean())
    assert clean.query_round_trip_s() == .002 and clean.readback.load_current_offset_A == 0.
    declared = ReadbackModel.realistic({"Vin_V": .01, "Iin_A": None})
    assert declared.quantisation["Vin_V"] == .01 and declared.quantisation["Iin_A"] == .0001


def test_normal_spawn_run_is_deterministic_complete_and_measured(tmp_path):
    plan = small_plan((0., .05, .1))
    # A virtual-clock owner never sleeps: its wall time is interpreter start-up
    # plus one fsync per record, which tracks host I/O load rather than model
    # time. Derive the hung-owner deadline from the plan's own record volume
    # instead of the fixed 60 s default, which a loaded 1 GB Pi can exceed.
    model_s = len(plan.points) * (plan.recipe.settling.timeout_s + plan.recipe.acquisition.duration_s)
    records = 4 * model_s / plan.recipe.acquisition.target_poll_interval_s
    deadline_s = 120. + .5 * records
    first = run_mock(plan, tmp_path, worker_timeout_s=deadline_s)
    second = run_mock(plan, tmp_path, worker_timeout_s=deadline_s)
    run, samples = evidence(first)
    repeated, repeated_samples = evidence(second)
    assert run["execution_status"] == repeated["execution_status"] == "completed", (run["errors"], repeated["errors"])
    assert all(point["qualification"] == "valid" for point in run["points"])
    assert run["model"]["seed"] == 1 and run["clock"]["mode"] == "virtual"
    assert run["software"]["dependency_lock_sha256"]
    assert run["software"]["source_files_sha256"]["runner.py"]
    assert run["real_hardware_opened"] is False
    assert [(s["value"], s["query_start_monotonic_s"]) for s in samples] == [
        (s["value"], s["query_start_monotonic_s"]) for s in repeated_samples]
    cycles = defaultdict(list)
    for sample in samples:
        cycles[sample["acquisition_cycle_id"]].append(sample)
        assert sample["query_end_monotonic_s"] > sample["query_start_monotonic_s"]
        assert sample["location"] and sample["raw_response"]
    for point in run["points"]:
        assert point["settled"]
        for cycle_id in point["acquisition_cycle_ids"]:
            cycle = cycles[cycle_id]
            assert {s["quantity"] for s in cycle} == {"Vin_V", "Iin_A", "Vout_V", "Iout_A"}
            assert len(cycle) == 4
            assert all(s["point_id"] == point["point_id"] and s["status"] == "ok" and s["phase"] == "acquiring" for s in cycle)
            assert next(s["value"] for s in cycle if s["quantity"] == "Vin_V") != point["vin_target_V"]
    assert all(state["state"] == "OFF" and state["verified"] for state in run["shutdown"].values())
    assert run["raw_sample_count"] == len(samples)


def test_plan_exclusions_are_preserved_not_clipped(tmp_path):
    plan = small_plan((.05, 4.))
    run, samples = evidence(run_mock(plan, tmp_path))
    assert len(run["points"]) == len(plan.points) == 2
    excluded = run["points"][1]
    assert excluded["iout_target_A"] == 4. and excluded["qualification"] == "unsupported"
    assert not excluded["acquisition_cycle_ids"]
    assert all(sample["point_id"] != excluded["point_id"] for sample in samples)
    assert json.loads((Path(tmp_path) / run["run_id"] / "plan.json").read_text())["plan_hash"] == plan.plan_hash


def test_run01_os_lock_blocks_another_worker_without_commands(tmp_path):
    plan = small_plan((.05,))
    with FileLock(str(_lock_paths(plan)[0])):
        run, samples = evidence(run_mock(plan, tmp_path))
    assert run["execution_status"] == "error" and "Timeout" in run["errors"][0]
    assert not samples
    assert all(record["state"] == "UNKNOWN" for record in run["shutdown"].values())
    assert all(point["qualification"] == "not-run" for point in run["points"])


def test_run03_query_timeout_preserves_partial_samples_and_stops(tmp_path):
    run, samples = evidence(run_mock(small_plan(), tmp_path, scenario="timeout"))
    assert run["execution_status"] == "error"
    assert any(sample["quality_flags"] == ["timeout"] and sample["value"] is None for sample in samples)
    assert run["points"][0]["qualification"] == "valid"
    assert run["points"][1]["qualification"] == "error"
    assert all(point["qualification"] == "not-run" for point in run["points"][2:])
    assert all(record["state"] == "OFF" for record in run["shutdown"].values())


def test_run04_crashed_worker_retains_evidence_and_never_claims_off(tmp_path):
    run, samples = evidence(run_mock(small_plan(), tmp_path, scenario="crash"))
    assert run["execution_status"] == "interrupted"
    assert samples and any(sample["phase"] == "acquiring" for sample in samples)
    assert all(record["state"] == "UNKNOWN" for record in run["shutdown"].values())
    assert all(not point["acquisition_cycle_ids"] for point in run["points"])


def test_run05_source_limit_invalidates_nominal_metrics(tmp_path):
    run, samples = evidence(run_mock(small_plan(), tmp_path, scenario="setup-limited"))
    limited = run["points"][1]
    assert limited["qualification"] == "setup-limited"
    assert not limited["acquisition_cycle_ids"]
    flagged = [s for s in samples if s["point_id"] == limited["point_id"] and "source-current-limited" in s["quality_flags"]]
    assert flagged
    # B1: the collapse signature, not a benign plateau: Iin pinned just above the (injected 20 mA) limit, nothing delivered.
    assert any(s["quantity"] == "Iin_A" and s["value"] == pytest.approx(.0205 - .0008, abs=.0005) for s in flagged)  # −0.8 mA readback offset
    assert all(s["value"] < 1. for s in flagged if s["quantity"] == "Vout_V")
    # B1: the input-voltage phase stops on the boundary, as the real guard does; higher loads are not attempted.
    assert all(p["qualification"] == "not-run" and BOUNDARY_REASON in p["reason"] for p in run["points"][2:])
    assert not any(s["point_id"] in {p["point_id"] for p in run["points"][2:]} for s in samples)
    assert run["execution_status"] == "completed" and all(s["state"] == "OFF" for s in run["shutdown"].values())


def test_natural_source_boundary_stops_the_phase_and_reads_like_the_recorded_event(tmp_path):
    """B1 without fault injection: at 12 V the refit plant meets the 1 A source near 0.85-0.9 A output."""
    plan = small_plan((.5, .9, .95))
    dut = plan.dut.model_copy(update={"known_behaviours": None})  # generic start so the 12 V phase runs
    recipe = plan.recipe.model_copy(deep=True)
    recipe.tests[0].input_voltage_targets_V = [12.]
    recipe.planning.efficiency_estimate_fraction = recipe.planning.source_current_budget_fraction = 1.
    plan = build_plan(dut, plan.bench, recipe)
    assert [p.status for p in plan.points] == ["executable"] * 3
    run, samples = evidence(run_mock(plan, tmp_path))
    assert [p["qualification"] for p in run["points"]] == ["valid", "setup-limited", "not-run"]
    flagged = [s for s in samples if s["point_id"] == "p0002" and "source-current-limited" in s["quality_flags"]]
    assert flagged and {s["phase"] for s in flagged} >= {"boundary"}
    # The held source readback may lag the first CC reading (as a real 1.1 s refresh would at a fast poll);
    # the confirming cycle 1.2 s later is the retained boundary observation and shows the recorded signature.
    observed = run["points"][1]["boundary_observation"]
    assert observed["source_mode"] == "CC"
    assert observed["values"]["Iin_A"] == pytest.approx(1.0005 - .0008, abs=.0003), "Iin just above the 1 A setting"
    assert observed["values"]["Vin_V"] == pytest.approx(2.661 + .003, abs=.01), "source terminal near 2.66 V as recorded"
    assert observed["values"]["Vout_V"] < .01
    assert BOUNDARY_REASON in run["points"][2]["reason"]


def test_cold_start_gate_refuses_the_recorded_12v_start_and_the_15v_phase_runs(tmp_path):
    """M2: five source-only cycles before the load; a failed gate ends the phase with the real path's wording."""
    plan = small_plan((0., .05, .1))
    recipe = plan.recipe.model_copy(deep=True)
    recipe.tests[0].input_voltage_targets_V = [12., 15.]
    plan = build_plan(plan.dut, plan.bench, recipe)
    assert plan.dut.known_behaviours.cold_start_failed_at_V == [12.]
    assert any("direct cold start at 12 V input failed" in w and "12 V is at or below" in w for w in plan.warnings)
    run, samples = evidence(run_mock(plan, tmp_path))
    twelve, fifteen = run["points"][:3], run["points"][3:]
    assert twelve[0]["qualification"] == "inconclusive" and twelve[0]["reason"] == STARTUP_FAILURE_REASON
    assert twelve[0]["startup_gate"].startswith("failed: output 7.9")
    assert all(p["qualification"] == "not-run" and STARTUP_FAILURE_REASON in p["reason"] for p in twelve[1:])
    gate = [s for s in samples if s["point_id"] == "p0001" and s["phase"] == "starting"]
    assert len(gate) == 20 and all(s["acquisition_settings"]["load_enabled"] is False for s in gate)
    assert max(s["value"] for s in gate if s["quantity"] == "Vout_V") < 8.1, "the recorded ~8 V plateau, load OFF"
    assert not any(s["point_id"] == "p0001" and s["phase"] in ("settling", "acquiring") for s in samples)
    assert all(p["qualification"] == "valid" for p in fifteen), fifteen
    assert fifteen[0]["startup_gate"].startswith("passed: 5 source-only cycles")
    events = [json.loads(line) for line in (tmp_path / run["run_id"] / "raw/events.jsonl").read_text().splitlines()]
    assert [e["stop_reason"] for e in events if e["event"] == "phase_complete" and e.get("stop_reason")] == [STARTUP_FAILURE_REASON]
    assert run["execution_status"] == "completed"


def test_simulated_run_budget_is_estimated_at_planning_and_enforced_by_the_runner(tmp_path):
    """QA M2: record count and wall-time estimate at planning time; a plan beyond the budget is refused, not hard-killed."""
    plan = small_plan((0., .05, .1))
    estimate = mock_run_estimate(plan)
    per_point = 4 * math.ceil((plan.recipe.settling.timeout_s + plan.recipe.acquisition.duration_s) / plan.recipe.acquisition.target_poll_interval_s)
    assert estimate["records"] == 3 * per_point + 5 * 4 + 5 * 4 and estimate["phases"] == 1 and estimate["within_budget"]
    assert any(w.startswith("Simulated run estimate: about ") for w in plan.warnings)
    same, errors, seconds = prepare_mock_plan(plan)
    assert same.plan_hash == plan.plan_hash and errors == [] and seconds == estimate["typical_s"] > 0
    recipe = plan.recipe.model_copy(deep=True)
    recipe.acquisition.duration_s = 3600.
    recipe.settling.timeout_s = 60.
    heavy = build_plan(plan.dut, plan.bench, recipe)
    heavy_estimate = mock_run_estimate(heavy)
    assert not heavy_estimate["within_budget"] and heavy_estimate["deadline_s"] > heavy_estimate["budget_s"] == 2400.
    assert any("The simulated worker refuses this plan" in w for w in heavy.warnings)
    _, errors, _ = prepare_mock_plan(heavy)
    assert len(errors) == 1 and errors[0].startswith("Simulated run refused: the simulated run would write about ")
    with pytest.raises(ValueError, match="Simulated run refused"):
        run_mock(heavy, tmp_path)
    assert not list(tmp_path.iterdir())
    plan.bench.mode = "real"
    with pytest.raises(ValueError, match="mock bench profiles only"):
        prepare_mock_plan(build_plan(plan.dut, plan.bench, plan.recipe))


def _run_mock_in_own_process_group(plan_json: str, out: str) -> None:
    os.setpgrp()  # the service unit's KillMode=control-group signals the whole group; mirror that here
    run_mock(Plan.model_validate_json(plan_json), Path(out), real_time=True)


def test_sigterm_finalizes_the_simulated_run_as_interrupted_with_integrity(tmp_path):
    """QA M2: a service stop or RuntimeMaxSec must leave finalized evidence, not a running run.json."""
    plan = small_plan((0., .05))
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_run_mock_in_own_process_group, args=(plan.model_dump_json(), str(tmp_path)))
    process.start()
    try:
        deadline = time.monotonic() + 30.
        while time.monotonic() < deadline:
            runs = [p for p in tmp_path.iterdir() if (p / "raw/samples.jsonl").exists() and (p / "raw/samples.jsonl").stat().st_size > 0]
            if runs:
                break
            time.sleep(.1)
        assert runs, "the real-time mock run did not start writing samples in time"
        os.killpg(process.pid, signal.SIGTERM)
        process.join(20.)
    finally:
        if process.is_alive():
            process.kill()
            process.join(5.)
    assert process.exitcode == 0, "run_mock returns normally after the plant owner finalized itself"
    run, samples = evidence(runs[0])
    assert run["execution_status"] == "interrupted" and run["lifecycle_state"] == "INTERRUPTED"
    assert any("SIGTERM" in error for error in run["errors"]) and samples
    assert all(record["state"] == "OFF" and record["verified"] for record in run["shutdown"].values())
    assert not any(point["qualification"] == "valid" for point in run["points"])
    assert (runs[0] / "integrity.json").exists()


@pytest.mark.parametrize("scenario,flag", [("stale", "stale"), ("overrange", "overrange"),
                                         ("malformed", "malformed"), ("unsettled", None)])
def test_run06_bad_measurements_never_become_valid_points(tmp_path, scenario, flag):
    run, samples = evidence(run_mock(small_plan(), tmp_path, scenario=scenario))
    point = run["points"][1]
    assert point["qualification"] == "inconclusive"
    assert not point["acquisition_cycle_ids"]
    affected = [sample for sample in samples if sample["point_id"] == point["point_id"]]
    assert affected
    if flag:
        assert any(flag in sample["quality_flags"] for sample in affected)
    else:
        voltages = [sample["value"] for sample in affected if sample["quantity"] == "Vout_V"]
        assert max(voltages) - min(voltages) > .05
    assert run["points"][2]["qualification"] == "valid"


def test_run08_persistence_fault_stops_acquisition_and_retains_prefix(tmp_path):
    run, samples = evidence(run_mock(small_plan(), tmp_path, scenario="diskfailure"))
    assert run["execution_status"] == "error"
    assert len(samples) == 8
    assert "PersistenceError" in run["errors"][0]
    assert not any(point["qualification"] == "valid" for point in run["points"])
    assert all(record["state"] == "OFF" for record in run["shutdown"].values())


def test_cleanup_devices_are_independent(tmp_path):
    run, _ = evidence(run_mock(small_plan((.05,)), tmp_path, scenario="shutdown-failure"))
    assert run["execution_status"] == "error"
    assert run["shutdown"]["load"]["state"] == "UNKNOWN"
    assert run["shutdown"]["source"]["state"] == "OFF"
    assert run["shutdown"]["source"]["verified"]


def test_controlled_abort_preserves_completed_and_unreached_points(tmp_path):
    run, _ = evidence(run_mock(small_plan(), tmp_path, scenario="aborted"))
    assert run["execution_status"] == "aborted"
    assert [point["qualification"] for point in run["points"]] == ["valid"]*3 + ["not-run"]*2
    assert all(record["state"] == "OFF" for record in run["shutdown"].values())


def test_parent_deadline_is_bounded_and_cancellation_retains_partial_run(tmp_path):
    started = time.monotonic()
    run, _ = evidence(run_mock(small_plan(), tmp_path, real_time=True, worker_timeout_s=.15))
    assert time.monotonic() - started < 8
    assert run["execution_status"] in ("aborted", "interrupted")
    assert not all(point["qualification"] == "valid" for point in run["points"])
    # A worker that traps SIGTERM finalizes itself with outputs verified OFF; only a killed worker leaves UNKNOWN.
    if run["execution_status"] == "interrupted" and not (Path(tmp_path) / run["run_id"] / "integrity.json").exists():
        assert all(record["state"] == "UNKNOWN" for record in run["shutdown"].values())


def test_run10_real_profiles_and_changed_plans_cannot_arm_mock(tmp_path):
    plan = small_plan()
    plan.recipe.execution_mode = "real"
    plan.bench.mode = "real"
    real = build_plan(plan.dut, plan.bench, plan.recipe)
    with pytest.raises(ValueError, match="mock profiles only"):
        run_mock(real, tmp_path)
    changed = small_plan()
    changed.points[0].vin_target_V += 1
    with pytest.raises(ValueError, match="hash mismatch"):
        run_mock(changed, tmp_path)
    with pytest.raises(ValueError, match="finite and positive"):
        run_mock(small_plan(), tmp_path, worker_timeout_s=math.nan)
    assert not list(tmp_path.iterdir())


def test_evidence_hash_detects_changes(tmp_path):
    directory = run_mock(small_plan((.05,)), tmp_path)
    samples = directory / "raw/samples.jsonl"
    samples.write_text(samples.read_text() + "{}\n")
    with pytest.raises(ValueError, match="integrity mismatch"):
        verify_integrity(directory)


def test_failed_atomic_replace_preserves_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    atomic_json(target, {"state": "old"})
    def fail_replace(*_):
        raise OSError("injected unavailable disk")
    monkeypatch.setattr("dcdc_bench.storage.os.replace", fail_replace)
    with pytest.raises(PersistenceError):
        atomic_json(target, {"state": "new"})
    assert json.loads(target.read_text()) == {"state": "old"}
    assert list(tmp_path.iterdir()) == [target]
