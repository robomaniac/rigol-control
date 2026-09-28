#!/usr/bin/env python3
"""Render standalone figure-theme previews for one issued report model.

Usage:
    python tools/theme_preview.py <report_model.json> <out_dir>

Writes ``index.html`` plus one page per theme variant (``variant-a.html``,
``variant-b.html``, ``variant-c.html``). Every page embeds Plotly.js once and
works from ``file://`` with the network blocked. Only ``Figure.to_html`` is
used: no browser, Kaleido, Quarto, PDF or instrument access is involved.

The previews are display experiments. They plot exactly the qualified points
of the supplied model, keep the figure registry order and numbering, and carry
the evidence label, run identity and measurement boundary on every figure.
They never add, smooth or interpolate measurements.

The renderer itself (``dcdc_bench.reporting.renderer``) is untouched; the
option document ``docs/report-aesthetics-options.md`` maps each variant back
to the renderer functions and CSS variables that would change.
"""
from __future__ import annotations

import html
import itertools
import json
import math
import sys
from pathlib import Path

# Slot order mirrors renderer.VOLTAGE_STYLE_INDEX: the same input condition keeps
# the same slot in every figure, including a report showing a subset of them.
VOLTAGE_SLOT = {"12": 0, "24": 1, "36": 2}
SYMBOLS = ("circle", "square", "diamond", "triangle-up", "triangle-down", "cross")
# Extra conditions beyond the three standard slots take these dataviz reference
# slots (validated adjacent in both modes there; unused by the current run).
EXTRA_SLOT_COLORS = ("#eda100", "#e87ba4", "#4a3aa7")

