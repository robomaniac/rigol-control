"""Pure settled-DC calculations and versioned analysis of preserved evidence.

Input power is positive into the declared boundary; output power is positive
out. Channel means (not mean instantaneous waveform power) define DC metrics.
"""
from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import Field, model_validator

from .domain import AcquisitionPolicy, Contract, Plan, RawSample, SettlingPolicy
from .storage import atomic_json, verify_integrity

FORMULA_VERSION = "settled-dc-1.1"
QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")
CSV_FIELDS = ["run_id", "analysis_id", "test_id", "point_id", "vin_target_V",
              "iout_target_A", *QUANTITIES, "Pin_W", "Pout_W", "loss_W",
              "efficiency_pct", "vout_error_pct", "qualification", "reason"]


class EvidenceRef(Contract):
    point_ids: list[str]
    figure_ids: list[str] = Field(default_factory=list)
    sample_ids: list[str] = Field(default_factory=list)


class MetricResult(Contract):
    id: str
    label: str
    value: float | None
    unit: str
    formula: str
    conditions: str
    selector: dict[str, Any]
    point_ids: list[str]
    figure_ids: list[str]
    qualification: str = "synthetic observation"
    uncertainty: dict[str, Any] = Field(default_factory=lambda: {
        "status": "unquantified", "expanded": None, "reason": "No applicable budget evaluated"})


class FigureSeries(Contract):
    id: str
    label: str
    point_ids: list[str]
    vin_target_V: float | None
    iout_target_A: float | None = None
    selection_key: str | None = None
    connect_points: bool = True
    # Comparison overlays: color follows the operating condition, line style
    # and marker follow the run. Single-run reports leave both unset.
    run_label: str | None = None
    condition_key: str | None = None


class FigureSpec(Contract):
    id: str
    title: str
    x_key: str
    y_key: str
    x_label: str
    y_label: str
    caption: str
    series: list[FigureSeries]


class TableSpec(Contract):
    id: str
    title: str
    columns: list[str]
    point_ids: list[str]


class SummaryEvidence(Contract):
    """References belong to a paragraph, while prose stays plain text."""
    paragraph_index: int = Field(ge=0)
    metric_ids: list[str]


class PointTiming(Contract):
    point_id: str
    qualification: str
    accepted_cycle_count: int | None = Field(default=None, ge=0)
    settling_elapsed_s: float | None = Field(default=None, ge=0)
    settling_inherited_from_previous_point: bool = False
    acquisition_elapsed_s: float | None = Field(default=None, ge=0)
    accepted_query_span_s: float | None = Field(default=None, ge=0)
    maximum_accepted_interchannel_skew_s: float | None = Field(default=None, ge=0)


class ReportMethod(Contract):
    declared_acquisition: AcquisitionPolicy
    declared_settling: SettlingPolicy
    clock_mode: str | None = None
    clock_note: str | None = None
    achieved_points: list[PointTiming]
    procedure_notes: list[str] = Field(default_factory=list)


class ReportModel(Contract):
    schema_version: str = "1.0"
    run_id: str
    analysis_id: str
    report_revision: str
    title: str
    evidence_label: str = "SYNTHETIC"
    boundary: str
    dut: dict[str, Any]
    bench: dict[str, Any]
    execution: dict[str, Any]
    coverage: dict[str, Any]
    points: list[dict[str, Any]]
    metrics: list[MetricResult]
    figures: list[FigureSpec]
    tables: list[TableSpec]
    evidence: list[EvidenceRef]
    summary: list[str]
    summary_evidence: list[SummaryEvidence] = Field(default_factory=list)
    method: ReportMethod | None = None
    prose: list[str]
    limitations: list[str]
    raw_samples: dict[str, list[dict[str, Any]]]
    provenance: dict[str, Any]

    @model_validator(mode="after")
    def references_exist(self) -> ReportModel:
        points = {p["point_id"]: p for p in self.points}
        if len(points) != len(self.points):
            raise ValueError("Duplicate point identifiers")
        figures = {f.id for f in self.figures}
        if len(figures) != len(self.figures):
            raise ValueError("Duplicate figure identifiers")
        for figure in self.figures:
            for series in figure.series:
                if series.vin_target_V is None and (series.iout_target_A is None or not series.selection_key):
                    raise ValueError("A series spanning input voltages must declare its common load and selection key")
                for pid in series.point_ids:
                    if pid not in points:
                        raise ValueError(f"Missing figure point {pid}")
                    if series.vin_target_V is not None and points[pid]["vin_target_V"] != series.vin_target_V:
                        raise ValueError("Figure condition does not match referenced point")
                    if series.iout_target_A is not None and points[pid]["iout_target_A"] != series.iout_target_A:
                        raise ValueError("Figure load condition does not match referenced point")
        samples = {s["sample_id"] for rows in self.raw_samples.values() for s in rows}
        for item in [*self.metrics, *self.tables, *self.evidence]:
            if not set(item.point_ids) <= points.keys():
                raise ValueError("Missing evidence point")
            if hasattr(item, "figure_ids") and not set(item.figure_ids) <= figures:
                raise ValueError("Missing evidence figure")
            if hasattr(item, "sample_ids") and not set(item.sample_ids) <= samples:
                raise ValueError("Missing evidence sample")
        for metric in self.metrics:
            for pid in metric.point_ids:
                for key, value in metric.selector.items():
                    if key in ("vin_target_V", "iout_target_A", "test_id", "point_id") and points[pid].get(key) != value:
                        raise ValueError("Metric selector does not match referenced point")
        metric_ids = {metric.id for metric in self.metrics}
        if len(metric_ids) != len(self.metrics):
            raise ValueError("Duplicate metric identifiers")
        referenced_paragraphs = set()
        for reference in self.summary_evidence:
            if reference.paragraph_index >= len(self.summary):
                raise ValueError("Summary reference targets a missing paragraph")
            if reference.paragraph_index in referenced_paragraphs:
                raise ValueError("Duplicate summary paragraph reference")
            referenced_paragraphs.add(reference.paragraph_index)
            if not set(reference.metric_ids) <= metric_ids:
                raise ValueError("Summary reference targets a missing metric")
        if self.method and not {point.point_id for point in self.method.achieved_points} <= points.keys():
            raise ValueError("Method timing references a missing point")
        return self


