"""Results recording for recipe runs.

Each run gets its own timestamped directory under the results base:

    05_Data/Runs/<UTCstamp>_<recipe_name>/
        measurements.jsonl   values + optional per-value verdicts
        execution.jsonl      one record per executed (or failed) action
        run.json             summary with status + pass/fail/error outcome
        measurements.csv     optional, produced by export_csv()
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from benchctl.paths import DEFAULT_RESULTS_DIR

MEASUREMENTS_FILENAME = "measurements.jsonl"
EXECUTION_LOG_FILENAME = "execution.jsonl"
SUMMARY_FILENAME = "run.json"
CSV_FILENAME = "measurements.csv"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", name.strip()) or "recipe"


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(record)) + "\n")


def create_run_dir(recipe_name: str, base: str | Path = DEFAULT_RESULTS_DIR) -> Path:
    """Create and return a fresh 05_Data/Runs/<UTCstamp>_<recipe_name>/ directory."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_path = Path(base)
    safe_name = _sanitize(recipe_name)
    candidate = base_path / f"{stamp}_{safe_name}"
    counter = 1
    while True:
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = base_path / f"{stamp}_{safe_name}_{counter}"
            counter += 1


def append_measurement(
    run_dir: str | Path,
    *,
    save_as: str,
    values: Mapping[str, float],
    setup: str,
    recipe_name: str,
    verdicts: Mapping[str, Mapping[str, Any]] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Append one measure-action record to measurements.jsonl; return it."""
    record: dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "recipe": recipe_name,
        "setup": setup,
        "save_as": save_as,
        "values": dict(values),
    }
    if verdicts is not None:
        record["verdicts"] = {
            label: dict(verdict) for label, verdict in verdicts.items()
        }
    if status is not None:
        record["status"] = status
    _append_jsonl(Path(run_dir) / MEASUREMENTS_FILENAME, record)
    return record


def append_event(
    run_dir: str | Path,
    *,
    phase: str,
    index: int,
    action: str,
    detail: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Append one execution-log record to execution.jsonl; return it."""
    record: dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "phase": phase,
        "index": index,
        "action": action,
        "status": "error" if error is not None else "ok",
    }
    if detail:
        record["detail"] = dict(detail)
    if error is not None:
        record["error"] = error
    _append_jsonl(Path(run_dir) / EXECUTION_LOG_FILENAME, record)
    return record


def write_run_summary(
    run_dir: str | Path,
    *,
    recipe_name: str,
    setup: str,
    parameters: Mapping[str, Any],
    started_at: str,
    finished_at: str,
    status: str,
    outcome: str | None = None,
    error: str | None = None,
    identities: Mapping[str, Any] | None = None,
) -> Path:
    """Write the run.json summary; return its path."""
    summary: dict[str, Any] = {
        "recipe": recipe_name,
        "setup": setup,
        "parameters": dict(parameters),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "outcome": outcome or ("pass" if status == "success" else "error"),
        "error": error,
    }
    if identities:
        summary["identities"] = dict(identities)
    path = Path(run_dir) / SUMMARY_FILENAME
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


def export_csv(run_dir: str | Path, csv_path: str | Path | None = None) -> Path:
    """Convert a run's JSONL measurements to CSV; return the CSV path.

    Existing value columns remain unchanged.  Additional measurement-status
    and per-value verdict/bound columns are included when available.
    """
    source = Path(run_dir) / MEASUREMENTS_FILENAME
    if not source.exists():
        raise FileNotFoundError(f"no measurements file at {source}")
    records = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels: set[str] = set()
    verdict_labels: set[str] = set()
    for record in records:
        labels.update(record.get("values", {}))
        verdict_labels.update(record.get("verdicts", {}))
    verdict_fields = [
        field
        for label in sorted(verdict_labels)
        for field in (
            f"{label}__verdict",
            f"{label}__min",
            f"{label}__max",
            f"{label}__reason",
        )
    ]
    fieldnames = [
        "timestamp",
        "recipe",
        "setup",
        "save_as",
        "measurement_status",
        *sorted(labels),
        *verdict_fields,
    ]

    target = Path(csv_path) if csv_path is not None else Path(run_dir) / CSV_FILENAME
    with open(target, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = {
                "timestamp": record.get("timestamp", ""),
                "recipe": record.get("recipe", ""),
                "setup": record.get("setup", ""),
                "save_as": record.get("save_as", ""),
                "measurement_status": record.get("status", ""),
            }
            row.update(record.get("values", {}))
            for label, verdict in record.get("verdicts", {}).items():
                row[f"{label}__verdict"] = verdict.get("status", "")
                row[f"{label}__min"] = verdict.get("min", "")
                row[f"{label}__max"] = verdict.get("max", "")
                row[f"{label}__reason"] = verdict.get("reason", "")
            writer.writerow(row)
    return target