THEMES = {
    "a": {
        "slug": "variant-a",
        "name": "Variant A · Datasheet classic",
        "tagline": "Pololu / TI-like: white surface, light gray grid on both axes, thin solid lines with "
                   "small distinct markers, boxed legend inside the plot, plain Arial/Helvetica labels.",
        "palette": ["#1157a4", "#40a35c", "#a63c0c"],
        "palette_dark": ["#4064b9", "#00a672", "#a24e10"],
        "dashes": ["solid", "solid", "solid"],
        "line_width": 1.6,
        "marker_size": 5,
        "font": {"family": "Arial, Helvetica, 'Liberation Sans', sans-serif", "size": 13, "color": "#1a1a1a"},
        "muted": "#555555",
        "title": {"size": 15, "x": 0.5, "xanchor": "center", "bold": False},
        "grid": {"color": "#d9d9d9", "width": 1, "dash": "solid", "x": True},
        "axis": {"showline": True, "linecolor": "#333333", "linewidth": 1, "mirror": True,
                 "ticks": "outside", "ticklen": 5, "tickcolor": "#333333"},
        "legend": "inside",
        "legend_box": {"bordercolor": "#444444", "borderwidth": 1, "bgcolor": "rgba(255,255,255,0.94)"},
        "plot_bg": "#ffffff",
        "paper_bg": "#ffffff",
        "halo": False,
        "height": 540,
        "margin": {"l": 72, "r": 24, "t": 64, "b": 128},
        "changes": [
            "Palette (12 V / 24 V / 36 V slots): #1157a4 blue, #40a35c green, #a63c0c brick — muted, "
            "saturated, validated all-pairs for protan/deutan (worst ΔE 13.5) on white.",
            "Lines 1.6 px solid; markers 5 px circle/square/diamond so shape still separates the conditions.",
            "Grid: 1 px solid #d9d9d9 on both axes; all four axis lines drawn (boxed plot), ticks outside.",
            "Legend inside the plot in a thin-bordered white box, placed in the emptiest corner of each figure.",
            "Typography: Arial/Helvetica 13 px labels, 15 px centered figure title, no letter-spacing tricks.",
        ],
        "css": (
            "body{font-family:Arial,Helvetica,'Liberation Sans',sans-serif;color:#1a1a1a;font-size:15px;line-height:1.55;"
            "max-width:1040px;margin:1.5rem auto;padding:0 1rem;background:#fff}"
            "h1{font-size:1.45rem;margin:.2rem 0 .3rem}h2{font-size:1.1rem;margin:1.8rem 0 .5rem;border-bottom:1px solid #bbb;padding-bottom:.25rem}"
            ".figure{border:1px solid #c8c8c8;padding:.4rem .4rem .2rem;margin:1.1rem 0;background:#fff}"
            "figcaption{font-size:.84rem;color:#444;margin:.35rem .3rem .4rem}"
        ),
    },
    "b": {
        "slug": "variant-b",
        "name": "Variant B · Modern engineering",
        "tagline": "EPC-like: white page with a faint plot panel, horizontal-only hairline grid, heavier lines, "
                   "large labels, legend below the plot, colors ordered cool→warm with rising input voltage.",
        "palette": ["#2c57cd", "#1ca288", "#c65102"],
        "palette_dark": ["#315dd4", "#27a98e", "#c65102"],
        "dashes": ["solid", "solid", "solid"],
        "line_width": 2.6,
        "marker_size": 7,
        "font": {"family": "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
                 "size": 15, "color": "#183047"},
        "muted": "#516677",
        "title": {"size": 18, "x": 0.0, "xanchor": "left", "bold": True},
        "grid": {"color": "#e3e8ed", "width": 1, "dash": "solid", "x": False},
        "axis": {"showline": True, "linecolor": "#c9d2da", "linewidth": 1, "mirror": False,
                 "ticks": "", "ticklen": 0, "tickcolor": "#c9d2da"},
        "legend": "below",
        "legend_box": {"bordercolor": "rgba(0,0,0,0)", "borderwidth": 0, "bgcolor": "rgba(0,0,0,0)"},
        "plot_bg": "#f8fafc",
        "paper_bg": "#ffffff",
        "halo": True,
        "height": 600,
        "margin": {"l": 78, "r": 28, "t": 72, "b": 190},
        "changes": [
            "Palette ordered by input voltage, cool→warm: #2c57cd blue (12 V), #1ca288 teal (24 V), "
            "#c65102 orange (36 V); validated all-pairs (worst CVD ΔE 12.9) on white.",
            "Lines 2.6 px with 7 px markers; a 12 %-alpha halo under each line (decorative, optional).",
            "Grid: horizontal hairlines only (#e3e8ed) on a faint #f8fafc panel; no boxed frame.",
            "Legend below the plot, horizontal; larger 15 px labels, bold 18 px left-aligned figure title.",
            "Typography: system UI sans (matches the current report.css body font).",
        ],
        "css": (
            "body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',sans-serif;color:#183047;font-size:16px;"
            "line-height:1.6;max-width:1120px;margin:1.5rem auto;padding:0 1rem;background:#fff}"
            "h1{font-size:1.7rem;font-weight:650;letter-spacing:-.02em;margin:.2rem 0 .3rem}"
            "h2{font-size:1.25rem;font-weight:650;letter-spacing:-.015em;margin:2rem 0 .5rem;border-bottom:1px solid #dce4e9;padding-bottom:.3rem}"
            ".figure{margin:1.3rem 0 1.8rem}figcaption{font-size:.88rem;color:#516677;font-style:italic;margin:.3rem 0 0}"
        ),
    },
    "c": {
        "slug": "variant-c",
        "name": "Variant C · Print-first monochrome-plus-accent",
        "tagline": "Designed to photocopy: dark high-contrast accent per input condition, plus solid/dash/dot "
                   "line styles and distinct markers, dashed gray grid, black boxed axes.",
        "palette": ["#114d9a", "#19825b", "#954200"],
        "palette_dark": None,
        "dashes": ["solid", "dash", "dot"],
        "line_width": 2.0,
        "marker_size": 8,
        "font": {"family": "'Liberation Sans', 'DejaVu Sans', Arial, sans-serif", "size": 14, "color": "#000000"},
        "muted": "#333333",
        "title": {"size": 16, "x": 0.0, "xanchor": "left", "bold": True},
        "grid": {"color": "#a8a8a8", "width": 1, "dash": "dash", "x": True},
        "axis": {"showline": True, "linecolor": "#000000", "linewidth": 1.2, "mirror": True,
                 "ticks": "outside", "ticklen": 6, "tickcolor": "#000000"},
        "legend": "inside",
        "legend_box": {"bordercolor": "#000000", "borderwidth": 1.2, "bgcolor": "#ffffff"},
        "plot_bg": "#ffffff",
        "paper_bg": "#ffffff",
        "halo": False,
        "height": 540,
        "margin": {"l": 74, "r": 24, "t": 64, "b": 128},
        "changes": [
            "Palette: #114d9a navy, #19825b dark green, #954200 dark rust — every mark ≥ 4.8:1 on white, "
            "lightness stepped (OKLCH L 0.43 / 0.54 / 0.48) so a grayscale copy still separates them.",
            "Line style carries identity too: solid / dashed / dotted, 2 px, with 8 px circle/square/diamond markers.",
            "Grid: dashed 1 px #a8a8a8 on both axes (as requested for print; dataviz guidance prefers solid hairlines).",
            "Black 1.2 px boxed axes with outside ticks; opaque white boxed legend inside the plot.",
            "Typography: Liberation Sans / DejaVu Sans 14 px — the same faces the Typst PDF uses today.",
        ],
        "css": (
            "body{font-family:'Liberation Sans','DejaVu Sans',Arial,sans-serif;color:#000;font-size:15px;line-height:1.5;"
            "max-width:1040px;margin:1.5rem auto;padding:0 1rem;background:#fff}"
            "h1{font-size:1.5rem;margin:.2rem 0 .3rem}h2{font-size:1.15rem;margin:1.8rem 0 .5rem;border-bottom:2px solid #000;padding-bottom:.2rem}"
            ".figure{border:1px solid #555;padding:.4rem .4rem .2rem;margin:1.1rem 0;background:#fff}"
            "figcaption{font-size:.85rem;color:#222;margin:.35rem .3rem .4rem}"
        ),
    },
}

