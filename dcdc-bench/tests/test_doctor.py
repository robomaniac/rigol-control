"""Read-only doctor and outputs-OFF cadence probe, exercised only through fake SCPI sessions.

The real benchctl drivers are used against the fakes so the transcript proves
what the driver read paths actually send. No VISA session is ever opened.
"""
from types import SimpleNamespace
import json
import re

import pytest
import yaml

from dcdc_bench import cli
from dcdc_bench.doctor import (DoctorRefusal, NEVER_ISSUED, READ_ONLY_QUERIES, ReadOnlyTransport,
                               diagnostics_dir, run_doctor)
from dcdc_bench.extended import extended_plan

FORBIDDEN_TOKENS = ("*RST", "*CLS", "*ESR?", "*TST?", "*RCL", "*SAV", "*TRG", "SYST:ERR?",
                    ":OUTP CH", ":SOUR:INP:STAT ON", ":SOUR:INP:STAT OFF", "CH1,ON", "CH1,OFF")


def is_query(command):
    """A SCPI query header ends with '?' before any argument (e.g. ':OUTP? CH1', '*IDN?')."""
    return command.split(" ", 1)[0].endswith("?")


class FakeClock:
    def __init__(self):
        self.value = 1000.

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def make_fake(tmp_path, monkeypatch, *, source_on=False, load_on=False, status_byte="0", serial_suffix="",
              load_voltage_period_s=None, latency_s=.003, sense="0", ovp_alarm="NO", question="0",
              fail_open=None, expected_serial=True):
    import benchctl.config
    import benchctl.transport
    import dcdc_bench.doctor as doctor

    clock, sessions, commands = FakeClock(), {}, []

    class Session:
        def __init__(self, role, resource, **kwargs):
            assert resource == f"FAKE-{role}" and kwargs["timeout_ms"] == 1500
            assert "diagnostics" in str(kwargs["log_path"]) or str(tmp_path) in str(kwargs["log_path"])
            self.role, self.opened, self.closed = role, False, False
            self.enabled = source_on if role == "source" else load_on
            self.responses = {
                "*STB?": status_byte, ":OUTP:CVCC? CH1": "UR", ":SOUR1:VOLT?": "24.000", ":SOUR1:CURR?": "0.1500",
                ":OUTP:OVP? CH1": "ON", ":OUTP:OVP:VAL? CH1": "26.00", ":OUTP:OVP:QUES? CH1": ovp_alarm,
                ":OUTP:OCP? CH1": "ON", ":OUTP:OCP:VAL? CH1": "0.500", ":OUTP:OCP:QUES? CH1": "NO",
                ":SYST:OTP?": "ON", ":TIMER?": "OFF", ":DELAY?": "OFF", ":INST:NSEL?": "1",
                ":MEAS:VOLT? CH1": "+0.000000E+00", ":MEAS:CURR? CH1": "+0.000000E+00",
                ":SOUR:FUNC?": "CURR", ":SOUR:FUNC:MODE?": "FIX", ":SOUR:CURR:LEV:IMM?": "0.1000",
                ":SOUR:CURR:VLIM?": "13.2000", ":SOUR:CURR:ILIM?": "0.6000", ":SOUR:SENS?": sense,
                ":STAT:QUES:COND?": question, ":MEAS:CURR?": "+1.100000E-03"}
            sessions[role] = self

        def open(self):
            if fail_open == self.role:
                raise OSError("simulated unreachable instrument")
            self.opened = True

        def close(self):
            self.closed = True

        def query(self, command):
            assert self.opened, "query before open"
            commands.append((self.role, "query", command))
            clock.value += latency_s
            if command == "*IDN?":
                model = "DP821A" if self.role == "source" else "DL3031A"
                return f"RIGOL TECHNOLOGIES,{model},FAKE-{self.role}{serial_suffix},00.01.16"
            if command in (":OUTP? CH1", ":SOUR:INP:STAT?"):
                return "ON" if self.enabled else "OFF"
            if command == ":OUTP? CH2":
                return "OFF"
            if command == ":MEAS:VOLT?":
                if load_voltage_period_s is None:
                    return "+1.780000E-01"
                step = int((clock.value - 1000.) // load_voltage_period_s)
                return f"+{.178 + step * 1e-4:.6E}"
            return self.responses[command]

        def write(self, command):
            commands.append((self.role, "write", command))
            raise AssertionError(f"fake instrument received a write: {command}")

    config = SimpleNamespace(devices={
        "psu_rigol_1": SimpleNamespace(expected_serial="FAKE-source" if expected_serial else None, driver="rigol_dp800", resource="FAKE-source"),
        "load_rigol_1": SimpleNamespace(expected_serial="FAKE-load" if expected_serial else None, driver="rigol_dl3000", resource="FAKE-load")})
    monkeypatch.setattr(benchctl.config, "load_config", lambda path: config)
    monkeypatch.setattr(benchctl.transport, "VisaTransport", Session)
    monkeypatch.setattr(doctor, "time", clock)
    monkeypatch.setenv("DCDC_DIAGNOSTICS_DIR", str(tmp_path / "diagnostics"))
    inventory = tmp_path / "fake-inventory.yaml"
    inventory.write_text("schema_version: 1\n")
    return SimpleNamespace(clock=clock, sessions=sessions, commands=commands, inventory=inventory)


def bench_file(tmp_path, *, approved=True, mode="real"):
    bench = extended_plan().bench
    bench.protective_controls.approved = approved
    if mode == "mock":
        bench.mode = "mock"
    path = tmp_path / f"bench-{'approved' if approved else 'unapproved'}-{mode}.yaml"
    path.write_text(yaml.safe_dump(bench.model_dump(mode="json")))
    return path


def assert_read_only(fake, diagnosis):
    assert not [c for c in fake.commands if c[1] == "write"]
    sent = [c[2] for c in fake.commands]
    assert sent and set(sent) <= READ_ONLY_QUERIES
    assert all(is_query(c) for c in sent)
    assert not any(token in c for c in sent for token in NEVER_ISSUED + FORBIDDEN_TOKENS)
    assert {e["command"] for e in diagnosis["transcript"]} == set(sent)
    assert diagnosis["summary"]["writes"] == 0
    assert all(s.opened and s.closed for s in fake.sessions.values())


def test_approved_profile_outputs_off_reads_everything_without_writing(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch)
    path, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory)
    assert diagnosis["exit_code"] == 0 and diagnosis["findings"] == []
    assert_read_only(fake, diagnosis)
    assert path.parent == (tmp_path / "diagnostics").resolve() and path.name.startswith("doctor-")
    saved = json.loads(path.read_text())
    source, load = saved["instruments"]["source"], saved["instruments"]["load"]
    assert source["identity"]["model"] == "DP821A" and load["identity"]["serial"] == "FAKE-load"
    assert source["output_on"] == {"CH1": False, "CH2": False} and load["input_on"] is False
    assert source["protections_CH1"]["OVP"] == {"enabled": True, "enabled_raw": "ON", "value": 26., "value_raw": "26.00",
                                                 "alarm_raw": "NO", "tripped": False}
    assert source["protections_CH1"]["OTP"]["enabled"] is True
    assert load["limits"]["voltage_limit_V"]["value"] == 13.2 and load["sense"] == "local"
    assert load["function"] == "cc" and load["questionable_condition"] == 0
    assert source["status_byte"]["error_queue_nonempty"] is False
    assert "not drained" in saved["read_only_policy"]["error_queue"]
    assert "SYST:ERR?" not in {e["command"] for e in saved["transcript"]}
    assert source["identity_checks"]["inventory_serial_match"] is True
    assert all(e["end_monotonic_s"] >= e["start_monotonic_s"] for e in saved["transcript"])
    assert saved["cadence"] is None


