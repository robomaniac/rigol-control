"""Three-voltage policy exercised through fake SCPI and the real drivers."""
import json
import signal

import pytest

from dcdc_bench.analysis import analyze_run
from dcdc_bench.extended import ExtendedAbort
from dcdc_bench.planning import verify_plan_hash
from dcdc_bench.storage import RunStore, verify_integrity
from dcdc_bench.voltage_sweep import (PHASES, VoltageSweepProcedure, VoltageSweepRigol,
                                    _validated_12v_attempt, run_voltage_sweep, voltage_sweep_plan)
from test_extended import fake_bench, writes


def bench(tmp_path, monkeypatch, **options):
    import benchctl.transport
    fake = fake_bench(tmp_path, monkeypatch, **options)
    transport = benchctl.transport.VisaTransport
    old_write, old_query = transport.write, transport.query

    def write(self, command):
        if command.startswith(":SOUR1:VOLT "):
            assert not self.enabled and self.delay == "OFF" and not fake.sessions["load"].enabled
        old_write(self, command)
        for prefix, query in ((":OUTP:OVP:VAL CH1,", ":OUTP:OVP:VAL? CH1"),
                              (":OUTP:OCP:VAL CH1,", ":OUTP:OCP:VAL? CH1"),
                              (":SOUR:CURR:ILIM ", ":SOUR:CURR:ILIM?")):
            if command.startswith(prefix):
                self.responses[query] = command[len(prefix):]

    def query(self, command):
        value = old_query(self, command)
        if command == ":MEAS:CURR? CH1" and self.enabled:
            current = fake.sessions["load"].request if fake.sessions["load"].enabled else 0.
            return str(.01 + current * 12.1 / (self.voltage * .90))
        return value

    monkeypatch.setattr(transport, "write", write)
    monkeypatch.setattr(transport, "query", query)
    return fake


def execute(fake):
    path = run_voltage_sweep(fake.config, fake.out, arm=True)
    return path, json.loads((path / "run.json").read_text())


def test_plan_preserves_nominal_grid_and_transparent_near36_condition():
    plan = voltage_sweep_plan()
    assert verify_plan_hash(plan) and len(plan.points) == 35
    assert [sum(p.vin_target_V == voltage for p in plan.points) for voltage in (12, 24, 36)] == [8, 13, 14]
    assert plan.bench.protective_controls.source_current_limit_A == 1
    assert max(p.iout_target_A for p in plan.points) == 2.5
    assert any("35.8" in note and "36" in note for note in plan.bench.notes)
    assert plan.recipe.acquisition.duration_s == 8 and all(p.status == "executable" for p in plan.points)
    assert plan.dut.ratings.input_voltage_min_V == 9 and plan.dut.ratings.input_voltage_max_V == 36


def test_unarmed_request_never_opens_config_or_hardware(tmp_path):
    with pytest.raises(ExtendedAbort, match="--arm"):
        run_voltage_sweep(tmp_path / "missing", tmp_path / "runs")
    assert not list(tmp_path.iterdir())


