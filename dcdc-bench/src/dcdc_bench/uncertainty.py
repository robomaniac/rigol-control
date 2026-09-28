"""Structured readback uncertainty budget for settled-DC points (brief section 9.2).

Pure arithmetic over analysis point means and the bench's declared readback
specifications. Importing this module never opens an instrument. Nothing here
reads a programming (setting) accuracy: the evaluator only ever consults
``MeasurementBinding.readback_specification`` (CORE-06 by construction).

Conventions
- A declared error limit of half-width ``a`` is a rectangular bound, so its
  standard uncertainty is ``a / sqrt(3)`` [R10].
- Specification, resolution and temperature terms are systematic. They are
  never divided by the number of averaged readings (UNC-04).
- Repeatability (Type A, ``s / sqrt(n)`` of the accepted readings) is recorded
  separately from the specification terms.
- Combined standard uncertainty follows the declared measurement model with
  the declared covariance; independence is recorded when assumed [R11].
- Expanded uncertainty is ``U = k * u_c``. ``k`` is recorded and no ``k = 2``
  interval is described as a validated 95 % confidence interval.
- Any required term that is unknown makes the affected quantity
  ``not_evaluated`` with a reason list. There is never a zero or a placeholder.
- Efficiency uncertainty is in percentage points; loss uncertainty is in watts
  and has its own propagation.
"""
from __future__ import annotations

import math
from statistics import stdev
from typing import Any

from .domain import MeasurementBinding, Plan, ReadbackSpecification, UncertaintyPolicy

SCHEMA_VERSION = "uncertainty-budget-1.0"
METHOD_VERSION = "readback-budget-1.0"
CHANNELS = ("Vin_V", "Iin_A", "Vout_V", "Iout_A")
CURRENT_CHANNELS = ("Iin_A", "Iout_A")
DERIVED = ("Pin_W", "Pout_W", "efficiency_pct", "loss_W")
MEASUREMENT_MODEL = {
    "Pin_W": "Vin_V * Iin_A",
    "Pout_W": "Vout_V * Iout_A",
    "efficiency_pct": "100 * Vout_V * Iout_A / (Vin_V * Iin_A)",
    "loss_W": "Vin_V * Iin_A - Vout_V * Iout_A",
}
DERIVED_UNITS = {"Pin_W": "W", "Pout_W": "W", "efficiency_pct": "percentage points", "loss_W": "W"}
LINEAR_MODEL_FLAG = "insufficient resolution / linear approximation questionable"
SYSTEMATIC_SCALING_NOTE = ("Specification, resolution and temperature terms are systematic and are not divided by "
                           "the number of averaged readings; only the separately recorded repeatability shrinks with n.")
UNQUANTIFIED_ASPECTS = [
    "ADC conversion freshness and the independence of successive polled readbacks are not modeled.",
    "Calibration enters only as the declared status; no certificate or as-found data is verified by software.",
    "Lead and contact drops between the sense location and the declared boundary are not corrected or budgeted.",
    "Ambient drift and instrument self-heating are modeled only when a temperature coefficient and an observed ambient temperature are both declared.",
    "Reading synchronization between channels is bounded by the accepted inter-channel skew, not budgeted as a term.",
]
_METROLOGY_BY_STATUS = {
    "calibrated": "quantified uncertainty",
    "datasheet_quoted": "specification-bound only",
    "unverified_user_entry": "specification-bound only (unverified user entry)",
    "synthetic_example": "specification-bound only (synthetic example)",
}
_METROLOGY_RANK = ("synthetic_example", "unverified_user_entry", "datasheet_quoted", "calibrated")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def rectangular_standard_uncertainty(half_width: float) -> float:
    """Standard uncertainty of a rectangular error limit of half-width ``a`` (a / sqrt(3))."""
    if not _finite(half_width) or half_width < 0:
        raise ValueError("A rectangular half-width must be a finite nonnegative number")
    return half_width / math.sqrt(3)


def _decimals(expanded: float) -> int:
    """Two significant digits of U, with trailing zeros dropped so 0.40 prints as 0.4."""
    if not _finite(expanded) or expanded <= 0:
        raise ValueError("Expanded uncertainty must be a finite positive number")
    decimals = max(0, 1 - math.floor(math.log10(expanded)))
    while decimals > 0 and f"{expanded:.{decimals}f}".endswith("0"):
        decimals -= 1
    return decimals


