"""Bounded real-pilot guard tests; all instruments below are in-memory fakes."""
from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from dcdc_bench.bringup import (BringupAbort, ILIMIT, IOUT, POLICY_ID, RecordingTransport, RigolPilot,
                                SOURCE_OCP, SOURCE_OVP, VIN, pilot_plan, run_bringup)
from dcdc_bench.planning import verify_plan_hash
from dcdc_bench.services import default_plan


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.writes = []
        self.queries = []

    def query(self, command):
        self.queries.append(command)
        return self.responses[command]

    def write(self, command):
        self.writes.append(command)


def pilot_fixture(*, source_on=False, load_on=False):
    st = FakeTransport({
        ":OUTP:OVP:VAL? CH1": str(SOURCE_OVP), ":OUTP:OCP:VAL? CH1": str(SOURCE_OCP),
        ":OUTP:OVP? CH1": "ON", ":OUTP:OCP? CH1": "ON",
        ":OUTP:OVP:QUES? CH1": "NO", ":OUTP:OCP:QUES? CH1": "NO",
        ":OUTP:CVCC? CH1": "CV", ":SYST:OTP?": "ON",
    })
    lt = FakeTransport({":SOUR:SENS?": "OFF", ":SOUR:CURR:VLIM?": "13.2",
                        ":SOUR:CURR:ILIM?": "0.15", ":STAT:QUES:COND?": "0"})
    calls = []
    supply = SimpleNamespace(get_output_enabled=lambda channel: source_on,
        check_errors=lambda: None,
        set_voltage=lambda channel, value: calls.append(("voltage", channel, value)),
        set_current_limit=lambda channel, value: calls.append(("current", channel, value)))
    load = SimpleNamespace(get_input_enabled=lambda: load_on,
        check_errors=lambda: None,
        set_mode=lambda value: calls.append(("load_mode", value)),
        set_current=lambda value: calls.append(("load_current", value)))
    return RigolPilot(supply, load, st, lt), st, lt, calls


def test_pilot_is_fixed_two_point_plan_without_widening_the_default_plan():
    before = default_plan().model_dump()
    plan = pilot_plan()
    assert verify_plan_hash(plan)
    assert plan.bench.mode == plan.recipe.execution_mode == "real"
    assert [(p.vin_target_V, p.iout_target_A) for p in plan.points] == [(VIN, 0.), (VIN, IOUT)]
    assert VIN == 24. and ILIMIT == .15 and IOUT == .1
    assert all(point.status == "executable" for point in plan.points)
    assert plan.bench.source.channel == 1
    assert plan.bench.protective_controls.source_current_limit_A == ILIMIT
    assert plan.bench.protective_controls.policy_id == POLICY_ID
    assert plan.dut.execution_approval.wiring_and_polarity_confirmed
    assert plan.dut.acceptance.minimum_efficiency_pct is None
    assert not plan.bench.load.remote_sense_required
    assert "load_input_terminals" in plan.bench.measurements["Vout_V"].location
    assert default_plan().model_dump() == before


def test_unarmed_request_stops_before_config_or_hardware_access(tmp_path):
    with pytest.raises(BringupAbort, match="--arm"):
        run_bringup(tmp_path / "absent-private-config.yaml", tmp_path / "runs")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("source_on,load_on", [(True, False), (False, True), (True, True)])
def test_configuration_rejects_any_enabled_output_before_mutations(source_on, load_on):
    pilot, st, lt, calls = pilot_fixture(source_on=source_on, load_on=load_on)
    with pytest.raises(BringupAbort, match="verified OFF"):
        pilot.configure_protections()
    assert not st.writes and not lt.writes and not calls


@pytest.mark.parametrize("sense", ["ON", "1", "unknown"])
def test_unconfirmed_remote_sensing_blocks_configuration(sense):
    pilot, st, lt, calls = pilot_fixture()
    lt.responses[":SOUR:SENS?"] = sense
    with pytest.raises(BringupAbort, match="local load sensing"):
        pilot.configure_protections()
    assert not st.writes and not lt.writes and not calls


