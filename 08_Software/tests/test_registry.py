"""Driver registry tests."""

import pytest

from benchctl.drivers.rigol_dl3000 import RigolDL3000
from benchctl.drivers.rigol_dp800 import RigolDP800
from benchctl.registry import UnknownDriverError, get_driver_class


def test_dp800_resolves():
    assert get_driver_class("rigol_dp800") is RigolDP800


def test_dl3000_resolves():
    assert get_driver_class("rigol_dl3000") is RigolDL3000


def test_unknown_driver_raises():
    with pytest.raises(UnknownDriverError):
        get_driver_class("rigol_ds1000z")
