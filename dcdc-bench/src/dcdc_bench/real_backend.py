"""Profile-driven, bounded DC acquisition on the verified two-instrument bench.

Importing, planning and confirmation validation never open an instrument. The
existing fixed-procedure lifecycle owns locks, raw persistence and independent
shutdown. This backend supports positive-load steady-state sweeps only.
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import mean

from .domain import Plan
from .extended import ExtendedAbort, _run_fixed
from .planning import _hash_payload, missing_approvals, verify_plan_hash
from .source_limit import SourceLimitRigol
from .storage import atomic_json
from .voltage_sweep import VoltageSweepProcedure

POLICY = "profile-dc-dp821a-ch1-v1"


def prepare_real_plan(original: Plan) -> tuple[Plan, list[str], float]:
    """Return an immutable preview with every requested point retained."""
    if not verify_plan_hash(original):
        raise ValueError("Plan hash mismatch")
    plan = original.model_copy(deep=True)
    b, r, d = plan.bench, plan.recipe, plan.dut
    c, errors = b.protective_controls, []
    c.policy_id = d.execution_approval.protective_policy_id = r.authorization.protective_policy_id = POLICY
    errors += missing_approvals(d, b)
    if b.mode != "real" or r.execution_mode != "real":
        errors.append("This backend requires real bench and recipe profiles")
    if b.source.channel != 1 or b.source.remote_sense_required or b.load.remote_sense_required:
        errors.append("Supported wiring is DP821A CH1 and local load sensing")
    if b.source.adapter not in ("benchctl_dp800", "benchctl_rigol_dp800") or b.load.adapter not in ("benchctl_dl3000", "benchctl_rigol_dl3000"):
        errors.append("Supported adapters are benchctl DP800 and DL3000")
    for quantity, role, location in (("Vin_V", "source", "source_terminals"),
            ("Iin_A", "source", "source_output"), ("Vout_V", "load", "load_input_terminals_local_sense"),
            ("Iout_A", "load", "load_input")):
        binding = b.measurements.get(quantity)
        if binding is None or binding.instrument_id != role or binding.location != location:
            errors.append(f"{quantity} must use {role} at {location}")
    if c.source_current_limit_A is None or not .05 <= c.source_current_limit_A <= 1:
        errors.append("Source current setting must be 0.05–1 A")
    if c.source_current_limit_A is not None and b.source.max_current_A is not None and c.source_current_limit_A > b.source.max_current_A:
        errors.append("Source current setting exceeds the saved bench capability")
    if c.dut_input_overvoltage_V is None or not 1 <= c.dut_input_overvoltage_V <= min(36., d.ratings.input_voltage_max_V):
        errors.append("Source OVP must be supplied, <=36 V and <=DUT maximum input")
    if not 1 <= d.ratings.output_voltage_nominal_V <= 12:
        errors.append("This initial backend supports nominal outputs from 1 to 12 V")
    if c.dut_output_overvoltage_V is None or not d.ratings.output_voltage_nominal_V < c.dut_output_overvoltage_V <= 13.2:
        errors.append("Output voltage guard must exceed nominal output and be <=13.2 V")
    if c.output_overcurrent_A is None or not .05 <= c.output_overcurrent_A <= 2.55:
        errors.append("Output current guard must be supplied and <=2.55 A")
    if c.output_overcurrent_A is not None and b.load.max_current_A is not None and c.output_overcurrent_A > b.load.max_current_A:
        errors.append("Output current guard exceeds the saved load capability")
    if c.dut_output_overvoltage_V is not None and b.load.max_voltage_V is not None and c.dut_output_overvoltage_V > b.load.max_voltage_V:
        errors.append("Output voltage guard exceeds the saved load capability")
    if c.maximum_temperature_C is not None or d.acceptance.maximum_surface_temperature_C is not None:
        errors.append("Temperature protection is unsupported: no temperature adapter is installed")
    if any(t.optional_quantities or set(t.required_quantities) != {"Vin_V", "Iin_A", "Vout_V", "Iout_A"} for t in r.tests):
        errors.append("Only the four electrical channels are supported")
    if not (5 <= r.settling.minimum_dwell_s <= 15 and 4 <= r.settling.window_s <= 15
            and 5 <= r.settling.minimum_fresh_samples <= 15 and r.settling.timeout_s >= r.settling.minimum_dwell_s):
        errors.append("Settling requires 5–15 s dwell, 4–15 s window and 5–15 queried samples")
    if not (5 <= r.acquisition.duration_s <= 15 and 1 <= r.acquisition.target_poll_interval_s <= 2
            and 5 <= r.acquisition.minimum_complete_cycles <= 15
            and 0 < r.acquisition.maximum_interchannel_skew_s <= .75):
        errors.append("Acquisition requires 5–15 s, 1–2 s polling, 5–15 cycles and <=750 ms query skew")
    if not 0 < r.settling.maximum_vout_span_V <= .05:
        errors.append("Settling voltage span must be >0 and <=50 mV")
    for point in plan.points:
        if point.status not in ("approval_blocked", "executable"):
            continue
        reasons = []
        if not 1 <= point.vin_target_V <= 35.8:
            reasons.append("source request outside supported 1–35.8 V envelope")
        if point.vin_target_V * 1.001 + .025 > d.ratings.input_voltage_max_V:
            reasons.append("input request leaves insufficient DC programming-accuracy margin below DUT maximum")
        if point.vin_target_V * .999 - .025 < d.ratings.input_voltage_min_V:
            reasons.append("input request leaves insufficient DC programming-accuracy margin above DUT minimum")
        if c.dut_input_overvoltage_V is not None and point.vin_target_V >= c.dut_input_overvoltage_V:
            reasons.append("input request must be below source OVP")
        if not .05 <= point.iout_target_A <= 2.5:
            reasons.append("only loaded 0.05–2.5 A observations are supported; no-load remains unqualified")
        if point.iout_target_A * (c.dut_output_overvoltage_V or 13.2) > 34:
            reasons.append("output exceeds the supported 34 W envelope")
        point.status = "unsupported" if reasons else "executable"
        point.reason = "; ".join(reasons) if reasons else "Eligible bounded DC point; fresh physical confirmation is required to arm"
    eligible = [p for p in plan.points if p.status == "executable"]
    phases = sum(i == 0 or (p.test_id, p.vin_target_V) != (eligible[i-1].test_id, eligible[i-1].vin_target_V)
                 for i, p in enumerate(eligible))
    seconds = len(eligible) * (max(r.settling.minimum_dwell_s, r.settling.window_s,
        r.settling.minimum_fresh_samples * r.acquisition.target_poll_interval_s) +
        max(r.acquisition.duration_s, r.acquisition.minimum_complete_cycles * r.acquisition.target_poll_interval_s) + 3) + phases * 14
    if not eligible:
        errors.append("No requested point is eligible")
    if seconds > 540:
        errors.append(f"Estimated acquisition {seconds:g} s exceeds the 540 s planning budget; split the recipe")
    plan.warnings += ["Real execution is bounded by a 660 s software deadline and a verified 720 s source timer per voltage phase.",
        "Every input-voltage phase starts with both outputs OFF and a fresh unloaded startup; warm-start descent is a separate procedure.",
        "Electrical guards are stop criteria, not DUT acceptance limits. OVP and polled readings do not certify fast transient protection.",
        "No-load, temperature, remote sensing, arbitrary commands and automatic restart are not supported."]
    plan.plan_hash = _hash_payload(plan.model_dump(mode="json", exclude={"plan_hash"}))
    return plan, errors, seconds


class ConfiguredProcedure:
    def __init__(self, plan: Plan, confirmation: dict, cancel: Path | None = None, *, notes="", attachments=None):
        if not verify_plan_hash(plan):
            raise ValueError("Plan hash mismatch")
        self.snapshot, self.confirmation, self.cancel = plan.model_copy(deep=True), confirmation, cancel
        self.notes, self.attachments = str(notes).strip(), list(attachments or [])
        self.stage, self.source_only_cycles = "starting", 0
        first = next(p for p in plan.points if p.status == "executable")
        self.voltage = first.vin_target_V
        controls = plan.bench.protective_controls
        self.lower_output = .9 * plan.dut.ratings.output_voltage_nominal_V
        procedure = self

        class ProfileRigol(SourceLimitRigol):
            voltage = first.vin_target_V
            current_limit = controls.source_current_limit_A
            source_ovp = controls.dut_input_overvoltage_V
            source_ocp = min(1.05, controls.source_current_limit_A * 1.1 + .005)
            output_voltage_limit = controls.dut_output_overvoltage_V
            output_current_limit = controls.output_overcurrent_A
            initial_current = first.iout_target_A

            def start(self):
                procedure.check_cancel()
                super().start()

            def _write_source(self, command):
                if command == ":DELAY ON":
                    procedure.check_cancel()
                super()._write_source(command)

            def configure(self, *args, **kwargs):
                procedure.check_cancel()
                for transport, wanted in ((self.st, "DP821A"), (self.lt, "DL3031A")):
                    fields = transport.query("*IDN?").strip().split(",")
                    if len(fields) < 3 or fields[1].strip().upper() != wanted:
                        raise ExtendedAbort(f"This backend requires the verified {wanted} model")
                super().configure(*args, **kwargs)

        self.adapter = ProfileRigol

    def check_cancel(self):
        if self.cancel is not None and self.cancel.exists():
            raise ExtendedAbort("Operator requested cancellation")

    def plan(self):
        self.check_cancel()
        return self.snapshot.model_copy(deep=True)

    @staticmethod
    def initial_point(run):
        return next(p for p in run["points"] if p["status"] == "executable")

    @staticmethod
    def record_attempt(run, point):
        if point["point_id"] not in run["executed_point_ids"]:
            run["executed_point_ids"].append(point["point_id"])
        run["current_point_id"] = point["point_id"]

    def metadata(self):
        c = self.snapshot.bench.protective_controls
        return {"scenario": "Configured supervised steady-state DC sweep", "executed_point_ids": [],
            "authorization": "Fresh local operator confirmation bound to the immutable saved plan",
            "operator_confirmation": self.confirmation,
            "operator_observations": ([self.notes] if self.notes else []) + [
                f"Referenced {a['role']}: {a['name']}. {a['caption']} Location: {a['location']} (reference only; file not embedded)."
                for a in self.attachments],
            "attachment_descriptors": self.attachments,
            "method": {"policy_id": POLICY, "source_current_limit_A": c.source_current_limit_A,
                "source_OVP_V": c.dut_input_overvoltage_V, "source_OCP_A": self.adapter.source_ocp,
                "hardware_deadline_s": 720, "software_deadline_s": 660,
                "configured_dc_sweep": True, "output_lower_stop_V": self.lower_output},
            "metrology_limitations": ["Source/load-terminal path includes wiring losses.",
                "Calibration, ADC freshness and readback uncertainty are unquantified; no temperature was acquired.",
                "No-load, thermal equilibrium, dynamic behavior and full ratings are not established."]}

    def guard(self, values, requested, *, loaded=True, startup=False, mode_before="CV", mode_after="CV"):
        self.check_cancel()
        c, d = self.snapshot.bench.protective_controls, self.snapshot.dut.ratings
        if any(not math.isfinite(value) for value in values.values()):
            raise ExtendedAbort("Nonfinite electrical observation")
        upper_input = min(self.voltage + .5, d.input_voltage_max_V - (.001*d.input_voltage_max_V + .025))
        lower_input = max(self.voltage - .5, d.input_voltage_min_V + (.001*d.input_voltage_min_V + .025))
        if not -.005 <= values["Iin_A"] <= min(1.02, c.source_current_limit_A + .02):
            raise ExtendedAbort("Input-current hard guard exceeded")
        if not -.05 <= values["Vin_V"] <= upper_input or not -.05 <= values["Vout_V"] <= c.dut_output_overvoltage_V:
            raise ExtendedAbort("Voltage hard guard exceeded")
        if not -.02 <= values["Iout_A"] <= c.output_overcurrent_A:
            raise ExtendedAbort("Output-current hard guard exceeded")
        if mode_before != "CV" or mode_after != "CV" or values["Vin_V"] < lower_input or values["Iin_A"] >= .995*c.source_current_limit_A:
            raise ExtendedAbort("Source headroom/current boundary reached; nominal-input efficiency is unqualified")
        if startup and not loaded:
            self.source_only_cycles += 1
        if (not startup or (not loaded and self.source_only_cycles >= 5)) and values["Vout_V"] < self.lower_output:
            raise ExtendedAbort("Output below startup/operating threshold; load will not be enabled or increased")
        if loaded and not startup and abs(values["Iout_A"]-requested) > .02:
            raise ExtendedAbort("Requested load current was not established")

    def execute(self, ctx):
        r, run, clock = self.snapshot.recipe, ctx.run, ctx.clock
        points = [p for p in run["points"] if p["status"] == "executable"]
        previous_phase = None
        previous_current = points[0]["iout_target_A"]
        for index, point in enumerate(points):
            self.check_cancel()
            if clock.monotonic() - ctx.began >= 600:
                raise ExtendedAbort("Remaining time reserved for safe shutdown")
            phase = (point["test_id"], point["vin_target_V"])
            if previous_phase is not None and phase != previous_phase:
                VoltageSweepProcedure.stop_phase(ctx)
                self.voltage, self.source_only_cycles = point["vin_target_V"], 0
                ctx.pilot.voltage, ctx.pilot.initial_current = self.voltage, point["iout_target_A"]
                ctx.pilot.configure()
            self.record_attempt(run, point)
            ctx.set_active(point)
            self.stage = point["test_id"]
            atomic_json(ctx.directory / "run.json", run)
            if previous_phase is not None and phase != previous_phase:
                ctx.pilot.start()
                for _ in range(5):
                    clock.sleep(1)
                    ctx.cycle(point, "starting", loaded=False, startup=True)
                ctx.load.input_on()
                for _ in range(5):
                    clock.sleep(1)
                    ctx.cycle(point, "starting", startup=True)
                previous_current = point["iout_target_A"]
            if point["iout_target_A"] != previous_current:
                ctx.load.set_current(point["iout_target_A"])
            previous_current, previous_phase = point["iout_target_A"], phase
            began, settled = clock.monotonic(), []
            while (clock.monotonic()-began < max(r.settling.minimum_dwell_s, r.settling.window_s)
                   or len(settled) < r.settling.minimum_fresh_samples):
                clock.sleep(r.acquisition.target_poll_interval_s)
                _, values, _ = ctx.cycle(point, "settling")
                settled.append(values["Vout_V"])
                if clock.monotonic()-began > r.settling.timeout_s:
                    raise ExtendedAbort("Settling timeout")
            if max(settled)-min(settled) > r.settling.maximum_vout_span_V:
                raise ExtendedAbort("Output did not settle within the configured voltage span")
            acquisition, accepted, readings, max_skew = clock.monotonic(), [], [], 0.
            while clock.monotonic()-acquisition < r.acquisition.duration_s or len(accepted) < r.acquisition.minimum_complete_cycles:
                cid, values, skew = ctx.cycle(point, "acquiring")
                accepted.append(cid)
                readings.append(values)
                max_skew = max(max_skew, skew)
                clock.sleep(r.acquisition.target_poll_interval_s)
            if max(row["Vout_V"] for row in readings)-min(row["Vout_V"] for row in readings) > r.settling.maximum_vout_span_V:
                raise ExtendedAbort("Output voltage span exceeded the configured bound during acquisition")
            point.update(qualification="valid", reason="Qualified bounded CV/DC observation; uncertainty unquantified",
                acquisition_cycle_ids=accepted, settled=True, settling_elapsed_s=acquisition-began,
                acquisition_elapsed_s=clock.monotonic()-acquisition,
                maximum_interchannel_skew_s=max_skew,
                acquisition_start_monotonic_s=acquisition-ctx.began,
                acquisition_end_monotonic_s=clock.monotonic()-ctx.began)
            run["latest"] = {key: mean(row[key] for row in readings) for key in readings[0]}
            ctx.store.append("points", point)
            atomic_json(ctx.directory / "run.json", run)
            ctx.set_active(None)
        run["current_point_id"] = None


def run_real(plan: Plan, inventory: Path, out: Path, *, confirmation: dict, cancel: Path | None = None,
             notes="", attachments=None) -> Path:
    """Only the job service supplies a validated, freshly confirmed plan."""
    if confirmation.get("plan_hash") != plan.plan_hash or not all(confirmation.get(k) is True for k in
            ("wiring_and_polarity", "channel1", "protections_reviewed")):
        raise ValueError("Physical confirmation must match this exact plan")
    # Rebuild from the saved profiles, never trust arbitrary executable flags.
    from .planning import build_plan
    rebuilt, errors, _ = prepare_real_plan(build_plan(plan.dut, plan.bench, plan.recipe))
    if errors or rebuilt.plan_hash != plan.plan_hash:
        raise ValueError("Real plan is unsupported or changed: " + "; ".join(errors))
    from benchctl.config import load_config
    devices = load_config(inventory).devices
    for role, name in (("source", "psu_rigol_1"), ("load", "load_rigol_1")):
        if not devices[name].expected_serial or confirmation.get(role+"_serial") != devices[name].expected_serial:
            raise ValueError("Instrument confirmation does not match the saved inventory")
    return _run_fixed(inventory, out, arm=True, procedure=ConfiguredProcedure(plan, confirmation, cancel,
        notes=notes, attachments=attachments))