@pytest.mark.parametrize("command,response", [
    (":OUTP:OVP:VAL? CH1", "30"), (":OUTP:OCP:VAL? CH1", "1"),
    (":OUTP:OVP? CH1", "OFF"), (":OUTP:OCP? CH1", "OFF"),
    (":OUTP:OVP:QUES? CH1", "YES"), (":OUTP:OCP:QUES? CH1", "YES"),
    (":OUTP:OVP:VAL? CH1", "nan"),
])
def test_incorrect_source_protection_blocks_setpoints(command, response):
    pilot, st, lt, calls = pilot_fixture()
    st.responses[command] = response
    with pytest.raises(BringupAbort, match="protection verification failed"):
        pilot.configure_protections()
    assert not calls
    assert not any("CH1,ON" in command and ":OVP" not in command and ":OCP" not in command
                   for command in st.writes)


@pytest.mark.parametrize("mode", ["CC", "UR", "OFF", "unknown"])
def test_non_cv_source_mode_aborts_nominal_input_point(mode):
    pilot, st, _, _ = pilot_fixture()
    st.responses[":OUTP:CVCC? CH1"] = mode
    with pytest.raises(BringupAbort, match="Source mode"):
        pilot.mode()


def test_successful_configuration_verifies_limits_without_enabling_any_output():
    pilot, st, lt, calls = pilot_fixture()
    pilot.configure_protections()
    assert calls == [("voltage", 1, VIN), ("current", 1, ILIMIT),
                     ("load_mode", "cc"), ("load_current", IOUT)]
    assert ":SOUR:CURR:RANG MIN" in lt.writes
    assert ":SOUR:CURR:SLEW:BOTH MIN" in lt.writes
    assert ":SOUR:CURR:VLIM 13.2" in lt.writes
    assert ":SOUR:CURR:ILIM 0.15" in lt.writes
    assert ":SYST:OTP ON" in st.writes
    assert not any(":SOUR:INP" in command for command in lt.writes)
    assert not any(command.startswith(":OUTP CH1") for command in st.writes)


@pytest.mark.parametrize("command,response", [
    (":SOUR:CURR:VLIM?", "15"), (":SOUR:CURR:ILIM?", "1"),
    (":SOUR:CURR:VLIM?", "nan"),
])
def test_wrong_load_limit_aborts_configuration_without_enabling_outputs(command, response):
    pilot, st, lt, calls = pilot_fixture()
    lt.responses[command] = response
    with pytest.raises(BringupAbort, match="Load CC limit readback"):
        pilot.configure_protections()
    assert ("load_current", IOUT) in calls
    assert not pilot.supply.get_output_enabled(1)
    assert not pilot.load.get_input_enabled()
    assert not any(":SOUR:INP" in command for command in lt.writes)
    assert not any(command.startswith(":OUTP CH1") for command in st.writes)


def test_disabled_thermal_protection_aborts_configuration_without_enabling_outputs():
    pilot, st, lt, calls = pilot_fixture()
    st.responses[":SYST:OTP?"] = "OFF"
    with pytest.raises(BringupAbort, match="thermal protection"):
        pilot.configure_protections()
    assert ("load_current", IOUT) in calls
    assert not pilot.supply.get_output_enabled(1)
    assert not pilot.load.get_input_enabled()
    assert not any(":SOUR:INP" in command for command in lt.writes)
    assert not any(command.startswith(":OUTP CH1") for command in st.writes)


@pytest.mark.parametrize("status", ["1", "2", "8", "512", "1024", "2048", "4096", "8192", "0x2000", "-1"])
def test_load_fault_status_aborts_without_clearing_fault(status):
    pilot, _, lt, _ = pilot_fixture()
    lt.responses[":STAT:QUES:COND?"] = status
    with pytest.raises(BringupAbort, match="questionable condition"):
        pilot.load_status(False)
    assert not lt.writes


