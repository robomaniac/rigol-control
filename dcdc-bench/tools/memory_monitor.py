"""Host memory/thermal monitor for the bench computer.

Appends one JSON line per sample (default every 30 s) so the owner can judge
whether the board's RAM is adequate over days of real use, and prints a
summary of the recorded log. Standard library plus dcdc_bench.resources;
nothing here touches instruments or the bench software's own state.

    python -m dcdc_bench.tools.memory_monitor --once            # one sample to stdout
    python tools/memory_monitor.py --log Data/Logs/memory-monitor.jsonl
    python tools/memory_monitor.py --summary Data/Logs/memory-monitor.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dcdc_bench.resources import snapshot
except ImportError:  # run from a checkout without the package installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dcdc_bench.resources import snapshot

LOW_AVAILABLE_MIB = 300.0
CRITICAL_AVAILABLE_MIB = 150.0


def cpu_temperature_c() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


def throttled_flags() -> str | None:
    """Raspberry Pi firmware flags (0x0 is healthy); None when vcgencmd is absent."""
    if not shutil.which("vcgencmd"):
        return None
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip().partition("=")[2] or None


def top_processes(limit: int = 6) -> list[dict]:
    rows = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            rss_kib = None
            for line in (entry / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib = int(line.split()[1])
                    break
            if rss_kib is None:
                continue
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except (OSError, ValueError):
            continue
        rows.append({"pid": int(entry.name), "rss_mib": round(rss_kib / 1024, 1), "command": command[:120]})
    rows.sort(key=lambda row: row["rss_mib"], reverse=True)
    return rows[:limit]


def sample() -> dict:
    record = snapshot()
    record.pop("pid", None)
    record.pop("rss_mib", None)
    record.update(cpu_temp_c=cpu_temperature_c(), throttled=throttled_flags(), top=top_processes())
    return record


def summarize(path: Path) -> dict:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        return {"samples": 0}
    available = [r["mem_available_mib"] for r in records if r.get("mem_available_mib") is not None]
    swap = [r.get("swap_used_mib", 0) or 0 for r in records]
    load = [r.get("load_1m") for r in records if r.get("load_1m") is not None]
    temps = [r["cpu_temp_c"] for r in records if r.get("cpu_temp_c") is not None]
    low = sum(1 for value in available if value < LOW_AVAILABLE_MIB)
    critical = sum(1 for value in available if value < CRITICAL_AVAILABLE_MIB)
    worst = min(records, key=lambda r: r.get("mem_available_mib", float("inf")))
    hog = {}
    for record in records:
        for row in record.get("top", [])[:3]:
            name = row["command"].split()[0].rsplit("/", 1)[-1] if row["command"] else str(row["pid"])
            hog[name] = max(hog.get(name, 0), row["rss_mib"])
    return {
        "samples": len(records),
        "first_utc": records[0]["utc"], "last_utc": records[-1]["utc"],
        "mem_total_mib": records[-1].get("mem_total_mib"),
        "mem_available_min_mib": min(available), "mem_available_median_mib": sorted(available)[len(available) // 2],
        "swap_used_max_mib": max(swap), "load_1m_max": max(load) if load else None,
        "cpu_temp_max_c": max(temps) if temps else None,
        "throttled_ever": sorted({r.get("throttled") for r in records if r.get("throttled") not in (None, "0x0")}),
        f"samples_below_{int(LOW_AVAILABLE_MIB)}_mib": low, f"samples_below_{int(CRITICAL_AVAILABLE_MIB)}_mib": critical,
        "worst_sample": {"utc": worst["utc"], "mem_available_mib": worst.get("mem_available_mib"),
                         "top": worst.get("top", [])[:4]},
        "largest_resident_processes_mib": dict(sorted(hog.items(), key=lambda kv: kv[1], reverse=True)[:8]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, help="Append JSON lines here (creates parent directories)")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between samples when looping")
    parser.add_argument("--once", action="store_true", help="Take one sample and exit")
    parser.add_argument("--summary", type=Path, metavar="LOG", help="Summarize an existing log and exit")
    args = parser.parse_args(argv)
    if args.summary:
        print(json.dumps(summarize(args.summary), indent=2))
        return 0
    if args.interval <= 0:
        parser.error("--interval must be positive")
    while True:
        record = sample()
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        else:
            print(json.dumps(record, default=str))
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
