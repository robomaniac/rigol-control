"""Synthetic temperature provider for the mock bench only. Never a hardware claim.

Case rise follows a first-order lag on the plant's synthetic module loss;
ambient drifts slowly. Every reading is labelled synthetic. A real bench
cannot bind this provider (``BenchProfile`` rejects it), so a missing real
sensor is never replaced by these model values.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from .domain import MOCK_THERMAL_ADAPTER, BenchProfile, TemperatureSensor

THERMAL_MODEL_VERSION = "first-order-case-1.0"
THERMAL_MODEL_PARAMETERS: dict[str, Any] = {
    "data_source": "simulated",
    "ambient_initial_C": 23.0,
    "ambient_drift_C_per_hour": 0.3,
    "ambient_gaussian_sigma_C": 0.01,
    "case_rise_per_module_loss_C_per_W": 8.0,
    "case_time_constant_s": 40.0,
    "case_offset_C": 0.05,
    "case_gaussian_sigma_C": 0.02,
    "loss_input": "synthetic plant module_loss_W; input lead loss is outside the modelled case",
}


@dataclass(frozen=True)
class ThermalState:
    sensor_id: str
    role: str
    ambient_C: float
    rise_C: float
    module_loss_W: float
    data_source: str = "synthetic"
    model_version: str = THERMAL_MODEL_VERSION


class MockThermalProvider:
    """``MeasurementProvider`` for the temperature roles of a mock bench profile."""

    def __init__(self, sensors: list[TemperatureSensor], plant, seed: int = 1,
                 parameters: dict[str, Any] | None = None):
        if not sensors:
            raise ValueError("synthetic thermal provider requires at least one declared sensor")
        if any(sensor.adapter != MOCK_THERMAL_ADAPTER for sensor in sensors):
            raise ValueError("synthetic thermal provider serves only mock_thermal sensors")
        self.sensors = {sensor.quantity: sensor for sensor in sensors}
        self.plant = plant
        self.parameters = {**THERMAL_MODEL_PARAMETERS, **(parameters or {})}
        self.random = random.Random(seed + 7919)  # independent of the electrical noise stream
        self.rise_C = 0.0
        self.last_time: float | None = None
        self.last_loss_W = 0.0

    @classmethod
    def for_bench(cls, bench: BenchProfile, plant, seed: int = 1,
                  parameters: dict[str, Any] | None = None) -> MockThermalProvider:
        """Bind to a mock bench profile; a real profile can never select the model."""
        if bench.mode != "mock":
            raise ValueError("The synthetic temperature provider is selectable only for a mock bench profile")
        sensors = [sensor for sensor in bench.temperature_sensors if sensor.adapter == MOCK_THERMAL_ADAPTER]
        if len(sensors) != len(bench.temperature_sensors):
            raise ValueError("Mock execution has no provider for a non-synthetic temperature adapter")
        return cls(sensors, plant, seed, parameters)

    @classmethod
    def attach(cls, bench: BenchProfile, plant, seed: int = 1,
               parameters: dict[str, Any] | None = None) -> MockThermalProvider:
        provider = cls.for_bench(bench, plant, seed, parameters)
        plant.thermal = provider
        return provider

    @property
    def quantities(self) -> tuple[str, ...]:
        return tuple(self.sensors)

    def identify(self) -> dict[str, Any]:
        return {"adapter": MOCK_THERMAL_ADAPTER, "model_version": THERMAL_MODEL_VERSION,
                "data_source": "simulated", "parameters": dict(self.parameters),
                "sensors": [sensor.sensor_id for sensor in self.sensors.values()],
                "note": "SYNTHETIC first-order case model; not an observation of any physical sensor"}

    def _ambient(self, now: float) -> float:
        return self.parameters["ambient_initial_C"] + self.parameters["ambient_drift_C_per_hour"] * now / 3600.0

    def _advance(self, now: float) -> None:
        """Exact first-order step; the plant loss at ``now`` is held across the elapsed interval."""
        loss = float(self.plant.state(now).module_loss_W)
        if self.last_time is not None and now > self.last_time:
            tau = self.parameters["case_time_constant_s"]
            target = self.parameters["case_rise_per_module_loss_C_per_W"] * loss
            self.rise_C = target + (self.rise_C - target) * math.exp(-(now - self.last_time) / tau)
        if self.last_time is None or now > self.last_time:
            self.last_time = now
        self.last_loss_W = loss

    def read(self, quantity: str, now: float) -> tuple[float, ThermalState]:
        sensor = self.sensors[quantity]
        self._advance(now)
        ambient = self._ambient(now)
        state = ThermalState(sensor.sensor_id, sensor.role, ambient, self.rise_C, self.last_loss_W)
        if sensor.role == "ambient":
            return ambient + self.random.gauss(0, self.parameters["ambient_gaussian_sigma_C"]), state
        return (ambient + self.rise_C + self.parameters["case_offset_C"]
                + self.random.gauss(0, self.parameters["case_gaussian_sigma_C"])), state