def dc_metrics(values: dict[str, float | None], nominal_V: float,
               *, no_load: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = dict.fromkeys(["Pin_W", "Pout_W", "loss_W",
                                          "efficiency_pct", "vout_error_pct"])
    flags: list[str] = []
    if any(values.get(q) is None for q in QUANTITIES):
        return {**result, "metric_flags": ["missing_measurement"], "efficiency_reason": "missing measurement"}
    if not all(math.isfinite(values[q]) for q in QUANTITIES):
        raise ValueError("Nonfinite measurement")
    vin, iin, vout, iout = (values[q] for q in QUANTITIES)
    pin, pout = vin * iin, vout * iout
    result.update(Pin_W=pin, Pout_W=pout, loss_W=pin-pout,
                  vout_error_pct=100*(vout-nominal_V)/nominal_V)
    reason = None
    if vin < 0 or iin < 0 or vout < 0 or iout < 0:
        flags.append("unexpected_sign")
    if no_load:
        reason = "not applicable: enabled with no external load"
        # An electronic load can report a current offset while its input is
        # disabled. Preserve that reading, but do not turn it into delivered
        # output power or a converter/path loss estimate.
        result.update(Pout_W=None, loss_W=None)
        result["output_power_reason"] = "not evaluated: no external load; load-off current is not delivered output current"
        result["loss_reason"] = "not evaluated: output power is unavailable with no external load"
    elif pin <= 0:
        reason = "nonpositive input power"
        flags.append("nonpositive_input_power")
    else:
        result["efficiency_pct"] = 100 * pout / pin
        if not 0 <= result["efficiency_pct"] <= 100 or result["loss_W"] < 0:
            flags.append("implausible_power_ratio")
    return {**result, "metric_flags": flags, "efficiency_reason": reason}


def regulation_span(values: list[float], nominal_V: float) -> float:
    if len(values) < 2 or nominal_V <= 0:
        raise ValueError("Regulation span requires at least two values and positive nominal voltage")
    return 100 * (max(values)-min(values)) / nominal_V


def current_only_efficiency_uncertainty(eta_pct: float, iin: float, iout: float,
                                      input_bound: float, output_bound: float,
                                      *, k: float = 2) -> float:
    """Explicit independent rectangular current limits; units must match.

    Synthetic regression helper, not a complete bench budget. Systematic
    terms do not decrease with a count of repeated readings.
    """
    if min(iin, iout) <= 0 or min(input_bound, output_bound, k) < 0:
        raise ValueError("Positive currents and nonnegative limits required")
    return k * abs(eta_pct) / math.sqrt(3) * math.hypot(input_bound/iin, output_bound/iout)


def difference_standard_uncertainty(ua: float, ub: float, covariance: float = 0) -> float:
    if ua < 0 or ub < 0 or abs(covariance) > ua*ub + 1e-15:
        raise ValueError("Invalid covariance")
    return math.sqrt(max(0, ua*ua + ub*ub - 2*covariance))


def transition_bracket(last_on_V: float, first_off_V: float) -> dict[str, Any]:
    """Observed descending-ramp bracket; does not implement a UVLO procedure."""
    if first_off_V >= last_on_V:
        raise ValueError("Expected a descending on-to-off observation")
    return {"lower_V": first_off_V, "upper_V": last_on_V, "exact_threshold_V": None,
            "convention": "observed off at lower and on at upper; threshold unresolved within step"}


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return "" if value is None else value


def points_csv(points: list[dict[str, Any]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for point in points:
        writer.writerow({key: _safe_cell(point.get(key)) for key in CSV_FIELDS})
    return handle.getvalue()


def coverage_by_test(points: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for p in points:
        groups[p["test_id"]].append(p)
    return {test: {"requested": len(rows), **dict(Counter(p["qualification"] for p in rows))}
            for test, rows in groups.items()}


def _evidence_label(plan: Plan, run: dict) -> str:
    """Do not let a changed display label reclassify simulated evidence."""
    source = run.get("data_source", "simulated")
    expected_mode = {"simulated": "mock", "measured": "real"}.get(source)
    if expected_mode is None:
        raise ValueError(f"Unknown acquisition data_source: {source!r}")
    if plan.bench.mode != expected_mode or plan.recipe.execution_mode != expected_mode:
        raise ValueError("Acquisition data_source does not match bench and recipe execution modes")
    if "real_hardware_opened" in run and run["real_hardware_opened"] is not (source == "measured"):
        raise ValueError("Acquisition data_source disagrees with real_hardware_opened")
    if source == "measured" and run.get("clock", {}).get("mode") == "virtual":
        raise ValueError("Measured acquisition cannot use a virtual clock")
    return "MEASURED" if source == "measured" else "SYNTHETIC"


def analyze_evidence(plan: Plan, run: dict, samples: list[dict], *, version: str = FORMULA_VERSION) -> dict:
    """Pure analysis. Accepted complete cycles are designated by the worker."""
    evidence_label = _evidence_label(plan, run)
    grouped: dict[str, list[dict]] = defaultdict(list)
    requests = {p.point_id: p for p in plan.points}
    sample_ids: set[str] = set()
    for item in samples:
        row = RawSample.model_validate(item).model_dump()
        request = requests.get(row["point_id"])
        if request is None or request.test_id != row["test_id"] or row["run_id"] != run["run_id"]:
            raise ValueError("Raw sample references an undeclared run, test or point")
        if row["sample_id"] in sample_ids:
            raise ValueError("Duplicate raw sample identifier")
        sample_ids.add(row["sample_id"])
        binding = plan.bench.measurements.get(row["quantity"])
        if (binding is None or binding.unit != row["unit"] or binding.location != row["location"]
                or binding.instrument_id != row["instrument_id"]):
            raise ValueError("Raw measurement does not match its declared role, unit or location")
        grouped[row["point_id"]].append(row)
    outcomes = {p["point_id"]: p for p in run.get("points", [])}
    points = []
    for request in plan.points:
        outcome = outcomes.get(request.point_id, {})
        qualification = outcome.get("qualification", "not-run")
        cycles = set(outcome.get("acquisition_cycle_ids", []))
        accepted = [s for s in grouped[request.point_id] if s["acquisition_cycle_id"] in cycles]
        by_cycle: dict[str, list] = defaultdict(list)
        for sample in accepted:
            by_cycle[sample["acquisition_cycle_id"]].append(sample)
        if set(by_cycle) != cycles:
            raise ValueError("Worker accepted an acquisition cycle with no preserved readings")
        for cid, rows in by_cycle.items():
            if (Counter(s["quantity"] for s in rows) != Counter(QUANTITIES)
                    or any(s["quality_flags"] or s["value"] is None or s["status"] != "ok"
                           or s["phase"] != "acquiring"
                           or s["acquisition_settings"].get("source_mode") != "CV"
                           or s["acquisition_settings"].get("load_compliance") is not True for s in rows)
                    or max(s["query_end_monotonic_s"] for s in rows)-min(s["query_start_monotonic_s"] for s in rows)
                    > plan.recipe.acquisition.maximum_interchannel_skew_s):
                raise ValueError(f"Worker accepted an invalid acquisition cycle: {cid}")
        if qualification == "valid" and len(by_cycle) < plan.recipe.acquisition.minimum_complete_cycles:
            raise ValueError("Valid point lacks the required accepted complete cycles")
        values = {q: mean([s["value"] for s in accepted if s["quantity"] == q])
                  if any(s["quantity"] == q for s in accepted) else None for q in QUANTITIES}
        derived = dc_metrics(values, plan.dut.ratings.output_voltage_nominal_V,
                             no_load=request.iout_target_A == 0)
        if qualification != "valid":
            derived.update(efficiency_pct=None, efficiency_reason=f"point {qualification}")
        elif derived["metric_flags"]:
            qualification = "inconclusive"
        requirements = {"output_voltage": "not-evaluated", "efficiency": "not-evaluated",
                        "surface_temperature": "not-evaluated"}
        acceptance = plan.dut.acceptance
        if qualification == "valid":
            if acceptance.output_voltage_tolerance_pct is not None:
                requirements["output_voltage"] = "pass" if abs(derived["vout_error_pct"]) <= acceptance.output_voltage_tolerance_pct else "fail"
            if request.iout_target_A == 0:
                requirements["efficiency"] = "not-applicable"
            elif acceptance.minimum_efficiency_pct is not None and derived["efficiency_pct"] is not None:
                requirements["efficiency"] = "pass" if derived["efficiency_pct"] >= acceptance.minimum_efficiency_pct else "fail"
        points.append({**request.model_dump(), **values, **derived,
                       "run_id": run["run_id"], "test_id": request.test_id,
                       "qualification": qualification, "reason": outcome.get("reason", request.reason),
                       "requirements": requirements, "metrology": "unquantified",
                       "accepted_cycle_count": len(by_cycle),
                       "accepted_sample_ids": [s["sample_id"] for s in accepted],
                       "acquisition_cycle_ids": sorted(cycles)})
    return {"schema_version": "1.0", "formula_version": version,
            "aggregation": "Metrics from qualified channel means over accepted complete acquisition cycles",
            "sign_convention": "Positive power enters input boundary and leaves output boundary; no absolute-value correction",
            "run_id": run["run_id"], "evidence_label": evidence_label,
            "boundary": run.get("measurement_boundary", plan.bench.measurement_boundary),
            "points": points, "coverage": coverage_by_test(points),
            "uncertainty": {"status": "unquantified", "reason": "No applicable complete readback uncertainty budget evaluated", "bands": None}}


def _finite_number(value: Any) -> float | None:
    """Return a finite float, or None for missing, boolean or non-numeric values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _condition_phrase(nominal: float, programmed: float | None) -> str:
    """Name a recorded input condition: '24 V', or 'near 36 V' when its setpoint was reduced."""
    return f"near {nominal:g} V" if programmed is not None and programmed != nominal else f"{nominal:g} V"


def _join_phrases(phrases: list[str]) -> str:
    """'12 V, 24 V and near 36 V' from a recorded condition list; '' when empty."""
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + " and " + phrases[-1]


def _recorded_conditions(method: dict) -> list[tuple[float, float | None]]:
    """(nominal, programmed) pairs from a recorded method; programmed is None when not recorded."""
    nominals = method.get("nominal_input_voltages_V") or []
    programmed = method.get("programmed_input_voltages_V") or []
    pairs = []
    for index, nominal in enumerate(nominals):
        value = _finite_number(nominal)
        if value is None:
            continue
        setpoint = _finite_number(programmed[index]) if index < len(programmed) else None
        pairs.append((value, setpoint))
    return pairs


def _reduced_setpoints(method: dict) -> list[tuple[float, float]]:
    """Recorded conditions whose programmed setpoint differs from the nominal condition."""
    return [(nominal, setpoint) for nominal, setpoint in _recorded_conditions(method)
            if setpoint is not None and setpoint != nominal]


def _report_method(plan: Plan, run: dict, analysis: dict, raw_samples: list[dict]) -> ReportMethod:
    """Keep declared policy separate from recorded durations and query timing.

    A first-to-last query span is not the entire acquisition phase duration or
    proof of a device's ADC update rate. Missing phase durations remain unknown.
    """
    outcomes = {point["point_id"]: point for point in run.get("points", [])}
    samples = {sample["sample_id"]: sample for sample in raw_samples}
    timings = []
    for point in analysis["points"]:
        outcome = outcomes.get(point["point_id"], {})
        accepted_ids = point.get("accepted_sample_ids", [])
        accepted = [samples[sid] for sid in accepted_ids if sid in samples]
        query_span = maximum_skew = None
        if accepted and len(accepted) == len(accepted_ids):
            complete_timing = all(isinstance(sample.get(field), (float, int))
                and not isinstance(sample[field], bool) and math.isfinite(sample[field])
                for sample in accepted
                for field in ("query_start_monotonic_s", "query_end_monotonic_s"))
            if complete_timing:
                by_cycle = defaultdict(list)
                for sample in accepted:
                    by_cycle[sample["acquisition_cycle_id"]].append(sample)
                query_span = max(s["query_end_monotonic_s"] for s in accepted) - min(
                    s["query_start_monotonic_s"] for s in accepted)
                maximum_skew = max(max(s["query_end_monotonic_s"] for s in rows)
                    - min(s["query_start_monotonic_s"] for s in rows) for rows in by_cycle.values())
        timings.append(PointTiming(point_id=point["point_id"], qualification=point["qualification"],
            accepted_cycle_count=point.get("accepted_cycle_count"),
            settling_elapsed_s=outcome.get("settling_elapsed_s"),
            settling_inherited_from_previous_point=outcome.get("settling_inherited_from_previous_point", False),
            acquisition_elapsed_s=outcome.get("acquisition_elapsed_s"),
            accepted_query_span_s=query_span,
            maximum_accepted_interchannel_skew_s=maximum_skew))
    clock = run.get("clock", {})
    recorded_method = run.get("method", {})
    notes = []
    if recorded_method.get("configured_dc_sweep"):
        notes.append("This configured DC sweep cold-starts each input-voltage phase with both outputs OFF before reconfiguration. "
                     "Startup readings must establish output voltage before the load is enabled; a boundary or fault stops the run.")
        notes.append("Settling checks the voltage span across the complete recorded settling interval, then acquisition checks "
                     "the span again across its complete window. The minimum duration and complete-cycle count must both be met. "
                     "No thermal-equilibrium or dynamic response claim follows from these DC windows.")
    if recorded_method.get("voltage_efficiency_sweep"):
        sweep = recorded_method["voltage_efficiency_sweep"]
        current_inputs = {point.vin_target_V for point in plan.points}
        settings = "; ".join(f"{nominal:g} V nominal → {programmed:g} V programmed"
            for nominal, programmed in zip(sweep["nominal_input_voltages_V"], sweep["programmed_input_voltages_V"])
            if nominal in current_inputs)
        limit = sweep.get("input_current_limit_A")
        limit_text = f" The supply current setting remains {limit:.3f} A." if isinstance(limit, (int, float)) else ""
        notes.append("Input conditions in this run: " + settings + "." + limit_text
                     + " Source and load are verified OFF between input conditions.")
        notes.append("The policy requires a settling interval and at least an eight-second acquisition with five complete "
                     "reading cycles for a qualified load window. Increasing load stops for that input condition near the source-current boundary; "
                     "hard faults stop the whole run. These short DC observations do not establish thermal equilibrium.")
        for nominal, programmed in zip(sweep["nominal_input_voltages_V"], sweep["programmed_input_voltages_V"]):
            if programmed != nominal:
                notes.append(f"The {nominal:g} V condition is near {nominal:g} V ({programmed:g} V programmed), not an exact "
                             f"{nominal:.3f} V test. Its reduced setpoint leaves margin for the source's specified DC programming "
                             "error. Sampled voltage checks and the OVP setting do not establish a certified transient clamp. "
                             "Actual input-voltage readings are retained for every result.")
        if prior := sweep.get("prior_input_attempt"):
            prior_nominal = _finite_number(prior.get("nominal_input_V"))
            if prior_nominal is None:
                prior_nominal = _finite_number(next((p.get("nominal_input_V") for p in sweep.get("phases", [])
                                                     if p.get("status") == "previous-attempt-unqualified"), None))
            attempt = f"The {prior_nominal:g} V startup attempt" if prior_nominal is not None else "The earlier startup attempt"
            first = min(current_inputs) if current_inputs else None
            starts = f" This continuation starts at {first:g} V;" if first is not None else " This continuation"
            notes.append(f"{attempt} is preserved separately as run {prior['run_id']} "
                         f"(integrity manifest SHA-256 {prior['integrity_sha256']}). It produced no qualified efficiency window."
                         f"{starts} earlier readings are not combined with its results.")
    if recorded_method.get("source_limit_search"):
        search = recorded_method["source_limit_search"]
        inputs = sorted({point.vin_target_V for point in plan.points})
        limit = _finite_number(search.get("input_current_limit_A", recorded_method.get("source_current_limit_A")))
        supply = " / ".join(text for text in (
            _join_phrases([f"{value:g} V" for value in inputs]),
            f"{limit:.3f} A" if limit is not None else "") if text)
        sentence = "Adaptive source-limit test" + (f": the supply is set to {supply}." if supply else ".")
        coarse = _finite_number(recorded_method.get("coarse_output_step_A"))
        fine = _finite_number(recorded_method.get("fine_output_step_A"))
        threshold = _finite_number(recorded_method.get("fine_step_threshold_input_current_A"))
        if coarse is not None:
            sentence += f" Output demand increases in {coarse * 1000:g} mA steps"
            if fine is not None and threshold is not None:
                sentence += f", then {fine * 1000:g} mA steps after measured input current reaches {threshold:.2f} A"
            sentence += "."
        target = _finite_number(search.get("target_input_current_A"))
        stop = _finite_number(recorded_method.get("headroom_stop_input_current_A"))
        if target is not None:
            sentence += (f" The target is approximately {target:.2f} A input;"
                         + (f" {stop:.3f} A or" if stop is not None else "")
                         + " loss of source voltage regulation ends escalation.")
        notes.append(sentence)
        window = _finite_number(recorded_method.get("candidate_window_s"))
        endpoint = _finite_number(recorded_method.get("endpoint_window_s"))
        return_load = _finite_number(recorded_method.get("return_load_A"))
        parts = []
        if window is not None:
            parts.append(f"Candidate acquisition windows last at least {window:g} s.")
        if endpoint is not None:
            parts.append("If the initial window reaches the input-current target, that uninterrupted observation "
                         f"extends to {endpoint:g} s. The final mean can differ from its trigger mean.")
        if return_load is not None:
            parts.append(f"A separate {return_load * 1000:g} mA return observation is planned if safe; "
                         "shutdown takes priority after a hard fault.")
        parts.append("This is not a thermal-equilibrium test.")
        notes.append(" ".join(parts))
        planning_pct = plan.recipe.planning.efficiency_estimate_fraction * 100
        if planning_pct == 100:
            assumption = "The planning efficiency of 100% defines an ideal-power ceiling only."
        else:
            assumption = (f"The planning efficiency estimate of {planning_pct:g}% only bounds the conditional candidates; "
                          "it is a planning assumption, not a measured value.")
        notes.append(assumption + " Measured current controls advancement; it is not an assumed converter efficiency. "
                     "Conditional candidates not commanded by the adaptive search are not failed measurements.")
    if recorded_method.get("hold_settling"):
        notes.append(str(recorded_method["hold_settling"]) + f". The {plan.recipe.settling.minimum_dwell_s:g} s settling dwell applies to sweep steps; continuous hold bins do not restart it.")
    if recorded_method.get("sustained_load_actual_elapsed_s") is not None:
        notes.append(f"Recorded sustained-load duration: {recorded_method['sustained_load_actual_elapsed_s']:.3f} s.")
    if recorded_method.get("hardware_deadline_s") is not None and recorded_method.get("software_deadline_s") is not None:
        scope = " from each voltage phase start" if recorded_method.get("voltage_efficiency_sweep") or recorded_method.get("configured_dc_sweep") else ""
        notes.append(f"Independent source shutoff: {recorded_method['hardware_deadline_s']:g} s{scope}; "
                     f"software deadline: {recorded_method['software_deadline_s']:g} s for the complete run.")
    return ReportMethod(declared_acquisition=plan.recipe.acquisition.model_copy(deep=True),
        declared_settling=plan.recipe.settling.model_copy(deep=True),
        clock_mode=clock.get("mode"), clock_note=clock.get("note"), achieved_points=timings,
        procedure_notes=notes)


SEQUENCE_STAGES = {"increasing-load": "Increasing demand", "sustained-load": "Sustained load",
                   "decreasing-load": "Decreasing demand"}


def _accepted_point_times(points: list[dict], raw_samples: list[dict]) -> None:
    """Retain each valid window's recorded times without inventing sample times."""
    samples = {s["sample_id"]: s for s in raw_samples}
    timed = []
    for point in points:
        point.update(elapsed_s=None, elapsed_start_s=None, elapsed_end_s=None)
        ids = point.get("accepted_sample_ids", [])
        accepted = [samples[sid] for sid in ids if sid in samples]
        if point["qualification"] != "valid" or not accepted or len(accepted) != len(ids):
            continue
        if not all(isinstance(s.get(key), (int, float)) and not isinstance(s[key], bool)
                   and math.isfinite(s[key]) for s in accepted
                   for key in ("query_start_monotonic_s", "query_end_monotonic_s")):
            continue
        start = min(s["query_start_monotonic_s"] for s in accepted)
        end = max(s["query_end_monotonic_s"] for s in accepted)
        if end < start or any(s["query_end_monotonic_s"] < s["query_start_monotonic_s"] for s in accepted):
            continue
        timed.append((point, start, end))
    if timed:
        origin = min(start for _, start, _ in timed)
        for point, start, end in timed:
            point.update(elapsed_start_s=start - origin, elapsed_end_s=end - origin,
                         elapsed_s=(start + end) / 2 - origin)


def _sequence_annotations(points: list[dict], raw_samples: list[dict]) -> bool:
    """Annotate ramp/hold/return windows from retained accepted evidence."""
    if not {"increasing-load", "decreasing-load"} <= {p["test_id"] for p in points}:
        return False
    stage_counts: Counter = Counter()
    for point in points:
        stage = SEQUENCE_STAGES.get(point["test_id"])
        if not stage:
            continue
        stage_counts[point["test_id"]] += 1
        target = point["iout_target_A"]
        current = f"{target * 1000:g} mA" if abs(target) < 1 else f"{target:g} A"
        label = f"Hold bin {stage_counts[point['test_id']]}" if point["test_id"] == "sustained-load" else stage
        point.update(phase_label=stage, display_label=f"{label} · {current}")
    _accepted_point_times([p for p in points if p.get("phase_label")], raw_samples)
    return True


def _voltage_comparison(points: list[dict], sweep: dict) -> list[dict]:
    """Compare qualified windows at a common requested load; never interpolate."""
    rows = []
    phases = {p["nominal_input_V"]: p for p in sweep.get("phases", [])}
    # Older sweep records predate the recorded reference load; they were all run at 0.5 A.
    reference_load = sweep.get("reference_load_A", .5)
    for nominal, programmed in zip(sweep["nominal_input_voltages_V"], sweep["programmed_input_voltages_V"]):
        label = f"{nominal:g} V input" if nominal == programmed else f"{nominal:g} V nominal ({programmed:g} V set)"
        candidates = [p for p in points if p["vin_target_V"] == nominal]
        for point in candidates:
            target = point["iout_target_A"]
            current = f"{target * 1000:g} mA" if abs(target) < 1 else f"{target:g} A"
            point.update(input_condition_label=label, programmed_input_V=programmed,
                         display_label=f"{label} · {current}")
        valid = [p for p in candidates if p["qualification"] == "valid"]
        reference = [p for p in valid if p["iout_target_A"] == reference_load]
        # Repeated visits are separate observations, not silently averaged.
        ref = reference[0] if len(reference) == 1 else {}
        efficient = [p for p in valid if p.get("efficiency_pct") is not None]
        peak = max(efficient, key=lambda p: p["efficiency_pct"]) if efficient else {}
        highest = max(valid, key=lambda p: p["Iout_A"]) if valid else {}
        phase = phases.get(nominal, {})
        rows.append(dict(nominal_input_V=nominal, programmed_input_V=programmed, label=label,
            qualified_points=len(valid), reference_load_A=reference_load, reference_point_id=ref.get("point_id"),
            reference_measured_input_V=ref.get("Vin_V"), reference_efficiency_pct=ref.get("efficiency_pct"),
            highest_load_A=highest.get("Iout_A"), highest_load_point_id=highest.get("point_id"),
            peak_efficiency_pct=peak.get("efficiency_pct"), peak_efficiency_current_A=peak.get("Iout_A"),
            peak_efficiency_point_id=peak.get("point_id"), phase_status=phase.get("status", "not recorded"),
            stop_reason=phase.get("stop_reason")))
    return rows


def _sequence_results(points: list[dict], series: list[FigureSeries], label: str,
                      boundary: str) -> tuple[list[FigureSpec], list[MetricResult]]:
    timeline_series = [item.model_copy(update={"connect_points": True}) for item in series]
    hold_ids = {p["point_id"] for p in points if p["test_id"] == "sustained-load"}
    sequence_description = ("raises demand, holds it, then reduces it" if hold_ids else
                            "raises demand, then returns to a lower load")
    figures = [FigureSpec(id="fig-demand-time", title="Output Current vs Time",
        x_key="elapsed_s", y_key="Iout_A", x_label="Elapsed Time (s)",
        y_label="Output Current (A)", series=timeline_series,
        caption=f"{label}. {boundary}. The requested sequence {sequence_description}. "
        "Time is relative to the first accepted query. "
        "Each marker is a qualified bin mean placed at the midpoint of its accepted-query span. "
        "Dotted lines join stage boundaries; no extra samples. "
        "Lines guide the eye; they do not reconstruct switching edges or unmeasured intervals. "
        "Startup and settling samples remain in raw evidence.")]
    hold_series = [item for item in timeline_series if set(item.point_ids) & hold_ids]
    if hold_series:
        figures.append(FigureSpec(id="fig-hold-voltage", title="Output Voltage vs Time (Sustained Load)",
            x_key="elapsed_s", y_key="Vout_V", x_label="Elapsed Time (s)",
            y_label="Output Voltage (V)", series=hold_series,
            caption=f"{label}. Sustained-load bin means at their recorded query-span midpoints. "
            "Time is relative to the first accepted query of the run. "
            "The voltage axis is expanded to reveal small changes; hover for exact values. "
            "No temperature was measured, and a short hold does not establish thermal equilibrium."))
    hold = [p for p in points if p["point_id"] in hold_ids and p["qualification"] == "valid"
            and p.get("elapsed_s") is not None and p.get("Vout_V") is not None]
    metrics = []
    # A drift comparison is meaningful only at a common requested operating
    # condition, and only when both endpoint bins have retained timing evidence.
    if len(hold) >= 2 and len({(p["vin_target_V"], p["iout_target_A"]) for p in hold}) == 1:
        first, last = min(hold, key=lambda p: p["elapsed_s"]), max(hold, key=lambda p: p["elapsed_s"])
        interval = last["elapsed_s"] - first["elapsed_s"]
        if interval > 0:
            metrics.append(MetricResult(id="hold-voltage-change", label="Sustained-load voltage change",
                value=1000 * (last["Vout_V"] - first["Vout_V"]), unit="mV",
                formula="1000 * (last qualified hold-bin mean Vout - first qualified hold-bin mean Vout)",
                conditions=f"{first['vin_target_V']:g} V requested input, {first['iout_target_A']:g} A requested load; "
                           f"{interval:.3f} s between accepted-query midpoints",
                selector={"test_id": "sustained-load", "vin_target_V": first["vin_target_V"],
                          "iout_target_A": first["iout_target_A"]},
                point_ids=[first["point_id"], last["point_id"]], figure_ids=["fig-hold-voltage", "fig-demand-time"]))
    increasing = [p for p in points if p["test_id"] == "increasing-load"]
    decreasing = [p for p in points if p["test_id"] == "decreasing-load"]
    if increasing and decreasing:
        first, last = increasing[0], decreasing[-1]
        if (all(p["qualification"] == "valid" and p.get("elapsed_s") is not None
                and p.get("Vout_V") is not None for p in (first, last))
                and (first["vin_target_V"], first["iout_target_A"]) == (last["vin_target_V"], last["iout_target_A"])
                and last["elapsed_s"] > first["elapsed_s"]):
            metrics.append(MetricResult(id="return-voltage-change", label="Voltage change after returning to the starting load",
                value=1000 * (last["Vout_V"] - first["Vout_V"]), unit="mV",
                formula="1000 * (final decreasing-load mean Vout - first increasing-load mean Vout)",
                conditions=f"{first['vin_target_V']:g} V requested input, {first['iout_target_A']:g} A requested load; "
                           f"{last['elapsed_s'] - first['elapsed_s']:.3f} s between accepted-query midpoints",
                selector={"vin_target_V": first["vin_target_V"], "iout_target_A": first["iout_target_A"]},
                point_ids=[first["point_id"], last["point_id"]], figure_ids=["fig-voltage", "fig-demand-time"]))
    return figures, metrics


def build_report_model(plan: Plan, run: dict, analysis: dict, raw_samples: list[dict],
                       revision: str = "r0001") -> ReportModel:
    evidence_label = _evidence_label(plan, run)
    if analysis.get("evidence_label", evidence_label) != evidence_label:
        raise ValueError("Analysis evidence label does not match its acquisition")
    observation = "measured" if evidence_label == "MEASURED" else "synthetic"
    boundary = run.get("measurement_boundary", plan.bench.measurement_boundary)
    if analysis.get("boundary", boundary) != boundary:
        raise ValueError("Analysis measurement boundary does not match its acquisition")
    # Presentation annotations never mutate the preserved analysis evidence.
    points = copy.deepcopy(analysis["points"])
    sequence = _sequence_annotations(points, raw_samples)
    search = run.get("method", {}).get("source_limit_search")
    voltage_sweep = run.get("method", {}).get("voltage_efficiency_sweep")
    startup_descent = run.get("method", {}).get("startup_descent")
    comparison = _voltage_comparison(points, voltage_sweep) if voltage_sweep else []
    if voltage_sweep or startup_descent:
        _accepted_point_times(points, raw_samples)
    executed = run.get("executed_point_ids") if search or voltage_sweep or startup_descent else None
    if executed is not None:
        known_ids = {p["point_id"] for p in points}
        if (not isinstance(executed, list) or any(not isinstance(pid, str) for pid in executed)
                or len(set(executed)) != len(executed) or not set(executed) <= known_ids):
            raise ValueError("Recorded execution order contains duplicate or unknown point IDs")
        sampled_ids = {sample["point_id"] for sample in raw_samples}
        valid_ids = {p["point_id"] for p in points if p["qualification"] == "valid"}
        outcome_ids = {p["point_id"] for p in run.get("points", []) if p.get("qualification") != "not-run"}
        if not (sampled_ids | valid_ids | outcome_ids) <= set(executed):
            raise ValueError("Recorded execution order omits acquired point evidence")
        first_times = {}
        for sample in raw_samples:
            timestamp = sample.get("query_start_monotonic_s")
            if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and math.isfinite(timestamp):
                pid = sample["point_id"]
                first_times[pid] = min(first_times.get(pid, timestamp), timestamp)
        observed_order = sorted(first_times, key=first_times.get)
        if [pid for pid in executed if pid in first_times] != observed_order:
            raise ValueError("Recorded execution order contradicts raw query chronology")
        order = {pid: index for index, pid in enumerate(executed)}
        for point in points:
            point["execution_index"] = order.get(point["point_id"])
    valid = [p for p in points if p["qualification"] == "valid"]
    series = []
    for test in plan.recipe.tests:
        for index, vin in enumerate(dict.fromkeys(test.input_voltage_targets_V)):
            rows = [p for p in points if p["test_id"] == test.id and p["vin_target_V"] == vin]
            if executed is not None:
                rows = sorted((p for p in rows if p["point_id"] in order),
                              key=lambda p: order[p["point_id"]])
            phase = SEQUENCE_STAGES.get(test.id) if sequence else None
            condition_label = next((row["label"] for row in comparison if row["nominal_input_V"] == vin), f"{vin:g} V input")
            series.append(FigureSeries(id=f"{test.id}-v{index}",
                label=f"{phase} · {vin:g} V" if phase else condition_label, vin_target_V=vin,
                selection_key=f"{test.id}-v{index}" if sequence else None,
                connect_points=test.id != "sustained-load" if sequence else True,
                                       point_ids=[p["point_id"] for p in rows]))
    startup_phrase = load_phrase = start_text = descent_load_A = None
    if startup_descent:
        recorded = _recorded_conditions(startup_descent)
        start_V = recorded[0][0] if recorded else None
        descent_load_A = _finite_number(startup_descent.get("load_current_A"))
        start_text = f"{start_V:g} V" if start_V is not None else "the recorded startup voltage"
        startup_phrase = f"after {start_text} startup"
        load_phrase = f"{descent_load_A * 1000:g} mA load" if descent_load_A is not None else "recorded load"
        outcomes = {p["point_id"]: p for p in run["points"]}
        for point in points:
            programmed = outcomes[point["point_id"]].get("programmed_input_V")
            point["programmed_input_V"] = programmed
            point["input_condition_label"] = (f"{programmed:g} V set input {startup_phrase}"
                                               if programmed is not None else f"{point['vin_target_V']:g} V planned input")
        series = [FigureSeries(id="energized-descent", label=f"{load_phrase} · {startup_phrase}",
            vin_target_V=None, iout_target_A=descent_load_A, selection_key="energized-descent",
            point_ids=[p["point_id"] for p in points])]
    figures = []
    covered_inputs = sorted({p["vin_target_V"] for p in valid})
    if len(covered_inputs) == 1:
        input_caption = f" Requested input: {covered_inputs[0]:g} V."
    elif covered_inputs:
        input_caption = f" Acquired input-target range: {min(covered_inputs):g}–{max(covered_inputs):g} V."
    else:
        input_caption = " No requested input target produced a qualified point."
    if voltage_sweep:
        reduced = "; ".join(f"nominal {nominal:g} V was programmed to {setpoint:g} V"
                            for nominal, setpoint in _reduced_setpoints(voltage_sweep))
        sweep_limit = _finite_number(voltage_sweep.get("input_current_limit_A"))
        input_caption += " Colors identify input conditions" + (f"; {reduced}." if reduced else ".")
        input_caption += (f" Each curve ends at its acquired load range under the same {sweep_limit:g} A supply setting."
                          if sweep_limit is not None else " Each curve ends at its acquired load range.")
    metric_captions = {
        "efficiency_pct": "Efficiency = 100 × Pout/Pin across the declared boundary; powers use DC channel means. No-load efficiency is not evaluated.",
        "Vout_V": "Absolute output voltage at the load terminals versus output current shows load regulation. Percent deviation from nominal is reported separately; no dropout threshold was measured.",
        "loss_W": "Power loss = Pin − Pout across the declared boundary, including its wiring losses. No-load path loss is not evaluated.",
    }
    for ident, title, key, unit in [
        ("fig-efficiency", "Efficiency", "efficiency_pct", "Efficiency (%)"),
        ("fig-voltage", "Load Regulation", "Vout_V", "Output Voltage (V)"),
        ("fig-loss", "Power Loss", "loss_W", "Power Loss (W)")]:
        figures.append(FigureSpec(id=ident, title=title, x_key="Iout_A", y_key=key,
            x_label="Output Current (A)", y_label=unit, series=series,
            caption=f"{evidence_label}. {boundary}; markers are qualified DC operating-point means. "
            + metric_captions[key] + input_caption))
    if startup_descent:
        for figure in figures:
            figure.x_key, figure.x_label = "Vin_V", "Input Voltage (V)"
            reduced = "; ".join(f"nominal {nominal:g} V was programmed to {setpoint:g} V"
                                for nominal, setpoint in _reduced_setpoints(startup_descent))
            figure.caption = (f"{evidence_label}. {boundary}. Stepped input reduction after unloaded {start_text} startup "
                f"at a {load_phrase}. Markers are qualified DC means; startup and transition readings are excluded. "
                "The horizontal axis uses measured input" + (f"; {reduced}." if reduced else ".")
                + " No dropout, cold-start, or UVLO threshold was established.")
        figures[0], figures[1] = figures[1], figures[0]
        figures[0].title = "Output Voltage vs Input Voltage (Line Regulation)"
        figures[0].caption += " Absolute output voltage shows line regulation over the acquired input range at fixed load."
        figures.append(FigureSpec(id="fig-input-time", title="Input Voltage vs Time",
            x_key="elapsed_s", y_key="Vin_V", x_label="Elapsed Time (s)",
            y_label="Input Voltage (V)", series=series,
            caption=f"{evidence_label}. Qualified input-voltage window means in execution order. "
                "Time is relative to the first accepted query. "
                "The source stayed enabled between input settings. The preceding unloaded startup is retained in raw evidence."))
    metrics: list[MetricResult] = []
    efficiency = [p for p in valid if p["efficiency_pct"] is not None]
    if efficiency:
        peak = max(efficiency, key=lambda p: p["efficiency_pct"])
        metrics.append(MetricResult(id="highest-observed-efficiency", label="Highest observed path efficiency",
            value=peak["efficiency_pct"], unit="%", formula="100 * (mean(Vout)*mean(Iout))/(mean(Vin)*mean(Iin))",
            conditions=(f"{peak['phase_label']}; " if peak.get("phase_label") else "")
                       + peak.get("input_condition_label", f"{peak['vin_target_V']:g} V requested input")
                       + f", {peak['iout_target_A']:g} A requested load",
            selector={"point_id": peak["point_id"]}, point_ids=[peak["point_id"]], figure_ids=["fig-efficiency"]))
    nominal = plan.dut.ratings.output_voltage_nominal_V
    for test in plan.recipe.tests:
        for vin in dict.fromkeys(test.input_voltage_targets_V):
            rows = [p for p in valid if p["test_id"] == test.id and p["vin_target_V"] == vin]
            if len(rows) >= 2 and len({p["iout_target_A"] for p in rows}) >= 2:
                low, high = min(p["iout_target_A"] for p in rows), max(p["iout_target_A"] for p in rows)
                metrics.append(MetricResult(id=f"load-span-{test.id}-{vin:g}", label="Load regulation span",
                    value=regulation_span([p["Vout_V"] for p in rows], nominal), unit="% of nominal",
                    formula="100*(max(Vout)-min(Vout))/Vout_nominal",
                    conditions=(f"{SEQUENCE_STAGES[test.id]}; " if sequence and test.id in SEQUENCE_STAGES else "")
                               + rows[0].get("input_condition_label", f"{vin:g} V requested input")
                               + f"; covered load {low:g}–{high:g} A",
                    selector={"test_id": test.id, "vin_target_V": vin},
                    point_ids=[p["point_id"] for p in rows], figure_ids=["fig-voltage"]))
        vins = set(test.input_voltage_targets_V)
        for current in dict.fromkeys(test.output_current_targets_A):
            rows = [p for p in valid if p["test_id"] == test.id and p["iout_target_A"] == current]
            if len(vins) >= 2 and {p["vin_target_V"] for p in rows} == vins:
                metrics.append(MetricResult(id=f"line-span-{test.id}-{current:g}", label="Line regulation span on common valid grid",
                    value=regulation_span([p["Vout_V"] for p in rows], nominal), unit="% of nominal",
                    formula="100*(max(Vout)-min(Vout))/Vout_nominal",
                    conditions=f"{current:g} A requested load; covered input {min(vins):g}–{max(vins):g} V",
                    selector={"test_id": test.id, "iout_target_A": current},
                    point_ids=[p["point_id"] for p in rows], figure_ids=["fig-voltage"]))
                if startup_descent:
                    metrics[-1].conditions = (f"{current:g} A requested load; measured input "
                        f"{min(p['Vin_V'] for p in rows):.3f}–{max(p['Vin_V'] for p in rows):.3f} V {startup_phrase}")
    if sequence:
        sequence_figures, sequence_metrics = _sequence_results(points, series, evidence_label, boundary)
        figures = sequence_figures[:1] + figures + sequence_figures[1:]
        metrics.extend(sequence_metrics)
    if search or voltage_sweep:
        limit = (search or voltage_sweep)["input_current_limit_A"]
        figures.insert(1 if sequence or voltage_sweep else 0, FigureSpec(id="fig-source-current",
            title="Input Current",
            x_key="Iout_A", y_key="Iin_A", x_label="Output Current (A)",
            y_label="Input Current (A)", series=series,
            caption=f"{evidence_label}. Qualified settled DC means with the supply current setting at {limit:g} A. "
            "Only attempted observation windows form these curves. Unselected conditional candidates remain in the data. "
            "Current-limit or voltage-boundary observations do not qualify as nominal-input efficiency measurements."))
        supplied = [p for p in valid if isinstance(p.get("Iin_A"), (int, float))
                    and math.isfinite(p["Iin_A"])]
        if supplied:
            endpoint = max(supplied, key=lambda p: p["Iin_A"])
            metrics.append(MetricResult(id="highest-qualified-input-current", label="Highest qualified supply current",
                value=endpoint["Iin_A"], unit="A", formula="maximum qualified window mean Iin",
                conditions=f"{endpoint['Iout_A']:.4g} A measured output, {endpoint['Pout_W']:.4g} W output; "
                           + endpoint.get("input_condition_label", f"{endpoint['vin_target_V']:g} V requested input")
                           + f"; {limit:g} A supply setting",
                selector={"point_id": endpoint["point_id"]}, point_ids=[endpoint["point_id"]],
                figure_ids=["fig-source-current"]))
    for metric in metrics:
        metric.qualification = f"{observation} observation"
    summary = [f"{len(valid)} of {len(points)} requested operating points produced qualified {observation} DC results."]
    summary_evidence = []
    if startup_descent:
        summary.append(f"This run checks continued operation after starting at {start_text}: the source is kept on while "
                       f"input voltage decreases in steps, with a {load_phrase}. It does not test cold start at the lower input voltages.")
        if startup_descent.get("startup_status") == "stable-before-load":
            summary.append(f"Before the load was enabled, output passed the five-reading stability gate "
                           f"after {startup_descent['startup_elapsed_s']:.1f} s of observation at {start_text} input. "
                           "That observation time includes the stability check; it is not a measured startup delay.")
        else:
            summary.append("The recorded unloaded startup did not complete the stability gate; later conditions may remain untested.")
        if valid:
            lowest = min(valid, key=lambda p: p["Vin_V"])
            summary.append(f"Lowest qualified measured input was {lowest['Vin_V']:.3f} V, with "
                           f"{lowest['Vout_V']:.3f} V output at {lowest['Iout_A']*1000:.1f} mA. "
                           "This establishes continued operation only for the tested startup history and light load.")
    if sequence:
        inputs = sorted({p["vin_target_V"] for p in points})
        unique_conditions = len({(p["vin_target_V"], p["iout_target_A"]) for p in points})
        summary[0] = (f"{len(valid)} of {len(points)} requested observation windows produced qualified {observation} DC results. "
                      f"The grid contains {unique_conditions} distinct requested voltage/current conditions. "
                      + ("Repeated hold bins are separate observation windows." if any(p["test_id"] == "sustained-load" for p in points) else ""))
        input_description = ", ".join(f"{value:g} V" for value in inputs)
        middle = "holds the largest requested load, and " if any(p["test_id"] == "sustained-load" for p in points) else ""
        summary.append(f"The requested sequence uses {input_description} input while the electronic load increases demand, "
                       + middle + "reduces demand again. This checks output voltage and "
                       "power delivery over time at partial power; it does not measure temperature or qualify rated power.")
    if search:
        attempted = len(executed) if executed is not None else len({s["point_id"] for s in raw_samples})
        summary[0] = (f"{len(valid)} qualified {observation} observation windows from {attempted} attempted windows. "
                      f"The plan declared {len(points)} conditional candidates; unused candidates were not failed tests.")
        summary.append(f"The supply was configured for {search['input_current_limit_A']:g} A at the requested input voltage. "
                       f"The load increased toward {search['target_input_current_A']:g} A measured input current, "
                       f"with an output-request cap of {search['output_current_cap_A']:g} A. "
                       "A source-limited endpoint describes this bench's capability, not the converter's "
                       f"{plan.dut.ratings.output_current_rated_A:g} A rating.")
        if search.get("stop_reason"):
            summary.append("Ramp stop reason recorded by the worker: " + str(search["stop_reason"]) + ".")
        source_metric = next((m for m in metrics if m.id == "highest-qualified-input-current"), None)
        if source_metric:
            summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[source_metric.id]))
            summary.append(f"Highest qualified mean supply current: {source_metric.value:.4f} A at {source_metric.conditions}.")
    if voltage_sweep:
        attempted = len(executed) if executed is not None else len({s["point_id"] for s in raw_samples})
        summary[0] = (f"{len(valid)} qualified {observation} load windows from {attempted} attempted windows "
                      f"in a {len(points)}-point input-voltage comparison.")
        recorded = _recorded_conditions(voltage_sweep)
        phrases = {nominal: _condition_phrase(nominal, setpoint) for nominal, setpoint in recorded}
        requested = _join_phrases(list(phrases.values()))
        current_inputs = {point.vin_target_V for point in plan.points}
        sweep_limit = _finite_number(voltage_sweep.get("input_current_limit_A"))
        if prior := voltage_sweep.get("prior_input_attempt"):
            observed = prior.get("last_startup_cycle") or {}
            prior_nominal = _finite_number(prior.get("nominal_input_V"))
            if prior_nominal is None:
                prior_nominal = _finite_number(next((p.get("nominal_input_V") for p in voltage_sweep.get("phases", [])
                                                     if p.get("status") == "previous-attempt-unqualified"), None))
            attempt = (f"The separate {prior_nominal:g} V startup attempt" if prior_nominal is not None
                       else "The separate earlier startup attempt")
            cycle = ""
            if all(_finite_number(observed.get(key)) is not None for key in ("Vin_V", "Iin_A", "Vout_V")):
                cycle = (f": its last recorded cycle showed {observed['Vin_V']:.3f} V input at {observed['Iin_A']:.4f} A "
                         f"and {observed['Vout_V']:.3f} V output")
            continued = _join_phrases([phrase for nominal, phrase in phrases.items() if nominal in current_inputs])
            summary.append((f"The requested comparison covers {requested}. " if requested else "")
                           + f"{attempt} stopped without a qualified efficiency result{cycle}. The cause is not established. "
                           + (f"The curves below contain the qualified results from the {continued} continuation."
                              if continued else "The curves below contain the qualified results from the continuation."))
        else:
            summary.append(f"This test compares efficiency as output load increases at {requested} input." if requested
                           else "This test compares efficiency as output load increases at each recorded input condition.")
        summary.append("The common load points allow like-for-like comparisons; heavier loads are attempted where the same "
                       + (f"{sweep_limit:g} A supply limit allows them." if sweep_limit is not None else "supply limit allows them."))
        reduced_pairs = _reduced_setpoints(voltage_sweep)
        for nominal, setpoint in reduced_pairs:
            margin = ("below the stated operating limit" if setpoint < nominal and nominal >= plan.dut.ratings.input_voltage_max_V
                      else "for the source's specified programming error")
            summary.append(f"The {nominal:g} V input condition is labeled {nominal:g} V nominal and programmed to {setpoint:g} V "
                           f"to leave margin {margin}. The report uses actual measured input voltage in every power and "
                           "efficiency calculation.")
        if not reduced_pairs:
            summary.append("The report uses actual measured input voltage in every power and efficiency calculation.")
        summary.append("Short windows show settled DC behavior. Differences between voltage curves are observed differences; "
                       "their statistical significance and temperature dependence have not been established.")
    if metrics and metrics[0].id == "highest-observed-efficiency":
        m = metrics[0]
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[m.id]))
        summary.append(f"Highest observed path efficiency: {m.value:.2f}% at {m.conditions}.")
    line_metrics = [m for m in metrics if m.id.startswith("line-span-")]
    if line_metrics:
        m = max(line_metrics, key=lambda item: item.value)
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[m.id]))
        summary.append(f"Largest line regulation span: {m.value:.3f}% of nominal at {m.conditions}.")
    hold_drift = next((m for m in metrics if m.id == "hold-voltage-change"), None)
    if hold_drift:
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[hold_drift.id]))
        summary.append(f"During the sustained-load observation, output voltage changed by {hold_drift.value:+.3f} mV "
                       f"between the first and last qualified bin means ({hold_drift.conditions}). "
                       "This is an observed change, with measurement uncertainty unquantified; it is not proof of thermal equilibrium.")
    summary.append("Acceptance requirements are evaluated only where explicitly supplied; unset requirements are not evaluated.")
    returned = next((m for m in metrics if m.id == "return-voltage-change"), None)
    if returned:
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[returned.id]))
        summary.append(f"After returning to the starting load, voltage differed by {returned.value:+.3f} mV "
                       f"from its initial mean ({returned.conditions}). Uncertainty is unquantified; this single comparison does not establish hysteresis or statistical significance.")
    grouped: dict[str, list] = defaultdict(list)
    for sample in raw_samples:
        grouped[sample["point_id"]].append(sample)
    locations = "; ".join(f"{quantity}: {binding.location.replace('_', ' ')}"
                          for quantity, binding in plan.bench.measurements.items())
    limitations = [
        (f"MEASURED: these observations were acquired from the connected {plan.dut.identity.model}; scope is limited to this run."
         if evidence_label == "MEASURED" else
         f"SYNTHETIC: these observations come from a deterministic plant model, not the physical {plan.dut.identity.model}."),
        "DUT ratings were supplied by the owner and are not verified against the sample label.",
        f"Measurement locations — {locations}. The declared boundary is {boundary}; path loss is not solely module heat.",
        "Uncertainty is unquantified. No validated uncertainty bands or difference-resolution claims are provided.",
        "Topology, controller, isolation, calibration and protection behavior are unknown.",
        "No schematic, board photograph or temperature channels were supplied.",
        f"This DC grid does not by itself qualify the claimed {plan.dut.ratings.output_power_rated_W:g} W rating, ripple, transient or thermal behavior.",
        ("At qualified no-load points, input consumption is reported; output power, path loss and efficiency are not evaluated because load-off current readback can contain an offset."
         if any(p["qualification"] == "valid" and p["iout_target_A"] == 0 for p in points) else
         "No qualified no-load point was acquired; enabled no-load input consumption was not measured in this run."),
    ]
    provenance = {"formula_version": analysis["formula_version"],
                  "plan_hash": plan.plan_hash, "evidence_hash": analysis.get("evidence_hash"),
                  "software": run.get("software", {}), "data_source": run.get("data_source", "simulated"),
                  "operator_observations": run.get("operator_observations", []),
                  "attachment_descriptors": run.get("attachment_descriptors", []),
                  "publication": "local only; not approved for publication"}
    if evidence_label == "MEASURED":
        provenance["instrument_identities"] = run.get("instrument_identities", {})
        # Early supervised pilots predate SCPI-log integrity coverage. Their
        # original manifests remain untouched; disclose the narrower scope.
        limitations.append("The acquisition integrity manifest defines exactly which files are hashed. "
                           "Early pilot manifests do not include the supplementary scpi.jsonl transport log; "
                           "the raw measurement samples and run configuration are covered.")
    if evidence_label == "SYNTHETIC":
        provenance["mock_model"] = run.get("model", {})
        if run.get("clock", {}).get("mode") == "virtual":
            limitations.append("Virtual-clock timestamps represent simulated model time, not hardware acquisition times.")
    for note in run.get("metrology_limitations", []):
        limitations.append(str(note))
    return ReportModel(run_id=run["run_id"], analysis_id=analysis["analysis_id"], report_revision=revision,
        title=f"{plan.dut.identity.model} · DC–DC characterization", boundary=boundary,
        evidence_label=evidence_label,
        dut=plan.dut.model_dump(), bench=plan.bench.model_dump(),
        execution={"status": run.get("execution_status", "unknown"),
                   "shutdown": run.get("shutdown", {}), "scenario": run.get("scenario", "unknown"),
                   **({"source_limit_search": copy.deepcopy(search)} if search else {}),
                   **({"voltage_efficiency_sweep": copy.deepcopy(voltage_sweep), "voltage_comparison": comparison} if voltage_sweep else {}),
                   **({"startup_descent": copy.deepcopy(startup_descent)} if startup_descent else {}),
                   **({"executed_point_ids": list(executed)} if executed is not None else {})},
        coverage=analysis["coverage"], points=points, metrics=metrics, figures=figures,
        tables=[TableSpec(id="table-points", title="All requested operating points", columns=CSV_FIELDS,
                          point_ids=[p["point_id"] for p in points])],
        evidence=[EvidenceRef(point_ids=m.point_ids, figure_ids=m.figure_ids) for m in metrics],
        summary=summary, summary_evidence=summary_evidence,
        method=_report_method(plan, run, analysis, raw_samples),
        prose=[analysis["aggregation"], analysis["sign_convention"]],
        limitations=limitations, raw_samples=dict(grouped), provenance=provenance)


