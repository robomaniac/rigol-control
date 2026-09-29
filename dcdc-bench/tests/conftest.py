"""Shared test defaults.

The render memory gate reads the host's /proc, so its verdict would depend on
whatever else the test host is running. Tests disable it unless they set the
thresholds (or a fake reader) explicitly.
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_memory_gate(monkeypatch):
    monkeypatch.setenv("DCDC_RENDER_MIN_AVAILABLE_MIB", "0")
    monkeypatch.setenv("DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB", "0")
