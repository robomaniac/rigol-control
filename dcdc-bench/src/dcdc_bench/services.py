"""Application operations shared by the CLI and a future bench UI.

Rendering has no access to instrument sessions. Acquisition outcomes are
finalized before rendering; a renderer error never changes their history.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from .analysis import analyze_run, build_report_model
from .annotations import annotations_file
from .domain import SUPPLY_PROFILE_TEST_TYPES, UVLO_TEST_TYPE, BenchProfile, DutProfile, Plan, ReportProfile, TestRecipe
from .planning import build_plan, load_profile
from .storage import atomic_json, verify_integrity

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_plan_inputs(dut: Path, bench: Path, recipe: Path) -> Plan:
    return build_plan(load_profile(dut, DutProfile), load_profile(bench, BenchProfile),
                      load_profile(recipe, TestRecipe))


def default_plan() -> Plan:
    profiles = PROJECT_ROOT / "profiles"
    if not profiles.is_dir():
        raise ValueError("Profiles not found. Use a source checkout or supply --dut, --bench and --recipe.")
    return load_plan_inputs(profiles / "dut/12t12-4a.yaml", profiles / "bench/mock.yaml",
                            profiles / "recipes/12t12-4a-quick.yaml")


def _validate_analysis_identity(run_dir: Path, plan: Plan, run: dict,
                                analysis: dict, samples: list[dict]) -> None:
    """Bind a selected analysis to the exact acquisition being reported.

    Point names are reused between runs of the same plan, so their presence
    alone cannot establish provenance. This validates the persisted analysis
    consumed by the report; the sibling metrics JSON and CSV are exports, not
    report inputs. Formula versions remain selectable without recalculation.
    """
    run_id = run["run_id"]
    if analysis.get("run_id") != run_id:
        raise ValueError("Analysis run_id does not match the selected run")
    evidence_hash = hashlib.sha256((run_dir / "integrity.json").read_bytes()).hexdigest()
    if analysis.get("evidence_hash") != evidence_hash:
        raise ValueError("Analysis evidence_hash does not match the selected acquisition")
    version = analysis.get("formula_version")
    if not isinstance(version, str) or not version:
        raise ValueError("Analysis formula_version is missing")
    analysis_id = "a-" + hashlib.sha256((evidence_hash + version).encode()).hexdigest()[:12]
    if analysis.get("analysis_id") != analysis_id:
        raise ValueError("Analysis identifier does not match its evidence and formula version")

    requests = {point.point_id: point for point in plan.points}
    points = analysis.get("points", [])
    point_ids = [point.get("point_id") for point in points]
    if len(set(point_ids)) != len(point_ids) or set(point_ids) != set(requests):
        raise ValueError("Analysis must contain each requested point exactly once")
    sample_ids = set()
    samples_by_cycle: dict[tuple[str, str], set[str]] = {}
    for sample in samples:
        request = requests.get(sample.get("point_id"))
        if (request is None or sample.get("run_id") != run_id
                or sample.get("test_id") != request.test_id):
            raise ValueError("Raw sample identity does not match the selected run and plan")
        sample_id = sample["sample_id"]
        if sample_id in sample_ids:
            raise ValueError("Duplicate raw sample identifier")
        sample_ids.add(sample_id)
        key = (sample["point_id"], sample["acquisition_cycle_id"])
        samples_by_cycle.setdefault(key, set()).add(sample_id)
    outcomes = {point["point_id"]: point for point in run.get("points", [])}
    for point in points:
        point_id = point["point_id"]
        request = requests[point_id]
        if point.get("run_id") != run_id or point.get("analysis_id") != analysis_id:
            raise ValueError(f"Analysis point {point_id} belongs to a different run or analysis")
        if any(point.get(key) != getattr(request, key)
               for key in ("test_id", "vin_target_V", "iout_target_A")):
            raise ValueError(f"Analysis point {point_id} conditions do not match the selected plan")
        cycles = outcomes.get(point_id, {}).get("acquisition_cycle_ids", [])
        actual_cycles = point.get("acquisition_cycle_ids", [])
        if (len(set(actual_cycles)) != len(actual_cycles)
                or set(actual_cycles) != set(cycles)):
            raise ValueError(f"Analysis point {point_id} cycles do not match the acquisition")
        expected_samples = {sample_id for cycle in cycles
                            for sample_id in samples_by_cycle.get((point_id, cycle), set())}
        accepted_samples = point.get("accepted_sample_ids", [])
        if (len(set(accepted_samples)) != len(accepted_samples)
                or set(accepted_samples) != expected_samples):
            raise ValueError(f"Analysis point {point_id} sample references do not match the acquisition")


def report_run(run_dir: Path, *, formats: tuple[str, ...] | None = None,
               profile: ReportProfile | None = None, analysis_dir: Path | None = None,
               annotations: dict | None = None) -> Path:
    from .reporting import render_report
    from .reporting.renderer import ReportRenderError
    from .resources import ENV_MIN_AVAILABLE_MIB, ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB, MemoryGate
    profile = profile or ReportProfile()
    formats = formats or tuple(profile.formats)
    if profile.selected_sections != ReportProfile().selected_sections or profile.default_metric != "efficiency_pct":
        raise ValueError("M1 supports the standard engineering sections and efficiency as the initial view; explore other quantities in the HTML")
    run_dir = Path(run_dir)
    # An explicit analysis selection must not bypass acquisition verification.
    verify_integrity(run_dir)
    # Refuse before anything is written: a render that starts short of memory
    # can take the 1 GB host down with it, and no placeholder report may appear.
    gate = MemoryGate()
    gate_ok, gate_reason, gate_snapshot = gate.check()
    if not gate_ok:
        raise ReportRenderError(
            f"Not enough free memory to render safely ({gate_reason}); nothing was rendered. "
            f"Thresholds: {json.dumps(gate.thresholds(), sort_keys=True)}. Snapshot: {json.dumps(gate_snapshot, sort_keys=True)}. "
            f"Override with {ENV_MIN_AVAILABLE_MIB} and {ENV_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB} (both 0 disables the gate).")
    analysis_dir = Path(analysis_dir) if analysis_dir is not None else analyze_run(run_dir)
    analysis = json.loads((analysis_dir / "analysis.json").read_text())
    plan = Plan.model_validate_json((run_dir / "plan.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    samples = [json.loads(line) for line in (run_dir / "raw/samples.jsonl").read_text().splitlines() if line]
    _validate_analysis_identity(run_dir, plan, run, analysis, samples)
    # Sensor markers are bound to a stored original's hash before any revision directory exists.
    annotation_content = annotations_file(run_dir, annotations)
    reports = run_dir / "reports"
    reports.mkdir(exist_ok=True)
    index = 1
    while True:
        revision = f"r{index:04d}"
        directory = reports / revision
        try:
            directory.mkdir()
            break
        except FileExistsError:
            index += 1
    model = build_report_model(plan, run, analysis, samples, revision)
    model.title = profile.title + " · " + plan.dut.identity.model
    atomic_json(directory / "report_profile.json", profile.model_dump())
    atomic_json(directory / "report_model.json", model.model_dump())
    atomic_json(directory / "annotations.json", annotation_content)
    # The renderer copies this verdict into build_manifest.json.
    atomic_json(directory / "memory_gate.json", {"ok": gate_ok, "reason": gate_reason,
                                                 "thresholds": gate.thresholds(), "snapshot": gate_snapshot})
    render_report(model.model_dump(), directory, formats=formats, paper=profile.paper)
    return directory


def acquire_mock(plan: Plan, out: Path, *, scenario: str = "normal", operator_observations: list[str] | None = None,
                 attachment_descriptors: list[dict] | None = None) -> Path:
    """Run the mock procedure that matches the plan's test type; never a real instrument.

    An all-``uvlo_input_ramp`` plan runs the phase-scoped ramp (``uvlo.run_uvlo_mock``);
    a plan of load sweeps runs the generic loop (``runner.run_mock``). A recipe that
    mixes the two is refused at planning time (every point ``unsupported``) and
    again here. Real UVLO execution has no context and stays refused upstream.
    """
    types = {test.type for test in plan.recipe.tests}
    if types == {UVLO_TEST_TYPE}:
        if scenario != "normal":
            raise ValueError("The UVLO input ramp has no failure-injection scenarios; use scenario 'normal'")
        from .uvlo import run_uvlo_mock
        return run_uvlo_mock(plan, out, operator_observations=operator_observations,
                             attachment_descriptors=attachment_descriptors)
    if UVLO_TEST_TYPE in types:
        raise ValueError("A recipe that mixes uvlo_input_ramp with other test types cannot be executed; "
                         "plan the ramp as its own recipe")
    if len(types) == 1 and types <= set(SUPPLY_PROFILE_TEST_TYPES):
        # ISO 16750-2 slow ramp / reset staircase: the phase-scoped supply-profile procedure (synthetic plant only).
        if scenario != "normal":
            raise ValueError("The supply-profile procedures have no failure-injection scenarios; use scenario 'normal'")
        from .supply_profiles import run_supply_profile_mock
        return run_supply_profile_mock(plan, out, operator_observations=operator_observations,
                                       attachment_descriptors=attachment_descriptors)
    if types & set(SUPPLY_PROFILE_TEST_TYPES):
        raise ValueError("A recipe that mixes a supply profile (slow_supply_ramp, reset_staircase) with other test types "
                         "cannot be executed; plan each profile as its own recipe")
    from .runner import run_mock
    return run_mock(plan, out, scenario=scenario, operator_observations=operator_observations,
                    attachment_descriptors=attachment_descriptors)


def execute(plan: Plan, out: Path, *, scenario: str = "normal", formats: tuple[str, ...] = ("html", "pdf")) -> Path:
    run_dir = acquire_mock(plan, out, scenario=scenario)
    # This stage may fail. Evidence and execution status remain intact.
    report_run(run_dir, formats=formats)
    return run_dir


def demo(out: Path, *, formats: tuple[str, ...] = ("html", "pdf"),
         progress=print) -> list[Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    plan = default_plan()
    results = []
    for scenario in ("normal", "setup-limited", "aborted"):
        progress(f"Mock {scenario}: acquiring and rendering…", flush=True)
        results.append(execute(plan, out / scenario, scenario=scenario, formats=formats))
        progress(f"Saved {results[-1]}", flush=True)
    links = []
    for run in results:
        report = sorted((run / "reports").glob("r*"))[-1]
        relative = report.relative_to(out).as_posix()
        label = {"normal": "Normal test", "setup-limited": "Supply reaches its current limit",
                 "aborted": "Test stopped early"}[run.parent.name]
        links.append(f'<li><h2>{html.escape(label)}</h2><a href="{relative}/report.html">Interactive report</a>'
                     + (f' · <a href="{relative}/report.pdf">Canonical PDF</a>' if "pdf" in formats else "") + "</li>")
    (out / "index.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width">'
        '<title>DC–DC mock demonstrations</title><style>body{font:18px system-ui;max-width:850px;margin:4rem auto;padding:1rem;'
        'color:#172e42;background:#f5f8fb}a{color:#075aa0}li{margin:2rem 0}h1{line-height:1.2}</style>'
        '<h1>DC–DC converter characterization</h1><p><strong>SYNTHETIC — software demonstration only.</strong></p>'
        '<p>Each run requests 12, 24 and 30 V input, with output loads from zero to 1 A. '
        'Explore the simulated voltage, efficiency and power loss, inspect individual readings, and export the selected data.</p>'
        '<p>The limited example injects source current limiting; the aborted example stops early and preserves its partial evidence.</p>'
        '<ul>' + "".join(links) + '</ul><p>No real equipment was connected. These are not measurements of your converter.</p></html>',
        encoding="utf-8")
    return results