def format_efficiency_label(value_pct: float, expanded_pp: float) -> str:
    """``92.6% ± 0.4 percentage points``: efficiency in percent, uncertainty in percentage points."""
    decimals = _decimals(expanded_pp)
    return f"{value_pct:.{decimals}f}% ± {expanded_pp:.{decimals}f} percentage points"


def format_quantity_label(value: float, expanded: float, unit: str) -> str:
    decimals = _decimals(expanded)
    return f"{value:.{decimals}f} {unit} ± {expanded:.{decimals}f} {unit}"


def channel_specification_review(quantity: str, binding: MeasurementBinding | None, *,
                                 bench_mode: str, evidence_label: str) -> dict[str, Any]:
    """Decide whether a channel's readback specification can be evaluated at all.

    Only ``readback_specification`` is consulted. ``programming_accuracy`` and the
    legacy ``accuracy`` marker are deliberately not read (CORE-06).
    """
    spec = binding.readback_specification if binding is not None else None
    reasons: list[str] = []
    if binding is None:
        reasons.append(f"{quantity}: no measurement binding on the bench profile")
    elif spec is None:
        reasons.append(f"{quantity}: readback_specification not declared")
    else:
        if spec.status == "synthetic_example" and (bench_mode == "real" or evidence_label == "MEASURED"):
            reasons.append(f"{quantity}: a synthetic example specification is not an instrument specification for a real bench")
        reasons.extend(f"{quantity}: {term}" for term in spec.missing_terms())
    return {"quantity": quantity, "unit": binding.unit if binding is not None else None,
            "evaluable": not reasons, "reasons": reasons,
            "status": spec.status if spec is not None else "unknown",
            "source": spec.source if spec is not None else "unknown",
            "source_candidates": list(spec.source_candidates) if spec is not None else [],
            "specification": spec.model_dump() if spec is not None else None,
            "programming_accuracy_consulted": False}


def channel_standard_uncertainty(spec: ReadbackSpecification, mean: Any, *, unit: str,
                                 samples: list[float] | tuple[float, ...] = (), ambient_C: float | None = None,
                                 include_repeatability: bool = True) -> dict[str, Any]:
    """Standard uncertainty of one channel mean from its declared readback terms.

    Half-width ``a = |mean| * percent_of_reading/100 + range_value * percent_of_range/100 + absolute_offset``
    is treated as a rectangular limit. Resolution contributes a rectangular half-width of
    ``resolution / 2``. A declared temperature coefficient applies per degree beyond the
    reference band and needs an observed ambient temperature. Terms combine in quadrature.
    """
    missing = spec.missing_terms()
    if missing:
        return {"status": "not_evaluated", "reasons": missing}
    if not _finite(mean):
        return {"status": "not_evaluated", "reasons": ["channel mean is not a finite number"]}
    mean = float(mean)
    range_value = spec.range_value or 0.
    reading_term = abs(mean) * spec.percent_of_reading / 100
    range_term = range_value * spec.percent_of_range / 100
    half_width = reading_term + range_term + spec.absolute_offset
    u_spec = rectangular_standard_uncertainty(half_width)
    u_res = rectangular_standard_uncertainty(spec.resolution / 2)
    if spec.temperature_coefficient is None:
        temperature: dict[str, Any] = {"status": "not_declared", "standard": 0.,
                                       "note": "no temperature coefficient declared; the specification is taken as applicable within its stated conditions"}
    elif ambient_C is None:
        return {"status": "not_evaluated",
                "reasons": ["temperature coefficient declared but no ambient temperature was recorded for this point"]}
    else:
        tc = spec.temperature_coefficient
        excess = max(0., abs(ambient_C - tc.reference_temperature_C) - tc.reference_band_C)
        a_temp = excess * (abs(mean) * tc.percent_of_reading_per_C / 100
                           + range_value * tc.percent_of_range_per_C / 100 + tc.absolute_per_C)
        temperature = {"status": "evaluated", "ambient_C": ambient_C, "excess_C": excess, "half_width": a_temp,
                       "standard": rectangular_standard_uncertainty(a_temp), "distribution": "rectangular"}
    u_systematic = math.sqrt(u_spec ** 2 + u_res ** 2 + temperature["standard"] ** 2)
    values = [float(v) for v in samples if _finite(v)]
    if len(values) >= 2:
        s = stdev(values)
        u_a = s / math.sqrt(len(values))
        repeatability: dict[str, Any] = {"status": "evaluated", "n": len(values), "sample_standard_deviation": s,
                                         "standard_error_of_mean": u_a, "included_in_combined": include_repeatability}
    else:
        u_a = 0.
        repeatability = {"status": "not_evaluated", "n": len(values), "reason": "fewer than two accepted readings",
                         "included_in_combined": False}
    u_c = math.sqrt(u_systematic ** 2 + (u_a ** 2 if repeatability["included_in_combined"] else 0.))
    return {"status": "evaluated", "mean": mean, "unit": unit,
            "terms": {"specification_limit": {"half_width": half_width, "standard": u_spec, "distribution": spec.distribution,
                                              "components": {"percent_of_reading": reading_term, "percent_of_range": range_term,
                                                             "absolute_offset": spec.absolute_offset},
                                              "range_value": spec.range_value},
                      "resolution": {"value": spec.resolution, "half_width": spec.resolution / 2, "standard": u_res,
                                     "distribution": "rectangular"},
                      "temperature": temperature},
            "systematic_standard": u_systematic, "repeatability": repeatability, "standard": u_c,
            "relative_standard": u_c / abs(mean) if mean != 0 else None,
            "systematic_scaling_with_n": "none", "specification_status": spec.status, "source": spec.source}


