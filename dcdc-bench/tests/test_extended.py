"""Fixed real-test contracts, exercised only through an in-memory SCPI bench."""
import json
import signal
from types import SimpleNamespace

import pytest

import dcdc_bench.extended as extended
from dcdc_bench.analysis import analyze_run
from dcdc_bench.planning import verify_plan_hash
from dcdc_bench.services import default_plan
from dcdc_bench.storage import RunStore, verify_integrity


class FakeClock:
    def __init__(self):
        self.value = 0.

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def fake_bench(tmp_path, monkeypatch, **options):
    import benchctl.config
    import benchctl.transport

    clock, sessions, commands, handlers = FakeClock(), {}, [], {}

    class Transport:
        def __init__(self, role, resource, **kwargs):
            assert resource == f"FAKE-{role}"
            assert kwargs["timeout_ms"] == 1500
            self.role, self.opened, self.closed = role, False, False
            self.enabled, self.was_started = False, False
            self.delay, self.delay_started, self.duration = "OFF", None, 5
            self.request, self.voltage, self.current = .25, 0., .15
            self.responses = {":SOUR:SENS?": "0", ":SOUR:FUNC:MODE?": "FIX", ":SOUR:FUNC?": "CURR",
                ":INST:NSEL?": "1", ":TIMER?": "OFF", ":DELAY:GROUPS?": "1", ":DELAY:CYCLES?": "N,1",
                ":DELAY:ENDSTATE?": "OFF", ":DELAY:STOP?": "NONE", ":SYST:OTP?": "ON",
                ":OUTP:OVP:VAL? CH1": "26", ":OUTP:OCP:VAL? CH1": ".5",
                ":OUTP:OVP? CH1": "ON", ":OUTP:OCP? CH1": "ON", ":OUTP:OVP:QUES? CH1": "NO",
                ":OUTP:OCP:QUES? CH1": "NO", ":OUTP:CVCC? CH1": "CV", ":STAT:QUES:COND?": "0",
                ":SOUR:CURR:VLIM?": "13.2", ":SOUR:CURR:ILIM?": ".6"}
            sessions[role] = self

        def open(self):
            self.opened = True

        def close(self):
            self.closed = True

        def query(self, command):
            commands.append((self.role, "query", command))
            clock.value += .001
            if self.delay_started is not None and self.delay == "ON" and clock.value - self.delay_started >= self.duration:
                self.enabled, self.delay = False, "OFF"
            override = options.get("query_overrides", {}).get((self.role, command))
            if override is not None:
                return override
            if command == "*IDN?":
                serial = f"FAKE-{self.role}" if options.get("identity_mismatch") != self.role else "WRONG-DEVICE"
                return f"RIGOL,{'DP821A' if self.role == 'source' else 'DL3031A'},{serial},1.0"
            if command in (":SYST:ERR?", "SYST:ERR?"): return '0,"No error"'
            if command in (":OUTP? CH1", ":SOUR:INP:STAT?"): return "ON" if self.enabled else "OFF"
            if command == ":DELAY?": return self.delay
            if command == ":DELAY:PARAMETER? 0,1":
                payload = f"0,ON,{self.duration};"
                return f"#9{len(payload):09d}{payload}"
            if command == ":SOUR1:VOLT?": return str(self.voltage)
            if command == ":SOUR1:CURR?": return str(self.current)
            if command == ":SOUR:CURR:LEV:IMM?": return str(self.request)
            if command == ":MEAS:VOLT? CH1": return str(self.voltage if self.enabled else 0.)
            if command == ":MEAS:CURR? CH1":
                current = sessions["load"].request if sessions["load"].enabled else 0.
                return str(.01 + current * 12.1 / (24 * .8)) if self.enabled else "0"
            if command == ":MEAS:VOLT?":
                if not sessions["source"].enabled: return ".178"
                if sessions["load"].request >= options.get("fault_at_load_A", 999): return "13.5"
                return "12.1"
            if command == ":MEAS:CURR?": return str(self.request if self.enabled else .001)
            return self.responses[command]

        def write(self, command):
            commands.append((self.role, "write", command))
            clock.value += .001
            if command == ":OUTP CH1,OFF" and self.was_started and options.get("fail_source_off"):
                raise OSError("Simulated source OFF failure")
            if command == ":SOUR:INP:STAT OFF" and self.was_started and options.get("fail_load_off"):
                raise OSError("Simulated load OFF failure")
            if command == ":DELAY ON":
                self.delay, self.enabled, self.was_started = "ON", True, True
                self.delay_started = clock.value
            elif command == ":DELAY OFF": self.delay = "OFF"
            elif command == ":OUTP CH1,OFF": self.enabled = False
            elif command.startswith(":SOUR:INP:STAT "):
                self.enabled = command.endswith("ON")
                self.was_started |= self.enabled
            elif command.startswith(":SOUR1:VOLT "): self.voltage = float(command.split()[-1])
            elif command.startswith(":SOUR1:CURR "): self.current = float(command.split()[-1])
            elif command.startswith(":SOUR:CURR:LEV:IMM "): self.request = float(command.split()[-1])
            elif command.startswith(":DELAY:PARAMETER "): self.duration = int(command.split(",")[-1])

    config = SimpleNamespace(devices={
        "psu_rigol_1": SimpleNamespace(expected_serial="FAKE-source", driver="rigol_dp800", resource="FAKE-source"),
        "load_rigol_1": SimpleNamespace(expected_serial="FAKE-load", driver="rigol_dl3000", resource="FAKE-load")})
    monkeypatch.setattr(benchctl.config, "load_config", lambda path: config)
    monkeypatch.setattr(benchctl.transport, "VisaTransport", Transport)
    monkeypatch.setattr(extended, "time", clock)

    def set_signal(number, handler):
        old = handlers.get(number, signal.SIG_DFL)
        handlers[number] = handler
        return old

    monkeypatch.setattr(extended, "signal", SimpleNamespace(SIGALRM=signal.SIGALRM, SIGTERM=signal.SIGTERM,
        SIGHUP=signal.SIGHUP, SIGINT=signal.SIGINT, SIG_IGN=signal.SIG_IGN,
        Signals=signal.Signals, signal=set_signal, alarm=lambda seconds: None))
    return SimpleNamespace(clock=clock, sessions=sessions, commands=commands, handlers=handlers,
                           config=tmp_path / "fake.yaml", out=tmp_path / "runs")


