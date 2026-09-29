"""Read-only bench diagnosis and outputs-OFF readback-cadence probe.

Nothing in this module writes to an instrument. Every SCPI command passes
through ``ReadOnlyTransport``, which refuses ``write`` outright and refuses
any ``query`` that is not on the explicit query-only allowlist below. The
existing benchctl drivers are reused for their read-only methods; their
state-changing methods (which also drain the SCPI error queue) are never
called. The instrument error queue is deliberately not read with
``SYST:ERR?`` because that command removes the entry it returns; instead the
IEEE 488.2 status byte (``*STB?``) is read and its error-available bit is
reported so a fault remains on the instrument for the operator to inspect.

Connection side effects of the reused drivers are documented in
``docs/doctor-and-publication.md`` and pinned by ``tests/test_doctor.py``.
"""
from __future__ import annotations

import hashlib
import os
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .domain import BenchProfile
from .planning import load_profile
from .storage import atomic_json

SOURCE_QUERIES = (
    "*IDN?", "*STB?",
    ":OUTP? CH1", ":OUTP? CH2", ":OUTP:CVCC? CH1",
    ":SOUR1:VOLT?", ":SOUR1:CURR?",
    ":OUTP:OVP? CH1", ":OUTP:OVP:VAL? CH1", ":OUTP:OVP:QUES? CH1",
    ":OUTP:OCP? CH1", ":OUTP:OCP:VAL? CH1", ":OUTP:OCP:QUES? CH1",
    ":SYST:OTP?", ":TIMER?", ":DELAY?", ":INST:NSEL?",
    ":MEAS:VOLT? CH1", ":MEAS:CURR? CH1",
)
LOAD_QUERIES = (
    "*IDN?", "*STB?",
    ":SOUR:INP:STAT?", ":SOUR:FUNC?", ":SOUR:FUNC:MODE?", ":SOUR:CURR:LEV:IMM?",
    ":SOUR:CURR:VLIM?", ":SOUR:CURR:ILIM?", ":SOUR:SENS?", ":STAT:QUES:COND?",
    ":MEAS:VOLT?", ":MEAS:CURR?",
)
READ_ONLY_QUERIES = frozenset(SOURCE_QUERIES + LOAD_QUERIES)
# Documented for reviewers; the allowlist above already excludes these. The
# error-queue query pops the entry it returns, *ESR? clears the event register.
NEVER_ISSUED = ("*RST", "*CLS", "*ESR?", "*TST?", "*RCL", "*SAV", "*TRG", "SYST:ERR?", ":SYST:ERR?")
MEASURE_QUERIES = {"source": ((":MEAS:VOLT? CH1", "Vin_V"), (":MEAS:CURR? CH1", "Iin_A")),
                   "load": ((":MEAS:VOLT?", "Vout_V"), (":MEAS:CURR?", "Iout_A"))}
DEVICE_NAMES = {"source": "psu_rigol_1", "load": "load_rigol_1"}
DRIVERS = {"source": "rigol_dp800", "load": "rigol_dl3000"}
ADAPTERS = {"source": ("benchctl_dp800", "benchctl_rigol_dp800"), "load": ("benchctl_dl3000", "benchctl_rigol_dl3000")}
# Documented DL3000 questionable-condition fault bits (VF, OC, OP, reverse
# voltage, unregulated, low reverse voltage, overvoltage, shutdown); the same
# mask the supervised procedures stop on. RUN/VON/RS are not fault bits.
LOAD_FAULT_MASK = 15883
STATUS_BYTE_ERROR_AVAILABLE = 0x04
CADENCE_SCOPE = "outputs-OFF cadence observation of the readback path"
CADENCE_IS_NOT = ["a loaded-measurement freshness qualification",
                  "an ADC update-rate specification",
                  "a readback accuracy or uncertainty statement"]


class DoctorRefusal(RuntimeError):
    """The doctor declined before or during a read-only diagnosis; no instrument was written."""


