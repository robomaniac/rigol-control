"""Manual command handler tests using fake drivers and fake transports.

No test in this file contacts hardware, opens a VISA session, or imports
the real driver modules.
"""

import argparse
import copy

import pytest
import yaml

from benchctl import commands_manual
from benchctl.interfaces import Identification

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
    "setups": {},
}

SAFETY_PROFILES = {
    "schema_version": 1,
    "profiles": {
        "dp821_physical": {
            "type": "power_supply",
            "channels": {
                1: {"max_voltage_v": 60.0, "max_current_a": 1.0, "max_power_w": 60.0},
                2: {"max_voltage_v": 8.0, "max_current_a": 10.0, "max_power_w": 80.0},
            },
        },
        "dl3021_physical": {
            "type": "electronic_load",
            "max_voltage_v": 150.0,
            "max_current_a": 40.0,
            "max_power_w": 200.0,
            "allowed_modes": ["cc", "cp"],
        },
    },
}


# -- fakes ---------------------------------------------------------------------


class FakeTransport:
    def __init__(self):
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
        raise AssertionError("fake drivers must not send raw SCPI in these tests")


class FakeSupplyDriver:
    def __init__(self, transport):
        self.transport = transport
        self.calls = []
        self.output_enabled = {1: False, 2: False}

    def get_output_enabled(self, channel: int) -> bool:
        self.calls.append(("get_output_enabled", channel))
        return self.output_enabled[channel]

    def set_voltage(self, channel: int, voltage_v: float):
        self.calls.append(("set_voltage", channel, voltage_v))

    def set_current_limit(self, channel: int, current_a: float):
        self.calls.append(("set_current_limit", channel, current_a))

    def output_on(self, channel: int):
        self.calls.append(("output_on", channel))
        self.output_enabled[channel] = True

    def output_off(self, channel: int):
        self.calls.append(("output_off", channel))
        self.output_enabled[channel] = False

    def all_outputs_off(self):
        self.calls.append(("all_outputs_off",))

    def measure_voltage(self, channel: int) -> float:
        self.calls.append(("measure_voltage", channel))
        return {1: 5.0, 2: 12.5}[channel]

    def measure_current(self, channel: int) -> float:
        self.calls.append(("measure_current", channel))
        return {1: 1.25, 2: 0.5}[channel]

    def measure_power(self, channel: int) -> float:
        self.calls.append(("measure_power", channel))
        return {1: 6.25, 2: 6.25}[channel]

    def identify(self):
        self.calls.append(("identify",))
        return Identification(
            "RIGOL TECHNOLOGIES", "DP821A", "DP8A000001", "00.01"
        )

    def check_errors(self):
        self.calls.append(("check_errors",))


class FakeLoadDriver:
    def __init__(self, transport):
        self.transport = transport
        self.calls = []
        self.input_enabled = False
        self.readings = {
            "voltage_v": 11.9,
            "current_a": 2.0,
            "power_w": 23.8,
        }

    def get_input_enabled(self):
        self.calls.append(("get_input_enabled",))
        return self.input_enabled

    def set_mode(self, mode: str):
        self.calls.append(("set_mode", mode))

    def set_current(self, current_a: float):
        self.calls.append(("set_current", current_a))

    def input_on(self):
        self.calls.append(("input_on",))
        self.input_enabled = True

    def input_off(self):
        self.calls.append(("input_off",))
        self.input_enabled = False

    def measure_voltage(self) -> float:
        self.calls.append(("measure_voltage",))
        return self.readings["voltage_v"]

    def measure_current(self) -> float:
        self.calls.append(("measure_current",))
        return self.readings["current_a"]

    def measure_power(self) -> float:
        self.calls.append(("measure_power",))
        return self.readings["power_w"]

    def identify(self):
        self.calls.append(("identify",))
        return Identification(
            "RIGOL TECHNOLOGIES", "DL3021", "DL3A000001", "00.01"
        )

    def check_errors(self):
        self.calls.append(("check_errors",))


