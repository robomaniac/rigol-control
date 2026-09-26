"""Configuration loading and validation.

All YAML is parsed with ``yaml.safe_load`` and validated with strict
Pydantic v2 models (unknown fields are rejected) before any instrument
connection is attempted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

DeviceKind = Literal["power_supply", "electronic_load"]
DriverName = Literal["rigol_dp800", "rigol_dl3000"]

# A driver is tied to one physical device kind.  Keep this mapping in the
# config layer so an internally inconsistent inventory is rejected before
# any registry import (and therefore before any driver or transport use).
DRIVER_KINDS: dict[DriverName, DeviceKind] = {
    "rigol_dp800": "power_supply",
    "rigol_dl3000": "electronic_load",
}

# Logical setup roles and the device kind each role requires.
ROLE_KINDS: dict[str, DeviceKind] = {
    "supply": "power_supply",
    "load": "electronic_load",
}

_RESOURCE_RE = re.compile(r"^TCPIP0::[A-Za-z0-9_.\-]+::INSTR$")


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded or validated."""


class DeviceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DeviceKind
    driver: DriverName
    resource: str
    expected_serial: str | None = None
    safety_profile: str

    @field_validator("resource")
    @classmethod
    def _validate_resource(cls, value: str) -> str:
        if not _RESOURCE_RE.match(value):
            raise ValueError(
                f"resource {value!r} must have the form 'TCPIP0::<IP>::INSTR'"
            )
        return value

    @model_validator(mode="after")
    def _validate_driver_kind(self) -> "DeviceConfig":
        required_kind = DRIVER_KINDS[self.driver]
        if self.kind != required_kind:
            raise ValueError(
                f"driver {self.driver!r} requires kind {required_kind!r}, "
                f"not {self.kind!r}"
            )
        return self


class LabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    devices: dict[str, DeviceConfig]
    setups: dict[str, dict[str, str]] = {}

    @model_validator(mode="after")
    def _validate_setups(self) -> "LabConfig":
        for setup_name, roles in self.setups.items():
            for role, device_name in roles.items():
                if role not in ROLE_KINDS:
                    raise ValueError(
                        f"setup {setup_name!r}: unknown role {role!r} "
                        f"(known roles: {sorted(ROLE_KINDS)})"
                    )
                if device_name not in self.devices:
                    raise ValueError(
                        f"setup {setup_name!r}: role {role!r} references "
                        f"unknown device {device_name!r}"
                    )
                required_kind = ROLE_KINDS[role]
                actual_kind = self.devices[device_name].kind
                if actual_kind != required_kind:
                    raise ValueError(
                        f"setup {setup_name!r}: role {role!r} requires kind "
                        f"{required_kind!r} but device {device_name!r} has kind "
                        f"{actual_kind!r}"
                    )
        return self


def load_config(path: str | Path) -> LabConfig:
    """Load and strictly validate a lab configuration file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level YAML content must be a mapping")
    try:
        return LabConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration in {path}:\n{exc}") from exc
