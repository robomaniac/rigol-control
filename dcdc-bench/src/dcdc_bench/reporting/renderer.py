"""Quarto documents from one already-analyzed model; no instrument dependencies.

The renderer formats supplied results. It does not calculate efficiency,
regulation, uncertainty, or narrative conditions independently of analysis.
"""
from __future__ import annotations

import copy
import asyncio
import csv
import hashlib
import html
import importlib.metadata
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# The issued CSV export guards text cells exactly as the analysis export does.
from ..analysis import _safe_cell
from .sensor_placement import with_sensor_placement
from ..resources import children_peak_rss_mib, session_survivors, terminate_group, try_log_event

PROJECT = Path(__file__).resolve().parents[3]
TEMPLATES = PROJECT / "templates"
# Engineering curves need distinct hues and shapes in both screen and print.
# Keep the familiar 12/24/36 V conditions stable even in a single-voltage report.
COLORS = ("#0072B2", "#D55E00", "#CC33AA", "#009E73", "#00A6C8", "#805400")
TRACE_PATTERNS = (("solid", "circle"), ("dash", "square"), ("dot", "diamond"),
                  ("dashdot", "triangle-up"), ("longdash", "triangle-down"),
                  ("longdashdot", "cross"))
VOLTAGE_STYLE_INDEX = {"12": 0, "24": 1, "36": 2}
STAGE_STYLE_INDEX = {"increasing-load": 0, "sustained-load": 1, "decreasing-load": 2}
TABLE_LAYOUTS = {
    "key-value": (38, 62),
    "equipment": (10, 16, 24, 22, 28),
    "bench-profile": (12, 24, 44, 20),
    "voltage-comparison": (20, 19, 18, 18, 25),
    "voltage-outcomes": (22, 14, 20, 44),
    "startup-readings": (25, 25, 25, 25),
    "exclusions": (10, 13, 17, 20, 40),
}
FIELDS = ("Vin_V", "Iin_A", "Vout_V", "Iout_A", "Pin_W", "Pout_W", "loss_W",
          "efficiency_pct", "vout_error_pct")
# A cold headless browser alone takes about 27 s on the 1 GB bench Pi.
# Allow its local Plotly bootstrap to finish under swap pressure; acquisition
# deadlines are independent and unchanged by this document-build timeout.
STATIC_START_TIMEOUT_S = 120
STATIC_IMAGE_TIMEOUT_S = 90
STATIC_CLOSE_TIMEOUT_S = 15
DOCUMENT_TIMEOUT_S = 600


class ReportRenderError(RuntimeError):
    def __init__(self, message: str, manifest: dict | None = None):
        super().__init__(message)
        self.manifest = manifest or {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)


def _embedded_json(value: Any) -> str:
    return _json(value).replace("&", "\\u0026").replace("<", "\\u003c").replace(
        ">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _md(value: Any) -> str:
    """Only renderer-owned strings may introduce Markdown/Typst/raw HTML."""
    text = "unknown" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]<>#!|@$])", r"\\\1", text)


def _number(value: Any) -> str:
    if value is None:
        return "not available"
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return f"{value:.6g}"
    return str(value)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: Any) -> float | None:
    return float(value) if _finite(value) and value > 0 else None


def _count_word(count: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
    return words[count] if 0 <= count < len(words) else str(count)


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _condition_phrase(condition: dict) -> str:
    """'24 V' for a condition programmed as requested; 'nominal 36 V' otherwise."""
    nominal, programmed = condition["nominal_input_V"], condition.get("programmed_input_V")
    if not _finite(programmed) or programmed == nominal:
        return f"{nominal:g} V"
    return f"nominal {nominal:g} V"


def _input_conditions(model: dict) -> list[dict]:
    """Recorded input conditions in the order the analysis compared them.

    Values come from the analysis comparison rows or, failing that, from the
    sweep's recorded nominal/programmed setpoints. A row without a finite
    nominal voltage is not described; no condition is assumed from a recipe.
    """
    execution = model.get("execution", {})
    rows = execution.get("voltage_comparison") or []
    conditions = [{"nominal_input_V": float(row["nominal_input_V"]),
                   "programmed_input_V": row.get("programmed_input_V"),
                   "phase_status": row.get("phase_status")}
                  for row in rows if isinstance(row, dict) and _finite(row.get("nominal_input_V"))]
    if conditions:
        return conditions
    sweep = execution.get("voltage_efficiency_sweep") or {}
    nominals, programmed = sweep.get("nominal_input_voltages_V"), sweep.get("programmed_input_voltages_V")
    if isinstance(nominals, list) and nominals and all(_finite(value) for value in nominals):
        if not (isinstance(programmed, list) and len(programmed) == len(nominals)):
            programmed = [None] * len(nominals)
        phases = {phase.get("nominal_input_V"): phase for phase in sweep.get("phases", []) if isinstance(phase, dict)}
        return [{"nominal_input_V": float(nominal), "programmed_input_V": setpoint,
                 "phase_status": phases.get(nominal, {}).get("status")}
                for nominal, setpoint in zip(nominals, programmed)]
    return []


def _source_current_limit(model: dict, method: dict | None) -> float | None:
    """The recorded supply current setting, or None when no evidence records one."""
    limit = _positive((method or {}).get("input_current_limit_A"))
    if limit is None:
        controls = model.get("bench", {}).get("protective_controls")
        limit = _positive(controls.get("source_current_limit_A")) if isinstance(controls, dict) else None
    return limit


def _temperature_note(model: dict) -> str | None:
    """State that temperature was not acquired only when the bindings show none.

    An empty or missing binding table is unknown, not evidence of absence.
    """
    bindings = model.get("bench", {}).get("measurements")
    if not isinstance(bindings, dict) or not bindings:
        return None
    for name, binding in bindings.items():
        unit = str(binding.get("unit", "")) if isinstance(binding, dict) else ""
        quantity = str(binding.get("quantity", name)) if isinstance(binding, dict) else str(name)
        normalized = unit.strip().casefold().replace("℃", "c").replace("°", "").removeprefix("deg").strip()
        if normalized in ("c", "k") or re.search(r"(?i)temp|_C$", quantity):
            return None
    return ("No temperature measurement channel is bound in this bench profile, "
            "so temperature was not acquired.")


def validate_report_model(model: dict) -> dict:
    """Reject invalid references and active identifier syntax before writing files."""
    try:
        _json(model)
    except (ValueError, TypeError) as exc:
        raise ValueError("Report model must contain finite, JSON-serializable data") from exc
    for name in ("run_id", "analysis_id", "dut", "points", "figures", "metrics"):
        if name not in model:
            raise ValueError(f"Report model is missing {name}")
    points = {p["point_id"]: p for p in model["points"]}
    if len(points) != len(model["points"]):
        raise ValueError("Duplicate point IDs in report model")
    figure_ids: set[str] = set()
    for figure in model["figures"]:
        fid = figure["id"]
        if not re.fullmatch(r"fig-[a-z0-9][a-z0-9-]*", fid):
            raise ValueError(f"Unsafe figure identifier: {fid!r}")
        if fid in figure_ids:
            raise ValueError(f"Duplicate figure identifier: {fid}")
        figure_ids.add(fid)
        for key in ("x_key", "y_key"):
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", figure[key]):
                raise ValueError(f"Invalid figure quantity: {figure[key]!r}")
        seen: set[str] = set()
        for series in figure["series"]:
            if series["id"] in seen:
                raise ValueError("Duplicate series identifier")
            seen.add(series["id"])
            if not set(series["point_ids"]) <= points.keys():
                raise ValueError(f"Figure {fid} references a missing point")
        for series in figure.get("sample_series", []):
            if series["point_id"] not in points:
                raise ValueError(f"Figure {fid} references a missing point")
            if len(series["x"]) != len(series["y"]):
                raise ValueError(f"Figure {fid} sample series lengths differ")
    for metric in model["metrics"]:
        if not set(metric.get("point_ids", [])) <= points.keys():
            raise ValueError("Metric references a missing point")
        if not set(metric.get("figure_ids", [])) <= figure_ids:
            raise ValueError("Metric references a missing figure")
    return model


def _identity(model: dict) -> str:
    dut = model["dut"]
    return str(dut.get("identity", {}).get("model", dut.get("model", dut.get("name", "DUT"))))


def _footer(model: dict, figure: dict, conditions: str = "canonical conditions") -> str:
    return (f"{model.get('evidence_label', 'Evidence status not supplied')} | {_identity(model)} | "
            f"Run {model['run_id']} | Analysis {model['analysis_id']}<br>"
            f"{figure['id']} | {conditions}<br>"
            f"Boundary: {model.get('boundary', 'not supplied')} | "
            "Aggregated settled DC points; uncertainty unquantified unless explicitly supplied")


def _stage_transition_pairs(model: dict, spec: dict) -> list[tuple[dict, dict]]:
    """Join only adjacent, qualified stage endpoints in the recorded sequence.

    Walking the complete point list preserves gaps from invalid or omitted
    windows. Recorded-time adjacency additionally rejects out-of-order windows.
    These pairs are drawing instructions, never new observations or point IDs.
    """
    if (spec["id"] != "fig-demand-time" or spec["x_key"] != "elapsed_s"
            or spec["y_key"] != "Iout_A"):
        return []

    def finite(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))

    included = {pid for series in spec["series"] for pid in series["point_ids"]}
    sequence = model["points"]
    by_id = {point["point_id"]: point for point in sequence}
    executed = model.get("execution", {}).get("executed_point_ids")
    if (isinstance(executed, list) and all(isinstance(pid, str) and pid in by_id for pid in executed)
            and len(set(executed)) == len(executed)
            and all(point["point_id"] in executed for point in sequence
                    if point.get("qualification") in ("valid", "inconclusive"))):
        # This policy record distinguishes uncommanded conditional candidates
        # from failed attempted windows; an ordinary display filter cannot.
        sequence = [by_id[pid] for pid in executed]
    timed = sorted((point for point in sequence if finite(point.get("elapsed_s"))),
                   key=lambda point: point["elapsed_s"])
    next_in_time = {before["point_id"]: after["point_id"]
                    for before, after in zip(timed, timed[1:])}
    pairs = []
    for before, after in zip(sequence, sequence[1:]):
        if not all(point["point_id"] in included and point.get("qualification") == "valid"
                   and all(finite(point.get(key)) for key in ("elapsed_s", "Iout_A", "vin_target_V"))
                   and point.get("phase_label") for point in (before, after)):
            continue
        if (before["phase_label"] == after["phase_label"]
                or before["vin_target_V"] != after["vin_target_V"]
                or before["elapsed_s"] >= after["elapsed_s"]
                or next_in_time.get(before["point_id"]) != after["point_id"]):
            continue
        pairs.append((before, after))
    return pairs


