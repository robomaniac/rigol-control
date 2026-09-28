"""Comparison documents, figures and exports from a validated comparison model.

Formats supplied results only. No efficiency, difference or uncertainty is
recalculated here, and no instrument code is imported.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import html
import io
import math
from pathlib import Path
from typing import Any

from .renderer import (COLORS, _csv_cell, _json, _md, _number, _rows_table, _sha, _version, _write_atomic,
                       validate_report_model)

# One style per run: the same hue for one operating condition in every run,
# distinguished by line style and marker only. Neither run gets a warning hue.
RUN_STYLES = (("solid", "circle"), ("dash", "square"), ("dot", "diamond"),
              ("dashdot", "triangle-up"), ("longdash", "triangle-down"), ("longdashdot", "cross"))
ZERO_LINE = {"color": "#183047", "width": 1.6, "dash": "dash"}
PLOTTED_QUALIFICATIONS = ("valid", "paired", "interpolated")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _signed(value: Any, decimals: int) -> str:
    return f"{value:+.{decimals}f}" if _finite(value) else "not available"


def _fixed(value: Any, decimals: int) -> str:
    return f"{value:.{decimals}f}" if _finite(value) else "not available"


def _condition_palette(model: dict) -> dict[str, str]:
    """Deterministic condition colors shared by every comparison figure."""
    keys: list[str] = []
    for spec in model["figures"]:
        for series in spec["series"]:
            key = series.get("condition_key") or series["id"]
            if key not in keys:
                keys.append(key)
    return {key: COLORS[index % len(COLORS)] for index, key in enumerate(keys)}


def _runs_by_label(model: dict) -> dict[str, dict]:
    return {run["label"]: run for run in model.get("runs", [])}


def _footer(model: dict, spec: dict, conditions: str) -> str:
    runs = "; ".join(f"{run['label']}: {run['run_id']} / {run['analysis_id']} ({run['evidence_label']})" for run in model.get("runs", []))
    labels = [run["label"] for run in model.get("runs", [])]
    sign = f"Differences = run {labels[1]} − run {labels[0]}" if len(labels) >= 2 else "Differences = other run − reference run"
    return (f"{model.get('evidence_label', 'Evidence status not supplied')} | {model['dut']['identity']['model']} | "
            f"Comparison {model.get('comparison_id', model['run_id'])}<br>{spec['id']} | {conditions}<br>Runs: {runs}<br>"
            f"Boundary: {model.get('boundary', 'not supplied')} | {sign}; uncertainty not evaluated unless stated")


def plot_comparison_figure(model: dict, spec: dict, number: int):
    """Overlay or difference figure: color = condition, line/marker = run, zero line on differences."""
    import plotly.graph_objects as go

    points = {p["point_id"]: p for p in model["points"]}
    run_index = {run["label"]: index for index, run in enumerate(model.get("runs", []))}
    palette = _condition_palette(model)
    figure = go.Figure()
    is_difference = str(spec["y_key"]).startswith("delta_")
    plotted_values: list[float] = []
    conditions: list[str] = []
    for series in spec["series"]:
        rows = [points[pid] for pid in series["point_ids"]]
        okay = [row.get("qualification") in PLOTTED_QUALIFICATIONS for row in rows]
        x = [row.get(spec["x_key"]) for row in rows]
        y = [row.get(spec["y_key"]) if flag else None for row, flag in zip(rows, okay)]
        plotted = [(float(a), float(b)) for a, b in zip(x, y) if _finite(a) and _finite(b)]
        if not plotted:
            continue
        plotted_values.extend(b for _, b in plotted)
        color = palette.get(series.get("condition_key") or series["id"], COLORS[0])
        dash, symbol = RUN_STYLES[run_index.get(series.get("run_label"), 0) % len(RUN_STYLES)]
        interpolated = any(row.get("kind") == "interpolated" for row in rows)
        if interpolated:
            dash, symbol = "dot", symbol + "-open"
        label = str(series.get("label", series["id"]))
        conditions.append(label)
        figure.add_trace(go.Scatter(x=x, y=y, name=html.escape(label),
            mode="lines+markers" if series.get("connect_points", True) else "markers",
            line={"width": 2, "color": color, "dash": dash},
            marker={"size": 10 if interpolated else 9, "color": color, "symbol": symbol}, connectgaps=False,
            legendgroup=series["id"], customdata=[row["point_id"] for row in rows],
            hovertemplate="%{customdata}<br>%{x:.6g}<br>%{y:.6g}<extra>%{fullData.name}</extra>"))
    labels = [run["label"] for run in model.get("runs", [])]
    if is_difference:
        figure.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y", y0=0, y1=0, line=ZERO_LINE, layer="below")
        zero_text = (f"Zero difference: run {labels[1]} = run {labels[0]}" if len(labels) >= 2 else "Zero difference")
        figure.add_annotation(xref="paper", x=0, yref="y", y=0, text=html.escape(zero_text), showarrow=False,
            xanchor="left", yanchor="bottom", font={"size": 11, "color": "#183047"}, bgcolor="rgba(255,255,255,0.9)")
        # A symmetric axis around zero gives both signs identical visual weight.
        span = max((abs(value) for value in plotted_values), default=1.) or 1.
        padding = max(.15 * span, 1e-9)
        figure.update_yaxes(range=[-(span + padding), span + padding], autorange=False)
    footer = _footer(model, spec, "; ".join(conditions) or "no plotted points")
    footer = "<br>".join(html.escape(line) for line in footer.split("<br>"))
    figure.update_layout(template="plotly_white", width=1080, height=530,
        font={"family": "DejaVu Sans, Arial, sans-serif", "size": 16, "color": "#183047"},
        title={"text": f"Figure {number}. {html.escape(spec['title'])}", "x": .06, "font": {"size": 19}},
        margin={"l": 75, "r": 28, "t": 70, "b": 150},
        legend={"orientation": "h", "y": 1.12, "x": 0, "font": {"size": 13}},
        xaxis={"title": html.escape(spec["x_label"]), "gridcolor": "#e6edf1", "zeroline": False},
        yaxis={"title": html.escape(spec["y_label"]), "gridcolor": "#e6edf1", "zeroline": False},
        annotations=[*figure.layout.annotations, {"text": footer, "xref": "paper", "yref": "paper", "x": 0, "y": -.24,
            "xanchor": "left", "yanchor": "top", "align": "left", "showarrow": False,
            "font": {"size": 12, "color": "#516677"}}])
    figure.update_xaxes(tickformat="~g", nticks=7)
    figure.update_yaxes(tickformat="~g", nticks=6)
    return figure


def _uncertainty_cell(pair: dict, quantity: str) -> str:
    entry = (pair.get("uncertainty") or {}).get(quantity) or {}
    if entry.get("status") != "evaluated":
        return "not evaluated" if entry.get("status") != "not applicable" else "not applicable"
    text = f"{entry['u_delta']:.4g} ({entry['covariance_basis']})"
    return text


def _pair_rows(model: dict) -> list[list[str]]:
    rows = []
    for pair in model.get("pairs", []):
        rows.append([pair["pair_id"], pair["test_id"], _number(pair["vin_target_V"]), _number(pair["iout_target_A"]),
                     pair["source_point_id_a"], pair["source_point_id_b"], _fixed(pair.get("Iout_a_A"), 4), _fixed(pair.get("Iout_b_A"), 4),
                     _fixed(pair.get("eta_a_pct"), 3), _fixed(pair.get("eta_b_pct"), 3), _signed(pair.get("delta_eta_pp"), 3),
                     _fixed(pair.get("loss_a_W"), 4), _fixed(pair.get("loss_b_W"), 4), _signed(pair.get("delta_loss_W"), 4),
                     _fixed(pair.get("Vout_a_V"), 4), _fixed(pair.get("Vout_b_V"), 4), _signed(pair.get("delta_Vout_V"), 4),
                     _uncertainty_cell(pair, "efficiency_pct")])
    return rows


def comparison_body(model: dict, *, figure_suffix: str = "svg") -> str:
    """Quarto/Markdown body for a comparison model; all user text is escaped."""
    evidence = str(model.get("evidence_label", "Evidence type unknown"))
    runs = model.get("runs", [])
    labels = [run["label"] for run in runs]
    reference, other = (labels[0], labels[1]) if len(labels) >= 2 else ("A", "B")
    figure_registry = {figure["id"] for figure in model["figures"]}
    metric_registry = {metric["id"]: metric for metric in model["metrics"]}
    out = ["## Summary {#summary}", "", f"**{_md(evidence)} — paired comparison — {_md(model.get('boundary', 'Boundary not supplied'))}.**", "",
           "This issued summary is fixed. Reader filters change exploratory views only. Every difference is "
           f"run {_md(other)} minus run {_md(reference)}; both signs receive the same neutral treatment.", ""]
    references = {item["paragraph_index"]: item["metric_ids"] for item in model.get("summary_evidence", [])}
    for index, text in enumerate(model.get("summary", [])):
        figure_ids: list[str] = []
        for metric_id in references.get(index, []):
            if metric_id not in metric_registry:
                raise ValueError("Summary reference targets a missing metric")
            for fid in metric_registry[metric_id].get("figure_ids", []):
                if fid not in figure_registry:
                    raise ValueError("Summary reference targets an invalid figure")
                if fid not in figure_ids:
                    figure_ids.append(fid)
        reference_text = " See " + ", ".join("@" + fid for fid in figure_ids) + "." if figure_ids else ""
        out += [_md(text) + reference_text, ""]
    out += ["### Compared runs", "", _rows_table(
        ["Run", "Run ID", "Analysis", "Evidence", "DUT", "Bench", "Outcome", "Acquired (UTC)", "Valid / points", "Uncertainty budget"],
        [[run["label"], run["run_id"], run["analysis_id"], run["evidence_label"], run["dut_model"], run["bench_id"],
          run["execution_status"], run.get("created_utc") or "not recorded", f"{run['valid_count']} / {run['point_count']}",
          run["uncertainty_status"]] for run in runs]), ""]
    out += ["### Paired measured points {#paired}", ""]
    pairs = model.get("pairs", [])
    if pairs:
        out += [_rows_table(["Pair", "Test", "Vin req (V)", "Iout req (A)", f"Point {reference}", f"Point {other}",
                             f"Iout {reference} (A)", f"Iout {other} (A)", f"η {reference} (%)", f"η {other} (%)", "Δη (pp)",
                             f"Loss {reference} (W)", f"Loss {other} (W)", "Δloss (W)", f"Vout {reference} (V)", f"Vout {other} (V)",
                             "ΔVout (V)", "u(Δη) (pp)"], _pair_rows(model)), "",
                "Requested conditions are the pairing key; measured currents of both points are shown so the reader can judge the "
                "actual achieved conditions. Δη is in percentage points.", ""]
    else:
        out += ["No point could be paired under the declared rules; see the availability section.", ""]
    out += [f"**Qualification:** {_md(evidence.lower())} observations from stored analyses; "
            + ("difference uncertainty not evaluated. " if model["difference_uncertainty"]["status"] == "not evaluated"
               else f"difference uncertainty {_md(model['difference_uncertainty']['status'])}. ")
            + "Paired DC points do not qualify rated power, temperature, ripple or transient behavior.", ""]
    out += ["```{=typst}", "#pagebreak()", "```", "", "## Results {#results}", ""]
    for text in model.get("prose", []):
        out += [_md(text), ""]
    for spec in model["figures"]:
        fid = spec["id"]
        out += [f"::: {{.figure-view #view-{fid}}}", "", f"### {_md(spec['title'])}", "",
                f"![{_md(spec['caption'])}](figures/{fid}.{figure_suffix}){{#{fid}}}", "", ":::", ""]
    out += ["## Availability of unpaired points {#unpaired}", ""]
    for row in model.get("availability", []):
        out.append("- " + _md(row["statement"]))
    out.append("")
    eligible = [row for row in model.get("unpaired", []) if row["eligible"]]
    if eligible:
        out += [_rows_table(["Run", "Point", "Test", "Vin req (V)", "Iout req (A)", "Qualification", "Reason"],
            [[row["run_label"], row["source_point_id"], row["test_id"], _number(row["vin_target_V"]), _number(row["iout_target_A"]),
              row["qualification"], row["reason"]] for row in eligible]), ""]
    else:
        out += ["Every valid point has a partner.", ""]
    ineligible: dict[tuple[str, str], int] = {}
    for row in model.get("unpaired", []):
        if not row["eligible"]:
            key = (row["run_label"], row["qualification"])
            ineligible[key] = ineligible.get(key, 0) + 1
    if ineligible:
        out += [_rows_table(["Run", "Qualification", "Points not eligible for pairing"],
            [[label, qualification, count] for (label, qualification), count in sorted(ineligible.items())]), "",
            "Unattempted or unqualified points are listed by count; they are not failed measurements and never enter a pair.", ""]
    interpolated = model.get("interpolated", [])
    if model.get("pairing", {}).get("interpolation_enabled"):
        out += ["## INTERPOLATED comparisons (not measured) {#interpolated}", "",
                "Enabled explicitly. Each row evaluates the other run's curve by linear interpolation between its two bracketing "
                "measured points at the same test id and requested input. These are estimates, not measurements, and are excluded "
                "from every paired-point count, metric and summary statement.", ""]
        if interpolated:
            out += [_rows_table(["Row", "Measured run", "Interpolated run", "Test", "Vin req (V)", "Iout req (A)", "η measured (%)",
                                 "η interpolated (%)", "Δη (pp)", "Bracketing points"],
                [[row["point_id"], row["run_label"], row["interpolated_run"], row["test_id"], _number(row["vin_target_V"]),
                  _number(row["iout_target_A"]), _fixed(row.get("eta_measured_pct"), 3), _fixed(row.get("eta_interpolated_pct"), 3),
                  _signed(row.get("delta_eta_pp"), 3), ", ".join(row["bracket_point_ids"])] for row in interpolated]), ""]
        else:
            out += ["No unpaired load was strictly bracketed by the other run's measured points; nothing was interpolated.", ""]
    out += ["## Disclosures: recorded fields that differ {#disclosures}", ""]
    disclosures = model.get("disclosures", [])
    identical = [name for name, flag in model.get("identical", {}).items() if flag]
    if disclosures:
        out += [_rows_table(["Field", *[f"Run {label}" for label in labels]],
            [[item["field"], *[_compact_value(item["values"].get(label, "<same as reference>")) for label in labels]]
             for item in disclosures[:80]]), ""]
        if len(disclosures) > 80:
            out += [f"{len(disclosures) - 80} further differing fields are listed in comparison_model.json.", ""]
    else:
        out += ["No recorded DUT, bench, recipe, method, instrument-identity or software field differs.", ""]
    if identical:
        out += ["Identical sections: " + _md(", ".join(identical)) + ".", ""]
    out += ["The runs are compared as tested. Differing fields are disclosed so the reader can judge comparability; "
            "no observed difference is attributed to any of them.", ""]
    uncertainty = model["difference_uncertainty"]
    out += ["## Uncertainty and resolvability {#uncertainty}", "",
            f"**Status:** {_md(uncertainty['status'])}. **Model:** {_md(uncertainty.get('model', 'not applicable'))}.", ""]
    if uncertainty.get("reason"):
        out += [_md(uncertainty["reason"]), ""]
    assumption = uncertainty.get("assumption") or {}
    if assumption.get("statement"):
        out += ["**Covariance basis:** " + _md(assumption["statement"]), ""]
    if uncertainty["status"] == "not evaluated":
        out += ["No uncertainty bands are drawn and no statement is made about whether any difference exceeds measurement uncertainty.", ""]
    out += ["```{=typst}", "#pagebreak()", "```", "", "## Interpretation {#interpretation}", "",
            "No author interpretation has been supplied. The computed observations describe the paired conditions of the compared "
            "runs only; they do not identify mechanisms, components or design choices, and they do not rank devices beyond the conditions listed.", "",
            "## Appendix: qualification and provenance {#appendix}", ""]
    for text in model.get("limitations", []):
        out.append("- " + _md(text))
    out += ["", "**Comparison:** " + _md(model.get("comparison_id", model["run_id"])) + "  ",
            "**Comparison method version:** " + _md(model.get("comparison_version", "unknown")) + "  ",
            *[f"**Run {_md(run['label'])}:** {_md(run['run_id'])} · analysis {_md(run['analysis_id'])} · {_md(run['formula_version'])}  " for run in runs],
            "", "```{=html}", '<p class="report-footer">Local artifacts: '
            '<a href="comparison_model.json">comparison model</a> · '
            '<a href="comparison_manifest.json">manifest</a> · '
            '<a href="exports/paired.csv">paired points CSV</a> · '
            '<a href="exports/unpaired.csv">unpaired points CSV</a> · '
            '<a href="exports/run_points.csv">all compared points CSV</a> · '
            '<a href="exports/comparison.meta.json">CSV conditions and columns</a></p>', "```", ""]
    return "\n".join(out)


def _compact_value(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_compact_value(item)}" for key, item in value.items()) or "{}"
    if isinstance(value, list):
        return ", ".join(_compact_value(item) for item in value) or "[]"
    return _number(value)


PAIRED_COLUMNS: dict[str, tuple[str, str | None]] = {
    "comparison_id": ("Comparison identifier", None), "pair_id": ("Pair identifier", None),
    "label_a": ("Reference run label", None), "label_b": ("Other run label", None),
    "run_id_a": ("Acquisition run identifier of run A", None), "run_id_b": ("Acquisition run identifier of run B", None),
    "analysis_id_a": ("Analysis identifier of run A", None), "analysis_id_b": ("Analysis identifier of run B", None),
    "evidence_type_a": ("Evidence label of run A", None), "evidence_type_b": ("Evidence label of run B", None),
    "test_id": ("Test definition shared by the pair", None), "test_type": ("Test type shared by the pair", None),
    "vin_target_V": ("Requested input voltage of the run A point (pairing key)", "V"),
    "iout_target_A": ("Requested output current of the run A point (pairing key)", "A"),
    "vin_target_b_V": ("Requested input voltage of the run B point", "V"), "iout_target_b_A": ("Requested output current of the run B point", "A"),
    "point_id_a": ("Point identifier within run A", None), "point_id_b": ("Point identifier within run B", None),
    "Vin_a_V": ("Mean input voltage, run A", "V"), "Vin_b_V": ("Mean input voltage, run B", "V"),
    "Iout_a_A": ("Mean output current, run A", "A"), "Iout_b_A": ("Mean output current, run B", "A"),
    "Vout_a_V": ("Mean output voltage, run A", "V"), "Vout_b_V": ("Mean output voltage, run B", "V"),
    "Pin_a_W": ("Input power, run A", "W"), "Pin_b_W": ("Input power, run B", "W"),
    "Pout_a_W": ("Output power, run A", "W"), "Pout_b_W": ("Output power, run B", "W"),
    "loss_a_W": ("Path loss, run A", "W"), "loss_b_W": ("Path loss, run B", "W"),
    "eta_a_pct": ("Path efficiency, run A", "%"), "eta_b_pct": ("Path efficiency, run B", "%"),
    "delta_eta_pp": ("eta_b_pct − eta_a_pct", "percentage points"), "delta_loss_W": ("loss_b_W − loss_a_W", "W"),
    "delta_Vout_V": ("Vout_b_V − Vout_a_V", "V"), "delta_Vin_measured_V": ("Vin_b_V − Vin_a_V (achieved-condition check)", "V"),
    "delta_Iout_measured_A": ("Iout_b_A − Iout_a_A (achieved-condition check)", "A"),
    "u_delta_eta_pp": ("Standard uncertainty of delta_eta_pp when evaluated; empty otherwise", "percentage points"),
    "u_delta_loss_W": ("Standard uncertainty of delta_loss_W when evaluated; empty otherwise", "W"),
    "u_delta_Vout_V": ("Standard uncertainty of delta_Vout_V when evaluated; empty otherwise", "V"),
    "uncertainty_status": ("Per-quantity difference-uncertainty status", None),
    "covariance_basis": ("supplied or independence assumed, per evaluated quantity", None),
}
UNPAIRED_COLUMNS: dict[str, tuple[str, str | None]] = {
    "comparison_id": ("Comparison identifier", None), "run_label": ("Run holding the point", None),
    "run_id": ("Acquisition run identifier", None), "analysis_id": ("Analysis identifier", None),
    "evidence_type": ("Evidence label of the run", None), "point_id": ("Point identifier within its run", None),
    "test_id": ("Test definition", None), "test_type": ("Test type", None),
    "vin_target_V": ("Requested input voltage", "V"), "iout_target_A": ("Requested output current", "A"),
    "qualification": ("Point qualification", None), "eligible": ("true when valid but without a partner", None),
    "compared_with": ("Run label searched for a partner", None), "reason": ("Recorded reason the point is unpaired", None),
    "Vin_V": ("Mean input voltage", "V"), "Iout_A": ("Mean output current", "A"), "Vout_V": ("Mean output voltage", "V"),
    "efficiency_pct": ("Path efficiency", "%"), "loss_W": ("Path loss", "W"),
}
POINT_COLUMNS: dict[str, tuple[str, str | None]] = {
    "comparison_id": ("Comparison identifier", None), "run_label": ("Run holding the point", None),
    "run_id": ("Acquisition run identifier", None), "analysis_id": ("Analysis identifier", None),
    "evidence_type": ("Evidence label of the run", None), "point_id": ("Point identifier within its run", None),
    "test_id": ("Test definition", None), "test_type": ("Test type", None),
    "vin_target_V": ("Requested input voltage", "V"), "iout_target_A": ("Requested output current", "A"),
    "Vin_V": ("Mean input voltage", "V"), "Iin_A": ("Mean input current", "A"), "Vout_V": ("Mean output voltage", "V"),
    "Iout_A": ("Mean output current", "A"), "Pin_W": ("Input power", "W"), "Pout_W": ("Output power", "W"),
    "loss_W": ("Path loss", "W"), "efficiency_pct": ("Path efficiency", "%"),
    "vout_error_pct": ("Output deviation from nominal", "%"), "qualification": ("Point qualification", None),
    "reason": ("Recorded qualification reason", None), "pair_id": ("Pair the point belongs to, when paired", None),
}
INTERPOLATED_COLUMNS: dict[str, tuple[str, str | None]] = {
    "comparison_id": ("Comparison identifier", None), "row_id": ("Interpolated row identifier", None),
    "label": ("INTERPOLATED marker; these rows are not measurements", None),
    "run_label": ("Run whose point was measured", None), "interpolated_run": ("Run whose curve was interpolated", None),
    "test_id": ("Test definition", None), "test_type": ("Test type", None),
    "vin_target_V": ("Requested input voltage of the measured point", "V"),
    "iout_target_A": ("Requested output current of the measured point", "A"),
    "measured_point_id": ("Measured point (run-prefixed identifier)", None),
    "bracket_point_id_low": ("Lower bracketing measured point of the interpolated run", None),
    "bracket_point_id_high": ("Upper bracketing measured point of the interpolated run", None),
    "bracket_load_low_A": ("Requested load of the lower bracketing point", "A"),
    "bracket_load_high_A": ("Requested load of the upper bracketing point", "A"),
    "eta_measured_pct": ("Measured efficiency", "%"), "eta_interpolated_pct": ("Interpolated efficiency", "%"),
    "delta_eta_pp": ("eta_B − eta_A with one side interpolated", "percentage points"),
    "delta_loss_W": ("loss_B − loss_A with one side interpolated", "W"),
    "delta_Vout_V": ("Vout_B − Vout_A with one side interpolated", "V"),
}


def _write_csv(path: Path, columns: dict[str, tuple[str, str | None]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = list(columns)
    if len(set(names)) != len(names):
        raise ValueError("Export columns must be unique")
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\r\n")
    writer.writerow(names)
    for row in rows:
        writer.writerow([_csv_cell(row.get(name)) for name in names])
    _write_atomic(path, handle.getvalue())
    return {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size, "rows": len(rows),
            "columns": [{"name": name, "description": columns[name][0], "unit": columns[name][1]} for name in names]}


def write_comparison_exports(model: dict, out_dir: Path) -> dict[str, dict]:
    """Write exports/: paired, unpaired, all compared points and (if enabled) interpolated rows, plus metadata."""
    exports = Path(out_dir) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    for stale in exports.iterdir():
        if stale.is_file():
            stale.unlink()
    runs = _runs_by_label(model)
    comparison_id = model.get("comparison_id", model["run_id"])
    points = {p["point_id"]: p for p in model["points"]}
    paired_rows = []
    for pair in model.get("pairs", []):
        run_a, run_b = runs[pair["label_a"]], runs[pair["label_b"]]
        entries = pair.get("uncertainty") or {}

        def u(quantity: str) -> float | None:
            entry = entries.get(quantity) or {}
            return entry.get("u_delta") if entry.get("status") == "evaluated" else None

        paired_rows.append({**{key: pair.get(key) for key in PAIRED_COLUMNS}, "comparison_id": comparison_id,
            "run_id_a": run_a["run_id"], "run_id_b": run_b["run_id"], "analysis_id_a": run_a["analysis_id"], "analysis_id_b": run_b["analysis_id"],
            "evidence_type_a": pair["evidence_label_a"], "evidence_type_b": pair["evidence_label_b"],
            "point_id_a": pair["source_point_id_a"], "point_id_b": pair["source_point_id_b"],
            "u_delta_eta_pp": u("efficiency_pct"), "u_delta_loss_W": u("loss_W"), "u_delta_Vout_V": u("Vout_V"),
            "uncertainty_status": "; ".join(f"{quantity}: {entry.get('status', 'not evaluated')}" for quantity, entry in entries.items()),
            "covariance_basis": "; ".join(f"{quantity}: {entry['covariance_basis']}" for quantity, entry in entries.items()
                                          if entry.get("status") == "evaluated") or None})
    unpaired_rows = []
    for row in model.get("unpaired", []):
        run = runs[row["run_label"]]
        point = points.get(row["point_id"], {})
        unpaired_rows.append({**{key: row.get(key) for key in UNPAIRED_COLUMNS}, "comparison_id": comparison_id,
            "run_id": run["run_id"], "analysis_id": run["analysis_id"], "evidence_type": run["evidence_label"],
            "point_id": row["source_point_id"], **{key: point.get(key) for key in ("Vin_V", "Iout_A", "Vout_V", "efficiency_pct", "loss_W")}})
    point_rows = []
    for point in model["points"]:
        if point.get("kind") != "point":
            continue
        run = runs[point["run_label"]]
        point_rows.append({**{key: point.get(key) for key in POINT_COLUMNS}, "comparison_id": comparison_id,
            "run_id": run["run_id"], "analysis_id": run["analysis_id"], "evidence_type": run["evidence_label"],
            "point_id": point["source_point_id"]})
    files = {"paired.csv": _write_csv(exports / "paired.csv", PAIRED_COLUMNS, paired_rows),
             "unpaired.csv": _write_csv(exports / "unpaired.csv", UNPAIRED_COLUMNS, unpaired_rows),
             "run_points.csv": _write_csv(exports / "run_points.csv", POINT_COLUMNS, point_rows)}
    if model.get("pairing", {}).get("interpolation_enabled"):
        interpolated_rows = [{**{key: row.get(key) for key in INTERPOLATED_COLUMNS}, "comparison_id": comparison_id,
                              "row_id": row["point_id"], "bracket_point_id_low": row["bracket_point_ids"][0],
                              "bracket_point_id_high": row["bracket_point_ids"][1], "bracket_load_low_A": row["bracket_loads_A"][0],
                              "bracket_load_high_A": row["bracket_loads_A"][1]} for row in model.get("interpolated", [])]
        files["interpolated.csv"] = _write_csv(exports / "interpolated.csv", INTERPOLATED_COLUMNS, interpolated_rows)
    metadata = {
        "schema_version": "1.0", "kind": "comparison-issued-export", "comparison_id": comparison_id,
        "comparison_version": model.get("comparison_version"), "evidence_type": model.get("evidence_label"),
        "runs": [{key: run[key] for key in ("label", "run_id", "analysis_id", "evidence_label", "run_dir", "boundary")} for run in model.get("runs", [])],
        "pairing": model.get("pairing"), "sign_convention": "Every delta column is the run B value minus the run A value",
        "difference_uncertainty": {key: model["difference_uncertainty"].get(key) for key in ("status", "model", "assumption", "reason")},
        "interpolation": {"enabled": bool(model.get("pairing", {}).get("interpolation_enabled")),
                          "rows": len(model.get("interpolated", [])),
                          "note": "INTERPOLATED rows are estimates between measured points; they are not measurements"},
        "files": {name: {key: value for key, value in info.items() if key != "path"} for name, info in files.items()},
        "csv": {"encoding": "utf-8", "delimiter": ",", "line_terminator": "CRLF", "header_row": 1,
                "quoting": "RFC 4180; fields containing quotes, commas or line breaks are quoted",
                "missing_values": "empty field", "numbers": "shortest round-trip decimal text",
                "string_safety": "Text cells beginning with = + - or @ are prefixed with an apostrophe; stored evidence is unchanged"},
    }
    meta_path = exports / "comparison.meta.json"
    _write_atomic(meta_path, _json(metadata))
    result = {name: {"path": info["path"], "sha256": info["sha256"], "bytes": info["bytes"]} for name, info in files.items()}
    result["comparison.meta.json"] = {"path": str(meta_path), "sha256": _sha(meta_path), "bytes": meta_path.stat().st_size}
    return result


def write_comparison(model: dict, out_dir: Path, *, overwrite: bool = False, created_utc: str | None = None) -> Path:
    """Write the comparison folder: model, Markdown body, exports, figure definitions and a manifest.

    Static SVG/PDF figures and HTML/PDF documents are not built here; the model
    is ready for the shared renderer, which dispatches comparison models to
    this module.
    """
    model = copy.deepcopy(validate_report_model(model))
    if model.get("kind") != "comparison":
        raise ValueError("write_comparison expects a comparison report model")
    out = Path(out_dir).resolve()
    if (out / "comparison_model.json").exists() and not overwrite:
        raise ValueError(f"{out} already holds a comparison; choose another folder or pass --overwrite")
    out.mkdir(parents=True, exist_ok=True)
    model_path = out / "comparison_model.json"
    _write_atomic(model_path, _json(model))
    header = (f"# {model.get('title', 'Paired comparison')}\n\n**{model.get('evidence_label', '')} · comparison "
              f"{model.get('comparison_id', model['run_id'])}** — generated from stored analyses; figure definitions are in "
              "figures/*.plotly.json (static rendering requires the report toolchain).\n\n")
    body_path = out / "comparison.md"
    _write_atomic(body_path, header + comparison_body(model, figure_suffix="plotly.json"))
    exports = write_comparison_exports(model, out)
    figures: dict[str, Any] = {}
    figure_note = "figure definitions written as Plotly JSON; static SVG/PDF rendering not performed by compare"
    try:
        import plotly  # noqa: F401
    except ImportError:
        figure_note = "plotly unavailable; figure definitions not written"
    else:
        figures_dir = out / "figures"
        figures_dir.mkdir(exist_ok=True)
        for number, spec in enumerate(model["figures"], 1):
            figure = plot_comparison_figure(model, spec, number)
            path = figures_dir / f"{spec['id']}.plotly.json"
            _write_atomic(path, figure.to_json())
            figures[spec["id"]] = {"number": number, "path": str(path), "sha256": _sha(path)}
    manifest = {"schema_version": "1.0", "kind": "comparison", "comparison_id": model.get("comparison_id"),
                "comparison_version": model.get("comparison_version"), "created_utc": created_utc, "status": "success",
                "evidence_label": model.get("evidence_label"),
                "model_sha256": hashlib.sha256(_json(model).encode()).hexdigest(),
                "artifacts": {name: {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
                              for name, path in (("comparison_model.json", model_path), ("comparison.md", body_path))},
                "exports": exports, "figures": {"definitions": figures, "note": figure_note},
                "source_runs": [{key: run[key] for key in ("label", "run_id", "analysis_id", "run_dir", "evidence_label")} for run in model.get("runs", [])],
                "source_runs_modified": False,
                "versions": {name: _version(name) for name in ("dcdc-bench", "plotly", "pydantic")}}
    _write_atomic(out / "comparison_manifest.json", _json(manifest))
    return out
