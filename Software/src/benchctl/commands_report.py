"""The ``report`` subcommand: render saved measurements without hardware."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchctl.paths import DEFAULT_RESULTS_DIR
from benchctl.report import ReportError, find_latest_run, generate_report


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "report",
        help="Create a standalone HTML report from a saved recipe run.",
    )
    parser.add_argument("run_dir", nargs="?", type=Path, metavar="RUN_DIR", help="A saved run directory.")
    parser.add_argument(
        "--latest", metavar="RECIPE_NAME",
        help="Use the newest saved run whose recipe name matches exactly.",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=DEFAULT_RESULTS_DIR, metavar="PATH",
        help=f"Base directory used with --latest (default: {DEFAULT_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--output", type=Path, metavar="PATH",
        help="Output HTML path (default: RUN_DIR/report.html).",
    )
    parser.set_defaults(func=handler)
    return parser


def handler(args: argparse.Namespace) -> int:
    if (args.run_dir is None) == (args.latest is None):
        print("error: provide RUN_DIR or --latest RECIPE_NAME", file=sys.stderr)
        return 2
    try:
        run_dir = find_latest_run(args.latest, args.results_dir) if args.latest else args.run_dir
        target = generate_report(run_dir, args.output)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"report written: {target}")
    return 0