def test_load_status_requires_expected_input_state():
    pilot, _, _, _ = pilot_fixture(load_on=True)
    with pytest.raises(BringupAbort, match="input state"):
        pilot.load_status(False)
    assert pilot.load_status(True) == 0


@pytest.fixture(autouse=True)
def isolated_activity_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))


def test_recording_transport_preserves_numeric_scpi_text_without_reformatting():
    underlying = FakeTransport({":MEAS:VOLT?": "+1.204000E+01"})
    tap = RecordingTransport(underlying)
    assert tap.query(":MEAS:VOLT?") == "+1.204000E+01"
    assert tap.last_response == "+1.204000E+01"
    tap.write(":SOUR:INP:STAT OFF")
    assert underlying.writes == [":SOUR:INP:STAT OFF"]


def test_protection_programming_scpi_lives_only_in_the_shared_adapter():
    """A protection fix must propagate to every fixed procedure automatically."""
    from pathlib import Path
    import dcdc_bench
    package = Path(dcdc_bench.__file__).parent
    literals = (":OUTP:OVP:VAL CH1,", ":OUTP:OCP:VAL CH1,", ":SOUR:CURR:VLIM ", ":SOUR:CURR:ILIM ", ":SYST:OTP ON")
    owners = {literal: sorted(path.name for path in package.rglob("*.py") if literal in path.read_text(encoding="utf-8"))
              for literal in literals}
    assert owners == {literal: ["bringup.py"] for literal in literals}, owners


def test_retained_current_request_is_lowered_before_tightening_current_limit():
    pilot, _, lt, calls = pilot_fixture()
    state = {"setpoint": .25}
    ordered = []

    def set_current(value):
        assert not pilot.load.get_input_enabled()
        state["setpoint"] = value
        ordered.append(("request", value))
        calls.append(("load_current", value))

    original_write = lt.write

    def write(command):
        if command.startswith(":SOUR:CURR:ILIM "):
            limit = float(command.split()[-1])
            ordered.append(("limit", limit))
            if state["setpoint"] > limit:
                raise ValueError("Instrument rejects a limit below its retained current request")
        original_write(command)

    pilot.load.set_current = set_current
    lt.write = write
    pilot.configure_protections()
    assert ordered == [("request", .1), ("limit", .15)]
    assert not pilot.load.get_input_enabled()