class Harness:
    """Injects fake transports and fake driver classes; records everything."""

    def __init__(self, *, load_readings=None, supply_output_enabled=None, load_input_enabled=False):
        self.transports = {}
        self.drivers = []
        self.load_readings = load_readings
        self.supply_output_enabled = supply_output_enabled or {}
        self.load_input_enabled = load_input_enabled

    def make_transport(self, name, device):
        transport = FakeTransport()
        self.transports[name] = transport
        return transport

    def get_driver_class(self, name):
        cls = {"rigol_dp800": FakeSupplyDriver, "rigol_dl3000": FakeLoadDriver}[name]

        def factory(transport):
            driver = cls(transport)
            if isinstance(driver, FakeSupplyDriver):
                driver.output_enabled.update(self.supply_output_enabled)
            if isinstance(driver, FakeLoadDriver):
                driver.input_enabled = self.load_input_enabled
                if self.load_readings is not None:
                    driver.readings.update(self.load_readings)
            self.drivers.append(driver)
            return driver

        return factory

    @property
    def all_calls(self):
        return [call for driver in self.drivers for call in driver.calls]


@pytest.fixture
def paths(tmp_path):
    config_path = tmp_path / "lab.yaml"
    config_path.write_text(yaml.safe_dump(BASE_CONFIG), encoding="utf-8")
    profiles_path = tmp_path / "safety_profiles.yaml"
    profiles_path.write_text(yaml.safe_dump(SAFETY_PROFILES), encoding="utf-8")
    return config_path, profiles_path


def run_command(monkeypatch, paths, argv, harness=None):
    harness = harness or Harness()
    monkeypatch.setattr(commands_manual, "make_transport", harness.make_transport)
    monkeypatch.setattr(commands_manual, "get_driver_class", harness.get_driver_class)
    config_path, profiles_path = paths
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands_manual.register(subparsers)
    args = parser.parse_args(
        argv + ["--config", str(config_path), "--safety-profiles", str(profiles_path)]
    )
    return args.func(args), harness


# -- measure --------------------------------------------------------------------


def test_measure_supply_prints_per_channel_values(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch, paths, ["measure", "--device", "psu_rigol_1"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "psu_rigol_1:" in out
    assert "channel 1: 5.000 V, 1.250 A, 6.250 W" in out
    assert "channel 2: 12.500 V, 0.500 A, 6.250 W" in out
    assert harness.all_calls[0] == ("identify",)
    assert harness.transports["psu_rigol_1"].closed


def test_measure_load_prints_values(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch, paths, ["measure", "--device", "load_rigol_1"]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "load_rigol_1: 11.900 V, 2.000 A, 23.800 W" in out
    assert harness.transports["load_rigol_1"].closed


def test_measure_is_read_only(monkeypatch, paths):
    _, harness = run_command(monkeypatch, paths, ["measure", "--device", "psu_rigol_1"])
    mutating = {
        "set_voltage",
        "set_current_limit",
        "output_on",
        "output_off",
        "all_outputs_off",
    }
    assert not [call for call in harness.all_calls if call[0] in mutating]


def test_measure_unknown_device_is_error(monkeypatch, capsys, paths):
    exit_code, harness = run_command(monkeypatch, paths, ["measure", "--device", "nope"])
    assert exit_code == 2
    assert harness.transports == {}
    assert "unknown device" in capsys.readouterr().err


# -- output-on -------------------------------------------------------------------


def test_output_on_valid_orders_calls_correctly(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "0.5",
        ],
    )
    assert exit_code == 0
    calls = harness.all_calls
    assert calls[0] == ("identify",)
    assert ("set_voltage", 1, 5.0) in calls
    assert ("set_current_limit", 1, 0.5) in calls
    assert ("output_on", 1) in calls
    # Setpoints must be applied before the output is enabled.
    on_index = calls.index(("output_on", 1))
    assert calls.index(("set_voltage", 1, 5.0)) < on_index
    assert calls.index(("set_current_limit", 1, 0.5)) < on_index
    assert harness.transports["psu_rigol_1"].closed


def test_output_on_refuses_live_reconfiguration_before_setpoint_writes(
    monkeypatch, capsys, paths
):
    harness = Harness(supply_output_enabled={1: True})
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "0.5",
        ],
        harness,
    )
    assert exit_code == 1
    assert harness.all_calls == [("identify",), ("get_output_enabled", 1)]
    assert "output is ON; turn it OFF" in capsys.readouterr().err


