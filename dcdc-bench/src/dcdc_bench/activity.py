"""One cross-process lease prevents rendering during bench acquisition."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

from filelock import FileLock, Timeout

_LOCKS: dict[str, FileLock] = {}


def activity_path() -> Path:
    return Path(os.environ.get("DCDC_ACTIVITY_LOCK", str(Path(__file__).resolve().parents[2] / "runs/.bench-activity.lock"))).resolve()


@contextmanager
def bench_activity(kind: str, timeout: float = 0):
    """Fail closed when busy; never queue an armed hardware operation."""
    if kind not in ("acquisition", "report"):
        raise ValueError("Unknown bench activity")
    path = activity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _LOCKS.setdefault(str(path), FileLock(path))
    try:
        lock.acquire(timeout=timeout)
    except Timeout as exc:
        raise RuntimeError("Bench is busy acquiring or rendering; retry explicitly after it finishes") from exc
    try:
        yield
    finally:
        lock.release()
