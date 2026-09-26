"""Runner tests with fake drivers, fake transports, and a fake safety module.

No test here opens a VISA session or contacts hardware.
"""

import argparse
import copy
import csv
import json
import math
import sys
import types
from pathlib import Path

import pytest
import yaml

from benchctl import commands_run, runner
from benchctl.config import LabConfig, load_config
from benchctl.interfaces import Identification
from benchctl.recipes import load_recipe, parse_recipe
from benchctl.report import generate_report
from benchctl.safety import load_safety_profiles

# -- fixtures: config, recipe, fake safety module -------------------------------

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
        "main_bench": {"supply": "psu_rigol_1", "load": "load_rigol_1"},
        "supply_only": {"supply": "psu_rigol_1"},
    },
}

PROFILES = {
    "dp821_physical": {
        "type": "power_supply",
        "max_voltage_v": 30.0,
        "max_current_a": 10.0,
        "max_power_w": 80.0,
    },
    "dl3021_physical": {
        "type": "electronic_load",
        "allowed_modes": ["cc"],
        "max_voltage_v": 150.0,
        "max_current_a": 40.0,
        "max_power_w": 200.0,
    },
}

BASE_RECIPE = {
    "schema_version": 1,
    "name": "runner_test",
    "requires": {
        "supply": {"kind": "power_supply"},
        "load": {"kind": "electronic_load"},
    },
    "parameters": {"voltage_v": 5.0},
    "steps": [
        {
            "action": "supply.configure",
            "channel": 1,
            "voltage_v": "${parameters.voltage_v}",
            "current_limit_a": 1.0,
        },
        {
            "action": "load.configure_cc",
            "current_a": 0.25,
            "max_voltage_v": 6.0,
        },
        {"action": "supply.output_on", "channel": 1},
        {"action": "wait", "seconds": 0.5},
        {"action": "load.input_on"},
        {
            "action": "measure",
            "save_as": "operating_point",
            "values": {
                "supply_voltage_v": {"source": "supply.voltage", "channel": 1},
                "load_current_a": {"source": "load.current"},
            },
        },
    ],
    "finally": [
        {"action": "load.input_off"},
        {"action": "supply.all_outputs_off"},
    ],
}


def make_recipe(**overrides):
    raw = copy.deepcopy(BASE_RECIPE)
    raw.update(overrides)
    return parse_recipe(raw)


def make_recipe_with_expectation(expect, *, label="supply_voltage_v"):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"][5]["values"][label]["expect"] = expect
    return parse_recipe(raw)


def make_config() -> LabConfig:
    return LabConfig.model_validate(copy.deepcopy(BASE_CONFIG))


def make_fake_safety_module() -> types.ModuleType:
    """A stand-in for benchctl.safety exposing only the documented names."""
    module = types.ModuleType("benchctl.safety")

    class SafetyError(Exception):
        pass

    def validate_supply_setpoint(profile, channel, voltage_v=None, current_a=None):
        if voltage_v is not None and voltage_v > profile["max_voltage_v"]:
            raise SafetyError(
                f"voltage {voltage_v} V exceeds limit {profile['max_voltage_v']} V"
            )
        if current_a is not None and current_a > profile["max_current_a"]:
            raise SafetyError(
                f"current {current_a} A exceeds limit {profile['max_current_a']} A"
            )
        if (
            voltage_v is not None
            and current_a is not None
            and voltage_v * current_a > profile["max_power_w"]
        ):
            raise SafetyError("voltage-current product exceeds power limit")

    def validate_load_setpoint(
        profile, mode=None, current_a=None, max_voltage_v=None
    ):
        if mode is not None and mode not in profile["allowed_modes"]:
            raise SafetyError(f"mode {mode!r} not allowed")
        if mode == "cc" and max_voltage_v is None:
            raise SafetyError("maximum expected voltage required")
        if current_a is not None and current_a > profile["max_current_a"]:
            raise SafetyError(
                f"current {current_a} A exceeds limit {profile['max_current_a']} A"
            )
        if (
            max_voltage_v is not None
            and max_voltage_v > profile["max_voltage_v"]
        ):
            raise SafetyError("maximum expected voltage exceeds limit")
        if (
            current_a is not None
            and max_voltage_v is not None
            and current_a * max_voltage_v > profile["max_power_w"]
        ):
            raise SafetyError("worst-case load power exceeds limit")

    def validate_load_measurements(
        profile, *, max_voltage_v, voltage_v, current_a, power_w
    ):
        if not all(
            value == value and abs(value) != float("inf")
            for value in (voltage_v, current_a, power_w)
        ):
            raise SafetyError("measurement must be finite")
        if voltage_v > max_voltage_v:
            raise SafetyError("measured voltage exceeds declared maximum")
        if power_w > profile["max_power_w"]:
            raise SafetyError("measured power exceeds profile limit")

    def get_device_safety_profile(profiles, device_name, device):
        try:
            profile = profiles[device.safety_profile]
        except KeyError:
            raise SafetyError(
                f"device {device_name!r} references missing safety profile "
                f"{device.safety_profile!r}"
            ) from None
        if profile["type"] != device.kind:
            raise SafetyError(
                f"safety profile {device.safety_profile!r} has type "
                f"{profile['type']!r}, but device {device_name!r} has kind "
                f"{device.kind!r}"
            )
        return profile

    def load_safety_profiles(path):
        return dict(PROFILES)

    module.SafetyError = SafetyError
    module.validate_supply_setpoint = validate_supply_setpoint
    module.validate_load_setpoint = validate_load_setpoint
    module.validate_load_measurements = validate_load_measurements
    module.get_device_safety_profile = get_device_safety_profile
    module.load_safety_profiles = load_safety_profiles
    return module


