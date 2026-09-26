"""Safety-hardened manual instrument commands.

Exposes ``register(subparsers)`` so the CLI can wire these subcommands in
a later integration pass. Every subparser sets ``func`` to a handler with
the signature ``handler(args) -> int`` (0 on success, nonzero on failure).

Safety model: the "on" commands (``output-on``, ``input-on``) validate all
setpoints against the device's safety profile *before* any instrument
connection is opened; a validation failure means no SCPI traffic at all.
Every live command identifies the instrument and verifies its serial when
``expected_serial`` is configured. ``measure`` is otherwise read-only, and ``input-on``
also checks live voltage/current/power immediately after enabling.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import cast

from benchctl.paths import DEFAULT_CONFIG_PATH, DEFAULT_SAFETY_PROFILES_PATH
from benchctl.config import ConfigError, DeviceConfig, LabConfig, load_config
from benchctl.identity import identify_and_verify
from benchctl.interfaces import Transport
from benchctl.safety import (
    LoadProfile,
    SafetyError,
    SupplyProfile,
    get_device_safety_profile,
    load_safety_profiles,
    validate_load_measurements,
    validate_load_setpoint,
    validate_supply_setpoint,
)
from benchctl.transport import VisaTransport


LOAD_MODES = ("cc",)


class CommandError(Exception):
    """Raised for user-facing failures detected before touching hardware."""


def make_transport(device_name: str, device: DeviceConfig) -> Transport:
    """Default transport factory; monkeypatchable in tests."""
    return VisaTransport(device_name, device.resource)


def get_driver_class(name: str):
    """Resolve a driver class by registry name; monkeypatchable in tests.

    Imported lazily so that importing this module never imports driver
    code (tests substitute fakes and never touch the real drivers).
    """
    from benchctl.registry import get_driver_class as _get

    return _get(name)


# -- shared helpers -----------------------------------------------------------


def _get_device(config: LabConfig, name: str) -> DeviceConfig:
    if name not in config.devices:
        raise CommandError(
            f"unknown device {name!r} (configured devices: {sorted(config.devices)})"
        )
    return config.devices[name]


def _require_kind(name: str, device: DeviceConfig, kind: str) -> None:
    if device.kind != kind:
        raise CommandError(
            f"device {name!r} has kind {device.kind!r}; "
            f"this command requires kind {kind!r}"
        )


def _get_profile(
    profiles_path: Path, device_name: str, device: DeviceConfig
) -> SupplyProfile | LoadProfile:
    profiles = load_safety_profiles(profiles_path)
    return get_device_safety_profile(profiles, device_name, device)


def _get_supply_profile(
    profiles_path: Path, device_name: str, device: DeviceConfig
) -> SupplyProfile:
    return cast(SupplyProfile, _get_profile(profiles_path, device_name, device))


def _get_load_profile(
    profiles_path: Path, device_name: str, device: DeviceConfig
) -> LoadProfile:
    return cast(LoadProfile, _get_profile(profiles_path, device_name, device))


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _failed(device_name: str, exc: Exception) -> int:
    print(f"{device_name}: FAILED: {exc}", file=sys.stderr)
    return 1


def _best_effort_input_off(driver, original: BaseException) -> None:
    """Disable a possibly enabled load without masking the triggering error."""
    try:
        driver.input_off()
    except BaseException as shutdown_error:
        original.add_note(
            "load input-off after enable failure also failed: "
            f"{type(shutdown_error).__name__}: {shutdown_error}"
        )
        print(
            "warning: load input-off after enable failure also failed: "
            f"{shutdown_error}",
            file=sys.stderr,
        )


def _best_effort_output_off(driver, channel: int, original: BaseException) -> None:
    """Disable a possibly enabled supply channel without masking the error."""
    try:
        driver.output_off(channel)
    except BaseException as shutdown_error:
        original.add_note(
            f"supply CH{channel} output-off after enable failure also failed: "
            f"{type(shutdown_error).__name__}: {shutdown_error}"
        )
        print(
            f"warning: supply CH{channel} output-off after enable failure "
            f"also failed: {shutdown_error}",
            file=sys.stderr,
        )


# -- handlers -----------------------------------------------------------------


def handle_measure(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        device = _get_device(config, args.device)
        if device.kind == "power_supply":
            profile = _get_supply_profile(args.safety_profiles, args.device, device)
            channels = sorted(profile.channels)
        else:
            _get_load_profile(args.safety_profiles, args.device, device)
    except (ConfigError, SafetyError, CommandError) as exc:
        return _error(str(exc))
    try:
        driver_cls = get_driver_class(device.driver)
        with make_transport(args.device, device) as transport:
            driver = driver_cls(transport)
            identify_and_verify(args.device, device, driver)
            if device.kind == "power_supply":
                print(f"{args.device}:")
                for channel in channels:
                    volts = driver.measure_voltage(channel)
                    amps = driver.measure_current(channel)
                    watts = driver.measure_power(channel)
                    print(
                        f"  channel {channel}: "
                        f"{volts:.3f} V, {amps:.3f} A, {watts:.3f} W"
                    )
            else:
                volts = driver.measure_voltage()
                amps = driver.measure_current()
                watts = driver.measure_power()
                print(f"{args.device}: {volts:.3f} V, {amps:.3f} A, {watts:.3f} W")
    except Exception as exc:
        return _failed(args.device, exc)
    return 0


def handle_output_off(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        device = _get_device(config, args.device)
        _require_kind(args.device, device, "power_supply")
    except (ConfigError, CommandError) as exc:
        return _error(str(exc))
    try:
        driver_cls = get_driver_class(device.driver)
        with make_transport(args.device, device) as transport:
            driver = driver_cls(transport)
            identify_and_verify(args.device, device, driver)
            if args.all:
                driver.all_outputs_off()
            else:
                driver.output_off(args.channel)
            driver.check_errors()
    except Exception as exc:
        return _failed(args.device, exc)
    if args.all:
        print(f"{args.device}: all outputs off")
    else:
        print(f"{args.device}: channel {args.channel} output off")
    return 0


def handle_input_off(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        device = _get_device(config, args.device)
        _require_kind(args.device, device, "electronic_load")
    except (ConfigError, CommandError) as exc:
        return _error(str(exc))
    try:
        driver_cls = get_driver_class(device.driver)
        with make_transport(args.device, device) as transport:
            driver = driver_cls(transport)
            identify_and_verify(args.device, device, driver)
            driver.input_off()
            driver.check_errors()
    except Exception as exc:
        return _failed(args.device, exc)
    print(f"{args.device}: input off")
    return 0


def handle_output_on(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        device = _get_device(config, args.device)
        _require_kind(args.device, device, "power_supply")
        profile = _get_supply_profile(args.safety_profiles, args.device, device)
        validate_supply_setpoint(
            profile,
            args.channel,
            voltage_v=args.voltage_v,
            current_a=args.current_limit_a,
        )
    except (ConfigError, SafetyError, CommandError) as exc:
        return _error(str(exc))
    try:
        driver_cls = get_driver_class(device.driver)
        with make_transport(args.device, device) as transport:
            driver = driver_cls(transport)
            identify_and_verify(args.device, device, driver)
            if driver.get_output_enabled(args.channel):
                raise CommandError(
                    f"channel {args.channel} output is ON; turn it OFF before "
                    "changing voltage or current limit"
                )
            driver.set_voltage(args.channel, args.voltage_v)
            driver.set_current_limit(args.channel, args.current_limit_a)
            try:
                driver.output_on(args.channel)
                driver.check_errors()
            except BaseException as exc:
                _best_effort_output_off(driver, args.channel, exc)
                raise
    except Exception as exc:
        return _failed(args.device, exc)
    print(
        f"{args.device}: channel {args.channel} output on "
        f"({args.voltage_v} V, current limit {args.current_limit_a} A)"
    )
    return 0


def handle_input_on(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        device = _get_device(config, args.device)
        _require_kind(args.device, device, "electronic_load")
        if args.mode != "cc":
            raise CommandError(
                f"input-on supports only constant-current mode 'cc', not "
                f"{args.mode!r}"
            )
        profile = _get_load_profile(args.safety_profiles, args.device, device)
        validate_load_setpoint(
            profile,
            mode=args.mode,
            current_a=args.current_a,
            max_voltage_v=args.max_voltage_v,
        )
    except (ConfigError, SafetyError, CommandError) as exc:
        return _error(str(exc))
    try:
        driver_cls = get_driver_class(device.driver)
        with make_transport(args.device, device) as transport:
            driver = driver_cls(transport)
            identify_and_verify(args.device, device, driver)
            if driver.get_input_enabled():
                raise CommandError(
                    "load input is ON; turn it OFF before changing mode or current"
                )
            driver.set_mode(args.mode)
            driver.set_current(args.current_a)
            try:
                driver.input_on()
                voltage_v = float(driver.measure_voltage())
                current_a = float(driver.measure_current())
                power_w = float(driver.measure_power())
                validate_load_measurements(
                    profile,
                    max_voltage_v=args.max_voltage_v,
                    voltage_v=voltage_v,
                    current_a=current_a,
                    power_w=power_w,
                )
                driver.check_errors()
            except BaseException as exc:
                _best_effort_input_off(driver, exc)
                raise
    except Exception as exc:
        return _failed(args.device, exc)
    print(
        f"{args.device}: input on (mode {args.mode}, {args.current_a} A; "
        f"verified {voltage_v:.3f} V, {current_a:.3f} A, {power_w:.3f} W)"
    )
    return 0


# -- CLI wiring ---------------------------------------------------------------


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the lab YAML configuration (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--safety-profiles",
        type=Path,
        default=DEFAULT_SAFETY_PROFILES_PATH,
        dest="safety_profiles",
        help=(
            "Path to the safety profiles YAML "
            f"(default: {DEFAULT_SAFETY_PROFILES_PATH})."
        ),
    )
    parser.add_argument(
        "--device",
        required=True,
        help="Name of the configured device to operate on.",
    )


def register(subparsers) -> None:
    """Add the manual-command subparsers to an argparse subparsers object."""
    measure = subparsers.add_parser(
        "measure",
        help="Read voltage/current/power from a device (read-only).",
    )
    _add_common_arguments(measure)
    measure.set_defaults(func=handle_measure)

    output_off = subparsers.add_parser(
        "output-off",
        help="Turn a power supply output off (one channel or all).",
    )
    _add_common_arguments(output_off)
    group = output_off.add_mutually_exclusive_group(required=True)
    group.add_argument("--channel", type=int, help="Channel to turn off.")
    group.add_argument(
        "--all", action="store_true", help="Turn all outputs off."
    )
    output_off.set_defaults(func=handle_output_off)

    input_off = subparsers.add_parser(
        "input-off",
        help="Turn an electronic load input off.",
    )
    _add_common_arguments(input_off)
    input_off.set_defaults(func=handle_input_off)

    output_on = subparsers.add_parser(
        "output-on",
        help=(
            "Set voltage and current limit, then enable a power supply "
            "output (validated against the safety profile first)."
        ),
    )
    _add_common_arguments(output_on)
    output_on.add_argument(
        "--channel", type=int, required=True, help="Channel to configure."
    )
    output_on.add_argument(
        "--voltage-v",
        type=float,
        required=True,
        dest="voltage_v",
        help="Voltage setpoint in volts.",
    )
    output_on.add_argument(
        "--current-limit-a",
        type=float,
        required=True,
        dest="current_limit_a",
        help="Current limit in amperes.",
    )
    output_on.set_defaults(func=handle_output_on)

    input_on = subparsers.add_parser(
        "input-on",
        help=(
            "Set CC current, then enable and verify an electronic load input "
            "(setpoint and expected voltage validated before connecting)."
        ),
    )
    _add_common_arguments(input_on)
    input_on.add_argument(
        "--mode",
        type=str.lower,
        choices=LOAD_MODES,
        required=True,
        help="Load mode (only constant-current 'cc' is supported safely).",
    )
    input_on.add_argument(
        "--current-a",
        type=float,
        required=True,
        dest="current_a",
        help="Current setpoint in amperes.",
    )
    input_on.add_argument(
        "--max-voltage-v",
        type=float,
        required=True,
        dest="max_voltage_v",
        help=(
            "Maximum voltage expected after enabling; used for preflight "
            "power validation and the immediate post-enable safety check."
        ),
    )
    input_on.set_defaults(func=handle_input_on)
