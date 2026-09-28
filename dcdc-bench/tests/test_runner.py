"""Process ownership, qualification and retained evidence under injected faults."""
from __future__ import annotations

import json
import math
import time
import uuid
from collections import defaultdict
from pathlib import Path

import pytest
from filelock import FileLock

from dcdc_bench.adapters import MODEL_PARAMETERS, MockBench
from dcdc_bench.domain import RawSample
from dcdc_bench.planning import build_plan
from dcdc_bench.runner import _lock_paths, run_mock
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
    early, steady = bench.state(.1), bench.state(20.)
    assert 0 < early.output_current_A < steady.output_current_A
    for state in (early, steady, bench.state(20., force_limit=True)):
        lead_loss = state.input_current_A**2 * MODEL_PARAMETERS["input_lead_resistance_ohm"]
        assert state.source_voltage_V * state.input_current_A == pytest.approx(
            state.output_voltage_V * state.output_current_A + state.module_loss_W + lead_loss)
    limited = bench.state(20., force_limit=True)
    assert limited.source_mode == "CC" and limited.source_voltage_V < 24.
    assert limited.output_voltage_V < steady.output_voltage_V
    with pytest.raises(RuntimeError, match="OFF"):
        bench.configure(30., 1., 30.)


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
    assert any(sample["point_id"] == limited["point_id"] and "source-current-limited" in sample["quality_flags"] for sample in samples)
    assert run["points"][2]["qualification"] == "valid"


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
    if run["execution_status"] == "interrupted":
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