class ReadOnlyTransport:
    """Structural guarantee: writes never reach the instrument, queries are allowlisted."""

    def __init__(self, role: str, transport, transcript: list, clock=None):
        self.role, self.transport, self.transcript = role, transport, transcript
        self.clock = clock or time

    def query(self, command: str) -> str:
        if command not in READ_ONLY_QUERIES:
            raise DoctorRefusal(f"Read-only doctor refused to send {command!r} to {self.role}: not on the query allowlist")
        entry = {"role": self.role, "command": command, "start_monotonic_s": self.clock.monotonic()}
        try:
            response = self.transport.query(command)
        except Exception as exc:  # noqa: BLE001 - the transcript keeps the failure as evidence
            entry.update(end_monotonic_s=self.clock.monotonic(), error=f"{type(exc).__name__}: {exc}")
            self.transcript.append(entry)
            raise
        entry.update(end_monotonic_s=self.clock.monotonic(), response=response)
        self.transcript.append(entry)
        return response

    def write(self, command: str) -> None:
        raise DoctorRefusal(f"Read-only doctor refused to write {command!r} to {self.role}")

    def close(self) -> None:
        return self.transport.close()


def diagnostics_dir(explicit: Path | None = None) -> Path:
    """Diagnostics live beside, never inside, run folders."""
    root = Path(explicit) if explicit is not None else Path(
        os.environ.get("DCDC_DIAGNOSTICS_DIR", str(Path(__file__).resolve().parents[2] / "diagnostics")))
    root = root.resolve()
    for candidate in (root, *root.parents):
        if (candidate / "integrity.json").exists() or (candidate / "run.json").exists():
            raise DoctorRefusal(f"Diagnostics folder {root} is inside a run folder ({candidate}); choose another location")
    return root


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _truthy(text: str) -> bool | None:
    token = str(text).strip().upper()
    if token in ("1", "+1", "ON", "TRUE"):
        return True
    if token in ("0", "+0", "OFF", "FALSE"):
        return False
    return None


def _number(text: str) -> float | None:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


class _Reader:
    """Read one value at a time; a failed read is recorded, never fatal."""

    def __init__(self, role: str, findings: list):
        self.role, self.findings, self.values = role, findings, {}

    def __call__(self, label: str, function):
        try:
            value = function()
        except DoctorRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - keep diagnosing the other fields
            self.values[label] = {"status": "unreadable", "error": f"{type(exc).__name__}: {exc}"}
            self.findings.append({"role": self.role, "severity": "attention", "field": label,
                                  "message": f"{self.role} {label} could not be read: {type(exc).__name__}: {exc}"})
            return None
        self.values[label] = value
        return value


def _identity_checks(role: str, identity: dict | None, device, capability, findings: list) -> dict:
    result = {"inventory_expected_serial_configured": bool(device.expected_serial)}
    if identity is None:
        result["inventory_serial_match"] = None
        return result
    if not device.expected_serial:
        result["inventory_serial_match"] = "not-configured"
        findings.append({"role": role, "severity": "blocking", "field": "expected_serial",
                         "message": f"inventory {DEVICE_NAMES[role]} has no expected_serial; set it from the "
                                    "reported identity before any control command"})
    else:
        from benchctl.identity import SerialMismatchError, verify_expected_serial
        from benchctl.interfaces import Identification
        try:
            verify_expected_serial(DEVICE_NAMES[role], device, Identification(**identity))
            result["inventory_serial_match"] = True
        except SerialMismatchError as exc:
            result["inventory_serial_match"] = False
            findings.append({"role": role, "severity": "blocking", "field": "serial", "message": str(exc)})
    expectations = {}
    for field, reported in (("physical_model", identity["model"]), ("firmware", identity["firmware"])):
        expected = getattr(capability, field)
        if expected is not None:
            expectations[field] = {"profile": expected, "reported": reported, "match": expected == reported}
            if expected != reported:
                findings.append({"role": role, "severity": "blocking", "field": field,
                                 "message": f"{role} reported {field} {reported!r} differs from bench profile {expected!r}"})
    if capability.reported_identity is not None:
        joined = ",".join(identity[k] for k in ("manufacturer", "model", "serial", "firmware"))
        match = capability.reported_identity == joined or identity["model"] in capability.reported_identity
        expectations["reported_identity"] = {"profile": capability.reported_identity, "reported": joined, "match": match}
        if not match:
            findings.append({"role": role, "severity": "blocking", "field": "reported_identity",
                             "message": f"{role} identity {joined!r} does not match bench profile reported_identity"})
    result["profile_expectations"] = expectations
    return result


