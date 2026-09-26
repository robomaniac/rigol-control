"""Safety profile parsing and setpoint validation tests. No hardware."""

import copy
import math
from pathlib import Path

import pytest
import yaml

from benchctl.config import DeviceConfig
from benchctl.safety import (
    LoadProfile,
    SafetyError,
    SupplyChannelLimits,
    SupplyProfile,
    get_device_safety_profile,
    load_safety_profiles,
    validate_load_measurements,
    validate_load_setpoint,
    validate_supply_setpoint,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_PROFILES = {
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
            "allowed_modes": ["cc", "cv", "cr", "cp"],
        },
    },
}


def write_profiles(tmp_path, data) -> Path:
    path = tmp_path / "safety_profiles.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# -- parsing ------------------------------------------------------------------


def test_load_valid_profiles(tmp_path):
    profiles = load_safety_profiles(write_profiles(tmp_path, VALID_PROFILES))
    assert set(profiles) == {"dp821_physical", "dl3021_physical"}

    supply = profiles["dp821_physical"]
    assert isinstance(supply, SupplyProfile)
    assert set(supply.channels) == {1, 2}
    assert supply.channels[1].max_voltage_v == 60.0
    assert supply.channels[1].max_current_a == 1.0
    assert supply.channels[1].max_power_w == 60.0
    assert supply.channels[2].max_voltage_v == 8.0
    assert supply.channels[2].max_current_a == 10.0
    assert supply.channels[2].max_power_w == 80.0

    load = profiles["dl3021_physical"]
    assert isinstance(load, LoadProfile)
    assert load.max_voltage_v == 150.0
    assert load.max_current_a == 40.0
    assert load.max_power_w == 200.0
    assert load.allowed_modes == ["cc", "cv", "cr", "cp"]


def test_shipped_profiles_file_is_valid():
    profiles = load_safety_profiles(REPO_ROOT / "config" / "safety_profiles.yaml")
    supply = profiles["dp821_physical"]
    assert isinstance(supply, SupplyProfile)
    assert supply.channels[1] == SupplyChannelLimits(
        max_voltage_v=60.0, max_current_a=1.0, max_power_w=60.0
    )
    assert supply.channels[2] == SupplyChannelLimits(
        max_voltage_v=8.0, max_current_a=10.0, max_power_w=80.0
    )
    assert isinstance(profiles["dl3021_physical"], LoadProfile)


def test_unknown_top_level_field_rejected(tmp_path):
    data = copy.deepcopy(VALID_PROFILES)
    data["surprise"] = True
    with pytest.raises(SafetyError):
        load_safety_profiles(write_profiles(tmp_path, data))


def test_unknown_profile_field_rejected(tmp_path):
    data = copy.deepcopy(VALID_PROFILES)
    data["profiles"]["dl3021_physical"]["max_resistance_ohm"] = 15000
    with pytest.raises(SafetyError):
        load_safety_profiles(write_profiles(tmp_path, data))


def test_unknown_channel_field_rejected(tmp_path):
    data = copy.deepcopy(VALID_PROFILES)
    data["profiles"]["dp821_physical"]["channels"][1]["max_energy_j"] = 1.0
    with pytest.raises(SafetyError):
        load_safety_profiles(write_profiles(tmp_path, data))


def test_unknown_profile_type_rejected(tmp_path):
    data = copy.deepcopy(VALID_PROFILES)
    data["profiles"]["dp821_physical"]["type"] = "signal_generator"
    with pytest.raises(SafetyError):
        load_safety_profiles(write_profiles(tmp_path, data))


def test_wrong_schema_version_rejected(tmp_path):
    data = copy.deepcopy(VALID_PROFILES)
    data["schema_version"] = 2
    with pytest.raises(SafetyError):
        load_safety_profiles(write_profiles(tmp_path, data))


def test_missing_file_rejected(tmp_path):
    with pytest.raises(SafetyError):
        load_safety_profiles(tmp_path / "does_not_exist.yaml")