def install_fake_bench(tmp_path, monkeypatch, *, output_voltage, off_load_voltage=0.,
                       off_source_voltage=0., input_current=.0064, output_current=.011096,
                       fail_load_shutdown=False):
    """Install every I/O boundary before running a pilot; never open a VISA session."""
    import benchctl.config
    import benchctl.identity
    import benchctl.registry
    import benchctl.transport
    import dcdc_bench.bringup as bringup
    sessions = {}
    _, source_template, load_template, _ = pilot_fixture()

    class Session(FakeTransport):
        def __init__(self, role, resource, **kwargs):
            assert resource == f"FAKE-{role}"
            assert kwargs["timeout_ms"] == 1500
            super().__init__(dict(source_template.responses if role == "source" else load_template.responses))
            self.role, self.enabled, self.opened, self.closed = role, False, False, False
            self.current_request = .25
            sessions[role] = self

        def open(self):
            self.opened = True

        def close(self):
            self.closed = True

        def query(self, command):
            self.queries.append(command)
            if command in (":OUTP? CH1", ":SOUR:INP:STAT?"):
                return "ON" if self.enabled else "OFF"
            if command == ":MEAS:VOLT? CH1":
                return "+2.400500E+01" if self.enabled else f"{off_source_voltage:+.6E}"
            if command == ":MEAS:CURR? CH1":
                return f"{input_current:+.6E}" if self.enabled else "+0.000000E+00"
            if command == ":MEAS:VOLT?":
                return f"{output_voltage:+.6E}" if sessions["source"].enabled else f"{off_load_voltage:+.6E}"
            if command == ":MEAS:CURR?":
                return f"{output_current:+.6E}" if self.enabled else "+1.109600E-02"
            return self.responses[command]

        def write(self, command):
            self.writes.append(command)
            if fail_load_shutdown and command == ":SOUR:INP:STAT OFF" and self.enabled:
                raise OSError("Simulated load shutdown transport failure")
            if command.startswith((":OUTP CH1,", ":SOUR:INP:STAT ")):
                self.enabled = command.endswith("ON")
            elif command.startswith(":SOUR:CURR:LEV:IMM "):
                self.current_request = float(command.split()[-1])
            elif command.startswith(":SOUR:CURR:ILIM "):
                if self.current_request > float(command.split()[-1]):
                    raise ValueError("Limit below retained current request")

    class Supply:
        def __init__(self, transport):
            self.t = transport

        def get_output_enabled(self, channel):
            assert channel == 1
            return self.t.query(":OUTP? CH1") == "ON"

        def output_on(self, channel):
            assert channel == 1
            self.t.write(":OUTP CH1,ON")

        def output_off(self, channel):
            assert channel == 1
            self.t.write(":OUTP CH1,OFF")

        def measure_voltage(self, channel):
            assert channel == 1
            return float(self.t.query(":MEAS:VOLT? CH1"))

        def measure_current(self, channel):
            assert channel == 1
            return float(self.t.query(":MEAS:CURR? CH1"))

        def set_voltage(self, channel, value):
            assert (channel, value) == (1, VIN)

        def set_current_limit(self, channel, value):
            assert (channel, value) == (1, ILIMIT)

        def check_errors(self):
            pass

    class Load:
        def __init__(self, transport):
            self.t = transport

        def get_input_enabled(self):
            return self.t.query(":SOUR:INP:STAT?") == "ON"

        def input_on(self):
            self.t.write(":SOUR:INP:STAT ON")

        def input_off(self):
            self.t.write(":SOUR:INP:STAT OFF")

        def measure_voltage(self):
            return float(self.t.query(":MEAS:VOLT?"))

        def measure_current(self):
            return float(self.t.query(":MEAS:CURR?"))

        def set_mode(self, value):
            assert value == "cc"

        def set_current(self, value):
            self.t.write(f":SOUR:CURR:LEV:IMM {value}")

        def check_errors(self):
            pass

    @dataclass
    class Identity:
        serial: str

    config = SimpleNamespace(devices={
        "psu_rigol_1": SimpleNamespace(expected_serial="FAKE-SOURCE", driver="rigol_dp800", resource="FAKE-source"),
        "load_rigol_1": SimpleNamespace(expected_serial="FAKE-LOAD", driver="rigol_dl3000", resource="FAKE-load"),
    })
    monkeypatch.setattr(benchctl.config, "load_config", lambda path: config)
    monkeypatch.setattr(benchctl.transport, "VisaTransport", Session)
    monkeypatch.setattr(benchctl.registry, "get_driver_class",
                        lambda name: {"rigol_dp800": Supply, "rigol_dl3000": Load}[name])
    monkeypatch.setattr(benchctl.identity, "identify_and_verify",
                        lambda role, device, driver: Identity(device.expected_serial))
    sleeps = []
    monkeypatch.setattr(bringup.time, "sleep", sleeps.append)
    monkeypatch.setattr(bringup.signal, "signal", lambda *args: None)
    monkeypatch.setattr(bringup.signal, "alarm", lambda seconds: None)

    return SimpleNamespace(sessions=sessions, sleeps=sleeps,
                           config_path=tmp_path / "fake-config.yaml", out=tmp_path / "runs")