def execute(fake):
    path = extended.run_extended(fake.config, fake.out, arm=True)
    return path, json.loads((path / "run.json").read_text())


def writes(fake, role):
    return [command for device, kind, command in fake.commands if device == role and kind == "write"]


def test_extended_plan_is_fixed_pure_and_within_conservative_budget():
    before = default_plan().model_dump()
    plan = extended.extended_plan()
    assert verify_plan_hash(plan)
    assert len(plan.points) == 37 and all(p.status == "executable" for p in plan.points)
    assert [p.iout_target_A for p in plan.points[:10]] == [n / 100 for n in range(5, 51, 5)]
    assert [p.iout_target_A for p in plan.points[10:28]] == [.5] * 18
    assert [p.iout_target_A for p in plan.points[28:]] == [n / 100 for n in range(45, 4, -5)]
    assert len({p.point_id for p in plan.points}) == 37
    assert plan.recipe.planning.efficiency_estimate_fraction == .65
    assert plan.points[0].planning_output_current_limit_A == pytest.approx(.5265)
    assert plan.bench.protective_controls.source_current_limit_A == .45
    assert plan.bench.protective_controls.output_overcurrent_A == .6
    assert default_plan().model_dump() == before


def test_unarmed_test_never_loads_config_or_opens_hardware(tmp_path):
    with pytest.raises(extended.ExtendedAbort, match="--arm"):
        extended.run_extended(tmp_path / "absent", tmp_path / "runs")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("response", ["0,ON,720;", "#0abc", "#90000000090,ON,721;", "#90000000100,ON,720;", "#90000000180,ON,720;1,ON,720;"])
def test_bad_independent_deadline_readback_never_energizes(tmp_path, monkeypatch, response):
    fake = fake_bench(tmp_path, monkeypatch, query_overrides={("source", ":DELAY:PARAMETER? 0,1"): response})
    path, run = execute(fake)
    assert run["execution_status"] == "aborted"
    assert ":DELAY ON" not in writes(fake, "source")
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    assert all(point["qualification"] == "not-run" for point in run["points"])
    verify_integrity(path)


@pytest.mark.parametrize("command,response", [
    (":DELAY:CYCLES?", "I"), (":DELAY:CYCLES?", "N,2"), (":DELAY:GROUPS?", "2"),
    (":DELAY:ENDSTATE?", "ON"), (":DELAY:STOP?", ">C,.4"), (":TIMER?", "ON"),
    (":OUTP:OCP:VAL? CH1", "1.1"), (":OUTP:OVP:VAL? CH1", "66"),
    (":INST:NSEL?", "2"), (":SYST:OTP?", "OFF")])
