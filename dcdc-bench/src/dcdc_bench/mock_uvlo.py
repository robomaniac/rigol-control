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

from .adapters import (UVLO_MODEL_PARAMETERS, UVLO_MODEL_VERSION, MODEL_PARAMETERS, HoldUpModel, MockBench,  # noqa: F401
                       PlantState, ReadbackModel, StartupModel, SyntheticUvlo)

__all__ = ["UVLO_MODEL_PARAMETERS", "UVLO_MODEL_VERSION", "MODEL_PARAMETERS", "HoldUpModel", "PlantState", "SyntheticUvlo",
           "UvloMockBench"]


class UvloMockBench(MockBench):
    """MockBench plus the sanctioned live commands of the phase-scoped procedures.

    ``configure`` keeps its outputs-OFF interlock. ``set_live_voltage`` is the
    exception the UVLO ramp needs: it changes the source setpoint while the
    source stays on, mirroring the bounded live step of the real driver, and
    records every change. The best-effort ISO 16750-2 procedures add a live
    output OFF/ON (``set_output``) and a command-latency draw
    (``command_latency_s``) so a command takes effect at ``now`` plus a seeded
    LAN round trip; with a ``hold_up`` model the DUT input node then decays
    through the converter's draw instead of following the supply instantly.
    Startup is instantaneous and readbacks are clean unless the caller passes
    its own models (see the module docstring).
    """

    def __init__(self, nominal_voltage: float, current_limit: float, minimum_load_voltage: float = 0.0,
                 seed: int = 1, uvlo: SyntheticUvlo | None = None, *, startup: StartupModel | None = None,
                 readback: ReadbackModel | None = None, hold_up: HoldUpModel | None = None):
        super().__init__(nominal_voltage, current_limit, minimum_load_voltage, seed, uvlo=uvlo,
                         startup=startup if startup is not None else StartupModel.instant(),
                         readback=readback if readback is not None else ReadbackModel.clean(), hold_up=hold_up)
        self.live_changes: list[dict] = []
        self.output_changes: list[dict] = []

    def identify(self) -> dict:
        return {**super().identify(), "uvlo_model_version": UVLO_MODEL_VERSION}

    def command_latency_s(self) -> float:
        """One LAN write's transport, drawn from the readback model's round-trip distribution (same seeded stream)."""
        return self.query_round_trip_s()

    def set_live_voltage(self, vin: float, now: float, *, effective_at: float | None = None) -> None:
        """Change the setpoint of the ON source. Without ``effective_at`` and without a hold-up model the plant
        follows at once (the UVLO ramp's behaviour); otherwise the change is queued for its effective instant and
        the DUT input node decays through the hold-up model when the new level is below it."""
        if not self.source_enabled:
            raise RuntimeError("a live voltage step requires an ON source; use configure while outputs are OFF")
        if vin < 0:
            raise ValueError("source voltage cannot be negative")
        if effective_at is None and self.hold_up is None:
            self.live_changes.append({"monotonic_s": now, "from_V": self.source_voltage, "to_V": vin})
            self.source_voltage = vin
            self._input_changed_at = now
            return
        at = now if effective_at is None else effective_at
        if at < now:
            raise ValueError("a command cannot take effect before it is issued")
        self.live_changes.append({"monotonic_s": now, "from_V": self.source_voltage, "to_V": vin, "effective_at_s": at})
        self.schedule_voltage(vin, at)

    def set_output(self, enabled: bool, now: float, *, effective_at: float | None = None) -> None:
        """Live source output OFF (an interruption: the setpoint is kept) or ON, effective at ``effective_at``."""
        at = now if effective_at is None else effective_at
        if at < now:
            raise ValueError("a command cannot take effect before it is issued")
        self.schedule_output(enabled, at)
        self.output_changes.append({"monotonic_s": now, "to": "ON" if enabled else "OFF", "effective_at_s": at})