DECISION_QUESTIONS = [
    "Legend inside the plot (Pololu/TI, saves vertical space, needs a free corner) or outside "
    "(current: horizontal above; Variant B: below)?",
    "Color by input voltage as an ordered cool→warm ramp (Variant B) or fixed per-condition hues "
    "(current blue/vermilion/magenta; Variants A/C)?",
    "Markers on every measured point (current, all variants) or sparse markers with a marker-per-N rule "
    "while keeping every point in hover/table?",
    "Offer a dark HTML option (validated dark steps exist for A and B; C is print-only) or stay light-only?",
    "Serif or sans in the PDF (Typst currently uses DejaVu Sans / Liberation Sans; all previews are sans)?",
    "One figure per quantity in sequence (current) or a 2 × 2 dashboard grid of the four figures on the "
    "first page (toggle available on each variant page)?",
    "Add a Pololu-style 'efficiency vs input voltage at fixed loads' figure? This run has only two input "
    "conditions (24 V and 35.8 V), so it needs the planned multi-voltage run first.",
    "Keep the boxed (four-sided) plot frame of A/C or the open EPC-like frame of B?",
    "Keep the three-line footer inside each figure (survives SVG/PNG export) or move identity into the HTML caption?",
]

FIXED_ELEMENTS = [
    "Evidence label (MEASURED) on every figure, the run ID, analysis ID, DUT identity and the declared "
    "boundary 'source-to-load-terminal path (input and output wiring included)' in each footer.",
    "Every qualified measured point drawn as a marker; unqualified points leave a gap (never joined).",
    "Figure order and numbering from the report model registry; axis titles with units from the model.",
    "Reference lines (nominal output voltage, supply current setting) shown only where the model supplies them, "
    "labeled as references, never as measurements.",
    "Brief §12.2 direction: restrained document layout, light grids, visible measured markers, no decorative cards.",
]


# --- small color checks (Python port of the dataviz validate_palette.js checks 2-5) ----------------
_MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
}


def _lin(color: str) -> list[float]:
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in values]


def _oklab(rgb: list[float]) -> list[float]:
    cbrt = lambda v: math.copysign(abs(v) ** (1 / 3), v)
    r, g, b = rgb
    l = cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]


def _delta_e(a: str, b: str, kind: str | None = None) -> float:
    def sim(color):
        rgb = _lin(color)
        if not kind:
            return rgb
        matrix = _MACHADO[kind]
        return [min(1, max(0, sum(matrix[i][j] * rgb[j] for j in range(3)))) for i in range(3)]
    return 100 * math.dist(_oklab(sim(a)), _oklab(sim(b)))


def _contrast(a: str, b: str) -> float:
    def lum(color):
        r, g, b_ = _lin(color)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def palette_report(palette: list[str], surface: str, mode: str) -> dict:
    """All-pairs checks: lines can cross, so any two conditions may be neighbours."""
    pairs = list(itertools.combinations(palette, 2))
    cvd = min(_delta_e(a, b, kind) for a, b in pairs for kind in ("protan", "deutan"))
    normal = min(_delta_e(a, b) for a, b in pairs)
    contrast = min(_contrast(c, surface) for c in palette)
    lightness = [_oklab(_lin(c))[0] for c in palette]
    band = (0.43, 0.77) if mode == "light" else (0.48, 0.67)
    in_band = all(band[0] <= L <= band[1] for L in lightness)
    verdict = ("FAIL" if cvd < 6 or normal < 15 or not in_band else "WARN" if cvd < 8 or contrast < 3 else "PASS")
    return {"mode": mode, "surface": surface, "cvd": cvd, "normal": normal, "contrast": contrast,
            "lightness": lightness, "verdict": verdict}


# --- model helpers ----------------------------------------------------------------------------------
def finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def condition_key(series: dict) -> str:
    value = series.get("selection_key") or series.get("vin_target_V", series["id"])
    if finite(value):
        return str(int(value)) if int(value) == value else str(value)
    return str(value)