@pytest.fixture
def fake_safety(monkeypatch):
    module = make_fake_safety_module()
    monkeypatch.setitem(sys.modules, "benchctl.safety", module)
    return module


# -- fakes: transports and drivers -----------------------------------------------


class FakeTransport:
    def __init__(self, name: str):
        self.name = name
        self.opened = False
        self.closed = False

    def __enter__(self):
        self.opened = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        self.closed = True

    def query(self, command: str) -> str:  # pragma: no cover - fakes bypass SCPI
        raise AssertionError("recipe execution must not send raw SCPI")


class FakeSupply:
    def __init__(self, calls, raises=None):
        self.calls = calls
        self.raises = raises or {}
        self.voltage_v = 5.001
        self.current_a = 0.249
        self.power_w = 1.245
        self.output_enabled = {1: False, 2: False}

    def _record(self, method, *args):
        self.calls.append((method, *args))
        if method in self.raises:
            raise self.raises[method]

    def identify(self):
        self._record("supply.identify")
        return Identification("RIGOL TECHNOLOGIES", "DP821A", "FAKEPSU1", "00.01")

    def check_errors(self):
        pass

    def get_output_enabled(self, channel):
        self._record("supply.get_output_enabled", channel)
        return self.output_enabled[channel]

    def set_voltage(self, channel, v):
        self._record("supply.set_voltage", channel, v)

    def set_current_limit(self, channel, a):
        self._record("supply.set_current_limit", channel, a)

    def output_on(self, channel):
        self.output_enabled[channel] = True
        self._record("supply.output_on", channel)

    def output_off(self, channel):
        self.output_enabled[channel] = False
        self._record("supply.output_off", channel)

    def all_outputs_off(self):
        self.output_enabled = {1: False, 2: False}
        self._record("supply.all_outputs_off")

    def measure_voltage(self, channel):
        self._record("supply.measure_voltage", channel)
        return self.voltage_v

    def measure_current(self, channel):
        self._record("supply.measure_current", channel)
        return self.current_a

    def measure_power(self, channel):
        self._record("supply.measure_power", channel)
        return self.power_w


class FakeLoad:
    def __init__(self, calls, raises=None):
        self.calls = calls
        self.raises = raises or {}
        self.voltage_v = 4.998
        self.current_a = 0.250
        self.power_w = 1.250
        self.input_enabled = False

    def _record(self, method, *args):
        self.calls.append((method, *args))
        if method in self.raises:
            raise self.raises[method]

    def identify(self):
        self._record("load.identify")
        return Identification("RIGOL TECHNOLOGIES", "DL3021", "FAKELOAD1", "00.01")

    def check_errors(self):
        pass

    def get_input_enabled(self):
        self._record("load.get_input_enabled")
        return self.input_enabled

    def set_mode(self, mode):
        self._record("load.set_mode", mode)

    def set_current(self, a):
        self._record("load.set_current", a)

    def input_on(self):
        self.input_enabled = True
        self._record("load.input_on")

    def input_off(self):
        self.input_enabled = False
        self._record("load.input_off")

    def measure_voltage(self):
        self._record("load.measure_voltage")
        return self.voltage_v

    def measure_current(self):
        self._record("load.measure_current")
        return self.current_a

    def measure_power(self):
        self._record("load.measure_power")
        return self.power_w


