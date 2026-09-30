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


@pytest.fixture(autouse=True)
def _isolated_bench_activity_lock(tmp_path, monkeypatch):
    """Unit tests must never contend for the real bench lease.

    Rendering and acquisition serialize on runs/.bench-activity.lock; a demo
    build or the bench UI rendering on the same machine would otherwise make
    unrelated render tests time out. Module fixtures that need their own path
    still override this.
    """
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "bench-activity.lock"))
