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

from .domain import (PHASE_SCOPED_TEST_TYPES, SLOW_SUPPLY_RAMP_TEST_TYPE, SUPPLY_PROFILE_TEST_TYPES, UVLO_TEST_TYPE,
                     AcquisitionPolicy, Contract, Plan, RawSample, SettlingPolicy, staircase_level_kinds, uvlo_ramp_phases)
from .storage import atomic_json, verify_integrity
from .uncertainty import DERIVED as UNCERTAINTY_DERIVED, evaluate_run_budget, evaluated_quantity
from .thermal import annotate_thermal_points, thermal_report_contribution

FORMULA_VERSION = "settled-dc-1.4"
QUANTITIES = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")
# Enabled no-load (brief 9.1, plan Gap E): input consumption with the load input OFF.
NO_LOAD_METRIC_PREFIX = "enabled-no-load-input-consumption-"
# Brief 9.1: an efficiency above 100 % or a negative loss is preserved and flagged,
# never clamped. The flag names travel with the point into every export.
IMPLAUSIBLE_RATIO_FLAG = "implausible_power_ratio"
UNEXPECTED_SIGN_FLAG = "unexpected_sign"
# Pass-through checks (DUT topology "none ..."): differences between the two
# instruments' readbacks along the declared path. Not a calibration.
READBACK_METRIC_PREFIX = "readback-cross-check-"
READBACK_LABEL = "Readback cross-check (pass-through, not calibration)"
CSV_FIELDS = ["run_id", "analysis_id", "test_id", "point_id", "vin_target_V",
              "iout_target_A", *QUANTITIES, "Pin_W", "Pout_W", "loss_W",
              "efficiency_pct", "vout_error_pct", "qualification", "quality_flags", "reason"]


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


class SampleSeries(Contract):
    """Retained raw time series for one point and channel, plotted exactly as supplied."""
    id: str
    label: str
    point_id: str
    quantity: str
    sensor_id: str | None = None
    x: list[float] = Field(min_length=2)
    y: list[float] = Field(min_length=2)

    @model_validator(mode="after")
    def aligned(self) -> SampleSeries:
        if len(self.x) != len(self.y):
            raise ValueError("Sample series x and y lengths differ")
        if any(later < earlier for earlier, later in zip(self.x, self.x[1:])):
            raise ValueError("Sample series time must not decrease")
        return self


class FigureSpec(Contract):
    id: str
    title: str
    x_key: str
    y_key: str
    x_label: str
    y_label: str
    caption: str
    series: list[FigureSeries]
    # Band keys are set only when the readback budget evaluated the plotted quantity
    # (WEB-03 / UNC-02): absent keys mean no band is drawn anywhere.
    lower_key: str | None = None
    upper_key: str | None = None
    uncertainty_source: str | None = None
    sample_series: list[SampleSeries] = Field(default_factory=list)


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
    uncertainty: dict[str, Any] = Field(default_factory=lambda: {
        "status": "not_evaluated", "metrology": "unquantified", "evaluated_point_ids": [],
        "note": "No readback uncertainty budget was evaluated for this analysis; no bands or resolved-difference verdicts are shown."})
    thermal: dict[str, Any] | None = None

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
            for sample_series in figure.sample_series:
                if sample_series.point_id not in points:
                    raise ValueError(f"Missing figure point {sample_series.point_id}")
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
    # With the load input OFF, Iout is the load's zero-current readback offset of
    # either sign (evidence, not delivered output current), so its sign is exempt.
    if vin < 0 or iin < 0 or vout < 0 or (iout < 0 and not no_load):
        flags.append("unexpected_sign")
    if no_load:
        reason = "not applicable: enabled with no external load"
        # An electronic load can report a current offset while its input is
        # disabled. Preserve that reading, but do not turn it into delivered
        # output power or a converter/path loss estimate.
        result.update(Pout_W=None, loss_W=None)
        result["output_power_reason"] = "not evaluated: no external load; load-off current is not delivered output current"
        result["loss_reason"] = ("not evaluated: output power is unavailable with no external load; the input consumption "
                                 "is a path quantity at the declared boundary and is not attributed to the module alone")
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


