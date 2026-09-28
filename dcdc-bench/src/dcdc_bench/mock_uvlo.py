"""Synthetic under-voltage lockout for the deterministic mock plant.

This module cannot connect to hardware. It hooks a latching UVLO comparator
onto ``adapters.MockBench`` by subclassing, so the coupled DC plant itself is
unchanged. The threshold, hysteresis and standby draw below are simulation
parameters chosen to exercise the procedure; they are not characteristics of
any physical DUT and every run that uses them is labelled synthetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .adapters import MODEL_PARAMETERS, MockBench, PlantState

UVLO_MODEL_VERSION = "synthetic-uvlo-1.0"
UVLO_MODEL_PARAMETERS = {
    "turn_off_below_dut_input_V": 8.6,
    "hysteresis_V": 0.5,
    "standby_input_current_A": 0.004,
    "decision_node": "DUT input voltage (source voltage minus modelled lead drop)",
    "label": "synthetic simulation parameters; not a DUT characteristic",
}


@dataclass
class SyntheticUvlo:
    """Latching comparator: off below ``turn_off_below_V``, on again above threshold + hysteresis.

    While off, the converter draws only ``standby_current_A`` from the source
    and delivers nothing; the plant reports 0 V / 0 A at the output with the
    load in the 0 A compliance state the base model already defines.
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

    def off_state(self, source_voltage_V: float) -> PlantState:
        lead = MODEL_PARAMETERS["input_lead_resistance_ohm"]
        dut_input = source_voltage_V - self.standby_current_A * lead
        return PlantState(source_voltage_V, self.standby_current_A, dut_input, 0.0, 0.0,
                          dut_input * self.standby_current_A, "CV", True)

    def apply(self, on_state: PlantState, now: float) -> PlantState:
        """Update the latch from the candidate operating state and return what the plant delivers."""
        if self.output_enabled and on_state.dut_input_voltage_V < self.turn_off_below_V:
            self.output_enabled = False
            self.transitions.append({"monotonic_s": now, "to": "off", "dut_input_V": on_state.dut_input_voltage_V})
        elif not self.output_enabled:
            resting = self.off_state(on_state.source_voltage_V)
            if resting.dut_input_voltage_V >= self.turn_on_at_V:
                self.output_enabled = True
                self.transitions.append({"monotonic_s": now, "to": "on", "dut_input_V": resting.dut_input_voltage_V})
        return on_state if self.output_enabled else self.off_state(on_state.source_voltage_V)


class UvloMockBench(MockBench):
    """MockBench plus a synthetic UVLO latch and a sanctioned live input-voltage step.

    ``configure`` keeps its outputs-OFF interlock. ``set_live_voltage`` is the
    single exception the UVLO ramp needs: it changes the source setpoint while
    the source stays on, mirroring the bounded live step of the real driver,
    and records every change.
    """

    def __init__(self, nominal_voltage: float, current_limit: float, minimum_load_voltage: float = 0.0,
                 seed: int = 1, uvlo: SyntheticUvlo | None = None):
        super().__init__(nominal_voltage, current_limit, minimum_load_voltage, seed)
        self.uvlo = uvlo if uvlo is not None else SyntheticUvlo()
        self.live_changes: list[dict] = []

    def identify(self) -> dict:
        return {**super().identify(), "uvlo_model_version": UVLO_MODEL_VERSION}

    def set_live_voltage(self, vin: float, now: float) -> None:
        if not self.source_enabled:
            raise RuntimeError("a live voltage step requires an ON source; use configure while outputs are OFF")
        if vin < 0:
            raise ValueError("source voltage cannot be negative")
        self.live_changes.append({"monotonic_s": now, "from_V": self.source_voltage, "to_V": vin})
        self.source_voltage = vin

    def state(self, now: float, *, force_limit: bool = False) -> PlantState:
        if not self.source_enabled:
            self.uvlo.output_enabled = False  # no input: the converter cannot be running
            return super().state(now, force_limit=force_limit)
        return self.uvlo.apply(super().state(now, force_limit=force_limit), now)
