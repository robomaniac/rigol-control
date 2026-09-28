"""Deterministic coupled DC plant. This module cannot connect to hardware."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

MODEL_VERSION = "coupled-dc-1.0"
MODEL_PARAMETERS = {
    "input_lead_resistance_ohm": 0.2,
    "output_resistance_ohm": 0.025,
    "base_loss_W": 0.09,
    "input_voltage_loss_W_per_V": 0.006,
    "output_current_loss_W_per_A2": 0.03,
    "output_power_loss_fraction": 0.025,
    "load_response_time_constant_s": 0.55,
    "current_limit_voltage_fraction": 0.9,
    "injected_source_current_limit_A": 0.02,
    "measurement_offsets": {"Vin_V": 0.003, "Iin_A": -0.0008,
                            "Vout_V": 0.001, "Iout_A": 0.0001},
    "measurement_gaussian_sigma": {"Vin_V": 0.0004, "Iin_A": 0.00003,
                                   "Vout_V": 0.0003, "Iout_A": 0.00002},
}


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


class MockBench:
    """Source + converter + load share one power-conserving model.

    Loss model: Pmodule = 0.09 + 0.006*Vin_source + 0.03*Iout²
    + 0.025*Pout. Input lead loss is Iin²*0.2. The source current
    limit collapses its output to 90% of the requested voltage, with
    output voltage then solved from remaining power. This synthetic
    compliance behavior is an explicit simplified model, not a DUT claim.
    """

    def __init__(self, nominal_voltage: float, current_limit: float,
                 minimum_load_voltage: float = 0.0, seed: int = 1):
        self.nominal_voltage = nominal_voltage
        self.current_limit = current_limit
        self.minimum_load_voltage = minimum_load_voltage
        self.random = random.Random(seed)
        self.source_enabled = False
        self.load_enabled = False
        self.source_voltage = 0.0
        self.target_current = 0.0
        self.start_current = 0.0
        self.changed_at = 0.0
        self.sense_enabled = False
        self.closed = False

    def identify(self) -> dict:
        return {"source": "synthetic-source", "load": "synthetic-load",
                "model_version": MODEL_VERSION, "data_source": "simulated"}

    def configure(self, vin: float, iout: float, now: float) -> None:
        if self.source_enabled or self.load_enabled:
            raise RuntimeError("mock configuration requires outputs OFF")
        self.source_voltage = vin
        self.target_current = iout
        self.start_current = 0.0
        self.changed_at = now
        self.sense_enabled = True

    def source_on(self) -> None:
        self.source_enabled = True

    def load_on(self) -> None:
        if not self.source_enabled or not self.sense_enabled:
            raise RuntimeError("mock load requires source and verified sense")
        self.load_enabled = True

    def load_off(self) -> None:
        self.load_enabled = False

    def source_off(self) -> None:
        self.source_enabled = False

    def close(self) -> None:
        self.closed = True

    def state(self, now: float, *, force_limit: bool = False) -> PlantState:
        if not self.source_enabled:
            return PlantState(0, 0, 0, 0, 0, 0, "OFF", True)
        elapsed = max(0.0, now - self.changed_at)
        current = self.target_current * (1.0 - math.exp(-elapsed / 0.55)) if self.load_enabled else 0.0
        voltage = max(0.0, self.nominal_voltage - 0.025 * current)
        fixed_loss = 0.09 + 0.006 * self.source_voltage + 0.03 * current**2
        loss = fixed_loss + 0.025 * voltage * current
        required = voltage * current + loss
        discriminant = self.source_voltage**2 - 0.8 * required
        needed_current = (2 * required / (self.source_voltage + math.sqrt(discriminant))
                          if discriminant >= 0 and self.source_voltage > 0 else math.inf)
        effective_limit = min(self.current_limit, 0.02) if force_limit else self.current_limit
        if needed_current > effective_limit:
            vin = 0.9 * self.source_voltage
            iin = effective_limit
            available = vin * iin - 0.2 * iin**2
            if current > 0:
                voltage = max(0.0, min(voltage, (available - fixed_loss) / (1.025 * current)))
            else:
                voltage = 0.0
            loss = max(0.0, available - voltage * current)
            mode = "CC"
        else:
            vin, iin, mode = self.source_voltage, needed_current, "CV"
        return PlantState(vin, iin, vin - iin * 0.2, voltage, current, loss,
                          mode, current == 0 or voltage >= self.minimum_load_voltage)

    def read(self, quantity: str, now: float, *, force_limit: bool = False) -> tuple[float, PlantState]:
        state = self.state(now, force_limit=force_limit)
        physical, offset, noise = {
            "Vin_V": (state.source_voltage_V, 0.003, 0.0004),
            "Iin_A": (state.input_current_A, -0.0008, 0.00003),
            "Vout_V": (state.output_voltage_V, 0.001, 0.0003),
            "Iout_A": (state.output_current_A, 0.0001, 0.00002),
        }[quantity]
        return physical + offset + self.random.gauss(0, noise), state
