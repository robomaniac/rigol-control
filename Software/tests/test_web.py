"""Web dashboard tests using fake transports and fake drivers.

No test in this file opens a real VISA session or contacts hardware:
everything is injected through the transport/driver factories.
"""

from __future__ import annotations

import argparse
import copy
import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from benchctl import commands_web
from benchctl.config import LabConfig
from benchctl.interfaces import Identification
from benchctl.web.server import create_server

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
    "setups": {"main_bench": {"supply": "psu_rigol_1", "load": "load_rigol_1"}},
}

# Canned SCPI responses per device: identify plus measurement queries only.
RESPONSES = {
    "psu_rigol_1": {
        "*IDN?": PSU_IDN,
        ":MEAS:VOLT? CH1": "12.000",
        ":MEAS:CURR? CH1": "0.500",
        ":MEAS:POW? CH1": "6.000",
        ":MEAS:VOLT? CH2": "5.000",
        ":MEAS:CURR? CH2": "0.100",
        ":MEAS:POW? CH2": "0.500",
    },
    "load_rigol_1": {
        "*IDN?": LOAD_IDN,
        ":MEAS:VOLT?": "3.300",
        ":MEAS:CURR?": "1.200",
        ":MEAS:POW?": "3.960",
    },
}


# -- fakes ---------------------------------------------------------------------


class FakeTransport:
    """Simulates one instrument; records every command and its lifecycle."""

    def __init__(self, responses: dict[str, str], factory: "FakeTransportFactory", fail: bool = False):
        self.responses = responses
        self.factory = factory
        self.fail = fail
        self.commands: list[str] = []
        self.open_count = 0
        self.closed = False

    def __enter__(self):
        self.open_count += 1
        self.closed = False
        self.factory.note_open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if not self.closed:
            self.factory.note_close()
        self.closed = True

    def query(self, command: str) -> str:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("simulated offline instrument")
        return self.responses[command]


class FakeTransportFactory:
    """Injectable factory that also tracks concurrent open sessions."""

    def __init__(self, failing: set[str] | None = None):
        self.failing = failing or set()
        self.created: dict[str, FakeTransport] = {}
        self.created_count: dict[str, int] = {}
        self._lock = threading.Lock()
        self._open_now = 0
        self.max_concurrent_open = 0

    def __call__(self, name: str, device) -> FakeTransport:
        transport = FakeTransport(RESPONSES[name], self, fail=name in self.failing)
        self.created[name] = transport
        self.created_count[name] = self.created_count.get(name, 0) + 1
        return transport

    def note_open(self):
        with self._lock:
            self._open_now += 1
            self.max_concurrent_open = max(self.max_concurrent_open, self._open_now)

    def note_close(self):
        with self._lock:
            self._open_now -= 1


class FakeSupplyDriver:
    """Implements the rigol_dp800 measurement contract against a transport."""

    def __init__(self, transport):
        self._transport = transport

    def identify(self) -> Identification:
        return Identification.from_idn(self._transport.query("*IDN?"))

    def measure_voltage(self, channel: int) -> float:
        return float(self._transport.query(f":MEAS:VOLT? CH{channel}"))

    def measure_current(self, channel: int) -> float:
        return float(self._transport.query(f":MEAS:CURR? CH{channel}"))

    def measure_power(self, channel: int) -> float:
        return float(self._transport.query(f":MEAS:POW? CH{channel}"))


class FakeLoadDriver:
    """Implements the rigol_dl3000 measurement contract against a transport."""

    def __init__(self, transport):
        self._transport = transport

    def identify(self) -> Identification:
        return Identification.from_idn(self._transport.query("*IDN?"))

    def measure_voltage(self) -> float:
        return float(self._transport.query(":MEAS:VOLT?"))

    def measure_current(self) -> float:
        return float(self._transport.query(":MEAS:CURR?"))

    def measure_power(self) -> float:
        return float(self._transport.query(":MEAS:POW?"))


def fake_driver_factory(name: str):
    return {"rigol_dp800": FakeSupplyDriver, "rigol_dl3000": FakeLoadDriver}[name]


# -- server helpers ------------------------------------------------------------


