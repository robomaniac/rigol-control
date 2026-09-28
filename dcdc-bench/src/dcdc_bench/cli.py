"""Small CLI; configuration and analysis paths do not import real drivers."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .domain import Plan, ReportProfile
from .planning import load_profile, verify_plan_hash
from .services import demo, execute, load_plan_inputs, report_run
from .storage import atomic_json


def _formats(text: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(text.split(",")))
    if not values or any(v not in ("html", "pdf") for v in values):
        raise argparse.ArgumentTypeError("Formats must be html, pdf, or html,pdf")
    return values


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="DC–DC bench: test planning, acquisition and engineering reports")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "plan"):
        command = sub.add_parser(name)
        for role in ("dut", "bench", "recipe"):
            command.add_argument("--"+role, required=True, type=Path)
        if name == "plan":
            command.add_argument("--out", required=True, type=Path)
    command = sub.add_parser("run")
    command.add_argument("--plan", required=True, type=Path)
    command.add_argument("--mode", choices=("mock", "real"), default="mock")
    command.add_argument("--arm", action="store_true")
    command.add_argument("--out", type=Path, default=Path("runs"))
    command.add_argument("--scenario", choices=("normal", "setup-limited", "aborted"), default="normal")
    command.add_argument("--formats", type=_formats, default=("html", "pdf"))
    command = sub.add_parser("demo")
    command.add_argument("--out", type=Path, default=Path("examples/generated"))
    command.add_argument("--formats", type=_formats, default=("html", "pdf"))
    command = sub.add_parser("analyze")
    command.add_argument("run_dir", type=Path)
    command = sub.add_parser("report")
    command.add_argument("run_dir", type=Path)
    command.add_argument("--formats", type=_formats)
    command.add_argument("--profile", type=Path)
    command = sub.add_parser("ui", help="Open the local converter test bench")
    command.add_argument("--root", type=Path, default=Path("dcdc-bench/workspace"))
    command.add_argument("--inventory", type=Path, help="Private benchctl instrument inventory for real tests")
    command.add_argument("--report-root", type=Path, help="Existing saved report directory; preserve its /Runs links")
    command.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost", "::1"))
    command.add_argument("--port", type=int, default=8082)
    for name in ("doctor", "compare"):
        sub.add_parser(name, help="Reserved for a later milestone").add_argument("arguments", nargs=argparse.REMAINDER)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "ui":
            from .ui import run_ui
            if not 1024 <= args.port <= 65535:
                raise ValueError("Choose a local port between 1024 and 65535")
            run_ui(args.root.resolve(), args.inventory.resolve() if args.inventory else None,
                   host=args.host, port=args.port,
                   report_root=args.report_root.resolve() if args.report_root else None)
            return 0
        if args.command in ("validate", "plan"):
            plan = load_plan_inputs(args.dut, args.bench, args.recipe)
            counts: dict[str, int] = {}
            for point in plan.points:
                counts[point.status] = counts.get(point.status, 0)+1
            print(json.dumps({"requested": len(plan.points), "status_counts": counts,
                              "plan_hash": plan.plan_hash, "warnings": plan.warnings}, indent=2))
            if args.command == "plan":
                atomic_json(args.out, plan.model_dump())
            return 0
        if args.command == "run":
            if args.mode != "mock" or args.arm:
                raise ValueError("M1 supports mock execution only. Real operation and arming are not implemented or approved.")
            plan = Plan.model_validate_json(args.plan.read_text())
            if not verify_plan_hash(plan):
                raise ValueError("Plan hash does not match its contents; regenerate the plan")
            directory = execute(plan, args.out, scenario=args.scenario, formats=args.formats)
            print(directory)
            status = json.loads((directory/"run.json").read_text())["execution_status"]
            return 0 if status == "completed" else 4
        if args.command == "demo":
            demo(args.out, formats=args.formats)
            print("Open: " + str((args.out/"index.html").resolve()))
            return 0
        if args.command == "analyze":
            from .analysis import analyze_run
            print(analyze_run(args.run_dir))
            return 0
        if args.command == "report":
            profile = load_profile(args.profile, ReportProfile) if args.profile else None
            print(report_run(args.run_dir, formats=args.formats, profile=profile))
            return 0
        raise ValueError(f"{args.command} is deferred; this increment provides the mock CLI and offline reports")
    except ImportError as exc:
        extra = "ui" if args.command == "ui" else "report"
        print(f"dcdc-bench: missing optional dependency ({exc}); install the {extra} extra" +
              (" and renderer tools" if extra == "report" else ""), file=sys.stderr)
        return 3
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"dcdc-bench: {exc}", file=sys.stderr)
        return 3 if type(exc).__name__ == "ReportRenderError" else 2


if __name__ == "__main__":
    raise SystemExit(main())