def test_unapproved_profile_exits_nonzero_with_message_and_still_never_writes(tmp_path, monkeypatch, capsys):
    fake = make_fake(tmp_path, monkeypatch)
    code = cli.main(["doctor", "--bench", str(bench_file(tmp_path, approved=False)), "--inventory", str(fake.inventory)])
    out = capsys.readouterr().out
    assert code == 4
    assert "not approved" in out and "protective_controls.approved" in out
    assert not [c for c in fake.commands if c[1] == "write"]
    saved = json.loads(next((tmp_path / "diagnostics").glob("doctor-*.json")).read_text())
    assert saved["exit_code"] == 4 and saved["findings"][0]["severity"] == "blocking"
    assert_read_only(fake, saved)


def test_mock_profile_is_refused_before_any_connection(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch)
    with pytest.raises(DoctorRefusal, match="mock profile"):
        run_doctor(bench_file(tmp_path, mode="mock"), fake.inventory)
    assert fake.sessions == {} and fake.commands == []
    assert not (tmp_path / "diagnostics").exists()


def test_enabled_output_is_reported_never_turned_off_and_cadence_is_refused(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch, source_on=True)
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory, cadence=True, seconds=2)
    assert diagnosis["instruments"]["source"]["output_on"]["CH1"] is True
    assert any("output is ON" in f["message"] for f in diagnosis["findings"])
    assert diagnosis["cadence"]["status"] == "refused" and diagnosis["exit_code"] == 2
    assert diagnosis["cadence"]["verified_states"] == {"source_CH1": True, "source_CH2": False, "load_input": False}
    assert_read_only(fake, diagnosis)
    assert not any(c[2] in (":MEAS:VOLT?", ":MEAS:CURR?") and i > 30 for i, c in enumerate(fake.commands))