def _status_byte(role: str, raw, findings: list) -> dict:
    value = _number(raw) if raw is not None else None
    if value is None or value < 0:
        return {"raw": raw, "error_queue_nonempty": None,
                "note": "status byte unreadable; the error queue was not read and remains on the instrument"}
    nonempty = bool(int(value) & STATUS_BYTE_ERROR_AVAILABLE)
    if nonempty:
        findings.append({"role": role, "severity": "attention", "field": "error_queue",
                         "message": f"{role} status byte reports the error/event queue is not empty; the doctor left "
                                    "it in place (SYST:ERR? would remove entries). Inspect it on the instrument."})
    return {"raw": raw, "value": int(value), "error_queue_nonempty": nonempty,
            "note": "IEEE 488.2 status byte bit 2 (error/event queue available); the bit assignment on this "
                    "instrument pair has not been bench-verified. The queue itself was not read."}


def _diagnose_source(read: _Reader, driver, transport, findings: list, bench: BenchProfile) -> dict:
    role = "source"
    idn = read("identity", lambda: asdict(driver.identify()))
    output = {f"CH{channel}": read(f"output_on_CH{channel}", lambda c=channel: driver.get_output_enabled(c))
              for channel in (1, 2)}
    for channel, enabled in output.items():
        if enabled:
            findings.append({"role": role, "severity": "attention", "field": f"output_{channel}",
                             "message": f"source {channel} output is ON; the doctor does not change it"})
    setpoints = {"voltage_V": read("voltage_setpoint_V", lambda: driver.get_voltage_setpoint(1)),
                 "current_limit_A": read("current_limit_A", lambda: driver.get_current_limit(1))}
    protections = {}
    for kind in ("OVP", "OCP"):
        enabled = read(f"{kind}_enabled", lambda k=kind: transport.query(f":OUTP:{k}? CH1").strip())
        value = read(f"{kind}_value", lambda k=kind: transport.query(f":OUTP:{k}:VAL? CH1").strip())
        alarm = read(f"{kind}_alarm", lambda k=kind: transport.query(f":OUTP:{k}:QUES? CH1").strip())
        protections[kind] = {"enabled": _truthy(enabled) if enabled is not None else None, "enabled_raw": enabled,
                             "value": _number(value) if value is not None else None, "value_raw": value,
                             "alarm_raw": alarm, "tripped": None if alarm is None else alarm.strip().upper() != "NO"}
        if protections[kind]["tripped"]:
            findings.append({"role": role, "severity": "attention", "field": kind,
                             "message": f"source {kind} reports an alarm ({alarm!r}); evidence left in place, not cleared"})
    otp = read("OTP_enabled", lambda: transport.query(":SYST:OTP?").strip())
    protections["OTP"] = {"enabled": _truthy(otp) if otp is not None else None, "enabled_raw": otp}
    if otp is not None and not protections["OTP"]["enabled"]:
        findings.append({"role": role, "severity": "attention", "field": "OTP",
                         "message": "source over-temperature protection reads disabled"})
    controls = bench.protective_controls
    for kind, expected in (("OVP", controls.dut_input_overvoltage_V), ("OCP", None)):
        actual = protections[kind]["value"]
        if expected is not None and actual is not None and abs(actual - expected) > .001:
            findings.append({"role": role, "severity": "attention", "field": f"{kind}_value",
                             "message": f"source {kind} value {actual:g} differs from bench profile {expected:g}; "
                                        "the doctor does not program protections"})
    timers = {"timer_raw": read("timer", lambda: transport.query(":TIMER?").strip()),
              "delay_raw": read("delay", lambda: transport.query(":DELAY?").strip()),
              "selected_channel_raw": read("selected_channel", lambda: transport.query(":INST:NSEL?").strip())}
    for key in ("timer_raw", "delay_raw"):
        if timers[key] is not None and timers[key].upper() not in ("OFF", "0"):
            findings.append({"role": role, "severity": "attention", "field": key,
                             "message": f"source {key.split('_')[0]} function reads {timers[key]!r}, not OFF"})
    mode = read("mode_CVCC_CH1", lambda: transport.query(":OUTP:CVCC? CH1").strip())
    measured = {"Vin_V": read("measured_voltage_V", lambda: driver.measure_voltage(1)),
                "Iin_A": read("measured_current_A", lambda: driver.measure_current(1))}
    status = _status_byte(role, read("status_byte", lambda: transport.query("*STB?").strip()), findings)
    return {"identity": idn, "output_on": output, "mode_CVCC_CH1": mode, "setpoints_CH1": setpoints,
            "protections_CH1": protections, "timers": timers, "measured_CH1": measured, "status_byte": status}


