"""Deterministic coupled DC plant. This module cannot connect to hardware.

Everything here is SYNTHETIC. ``coupled-dc-2.0`` re-fits the plant to the
behaviour recorded on the physical 12T12-4A sample (losses and wiring from the
24 V / 35.8 V load sweeps ``eb3bcd``, the failed 12 V cold start and the
source current-limit collapse of ``e0fab9``, the load's +11 mA current readback
of the pass-through run ``bed075``) so that a rehearsal on the mock prepares an
operator for what the DP821A/DL3031A bench will show. No value below is a
property of the DUT, an instrument identity or a measurement; every run that
uses the plant is labelled synthetic. Equations, the fit table and the limits
of the model are in ``docs/simulation-plant.md``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .domain import DutProfile, LoadCapabilities, Plan, SourceCapabilities

MODEL_VERSION = "coupled-dc-2.0"
UVLO_MODEL_VERSION = "synthetic-uvlo-1.0"
UVLO_MODEL_PARAMETERS = {
    "turn_off_below_dut_input_V": 8.6,
    "hysteresis_V": 0.5,
    "standby_input_current_A": 0.004,
    "decision_node": "DUT input voltage (source voltage minus modelled lead drop)",
    "label": "synthetic simulation parameters; not a DUT characteristic",
}
STARTUP_MODEL_PARAMETERS: dict[str, Any] = {
    # Recorded: 12.146 V output by +2.1 s at 24 V, 7.12 / 7.95 / 12.146 V at +2.2 / +3.5 / +4.8 s at 15 V.
    "cold_start_delay_s": 1.0,
    "soft_start_time_constant_s": 0.3,
    # A cold start needs at least this at the DUT input; None means the UVLO turn-on level. For a DUT
    # profile that records a failed direct cold start the runner places it this margin above the
    # highest recorded failed input, so the mock reproduces the record (the true threshold is unknown).
    "start_threshold_dut_input_V": None,
    "start_threshold_margin_above_recorded_failure_V": 0.5,
    # Recorded 12 V attempt: output plateau 7.98 V with the load OFF before the collapse.
    "stalled_output_fraction": 0.665,
    "label": "synthetic startup model shaped on the recorded cold starts; not a DUT characteristic",
}
SOURCE_LIMIT_PARAMETERS: dict[str, Any] = {
    # Recorded collapse: source terminal 2.661 V at 1.0005 A against a 1.000 A setting.
    "current_overshoot_A": 0.0005,
    "collapsed_input_resistance_ohm": 2.66,
    "hiccup_period_s": 0.37,
    "hiccup_attempt_fraction": 0.1,
    "label": "synthetic constant-power collapse into a current-limited source; shape from run e0fab9",
}
READBACK_MODEL_PARAMETERS: dict[str, Any] = {
    # Displayed digits of the DP821A (1 mV / 0.1 mA) and DL3031A (0.1 mV / 0.1 mA); a profile binding
    # that declares a resolution overrides these.
    "quantisation": {"Vin_V": 0.001, "Iin_A": 0.0001, "Vout_V": 0.0001, "Iout_A": 0.0001},
    # Each channel holds its last conversion for this long (recorded: load refreshes within 0.19 s,
    # source strings repeat across the 1.1 s poll period).
    "hold_s": {"Vin_V": 1.1, "Iin_A": 1.1, "Vout_V": 0.05, "Iout_A": 0.05},
    "offsets": {"Vin_V": 0.003, "Iin_A": -0.0008, "Vout_V": 0.001, "Iout_A": 0.0001},
    "gaussian_sigma": {"Vin_V": 0.0004, "Iin_A": 0.00003, "Vout_V": 0.0003, "Iout_A": 0.00002},
    # Pass-through run bed075: load current readback +11.0 to +11.3 mA above the source's at every load.
    "load_current_offset_A": 0.011,
    # Load input OFF: readback alternates between exactly 0 A and 10.9-11.3 mA between polls.
    "load_off_bistable_A": 0.011,
    # Recorded round trips: 4-5 ms median, 13-36 ms p95, 55 ms worst.
    "round_trip_min_s": 0.004, "round_trip_scale_s": 0.004, "round_trip_max_s": 0.055,
    "label": "synthetic readback model shaped on the recorded instrument behaviour; not an instrument specification",
}
HOLD_UP_MODEL_PARAMETERS: dict[str, Any] = {
    # Input hold-up of the synthetic converter (best-effort ISO 16750-2 procedures, docs/simulation-plant.md §10).
    # While the supply holds the DUT input node the capacitor is invisible; when the supply stops holding it
    # (output OFF, or a setpoint below the node: a lab supply cannot sink) the node decays through the
    # converter's draw. Running: constant input power fixed at the operating point, V(t)² = V0² − 2·P·t/C, so
    # the hold-up time to the UVLO turn-off is t = C·(V0² − Vuvlo²)/(2·P). After the trip: the standby
    # current discharges the node linearly. 470 µF holds a 12 V input above 8.6 V for about 9 ms at 1.8 W,
    # so a 100 ms interruption trips the converter unless a recipe's plant declares a larger value
    # (10 mF rides through about 190 ms). A simulation parameter, not a DUT property.
    "input_capacitance_F": 470e-6,
    "decay_while_running": "constant input power, fixed at the operating point when the supply stopped holding the node",
    "decay_after_trip": "constant standby current (uvlo.standby_input_current_A)",
    "label": "synthetic input hold-up; not a DUT characteristic and not a measurement",
}
INSTRUMENT_TIMING_PARAMETERS: dict[str, Any] = {
    # Emulated DP800 Delayer/Timer programs (docs/standards/instrument-sequencing-dp800.md): whole-second groups,
    # 1 s to 99999 s, Timer and Delayer never enabled together, end state applied when the program ends. Each
    # group boundary lands within this error of its nominal instant so two boundaries differ by at most 1 ms
    # from the programmed whole seconds; the real figure is unverified (bench check B1).
    "group_seconds": {"min": 1, "max": 99999, "integer": True},
    "group_boundary_error_max_s": 0.0005,
    "programs_exclusive": True,
    "label": ("synthetic emulation of the DP800 Delayer/Timer timing; whole-second groups per the programming guide, "
              "sub-second acceptance and the boundary error are unverified on the instrument"),
}
MODEL_PARAMETERS: dict[str, Any] = {
    "label": ("SYNTHETIC plant fitted to the recorded behaviour of the first converter sample (runs eb3bcd, e0fab9, "
              "bed075); not a DUT characteristic and not a measurement"),
    "input_lead_resistance_ohm": 0.06,
    "output_path_resistance_ohm": 0.10,
    "output_setpoint_offset_fraction": 0.01,
    "base_loss_W": 0.30,
    "input_voltage_loss_W_per_V": 0.020,
    "output_current_loss_W_per_A2": 0.25,
    "output_power_loss_fraction": 0.07,
    "load_step_time_s": 0.010,
    "injected_source_current_limit_A": 0.02,
    "uvlo": UVLO_MODEL_PARAMETERS,
    "startup": STARTUP_MODEL_PARAMETERS,
    "source_current_limit": SOURCE_LIMIT_PARAMETERS,
    "readback": READBACK_MODEL_PARAMETERS,
}
QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")


@dataclass(frozen=True)
class PlantState:
    source_voltage_V: float
    input_current_A: float
    dut_input_voltage_V: float
    output_voltage_V: float
    output_current_A: float
    module_loss_W: float
    source_mode: str
    load_compliance: bool


@dataclass
class SyntheticUvlo:
    """Latching comparator: off below ``turn_off_below_V``, on again above threshold + hysteresis.

    While off, the converter draws only ``standby_current_A`` from the source
    and delivers nothing. The plant decides at the DUT input after the modelled
    lead drop and records every transition.
    """
    turn_off_below_V: float = UVLO_MODEL_PARAMETERS["turn_off_below_dut_input_V"]
    hysteresis_V: float = UVLO_MODEL_PARAMETERS["hysteresis_V"]
    standby_current_A: float = UVLO_MODEL_PARAMETERS["standby_input_current_A"]
    output_enabled: bool = False
    transitions: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.turn_off_below_V <= 0 or self.hysteresis_V < 0 or self.standby_current_A < 0:
            raise ValueError("Synthetic UVLO needs a positive threshold and nonnegative hysteresis and standby current")

    @property
    def turn_on_at_V(self) -> float:
        return self.turn_off_below_V + self.hysteresis_V

    def parameters(self) -> dict:
        return {"version": UVLO_MODEL_VERSION, "turn_off_below_dut_input_V": self.turn_off_below_V,
                "hysteresis_V": self.hysteresis_V, "turn_on_at_dut_input_V": self.turn_on_at_V,
                "standby_input_current_A": self.standby_current_A,
                "decision_node": UVLO_MODEL_PARAMETERS["decision_node"], "label": UVLO_MODEL_PARAMETERS["label"]}

    def trip(self, now: float, dut_input_V: float) -> None:
        if self.output_enabled:
            self.output_enabled = False
            self.transitions.append({"monotonic_s": now, "to": "off", "dut_input_V": dut_input_V})

    def arm(self, now: float, dut_input_V: float) -> None:
        if not self.output_enabled:
            self.output_enabled = True
            self.transitions.append({"monotonic_s": now, "to": "on", "dut_input_V": dut_input_V})

    def off_state(self, source_voltage_V: float) -> PlantState:
        lead = MODEL_PARAMETERS["input_lead_resistance_ohm"]
        dut_input = source_voltage_V - self.standby_current_A * lead
        return PlantState(source_voltage_V, self.standby_current_A, dut_input, 0.0, 0.0,
                          dut_input * self.standby_current_A, "CV", True)

    def apply(self, on_state: PlantState, now: float) -> PlantState:
        """Legacy helper: update the latch from a candidate operating state and return what is delivered."""
        if self.output_enabled and on_state.dut_input_voltage_V < self.turn_off_below_V:
            self.trip(now, on_state.dut_input_voltage_V)
        elif not self.output_enabled:
            resting = self.off_state(on_state.source_voltage_V)
            if resting.dut_input_voltage_V >= self.turn_on_at_V:
                self.arm(now, resting.dut_input_voltage_V)
        return on_state if self.output_enabled else self.off_state(on_state.source_voltage_V)


@dataclass(frozen=True)
class StartupModel:
    """Cold start of the synthetic converter: a delay, a soft start and an optional start threshold.

    A cold start (source enabled from OFF) begins ``cold_start_delay_s`` after the source is
    enabled and only once the DUT input is at or above the start threshold; below it, but above
    the UVLO turn-on level, the converter stalls at ``stalled_output_fraction`` of nominal, as the
    physical sample did at 12 V. A restart after a UVLO trip with the source still on re-arms at the
    UVLO turn-on level with the same soft start and no delay.
    """
    cold_start_delay_s: float = STARTUP_MODEL_PARAMETERS["cold_start_delay_s"]
    soft_start_time_constant_s: float = STARTUP_MODEL_PARAMETERS["soft_start_time_constant_s"]
    start_threshold_dut_input_V: float | None = STARTUP_MODEL_PARAMETERS["start_threshold_dut_input_V"]
    stalled_output_fraction: float = STARTUP_MODEL_PARAMETERS["stalled_output_fraction"]

    def __post_init__(self) -> None:
        if self.cold_start_delay_s < 0 or self.soft_start_time_constant_s < 0:
            raise ValueError("Startup delay and time constant cannot be negative")
        if self.start_threshold_dut_input_V is not None and self.start_threshold_dut_input_V <= 0:
            raise ValueError("A start threshold must be positive")
        if not 0 <= self.stalled_output_fraction < 1:
            raise ValueError("The stalled output fraction must lie in [0, 1)")

    @classmethod
    def instant(cls) -> StartupModel:
        """No delay, step output, start at the UVLO turn-on level (the phase-scoped procedures' plant)."""
        return cls(cold_start_delay_s=0.0, soft_start_time_constant_s=0.0, start_threshold_dut_input_V=None)

    @classmethod
    def for_dut(cls, dut: DutProfile) -> StartupModel:
        """Generic start, or a start threshold above the highest cold-start input the DUT profile records as failed."""
        failed = dut.known_behaviours.cold_start_failed_at_V if dut.known_behaviours is not None else []
        if not failed:
            return cls()
        return cls(start_threshold_dut_input_V=max(failed)
                   + STARTUP_MODEL_PARAMETERS["start_threshold_margin_above_recorded_failure_V"])

    def soft(self, elapsed_s: float) -> float:
        if elapsed_s <= 0:
            return 0.0
        if self.soft_start_time_constant_s <= 0:
            return 1.0
        return 1.0 - math.exp(-elapsed_s / self.soft_start_time_constant_s)

    def parameters(self) -> dict:
        return {"cold_start_delay_s": self.cold_start_delay_s,
                "soft_start_time_constant_s": self.soft_start_time_constant_s,
                "start_threshold_dut_input_V": self.start_threshold_dut_input_V,
                "stalled_output_fraction": self.stalled_output_fraction,
                "label": STARTUP_MODEL_PARAMETERS["label"]}


@dataclass(frozen=True)
class ReadbackModel:
    """How the synthetic instruments report the plant: quantised, held, offset and noisy readbacks."""
    quantisation: dict[str, float] = field(default_factory=lambda: dict(READBACK_MODEL_PARAMETERS["quantisation"]))
    hold_s: dict[str, float] = field(default_factory=lambda: dict(READBACK_MODEL_PARAMETERS["hold_s"]))
    offsets: dict[str, float] = field(default_factory=lambda: dict(READBACK_MODEL_PARAMETERS["offsets"]))
    gaussian_sigma: dict[str, float] = field(default_factory=lambda: dict(READBACK_MODEL_PARAMETERS["gaussian_sigma"]))
    load_current_offset_A: float = READBACK_MODEL_PARAMETERS["load_current_offset_A"]
    load_off_bistable_A: float = READBACK_MODEL_PARAMETERS["load_off_bistable_A"]
    round_trip_min_s: float = READBACK_MODEL_PARAMETERS["round_trip_min_s"]
    round_trip_scale_s: float = READBACK_MODEL_PARAMETERS["round_trip_scale_s"]
    round_trip_max_s: float = READBACK_MODEL_PARAMETERS["round_trip_max_s"]

    @classmethod
    def realistic(cls, resolutions: dict[str, float | None] | None = None, **overrides: Any) -> ReadbackModel:
        """The recorded instrument behaviour; a declared profile resolution replaces the displayed-digit default."""
        quantisation = dict(READBACK_MODEL_PARAMETERS["quantisation"])
        for quantity, resolution in (resolutions or {}).items():
            if resolution is not None and resolution > 0:
                quantisation[quantity] = float(resolution)
        return cls(quantisation=quantisation, **overrides)

    @classmethod
    def clean(cls, **overrides: Any) -> ReadbackModel:
        """Unquantised, fresh, offset-free load readback with a fixed 2 ms round trip (legacy plant behaviour).

        ``overrides`` replace individual terms: the best-effort procedures keep the clean readbacks but
        draw command latencies from the recorded round-trip distribution (``recorded_round_trips()``).
        """
        values: dict[str, Any] = dict(quantisation={q: 0.0 for q in QUANTITIES}, hold_s={q: 0.0 for q in QUANTITIES},
                                      load_current_offset_A=0.0, load_off_bistable_A=0.0,
                                      round_trip_min_s=0.002, round_trip_scale_s=0.0, round_trip_max_s=0.002)
        values.update(overrides)
        return cls(**values)

    @classmethod
    def recorded_round_trips(cls) -> dict[str, float]:
        """The recorded LAN round-trip terms (4 ms + Exp(4 ms), capped at 55 ms) as ``clean(**...)`` overrides."""
        return {key: READBACK_MODEL_PARAMETERS[key] for key in ("round_trip_min_s", "round_trip_scale_s", "round_trip_max_s")}

    def parameters(self) -> dict:
        return {"quantisation": dict(self.quantisation), "hold_s": dict(self.hold_s), "offsets": dict(self.offsets),
                "gaussian_sigma": dict(self.gaussian_sigma), "load_current_offset_A": self.load_current_offset_A,
                "load_off_bistable_A": self.load_off_bistable_A,
                "round_trip_s": {"min": self.round_trip_min_s, "scale": self.round_trip_scale_s, "max": self.round_trip_max_s},
                "label": READBACK_MODEL_PARAMETERS["label"]}


@dataclass(frozen=True)
class HoldUpModel:
    """Input hold-up of the synthetic converter: one capacitor at the DUT input (``HOLD_UP_MODEL_PARAMETERS``).

    Used only when the supply stops holding the node (live output OFF, or a setpoint below the node). The
    converter draws constant power from the capacitor until the UVLO turn-off, then its standby current.
    """
    input_capacitance_F: float = HOLD_UP_MODEL_PARAMETERS["input_capacitance_F"]

    def __post_init__(self) -> None:
        if not math.isfinite(self.input_capacitance_F) or self.input_capacitance_F <= 0:
            raise ValueError("The hold-up capacitance must be a finite positive value")

    def constant_power_decay_s(self, v0: float, v1: float, power_W: float) -> float:
        """Time for the node to fall from ``v0`` to ``v1`` under a constant power draw (0 when v1 >= v0, inf for no draw)."""
        if v1 >= v0:
            return 0.0
        if power_W <= 0:
            return math.inf
        return self.input_capacitance_F * (v0**2 - v1**2) / (2.0 * power_W)

    def voltage_after_constant_power(self, v0: float, power_W: float, elapsed_s: float) -> float:
        return math.sqrt(max(0.0, v0**2 - 2.0 * power_W * max(0.0, elapsed_s) / self.input_capacitance_F))

    def constant_current_decay_s(self, v0: float, v1: float, current_A: float) -> float:
        if v1 >= v0:
            return 0.0
        if current_A <= 0:
            return math.inf
        return (v0 - v1) * self.input_capacitance_F / current_A

    def voltage_after_constant_current(self, v0: float, current_A: float, elapsed_s: float) -> float:
        return max(0.0, v0 - current_A * max(0.0, elapsed_s) / self.input_capacitance_F)

    def hold_up_s(self, v0: float, uvlo_turn_off_V: float, power_W: float) -> float:
        """How long the running converter rides through an interruption from ``v0`` before its UVLO trips."""
        return self.constant_power_decay_s(v0, uvlo_turn_off_V, power_W)

    def parameters(self) -> dict:
        return {**HOLD_UP_MODEL_PARAMETERS, "input_capacitance_F": self.input_capacitance_F}


def quantise(value: float, step: float) -> float:
    """Round to the instrument's displayed digit; a zero step keeps the full float."""
    if step <= 0:
        return value
    return round(round(value / step) * step, 10)


class MockBench:
    """Source + converter + load share one power-conserving synthetic model.

    Loss model (module): ``P = 0.30 W + 0.020 W/V · Vin + 0.25 W/A² · Iout² + 0.07 · Pout``;
    input lead ``0.06 Ω``; output ``Vout = 1.01 · Vnom − 0.10 Ω · Iout`` at the load terminals
    (local sense). The input current solves ``Vin · Iin − R_lead · Iin² = Pout + P`` exactly, so
    ``Vin · Iin = Pout + P + R_lead · Iin²`` holds in every CV state. A converter that starts is
    soft-started; below the start threshold it stalls near 8 V (12 V nominal); when the demanded
    input current exceeds the source limit the source enters CC and the converter collapses to a
    UVLO hiccup with ``Iin`` just above the limit (``Vin ≈ 2.66 Ω · Iin``), delivering nothing.
    All of it is a simplified synthetic model, not a DUT claim.
    """

    def __init__(self, nominal_voltage: float, current_limit: float,
                 minimum_load_voltage: float = 0.0, seed: int = 1, *,
                 uvlo: SyntheticUvlo | None = None, startup: StartupModel | None = None,
                 readback: ReadbackModel | None = None, hold_up: HoldUpModel | None = None):
        self.nominal_voltage = nominal_voltage
        self.current_limit = current_limit
        self.minimum_load_voltage = minimum_load_voltage
        self.random = random.Random(seed)
        self.uvlo = uvlo if uvlo is not None else SyntheticUvlo()
        self.startup = startup if startup is not None else StartupModel()
        self.readback = readback if readback is not None else ReadbackModel.realistic()
        # Optional input hold-up (best-effort procedures). None keeps the legacy plant: the DUT input node follows
        # the supply instantly and a live output OFF trips the converter at once.
        self.hold_up = hold_up
        # Live output and setpoint commands with their effective instants, instrument programs and the DUT input
        # node's decay segment (section "live commands" below). Cleared with the converter state.
        self._output_live = True
        self._scheduled: list[dict[str, Any]] = []
        self._node: dict[str, Any] | None = None
        self._program: dict[str, Any] | None = None
        self.applied_transitions: list[dict[str, Any]] = []
        self.source_enabled = False
        self.load_enabled = False
        self.source_voltage = 0.0
        self.target_current = 0.0
        self.start_current = 0.0
        self.changed_at = 0.0
        self.load_changed_at = 0.0
        self.source_on_at: float | None = None
        self.sense_enabled = False
        self.closed = False
        self.thermal = None  # optional synthetic temperature provider (mock_thermal.MockThermalProvider.attach)
        self._running = False
        self._started_at: float | None = None
        self._cold = True
        self._collapsed_since: float | None = None
        self._tripped_at: float | None = None
        self._input_changed_at = 0.0
        self._injected_limit = False
        self._held: dict[str, tuple[float, float]] = {}
        self._bistable_high = False

    @classmethod
    def for_plan(cls, plan: Plan, seed: int = 1) -> MockBench:
        """The plant the mock runner uses: DUT nominal output, the bench's source limit, the load's minimum
        voltage, a startup shaped by the DUT profile's recorded behaviour and readbacks quantised to the
        profile's declared resolutions."""
        limit = plan.bench.protective_controls.source_current_limit_A or plan.bench.source.max_current_A
        resolutions = {quantity: binding.resolution for quantity, binding in plan.bench.measurements.items()
                       if quantity in QUANTITIES}
        return cls(plan.dut.ratings.output_voltage_nominal_V, limit, plan.bench.load.min_voltage_V, seed,
                   startup=StartupModel.for_dut(plan.dut), readback=ReadbackModel.realistic(resolutions))

    def parameters(self) -> dict:
        """Every model parameter this instance uses, for the run record and the report provenance."""
        electrical = {key: value for key, value in MODEL_PARAMETERS.items()
                      if key not in ("uvlo", "startup", "source_current_limit", "readback")}
        return {**electrical, "source_current_limit_A": float(self.current_limit),
                "load_minimum_voltage_V": float(self.minimum_load_voltage),
                "uvlo": self.uvlo.parameters(), "startup": self.startup.parameters(),
                "source_current_limit": dict(SOURCE_LIMIT_PARAMETERS), "readback": self.readback.parameters(),
                **({"hold_up": self.hold_up.parameters(), "instrument_timing": dict(INSTRUMENT_TIMING_PARAMETERS)}
                   if self.hold_up is not None else {})}

    def identify(self) -> dict:
        return {"source": "synthetic-source", "load": "synthetic-load",
                "model_version": MODEL_VERSION, "data_source": "simulated"}

    def source_capabilities(self) -> SourceCapabilities:
        """The plant's own source limits, labelled synthetic; never a hardware claim."""
        return SourceCapabilities(
            instrument_id="synthetic-source", adapter="mock_source",
            reported_identity=f"synthetic-source {MODEL_VERSION}", capabilities_confirmed=True,
            max_current_A=float(self.current_limit))

    def load_capabilities(self) -> LoadCapabilities:
        return LoadCapabilities(
            instrument_id="synthetic-load", adapter="mock_load",
            reported_identity=f"synthetic-load {MODEL_VERSION}", capabilities_confirmed=True,
            mode="CC", min_current_A=0.0, min_voltage_V=float(self.minimum_load_voltage),
            remote_sense_supported=True)

    def status(self) -> dict:
        """Switch states and setpoints as last commanded; no plant solution here."""
        return {"source_output": "ON" if self.output_live else "OFF",
                "load_input": "ON" if self.load_enabled else "OFF",
                "remote_sense_verified": self.sense_enabled,
                "source_voltage_setpoint_V": self.source_voltage,
                "load_current_setpoint_A": self.target_current,
                "closed": self.closed}

    # -- switches and setpoints -------------------------------------------------------------------
    def configure(self, vin: float, iout: float, now: float) -> None:
        if self.source_enabled or self.load_enabled:
            raise RuntimeError("mock configuration requires outputs OFF")
        if vin < 0 or iout < 0:
            raise ValueError("source voltage and load current cannot be negative")
        self.source_voltage = vin
        self.target_current = iout
        self.start_current = 0.0
        self.changed_at = now
        self.load_changed_at = now
        self._input_changed_at = now
        self.sense_enabled = True
        self._reset_converter()

    def set_load_current(self, iout: float, now: float) -> None:
        """Change the load's CC setpoint live, as the DL3031A allows; the load steps in ``load_step_time_s``."""
        if iout < 0:
            raise ValueError("load current cannot be negative")
        self.start_current = self._load_command(now)
        self.target_current = iout
        self.load_changed_at = now

    def source_on(self, now: float | None = None) -> None:
        self.source_enabled = True
        self.source_on_at = now if now is not None else self.changed_at
        self._input_changed_at = self.source_on_at
        self._reset_converter()

    def load_on(self, now: float | None = None) -> None:
        if not self.source_enabled or not self.sense_enabled:
            raise RuntimeError("mock load requires source and verified sense")
        self.load_enabled = True
        self.start_current = 0.0
        self.load_changed_at = now if now is not None else self.changed_at

    def load_off(self) -> None:
        self.load_enabled = False
        self.start_current = 0.0

    def source_off(self) -> None:
        self.source_enabled = False
        self._reset_converter()

    def close(self) -> None:
        self.closed = True

    # -- the coupled plant ------------------------------------------------------------------------
    def _reset_converter(self) -> None:
        self._running = False
        self._started_at = None
        self._cold = True
        self._collapsed_since = None
        self._tripped_at = None
        self.uvlo.output_enabled = False  # no input: the converter cannot be running
        # No source: no pending live command, no program, the node follows the (absent) supply.
        self._output_live = True
        self._scheduled = []
        self._node = None
        self._program = None

    def _load_command(self, now: float) -> float:
        """The electronic load's actual CC demand: a ``load_step_time_s`` linear step, zero with the input OFF."""
        if not self.load_enabled:
            return 0.0
        step = MODEL_PARAMETERS["load_step_time_s"]
        elapsed = now - self.load_changed_at
        fraction = 1.0 if step <= 0 or elapsed >= step else max(0.0, elapsed / step)
        return self.start_current + (self.target_current - self.start_current) * fraction

    def _standby_input(self) -> float:
        return self.source_voltage - self.uvlo.standby_current_A * MODEL_PARAMETERS["input_lead_resistance_ohm"]

    def _off_state(self) -> PlantState:
        iin = self.uvlo.standby_current_A
        dut_input = self.source_voltage - iin * MODEL_PARAMETERS["input_lead_resistance_ohm"]
        return PlantState(self.source_voltage, iin, dut_input, 0.0, 0.0, dut_input * iin, "CV", True)

    def _start_threshold(self) -> float:
        threshold = self.uvlo.turn_on_at_V
        if self._cold and self.startup.start_threshold_dut_input_V is not None:
            threshold = max(threshold, self.startup.start_threshold_dut_input_V)
        return threshold

    def _try_start(self, now: float) -> None:
        standby_input = self._standby_input()
        if standby_input < self._start_threshold():
            return
        if self._cold:
            ready_at = (self.source_on_at if self.source_on_at is not None else self.changed_at) + self.startup.cold_start_delay_s
            if now < ready_at:
                return
            self._started_at = ready_at
        else:
            # A restart after a trip begins when the input or the load was last commanded (a live step or a
            # reduced load is what brings the input back above the turn-on level), never after now.
            candidates = [self._input_changed_at, self.load_changed_at]
            if self._tripped_at is not None:
                candidates.append(self._tripped_at)
            self._started_at = min(now, max(candidates))
        self._running = True
        self._cold = False
        self.uvlo.arm(now, standby_input)

    def _stalled(self) -> bool:
        """Cold, above the UVLO turn-on level, below the start threshold: the recorded 12 V plateau."""
        return (self._cold and self.startup.start_threshold_dut_input_V is not None
                and self.uvlo.turn_on_at_V <= self._standby_input() < self._start_threshold())

    def _stalled_state(self, now: float, command: float, limit: float) -> PlantState:
        ready_at = (self.source_on_at if self.source_on_at is not None else self.changed_at) + self.startup.cold_start_delay_s
        if now < ready_at:
            return self._off_state()
        if self.load_enabled and command > 0:
            # The recorded event: the load enabled at a stalled output drags the input down into the source limit.
            return self._collapse(now, limit, command)
        self._collapsed_since = None
        plateau = self.startup.stalled_output_fraction * self.nominal_voltage * self.startup.soft(now - ready_at)
        off = self._off_state()
        return PlantState(off.source_voltage_V, off.input_current_A, off.dut_input_voltage_V, plateau, 0.0,
                          off.module_loss_W, "CV", True)

    def _collapse(self, now: float, limit: float, command: float) -> PlantState:
        """Source in CC, converter tripped and hiccupping; nothing is delivered and Iin sits just above the limit."""
        lead = MODEL_PARAMETERS["input_lead_resistance_ohm"]
        cl = SOURCE_LIMIT_PARAMETERS
        if self._collapsed_since is None:
            self._collapsed_since = now
            self._tripped_at = now
            self.uvlo.trip(now, (limit + cl["current_overshoot_A"]) * (cl["collapsed_input_resistance_ohm"] - lead))
        self._running = False
        self._started_at = None
        iin = limit + cl["current_overshoot_A"]
        floor = iin * cl["collapsed_input_resistance_ohm"]
        period, attempt = cl["hiccup_period_s"], cl["hiccup_attempt_fraction"]
        phase = ((now - self._collapsed_since) % period) / period if period > 0 else 0.0
        vin = floor
        if attempt > 0 and phase >= 1.0 - attempt:
            # Re-fire attempt: the input recharges toward the run threshold, the converter starts, the
            # demand exceeds the limit again and the input falls back.
            progress = (phase - (1.0 - attempt)) / attempt
            vin = floor + (self.uvlo.turn_on_at_V - floor) * progress
        vin = min(max(vin, 0.0), self.source_voltage)
        dut_input = vin - iin * lead
        loss = max(0.0, vin * iin - iin**2 * lead)  # dissipated in the DUT's input network; the output delivers nothing
        compliance = not (self.load_enabled and command > 0)
        return PlantState(vin, iin, dut_input, 0.0, 0.0, loss, "CC", compliance)

    def _input_current(self, required_W: float) -> float:
        """Iin from ``Vin·Iin − R_lead·Iin² = required``; infinite when the source cannot deliver it."""
        vin, lead = self.source_voltage, MODEL_PARAMETERS["input_lead_resistance_ohm"]
        if vin <= 0:
            return math.inf
        if required_W <= 0:
            return 0.0
        discriminant = vin**2 - 4 * lead * required_W
        if discriminant < 0:
            return math.inf
        return 2 * required_W / (vin + math.sqrt(discriminant))

    def _steady_demand(self, command: float) -> float:
        """Input current the fully started converter would need for this load command."""
        p = MODEL_PARAMETERS
        voltage = (1.0 + p["output_setpoint_offset_fraction"]) * self.nominal_voltage - p["output_path_resistance_ohm"] * command
        current = command if command <= 0 or voltage >= self.minimum_load_voltage else 0.0
        pout = voltage * current
        loss = (p["base_loss_W"] + p["input_voltage_loss_W_per_V"] * self.source_voltage
                + p["output_current_loss_W_per_A2"] * current**2 + p["output_power_loss_fraction"] * pout)
        return self._input_current(pout + loss)

    def state(self, now: float, *, force_limit: bool = False) -> PlantState:
        if not self.source_enabled:
            self._reset_converter()
            return PlantState(0, 0, 0, 0, 0, 0, "OFF", True)
        if self._scheduled or self._node is not None:
            self._advance(now)
        if not self._output_live or self._node is not None:
            # A live interruption, or the DUT input node still above a supply that cannot sink: the capacitor path.
            return self._capacitor_state(now)
        p = MODEL_PARAMETERS
        limited = force_limit or self._injected_limit
        limit = min(self.current_limit, p["injected_source_current_limit_A"]) if limited else self.current_limit
        command = self._load_command(now)
        if self._collapsed_since is not None:
            # Collapsed into the source limit: the hiccup persists while the operating point still demands
            # more than the source can deliver; it clears only when the load or the input is changed.
            if self._steady_demand(command) > limit or (self._stalled() and command > 0):
                return self._collapse(now, limit, command)
            self._collapsed_since = None
        if not self._running:
            self._try_start(now)
        if not self._running:
            if self._stalled():
                return self._stalled_state(now, command, limit)
            self._collapsed_since = None
            return self._off_state()
        elapsed = now - (self._started_at if self._started_at is not None else now)
        open_circuit = (1.0 + p["output_setpoint_offset_fraction"]) * self.nominal_voltage * self.startup.soft(elapsed)
        voltage = open_circuit - p["output_path_resistance_ohm"] * command
        current = command
        compliance = True
        if command > 0 and voltage < self.minimum_load_voltage:
            # A CC load below its minimum operating voltage cannot sink its setpoint.
            current, voltage, compliance = 0.0, open_circuit, False
        pout = voltage * current
        loss = (p["base_loss_W"] + p["input_voltage_loss_W_per_V"] * self.source_voltage
                + p["output_current_loss_W_per_A2"] * current**2 + p["output_power_loss_fraction"] * pout)
        needed = self._input_current(pout + loss)
        if needed > limit:
            return self._collapse(now, limit, command)
        self._collapsed_since = None
        dut_input = self.source_voltage - needed * p["input_lead_resistance_ohm"]
        if dut_input < self.uvlo.turn_off_below_V:
            self.uvlo.trip(now, dut_input)
            self._running = False
            self._started_at = None
            self._tripped_at = now
            return self._off_state()
        return PlantState(self.source_voltage, needed, dut_input, voltage, current, loss, "CV", compliance)

    # -- live commands, instrument programs and the input hold-up (best-effort procedures) --------
    # Every live command takes effect at an instant the caller supplies (its issue time plus a drawn LAN
    # latency); the plant replays pending transitions in order whenever it is evaluated, evolving the DUT
    # input node between them, so a 100 ms interruption between two polls still reaches the UVLO latch at
    # the analytically solved crossing time instead of being missed at query time.
    def schedule_output(self, enabled: bool, at: float, *, origin: str = "lan") -> None:
        """Queue a live source-output change effective at ``at`` (the source stays energised in the procedure's sense)."""
        if not self.source_enabled:
            raise RuntimeError("a live output command requires an energised source; use source_on/source_off while idle")
        self._scheduled.append({"at": float(at), "kind": "output", "value": bool(enabled), "origin": origin})
        self._scheduled.sort(key=lambda item: item["at"])

    def schedule_voltage(self, vin: float, at: float, *, origin: str = "lan") -> None:
        """Queue a live setpoint change effective at ``at``."""
        if not self.source_enabled:
            raise RuntimeError("a live voltage step requires an ON source; use configure while outputs are OFF")
        if vin < 0:
            raise ValueError("source voltage cannot be negative")
        self._scheduled.append({"at": float(at), "kind": "voltage", "value": float(vin), "origin": origin})
        self._scheduled.sort(key=lambda item: item["at"])

    @property
    def output_live(self) -> bool:
        """The live source-output state (False during a commanded interruption); the setpoint is kept."""
        return self.source_enabled and self._output_live

    def _advance(self, now: float) -> None:
        pending = [item for item in self._scheduled if item["at"] <= now]
        self._scheduled = [item for item in self._scheduled if item["at"] > now]
        for item in pending:
            self._evolve_node(item["at"])
            self._apply(item)
        self._evolve_node(now)

    def _node_floor(self) -> float:
        """What the supply holds the DUT input node at: its setpoint while the output is live, nothing otherwise."""
        return self.source_voltage if self._output_live else 0.0

    def _segment_voltage(self, segment: dict[str, Any], t: float) -> float:
        hold_up = self.hold_up
        elapsed = t - segment["t0"]
        if segment["mode"] == "power":
            return hold_up.voltage_after_constant_power(segment["v0"], segment["p_W"], elapsed)
        return hold_up.voltage_after_constant_current(segment["v0"], segment["i_A"], elapsed)

    def _node_voltage_at(self, t: float) -> float:
        if self._node is not None:
            return max(self._segment_voltage(self._node, t), self._node_floor())
        if not self._output_live:
            return 0.0
        if self._running:
            iin = self._steady_demand(self._load_command(t))
            iin = iin if math.isfinite(iin) else self.current_limit
            return self.source_voltage - iin * MODEL_PARAMETERS["input_lead_resistance_ohm"]
        return self._standby_input()

    def _input_power_W(self, t: float) -> float:
        """Power the running converter draws from its input node at the current operating point."""
        iin = self._steady_demand(self._load_command(t))
        iin = iin if math.isfinite(iin) else self.current_limit
        return max(1e-9, self.source_voltage * iin - iin**2 * MODEL_PARAMETERS["input_lead_resistance_ohm"])

    def _begin_decay(self, t: float, v0: float) -> None:
        if self.hold_up is None:
            # Legacy plant: the node follows the supply instantly; a live OFF trips a running converter at once.
            self._node = None
            if self._running and self._node_floor() < self.uvlo.turn_off_below_V:
                self.uvlo.trip(t, self._node_floor())
                self._running, self._started_at, self._tripped_at = False, None, t
            return
        if self._node is not None:
            return  # already decaying; the floor is evaluated dynamically
        if self._running:
            self._node = {"t0": t, "v0": v0, "mode": "power", "p_W": self._input_power_W(t)}
        else:
            self._node = {"t0": t, "v0": v0, "mode": "standby", "i_A": self.uvlo.standby_current_A}

    def _settle_node(self, t: float) -> None:
        if self._node is not None and self._node_floor() >= self._segment_voltage(self._node, t):
            self._node = None  # the supply holds the node again

    def _evolve_node(self, t: float) -> None:
        """Advance the decay segment to ``t``: trip at the solved UVLO crossing, end the segment at the floor."""
        segment = self._node
        if segment is None:
            return
        floor = self._node_floor()
        turn_off = self.uvlo.turn_off_below_V
        if segment["mode"] == "power" and floor < turn_off < segment["v0"]:
            crossing = segment["t0"] + self.hold_up.constant_power_decay_s(segment["v0"], turn_off, segment["p_W"])
            if crossing <= t:
                self.uvlo.trip(crossing, turn_off)
                self._running, self._started_at, self._tripped_at = False, None, crossing
                segment = self._node = {"t0": crossing, "v0": turn_off, "mode": "standby", "i_A": self.uvlo.standby_current_A}
        if self._segment_voltage(segment, t) <= floor + 1e-12:
            self._node = None

    def _apply(self, item: dict[str, Any]) -> None:
        t, kind, value = item["at"], item["kind"], item["value"]
        node_before = self._node_voltage_at(t)
        if kind == "output":
            if value:
                self._output_live = True
                self._input_changed_at = t
                self._settle_node(t)
            else:
                self._output_live = False
                self._begin_decay(t, node_before)
        else:
            previous = self.source_voltage
            self.source_voltage = value
            self._input_changed_at = t
            if self.hold_up is not None and self._output_live and value < node_before:
                self._begin_decay(t, node_before)  # the supply cannot sink: the node falls through the converter's draw
            elif self.hold_up is not None:
                self._settle_node(t)
            item = {**item, "from_V": previous}
        self.applied_transitions.append({**item, "node_before_V": node_before, "converter_running": self._running})

    def _capacitor_state(self, now: float) -> PlantState:
        """The plant while the supply is not holding the DUT input node (interruption or a setpoint below it)."""
        p = MODEL_PARAMETERS
        node = self._node_voltage_at(now)
        live = self._output_live
        # The instrument reports its disabled output as 0 V / 0 A (OFF-state impedance unverified); while live but
        # back-driven by the node it shows the node voltage and delivers nothing.
        terminal = max(self.source_voltage, node) if live else 0.0
        command = self._load_command(now)
        if self._running:
            elapsed = now - (self._started_at if self._started_at is not None else now)
            open_circuit = (1.0 + p["output_setpoint_offset_fraction"]) * self.nominal_voltage * self.startup.soft(elapsed)
            voltage, current, compliance = open_circuit - p["output_path_resistance_ohm"] * command, command, True
            if command > 0 and voltage < self.minimum_load_voltage:
                current, voltage, compliance = 0.0, open_circuit, False
            pout = voltage * current
            loss = (p["base_loss_W"] + p["input_voltage_loss_W_per_V"] * node
                    + p["output_current_loss_W_per_A2"] * current**2 + p["output_power_loss_fraction"] * pout)
        else:
            voltage = current = 0.0
            compliance = not (self.load_enabled and command > 0)
            loss = node * self.uvlo.standby_current_A
        return PlantState(terminal, 0.0, node, voltage, current, loss, "CV" if live else "OFF", compliance)

    def _group_boundary_error_s(self) -> float:
        bound = INSTRUMENT_TIMING_PARAMETERS["group_boundary_error_max_s"]
        return self.random.uniform(-bound, bound)

    @staticmethod
    def _whole_seconds(value: Any, what: str) -> int:
        limits = INSTRUMENT_TIMING_PARAMETERS["group_seconds"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value != int(value):
            raise ValueError(f"{what} must be a whole number of seconds ({limits['min']} s to {limits['max']} s)")
        seconds = int(value)
        if not limits["min"] <= seconds <= limits["max"]:
            raise ValueError(f"{what} must lie between {limits['min']} s and {limits['max']} s")
        return seconds

    def _require_no_program(self, now: float, kind: str) -> None:
        if not self.source_enabled or not self._output_live:
            raise RuntimeError(f"the {kind} is started with the output ON; energise the source first")
        if self._program is not None and now < self._program["ends_at"]:
            raise RuntimeError("the Timer and the Delayer cannot be enabled together; the running program must end or be cancelled first")

    def program_delayer(self, groups: list[tuple[str, int]], now: float, *, cycles: int = 1, end_state: str = "OFF",
                        start_latency_s: float = 0.0) -> dict[str, Any]:
        """Emulate a DP800 Delayer program: ON/OFF groups in whole seconds, executed by the plant's own clock.

        The program starts ``start_latency_s`` after ``now`` (the ``:DELAY ON`` write's transport) and ends with
        ``end_state`` (``OFF``, ``ON`` or ``LAST``). Returns the schedule as the plant will run it; the procedure
        records only what the host can know (its own write instants and the programmed whole seconds).
        """
        self._require_no_program(now, "Delayer")
        if not 1 <= len(groups) <= 2048 or not 1 <= int(cycles) <= 99999 or end_state not in ("ON", "OFF", "LAST"):
            raise ValueError("A Delayer program has 1-2048 groups, 1-99999 cycles and an end state ON, OFF or LAST")
        validated = []
        for state, seconds in groups:
            if str(state).upper() not in ("ON", "OFF"):
                raise ValueError("Delayer groups are ON or OFF")
            validated.append((str(state).upper(), self._whole_seconds(seconds, "a Delayer group")))
        started_at = now + start_latency_s
        t, schedule = started_at, []
        for cycle in range(int(cycles)):
            for index, (state, seconds) in enumerate(validated):
                at = t + (self._group_boundary_error_s() if (cycle or index) else 0.0)
                schedule.append({"at": at, "nominal_at": t, "kind": "output", "value": state == "ON", "group": index, "cycle": cycle})
                t += seconds
        ends_at = t
        if end_state != "LAST":
            schedule.append({"at": ends_at + self._group_boundary_error_s(), "nominal_at": ends_at, "kind": "output",
                             "value": end_state == "ON", "group": None, "cycle": None, "end_state": end_state})
        self._scheduled.extend({**item, "origin": "delayer"} for item in schedule)
        self._scheduled.sort(key=lambda item: item["at"])
        self._program = {"kind": "delayer", "started_at": started_at, "ends_at": ends_at, "groups": validated,
                         "cycles": int(cycles), "end_state": end_state, "schedule": schedule}
        return dict(self._program)

    def program_timer(self, groups: list[tuple[float, float, int]], now: float, *, cycles: int = 1, end_state: str = "OFF",
                      start_latency_s: float = 0.0) -> dict[str, Any]:
        """Emulate a DP800 Timer program: (voltage, current, whole seconds) groups with the output already ON.

        The current of every group must not exceed the plant's source current limit (the Timer programs the
        channel's limit too). End state ``OFF`` turns the output off when the program ends; ``LAST`` keeps the
        last group's setpoint.
        """
        self._require_no_program(now, "Timer")
        if not 1 <= len(groups) <= 2048 or not 1 <= int(cycles) <= 99999 or end_state not in ("OFF", "LAST"):
            raise ValueError("A Timer program has 1-2048 groups, 1-99999 cycles and an end state OFF or LAST")
        validated = []
        for voltage, current, seconds in groups:
            if voltage < 0 or current < 0 or current > self.current_limit + 1e-12:
                raise ValueError("Timer groups need a nonnegative voltage and a current within the source current limit")
            validated.append((float(voltage), float(current), self._whole_seconds(seconds, "a Timer group")))
        started_at = now + start_latency_s
        t, schedule = started_at, []
        for cycle in range(int(cycles)):
            for index, (voltage, current, seconds) in enumerate(validated):
                at = t + (self._group_boundary_error_s() if (cycle or index) else 0.0)
                schedule.append({"at": at, "nominal_at": t, "kind": "voltage", "value": voltage, "current_A": current,
                                 "group": index, "cycle": cycle})
                t += seconds
        ends_at = t
        if end_state == "OFF":
            schedule.append({"at": ends_at + self._group_boundary_error_s(), "nominal_at": ends_at, "kind": "output",
                             "value": False, "group": None, "cycle": None, "end_state": end_state})
        self._scheduled.extend({**item, "origin": "timer"} for item in schedule)
        self._scheduled.sort(key=lambda item: item["at"])
        self._program = {"kind": "timer", "started_at": started_at, "ends_at": ends_at, "groups": validated,
                         "cycles": int(cycles), "end_state": end_state, "schedule": schedule}
        return dict(self._program)

    def program_status(self, now: float) -> dict[str, Any] | None:
        """What ``:TIMER?`` / ``:DELAY?`` would report: the running program and its elapsed time, or None."""
        program = self._program
        if program is None:
            return None
        return {"kind": program["kind"], "running": program["started_at"] <= now < program["ends_at"],
                "elapsed_s": now - program["started_at"], "ends_at": program["ends_at"]}

    def cancel_program(self) -> None:
        """``:TIMER OFF`` / ``:DELAY OFF``: drop the pending program transitions; the output keeps its current state."""
        self._scheduled = [item for item in self._scheduled if item["origin"] not in ("delayer", "timer")]
        self._program = None

    # -- what the synthetic instruments report --------------------------------------------------
    def query_round_trip_s(self) -> float:
        """One instrument query's round trip, drawn from the seeded stream (4-55 ms recorded)."""
        rb = self.readback
        if rb.round_trip_scale_s <= 0:
            return rb.round_trip_min_s
        return min(rb.round_trip_max_s, rb.round_trip_min_s + self.random.expovariate(1.0 / rb.round_trip_scale_s))

    def read(self, quantity: str, now: float, *, force_limit: bool = False) -> tuple[float, PlantState]:
        if self.thermal is not None and quantity in self.thermal.quantities:
            return self.thermal.read(quantity, now)
        # The injected limit of a fault scenario stays in force for every plant evaluation until the next
        # electrical read without it, so a thermal read between two faulted reads sees the same plant.
        self._injected_limit = bool(force_limit)
        state = self.state(now, force_limit=force_limit)
        rb = self.readback
        held = self._held.get(quantity)
        hold = rb.hold_s.get(quantity, 0.0)
        if held is not None and hold > 0 and 0 <= now - held[1] < hold:
            return held[0], state
        physical = {"Vin_V": state.source_voltage_V, "Iin_A": state.input_current_A,
                    "Vout_V": state.output_voltage_V, "Iout_A": state.output_current_A}[quantity]
        sigma = rb.gaussian_sigma.get(quantity, 0.0)
        value = physical + rb.offsets.get(quantity, 0.0) + self.random.gauss(0, sigma)
        if quantity == "Iout_A":
            if self.load_enabled and state.output_current_A > 0:
                value += rb.load_current_offset_A
            elif not self.load_enabled and rb.load_off_bistable_A > 0:
                # Recorded DL3031A behaviour with its input OFF: exactly 0 A or about 11 mA, alternating between polls.
                self._bistable_high = not self._bistable_high
                value = rb.load_off_bistable_A + self.random.gauss(0, sigma) if self._bistable_high else 0.0
        value = quantise(value, rb.quantisation.get(quantity, 0.0))
        self._held[quantity] = (value, now)
        return value, state
