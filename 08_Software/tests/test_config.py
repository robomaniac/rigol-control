"""Configuration validation tests. No hardware is contacted."""

import copy
from pathlib import Path

import pytest
import yaml

from benchctl.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

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


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "lab.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_valid_config_loads(tmp_path):
    config = load_config(write_config(tmp_path, BASE_CONFIG))
    assert set(config.devices) == {"psu_rigol_1", "load_rigol_1"}
    assert config.devices["psu_rigol_1"].driver == "rigol_dp800"
    assert config.devices["psu_rigol_1"].expected_serial is None
    assert config.setups["main_bench"]["supply"] == "psu_rigol_1"


def test_shipped_example_config_loads():
    config = load_config(REPO_ROOT / "config" / "lab.example.yaml")
    assert config.schema_version == 1
    assert set(config.setups["main_bench"]) == {"supply", "load"}
    assert config.devices["psu_rigol_1"].resource == (
        "TCPIP0::supply.example.invalid::INSTR"
    )
    assert config.devices["load_rigol_1"].resource == (
        "TCPIP0::load.example.invalid::INSTR"
    )
    assert config.devices["psu_rigol_1"].expected_serial is None
    assert config.devices["load_rigol_1"].expected_serial is None


def test_unknown_top_level_field_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["surprise"] = True
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_unknown_device_field_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["max_volts"] = 30
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_invalid_schema_version_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["schema_version"] = 2
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_setup_referencing_missing_device_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["setups"]["main_bench"]["supply"] = "no_such_device"
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_setup_role_kind_mismatch_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    # An electronic load cannot fill the 'supply' role.
    data["setups"]["main_bench"]["supply"] = "load_rigol_1"
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_unknown_setup_role_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["setups"]["main_bench"]["oscilloscope"] = "psu_rigol_1"
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_unknown_driver_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["driver"] = "keysight_e36300"
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


@pytest.mark.parametrize(
    ("device_name", "wrong_kind"),
    [
        ("psu_rigol_1", "electronic_load"),
        ("load_rigol_1", "power_supply"),
    ],
)
def test_driver_kind_mismatch_rejected(tmp_path, device_name, wrong_kind):
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"][device_name]["kind"] = wrong_kind
    with pytest.raises(ConfigError, match="driver.*requires kind"):
        load_config(write_config(tmp_path, data))


def test_non_tcpip_resource_rejected(tmp_path):
    data = copy.deepcopy(BASE_CONFIG)
    data["devices"]["psu_rigol_1"]["resource"] = "GPIB0::5::INSTR"
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, data))


def test_invalid_yaml_rejected(tmp_path):
    path = tmp_path / "lab.yaml"
    path.write_text("devices: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_non_mapping_yaml_rejected(tmp_path):
    path = tmp_path / "lab.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "does_not_exist.yaml")
