"""VisaTransport tests with a fake VISA session. No hardware contact."""

import fcntl
import json
from pathlib import Path

import pytest

from benchctl.transport import DeviceLockError, TransportError, VisaTransport

RESOURCE = "TCPIP0::192.0.2.10::INSTR"


class FakeSession:
    def __init__(self, response: str = "ok", fail: bool = False):
        self.response = response
        self.fail = fail
        self.closed = False
        self.timeout = None
        self.written: list[str] = []
        self.queried: list[str] = []

    def write(self, command: str) -> None:
        self.written.append(command)
        if self.fail:
            raise RuntimeError("simulated VISA write failure")

    def query(self, command: str) -> str:
        self.queried.append(command)
        if self.fail:
            raise RuntimeError("simulated VISA query failure")
        return self.response + "\n"

    def close(self) -> None:
        self.closed = True


class FakeResourceManager:
    def __init__(self, session: FakeSession):
        self.session = session

    def open_resource(self, resource: str) -> FakeSession:
        return self.session


def make_transport(tmp_path, session, **kwargs) -> VisaTransport:
    return VisaTransport(
        "dev_under_test",
        RESOURCE,
        resource_manager=FakeResourceManager(session),
        log_path=tmp_path / "logs" / "commands.jsonl",
        lock_dir=tmp_path,
        **kwargs,
    )


def read_log_entries(tmp_path) -> list[dict]:
    log_path = tmp_path / "logs" / "commands.jsonl"
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]


def assert_lock_released(tmp_path):
    lock_files = list(Path(tmp_path).glob("benchctl-*.lock"))
    assert len(lock_files) == 1
    with open(lock_files[0], "a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# -- write() -------------------------------------------------------------------


def test_write_sends_command(tmp_path):
    session = FakeSession()
    with make_transport(tmp_path, session) as transport:
        transport.write(":SOUR1:VOLT 5.0")
    assert session.written == [":SOUR1:VOLT 5.0"]


def test_write_logs_jsonl_without_response(tmp_path):
    session = FakeSession()
    with make_transport(tmp_path, session) as transport:
        transport.write(":SOUR1:VOLT 5.0")
    (entry,) = read_log_entries(tmp_path)
    assert entry["device"] == "dev_under_test"
    assert entry["resource"] == RESOURCE
    assert entry["command"] == ":SOUR1:VOLT 5.0"
    assert entry["duration_s"] >= 0
    assert entry["timestamp"].endswith("+00:00")
    assert "response" not in entry
    assert "error" not in entry


def test_write_failure_logged_and_raised(tmp_path):
    session = FakeSession(fail=True)
    with pytest.raises(RuntimeError):
        with make_transport(tmp_path, session) as transport:
            transport.write(":SOUR1:VOLT 5.0")
    (entry,) = read_log_entries(tmp_path)
    assert "simulated VISA write failure" in entry["error"]
    assert "response" not in entry


def test_query_still_logs_response(tmp_path):
    session = FakeSession(response="4.999")
    with make_transport(tmp_path, session) as transport:
        assert transport.query(":MEAS:VOLT? CH1") == "4.999"
    (entry,) = read_log_entries(tmp_path)
    assert entry["response"] == "4.999"


def test_write_requires_open_transport(tmp_path):
    transport = make_transport(tmp_path, FakeSession())
    with pytest.raises(TransportError):
        transport.write(":OUTP CH1,OFF")


def test_query_requires_open_transport(tmp_path):
    transport = make_transport(tmp_path, FakeSession())
    with pytest.raises(TransportError):
        transport.query("*IDN?")


# -- timeout -------------------------------------------------------------------


def test_default_timeout_applied_to_session(tmp_path):
    session = FakeSession()
    with make_transport(tmp_path, session):
        assert session.timeout == 5000


def test_custom_timeout_applied_to_session(tmp_path):
    session = FakeSession()
    with make_transport(tmp_path, session, timeout_ms=1234):
        assert session.timeout == 1234


# -- lock and close behavior with write() ----------------------------------------


def test_session_and_lock_released_after_write_success(tmp_path):
    session = FakeSession()
    with make_transport(tmp_path, session) as transport:
        transport.write(":OUTP CH1,OFF")
    assert session.closed
    assert_lock_released(tmp_path)


def test_session_and_lock_released_after_write_failure(tmp_path):
    session = FakeSession(fail=True)
    with pytest.raises(RuntimeError):
        with make_transport(tmp_path, session) as transport:
            transport.write(":OUTP CH1,OFF")
    assert session.closed
    assert_lock_released(tmp_path)


def test_lock_blocks_second_transport_during_writes(tmp_path):
    first = make_transport(tmp_path, FakeSession())
    second = make_transport(tmp_path, FakeSession())
    with first as transport:
        transport.write(":OUTP CH1,OFF")
        with pytest.raises(DeviceLockError):
            second.open()
    with second:
        pass
