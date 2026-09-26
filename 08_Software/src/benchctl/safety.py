"""Safety profiles: strict parsing and setpoint validation.

Safety profiles describe manually maintained physical limits for each
instrument (see ``08_Software/config/safety_profiles.yaml``). Any command that would
apply a setpoint must validate it here first; validation failures raise
:class:`SafetyError` and nothing is sent to the instrument.

Software limits are a first line of defence only — they do not replace
the instruments' hardware OVP/OCP/OPP protections.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from benchctl.config import DeviceConfig


class SafetyError(Exception):
    """Raised when a safety profile is invalid or a setpoint violates it."""


class SupplyChannelLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_voltage_v: float = Field(gt=0, allow_inf_nan=False)
    max_current_a: float = Field(gt=0, allow_inf_nan=False)
    max_power_w: float = Field(gt=0, allow_inf_nan=False)


class SupplyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["power_supply"]
    channels: dict[int, SupplyChannelLimits]


class LoadProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["electronic_load"]
    max_voltage_v: float = Field(gt=0, allow_inf_nan=False)
    max_current_a: float = Field(gt=0, allow_inf_nan=False)
    max_power_w: float = Field(gt=0, allow_inf_nan=False)
    allowed_modes: list[str]


# Discriminated on "type" so unknown profile types are rejected with a
# clear validation error instead of being coerced into the wrong model.
SafetyProfile = Annotated[SupplyProfile | LoadProfile, Field(discriminator="type")]


class _SafetyProfilesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profiles: dict[str, SafetyProfile]


def load_safety_profiles(path: str | Path) -> dict[str, SupplyProfile | LoadProfile]:
    """Load and strictly validate a safety profiles file.

    Raises :class:`SafetyError` if the file cannot be read, is not valid
    YAML, or fails strict schema validation (unknown fields, unknown
    profile types, wrong schema version).
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SafetyError(f"cannot read safety profiles file {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SafetyError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SafetyError(f"{path}: top-level YAML content must be a mapping")
    try:
        parsed = _SafetyProfilesFile.model_validate(raw)
    except ValidationError as exc:
        raise SafetyError(f"invalid safety profiles in {path}:\n{exc}") from exc
    return dict(parsed.profiles)


def get_device_safety_profile(
    profiles: Mapping[str, SupplyProfile | LoadProfile],
    device_name: str,
    device: "DeviceConfig",
) -> SupplyProfile | LoadProfile:
    """Resolve a device's profile and enforce device/profile type compatibility."""
    profile = profiles.get(device.safety_profile)
    if profile is None:
        raise SafetyError(
            f"device {device_name!r} references missing safety profile "
            f"{device.safety_profile!r} (available profiles: {sorted(profiles)})"
        )
    if profile.type != device.kind:
        raise SafetyError(
            f"safety profile {device.safety_profile!r} has type {profile.type!r}, "
            f"but device {device_name!r} has kind {device.kind!r}"
        )
    return profile


def _check_value(name: str, value: float, maximum: float, unit: str) -> None:
    if not math.isfinite(value):
        raise SafetyError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise SafetyError(f"{name} must not be negative, got {value} {unit}")
    if value > maximum:
        raise SafetyError(
            f"{name} {value} {unit} exceeds the profile limit of {maximum} {unit}"
        )


def validate_supply_setpoint(
    profile: SupplyProfile,
    channel: int,
    voltage_v: float | None = None,
    current_a: float | None = None,
) -> None:
    """Validate a power-supply setpoint against its safety profile.

    Raises :class:`SafetyError` if the channel is not in the profile or
    any provided value is negative, non-finite, or above the limit.
    Values exactly at the limit are allowed.
    """
    limits = profile.channels.get(channel)
    if limits is None:
        raise SafetyError(
            f"channel {channel} is not covered by the safety profile "
            f"(covered channels: {sorted(profile.channels)})"
        )
    if voltage_v is not None:
        _check_value("voltage", voltage_v, limits.max_voltage_v, "V")
    if current_a is not None:
        _check_value("current", current_a, limits.max_current_a, "A")
    if voltage_v is not None and current_a is not None:
        power_w = voltage_v * current_a
        _check_value("voltage-current product", power_w, limits.max_power_w, "W")


def validate_load_setpoint(
    profile: LoadProfile,
    mode: str | None = None,
    current_a: float | None = None,
    max_voltage_v: float | None = None,
) -> None:
    """Validate an electronic-load setpoint against its safety profile.

    Raises :class:`SafetyError` if the mode is not allowed by the profile
    or a declared current/maximum expected voltage is negative, non-finite,
    or above its limit. Constant-current operation requires an explicit
    expected maximum voltage so its worst-case power can be checked. Values
    exactly at the limits are allowed.
    """
    if mode is not None and mode not in profile.allowed_modes:
        raise SafetyError(
            f"mode {mode!r} is not allowed by the safety profile "
            f"(allowed modes: {profile.allowed_modes})"
        )
    if mode == "cc" and max_voltage_v is None:
        raise SafetyError(
            "constant-current mode requires an explicit maximum expected voltage"
        )
    if current_a is not None:
        _check_value("current", current_a, profile.max_current_a, "A")
    if max_voltage_v is not None:
        if max_voltage_v <= 0:
            raise SafetyError(
                "maximum expected voltage must be greater than zero"
            )
        _check_value(
            "maximum expected voltage",
            max_voltage_v,
            profile.max_voltage_v,
            "V",
        )
    if current_a is not None and max_voltage_v is not None:
        power_w = current_a * max_voltage_v
        _check_value("worst-case load power", power_w, profile.max_power_w, "W")


def validate_load_measurements(
    profile: LoadProfile,
    *,
    max_voltage_v: float,
    voltage_v: float,
    current_a: float,
    power_w: float,
) -> None:
    """Validate the immediate measurements taken after enabling a load.

    All three measurements must be finite and non-negative. The measured
    voltage may not exceed the run's declared bound, and measured current
    and power may not exceed the physical profile limits.
    """
    if max_voltage_v <= 0:
        raise SafetyError("maximum expected voltage must be greater than zero")
    _check_value(
        "maximum expected voltage",
        max_voltage_v,
        profile.max_voltage_v,
        "V",
    )
    measurements = {
        "measured voltage": (voltage_v, "V"),
        "measured current": (current_a, "A"),
        "measured power": (power_w, "W"),
    }
    for name, (value, unit) in measurements.items():
        if not math.isfinite(value):
            raise SafetyError(f"{name} must be finite, got {value!r} {unit}")
    _check_value("measured voltage", voltage_v, profile.max_voltage_v, "V")
    _check_value("measured current", current_a, profile.max_current_a, "A")
    _check_value("measured power", power_w, profile.max_power_w, "W")
    if voltage_v > max_voltage_v:
        raise SafetyError(
            f"measured voltage {voltage_v} V exceeds the declared maximum "
            f"expected voltage of {max_voltage_v} V"
        )
