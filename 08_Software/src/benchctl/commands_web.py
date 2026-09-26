"""`benchctl web` subcommand: serve the read-only status dashboard.

Exposes ``register(subparsers)`` so the main CLI can wire the command in.
Standard library only (argparse + http.server via benchctl.web).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchctl.paths import DEFAULT_CONFIG_PATH
from benchctl.config import ConfigError, DeviceConfig, load_config
from benchctl.transport import VisaTransport
from benchctl.web.server import create_server



def make_transport(device_name: str, device: DeviceConfig) -> VisaTransport:
    """Default transport factory; tests replace this with fakes."""
    return VisaTransport(device_name, device.resource)


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "web",
        help="Serve a read-only web status dashboard (GET-only HTTP).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the lab YAML configuration (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to bind (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="TCP port to listen on (default: 8080).",
    )
    parser.set_defaults(func=handler)
    return parser


def handler(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server = create_server(config, make_transport, host=args.host, port=args.port)
    host, port = server.server_address[:2]
    print(f"Serving read-only dashboard on http://{host}:{port}/ (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