def test_incorrect_protection_or_timer_configuration_fails_closed(tmp_path, monkeypatch, command, response):
    fake = fake_bench(tmp_path, monkeypatch, query_overrides={("source", command): response})
    _, run = execute(fake)
    assert run["execution_status"] in ("aborted", "error")
    assert ":DELAY ON" not in writes(fake, "source")
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")


def test_complete_fake_test_preserves_all_37_points_and_real_elapsed_hold(tmp_path, monkeypatch):
    fake = fake_bench(tmp_path, monkeypatch)
    path, run = execute(fake)
    assert run["execution_status"] == "completed" and not run["errors"]
    assert all(point["qualification"] == "valid" for point in run["points"])
    assert run["method"]["sustained_load_actual_elapsed_s"] >= 180
    assert run["method"]["sustained_load_completed_bins"] == 18
    assert all(p["acquisition_elapsed_s"] >= 10. and len(p["acquisition_cycle_ids"]) >= 5 for p in run["points"])
    hold = [p for p in run["points"] if p["test_id"] == "sustained-load"]
    assert all(p["settling_inherited_from_previous_point"] for p in hold)
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    assert all(session.closed and not session.enabled for session in fake.sessions.values())
    source_commands = writes(fake, "source")
    assert ":OUTP CH1,ON" not in source_commands and source_commands.count(":DELAY ON") == 1
    start = source_commands.index(":DELAY ON")
    first_off = source_commands.index(":OUTP CH1,OFF", start)
    cancel = source_commands.index(":DELAY OFF")
    last_off = len(source_commands) - 1 - source_commands[::-1].index(":OUTP CH1,OFF")
    assert start < first_off < cancel < last_off
    verify_integrity(path)
    analysis_path = analyze_run(path)
    analysis = json.loads((analysis_path / "analysis.json").read_text())
    assert len(analysis["points"]) == 37
    assert all(p["qualification"] == "valid" and p["efficiency_pct"] is not None for p in analysis["points"])
    rows = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert all(row["value"] == float(row["raw_response"]) for row in rows)


@pytest.mark.parametrize("role", ["source", "load"])
def test_identity_mismatch_never_mutates_unverified_instrument(tmp_path, monkeypatch, role):
    fake = fake_bench(tmp_path, monkeypatch, identity_mismatch=role)
    _, run = execute(fake)
    assert run["execution_status"] == "error"
    assert not writes(fake, role)
    assert all(session.closed for session in fake.sessions.values())
    assert ":DELAY ON" not in writes(fake, "source")


@pytest.mark.parametrize("phase,stage", [("starting", "increasing-load"), ("settling", "increasing-load"),
                                          ("acquiring", "sustained-load")])
def test_sighup_interrupts_safely_and_preserves_inconclusive_active_point(tmp_path, monkeypatch, phase, stage):
    fake = fake_bench(tmp_path, monkeypatch)
    append = RunStore.append
    fired = False

    def interrupt(store, stream, row):
        nonlocal fired
        if not fired and stream == "samples" and row["phase"] == phase and row["test_id"] == stage:
            fired = True
            fake.handlers[signal.SIGHUP](signal.SIGHUP, None)
        return append(store, stream, row)

    monkeypatch.setattr(RunStore, "append", interrupt)
    path, run = execute(fake)
    assert fired and run["execution_status"] == "aborted"
    assert "SIGHUP" in run["errors"][0]
    assert sum(p["qualification"] == "inconclusive" for p in run["points"]) == 1
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    if stage == "sustained-load":
        assert run["method"]["sustained_load_actual_elapsed_s"] >= 0
    verify_integrity(path)


@pytest.mark.parametrize("fault", ["fail_load_off", "fail_source_off"])
def test_shutdown_failures_preserve_independent_attempts_and_hardware_fallback(tmp_path, monkeypatch, fault):
    fake = fake_bench(tmp_path, monkeypatch, fault_at_load_A=.15, **{fault: True})
    _, run = execute(fake)
    assert run["execution_status"] == "error"
    assert ":OUTP CH1,OFF" in writes(fake, "source")
    assert ":SOUR:INP:STAT OFF" in writes(fake, "load")
    if fault == "fail_source_off":
        assert ":DELAY OFF" not in writes(fake, "source")
        assert fake.sessions["source"].delay == "ON"
        assert run["shutdown"]["load"] == {"state": "OFF", "verified": True}
    else:
        assert fake.sessions["source"].delay == "OFF" and not fake.sessions["source"].enabled
        assert run["shutdown"]["source"] == {"state": "OFF", "verified": True}


