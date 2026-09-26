"""Identification flow tests using fake transports and fake VISA sessions.

No test in this file contacts hardware.
"""

import fcntl
import json
from pathlib import Path

import pytest
import yaml

from benchctl import cli
from benchctl.transport import DeviceLockError, VisaTransport

PSU_IDN = "RIGOL TECHNOLOGIES,DP821A,DP8A000001,00.01.16"
LOAD_IDN = "RIGOL TECHNOLOGIES,DL3021,DL3A000001,00.01.05"

BASE_CONFIG = {
    "schema_version": 1,
    "devices": {
        "psu_rigol_1": {
            "kind": "power_supply",
            "driver": "rigol_dp800",
            "resource": "TCPIP0::192.0.2.10::INSTR",
            "expected_serial": None,
            "safety_profile": "dp821_physical",
        },
        "load_rigol_1": {
            "kind": "electronic_load",
            "driver": "rigol_dl3000",
            "resource": "TCPIP0::192.0.2.20::INSTR",
            "expected_serial": None,
            "safety_profile": "dl3021_physical",
        },
    },
    "setups": {
        "main_bench": {
            "supply": "psu_rigol_1",
            "load": "load_rigol_1",
        },
    },
}

IDN_BY_DEVICE = {
    "psu_rigol_1": PSU_IDN,
    "load_rigol_1": LOAD_IDN,
}


class FakeTransport:
    """Records commands and lifecycle; simulates one instrument."""

    def __init__(self, idn: str, fail: bool = False):
        self.idn = idn
        self.fail = fail
        self.commands: list[str] = []
        self.opened = False
        self.closed = False

    def __enter__(self):
        self.opened = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        self.closed = True

    def query(self, command: str) -> str:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("simulated instrument failure")
        return self.idn


class FakeTransportFactory:
    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()
        self.created: dict[str, FakeTransport] = {}

    def __call__(self, name: str, device) -> FakeTransport:
        transport = FakeTransport(IDN_BY_DEVICE[name], fail=name in self.failing)
        self.created[name] = transport
        return transport


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "lab.yaml"
    path.write_text(yaml.safe_dump(BASE_CONFIG), encoding="utf-8")
    return path


def run_cli(monkeypatch, factory, argv):
    monkeypatch.setattr(cli, "make_transport", factory)
    return cli.main(argv)


# -- selection ---------------------------------------------------------------


def test_identify_all_devices(monkeypatch, capsys, config_path):
    factory = FakeTransportFactory()
    exit_code = run_cli(monkeypatch, factory, ["identify", "--config", str(config_path)])
    assert exit_code == 0
    assert set(factory.created) == {"psu_rigol_1", "load_rigol_1"}
    out = capsys.readouterr().out
    assert "psu_rigol_1:" in out
    assert "load_rigol_1:" in out
    assert "RIGOL TECHNOLOGIES" in out
    assert "DP821A" in out
    assert "DP8A000001" in out
    assert "00.01.16" in out
    assert "TCPIP0::192.0.2.10::INSTR" in out


def test_identify_single_device(monkeypatch, config_path):
    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(config_path), "--device", "psu_rigol_1"],
    )
    assert exit_code == 0
    assert set(factory.created) == {"psu_rigol_1"}


def test_identify_setup(monkeypatch, config_path):
    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(config_path), "--setup", "main_bench"],
    )
    assert exit_code == 0
    assert set(factory.created) == {"psu_rigol_1", "load_rigol_1"}


def test_unknown_device_is_error(monkeypatch, config_path):
    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(config_path), "--device", "nope"],
    )
    assert exit_code == 2
    assert factory.created == {}


def test_unknown_setup_is_error(monkeypatch, config_path):
    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(config_path), "--setup", "nope"],
    )
    assert exit_code == 2
    assert factory.created == {}


def test_device_and_setup_mutually_exclusive(config_path):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            [
                "identify",
                "--config",
                str(config_path),
                "--device",
                "psu_rigol_1",
                "--setup",
                "main_bench",
            ]
        )
    assert excinfo.value.code == 2


# -- safety boundary ----------------------------------------------------------


def test_only_idn_is_sent(monkeypatch, config_path):
    factory = FakeTransportFactory()
    run_cli(monkeypatch, factory, ["identify", "--config", str(config_path)])
    for transport in factory.created.values():
        assert transport.commands == ["*IDN?"]


def test_transports_closed_after_success(monkeypatch, config_path):
    factory = FakeTransportFactory()
    run_cli(monkeypatch, factory, ["identify", "--config", str(config_path)])
    assert all(t.closed for t in factory.created.values())


def test_transports_closed_after_failure(monkeypatch, config_path):
    factory = FakeTransportFactory(failing={"psu_rigol_1"})
    run_cli(monkeypatch, factory, ["identify", "--config", str(config_path)])
    assert all(t.closed for t in factory.created.values())