def test_output_on_failure_attempts_channel_off(monkeypatch, capsys, paths):
    def uncertain_output_on(self, channel):
        self.calls.append(("output_on", channel))
        self.output_enabled[channel] = True
        raise RuntimeError("enable acknowledgement lost")

    monkeypatch.setattr(FakeSupplyDriver, "output_on", uncertain_output_on)
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "0.5",
        ],
    )
    assert exit_code == 1
    driver = harness.drivers[0]
    assert driver.calls[-2:] == [("output_on", 1), ("output_off", 1)]
    assert driver.output_enabled[1] is False
    assert "enable acknowledgement lost" in capsys.readouterr().err


def test_output_on_shutdown_failure_preserves_enable_error(
    monkeypatch, capsys, paths
):
    def uncertain_output_on(self, channel):
        self.calls.append(("output_on", channel))
        raise RuntimeError("enable failed")

    def broken_output_off(self, channel):
        self.calls.append(("output_off", channel))
        raise OSError("off failed")

    monkeypatch.setattr(FakeSupplyDriver, "output_on", uncertain_output_on)
    monkeypatch.setattr(FakeSupplyDriver, "output_off", broken_output_off)
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "0.5",
        ],
    )
    assert exit_code == 1
    assert harness.all_calls[-2:] == [("output_on", 1), ("output_off", 1)]
    error = capsys.readouterr().err
    assert "enable failed" in error
    assert "off failed" in error


def test_output_on_at_limit_passes(monkeypatch, paths):
    exit_code, _ = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "2",
            "--voltage-v", "8.0",
            "--current-limit-a", "10.0",
        ],
    )
    assert exit_code == 0


def test_output_on_over_voltage_refused_without_driver_calls(
    monkeypatch, capsys, paths
):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "60.5",
            "--current-limit-a", "1.0",
        ],
    )
    assert exit_code != 0
    assert harness.drivers == []
    assert harness.transports == {}
    assert "exceeds" in capsys.readouterr().err