class FakeBench:
    """Bundles the transport and driver factories plus a shared call log."""

    def __init__(self, supply_raises=None, load_raises=None, load_readings=None):
        self.calls: list[tuple] = []
        self.transports: list[FakeTransport] = []
        self.supply = FakeSupply(self.calls, supply_raises)
        self.load = FakeLoad(self.calls, load_raises)
        if load_readings:
            for name, value in load_readings.items():
                setattr(self.load, name, value)

    def transport_factory(self, name, device):
        transport = FakeTransport(name)
        self.transports.append(transport)
        return transport

    def driver_factory(self, device, transport):
        return self.supply if device.kind == "power_supply" else self.load


def run(bench, recipe, tmp_path, *, config=None, sleep_log=None):
    return runner.run_recipe(
        recipe,
        config or make_config(),
        "main_bench",
        PROFILES,
        transport_factory=bench.transport_factory,
        driver_factory=bench.driver_factory,
        results_base=tmp_path / "results",
        sleep=(sleep_log.append if sleep_log is not None else lambda s: None),
    )


def read_summary(result_or_dir) -> dict:
    run_dir = getattr(result_or_dir, "run_dir", result_or_dir)
    return json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))


# -- happy path -------------------------------------------------------------------


def test_happy_path_executes_actions_in_order(fake_safety, tmp_path):
    bench = FakeBench()
    sleeps: list[float] = []
    result = run(bench, make_recipe(), tmp_path, sleep_log=sleeps)

    assert result.status == "success"
    assert result.outcome == "pass"
    assert sleeps == [0.5]
    methods = [call[0] for call in bench.calls]
    # Configuration strictly precedes enabling outputs.
    assert methods.index("supply.set_voltage") < methods.index("supply.output_on")
    assert methods.index("supply.set_current_limit") < methods.index("supply.output_on")
    assert methods.index("load.set_mode") < methods.index("load.input_on")
    assert methods.index("load.set_current") < methods.index("load.input_on")
    # Cleanup actions run last, in recipe order.
    assert methods[-2:] == ["load.input_off", "supply.all_outputs_off"]
    assert bench.calls[:2] == [("supply.identify",), ("load.identify",)]
    assert ("supply.set_voltage", 1, 5.0) in bench.calls
    assert ("supply.set_current_limit", 1, 1.0) in bench.calls
    assert ("load.set_current", 0.25) in bench.calls
    # Transports were opened and closed.
    assert all(t.opened and t.closed for t in bench.transports)


