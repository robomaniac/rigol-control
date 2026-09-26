"""benchctl command-line interface (argparse, standard library only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from benchctl.paths import DEFAULT_CONFIG_PATH
from benchctl.config import ConfigError, DeviceConfig, LabConfig, load_config
from benchctl.identity import SerialMismatchError, identify_and_verify
from benchctl.interfaces import Identification, Transport
from benchctl.registry import get_driver_class
from benchctl.transport import VisaTransport


TransportFactory = Callable[[str, DeviceConfig], Transport]


class SelectionError(Exception):
    """Raised when --device or --setup does not match the configuration."""


def make_transport(device_name: str, device: DeviceConfig) -> VisaTransport:
    return VisaTransport(device_name, device.resource)


def select_devices(
    config: LabConfig,
    device: str | None = None,
    setup: str | None = None,
) -> list[str]:
    """Resolve CLI selection options to a list of logical device names."""
    if device is not None:
        if device not in config.devices:
            raise SelectionError(
                f"unknown device {device!r} (configured devices: "
                f"{sorted(config.devices)})"
            )
        return [device]
    if setup is not None:
        if setup not in config.setups:
            raise SelectionError(
                f"unknown setup {setup!r} (configured setups: "
                f"{sorted(config.setups)})"
            )
        return list(config.setups[setup].values())
    return list(config.devices)


def identify_device(
    name: str,
    device: DeviceConfig,
    transport_factory: TransportFactory,
) -> Identification:
    driver_cls = get_driver_class(device.driver)
    with transport_factory(name, device) as transport:
        return identify_and_verify(name, device, driver_cls(transport))


def run_identify(
    config: LabConfig,
    names: list[str],
    transport_factory: TransportFactory,
) -> int:
    """Identify each selected device; continue past failures.

    Returns 0 if every device identified successfully, 1 otherwise.
    """
    failures = 0
    for name in names:
        device = config.devices[name]
        try:
            ident = identify_device(name, device, transport_factory)
        except SerialMismatchError as exc:
            print(
                f"{name}: FAILED ({device.resource}): {exc}",
                file=sys.stderr,
            )
            failures += 1
            continue
        except Exception as exc:
            print(f"{name}: FAILED ({device.resource}): {exc}", file=sys.stderr)
            failures += 1
            continue
        print(f"{name}:")
        print(f"  resource:     {device.resource}")
        print(f"  manufacturer: {ident.manufacturer}")
        print(f"  model:        {ident.model}")
        print(f"  serial:       {ident.serial}")
        print(f"  firmware:     {ident.firmware}")
    return 1 if failures else 0


def handle_identify(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        names = select_devices(config, device=args.device, setup=args.setup)
    except (ConfigError, SelectionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return run_identify(config, names, make_transport)


def build_parser() -> argparse.ArgumentParser:
    # Imported here so that `benchctl identify` stays importable even if an
    # optional subsystem is being worked on; each module wires its own
    # subcommands via register(subparsers) + set_defaults(func=handler).
    from benchctl import commands_manual, commands_report, commands_run, commands_web

    parser = argparse.ArgumentParser(
        prog="benchctl",
        description="Bench instrument control for Rigol supplies and loads.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    identify = subparsers.add_parser(
        "identify",
        help="Query *IDN? on configured instruments (read-only).",
    )
    identify.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the lab YAML configuration (default: {DEFAULT_CONFIG_PATH}).",
    )
    group = identify.add_mutually_exclusive_group()
    group.add_argument("--device", help="Identify a single configured device.")
    group.add_argument(
        "--setup",
        help="Identify every device referenced by the named setup.",
    )
    identify.set_defaults(func=handle_identify)

    commands_manual.register(subparsers)
    commands_report.register(subparsers)
    commands_run.register(subparsers)
    commands_web.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
