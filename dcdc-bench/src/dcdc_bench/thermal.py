"""Pure thermal analysis (implementation brief, section 10). No hardware or UI imports.

Absolute temperature and rise above *time-aligned* ambient are computed only
from retained raw readings. A missing ambient reference means no rise, not an
assumed room temperature. A slope of surface rise versus total measured loss
is an empirical relationship for the stated boundary and setup only.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Any

from .domain import (ANNOTATIONS_SCHEMA_VERSION, MOCK_THERMAL_ADAPTER, BenchProfile, Plan, SensorPlacement,
                     TemperatureSensor, ThermalSettlingPolicy)

THERMAL_PHASE = "thermal-settling"
QUALIFICATIONS = ("settled", "inconclusive", "logged-only", "not-run")


# ---------------------------------------------------------------------------
# Photograph placement: the marker editor writes annotations.json (schema 1.0)
# ---------------------------------------------------------------------------

def placements_from_annotations(annotations: dict[str, Any]) -> dict[str, SensorPlacement]:
    """Read ``annotations.json`` markers into placements keyed by sensor_id."""
    if not isinstance(annotations, dict) or annotations.get("schema_version") != ANNOTATIONS_SCHEMA_VERSION:
        raise ValueError(f"annotations.json requires schema_version {ANNOTATIONS_SCHEMA_VERSION!r}")
    image = annotations.get("image_asset_sha256")
    markers = annotations.get("markers")
    if not isinstance(image, str) or not isinstance(markers, list):
        raise ValueError("annotations.json requires image_asset_sha256 and a markers list")
    placements: dict[str, SensorPlacement] = {}
    for marker in markers:
        if not isinstance(marker, dict) or not isinstance(marker.get("sensor_id"), str):
            raise ValueError("Every marker names its sensor_id")
        sensor_id = marker["sensor_id"]
        if sensor_id in placements:
            raise ValueError(f"Duplicate marker for sensor {sensor_id}")
        coordinates = {}
        for axis in ("x_norm", "y_norm"):
            value = marker.get(axis)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Marker {sensor_id} requires numeric {axis}")
            coordinates[axis] = float(value)
        label = marker.get("label")
        placements[sensor_id] = SensorPlacement(image_asset_sha256=image, label=label if isinstance(label, str) else None,
                                                **coordinates)
    return placements


def apply_placements(sensors: list[TemperatureSensor], annotations: dict[str, Any]) -> list[TemperatureSensor]:
    """Return sensor copies carrying the photograph markers; unknown sensor_ids are an error."""
    placements = placements_from_annotations(annotations)
    known = {sensor.sensor_id for sensor in sensors}
    unknown = sorted(set(placements) - known)
    if unknown:
        raise ValueError(f"annotations.json marks undeclared sensors: {', '.join(unknown)}")
    return [sensor.model_copy(update={"placement": placements[sensor.sensor_id]}) if sensor.sensor_id in placements
            else sensor for sensor in sensors]


def annotations_from_sensors(sensors: list[TemperatureSensor]) -> dict[str, Any]:
    """Write the exact ``annotations.json`` schema from placed sensors (one original image)."""
    placed = [sensor for sensor in sensors if sensor.placement is not None]
    if not placed:
        raise ValueError("No sensor carries a photograph placement")
    images = {sensor.placement.image_asset_sha256 for sensor in placed}
    if len(images) != 1:
        raise ValueError("annotations.json describes exactly one original image")
    return {"schema_version": ANNOTATIONS_SCHEMA_VERSION, "image_asset_sha256": images.pop(),
            "markers": [{"sensor_id": sensor.sensor_id, "x_norm": sensor.placement.x_norm,
                         "y_norm": sensor.placement.y_norm,
                         "label": sensor.placement.label if sensor.placement.label is not None else sensor.sensor_id}
                        for sensor in placed]}


# ---------------------------------------------------------------------------
# Thermal settling: slope of rise above ambient over a window
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SlopeVerdict:
    met: bool
    slope_C_per_min: float | None
    window_span_s: float
    samples: int
    reason: str


def least_squares_slope(series: list[tuple[float, float]]) -> float | None:
    """Slope per second of value against time; None below two distinct times."""
    if len(series) < 2:
        return None
    times = [t for t, _ in series]
    values = [v for _, v in series]
    t_mean, v_mean = mean(times), mean(values)
    denominator = sum((t - t_mean) ** 2 for t in times)
    if denominator <= 0:
        return None
    return sum((t - t_mean) * (v - v_mean) for t, v in zip(times, values)) / denominator


def evaluate_thermal_window(series: list[tuple[float, float]], policy: ThermalSettlingPolicy,
                            elapsed_s: float) -> SlopeVerdict:
    """Decide whether the retained (time, rise) window meets the declared slope criterion."""
    span = series[-1][0] - series[0][0] if len(series) >= 2 else 0.0
    slope_s = least_squares_slope(series)
    slope_min = slope_s * 60 if slope_s is not None else None
    if elapsed_s < policy.minimum_observation_s:
        reason = "minimum observation not yet reached"
    elif len(series) < policy.minimum_samples:
        reason = "insufficient consecutive electrically valid temperature samples in the window"
    elif span < policy.window_s:
        reason = "slope window not yet filled"
    elif slope_min is None or not math.isfinite(slope_min):
        reason = "slope undefined"
    elif abs(slope_min) > policy.slope_threshold_C_per_min:
        reason = f"rise slope {slope_min:.4g} C/min exceeds {policy.slope_threshold_C_per_min:g} C/min"
    else:
        return SlopeVerdict(True, slope_min, span, len(series),
                            f"rise slope {slope_min:.4g} C/min within {policy.slope_threshold_C_per_min:g} C/min over {span:.3g} s")
    return SlopeVerdict(False, slope_min, span, len(series), reason)


def thermal_policy_for(plan: Plan, test_id: str) -> ThermalSettlingPolicy | None:
    return next((test.thermal_settling for test in plan.recipe.tests if test.id == test_id), None)


def temperature_data_source(bench: BenchProfile) -> str | None:
    if not bench.temperature_sensors:
        return None
    return "synthetic" if all(s.adapter == MOCK_THERMAL_ADAPTER for s in bench.temperature_sensors) else "measured"


# ---------------------------------------------------------------------------
# Analysis: absolute temperature and rise above time-aligned ambient per point
# ---------------------------------------------------------------------------

def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _stem(quantity: str) -> str:
    return quantity[:-2] if quantity.endswith("_C") else quantity


def _window_mean(rows: list[dict], start: float, end: float) -> tuple[float | None, int]:
    inside = [r["value"] for r in rows if r["status"] == "ok" and _finite(r["value"])
              and r["query_start_monotonic_s"] >= start and r["query_end_monotonic_s"] <= end]
    return (mean(inside) if inside else None), len(inside)


def annotate_thermal_points(plan: Plan, run: dict, grouped: dict[str, list[dict]], points: list[dict]) -> None:
    """Add per-sensor absolute temperature and rise above time-aligned ambient to analysis points.

    Values exist only for a valid point's accepted acquisition window. Missing
    ambient → rise ``not_evaluated`` with a reason. Unsettled points keep their
    last observed reading labelled as such; no equilibrium is inferred.
    """
    sensors = plan.bench.temperature_sensors
    if not sensors:
        return
    by_id = {sensor.sensor_id: sensor for sensor in sensors}
    source = temperature_data_source(plan.bench)
    outcomes = {p["point_id"]: p for p in run.get("points", [])}
    for point in points:
        rows = grouped.get(point["point_id"], [])
        cycles = set(point.get("acquisition_cycle_ids", []))
        accepted = [r for r in rows if r["acquisition_cycle_id"] in cycles]
        window = ((min(r["query_start_monotonic_s"] for r in accepted), max(r["query_end_monotonic_s"] for r in accepted))
                  if accepted and point["qualification"] == "valid" else None)
        settling = outcomes.get(point["point_id"], {}).get("thermal_settling")
        policy = thermal_policy_for(plan, point["test_id"])
        if policy is None:
            qualification = "logged-only" if any(r["quantity"] in {s.quantity for s in sensors} for r in rows) else "not-run"
        elif settling and settling.get("status") == "met" and point["qualification"] == "valid":
            qualification = "settled"
        elif settling:
            qualification = "inconclusive"
        else:
            qualification = "not-run"
        details = []
        for sensor in sensors:
            if sensor.role != "surface":
                continue
            readings = [r for r in rows if r["quantity"] == sensor.quantity]
            absolute, count = _window_mean(readings, *window) if window else (None, 0)
            detail: dict[str, Any] = {"sensor_id": sensor.sensor_id, "quantity": sensor.quantity,
                                      "measured_surface": sensor.measured_surface, "data_source": source,
                                      "absolute_C": absolute, "window_samples": count,
                                      "ambient_sensor_id": sensor.ambient_reference, "ambient_C": None,
                                      "rise_C": None, "rise_status": "not_evaluated", "rise_reason": None}
            if absolute is None:
                detail["absolute_reason"] = ("no accepted acquisition window; the point is not thermally qualified"
                                             if not window else "no temperature reading inside the accepted window")
                observed = [r for r in readings if r["status"] == "ok" and _finite(r["value"])]
                if observed:
                    last = max(observed, key=lambda r: r["query_end_monotonic_s"])
                    detail["last_observed_C"] = last["value"]
                    detail["last_observed_status"] = "unsettled observation; not an equilibrium value"
            if sensor.ambient_reference is None:
                detail["rise_reason"] = "no ambient reference declared for this sensor; room temperature is not assumed"
            elif window is None:
                detail["rise_reason"] = "no accepted acquisition window"
            else:
                ambient_sensor = by_id[sensor.ambient_reference]
                ambient, ambient_count = _window_mean([r for r in rows if r["quantity"] == ambient_sensor.quantity], *window)
                detail["ambient_C"] = ambient
                if absolute is None or ambient is None:
                    detail["rise_reason"] = "time-aligned ambient or surface reading missing inside the accepted window"
                else:
                    detail.update(rise_C=absolute - ambient, rise_status="evaluated", ambient_window_samples=ambient_count,
                                  rise_reason=None)
            stem = _stem(sensor.quantity)
            point[sensor.quantity] = absolute
            point[f"{stem}_rise_C"] = detail["rise_C"]
            point[f"{stem}_rise_status"] = detail["rise_status"]
            details.append(detail)
        point["thermal"] = {"qualification": qualification, "data_source": source, "sensors": details,
                            "settling": settling}


# ---------------------------------------------------------------------------
# Report contribution: separate temperature figures, one metric, prose
# ---------------------------------------------------------------------------

def _settling_series(plan: Plan, points: list[dict], raw_samples: list[dict]) -> list[dict[str, Any]]:
    """Retained temperature-versus-time traces for the first thermally observed point."""
    by_point: dict[str, list[dict]] = defaultdict(list)
    quantities = {s.quantity: s for s in plan.bench.temperature_sensors}
    for sample in raw_samples:
        if sample.get("quantity") in quantities and sample.get("status") == "ok" and _finite(sample.get("value")):
            by_point[sample["point_id"]].append(sample)
    for point in points:
        rows = by_point.get(point["point_id"], [])
        if thermal_policy_for(plan, point["test_id"]) is None or not any(r["phase"] == THERMAL_PHASE for r in rows):
            continue
        origin = min(r["query_start_monotonic_s"] for r in rows)
        traces = []
        for quantity, sensor in quantities.items():
            readings = sorted((r for r in rows if r["quantity"] == quantity), key=lambda r: r["query_end_monotonic_s"])
            if len(readings) < 2:
                continue
            traces.append({"id": f"{point['point_id']}-{sensor.sensor_id}", "point_id": point["point_id"],
                           "quantity": quantity, "sensor_id": sensor.sensor_id,
                           "label": f"{sensor.sensor_id} · {sensor.measured_surface} · {point['vin_target_V']:g} V, "
                                    f"{point['iout_target_A']:g} A",
                           "x": [float(r["query_end_monotonic_s"] - origin) for r in readings],
                           "y": [float(r["value"]) for r in readings]})
        if traces:
            return traces
    return []


def thermal_report_contribution(plan: Plan, run: dict, points: list[dict], raw_samples: list[dict],
                                series: list[Any], evidence_label: str, boundary: str) -> dict[str, Any]:
    """Figures, metric, summary paragraphs and limitations for bound temperature channels.

    Returns empty collections when the bench binds no temperature sensor.
    Captions describe empirical relationships for the stated boundary and
    setup; they never name internal components or device parameters.
    """
    from .analysis import FigureSpec, MetricResult, SampleSeries

    empty = {"figures": [], "metrics": [], "summary": [], "limitations": [], "model": None}
    sensors = plan.bench.temperature_sensors
    if not sensors:
        return empty
    source = temperature_data_source(plan.bench)
    label = "SYNTHETIC" if source == "synthetic" else evidence_label
    surfaces = [s for s in sensors if s.role == "surface"]
    policies = {test.id: test.thermal_settling for test in plan.recipe.tests if test.thermal_settling is not None}
    figures: list[Any] = []
    metrics: list[Any] = []
    summary: list[tuple[str, list[str]]] = []
    valid = [p for p in points if p["qualification"] == "valid"]
    sensor_text = "; ".join(f"{s.sensor_id}: {s.measured_surface} ({s.sensor_type}, {s.attachment_method})" for s in surfaces)
    for sensor in surfaces:
        stem = _stem(sensor.quantity)
        if any(_finite(p.get(sensor.quantity)) for p in valid):
            figures.append(FigureSpec(id=f"fig-temperature-{sensor.sensor_id.lower()}", title=f"Surface Temperature · {sensor.sensor_id}",
                x_key="Iout_A", y_key=sensor.quantity, x_label="Output Current (A)", y_label="Temperature (°C)",
                series=series,
                caption=f"{label}. Absolute temperature of the {sensor.measured_surface} (sensor {sensor.sensor_id}, "
                        f"{sensor.sensor_type}, {sensor.attachment_method}); each marker is the mean over the point's accepted "
                        "acquisition window. Temperature is plotted on its own figure, separate from efficiency and voltage. "
                        + ("These are outputs of a first-order synthetic model, not sensor observations." if source == "synthetic"
                           else "Calibration status: " + sensor.calibration_status + ".")))
        if any(_finite(p.get(f"{stem}_rise_C")) and _finite(p.get("loss_W")) for p in valid):
            figures.append(FigureSpec(id=f"fig-temperature-rise-loss-{sensor.sensor_id.lower()}",
                title=f"Surface Rise vs Measured Loss · {sensor.sensor_id}",
                x_key="loss_W", y_key=f"{stem}_rise_C", x_label="Measured Path Loss (W)",
                y_label="Rise above time-aligned ambient (°C)", series=series,
                caption=f"{label}. Rise of the {sensor.measured_surface} above the time-aligned ambient reading "
                        f"({sensor.ambient_reference}) against total measured loss across {boundary}. This is an empirical "
                        "relationship for the stated boundary and setup only: the loss includes input wiring, and the "
                        "surface is an accessible external location. It does not identify internal component temperatures "
                        "or any device parameter."))
    traces = _settling_series(plan, points, raw_samples)
    if traces:
        policy = next(iter(policies.values()))
        figures.append(FigureSpec(id="fig-thermal-settling", title="Thermal Settling · Temperature vs Time",
            x_key="thermal_elapsed_s", y_key="temperature_C", x_label="Time since first temperature reading (s)",
            y_label="Temperature (°C)", series=[],
            sample_series=[SampleSeries(**trace) for trace in traces],
            caption=f"{label}. Retained temperature time series for one thermally observed point. The draft criterion "
                    f"requires |d(rise)/dt| ≤ {policy.slope_threshold_C_per_min:g} °C/min over {policy.window_s:g} s after at "
                    f"least {policy.minimum_observation_s:g} s, with electrically valid readings, before the {policy.timeout_s:g} s "
                    "timeout; a timeout leaves the point inconclusive. Every retained reading is shown; nothing is interpolated."))
    rises = [(p, s) for p in valid for s in p.get("thermal", {}).get("sensors", []) if _finite(s.get("rise_C"))]
    if rises:
        point, detail = max(rises, key=lambda item: item[1]["rise_C"])
        figure_id = f"fig-temperature-rise-loss-{detail['sensor_id'].lower()}"
        metrics.append(MetricResult(id="highest-observed-surface-rise", label="Highest observed surface rise above ambient",
            value=detail["rise_C"], unit="°C",
            formula="mean(T_surface) − mean(T_ambient) over the same accepted acquisition window",
            conditions=f"{detail['measured_surface']} (sensor {detail['sensor_id']}); {point['vin_target_V']:g} V requested input, "
                       f"{point['iout_target_A']:g} A requested load",
            selector={"point_id": point["point_id"]}, point_ids=[point["point_id"]],
            figure_ids=[figure_id] if any(f.id == figure_id for f in figures) else []))
    observed = [p for p in points if p.get("thermal", {}).get("settling")]
    met = [p for p in observed if p["thermal"]["qualification"] == "settled"]
    timed_out = [p for p in observed if p["thermal"]["qualification"] == "inconclusive"]
    if policies:
        policy = next(iter(policies.values()))
        summary.append((f"Temperature ({label}): {len(met)} of {len(observed)} thermally observed points met the draft thermal-settling "
                        f"criterion (|d(rise)/dt| ≤ {policy.slope_threshold_C_per_min:g} °C/min over {policy.window_s:g} s after at least "
                        f"{policy.minimum_observation_s:g} s, timeout {policy.timeout_s:g} s); {len(timed_out)} timed out and remain "
                        "inconclusive with their time series retained. The criterion is unvalidated for this module, sensor and setup.", []))
    elif surfaces:
        summary.append((f"Temperature ({label}) was logged during electrical settling and acquisition; no thermal settling criterion "
                        "was declared, so no point is thermally qualified.", []))
    if metrics:
        m = metrics[0]
        summary.append((f"Highest observed surface rise above time-aligned ambient: {m.value:.2f} °C at {m.conditions}. "
                        "Rise versus measured path loss is an empirical relationship for this boundary and setup.", [m.id]))
    limitations = [
        (f"SYNTHETIC temperature: channels {', '.join(s.quantity for s in sensors)} come from the first-order mock thermal model "
         f"({run.get('thermal_model', {}).get('model_version', 'version not recorded')}), not from sensors on the physical DUT."
         if source == "synthetic" else
         f"Temperature channels {', '.join(s.quantity for s in sensors)} are measured; calibration status per sensor is recorded in the bench profile."),
        f"Temperature sensors — {sensor_text}. Internal component positions are unknown; no reading is a junction temperature.",
        "A surface-rise-versus-loss slope is an empirical relationship for the stated boundary and setup; it is not component "
        "thermal resistance or a junction-temperature estimator, and source-path loss including input wiring is not isolated module dissipation.",
        "Thermal settling criteria are drafts that require validation for the module, sensor and setup; a timed-out point is "
        "inconclusive, never an assumed equilibrium.",
    ]
    if any(s.role == "surface" and s.ambient_reference is None for s in sensors):
        limitations.append("A surface sensor without an ambient reference has no rise evaluation; room temperature is not assumed.")
    model = {"data_source": source,
             "label": ("SYNTHETIC temperature model output; not sensor observations of the physical DUT"
                       if source == "synthetic" else "MEASURED temperature channels"),
             "sensors": [{**s.model_dump(mode="json"), "data_source": source} for s in sensors],
             "settling_policies": {test_id: policy.model_dump(mode="json") for test_id, policy in policies.items()},
             "points": [{"point_id": p["point_id"], "thermal_qualification": p.get("thermal", {}).get("qualification", "not-run"),
                         "settling": p.get("thermal", {}).get("settling")} for p in points],
             "provider": run.get("thermal_model")}
    return {"figures": figures, "metrics": metrics, "summary": summary, "limitations": limitations, "model": model}
