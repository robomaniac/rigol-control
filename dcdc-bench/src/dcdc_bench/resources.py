"""Host resource telemetry, a render memory gate and descendant hygiene.

Standard library only; nothing here touches instruments. ``snapshot`` reads
/proc, ``MemoryGate`` compares it with thresholds from the environment, and
the sweep helpers find and stop processes left behind in a session or process
group that a finished child owned. Every reader is injectable for tests.
"""
from __future__ import annotations

import json
import os
import resource
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PHASES = ("start", "end", "deferred", "refused", "survivors")
ENV_MIN_AVAILABLE_MIB = "DCDC_RENDER_MIN_AVAILABLE_MIB"
ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB = "DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB"
DEFAULT_MIN_AVAILABLE_MIB = 150.
DEFAULT_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB = 600.
PROC = Path("/proc")


def read_proc(relative: str) -> str:
    """Return one /proc text file; the default reader behind every probe."""
    return (PROC / relative).read_text()


def _mib(kib) -> float:
    return round(int(kib) / 1024, 1)


def _kib_fields(text: str) -> dict[str, int]:
    """``Key:   1234 kB`` lines (meminfo, status) as integers; other lines are skipped."""
    fields: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        parts = rest.split()
        if separator and parts and parts[0].lstrip("-").isdigit():
            fields[key.strip()] = int(parts[0])
    return fields


def snapshot(pid: int | None = None, *, reader: Callable[[str], str] | None = None) -> dict:
    """Memory, swap, own (or ``pid``) resident set, load average and both clocks, in MiB."""
    reader = reader or read_proc
    pid = os.getpid() if pid is None else int(pid)
    meminfo = _kib_fields(reader("meminfo"))
    try:
        status = _kib_fields(reader(f"{pid}/status"))
    except OSError:
        status = {}
    try:
        load = [float(value) for value in reader("loadavg").split()[:3]]
    except (OSError, ValueError):
        load = [None, None, None]
    swap_total, swap_free = meminfo.get("SwapTotal", 0), meminfo.get("SwapFree", 0)
    available = meminfo.get("MemAvailable", 0)
    return {"utc": datetime.now(timezone.utc).isoformat(), "monotonic_s": round(time.monotonic(), 3), "pid": pid,
            "mem_total_mib": _mib(meminfo.get("MemTotal", 0)), "mem_available_mib": _mib(available),
            "mem_available_plus_swap_free_mib": _mib(available + swap_free),
            "swap_total_mib": _mib(swap_total), "swap_free_mib": _mib(swap_free),
            "swap_used_mib": _mib(swap_total - swap_free),
            "rss_mib": _mib(status["VmRSS"]) if "VmRSS" in status else None,
            "load_1m": load[0], "load_5m": load[1], "load_15m": load[2]}