def test_invalid_yaml_rejected(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("profiles: [unclosed", encoding="utf-8")
    with pytest.raises(SafetyError):
        load_safety_profiles(path)


def test_non_mapping_top_level_rejected(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(SafetyError):
        load_safety_profiles(path)


# -- supply setpoint validation -------------------------------------------------


@pytest.fixture
def supply_profile() -> SupplyProfile:
    return SupplyProfile(
        type="power_supply",
        channels={
            1: SupplyChannelLimits(
                max_voltage_v=60.0, max_current_a=1.0, max_power_w=60.0
            ),
            2: SupplyChannelLimits(
                max_voltage_v=8.0, max_current_a=10.0, max_power_w=80.0
            ),
        },
    )


def test_supply_at_limit_passes(supply_profile):
    validate_supply_setpoint(supply_profile, 1, voltage_v=60.0, current_a=1.0)
    validate_supply_setpoint(supply_profile, 2, voltage_v=8.0, current_a=10.0)


def test_supply_product_over_power_limit_raises(supply_profile):
    supply_profile.channels[1].max_power_w = 50.0
    with pytest.raises(SafetyError, match="voltage-current product"):
        validate_supply_setpoint(
            supply_profile, 1, voltage_v=60.0, current_a=1.0
        )


def test_supply_zero_passes(supply_profile):
    validate_supply_setpoint(supply_profile, 1, voltage_v=0.0, current_a=0.0)


def test_supply_channel_only_passes(supply_profile):
    validate_supply_setpoint(supply_profile, 1)


def test_supply_above_voltage_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 1, voltage_v=60.001)


def test_supply_above_current_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 2, current_a=10.001)


def test_supply_negative_voltage_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 1, voltage_v=-0.1)


def test_supply_negative_current_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 1, current_a=-0.1)


def test_supply_nan_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 1, voltage_v=math.nan)


def test_supply_unknown_channel_raises(supply_profile):
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 3, voltage_v=1.0)


def test_supply_channel_limits_are_independent(supply_profile):
    # 5 A is fine on channel 2 but exceeds channel 1's 1 A limit.
    validate_supply_setpoint(supply_profile, 2, current_a=5.0)
    with pytest.raises(SafetyError):
        validate_supply_setpoint(supply_profile, 1, current_a=5.0)


# -- load setpoint validation ---------------------------------------------------


@pytest.fixture
def load_profile() -> LoadProfile:
    return LoadProfile(
        type="electronic_load",
        max_voltage_v=150.0,
        max_current_a=40.0,
        max_power_w=200.0,
        allowed_modes=["cc", "cp"],
    )


def test_load_at_limit_passes(load_profile):
    validate_load_setpoint(
        load_profile,
        mode="cc",
        current_a=40.0,
        max_voltage_v=5.0,
    )


def test_load_zero_passes(load_profile):
    validate_load_setpoint(
        load_profile,
        mode="cc",
        current_a=0.0,
        max_voltage_v=150.0,
    )


def test_load_no_values_passes(load_profile):
    validate_load_setpoint(load_profile)


def test_load_above_current_raises(load_profile):
    with pytest.raises(SafetyError):
        validate_load_setpoint(load_profile, current_a=40.001)


def test_load_negative_current_raises(load_profile):
    with pytest.raises(SafetyError):
        validate_load_setpoint(load_profile, current_a=-1.0)


def test_load_nan_raises(load_profile):
    with pytest.raises(SafetyError):
        validate_load_setpoint(load_profile, current_a=math.nan)


def test_load_disallowed_mode_raises(load_profile):
    with pytest.raises(SafetyError):
        validate_load_setpoint(load_profile, mode="cv")


def test_load_allowed_modes(load_profile):
    validate_load_setpoint(load_profile, mode="cc", max_voltage_v=5.0)
    validate_load_setpoint(load_profile, mode="cp")


def test_load_cc_requires_maximum_expected_voltage(load_profile):
    with pytest.raises(SafetyError, match="maximum expected voltage"):
        validate_load_setpoint(load_profile, mode="cc", current_a=1.0)


