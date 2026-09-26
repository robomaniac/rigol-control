"""Driver registry: maps configured driver names to driver classes."""

from __future__ import annotations

from benchctl.drivers.rigol_dl3000 import RigolDL3000
from benchctl.drivers.rigol_dp800 import RigolDP800


class UnknownDriverError(KeyError):
    """Raised when a configuration names a driver that is not registered."""


_DRIVERS = {
    "rigol_dp800": RigolDP800,
    "rigol_dl3000": RigolDL3000,
}


def get_driver_class(name: str):
    try:
        return _DRIVERS[name]
    except KeyError:
        raise UnknownDriverError(
            f"unknown driver {name!r} (known drivers: {sorted(_DRIVERS)})"
        ) from None