def test_guard_failure_stops_before_any_further_current_increase(tmp_path, monkeypatch):
    fake = fake_bench(tmp_path, monkeypatch, fault_at_load_A=.15)
    path, run = execute(fake)
    assert run["execution_status"] == "aborted"
    requests = [float(command.split()[-1]) for command in writes(fake, "load") if command.startswith(":SOUR:CURR:LEV:IMM ")]
    assert requests == [.05, .1, .15]
    assert [p["qualification"] for p in run["points"][:4]] == ["valid", "valid", "inconclusive", "not-run"]
    verify_integrity(path)


def test_persistence_failure_shuts_down_and_never_increases_load(tmp_path, monkeypatch):
    fake = fake_bench(tmp_path, monkeypatch)
    append = RunStore.append

    def fail_samples(store, stream, row):
        if stream == "samples": raise OSError("Simulated full disk")
        return append(store, stream, row)

    monkeypatch.setattr(RunStore, "append", fail_samples)
    _, run = execute(fake)
    assert run["execution_status"] == "error"
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    assert ":SOUR:CURR:LEV:IMM 0.1" not in writes(fake, "load")


def test_slow_storage_is_outside_query_span_and_never_precedes_remaining_queries(tmp_path, monkeypatch):
    """A realistic SD fsync stall must not make otherwise prompt reads stale."""
    fake = fake_bench(tmp_path, monkeypatch)
    append = RunStore.append
    captured = []

    def delayed_sample_write(store, stream, row):
        if stream == "samples":
            # The first durable row must already have all four query replies.
            recent_queries = [command for _, kind, command in fake.commands if kind == "query"]
            assert recent_queries[-4:] == [":MEAS:VOLT? CH1", ":MEAS:CURR? CH1", ":MEAS:VOLT?", ":MEAS:CURR?"]
            captured.append(row)
            fake.clock.sleep(.3)
        return append(store, stream, row)

    monkeypatch.setattr(RunStore, "append", delayed_sample_write)
    path, run = execute(fake)
    assert run["execution_status"] == "completed"
    assert run["method"]["sustained_load_actual_elapsed_s"] >= 180
    assert len(captured) >= 37 * 5 * 4
    by_cycle = {}
    for row in captured:
        by_cycle.setdefault(row["acquisition_cycle_id"], []).append(row)
    assert all(rows[-1]["query_end_monotonic_s"] - rows[0]["query_start_monotonic_s"] < .01
               for rows in by_cycle.values())
    assert all(p["maximum_interchannel_skew_s"] < .01 for p in run["points"])
    verify_integrity(path)


def test_later_query_failure_preserves_partial_cycle_and_shuts_down(tmp_path, monkeypatch):
    fake = fake_bench(tmp_path, monkeypatch)
    original_read = extended.ExtendedRigol.read

    def fail_third_query(pilot, quantity):
        if quantity == "Vout_V":
            raise OSError("Simulated output-voltage query timeout")
        return original_read(pilot, quantity)

    monkeypatch.setattr(extended.ExtendedRigol, "read", fail_third_query)
    path, run = execute(fake)
    rows = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert run["execution_status"] == "error"
    assert "query timeout" in run["errors"][0]
    assert [row["quantity"] for row in rows] == ["Vin_V", "Iin_A"]
    assert len({row["acquisition_cycle_id"] for row in rows}) == 1
    assert all(float(row["raw_response"]) == row["value"] for row in rows)
    assert run["points"][0]["qualification"] == "inconclusive"
    assert run["points"][0]["acquisition_cycle_ids"] == []
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    verify_integrity(path)


@pytest.mark.parametrize("values", [
    {"Vin_V": 25., "Iin_A": .1, "Vout_V": 12., "Iout_A": .1},
    {"Vin_V": 24., "Iin_A": .451, "Vout_V": 12., "Iout_A": .1},
    {"Vin_V": 24., "Iin_A": .1, "Vout_V": 13.21, "Iout_A": .1},
    {"Vin_V": 24., "Iin_A": .1, "Vout_V": 12., "Iout_A": .601},
    {"Vin_V": 24., "Iin_A": .1, "Vout_V": 12., "Iout_A": float("nan")},
])
def test_guard_rejects_unsafe_or_invalid_readings_even_during_startup(values):
    with pytest.raises(extended.ExtendedAbort): extended._guard(values, .1, startup=True)
