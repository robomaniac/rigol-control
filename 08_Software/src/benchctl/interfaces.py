"""Shared interfaces, value types, and SCPI error-queue handling."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """A context-managed connection to one instrument.

    Drivers receive a Transport by injection; they never open VISA
    sessions themselves.
    """

    def query(self, command: str) -> str: ...

    def write(self, command: str) -> None: ...

    def close(self) -> None: ...

    def __enter__(self) -> "Transport": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class IdentificationError(ValueError):
    """Raised when a ``*IDN?`` response cannot be parsed."""


class ScpiError(RuntimeError):
    """Raised when an instrument reports errors on its SCPI error queue."""


class ReadbackMismatchError(RuntimeError):
    """Raised when a setting or state readback disagrees with a completed write."""


@dataclass(frozen=True)
class Identification:
    manufacturer: str
    model: str
    serial: str
    firmware: str

    @classmethod
    def from_idn(cls, response: str) -> "Identification":
        """Parse a ``*IDN?`` response of the form 'maker,model,serial,fw'."""
        parts = [part.strip() for part in response.strip().split(",")]
        if len(parts) < 4 or not all(parts[:4]):
            raise IdentificationError(f"malformed *IDN? response: {response!r}")
        manufacturer, model, serial = parts[:3]
        firmware = ",".join(parts[3:])
        return cls(manufacturer, model, serial, firmware)


ERROR_QUEUE_COMMAND = "SYST:ERR?"


def _parse_error_code(response: str) -> int:
    code_text = response.split(",", 1)[0].strip()
    try:
        return int(code_text)
    except ValueError:
        raise ScpiError(
            f"malformed {ERROR_QUEUE_COMMAND} response: {response!r}"
        ) from None


def drain_scpi_errors(transport: Transport, *, max_reads: int = 10) -> None:
    """Read the SCPI error queue until it reports no error.

    Queries ``SYST:ERR?`` up to ``max_reads`` times. Accepts the no-error
    variants ('0,"No error"', '+0,"No error"', '0,No error', ...) by
    parsing the numeric code. Raises :class:`ScpiError` listing every
    error found, or if the queue does not drain within ``max_reads``.
    """
    errors: list[str] = []
    for _ in range(max_reads):
        response = transport.query(ERROR_QUEUE_COMMAND).strip()
        if _parse_error_code(response) == 0:
            break
        errors.append(response)
    else:
        errors.append(f"error queue still not empty after {max_reads} reads")
    if errors:
        raise ScpiError("instrument reported SCPI errors: " + "; ".join(errors))
