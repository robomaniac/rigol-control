"""Adaptive source-limit tests use real drivers with fake SCPI only."""
import json

import pytest

from dcdc_bench.analysis import analyze_run
from dcdc_bench.planning import verify_plan_hash
from dcdc_bench.source_limit import (BenchBoundary, SourceLimitProcedure, SourceLimitRigol,
                                    run_source_limit, source_limit_plan)
from dcdc_bench.extended import ExtendedAbort
from dcdc_bench.storage import RunStore, verify_integrity
from test_extended import fake_bench, writes


def bench(tmp_path, monkeypatch, **options):
    overrides = options.pop("query_overrides", {})
    defaults = {("source", ":OUTP:OCP:VAL? CH1"): "1.05", ("load", ":SOUR:CURR:ILIM?"): "2.05"}
    defaults.update(overrides)
    return fake_bench(tmp_path, monkeypatch, query_overrides=defaults, **options)


def execute(fake):
    path = run_source_limit(fake.config, fake.out, arm=True)
    return path, json.loads((path / "run.json").read_text())


def requests(fake):
    return [float(command.split()[-1]) for command in writes(fake, "load") if command.startswith(":SOUR:CURR:LEV:IMM ")]


def test_plan_keeps_conditional_grid_and_separate_return_without_claiming_expected_efficiency():
    plan = source_limit_plan()
    assert verify_plan_hash(plan)
    assert len(plan.points) == 78
    assert len({p.point_id for p in plan.points}) == 78
    assert all(p.vin_target_V == 24 and p.iout_target_A <= 2 for p in plan.points)
    assert plan.bench.source.max_current_A == plan.bench.protective_controls.source_current_limit_A == 1
    assert plan.points[-1].test_id == "decreasing-load" and plan.points[-1].iout_target_A == .1
    assert all("Conditional" in p.reason for p in plan.points)
    assert any("ideal-power" in note for note in plan.bench.notes)


def test_unarmed_request_stops_before_any_hardware_or_config(tmp_path):
    with pytest.raises(ExtendedAbort, match="--arm"):
        run_source_limit(tmp_path / "absent", tmp_path / "runs")
    assert not list(tmp_path.iterdir())