@contextmanager
def running_server(factory: FakeTransportFactory, config_data=None):
    config = LabConfig.model_validate(config_data or BASE_CONFIG)
    server = create_server(
        config,
        factory,
        host="127.0.0.1",
        port=0,
        driver_factory=fake_driver_factory,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        assert response.headers["Content-Type"] == "application/json"
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture
def factory():
    return FakeTransportFactory()


# -- endpoints -----------------------------------------------------------------


def test_index_page_is_self_contained_html(factory):
    with running_server(factory) as base:
        with urllib.request.urlopen(f"{base}/", timeout=10) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            body = response.read().decode("utf-8")
    assert "/api/status" in body  # page polls the JSON API
    assert "<script>" in body
    # Self-contained: no external assets fetched from CDNs.
    assert "http://" not in body and "https://" not in body
    # Serving the page alone must not touch instruments.
    assert factory.created == {}


def test_api_devices_lists_configuration(factory):
    with running_server(factory) as base:
        devices = get_json(f"{base}/api/devices")
    assert set(devices) == {"psu_rigol_1", "load_rigol_1"}
    psu = devices["psu_rigol_1"]
    assert psu["kind"] == "power_supply"
    assert psu["driver"] == "rigol_dp800"
    assert psu["resource"] == "TCPIP0::192.0.2.10::INSTR"
    # Inventory endpoint is config-only: no instrument I/O.
    assert factory.created == {}


def test_api_status_shape_and_values(factory):
    with running_server(factory) as base:
        status = get_json(f"{base}/api/status")

    assert set(status) == {"psu_rigol_1", "load_rigol_1"}

    psu = status["psu_rigol_1"]
    assert psu["error"] is None
    assert psu["kind"] == "power_supply"
    assert psu["resource"] == "TCPIP0::192.0.2.10::INSTR"
    assert psu["identify"] == {
        "manufacturer": "RIGOL TECHNOLOGIES",
        "model": "DP821A",
        "serial": "DP8A000001",
        "firmware": "00.01.16",
    }
    assert set(psu["measurements"]) == {"channel_1", "channel_2"}
    assert psu["measurements"]["channel_1"] == {
        "voltage_v": 12.0,
        "current_a": 0.5,
        "power_w": 6.0,
    }
    assert psu["measurements"]["channel_2"]["voltage_v"] == 5.0

    load = status["load_rigol_1"]
    assert load["error"] is None
    assert load["identify"]["model"] == "DL3021"
    assert load["measurements"] == {
        "voltage_v": 3.3,
        "current_a": 1.2,
        "power_w": 3.96,
    }


def test_unknown_path_is_404(factory):
    with running_server(factory) as base:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(f"{base}/nope", timeout=10)
    assert excinfo.value.code == 404


# -- error isolation -----------------------------------------------------------


def test_one_offline_device_does_not_break_others():
    factory = FakeTransportFactory(failing={"psu_rigol_1"})
    with running_server(factory) as base:
        status = get_json(f"{base}/api/status")

    psu = status["psu_rigol_1"]
    assert psu["error"] is not None
    assert "simulated offline instrument" in psu["error"]
    assert psu["identify"] is None
    assert psu["measurements"] is None
    # The healthy device still reports fully.
    load = status["load_rigol_1"]
    assert load["error"] is None
    assert load["identify"]["model"] == "DL3021"
    assert load["measurements"]["voltage_v"] == 3.3


def test_transports_closed_even_on_failure():
    factory = FakeTransportFactory(failing={"psu_rigol_1"})
    with running_server(factory) as base:
        get_json(f"{base}/api/status")
    assert factory.created  # both devices were polled
    assert all(t.closed for t in factory.created.values())


# -- read-only guarantees --------------------------------------------------------


def test_only_idn_and_measurement_queries_are_sent(factory):
    with running_server(factory) as base:
        get_json(f"{base}/api/status")
    assert set(factory.created) == {"psu_rigol_1", "load_rigol_1"}
    for transport in factory.created.values():
        assert transport.commands, "device was never queried"
        assert transport.commands[0] == "*IDN?"
        for command in transport.commands:
            assert command == "*IDN?" or command.startswith(":MEAS:"), (
                f"non-read-only command sent: {command!r}"
            )


def test_serial_mismatch_stops_web_poll_after_identification():
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["expected_serial"] = "WRONG_SERIAL"
    factory = FakeTransportFactory()
    with running_server(factory, data) as base:
        status = get_json(f"{base}/api/status")

    psu = status["psu_rigol_1"]
    assert "SerialMismatchError" in psu["error"]
    assert psu["measurements"] is None
    transport = factory.created["psu_rigol_1"]
    assert transport.commands == ["*IDN?"]
    assert transport.closed
    assert status["load_rigol_1"]["measurements"]["voltage_v"] == 3.3


def test_post_is_rejected_with_405(factory):
    with running_server(factory) as base:
        request = urllib.request.Request(
            f"{base}/api/status", data=b"{}", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)
    assert excinfo.value.code == 405
    assert excinfo.value.headers["Allow"] == "GET"
    # A rejected write attempt must never reach an instrument.
    assert factory.created == {}


def test_put_and_delete_are_rejected_with_405(factory):
    with running_server(factory) as base:
        for method in ("PUT", "DELETE"):
            request = urllib.request.Request(f"{base}/api/devices", method=method)
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=10)
            assert excinfo.value.code == 405
    assert factory.created == {}


# -- session discipline ----------------------------------------------------------


def test_sessions_are_short_lived_per_poll(factory):
    with running_server(factory) as base:
        get_json(f"{base}/api/status")
        get_json(f"{base}/api/status")
    # A fresh transport is created (and closed) for every poll: no session
    # is held between requests, so the per-resource flock is released.
    assert factory.created_count == {"psu_rigol_1": 2, "load_rigol_1": 2}
    for transport in factory.created.values():
        assert transport.open_count == 1
        assert transport.closed


def test_concurrent_status_requests_never_overlap_instrument_access(factory):
    with running_server(factory) as base:
        errors: list[Exception] = []

        def hit():
            try:
                get_json(f"{base}/api/status")
            except Exception as exc:  # pragma: no cover - surfaced via assert
                errors.append(exc)

        threads = [threading.Thread(target=hit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

    assert not errors
    assert factory.max_concurrent_open == 1


# -- CLI registration ------------------------------------------------------------


def build_parser_with_web():
    parser = argparse.ArgumentParser(prog="benchctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands_web.register(subparsers)
    return parser


def test_register_adds_web_command_with_defaults():
    args = build_parser_with_web().parse_args(["web"])
    assert args.command == "web"
    assert args.config == Path("Software/config/lab.yaml")
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.func is commands_web.handler


def test_register_parses_overrides():
    args = build_parser_with_web().parse_args(
        ["web", "--config", "/tmp/other.yaml", "--host", "0.0.0.0", "--port", "9000"]
    )
    assert args.config == Path("/tmp/other.yaml")
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_handler_returns_2_on_bad_config(tmp_path, capsys):
    args = argparse.Namespace(
        config=tmp_path / "missing.yaml", host="127.0.0.1", port=0
    )
    assert commands_web.handler(args) == 2
    assert "error:" in capsys.readouterr().err