def test_unreadable_output_state_refuses_cadence(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch)
    original = fake.sessions  # populated lazily; patch the Session class through the transport module
    import benchctl.transport
    Session = benchctl.transport.VisaTransport
    query = Session.query

    def flaky(self, command):
        if command == ":SOUR:INP:STAT?":
            raise OSError("timeout")
        return query(self, command)

    monkeypatch.setattr(Session, "query", flaky)
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory, cadence=True, seconds=1)
    assert diagnosis["instruments"]["load"]["input_on"] is None
    assert diagnosis["instruments"]["load"]["unreadable"]["input_on"]["status"] == "unreadable"
    assert diagnosis["cadence"]["status"] == "refused" and diagnosis["exit_code"] == 2
    assert not [c for c in fake.commands if c[1] == "write"]
    assert original is fake.sessions


def test_cadence_probe_estimates_change_period_and_states_its_scope(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch, load_voltage_period_s=.2, latency_s=.003)
    path, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory, cadence=True, seconds=4, poll_interval=.02)
    assert diagnosis["exit_code"] == 0
    assert_read_only(fake, diagnosis)
    cadence = diagnosis["cadence"]
    assert cadence["status"] == "completed" and cadence["scope"] == "outputs-OFF cadence observation of the readback path"
    assert "NOT a loaded-measurement freshness qualification" in cadence["statement"]
    assert "NOT an ADC update-rate specification" in cadence["statement"]
    assert cadence["verified_states"] == {"source_CH1": False, "source_CH2": False, "load_input": False}
    vout = cadence["channels"]["load:Vout_V"]
    assert vout["query_count"] >= 100 and vout["failed_query_count"] == 0
    assert vout["median_query_latency_s"] == pytest.approx(.003)
    assert vout["distinct_value_change_count"] >= 15
    assert vout["estimate_status"] == "observed"
    assert vout["estimated_readback_update_period_s"] == pytest.approx(.2, abs=.035)
    assert all(.15 <= i <= .25 for i in vout["change_intervals_s"])
    assert all("raw_response" in s and s["end_monotonic_s"] >= s["start_monotonic_s"] for s in vout["samples"])
    constant = cadence["channels"]["source:Vin_V"]
    assert constant["distinct_value_change_count"] == 0 and constant["estimated_readback_update_period_s"] is None
    assert constant["estimate_status"].startswith("not observable")
    assert set(cadence["channels"]) == {"source:Vin_V", "source:Iin_A", "load:Vout_V", "load:Iout_A"}
    assert path.parent == (tmp_path / "diagnostics").resolve()
    assert not any(p.name in ("run.json", "integrity.json") for p in path.parent.iterdir())
    assert json.loads(path.read_text())["cadence"]["channels"]["load:Vout_V"]["estimate_status"] == "observed"


