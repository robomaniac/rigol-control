"""Synthetic under-voltage lockout for the deterministic mock plant.

This module cannot connect to hardware. The latching UVLO comparator lives in
``adapters.MockBench`` itself (``adapters.SyntheticUvlo``), so the coupling
between the source current-limit collapse and the UVLO latch exists in every
mock run. ``UvloMockBench`` adds the one sanctioned live input-voltage step the
UVLO ramp and the ISO 16750-2 supply profiles need. Those phase-scoped
procedures declare their own bounded startup interval and apply the
minimum-output rule at every settling cycle after a live step, so their plant
keeps an instantaneous start and clean, unquantised readbacks; the cold-start
delay, soft start, start threshold and the recorded readback artefacts belong
to the steady-state sweep runner's plant (``MockBench.for_plan``). The
threshold, hysteresis and standby draw are simulation parameters chosen to
exercise the procedure; they are not characteristics of any physical DUT and
every run that uses them is labelled synthetic.
"""
from __future__ import annotations

from .adapters import (UVLO_MODEL_PARAMETERS, UVLO_MODEL_VERSION, MODEL_PARAMETERS, MockBench, PlantState,  # noqa: F401
                       ReadbackModel, StartupModel, SyntheticUvlo)

__all__ = ["UVLO_MODEL_PARAMETERS", "UVLO_MODEL_VERSION", "MODEL_PARAMETERS", "PlantState", "SyntheticUvlo",
           "UvloMockBench"]


class UvloMockBench(MockBench):
    """MockBench plus a sanctioned live input-voltage step.

    ``configure`` keeps its outputs-OFF interlock. ``set_live_voltage`` is the
    single exception the UVLO ramp needs: it changes the source setpoint while
    the source stays on, mirroring the bounded live step of the real driver,
    and records every change. Startup is instantaneous and readbacks are clean
    unless the caller passes its own models (see the module docstring).
    """

    def __init__(self, nominal_voltage: float, current_limit: float, minimum_load_voltage: float = 0.0,
                 seed: int = 1, uvlo: SyntheticUvlo | None = None, *, startup: StartupModel | None = None,
                 readback: ReadbackModel | None = None):
        super().__init__(nominal_voltage, current_limit, minimum_load_voltage, seed, uvlo=uvlo,
                         startup=startup if startup is not None else StartupModel.instant(),
                         readback=readback if readback is not None else ReadbackModel.clean())
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
        self._input_changed_at = now