@pytest.mark.parametrize("output_voltage,expected_rows", [(0., 24), (13.5, 4)])
def test_startup_voltage_guards_abort_before_load_enable_and_preserve_evidence(
        tmp_path, monkeypatch, output_voltage, expected_rows):
    """Allow zero only in the fixed startup window; never relax overvoltage."""
    from dcdc_bench.analysis import analyze_run
    from dcdc_bench.storage import verify_integrity

    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=output_voltage)
    sessions, sleeps = fake.sessions, fake.sleeps

    path = run_bringup(fake.config_path, fake.out, arm=True)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert run["execution_status"] == "aborted"
    assert "Output guard failed" in run["errors"][0]
    assert run["points"][0]["qualification"] == "inconclusive"
    assert run["points"][0]["acquisition_cycle_ids"] == []
    assert run["points"][1]["qualification"] == "not-run"
    assert len(samples) == expected_rows
    if output_voltage == 0:
        # Five startup observations may be below nominal. The first subsequent
        # settling observation must enforce the normal lower voltage bound.
        assert [row["phase"] for row in samples] == ["starting"] * 20 + ["settling"] * 4
        assert sleeps == [1] * 6
    else:
        # An excessive output fails on the first startup observation, without
        # waiting for the complete startup allowance.
        assert all(row["phase"] == "starting" for row in samples)
        assert sleeps == [1]
    assert all(row["acquisition_settings"]["load_enabled"] is False for row in samples)
    by_quantity = {row["quantity"]: row for row in samples}
    assert by_quantity["Vout_V"]["value"] == output_voltage
    assert by_quantity["Vin_V"]["raw_response"] == "+2.400500E+01"
    assert by_quantity["Iin_A"]["value"] == .0064
    assert ":OUTP CH1,ON" in sessions["source"].writes
    assert ":SOUR:INP:STAT ON" not in sessions["load"].writes
    for role, session in sessions.items():
        assert session.opened and session.closed and not session.enabled
        assert run["shutdown"][role] == {"state": "OFF", "verified": True}
    verify_integrity(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert all(point["efficiency_pct"] is None for point in analysis["points"])


def test_loaded_only_plan_has_one_fixed_point_and_keeps_default_plan_intact():
    before = default_plan().model_dump()
    plan = pilot_plan(loaded_only=True)
    assert verify_plan_hash(plan)
    assert [(p.vin_target_V, p.iout_target_A) for p in plan.points] == [(24., .1)]
    assert plan.bench.source.max_current_A == ILIMIT
    assert plan.bench.protective_controls.source_current_limit_A == ILIMIT
    assert plan.recipe.acquisition.minimum_complete_cycles == 5
    assert plan.recipe.acquisition.maximum_interchannel_skew_s == .75
    assert default_plan().model_dump() == before


@pytest.mark.parametrize("mismatched_role", ["source", "load"])
def test_identity_mismatch_closes_session_without_controlling_unverified_device(
        tmp_path, monkeypatch, mismatched_role):
    import benchctl.identity

    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=12.1)
    identify = benchctl.identity.identify_and_verify

    def verified(role, device, driver):
        if role == mismatched_role:
            raise ValueError("Configured serial does not match connected instrument")
        return identify(role, device, driver)

    monkeypatch.setattr(benchctl.identity, "identify_and_verify", verified)
    path = run_bringup(fake.config_path, fake.out, arm=True, loaded_only=True)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "error"
    assert fake.sessions[mismatched_role].writes == []
    assert all(session.closed for session in fake.sessions.values())
    assert run["shutdown"][mismatched_role]["state"] == "UNKNOWN"
    assert (path / "raw/samples.jsonl").read_text() == ""


