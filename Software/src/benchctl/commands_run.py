"""Validate or execute a YAML recipe against a configured setup."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from benchctl import runner
from benchctl.paths import DEFAULT_CONFIG_PATH, DEFAULT_SAFETY_PROFILES_PATH, DEFAULT_RESULTS_DIR
from benchctl.config import ConfigError, load_config
from benchctl.recipes import LoadConfigureCC, Measure, RecipeError, Wait, load_recipe



def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "run",
        help="Run a YAML recipe against a configured setup.",
        description=(
            "Validate a recipe (schema, parameters, and every setpoint "
            "against safety profiles) and execute it. After identity checks "
            "succeed, cleanup is attempted when execution exits."
        ),
    )
    parser.add_argument(
        "recipe",
        metavar="RECIPE_PATH",
        type=Path,
        help="Path to the recipe YAML file.",
    )
    parser.add_argument(
        "--setup",
        required=True,
        help="Name of the setup (from the lab config) to run against.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the lab YAML configuration (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--safety-profiles",
        dest="safety_profiles",
        type=Path,
        default=DEFAULT_SAFETY_PROFILES_PATH,
        help=(
            "Path to the safety profiles YAML "
            f"(default: {DEFAULT_SAFETY_PROFILES_PATH})."
        ),
    )
    parser.add_argument(
        "--results-dir",
        dest="results_dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help=f"Base directory for run results (default: {DEFAULT_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Expand and validate the complete plan without contacting hardware or creating results.",
    )
    parser.set_defaults(func=handler)
    return parser


def handler(args: argparse.Namespace) -> int:
    try:
        recipe = load_recipe(args.recipe)
    except RecipeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        # Imported lazily; another module owns benchctl.safety.
        safety = importlib.import_module("benchctl.safety")
        profiles = safety.load_safety_profiles(args.safety_profiles)
    except Exception as exc:
        print(
            f"error: cannot load safety profiles from {args.safety_profiles}: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        if getattr(args, "dry_run", False):
            devices = runner.resolve_devices(recipe, config, args.setup, profiles)
            runner.validate_setpoints(recipe, devices)
            measurements = sum(isinstance(action, Measure) for action in recipe.steps)
            waits = sum(action.seconds for action in recipe.steps if isinstance(action, Wait))
            currents = [action.current_a for action in recipe.steps if isinstance(action, LoadConfigureCC)]
            print(f"plan valid: {recipe.name} on {args.setup}")
            print(f"  {len(recipe.steps)} actions, {measurements} measurements, {len(recipe.finally_steps)} cleanup actions")
            print(f"  {waits:g} seconds of planned settling, plus instrument I/O")
            if currents:
                print(f"  load current range: {min(currents):g}–{max(currents):g} A")
            print("  hardware was not contacted; wiring and hardware protections still need checking")
            return 0
        result = runner.run_recipe(
            recipe,
            config,
            args.setup,
            profiles,
            results_base=args.results_dir,
        )
    except runner.RunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "interrupted: inspect the front panels to confirm outputs are off; "
            "see the results directory for any partial run log",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(f"error: recipe {recipe.name!r} failed: {exc}", file=sys.stderr)
        return 1

    print(f"run complete: results in {result.run_dir}")
    return 0
