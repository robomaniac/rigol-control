"""Explicitly armed, fixed one- or two-point pilot using the benchctl drivers.

This is a supervised bring-up procedure, not the general M2 sweep backend.
No import or planning operation opens hardware. SCPI extensions below are
documented DP800/DL3000 protection/status commands; ordinary control reuses
the owner's drivers. No clear/reset command can implicitly re-enable output.
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
import uuid

from .domain import BenchProfile, Plan, RawSample, unknown_readback_specification
from .planning import _hash_payload, build_plan
from .services import default_plan
from .storage import RunStore, atomic_json

VIN = 24.0
ILIMIT = 0.15
VOUT_MIN, VOUT_MAX = 10.8, 13.2
SOURCE_OVP, SOURCE_OCP = 26.0, .18
IOUT = .1
POLICY_ID = "supervised-24V-150mA-100mA-v2"


class BringupAbort(RuntimeError):
    pass


class RecordingTransport:
    """Retain the exact raw query text while delegating to the existing transport."""
    def __init__(self, transport):
        self.transport = transport
        self.last_response = None

    def query(self, command):
        self.last_response = self.transport.query(command)
        return self.last_response

    def write(self, command):
        return self.transport.write(command)

    def close(self):
        return self.transport.close()


class RigolPilot:
    """Thin driver adapter plus the verified protection/status extensions.

    Every protection-setting SCPI sequence lives here once; the fixed
    procedures only supply values. Subclasses set `abort` to their own error.
    """
    abort = BringupAbort

    def __init__(self, supply, load, supply_transport, load_transport, *, bench: BenchProfile | None = None):
        self.supply, self.load = supply, load
        self.st, self.lt = supply_transport, load_transport
        self.bench = bench

    # -- SourceAdapter / LoadAdapter contract (domain.py section 5.2) --------

    def identify(self):
        def describe(identity):
            return asdict(identity) if hasattr(identity, "__dataclass_fields__") else dict(vars(identity))
        return {"source": describe(self.supply.identify()), "load": describe(self.load.identify())}

    def _capabilities(self, role):
        if self.bench is None:
            raise self.abort("No bench profile is bound to this adapter; capabilities are unknown")
        return getattr(self.bench, role)

    def source_capabilities(self):
        return self._capabilities("source")

    def load_capabilities(self):
        return self._capabilities("load")

    def configure(self, vin=None, iout=None, now=None):
        """Program protections and setpoints while both outputs are OFF."""
        self.configure_protections()

    def source_on(self):
        self.require_outputs_off("immediately before enabling the source")
        self.supply.output_on(1)

    def source_off(self):
        self.supply.output_off(1)

    def load_on(self):
        if not self.supply.get_output_enabled(1):
            raise self.abort("Load input stays OFF until the source output is verified ON")
        self.load.input_on()

    def load_off(self):
        self.load.input_off()

    def status(self):
        return {"source_output_on": self.supply.get_output_enabled(1),
                "load_input_on": self.load.get_input_enabled(),
                "source_mode": self.st.query(":OUTP:CVCC? CH1").strip(),
                "remote_sense_verified": False}

    def close(self):
        """Release both transports independently; never touches output state."""
        first = None
        for transport in (self.st, self.lt):
            try:
                transport.close()
            except Exception as exc:  # noqa: BLE001 - one failed close must not skip the other
                first = first or exc
        if first is not None:
            raise first

    def _write_source(self, command):
        self.st.write(command)
        self.supply.check_errors()

    def _write_load(self, command):
        self.lt.write(command)
        self.load.check_errors()

    def _readback(self, transport, query, wanted, description, tolerance=.001):
        response = transport.query(query)
        try:
            actual = float(response)
        except (TypeError, ValueError):
            raise self.abort(f"{description}: malformed readback {response!r}") from None
        if not math.isclose(actual, wanted, rel_tol=0., abs_tol=tolerance):
            raise self.abort(f"{description}: expected {wanted:g}, read {response!r}")

    def require_outputs_off(self, context="before configuration"):
        if self.supply.get_output_enabled(1) or self.load.get_input_enabled():
            raise self.abort(f"Both outputs must be verified OFF {context}")

    def require_local_sense(self):
        if self.lt.query(":SOUR:SENS?").strip().upper() not in ("0", "OFF"):
            raise self.abort("Local load sensing is required; this pilot requires local load sensing "
                             "and separate sense wiring has not been confirmed")

    def apply_source_protections(self, ovp_V, ocp_A):
        """Program and verify CH1 OVP/OCP; never touches output state."""
        for command in (f":OUTP:OVP:VAL CH1,{ovp_V}", ":OUTP:OVP CH1,ON",
                        f":OUTP:OCP:VAL CH1,{ocp_A}", ":OUTP:OCP CH1,ON"):
            self._write_source(command)
        for kind, wanted in (("OVP", ovp_V), ("OCP", ocp_A)):
            self._readback(self.st, f":OUTP:{kind}:VAL? CH1", wanted, f"Source {kind} protection verification failed")
            enabled = self.st.query(f":OUTP:{kind}? CH1").strip().upper()
            alarm = self.st.query(f":OUTP:{kind}:QUES? CH1").strip().upper()
            if enabled not in ("ON", "1") or alarm != "NO":
                raise self.abort(f"Source {kind} protection verification failed: disabled or tripped")

    def apply_load_cc_limits(self, vlim_V, ilim_A):
        """Tighten CC range/slew and program verified voltage/current limits."""
        for command in (":SOUR:CURR:RANG MIN", ":SOUR:CURR:SLEW:BOTH MIN",
                        f":SOUR:CURR:VLIM {vlim_V}", f":SOUR:CURR:ILIM {ilim_A}"):
            self._write_load(command)
        for query, wanted in ((":SOUR:CURR:VLIM?", vlim_V), (":SOUR:CURR:ILIM?", ilim_A)):
            self._readback(self.lt, query, wanted, "Load CC limit readback verification failed")

    def enable_source_otp(self):
        self._write_source(":SYST:OTP ON")
        if self.st.query(":SYST:OTP?").strip().upper() not in ("1", "ON"):
            raise self.abort("Source thermal protection was not verified enabled")

    def configure_protections(self):
        self.require_outputs_off()
        self.require_local_sense()
        self.apply_source_protections(SOURCE_OVP, SOURCE_OCP)
        self.supply.set_voltage(1, VIN)
        self.supply.set_current_limit(1, ILIMIT)
        self.load.set_mode("cc")
        # The instrument rejects an upper current limit below its retained
        # setpoint, even while input is OFF. Lower the request first.
        self.load.set_current(IOUT)
        self.apply_load_cc_limits(VOUT_MAX, .15)
        self.enable_source_otp()

    def mode(self):
        mode = self.st.query(":OUTP:CVCC? CH1").strip()
        if mode != "CV":
            raise self.abort(f"Source mode {mode}; nominal input voltage is not established")
        return mode

    def load_status(self, enabled):
        raw = self.lt.query(":STAT:QUES:COND?").strip()
        status = int(raw, 0) if raw.lower().startswith("0x") else int(raw)
        # Documented VF, OC, OP, reverse voltage, unregulated, low reverse
        # voltage, overvoltage, shutdown. RUN/VON/RS are not fault bits.
        mask = 15883
        if status & mask:
            raise self.abort(f"Load questionable condition {status}; stopping rather than clearing it")
        if self.load.get_input_enabled() != enabled:
            raise self.abort("Load input state no longer matches the requested phase")
        return status

    def read(self, quantity, now=None):
        return {"Vin_V": lambda: self.supply.measure_voltage(1),
                "Iin_A": lambda: self.supply.measure_current(1),
                "Vout_V": self.load.measure_voltage,
                "Iout_A": self.load.measure_current}[quantity]()


def pilot_plan(*, loaded_only: bool = False):
    base = default_plan()
    dut, recipe = base.dut.model_copy(deep=True), base.recipe.model_copy(deep=True)
    dut.execution_approval.real_hardware_enabled = True
    dut.execution_approval.wiring_and_polarity_confirmed = True
    dut.execution_approval.protective_policy_id = POLICY_ID
    bench = base.bench.model_copy(deep=True)
    bench.mode = "real"
    bench.bench_id = "rigol-supervised-bringup"
    bench.source.instrument_id, bench.load.instrument_id = "source", "load"
    bench.source.adapter, bench.load.adapter = "benchctl_rigol_dp800", "benchctl_rigol_dl3000"
    bench.source.reported_identity = bench.load.reported_identity = None
    bench.source.max_current_A = ILIMIT
    # Purpose-limited envelope, not an inference of the load's certified physical rating.
    bench.load.max_voltage_V, bench.load.max_current_A, bench.load.max_power_W = 15., .2, 3.
    bench.load.remote_sense_required = False
    bench.measurement_boundary = "source-to-load-terminal path (input and output wiring included)"
    for name, binding in bench.measurements.items():
        binding.instrument_id = "source" if name in ("Vin_V", "Iin_A") else "load"
        if name == "Vout_V": binding.location = "load_input_terminals_local_sense"
        if name == "Iout_A": binding.location = "load_input"
        # A real bench never inherits the mock profile's synthetic readback terms.
        binding.readback_specification = unknown_readback_specification(name)
    bench.protective_controls.policy_id = POLICY_ID
    bench.protective_controls.source_current_limit_A = ILIMIT
    bench.protective_controls.dut_input_overvoltage_V = SOURCE_OVP
    bench.protective_controls.dut_output_overvoltage_V = VOUT_MAX
    bench.protective_controls.output_overcurrent_A = .15
    bench.protective_controls.approved = True
    bench.notes = ["Operator confirmed 12T12-4A connected to CH1 with correct polarity and explicitly authorized this bring-up.",
        "Local load sensing; no separate S+/S- wiring was confirmed.",
        "Load physical model/modification and full readback uncertainty remain unverified; purpose-limited envelope only.",
        "Output 10.8–13.2 V and current guards are conservative bring-up stop criteria, not manufacturer acceptance limits.",
        "Underlying ADC freshness and calibration are not independently verified; query timing is retained, polling interval >= 1 s."]
    recipe.recipe_id, recipe.execution_mode = "12t12-supervised-bringup", "real"
    recipe.tests[0].id = "bringup"
    recipe.tests[0].input_voltage_targets_V = [VIN]
    recipe.tests[0].output_current_targets_A = [IOUT] if loaded_only else [0., IOUT]
    recipe.settling.minimum_dwell_s = 5.
    recipe.settling.window_s = 4.
    recipe.settling.minimum_fresh_samples = 5
    recipe.acquisition.duration_s = 5.
    recipe.acquisition.target_poll_interval_s = 1.
    recipe.acquisition.minimum_complete_cycles = 5
    recipe.acquisition.maximum_interchannel_skew_s = .75
    recipe.authorization.protective_policy_id = POLICY_ID
    plan = build_plan(dut, bench, recipe)
    # Generic real plans remain blocked. Only this fixed, explicitly armed pilot
    # has a reviewed execution function; limits cannot be supplied by a recipe.
    for point in plan.points:
        if point.status != "approval_blocked":
            raise BringupAbort(f"Pilot point violates capability planning: {point.reason}")
        point.status = "executable"
        point.reason = "Explicit operator authorization; fixed supervised bring-up only"
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan


def run_bringup(config_path: Path, out: Path, *, arm: bool = False, loaded_only: bool = False) -> Path:
    """Single-owner bring-up: the bench lease fails closed if anything else is active."""
    if not arm:
        raise BringupAbort("Explicit --arm is required; this command operates real equipment")
    from .activity import bench_activity
    with bench_activity("acquisition", timeout=0):
        return _run_bringup_unlocked(config_path, out, loaded_only=loaded_only)


def _run_bringup_unlocked(config_path: Path, out: Path, *, loaded_only: bool = False) -> Path:
    from .planning import missing_approvals
    plan = pilot_plan(loaded_only=loaded_only)
    missing = missing_approvals(plan.dut, plan.bench)
    if missing:
        raise BringupAbort("Saved-profile approvals are missing; no instrument was opened: " + "; ".join(missing))
    from benchctl.config import load_config
    from benchctl.identity import identify_and_verify
    from benchctl.registry import get_driver_class
    from benchctl.transport import VisaTransport
    from .runner import _provenance
    config = load_config(config_path)
    devices = {role: config.devices[name] for role, name in
               (("source", "psu_rigol_1"), ("load", "load_rigol_1"))}
    if any(not d.expected_serial for d in devices.values()):
        raise BringupAbort("Both configured instrument serial numbers are required")
    if devices["source"].driver != "rigol_dp800" or devices["load"].driver != "rigol_dl3000":
        raise BringupAbort("Pilot supports the existing DP800 and DL3000 drivers only")
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S.%fZ") + "_real_" + uuid.uuid4().hex[:6]
    directory = Path(out) / run_id
    store = RunStore(directory)
    run = {"schema_version": "1.0", "run_id": run_id, "data_source": "measured",
        "execution_status": "running", "lifecycle_state": "PREFLIGHT", "created_utc": now.isoformat(),
        "scenario": "supervised real bring-up", "plan_hash": plan.plan_hash,
        "measurement_boundary": plan.bench.measurement_boundary, "real_hardware_opened": True,
        "software": _provenance(), "clock": {"mode": "wall"}, "errors": [],
        "authorization": "User explicitly confirmed DUT connection, CH1, polarity and requested immediate testing in this session",
        "operator_observations": ["User measured approximately 12 V with a multimeter at 24 V input, then observed 0.0993 A at 12.133 V with load enabled. These are operator observations, not automatically acquired samples."],
        "metrology_limitations": ["Local load-terminal voltage includes output lead losses; DUT output sense wiring was not confirmed.",
            "ADC freshness, calibration and current readback uncertainty were not independently verified. Queries were polled at least one second apart.",
            "The disabled load reported a small nonzero current during preflight. Raw offsets are retained without correction; no-load output power/loss are not inferred."],
        "points": [{**p.model_dump(), "qualification": "not-run", "acquisition_cycle_ids": []} for p in plan.points],
        "shutdown": {role: {"state": "UNKNOWN"} for role in devices}}
    store.initialize({"dut": plan.dut.model_dump(), "bench": plan.bench.model_dump(),
                      "recipe": plan.recipe.model_dump(), "authorization": run["authorization"]}, plan.model_dump(), run)
    transports, drivers, recorders = {}, {}, {}
    active = None
    began, counter = time.monotonic(), 0
    def event(name, **values):
        store.append("events", {"event": name, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                                "monotonic_s": time.monotonic()-began, **values})
    def deadline(signum, frame):
        raise BringupAbort("90 second whole-test deadline reached")
    previous = signal.signal(signal.SIGALRM, deadline)
    previous_term = signal.signal(signal.SIGTERM, deadline)
    signal.alarm(90)
    try:
        for role, device in devices.items():
            t = VisaTransport(role, device.resource, timeout_ms=1500, log_path=directory / "scpi.jsonl")
            transports[role] = t
            t.open()
            recording = RecordingTransport(t)
            recorders[role] = recording
            driver = get_driver_class(device.driver)(recording)
            identity = identify_and_verify(role, device, driver)
            # Cleanup may issue OFF commands only after the configured serial
            # has been verified. Opening a session does not authorize control.
            drivers[role] = driver
            run.setdefault("instrument_identities", {})[role] = asdict(identity)
            event("identity_verified", role=role, identity=asdict(identity))
        supply, load = drivers["source"], drivers["load"]
        # Independent shutdown is repeated in finally if either call fails.
        load.input_off()
        supply.output_off(1)
        off_source_V, off_load_V = supply.measure_voltage(1), load.measure_voltage()
        event("outputs_off_readbacks", source_V=off_source_V, load_V=off_load_V,
              note="Load-off voltage may be retained charge or stale readback; not a qualified DUT voltage")
        if abs(off_source_V) > .5 or (not loaded_only and abs(off_load_V) > .5):
            raise BringupAbort("Unexpected external/residual voltage while outputs are OFF")
        if loaded_only and not -.05 <= off_load_V <= VOUT_MAX:
            raise BringupAbort("Off-state load reading exceeds the absolute output guard")
        pilot = RigolPilot(supply, load, transports["source"], transports["load"])
        pilot.configure_protections()
        event("protection_verified", source_OVP_V=SOURCE_OVP, source_OCP_A=SOURCE_OCP,
              source_current_limit_A=ILIMIT, load_sense="local", output_guard_V=[VOUT_MIN,VOUT_MAX])
        print("Protection verified; starting CH1 at 24 V / 0.15 A, load OFF", flush=True)
        supply.output_on(1)
        run["lifecycle_state"] = "RUNNING"
        def cycle(point, phase, load_enabled):
            nonlocal counter
            counter += 1
            cid=f"c{counter:06d}"
            mode = pilot.mode()
            status = pilot.load_status(load_enabled)
            rows=[]
            for quantity in ("Vin_V", "Iin_A", "Vout_V", "Iout_A"):
                binding=plan.bench.measurements[quantity]
                start_utc=datetime.now(timezone.utc).isoformat(); start=time.monotonic()-began
                value=pilot.read(quantity)
                end=time.monotonic()-began; end_utc=datetime.now(timezone.utc).isoformat()
                row=RawSample(sample_id=f"{cid}-{quantity}",run_id=run_id,test_id="bringup",point_id=point["point_id"],
                    channel_id="CH1" if binding.instrument_id=="source" else "INPUT", instrument_id=binding.instrument_id,
                    quantity=quantity,value=value,unit=binding.unit,location=binding.location,
                    query_start_utc=start_utc,query_end_utc=end_utc,query_start_monotonic_s=start,query_end_monotonic_s=end,
                    measurement_range=None,resolution=None,raw_response=recorders[binding.instrument_id].last_response,
                    acquisition_cycle_id=cid,phase=phase,
                    acquisition_settings={"source_mode":mode,"load_compliance":True,"load_enabled":load_enabled,
                        "load_sense":"local","load_condition_register":status,
                        "adc_freshness":"not independently verified","raw_SCPI_response_file":"scpi.jsonl"})
                store.append("samples",row.model_dump()); rows.append(row)
            values={s.quantity:s.value for s in rows}
            if rows[-1].query_end_monotonic_s-rows[0].query_start_monotonic_s > .75:
                raise BringupAbort("Interchannel query skew exceeded 0.75 s")
            pilot.mode()
            if not 23.5 <= values["Vin_V"] <= 24.5 or not -.005 <= values["Iin_A"] <= ILIMIT:
                raise BringupAbort(f"Input guard failed: {values}")
            # A converter is allowed to start from zero. This expected state
            # exists only during the fixed startup windows; the absolute
            # upper voltage/current guards apply at every observation.
            lower_output = -.05 if phase == "starting" else VOUT_MIN
            if not lower_output <= values["Vout_V"] <= VOUT_MAX or not -.02 <= values["Iout_A"] <= .15:
                raise BringupAbort(f"Output guard failed: {values}")
            if load_enabled and phase != "starting" and abs(values["Iout_A"]-IOUT) > .03:
                raise BringupAbort(f"Requested load current not established: {values['Iout_A']}")
            return cid, values
        active = run["points"][0]
        if loaded_only:
            # The operator and prior automated loaded readbacks established
            # the nominal output. Do not qualify cached/load-off voltage as a
            # no-load measurement. This branch acquires only the active point.
            # Poll throughout the source-only dwell. These observations stay
            # in the unqualified starting phase; they are not a no-load test.
            # In particular, enforce the absolute upper voltage/current
            # guards before permitting the load input to turn on.
            for _ in range(5):
                time.sleep(1)
                cycle(active, "starting", False)
            load.input_on()
        for _ in range(5):
            time.sleep(1)
            cycle(active, "starting", loaded_only)
        for index, point in enumerate(run["points"]):
            active = point
            loaded=loaded_only or index==1
            if loaded and not load.get_input_enabled():
                load.input_on()
            # Startup dwell then regular guarded polling; no dynamic claims.
            time.sleep(1)
            observed=[]
            for _ in range(5):
                _, values=cycle(point,"settling",loaded); observed.append(values["Vout_V"]); time.sleep(1)
            if max(observed)-min(observed) > .05:
                raise BringupAbort("Output did not settle within a 50 mV span")
            accepted=[]
            for _ in range(5):
                cid, values=cycle(point,"acquiring",loaded); accepted.append(cid); time.sleep(1)
            point.update(qualification="valid",reason="Stable supervised DC readbacks; uncertainty and ADC independence unquantified",
                         acquisition_cycle_ids=accepted,settled=True)
            store.append("points",point)
            atomic_json(directory/"run.json",run)
            print(json.dumps({"point":"0.1 A load" if loaded else "no external load",**values}),flush=True)
            active = None
        run["execution_status"]="completed"
    except BaseException as exc:
        run["execution_status"]="aborted" if isinstance(exc,(BringupAbort,KeyboardInterrupt)) else "error"
        run["errors"].append(f"{type(exc).__name__}: {exc}")
        if active is not None:
            active.update(qualification="inconclusive", reason=run["errors"][-1], acquisition_cycle_ids=[])
        print("Stopped: "+run["errors"][-1],flush=True)
    finally:
        signal.alarm(0)
        for role in ("load","source"):
            driver=drivers.get(role)
            if driver is not None:
                try:
                    if role=="load": driver.input_off(); enabled=driver.get_input_enabled()
                    else: driver.output_off(1); enabled=driver.get_output_enabled(1)
                    run["shutdown"][role]={"state":"ON" if enabled else "OFF","verified":not enabled}
                except BaseException as exc:
                    run["shutdown"][role]={"state":"UNKNOWN","reason":str(exc)}
                    run["errors"].append(f"{role} shutdown: {exc}")
            try:
                if role in transports: transports[role].close()
            except Exception as exc:
                run["errors"].append(f"{role} close: {exc}")
        signal.signal(signal.SIGALRM,previous)
        signal.signal(signal.SIGTERM,previous_term)
        run["lifecycle_state"]="FINALIZED"
        run["finished_utc"]=datetime.now(timezone.utc).isoformat()
        event("shutdown",states=run["shutdown"])
        store.finalize(run)
    print(json.dumps({"run":str(directory),"execution":run["execution_status"],"shutdown":run["shutdown"]}),flush=True)
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=Path("runs/real-bringup"))
    parser.add_argument("--arm",action="store_true")
    parser.add_argument("--loaded-only",action="store_true",help="Acquire only the previously verified 100 mA loaded point; do not qualify load-off readbacks")
    args=parser.parse_args()
    path=run_bringup(args.config,args.out,arm=args.arm,loaded_only=args.loaded_only)
    run=json.loads((path/"run.json").read_text())
    safe=all(item.get("state")=="OFF" and item.get("verified") is True for item in run["shutdown"].values())
    return 0 if run["execution_status"]=="completed" and safe else 4


if __name__ == "__main__":
    raise SystemExit(main())
