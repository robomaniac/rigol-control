"""Driver for the Rigol DP800 power supply family.

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

VALID_CHANNELS = (1, 2)

# The DP800 data sheet documents 10 mV/10 mA as the largest programming
# increments among the standard-resolution, two-channel models supported by
# this family driver.  A-models and instruments with HIRES-DP800 are finer.
VOLTAGE_PROGRAMMING_RESOLUTION_V = 0.010
CURRENT_PROGRAMMING_RESOLUTION_A = 0.010

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


class RigolDP800:
    family = "rigol_dp800"

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    # -- read-only ----------------------------------------------------------

    def identify(self) -> Identification:
        return Identification.from_idn(self._transport.query(IDN_COMMAND))

    def get_voltage_setpoint(self, channel: int) -> float:
        self._validate_channel(channel)
        command = f":SOUR{channel}:VOLT?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def get_current_limit(self, channel: int) -> float:
        self._validate_channel(channel)
        command = f":SOUR{channel}:CURR?"
        return _parse_finite_float(self._transport.query(command), command=command)

    def get_output_enabled(self, channel: int) -> bool:
        self._validate_channel(channel)
        command = f":OUTP? CH{channel}"
        return _parse_bool(self._transport.query(command), command=command)

    def measure_voltage(self, channel: int) -> float:
        self._validate_channel(channel)
        command = f":MEAS:VOLT? CH{channel}"
        return _parse_finite_float(self._transport.query(command), command=command)

    def measure_current(self, channel: int) -> float:
        self._validate_channel(channel)
        command = f":MEAS:CURR? CH{channel}"
        return _parse_finite_float(self._transport.query(command), command=command)

    def measure_power(self, channel: int) -> float:
        self._validate_channel(channel)
        command = f":MEAS:POWE? CH{channel}"
        return _parse_finite_float(self._transport.query(command), command=command)

    def check_errors(self) -> None:
        """Drain the SCPI error queue; raise ScpiError if it held errors."""
        drain_scpi_errors(self._transport)

    # -- state-changing -----------------------------------------------------

    def set_voltage(self, channel: int, voltage_v: float) -> None:
        self._validate_channel(channel)
        self._require_output_off(channel)
        requested = float(voltage_v)
        self._transport.write(f":SOUR{channel}:VOLT {requested}")
        self.check_errors()
        actual = self.get_voltage_setpoint(channel)
        if not math.isclose(
            actual,
            requested,
            rel_tol=0.0,
            abs_tol=VOLTAGE_PROGRAMMING_RESOLUTION_V,
        ):
            raise ReadbackMismatchError(
                f"CH{channel} voltage setpoint readback mismatch: "
                f"requested {requested} V, got {actual} V "
                f"(tolerance {VOLTAGE_PROGRAMMING_RESOLUTION_V} V)"
            )

    def set_current_limit(self, channel: int, current_a: float) -> None:
        self._validate_channel(channel)
        self._require_output_off(channel)
        requested = float(current_a)
        self._transport.write(f":SOUR{channel}:CURR {requested}")
        self.check_errors()
        actual = self.get_current_limit(channel)
        if not math.isclose(
            actual,
            requested,
            rel_tol=0.0,
            abs_tol=CURRENT_PROGRAMMING_RESOLUTION_A,
        ):
            raise ReadbackMismatchError(
                f"CH{channel} current limit readback mismatch: "
                f"requested {requested} A, got {actual} A "
                f"(tolerance {CURRENT_PROGRAMMING_RESOLUTION_A} A)"
            )

    def output_on(self, channel: int) -> None:
        self._validate_channel(channel)
        self._transport.write(f":OUTP CH{channel},ON")
        self.check_errors()
        self._verify_output_enabled(channel, expected=True)

    def output_off(self, channel: int) -> None:
        self._validate_channel(channel)
        self._transport.write(f":OUTP CH{channel},OFF")
        self.check_errors()
        self._verify_output_enabled(channel, expected=False)

    def all_outputs_off(self) -> None:
        first_error: BaseException | None = None
        for channel in VALID_CHANNELS:
            try:
                self.output_off(channel)
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                else:
                    first_error.add_note(
                        f"CH{channel} output-off also failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
        if first_error is not None:
            raise first_error

    # -- internals ----------------------------------------------------------

    def _require_output_off(self, channel: int) -> None:
        if self.get_output_enabled(channel):
            raise RuntimeError(
                f"CH{channel} output is ON; turn it OFF before changing "
                "voltage or current limit"
            )

    def _verify_output_enabled(self, channel: int, *, expected: bool) -> None:
        actual = self.get_output_enabled(channel)
        if actual != expected:
            expected_text = "ON" if expected else "OFF"
            actual_text = "ON" if actual else "OFF"
            raise ReadbackMismatchError(
                f"CH{channel} output state readback mismatch: "
                f"expected {expected_text}, got {actual_text}"
            )

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if channel not in VALID_CHANNELS:
            raise ValueError(
                f"channel must be one of {VALID_CHANNELS}, got {channel!r}"
            )