def condition_styles(model: dict, theme: dict) -> dict[str, dict]:
    """Slot assignment mirroring renderer._condition_styles for voltage conditions.

    Standard 12/24/36 V keys keep their slot; declared-but-unmeasured nominal
    voltages reserve theirs without creating a trace; other conditions take the
    remaining slots in sorted order.
    """
    conditions: dict[str, dict | None] = {}
    for spec in model["figures"]:
        for series in spec["series"]:
            conditions.setdefault(condition_key(series), series)
    declared = (model.get("execution", {}).get("voltage_efficiency_sweep") or {}).get("nominal_input_voltages_V", [])
    if isinstance(declared, list) and all(finite(v) for v in declared):
        conditions = {**{condition_key({"vin_target_V": v, "id": ""}): None for v in sorted(set(declared))},
                      **conditions}
    ordered = sorted(conditions, key=lambda k: (0, float(k)) if k.replace(".", "", 1).isdigit() else (1, k))
    assigned = {key: VOLTAGE_SLOT[key] for key in ordered if key in VOLTAGE_SLOT}
    free = [i for i in range(len(theme["palette"]) + len(EXTRA_SLOT_COLORS)) if i not in set(VOLTAGE_SLOT.values())]
    for key in ordered:
        if key not in assigned:
            assigned[key] = free.pop(0) if free else len(theme["palette"]) - 1
    colors = list(theme["palette"]) + list(EXTRA_SLOT_COLORS)
    dashes = list(theme["dashes"]) + ["dashdot", "longdash", "longdashdot"]
    return {key: {"color": colors[slot % len(colors)], "dash": dashes[slot % len(dashes)],
                  "symbol": SYMBOLS[slot % len(SYMBOLS)]} for key, slot in assigned.items()}


def figure_reference(model: dict, spec: dict) -> dict | None:
    """Supplied nominal/limit values only; mirrors renderer._figure_references."""
    points = {p["point_id"]: p for p in model["points"]}
    nominal = model.get("dut", {}).get("ratings", {}).get("output_voltage_nominal_V")
    execution = model.get("execution", {})
    search = execution.get("source_limit_search") or execution.get("voltage_efficiency_sweep") or {}
    source_current = spec["id"] == "fig-source-current" and spec["y_key"] == "Iin_A"
    value = nominal if spec["y_key"] == "Vout_V" else search.get("input_current_limit_A") if source_current else None
    if not finite(value) or value <= 0:
        return None
    values = [float(value)] + ([0.0] if source_current else [])
    for series in spec["series"]:
        for pid in series["point_ids"]:
            point = points[pid]
            if point.get("qualification") == "valid" and finite(point.get(spec["x_key"])) and finite(point.get(spec["y_key"])):
                values.append(float(point[spec["y_key"]]))
    low, high = min(values), max(values)
    padding = max(.08 * (high - low), .001 * abs(value), .001)
    return {"value": float(value), "label": f"Supply limit {value:g} A" if source_current else f"Nominal {value:g} V",
            "y_range": [low - padding, high + padding]}


def series_rows(model: dict, spec: dict, series: dict):
    points = {p["point_id"]: p for p in model["points"]}
    rows = [points[pid] for pid in series["point_ids"]]
    x = [p.get(spec["x_key"]) for p in rows]
    y = [p.get(spec["y_key"]) if p.get("qualification") == "valid" else None for p in rows]
    plotted = [(float(a), float(b)) for a, b in zip(x, y) if finite(a) and finite(b)]
    return rows, x, y, plotted


def identity(model: dict) -> str:
    dut = model.get("dut", {})
    return str(dut.get("identity", {}).get("model", dut.get("model", dut.get("name", "DUT"))))


def footer_lines(model: dict, spec: dict, conditions: list[str]) -> list[str]:
    return [f"{model.get('evidence_label', 'Evidence status not supplied')} | {identity(model)} | "
            f"Run {model['run_id']} | Analysis {model.get('analysis_id', 'n/a')}",
            f"{spec['id']} | {'; '.join(conditions) or 'no qualified plotted conditions'}",
            f"Boundary: {model.get('boundary', 'not supplied')} | "
            "Aggregated settled DC points; uncertainty unquantified unless explicitly supplied"]