def _diagnose_load(read: _Reader, driver, transport, findings: list, bench: BenchProfile) -> dict:
    role = "load"
    idn = read("identity", lambda: asdict(driver.identify()))
    enabled = read("input_on", driver.get_input_enabled)
    if enabled:
        findings.append({"role": role, "severity": "attention", "field": "input",
                         "message": "load input is ON; the doctor does not change it"})
    function = read("function", driver.get_mode)
    operation = read("operation_mode", lambda: transport.query(":SOUR:FUNC:MODE?").strip())
    setpoint = read("current_setpoint_A", driver.get_current_setpoint)
    limits = {}
    for key, query in (("voltage_limit_V", ":SOUR:CURR:VLIM?"), ("current_limit_A", ":SOUR:CURR:ILIM?")):
        raw = read(key, lambda q=query: transport.query(q).strip())
        limits[key] = {"value": _number(raw) if raw is not None else None, "raw": raw}
    controls = bench.protective_controls
    for key, expected in (("voltage_limit_V", controls.dut_output_overvoltage_V), ("current_limit_A", controls.output_overcurrent_A)):
        actual = limits[key]["value"]
        if expected is not None and actual is not None and abs(actual - expected) > .001:
            findings.append({"role": role, "severity": "attention", "field": key,
                             "message": f"load {key} {actual:g} differs from bench profile {expected:g}; "
                                        "the doctor does not program limits"})
    sense_raw = read("sense", lambda: transport.query(":SOUR:SENS?").strip())
    sense = None if sense_raw is None else ("local" if sense_raw.upper() in ("0", "OFF") else
                                            "remote" if sense_raw.upper() in ("1", "ON") else "unknown")
    if sense is not None:
        wanted = "remote" if bench.load.remote_sense_required else "local"
        if sense != wanted:
            findings.append({"role": role, "severity": "blocking", "field": "sense",
                             "message": f"load sense reads {sense} ({sense_raw!r}); the bench profile requires {wanted} sensing"})
    condition_raw = read("questionable_condition", lambda: transport.query(":STAT:QUES:COND?").strip())
    condition = None
    if condition_raw is not None:
        try:
            condition = int(condition_raw, 0) if condition_raw.lower().startswith("0x") else int(condition_raw)
        except ValueError:
            condition = None
        if condition is not None and condition & LOAD_FAULT_MASK:
            findings.append({"role": role, "severity": "attention", "field": "questionable_condition",
                             "message": f"load questionable condition {condition} has fault bits set; left in place, not cleared"})
    measured = {"Vout_V": read("measured_voltage_V", driver.measure_voltage),
                "Iout_A": read("measured_current_A", driver.measure_current)}
    status = _status_byte(role, read("status_byte", lambda: transport.query("*STB?").strip()), findings)
    return {"identity": idn, "input_on": enabled, "function": function, "operation_mode_raw": operation,
            "current_setpoint_A": setpoint, "limits": limits, "sense": sense, "sense_raw": sense_raw,
            "questionable_condition": condition, "questionable_condition_raw": condition_raw,
            "measured": measured, "status_byte": status}