def sensitivity_coefficients(quantity: str, means: dict[str, float]) -> dict[str, float]:
    """First-order partial derivatives of the declared measurement model."""
    v1, i1, v2, i2 = (means[q] for q in CHANNELS)
    if quantity == "Pin_W":
        return {"Vin_V": i1, "Iin_A": v1}
    if quantity == "Pout_W":
        return {"Vout_V": i2, "Iout_A": v2}
    if quantity == "loss_W":
        return {"Vin_V": i1, "Iin_A": v1, "Vout_V": -i2, "Iout_A": -v2}
    if quantity == "efficiency_pct":
        pin = v1 * i1
        if pin == 0:
            raise ValueError("Efficiency sensitivities need nonzero input power")
        return {"Vout_V": 100 * i2 / pin, "Iout_A": 100 * v2 / pin,
                "Vin_V": -100 * v2 * i2 / (pin * v1), "Iin_A": -100 * v2 * i2 / (pin * i1)}
    raise ValueError(f"Unknown derived quantity {quantity!r}")


def propagate(coefficients: dict[str, float], standard: dict[str, float],
              correlations: dict[frozenset, float] | None = None) -> float:
    """u_c = sqrt(sum_i sum_j c_i c_j u(x_i, x_j)) with u(x_i, x_j) = r_ij u_i u_j."""
    correlations = correlations or {}
    variance = 0.
    for a, ca in coefficients.items():
        for b, cb in coefficients.items():
            r = 1. if a == b else correlations.get(frozenset((a, b)), 0.)
            variance += ca * cb * r * standard[a] * standard[b]
    return math.sqrt(max(variance, 0.))


def difference_uncertainty(result_a: dict[str, Any], result_b: dict[str, Any], *, correlation: float = 0.,
                           k: float | None = None) -> dict[str, Any]:
    """Uncertainty of (a - b) between two evaluated quantity results, respecting a declared correlation (UNC-03)."""
    if not -1 <= correlation <= 1:
        raise ValueError("A correlation coefficient must lie in [-1, 1]")
    reasons = [f"{name} is not evaluated" for name, item in (("a", result_a), ("b", result_b))
               if item.get("status") != "evaluated"]
    if reasons:
        return {"status": "not_evaluated", "reasons": reasons}
    if result_a.get("unit") != result_b.get("unit"):
        raise ValueError("Difference requires results in the same unit")
    ua, ub = result_a["standard"], result_b["standard"]
    covariance = correlation * ua * ub
    u = math.sqrt(max(0., ua * ua + ub * ub - 2 * covariance))
    return {"status": "evaluated", "difference": result_a["value"] - result_b["value"], "unit": result_a["unit"],
            "standard": u, "covariance": covariance, "correlation": correlation,
            "independence_assumed": correlation == 0, "k": k, "expanded": k * u if k else None}


def _quantity_result(name: str, value: float, u_c: float, k: float, coefficients: dict[str, float],
                     independence_assumed: bool, flags: list[str]) -> dict[str, Any]:
    unit = DERIVED_UNITS[name]
    expanded = k * u_c
    if expanded > 0:
        label = (format_efficiency_label(value, expanded) if name == "efficiency_pct"
                 else format_quantity_label(value, expanded, unit))
    else:
        label = f"{value:g} {'%' if name == 'efficiency_pct' else unit} ± 0 {unit} (all declared terms are zero)"
    return {"status": "evaluated", "value": value, "unit": unit, "standard": u_c, "expanded": expanded, "k": k,
            "lower": value - expanded, "upper": value + expanded, "label": label,
            "sensitivity_coefficients": coefficients, "independence_assumed": independence_assumed,
            "model": MEASUREMENT_MODEL[name], "flags": flags}