def _condition_key(series: dict) -> str:
    value = series.get("selection_key") or series.get("vin_target_V", series["id"])
    # JSON numbers such as 12.0 become "12" in JavaScript String().
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return str(int(value)) if int(value) == value else str(value)
    return str(value)


def _condition_styles(model: dict) -> dict[str, dict[str, str]]:
    """One style registry shared by static figures and interactive reports.

    Known voltage/stage styles survive missing curves and figure reordering.
    Other conditions are assigned in a deterministic order within this report.
    Reserving a style never creates a trace, legend entry or measurement.
    """
    conditions = {}
    for spec in model["figures"]:
        for series in spec["series"]:
            conditions.setdefault(_condition_key(series), series)
    if conditions and all(not series.get("selection_key") and
            isinstance(series.get("vin_target_V"), (float, int)) and
            not isinstance(series["vin_target_V"], bool) and
            math.isfinite(series["vin_target_V"]) for series in conditions.values()):
        conditions = dict(sorted(conditions.items(), key=lambda item: item[1]["vin_target_V"]))
        sweep = model.get("execution", {}).get("voltage_efficiency_sweep") or {}
        declared = sweep.get("nominal_input_voltages_V", [])
        if isinstance(declared, list) and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) for value in declared):
            # Reserve the original condition palette for a continuation run.
            # A reserved color creates no trace, legend entry or measurement.
            reserved = {_condition_key({"vin_target_V": value, "id": ""}): None for value in sorted(set(declared))}
            conditions = {**reserved, **conditions}
    fixed = {}
    for key, series in conditions.items():
        if series is None or not series.get("selection_key"):
            if key in VOLTAGE_STYLE_INDEX:
                fixed[key] = VOLTAGE_STYLE_INDEX[key]
        else:
            stage = next((name for name in STAGE_STYLE_INDEX
                          if key == name or key.startswith(name + "-v")), None)
            if stage:
                fixed[key] = STAGE_STYLE_INDEX[stage]
    # Reserve all three standard styles for voltage conditions, including
    # conditions absent from this particular report. Additional voltages then
    # cannot take a standard voltage's color merely because it is missing.
    voltage_grid = all(series is None or not series.get("selection_key")
                       for series in conditions.values())
    available = [index for index in range(len(COLORS))
                 if index not in (set(VOLTAGE_STYLE_INDEX.values()) if voltage_grid else set(fixed.values()))]
    if not available:
        available = list(range(len(COLORS)))
    remaining = sorted((key for key in conditions if key not in fixed),
                       key=lambda key: (0, float(key)) if re.fullmatch(r"-?\d+(?:\.\d+)?", key) else (1, key))
    assigned = {key: available[index % len(available)] for index, key in enumerate(remaining)}
    assigned.update(fixed)
    return {key: {"color": COLORS[assigned[key]], "dash": TRACE_PATTERNS[assigned[key]][0],
                  "symbol": TRACE_PATTERNS[assigned[key]][1]} for key in conditions}


def _condition_colors(model: dict) -> dict[str, str]:
    """Retain the color-only registry used by existing report controls."""
    return {key: style["color"] for key, style in _condition_styles(model).items()}


def _figure_references(model: dict) -> dict[str, dict]:
    """Display supplied nominal/limit values without inventing observations.

    The same registry is embedded for HTML and used by the static plots. Its
    initial ranges include the reference and qualified finite plotted values;
    they do not establish accuracy, tolerance or additional measured results.
    """
    def finite(value):
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

    points = {point["point_id"]: point for point in model["points"]}
    nominal = model.get("dut", {}).get("ratings", {}).get("output_voltage_nominal_V")
    execution = model.get("execution", {})
    search = execution.get("source_limit_search") or execution.get("voltage_efficiency_sweep") or {}
    current_limit = search.get("input_current_limit_A")
    result = {}
    for spec in model["figures"]:
        source_current = spec["id"] == "fig-source-current" and spec["y_key"] == "Iin_A"
        value = nominal if spec["y_key"] == "Vout_V" else current_limit if source_current else None
        if not finite(value) or value <= 0:
            continue
        values = [float(value), *([0.] if source_current else [])]
        for series in spec["series"]:
            for pid in series["point_ids"]:
                point = points[pid]
                if (point.get("qualification") != "valid" or not finite(point.get(spec["x_key"]))
                        or not finite(point.get(spec["y_key"]))):
                    continue
                # Keep any supplied display band in view as well as the mean.
                values.extend(float(point[key]) for key in (spec["y_key"], spec.get("lower_key"), spec.get("upper_key"))
                              if key and finite(point.get(key)))
        low, high = min(values), max(values)
        padding = max(.08 * (high - low), .001 * abs(value), .001)
        result[spec["id"]] = {"value": value,
            "label": f"Supply limit {value:g} A" if source_current else f"Nominal {value:g} V",
            "y_range": [low - padding, high + padding]}
    return result


def _plot_figure(model: dict, spec: dict, number: int):
    if model.get("kind") == "comparison":
        from .comparison import plot_comparison_figure
        return plot_comparison_figure(model, spec, number)
    import plotly.graph_objects as go

    points = {p["point_id"]: p for p in model["points"]}
    figure = go.Figure()
    # Draw guides behind the existing measured markers and stage curves.
    for before, after in _stage_transition_pairs(model, spec):
        figure.add_trace(go.Scatter(x=[before["elapsed_s"], after["elapsed_s"]],
            y=[before["Iout_A"], after["Iout_A"]], mode="lines",
            line={"color": "#91a1ad", "width": 1.5, "dash": "dot"},
            showlegend=False, hoverinfo="skip", connectgaps=False,
            meta={"isTransition": True}))
    conditions = []
    plotted_currents: set[float] = set()
    # The same condition keeps its color across both formats and every figure,
    # including a hold-only panel with a subset of the sequence's conditions.
    condition_styles = _condition_styles(model)
    for index, series in enumerate(spec["series"]):
        rows = [points[pid] for pid in series["point_ids"]]
        valid = [p.get("qualification") == "valid" for p in rows]
        x = [p.get(spec["x_key"]) for p in rows]
        y = [p.get(spec["y_key"]) if okay else None for p, okay in zip(rows, valid)]
        plotted = [(float(horizontal), float(value)) for horizontal, value in zip(x, y)
            if isinstance(horizontal, (int, float)) and not isinstance(horizontal, bool)
            and isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(horizontal) and math.isfinite(value)]
        # Keep requested points in the report model/evidence controls, but do
        # not imply a measured curve exists through an empty legend entry.
        if not plotted:
            continue
        style = condition_styles[_condition_key(series)]
        color = style["color"]
        condition = str(series.get("label", series["id"]))
        conditions.append(condition)
        if spec["x_key"] == "Iout_A":
            plotted_currents.update(current for current, _ in plotted)
        lower, upper = spec.get("lower_key"), spec.get("upper_key")
        if lower and upper:
            for key, fill in ((lower, None), (upper, "tonexty")):
                figure.add_trace(go.Scatter(x=x, y=[p.get(key) if okay else None
                    for p, okay in zip(rows, valid)], mode="lines", line={"width": 0},
                    fill=fill, fillcolor=_rgba(color, .13), showlegend=False,
                    legendgroup=series["id"], hoverinfo="skip", connectgaps=False))
        figure.add_trace(go.Scatter(x=x, y=y, name=html.escape(condition),
            mode="lines+markers" if series.get("connect_points", True) else "markers",
            line={"width": 2, "color": color, "dash": style["dash"]},
            marker={"size": 9, "color": color, "symbol": style["symbol"]}, connectgaps=False,
            legendgroup=series["id"], customdata=[p["point_id"] for p in rows],
            hovertemplate="%{customdata}<br>%{x:.6g}<br>%{y:.6g}<extra>%{fullData.name}</extra>"))
    # Retained raw time series (e.g. thermal settling) are drawn exactly as supplied.
    for index, series in enumerate(spec.get("sample_series", [])):
        color = COLORS[index % len(COLORS)]
        label = str(series.get("label", series["id"]))
        conditions.append(label)
        figure.add_trace(go.Scatter(x=list(series["x"]), y=list(series["y"]), name=html.escape(label),
            mode="lines+markers", line={"width": 1.5, "color": color}, marker={"size": 5, "color": color},
            connectgaps=False, legendgroup=series["id"],
            hovertemplate="%{x:.6g} s<br>%{y:.6g}<extra>%{fullData.name}</extra>"))
    footer = _footer(model, spec, "; ".join(conditions) or "no qualified plotted conditions")
    # Every user supplied segment is escaped before entering Plotly rich text.
    footer = "<br>".join(html.escape(line) for line in footer.split("<br>"))
    figure.update_layout(template="plotly_white", width=1080, height=530,
        font={"family": "DejaVu Sans, Arial, sans-serif", "size": 16, "color": "#183047"},
        title={"text": f"Figure {number}. {html.escape(spec['title'])}", "x": .06,
               "font": {"size": 19}},
        margin={"l": 75, "r": 28, "t": 70, "b": 135},
        legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 14}},
        xaxis={"title": html.escape(spec["x_label"]), "gridcolor": "#e6edf1", "zeroline": False},
        yaxis={"title": html.escape(spec["y_label"]), "gridcolor": "#e6edf1", "zeroline": False},
        annotations=[{"text": footer, "xref": "paper", "yref": "paper", "x": 0, "y": -.24,
            "xanchor": "left", "yanchor": "top", "align": "left", "showarrow": False,
            "font": {"size": 12, "color": "#516677"}}])
    figure.update_xaxes(tickformat="~g", nticks=7)
    figure.update_yaxes(tickformat="~g", nticks=6)
    reference = _figure_references(model).get(spec["id"])
    if reference:
        figure.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y",
            y0=reference["value"], y1=reference["value"],
            line={"color": "#77828c", "width": 1.2, "dash": "dash"}, layer="below")
        figure.add_annotation(xref="paper", x=0, yref="y", y=reference["value"],
            text=html.escape(reference["label"]), showarrow=False, xanchor="left", yanchor="bottom",
            font={"size": 11, "color": "#596773"}, bgcolor="rgba(255,255,255,0.9)")
        figure.update_yaxes(range=reference["y_range"], autorange=False)
    # Plotly otherwise gives a lone ~0.1 A observation a misleading negative
    # current axis. Keep ordinary autoscaling for every multi-current figure.
    if len(plotted_currents) == 1:
        current = next(iter(plotted_currents))
        if current > 0:
            figure.update_xaxes(range=[0, 2 * current], autorange=False)
    return figure


