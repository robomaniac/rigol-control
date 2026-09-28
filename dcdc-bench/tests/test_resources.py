"""Resource telemetry and the render memory gate work from injected /proc text; stdlib only."""
from __future__ import annotations

from datetime import datetime
import json
import os
import subprocess

import pytest

from dcdc_bench import resources
from dcdc_bench.resources import (ENV_MIN_AVAILABLE_MIB, ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, MemoryGate,
                                  log_event, session_survivors, snapshot, terminate_group)

MEMINFO = ("MemTotal:         926820 kB\nMemFree:           39076 kB\nMemAvailable:     {available} kB\n"
           "Buffers:            1948 kB\nSwapTotal:       1713144 kB\nSwapFree:         {swap_free} kB\n")


def reader(available_kib, swap_free_kib, rss_kib=20480):
    def read(relative):
        if relative == "meminfo":
            return MEMINFO.format(available=available_kib, swap_free=swap_free_kib)
        if relative == "loadavg":
            return "0.53 1.01 0.79 17/315 28443\n"
        if relative.endswith("/status"):
            return f"Name:\tpython\nUid:\t1000\t1000\t1000\t1000\nVmHWM:\t{rss_kib} kB\nVmRSS:\t{rss_kib} kB\n"
        raise FileNotFoundError(relative)
    return read


def test_snapshot_reports_memory_swap_rss_and_load_in_mib():
    snap = snapshot(1234, reader=reader(153600, 716800, rss_kib=51200))
    assert snap["pid"] == 1234
    assert snap["mem_total_mib"] == 905.1 and snap["mem_available_mib"] == 150.0
    assert snap["swap_total_mib"] == 1673.0 and snap["swap_free_mib"] == 700.0 and snap["swap_used_mib"] == 973.0
    assert snap["mem_available_plus_swap_free_mib"] == 850.0 and snap["rss_mib"] == 50.0
    assert (snap["load_1m"], snap["load_5m"], snap["load_15m"]) == (.53, 1.01, .79)
    assert isinstance(snap["monotonic_s"], float) and datetime.fromisoformat(snap["utc"]).tzinfo is not None
    own = snapshot()
    assert own["pid"] == os.getpid() and own["rss_mib"] > 0 and own["mem_total_mib"] > 0


@pytest.mark.parametrize("available_kib,swap_free_kib,ok,reason", [
    (204800, 512000, True, "memory thresholds met"),
    (102400, 1024000, False, "MemAvailable below 150 MiB"),
    (204800, 307200, False, "MemAvailable+SwapFree below 600 MiB"),
    (102400, 102400, False, "MemAvailable below 150 MiB; MemAvailable+SwapFree below 600 MiB"),
])
def test_gate_checks_both_thresholds(available_kib, swap_free_kib, ok, reason):
    gate = MemoryGate(150, 600, reader=reader(available_kib, swap_free_kib))
    verdict, text, snap = gate.check()
    assert (verdict, text) == (ok, reason)
    assert snap["mem_available_mib"] == available_kib / 1024 and gate.enabled
    assert gate.thresholds()["min_available_mib"] == 150 and gate.thresholds()["min_available_plus_swap_free_mib"] == 600


def test_gate_thresholds_come_from_the_environment_and_zero_disables(monkeypatch):
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "0")
    monkeypatch.setenv(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, "0")
    gate = MemoryGate(reader=reader(1024, 1024))
    assert not gate.enabled and gate.check()[:2] == (True, "memory gate disabled")
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "300")
    gate = MemoryGate(reader=reader(204800, 0))
    assert (gate.min_available_mib, gate.min_available_plus_swap_free_mib) == (300, 0)
    assert gate.check()[1] == "MemAvailable below 300 MiB"
    monkeypatch.delenv(ENV_MIN_AVAILABLE_MIB)
    monkeypatch.delenv(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB)
    gate = MemoryGate(reader=reader(204800, 512000))
    assert (gate.min_available_mib, gate.min_available_plus_swap_free_mib) == (150, 600) and gate.check()[0]
    monkeypatch.setenv(ENV_MIN_AVAILABLE_MIB, "lots")
    with pytest.raises(ValueError, match=ENV_MIN_AVAILABLE_MIB):
        MemoryGate()
    with pytest.raises(ValueError, match="zero or positive"):
        MemoryGate(-1, 0)


def test_log_event_appends_one_json_line_with_the_required_fields(tmp_path):
    path = tmp_path / "logs" / "resources.jsonl"
    log_event(path, "acquisition", "start", reader=reader(153600, 716800), job_id="j1")
    log_event(path, "acquisition", "end", reader=reader(153600, 716800), duration_s=12.5, child_pid=99,
              child_peak_rss_mib=210.5)
    start, end = [json.loads(line) for line in path.read_text().splitlines()]
    for key in ("utc", "monotonic_s", "pid", "task", "phase", "mem_available_mib", "swap_used_mib", "rss_mib"):
        assert key in start and key in end
    assert start["phase"] == "start" and "duration_s" not in start and start["job_id"] == "j1"
    assert end["phase"] == "end" and end["duration_s"] == 12.5
    assert end["child_pid"] == 99 and end["child_peak_rss_mib"] == 210.5
    assert end["pid"] == os.getpid() and end["mem_available_mib"] == 150.0 and end["swap_used_mib"] == 973.0
    assert datetime.fromisoformat(end["utc"]) >= datetime.fromisoformat(start["utc"])
    with pytest.raises(ValueError, match="phase"):
        log_event(path, "acquisition", "bogus")
    assert resources.try_log_event(None, "acquisition", "start") is None
    assert len(path.read_text().splitlines()) == 2


def test_session_survivors_and_terminate_group_stop_a_real_orphan():
    child = subprocess.Popen(["sh", "-c", "sleep 300 & exit 0"], start_new_session=True, stdin=subprocess.DEVNULL)
    assert child.wait(timeout=10) == 0
    survivors = session_survivors(child.pid)
    assert len(survivors) == 1 and survivors[0]["pgrp"] == child.pid and survivors[0]["session"] == child.pid
    assert survivors[0]["comm"] in ("sh", "sleep") and survivors[0]["pid"] != os.getpid()
    outcome = terminate_group(child.pid, grace_s=5)
    assert outcome["found"] == survivors and outcome["signalled"] == [survivors[0]["pid"]]
    assert outcome["remaining"] == [] and outcome["killed"] == []
    assert session_survivors(child.pid) == []
    assert terminate_group(child.pid)["found"] == []
    assert session_survivors(0) == [] and session_survivors(1) == []
    with pytest.raises(ValueError):
        terminate_group(1)


def test_module_entry_point_prints_one_snapshot(capsys):
    assert resources.main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["pid"] == os.getpid() and printed["mem_total_mib"] > 0 and "swap_used_mib" in printed