def uvlo_ramp_brackets(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn-off, turn-on and hysteresis brackets from ordered ramp steps; never an exact threshold.

    ``steps`` are the declared steps in execution order, each with
    ``ramp_phase`` (``down``/``up``), ``vin_target_V``, ``point_id`` and
    ``output_state`` (``on``, ``off``, ``indeterminate``, or None when the step
    has no accepted mean). Descending bracket: last ``on`` step to first
    ``off`` step. Ascending bracket (from the turnaround): last ``off`` step
    to first ``on`` step. Hysteresis: the difference of the two brackets,
    bound by bound. Unqualified or indeterminate steps inside a bracket widen
    it and are listed; nothing is interpolated. DATA-04 convention.
    """
    result: dict[str, Any] = {"turn_off": None, "turn_on": None, "hysteresis": None, "exact_threshold_V": None,
        "convention": {
            "turn_off": "descending ramp: output on at the upper bound, off at the lower bound; the threshold lies within that step and is unresolved",
            "turn_on": "ascending ramp: output off at the lower bound, on at the upper bound; the threshold lies within that step and is unresolved",
            "hysteresis": "turn-on bracket minus turn-off bracket, bound by bound (lower = turn-on lower − turn-off upper; "
                          "upper = turn-on upper − turn-off lower); a step-limited interval, not a measured value"},
        "notes": []}
    down = [step for step in steps if step["ramp_phase"] == "down"]
    up = steps[len(down) - 1:] if down else []
    if not down or len(up) < 2:
        result["notes"].append("ramp steps do not form a descending and ascending sequence")
        return result
    first_off = next((i for i, step in enumerate(down) if step["output_state"] == "off"), None)
    if first_off is None:
        result["notes"].append(f"no output-off step was observed on the descending ramp down to "
                               f"{down[-1]['vin_target_V']:g} V; turn-off is not bracketed")
    else:
        last_on = next((i for i in range(first_off - 1, -1, -1) if down[i]["output_state"] == "on"), None)
        if last_on is None:
            result["notes"].append("the output was not observed on before its first off step; turn-off is not bracketed")
        else:
            result["turn_off"] = {**transition_bracket(down[last_on]["vin_target_V"], down[first_off]["vin_target_V"]),
                "direction": "descending", "last_on_point_id": down[last_on]["point_id"],
                "first_off_point_id": down[first_off]["point_id"],
                "unresolved_steps_inside": [step["point_id"] for step in down[last_on + 1:first_off]]}
    first_off_up = next((i for i, step in enumerate(up) if step["output_state"] == "off"), None)
    if first_off_up is None:
        result["notes"].append("no output-off step at or after the turnaround; turn-on is not bracketed")
    else:
        first_on = next((i for i in range(first_off_up + 1, len(up)) if up[i]["output_state"] == "on"), None)
        if first_on is None:
            result["notes"].append(f"the output had not returned by the final ascending step "
                                   f"{up[-1]['vin_target_V']:g} V; turn-on is not bracketed")
        else:
            last_off = max(i for i in range(first_off_up, first_on) if up[i]["output_state"] == "off")
            result["turn_on"] = {**transition_bracket(up[first_on]["vin_target_V"], up[last_off]["vin_target_V"]),
                "direction": "ascending", "last_off_point_id": up[last_off]["point_id"],
                "first_on_point_id": up[first_on]["point_id"],
                "unresolved_steps_inside": [step["point_id"] for step in up[last_off + 1:first_on]]}
    if result["turn_off"] and result["turn_on"]:
        off, on = result["turn_off"], result["turn_on"]
        lower, upper = on["lower_V"] - off["upper_V"], on["upper_V"] - off["lower_V"]
        result["hysteresis"] = {"lower_V": lower, "upper_V": upper, "exact_V": None}
        if lower <= 0:
            result["notes"].append("hysteresis is not resolved by the declared step size (its lower bound is not positive)")
    return result


def _safe_cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        # Flag lists become one semicolon-joined text cell (the interactive
        # export joins the same way, so the two CSV files stay byte-identical).
        value = ";".join(str(item) for item in value)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return "" if value is None else value


def flag_reason(values: dict[str, Any], derived: dict[str, Any], flags: list[str]) -> str:
    """Computed statement for a point demoted by metric flags. Quotes the readings; adjusts nothing."""
    vin, iin, vout, iout = (values.get(q) for q in QUANTITIES)
    finite = {q: _finite_number(values.get(q)) for q in QUANTITIES}
    parts = []
    eta, pin, pout = (_finite_number(derived.get(k)) for k in ("efficiency_pct", "Pin_W", "Pout_W"))
    if IMPLAUSIBLE_RATIO_FLAG in flags and eta is not None and pin is not None and pout is not None:
        if eta > 100:
            parts.append(f"Implausible power ratio: computed efficiency {eta:.1f} % exceeds 100 % "
                         f"(output power {pout:.3f} W > input power {pin:.3f} W); readings preserved, point not qualified.")
        else:
            parts.append(f"Implausible power ratio: computed efficiency {eta:.1f} % is below 0 % "
                         f"(output power {pout:.3f} W with input power {pin:.3f} W); readings preserved, point not qualified.")
        if finite["Iin_A"] is not None and finite["Iout_A"] is not None:
            parts.append(f"Input and output current readbacks differ by {1000 * (iout - iin):+.1f} mA.")
    if "nonpositive_input_power" in flags and pin is not None:
        parts.append(f"Nonpositive input power ({pin:.4g} W): efficiency suppressed; readings preserved, point not qualified.")
    if UNEXPECTED_SIGN_FLAG in flags:
        negative = [f"{q} = {finite[q]:.6g}" for q in QUANTITIES if finite[q] is not None and finite[q] < 0]
        parts.append("Unexpected sign: " + (", ".join(negative) if negative else "a negative channel mean")
                     + " at a loaded point; readings preserved, point not qualified.")
    if not parts:
        parts.append("Metric flags " + ", ".join(flags) + ": readings preserved, point not qualified.")
    return " ".join(parts)


def is_flagged_implausible(point: dict[str, Any]) -> bool:
    """A demoted point whose readings give output power above input power (or a negative ratio)."""
    return point.get("qualification") == "inconclusive" and IMPLAUSIBLE_RATIO_FLAG in (point.get("quality_flags") or [])


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
    # The bench decides real vs simulated; a legacy recipe execution_mode is planning metadata.
    if plan.bench.mode != expected_mode:
        raise ValueError("Acquisition data_source does not match the bench execution mode")
    if "real_hardware_opened" in run and run["real_hardware_opened"] is not (source == "measured"):
        raise ValueError("Acquisition data_source disagrees with real_hardware_opened")
    if source == "measured" and run.get("clock", {}).get("mode") == "virtual":
        raise ValueError("Measured acquisition cannot use a virtual clock")
    return "MEASURED" if source == "measured" else "SYNTHETIC"


def _uvlo_analysis(plan: Plan, run: dict, points: list[dict]) -> dict[str, Any]:
    """Recompute each UVLO step's output state from accepted means; bracket transitions per test.

    Off/indeterminate steps are recorded states, not efficiency points, and
    carry no output power or loss either. A non-on state outside the declared
    expected-off phase is reclassified as inconclusive here regardless of what
    the worker claimed, and a worker output-state claim that disagrees with the
    accepted mean is rejected. The state is classified from the accepted mean
    alone; metric flags never demote an off step (a 0 V / 0 A readback commonly
    reads a few counts negative), only an operating step.
    """
    outcomes = {p["point_id"]: p for p in run.get("points", [])}
    by_point = {p["point_id"]: p for p in points}
    result: dict[str, Any] = {}
    for test in plan.recipe.tests:
        if test.type != UVLO_TEST_TYPE or test.uvlo is None:
            continue
        phases = uvlo_ramp_phases(test.input_voltage_targets_V)
        requests = [p for p in plan.points if p.test_id == test.id]
        if [p.vin_target_V for p in requests] != list(test.input_voltage_targets_V):
            raise ValueError("UVLO plan points do not match the declared ramp steps")
        steps = []
        for request, phase in zip(requests, phases):
            point = by_point[request.point_id]
            state = test.uvlo.classify_output(point["Vout_V"]) if point["qualification"] == "valid" else None
            if point["qualification"] == "valid" and state is None:
                raise ValueError(f"Valid UVLO step {request.point_id} has no accepted Vout mean to classify")
            recorded = outcomes.get(request.point_id, {}).get("output_state")
            if state is not None and recorded is not None and recorded != state:
                raise ValueError(f"Worker recorded output state {recorded!r} for {request.point_id}; "
                                 f"the accepted Vout mean classifies as {state!r}")
            off_expected = test.uvlo.off_expected(request.vin_target_V, phase)
            point.update(ramp_phase=phase, output_state=state, output_off_expected=off_expected,
                         minimum_vout_rule_applied=not off_expected)
            if state == "on" and point.get("metric_flags"):
                # An operating step is an efficiency point: the generic metric-flag
                # demotion (skipped for UVLO steps in analyze_evidence) applies here.
                point.update(qualification="inconclusive", quality_flags=list(point["metric_flags"]),
                             reason=flag_reason(point, point, list(point["metric_flags"])))
                point["requirements"].update(output_voltage="not-evaluated", efficiency="not-evaluated")
            if state is not None and state != "on":
                point.update(efficiency_pct=None,
                             efficiency_reason=f"output {state}: recorded UVLO ramp state, not an efficiency point",
                             Pout_W=None, loss_W=None,
                             output_power_reason=f"not evaluated: output {state}; a standby reading is not delivered output power",
                             loss_reason=f"not evaluated: output {state}; output power is not applicable to a recorded ramp state")
                point["requirements"].update(output_voltage="not-applicable", efficiency="not-applicable")
                if not off_expected:
                    point.update(qualification="inconclusive",
                                 reason=f"output {state} outside the declared expected-off phase; cause unclassified")
            steps.append({"point_id": request.point_id, "vin_target_V": request.vin_target_V, "ramp_phase": phase,
                          "output_state": state, "qualification": point["qualification"]})
        result[test.id] = {"policy": test.uvlo.model_dump(), "load_A": test.output_current_targets_A[0],
                           "steps": steps, **uvlo_ramp_brackets(steps)}
    return result


SUPPLY_PROFILE_LABELS = {SLOW_SUPPLY_RAMP_TEST_TYPE: "slow supply ramp (clause 4.5 profile)",
                         "reset_staircase": "reset staircase (clause 4.6.2 profile)"}
SUPPLY_PROFILE_CADENCE = ("levels are commanded as bounded DC steps at the ~1 s command cadence; the source's own slew "
                          "between steps is not characterised and no edge, drop or transient is measured")


def level_observation(level_kind: str, state: str | None, previous_state: str | None, off_expected: bool) -> str:
    """One computed phrase per supply-profile level: in band / reset / recovered / not recovered, from classified states only."""
    if state is None:
        return "no qualified observation"
    if state == "indeterminate":
        return "output indeterminate (between the off ceiling and the on floor)"
    if state == "on":
        return "recovered: output back in band" if previous_state in ("off", "indeterminate") else "output in band"
    if level_kind == "recovery":
        phrase = "not recovered: output off at a recovery level"
    elif level_kind == "up":
        phrase = "output still off on the increase"
    else:
        phrase = "reset: output off"
    return phrase + (" (documented expectation below the declared boundary)" if off_expected
                     else " where the policy expects it on; cause unclassified")


def _state_runs(levels: list[dict[str, Any]]) -> list[tuple[str | None, float, float]]:
    """Consecutive levels with the same classified state as (state, first V, last V)."""
    runs: list[tuple[str | None, float, float]] = []
    for level in levels:
        state, vin = level["output_state"], level["vin_target_V"]
        if runs and runs[-1][0] == state:
            runs[-1] = (state, runs[-1][1], vin)
        else:
            runs.append((state, vin, vin))
    return runs


def _describe_run(state: str | None, first: float, last: float) -> str:
    words = {"on": "in band", "off": "off (reset)", "indeterminate": "indeterminate", None: "not qualified"}[state]
    return f"{words} at {first:g} V" if first == last else f"{words} from {first:g} V to {last:g} V"


def supply_profile_statements(test_type: str, levels: list[dict[str, Any]], policy: dict[str, Any],
                              stop: dict[str, Any] | None, *, synthetic: bool) -> list[str]:
    """Plain sentences computed from the classified levels; nothing here is inferred beyond the recorded states."""
    prefix = "Synthetic plant: " if synthetic else ""
    statements = []
    if test_type == SLOW_SUPPLY_RAMP_TEST_TYPE:
        down = [level for level in levels if level["level_kind"] == "down"]
        up = [level for level in levels if level["level_kind"] == "up"]
        if down:
            statements.append(prefix + f"decreasing from {down[0]['vin_target_V']:g} V, the output was "
                              + "; ".join(_describe_run(*run) for run in _state_runs(down)) + ".")
        if up:
            statements.append(f"Increasing to {up[-1]['vin_target_V']:g} V, the output was "
                              + "; ".join(_describe_run(*run) for run in _state_runs(up)) + ".")
        recovered = next((level for level in up if level["observation"].startswith("recovered")), None)
        if recovered:
            statements.append(f"The output was back in band at {recovered['vin_target_V']:g} V on the increase "
                              "(the first qualified in-band level after an off level; the return lies between it and the previous level).")
        elif any(level["output_state"] == "off" for level in down) and up:
            statements.append("The output had not returned by the last increasing level.")
        rate, step, interval = policy.get("ramp_rate_V_per_min"), policy.get("step_V"), policy.get("step_interval_s")
        if step is not None and interval is not None:
            rate = rate if rate is not None else step / interval * 60
            statements.append(f"Levels were reached in {step * 1000:g} mV live steps held {interval:g} s ({rate:g} V/min); "
                              f"{SUPPLY_PROFILE_CADENCE}; states are established at the {len(levels)} observation levels only.")
    else:
        lows = [level for level in levels if level["level_kind"] == "low"]
        recoveries = [level for level in levels if level["level_kind"] == "recovery"]
        in_band = [level["vin_target_V"] for level in lows if level["output_state"] == "on"]
        reset = [level["vin_target_V"] for level in lows if level["output_state"] == "off"]
        unqualified = [level["vin_target_V"] for level in lows if level["output_state"] is None]
        parts = []
        if in_band:
            parts.append("in band at the " + ", ".join(f"{v:g} V" for v in in_band) + (" low" if len(in_band) == 1 else " lows"))
        if reset:
            parts.append("off (reset) at the " + ", ".join(f"{v:g} V" for v in reset) + (" low" if len(reset) == 1 else " lows"))
        if unqualified:
            parts.append("not qualified at " + ", ".join(f"{v:g} V" for v in unqualified))
        statements.append(prefix + "at the low levels the output was " + ("; ".join(parts) if parts else "not qualified") + ".")
        judged = [level for level in recoveries[1:] if level["output_state"] is not None]
        back = [level for level in judged if level["output_state"] == "on"]
        failed = [level for level in judged if level["output_state"] != "on"]
        if recoveries:
            text = f"At the {recoveries[0]['vin_target_V']:g} V recovery level after a low the output was back in band {len(back)} of {len(judged)} times"
            if failed:
                text += "; it was " + ", ".join(f"{level['output_state']} after the {lows[index]['vin_target_V']:g} V low"
                                                 for index, level in ((recoveries.index(f) - 1, f) for f in failed) if 0 <= index < len(lows))
            statements.append(text + ".")
        low_hold, recovery_hold = policy.get("low_hold_s"), policy.get("recovery_hold_s")
        if low_hold is not None:
            statements.append(f"Each low was held {low_hold:g} s and each recovery {recovery_hold:g} s before acquisition; "
                              f"{SUPPLY_PROFILE_CADENCE}.")
    lowest = min(level["vin_target_V"] for level in levels)
    statements.append(f"The lowest requested level was {lowest:g} V; the standard's profile continues to 0 V, which is not a "
                      "positive source setpoint on this bench.")
    if stop and any(level["point_id"] == stop.get("point_id") for level in levels):
        level = next(level for level in levels if level["point_id"] == stop["point_id"])
        statements.append(f"The run stopped at the {level['vin_target_V']:g} V {level['level_kind']} level "
                          f"({stop.get('classification')}): {stop.get('reason')}. Later levels were not run.")
    return statements


def _supply_profile_analysis(plan: Plan, run: dict, points: list[dict]) -> dict[str, Any]:
    """Recompute each ISO 16750-2 supply-profile level's state from accepted means; state per level what was observed.

    Same rules as the UVLO ramp: off/indeterminate levels are recorded states,
    not efficiency points; an off level where the policy expects the output on
    is inconclusive; a worker claim that disagrees with the accepted mean is
    rejected. The per-level statement (in band / reset / recovered / not
    recovered) is computed here from the classified states and labelled as the
    synthetic plant when the run is simulated.
    """
    outcomes = {p["point_id"]: p for p in run.get("points", [])}
    by_point = {p["point_id"]: p for p in points}
    method = (run.get("method") or {}).get("supply_profile") or {}
    synthetic = run.get("data_source", "simulated") == "simulated"
    result: dict[str, Any] = {}
    for test in plan.recipe.tests:
        if test.type not in SUPPLY_PROFILE_TEST_TYPES or test.supply_profile is None:
            continue
        policy = test.supply_profile
        kinds = (uvlo_ramp_phases(test.input_voltage_targets_V) if test.type == SLOW_SUPPLY_RAMP_TEST_TYPE
                 else staircase_level_kinds(test.input_voltage_targets_V))
        requests = [p for p in plan.points if p.test_id == test.id]
        if [p.vin_target_V for p in requests] != list(test.input_voltage_targets_V):
            raise ValueError("Supply-profile plan points do not match the declared levels")
        levels, previous = [], None
        for request, kind in zip(requests, kinds):
            point = by_point[request.point_id]
            state = policy.classify_output(point["Vout_V"]) if point["qualification"] == "valid" else None
            if point["qualification"] == "valid" and state is None:
                raise ValueError(f"Valid supply-profile level {request.point_id} has no accepted Vout mean to classify")
            recorded = outcomes.get(request.point_id, {}).get("output_state")
            if state is not None and recorded is not None and recorded != state:
                raise ValueError(f"Worker recorded output state {recorded!r} for {request.point_id}; "
                                 f"the accepted Vout mean classifies as {state!r}")
            off_expected = policy.off_expected(request.vin_target_V, kind)
            point.update(level_kind=kind, ramp_phase=kind if kind in ("down", "up") else None, output_state=state,
                         output_off_expected=off_expected, minimum_vout_rule_applied=not off_expected)
            if state == "on" and point.get("metric_flags"):
                point.update(qualification="inconclusive", quality_flags=list(point["metric_flags"]),
                             reason=flag_reason(point, point, list(point["metric_flags"])))
                point["requirements"].update(output_voltage="not-evaluated", efficiency="not-evaluated")
            if state is not None and state != "on":
                point.update(efficiency_pct=None,
                             efficiency_reason=f"output {state}: recorded supply-profile state, not an efficiency point",
                             Pout_W=None, loss_W=None,
                             output_power_reason=f"not evaluated: output {state}; a standby reading is not delivered output power",
                             loss_reason=f"not evaluated: output {state}; output power is not applicable to a recorded profile state")
                point["requirements"].update(output_voltage="not-applicable", efficiency="not-applicable")
                if not off_expected:
                    point.update(qualification="inconclusive",
                                 reason=f"output {state} at a level where the declared policy expects it on; cause unclassified")
            observation = level_observation(kind, state, previous, off_expected)
            if state == "on" and point["requirements"].get("output_voltage") == "fail":
                observation = (f"output on but outside the ±{plan.dut.acceptance.output_voltage_tolerance_pct:g} % acceptance band"
                               + (" (after an off level)" if previous in ("off", "indeterminate") else ""))
            point["level_observation"] = observation
            levels.append({"point_id": request.point_id, "vin_target_V": request.vin_target_V, "level_kind": kind,
                           "ramp_phase": point["ramp_phase"], "output_state": state, "output_off_expected": off_expected,
                           "observation": observation, "qualification": point["qualification"]})
            if state is not None:
                previous = state
        detail: dict[str, Any] = {"type": test.type, "label": SUPPLY_PROFILE_LABELS.get(test.type, test.type),
                                  "clause": plan.recipe.standard_clause, "policy": policy.model_dump(),
                                  "load_A": test.output_current_targets_A[0], "levels": levels,
                                  "cadence": method.get("cadence"), "synthetic": synthetic}
        if test.type == SLOW_SUPPLY_RAMP_TEST_TYPE:
            detail.update(uvlo_ramp_brackets(levels))
            detail["bracket_note"] = ("brackets lie between adjacent observation levels; the live steps between them were "
                                      "guarded, not qualified")
        policy_dump = {**policy.model_dump(), "ramp_rate_V_per_min": policy.ramp_rate_V_per_min}
        detail["statements"] = supply_profile_statements(test.type, levels, policy_dump, run.get("stop"), synthetic=synthetic)
        result[test.id] = detail
    return result


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
    # UVLO steps and supply-profile levels are classified from the accepted Vout mean first.
    uvlo_tests = {t.id for t in plan.recipe.tests if t.type in PHASE_SCOPED_TEST_TYPES}
    points = []
    accepted_values: dict[str, dict[str, list[float]]] = {}
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
        accepted_values[request.point_id] = {q: [s["value"] for s in accepted if s["quantity"] == q] for q in QUANTITIES}
        derived = dc_metrics(values, plan.dut.ratings.output_voltage_nominal_V,
                             no_load=request.iout_target_A == 0)
        # The worker's reason stands unless the analysis demotes the point; then
        # the reason states what was computed (brief 9.1) and the flags that did it.
        reason = outcome.get("reason", request.reason)
        quality_flags: list[str] = []
        if qualification != "valid":
            derived.update(efficiency_pct=None, efficiency_reason=f"point {qualification}")
        elif derived["metric_flags"] and request.test_id not in uvlo_tests:
            # UVLO steps are classified from the accepted Vout mean first
            # (_uvlo_analysis); a near-zero, slightly negative off-state readback
            # must not demote a recorded off step. Operating steps are demoted there.
            qualification = "inconclusive"
            quality_flags = list(derived["metric_flags"])
            reason = flag_reason(values, derived, quality_flags)
        no_load = request.iout_target_A == 0
        load_states = {s["acquisition_settings"].get("load_enabled") for s in accepted}
        readbacks = {s["acquisition_settings"].get("load_input_readback") for s in accepted}
        if no_load and qualification == "valid" and (True in load_states or True in readbacks):
            raise ValueError("Worker accepted an enabled no-load point with the load input enabled")
        # Enabled no-load (brief 9.1, plan Gap E): the measurand is input consumption
        # with the load input OFF; the load's current readback is kept as an offset,
        # never as delivered output current.
        observation = {"observation": "enabled_no_load" if no_load else "loaded",
                       "load_input_state": ("not recorded" if not load_states or load_states == {None}
                                            else "OFF" if load_states == {False} else "ON" if load_states == {True}
                                            else "mixed"),
                       "load_readback_offset_A": values["Iout_A"] if no_load else None,
                       "enabled_no_load_consumption_W": derived["Pin_W"] if no_load and qualification == "valid" else None}
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
        points.append({**request.model_dump(), **values, **derived, **observation,
                       "run_id": run["run_id"], "test_id": request.test_id,
                       "qualification": qualification, "quality_flags": quality_flags, "reason": reason,
                       "requirements": requirements, "metrology": "unquantified",
                       "accepted_cycle_count": len(by_cycle),
                       "accepted_sample_ids": [s["sample_id"] for s in accepted],
                       "acquisition_cycle_ids": sorted(cycles)})
    # UVLO steps are classified first so expected-off steps carry no efficiency
    # before the budget is evaluated on the final point set.
    uvlo = _uvlo_analysis(plan, run, points) if any(t.type == UVLO_TEST_TYPE for t in plan.recipe.tests) else None
    profiles = (_supply_profile_analysis(plan, run, points)
                if any(t.type in SUPPLY_PROFILE_TEST_TYPES for t in plan.recipe.tests) else None)
    annotate_thermal_points(plan, run, grouped, points)
    # Structured readback budget (section 9.2). Unknown terms yield not_evaluated
    # reasons, never zeros; the per-point qualification state follows the budget.
    budget = evaluate_run_budget(plan, points, accepted_values, evidence_label=evidence_label,
                                 observed_conditions={"ambient_temperature_C": run.get("ambient_temperature_C")})
    for p in points:
        p["metrology"] = budget["points"][p["point_id"]]["metrology"]
    return {"schema_version": "1.0", "formula_version": version,
            "aggregation": "Metrics from qualified channel means over accepted complete acquisition cycles",
            "sign_convention": "Positive power enters input boundary and leaves output boundary; no absolute-value correction",
            "run_id": run["run_id"], "evidence_label": evidence_label,
            "boundary": run.get("measurement_boundary", plan.bench.measurement_boundary),
            "points": points, "coverage": coverage_by_test(points),
            "uncertainty": budget,
            **({"uvlo_input_ramp": uvlo} if uvlo else {}),
            **({"supply_profiles": profiles} if profiles else {})}


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
    if plan.recipe.title:
        notes.append(f"Recipe: {plan.recipe.title}.")
    if plan.recipe.standard_clause:
        notes.append(f"Referenced clause: {plan.recipe.standard_clause}. A clause reference identifies the source of "
                     "the selected test conditions; it does not establish standards compliance.")
    if plan.recipe.description:
        notes.append(f"Declared recipe scope: {plan.recipe.description}")
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
    if recorded_method.get("uvlo_input_ramp"):
        notes.append("Approved UVLO input ramp: the source stays on while the input steps down to the declared floor and back "
                     f"up at a fixed light load; each step waits the {plan.recipe.settling.minimum_dwell_s:g} s dwell before "
                     "acquisition. The normal minimum-output and load-established rules apply only where output-off is not "
                     "expected (descending steps at or above the expected-off boundary, ascending steps at or above the "
                     "expected-on boundary); elsewhere output-off is recorded, not faulted. Absolute input-current, "
                     "voltage and output-current limits apply at every step.")
        if recorded_method["uvlo_input_ramp"].get("synthetic_model"):
            notes.append("The synthetic plant's UVLO threshold, hysteresis and standby draw are simulation parameters, "
                         "not characteristics of the DUT.")
    if recorded_method.get("supply_profile"):
        profile = recorded_method["supply_profile"]
        cadence = profile.get("cadence") or {}
        label = SUPPLY_PROFILE_LABELS.get(profile.get("type"), str(profile.get("type")))
        notes.append(f"ISO 16750-2 {label} run as bounded DC steps: {SUPPLY_PROFILE_CADENCE}. The source stays on from the "
                     "first level to the last at a fixed light load.")
        if profile.get("type") == SLOW_SUPPLY_RAMP_TEST_TYPE and cadence.get("live_step_V") is not None:
            rate = cadence.get("rate_V_per_min")
            notes.append(f"The {rate:g} V/min rate is realised as {cadence['live_step_V'] * 1000:g} mV live steps every "
                         f"{cadence['live_step_interval_s']:g} s: a staircase, not a linear ramp. Readings between observation "
                         "levels are guarded and preserved as raw samples but are not qualified points; each observation level "
                         f"waits the {plan.recipe.settling.minimum_dwell_s:g} s dwell before acquisition.")
        elif cadence.get("low_hold_s") is not None:
            notes.append(f"Each low level is held {cadence['low_hold_s']:g} s and each recovery level "
                         f"{cadence['recovery_hold_s']:g} s before acquisition.")
        notes.append("The normal minimum-output and load-established rules apply only where output-off is not expected "
                     "(descending or low levels at or above the expected-off boundary, ascending or recovery levels at or above "
                     "the expected-on boundary); elsewhere output-off is recorded, not faulted. Absolute input-current, voltage "
                     "and output-current limits apply at every level and every live step.")
        if profile.get("synthetic_model"):
            notes.append("The synthetic plant's UVLO threshold, hysteresis and standby draw are simulation parameters, "
                         "not characteristics of the DUT; every statement about reset and recovery describes the mock plant.")
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


def _blocking_summary(budget: Any) -> str:
    """One clause per channel whose readback specification blocks evaluation."""
    if not isinstance(budget, dict):
        return ""
    clauses = []
    for review in budget.get("channels", {}).values():
        reasons = review.get("reasons", []) if isinstance(review, dict) else []
        if reasons:
            clauses.append(str(reasons[0]) + (f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""))
    return "; ".join(clauses)


def _apply_uncertainty(points: list[dict], figures: list[FigureSpec], metrics: list[MetricResult],
                       budget: Any) -> dict[str, Any]:
    """Expose evaluated per-point uncertainty to the report model; nothing when not evaluated.

    Band keys, ± labels and metric uncertainty appear only for quantities whose budget
    status is ``evaluated`` (UNC-02, WEB-03). The returned summary feeds
    ``ReportModel.uncertainty`` and the limitations text.
    """
    evaluated_ids: set[str] = set()
    banded_keys: set[str] = set()
    for point in points:
        for name in (*QUANTITIES, *UNCERTAINTY_DERIVED):
            result = evaluated_quantity(budget, point["point_id"], name)
            if result is None:
                continue
            point[f"{name}_lower"], point[f"{name}_upper"] = result["lower"], result["upper"]
            point[f"{name}_uncertainty_label"] = f"± {result['label'].split(' ± ', 1)[1]} (k = {result['k']:g})"
            evaluated_ids.add(point["point_id"])
            banded_keys.add(name)
    blocked = _blocking_summary(budget)
    if not isinstance(budget, dict) or not evaluated_ids:
        return {"status": "not_evaluated", "metrology": "unquantified", "evaluated_point_ids": [],
                "note": "Uncertainty is unquantified: no readback uncertainty budget was evaluated for this analysis."
                        + (f" Blocking terms: {blocked}." if blocked else "")
                        + " No validated uncertainty bands or difference-resolution claims are provided."}
    k = budget.get("coverage_factor")
    metrology = str(budget.get("metrology", "unquantified"))
    source = f"uncertainty.json ({budget.get('schema_version')}, k = {k:g})"
    by_id = {p["point_id"]: p for p in points}
    for figure in figures:
        keys = (f"{figure.y_key}_lower", f"{figure.y_key}_upper")
        if figure.y_key in banded_keys and any(keys[0] in by_id[pid] for s in figure.series for pid in s.point_ids):
            figure.lower_key, figure.upper_key, figure.uncertainty_source = *keys, source
            unit = "percentage points" if figure.y_key == "efficiency_pct" else None
            figure.caption += (f" Shaded bands are expanded uncertainties (k = {k:g}"
                               + (f", in {unit}" if unit else "") + f") from the declared readback specifications ({metrology}); "
                               "they are not validated 95 % confidence intervals, and points without a band were not evaluated.")
    metric_quantity = {"highest-observed-efficiency": "efficiency_pct", "highest-qualified-input-current": "Iin_A"}
    for metric in metrics:
        name = metric_quantity.get(metric.id) or ("Pin_W" if metric.id.startswith(NO_LOAD_METRIC_PREFIX) else None)
        pid = metric.selector.get("point_id")
        result = evaluated_quantity(budget, pid, name) if name and isinstance(pid, str) else None
        if result is not None:
            metric.uncertainty = {"status": metrology, "standard": result["standard"], "expanded": result["expanded"],
                                  "k": result["k"], "unit": result["unit"], "label": result["label"],
                                  "independence_assumed": result.get("independence_assumed", True),
                                  "reference": f"uncertainty.json#points/{pid}/{'quantities' if name in UNCERTAINTY_DERIVED else 'channels'}/{name}",
                                  "reason": None}
    status = str(budget.get("status", "partially_evaluated"))
    note = (f"Uncertainty is {'evaluated' if status == 'evaluated' else 'partially evaluated'} from the declared readback "
            f"specifications ({metrology}); ± values and bands are expanded uncertainties with k = {k:g}, not validated 95 % "
            "confidence intervals. Efficiency uncertainty is in percentage points; loss uncertainty is propagated separately in watts. "
            "Systematic terms are not reduced by averaging. ADC freshness and calibration remain unquantified aspects.")
    if status != "evaluated":
        note += (" Not evaluated for some points or quantities"
                 + (f"; blocking terms: {blocked}" if blocked else "; see the per-point reasons in uncertainty.json") + ".")
    return {"status": status, "metrology": metrology, "coverage_factor": k,
            "coverage_factor_note": budget.get("coverage_factor_note"), "evaluated_point_ids": sorted(evaluated_ids),
            "banded_quantities": sorted(banded_keys), "specification_status": {
                q: c.get("status") for q, c in budget.get("channels", {}).items() if isinstance(c, dict)},
            "unquantified_aspects": list(budget.get("unquantified_aspects", [])), "note": note}


def _implausible_ratio_statements(points: list[dict]) -> tuple[str | None, str | None]:
    """Summary paragraph and limitation line for points flagged implausible; computed, never invented."""
    flagged = [p for p in points if is_flagged_implausible(p)]
    if not flagged:
        return None, None
    loaded = [p for p in points if p.get("iout_target_A") not in (None, 0)]
    etas = [_finite_number(p.get("efficiency_pct")) for p in flagged]
    above = [p for p, eta in zip(flagged, etas) if eta is not None and eta > 100]
    if len(above) == len(flagged):
        kind = "output power above input power"
    elif not above:
        kind = "negative output power"
    else:
        kind = "output power above input power or negative"
    text = (f"{len(flagged)} of {len(loaded)} loaded points show a physically impossible power ratio ({kind}) "
            "and are not qualified; the readings are preserved in the table and explorer.")
    differences = [1000 * (p["Iout_A"] - p["Iin_A"]) for p in above
                   if _finite_number(p.get("Iout_A")) is not None and _finite_number(p.get("Iin_A")) is not None]
    if differences and (all(d > 0 for d in differences) or all(d < 0 for d in differences)):
        text += (f" The input and output current readbacks differ by {min(differences):+.1f} mA to "
                 f"{max(differences):+.1f} mA across these points, which points to instrument readback disagreement "
                 "at the declared boundary rather than converter behaviour (output power cannot exceed input power).")
    limitation = (f"Points flagged {IMPLAUSIBLE_RATIO_FLAG} ({', '.join(p['point_id'] for p in flagged)}) keep their "
                  "readings and their unclamped computed efficiency and loss; they are not qualified, contribute to no "
                  "issued metric, and are drawn with open markers in the figures.")
    return text, limitation


def _readback_cross_check(plan: Plan, points: list[dict]) -> dict[str, Any]:
    """Pass-through DUT (topology 'none ...'): per-point and aggregate readback differences.

    ``current_readback_difference_A = Iout_A − Iin_A`` and ``voltage_drop_V = Vin_V − Vout_V``
    over loaded points with complete channel means, whatever their qualification.
    These compare two instruments' readbacks along the declared path; they are
    not a calibration and correct no stored value.
    """
    empty = {"metrics": [], "summary": None, "summary_metric_ids": [], "limitation": None}
    if not str(plan.dut.construction.topology).strip().lower().startswith("none"):
        return empty
    loaded = [p for p in points if p.get("iout_target_A") not in (None, 0)
              and all(_finite_number(p.get(q)) is not None for q in QUANTITIES)]
    if not loaded:
        return empty
    quantities = {
        "current-difference": ("current readback difference", "Iout_A − Iin_A", "A",
                               lambda p: p["Iout_A"] - p["Iin_A"]),
        "voltage-drop": ("voltage drop", "Vin_V − Vout_V", "V", lambda p: p["Vin_V"] - p["Vout_V"]),
    }
    basis = " (channel means over accepted cycles; a difference between two instrument readbacks along the declared path, not a correction)"
    ids = [p["point_id"] for p in loaded]
    inputs = sorted({p["vin_target_V"] for p in loaded})
    loads = sorted({p["iout_target_A"] for p in loaded})
    scope = (f"{len(loaded)} loaded points ({', '.join(ids)}); "
             + _join_phrases([f"{v:g} V" for v in inputs]) + " requested input; requested loads "
             + (f"{loads[0]:g} A" if len(loads) == 1 else f"{loads[0]:g}–{loads[-1]:g} A"))
    metrics: list[MetricResult] = []
    aggregates: dict[str, dict[str, float]] = {}
    for name, (description, formula, unit, compute) in quantities.items():
        values = [compute(p) for p in loaded]
        for point, value in zip(loaded, values):
            metrics.append(MetricResult(id=f"{READBACK_METRIC_PREFIX}{name}-{point['point_id']}",
                label=f"{READBACK_LABEL}: {description}", value=float(value), unit=unit,
                formula=formula + basis,
                conditions=(f"{point['point_id']}: {point['vin_target_V']:g} V requested input, "
                            f"{point['iout_target_A']:g} A requested load; point {point['qualification']}"),
                selector={"point_id": point["point_id"]}, point_ids=[point["point_id"]], figure_ids=[]))
        aggregates[name] = {"mean": float(mean(values)), "min": float(min(values)), "max": float(max(values))}
        for statistic, value in aggregates[name].items():
            metrics.append(MetricResult(id=f"{READBACK_METRIC_PREFIX}{name}-{statistic}",
                label=f"{READBACK_LABEL}: {statistic} {description}", value=value, unit=unit,
                formula=f"{statistic}({formula}) over loaded points{basis}",
                conditions=scope, selector={"observation": "loaded", "topology": plan.dut.construction.topology},
                point_ids=ids, figure_ids=[]))
    current, drop = aggregates["current-difference"], aggregates["voltage-drop"]
    summary = (f"{READBACK_LABEL}: across {len(loaded)} loaded points the load current readback minus the source "
               f"current readback is {1000 * current['mean']:+.1f} mA on average ({1000 * current['min']:+.1f} to "
               f"{1000 * current['max']:+.1f} mA), and the source-terminal voltage minus the load-terminal voltage is "
               f"{1000 * drop['mean']:.1f} mV on average ({1000 * drop['min']:.1f} to {1000 * drop['max']:.1f} mV). "
               "These are differences between two instruments' readbacks along the declared path; no stored value is corrected.")
    limitation = ("The readback cross-check compares the source and load instruments' readbacks along the declared "
                  "pass-through path. It is not a calibration, its uncertainty is unquantified, and it corrects no stored value.")
    return {"metrics": metrics, "summary": summary,
            "summary_metric_ids": [f"{READBACK_METRIC_PREFIX}{name}-mean" for name in quantities],
            "limitation": limitation}


SOURCE_LIMIT_FLAG = "source-current-limited"


def _source_limited_phases(points: list[dict]) -> list[dict]:
    """Each input-voltage phase whose source entered current limiting: the limited point and the higher
    loads of that phase left not-run, in plan order. Computed from the retained outcomes, never invented."""
    phases = []
    for point in points:
        if point.get("qualification") != "setup-limited":
            continue
        same_phase = [p for p in points if p["test_id"] == point["test_id"] and p["vin_target_V"] == point["vin_target_V"]]
        skipped = [p for p in same_phase if p["iout_target_A"] > point["iout_target_A"] and p.get("qualification") == "not-run"]
        phases.append({"point": point, "skipped": skipped})
    return phases


def _source_limit_statements(points: list[dict]) -> list[str]:
    """One deterministic summary sentence per current-limited phase (brief 9.3: points unavailable because the
    source budget was exceeded belong in the prose, not only in the coverage table)."""
    statements = []
    for phase in _source_limited_phases(points):
        point, skipped = phase["point"], phase["skipped"]
        vin, iout = point["vin_target_V"], point["iout_target_A"]
        text = f"The source entered current limiting at {vin:g} V, {iout:g} A requested ({point['point_id']}); "
        if skipped:
            ids = ", ".join(p["point_id"] for p in skipped)
            text += f"{len(skipped)} higher load{'s' if len(skipped) != 1 else ''} at {vin:g} V ({ids}) were not attempted."
        else:
            text += f"no higher load at {vin:g} V was requested."
        statements.append(text)
    return statements


def _flag_figure_captions(figures: list[FigureSpec], points: list[dict]) -> None:
    """Say what an open marker means on every figure that draws a flagged point, and where a curve ends
    because the source entered current limiting."""
    by_id = {p["point_id"]: p for p in points}
    limited = _source_limited_phases(points)
    for figure in figures:
        drawn = [pid for series in figure.series for pid in series.point_ids
                 if is_flagged_implausible(by_id[pid])
                 and _finite_number(by_id[pid].get(figure.x_key)) is not None
                 and _finite_number(by_id[pid].get(figure.y_key)) is not None]
        if drawn:
            figure.caption += (f" Open markers are {len(drawn)} point(s) flagged {IMPLAUSIBLE_RATIO_FLAG}; they are drawn "
                               "unclamped for visibility, are not qualified, and are excluded from issued results.")
        for phase in limited:
            point = phase["point"]
            if not any(point["point_id"] in series.point_ids for series in figure.series):
                continue
            vin, iout = point["vin_target_V"], point["iout_target_A"]
            figure.caption += (f" The {vin:g} V series stops before {iout:g} A: the source entered current limiting there "
                               f"(flag {SOURCE_LIMIT_FLAG}; {point['point_id']} is not drawn)"
                               + (f" and {len(phase['skipped'])} higher load"
                                  f"{'s' if len(phase['skipped']) != 1 else ''} at {vin:g} V were not attempted."
                                  if phase["skipped"] else "."))


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
    for point in points:
        # Analyses issued before settled-dc-1.3 carry no per-point flag list.
        point.setdefault("quality_flags", [])
    sequence = _sequence_annotations(points, raw_samples)
    search = run.get("method", {}).get("source_limit_search")
    voltage_sweep = run.get("method", {}).get("voltage_efficiency_sweep")
    startup_descent = run.get("method", {}).get("startup_descent")
    uvlo = analysis.get("uvlo_input_ramp")
    profiles = analysis.get("supply_profiles")
    comparison = _voltage_comparison(points, voltage_sweep) if voltage_sweep else []
    if voltage_sweep or startup_descent:
        _accepted_point_times(points, raw_samples)
    executed = run.get("executed_point_ids") if search or voltage_sweep or startup_descent or uvlo or profiles else None
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
    if uvlo:
        for test in plan.recipe.tests:
            detail = uvlo.get(test.id)
            if not detail:
                continue
            load_mA = detail["load_A"] * 1000
            figures.append(FigureSpec(id=f"fig-uvlo-{test.id}", title="Output Voltage vs Input Step (UVLO Ramp)",
                x_key="Vin_V", y_key="Vout_V", x_label="Input Voltage (V)", y_label="Output Voltage (V)",
                series=[FigureSeries(id=f"uvlo-{test.id}", label=f"{load_mA:g} mA load · declared ramp order",
                    vin_target_V=None, iout_target_A=detail["load_A"], selection_key=f"uvlo-{test.id}",
                    point_ids=[step["point_id"] for step in detail["steps"]])],
                caption=f"{evidence_label}. {boundary}. Accepted DC means at each declared input step in execution order "
                        f"(descending, then ascending) at a fixed {load_mA:g} mA load. Output-off steps are recorded states "
                        "under the declared UVLO convention, not faults. Transitions are bracketed between adjacent steps; "
                        "no exact threshold is claimed."))
    if profiles:
        for test in plan.recipe.tests:
            detail = profiles.get(test.id)
            if not detail:
                continue
            load_mA = detail["load_A"] * 1000
            order = ("descending, then ascending" if detail["type"] == SLOW_SUPPLY_RAMP_TEST_TYPE
                     else "the recovery level alternating with each low")
            figures.append(FigureSpec(id=f"fig-profile-{test.id}", title=f"Output Voltage vs Input Level (ISO 16750-2 {detail['label']})",
                x_key="Vin_V", y_key="Vout_V", x_label="Input Voltage (V)", y_label="Output Voltage (V)",
                series=[FigureSeries(id=f"profile-{test.id}", label=f"{load_mA:g} mA load · declared level order",
                    vin_target_V=None, iout_target_A=detail["load_A"], selection_key=f"profile-{test.id}",
                    point_ids=[level["point_id"] for level in detail["levels"]])],
                caption=f"{evidence_label}. {boundary}. Accepted DC means at each declared level in execution order ({order}) "
                        f"at a fixed {load_mA:g} mA load. Output-off levels are recorded states under the declared policy, not "
                        f"faults. {SUPPLY_PROFILE_CADENCE[0].upper() + SUPPLY_PROFILE_CADENCE[1:]}."))
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
    for point in valid:
        if point.get("observation") != "enabled_no_load" or point.get("enabled_no_load_consumption_W") is None:
            continue
        offset = point.get("load_readback_offset_A")
        metrics.append(MetricResult(id=f"{NO_LOAD_METRIC_PREFIX}{point['point_id']}",
            label="Enabled no-load path input consumption", value=point["enabled_no_load_consumption_W"], unit="W",
            formula="mean(Vin) * mean(Iin) with the load input OFF",
            conditions=point.get("input_condition_label", f"{point['vin_target_V']:g} V requested input")
                       + f"; load input {point.get('load_input_state', 'not recorded')}"
                       + (f"; load current readback {offset:.4f} A retained as a load-off offset, not output current"
                          if isinstance(offset, (int, float)) and not isinstance(offset, bool) else "")
                       + "; efficiency not applicable; path consumption at the declared boundary, not module-only loss",
            selector={"point_id": point["point_id"]}, point_ids=[point["point_id"]], figure_ids=[]))
    nominal = plan.dut.ratings.output_voltage_nominal_V
    for test in plan.recipe.tests:
        if test.type in PHASE_SCOPED_TEST_TYPES:
            continue  # a ramp or staircase through an expected-off region is not a regulation sweep
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
    cross_check = _readback_cross_check(plan, points)
    metrics.extend(cross_check["metrics"])
    uncertainty = _apply_uncertainty(points, figures, metrics, analysis.get("uncertainty"))
    # Bound temperature channels contribute separate figures (no secondary axes).
    thermal_section = thermal_report_contribution(plan, run, points, raw_samples, series, evidence_label, boundary)
    figures.extend(thermal_section["figures"])
    metrics.extend(thermal_section["metrics"])
    _flag_figure_captions(figures, points)
    for metric in metrics:
        metric.qualification = f"{observation} observation"
    summary = [f"{len(valid)} of {len(points)} requested operating points produced qualified {observation} DC results."]
    summary.extend(_source_limit_statements(points))
    summary_evidence = []
    implausible_summary, implausible_limitation = _implausible_ratio_statements(points)
    if implausible_summary:
        summary.append(implausible_summary)
    if cross_check["summary"]:
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=cross_check["summary_metric_ids"]))
        summary.append(cross_check["summary"])
    if uvlo:
        for test_id, detail in uvlo.items():
            off, on, hysteresis = detail["turn_off"], detail["turn_on"], detail["hysteresis"]
            parts = [f"UVLO input ramp '{test_id}' at {detail['load_A'] * 1000:g} mA:",
                     (f"turn-off is bracketed between {off['lower_V']:g} and {off['upper_V']:g} V input "
                      f"(last on at {off['upper_V']:g} V, first off at {off['lower_V']:g} V)." if off else "turn-off was not bracketed."),
                     (f"Turn-on is bracketed between {on['lower_V']:g} and {on['upper_V']:g} V "
                      f"(last off at {on['lower_V']:g} V, first on at {on['upper_V']:g} V)." if on else "Turn-on was not bracketed.")]
            if hysteresis:
                parts.append(f"Hysteresis lies between {hysteresis['lower_V']:g} and {hysteresis['upper_V']:g} V "
                             "by the bracket-difference convention.")
            parts.append("These are step-limited intervals under the declared convention; no exact threshold is claimed.")
            summary.append(" ".join(parts))
            for note in detail["notes"]:
                summary.append(f"UVLO input ramp '{test_id}': {note}.")
    if profiles:
        for test_id, detail in profiles.items():
            summary.append(f"ISO 16750-2 {detail['label']} '{test_id}' at {detail['load_A'] * 1000:g} mA. "
                           + " ".join(detail["statements"]))
            if detail["type"] == SLOW_SUPPLY_RAMP_TEST_TYPE:
                off, on = detail.get("turn_off"), detail.get("turn_on")
                parts = [(f"On the observation grid the output went off between {off['upper_V']:g} V (last in band) and "
                          f"{off['lower_V']:g} V (first off) on the decrease." if off else
                          "No off level was observed on the decrease, so no turn-off is bracketed."),
                         (f"It came back between {on['lower_V']:g} V (last off) and {on['upper_V']:g} V (first in band) on the increase."
                          if on else "No return to band is bracketed on the increase.")]
                parts.append("These are observation-grid intervals; no threshold value is claimed.")
                summary.append(" ".join(parts))
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
        if m.uncertainty.get("expanded") is not None and m.uncertainty.get("label"):
            summary.append(f"Highest observed path efficiency: {m.uncertainty['label']} (k = {m.uncertainty['k']:g}, "
                           f"{m.uncertainty['status']}) at {m.conditions}.")
        else:
            summary.append(f"Highest observed path efficiency: {m.value:.2f}% at {m.conditions}.")
    for m in metrics:
        if not m.id.startswith(NO_LOAD_METRIC_PREFIX):
            continue
        summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=[m.id]))
        if m.uncertainty.get("expanded") is not None and m.uncertainty.get("label"):
            summary.append(f"Enabled no-load path input consumption: {m.uncertainty['label']} (k = {m.uncertainty['k']:g}, "
                           f"{m.uncertainty['status']}) at {m.conditions}.")
        else:
            summary.append(f"Enabled no-load path input consumption: {m.value:.4g} W (uncertainty unquantified) at {m.conditions}.")
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
    for paragraph, metric_ids in thermal_section["summary"]:
        if metric_ids:
            summary_evidence.append(SummaryEvidence(paragraph_index=len(summary), metric_ids=metric_ids))
        summary.append(paragraph)
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
        (f"DUT ratings source: {plan.dut.ratings.origin.replace('_', ' ')}. "
         + ("The DUT profile records sample-label verification by the operator."
            if plan.dut.ratings.verified_from_sample_label else "Sample-label verification is not recorded.")),
        f"Measurement locations — {locations}. The declared boundary is {boundary}; path loss is not solely module heat.",
        uncertainty["note"],
        "Construction details are recorded from the DUT profile; these DC observations do not verify topology, "
        "controller identity or isolation. Protection behavior is not established by this run.",
        ("Bound temperature channels and sensor metadata are described in the temperature section."
         if plan.bench.temperature_sensors else "No temperature channels were bound for this acquisition."),
        f"This DC grid does not by itself qualify the claimed {plan.dut.ratings.output_power_rated_W:g} W rating, ripple, transient or thermal behavior.",
        ("At qualified no-load points, input consumption is reported; output power, path loss and efficiency are not evaluated because load-off current readback can contain an offset."
         if any(p["qualification"] == "valid" and p["iout_target_A"] == 0 for p in points) else
         "No qualified no-load point was acquired; enabled no-load input consumption was not measured in this run."),
    ]
    if implausible_limitation:
        limitations.append(implausible_limitation)
    if cross_check["limitation"]:
        limitations.append(cross_check["limitation"])
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
    limitations.extend(thermal_section["limitations"])
    return ReportModel(run_id=run["run_id"], analysis_id=analysis["analysis_id"], report_revision=revision,
        title=f"{plan.dut.identity.model} · DC–DC characterization", boundary=boundary,
        evidence_label=evidence_label,
        dut=plan.dut.model_dump(), bench=plan.bench.model_dump(),
        execution={"status": run.get("execution_status", "unknown"),
                   "shutdown": run.get("shutdown", {}), "scenario": run.get("scenario", "unknown"),
                   # Acquisition span for the report's "Recorded" line, UTC as written in run.json.
                   "created_utc": run.get("created_utc"),
                   "finished_utc": run.get("finished_utc") or run.get("completed_utc"),
                   **({"source_limit_search": copy.deepcopy(search)} if search else {}),
                   **({"voltage_efficiency_sweep": copy.deepcopy(voltage_sweep), "voltage_comparison": comparison} if voltage_sweep else {}),
                   **({"startup_descent": copy.deepcopy(startup_descent)} if startup_descent else {}),
                   **({"uvlo_input_ramp": copy.deepcopy(uvlo)} if uvlo else {}),
                   **({"supply_profiles": copy.deepcopy(profiles)} if profiles else {}),
                   **({"executed_point_ids": list(executed)} if executed is not None else {})},
        coverage=analysis["coverage"], points=points, metrics=metrics, figures=figures,
        tables=[TableSpec(id="table-points", title="All requested operating points", columns=CSV_FIELDS,
                          point_ids=[p["point_id"] for p in points])],
        evidence=[EvidenceRef(point_ids=m.point_ids, figure_ids=m.figure_ids) for m in metrics],
        summary=summary, summary_evidence=summary_evidence,
        method=_report_method(plan, run, analysis, raw_samples),
        prose=[analysis["aggregation"], analysis["sign_convention"]],
        limitations=limitations, raw_samples=dict(grouped), provenance=provenance, uncertainty=uncertainty,
        thermal=thermal_section["model"])


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