def _rgba(color: str, alpha: float) -> str:
    return f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},{alpha})"


def _rows_table(headers: list[str], rows: list[list[Any]], *, layout: str | None = None) -> str:
    table = "\n".join(["| " + " | ".join(_md(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(_md(c) for c in row) + " |" for row in rows)])
    if layout is None:
        return table
    widths = TABLE_LAYOUTS[layout]
    if len(widths) != len(headers):
        raise ValueError("Table layout does not match its columns")
    # Quarto carries these widths to both HTML colgroups and Typst columns.
    # Named wrappers let the HTML apply only the relevant responsive behavior.
    widths_text = ",".join(str(width) for width in widths)
    return (f"::: {{.report-table .table-{layout}}}\n\n{table}\n\n"
            f': {{tbl-colwidths="[{widths_text}]"}}\n\n:::')


def _equipment_rows(identities: dict) -> list[list[str]]:
    """Separate reported fields without turning an instrument reply into markup."""
    def field(identity, key):
        value = identity.get(key) if isinstance(identity, dict) else None
        return str(value).strip() if isinstance(value, (str, int, float)) and str(value).strip() else "not reported"

    return [[str(role).capitalize(), *(field(identity, key) for key in
             ("model", "serial", "firmware", "manufacturer"))]
            for role, identity in identities.items()]


def _display_quantity(value: Any, unit: str, decimals: int) -> str:
    """Presentation precision only; exports retain the supplied numeric value."""
    if value is None:
        return "not available"
    return f"{value:.{decimals}f} {unit}"


def _voltage_comparison_rows(comparison: list[dict]) -> list[list[str]]:
    rows = []
    for condition in comparison:
        peak = _display_quantity(condition.get("peak_efficiency_pct"), "%", 2)
        if condition.get("peak_efficiency_pct") is not None and condition.get("peak_efficiency_current_A") is not None:
            peak += " at " + _display_quantity(condition["peak_efficiency_current_A"], "A", 2)
        rows.append([condition.get("label") or f"{_number(condition.get('nominal_input_V'))} V input",
            _display_quantity(condition.get("reference_measured_input_V"), "V", 3),
            _display_quantity(condition.get("reference_efficiency_pct"), "%", 2),
            _display_quantity(condition.get("highest_load_A"), "A", 3), peak])
    return rows


def _phase_outcome(value: Any) -> str:
    labels = {"previous-attempt-unqualified": "Earlier startup stopped", "not-run": "Not started",
              "completed": "Completed", "aborted": "Stopped", "running": "In progress"}
    return labels.get(value, str(value).replace("_", " ").replace("-", " ").capitalize()) if value else "Not reported"


def _body(model: dict) -> str:
    if model.get("kind") == "comparison":
        from .comparison import comparison_body
        return comparison_body(model)
    evidence = str(model.get("evidence_label", "Evidence type unknown"))
    out = ["## Summary {#summary}", "", f"**{_md(evidence)} — {_md(model.get('boundary', 'Boundary not supplied'))}.**",
        "", "This issued summary is fixed. Reader filters change exploratory views only.", ""]
    metrics = model["metrics"]
    metric_registry = {metric["id"]: metric for metric in metrics}
    figure_registry = {figure["id"] for figure in model["figures"]}
    source_search = model.get('execution', {}).get('source_limit_search')
    voltage_sweep = model.get('execution', {}).get('voltage_efficiency_sweep')
    voltage_comparison = model.get('execution', {}).get('voltage_comparison', [])
    prior_input_attempt = voltage_sweep.get('prior_input_attempt') if voltage_sweep else None
    summary_references = {item["paragraph_index"]: item["metric_ids"]
                          for item in model.get("summary_evidence", [])}
    for index, text in enumerate(model.get("summary", [])):
        figure_ids = []
        for metric_id in summary_references.get(index, []):
            if metric_id not in metric_registry:
                raise ValueError("Summary reference targets a missing metric")
            for fid in metric_registry[metric_id].get("figure_ids", []):
                if fid not in figure_registry or not re.fullmatch(r"fig-[a-z0-9][a-z0-9-]*", fid):
                    raise ValueError("Summary reference targets an invalid figure")
                if fid not in figure_ids:
                    figure_ids.append(fid)
        # Prose remains escaped data. Only validated registry IDs introduce
        # Quarto cross-references; numbering follows the issued figure order.
        reference = " See " + ", ".join("@" + fid for fid in figure_ids) + "." if figure_ids else ""
        out += [_md(text) + reference, ""]
    # Narrative conditions are read from the model; a value the evidence does
    # not record leaves its sentence out rather than falling back to a recipe.
    conditions = _input_conditions(model) if voltage_sweep else []
    prior_conditions = [c for c in conditions if c.get("phase_status") == "previous-attempt-unqualified"]
    continued_conditions = [c for c in conditions if c.get("phase_status") != "previous-attempt-unqualified"]
    if prior_input_attempt and not prior_conditions and _finite(prior_input_attempt.get("nominal_input_V")):
        prior_conditions = [{"nominal_input_V": float(prior_input_attempt["nominal_input_V"]),
                             "programmed_input_V": None}]
    prior_phrase = _join([_condition_phrase(c) for c in prior_conditions]) or None
    continued_phrase = _join([_condition_phrase(c) for c in continued_conditions]) or None
    source_limit = _source_current_limit(model, voltage_sweep) if voltage_sweep else None
    if voltage_sweep and voltage_comparison:
        loads = {float(row["reference_load_A"]) for row in voltage_comparison
                 if isinstance(row, dict) and _finite(row.get("reference_load_A"))}
        reference_load = loads.pop() if len(loads) == 1 else None
        at_reference = f"at {reference_load:g} A" if reference_load is not None else "at the reference load"
        intro = []
        if reference_load is not None:
            intro.append(f"Compare the curves at the same {reference_load:g} A requested output load.")
        if source_limit is not None:
            intro.append("Each curve can reach a different maximum load because the supply is limited to "
                         f"{source_limit:g} A at its output.")
        out += ["### Efficiency at each input voltage", "", *([" ".join(intro), ""] if intro else []),
            _rows_table(["Input condition", f"Measured input {at_reference}", f"Efficiency {at_reference}",
                         "Highest qualified load", "Best observed efficiency"],
                        _voltage_comparison_rows(voltage_comparison), layout="voltage-comparison"), "",
            "Only qualified measurements are shown. Best observed efficiency describes the measured grid; "
            "it is not an interpolated optimum. " + ("See @fig-efficiency." if "fig-efficiency" in figure_registry else ""), ""]
        if prior_input_attempt:
            plural = len(prior_conditions) > 1
            out += [(f"The {prior_phrase} condition{'s were' if plural else ' was'} attempted in an earlier run "
                     "and produced no qualified efficiency result. " if prior_phrase else
                     "An earlier run attempted an input condition and produced no qualified efficiency result. ")
                    + f"{'They' if plural else 'It'} therefore {'have' if plural else 'has'} no efficiency curve. "
                    + (f"This run continues with {continued_phrase}. " if continued_phrase else "")
                    + "See the [earlier startup observations](#prior-input-attempt).", ""]
    if metrics and not (voltage_sweep and voltage_comparison):
        # References below are renderer-owned and target the validated figure registry.
        out += ["| Result | Value | Conditions and evidence |", "| --- | ---: | --- |"]
        for metric in [m for i, m in enumerate(metrics) if i == 0 or m['id'] == 'highest-qualified-input-current']:
            refs = ", ".join("@" + fid for fid in metric.get("figure_ids", []))
            value = metric.get("value")
            display_value = (f"{value:.2f}" if metric.get("id") == "highest-observed-efficiency"
                             and isinstance(value, (int, float)) else _number(value))
            uncertainty = metric.get("uncertainty") or {}
            # ± text appears only for an evaluated budget (UNC-02); k is stated, never "95 %".
            cell = (f"{uncertainty['label']} (k = {_number(uncertainty.get('k'))})"
                    if _finite(uncertainty.get("expanded")) and isinstance(uncertainty.get("label"), str)
                    else f"{display_value} {metric.get('unit','')}")
            out.append(f"| {_md(metric['label'])} | {_md(cell)} | "
                       f"{_md(metric.get('conditions',''))} {refs} |")
        out.append("")
    coverage = model.get("coverage", {})
    if coverage:
        rows = []
        for test, counts in coverage.items():
            if isinstance(counts, dict):
                rows.append([test, counts.get("requested", "unknown"), counts.get("valid", 0),
                    "; ".join(f"{k}: {v}" for k,v in counts.items() if k not in ("requested", "valid")) or "none"])
        if rows:
            out += ["### Coverage", "", _rows_table(["Test", "Declared candidates" if source_search or voltage_sweep else "Requested", "Valid", "Other outcomes"], rows), ""]
    budget = model.get("uncertainty") or {}
    qualification_text = ("uncertainty unquantified" if not budget.get("evaluated_point_ids") else
                          f"uncertainty {str(budget.get('status', 'not_evaluated')).replace('_', ' ')} from declared readback "
                          f"specifications ({budget.get('metrology', 'unquantified')}); ± values use k = "
                          f"{_number(budget.get('coverage_factor'))} and are not validated 95 % intervals")
    out += ["", f"**Qualification:** {_md(evidence.lower())} observations; {_md(qualification_text)}. "
            "This partial-power DC grid does not qualify rated power, temperature, ripple or transient behavior.", ""]
    stages = list(dict.fromkeys(point.get("phase_label") for point in model["points"] if point.get("phase_label")))
    if stages or voltage_sweep or model.get("execution", {}).get("startup_descent"):
        out += ["```{=typst}", "#pagebreak()", "```", ""]
    out += ["", "## Device under test {#dut}", ""]
    dut = model["dut"]
    identity = dut.get("identity", dut)
    identity_rows = [["Model", _identity(model)], ["Sample", identity.get("sample_id") or "not assigned"],
                     ["Brand on sample label", identity.get("actual_brand_on_label") or "unknown"],
                     ["Owner-provided aliases", ", ".join(identity.get("brand_aliases", [])) or "none"],
                     ["Topology / controller / isolation", "unknown — black-box characterization"]]
    if identity_rows:
        out += [_rows_table(["Identity", "Recorded value"], identity_rows, layout="key-value"), ""]
    ratings = dut.get("ratings", {})
    if ratings:
        rows = [["Input operating range", f"{ratings.get('input_voltage_min_V')}–{ratings.get('input_voltage_max_V')} V"],
                ["Nominal output", f"{ratings.get('output_voltage_nominal_V')} V"],
                ["Rated output", f"{ratings.get('output_current_rated_A')} A / {ratings.get('output_power_rated_W')} W"],
                ["Rating origin", ratings.get("origin", "unknown")],
                ["Sample-label verification", "yes" if ratings.get("verified_from_sample_label") else "not verified"]]
        out += [_rows_table(["Rating / evidence", "Recorded value"], rows, layout="key-value"), ""]
    out += ["Schematic and sample photographs: not supplied in this report model. "
            "No internal topology or component identity is inferred.", ""]
    if not stages:
        out += ["```{=typst}", "#pagebreak()", "```", ""]
    # Scope denser vertical table padding to the PDF method section. Keeping
    # the type size and horizontal padding preserves readability while avoiding
    # a nearly empty page caused by the final shutdown row spilling over.
    # Raw Typst blocks disappear from HTML; no web content or figure changes.
    out += ["```{=typst}", "#block(breakable: true)[",
            "#set table(inset: (x: 6pt, y: 3pt))",
            "#set par(spacing: 0.55em)", "```", ""]
    out += ["## Setup and method {#setup}", "", _md(model.get("boundary", "Boundary not supplied")), ""]
    bench = model.get("bench", {})
    for key in ("bench_id",):
        if key in bench:
            out += [f"**{_md(key.replace('_',' '))}:** {_md(_compact(bench[key]))}", ""]
    sources = []
    for key in ("source", "load"):
        item = bench.get(key)
        if isinstance(item, dict):
            sources.append([key.capitalize(), item.get("instrument_id", "unknown"),
                f"{_number(item.get('max_voltage_V'))} V / {_number(item.get('max_current_A'))} A / {_number(item.get('max_power_W'))} W",
                "required" if item.get("remote_sense_required") else "not requested"])
    if sources:
        out += [_rows_table(["Role", "Instrument ID", "Profile envelope", "Remote sense"], sources,
                           layout="bench-profile"), ""]
    provenance = model.get("provenance", {})
    identities = provenance.get("instrument_identities", {})
    if identities:
        out += ["### Connected equipment", "",
                _rows_table(["Role", "Equipment Model", "Serial Number", "Firmware", "Manufacturer"],
                    _equipment_rows(identities), layout="equipment"), "",
                "Reported identities identify the connected instruments; they do not establish calibration or modified hardware ratings.", ""]
    observations = provenance.get("operator_observations", [])
    if observations:
        out += ["### Operator observations", ""]
        out += [_md(note) + "\n" for note in observations]
    # A schematic of measurement roles, not an invented DUT circuit or photograph.
    out += ["```{=typst}", '#align(center)[#box(stroke: 0.6pt, inset: 9pt)[Source terminals]'
            ' → #box(stroke: 0.6pt, inset: 9pt)[DUT input → output]'
            ' → #box(stroke: 0.6pt, inset: 9pt)[Load]]', "```", "",
            "```{=html}", '<div class="setup-diagram" aria-label="Power flows from source terminals through the DUT to the load">'
            '<strong>Source terminals</strong> → <strong>DUT input → output</strong> → <strong>Load</strong></div>', "```", "",
            "Power leads carry input/output current. "
            + ("Separate load S+ / S− sense leads terminate at the DUT output. "
               if bench.get("load", {}).get("remote_sense_required") else "Load remote sense is not requested by this profile. ")
            + "The measurement locations below define the boundary. Supply remote sense is not implied by a voltage reading.", ""]
    bindings = bench.get("measurements", {})
    if bindings:
        out += [_rows_table(["Quantity", "Instrument", "Measurement location", "Readback budget"],
            [[name, row.get("instrument_id"), str(row.get("location", "unknown")).replace("_", " "),
              "not evaluated"] for name, row in bindings.items()]), ""]
    method = model.get("method")
    if voltage_sweep:
        described = [_condition_phrase(c) for c in conditions]
        ratings = model.get("dut", {}).get("ratings") or {}
        nominal_output = _positive(ratings.get("output_voltage_nominal_V"))
        input_min, input_max = ratings.get("input_voltage_min_V"), ratings.get("input_voltage_max_V")
        plural = "s" if len(described) != 1 else ""
        if prior_input_attempt:
            what = ((f"The comparison covers the requested {_join(described)} condition{plural}. " if described else "")
                    + (f"The earlier {prior_phrase} startup attempt produced no qualified efficiency result. "
                       if prior_phrase else "An earlier startup attempt produced no qualified efficiency result. ")
                    + (f"This acquisition continues at {continued_phrase}. " if continued_phrase else ""))
        elif described:
            what = (f"The supply powers the converter input at {_count_word(len(described))} "
                    f"condition{plural}: {_join(described)}. ")
        else:
            what = "The supply powers the converter input at each requested condition. "
        what += ("At each tested input, the electronic load gradually draws more current from the converter's "
                 + (f"{nominal_output:g} V output. " if nominal_output else "output. ")
                 + "Input and output power are measured to show how much reaches the load as useful output power. "
                 "Each input condition has its own color throughout the report.")
        boundary_text = ((f"The supply current limit is {source_limit:g} A, so the available input power and the "
                          "maximum reachable output load differ between input conditions. " if source_limit is not None else "")
                         + "A curve stops at the recorded source or measurement boundary.")
        setpoints = []
        for condition in conditions:
            nominal, programmed = condition["nominal_input_V"], condition.get("programmed_input_V")
            if not _finite(programmed) or programmed == nominal:
                continue
            sentence = f"The nominal {nominal:g} V condition is programmed at {programmed:g} V"
            if _finite(input_max) and programmed < input_max <= nominal:
                sentence += f", {input_max - programmed:.3g} V below the stated {input_max:g} V input ceiling"
            endpoint = " endpoint" if nominal in (input_min, input_max) else ""
            setpoints.append(sentence + ". The measured input voltage is retained with every point; "
                             f"this is not an exact {nominal:.3f} V{endpoint} test.")
        if described and _finite(input_min) and _finite(input_max):
            setpoints.append(f"The stated {input_min:g}–{input_max:g} V operating range is not fully verified "
                             f"by these {_count_word(len(described))} condition{plural}.")
        if temperature := _temperature_note(model):
            setpoints.append(temperature)
        out += ["### What this test does", "", what, "", boundary_text, "",
                *([" ".join(setpoints), ""] if setpoints else [])]
    if method:
        acquisition = method["declared_acquisition"]
        settling = method["declared_settling"]
        qualified_timings = [point for point in method["achieved_points"] if point["qualification"] == "valid"]

        def achieved(field: str, unit: str = "s", scale: float = 1.) -> str:
            applicable = [point for point in qualified_timings if not (
                field == "settling_elapsed_s" and point.get("settling_inherited_from_previous_point"))]
            values = [point[field] * scale for point in applicable if point.get(field) is not None]
            if not values:
                return "not recorded" if qualified_timings else "no qualified points"
            low, high = min(values), max(values)
            low_text, high_text = f"{low:.3g}", f"{high:.3g}"
            span = low_text if low_text == high_text else f"{low_text}–{high_text}"
            missing = len(applicable) - len(values)
            return f"{span} {unit}".strip() + (f"; {missing} point(s) unknown" if missing else "")

        out += ["### Acquisition method", "", _rows_table(["Policy / evidence", "Recorded setting or result"], [
            ["Declared settling", f"At least {_number(settling['minimum_dwell_s'])} s dwell; "
             f"{_number(settling['window_s'])} s window with {settling['minimum_fresh_samples']} queried readings; "
             f"Vout span ≤ {_number(settling['maximum_vout_span_V'])} V; timeout {_number(settling['timeout_s'])} s"],
            ["Declared acquisition", f"{_number(acquisition['duration_s'])} s phase; "
             f"{_number(acquisition['target_poll_interval_s'])} s polling target; "
             f"at least {acquisition['minimum_complete_cycles']} complete cycles; "
             f"interchannel query skew ≤ {_number(acquisition['maximum_interchannel_skew_s'])} s"],
            ["Accepted cycles per qualified point", achieved("accepted_cycle_count", "cycles")],
            ["Recorded new-load settling / acquisition phase duration", achieved("settling_elapsed_s") + " / "
             + achieved("acquisition_elapsed_s")],
            ["Accepted query span / maximum cycle skew", achieved("accepted_query_span_s") + " / "
             + achieved("maximum_accepted_interchannel_skew_s", "ms", 1000.)],
        ], layout="key-value"), "", "**Timing basis:** " + _md(method.get("clock_mode") or "unknown") + ". "
            "Achieved ranges cover qualified points only. The query span runs from the first accepted "
            "query start to the last accepted query completion; it is not the entire acquisition phase or "
            "an instrument ADC update interval. Missing durations remain unknown.", ""]
        if method.get("clock_note"):
            out += [_md(method["clock_note"]), ""]
        if model.get("evidence_label") == "MEASURED":
            out += ["ADC freshness and independence are unverified for this bench; queried readings are not proven fresh conversions.", ""]
        for note in method.get("procedure_notes", []):
            out += [_md(note), ""]
    has_hold = 'fig-hold-voltage' in figure_registry
    attempted_ids = set(model.get('execution', {}).get('executed_point_ids', []))
    if stages:
        stage_rows = []
        for stage in stages:
            rows = [point for point in model["points"] if point.get("phase_label") == stage]
            targets = [point["iout_target_A"] * 1000 for point in rows]
            target_text = f"{targets[0]:g} mA" if len(set(targets)) == 1 else f"{targets[0]:g} → {targets[-1]:g} mA"
            stage_rows.append([stage, target_text, len(rows), sum(p["qualification"] == "valid" for p in rows)])
        out += ["### What this test does", "",
                "The supply powers the converter input. The electronic load acts as an adjustable device on its output. "
                "Increasing demand checks how voltage and power delivery change. "
                + ("The hold observes short-term voltage drift. " if has_hold else "")
                + "Returning to a lower load lets you compare the output with its earlier reading.", "",
                _rows_table(["Stage", "Candidate loads" if source_search else "Requested load", "Candidates" if source_search else "Planned bins", "Qualified windows"], stage_rows), ""]
        if source_search:
            search_limit = _source_current_limit(model, source_search)
            out += ["The output load increases only while measured input current and voltage allow it. "
                    + (f"The {search_limit:g} A limit belongs to the supply feeding the converter; output current can be higher. "
                       if search_limit is not None else "")
                    + "Unused candidates are possible settings that the adaptive search did not request. "
                    "A final light-load observation is planned to check the return condition, if the test can continue safely.", ""]
        if has_hold:
            out += ["Each hold bin covers a separate acquisition interval at the same requested load. "
                "The converter remains loaded between those bins; the test does not repeatedly switch the load off. "
                "The time plot uses recorded query times, so a long hold occupies real horizontal space.", ""]
        if temperature := _temperature_note(model):
            out += [temperature, ""]
    # The outcome, shutdown states and evidence note form one PDF block. An
    # individual OFF row must not become the sole content on a later page.
    out += ["```{=typst}", "#block(breakable: false)[", "```", ""]
    out += ["**Acquisition outcome:** " + _md(model.get("execution", {}).get("status", "unknown")) + ". "
            "Output shutdown state is recorded separately in the run evidence.", ""]
    shutdown = model.get("execution", {}).get("shutdown", {})
    if shutdown:
        out += [_rows_table(["Instrument", "End-of-run output state", "Readback verified"],
            [[role.capitalize(), state.get("state", "UNKNOWN"),
              "yes" if state.get("verified") is True else "not established"]
             for role, state in shutdown.items()]), ""]
    out += ["Measured values are aggregated settled DC point results. The raw-sample explorer in HTML "
            "shows only evidence embedded in this report. No waveform, thermal, calibration or uncertainty "
            "claim is inferred from ordinary DC polling.", ""]
    out += ["```{=typst}", "]", "]", "```", ""]
    out += ["```{=typst}", "#pagebreak()", "```", "", "## Results {#results}", ""]
    for text in model.get("prose", []):
        out += [_md(text), ""]
    out += ["```{=html}", _controls_html(model), "```", ""]
    for spec in model["figures"]:
        fid = spec["id"]
        out += [f"::: {{.figure-view #view-{fid}}}", "", f"### {_md(spec['title'])}", "",
                f"![{_md(spec['caption'])}](figures/{fid}.svg){{#{fid}}}", "",
                "```{=html}", f'<div class="figure-actions" data-figure="{fid}">'
                '<button type="button" data-action="selected">Export selected curves CSV</button>'
                '<button type="button" data-action="visible">Export visible range CSV</button>'
                '<button type="button" data-action="svg">Export SVG</button>'
                '<button type="button" data-action="png">Export PNG</button></div>'
                f'<p class="figure-status" id="status-{fid}" aria-live="polite"></p>', "```", "", "::: ", ""]
    out += ["```{=html}", '<section class="raw-evidence" aria-labelledby="evidence-title">'
            '<h3 id="evidence-title">Point results and raw evidence</h3>'
            '<label for="point-picker">Inspect point (keyboard accessible)</label><br>'
            '<select id="point-picker"></select><p id="point-detail"></p>'
            '<div id="raw-evidence" class="raw-table"></div></section>', "```", "",
            ("## Regulation and sustained-load results {#regulation}" if has_hold else
             "## Regulation and return results {#regulation}" if stages else
             "## Regulation results {#regulation}" if voltage_sweep else
             "## Regulation and no-load results {#regulation}"), ""]
    if len(metrics) > 1:
        out += [_rows_table(["Metric", "Value", "Actually covered conditions"],
            [[m["label"], f"{_number(m.get('value'))} {m.get('unit','')}", m.get("conditions", "")]
             for m in metrics[1:]]), "", "See @fig-voltage for the qualified voltage values."
             + (" See @fig-hold-voltage for the sustained-load interval." if has_hold else ""), ""]
    no_load = [p for p in model["points"] if p.get("iout_target_A") == 0 and p.get("qualification") == "valid"]
    if no_load:
        out += ["### Enabled with no external load", "", "These values describe board/path input consumption, not controller quiescent current. Efficiency is not applicable.", "",
            _rows_table(["Requested input (V)", "Measured input current (A)", "Input power (W)", "Output voltage (V)"],
                [[_number(p.get(key)) for key in ("vin_target_V", "Iin_A", "Pin_W", "Vout_V")]
                 for p in no_load]), ""]
    elif stages or voltage_sweep:
        out += ["No-load consumption was not measured in this run.", ""]
    if len(metrics) <= 1 and not no_load:
        out += ["This run has insufficient input-voltage and load coverage to calculate regulation, "
                "and no qualified no-load point. A broader acquired grid is needed for these results.", ""]
    out += ["```{=typst}", "#pagebreak()", "```", "",
            "## Interpretation {#interpretation}", "", "No author interpretation has been supplied. "
            "The computed observations establish trends only within the acquired grid; they do not identify topology or loss mechanisms.", "",
            "## Appendix: qualification and provenance {#appendix}", ""]
    for text in model.get("limitations", []):
        out.append("- " + _md(text))
    out.append("")
    exclusions = [p for p in model["points"] if p.get("qualification") != "valid"]
    if voltage_sweep and voltage_comparison:
        out += ["### Input-condition outcomes", "",
            _rows_table(["Input condition", "Qualified points", "Outcome", "Recorded stop reason"],
                [[row.get("label") or f"{_number(row.get('nominal_input_V'))} V input",
                  row.get("qualified_points", 0), _phase_outcome(row.get("phase_status")),
                  ("No efficiency result; not repeated in this run." if row.get("phase_status") == "previous-attempt-unqualified"
                   else row.get("stop_reason") or "not reported")] for row in voltage_comparison],
                layout="voltage-outcomes"), ""]
    if prior_input_attempt:
        startup = prior_input_attempt.get('last_startup_cycle', {})
        out += [(f"### Earlier {prior_phrase} startup attempt {{#prior-input-attempt}}" if prior_phrase
                 else "### Earlier startup attempt {#prior-input-attempt}"), "",
            "These readings belong to the last recorded startup cycle of a separate, aborted run. "
            "They are not a settled operating point and do not qualify an efficiency measurement. "
            "They are excluded from the efficiency curves and comparison values.", "",
            _rows_table(["Input voltage", "Input current", "Output voltage", "Output current"],
                [[_display_quantity(startup.get(key), unit, precision) for key, unit, precision in
                  (("Vin_V", "V", 3), ("Iin_A", "A", 4), ("Vout_V", "V", 3), ("Iout_A", "A", 4))]],
                layout="startup-readings"), "",
            "Startup stopped before a qualified operating point was obtained. The cause has not been established. "
            "The full stop details are retained in the report model and earlier acquisition.", "",
            "**Earlier run:** " + _md(prior_input_attempt.get('run_id') or 'not reported') + ". "
            "Its acquisition remains separate; its identity and integrity hash are retained in this report model.", ""]
    if source_search or voltage_sweep:
        unused = [p for p in exclusions if p['point_id'] not in attempted_ids and p.get('qualification') == 'not-run']
        if unused:
            if voltage_sweep:
                out += [f"{len(unused)} declared load conditions were not reached. The recorded input-condition outcomes "
                    "explain where testing stopped. These are unperformed conditions, not failed measurements. "
                    "Every condition remains listed in the report model and point explorer.", ""]
            else:
                out += [f"{len(unused)} conditional load candidates were not requested. The search skips intermediate "
                    "settings during coarse stepping and stops when its measured boundary is reached. "
                    "These are not failed measurements. Every candidate remains listed in the report model and point explorer.", ""]
            unused_ids = {p['point_id'] for p in unused}
            exclusions = [p for p in exclusions if p['point_id'] not in unused_ids]
    if exclusions:
        out += [_rows_table(["Point", "Test", "Requested input / load", "Qualification", "Reason"],
            [[p["point_id"],p.get("test_id"),f"{p.get('vin_target_V')} V / {p.get('iout_target_A')} A",
              p.get("qualification"),p.get("reason", "not supplied")] for p in exclusions],
            layout="exclusions"), ""]
    else:
        out += ["No attempted measurements were excluded." if source_search or voltage_sweep else
                "No excluded points are recorded in this analysis.", ""]
    out += ["Uncertainty: " + _md((model.get("uncertainty") or {}).get("note") or "No applicable validated uncertainty budget "
            "is supplied. Bands and difference-resolution conclusions are not fabricated."), "",
            "**Run:** " + _md(model["run_id"]) + "  ",
            "**Analysis:** " + _md(model["analysis_id"]) + "  ",
            "**Report revision:** " + _md(model.get("report_revision", "not supplied")), "",
            "**Method version:** " + _md(model.get("provenance", {}).get("formula_version", "unknown")), "",
            "```{=html}", '<p class="report-footer">Local artifacts: '
            '<a href="report_model.json">report model and embedded evidence</a> · '
            '<a href="build_manifest.json">build manifest</a> · '
            '<a href="exports/points.csv">issued point results CSV</a> · '
            '<a href="exports/points.meta.json">CSV conditions and columns</a> '
            '<span id="canonical-pdf-link"></span></p>', "```", ""]
    return "\n".join(out)


def _compact(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key.replace('_',' ')}: {_compact(item)}" for key,item in value.items())
    if isinstance(value, list):
        return ", ".join(_compact(item) for item in value)
    return _number(value)


def _controls_html(model: dict) -> str:
    time_option = ('<option value="elapsed_s">Elapsed time (s)</option>'
                   if any(figure["x_key"] == "elapsed_s" for figure in model["figures"]) else '')
    temperature = (' Temperatures: not acquired; no temperature channel is bound in this bench profile.'
                   if _temperature_note(model) else '')
    return ('<div class="exploratory-print">EXPLORATORY CURRENT VIEW — issued findings remain unchanged.</div>'
        '<section class="report-controls" aria-labelledby="controls-title"><h3 id="controls-title">Explore recorded results</h3>'
        f'<div class="identity-strip">{html.escape(_identity(model))} · {html.escape(model["run_id"])} · '
        f'{html.escape(model.get("evidence_label", ""))}</div>'
        '<div class="control-grid"><label>Metric<select id="metric-select"><option value="all">All result figures</option></select></label>'
        '<label>Horizontal axis<select id="x-select"><option value="default">Figure default</option>'
        '<option value="Iout_A">Measured output current (A)</option><option value="Pout_W">Measured output power (W)</option>'
        '<option value="Vin_V">Measured input voltage (V)</option>' + time_option + '</select></label>'
        '<label>Hover<select id="hover-select"><option value="closest">Nearest measured point</option>'
        '<option value="x unified">Values at measured x</option></select></label>'
        '<label><span>Current scale</span><span><input id="log-current" type="checkbox"> Log current</span></label></div>'
        '<fieldset><legend class="scope-note">Test conditions — also synchronized with plot legends</legend>'
        '<div id="trace-options" class="trace-options"></div></fieldset>'
        '<div class="figure-actions"><button type="button" id="reset-zoom">Reset zoom</button>'
        '<button type="button" id="restore-view">Restore default view</button>'
        '<button type="button" id="save-view">Save view JSON</button>'
        '<button type="button" id="print-view">Print current view</button></div>'
        '<p class="scope-note">Selected-curves CSV includes every point in the chosen traces, before zoom and log display exclusions. '
        'Visible-range CSV uses inclusive current plot bounds and excludes points absent from that view. '
        'Each CSV has a separate metadata JSON download. Nonpositive current is omitted only from log views; '
        'no-load points remain in the evidence explorer.' + html.escape(temperature) + '</p>'
        '<p id="report-error" role="alert"></p></section>')


# Issued numerical export: the same columns, order and number text as the
# interactive report's selected-curves CSV, so the two files diff cleanly.
EXPORT_FIELDS = ("run_id", "analysis_id", "evidence_type", "point_id", "test_id", "vin_target_V",
                 "programmed_input_V", "input_condition_label", "iout_target_A",
                 "Vin_V", "Iin_A", "Vout_V", "Iout_A", "Pin_W", "Pout_W", "loss_W",
                 "efficiency_pct", "vout_error_pct", "qualification", "reason")
EXPORT_TIMING_FIELDS = ("phase_label", "elapsed_start_s", "elapsed_s", "elapsed_end_s")
EXPORT_COLUMNS: dict[str, tuple[str, str | None]] = {
    "run_id": ("Acquisition run identifier", None),
    "analysis_id": ("Analysis identifier bound to this evidence and formula version", None),
    "evidence_type": ("Evidence label of the whole run: MEASURED or SYNTHETIC", None),
    "point_id": ("Requested operating-point identifier", None),
    "test_id": ("Test definition the point belongs to", None),
    "vin_target_V": ("Requested (nominal) input voltage", "V"),
    "programmed_input_V": ("Input voltage actually programmed on the source, when recorded", "V"),
    "input_condition_label": ("Recorded input-condition label, when recorded", None),
    "iout_target_A": ("Requested output load current", "A"),
    "Vin_V": ("Mean input voltage over accepted acquisition cycles", "V"),
    "Iin_A": ("Mean input current over accepted acquisition cycles", "A"),
    "Vout_V": ("Mean output voltage over accepted acquisition cycles", "V"),
    "Iout_A": ("Mean output current over accepted acquisition cycles", "A"),
    "Pin_W": ("Input power = mean(Vin) × mean(Iin)", "W"),
    "Pout_W": ("Output power = mean(Vout) × mean(Iout); not evaluated at no load", "W"),
    "loss_W": ("Path loss = Pin − Pout across the declared boundary", "W"),
    "efficiency_pct": ("Path efficiency = 100 × Pout / Pin", "%"),
    "vout_error_pct": ("Output deviation = 100 × (Vout − Vnominal) / Vnominal", "%"),
    "qualification": ("Point qualification: valid, inconclusive, setup-limited, not-run, …", None),
    "reason": ("Recorded qualification reason", None),
    "phase_label": ("Sequence stage label, when the run records stages", None),
    "elapsed_start_s": ("Start of the accepted query span, relative to the first accepted query", "s"),
    "elapsed_s": ("Midpoint of the accepted query span", "s"),
    "elapsed_end_s": ("End of the accepted query span", "s"),
}


def _export_fields(model: dict) -> list[str]:
    fields = list(EXPORT_FIELDS)
    if any(figure.get("x_key") == "elapsed_s" for figure in model["figures"]):
        fields.extend(EXPORT_TIMING_FIELDS)
    return fields


def _csv_number(value: int | float) -> str:
    """Shortest round-trip decimal text in ECMAScript Number.toString form.

    The interactive report writes numbers through JavaScript. Producing the
    same text here keeps the issued and exploratory CSV files byte-comparable
    while retaining full numerical precision.
    """
    if isinstance(value, int) or (value.is_integer() and abs(value) < 1e21):
        return str(int(value))
    sign, digits, exponent = Decimal(repr(value)).normalize().as_tuple()
    text = "".join(map(str, digits))
    k, n = len(digits), exponent + len(digits)
    if k <= n <= 21:
        body = text + "0" * (n - k)
    elif 0 < n <= 21:
        body = text[:n] + "." + text[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + text
    else:
        body = text[0] + ("." + text[1:] if k > 1 else "") + "e" + ("+" if n - 1 >= 0 else "-") + str(abs(n - 1))
    return ("-" if sign else "") + body


def _csv_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if _finite(value):
        return _csv_number(value)
    return _safe_cell(value)


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def write_exports(model: dict, out_dir: Path) -> dict[str, dict]:
    """Write reports/<revision>/exports/: the issued numerical selection.

    points.csv holds every requested operating point of the issued model in
    report order, with unique unit-bearing column names, empty missing values
    and run/analysis/point identifiers. points.meta.json describes the
    columns, recorded conditions and the selection. Text cells are guarded
    against spreadsheet formula execution without altering stored evidence.
    """
    exports = Path(out_dir) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    for stale in exports.iterdir():
        if stale.is_file():
            stale.unlink()
    fields = _export_fields(model)
    if len(set(fields)) != len(fields) or any(name not in EXPORT_COLUMNS for name in fields):
        raise ValueError("Export columns must be unique and documented")
    constants = {"run_id": model["run_id"], "analysis_id": model["analysis_id"],
                 "evidence_type": model.get("evidence_label")}
    points = model["points"]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\r\n")
    writer.writerow(fields)
    for point in points:
        writer.writerow([_csv_cell(constants[key] if key in constants else point.get(key)) for key in fields])
    csv_path = exports / "points.csv"
    _write_atomic(csv_path, handle.getvalue())

    input_conditions: list[dict] = []
    for point in points:
        if not _finite(point.get("vin_target_V")):
            continue
        entry = {"vin_target_V": point["vin_target_V"],
                 "programmed_input_V": point["programmed_input_V"] if _finite(point.get("programmed_input_V")) else None,
                 "label": point.get("input_condition_label")}
        if entry not in input_conditions:
            input_conditions.append(entry)
    execution = model.get("execution", {})
    method = execution.get("source_limit_search") or execution.get("voltage_efficiency_sweep") or None
    metadata = {
        "schema_version": "1.0", "kind": "canonical-issued-export",
        "selection": "Canonical issued selection: every requested operating point of the issued report model, "
                     "in report order, before any reader filter, zoom or log-axis omission. This is the report's "
                     "default view, not an exploratory reader selection.",
        "run_id": model["run_id"], "analysis_id": model["analysis_id"],
        "report_revision": model.get("report_revision"), "evidence_type": model.get("evidence_label"),
        "dut": _identity(model), "measurement_boundary": model.get("boundary"),
        "formula_version": model.get("provenance", {}).get("formula_version"),
        "point_count": len(points),
        "conditions": {
            "input_conditions": input_conditions,
            "requested_loads_A": sorted({float(p["iout_target_A"]) for p in points if _finite(p.get("iout_target_A"))}),
            "test_ids": list(dict.fromkeys(str(p["test_id"]) for p in points if p.get("test_id") is not None)),
            "source_current_limit_A": _source_current_limit(model, method) if method else None,
            "qualification_counts": {label: sum(1 for p in points if p.get("qualification") == label)
                                     for label in dict.fromkeys(str(p.get("qualification")) for p in points)},
        },
        "figure_ids": [figure["id"] for figure in model["figures"]],
        "columns": [{"name": name, "description": EXPORT_COLUMNS[name][0], "unit": EXPORT_COLUMNS[name][1]}
                    for name in fields],
        "csv": {"file": "points.csv", "encoding": "utf-8", "delimiter": ",", "line_terminator": "CRLF",
                "header_row": 1, "quoting": "RFC 4180; fields containing quotes, commas or line breaks are quoted",
                "missing_values": "empty field",
                "numbers": "shortest round-trip decimal text, identical to the interactive report's CSV export",
                "string_safety": "Text cells beginning with = + - or @ are prefixed with an apostrophe to prevent "
                                 "spreadsheet formula execution; stored evidence is unchanged",
                "sha256": _sha(csv_path), "bytes": csv_path.stat().st_size},
    }
    meta_path = exports / "points.meta.json"
    _write_atomic(meta_path, _json(metadata))
    return {name: {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
            for name, path in (("points.csv", csv_path), ("points.meta.json", meta_path))}


def _quarto() -> str:
    candidates = [os.environ.get("QUARTO_PATH"), shutil.which("quarto"),
                  str(PROJECT / ".tools/quarto/bin/quarto")]
    candidates.extend(str(p) for p in sorted((PROJECT / ".tools").glob("quarto-*/bin/quarto"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ReportRenderError("Quarto is unavailable. Install the reporting tools or set QUARTO_PATH.")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_pdf(artifact: Path, model: dict) -> dict:
    """PDF-02 pagination check of the finished document (see pdf_check)."""
    from .pdf_check import check_pdf
    return check_pdf(artifact, model).to_dict()


def _record_pdf_check(manifest: dict, artifact: Path, model: dict) -> None:
    """Record the pagination check; an error finding makes the PDF a validation failure.

    The document is kept for inspection. A crash inside the checker is
    recorded as a failed check, never as an unverified success. When the
    checker's tools (pypdf, poppler pdftohtml) are unavailable the artifact is
    "unverified": kept and linked, but named as not verified.
    """
    try:
        manifest["pdf_check"] = _check_pdf(artifact, model)
    except Exception as exc:
        manifest["pdf_check"] = {"schema_version": "1.0", "status": "fail", "path": str(artifact),
            "findings": [{"code": "checker-error", "severity": "error", "page": None,
                          "message": f"{type(exc).__name__}: {exc}", "details": {}}], "pages": []}
    if manifest["pdf_check"].get("status") == "fail":
        errors = [f for f in manifest["pdf_check"].get("findings", []) if f.get("severity") == "error"]
        summary = "; ".join((f"p{f['page']}: " if f.get("page") else "") + str(f.get("code")) for f in errors[:8])
        manifest["artifacts"]["pdf"].update(status="failed-validation",
            error=f"PDF pagination check (PDF-02) reported {len(errors)} error finding(s): {summary}")
    elif manifest["pdf_check"].get("status") == "unverified":
        missing = [str(f.get("code")) for f in manifest["pdf_check"].get("findings", []) if f.get("severity") == "unverified"]
        manifest["artifacts"]["pdf"].update(status="unverified",
            note="PDF not verified: tool missing (" + ", ".join(missing) + "); the pagination check (PDF-02) could not run")


def _print_header(identity: str) -> str:
    """Typst header include for the PDF: running identity, type, heading and table pagination rules."""
    # JSON string syntax is also a valid Typst quoted string; user text is never raw code.
    return ('#set page(numbering: "1 / 1", header: text(size: 7pt, fill: rgb("516677"), '
            + json.dumps(identity, ensure_ascii=False) + '))\n'
            '#set text(font: ("DejaVu Sans", "Liberation Sans"), fill: rgb("183047"))\n'
            # A sticky heading travels with the block after it, so a table moved
            # whole to the next page never strands its heading (brief §12.6).
            '#show heading: it => { block(above: 1.2em, below: 0.5em, sticky: true, it) }\n'
            '#set par(justify: false)\n'
            # Tables up to half a page never split; taller ones keep their last two rows together.
            + (TEMPLATES / "theme/print-tables.typ").read_text(encoding="utf-8"))


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _browser_path() -> str | None:
    if os.environ.get("BROWSER_PATH"):
        return os.environ["BROWSER_PATH"]
    configured = PROJECT / ".tools/browser-path.txt"
    if configured.exists():
        return configured.read_text().strip()
    return (shutil.which("chromium-headless-shell") or shutil.which("chromium")
            or shutil.which("google-chrome"))


def _stop_group(child: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the child's own session; the child led it (start_new_session)."""
    for sig, wait_s in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=wait_s)
            return
        except subprocess.TimeoutExpired:
            continue


def _run_tool(command: list[str], *, cwd: Path, timeout_s: float, log_path: Path | None = None, task: str = "tool"):
    """Run one document tool in its own session; on timeout stop the whole group.

    ``subprocess.run(timeout=...)`` kills only the direct child, which can leave
    Pandoc/Typst grandchildren running. Every exit path sweeps the session and
    records peak child RSS so build_manifest.json shows what the tool cost.
    """
    started = time.monotonic()
    usage: dict = {"command": command[:1] + [str(part) for part in command[1:]], "pid": None, "duration_s": None,
                   "peak_child_rss_mib": None, "survivors": [], "survivors_remaining": [], "timed_out": False, "returncode": None}
    try_log_event(log_path, task, "start")
    child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    usage["pid"] = child.pid
    stdout = stderr = ""
    try:
        try:
            stdout, stderr = child.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            usage["timed_out"] = True
            _stop_group(child)
            try:
                stdout, stderr = child.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                # A grandchild outside the group still holds the pipes: sweep the session.
                terminate_group(child.pid, grace_s=5.)
                stdout, stderr = child.communicate(timeout=15)
    finally:
        usage["returncode"] = child.returncode
        usage["duration_s"] = round(time.monotonic() - started, 3)
        usage["survivors"] = session_survivors(child.pid)
        if usage["survivors"]:
            usage["survivors_remaining"] = terminate_group(child.pid, grace_s=5.)["remaining"]
        usage["peak_child_rss_mib"] = children_peak_rss_mib()
        try_log_event(log_path, task, "survivors", child_pid=child.pid, count=len(usage["survivors"]), processes=usage["survivors"])
        try_log_event(log_path, task, "end", child_pid=child.pid, duration_s=usage["duration_s"], returncode=child.returncode,
                      child_peak_rss_mib=usage["peak_child_rss_mib"], timed_out=usage["timed_out"])
    return SimpleNamespace(stdout=stdout or "", stderr=stderr or "", returncode=child.returncode, usage=usage)


def _browser_pid(browser) -> int | None:
    """Chromium's group leader. Kaleido subclasses choreographer's ``Browser``, whose
    ``subprocess`` attribute is the Popen of the browser wrapper started with
    ``start_new_session=True``; Chromium and its renderers share that group."""
    pid = getattr(getattr(browser, "subprocess", None), "pid", None)
    return pid if isinstance(pid, int) and pid > 1 else None


def _stop_browser_tree(browser, log_path: Path | None) -> dict | None:
    pid = _browser_pid(browser)
    if pid is None:
        try_log_event(log_path, "static-figures", "survivors", count=None,
                      note="browser close timed out; pid unavailable, the parent's session sweep applies")
        return None
    outcome = terminate_group(pid, grace_s=5.)
    try_log_event(log_path, "static-figures", "survivors", child_pid=pid, count=len(outcome["found"]),
                  processes=outcome["found"], remaining=outcome["remaining"], note="browser close timed out")
    return outcome


async def _write_static_figures(model: dict, figures_dir: Path, log_path: Path | None = None) -> None:
    """Use one offline browser/tab and render one image at a time.

    Kaleido's batch wrapper schedules every image up front. Avoid that extra
    queued state on small hosts, and disable its default MathJax CDN request.
    Choreographer (the pinned Kaleido dependency) also supplies Chromium's
    --disable-dev-shm-usage flag. These limits do not make rendering suitable
    to run concurrently with acquisition on a memory-constrained controller.
    """
    import kaleido
    import plotly
    from choreographer.browsers.chromium import Chromium

    class SingleRendererChromium(Chromium):
        def get_cli(self):
            return [*super().get_cli(), "--renderer-process-limit=1",
                    "--disable-background-networking"]

    if not model["figures"]:
        return
    plotly_path = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if not plotly_path.is_file():
        raise ReportRenderError("The installed Plotly.js asset is missing; CDN fallback is disabled.")
    browser = kaleido.Kaleido(path=_browser_path(), n=1, timeout=STATIC_IMAGE_TIMEOUT_S,
        plotlyjs=plotly_path.as_uri(), mathjax=False, enable_gpu=False,
        enable_extensions=False, headless=True, browser_cls=SingleRendererChromium)
    try:
        await asyncio.wait_for(browser.open(), timeout=STATIC_START_TIMEOUT_S)
        for number, spec in enumerate(model["figures"], 1):
            print(f"Rendering Figure {number}: {spec.get('title', spec['id'])}", file=sys.stderr, flush=True)
            figure = _plot_figure(model, spec, number)
            for extension in ("svg", "pdf"):
                path = figures_dir / f"{spec['id']}.{extension}"
                path.unlink(missing_ok=True)
                # Explicit errors: Kaleido otherwise returns an error tuple,
                # which the Plotly batch wrapper currently ignores.
                await asyncio.wait_for(browser.write_fig(figure, path=path,
                    opts={"format": extension, "width": 1080, "height": 530, "scale": 1},
                    cancel_on_error=True), timeout=STATIC_IMAGE_TIMEOUT_S)
                if not path.is_file() or path.stat().st_size == 0:
                    raise ReportRenderError(f"Static figure renderer produced no output: {path.name}")
            del figure
    finally:
        try:
            await asyncio.wait_for(browser.close(), timeout=STATIC_CLOSE_TIMEOUT_S)
        except TimeoutError:
            # Kaleido's own kill did not finish: make sure the Chromium tree is gone.
            _stop_browser_tree(browser, log_path or figures_dir.parent / "resources.jsonl")
            raise


def _static_figures(model: dict, figures_dir: Path, tool_versions: dict | None = None) -> dict:
    """Reuse verified vectors across report-only retries of the same evidence.

    The document revision changes on retry, but does not appear in the plot.
    Every other model field, renderer source and rendering dependency belongs
    to the cache identity. A corrupt or incomplete cache is rendered again.
    """
    from filelock import FileLock
    comparable = copy.deepcopy(model)
    comparable.pop("report_revision", None)
    identity = {"model": comparable, "renderer": _sha(Path(__file__)), "tools": tool_versions,
                "versions": {name: _version(name) for name in ("plotly", "kaleido", "choreographer")}}
    key = hashlib.sha256(_json(identity).encode()).hexdigest()
    cache = figures_dir.parent.parent / ".figure-cache" / key
    cache.mkdir(parents=True, exist_ok=True)
    filenames = [spec["id"] + "." + extension for spec in model["figures"] for extension in ("svg", "pdf")]
    with FileLock(str(cache / "build.lock"), timeout=120):
        try:
            hashes = json.loads((cache / "hashes.json").read_text())
            valid = (set(hashes) == set(filenames) and all(
                (cache / name).is_file() and (cache / name).stat().st_size > 0
                and _sha(cache / name) == hashes[name] for name in filenames))
        except (OSError, ValueError, TypeError):
            valid = False
        if valid:
            for name in filenames:
                shutil.copyfile(cache / name, figures_dir / name)
            print("Reusing verified vector figures for this report revision", file=sys.stderr, flush=True)
        else:
            asyncio.run(_write_static_figures(model, figures_dir))
            hashes = {}
            for name in filenames:
                source = figures_dir / name
                hashes[name] = _sha(source)
                temporary = cache / (name + ".tmp")
                shutil.copyfile(source, temporary)
                temporary.replace(cache / name)
            temporary = cache / "hashes.json.tmp"
            temporary.write_text(_json(hashes))
            temporary.replace(cache / "hashes.json")
    return {"key": key, "reused": valid, "verified_files": len(filenames)}


def render_report(report_model: dict, out_dir: Path, formats=("html", "pdf")) -> dict:
    from ..activity import bench_activity
    with bench_activity("report", timeout=0):
        return _render_report(report_model, out_dir, formats)


def _render_report(report_model: dict, out_dir: Path, formats=("html", "pdf")) -> dict:
    """Render requested formats, recording truthful successes and failures.

    On any requested-format failure, write build_manifest.json and raise
    ReportRenderError with that manifest. Acquisition may succeed independently.
    """
    model = copy.deepcopy(validate_report_model(report_model))
    requested = tuple(dict.fromkeys(formats))
    if not requested or any(fmt not in ("html", "pdf") for fmt in requested):
        raise ValueError("Report formats must be html and/or pdf")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"schema_version": "1.0", "run_id": model["run_id"],
        "analysis_id": model["analysis_id"], "report_revision": model.get("report_revision"),
        "created_utc": datetime.now(timezone.utc).isoformat(), "requested_formats": list(requested),
        "status": "building", "artifacts": {}, "figures": [], "exports": {},
        "versions": {name: _version(name) for name in ("plotly", "kaleido", "dcdc-bench")},
        "model_sha256": hashlib.sha256(_json(model).encode()).hexdigest(),
        "template_sha256": _sha(TEMPLATES / "characterization.qmd"),
        "render_sources_sha256": {
            "renderer.py": _sha(Path(__file__).resolve()),
            "report.css": _sha(TEMPLATES / "theme/report.css"),
            "print-tables.typ": _sha(TEMPLATES / "theme/print-tables.typ"),
            "report.js": _sha(TEMPLATES / "web/report.js"),
        }}
    gate_record = out / "memory_gate.json"
    if gate_record.is_file():
        manifest["memory_gate"] = json.loads(gate_record.read_text(encoding="utf-8"))
    resources_log = out / "resources.jsonl"
    for fmt in requested:
        (out / f"report.{fmt}").unlink(missing_ok=True)
    # A killed render leaves a visible incomplete build instead of an
    # apparently finished report folder without an outcome record.
    (out / "build_manifest.json").write_text(_json(manifest), encoding="utf-8")
    try:
        # The numerical export needs no document toolchain; write it first so
        # a failed document build still leaves the issued selection inspectable.
        if model.get("kind") == "comparison":
            from .comparison import write_comparison_exports
            manifest["exports"] = write_comparison_exports(model, out)
        else:
            manifest["exports"] = write_exports(model, out)
        from plotly.offline import get_plotlyjs, get_plotlyjs_version

        manifest["versions"]["plotly_js"] = get_plotlyjs_version()
        plotly_js = get_plotlyjs()
        manifest["plotly_js_sha256"] = hashlib.sha256(plotly_js.encode()).hexdigest()
        browser_path = _browser_path()
        if browser_path:
            manifest["versions"]["chromium"] = subprocess.run([browser_path, "--version"], check=True,
                capture_output=True, text=True, timeout=30).stdout.strip()
        quarto = _quarto()
        manifest["versions"]["quarto"] = subprocess.run([quarto, "--version"], check=True,
            capture_output=True, text=True, timeout=30).stdout.strip()
        figures_dir = out / "figures"
        figures_dir.mkdir(exist_ok=True)
        manifest["static_render_policy"] = {"browser_tabs": 1, "concurrent_images": 1,
            "renderer_process_limit": 1,
            "local_plotly_js": True, "mathjax": False, "gpu": False,
            "startup_timeout_s": STATIC_START_TIMEOUT_S,
            "image_timeout_s": STATIC_IMAGE_TIMEOUT_S,
            "close_timeout_s": STATIC_CLOSE_TIMEOUT_S}
        static_started = time.monotonic()
        try_log_event(resources_log, "static-figures", "start")
        try:
            manifest["static_cache"] = _static_figures(model, figures_dir, manifest["versions"])
        finally:
            try_log_event(resources_log, "static-figures", "end", duration_s=round(time.monotonic() - static_started, 3),
                          reused=manifest.get("static_cache", {}).get("reused"), child_peak_rss_mib=children_peak_rss_mib())
        for i,spec in enumerate(model["figures"], 1):
            manifest["figures"].append({"id": spec["id"], "number": i,
                "svg_sha256": _sha(figures_dir / f"{spec['id']}.svg"),
                "pdf_sha256": _sha(figures_dir / f"{spec['id']}.pdf")})
        (out / "report_model.json").write_text(_json(model), encoding="utf-8")
        shutil.copyfile(TEMPLATES / "theme/report.css", out / "report.css")
        (out / "metadata.html").write_text('<meta name="robots" content="noindex,nofollow">', encoding="utf-8")
        script = (TEMPLATES / "web/report.js").read_text(encoding="utf-8")
        payload = {"model": model, "colors": COLORS, "condition_colors": _condition_colors(model),
                   "condition_styles": _condition_styles(model),
                   "figure_references": _figure_references(model),
                   "plotly_js_version": get_plotlyjs_version(),
                   "canonical_pdf": "pdf" in requested}
        # Keep both the vendor runtime and potentially large raw evidence out
        # of Pandoc's document parser. Insert them after Quarto finishes; the
        # final HTML remains self-contained with the exact same data/runtime.
        runtime_slot = '<script id="dcdc-plotly-runtime"></script>'
        interactions = '<script id="dcdc-plotly-runtime">' + plotly_js + '</script>\n' \
            + '<script type="application/json" id="dcdc-report-data">' + _embedded_json(payload) + '</script>\n' \
            + '<script>' + script + '</script>'
        (out / "interactions.html").write_text(runtime_slot + '\n', encoding="utf-8")
        identity = f"{model.get('evidence_label','')} · {_identity(model)} · {model['run_id']}"
        (out / "print-header.typ").write_text(_print_header(identity), encoding="utf-8")
        source = (TEMPLATES / "characterization.qmd").read_text(encoding="utf-8")
        source = source.replace("__TITLE__", json.dumps(_md(model.get("title", f"{_identity(model)} characterization"))))
        source = source.replace("__SUBTITLE__", json.dumps(_md(identity + " · " + model["analysis_id"])))
        source = source.replace("__BODY__", with_sensor_placement(_body(model), out, _md))
        (out / "report.qmd").write_text(source, encoding="utf-8")
        for fmt in requested:
            print(f"Building {fmt.upper()} document…", file=sys.stderr, flush=True)
            artifact = out / f"report.{fmt}"
            try:
                result = _run_tool([quarto, "render", "report.qmd", "--to", "typst" if fmt == "pdf" else "html"],
                    cwd=out, timeout_s=DOCUMENT_TIMEOUT_S, log_path=resources_log, task=f"quarto-{fmt}")
                manifest.setdefault("resource_usage", {})[fmt] = result.usage
                (out / f"render-{fmt}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
                if result.usage.get("timed_out"):
                    raise subprocess.TimeoutExpired(result.usage.get("command", [quarto]), DOCUMENT_TIMEOUT_S)
                if result.returncode or not artifact.is_file() or artifact.stat().st_size == 0:
                    raise ReportRenderError((result.stderr or result.stdout)[-3500:] or "No document produced")
                if fmt == "html":
                    document = artifact.read_text(encoding="utf-8")
                    if document.count(runtime_slot) != 1:
                        raise ReportRenderError("Missing or duplicated local Plotly runtime slot")
                    artifact.write_text(document.replace(runtime_slot, interactions), encoding="utf-8")
                manifest["artifacts"][fmt] = {"status": "success", "path": str(artifact),
                    "sha256": _sha(artifact), "bytes": artifact.stat().st_size}
                if fmt == "pdf":
                    _record_pdf_check(manifest, artifact, model)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                manifest["artifacts"][fmt] = {"status": "failed", "error": message}
                with (out / f"render-{fmt}.log").open("a", encoding="utf-8") as log:
                    log.write("\n" + message + "\n")
                artifact.unlink(missing_ok=True)
            # One format failing must not suppress the other or conceal an
            # already completed artifact while the next compiler is running.
            (out / "build_manifest.json").write_text(_json(manifest), encoding="utf-8")
    except Exception as exc:
        for fmt in requested:
            manifest["artifacts"].setdefault(fmt, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    statuses = {fmt: manifest["artifacts"].get(fmt, {}).get("status") for fmt in requested}
    failures = [fmt for fmt, status in statuses.items() if status not in ("success", "unverified")]
    # A document that built but failed its pagination check is kept and named as
    # such; one whose checker tools were unavailable is kept as "unverified".
    manifest["status"] = (("success" if all(status == "success" for status in statuses.values()) else "unverified")
                          if not failures else "failed-validation"
                          if all(statuses[fmt] == "failed-validation" for fmt in failures) else "failed")
    (out / "build_manifest.json").write_text(_json(manifest), encoding="utf-8")
    if failures:
        details = "; ".join(f"{fmt}: {manifest['artifacts'].get(fmt,{}).get('error','no output')}" for fmt in failures)
        raise ReportRenderError("Requested report formats failed: " + details, manifest)
    return manifest