def _cadence(transports: dict, seconds: float, poll_interval: float, clock) -> dict:
    """Poll measure queries with outputs verified OFF and time distinct-value changes."""
    began = clock.monotonic()
    records = {(role, quantity): [] for role, pairs in MEASURE_QUERIES.items() for _, quantity in pairs
               if role in transports}
    rounds = 0
    while True:
        round_start = clock.monotonic()
        for role, pairs in MEASURE_QUERIES.items():
            transport = transports.get(role)
            if transport is None:
                continue
            for command, quantity in pairs:
                start = clock.monotonic()
                try:
                    raw = transport.query(command)
                    error = None
                except DoctorRefusal:
                    raise
                except Exception as exc:  # noqa: BLE001 - a failed poll is evidence, not an abort
                    raw, error = None, f"{type(exc).__name__}: {exc}"
                end = clock.monotonic()
                records[(role, quantity)].append({"start_monotonic_s": start - began, "end_monotonic_s": end - began,
                                                  "raw_response": raw, **({"error": error} if error else {})})
        rounds += 1
        if clock.monotonic() - began >= seconds:
            break
        remaining = poll_interval - (clock.monotonic() - round_start)
        if remaining > 0:
            clock.sleep(remaining)
    channels = {}
    for (role, quantity), rows in records.items():
        good = [r for r in rows if "error" not in r]
        latencies = [r["end_monotonic_s"] - r["start_monotonic_s"] for r in good]
        change_times, previous = [], None
        for row in good:
            if previous is not None and row["raw_response"] != previous:
                change_times.append((row["start_monotonic_s"] + row["end_monotonic_s"]) / 2)
            previous = row["raw_response"]
        intervals = [b - a for a, b in zip(change_times, change_times[1:])]
        estimate = statistics.median(intervals) if len(intervals) >= 2 else None
        channels[f"{role}:{quantity}"] = {
            "role": role, "quantity": quantity, "query_count": len(rows), "failed_query_count": len(rows) - len(good),
            "median_query_latency_s": statistics.median(latencies) if latencies else None,
            "min_query_latency_s": min(latencies) if latencies else None,
            "max_query_latency_s": max(latencies) if latencies else None,
            "distinct_value_change_count": len(change_times),
            "change_intervals_s": intervals[:500],
            "median_change_interval_s": statistics.median(intervals) if intervals else None,
            "min_change_interval_s": min(intervals) if intervals else None,
            "max_change_interval_s": max(intervals) if intervals else None,
            "estimated_readback_update_period_s": estimate,
            "estimate_status": ("observed" if estimate is not None else
                                "not observable: fewer than three distinct consecutive values in the window"),
            "distinct_values_seen": len({r["raw_response"] for r in good}),
            "samples": rows[:2000]}
    elapsed = clock.monotonic() - began
    return {"status": "completed", "scope": CADENCE_SCOPE, "is_not": CADENCE_IS_NOT,
            "statement": ("This is an outputs-OFF cadence observation of the readback path. It is NOT a "
                          "loaded-measurement freshness qualification and NOT an ADC update-rate specification. "
                          "A distinct-value change interval bounds the readback update period only when the "
                          "underlying reading changes between updates; identical consecutive updates are invisible, "
                          "and the resolution is limited by the polling period plus query latency."),
            "requested_seconds": seconds, "elapsed_s": elapsed, "poll_interval_s": poll_interval, "rounds": rounds,
            "channels": channels}


