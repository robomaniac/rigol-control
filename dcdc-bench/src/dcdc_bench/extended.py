"""Explicitly armed, fixed 24 V characterization of the connected 12T12-4A.

This supervised extension is separate from the general real backend. The
source's independent one-shot delayer bounds energization if the host dies.
No CLI option can widen electrical limits, duration, or the requested grid.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import signal
import time
from types import SimpleNamespace
import uuid

from .bringup import BringupAbort, RecordingTransport, RigolPilot
from .domain import RawSample, TestDefinition
from .planning import _hash_payload, build_plan
from .services import default_plan
from .storage import RunStore, atomic_json

VIN, ILIMIT, SOURCE_OVP, SOURCE_OCP = 24., .45, 26., .50
VOUT_MIN, VOUT_MAX, IOUT_MAX = 10.8, 13.2, .60
INITIAL_IOUT, PEAK_IOUT = .05, .50
SOFTWARE_DEADLINE_S, HARDWARE_DEADLINE_S = 660, 720
ACQUISITION_S, HOLD_BINS = 10., 18
POLICY_ID = "supervised-24V-450mA-500mA-720s-v1"


class ExtendedAbort(BringupAbort):
    pass


def _number(response: str, wanted: float, description: str, tolerance: float = .001):
    try:
        actual = float(response)
    except (TypeError, ValueError):
        raise ExtendedAbort(f"{description}: malformed readback {response!r}") from None
    if not math.isclose(actual, wanted, rel_tol=0., abs_tol=tolerance):
        raise ExtendedAbort(f"{description}: expected {wanted:g}, read {response!r}")


def _delay_parameter(response: str) -> tuple[int, str, int]:
    """Parse one SCPI definite-length block; reject extra/missing groups."""
    text = response.strip()
    if not text.startswith("#") or len(text) < 3 or not text[1].isdigit() or text[1] == "0":
        raise ExtendedAbort("Delayer parameter readback is not a definite-length block")
    digits = int(text[1])
    length = text[2:2 + digits]
    if len(length) != digits or not length.isdigit():
        raise ExtendedAbort("Malformed delayer parameter block length")
    payload = text[2 + digits:]
    if len(payload) != int(length):
        raise ExtendedAbort("Delayer parameter block length mismatch")
    fields = payload.rstrip(";").split(",")
    if len(fields) != 3:
        raise ExtendedAbort("Delayer must contain exactly one verified group")
    try:
        group, state, duration = int(fields[0]), fields[1].strip().upper(), int(fields[2])
    except ValueError:
        raise ExtendedAbort("Malformed delayer group") from None
    return group, state, duration


class ExtendedRigol(RigolPilot):
    """Reuse read/status operations; every changed protection is explicit here."""

    voltage = VIN
    current_limit = ILIMIT
    source_ovp = SOURCE_OVP
    source_ocp = SOURCE_OCP
    output_voltage_limit = VOUT_MAX
    output_current_limit = IOUT_MAX
    initial_current = INITIAL_IOUT

    def _write_source(self, command):
        self.st.write(command)
        self.supply.check_errors()

    def _write_load(self, command):
        self.lt.write(command)
        self.load.check_errors()

    def configure(self):
        if self.supply.get_output_enabled(1) or self.load.get_input_enabled():
            raise ExtendedAbort("Both outputs must be verified OFF before configuration")
        if self.lt.query(":SOUR:SENS?").strip().upper() not in ("0", "OFF"):
            raise ExtendedAbort("Local load sensing is required; remote sense wiring is unconfirmed")
        self._write_source(":INST:NSEL 1")
        _number(self.st.query(":INST:NSEL?"), 1., "Selected source channel", 0.)
        for command in (":TIMER?", ":DELAY?"):
            if self.st.query(command).strip().upper() != "OFF":
                raise ExtendedAbort("An existing source timer/delayer is active; no test was enabled")
        for command in (f":OUTP:OVP:VAL CH1,{self.source_ovp}", ":OUTP:OVP CH1,ON",
                        f":OUTP:OCP:VAL CH1,{self.source_ocp}", ":OUTP:OCP CH1,ON"):
            self._write_source(command)
        for kind, wanted in (("OVP", self.source_ovp), ("OCP", self.source_ocp)):
            _number(self.st.query(f":OUTP:{kind}:VAL? CH1"), wanted, f"Source {kind}")
            if (self.st.query(f":OUTP:{kind}? CH1").strip().upper() not in ("ON", "1")
                    or self.st.query(f":OUTP:{kind}:QUES? CH1").strip().upper() != "NO"):
                raise ExtendedAbort(f"Source {kind} protection is disabled or tripped")
        self.supply.set_voltage(1, self.voltage)
        self.supply.set_current_limit(1, self.current_limit)
        # Driver tolerances cover multiple models. This fixed pilot requires
        # the narrower readback agreement supported by this particular bench.
        _number(self.supply.get_voltage_setpoint(1), self.voltage, "Voltage request")
        _number(self.supply.get_current_limit(1), self.current_limit, "Current limit", .0005)
        self.load.set_mode("cc")
        # Lower retained request before tightening CC limits, while input OFF.
        self.load.set_current(self.initial_current)
        for command in (":SOUR:CURR:RANG MIN", ":SOUR:CURR:SLEW:BOTH MIN",
                        f":SOUR:CURR:VLIM {self.output_voltage_limit}", f":SOUR:CURR:ILIM {self.output_current_limit}"):
            self._write_load(command)
        for command, wanted in ((":SOUR:CURR:VLIM?", self.output_voltage_limit), (":SOUR:CURR:ILIM?", self.output_current_limit)):
            _number(self.lt.query(command), wanted, "Load CC limit")
        self._write_source(":SYST:OTP ON")
        if self.st.query(":SYST:OTP?").strip().upper() not in ("1", "ON"):
            raise ExtendedAbort("Source thermal protection is not enabled")
        # Configuration alone never enables output. Only start() does that.
        for command in (":DELAY:GROUPS 1", ":DELAY:CYCLES N,1", ":DELAY:ENDSTATE OFF",
                        ":DELAY:STOP NONE", f":DELAY:PARAMETER 0,ON,{HARDWARE_DEADLINE_S}"):
            self._write_source(command)
        self.verify_deadline_configuration()
        if self.supply.get_output_enabled(1) or self.load.get_input_enabled():
            raise ExtendedAbort("An output changed state during configuration")

    def verify_deadline_configuration(self):
        _number(self.st.query(":INST:NSEL?"), 1., "Selected source channel", 0.)
        _number(self.st.query(":DELAY:GROUPS?"), 1., "Delayer group count", 0.)
        cycles = self.st.query(":DELAY:CYCLES?").strip().upper().replace(" ", "")
        if cycles != "N,1":
            raise ExtendedAbort(f"Delayer is not a single cycle: {cycles!r}")
        if self.st.query(":DELAY:ENDSTATE?").strip().upper() != "OFF":
            raise ExtendedAbort("Delayer must finish with output OFF")
        stop = self.st.query(":DELAY:STOP?").strip().upper()
        if stop != "NONE":
            raise ExtendedAbort(f"Unexpected delayer stop condition: {stop!r}")
        if _delay_parameter(self.st.query(":DELAY:PARAMETER? 0,1")) != (0, "ON", HARDWARE_DEADLINE_S):
            raise ExtendedAbort("Delayer ON duration does not match the fixed hardware deadline")

    def start(self):
        if self.supply.get_output_enabled(1) or self.load.get_input_enabled():
            raise ExtendedAbort("Both outputs must remain OFF immediately before start")
        self.verify_deadline_configuration()
        if self.st.query(":TIMER?").strip().upper() != "OFF" or self.st.query(":DELAY?").strip().upper() != "OFF":
            raise ExtendedAbort("Unexpected timer state before start")
        self._write_source(":DELAY ON")
        if self.st.query(":DELAY?").strip().upper() != "ON" or not self.supply.get_output_enabled(1):
            raise ExtendedAbort("Independent deadline did not start with source output ON")

    def verify_running(self, loaded):
        if not self.supply.get_output_enabled(1) or self.st.query(":DELAY?").strip().upper() != "ON":
            raise ExtendedAbort("Source output or independent deadline is no longer active")
        if self.load.get_mode() != "cc":
            raise ExtendedAbort("Load mode changed during acquisition")
        return self.mode(), self.load_status(loaded)


def extended_plan():
    base = default_plan()
    dut, bench, recipe = (item.model_copy(deep=True) for item in (base.dut, base.bench, base.recipe))
    dut.execution_approval.real_hardware_enabled = True
    dut.execution_approval.wiring_and_polarity_confirmed = True
    dut.execution_approval.protective_policy_id = POLICY_ID
    bench.mode, bench.bench_id = "real", "rigol-supervised-extended"
    bench.source.instrument_id, bench.load.instrument_id = "source", "load"
    bench.source.adapter, bench.load.adapter = "benchctl_rigol_dp800", "benchctl_rigol_dl3000"
    bench.source.reported_identity = bench.load.reported_identity = None
    bench.source.max_current_A = ILIMIT
    bench.load.max_voltage_V, bench.load.max_current_A, bench.load.max_power_W = 15., IOUT_MAX, 8.
    bench.load.remote_sense_required = False
    bench.measurement_boundary = "source-to-load-terminal path (input and output wiring included)"
    for name, binding in bench.measurements.items():
        binding.instrument_id = "source" if name in ("Vin_V", "Iin_A") else "load"
        if name == "Vout_V": binding.location = "load_input_terminals_local_sense"
        if name == "Iout_A": binding.location = "load_input"
    controls = bench.protective_controls
    controls.policy_id, controls.approved = POLICY_ID, True
    controls.source_current_limit_A, controls.dut_input_overvoltage_V = ILIMIT, SOURCE_OVP
    controls.dut_output_overvoltage_V, controls.output_overcurrent_A = VOUT_MAX, IOUT_MAX
    bench.notes = [
        "User explicitly authorized a longer test after the successful 24 V / 100 mA pilot; CH1 wiring and polarity were confirmed in this session.",
        "Purpose-limited 24 V / 500 mA test; physical DUT/load ratings remain unverified.",
        "Source hardware delayer must be verified as one ON group of 720 s, one cycle, end OFF; software deadline 660 s.",
        "Local load sensing. ADC freshness, calibration, and readback uncertainty are not independently verified.",
        "10.8–13.2 V and 0.60 A are conservative stop criteria, not manufacturer acceptance limits.",
        "180 s minimum sustained-load observation is not a temperature measurement or thermal qualification."]
    recipe.recipe_id, recipe.execution_mode = "12t12-24v-extended", "real"
    recipe.tests = [
        TestDefinition(id="increasing-load", input_voltage_targets_V=[VIN], output_current_targets_A=[n / 100 for n in range(5, 51, 5)]),
        TestDefinition(id="sustained-load", input_voltage_targets_V=[VIN], output_current_targets_A=[PEAK_IOUT] * HOLD_BINS),
        TestDefinition(id="decreasing-load", input_voltage_targets_V=[VIN], output_current_targets_A=[n / 100 for n in range(45, 4, -5)])]
    recipe.planning.efficiency_estimate_fraction = .65
    recipe.settling.minimum_dwell_s, recipe.settling.window_s = 5., 4.
    recipe.settling.minimum_fresh_samples, recipe.settling.maximum_vout_span_V = 5, .05
    recipe.acquisition.duration_s, recipe.acquisition.target_poll_interval_s = ACQUISITION_S, 1.
    recipe.acquisition.minimum_complete_cycles, recipe.acquisition.maximum_interchannel_skew_s = 5, .75
    recipe.authorization.protective_policy_id = POLICY_ID
    plan = build_plan(dut, bench, recipe)
    for point in plan.points:
        if point.status != "approval_blocked":
            raise ExtendedAbort(f"Fixed test violates capability planning: {point.reason}")
        point.status = "executable"
        point.reason = "Explicit operator authorization; fixed supervised extended test with independent source deadline"
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan


def _guard(values, requested, *, startup=False, loaded=True):
    if any(not math.isfinite(value) for value in values.values()):
        raise ExtendedAbort("Nonfinite measurement")
    if not 23.5 <= values["Vin_V"] <= 24.5 or not -.005 <= values["Iin_A"] <= ILIMIT:
        raise ExtendedAbort(f"Input guard failed: {values}")
    minimum = -.05 if startup else VOUT_MIN
    if not minimum <= values["Vout_V"] <= VOUT_MAX or not -.02 <= values["Iout_A"] <= IOUT_MAX:
        raise ExtendedAbort(f"Output guard failed: {values}")
    if loaded and not startup and abs(values["Iout_A"] - requested) > .02:
        raise ExtendedAbort(f"Requested load current not established: requested {requested:g} A; {values}")


def _run_fixed(config_path: Path, out: Path, *, arm: bool = False, procedure=None) -> Path:
    """Serialize every fixed acquisition with report rendering on this bench."""
    if not arm:
        raise ExtendedAbort("Explicit --arm is required; this command operates real equipment")
    from .activity import bench_activity
    with bench_activity("acquisition", timeout=0):
        return _run_fixed_unlocked(config_path, out, arm=arm, procedure=procedure)


def _run_fixed_unlocked(config_path: Path, out: Path, *, arm: bool = False, procedure=None) -> Path:
    """Shared lifecycle for explicitly coded fixed procedures; no recipe executor."""
    if not arm:
        raise ExtendedAbort("Explicit --arm is required; this command operates real equipment")
    from benchctl.config import load_config
    from benchctl.identity import identify_and_verify
    from benchctl.registry import get_driver_class
    from benchctl.transport import VisaTransport
    from .runner import _provenance
    plan = extended_plan() if procedure is None else procedure.plan()
    adapter = ExtendedRigol if procedure is None else procedure.adapter
    from .planning import missing_approvals
    missing = missing_approvals(plan.dut, plan.bench)
    if missing:
        raise ExtendedAbort("Saved-profile approvals are missing; no instrument was opened: " + "; ".join(missing))
    config = load_config(config_path)
    devices = {role: config.devices[name] for role, name in (("source", "psu_rigol_1"), ("load", "load_rigol_1"))}
    if any(not device.expected_serial for device in devices.values()):
        raise ExtendedAbort("Both configured instrument serials are required")
    if devices["source"].driver != "rigol_dp800" or devices["load"].driver != "rigol_dl3000":
        raise ExtendedAbort("Only the verified DP800 / DL3000 driver pair is supported")
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "_real_" + uuid.uuid4().hex[:6]
    directory, began = Path(out) / run_id, time.monotonic()
    store = RunStore(directory)
    run = {"schema_version": "1.0", "run_id": run_id, "data_source": "measured", "execution_status": "running",
        "lifecycle_state": "PREFLIGHT", "created_utc": now.isoformat(), "scenario": "supervised extended real characterization",
        "plan_hash": plan.plan_hash, "measurement_boundary": plan.bench.measurement_boundary, "real_hardware_opened": True,
        "software": _provenance(), "clock": {"mode": "wall"}, "errors": [],
        "authorization": "User explicitly requested longer testing of the connected DUT after the successful real pilot; CH1 and polarity confirmed in session",
        "method": {"source_current_limit_A": ILIMIT, "source_OVP_V": SOURCE_OVP, "source_OCP_A": SOURCE_OCP,
            "hardware_deadline_s": HARDWARE_DEADLINE_S, "software_deadline_s": SOFTWARE_DEADLINE_S,
            "sustained_load_minimum_s": HOLD_BINS * ACQUISITION_S, "sustained_load_bin_target_s": ACQUISITION_S,
            "hold_settling": "Continuous 500 mA hold inherits the preceding settled condition; each bin checks voltage span",
            "deadline_manual": "Rigol DP800 Programming Guide, DELAY commands, sections 2-12 through 2-16"},
        "metrology_limitations": ["Source/load-terminal boundary includes input and output wiring losses.",
            "ADC freshness, calibration, and readback uncertainty are unquantified; no temperature sensor is present.",
            "No-load power, ripple, transients, full rated power, and line regulation are not evaluated."],
        "points": [{**p.model_dump(), "qualification": "not-run", "acquisition_cycle_ids": []} for p in plan.points],
        "shutdown": {"source": {"state": "UNKNOWN"}, "load": {"state": "UNKNOWN"}, "source_deadline": {"state": "UNKNOWN"}}}
    if procedure is not None:
        run.update(procedure.metadata())
    store.initialize({"dut": plan.dut.model_dump(), "bench": plan.bench.model_dump(), "recipe": plan.recipe.model_dump(),
                      "authorization": run["authorization"]}, plan.model_dump(), run)
    transports, drivers, recorders, identities = {}, {}, {}, set()
    active, counter, pilot = None, 0, None
    held_from = held_until = None

    def event(name, **values):
        store.append("events", {"event": name, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                "monotonic_s": time.monotonic() - began, **values})

    def interrupted(signum, frame):
        name = signal.Signals(signum).name
        raise ExtendedAbort(f"{name}: test interrupted" if signum != signal.SIGALRM else "660 second software deadline reached")

    signals = (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    previous = {number: signal.signal(number, interrupted) for number in signals}
    signal.alarm(SOFTWARE_DEADLINE_S)
    try:
        for role, device in devices.items():
            transport = VisaTransport(role, device.resource, timeout_ms=1500, log_path=directory / "scpi.jsonl")
            transports[role] = transport
            transport.open()  # Existing driver transport obtains per-resource process lock.
            recorders[role] = RecordingTransport(transport)
            driver = get_driver_class(device.driver)(recorders[role])
            drivers[role] = driver
            identity = identify_and_verify(role, device, driver)
            identities.add(role)
            run.setdefault("instrument_identities", {})[role] = asdict(identity)
            event("identity_verified", role=role, identity=asdict(identity))
        supply, load = drivers["source"], drivers["load"]
        load.input_off()
        supply.output_off(1)
        off_source, off_load = supply.measure_voltage(1), load.measure_voltage()
        event("outputs_off_readbacks", source_V=off_source, load_V=off_load,
              note="Residual load voltage is retained as an off-state observation, not a no-load result")
        if not math.isfinite(off_source) or abs(off_source) > .5 or not -.05 <= off_load <= adapter.output_voltage_limit:
            raise ExtendedAbort("Unexpected external/residual voltage while outputs are OFF")
        pilot = adapter(supply, load, transports["source"], transports["load"])
        pilot.configure()
        event("protection_verified", source_current_limit_A=pilot.current_limit, source_OVP_V=pilot.source_ovp,
              source_OCP_A=pilot.source_ocp, output_guard_V=[getattr(procedure, "lower_output", VOUT_MIN), pilot.output_voltage_limit], output_guard_A=pilot.output_current_limit,
              hardware_deadline_s=HARDWARE_DEADLINE_S)
        atomic_json(directory / "run.json", run)

        def cycle(point, phase, *, loaded=True, startup=False):
            nonlocal counter
            counter += 1
            cycle_id = f"c{counter:06d}"
            mode, condition = pilot.verify_running(loaded)
            rows = []
            try:
                # Keep SD-card fsync latency outside the four-query span.
                # Nothing is accepted until every captured row is durable.
                for quantity in ("Vin_V", "Iin_A", "Vout_V", "Iout_A"):
                    binding = plan.bench.measurements[quantity]
                    start_utc, start = datetime.now(timezone.utc).isoformat(), time.monotonic() - began
                    value = pilot.read(quantity)
                    end, end_utc = time.monotonic() - began, datetime.now(timezone.utc).isoformat()
                    rows.append(RawSample(sample_id=f"{cycle_id}-{quantity}", run_id=run_id, test_id=point["test_id"],
                        point_id=point["point_id"], channel_id="CH1" if binding.instrument_id == "source" else "INPUT",
                        instrument_id=binding.instrument_id, quantity=quantity, value=value, unit=binding.unit,
                        location=binding.location, query_start_utc=start_utc, query_end_utc=end_utc,
                        query_start_monotonic_s=start, query_end_monotonic_s=end,
                        raw_response=recorders[binding.instrument_id].last_response,
                        acquisition_cycle_id=cycle_id, phase=phase, acquisition_settings={
                            **({"procedure_stage": procedure.stage} if procedure is not None else {}),
                            "source_mode": mode, "load_compliance": True, "load_enabled": loaded,
                            "load_condition_register": condition, "load_sense": "local", "requested_load_A": point["iout_target_A"],
                            "adc_freshness": "not independently verified", "raw_SCPI_response_file": "scpi.jsonl"}))
            finally:
                # A later query or interruption may leave an incomplete cycle.
                # Preserve its earlier responses without qualifying that cycle.
                for row in rows:
                    store.append("samples", row.model_dump())
            values = {row.quantity: row.value for row in rows}
            skew = rows[-1].query_end_monotonic_s - rows[0].query_start_monotonic_s
            if skew > plan.recipe.acquisition.maximum_interchannel_skew_s:
                raise ExtendedAbort(f"Interchannel query span {skew:.3f} s exceeds 0.75 s")
            mode_after, _ = pilot.verify_running(loaded)
            if procedure is None:
                _guard(values, point["iout_target_A"], loaded=loaded, startup=startup)
            else:
                procedure.guard(values, point["iout_target_A"], loaded=loaded, startup=startup,
                                mode_before=mode, mode_after=mode_after)
            return cycle_id, values, skew

        initial_point = getattr(procedure, "initial_point", None)
        active = initial_point(run) if callable(initial_point) else run["points"][0]
        if procedure is not None:
            procedure.record_attempt(run, active)
            atomic_json(directory / "run.json", run)
        print(f"Verified protections and independent 720 s deadline; starting CH1 at {pilot.voltage:g} V / {pilot.current_limit:g} A", flush=True)
        pilot.start()
        event("source_enabled_with_deadline")
        run["lifecycle_state"] = "RUNNING"
        if procedure is not None:
            def set_active(point):
                nonlocal active
                active = point
            context = SimpleNamespace(plan=plan, run=run, directory=directory, began=began,
                pilot=pilot, load=load, cycle=cycle, event=event, store=store,
                set_active=set_active, clock=time)
        startup = getattr(procedure, "startup", None)
        if startup is not None:
            startup(context)
        else:
            # Existing fixed procedures retain their original startup sequence.
            # Load-off startup samples never qualify as no-load measurements.
            for _ in range(5):
                time.sleep(1)
                cycle(active, "starting", loaded=False, startup=True)
            load.input_on()
            for _ in range(5):
                time.sleep(1)
                cycle(active, "starting", startup=True)
        if procedure is not None:
            procedure.execute(context)
            active = None
        else:
            previous_request = INITIAL_IOUT
            for point in run["points"]:
                active = point
                target = point["iout_target_A"]
                if target != previous_request:
                    load.set_current(target)
                    event("load_request_changed", point_id=point["point_id"], requested_load_A=target)
                    previous_request = target
                settling_started = time.monotonic()
                if point["test_id"] != "sustained-load":
                    observed = []
                    for _ in range(5):
                        time.sleep(1)
                        _, values, _ = cycle(point, "settling")
                        observed.append(values["Vout_V"])
                    if max(observed) - min(observed) > .05:
                        raise ExtendedAbort("Output did not settle within a 50 mV span")
                settling_elapsed = time.monotonic() - settling_started
                acquisition_started, accepted, voltages, maximum_skew = time.monotonic(), [], [], 0.
                if point["test_id"] == "sustained-load" and held_from is None:
                    held_from = acquisition_started
                while time.monotonic() - acquisition_started < ACQUISITION_S or len(accepted) < 5:
                    cycle_id, values, skew = cycle(point, "acquiring")
                    accepted.append(cycle_id)
                    voltages.append(values["Vout_V"])
                    maximum_skew = max(maximum_skew, skew)
                    # Keep observation spacing at least one second after the prior
                    # cycle. This is polling cadence, not an ADC freshness claim.
                    time.sleep(1)
                ended = time.monotonic()
                if max(voltages) - min(voltages) > .05:
                    raise ExtendedAbort("Voltage span exceeded 50 mV during acquisition")
                if point["test_id"] == "sustained-load":
                    held_until = ended
                    run["method"]["sustained_load_actual_elapsed_s"] = held_until - held_from
                    run["method"]["sustained_load_completed_bins"] = sum(
                        p["test_id"] == "sustained-load" and p["qualification"] == "valid" for p in run["points"]) + 1
                point.update(qualification="valid", reason="Stable guarded DC readbacks; uncertainty and ADC independence unquantified",
                    acquisition_cycle_ids=accepted, settled=True, settling_elapsed_s=settling_elapsed,
                    acquisition_elapsed_s=ended - acquisition_started,
                    acquisition_start_monotonic_s=acquisition_started - began, acquisition_end_monotonic_s=ended - began,
                    maximum_interchannel_skew_s=maximum_skew,
                    settling_inherited_from_previous_point=point["test_id"] == "sustained-load")
                store.append("points", {**point, "event": "point_finalized", "monotonic_s": ended - began})
                atomic_json(directory / "run.json", run)
                print(json.dumps({"point": point["point_id"], "stage": point["test_id"], "load_A": target,
                                  "accepted_cycles": len(accepted), **values}), flush=True)
                active = None
            run["method"]["sustained_load_actual_elapsed_s"] = held_until - held_from
        run["execution_status"] = "completed"
    except BaseException as exc:
        run["execution_status"] = "aborted" if isinstance(exc, (BringupAbort, KeyboardInterrupt)) else "error"
        run["errors"].append(f"{type(exc).__name__}: {exc}")
        if active is not None:
            if held_from is not None and active["test_id"] == "sustained-load":
                run["method"]["sustained_load_actual_elapsed_s"] = time.monotonic() - held_from
            active.update(qualification="inconclusive", reason=run["errors"][-1], acquisition_cycle_ids=[])
        print("Stopped: " + run["errors"][-1], flush=True)
    finally:
        signal.alarm(0)
        # Prevent a second termination signal from interrupting independent
        # best-effort shutdown. Instrument timeout still bounds each call.
        for number in signals:
            signal.signal(number, signal.SIG_IGN)
        load, supply = drivers.get("load"), drivers.get("source")
        if "source" in identities:
            st = transports["source"]
            source_off = False
            try:
                supply.output_off(1)
                enabled = supply.get_output_enabled(1)
                source_off = not enabled
                run["shutdown"]["source"] = {"state": "ON" if enabled else "OFF", "verified": not enabled}
            except BaseException as exc:
                run["errors"].append(f"source shutdown: {exc}")
            if source_off:
                # Do not remove the independent fallback until explicit OFF
                # succeeds. This one-group program has no later ON edges.
                try:
                    st.write(":INST:NSEL 1")
                    supply.check_errors()
                    _number(st.query(":INST:NSEL?"), 1., "Shutdown source channel", 0.)
                    st.write(":DELAY OFF")
                    supply.check_errors()
                    if st.query(":DELAY?").strip().upper() != "OFF":
                        raise ExtendedAbort("Source delayer is still active")
                    run["shutdown"]["source_deadline"] = {"state": "OFF", "verified": True}
                    supply.output_off(1)
                    if supply.get_output_enabled(1):
                        raise ExtendedAbort("Source output is not OFF after cancelling the delayer")
                except BaseException as exc:
                    run["errors"].append(f"source deadline shutdown: {exc}")
                    run["shutdown"]["source"] = {"state": "UNKNOWN", "verified": False,
                        "reason": "Final source state after timer cancellation could not be verified"}
            else:
                run["shutdown"]["source_deadline"] = {"state": "UNKNOWN", "verified": False,
                    "reason": "Left uncancelled because explicit source OFF was not verified"}
        # A source shutdown failure must not prevent the load shutdown attempt.
        if "load" in identities:
            try:
                load.input_off()
                enabled = load.get_input_enabled()
                run["shutdown"]["load"] = {"state": "ON" if enabled else "OFF", "verified": not enabled}
            except BaseException as exc:
                run["errors"].append(f"load shutdown: {exc}")
        for role, transport in transports.items():
            try:
                transport.close()
            except BaseException as exc:
                run["errors"].append(f"{role} close: {exc}")
        for number, handler in previous.items():
            signal.signal(number, handler)
        safe = all(item.get("state") == "OFF" and item.get("verified") is True for item in run["shutdown"].values())
        if not safe:
            run["errors"].append("Shutdown state is not fully verified OFF; independent source deadline may still be active")
            run["execution_status"] = "error"
        run.update(lifecycle_state="FINALIZED", finished_utc=datetime.now(timezone.utc).isoformat(),
                   duration_s=time.monotonic() - began)
        event("shutdown", states=run["shutdown"])
        store.finalize(run)
    print(json.dumps({"run": str(directory), "execution": run["execution_status"], "shutdown": run["shutdown"]}), flush=True)
    return directory


def run_extended(config_path: Path, out: Path, *, arm: bool = False) -> Path:
    return _run_fixed(config_path, out, arm=arm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("runs/real-extended"))
    parser.add_argument("--arm", action="store_true")
    args = parser.parse_args()
    path = run_extended(args.config, args.out, arm=args.arm)
    run = json.loads((path / "run.json").read_text())
    return 0 if run["execution_status"] == "completed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