def test_load_above_maximum_expected_voltage_raises(load_profile):
    with pytest.raises(SafetyError, match="maximum expected voltage"):
        validate_load_setpoint(
            load_profile,
            mode="cc",
            current_a=1.0,
            max_voltage_v=150.001,
        )


def test_load_zero_maximum_expected_voltage_raises(load_profile):
    with pytest.raises(SafetyError, match="greater than zero"):
        validate_load_setpoint(
            load_profile,
            mode="cc",
            current_a=0.0,
            max_voltage_v=0.0,
        )


def test_load_worst_case_power_over_limit_raises(load_profile):
    with pytest.raises(SafetyError, match="worst-case load power"):
        validate_load_setpoint(
            load_profile,
            mode="cc",
            current_a=2.0,
            max_voltage_v=101.0,
        )


def test_load_nonfinite_maximum_voltage_raises(load_profile):
    with pytest.raises(SafetyError, match="finite"):
        validate_load_setpoint(
            load_profile,
            mode="cc",
            current_a=1.0,
            max_voltage_v=math.inf,
        )


def test_load_live_measurements_at_bounds_pass(load_profile):
    validate_load_measurements(
        load_profile,
        max_voltage_v=5.0,
        voltage_v=5.0,
        current_a=40.0,
        power_w=200.0,
    )


def test_load_live_voltage_over_declared_bound_raises(load_profile):
    with pytest.raises(SafetyError, match="declared maximum"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=6.0,
            voltage_v=6.001,
            current_a=1.0,
            power_w=6.001,
        )


def test_load_live_power_over_profile_raises(load_profile):
    with pytest.raises(SafetyError, match="measured power"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=150.0,
            voltage_v=100.0,
            current_a=3.0,
            power_w=200.001,
        )


def test_load_live_current_over_profile_raises(load_profile):
    with pytest.raises(SafetyError, match="measured current.*exceeds"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=6.0,
            voltage_v=1.0,
            current_a=40.001,
            power_w=40.001,
        )


def test_load_live_negative_current_raises(load_profile):
    with pytest.raises(SafetyError, match="measured current.*negative"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=6.0,
            voltage_v=1.0,
            current_a=-0.001,
            power_w=0.0,
        )


@pytest.mark.parametrize(
    ("voltage_v", "power_w", "field"),
    [(-0.001, 0.0, "measured voltage"), (1.0, -0.001, "measured power")],
)
def test_load_live_negative_voltage_or_power_raises(
    load_profile, voltage_v, power_w, field
):
    with pytest.raises(SafetyError, match=field + ".*negative"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=6.0,
            voltage_v=voltage_v,
            current_a=0.1,
            power_w=power_w,
        )


def test_load_live_nonfinite_measurement_raises(load_profile):
    with pytest.raises(SafetyError, match="must be finite"):
        validate_load_measurements(
            load_profile,
            max_voltage_v=6.0,
            voltage_v=math.nan,
            current_a=1.0,
            power_w=5.0,
        )


# -- profile/device compatibility ----------------------------------------------


def _device(kind, driver, profile) -> DeviceConfig:
    return DeviceConfig(
        kind=kind,
        driver=driver,
        resource="TCPIP0::192.0.2.10::INSTR",
        safety_profile=profile,
    )


def test_device_profile_lookup_returns_compatible_profile(
    supply_profile, load_profile
):
    profiles = {"supply": supply_profile, "load": load_profile}
    device = _device("power_supply", "rigol_dp800", "supply")
    assert get_device_safety_profile(profiles, "psu", device) is supply_profile


def test_device_profile_lookup_rejects_missing_profile(supply_profile):
    device = _device("power_supply", "rigol_dp800", "missing")
    with pytest.raises(SafetyError, match="missing safety profile"):
        get_device_safety_profile({"supply": supply_profile}, "psu", device)


def test_device_profile_lookup_rejects_type_mismatch(load_profile):
    device = _device("power_supply", "rigol_dp800", "load")
    with pytest.raises(SafetyError, match="has type 'electronic_load'"):
        get_device_safety_profile({"load": load_profile}, "psu", device)
