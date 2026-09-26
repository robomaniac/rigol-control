"""Driver for the Rigol DL3000 electronic load family.

Mechanism only: no limit enforcement happens here (a separate safety
layer owns limits), and physical limits are never inferred from the
reported model name. ``*RST`` is never sent. Every state-changing method
drains the SCPI error queue afterwards so failed writes are never
silently trusted.
"""

from __future__ import annotations

import math

from benchctl.interfaces import (
    Identification,
    ReadbackMismatchError,
    Transport,
    drain_scpi_errors,
)

IDN_COMMAND = "*IDN?"

MODE_TO_SCPI_FUNCTION = {
    "cc": "CURR",
    "cv": "VOLT",
    "cr": "RES",
    "cp": "POW",
}

# The DL3000 data sheet specifies 1 mA CC programming resolution for every
# model and current range in the family.
CURRENT_PROGRAMMING_RESOLUTION_A = 0.001

_SCPI_FUNCTION_TO_MODE = {
    "CC": "cc",
    "CURR": "cc",
    "CURRENT": "cc",
    "CV": "cv",
    "VOLT": "cv",
    "VOLTAGE": "cv",
    "CR": "cr",
    "RES": "cr",
    "RESISTANCE": "cr",
    "CP": "cp",
    "POW": "cp",
    "POWER": "cp",
}
_TRUE_RESPONSES = frozenset({"1", "+1", "ON", "TRUE"})
_FALSE_RESPONSES = frozenset({"0", "+0", "OFF", "FALSE"})


def _parse_finite_float(response: str, *, command: str) -> float:
    try:
        value = float(response.strip())
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"malformed {command} response: {response!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"malformed {command} response: {response!r}")
    return value


def _parse_bool(response: str, *, command: str) -> bool:
    try:
        token = response.strip().upper()
    except AttributeError:
        raise ValueError(f"malformed {command} response: {response!r}") from None
    if token in _TRUE_RESPONSES:
        return True
    if token in _FALSE_RESPONSES:
        return False
    raise ValueError(f"malformed {command} response: {response!r}")


class RigolDL3000:
    family = "rigol_dl3000"

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    # -- read-only ----------------------------------------------------------

    def identify(self) -> Identification:
        return Identification.from_idn(self._transport.query(IDN_COMMAND))

    def get_mode(self) -> str:
        command = ":SOUR:FUNC?"
        response = self._transport.query(command)
        try:
            token = response.strip().upper()
        except AttributeError:
            raise ValueError(
                f"malformed {command} response: {response!r}"
            ) from None
        try:
            return _SCPI_FUNCTION_TO_MODE[token]
        except KeyError:
            raise ValueError(
                f"malformed {command} response: {response!r}"
            ) from None

    def get_current_setpoint(self) -> float:
        command = ":SOUR:CURR:LEV:IMM?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def get_input_enabled(self) -> bool:
        command = ":SOUR:INP:STAT?"
        return _parse_bool(self._transport.query(command), command=command)

    def measure_voltage(self) -> float:
        command = ":MEAS:VOLT?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def measure_current(self) -> float:
        command = ":MEAS:CURR?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def measure_power(self) -> float:
        command = ":MEAS:POW?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def check_errors(self) -> None:
        """Drain the SCPI error queue; raise ScpiError if it held errors."""
        drain_scpi_errors(self._transport)

    # -- state-changing -----------------------------------------------------

    def set_mode(self, mode: str) -> None:
        try:
            normalized_mode = mode.lower()
            function = MODE_TO_SCPI_FUNCTION[normalized_mode]
        except (KeyError, AttributeError):
            raise ValueError(
                f"mode must be one of {sorted(MODE_TO_SCPI_FUNCTION)}, "
                f"got {mode!r}"
            ) from None
        # Function (CC/CV/CR/CP) and operation/display mode are separate.
        # Request fixed operation; WAV is also a documented waveform display
        # for normal loading and may remain in the readback after this write.
        self._transport.write(":SOUR:FUNC:MODE FIX")
        self.check_errors()
        command = ":SOUR:FUNC:MODE?"
        response = self._transport.query(command)
        try:
            operation_mode = response.strip().upper()
        except AttributeError:
            raise ValueError(
                f"malformed {command} response: {response!r}"
            ) from None
        if operation_mode not in {"FIX", "WAV"}:
            raise ReadbackMismatchError(
                f"load operation mode readback mismatch: expected FIX or WAV, "
                f"got {operation_mode!r}"
            )
        self._transport.write(f":SOUR:FUNC {function}")
        self.check_errors()
        actual = self.get_mode()
        if actual != normalized_mode:
            raise ReadbackMismatchError(
                f"load mode readback mismatch: expected {normalized_mode}, "
                f"got {actual}"
            )

    def set_current(self, current_a: float) -> None:
        requested = float(current_a)
        self._transport.write(f":SOUR:CURR:LEV:IMM {requested}")
        self.check_errors()
        actual = self.get_current_setpoint()
        if not math.isclose(
            actual,
            requested,
            rel_tol=0.0,
            abs_tol=CURRENT_PROGRAMMING_RESOLUTION_A,
        ):
            raise ReadbackMismatchError(
                f"load current setpoint readback mismatch: "
                f"requested {requested} A, got {actual} A "
                f"(tolerance {CURRENT_PROGRAMMING_RESOLUTION_A} A)"
            )

    def input_on(self) -> None:
        self._transport.write(":SOUR:INP:STAT ON")
        self.check_errors()
        self._verify_input_enabled(expected=True)

    def input_off(self) -> None:
        self._transport.write(":SOUR:INP:STAT OFF")
        self.check_errors()
        self._verify_input_enabled(expected=False)

    def _verify_input_enabled(self, *, expected: bool) -> None:
        actual = self.get_input_enabled()
        if actual != expected:
            expected_text = "ON" if expected else "OFF"
            actual_text = "ON" if actual else "OFF"
            raise ReadbackMismatchError(
                f"load input state readback mismatch: "
                f"expected {expected_text}, got {actual_text}"
            )