def emptiest_corner(all_points: list[tuple[float, float]], y_range=None) -> dict:
    """Place an inside legend where the fewest measured points sit."""
    if not all_points:
        return {"x": .98, "y": .98, "xanchor": "right", "yanchor": "top"}
    xs, ys = [p[0] for p in all_points], [p[1] for p in all_points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = (y_range if y_range else (min(ys), max(ys)))
    spanx, spany = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    counts = {"tr": 0, "br": 0, "tl": 0, "bl": 0}
    for x, y in all_points:
        right = (x - x0) / spanx >= .5
        top = (y - y0) / spany >= .5
        counts[("t" if top else "b") + ("r" if right else "l")] += 1
    corner = min(("tr", "br", "tl", "bl"), key=lambda c: counts[c])
    return {"x": .98 if corner.endswith("r") else .02, "y": .97 if corner.startswith("t") else .03,
            "xanchor": "right" if corner.endswith("r") else "left",
            "yanchor": "top" if corner.startswith("t") else "bottom"}


def rgba(color: str, alpha: float) -> str:
    return f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},{alpha})"


# --- figure construction ----------------------------------------------------------------------------
def build_figure(model: dict, spec: dict, number: int, theme: dict, styles: dict, *, compact: bool = False):
    import plotly.graph_objects as go

    figure = go.Figure()
    conditions, all_points = [], []
    reference = figure_reference(model, spec)
    for series in spec["series"]:
        rows, x, y, plotted = series_rows(model, spec, series)
        if not plotted:
            continue  # a requested-but-unmeasured condition creates no trace or legend entry
        style = styles[condition_key(series)]
        label = str(series.get("label", series["id"]))
        conditions.append(label)
        all_points.extend(plotted)
        connect = series.get("connect_points", True)
        if theme["halo"] and connect:
            figure.add_trace(go.Scatter(x=x, y=y, mode="lines", showlegend=False, hoverinfo="skip",
                                        connectgaps=False, legendgroup=series["id"],
                                        line={"width": theme["line_width"] + 6, "color": rgba(style["color"], .12)}))
        figure.add_trace(go.Scatter(
            x=x, y=y, name=html.escape(label), mode="lines+markers" if connect else "markers",
            line={"width": theme["line_width"], "color": style["color"], "dash": style["dash"]},
            marker={"size": theme["marker_size"] * (0.8 if compact else 1.0), "color": style["color"],
                    "symbol": style["symbol"], "line": {"width": 1, "color": theme["plot_bg"]}},
            connectgaps=False, legendgroup=series["id"], customdata=[p["point_id"] for p in rows],
            hovertemplate=(f"%{{customdata}}<br>{html.escape(spec['x_label'])}: %{{x:.5g}}<br>"
                           f"{html.escape(spec['y_label'])}: %{{y:.5g}}<extra>%{{fullData.name}}</extra>")))

    font = dict(theme["font"])
    if compact:
        font["size"] = max(11, font["size"] - 1)
    title_text = (f"Efficiency vs output current — measured input conditions" if compact
                  else f"Figure {number}. {spec['title']}")
    title_text = html.escape(title_text)
    if theme["title"]["bold"]:
        title_text = f"<b>{title_text}</b>"
    grid = theme["grid"]
    axis_common = {"gridcolor": grid["color"], "gridwidth": grid["width"], "griddash": grid["dash"],
                   "zeroline": False, "showline": theme["axis"]["showline"], "linecolor": theme["axis"]["linecolor"],
                   "linewidth": theme["axis"]["linewidth"], "mirror": theme["axis"]["mirror"],
                   "ticks": theme["axis"]["ticks"], "ticklen": theme["axis"]["ticklen"],
                   "tickcolor": theme["axis"]["tickcolor"], "tickformat": "~g",
                   "title": {"font": {"size": font["size"] + (0 if compact else 1)}}}
    height = 430 if compact else theme["height"]
    margin = ({"l": 64, "r": 22, "t": 62, "b": 96} if compact else dict(theme["margin"]))
    if compact and theme["legend"] == "below":
        margin["b"] = 140
    layout = {
        "template": "plotly_white", "height": height, "autosize": True,
        "font": font, "paper_bgcolor": theme["paper_bg"], "plot_bgcolor": theme["plot_bg"],
        "title": {"text": title_text, "x": theme["title"]["x"], "xanchor": theme["title"]["xanchor"],
                  "font": {"size": theme["title"]["size"] - (2 if compact else 0)}},
        "margin": margin,
        "xaxis": {**axis_common, "showgrid": grid["x"], "nticks": 7, "title": {**axis_common["title"], "text": html.escape(spec["x_label"])}},
        "yaxis": {**axis_common, "showgrid": True, "nticks": 6, "title": {**axis_common["title"], "text": html.escape(spec["y_label"])}},
        "hoverlabel": {"bgcolor": "#ffffff", "bordercolor": "#9aa5ad", "font": {"family": font["family"], "size": 12, "color": font["color"]}},
        "hovermode": "closest",
    }
    legend_font = {"size": font["size"] - (2 if compact else 1)}
    if theme["legend"] == "inside" or compact:
        corner = emptiest_corner(all_points, reference["y_range"] if reference else None)
        layout["legend"] = {**corner, "orientation": "v", "font": legend_font, **theme["legend_box"],
                            "itemsizing": "constant"}
        if compact and theme["legend"] == "below":
            layout["legend"] = {**theme["legend_box"], "orientation": "h", "x": 0, "y": -0.28, "xanchor": "left",
                                "yanchor": "top", "font": legend_font}
    else:
        layout["legend"] = {"orientation": "h", "x": 0, "y": -0.2, "xanchor": "left", "yanchor": "top",
                            "font": legend_font, **theme["legend_box"], "itemsizing": "constant"}
    figure.update_layout(**layout)

    footer = footer_lines(model, spec, conditions)
    if compact:
        footer = [f"{model.get('evidence_label', 'Evidence status not supplied')} | {identity(model)} | "
                  f"Run {model['run_id']} | {model.get('boundary', 'boundary not supplied')}"]
    footer_y = -0.36 if theme["legend"] == "below" and not compact else (-0.24 if compact else -0.21)
    if compact and theme["legend"] == "below":
        footer_y = -0.46
    figure.add_annotation(text="<br>".join(html.escape(line) for line in footer), xref="paper", yref="paper",
                          x=0, y=footer_y, xanchor="left", yanchor="top", align="left", showarrow=False,
                          font={"size": 10 if compact else 11, "color": theme["muted"]})
    evidence = str(model.get("evidence_label", "")).strip()
    if evidence:
        badge_color = font["color"] if evidence.upper() == "MEASURED" else "#785018"
        figure.add_annotation(text=f"<b>{html.escape(evidence)}</b>", xref="paper", yref="paper", x=1, y=1,
                              xanchor="right", yanchor="bottom", yshift=10, showarrow=False,
                              font={"size": 10 if compact else 11, "color": badge_color},
                              bordercolor=badge_color, borderwidth=1, borderpad=3, bgcolor=theme["paper_bg"])
    if reference and not compact:
        figure.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y", y0=reference["value"], y1=reference["value"],
                         line={"color": "#77828c", "width": 1.2, "dash": "dash"}, layer="below")
        figure.add_annotation(xref="paper", x=0.01, yref="y", y=reference["value"], text=html.escape(reference["label"]),
                              showarrow=False, xanchor="left", yanchor="bottom",
                              font={"size": 11, "color": theme["muted"]}, bgcolor=rgba(theme["plot_bg"], .9))
        figure.update_yaxes(range=reference["y_range"], autorange=False)
    return figure