def test_approaches_one_ampere_input_not_one_ampere_output_then_returns(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    path, run = execute(fake)
    assert run["execution_status"] == "completed" and not run["errors"]
    source_writes = writes(fake, "source")
    assert ":SOUR1:CURR 1.0" in source_writes and ":OUTP:OCP:VAL CH1,1.05" in source_writes
    assert max(requests(fake)) == 1.55
    assert requests(fake)[-4:] == [1.5, 1.525, 1.55, .1]
    method = run["method"]
    assert method["target_reached_in_cv"] and method["recovery_attempts"] == 0 and method["return_completed"]
    endpoint_id = method["source_limit_search"]["selected_endpoint_point_id"]
    endpoint = next(p for p in run["points"] if p["point_id"] == endpoint_id)
    assert endpoint["extended_endpoint_window"] and endpoint["acquisition_elapsed_s"] >= 30
    assert .98 <= method["highest_qualified_ascent_point"]["Iin_A"] < .995
    assert run["executed_point_ids"][-1] == "p0078"
    assert len(run["executed_point_ids"]) == len(set(run["executed_point_ids"])) == 18
    assert [next(p for p in run["points"] if p["point_id"] == pid)["execution_index"]
            for pid in run["executed_point_ids"]] == list(range(1, 19))
    assert sum(p["qualification"] == "not-run" for p in run["points"]) == 60
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    verify_integrity(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert len([p for p in analysis["points"] if p["qualification"] == "valid"]) == 18
    return_point = run["points"][-1]
    assert not set(endpoint["acquisition_cycle_ids"]) & set(return_point["acquisition_cycle_ids"])


def test_source_cc_is_preserved_unqualified_then_one_backoff_recovers(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = SourceLimitRigol.mode

    def mode(pilot):
        return "CC" if fake.sessions["load"].request >= 1.3 else original(pilot)

    monkeypatch.setattr(SourceLimitRigol, "mode", mode)
    path, run = execute(fake)
    assert run["execution_status"] == "completed"
    assert requests(fake)[-2:] == [1.3, .1] and max(requests(fake)) == 1.3
    assert run["method"]["recovery_attempts"] == 1 and run["method"]["return_completed"]
    boundary_id = run["method"]["boundary_observation"]["point_id"]
    boundary = next(p for p in run["points"] if p["point_id"] == boundary_id)
    assert boundary["qualification"] == "setup-limited" and boundary["acquisition_cycle_ids"] == []
    assert run["executed_point_ids"][-2:] == [boundary_id, "p0078"]
    rows = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    cc = [r for r in rows if r["acquisition_settings"]["source_mode"] == "CC"]
    assert len(cc) == 4 and all(r["point_id"] == boundary_id for r in cc)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert next(p for p in analysis["points"] if p["point_id"] == boundary_id)["efficiency_pct"] is None
    verify_integrity(path)


def test_endpoint_trigger_and_final_mean_remain_distinct_when_current_drifts(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = SourceLimitRigol.read
    endpoint_reads = 0

    def read(pilot, quantity):
        nonlocal endpoint_reads
        value = original(pilot, quantity)
        if quantity == "Iin_A" and fake.sessions["load"].request >= 1.55:
            endpoint_reads += 1
            value = .99 if endpoint_reads <= 15 else .94  # Five settling + ten trigger readings.
            pilot.supply._transport.last_response = str(value)
        return value

    monkeypatch.setattr(SourceLimitRigol, "read", read)
    _, run = execute(fake)
    assert run["execution_status"] == "completed"
    method = run["method"]
    endpoint = next(p for p in run["points"] if p["point_id"] == method["source_limit_search"]["selected_endpoint_point_id"])
    assert method["target_reached_in_cv"] is True
    assert endpoint["endpoint_trigger"]["input_current_mean_A"] == pytest.approx(.99)
    assert method["endpoint_final_mean_input_A"] < .98
    assert endpoint["iout_target_A"] == 1.55 and endpoint["acquisition_elapsed_s"] >= 30


def test_recovery_is_observed_before_slow_explanatory_checkpoint(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original_mode, append = SourceLimitRigol.mode, RunStore.append

    def mode(pilot):
        return "CC" if fake.sessions["load"].request >= .3 else original_mode(pilot)

    def delayed_event(store, stream, row):
        if stream == "events" and row["event"] == "boundary_then_light_load_backoff":
            fake.clock.sleep(10)
        return append(store, stream, row)

    monkeypatch.setattr(SourceLimitRigol, "mode", mode)
    monkeypatch.setattr(RunStore, "append", delayed_event)
    _, run = execute(fake)
    assert run["execution_status"] == "completed"
    assert run["method"]["recovery_verified_cv"] is True
    assert 1 <= run["method"]["backoff_to_recovery_observation_elapsed_s"] < 2


def test_failed_single_recovery_aborts_without_retry_or_new_increase(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = SourceLimitRigol.mode
    tripped = False

    def mode(pilot):
        nonlocal tripped
        tripped |= fake.sessions["load"].request >= .3
        return "CC" if tripped else original(pilot)

    monkeypatch.setattr(SourceLimitRigol, "mode", mode)
    path, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert requests(fake) == [.1, .2, .3, .1]
    assert run["method"]["recovery_attempts"] == 1
    assert run["points"][-1]["qualification"] == "inconclusive"
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    verify_integrity(path)


def test_output_overvoltage_aborts_directly_without_backoff_or_return(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, fault_at_load_A=.3)
    _, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert requests(fake) == [.1, .2, .3]
    assert "Absolute output guard" in run["errors"][0]
    assert run["points"][-1]["qualification"] == "not-run"
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())


@pytest.mark.parametrize("values,modes,error", [
    ({"Vin_V": 24., "Iin_A": .995, "Vout_V": 12., "Iout_A": 1.6}, ("CV", "CV"), BenchBoundary),
    ({"Vin_V": 23.4, "Iin_A": .98, "Vout_V": 12., "Iout_A": 1.6}, ("CV", "CV"), BenchBoundary),
    ({"Vin_V": 24., "Iin_A": .98, "Vout_V": 12., "Iout_A": 1.6}, ("CV", "CC"), BenchBoundary),
    ({"Vin_V": 24., "Iin_A": 1.021, "Vout_V": 12., "Iout_A": 1.6}, ("CC", "CC"), ExtendedAbort),
    ({"Vin_V": 24., "Iin_A": .98, "Vout_V": 13.21, "Iout_A": 1.6}, ("CV", "CV"), ExtendedAbort),
])
def test_boundary_and_hard_fault_classifications(values, modes, error):
    with pytest.raises(error) as caught:
        SourceLimitProcedure.guard(values, 1.6, mode_before=modes[0], mode_after=modes[1])
    assert type(caught.value) is error


def test_wrong_one_ampere_protection_readback_blocks_energization(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, query_overrides={("source", ":OUTP:OCP:VAL? CH1"): "1.1"})
    _, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert ":DELAY ON" not in writes(fake, "source")
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