def test_output_on_negative_current_refused(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "-1.0",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []


def test_output_on_unknown_channel_refused(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "3",
            "--voltage-v", "1.0",
            "--current-limit-a", "0.1",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []


def test_output_on_missing_safety_profile_is_hard_error(
    monkeypatch, capsys, tmp_path, paths
):
    config_path, _ = paths
    empty_profiles = tmp_path / "empty_profiles.yaml"
    empty_profiles.write_text(
        yaml.safe_dump({"schema_version": 1, "profiles": {}}), encoding="utf-8"
    )
    exit_code, harness = run_command(
        monkeypatch,
        (config_path, empty_profiles),
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "1.0",
            "--current-limit-a", "0.1",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []
    assert "dp821_physical" in capsys.readouterr().err


def test_output_on_on_load_is_kind_mismatch(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "output-on",
            "--device", "load_rigol_1",
            "--channel", "1",
            "--voltage-v", "1.0",
            "--current-limit-a", "0.1",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []
    assert "kind" in capsys.readouterr().err


# -- output-off / input-off --------------------------------------------------------


def test_output_off_single_channel(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        ["output-off", "--device", "psu_rigol_1", "--channel", "2"],
    )
    assert exit_code == 0
    assert harness.all_calls[0] == ("identify",)
    assert ("output_off", 2) in harness.all_calls
    assert harness.transports["psu_rigol_1"].closed


def test_output_off_all(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        ["output-off", "--device", "psu_rigol_1", "--all"],
    )
    assert exit_code == 0
    assert ("all_outputs_off",) in harness.all_calls


def test_output_off_requires_channel_or_all(paths):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands_manual.register(subparsers)
    with pytest.raises(SystemExit):
        parser.parse_args(["output-off", "--device", "psu_rigol_1"])


def test_output_off_works_without_safety_profiles_file(monkeypatch, tmp_path, paths):
    # The safe direction must never depend on limits being loadable.
    config_path, _ = paths
    missing_profiles = tmp_path / "no_such_profiles.yaml"
    exit_code, harness = run_command(
        monkeypatch,
        (config_path, missing_profiles),
        ["output-off", "--device", "psu_rigol_1", "--all"],
    )
    assert exit_code == 0
    assert ("all_outputs_off",) in harness.all_calls


def test_output_off_on_load_fails_cleanly(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        ["output-off", "--device", "load_rigol_1", "--all"],
    )
    assert exit_code != 0
    assert harness.all_calls == []
    assert harness.transports == {}
    assert "kind" in capsys.readouterr().err


def test_input_off(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch, paths, ["input-off", "--device", "load_rigol_1"]
    )
    assert exit_code == 0
    assert harness.all_calls[0] == ("identify",)
    assert ("input_off",) in harness.all_calls
    assert harness.transports["load_rigol_1"].closed


def test_input_off_on_supply_fails_cleanly(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch, paths, ["input-off", "--device", "psu_rigol_1"]
    )
    assert exit_code != 0
    assert harness.all_calls == []
    assert "kind" in capsys.readouterr().err


# -- input-on ----------------------------------------------------------------------


def test_input_on_refuses_live_reconfiguration_before_setpoint_writes(
    monkeypatch, capsys, paths
):
    harness = Harness(load_input_enabled=True)
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "0.2",
            "--max-voltage-v", "5.0",
        ],
        harness,
    )
    assert exit_code == 1
    assert harness.all_calls == [("identify",), ("get_input_enabled",)]
    assert harness.transports["load_rigol_1"].closed
    assert "input is ON; turn it OFF" in capsys.readouterr().err


def test_input_on_valid_orders_calls_correctly(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "3.0",
            "--max-voltage-v", "12.0",
        ],
    )
    assert exit_code == 0
    calls = harness.all_calls
    assert calls[0] == ("identify",)
    assert ("set_mode", "cc") in calls
    assert ("set_current", 3.0) in calls
    on_index = calls.index(("input_on",))
    assert calls.index(("set_mode", "cc")) < on_index
    assert calls.index(("set_current", 3.0)) < on_index
    assert calls[on_index + 1:on_index + 4] == [
        ("measure_voltage",),
        ("measure_current",),
        ("measure_power",),
    ]
    assert harness.transports["load_rigol_1"].closed


def test_input_on_disallowed_mode_refused(monkeypatch, capsys, paths):
    harness = Harness()
    with pytest.raises(SystemExit):
        run_command(
            monkeypatch,
            paths,
            [
                "input-on",
                "--device", "load_rigol_1",
                "--mode", "cv",
                "--current-a", "1.0",
                "--max-voltage-v", "12.0",
            ],
            harness,
        )
    assert harness.all_calls == []
    assert harness.transports == {}
    assert "invalid choice" in capsys.readouterr().err


def test_input_on_handler_defensively_rejects_non_cc_mode(
    monkeypatch, capsys, paths
):
    harness = Harness()
    monkeypatch.setattr(commands_manual, "make_transport", harness.make_transport)
    monkeypatch.setattr(
        commands_manual, "get_driver_class", harness.get_driver_class
    )
    config_path, profiles_path = paths
    args = argparse.Namespace(
        config=config_path,
        safety_profiles=profiles_path,
        device="load_rigol_1",
        mode="cp",
        current_a=1.0,
        max_voltage_v=6.0,
    )
    assert commands_manual.handle_input_on(args) == 2
    assert harness.transports == {}
    assert "only constant-current" in capsys.readouterr().err


def test_input_on_over_current_refused(monkeypatch, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "40.5",
            "--max-voltage-v", "1.0",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []


def test_input_on_on_supply_is_kind_mismatch(monkeypatch, capsys, paths):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "psu_rigol_1",
            "--mode", "cc",
            "--current-a", "1.0",
            "--max-voltage-v", "12.0",
        ],
    )
    assert exit_code != 0
    assert harness.all_calls == []
    assert "kind" in capsys.readouterr().err