def figure_html(figure, div_id: str, include_js: bool) -> str:
    return figure.to_html(full_html=False, include_plotlyjs=include_js, div_id=div_id,
                          default_width="100%", default_height=f"{figure.layout.height}px",
                          config={"responsive": True, "displaylogo": False,
                                  "modeBarButtonsToRemove": ["select2d", "lasso2d"]})


# --- pages ------------------------------------------------------------------------------------------
PAGE_JS = """
(function(){
  const wrap=document.getElementById('figures');
  const resize=()=>{for(const g of document.querySelectorAll('.plotly-graph-div')){try{Plotly.Plots.resize(g);}catch(e){}}};
  for(const b of document.querySelectorAll('[data-layout]')){
    b.addEventListener('click',()=>{wrap.className='figures '+b.dataset.layout;
      for(const o of document.querySelectorAll('[data-layout]'))o.setAttribute('aria-pressed',String(o===b));
      setTimeout(resize,30);});
  }
})();
"""

SHARED_CSS = (
    ".figures.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}"
    ".figures.grid .figure{margin:0}.figures.grid .compact{grid-column:1/-1}"
    ".toolbar{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin:.8rem 0;font-size:.85rem}"
    ".toolbar button{font:inherit;padding:.3rem .7rem;border:1px solid #888;background:#fff;border-radius:4px;cursor:pointer}"
    ".toolbar button[aria-pressed=true]{background:#e8eef3;border-color:#456}"
    "nav a{margin-right:1rem}.meta{font-size:.85rem;color:#555;overflow-wrap:anywhere}"
    "ul.tight li{margin:.2rem 0}.swatch{display:inline-block;width:1.1em;height:1.1em;vertical-align:-.2em;border:1px solid #999;margin-right:.3em}"
    "table.spec{border-collapse:collapse;font-size:.85rem;width:100%}table.spec th,table.spec td{border:1px solid #ccc;padding:.35rem .5rem;text-align:left;vertical-align:top}"
    "@media(max-width:800px){.figures.grid{grid-template-columns:1fr}}"
)


