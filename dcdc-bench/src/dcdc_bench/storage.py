"""Append-only acquisition evidence with fsync and atomic JSON finalization."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class PersistenceError(OSError):
    """A measurement could not be durably recorded."""


def atomic_json(path: Path, value: Any) -> None:
    """Replace one structured artifact atomically; reject NaN and infinity."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise PersistenceError(f"cannot finalize {path.name}: {exc}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class RunStore:
    """One process writes evidence; readers do not change acquisition files.

    Every JSONL record is flushed and fsynced before acquisition continues.
    File replacement is atomic; durability across host/power failure remains
    dependent on the filesystem and storage hardware.
    """

    FILES = {"samples": "raw/samples.jsonl", "events": "raw/events.jsonl",
             "points": "raw/point_events.jsonl"}

    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self, request: dict, plan: dict, run: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "raw").mkdir()
        (self.path / "attachments" / "originals").mkdir(parents=True)
        atomic_json(self.path / "request.json", request)
        atomic_json(self.path / "plan.json", plan)
        atomic_json(self.path / "run.json", run)
        atomic_json(self.path / "attachments/manifest.json", {"assets": []})
        for relative in self.FILES.values():
            (self.path / relative).touch(exist_ok=False)

    def append(self, stream: str, value: dict) -> None:
        relative = self.FILES[stream]
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"
        try:
            with (self.path / relative).open("a", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise PersistenceError(f"cannot append {relative}: {exc}") from exc

    def finalize(self, run: dict) -> None:
        atomic_json(self.path / "run.json", run)
        paths = ["request.json", "plan.json", "run.json", *self.FILES.values(),
                 "attachments/manifest.json"]
        # Real adapters may keep a separate SCPI transcript. The transport is
        # closed before finalization, so flush its completed bytes to storage
        # and cover them in the same manifest. Existing finalized runs remain
        # untouched; mock runs need not contain a hardware transcript.
        transcript = self.path / "scpi.jsonl"
        if transcript.exists():
            try:
                with transcript.open("rb") as handle:
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise PersistenceError(f"cannot persist scpi.jsonl: {exc}") from exc
            paths.append("scpi.jsonl")
        hashes = {name: hashlib.sha256((self.path / name).read_bytes()).hexdigest()
                  for name in paths}
        atomic_json(self.path / "integrity.json", {
            "schema_version": "1.0", "algorithm": "sha256", "files": hashes,
            "scope": "finalized acquisition evidence only",
        })


def verify_integrity(run_dir: Path) -> None:
    """Fail on missing/changed evidence or an unsafe manifest path."""
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "integrity.json").read_text())
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid integrity path")
        actual = hashlib.sha256((run_dir / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"acquisition integrity mismatch: {name}")