def test_happy_path_records_measurements_and_summary(fake_safety, tmp_path):
    bench = FakeBench()
    result = run(bench, make_recipe(), tmp_path)

    lines = (result.run_dir / "measurements.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["save_as"] == "operating_point"
    assert record["values"] == {"supply_voltage_v": 5.001, "load_current_a": 0.250}
    assert record["setup"] == "main_bench"
    assert record["recipe"] == "runner_test"
    assert record["status"] == "not_checked"
    assert {
        verdict["status"] for verdict in record["verdicts"].values()
    } == {"not_checked"}

    summary = read_summary(result)
    assert summary["status"] == "success"
    assert summary["outcome"] == "pass"
    assert summary["error"] is None
    assert summary["parameters"] == {"voltage_v": 5.0}
    assert summary["identities"]["supply"]["model"] == "DP821A"
    assert summary["identities"]["load"]["model"] == "DL3021"

    events = [
        json.loads(line)
        for line in (result.run_dir / "execution.jsonl").read_text().splitlines()
    ]
    assert [e["phase"] for e in events] == ["steps"] * 6 + ["finally"] * 2
    assert all(e["status"] == "ok" for e in events)


def test_shipped_load_sweep_runs_and_reports_with_fake_bench(tmp_path):
    """Exercise the published demo end to end without a VISA connection."""

    class SweepLoad(FakeLoad):
        input_enabled = False

        def set_current(self, current_a):
            super().set_current(current_a)
            self.current_a = current_a

        def input_on(self):
            super().input_on()
            self.input_enabled = True

        def input_off(self):
            super().input_off()
            self.input_enabled = False

        def measure_current(self):
            self._record("load.measure_current")
            return self.current_a if self.input_enabled else 0.0

        def measure_voltage(self):
            self._record("load.measure_voltage")
            return 5.0 - 0.05 * self.measure_current()

        def measure_power(self):
            self._record("load.measure_power")
            return self.measure_voltage() * self.measure_current()

    class SweepSupply(FakeSupply):
        def __init__(self, calls, load):
            super().__init__(calls)
            self.load = load

        def measure_voltage(self, channel):
            self._record("supply.measure_voltage", channel)
            return 5.0 if self.output_enabled[channel] else 0.0

        def measure_current(self, channel):
            self._record("supply.measure_current", channel)
            return self.load.current_a if self.load.input_enabled else 0.0

        def measure_power(self, channel):
            self._record("supply.measure_power", channel)
            return self.measure_voltage(channel) * self.measure_current(channel)

    bench = FakeBench()
    bench.load = SweepLoad(bench.calls)
    bench.supply = SweepSupply(bench.calls, bench.load)
    root = Path(__file__).resolve().parent.parent
    recipe = load_recipe(root / "recipes" / "load_sweep.yaml")
    config = load_config(root / "config" / "lab.example.yaml")
    profiles = load_safety_profiles(root / "config" / "safety_profiles.yaml")
    result = runner.run_recipe(
        recipe,
        config,
        "main_bench",
        profiles,
        transport_factory=bench.transport_factory,
        driver_factory=bench.driver_factory,
        results_base=tmp_path / "results",
        sleep=lambda _: None,
    )

    assert result.outcome == "pass"
    records = [
        json.loads(line)
        for line in (result.run_dir / "measurements.jsonl").read_text().splitlines()
    ]
    currents = [round(0.05 + 0.025 * index, 3) for index in range(11)]
    currents += currents[-2::-1]
    assert len(records) == 22
    assert records[0]["save_as"] == "no_load"
    assert [record["values"]["load_current_a"] for record in records[1:]] == currents
    assert [call[1] for call in bench.calls if call[0] == "load.set_current"] == currents
    assert len({record["save_as"] for record in records}) == len(records)
    assert all(record["status"] == "pass" for record in records)
    assert bench.load.input_enabled is False
    assert bench.supply.output_enabled[1] is False
    page = generate_report(result.run_dir).read_text(encoding="utf-8")
    assert page.count("<svg ") == 4
    assert "Largest current error" in page


# -- measurement expectations ---------------------------------------------------


def test_measurement_expectation_passes_at_inclusive_bound(fake_safety, tmp_path):
    bench = FakeBench()
    recipe = make_recipe_with_expectation({"min": 5.001, "max": 5.001})
    result = run(bench, recipe, tmp_path)

    record = json.loads(
        (result.run_dir / "measurements.jsonl").read_text().splitlines()[0]
    )
    assert record["status"] == "pass"
    assert record["verdicts"]["supply_voltage_v"] == {
        "status": "pass",
        "min": 5.001,
        "max": 5.001,
    }
    assert read_summary(result)["outcome"] == "pass"


def test_failed_expectation_is_recorded_then_runs_cleanup(fake_safety, tmp_path):
    bench = FakeBench()
    recipe = make_recipe_with_expectation({"max": 5.0})
    with pytest.raises(runner.MeasurementExpectationError, match="above maximum"):
        run(bench, recipe, tmp_path)

    run_dir = next((tmp_path / "results").iterdir())
    record = json.loads(
        (run_dir / "measurements.jsonl").read_text().splitlines()[0]
    )
    assert record["values"]["supply_voltage_v"] == 5.001
    assert record["status"] == "fail"
    assert record["verdicts"]["supply_voltage_v"]["status"] == "fail"
    assert [call[0] for call in bench.calls][-2:] == [
        "load.input_off",
        "supply.all_outputs_off",
    ]
    summary = read_summary(run_dir)
    assert summary["status"] == "failed"
    assert summary["outcome"] == "fail"


def test_nonfinite_expected_measurement_is_recorded_as_failure(
    fake_safety, tmp_path
):
    bench = FakeBench()
    bench.supply.voltage_v = math.nan
    recipe = make_recipe_with_expectation({"max": 6.0})
    with pytest.raises(runner.MeasurementExpectationError, match="not finite"):
        run(bench, recipe, tmp_path)

    run_dir = next((tmp_path / "results").iterdir())
    record = json.loads(
        (run_dir / "measurements.jsonl").read_text().splitlines()[0]
    )
    assert math.isnan(record["values"]["supply_voltage_v"])
    verdict = record["verdicts"]["supply_voltage_v"]
    assert verdict["status"] == "fail"
    assert verdict["reason"] == "value is not finite"
    assert read_summary(run_dir)["outcome"] == "fail"


def test_expectation_failure_preserves_result_when_cleanup_also_fails(
    fake_safety, tmp_path
):
    bench = FakeBench(
        load_raises={"load.input_off": KeyboardInterrupt("cleanup interrupted")}
    )
    recipe = make_recipe_with_expectation({"max": 5.0})
    with pytest.raises(runner.MeasurementExpectationError):
        run(bench, recipe, tmp_path)

    assert [call[0] for call in bench.calls][-1] == "supply.all_outputs_off"
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["outcome"] == "fail"
    assert "MeasurementExpectationError" in summary["error"]


# -- automatic CSV export --------------------------------------------------------


def test_successful_run_writes_measurements_csv(fake_safety, tmp_path):
    bench = FakeBench()
    result = run(bench, make_recipe(), tmp_path)

    csv_path = result.run_dir / "measurements.csv"
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["save_as"] == "operating_point"
    assert float(rows[0]["supply_voltage_v"]) == 5.001
    assert float(rows[0]["load_current_a"]) == 0.250
    assert rows[0]["measurement_status"] == "not_checked"
    assert rows[0]["supply_voltage_v__verdict"] == "not_checked"


def test_failed_run_with_measurements_writes_csv(fake_safety, tmp_path):
    # The measure step succeeds; a later cleanup action fails the run.
    bench = FakeBench(load_raises={"load.input_off": RuntimeError("stuck relay")})
    with pytest.raises(RuntimeError, match="stuck relay"):
        run(bench, make_recipe(), tmp_path)

    run_dir = next((tmp_path / "results").iterdir())
    assert read_summary(run_dir)["status"] == "failed"
    with open(run_dir / "measurements.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["save_as"] == "operating_point"


def test_run_without_measurements_writes_no_csv(fake_safety, tmp_path):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"] = [s for s in raw["steps"] if s["action"] != "measure"]
    bench = FakeBench()
    result = run(bench, parse_recipe(raw), tmp_path)

    assert result.status == "success"
    assert not (result.run_dir / "measurements.csv").exists()


def test_csv_export_failure_does_not_mask_run_outcome(
    fake_safety, monkeypatch, tmp_path, capsys
):
    def broken_export(run_dir, csv_path=None):
        raise OSError("disk full")

    monkeypatch.setattr(runner.results, "export_csv", broken_export)
    bench = FakeBench()
    result = run(bench, make_recipe(), tmp_path)

    assert result.status == "success"
    assert "could not write measurements.csv" in capsys.readouterr().err
    assert not (result.run_dir / "measurements.csv").exists()


# -- cleanup guarantees --------------------------------------------------------------


def test_finally_runs_after_midstep_exception(fake_safety, tmp_path):
    bench = FakeBench(load_raises={"load.input_on": RuntimeError("input stuck")})
    with pytest.raises(RuntimeError, match="input stuck"):
        run(bench, make_recipe(), tmp_path)

    methods = [call[0] for call in bench.calls]
    assert methods[-2:] == ["load.input_off", "supply.all_outputs_off"]
    assert all(t.closed for t in bench.transports)

    run_dir = next((tmp_path / "results").iterdir())
    summary = read_summary(run_dir)
    assert summary["status"] == "failed"
    assert "input stuck" in summary["error"]


def test_supply_enable_failure_attempts_immediate_channel_off(
    fake_safety, tmp_path
):
    bench = FakeBench(
        supply_raises={"supply.output_on": RuntimeError("enable acknowledgement lost")}
    )
    with pytest.raises(RuntimeError, match="enable acknowledgement lost"):
        run(bench, make_recipe(), tmp_path)

    methods = [call[0] for call in bench.calls]
    on_index = methods.index("supply.output_on")
    assert methods[on_index + 1] == "supply.output_off"
    assert methods[-2:] == ["load.input_off", "supply.all_outputs_off"]
    assert bench.supply.output_enabled[1] is False


def test_supply_enable_shutdown_failure_preserves_original_error(
    fake_safety, tmp_path, capsys
):
    bench = FakeBench(
        supply_raises={
            "supply.output_on": RuntimeError("enable failure"),
            "supply.output_off": OSError("off failure"),
        }
    )
    with pytest.raises(RuntimeError, match="enable failure"):
        run(bench, make_recipe(), tmp_path)

    assert ("supply.output_off", 1) in bench.calls
    assert [call[0] for call in bench.calls][-1] == "supply.all_outputs_off"
    assert "off failure" in capsys.readouterr().err


def test_finally_runs_after_keyboard_interrupt(fake_safety, tmp_path):
    bench = FakeBench(supply_raises={"supply.measure_voltage": KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        run(bench, make_recipe(), tmp_path)

    methods = [call[0] for call in bench.calls]
    assert methods[-2:] == ["load.input_off", "supply.all_outputs_off"]
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["status"] == "failed"
    assert "KeyboardInterrupt" in summary["error"]


def test_cleanup_failure_does_not_mask_original_error(fake_safety, tmp_path, capsys):
    bench = FakeBench(
        load_raises={
            "load.input_on": RuntimeError("original failure"),
            "load.input_off": RuntimeError("cleanup failure"),
        }
    )
    with pytest.raises(RuntimeError, match="original failure"):
        run(bench, make_recipe(), tmp_path)

    # The failing cleanup step was reported, and later cleanup still ran.
    assert "cleanup failure" in capsys.readouterr().err
    assert [call[0] for call in bench.calls][-1] == "supply.all_outputs_off"


def test_cleanup_failure_after_success_propagates(fake_safety, tmp_path):
    bench = FakeBench(load_raises={"load.input_off": RuntimeError("stuck relay")})
    with pytest.raises(RuntimeError, match="stuck relay"):
        run(bench, make_recipe(), tmp_path)
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["status"] == "failed"


def test_cleanup_log_failure_still_runs_later_hardware_cleanup(
    fake_safety, monkeypatch, tmp_path, capsys
):
    append_event = runner.results.append_event

    def broken_first_cleanup_log(run_dir, *, phase, index, **kwargs):
        if phase == "finally" and index == 0:
            raise OSError("log disk full")
        return append_event(run_dir, phase=phase, index=index, **kwargs)

    monkeypatch.setattr(runner.results, "append_event", broken_first_cleanup_log)
    bench = FakeBench()
    with pytest.raises(OSError, match="log disk full"):
        run(bench, make_recipe(), tmp_path)

    assert [call[0] for call in bench.calls][-2:] == [
        "load.input_off",
        "supply.all_outputs_off",
    ]
    assert "could not log cleanup action" in capsys.readouterr().err


def test_cleanup_catches_repeated_baseexceptions_and_reraises_first(
    fake_safety, tmp_path
):
    bench = FakeBench(
        supply_raises={"supply.all_outputs_off": SystemExit("second cleanup")},
        load_raises={"load.input_off": KeyboardInterrupt("first cleanup")},
    )
    with pytest.raises(KeyboardInterrupt, match="first cleanup"):
        run(bench, make_recipe(), tmp_path)

    methods = [call[0] for call in bench.calls]
    assert methods[-2:] == ["load.input_off", "supply.all_outputs_off"]
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["outcome"] == "error"
    assert "first cleanup" in summary["error"]


def test_repeated_cleanup_interruptions_do_not_mask_original(
    fake_safety, tmp_path
):
    bench = FakeBench(
        supply_raises={"supply.all_outputs_off": SystemExit("second cleanup")},
        load_raises={
            "load.input_on": RuntimeError("original"),
            "load.input_off": KeyboardInterrupt("first cleanup"),
        },
    )
    with pytest.raises(RuntimeError, match="original"):
        run(bench, make_recipe(), tmp_path)

    assert [call[0] for call in bench.calls][-2:] == [
        "load.input_off",
        "supply.all_outputs_off",
    ]
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["outcome"] == "error"
    assert "RuntimeError: original" == summary["error"]


# -- post-enable live load checks ----------------------------------------------


@pytest.mark.parametrize(
    ("readings", "message"),
    [
        ({"voltage_v": 6.1, "power_w": 1.5}, "measured voltage"),
        ({"voltage_v": 5.0, "power_w": 201.0}, "measured power"),
    ],
)
def test_load_enable_violation_turns_off_and_finally_still_runs(
    fake_safety, tmp_path, readings, message
):
    bench = FakeBench(load_readings=readings)
    with pytest.raises(Exception, match=message):
        run(bench, make_recipe(), tmp_path)

    methods = [call[0] for call in bench.calls]
    on_index = methods.index("load.input_on")
    assert methods[on_index + 1:on_index + 4] == [
        "load.measure_voltage",
        "load.measure_current",
        "load.measure_power",
    ]
    assert methods.count("load.input_off") == 2
    assert methods[-1] == "supply.all_outputs_off"
    assert read_summary(next((tmp_path / "results").iterdir()))["outcome"] == "error"


# -- fail-fast validation ---------------------------------------------------------


def test_unsafe_setpoint_aborts_before_any_driver_call(fake_safety, tmp_path):
    recipe = make_recipe(parameters={"voltage_v": 100.0})
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="unsafe setpoint"):
        run(bench, recipe, tmp_path)
    assert bench.calls == []
    assert bench.transports == []
    assert not (tmp_path / "results").exists()


def test_supply_power_limit_aborts_before_transport(fake_safety, tmp_path):
    profiles = copy.deepcopy(PROFILES)
    profiles["dp821_physical"]["max_power_w"] = 4.0
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="voltage-current product"):
        runner.run_recipe(
            make_recipe(),
            make_config(),
            "main_bench",
            profiles,
            transport_factory=bench.transport_factory,
            driver_factory=bench.driver_factory,
            results_base=tmp_path / "results",
        )
    assert bench.transports == []


def test_load_worst_case_power_aborts_before_transport(fake_safety, tmp_path):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"][1]["current_a"] = 40.0
    raw["steps"][1]["max_voltage_v"] = 6.0
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="worst-case load power"):
        run(bench, parse_recipe(raw), tmp_path)
    assert bench.transports == []


def test_unsafe_finally_setpoint_also_aborts(fake_safety, tmp_path):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["finally"].insert(
        0,
        {
            "action": "load.configure_cc",
            "current_a": 999.0,
            "max_voltage_v": 6.0,
        },
    )
    recipe = parse_recipe(raw)
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="unsafe setpoint at finally"):
        run(bench, recipe, tmp_path)
    assert bench.calls == []