def test_cadence_cli_flags_and_bounds(tmp_path, monkeypatch, capsys):
    fake = make_fake(tmp_path, monkeypatch, load_voltage_period_s=.5)
    code = cli.main(["doctor", "--bench", str(bench_file(tmp_path)), "--inventory", str(fake.inventory),
                     "--readback-cadence", "--seconds", "2", "--poll-interval", "0.05",
                     "--out", str(tmp_path / "diagnostics" / "probe.json")])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["cadence"] == "completed" and printed["diagnosis"].endswith("probe.json")
    assert (tmp_path / "diagnostics" / "probe.json").exists()
    with pytest.raises(DoctorRefusal, match="1–120"):
        run_doctor(bench_file(tmp_path), fake.inventory, cadence=True, seconds=0)
    assert not [c for c in fake.commands if c[1] == "write"]


def test_read_only_transport_refuses_writes_and_non_allowlisted_queries():
    received = []
    inner = SimpleNamespace(query=lambda c: received.append(c) or "x", write=lambda c: received.append(c), close=lambda: None)
    transcript = []
    transport = ReadOnlyTransport("source", inner, transcript, clock=FakeClock())
    for command in ("SYST:ERR?", ":SYST:ERR?", "*ESR?", "*RST", ":OUTP CH1,ON", ":MEAS:VOLT? CH2"):
        with pytest.raises(DoctorRefusal):
            transport.query(command)
    for command in ("*CLS", "*RST", ":OUTP CH1,OFF", ":SOUR1:VOLT 5"):
        with pytest.raises(DoctorRefusal, match="refused to write"):
            transport.write(command)
    assert received == [] and transcript == []
    assert transport.query("*IDN?") == "x" and received == ["*IDN?"]
    assert transcript[0]["command"] == "*IDN?" and transcript[0]["response"] == "x"
    assert "SYST:ERR?" in NEVER_ISSUED and "*RST" in NEVER_ISSUED and "*CLS" in NEVER_ISSUED
    assert not any(q in NEVER_ISSUED for q in READ_ONLY_QUERIES)
    assert all(q.endswith("?") or " CH" in q for q in READ_ONLY_QUERIES)
    assert all("?" in q for q in READ_ONLY_QUERIES)


def test_identity_mismatch_and_error_flag_and_alarms_become_findings_not_actions(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch, serial_suffix="-OTHER", status_byte="4", ovp_alarm="YES", sense="1", question="8")
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory)
    messages = " | ".join(f["message"] for f in diagnosis["findings"])
    assert diagnosis["exit_code"] == 4
    assert "serial mismatch" in messages
    assert "error/event queue is not empty" in messages and "SYST:ERR?" in messages
    assert "OVP reports an alarm" in messages and "not cleared" in messages
    assert "requires local sensing" in messages
    assert "questionable condition 8" in messages
    assert diagnosis["instruments"]["source"]["identity_checks"]["inventory_serial_match"] is False
    assert diagnosis["instruments"]["load"]["status_byte"]["error_queue_nonempty"] is True
    assert_read_only(fake, diagnosis)


def test_missing_inventory_serial_is_a_blocking_finding(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch, expected_serial=False)
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory)
    assert diagnosis["exit_code"] == 4
    assert [f for f in diagnosis["findings"] if f["field"] == "expected_serial" and f["severity"] == "blocking"]
    assert diagnosis["instruments"]["load"]["identity_checks"]["inventory_serial_match"] == "not-configured"
    assert_read_only(fake, diagnosis)


def test_one_unreachable_instrument_does_not_hide_the_other(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch, fail_open="source")
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory)
    assert diagnosis["instruments"]["source"]["connection"]["status"] == "failed"
    assert diagnosis["instruments"]["load"]["connection"]["status"] == "open"
    assert diagnosis["exit_code"] == 4 and fake.sessions["load"].closed
    assert not [c for c in fake.commands if c[1] == "write"]


