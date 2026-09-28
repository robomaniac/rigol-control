"""Paired comparison of stored analyses from finalized runs (M4, CMP-01/CMP-02/UNC-03).

A comparison reads run folders and their selected analysis revisions. It
commands no instrument and writes nothing into a source run folder.

Pairing uses qualified conditions and identifiers only: the same measurement
boundary, the same test type and test id, requested input voltage and requested
output current equal within the declared tolerances, and ``valid``
qualification on both sides. Points are never joined by array position.
Repeated visits to one condition are separate observations; they are listed as
unpaired rather than paired by order.

``delta_eta_pp = eta_B_pct - eta_A_pct``: run A is the reference (first run
folder), run B the other. Loss and output-voltage differences use the same
B minus A convention. Resolvability is evaluated only when both analyses carry
an evaluated uncertainty budget for the paired quantity; then
``u_delta^2 = u_A^2 + u_B^2 - 2*cov(A,B)`` with independence recorded as an
explicit assumption whenever no covariance model is supplied. Otherwise the
differences are descriptive and resolvability is ``not evaluated``.

Evaluated-budget contract consumed here (``analysis.json`` -> ``uncertainty``):
``{"status": "evaluated", "standard": {point_id: {"efficiency_pct": u_pp,
"loss_W": u_W, "Vout_V": u_V}}, "coverage_factor": k}``. Standard
uncertainties are in the quantity's unit (percentage points for efficiency).
Anything else is treated as not evaluated; nothing is invented.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .analysis import (FORMULA_VERSION, EvidenceRef, FigureSeries, FigureSpec, MetricResult,
                       ReportModel, SummaryEvidence, TableSpec, _evidence_label, _finite_number,
                       difference_standard_uncertainty)
from .domain import Contract, Plan
from .services import _validate_analysis_identity
from .storage import verify_integrity

COMPARISON_VERSION = "paired-comparison-1.0"
DIFFERENCE_MODEL = "u_delta^2 = u_A^2 + u_B^2 - 2*cov(A,B)"
RUN_LABELS = tuple("ABCDEFGH")
PAIRED_QUANTITIES = (("efficiency_pct", "delta_eta_pp", "percentage points"),
                     ("loss_W", "delta_loss_W", "W"),
                     ("Vout_V", "delta_Vout_V", "V"))


class PairingPolicy(Contract):
    """Declared pairing rules; every rule is recorded with the comparison."""
    requested_input_tolerance_V: float = Field(default=.01, ge=0)
    requested_load_tolerance_A: float = Field(default=.001, ge=0)
    require_same_boundary: Literal[True] = True
    require_same_test_type: Literal[True] = True
    require_same_test_id: bool = True
    require_valid_qualification: Literal[True] = True
    interpolation_enabled: bool = False
    basis: str = "requested conditions and identifiers only; never array position"


class ComparisonRun(Contract):
    label: str
    run_id: str
    analysis_id: str
    run_dir: str
    evidence_label: str
    data_source: str
    boundary: str
    dut_model: str
    sample_id: str | None
    bench_id: str
    formula_version: str
    execution_status: str
    created_utc: str | None
    duration_s: float | None
    instrument_identities: dict[str, Any]
    test_types: dict[str, str]
    point_count: int
    valid_count: int
    qualification_counts: dict[str, int]
    uncertainty_status: str
    temperature_measured: bool | None


class Disclosure(Contract):
    field: str
    values: dict[str, Any]


class ComparisonReportModel(ReportModel):
    """The shared report model, extended additively for paired comparisons.

    ``points`` holds every compared point with run-prefixed identifiers
    (``A:p0001``) plus the derived pair rows (``pair-B-0001``) and, only when
    enabled, labeled interpolated rows. ``run_id``/``analysis_id`` carry the
    comparison identifier; the source identities are in ``runs``.
    """
    kind: Literal["comparison"] = "comparison"
    comparison_id: str
    comparison_version: str
    runs: list[ComparisonRun]
    pairing: PairingPolicy
    pairs: list[dict[str, Any]]
    unpaired: list[dict[str, Any]]
    interpolated: list[dict[str, Any]]
    availability: list[dict[str, Any]]
    difference_uncertainty: dict[str, Any]
    disclosures: list[Disclosure]
    identical: dict[str, bool]


class LoadedRun:
    """One verified run folder with its selected analysis revision (read-only)."""

    def __init__(self, label: str, run_dir: Path, plan: Plan, run: dict, analysis: dict, analysis_dir: Path):
        self.label, self.run_dir, self.plan, self.run = label, run_dir, plan, run
        self.analysis, self.analysis_dir = analysis, analysis_dir
        self.evidence_label = analysis["evidence_label"]
        self.boundary = analysis["boundary"]
        self.test_types = {test.id: test.type for test in plan.recipe.tests}

    @property
    def run_id(self) -> str:
        return self.run["run_id"]

    @property
    def analysis_id(self) -> str:
        return self.analysis["analysis_id"]


def select_analysis(run_dir: Path, analysis_id: str | None) -> Path:
    """Choose a stored analysis revision without creating one."""
    root = run_dir / "analysis"
    if analysis_id is not None:
        if not analysis_id or "/" in analysis_id or "\\" in analysis_id or analysis_id in (".", ".."):
            raise ValueError(f"Invalid analysis identifier {analysis_id!r}")
        directory = root / analysis_id
        if not (directory / "analysis.json").is_file():
            raise ValueError(f"Analysis revision {analysis_id} not found in {run_dir}")
        return directory
    candidates = sorted(path.parent for path in root.glob("*/analysis.json")) if root.is_dir() else []
    if not candidates:
        raise ValueError(f"{run_dir} has no analysis revision; run `dcdc-bench analyze` first. "
                         "A comparison never writes into a run folder.")
    if len(candidates) == 1:
        return candidates[0]
    evidence_hash = hashlib.sha256((run_dir / "integrity.json").read_bytes()).hexdigest()
    current = "a-" + hashlib.sha256((evidence_hash + FORMULA_VERSION).encode()).hexdigest()[:12]
    for candidate in candidates:
        if candidate.name == current:
            return candidate
    names = ", ".join(path.name for path in candidates)
    raise ValueError(f"{run_dir} has several analysis revisions ({names}); select one explicitly")


def load_run(run_dir: Path, analysis_id: str | None = None, label: str = "A") -> LoadedRun:
    """Verify acquisition integrity and analysis identity exactly as the report path does."""
    run_dir = Path(run_dir)
    if not (run_dir / "integrity.json").is_file():
        raise ValueError(f"{run_dir} is not a finalized run folder (integrity.json missing)")
    verify_integrity(run_dir)
    plan = Plan.model_validate_json((run_dir / "plan.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    samples = [json.loads(line) for line in (run_dir / "raw/samples.jsonl").read_text().splitlines() if line]
    analysis_dir = select_analysis(run_dir, analysis_id)
    analysis = json.loads((analysis_dir / "analysis.json").read_text())
    _validate_analysis_identity(run_dir, plan, run, analysis, samples)
    evidence_label = _evidence_label(plan, run)
    if analysis.get("evidence_label") != evidence_label:
        raise ValueError("Analysis evidence label does not match its acquisition")
    boundary = run.get("measurement_boundary", plan.bench.measurement_boundary)
    if analysis.get("boundary") != boundary:
        raise ValueError("Analysis measurement boundary does not match its acquisition")
    return LoadedRun(label, run_dir.resolve(), plan, run, analysis, analysis_dir)


def _prefixed_points(loaded: LoadedRun) -> list[dict[str, Any]]:
    points = []
    for point in loaded.analysis["points"]:
        row = copy.deepcopy(point)
        row.update(source_point_id=point["point_id"], point_id=f"{loaded.label}:{point['point_id']}",
                   kind="point", run_label=loaded.label, source_run_id=loaded.run_id,
                   source_analysis_id=loaded.analysis_id, evidence_label=loaded.evidence_label,
                   test_type=loaded.test_types.get(point["test_id"], "unknown"), pair_id=None)
        points.append(row)
    return points


def _within(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance + 1e-12


def _condition_text(point: dict[str, Any]) -> str:
    return f"{point['vin_target_V']:g} V, {point['iout_target_A']:g} A ({point['test_id']})"


def pair_points(reference: list[dict[str, Any]], other: list[dict[str, Any]], policy: PairingPolicy,
                *, same_boundary: bool, label_a: str, label_b: str) -> tuple[list[dict], list[dict]]:
    """Pair valid points of two runs by declared conditions; list every other point separately."""
    unpaired: list[dict] = []

    def unpaired_row(point: dict, compared_with: str, reason: str, eligible: bool) -> dict:
        return {"point_id": point["point_id"], "run_label": point["run_label"], "compared_with": compared_with,
                "source_point_id": point["source_point_id"], "test_id": point["test_id"],
                "test_type": point.get("test_type"), "vin_target_V": point["vin_target_V"],
                "iout_target_A": point["iout_target_A"], "qualification": point["qualification"],
                "eligible": eligible, "reason": reason}

    valid_a = [p for p in reference if p["qualification"] == "valid"]
    valid_b = [p for p in other if p["qualification"] == "valid"]
    for point in reference:
        if point["qualification"] != "valid":
            unpaired.append(unpaired_row(point, label_b, f"qualification {point['qualification']}; only valid points are paired", False))
    for point in other:
        if point["qualification"] != "valid":
            unpaired.append(unpaired_row(point, label_a, f"qualification {point['qualification']}; only valid points are paired", False))
    if not same_boundary:
        for point in valid_a:
            unpaired.append(unpaired_row(point, label_b, "measurement boundary differs between the runs; no pairing", True))
        for point in valid_b:
            unpaired.append(unpaired_row(point, label_a, "measurement boundary differs between the runs; no pairing", True))
        return [], unpaired

    def key(point: dict) -> tuple:
        return (point["test_type"], point["test_id"] if policy.require_same_test_id else None,
                point["vin_target_V"], point["iout_target_A"])

    groups_a: dict[tuple, list[dict]] = defaultdict(list)
    for point in valid_a:
        groups_a[key(point)].append(point)
    candidates: dict[tuple, list[dict]] = {}
    claims: Counter = Counter()
    for group_key, rows in groups_a.items():
        matches = [q for q in valid_b
                   if q["test_type"] == group_key[0]
                   and (not policy.require_same_test_id or q["test_id"] == group_key[1])
                   and _within(q["vin_target_V"], group_key[2], policy.requested_input_tolerance_V)
                   and _within(q["iout_target_A"], group_key[3], policy.requested_load_tolerance_A)]
        candidates[group_key] = matches
        for match in matches:
            claims[match["point_id"]] += 1
    pairs: list[dict] = []
    paired_b: set[str] = set()
    ids_b = {q["test_id"] for q in valid_b}
    for group_key, rows in groups_a.items():
        matches = candidates[group_key]
        if len(rows) > 1:
            reason = (f"repeated condition in run {label_a}: {len(rows)} valid observations at "
                      f"{_condition_text(rows[0])}; not paired by order")
            for point in rows:
                unpaired.append(unpaired_row(point, label_b, reason, True))
            continue
        point = rows[0]
        if not matches:
            if point["test_id"] not in ids_b and policy.require_same_test_id:
                reason = f"no valid run {label_b} point with test id {point['test_id']!r}"
            else:
                reason = f"no valid run {label_b} point at {_condition_text(point)} within tolerance"
            unpaired.append(unpaired_row(point, label_b, reason, True))
            continue
        if len(matches) > 1:
            unpaired.append(unpaired_row(point, label_b,
                f"ambiguous: {len(matches)} run {label_b} points within tolerance of {_condition_text(point)}", True))
            continue
        match = matches[0]
        if claims[match["point_id"]] > 1:
            unpaired.append(unpaired_row(point, label_b,
                f"ambiguous: run {label_b} point {match['source_point_id']} is within tolerance of several run {label_a} conditions", True))
            continue
        paired_b.add(match["point_id"])
        pairs.append(_pair_row(point, match, label_a, label_b, len(pairs) + 1))
    matched_b_groups: dict[tuple, list[dict]] = defaultdict(list)
    for point in valid_b:
        matched_b_groups[key(point)].append(point)
    ids_a = {p["test_id"] for p in valid_a}
    for group_key, rows in matched_b_groups.items():
        for point in rows:
            if point["point_id"] in paired_b:
                continue
            if len(rows) > 1:
                reason = (f"repeated condition in run {label_b}: {len(rows)} valid observations at "
                          f"{_condition_text(point)}; not paired by order")
            elif claims[point["point_id"]] > 1:
                reason = f"ambiguous: within tolerance of several run {label_a} conditions"
            elif claims[point["point_id"]] == 1:
                reason = f"its run {label_a} counterpart at {_condition_text(point)} is repeated or ambiguous"
            elif point["test_id"] not in ids_a and policy.require_same_test_id:
                reason = f"no valid run {label_a} point with test id {point['test_id']!r}"
            else:
                reason = f"no valid run {label_a} point at {_condition_text(point)} within tolerance"
            unpaired.append(unpaired_row(point, label_a, reason, True))
    return pairs, unpaired


def _delta(b: Any, a: Any) -> float | None:
    fb, fa = _finite_number(b), _finite_number(a)
    return None if fb is None or fa is None else fb - fa


def _pair_row(a: dict, b: dict, label_a: str, label_b: str, index: int) -> dict[str, Any]:
    pair_id = f"pair-{label_b}-{index:04d}"
    return {"point_id": pair_id, "pair_id": pair_id, "kind": "pair", "qualification": "paired",
            "label_a": label_a, "label_b": label_b, "run_label": label_b,
            "test_id": a["test_id"], "test_type": a["test_type"],
            "vin_target_V": a["vin_target_V"], "iout_target_A": a["iout_target_A"],
            "vin_target_b_V": b["vin_target_V"], "iout_target_b_A": b["iout_target_A"],
            "point_id_a": a["point_id"], "point_id_b": b["point_id"],
            "source_point_id_a": a["source_point_id"], "source_point_id_b": b["source_point_id"],
            "Vin_a_V": a.get("Vin_V"), "Vin_b_V": b.get("Vin_V"), "Iout_a_A": a.get("Iout_A"), "Iout_b_A": b.get("Iout_A"),
            "Vout_a_V": a.get("Vout_V"), "Vout_b_V": b.get("Vout_V"), "Pin_a_W": a.get("Pin_W"), "Pin_b_W": b.get("Pin_W"),
            "Pout_a_W": a.get("Pout_W"), "Pout_b_W": b.get("Pout_W"), "loss_a_W": a.get("loss_W"), "loss_b_W": b.get("loss_W"),
            "eta_a_pct": a.get("efficiency_pct"), "eta_b_pct": b.get("efficiency_pct"),
            "delta_eta_pp": _delta(b.get("efficiency_pct"), a.get("efficiency_pct")),
            "delta_loss_W": _delta(b.get("loss_W"), a.get("loss_W")),
            "delta_Vout_V": _delta(b.get("Vout_V"), a.get("Vout_V")),
            "delta_Vin_measured_V": _delta(b.get("Vin_V"), a.get("Vin_V")),
            "delta_Iout_measured_A": _delta(b.get("Iout_A"), a.get("Iout_A")),
            "evidence_label_a": a["evidence_label"], "evidence_label_b": b["evidence_label"],
            "uncertainty": {}}


def _standard_uncertainty(analysis: dict, point_id: str, quantity: str) -> float | None:
    budget = analysis.get("uncertainty") or {}
    if budget.get("status") != "evaluated":
        return None
    table = budget.get("standard")
    if not isinstance(table, dict):
        return None
    value = _finite_number((table.get(point_id) or {}).get(quantity)) if isinstance(table.get(point_id), dict) else None
    return value if value is not None and value >= 0 else None


def _coverage_factor(analysis: dict) -> float | None:
    budget = analysis.get("uncertainty") or {}
    value = _finite_number(budget.get("coverage_factor"))
    return value if value is not None and value > 0 else None


def evaluate_pair_uncertainty(pairs: list[dict], reference: LoadedRun, other: LoadedRun,
                              covariance: dict[str, Any] | None) -> dict[str, Any]:
    """Fill each pair's per-quantity difference uncertainty; summarize the basis.

    Independence is recorded as an assumption only when a difference is
    actually evaluated without a supplied covariance. A missing budget yields
    ``not evaluated`` and no bands.
    """
    supplied = dict((covariance or {}).get("quantities") or {})
    for name, value in supplied.items():
        if _finite_number(value) is None:
            raise ValueError(f"Covariance for {name} must be a finite number")
    k_a, k_b = _coverage_factor(reference.analysis), _coverage_factor(other.analysis)
    k = k_a if k_a is not None and k_a == k_b else None
    evaluated = missing = 0
    for pair in pairs:
        result = {}
        for quantity, delta_key, unit in PAIRED_QUANTITIES:
            if pair[delta_key] is None:
                result[quantity] = {"status": "not applicable", "unit": unit,
                                    "reason": "the quantity is not evaluated at one or both points"}
                continue
            u_a = _standard_uncertainty(reference.analysis, pair["source_point_id_a"], quantity)
            u_b = _standard_uncertainty(other.analysis, pair["source_point_id_b"], quantity)
            if u_a is None or u_b is None:
                missing += 1
                result[quantity] = {"status": "not evaluated", "unit": unit,
                                    "reason": "no evaluated standard uncertainty for this quantity in both analyses"}
                continue
            cov = float(supplied.get(quantity, 0.))
            u_delta = difference_standard_uncertainty(u_a, u_b, cov)
            evaluated += 1
            result[quantity] = {"status": "evaluated", "unit": unit, "model": DIFFERENCE_MODEL,
                                "u_a": u_a, "u_b": u_b, "covariance": cov,
                                "covariance_basis": "supplied" if quantity in supplied else "independence assumed (cov = 0)",
                                "u_delta": u_delta, "k": k, "expanded": k * u_delta if k is not None else None,
                                "abs_delta_over_u_delta": abs(pair[delta_key]) / u_delta if u_delta > 0 else None}
        pair["uncertainty"] = result
    status = "not evaluated" if evaluated == 0 else "evaluated" if missing == 0 else "partially evaluated"
    summary: dict[str, Any] = {"status": status, "model": DIFFERENCE_MODEL, "evaluated_terms": evaluated,
                               "missing_terms": missing, "coverage_factor": k,
                               "budgets": {reference.label: (reference.analysis.get("uncertainty") or {}).get("status", "unknown"),
                                           other.label: (other.analysis.get("uncertainty") or {}).get("status", "unknown")}}
    if evaluated == 0:
        summary["assumption"] = {"independence_assumed": False, "applicable": False,
                                 "statement": "No difference uncertainty was evaluated, so no covariance assumption applies."}
        summary["reason"] = ("Neither analysis, or only one, carries an evaluated uncertainty budget for the paired quantities. "
                             "Differences are descriptive; resolvability is not evaluated and no bands are drawn.")
    elif supplied:
        summary["assumption"] = {"independence_assumed": False, "applicable": True, "supplied_covariance": supplied,
                                 "note": (covariance or {}).get("note"),
                                 "statement": "Covariance between runs was supplied for the listed quantities; "
                                              "quantities without a supplied value use cov = 0 (independence assumed)."}
    else:
        summary["assumption"] = {"independence_assumed": True, "applicable": True,
                                 "statement": ("Independence between the two runs is assumed (cov = 0) for every paired quantity. "
                                               "This is an assumption, not a result: shared instruments, ranges or corrections "
                                               "introduce covariance that this comparison did not evaluate.")}
    return summary


def interpolate_unpaired(reference: list[dict], other: list[dict], unpaired: list[dict], policy: PairingPolicy,
                         label_a: str, label_b: str) -> list[dict]:
    """Optional, labeled linear interpolation of the other run's curve at an unpaired measured load.

    Only strictly bracketed loads on the same test id and input condition are
    interpolated; nothing is extrapolated. Rows are excluded from the paired
    results and are marked INTERPOLATED everywhere.
    """
    rows: list[dict] = []
    by_label = {label_a: reference, label_b: other}
    unpaired_ids = {row["point_id"] for row in unpaired if row["eligible"]
                    and "repeated" not in row["reason"] and "ambiguous" not in row["reason"]}
    for measured_label, curve_label in ((label_a, label_b), (label_b, label_a)):
        measured_points = [p for p in by_label[measured_label] if p["point_id"] in unpaired_ids]
        curve_points = [p for p in by_label[curve_label] if p["qualification"] == "valid"]
        for point in sorted(measured_points, key=lambda p: (p["test_id"], p["vin_target_V"], p["iout_target_A"])):
            same = [q for q in curve_points if q["test_type"] == point["test_type"]
                    and (not policy.require_same_test_id or q["test_id"] == point["test_id"])
                    and _within(q["vin_target_V"], point["vin_target_V"], policy.requested_input_tolerance_V)]
            loads: dict[float, list[dict]] = defaultdict(list)
            for q in same:
                loads[q["iout_target_A"]].append(q)
            singles = sorted((load, group[0]) for load, group in loads.items() if len(group) == 1)
            below = [(load, q) for load, q in singles if load < point["iout_target_A"] - policy.requested_load_tolerance_A]
            above = [(load, q) for load, q in singles if load > point["iout_target_A"] + policy.requested_load_tolerance_A]
            if not below or not above:
                continue
            (x0, lo), (x1, hi) = below[-1], above[0]
            x = point["iout_target_A"]
            fraction = (x - x0) / (x1 - x0)

            def between(key: str) -> float | None:
                a, b = _finite_number(lo.get(key)), _finite_number(hi.get(key))
                return None if a is None or b is None else a + fraction * (b - a)

            interpolated = {"efficiency_pct": between("efficiency_pct"), "loss_W": between("loss_W"), "Vout_V": between("Vout_V")}
            measured = {"efficiency_pct": point.get("efficiency_pct"), "loss_W": point.get("loss_W"), "Vout_V": point.get("Vout_V")}
            a_values, b_values = (interpolated, measured) if curve_label == label_a else (measured, interpolated)
            rows.append({"point_id": f"interp-{measured_label}-{len(rows) + 1:04d}", "kind": "interpolated",
                         "qualification": "interpolated", "run_label": measured_label, "interpolated_run": curve_label,
                         "label": f"INTERPOLATED: run {curve_label} curve evaluated linearly at a run {measured_label} load; not a measurement",
                         "test_id": point["test_id"], "test_type": point["test_type"],
                         "vin_target_V": point["vin_target_V"], "iout_target_A": x,
                         "measured_point_id": point["point_id"], "bracket_point_ids": [lo["point_id"], hi["point_id"]],
                         "bracket_loads_A": [x0, x1], "eta_measured_pct": measured["efficiency_pct"],
                         "eta_interpolated_pct": interpolated["efficiency_pct"],
                         "delta_eta_pp": _delta(b_values["efficiency_pct"], a_values["efficiency_pct"]),
                         "delta_loss_W": _delta(b_values["loss_W"], a_values["loss_W"]),
                         "delta_Vout_V": _delta(b_values["Vout_V"], a_values["Vout_V"]),
                         "uncertainty": {"status": "not evaluated", "reason": "interpolated values carry no evaluated budget"}})
    return rows


def _differences(a: Any, b: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for name in sorted(set(a) | set(b)):
            out.extend(_differences(a.get(name, "<absent>"), b.get(name, "<absent>"), f"{path}.{name}" if path else name))
        return out
    return [] if a == b else [(path or "<root>", a, b)]


def _temperature_measured(plan: Plan) -> bool | None:
    bindings = plan.bench.measurements
    if not bindings:
        return None
    return any(str(b.unit).strip().casefold().replace("°", "").removeprefix("deg").strip() in ("c", "k")
               or "temp" in str(b.quantity).casefold() for b in bindings.values())


def _run_summary(loaded: LoadedRun) -> ComparisonRun:
    points = loaded.analysis["points"]
    return ComparisonRun(label=loaded.label, run_id=loaded.run_id, analysis_id=loaded.analysis_id,
        run_dir=str(loaded.run_dir), evidence_label=loaded.evidence_label,
        data_source=str(loaded.run.get("data_source", "unknown")), boundary=loaded.boundary,
        dut_model=loaded.plan.dut.identity.model, sample_id=loaded.plan.dut.identity.sample_id,
        bench_id=loaded.plan.bench.bench_id, formula_version=str(loaded.analysis["formula_version"]),
        execution_status=str(loaded.run.get("execution_status", "unknown")),
        created_utc=loaded.run.get("created_utc") if isinstance(loaded.run.get("created_utc"), str) else None,
        duration_s=_finite_number(loaded.run.get("duration_s")),
        instrument_identities=copy.deepcopy(loaded.run.get("instrument_identities", {})),
        test_types=dict(loaded.test_types), point_count=len(points),
        valid_count=sum(1 for p in points if p["qualification"] == "valid"),
        qualification_counts=dict(Counter(str(p["qualification"]) for p in points)),
        uncertainty_status=str((loaded.analysis.get("uncertainty") or {}).get("status", "unknown")),
        temperature_measured=_temperature_measured(loaded.plan))


def _load_text(value: float) -> str:
    return f"{value:g} A"


def _availability(reference: LoadedRun, other: LoadedRun, points_a: list[dict], points_b: list[dict],
                  unpaired: list[dict]) -> list[dict[str, Any]]:
    """Which requested conditions each run covers with valid points; unpaired loads per condition."""
    rows: list[dict[str, Any]] = []
    valid = {reference.label: [p for p in points_a if p["qualification"] == "valid"],
             other.label: [p for p in points_b if p["qualification"] == "valid"]}
    vins = sorted({p["vin_target_V"] for label in valid for p in valid[label]})
    for vin in vins:
        present = [label for label in (reference.label, other.label) if any(p["vin_target_V"] == vin for p in valid[label])]
        counts = {label: sum(1 for p in valid[label] if p["vin_target_V"] == vin) for label in present}
        if len(present) == 1:
            statement = f"{vin:g} V requested input: run {present[0]} only ({counts[present[0]]} valid point{'s' if counts[present[0]] != 1 else ''})"
        else:
            statement = f"{vin:g} V requested input: valid points in run {present[0]} ({counts[present[0]]}) and run {present[1]} ({counts[present[1]]})"
        rows.append({"scope": "input", "vin_target_V": vin, "valid_in": present, "counts": counts, "statement": statement})
    unpaired_valid = [row for row in unpaired if row["eligible"]]
    conditions = sorted({(row["test_id"], row["vin_target_V"]) for row in unpaired_valid})
    for test_id, vin in conditions:
        parts = []
        for label in (reference.label, other.label):
            rows_here = [row for row in unpaired_valid if row["run_label"] == label and row["test_id"] == test_id
                         and row["vin_target_V"] == vin]
            if not rows_here:
                continue
            repeated = [row for row in rows_here if "repeated condition" in row["reason"]]
            single = [row for row in rows_here if row not in repeated]
            if single:
                loads = sorted({row["iout_target_A"] for row in single})
                parts.append(", ".join(_load_text(v) for v in loads) + f" only in run {label}")
            if repeated:
                by_load = Counter(row["iout_target_A"] for row in repeated)
                parts.append("; ".join(f"{n} repeated observations at {_load_text(load)} in run {label} (not paired)"
                                       for load, n in sorted(by_load.items())))
        rows.append({"scope": "load", "test_id": test_id, "vin_target_V": vin,
                     "statement": f"{test_id} at {vin:g} V: " + "; ".join(parts)})
    return rows


def _largest(pairs: list[dict], key: str) -> dict | None:
    finite = [p for p in pairs if _finite_number(p.get(key)) is not None]
    return max(finite, key=lambda p: abs(p[key])) if finite else None


def build_comparison_model(runs: list[LoadedRun], policy: PairingPolicy,
                           covariance: dict[str, Any] | None = None) -> ComparisonReportModel:
    if len(runs) < 2:
        raise ValueError("A comparison needs at least two runs")
    if len({loaded.run_id for loaded in runs}) != len(runs):
        raise ValueError("Each compared run must be a different acquisition")
    reference, others = runs[0], runs[1:]
    per_run_points = {loaded.label: _prefixed_points(loaded) for loaded in runs}
    points: list[dict] = [p for loaded in runs for p in per_run_points[loaded.label]]
    pairs: list[dict] = []
    unpaired: list[dict] = []
    interpolated: list[dict] = []
    availability: list[dict] = []
    uncertainty_by_run: dict[str, Any] = {}
    for other in others:
        same_boundary = reference.boundary == other.boundary
        new_pairs, new_unpaired = pair_points(per_run_points[reference.label], per_run_points[other.label], policy,
                                              same_boundary=same_boundary, label_a=reference.label, label_b=other.label)
        uncertainty_by_run[other.label] = evaluate_pair_uncertainty(new_pairs, reference, other, covariance)
        if policy.interpolation_enabled and same_boundary:
            interpolated.extend(interpolate_unpaired(per_run_points[reference.label], per_run_points[other.label],
                                                     new_unpaired, policy, reference.label, other.label))
        availability.extend(_availability(reference, other, per_run_points[reference.label], per_run_points[other.label], new_unpaired))
        pairs.extend(new_pairs)
        unpaired.extend(new_unpaired)
    for pair in pairs:
        for point in points:
            if point["point_id"] in (pair["point_id_a"], pair["point_id_b"]):
                point["pair_id"] = pair["pair_id"]
    points.extend(copy.deepcopy(pairs))
    points.extend(copy.deepcopy(interpolated))
    if len(others) == 1:
        difference_uncertainty = uncertainty_by_run[others[0].label]
    else:
        statuses = {summary["status"] for summary in uncertainty_by_run.values()}
        difference_uncertainty = {"status": statuses.pop() if len(statuses) == 1 else "partially evaluated",
                                  "model": DIFFERENCE_MODEL, "per_run": uncertainty_by_run,
                                  "assumption": {"independence_assumed": any(s["assumption"].get("independence_assumed") for s in uncertainty_by_run.values()),
                                                 "applicable": any(s["assumption"].get("applicable") for s in uncertainty_by_run.values()),
                                                 "statement": "See per_run for each pairing's covariance basis."}}
    evidence_labels = {loaded.evidence_label for loaded in runs}
    evidence_label = evidence_labels.pop() if len(evidence_labels) == 1 else "MIXED: SYNTHETIC AND MEASURED"
    boundaries = {loaded.boundary for loaded in runs}
    boundary = boundaries.pop() if len(boundaries) == 1 else " | ".join(f"{loaded.label}: {loaded.boundary}" for loaded in runs)
    dut_dumps = {loaded.label: loaded.plan.dut.model_dump() for loaded in runs}
    bench_dumps = {loaded.label: loaded.plan.bench.model_dump() for loaded in runs}
    recipe_dumps = {loaded.label: loaded.plan.recipe.model_dump() for loaded in runs}
    method_dumps = {loaded.label: copy.deepcopy(loaded.run.get("method", {})) for loaded in runs}
    identity_dumps = {loaded.label: copy.deepcopy(loaded.run.get("instrument_identities", {})) for loaded in runs}
    software_dumps = {loaded.label: copy.deepcopy(loaded.run.get("software", {})) for loaded in runs}
    disclosures: list[Disclosure] = []
    identical = {}
    for section, dumps in (("dut", dut_dumps), ("bench", bench_dumps), ("recipe", recipe_dumps),
                           ("method", method_dumps), ("instrument_identities", identity_dumps), ("software", software_dumps)):
        fields: dict[str, dict[str, Any]] = {}
        for other in others:
            for path, value_a, value_b in _differences(dumps[reference.label], dumps[other.label]):
                fields.setdefault(f"{section}.{path}", {reference.label: value_a})[other.label] = value_b
        identical[section] = not fields
        disclosures.extend(Disclosure(field=name, values=values) for name, values in fields.items())
    models = {loaded.plan.dut.identity.model for loaded in runs}
    identity_label = models.pop() if len(models) == 1 else " / ".join(f"{loaded.label}: {loaded.plan.dut.identity.model}" for loaded in runs)
    comparison_id = "cmp-" + hashlib.sha256(json.dumps({"runs": [(loaded.run_id, loaded.analysis_id) for loaded in runs],
        "policy": policy.model_dump(), "covariance": covariance, "version": COMPARISON_VERSION}, sort_keys=True).encode()).hexdigest()[:12]
    figures, tables = _figures_and_tables(runs, points, pairs, unpaired, interpolated, evidence_label, boundary, policy)
    metrics = _metrics(pairs, evidence_label, difference_uncertainty)
    summary, summary_evidence, limitations = _narrative(runs, pairs, unpaired, interpolated, availability,
                                                        difference_uncertainty, disclosures, identical, metrics, policy, boundary)
    observation = "measured" if evidence_label == "MEASURED" else "synthetic" if evidence_label == "SYNTHETIC" else "mixed synthetic/measured"
    prose = [f"Comparison of stored analyses ({COMPARISON_VERSION}); no instrument was commanded and no source run folder was modified.",
             f"delta_eta_pp = eta_{others[0].label}_pct - eta_{reference.label}_pct; loss and output-voltage differences use the same "
             f"run {others[0].label} minus run {reference.label} convention. Positive and negative differences receive the same neutral treatment.",
             f"Pairing basis: {policy.basis}; requested input voltage within {policy.requested_input_tolerance_V:g} V and requested load "
             f"within {policy.requested_load_tolerance_A:g} A; same measurement boundary, test type and test id; valid qualification on both sides."]
    provenance = {"comparison_version": COMPARISON_VERSION, "formula_versions": {loaded.label: loaded.analysis["formula_version"] for loaded in runs},
                  "plan_hashes": {loaded.label: loaded.plan.plan_hash for loaded in runs},
                  "evidence_hashes": {loaded.label: loaded.analysis.get("evidence_hash") for loaded in runs},
                  "run_dirs": {loaded.label: str(loaded.run_dir) for loaded in runs},
                  "data_sources": {loaded.label: loaded.run.get("data_source", "unknown") for loaded in runs},
                  "covariance_model": covariance, "publication": "local only; not approved for publication"}
    return ComparisonReportModel(run_id=comparison_id, analysis_id=comparison_id, report_revision="r0001",
        title=f"{identity_label} · paired comparison of runs {' and '.join(loaded.label for loaded in runs)}",
        evidence_label=evidence_label, boundary=boundary,
        dut={"identity": {"model": identity_label, "sample_id": None if len({loaded.plan.dut.identity.sample_id for loaded in runs}) != 1
                          else reference.plan.dut.identity.sample_id}, "same_profile": identical["dut"], "per_run": dut_dumps},
        bench={"bench_id": " / ".join(f"{loaded.label}: {loaded.plan.bench.bench_id}" for loaded in runs),
               "same_profile": identical["bench"], "per_run": bench_dumps},
        execution={loaded.label: {"status": loaded.run.get("execution_status", "unknown"), "created_utc": loaded.run.get("created_utc"),
                                  "duration_s": loaded.run.get("duration_s"), "method_keys": sorted(method_dumps[loaded.label])} for loaded in runs},
        coverage={loaded.label: copy.deepcopy(loaded.analysis["coverage"]) for loaded in runs},
        points=points, metrics=metrics, figures=figures, tables=tables,
        evidence=[EvidenceRef(point_ids=m.point_ids, figure_ids=m.figure_ids) for m in metrics],
        summary=summary, summary_evidence=summary_evidence, method=None, prose=prose, limitations=limitations,
        raw_samples={}, provenance=provenance, comparison_id=comparison_id, comparison_version=COMPARISON_VERSION,
        runs=[_run_summary(loaded) for loaded in runs], pairing=policy, pairs=pairs, unpaired=unpaired,
        interpolated=interpolated, availability=availability, difference_uncertainty=difference_uncertainty,
        disclosures=disclosures, identical=identical)


def _figures_and_tables(runs: list[LoadedRun], points: list[dict], pairs: list[dict], unpaired: list[dict], interpolated: list[dict],
                        evidence_label: str, boundary: str, policy: PairingPolicy) -> tuple[list[FigureSpec], list[TableSpec]]:
    reference = runs[0]
    conditions: dict[tuple[str, float], str] = {}
    for point in points:
        if point["kind"] == "point":
            conditions.setdefault((point["test_id"], point["vin_target_V"]), f"{point['test_id']}@{point['vin_target_V']:g}V")
    overlay_series: list[FigureSeries] = []
    for loaded in runs:
        for index, ((test_id, vin), key) in enumerate(conditions.items()):
            ids = [p["point_id"] for p in points if p["kind"] == "point" and p["run_label"] == loaded.label
                   and p["test_id"] == test_id and p["vin_target_V"] == vin]
            if ids:
                overlay_series.append(FigureSeries(id=f"{loaded.label}-{test_id}-v{index}",
                    label=f"Run {loaded.label} ({loaded.evidence_label}) · {test_id} · {vin:g} V", vin_target_V=vin,
                    point_ids=ids, run_label=loaded.label, condition_key=key))
    delta_series: list[FigureSeries] = []
    for loaded in runs[1:]:
        for index, ((test_id, vin), key) in enumerate(conditions.items()):
            ids = [p["point_id"] for p in pairs if p["label_b"] == loaded.label and p["test_id"] == test_id and p["vin_target_V"] == vin]
            if ids:
                delta_series.append(FigureSeries(id=f"delta-{loaded.label}-{test_id}-v{index}",
                    label=f"Run {loaded.label} − run {reference.label} · {test_id} · {vin:g} V", vin_target_V=vin,
                    point_ids=ids, connect_points=False, run_label=loaded.label, condition_key=key))
    labels = " and ".join(f"run {loaded.label} ({loaded.evidence_label}, {loaded.run_id})" for loaded in runs)
    other_label = runs[1].label
    common = (f"{evidence_label}. {boundary}. {labels}. Color identifies the operating condition (test id and requested input); "
              f"line style and marker identify the run. Markers are qualified DC operating-point means from each run's stored analysis.")
    figures = [
        FigureSpec(id="fig-delta-efficiency", title="Efficiency Difference at Paired Points", x_key="iout_target_A",
            y_key="delta_eta_pp", x_label="Requested Output Current (A) — pairing condition", y_label="Efficiency Difference (percentage points)",
            series=delta_series, caption=f"{evidence_label}. delta_eta_pp = eta_{other_label}_pct − eta_{reference.label}_pct at each paired point "
            f"({len(pairs)} pairs). The zero line marks equal efficiency; points above it show run {other_label} higher, points below show "
            f"run {reference.label} higher, with the same neutral treatment. Horizontal position is the shared requested load; measured currents are in the paired table. "
            "No uncertainty bands are drawn unless a difference budget is evaluated."),
        FigureSpec(id="fig-delta-loss", title="Power-Loss Difference at Paired Points", x_key="iout_target_A", y_key="delta_loss_W",
            x_label="Requested Output Current (A) — pairing condition", y_label="Power-Loss Difference (W)", series=delta_series,
            caption=f"{evidence_label}. delta_loss_W = loss_{other_label} − loss_{reference.label} across the declared boundary at each paired point; "
            "the zero line marks equal loss. Loss differences are propagated separately from efficiency; they are not derived from the efficiency difference."),
        FigureSpec(id="fig-delta-voltage", title="Output-Voltage Difference at Paired Points", x_key="iout_target_A", y_key="delta_Vout_V",
            x_label="Requested Output Current (A) — pairing condition", y_label="Output-Voltage Difference (V)", series=delta_series,
            caption=f"{evidence_label}. delta_Vout_V = Vout_{other_label} − Vout_{reference.label} at each paired point; the zero line marks equal output voltage."),
        FigureSpec(id="fig-cmp-efficiency", title="Efficiency Overlay", x_key="Iout_A", y_key="efficiency_pct",
            x_label="Output Current (A)", y_label="Efficiency (%)", series=overlay_series,
            caption=common + " Efficiency = 100 × Pout/Pin; no-load efficiency is not evaluated."),
        FigureSpec(id="fig-cmp-voltage", title="Output Voltage Overlay", x_key="Iout_A", y_key="Vout_V",
            x_label="Output Current (A)", y_label="Output Voltage (V)", series=overlay_series,
            caption=common + " Absolute output voltage at each run's declared output measurement location."),
        FigureSpec(id="fig-cmp-loss", title="Power Loss Overlay", x_key="Iout_A", y_key="loss_W",
            x_label="Output Current (A)", y_label="Power Loss (W)", series=overlay_series,
            caption=common + " Power loss = Pin − Pout across each run's declared boundary, including wiring."),
    ]
    if policy.interpolation_enabled:
        interp_series = []
        for index, ((test_id, vin), key) in enumerate(conditions.items()):
            for measured_label in {row["run_label"] for row in interpolated}:
                ids = [row["point_id"] for row in interpolated if row["test_id"] == test_id and row["vin_target_V"] == vin
                       and row["run_label"] == measured_label]
                if ids:
                    interp_series.append(FigureSeries(id=f"interp-{measured_label}-{test_id}-v{index}",
                        label=f"INTERPOLATED · measured run {measured_label} vs interpolated other run · {test_id} · {vin:g} V",
                        vin_target_V=vin, point_ids=ids, connect_points=False, run_label=measured_label, condition_key=key))
        figures.append(FigureSpec(id="fig-delta-efficiency-interpolated", title="INTERPOLATED Efficiency Difference (not measured)",
            x_key="iout_target_A", y_key="delta_eta_pp", x_label="Requested Output Current (A) of the measured point",
            y_label="Efficiency Difference (percentage points), INTERPOLATED", series=interp_series,
            caption=f"{evidence_label}. INTERPOLATED comparison, enabled explicitly: at loads measured in only one run, the other run's "
            "curve is evaluated by linear interpolation between its two bracketing measured points on the same test id and input condition. "
            "These hollow markers are not measurements; they are excluded from the paired-point counts, metrics and summary."))
    tables = [
        TableSpec(id="table-paired", title="Paired measured points", columns=PAIR_TABLE_COLUMNS, point_ids=[p["point_id"] for p in pairs]),
        TableSpec(id="table-unpaired", title="Valid points without a partner", columns=UNPAIRED_TABLE_COLUMNS,
                  point_ids=[row["point_id"] for row in unpaired if row["eligible"]]),
        TableSpec(id="table-points", title="All points of every compared run", columns=POINT_TABLE_COLUMNS,
                  point_ids=[p["point_id"] for p in points if p["kind"] == "point"]),
    ]
    if interpolated:
        tables.append(TableSpec(id="table-interpolated", title="INTERPOLATED comparisons (not measured)",
                                columns=INTERPOLATED_TABLE_COLUMNS, point_ids=[row["point_id"] for row in interpolated]))
    return figures, tables


PAIR_TABLE_COLUMNS = ["pair_id", "test_id", "vin_target_V", "iout_target_A", "point_id_a", "point_id_b", "Iout_a_A", "Iout_b_A",
                      "eta_a_pct", "eta_b_pct", "delta_eta_pp", "loss_a_W", "loss_b_W", "delta_loss_W", "Vout_a_V", "Vout_b_V",
                      "delta_Vout_V", "u_delta_eta_pp"]
UNPAIRED_TABLE_COLUMNS = ["run_label", "point_id", "test_id", "vin_target_V", "iout_target_A", "qualification", "reason"]
POINT_TABLE_COLUMNS = ["run_label", "point_id", "test_id", "vin_target_V", "iout_target_A", "Vin_V", "Iin_A", "Vout_V", "Iout_A",
                       "Pin_W", "Pout_W", "loss_W", "efficiency_pct", "qualification", "pair_id"]
INTERPOLATED_TABLE_COLUMNS = ["point_id", "run_label", "interpolated_run", "test_id", "vin_target_V", "iout_target_A",
                              "eta_measured_pct", "eta_interpolated_pct", "delta_eta_pp", "bracket_point_ids"]


def _metric_uncertainty(pair: dict | None, quantity: str, unit: str, difference_uncertainty: dict) -> dict[str, Any]:
    if pair is None:
        return {"status": "not evaluated", "expanded": None, "reason": "no paired point"}
    entry = (pair.get("uncertainty") or {}).get(quantity) or {}
    if entry.get("status") != "evaluated":
        return {"status": "not evaluated", "expanded": None,
                "reason": entry.get("reason", "no evaluated difference budget"), "unit": unit}
    return {"status": "evaluated", "standard": entry["u_delta"], "expanded": entry.get("expanded"), "k": entry.get("k"),
            "unit": unit, "model": DIFFERENCE_MODEL, "covariance": entry["covariance"], "covariance_basis": entry["covariance_basis"],
            "assumption": difference_uncertainty.get("assumption", {}).get("statement")}


def _metrics(pairs: list[dict], evidence_label: str, difference_uncertainty: dict) -> list[MetricResult]:
    observation = {"MEASURED": "measured", "SYNTHETIC": "synthetic"}.get(evidence_label, "mixed synthetic/measured")
    metrics = [MetricResult(id="paired-point-count", label="Paired measured points", value=float(len(pairs)), unit="points",
        formula="count of valid points matched by declared conditions on both runs", conditions="all paired conditions",
        selector={"comparison": "paired points"}, point_ids=[p["point_id"] for p in pairs], figure_ids=["fig-delta-efficiency"],
        qualification=f"{observation} observation")]
    for quantity, key, unit, ident, label, figure in (
            ("efficiency_pct", "delta_eta_pp", "percentage points", "largest-efficiency-difference", "Largest observed efficiency difference (B − A)", "fig-delta-efficiency"),
            ("loss_W", "delta_loss_W", "W", "largest-loss-difference", "Largest observed power-loss difference (B − A)", "fig-delta-loss"),
            ("Vout_V", "delta_Vout_V", "V", "largest-voltage-difference", "Largest observed output-voltage difference (B − A)", "fig-delta-voltage")):
        pair = _largest(pairs, key)
        if pair is None:
            continue
        metrics.append(MetricResult(id=ident, label=label.replace("B − A", f"{pair['label_b']} − {pair['label_a']}"), value=pair[key], unit=unit,
            formula=f"{key} = {quantity} of run {pair['label_b']} point − {quantity} of run {pair['label_a']} point at one paired condition",
            conditions=f"{pair['vin_target_V']:g} V requested input, {pair['iout_target_A']:g} A requested load ({pair['test_id']}); "
                       f"run {pair['label_a']} point {pair['source_point_id_a']}, run {pair['label_b']} point {pair['source_point_id_b']}",
            selector={"pair_id": pair["pair_id"]}, point_ids=[pair["point_id"], pair["point_id_a"], pair["point_id_b"]],
            figure_ids=[figure], qualification=f"{observation} observation",
            uncertainty=_metric_uncertainty(pair, quantity, unit, difference_uncertainty)))
    return metrics


def _narrative(runs: list[LoadedRun], pairs: list[dict], unpaired: list[dict], interpolated: list[dict], availability: list[dict],
               difference_uncertainty: dict, disclosures: list[Disclosure], identical: dict[str, bool], metrics: list[MetricResult],
               policy: PairingPolicy, boundary: str) -> tuple[list[str], list[SummaryEvidence], list[str]]:
    reference, other = runs[0], runs[1]
    summary: list[str] = []
    evidence: list[SummaryEvidence] = []
    metric_ids = {m.id for m in metrics}
    labels = ", ".join(f"run {loaded.label} = {loaded.run_id} (analysis {loaded.analysis_id}, {loaded.evidence_label})" for loaded in runs)
    summary.append(f"This comparison reads stored analyses only: {labels}. Measurement boundary: {boundary}.")
    if pairs:
        by_condition = defaultdict(list)
        for pair in pairs:
            by_condition[(pair["test_id"], pair["vin_target_V"])].append(pair["iout_target_A"])
        described = "; ".join(f"{test_id} at {vin:g} V: " + ", ".join(_load_text(v) for v in sorted(loads))
                              for (test_id, vin), loads in sorted(by_condition.items()))
        evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=["paired-point-count"]))
        summary.append(f"{len(pairs)} paired measured point{'s' if len(pairs) != 1 else ''} matched by requested conditions and identifiers "
                       f"(input within {policy.requested_input_tolerance_V:g} V, load within {policy.requested_load_tolerance_A:g} A, same test id, "
                       f"both valid): {described}.")
        largest = next((m for m in metrics if m.id == "largest-efficiency-difference"), None)
        if largest:
            pair = next(p for p in pairs if p["pair_id"] == largest.selector["pair_id"])
            evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[largest.id]))
            summary.append(f"Largest observed efficiency difference (run {pair['label_b']} minus run {pair['label_a']}): {largest.value:+.2f} percentage points "
                           f"at {largest.conditions}; run {pair['label_a']} {pair['eta_a_pct']:.2f}%, run {pair['label_b']} {pair['eta_b_pct']:.2f}%. "
                           f"Measured output currents at that pair: {pair['Iout_a_A']:.4f} A and {pair['Iout_b_A']:.4f} A.")
        deltas = [p["delta_eta_pp"] for p in pairs if _finite_number(p.get("delta_eta_pp")) is not None]
        if deltas:
            higher_b = [p for p in pairs if _finite_number(p.get("delta_eta_pp")) is not None and p["delta_eta_pp"] > 0]
            higher_a = [p for p in pairs if _finite_number(p.get("delta_eta_pp")) is not None and p["delta_eta_pp"] < 0]
            if higher_a and higher_b:
                ordering = (f"The sign of the efficiency difference reverses between paired conditions: run {other.label} higher at "
                            + ", ".join(_load_text(p["iout_target_A"]) for p in higher_b) + f"; run {reference.label} higher at "
                            + ", ".join(_load_text(p["iout_target_A"]) for p in higher_a) + ". Both regions are retained.")
            elif higher_b or higher_a:
                winner = other.label if higher_b else reference.label
                ordering = (f"Run {winner} showed the higher efficiency at {len(higher_b or higher_a)} of {len(deltas)} paired points"
                            + (" and equal efficiency at the rest" if len(higher_b or higher_a) < len(deltas) else "")
                            + ". This ordering describes the paired conditions of these two runs only; it is not a statement about other conditions, samples or devices.")
            else:
                ordering = "Efficiency was equal at every paired point."
            summary.append(f"Efficiency differences across the paired points range from {min(deltas):+.2f} to {max(deltas):+.2f} percentage points. " + ordering)
        for ident, name, unit in (("largest-loss-difference", "power-loss", "W"), ("largest-voltage-difference", "output-voltage", "V")):
            metric = next((m for m in metrics if m.id == ident), None)
            if metric:
                evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[metric.id]))
                summary.append(f"Largest observed {name} difference: {metric.value:+.4f} {unit} at {metric.conditions}.")
    else:
        reasons = Counter(row["reason"] for row in unpaired if row["eligible"])
        summary.append("No point could be paired under the declared rules. " +
                       ("Recorded reasons: " + "; ".join(f"{reason} ({count})" for reason, count in reasons.most_common(4)) + "."
                        if reasons else "Neither run has valid points."))
    for row in availability:
        if row["scope"] == "input" and len(row["valid_in"]) == 1:
            summary.append(row["statement"] + "; these points have no partner and are listed separately.")
    load_rows = [row["statement"] for row in availability if row["scope"] == "load"]
    if load_rows:
        summary.append("Valid points without a partner (listed separately, not interpolated): " + " | ".join(load_rows) + ".")
    ineligible = Counter((row["run_label"], row["qualification"]) for row in unpaired if not row["eligible"])
    if ineligible:
        summary.append("Points not eligible for pairing: " + "; ".join(f"run {label}: {count} {qualification}" for (label, qualification), count in sorted(ineligible.items()))
                       + ". Unattempted candidates are not failed measurements.")
    if policy.interpolation_enabled:
        summary.append(f"INTERPOLATED comparison enabled explicitly: {len(interpolated)} labeled interpolated row{'s' if len(interpolated) != 1 else ''} "
                       "are shown separately and excluded from the paired-point counts, metrics and statements above.")
    status = difference_uncertainty["status"]
    if status == "not evaluated":
        summary.append("Difference resolvability: not evaluated. " + difference_uncertainty.get("reason", "") +
                       " No statement is made about whether any difference exceeds measurement uncertainty.")
    else:
        assumption = difference_uncertainty.get("assumption", {})
        k = difference_uncertainty.get("coverage_factor")
        summary.append(f"Difference uncertainty ({status}) uses {DIFFERENCE_MODEL}. {assumption.get('statement', '')} "
                       + (f"Expanded values use the analyses' shared coverage factor k = {k:g}; that interval is not automatically a validated 95% confidence interval."
                          if k is not None else "No shared coverage factor is declared, so only standard uncertainties are reported."))
    differing = [d.field for d in disclosures]
    same = [name for name, flag in identical.items() if flag]
    summary.append(f"{len(differing)} recorded DUT, bench, recipe, method, instrument-identity or software fields differ between the runs"
                   + (f" (first: {', '.join(differing[:6])}{'; …' if len(differing) > 6 else ''})" if differing else "")
                   + (f"; identical sections: {', '.join(same)}" if same else "") +
                   ". The implementations are compared as tested; no observed difference is attributed to a mechanism, component or design choice.")
    thermal = {loaded.label: loaded.plan for loaded in runs}
    measured_temps = [label for label, plan in thermal.items() if _temperature_measured(plan)]
    limitations = [
        "Comparison of stored analyses only; no instrument was commanded and no source run folder was modified.",
        "Pairs use requested conditions within the declared tolerances; measured input voltage and output current of both points are retained in the paired table.",
        ("Thermal state was not measured in either run; nothing about temperature or junction conditions follows from these DC points."
         if not measured_temps else f"Temperature channels exist in run {', '.join(measured_temps)} only; thermal state is not compared."),
        "A difference at one paired condition describes that condition only; it does not establish an ordering across other loads, inputs, samples or devices.",
        ("Sample identities are not recorded, so whether the runs tested the same physical unit is not established."
         if all(loaded.plan.dut.identity.sample_id is None for loaded in runs) else
         "Recorded sample identities: " + ", ".join(f"run {loaded.label}: {loaded.plan.dut.identity.sample_id or 'not recorded'}" for loaded in runs) + "."),
    ]
    if status == "not evaluated":
        limitations.append("Uncertainty is unquantified in at least one analysis; no bands are drawn and no resolvability verdict is given.")
    else:
        limitations.append("Difference uncertainties depend on the supplied budgets and the recorded covariance basis; independence, where assumed, is not established by evidence.")
    if policy.interpolation_enabled:
        limitations.append("Interpolated rows are linear estimates between two measured points of the other run; they are not measurements and carry no evaluated budget.")
    for loaded in runs:
        for note in loaded.run.get("metrology_limitations", []):
            text = f"Run {loaded.label}: {note}"
            if text not in limitations:
                limitations.append(text)
    return summary, evidence, limitations


def load_covariance(path: Path | None) -> dict[str, Any] | None:
    """Read a covariance model: {"quantities": {"efficiency_pct": cov, ...}, "note": "..."}."""
    if path is None:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("quantities"), dict):
        raise ValueError("Covariance model must be a JSON object with a 'quantities' mapping")
    unknown = set(value["quantities"]) - {quantity for quantity, _, _ in PAIRED_QUANTITIES}
    if unknown:
        raise ValueError(f"Covariance model names unknown quantities: {sorted(unknown)}")
    return {"quantities": {name: float(v) for name, v in value["quantities"].items()}, "note": value.get("note")}


def compare_runs(run_dirs: list[Path], out: Path, *, analysis_ids: list[str | None] | None = None,
                 requested_input_tolerance_V: float = .01, requested_load_tolerance_A: float = .001,
                 interpolate: bool = False, covariance_path: Path | None = None, covariance: dict[str, Any] | None = None,
                 overwrite: bool = False) -> Path:
    """Load, verify, pair and write a comparison folder; the source runs stay read-only."""
    if len(run_dirs) < 2:
        raise ValueError("Give at least two run folders to compare")
    if len(run_dirs) > len(RUN_LABELS):
        raise ValueError(f"At most {len(RUN_LABELS)} runs can be compared at once")
    ids = list(analysis_ids or [])
    ids.extend([None] * (len(run_dirs) - len(ids)))
    policy = PairingPolicy(requested_input_tolerance_V=float(requested_input_tolerance_V),
                           requested_load_tolerance_A=float(requested_load_tolerance_A), interpolation_enabled=bool(interpolate))
    if covariance_path is not None and covariance is not None:
        raise ValueError("Supply the covariance model once")
    covariance = load_covariance(covariance_path) if covariance_path is not None else covariance
    runs = [load_run(Path(run_dir), analysis_id, label) for run_dir, analysis_id, label in zip(run_dirs, ids, RUN_LABELS)]
    model = build_comparison_model(runs, policy, covariance)
    from .reporting.comparison import write_comparison
    return write_comparison(model.model_dump(), Path(out), overwrite=overwrite,
                            created_utc=datetime.now(timezone.utc).isoformat())