def test_input_on_requires_maximum_voltage_argument(monkeypatch, paths):
    harness = Harness()
    with pytest.raises(SystemExit):
        run_command(
            monkeypatch,
            paths,
            [
                "input-on",
                "--device", "load_rigol_1",
                "--mode", "cc",
                "--current-a", "1.0",
            ],
            harness,
        )
    assert harness.transports == {}


def test_input_on_worst_case_power_rejected_before_connecting(
    monkeypatch, capsys, paths
):
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "2.0",
            "--max-voltage-v", "101.0",
        ],
    )
    assert exit_code == 2
    assert harness.transports == {}
    assert "worst-case load power" in capsys.readouterr().err


def test_input_on_overvoltage_measurement_turns_input_off(
    monkeypatch, capsys, paths
):
    harness = Harness(load_readings={"voltage_v": 6.1, "power_w": 6.1})
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "1.0",
            "--max-voltage-v", "6.0",
        ],
        harness,
    )
    assert exit_code == 1
    assert ("input_on",) in harness.all_calls
    assert ("input_off",) in harness.all_calls
    assert harness.all_calls.index(("input_on",)) < harness.all_calls.index(
        ("input_off",)
    )
    assert "declared maximum" in capsys.readouterr().err


def test_input_on_overpower_measurement_turns_input_off(
    monkeypatch, capsys, paths
):
    harness = Harness(
        load_readings={"voltage_v": 5.0, "current_a": 1.0, "power_w": 201.0}
    )
    exit_code, harness = run_command(
        monkeypatch,
        paths,
        [
            "input-on",
            "--device", "load_rigol_1",
            "--mode", "cc",
            "--current-a", "1.0",
            "--max-voltage-v", "6.0",
        ],
        harness,
    )
    assert exit_code == 1
    assert ("input_off",) in harness.all_calls
    assert "measured power" in capsys.readouterr().err


def test_serial_mismatch_closes_session_before_manual_operation(
    monkeypatch, capsys, paths
):
    config_path, profiles_path = paths
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["expected_serial"] = "EXPECTED_SERIAL"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    exit_code, harness = run_command(
        monkeypatch,
        (config_path, profiles_path),
        ["output-off", "--device", "psu_rigol_1", "--all"],
    )
    assert exit_code == 1
    assert harness.all_calls == [("identify",)]
    assert harness.transports["psu_rigol_1"].closed
    assert "serial mismatch" in capsys.readouterr().err


def test_profile_type_mismatch_rejected_before_connecting(
    monkeypatch, capsys, paths
):
    config_path, profiles_path = paths
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["safety_profile"] = "dl3021_physical"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    exit_code, harness = run_command(
        monkeypatch,
        (config_path, profiles_path),
        [
            "output-on",
            "--device", "psu_rigol_1",
            "--channel", "1",
            "--voltage-v", "5.0",
            "--current-limit-a", "1.0",
        ],
    )
    assert exit_code == 2
    assert harness.transports == {}
    assert "has type 'electronic_load'" in capsys.readouterr().err
