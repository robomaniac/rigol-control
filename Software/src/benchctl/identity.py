"""Shared instrument identity and configured-serial verification."""

from __future__ import annotations

from typing import Any

from benchctl.config import DeviceConfig
from benchctl.interfaces import Identification


class SerialMismatchError(RuntimeError):
    """Raised when an instrument does not match its configured serial."""

    def __init__(
        self,
        *,
        device_name: str,
        expected_serial: str,
        identification: Identification,
    ) -> None:
        self.device_name = device_name
        self.expected_serial = expected_serial
        self.identification = identification
        super().__init__(
            f"serial mismatch for {device_name!r}: expected {expected_serial!r}, "
            f"but {identification.manufacturer} {identification.model} reported "
            f"{identification.serial!r}"
        )


def verify_expected_serial(
    device_name: str,
    device: DeviceConfig,
    identification: Identification,
) -> Identification:
    """Return an identity only when its serial matches the inventory."""
    expected = device.expected_serial
    if expected is not None and identification.serial != expected:
        raise SerialMismatchError(
            device_name=device_name,
            expected_serial=expected,
            identification=identification,
        )
    return identification


def identify_and_verify(
    device_name: str,
    device: DeviceConfig,
    driver: Any,
) -> Identification:
    """Identify a live instrument, then enforce ``expected_serial``."""
    return verify_expected_serial(device_name, device, driver.identify())