def children_peak_rss_mib() -> float:
    """Largest resident set of any waited-for descendant so far (Linux reports KiB)."""
    return _mib(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


def log_event(path: Path | str, task: str, phase: str, *, snap: dict | None = None,
              reader: Callable[[str], str] | None = None, **fields) -> dict:
    """Append one JSON line: the snapshot plus task, phase and any extra fields."""
    if phase not in PHASES:
        raise ValueError(f"Unknown resource phase {phase!r}; expected one of {PHASES}")
    record = dict(snap if snap is not None else snapshot(reader=reader))
    record.update(task=task, phase=phase)
    record.update(fields)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return record


def try_log_event(path: Path | str | None, task: str, phase: str, **fields) -> dict | None:
    """Telemetry must never change an outcome: skip a missing path, swallow I/O errors."""
    if path is None:
        return None
    try:
        return log_event(path, task, phase, **fields)
    except OSError:
        return None


class MemoryGate:
    """Refuse heavy rendering when MemAvailable or MemAvailable+SwapFree is too small.

    Thresholds come from ``DCDC_RENDER_MIN_AVAILABLE_MIB`` (default 150) and
    ``DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB`` (default 600) unless given
    explicitly. Setting both to 0 disables the gate.
    """

    def __init__(self, min_available_mib: float | None = None,
                 min_available_plus_swap_free_mib: float | None = None, *,
                 reader: Callable[[str], str] | None = None, environ=None):
        environ = os.environ if environ is None else environ
        self.min_available_mib = self._threshold(
            min_available_mib, environ, ENV_MIN_AVAILABLE_MIB, DEFAULT_MIN_AVAILABLE_MIB)
        self.min_available_plus_swap_free_mib = self._threshold(
            min_available_plus_swap_free_mib, environ, ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB,
            DEFAULT_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB)
        self.reader = reader

    @staticmethod
    def _threshold(value, environ, name: str, default: float) -> float:
        raw = environ.get(name, default) if value is None else value
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number of MiB (0 disables the check); got {raw!r}") from None
        if not number >= 0:
            raise ValueError(f"{name} must be zero or positive MiB; got {raw!r}")
        return number

    @property
    def enabled(self) -> bool:
        return self.min_available_mib > 0 or self.min_available_plus_swap_free_mib > 0

    def thresholds(self) -> dict:
        return {"min_available_mib": self.min_available_mib,
                "min_available_plus_swap_free_mib": self.min_available_plus_swap_free_mib,
                "enabled": self.enabled,
                "environment": {ENV_MIN_AVAILABLE_MIB: os.environ.get(ENV_MIN_AVAILABLE_MIB),
                                ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB: os.environ.get(ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB)}}

    def check(self) -> tuple[bool, str, dict]:
        """(ok, stable reason text, snapshot). The numbers live in the snapshot."""
        snap = snapshot(reader=self.reader)
        if not self.enabled:
            return True, "memory gate disabled", snap
        reasons = []
        if self.min_available_mib > 0 and snap["mem_available_mib"] < self.min_available_mib:
            reasons.append(f"MemAvailable below {self.min_available_mib:g} MiB")
        if (self.min_available_plus_swap_free_mib > 0
                and snap["mem_available_plus_swap_free_mib"] < self.min_available_plus_swap_free_mib):
            reasons.append(f"MemAvailable+SwapFree below {self.min_available_plus_swap_free_mib:g} MiB")
        if reasons:
            return False, "; ".join(reasons), snap
        return True, "memory thresholds met", snap


def _stat(entry: Path) -> dict:
    """/proc/<pid>/stat split around the last ')' because comm may contain spaces."""
    head, _, tail = (entry / "stat").read_text().rpartition(")")
    pid, _, comm = head.partition(" (")
    fields = tail.split()
    return {"pid": int(pid), "comm": comm, "state": fields[0], "ppid": int(fields[1]),
            "pgrp": int(fields[2]), "session": int(fields[3])}


def session_survivors(sid_or_pgid: int, *, proc: Path = PROC) -> list[dict]:
    """Live processes whose process group or session is ``sid_or_pgid``; zombies excluded."""
    target = int(sid_or_pgid)
    if target <= 1:
        return []
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            info = _stat(entry)
        except (OSError, ValueError, IndexError):
            continue
        if info["state"] != "Z" and target in (info["pgrp"], info["session"]):
            found.append(info)
    return sorted(found, key=lambda item: item["pid"])


def _wait_gone(pgid: int, timeout_s: float, proc: Path) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = session_survivors(pgid, proc=proc)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(.05)


def _signal_all(pgid: int, processes: list[dict], sig: signal.Signals) -> list[int]:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    for item in processes:
        if item["pgrp"] != pgid:  # same session, different group: signal it directly
            try:
                os.kill(item["pid"], sig)
            except (ProcessLookupError, PermissionError):
                pass
    return [item["pid"] for item in processes]


def terminate_group(pgid: int, grace_s: float = 5., *, proc: Path = PROC) -> dict:
    """SIGTERM the group (and any session member that left it), wait, then SIGKILL."""
    pgid = int(pgid)
    if pgid <= 1:
        raise ValueError("Refusing to signal process group 0/1")
    found = session_survivors(pgid, proc=proc)
    result = {"pgid": pgid, "found": found, "signalled": [], "killed": [], "remaining": []}
    if not found:
        return result
    result["signalled"] = _signal_all(pgid, found, signal.SIGTERM)
    remaining = _wait_gone(pgid, grace_s, proc)
    if remaining:
        result["killed"] = _signal_all(pgid, remaining, signal.SIGKILL)
        remaining = _wait_gone(pgid, min(grace_s, 2.), proc)
    result["remaining"] = remaining
    return result


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(snapshot(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