def test_complete_three_voltage_run_has_separate_raw_evidence_and_off_transitions(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    path, run = execute(fake)
    assert run["execution_status"] == "completed" and not run["errors"]
    assert all(p["qualification"] == "valid" for p in run["points"])
    assert len(run["executed_point_ids"]) == len(set(run["executed_point_ids"])) == 35
    assert fake.clock.value < 660
    source = writes(fake, "source")
    assert [command for command in source if command.startswith(":SOUR1:VOLT ")] == [
        ":SOUR1:VOLT 12.0", ":SOUR1:VOLT 24.0", ":SOUR1:VOLT 35.8"]
    assert source.count(":DELAY ON") == 3
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    phases = run["method"]["voltage_efficiency_sweep"]["phases"]
    assert [len(p["qualified_point_ids"]) for p in phases] == [8, 13, 14]
    assert phases[-1]["highest_qualified_point"]["Vin_V"] == 35.8
    rows = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    by_id = {point["point_id"]: point for point in run["points"]}
    for row in rows:
        if row["quantity"] == "Vin_V":
            target = by_id[row["point_id"]]["vin_target_V"]
            assert row["value"] == (35.8 if target == 36 else target)
    assert all(len(p["acquisition_cycle_ids"]) >= 5 and p["acquisition_elapsed_s"] >= 8 for p in run["points"])
    verify_integrity(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert all(p["qualification"] == "valid" and p["efficiency_pct"] is not None for p in analysis["points"])


def test_cc_boundary_is_excluded_and_next_voltage_starts_at_light_load(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.mode

    def mode(pilot):
        if pilot.voltage == 12 and fake.sessions["load"].request >= .6:
            return "CC"
        return original(pilot)

    monkeypatch.setattr(VoltageSweepRigol, "mode", mode)
    path, run = execute(fake)
    assert run["execution_status"] == "completed"
    twelve = [p for p in run["points"] if p["vin_target_V"] == 12]
    assert [p["qualification"] for p in twelve] == ["valid"] * 5 + ["setup-limited", "not-run", "not-run"]
    assert twelve[5]["acquisition_cycle_ids"] == []
    assert all(p["qualification"] == "valid" for p in run["points"] if p["vin_target_V"] != 12)
    commands = fake.commands
    boundary_query = next(i for i, (role, kind, command) in enumerate(commands)
                          if role == "load" and kind == "write" and command == ":SOUR:CURR:LEV:IMM 0.6")
    next_write = next(command for role, kind, command in commands[boundary_query + 1:] if kind == "write")
    assert next_write == ":OUTP CH1,OFF"
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert next(p for p in analysis["points"] if p["point_id"] == twelve[5]["point_id"])["efficiency_pct"] is None
    verify_integrity(path)


def test_upper_voltage_readback_aborts_all_and_preserves_startup_attempt(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.read

    def read(pilot, quantity):
        value = original(pilot, quantity)
        return 35.94 if quantity == "Vin_V" and pilot.voltage > 35 else value

    monkeypatch.setattr(VoltageSweepRigol, "read", read)
    path, run = execute(fake)
    assert run["execution_status"] == "aborted" and "input-voltage guard" in run["errors"][0]
    thirtysix = [p for p in run["points"] if p["vin_target_V"] == 36]
    assert thirtysix[0]["qualification"] == "inconclusive"
    assert thirtysix[0]["point_id"] == run["executed_point_ids"][-1]
    assert all(p["qualification"] == "not-run" for p in thirtysix[1:])
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    verify_integrity(path)


def test_hard_output_fault_never_advances_to_next_voltage(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, fault_at_load_A=.3)
    _, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert [c for c in writes(fake, "source") if c.startswith(":SOUR1:VOLT ")] == [":SOUR1:VOLT 12.0"]
    assert all(p["qualification"] == "not-run" for p in run["points"] if p["vin_target_V"] != 12)


def test_qualified_input_target_ends_phase_without_attempting_remaining_loads(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.read

    def read(pilot, quantity):
        value = original(pilot, quantity)
        return .985 if quantity == "Iin_A" and pilot.voltage == 24 and fake.sessions["load"].request >= 1.5 else value

    monkeypatch.setattr(VoltageSweepRigol, "read", read)
    _, run = execute(fake)
    phase = run["method"]["voltage_efficiency_sweep"]["phases"][1]
    assert run["execution_status"] == "completed" and "Target mean" in phase["stop_reason"]
    assert phase["highest_qualified_point"]["Iin_A"] == .985
    assert phase["highest_qualified_point"]["Iout_A"] == 1.5
    assert all(p["qualification"] == "not-run" for p in run["points"]
               if p["vin_target_V"] == 24 and p["iout_target_A"] > 1.5)
    assert all(p["qualification"] == "valid" for p in run["points"] if p["vin_target_V"] == 36)


def test_failed_source_off_preserves_deadline_and_never_changes_voltage(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, fail_source_off=True)
    _, run = execute(fake)
    assert run["execution_status"] == "error"
    assert ":DELAY OFF" not in writes(fake, "source")
    assert fake.sessions["source"].delay == "ON"
    assert run["shutdown"]["load"] == {"state": "OFF", "verified": True}
    assert ":SOUR1:VOLT 24.0" not in writes(fake, "source")


def test_failed_load_off_blocks_voltage_change_and_rearm(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, fail_load_off=True)
    _, run = execute(fake)
    assert run["execution_status"] == "error"
    assert writes(fake, "source").count(":DELAY ON") == 1
    assert ":SOUR1:VOLT 24.0" not in writes(fake, "source")
    assert run["shutdown"]["source"] == {"state": "OFF", "verified": True}


def test_residual_voltage_decay_is_polled_only_while_off_before_reconfiguration(tmp_path, monkeypatch):
    import benchctl.transport
    fake = bench(tmp_path, monkeypatch)
    transport = benchctl.transport.VisaTransport
    original = transport.query
    off_reads = 0

    def query(self, command):
        nonlocal off_reads
        value = original(self, command)
        if command == ":MEAS:VOLT? CH1" and self.was_started and not self.enabled:
            assert not fake.sessions["load"].enabled and self.delay == "OFF"
            off_reads += 1
            return "1.0" if off_reads < 4 else value
        return value

    monkeypatch.setattr(transport, "query", query)
    path, run = execute(fake)
    assert run["execution_status"] == "completed"
    events = [json.loads(row) for row in (path / "raw/events.jsonl").read_text().splitlines()]
    waits = [event for event in events if event["event"] == "voltage_phase_outputs_off"]
    assert waits[0]["source_off_decay_wait_s"] >= .6 and waits[0]["residual_source_V"] <= .5


def test_persistent_residual_voltage_blocks_next_phase(tmp_path, monkeypatch):
    import benchctl.transport
    fake = bench(tmp_path, monkeypatch)
    transport = benchctl.transport.VisaTransport
    original = transport.query

    def query(self, command):
        value = original(self, command)
        return "1.0" if command == ":MEAS:VOLT? CH1" and self.was_started and not self.enabled else value

    monkeypatch.setattr(transport, "query", query)
    _, run = execute(fake)
    assert run["execution_status"] == "aborted" and "Residual source" in run["errors"][0]
    assert ":SOUR1:VOLT 24.0" not in writes(fake, "source")
    assert writes(fake, "source").count(":DELAY ON") == 1


def test_timer_reverification_failure_blocks_later_phase_start(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.verify_deadline_configuration

    def verify(pilot):
        if pilot.voltage == 24:
            raise ExtendedAbort("Injected invalid second-phase timer")
        return original(pilot)

    monkeypatch.setattr(VoltageSweepRigol, "verify_deadline_configuration", verify)
    _, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert writes(fake, "source").count(":DELAY ON") == 1
    assert all(p["qualification"] == "not-run" for p in run["points"] if p["vin_target_V"] != 12)
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())


def test_time_reserve_does_not_start_another_phase(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    append = RunStore.append

    def inject_time(store, stream, row):
        if stream == "events" and row["event"] == "voltage_phase_complete":
            fake.clock.value = max(fake.clock.value, 600.)
        return append(store, stream, row)

    monkeypatch.setattr(RunStore, "append", inject_time)
    _, run = execute(fake)
    assert run["execution_status"] == "completed"
    assert writes(fake, "source").count(":DELAY ON") == 1
    assert all(p["qualification"] == "not-run" for p in run["points"] if p["vin_target_V"] != 12)
    assert "time budget" in run["method"]["voltage_efficiency_sweep"]["phases"][1]["stop_reason"]


def test_global_deadline_during_later_startup_stops_all_outputs(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    append = RunStore.append
    fired = False

    def interrupt(store, stream, row):
        nonlocal fired
        if not fired and stream == "samples" and row["test_id"] == "efficiency-24v":
            fired = True
            fake.handlers[signal.SIGALRM](signal.SIGALRM, None)
        return append(store, stream, row)

    monkeypatch.setattr(RunStore, "append", interrupt)
    _, run = execute(fake)
    assert fired and run["execution_status"] == "aborted"
    assert "660 second" in run["errors"][0]
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    assert not any(p["qualification"] == "valid" for p in run["points"] if p["vin_target_V"] != 12)


@pytest.mark.parametrize("quantity,value", [("Vin_V", 35.94), ("Iin_A", 1.021), ("Vout_V", 13.21), ("Iout_A", 2.551)])
def test_absolute_faults_are_not_recoverable_phase_boundaries(quantity, value):
    procedure = VoltageSweepProcedure()
    procedure.phase = PHASES[-1]
    values = {"Vin_V": 35.8, "Iin_A": .9, "Vout_V": 12., "Iout_A": 2.4}
    values[quantity] = value
    with pytest.raises(ExtendedAbort) as caught:
        procedure.guard(values, 2.4)
    assert type(caught.value) is ExtendedAbort


def test_low_output_at_fifth_source_only_observation_never_enables_load(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.read

    def read(pilot, quantity):
        value = original(pilot, quantity)
        return 8. if quantity == "Vout_V" else value

    monkeypatch.setattr(VoltageSweepRigol, "read", read)
    path, run = execute(fake)
    assert run["execution_status"] == "aborted" and "source-only startup" in run["errors"][0]
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    assert ":SOUR1:VOLT 24.0" not in writes(fake, "source")
    assert run["executed_point_ids"] == ["p0001"]
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    verify_integrity(path)


def prior_startup_abort(tmp_path, monkeypatch):
    """Create a finalized synthetic-instrument boundary fixture, never hardware."""
    fake = bench(tmp_path, monkeypatch)
    original = VoltageSweepRigol.read

    def read(pilot, quantity):
        value = original(pilot, quantity)
        if pilot.voltage == 12 and fake.sessions["load"].enabled:
            return {"Vin_V": 2.7, "Iin_A": 1.0}.get(quantity, value)
        return value

    with monkeypatch.context() as patch:
        patch.setattr(VoltageSweepRigol, "read", read)
        path, run = execute(fake)
    assert run["execution_status"] == "aborted" and run["errors"][0].startswith("BenchBoundary:")
    return fake, path, run


def test_continuation_never_repeats_12v_and_preserves_prior_evidence(tmp_path, monkeypatch):
    _, prior_path, prior = prior_startup_abort(tmp_path, monkeypatch)
    before = {str(path.relative_to(prior_path)): path.read_bytes() for path in prior_path.rglob("*") if path.is_file()}
    fake = bench(tmp_path, monkeypatch)
    path = run_voltage_sweep(fake.config, fake.out, arm=True, continue_after_12v_startup=prior_path)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and len(run["points"]) == 27
    assert {p["vin_target_V"] for p in run["points"]} == {24., 36.}
    assert run["executed_point_ids"][0] == "p0009"
    assert [command for command in writes(fake, "source") if command.startswith(":SOUR1:VOLT ")] == [
        ":SOUR1:VOLT 24.0", ":SOUR1:VOLT 35.8"]
    assert writes(fake, "source").count(":DELAY ON") == 2
    sweep = run["method"]["voltage_efficiency_sweep"]
    assert sweep["prior_input_attempt"]["run_id"] == prior["run_id"]
    assert sweep["prior_input_attempt"]["last_startup_cycle"]["Vin_V"] == 2.7
    assert sweep["phases"][0]["status"] == "previous-attempt-unqualified"
    assert sweep["phases"][0]["executed_point_ids"] == []
    samples = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert samples[0]["test_id"] == "efficiency-24v"
    assert all(row["test_id"] != "efficiency-12v" for row in samples)
    assert before == {str(file.relative_to(prior_path)): file.read_bytes() for file in prior_path.rglob("*") if file.is_file()}
    verify_integrity(prior_path)
    verify_integrity(path)


@pytest.mark.parametrize("change", ["unsafe-off", "accepted-point", "wrong-error", "later-attempt", "identity", "wrong-plan", "unhashed"])
def test_continuation_prerequisite_rejections_never_open_new_hardware(tmp_path, monkeypatch, change):
    fake, prior_path, prior = prior_startup_abort(tmp_path, monkeypatch)
    if change == "unsafe-off":
        prior["shutdown"]["source"]["verified"] = False
    elif change == "accepted-point":
        prior["points"][0]["qualification"] = "valid"
    elif change == "wrong-error":
        prior["errors"] = ["ExtendedAbort: input overvoltage"]
    elif change == "later-attempt":
        prior["executed_point_ids"].append("p0009")
    elif change == "identity":
        prior["instrument_identities"]["source"]["serial"] = "ANOTHER-SOURCE"
    elif change == "wrong-plan":
        prior["plan_hash"] = "mismatch"
    # This modifies generated test fixtures only, never production run evidence.
    RunStore(prior_path).finalize(prior)
    if change == "unhashed":
        (prior_path / "integrity.json").write_text('{"files":{}}')
    before_commands = list(fake.commands)
    with pytest.raises(ExtendedAbort):
        run_voltage_sweep(fake.config, fake.out, arm=True, continue_after_12v_startup=prior_path)
    assert fake.commands == before_commands


def test_continuation_fails_on_changed_preserved_raw_evidence(tmp_path, monkeypatch):
    fake, prior_path, _ = prior_startup_abort(tmp_path, monkeypatch)
    with (prior_path / "raw/samples.jsonl").open("a") as handle:
        handle.write("\n")
    before = list(fake.commands)
    with pytest.raises(ValueError, match="integrity mismatch"):
        _validated_12v_attempt(prior_path, fake.config)
    assert fake.commands == before