def _metrology(statuses: list[str]) -> str:
    weakest = min(statuses, key=_METROLOGY_RANK.index)
    return _METROLOGY_BY_STATUS[weakest]


def evaluate_point(point: dict[str, Any], reviews: dict[str, dict[str, Any]], *, policy: UncertaintyPolicy,
                   correlations: dict[frozenset, float], samples: dict[str, list[float]] | None = None,
                   ambient_C: float | None = None) -> dict[str, Any]:
    """Budget for one analysis point: channel uncertainties, then each derived quantity."""
    samples = samples or {}
    result: dict[str, Any] = {"point_id": point["point_id"], "qualification": point.get("qualification"),
                              "status": "not_evaluated", "metrology": "unquantified", "reasons": [],
                              "channels": {}, "quantities": {}}
    if point.get("qualification") != "valid":
        reason = f"point qualification is {point.get('qualification')}; only valid points are evaluated"
        result["reasons"].append(reason)
        result["channels"] = {q: {"status": "not_evaluated", "reasons": [reason]} for q in CHANNELS}
        result["quantities"] = {name: {"status": "not_evaluated", "reasons": [reason], "flags": []} for name in DERIVED}
        return result
    channels = result["channels"]
    for q in CHANNELS:
        review = reviews[q]
        if not review["evaluable"]:
            channels[q] = {"status": "not_evaluated", "reasons": list(review["reasons"])}
            continue
        spec = ReadbackSpecification.model_validate(review["specification"])
        channel = channel_standard_uncertainty(spec, point.get(q), unit=review["unit"], samples=samples.get(q, []),
                                               ambient_C=ambient_C, include_repeatability=policy.include_repeatability_in_combined)
        if channel["status"] == "evaluated":
            expanded = policy.coverage_factor * channel["standard"]
            channel.update(k=policy.coverage_factor, expanded=expanded, value=channel["mean"],
                           lower=channel["mean"] - expanded, upper=channel["mean"] + expanded,
                           label=(format_quantity_label(channel["mean"], expanded, review["unit"]) if expanded > 0
                                  else f"{channel['mean']:g} {review['unit']} ± 0 {review['unit']} (all declared terms are zero)"))
        channels[q] = channel
    standard = {q: channels[q]["standard"] for q in CHANNELS if channels[q]["status"] == "evaluated"}
    means = {q: _number(point.get(q)) for q in CHANNELS}
    bound = policy.linear_model_relative_uncertainty_bound
    independence_assumed = not correlations
    for name in DERIVED:
        value = _number(point.get(name))
        needed = ["Vin_V", "Iin_A"] if name == "Pin_W" else ["Vout_V", "Iout_A"] if name == "Pout_W" else list(CHANNELS)
        reasons = [f"{q} standard uncertainty not evaluated" for q in needed if q not in standard]
        if value is None:
            reasons.append(str(point.get({"efficiency_pct": "efficiency_reason", "Pout_W": "output_power_reason",
                                          "loss_W": "loss_reason"}.get(name, ""), None)
                               or f"{name} was not evaluated by the analysis"))
        flags: list[str] = []
        exceeded = {q: channels[q]["relative_standard"] for q in needed if q in standard
                    and (channels[q]["relative_standard"] is None or channels[q]["relative_standard"] > bound)}
        if exceeded:
            detail = "; ".join(f"relative standard uncertainty of {q} "
                               + ("is undefined at a zero mean" if rel is None else f"= {rel:.3g}")
                               + f" exceeds the declared bound {bound:g}" for q, rel in exceeded.items())
            flags.append(LINEAR_MODEL_FLAG)
            if name == "efficiency_pct":
                reasons.append(f"{LINEAR_MODEL_FLAG}: {detail}; no symmetric interval is reported for this ratio")
            else:
                flags.append(f"{detail}; the product's interval is dominated by that channel")
        if reasons:
            result["quantities"][name] = {"status": "not_evaluated", "reasons": reasons, "flags": flags,
                                          "unit": DERIVED_UNITS[name]}
            continue
        coefficients = sensitivity_coefficients(name, means)
        u_c = propagate(coefficients, standard, correlations)
        result["quantities"][name] = _quantity_result(name, value, u_c, policy.coverage_factor, coefficients,
                                                      independence_assumed, flags)
    evaluated_channels = [q for q in CHANNELS if channels[q]["status"] == "evaluated"]
    evaluated_quantities = [n for n in DERIVED if result["quantities"][n]["status"] == "evaluated"]
    if len(evaluated_channels) == len(CHANNELS):
        result["metrology"] = _metrology([channels[q]["specification_status"] for q in CHANNELS])
    if len(evaluated_channels) == len(CHANNELS) and len(evaluated_quantities) == len(DERIVED):
        result["status"] = "evaluated"
    elif evaluated_channels or evaluated_quantities:
        result["status"] = "partially_evaluated"
    result["reasons"] = sorted({reason for q in CHANNELS for reason in channels[q].get("reasons", [])}
                               | {reason for n in DERIVED for reason in result["quantities"][n].get("reasons", [])})
    return result


