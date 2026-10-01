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


FORMATS_HELP = "Report formats to render, comma-separated: html, pdf or html,pdf"
PROFILE_HELP = {
    "dut": "DUT profile YAML: the converter's ratings, limits and declared measurement path",
    "bench": "Bench profile YAML: the source and load instruments and their envelopes",
    "recipe": "Recipe YAML: requested input voltages, output loads and settling policy",
}


def parser() -> argparse.ArgumentParser:
    # `prog` keeps `python -m dcdc_bench --help` from printing `__main__.py`.
    root = argparse.ArgumentParser(prog="dcdc-bench",
                                   description="DC–DC bench: test planning, acquisition and engineering reports. "
                                               "Every command below runs without an instrument unless it says otherwise.")
    sub = root.add_subparsers(dest="command", required=True, title="commands")
    for name in ("validate", "plan"):
        summary = ("Check DUT, bench and recipe profiles and print the feasible-plan summary (writes nothing)"
                   if name == "validate" else
                   "Plan the feasible points for a DUT, bench and recipe and write the plan JSON")
        command = sub.add_parser(name, help=summary, description=summary + ". No instrument is contacted.")
        for role in ("dut", "bench", "recipe"):
            command.add_argument("--"+role, required=True, type=Path, help=PROFILE_HELP[role])
        if name == "plan":
            command.add_argument("--out", required=True, type=Path, help="Plan JSON to write (input of `dcdc-bench run`)")
    command = sub.add_parser("run", help="Execute a plan on the simulated bench and issue its report",
                             description="Execute a plan file on the simulated bench and render its report. "
                                         "M1 supports mock execution only: --mode real and --arm are accepted by the "
                                         "parser and refused at run time (exit code 2). Real tests run from the bench "
                                         "page (`dcdc-bench ui`) or the fixed, owner-armed procedures.")
    command.add_argument("--plan", required=True, type=Path, help="Plan JSON written by `dcdc-bench plan`")
    command.add_argument("--mode", choices=("mock", "real"), default="mock",
                         help="Bench backend; only mock runs here, real is refused (default: mock)")
    command.add_argument("--arm", action="store_true",
                         help="Operator arming for the fixed real procedures; refused by this command")
    command.add_argument("--out", type=Path, default=Path("runs"),
                         help="Folder that receives the new run directory (default: runs)")
    command.add_argument("--scenario", choices=("normal", "setup-limited", "aborted"), default="normal",
                         help="Simulated bench behaviour: normal, setup-limited (source reaches its current limit) "
                              "or aborted (early stop) (default: normal)")
    command.add_argument("--formats", type=_formats, default=("html", "pdf"), help=FORMATS_HELP + " (default: html,pdf)")
    command = sub.add_parser("demo", help="Render the four simulated example reports and their index (no hardware)",
                             description="Run the normal, setup-limited and aborted load sweeps and the best-effort "
                                         "ISO 16750-2 jump start on the simulated bench and render their HTML and PDF "
                                         "reports plus an index page. Rendering is the heavy step: allow several minutes "
                                         "on a Raspberry Pi.")
    command.add_argument("--out", type=Path, default=Path("examples/generated"),
                         help="Output folder; existing demo contents are replaced (default: examples/generated)")
    command.add_argument("--formats", type=_formats, default=("html", "pdf"), help=FORMATS_HELP + " (default: html,pdf)")
    command = sub.add_parser("analyze", help="Recompute the analysis of a stored run folder and print its path",
                             description="Recompute the deterministic analysis of a stored run from its retained "
                                         "evidence and print the analysis path. The run folder is read, not changed.")
    command.add_argument("run_dir", type=Path, help="Run folder, e.g. runs/<procedure>/<timestamp>_<id>")
    command = sub.add_parser("report", help="Render a new report revision from a stored run's analysis",
                             description="Render a new report revision (reports/r000N) from the stored analysis of a "
                                         "run. Earlier revisions are kept.")
    command.add_argument("run_dir", type=Path, help="Run folder, e.g. runs/<procedure>/<timestamp>_<id>")
    command.add_argument("--formats", type=_formats, help=FORMATS_HELP + " (default: html,pdf)")
    command.add_argument("--profile", type=Path, help="Report profile YAML: presentation options such as paper size")
    command.add_argument("--annotations", type=Path,
                         help="Sensor placement annotations JSON saved with this new report revision")
    command = sub.add_parser("ui", help="Open the local converter test bench page (loopback only)",
                             description="Serve the one-page bench UI on a loopback address. Nothing is switched on "
                                         "until an operator approves a real job in the browser; the simulated bench "
                                         "needs no inventory.")
    command.add_argument("--root", type=Path, default=Path("dcdc-bench/workspace"),
                         help="Workspace folder for saved profiles, jobs and reports (default: dcdc-bench/workspace)")
    command.add_argument("--inventory", type=Path, help="Private benchctl instrument inventory for real tests")
    command.add_argument("--report-root", type=Path, help="Existing saved report directory; preserve its /Runs links")
    command.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost", "::1"),
                         help="Loopback address to bind (default: 127.0.0.1)")
    command.add_argument("--port", type=int, default=8082,
                         help="TCP port, 1024–65535 (default: 8082; the development Pi's service uses 8081)")
    command = sub.add_parser("compare", help="Compare stored analyses of two finalized runs; commands no instrument",
                             description="Pair the qualified points of two stored runs by requested condition (never "
                                         "by position) and write a comparison folder: model JSON, Markdown body, CSV "
                                         "exports, figure JSON and a manifest. Both runs are read only.")
    command.add_argument("run_a", type=Path, help="Run folder A (its stored analysis is read; nothing is written there)")
    command.add_argument("run_b", type=Path, help="Run folder B (read only)")
    command.add_argument("--out", required=True, type=Path, help="Comparison folder to create")
    command.add_argument("--analysis-a", help="Analysis revision of run A (default: its single or current revision)")
    command.add_argument("--analysis-b", help="Analysis revision of run B (default: its single or current revision)")
    command.add_argument("--tolerance-vin", type=float, default=.01, help="Requested input-voltage pairing tolerance (V)")
    command.add_argument("--tolerance-iout", type=float, default=.001, help="Requested output-current pairing tolerance (A)")
    command.add_argument("--interpolate", action="store_true", help="Add labeled INTERPOLATED rows; off by default")
    command.add_argument("--covariance", type=Path, help="JSON covariance model between runs A and B")
    command.add_argument("--overwrite", action="store_true", help="Replace an existing comparison folder")
    command = sub.add_parser("doctor", help="Read-only bench diagnosis; never writes to an instrument",
                             description="REAL HARDWARE, read-only: query the configured instruments' identities, "
                                         "output states and readbacks and write a diagnosis JSON with its SCPI "
                                         "transcript. No write or output command is ever sent.")
    command.add_argument("--bench", required=True, type=Path, help=PROFILE_HELP["bench"])
    command.add_argument("--inventory", required=True, type=Path, help="Private benchctl instrument inventory")
    command.add_argument("--out", type=Path, help="Diagnosis JSON path (default: diagnostics/doctor-<utc>.json)")
    command.add_argument("--readback-cadence", action="store_true", help="Outputs-OFF readback cadence probe")
    command.add_argument("--seconds", type=float, default=10., help="Duration of the cadence probe in seconds (default: 10)")
    command.add_argument("--poll-interval", type=float, default=.05,
                         help="Seconds between cadence-probe queries (default: 0.05)")
    command = sub.add_parser("publish", help="Approval-gated redacted static copy of one issued report revision",
                             description="Copy one issued report revision to a static folder with endpoints, paths and "
                                         "serials redacted, as allowed by a reviewer's approval file. Uses no git or "
                                         "network.")
    command.add_argument("run_dir", type=Path, help="Run folder holding the issued report revision")
    command.add_argument("--revision", required=True, help="Report revision to publish, e.g. r0001")
    command.add_argument("--out", required=True, type=Path, help="Folder that receives the redacted static copy")
    command.add_argument("--approval", required=True, type=Path,
                         help="Approval YAML naming the reviewer, the revision and the redaction choices")
    command = sub.add_parser("pdf-check", help="Inspect every page of an issued PDF (PDF-02) and print the JSON result",
                             description="Run the pagination check on a PDF: orphan headings, split or lone table "
                                         "rows, separated captions, clipped text, missing page numbers or identity. "
                                         "Exit code 4 when the document fails or could not be verified.")
    command.add_argument("pdf", type=Path, help="Issued report PDF to inspect")
    command.add_argument("--model", type=Path, help="report_model.json for run/DUT identity checks; defaults to the sibling file")
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
            annotations = json.loads(args.annotations.read_text(encoding="utf-8")) if args.annotations else None
            print(report_run(args.run_dir, formats=args.formats, profile=profile, annotations=annotations))
            return 0
        if args.command == "compare":
            from .comparison import compare_runs
            print(compare_runs([args.run_a, args.run_b], args.out, analysis_ids=[args.analysis_a, args.analysis_b],
                               requested_input_tolerance_V=args.tolerance_vin, requested_load_tolerance_A=args.tolerance_iout,
                               interpolate=args.interpolate, covariance_path=args.covariance, overwrite=args.overwrite))
            return 0
        if args.command == "doctor":
            from .doctor import run_doctor
            path, diagnosis = run_doctor(args.bench, args.inventory, out=args.out, cadence=args.readback_cadence,
                                         seconds=args.seconds, poll_interval=args.poll_interval)
            print(json.dumps({"diagnosis": str(path), "exit_code": diagnosis["exit_code"],
                              "summary": diagnosis["summary"], "cadence": (diagnosis["cadence"] or {}).get("status"),
                              "findings": [f["message"] for f in diagnosis["findings"]]}, indent=2))
            return diagnosis["exit_code"]
        if args.command == "publish":
            from .publish import publish_run
            print(publish_run(args.run_dir, args.revision, args.out, args.approval))
            return 0
        if args.command == "pdf-check":
            from .reporting.pdf_check import check_pdf
            model_path = args.model or (args.pdf.parent / "report_model.json")
            model = json.loads(model_path.read_text(encoding="utf-8")) if model_path.is_file() else None
            result = check_pdf(args.pdf, model)
            print(result.to_json())
            return 0 if result.status in ("pass", "warning") else 4
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