def test_runtime_supply_enable_guard_defends_against_mutated_recipe(
    fake_safety, tmp_path
):
    recipe = make_recipe()
    del recipe.steps[0]  # bypass schema validation after construction
    bench = FakeBench()
    with pytest.raises(runner.RuntimeSafetyError, match="supply.configure"):
        run(bench, recipe, tmp_path)
    assert "supply.output_on" not in [call[0] for call in bench.calls]


def test_runtime_supply_configure_refuses_enabled_output_before_setpoint_writes(
    fake_safety, tmp_path
):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"].insert(
        3,
        {
            "action": "supply.configure",
            "channel": 1,
            "voltage_v": 4.0,
            "current_limit_a": 0.5,
        },
    )
    bench = FakeBench()
    with pytest.raises(runner.RuntimeSafetyError, match="output is ON"):
        run(bench, parse_recipe(raw), tmp_path)

    assert [call[0] for call in bench.calls].count("supply.set_voltage") == 1
    assert [call[0] for call in bench.calls].count("supply.set_current_limit") == 1
    assert [call[0] for call in bench.calls][-1] == "supply.all_outputs_off"


def test_runtime_load_enable_guard_defends_against_mutated_recipe(
    fake_safety, tmp_path
):
    recipe = make_recipe()
    del recipe.steps[1]  # bypass schema validation after construction
    bench = FakeBench()
    with pytest.raises(runner.RuntimeSafetyError, match="load.configure_cc"):
        run(bench, recipe, tmp_path)
    assert "load.input_on" not in [call[0] for call in bench.calls]