def analyze_run(run_dir: Path, *, version: str = FORMULA_VERSION) -> Path:
    run_dir = Path(run_dir)
    verify_integrity(run_dir)
    plan = Plan.model_validate_json((run_dir / "plan.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    samples = [json.loads(line) for line in (run_dir / "raw/samples.jsonl").read_text().splitlines() if line]
    evidence_hash = hashlib.sha256((run_dir / "integrity.json").read_bytes()).hexdigest()
    analysis_id = "a-" + hashlib.sha256((evidence_hash + version).encode()).hexdigest()[:12]
    analysis = analyze_evidence(plan, run, samples, version=version)
    analysis.update(analysis_id=analysis_id, evidence_hash=evidence_hash)
    for p in analysis["points"]:
        p["analysis_id"] = analysis_id
    directory = run_dir / "analysis" / analysis_id
    if directory.exists():
        if json.loads((directory / "analysis.json").read_text()) != analysis:
            raise ValueError("Existing analysis revision differs; change formula version")
        return directory
    directory.mkdir(parents=True)
    model = build_report_model(plan, run, analysis, samples)
    atomic_json(directory / "analysis.json", analysis)
    atomic_json(directory / "metrics.json", [m.model_dump() for m in model.metrics])
    atomic_json(directory / "uncertainty.json", analysis["uncertainty"])
    atomic_json(directory / "validation.json", {"status": "valid", "analysis_id": analysis_id,
        "checks": ["acquisition hashes", "raw sample schema", "accepted cycle completeness and skew", "report references"]})
    (directory / "points.csv").write_text(points_csv(analysis["points"]), encoding="utf-8", newline="")
    atomic_json(directory / "points.metadata.json", {"evidence_label": model.evidence_label, "run_id": run["run_id"],
        "analysis_id": analysis_id, "boundary": analysis["boundary"], "scope": "all requested points",
        "missing_values": "empty fields", "units": "Encoded in numeric column names; efficiency_pct is percent"})
    return directory
