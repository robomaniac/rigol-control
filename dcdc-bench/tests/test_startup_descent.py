"""Fixed startup/descent exercised through fake SCPI and real drivers only."""
import json

import pytest

from dcdc_bench.analysis import analyze_run, build_report_model
from dcdc_bench.domain import Plan
from dcdc_bench.extended import ExtendedAbort
from dcdc_bench.planning import verify_plan_hash
from dcdc_bench.startup_descent import (PROGRAMMED_INPUTS, StartupDescentRigol,
                                      run_startup_descent, startup_descent_plan)
from dcdc_bench.storage import verify_integrity
from test_extended import fake_bench, writes


@pytest.fixture(autouse=True)
def isolated_activity_lease(tmp_path,monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK",str(tmp_path/".activity.lock"))


def bench(tmp_path, monkeypatch, *, startup_ready_s=0., transition_lag_cycles=0,
          transition_stuck=False, unstable_startup=False, **options):
    import benchctl.transport
    fake = fake_bench(tmp_path, monkeypatch, **options)
    transport = benchctl.transport.VisaTransport
    old_write, old_query = transport.write, transport.query
    fake.load_enable_times = []
    fake.startup_output_reads = 0

    def write(self, command):
        if command.startswith(":SOUR1:VOLT ") and self.enabled:
            self.previous_voltage = self.voltage
            self.transition_reads = 0
        if command == ":SOUR:INP:STAT ON":
            fake.load_enable_times.append(fake.clock.value)
        old_write(self, command)
        for prefix,query in ((":OUTP:OVP:VAL CH1,",":OUTP:OVP:VAL? CH1"),
                             (":OUTP:OCP:VAL CH1,",":OUTP:OCP:VAL? CH1"),
                             (":SOUR:CURR:ILIM ",":SOUR:CURR:ILIM?")):
            if command.startswith(prefix):
                self.responses[query] = command[len(prefix):]

    def query(self, command):
        response = old_query(self, command)
        source = fake.sessions.get("source")
        if command == ":MEAS:VOLT? CH1" and self.enabled and hasattr(self,"previous_voltage"):
            self.transition_reads += 1
            if transition_stuck or self.transition_reads <= transition_lag_cycles:
                return str(self.previous_voltage)
        if command == ":MEAS:CURR? CH1" and self.enabled:
            current = fake.sessions["load"].request if fake.sessions["load"].enabled else 0.
            return str(.01 + current*12.1/(self.voltage*.8))
        if command == ":MEAS:VOLT?" and source.enabled and not self.enabled:
            fake.startup_output_reads += 1
            if fake.clock.value-source.delay_started < startup_ready_s:
                return "2.0"
            if unstable_startup:
                return "12.2" if fake.startup_output_reads % 2 else "12.0"
        return response

    monkeypatch.setattr(transport,"write",write)
    monkeypatch.setattr(transport,"query",query)
    return fake


def execute(fake):
    path = run_startup_descent(fake.config,fake.out,arm=True)
    return path,json.loads((path/"run.json").read_text())


def test_driver_refusing_the_live_step_aborts_without_a_raw_voltage_write(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)

    def refuse(self, channel, voltage_v, *, max_step_v):
        raise ValueError(f"CH{channel} live voltage step refused for the test")

    monkeypatch.setattr("benchctl.drivers.rigol_dp800.RigolDP800.set_voltage_live", refuse)
    path, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert any("refused by the driver" in error for error in run["errors"])
    assert not any(command.startswith(":SOUR1:VOLT ") and command != f":SOUR1:VOLT {PROGRAMMED_INPUTS[0]}"
                   for command in writes(fake, "source"))
    assert all(state["state"] == "OFF" and state["verified"] for state in run["shutdown"].values()
               if isinstance(state, dict) and "verified" in state)
    verify_integrity(path)


def test_instrument_fault_during_the_live_step_keeps_its_own_error_status(tmp_path, monkeypatch):
    from benchctl.interfaces import ScpiError
    fake = bench(tmp_path, monkeypatch)

    def fault(self, channel, voltage_v, *, max_step_v):
        raise ScpiError("-222,Data out of range")

    monkeypatch.setattr("benchctl.drivers.rigol_dp800.RigolDP800.set_voltage_live", fault)
    path, run = execute(fake)
    assert run["execution_status"] == "error"
    assert any("Data out of range" in error for error in run["errors"])
    assert not any("refused by the driver" in error for error in run["errors"])
    verify_integrity(path)


def samples(path):
    return [json.loads(line) for line in (path/"raw/samples.jsonl").read_text().splitlines()]


def test_fixed_plan_preserves_nominal_and_programmed_input_identity():
    plan = startup_descent_plan()
    assert verify_plan_hash(plan)
    assert [p.vin_target_V for p in plan.points] == [15,14,13,12,11,10,9]
    assert all(p.iout_target_A == .1 and p.status == "executable" for p in plan.points)
    assert plan.bench.protective_controls.source_current_limit_A == 1
    assert plan.bench.protective_controls.output_overcurrent_A == .15
    assert any("9.1" in note for note in plan.bench.notes)


def test_unarmed_never_opens_config_or_hardware(tmp_path):
    with pytest.raises(ExtendedAbort,match="--arm"):
        run_startup_descent(tmp_path/"absent",tmp_path/"runs")
    assert not list(tmp_path.iterdir())


def test_busy_bench_lease_prevents_all_hardware_access(tmp_path,monkeypatch):
    from filelock import FileLock
    fake = bench(tmp_path,monkeypatch)
    with FileLock(tmp_path/".activity.lock"):
        with pytest.raises(RuntimeError,match="Bench is busy"):
            run_startup_descent(fake.config,fake.out,arm=True)
    assert not fake.sessions and not fake.out.exists()


def test_delayed_startup_then_continuous_descent_is_fully_traceable(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch,startup_ready_s=10.)
    path,run = execute(fake)
    assert run["execution_status"] == "completed" and not run["errors"]
    detail = run["method"]["startup_descent"]
    assert detail["startup_status"] == "stable-before-load" and detail["startup_elapsed_s"] >= 14
    assert len(detail["startup_stable_cycle_ids"]) == 5 and detail["startup_stable_span_s"] >= 4
    assert detail["descent_completed"]
    assert len(run["executed_point_ids"]) == 7
    assert all(p["qualification"] == "valid" and len(p["acquisition_cycle_ids"]) >= 5 for p in run["points"])
    assert run["points"][-1]["vin_target_V"] == 9 and run["points"][-1]["programmed_input_V"] == 9.1
    rows = samples(path)
    startup_rows = [r for r in rows if not r["acquisition_settings"]["load_enabled"]]
    assert all(r["phase"] == "starting" for r in startup_rows)
    assert not set(detail["startup_cycle_ids"]) & {cid for p in run["points"] for cid in p["acquisition_cycle_ids"]}
    assert any(r["quantity"] == "Vout_V" and r["value"] == 2 for r in startup_rows)
    source = writes(fake,"source")
    assert [c for c in source if c.startswith(":SOUR1:VOLT ")] == [f":SOUR1:VOLT {v}" for v in PROGRAMMED_INPUTS]
    assert source.count(":DELAY ON") == 1
    enabled = source.index(":DELAY ON")
    final_change = source.index(":SOUR1:VOLT 9.1")
    assert not any(c in (":OUTP CH1,OFF",":DELAY OFF") for c in source[enabled:final_change])
    assert writes(fake,"load").count(":SOUR:INP:STAT ON") == 1
    assert all(s == {"state":"OFF","verified":True} for s in run["shutdown"].values())
    verify_integrity(path)
    analysis = json.loads((analyze_run(path)/"analysis.json").read_text())
    assert all(p["qualification"] == "valid" and p["efficiency_pct"] is not None for p in analysis["points"])
    model = build_report_model(Plan.model_validate_json((path/"plan.json").read_text()),run,analysis,rows)
    figures = {figure.id:figure for figure in model.figures}
    assert all(figures[name].x_key == "Vin_V" for name in ("fig-efficiency","fig-voltage","fig-loss"))
    assert figures["fig-voltage"].title == "Output Voltage vs Input Voltage (Line Regulation)"
    assert figures["fig-voltage"].y_key == "Vout_V"
    assert figures["fig-voltage"].y_label == "Output Voltage (V)"
    assert "No dropout, cold-start, or UVLO threshold was established" in figures["fig-voltage"].caption
    assert figures["fig-input-time"].title == "Input Voltage vs Time"
    assert figures["fig-input-time"].x_key == "elapsed_s"
    for name in ("fig-efficiency","fig-voltage","fig-loss"):
        assert len(figures[name].series) == 1
        series = figures[name].series[0]
        assert len(series.point_ids) == 7 and series.vin_target_V is None
        assert series.selection_key == "energized-descent"
    lowest = min(model.points,key=lambda p:p["Vin_V"])
    assert lowest["Vin_V"] == 9.1 and lowest["programmed_input_V"] == 9.1
    assert any("9.100 V" in paragraph and "Lowest qualified" in paragraph for paragraph in model.summary)
    assert all(not set(p["acquisition_cycle_ids"]) & set(detail["startup_cycle_ids"])
               for p in model.points)
    transition_ids = {cid for transition in detail["transitions"] for cid in transition["cycle_ids"]}
    assert all(not set(p["acquisition_cycle_ids"]) & transition_ids for p in model.points)


@pytest.mark.parametrize("options",[{"startup_ready_s":100.},{"unstable_startup":True}])
def test_unready_or_unstable_output_times_out_without_enabling_load(tmp_path,monkeypatch,options):
    fake = bench(tmp_path,monkeypatch,**options)
    path,run = execute(fake)
    assert run["execution_status"] == "aborted" and "startup" in run["errors"][0]
    assert run["method"]["startup_descent"]["startup_status"] == "timeout"
    assert ":SOUR:INP:STAT ON" not in writes(fake,"load")
    assert [p["qualification"] for p in run["points"]] == ["inconclusive"]+["not-run"]*6
    assert all(s == {"state":"OFF","verified":True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_old_input_during_transition_is_preserved_but_never_qualified(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch,transition_lag_cycles=3)
    path,run = execute(fake)
    assert run["execution_status"] == "completed"
    transitions = run["method"]["startup_descent"]["transitions"]
    assert all(len(t["cycle_ids"]) == 4 for t in transitions)
    rows = samples(path)
    for t in transitions:
        raw = [r for r in rows if r["acquisition_cycle_id"] in t["cycle_ids"] and r["quantity"] == "Vin_V"]
        assert [r["value"] for r in raw] == [t["from_programmed_V"]]*3+[t["to_programmed_V"]]
    accepted = {cid for p in run["points"] for cid in p["acquisition_cycle_ids"]}
    assert not accepted & {cid for t in transitions for cid in t["cycle_ids"]}


def test_stuck_transition_times_out_and_does_not_visit_later_input(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch,transition_stuck=True)
    path,run = execute(fake)
    assert run["execution_status"] == "aborted" and "within 5 s" in run["errors"][0]
    assert [p["qualification"] for p in run["points"]] == ["valid","inconclusive"]+["not-run"]*5
    assert ":SOUR1:VOLT 13.0" not in writes(fake,"source")
    assert run["method"]["startup_descent"]["transitions"][0]["status"] == "timeout"
    verify_integrity(path)


@pytest.mark.parametrize("quantity,bad_value",[("Iin_A",1.03),("Iin_A",.999),("Vin_V",8.99),("Vout_V",10.5),("Vout_V",13.3),("Iout_A",.16)])
def test_electrical_fault_stops_descent_and_verifies_shutdown(tmp_path,monkeypatch,quantity,bad_value):
    fake = bench(tmp_path,monkeypatch)
    original = StartupDescentRigol.read
    def read(pilot,key):
        value = original(pilot,key)
        return bad_value if pilot.voltage == 13 and key == quantity else value
    monkeypatch.setattr(StartupDescentRigol,"read",read)
    path,run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert ":SOUR1:VOLT 12.0" not in writes(fake,"source")
    assert run["points"][2]["qualification"] == "inconclusive" and not run["points"][2]["acquisition_cycle_ids"]
    assert all(s == {"state":"OFF","verified":True} for s in run["shutdown"].values())
    assert any(r["quantity"] == quantity and r["value"] == bad_value for r in samples(path))
    verify_integrity(path)


def test_live_voltage_method_rejects_nonadjacent_target_without_write(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch)
    original = StartupDescentRigol.set_live_voltage
    def invalid(pilot,target):
        return original(pilot,9.1)
    monkeypatch.setattr(StartupDescentRigol,"set_live_voltage",invalid)
    _,run = execute(fake)
    assert run["execution_status"] == "aborted" and "next fixed" in run["errors"][0]
    assert ":SOUR1:VOLT 9.1" not in writes(fake,"source")


def test_source_cc_during_transition_preserves_cycle_and_stops(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch)
    original = StartupDescentRigol.mode
    def mode(pilot):
        return "CC" if pilot.voltage == 13 else original(pilot)
    monkeypatch.setattr(StartupDescentRigol,"mode",mode)
    path,run = execute(fake)
    assert run["execution_status"] == "aborted" and "Source mode" in run["errors"][0]
    assert ":SOUR1:VOLT 12.0" not in writes(fake,"source")
    boundary = [r for r in samples(path) if r["point_id"] == "p0003"]
    assert len(boundary) == 4 and all(r["acquisition_settings"]["source_mode"] == "CC" for r in boundary)
    assert not run["points"][2]["acquisition_cycle_ids"]
    assert all(s == {"state":"OFF","verified":True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_failed_source_off_keeps_independent_deadline_active(tmp_path,monkeypatch):
    fake = bench(tmp_path,monkeypatch,fail_source_off=True)
    _,run = execute(fake)
    assert run["execution_status"] == "error"
    assert ":DELAY OFF" not in writes(fake,"source")
    assert fake.sessions["source"].delay == "ON"
    assert run["shutdown"]["load"] == {"state":"OFF","verified":True}