def test_runtime_configuration_persists_across_off_on_cycles(
    fake_safety, tmp_path
):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"].insert(3, {"action": "supply.output_off", "channel": 1})
    raw["steps"].insert(4, {"action": "supply.output_on", "channel": 1})
    raw["steps"].insert(7, {"action": "load.input_off"})
    raw["steps"].insert(8, {"action": "load.input_on"})
    bench = FakeBench()
    run(bench, parse_recipe(raw), tmp_path)
    methods = [call[0] for call in bench.calls]
    assert methods.count("supply.output_on") == 2
    assert methods.count("load.input_on") == 2


def test_serial_mismatch_closes_all_sessions_before_actions(fake_safety, tmp_path):
    config = make_config()
    config.devices["psu_rigol_1"].expected_serial = "WRONG_SERIAL"
    bench = FakeBench()
    with pytest.raises(Exception, match="serial mismatch"):
        run(bench, make_recipe(), tmp_path, config=config)

    assert bench.calls == [("supply.identify",)]
    assert all(transport.closed for transport in bench.transports)
    summary = read_summary(next((tmp_path / "results").iterdir()))
    assert summary["outcome"] == "error"


def test_profile_type_mismatch_aborts_before_transport(fake_safety, tmp_path):
    profiles = copy.deepcopy(PROFILES)
    profiles["dp821_physical"]["type"] = "electronic_load"
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="has type 'electronic_load'"):
        runner.run_recipe(
            make_recipe(),
            make_config(),
            "main_bench",
            profiles,
            transport_factory=bench.transport_factory,
            driver_factory=bench.driver_factory,
            results_base=tmp_path / "results",
        )
    assert bench.transports == []