def run_doctor(bench_path: Path, inventory_path: Path, *, out: Path | None = None, cadence: bool = False,
               seconds: float = 10., poll_interval: float = .05, diagnostics: Path | None = None) -> tuple[Path, dict]:
    """Connect read-only, read identities/states/protections, compare with the profile, save a diagnosis."""
    bench_path, inventory_path = Path(bench_path), Path(inventory_path)
    bench = load_profile(bench_path, BenchProfile)
    if bench.mode != "real":
        raise DoctorRefusal(f"Bench profile {bench.bench_id!r} is a {bench.mode} profile; there are no instruments to diagnose")
    for role in ("source", "load"):
        if getattr(bench, role).adapter not in ADAPTERS[role]:
            raise DoctorRefusal(f"Bench profile {role} adapter {getattr(bench, role).adapter!r} is not a benchctl DP800/DL3000 adapter")
    if cadence and not 1 <= seconds <= 120:
        raise DoctorRefusal("Cadence probe duration must be 1–120 seconds")
    if cadence and not .01 <= poll_interval <= 5:
        raise DoctorRefusal("Cadence poll interval must be 0.01–5 seconds")
    from benchctl.config import load_config
    config = load_config(inventory_path)
    devices = {}
    for role, name in DEVICE_NAMES.items():
        if name not in config.devices:
            raise DoctorRefusal(f"Inventory has no {name!r} device")
        devices[role] = config.devices[name]
        if devices[role].driver != DRIVERS[role]:
            raise DoctorRefusal(f"Inventory {name!r} driver {devices[role].driver!r} is not {DRIVERS[role]!r}")
    folder = diagnostics_dir(diagnostics)
    if out is not None:
        out = Path(out)
        diagnostics_dir(out.parent)
        # The diagnosis names endpoints and serials: it only ever goes to a new
        # .json file, never over a profile, job record, approval or published copy.
        if out.suffix.lower() != ".json":
            raise DoctorRefusal(f"--out {out} must name a new .json file")
        if out.is_symlink() or out.exists():
            raise DoctorRefusal(f"--out {out} already exists; the doctor never overwrites a file")
        if (out.parent / "publication_manifest.json").exists():
            raise DoctorRefusal(f"--out {out} is inside a publication copy; diagnostics are not for publication")
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    target = out if out is not None else folder / f"doctor-{stamp}.json"
    findings: list[dict] = []
    if not bench.protective_controls.approved:
        findings.append({"role": "bench", "severity": "blocking", "field": "protective_controls.approved",
                         "message": f"bench profile {bench.bench_id!r} is not approved (protective_controls.approved is false); "
                                    "real execution stays blocked. The doctor read the instruments without writing."})
    from .runner import _provenance
    diagnosis = {
        "schema_version": "1.0", "kind": "doctor", "created_utc": now.isoformat(),
        "privacy": "Local diagnostic. Contains instrument endpoints and serials; not for publication.",
        "bench_profile": {"path": str(bench_path), "sha256": _sha(bench_path), "bench_id": bench.bench_id,
                          "mode": bench.mode, "protective_controls_approved": bench.protective_controls.approved,
                          "policy_id": bench.protective_controls.policy_id},
        "inventory": {"path": str(inventory_path), "sha256": _sha(inventory_path),
                      "devices": {role: {"name": DEVICE_NAMES[role], "driver": d.driver, "resource": d.resource,
                                         "expected_serial_configured": bool(d.expected_serial)}
                                  for role, d in devices.items()}},
        "read_only_policy": {"writes_permitted": False, "query_allowlist": sorted(READ_ONLY_QUERIES),
                             "never_issued": list(NEVER_ISSUED),
                             "error_queue": "not read and not drained: SYST:ERR? removes the entry it returns; "
                                            "only the *STB? error-available bit is reported",
                             "instrument_lock": "benchctl VisaTransport per-instrument flock; the doctor fails closed "
                                                "if an acquisition owns an instrument"},
        "instruments": {}, "findings": findings, "transcript": [], "cadence": None,
        "software": _provenance(), "exit_code": 0}
    transcript = diagnosis["transcript"]
    from benchctl.registry import get_driver_class
    from benchctl.transport import VisaTransport
    raw_transports, readonly = {}, {}
    refusal: DoctorRefusal | None = None
    try:
        for role, device in devices.items():
            transport = VisaTransport(role, device.resource, timeout_ms=1500, log_path=folder / f"doctor-{stamp}.scpi.jsonl")
            try:
                transport.open()
            except Exception as exc:  # noqa: BLE001 - one unreachable instrument must not hide the other
                diagnosis["instruments"][role] = {"connection": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}}
                findings.append({"role": role, "severity": "blocking", "field": "connection",
                                 "message": f"{role} connection failed: {type(exc).__name__}: {exc}"})
                continue
            raw_transports[role] = transport
            readonly[role] = ReadOnlyTransport(role, transport, transcript, clock=time)
            driver = get_driver_class(device.driver)(readonly[role])
            read = _Reader(role, findings)
            report = (_diagnose_source if role == "source" else _diagnose_load)(read, driver, readonly[role], findings, bench)
            report["connection"] = {"status": "open"}
            report["identity_checks"] = _identity_checks(role, report.get("identity"), device, getattr(bench, role), findings)
            report["unreadable"] = {k: v for k, v in read.values.items() if isinstance(v, dict) and v.get("status") == "unreadable"}
            diagnosis["instruments"][role] = report
        if cadence:
            source, load = diagnosis["instruments"].get("source", {}), diagnosis["instruments"].get("load", {})
            states = {"source_CH1": source.get("output_on", {}).get("CH1"), "source_CH2": source.get("output_on", {}).get("CH2"),
                      "load_input": load.get("input_on")}
            if any(state is not True and state is not False for state in states.values()) or any(states.values()):
                diagnosis["cadence"] = {"status": "refused", "scope": CADENCE_SCOPE,
                                        "reason": "outputs were not verified OFF by readback; the doctor never turns anything off",
                                        "verified_states": states}
                diagnosis["exit_code"] = 2
            else:
                diagnosis["cadence"] = _cadence(readonly, seconds, poll_interval, time)
                diagnosis["cadence"]["verified_states"] = states
    except DoctorRefusal as exc:
        # What was read before the refusal is evidence too: keep it, then exit non-zero.
        refusal = exc
    finally:
        errors = []
        for role, transport in raw_transports.items():
            try:
                transport.close()
            except Exception as exc:  # noqa: BLE001 - one failed close must not skip the other
                errors.append(f"{role} close: {type(exc).__name__}: {exc}")
        diagnosis["close_errors"] = errors
    if refusal is not None:
        diagnosis["refusal"] = f"{type(refusal).__name__}: {refusal}"
        findings.append({"role": "doctor", "severity": "blocking", "field": "refusal",
                         "message": f"diagnosis stopped early: {refusal}"})
        diagnosis["exit_code"] = 2
    elif diagnosis["exit_code"] == 0 and findings:
        diagnosis["exit_code"] = 4
    diagnosis["summary"] = {"findings": len(findings), "blocking": sum(f["severity"] == "blocking" for f in findings),
                            "queries": len(transcript), "writes": 0}
    atomic_json(target, diagnosis)
    if refusal is not None:
        raise DoctorRefusal(f"{refusal}; partial diagnosis saved to {target}") from refusal
    return target, diagnosis