# -- failure handling ---------------------------------------------------------


def test_one_failure_continues_and_exit_is_nonzero(monkeypatch, capsys, config_path):
    factory = FakeTransportFactory(failing={"psu_rigol_1"})
    exit_code = run_cli(monkeypatch, factory, ["identify", "--config", str(config_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    # The failing device is reported on stderr...
    assert "psu_rigol_1: FAILED" in captured.err
    # ...and the healthy device is still identified.
    assert "load_rigol_1:" in captured.out
    assert "DL3021" in captured.out


def test_serial_mismatch_fails(monkeypatch, capsys, tmp_path):
    import copy

    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["expected_serial"] = "WRONG_SERIAL"
    path = tmp_path / "lab.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(path), "--device", "psu_rigol_1"],
    )
    assert exit_code == 1
    error = capsys.readouterr().err
    assert "serial mismatch" in error
    assert "WRONG_SERIAL" in error
    assert "DP821A" in error
    assert "DP8A000001" in error
    transport = factory.created["psu_rigol_1"]
    assert transport.commands == ["*IDN?"]
    assert transport.closed


def test_serial_match_succeeds(monkeypatch, tmp_path):
    import copy

    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["expected_serial"] = "DP8A000001"
    path = tmp_path / "lab.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    factory = FakeTransportFactory()
    exit_code = run_cli(
        monkeypatch,
        factory,
        ["identify", "--config", str(path), "--device", "psu_rigol_1"],
    )
    assert exit_code == 0


# -- VisaTransport lock, session, and log behavior (fake VISA session) --------


class FakeSession:
    def __init__(self, response: str = PSU_IDN, fail: bool = False):
        self.response = response
        self.fail = fail
        self.closed = False
        self.timeout = None
        self.commands: list[str] = []

    def query(self, command: str) -> str:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("simulated VISA failure")
        return self.response + "\n"

    def close(self):
        self.closed = True


class FakeResourceManager:
    def __init__(self, session: FakeSession):
        self.session = session

    def open_resource(self, resource: str) -> FakeSession:
        return self.session


def make_visa_transport(tmp_path, session) -> VisaTransport:
    return VisaTransport(
        "psu_rigol_1",
        "TCPIP0::192.0.2.10::INSTR",
        resource_manager=FakeResourceManager(session),
        log_path=tmp_path / "logs" / "commands.jsonl",
        lock_dir=tmp_path,
    )


def assert_lock_released(tmp_path):
    lock_files = list(Path(tmp_path).glob("benchctl-*.lock"))
    assert len(lock_files) == 1
    with open(lock_files[0], "a+", encoding="utf-8") as fh:
        # Raises BlockingIOError if the lock were still held.
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def test_visa_transport_success_releases_session_and_lock(tmp_path):
    session = FakeSession()
    transport = make_visa_transport(tmp_path, session)
    with transport as t:
        assert t.query("*IDN?") == PSU_IDN
    assert session.closed
    assert_lock_released(tmp_path)


def test_visa_transport_failure_releases_session_and_lock(tmp_path):
    session = FakeSession(fail=True)
    transport = make_visa_transport(tmp_path, session)
    with pytest.raises(RuntimeError):
        with transport as t:
            t.query("*IDN?")
    assert session.closed
    assert_lock_released(tmp_path)


def test_visa_transport_lock_blocks_second_process(tmp_path):
    first = make_visa_transport(tmp_path, FakeSession())
    second = make_visa_transport(tmp_path, FakeSession())
    with first:
        with pytest.raises(DeviceLockError):
            second.open()
    # After the first releases, the second can acquire.
    with second as t:
        assert t.query("*IDN?") == PSU_IDN


def test_visa_transport_writes_jsonl_log(tmp_path):
    session = FakeSession()
    transport = make_visa_transport(tmp_path, session)
    with transport as t:
        t.query("*IDN?")

    log_path = tmp_path / "logs" / "commands.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["device"] == "psu_rigol_1"
    assert entry["resource"] == "TCPIP0::192.0.2.10::INSTR"
    assert entry["command"] == "*IDN?"
    assert entry["response"] == PSU_IDN
    assert entry["duration_s"] >= 0
    assert entry["timestamp"].endswith("+00:00")


def test_visa_transport_logs_errors(tmp_path):
    session = FakeSession(fail=True)
    transport = make_visa_transport(tmp_path, session)
    with pytest.raises(RuntimeError):
        with transport as t:
            t.query("*IDN?")

    log_path = tmp_path / "logs" / "commands.jsonl"
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert "error" in entry
    assert "simulated VISA failure" in entry["error"]
    assert "response" not in entry
