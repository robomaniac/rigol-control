"""VISA transport with per-instrument process locking and JSONL logging.

The transport is command-agnostic: what may be sent to an instrument is
decided by the drivers. Every write and query is appended to a JSONL log.
"""

from __future__ import annotations

import fcntl
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO

from benchctl.paths import DEFAULT_LOG_PATH
DEFAULT_LOCK_DIR = Path("/tmp")
DEFAULT_TIMEOUT_MS = 5000


class TransportError(RuntimeError):
    """Raised for transport-level failures."""


class DeviceLockError(TransportError):
    """Raised when another process holds the instrument lock."""


def _sanitize(resource: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", resource)


class VisaTransport:
    """A context-managed VISA session for a single instrument.

    While open, an exclusive ``flock`` on a per-instrument lock file
    prevents other benchctl processes on this machine from talking to the
    same instrument. Every command is appended to a JSONL log with a UTC
    timestamp, device name, resource, command, response or error, and
    duration (writes have no response field). Credentials are never part
    of SCPI traffic and are never logged.

    The VISA I/O timeout is explicit and configurable via ``timeout_ms``
    and is applied to the session when it is opened.
    """

    def __init__(
        self,
        device_name: str,
        resource: str,
        *,
        resource_manager: Any | None = None,
        log_path: str | Path = DEFAULT_LOG_PATH,
        lock_dir: str | Path = DEFAULT_LOCK_DIR,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        self.device_name = device_name
        self.resource = resource
        self.timeout_ms = timeout_ms
        self._resource_manager = resource_manager
        self._log_path = Path(log_path)
        self._lock_path = Path(lock_dir) / f"benchctl-{_sanitize(resource)}.lock"
        self._lock_file: IO[str] | None = None
        self._session: Any | None = None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> "VisaTransport":
        if self._session is not None:
            return self
        self._acquire_lock()
        try:
            if self._resource_manager is None:
                import pyvisa

                self._resource_manager = pyvisa.ResourceManager("@py")
            session = self._resource_manager.open_resource(self.resource)
            session.timeout = self.timeout_ms
            self._session = session
        except Exception:
            self._release_lock()
            raise
        return self

    def close(self) -> None:
        try:
            if self._session is not None:
                self._session.close()
        finally:
            self._session = None
            self._release_lock()

    def __enter__(self) -> "VisaTransport":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- I/O ---------------------------------------------------------------

    def query(self, command: str) -> str:
        session = self._require_session()
        start = time.monotonic()
        try:
            response = str(session.query(command)).strip()
        except Exception as exc:
            self._log(
                command,
                error=f"{type(exc).__name__}: {exc}",
                duration_s=time.monotonic() - start,
            )
            raise
        self._log(command, response=response, duration_s=time.monotonic() - start)
        return response

    def write(self, command: str) -> None:
        session = self._require_session()
        start = time.monotonic()
        try:
            session.write(command)
        except Exception as exc:
            self._log(
                command,
                error=f"{type(exc).__name__}: {exc}",
                duration_s=time.monotonic() - start,
            )
            raise
        self._log(command, duration_s=time.monotonic() - start)

    # -- internals ----------------------------------------------------------

    def _require_session(self) -> Any:
        if self._session is None:
            raise TransportError(f"transport for {self.resource} is not open")
        return self._session

    def _acquire_lock(self) -> None:
        lock_file = open(self._lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            raise DeviceLockError(
                f"instrument {self.resource} is in use by another process "
                f"(lock file {self._lock_path})"
            ) from exc
        self._lock_file = lock_file

    def _release_lock(self) -> None:
        if self._lock_file is None:
            return
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_file.close()
            self._lock_file = None

    def _log(
        self,
        command: str,
        *,
        response: str | None = None,
        error: str | None = None,
        duration_s: float,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device": self.device_name,
            "resource": self.resource,
            "command": command,
            "duration_s": round(duration_s, 6),
        }
        if error is not None:
            entry["error"] = error
        elif response is not None:
            entry["response"] = response
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