def test_loaded_only_preserves_residual_readback_without_creating_no_load_result(tmp_path, monkeypatch):
    from dcdc_bench.analysis import analyze_run
    from dcdc_bench.storage import verify_integrity

    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=12.134,
                              off_load_voltage=12.1, input_current=.0688, output_current=.0993)
    path = run_bringup(fake.config_path, fake.out, arm=True, loaded_only=True)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    events = [json.loads(line) for line in (path / "raw/events.jsonl").read_text().splitlines()]
    assert run["execution_status"] == "completed"
    assert run["errors"] == []
    assert len(run["points"]) == 1
    point = run["points"][0]
    assert point["qualification"] == "valid" and point["iout_target_A"] == .1
    assert point["acquisition_cycle_ids"] == [f"c{n:06d}" for n in range(16, 21)]
    assert [s["phase"] for s in samples] == ["starting"] * 40 + ["settling"] * 20 + ["acquiring"] * 20
    assert all(s["acquisition_settings"]["load_enabled"] is False for s in samples[:20])
    assert all(s["acquisition_settings"]["load_enabled"] is True for s in samples[20:])
    assert all(s["point_id"] == point["point_id"] for s in samples)
    assert all(s["value"] == float(s["raw_response"]) for s in samples)
    preflight = next(e for e in events if e["event"] == "outputs_off_readbacks")
    assert preflight["load_V"] == 12.1
    assert "not a qualified DUT voltage" in preflight["note"]
    assert not any(s["quantity"] == "Vout_V" and s["value"] == 12.1 for s in samples)
    for role, session in fake.sessions.items():
        assert session.opened and session.closed and not session.enabled
        assert run["shutdown"][role] == {"state": "OFF", "verified": True}
    verify_integrity(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    assert len(analysis["points"]) == 1
    assert analysis["points"][0]["efficiency_pct"] == pytest.approx(100 * 12.134 * .0993 / (24.005 * .0688))


@pytest.mark.parametrize("off_source,off_load", [(0., 13.21), (0., -.051), (.501, 12.1)])
def test_loaded_only_rejects_unsafe_off_state_before_enabling_either_output(
        tmp_path, monkeypatch, off_source, off_load):
    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=12.134,
                              off_source_voltage=off_source, off_load_voltage=off_load)
    path = run_bringup(fake.config_path, fake.out, arm=True, loaded_only=True)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted"
    assert ":OUTP CH1,ON" not in fake.sessions["source"].writes
    assert ":SOUR:INP:STAT ON" not in fake.sessions["load"].writes
    assert (path / "raw/samples.jsonl").read_text() == ""
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())


@pytest.mark.parametrize("voltage,current,expected_rows,error", [
    (13.5, .0993, 4, "Output guard failed"),
    (0., .0993, 44, "Output guard failed"),
    (12.134, .04, 44, "Requested load current not established"),
    (12.134, .151, 24, "Output guard failed"),
])
def test_loaded_only_guards_abort_without_qualifying_startup_or_settling_samples(
        tmp_path, monkeypatch, voltage, current, expected_rows, error):
    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=voltage,
                              input_current=.0688, output_current=current)
    path = run_bringup(fake.config_path, fake.out, arm=True, loaded_only=True)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert run["execution_status"] == "aborted"
    assert error in run["errors"][0]
    assert run["points"][0]["qualification"] == "inconclusive"
    assert run["points"][0]["acquisition_cycle_ids"] == []
    assert len(samples) == expected_rows
    assert all(s["phase"] != "acquiring" for s in samples)
    if voltage > 13.2:
        assert ":SOUR:INP:STAT ON" not in fake.sessions["load"].writes
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())


def test_loaded_only_source_shutdown_is_attempted_even_if_load_shutdown_fails(tmp_path, monkeypatch):
    fake = install_fake_bench(tmp_path, monkeypatch, output_voltage=12.134,
                              input_current=.0688, output_current=.0993, fail_load_shutdown=True)
    path = run_bringup(fake.config_path, fake.out, arm=True, loaded_only=True)
    run = json.loads((path / "run.json").read_text())
    assert run["shutdown"]["load"]["state"] == "UNKNOWN"
    assert run["shutdown"]["source"] == {"state": "OFF", "verified": True}
    assert "load shutdown" in run["errors"][0]
    assert not fake.sessions["source"].enabled
    assert all(session.closed for session in fake.sessions.values())