def evaluate_run_budget(plan: Plan, points: list[dict[str, Any]], accepted_values: dict[str, dict[str, list[float]]],
                        *, evidence_label: str, observed_conditions: dict[str, Any] | None = None) -> dict[str, Any]:
    """The schema-versioned content of ``uncertainty.json`` for one analysis revision."""
    bench = plan.bench
    policy = bench.uncertainty_policy
    reviews = {q: channel_specification_review(q, bench.measurements.get(q), bench_mode=bench.mode,
                                               evidence_label=evidence_label) for q in CHANNELS}
    correlations = {frozenset((c.quantity_a, c.quantity_b)): c.coefficient for c in bench.readback_correlations}
    ambient = _number((observed_conditions or {}).get("ambient_temperature_C"))
    results = {p["point_id"]: evaluate_point(p, reviews, policy=policy, correlations=correlations,
                                             samples=accepted_values.get(p["point_id"], {}), ambient_C=ambient)
               for p in points}
    valid = [r for r in results.values() if r["qualification"] == "valid"]
    fully = [r for r in valid if r["status"] == "evaluated"]
    partially = [r for r in valid if r["status"] == "partially_evaluated"]
    if valid and len(fully) == len(valid):
        status = "evaluated"
    elif fully or partially:
        status = "partially_evaluated"
    else:
        status = "not_evaluated"
    reasons = sorted({reason for review in reviews.values() for reason in review["reasons"]})
    if not valid:
        reasons.append("no valid point to evaluate")
    metrology = "unquantified"
    if all(review["evaluable"] for review in reviews.values()):
        metrology = _metrology([reviews[q]["status"] for q in CHANNELS])
    return {"schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION, "status": status,
            "metrology": metrology, "evidence_label": evidence_label, "bench_id": bench.bench_id, "bench_mode": bench.mode,
            "measurement_model": dict(MEASUREMENT_MODEL), "efficiency_uncertainty_unit": "percentage points",
            "loss_uncertainty_unit": "W", "coverage_factor": policy.coverage_factor,
            "coverage_factor_note": policy.coverage_factor_note, "policy": policy.model_dump(),
            "channels": reviews,
            "correlations": {"declared": [c.model_dump() for c in bench.readback_correlations],
                             "independence_assumed": not correlations},
            "systematic_terms": SYSTEMATIC_SCALING_NOTE,
            "repeatability": ("Type A standard error of the mean of the accepted readings, recorded per channel; "
                              + ("included in the combined standard uncertainty" if policy.include_repeatability_in_combined
                                 else "recorded only, not included in the combined standard uncertainty")),
            "unquantified_aspects": list(UNQUANTIFIED_ASPECTS), "reasons": reasons,
            "summary": {"valid_points": len(valid), "evaluated_points": len(fully),
                        "partially_evaluated_points": len(partially),
                        "not_evaluated_points": len(results) - len(fully) - len(partially)},
            "points": results}


def evaluated_quantity(budget: dict[str, Any] | None, point_id: str, name: str) -> dict[str, Any] | None:
    """The evaluated result for one point quantity, or None. Presentation code uses only this."""
    if not isinstance(budget, dict) or str(budget.get("schema_version", "")) != SCHEMA_VERSION:
        return None
    item = budget.get("points", {}).get(point_id, {})
    source = item.get("quantities", {}) if name in DERIVED else item.get("channels", {})
    result = source.get(name)
    if not isinstance(result, dict) or result.get("status") != "evaluated" or not _finite(result.get("expanded")):
        return None
    return result