def test_requires_kind_mismatch_aborts(fake_safety, tmp_path):
    # A recipe that declares role 'supply' with the wrong kind (no supply.*
    # actions, so the recipe itself validates) must be rejected by the runner.
    recipe = parse_recipe(
        {
            "schema_version": 1,
            "name": "mismatch",
            "requires": {"supply": {"kind": "electronic_load"}},
            "steps": [],
        }
    )
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="kind"):
        run(bench, recipe, tmp_path)
    assert bench.transports == []


def test_missing_role_in_setup_aborts(fake_safety, tmp_path):
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="does not provide role 'load'"):
        runner.run_recipe(
            make_recipe(),
            make_config(),
            "supply_only",
            PROFILES,
            transport_factory=bench.transport_factory,
            driver_factory=bench.driver_factory,
            results_base=tmp_path / "results",
        )
    assert bench.transports == []


def test_missing_safety_profile_is_hard_error(fake_safety, tmp_path):
    bench = FakeBench()
    profiles = {"dp821_physical": PROFILES["dp821_physical"]}  # load profile absent
    with pytest.raises(runner.RunnerError, match="dl3021_physical"):
        runner.run_recipe(
            make_recipe(),
            make_config(),
            "main_bench",
            profiles,
            transport_factory=bench.transport_factory,
            driver_factory=bench.driver_factory,
            results_base=tmp_path / "results",
        )
    assert bench.transports == []