def model_meta(model: dict) -> str:
    fields = [("Title", model.get("title", "")), ("Evidence", model.get("evidence_label", "")),
              ("DUT", identity(model)), ("Run", model["run_id"]), ("Analysis", model.get("analysis_id", "")),
              ("Report revision", model.get("report_revision", "")), ("Boundary", model.get("boundary", ""))]
    return " · ".join(f"<b>{html.escape(str(k))}</b> {html.escape(str(v))}" for k, v in fields if v)


def render_variant(model: dict, key: str, theme: dict) -> str:
    styles = condition_styles(model, theme)
    parts, include_js = [], True
    for number, spec in enumerate(model["figures"], 1):
        figure = build_figure(model, spec, number, theme, styles)
        parts.append(f'<figure class="figure" id="{html.escape(spec["id"])}">'
                     f'{figure_html(figure, f"fig-{key}-{number}", include_js)}'
                     f'<figcaption><b>Figure {number}. {html.escape(str(spec["title"]))}.</b> '
                     f'{html.escape(str(spec.get("caption", "")))}</figcaption></figure>')
        include_js = False
    efficiency = next((s for s in model["figures"] if s.get("y_key") == "efficiency_pct"), model["figures"][0])
    summary = build_figure(model, efficiency, 0, theme, styles, compact=True)
    summary_html = (f'<figure class="figure compact" style="max-width:760px">'
                    f'{figure_html(summary, f"fig-{key}-summary", False)}'
                    f'<figcaption>Pololu-style summary panel: the same qualified efficiency points as Figure '
                    f'{model["figures"].index(efficiency) + 1}, compact size, legend inside. It is a display variant of '
                    f'existing evidence, not an additional measurement.</figcaption></figure>')
    others = " ".join(f'<a href="{t["slug"]}.html">{html.escape(t["name"].split(" · ")[0])}</a>'
                      for k, t in THEMES.items() if k != key)
    changes = "".join(f"<li>{html.escape(c)}</li>" for c in theme["changes"])
    fixed = "".join(f"<li>{html.escape(c)}</li>" for c in FIXED_ELEMENTS)
    legend_rows = "".join(
        f'<tr><td><span class="swatch" style="background:{s["color"]}"></span>{html.escape(k)} V slot</td>'
        f'<td>{s["color"]}</td><td>{s["dash"]}</td><td>{s["symbol"]}</td></tr>' for k, s in styles.items())
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(theme['name'])} — figure theme preview</title>
<style>{theme['css']}{SHARED_CSS}</style></head><body>
<nav><a href="index.html">← All variants</a> {others}</nav>
<h1>{html.escape(theme['name'])}</h1>
<p>{html.escape(theme['tagline'])}</p>
<p class="meta">{model_meta(model)}</p>
<p class="meta">Preview only: figures are re-drawn from the issued report model with a different visual theme. The issued report, its figures and its data are unchanged. Interactive hover shows point IDs; drag to zoom, double-click to reset.</p>
<div class="toolbar"><span>Layout:</span>
<button type="button" data-layout="single" aria-pressed="true">Single column</button>
<button type="button" data-layout="grid" aria-pressed="false">2 × 2 grid</button></div>
<div id="figures" class="figures single">{''.join(parts)}</div>
<h2>Summary panel</h2>
{summary_html}
<h2>What this variant changes</h2><ul class="tight">{changes}</ul>
<h2>What stays fixed</h2><ul class="tight">{fixed}</ul>
<h2>Condition styles in this variant</h2>
<table class="spec"><thead><tr><th>Input condition</th><th>Color</th><th>Line</th><th>Marker</th></tr></thead><tbody>{legend_rows}</tbody></table>
<p class="meta">Reserved slots (for example 12 V in this run) create no trace, legend entry or measurement; they only keep the same condition on the same style across reports.</p>
<p class="meta">Generated by dcdc-bench/tools/theme_preview.py with Plotly's HTML export; Plotly.js is embedded once per page and no network access is required.</p>
<script>{PAGE_JS}</script>
</body></html>"""


def render_index(model: dict, sizes: dict[str, int]) -> str:
    rows = []
    for key, theme in THEMES.items():
        reports = [palette_report(theme["palette"], "#ffffff", "light")]
        if theme["palette_dark"]:
            reports.append(palette_report(theme["palette_dark"], "#1a1a19", "dark"))
        swatches = "".join(f'<span class="swatch" style="background:{c}"></span>' for c in theme["palette"])
        checks = "<br>".join(
            f"{r['mode']}: {r['verdict']} · worst CVD ΔE {r['cvd']:.1f} · normal ΔE {r['normal']:.1f} · "
            f"min contrast {r['contrast']:.2f}:1" for r in reports)
        rows.append(
            f'<tr><td><a href="{theme["slug"]}.html"><b>{html.escape(theme["name"])}</b></a><br>'
            f'<span class="meta">{sizes.get(theme["slug"], 0) / 1e6:.1f} MB</span></td>'
            f'<td>{html.escape(theme["tagline"])}</td>'
            f'<td>{swatches}<br><code>{", ".join(theme["palette"])}</code>'
            + (f'<br>dark: <code>{", ".join(theme["palette_dark"])}</code>' if theme["palette_dark"] else
               "<br>dark: not designed (print-first)")
            + f'</td><td>{checks}</td></tr>')
    current = palette_report(["#0072B2", "#D55E00", "#CC33AA"], "#ffffff", "light")
    questions = "".join(f"<li>{html.escape(q)}</li>" for q in DECISION_QUESTIONS)
    fixed = "".join(f"<li>{html.escape(c)}</li>" for c in FIXED_ELEMENTS)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Report figure theme previews</title>
<style>body{{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#183047;font-size:15px;line-height:1.6;max-width:1100px;margin:1.5rem auto;padding:0 1rem}}
h1{{font-size:1.6rem;font-weight:650;letter-spacing:-.02em}}h2{{font-size:1.2rem;font-weight:650;border-bottom:1px solid #dce4e9;padding-bottom:.3rem;margin-top:2rem}}{SHARED_CSS}</style></head><body>
<h1>Report figure theme previews</h1>
<p>Three visual themes applied to the same issued measurements. Open each variant, compare the four standard figures and the compact summary panel, then answer the questions below. Nothing here changes the issued report.</p>
<p class="meta">{model_meta(model)}</p>
<h2>Variants</h2>
<table class="spec"><thead><tr><th>Variant</th><th>Look</th><th>Palette (12 V / 24 V / 36 V slots)</th><th>Palette checks (all pairs, protan/deutan)</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="meta">Checks are the dataviz method's computable gates (OKLab ΔE×100 under Machado 2009 simulation; ≥ 8 target, 6–8 legal only with line-style/marker encoding; normal-vision floor 15; marks ≥ 3:1 on the surface). The current renderer palette #0072B2 / #D55E00 / #CC33AA passes on adjacent pairs but its blue↔magenta pair measures ΔE {current['cvd']:.1f} all-pairs, which is why every variant here replaces magenta/purple with a green or teal slot.</p>
<h2>What every variant keeps</h2><ul class="tight">{fixed}</ul>
<h2>Decision questions</h2><ol>{questions}</ol>
<p class="meta">Sources consulted: Pololu D24V7F6 product page graphs (efficiency, quiescent current on a log axis, dropout voltage vs output current); TI LMR33630 datasheet §7.8 Typical Characteristics; EPC90120 quick start guide pages 9–11; dataviz skill palette method. See dcdc-bench/docs/report-aesthetics-options.md for the full research summary and renderer mapping.</p>
<p class="meta">Regenerate with: <code>python tools/theme_preview.py &lt;report_model.json&gt; &lt;out_dir&gt;</code></p>
</body></html>"""


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    model_path, out_dir = Path(argv[1]), Path(argv[2])
    model = json.loads(model_path.read_text(encoding="utf-8"))
    for required in ("run_id", "points", "figures"):
        if required not in model:
            raise SystemExit(f"report model lacks '{required}'")
    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for key, theme in THEMES.items():
        page = render_variant(model, key, theme)
        target = out_dir / f"{theme['slug']}.html"
        target.write_text(page, encoding="utf-8")
        sizes[theme["slug"]] = target.stat().st_size
        print(f"wrote {target} ({sizes[theme['slug']] / 1e6:.2f} MB)", file=sys.stderr)
    index = out_dir / "index.html"
    index.write_text(render_index(model, sizes), encoding="utf-8")
    print(f"wrote {index} ({index.stat().st_size / 1e3:.1f} kB)", file=sys.stderr)
    for key, theme in THEMES.items():
        light = palette_report(theme["palette"], "#ffffff", "light")
        print(f"{theme['name']}: light {light['verdict']} (CVD {light['cvd']:.1f}, normal {light['normal']:.1f}, "
              f"contrast {light['contrast']:.2f})", file=sys.stderr)
        if theme["palette_dark"]:
            dark = palette_report(theme["palette_dark"], "#1a1a19", "dark")
            print(f"    dark {dark['verdict']} (CVD {dark['cvd']:.1f}, normal {dark['normal']:.1f}, "
                  f"contrast {dark['contrast']:.2f})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