def test_profile_expectations_are_compared_when_present(tmp_path, monkeypatch):
    fake = make_fake(tmp_path, monkeypatch)
    bench = extended_plan().bench
    bench.source.physical_model, bench.load.firmware = "DP832", "99.99"
    path = tmp_path / "bench-expect.yaml"
    path.write_text(yaml.safe_dump(bench.model_dump(mode="json")))
    _, diagnosis = run_doctor(path, fake.inventory)
    checks = {role: diagnosis["instruments"][role]["identity_checks"]["profile_expectations"] for role in ("source", "load")}
    assert checks["source"]["physical_model"] == {"profile": "DP832", "reported": "DP821A", "match": False}
    assert checks["load"]["firmware"]["match"] is False and diagnosis["exit_code"] == 4
    assert_read_only(fake, diagnosis)


def test_diagnostics_folder_inside_a_run_folder_is_refused(tmp_path, monkeypatch):
    run = tmp_path / "runs" / "20260101T000000.000000Z_real_abcdef"
    (run / "raw").mkdir(parents=True)
    (run / "run.json").write_text("{}")
    with pytest.raises(DoctorRefusal, match="inside a run folder"):
        diagnostics_dir(run / "diagnostics")
    monkeypatch.setenv("DCDC_DIAGNOSTICS_DIR", str(tmp_path / "elsewhere"))
    assert diagnostics_dir() == (tmp_path / "elsewhere").resolve()
    fake = make_fake(tmp_path, monkeypatch)
    with pytest.raises(DoctorRefusal, match="inside a run folder"):
        run_doctor(bench_file(tmp_path), fake.inventory, out=run / "doctor.json")
    assert fake.sessions == {}


def test_doctor_never_uses_the_write_paths_of_the_real_drivers(tmp_path, monkeypatch):
    """Guard against a future driver read method starting to drain the error queue."""
    from benchctl.drivers.rigol_dl3000 import RigolDL3000
    from benchctl.drivers.rigol_dp800 import RigolDP800
    fake = make_fake(tmp_path, monkeypatch)
    for cls, name in ((RigolDP800, "check_errors"), (RigolDL3000, "check_errors")):
        monkeypatch.setattr(cls, name, lambda self: (_ for _ in ()).throw(AssertionError("error queue drained")))
    _, diagnosis = run_doctor(bench_file(tmp_path), fake.inventory, cadence=True, seconds=1)
    assert diagnosis["exit_code"] == 0
    assert_read_only(fake, diagnosis)


def test_mid_run_refusal_keeps_the_partial_diagnosis_and_exits_nonzero(tmp_path, monkeypatch):
    """m7: a refusal after the source was read must not discard what was gathered."""
    import dcdc_bench.doctor as doctor
    fake = make_fake(tmp_path, monkeypatch)
    original = doctor._identity_checks

    def refusing(role, identity, device, capability, findings):
        if role == "load":
            raise DoctorRefusal("simulated refusal while diagnosing the load")
        return original(role, identity, device, capability, findings)
    monkeypatch.setattr(doctor, "_identity_checks", refusing)
    with pytest.raises(DoctorRefusal, match="partial diagnosis saved to") as caught:
        run_doctor(bench_file(tmp_path), fake.inventory)
    path = next((tmp_path / "diagnostics").glob("doctor-*.json"))
    assert str(path.resolve()) in str(caught.value)
    saved = json.loads(path.read_text())
    assert saved["exit_code"] == 2 and saved["refusal"].startswith("DoctorRefusal: simulated refusal")
    assert saved["instruments"]["source"]["identity"]["model"] == "DP821A" and "load" not in saved["instruments"]
    assert any(f["field"] == "refusal" and f["severity"] == "blocking" for f in saved["findings"])
    assert saved["summary"]["queries"] == len(saved["transcript"]) > 0 and saved["summary"]["writes"] == 0
    assert saved["close_errors"] == [] and all(s.opened and s.closed for s in fake.sessions.values())
    assert not [c for c in fake.commands if c[1] == "write"]