def test_unknown_setup_aborts(fake_safety, tmp_path):
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="unknown setup"):
        runner.run_recipe(
            make_recipe(),
            make_config(),
            "nope",
            PROFILES,
            transport_factory=bench.transport_factory,
            driver_factory=bench.driver_factory,
            results_base=tmp_path / "results",
        )


# -- run subcommand (register + handler) --------------------------------------------


def build_run_args(argv):
    parser = argparse.ArgumentParser(prog="benchctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands_run.register(subparsers)
    return parser.parse_args(argv)


@pytest.fixture
def cli_files(tmp_path):
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(yaml.safe_dump(copy.deepcopy(BASE_RECIPE)), encoding="utf-8")
    config_path = tmp_path / "lab.yaml"
    config_path.write_text(yaml.safe_dump(copy.deepcopy(BASE_CONFIG)), encoding="utf-8")
    return recipe_path, config_path


def test_run_command_happy_path(fake_safety, monkeypatch, tmp_path, cli_files, capsys):
    recipe_path, config_path = cli_files
    bench = FakeBench()
    monkeypatch.setattr(runner, "make_transport", bench.transport_factory)
    monkeypatch.setattr(runner, "make_driver", bench.driver_factory)
    monkeypatch.setattr(runner, "time", types.SimpleNamespace(sleep=lambda s: None))

    args = build_run_args(
        [
            "run",
            str(recipe_path),
            "--setup",
            "main_bench",
            "--config",
            str(config_path),
            "--safety-profiles",
            str(tmp_path / "profiles.yaml"),
            "--results-dir",
            str(tmp_path / "results"),
        ]
    )
    exit_code = args.func(args)
    assert exit_code == 0
    assert "run complete" in capsys.readouterr().out
    assert [call[0] for call in bench.calls][-1] == "supply.all_outputs_off"


def test_run_command_rejects_unsafe_recipe(
    fake_safety, monkeypatch, tmp_path, cli_files, capsys
):
    recipe_path, config_path = cli_files
    raw = copy.deepcopy(BASE_RECIPE)
    raw["parameters"]["voltage_v"] = 100.0
    recipe_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    bench = FakeBench()
    monkeypatch.setattr(runner, "make_transport", bench.transport_factory)
    monkeypatch.setattr(runner, "make_driver", bench.driver_factory)

    args = build_run_args(
        [
            "run",
            str(recipe_path),
            "--setup",
            "main_bench",
            "--config",
            str(config_path),
            "--safety-profiles",
            str(tmp_path / "profiles.yaml"),
            "--results-dir",
            str(tmp_path / "results"),
        ]
    )
    exit_code = args.func(args)
    assert exit_code == 2
    assert "unsafe setpoint" in capsys.readouterr().err
    assert bench.calls == []


def test_every_sweep_setpoint_is_validated_before_transport(fake_safety, tmp_path):
    raw = copy.deepcopy(BASE_RECIPE)
    raw["steps"] = [
        {
            "action": "sweep",
            "start": 0.25,
            "stop": 50.25,
            "step": 10.0,
            "steps": [
                {
                    "action": "load.configure_cc",
                    "current_a": "${sweep.value}",
                    "max_voltage_v": 1.0,
                }
            ],
        }
    ]
    bench = FakeBench()
    with pytest.raises(runner.RunnerError, match="unsafe setpoint"):
        run(bench, parse_recipe(raw), tmp_path)
    assert bench.transports == []
    assert bench.calls == []
