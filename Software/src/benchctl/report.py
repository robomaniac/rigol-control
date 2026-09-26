"""Create a standalone, read-only HTML report from a recipe run directory.

Comparison plots use measured values. A separate timeline distinguishes
recorded load commands from measurements. The report also shows data that
survived a failed or interrupted run. No instrument connection is made here.
"""

from __future__ import annotations

import html
import base64
import csv
import hashlib
import io
import json
import math
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from benchctl.paths import DEFAULT_RESULTS_DIR
from benchctl.results import EXECUTION_LOG_FILENAME, MEASUREMENTS_FILENAME, SUMMARY_FILENAME


class ReportError(ValueError):
    """The selected run cannot be used to create a report."""


@dataclass(frozen=True)
class Sample:
    label: str
    timestamp: str
    status: str
    values: dict[str, float]
    requested_current_a: float | None = None
    load_enabled: bool | None = None

    def value(self, name: str) -> float | None:
        return self.values.get(name)

    def voltage_drop_v(self) -> float | None:
        supply = self.value("supply_voltage_v")
        load = self.value("load_voltage_v")
        return _number(supply - load) if supply is not None and load is not None else None

    def current_gap_a(self) -> float | None:
        supply = self.value("supply_current_a")
        load = self.value("load_current_a")
        return _number(supply - load) if supply is not None and load is not None else None

    def lead_resistance_ohm(self) -> float | None:
        current = self.value("load_current_a")
        drop = self.voltage_drop_v()
        if current is None or current <= 0 or drop is None:
            return None
        return _number(drop / current)


_UNITS = {"_v": "V", "_a": "A", "_w": "W", "_ohm": "Ω"}
_COLORS = ("#45dcc6", "#f5ae72", "#a99af8")


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _read_run(run_dir: Path) -> tuple[dict[str, Any], list[Sample], list[str]]:
    if not run_dir.is_dir():
        raise ReportError(f"run directory does not exist: {run_dir}")

    warnings: list[str] = []
    summary_path = run_dir / SUMMARY_FILENAME
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportError(f"cannot read {summary_path}: {exc}") from exc
        if not isinstance(summary, dict):
            raise ReportError(f"{summary_path} must contain a JSON object")
    else:
        summary = {}
        warnings.append("Run summary is missing; this may be a partial run.")

    samples: list[Sample] = []
    measurements_path = run_dir / MEASUREMENTS_FILENAME
    if measurements_path.exists():
        try:
            with measurements_path.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        warnings.append(f"Measurement line {line_number} is invalid JSON and was skipped.")
                        continue
                    if not isinstance(record, dict) or not isinstance(record.get("values"), dict):
                        warnings.append(f"Measurement line {line_number} has no values object and was skipped.")
                        continue
                    values = {
                        str(key): number
                        for key, value in record["values"].items()
                        if (number := _number(value)) is not None
                    }
                    samples.append(
                        Sample(
                            label=str(record.get("save_as") or f"Sample {len(samples) + 1}"),
                            timestamp=str(record.get("timestamp") or ""),
                            status=str(record.get("status") or "ungraded"),
                            values=values,
                        )
                    )
        except OSError as exc:
            raise ReportError(f"cannot read {measurements_path}: {exc}") from exc
    else:
        warnings.append("No measurements file was found; there is no data to plot.")
    samples = _attach_requested_currents(run_dir, samples, warnings)
    return summary, samples, warnings


def _attach_requested_currents(
    run_dir: Path, samples: list[Sample], warnings: list[str]
) -> list[Sample]:
    """Match measurement labels to the latest successful CC command.

    Targets come from execution records. A label is never interpreted as a
    number, so the report cannot mistake a naming convention for a setpoint.
    """
    path = run_dir / EXECUTION_LOG_FILENAME
    if not path.exists():
        return samples
    targets: dict[str, deque[tuple[float | None, bool | None]]] = {}
    current_target: float | None = None
    load_enabled: bool | None = None
    try:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(f"Execution line {line_number} is invalid JSON and was skipped.")
                    continue
                if not isinstance(event, dict) or event.get("phase") != "steps":
                    continue
                detail = event.get("detail")
                if not isinstance(detail, dict):
                    detail = {}
                if event.get("action") == "load.configure_cc" and event.get("status") == "ok":
                    current_target = _number(detail.get("current_a"))
                elif event.get("action") == "load.input_on" and event.get("status") == "ok":
                    load_enabled = True
                elif event.get("action") == "load.input_off" and event.get("status") == "ok":
                    load_enabled = False
                elif event.get("action") == "measure":
                    label = detail.get("save_as")
                    if isinstance(label, str):
                        targets.setdefault(label, deque()).append(
                            (current_target if load_enabled else None, load_enabled)
                        )
    except OSError as exc:
        warnings.append(f"Could not read execution log: {exc}")
        return samples

    matched: list[Sample] = []
    for sample in samples:
        queue = targets.get(sample.label)
        target, enabled = queue.popleft() if queue else (None, None)
        matched.append(replace(sample, requested_current_a=target, load_enabled=enabled))
    return matched


def _format_number(value: float | None, *, digits: int = 4) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"


def _field_label(field: str) -> str:
    for suffix, unit in _UNITS.items():
        if field.endswith(suffix):
            name = field[: -len(suffix)].replace("_", " ").title()
            return f"{name} ({unit})"
    return field.replace("_", " ").title()


def _nice_ticks(low: float, high: float, *, integer: bool = False) -> list[float]:
    """Place ticks at multiples of 1, 2, or 5, without moving any data points."""
    if low == high:
        return [low]
    rough_step = (high - low) / 7
    magnitude = 10 ** math.floor(math.log10(rough_step))
    step = next(factor * magnitude for factor in (1, 2, 5, 10)
                if factor * magnitude >= rough_step)
    if integer:
        step = max(1, step)
    first, last = math.ceil(low / step), math.floor(high / step)
    # Rounding only removes binary arithmetic noise in tick locations.
    return [float(f"{index * step:.12g}") for index in range(first, last + 1)]


def _plot(
    title: str,
    ylabel: str,
    series: list[tuple[str, list[tuple[int, float, float]]]],
    *,
    chart_id: str,
    description: str,
    zero_baseline: bool = False,
    featured: bool = False,
    xlabel: str = "Measured load current (mA)",
    xunit: str = "mA",
    reading_axis: bool = False,
    round_y_ticks: bool = True,
    point_notes: Mapping[int, str] | None = None,
) -> str:
    """Render recorded data in acquisition order, retaining each sample's identity."""
    series = [(name, points) for name, points in series if points]
    card_class = "chart-card featured" if featured else "chart-card"
    header = (
        f'<div class="chart-heading"><h3 id="{chart_id}-title">{_escape(title)}</h3>'
        f'<p>{_escape(description)}</p>'
        f'<div class="mobile-axes"><span>Y: {_escape(ylabel)}</span>'
        f'<span>X: {_escape(xlabel)}</span></div></div>'
    )
    if not series:
        return (
            f'<section class="{card_class}">{header}'
            '<p class="empty">No matching measured values are available.</p></section>'
        )

    width, height = 860, 340
    left, right, top, bottom = 76, 24, 24, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = [x for _, points in series for _, x, _ in points]
    ys = [y for _, points in series for _, _, y in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if zero_baseline:
        y_min, y_max = min(0.0, y_min), max(0.0, y_max)
    x_pad = 0.5 if reading_axis else ((x_max - x_min) * 0.06 or max(abs(x_min) * 0.06, 0.05))
    y_pad = (y_max - y_min) * 0.12 or max(abs(y_min) * 0.01, 0.05)
    x_min -= x_pad
    x_max += x_pad
    if zero_baseline and y_min == 0:
        y_max += y_pad
    else:
        y_min -= y_pad
        y_max += y_pad

    def px(x: float) -> float:
        return left + (x - x_min) / (x_max - x_min) * plot_w

    def py(y: float) -> float:
        return top + (y_max - y) / (y_max - y_min) * plot_h

    elements = [
        f'<rect class="plot-surface" x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" rx="8"/>'
    ]
    y_ticks = (_nice_ticks(y_min, y_max) if round_y_ticks else
               [y_max - tick * (y_max - y_min) / 4 for tick in range(5)])
    for value in y_ticks:
        y = py(value)
        elements.append(
            f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}"/>'
            f'<text class="tick" x="{left-12}" y="{y+4:.2f}" text-anchor="end">{_escape(format(value, ".4g"))}</text>'
        )
    x_ticks = _nice_ticks(x_min, x_max)
    if reading_axis:
        # Include the first and last reading, never fractional or zero indices.
        x_ticks = sorted(set([min(xs), *_nice_ticks(min(xs), max(xs), integer=True), max(xs)]))
    for value in x_ticks:
        x = px(value)
        elements.append(
            f'<text class="tick x-tick" data-tick="{value}" x="{x:.2f}" y="{height-bottom+25}" text-anchor="middle">'
            f'{_escape(format(value, ".12g"))}</text>'
        )
    elements.append(
        f'<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}"/>'
        f'<text class="axis-label" x="{left+plot_w/2:.2f}" y="{height-10}" text-anchor="middle">'
        f'{_escape(xlabel)}</text>'
        f'<text class="axis-label" x="18" y="{top+plot_h/2:.2f}" text-anchor="middle" '
        f'transform="rotate(-90 18 {top+plot_h/2:.2f})">{_escape(ylabel)}</text>'
        f'<line class="cursor-line" x1="0" x2="0" y1="{top}" y2="{height-bottom}" visibility="hidden"/>'
    )
    legend = []
    for index, (name, points) in enumerate(series):
        color = _COLORS[index % len(_COLORS)]
        coords = " ".join(f"{px(x):.3f},{py(y):.3f}" for _, x, y in points)
        if len(points) > 1:
            elements.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>')
        for sample_index, x, y in points:
            position = f"reading {_format_number(x, digits=0)}" if reading_axis else f"{_format_number(x, digits=9)} {xunit}"
            yunit = ylabel.rsplit("(", 1)[-1].rstrip(")")
            note = f" · {point_notes[sample_index]}" if point_notes and sample_index in point_notes else ""
            elements.append(
                f'<circle class="data-point" data-sample="{sample_index}" '
                f'data-series="{_escape(name)}" data-value="{y}" data-x="{x}" '
                f'cx="{px(x):.3f}" cy="{py(y):.3f}" r="4.5" fill="{color}" '
                f'stroke="#101e2b" stroke-width="2"><title>Reading {sample_index + 1} · {_escape(name)}: '
                f'{_escape(_format_number(y, digits=9))} {_escape(yunit)} at {_escape(position)}{_escape(note)}</title></circle>'
            )
        legend.append(f'<span class="legend-item"><i style="background:{color}"></i>{_escape(name)}</span>')
    return (
        f'<section class="{card_class}" id="{chart_id}" data-unit="{_escape(ylabel.rsplit("(", 1)[-1].rstrip(")"))}">'
        + header
        + '<div class="plot-wrap">'
        + f'<svg class="interactive-chart" viewBox="0 0 {width} {height}" role="img" '
        + f'aria-labelledby="{chart_id}-title" aria-describedby="chart-help" tabindex="0" '
        + f'data-left="{left}" data-right="{width-right}" data-top="{top}" data-bottom="{height-bottom}">'
        + "".join(elements)
        + '</svg><div class="plot-tooltip" hidden></div></div><div class="legend">'
        + "".join(legend) + '</div></section>'
    )


def _series(samples: list[Sample], field: str) -> list[tuple[int, float, float]]:
    return [
        (index, current * 1000, value)
        for index, sample in enumerate(samples)
        if (current := sample.value("load_current_a")) is not None
        and math.isfinite(current * 1000)
        and (value := sample.value(field)) is not None
    ]


def _drop_series(samples: list[Sample]) -> list[tuple[int, float, float]]:
    return [
        (index, current * 1000, drop * 1000)
        for index, sample in enumerate(samples)
        if (current := sample.value("load_current_a")) is not None
        and math.isfinite(current * 1000)
        and (drop := sample.voltage_drop_v()) is not None
        and math.isfinite(drop * 1000)
    ]


def _demand_series(samples: list[Sample]) -> list[tuple[str, list[tuple[int, float, float]]]]:
    """Show commands separately from readings; known input-off means zero demand."""
    requested, measured = [], []
    for index, sample in enumerate(samples):
        target = 0.0 if sample.load_enabled is False else sample.requested_current_a
        if target is not None and math.isfinite(target * 1000):
            requested.append((index, index + 1, target * 1000))
        current = sample.value("load_current_a")
        if current is not None and math.isfinite(current * 1000):
            measured.append((index, index + 1, current * 1000))
    return [("Requested current", requested), ("Measured current", measured)]


def _sweep_directions(samples: list[Sample]) -> list[str | None]:
    """Infer direction only from recorded commands, preserving acquisition order."""
    directions: list[str | None] = [None] * len(samples)
    known = [(index, sample.requested_current_a) for index, sample in enumerate(samples)
             if sample.requested_current_a is not None]
    initial = next(("Increasing demand" if right > left else "Reducing demand"
                    for (_, left), (_, right) in zip(known, known[1:]) if right != left),
                   "Holding demand steady")
    previous = None
    direction = initial
    for index, target in known:
        if previous is not None and target != previous:
            direction = "Increasing demand" if target > previous else "Reducing demand"
        directions[index] = direction
        previous = target
    return directions


def _sample_names(samples: list[Sample]) -> list[str]:
    """Describe the recorded demand, without interpreting internal step IDs."""
    names = []
    for index, (sample, direction) in enumerate(zip(samples, _sweep_directions(samples))):
        if sample.load_enabled is False:
            name = "Before drawing current" if index == 0 else "Load switched off"
        elif sample.requested_current_a is not None:
            demand = _format_number(sample.requested_current_a * 1000, digits=3)
            name = f"{demand} mA · {(direction or 'Recorded demand')}"
        elif (current := sample.value("load_current_a")) is not None:
            name = f"{_format_number(current * 1000, digits=3)} mA measured · reading {index + 1}"
        else:
            name = f"Reading {index + 1}"
        names.append(name)
    return names


def _directional_drop_series(samples: list[Sample]) -> list[tuple[str, list[tuple[int, float, float]]]]:
    points = _drop_series(samples)
    directions = _sweep_directions(samples)
    if not any(directions):
        return [("Voltage drop", points)]
    segments: list[tuple[str, list[tuple[int, float, float]]]] = []
    previous = None
    for point in points:
        direction = directions[point[0]] or "Direction not recorded"
        if not segments or segments[-1][0] != direction:
            # Include the measured turning point in both lines without inventing a sample.
            turning = [previous] if previous is not None and direction != "Direction not recorded" and segments[-1][0] != "Direction not recorded" else []
            segments.append((direction, turning))
        segments[-1][1].append(point)
        previous = point
    return segments


def _baseline_supply_v(samples: list[Sample]) -> float | None:
    for sample in samples:
        if sample.load_enabled is True:
            break
        if sample.load_enabled is False and sample.value("supply_voltage_v") is not None:
            return sample.value("supply_voltage_v")
    return None


def _supply_droop_percent(sample: Sample, baseline_v: float | None) -> float | None:
    supply_v = sample.value("supply_voltage_v")
    if baseline_v is None or baseline_v <= 0 or supply_v is None:
        return None
    return _number((baseline_v - supply_v) / baseline_v * 100)


def _metric(label: str, value: str, detail: str = "") -> str:
    return (
        '<div class="metric"><div class="metric-label">' + _escape(label) + '</div>'
        '<div class="metric-value">' + _escape(value) + '</div>'
        '<div class="metric-detail">' + _escape(detail) + '</div></div>'
    )


def _summary_cards(samples: list[Sample], summary: Mapping[str, Any]) -> str:
    names = _sample_names(samples)
    currents = [value for sample in samples if (value := sample.value("load_current_a")) is not None]
    powers = [value for sample in samples if (value := sample.value("load_power_w")) is not None]
    voltages = [value for sample in samples if (value := sample.value("load_voltage_v")) is not None]
    endpoints = [(sample.voltage_drop_v(), index) for index, sample in enumerate(samples)
                 if sample.voltage_drop_v() is not None]
    largest = max(endpoints) if endpoints else None
    highest = max((sample for sample in samples if sample.lead_resistance_ohm() is not None),
                  key=lambda sample: sample.value("load_current_a") or 0, default=None)
    resistance = highest.lead_resistance_ohm() if highest else None
    baseline_v = _baseline_supply_v(samples)
    highest_supply = max((sample for sample in samples if sample.value("load_current_a") is not None
                          and sample.value("supply_voltage_v") is not None),
                         key=lambda sample: sample.value("load_current_a") or 0, default=None)
    supply_droop = _supply_droop_percent(highest_supply, baseline_v) if highest_supply else None
    primary = [
        _metric("Lowest voltage at the device", f"{_format_number(min(voltages) if voltages else None, digits=3)} V",
                "Measured at the electronic load"),
        _metric("Largest supply-to-device difference", f"{_format_number(largest[0] * 1000 if largest else None, digits=2)} mV",
                names[largest[1]] if largest else "Both voltage readings are needed"),
        _metric("Highest measured demand", f"{_format_number(max(currents) * 1000 if currents else None, digits=3)} mA",
                f"{len(currents)} readings with load current"),
    ]
    parameters = summary.get("parameters")
    lower = _number(parameters.get("min_acceptable_voltage_v")) if isinstance(parameters, dict) else None
    if lower is not None and voltages:
        margin = (min(voltages) - lower) * 1000
        position = "below" if margin < 0 else "above"
        primary[0] = _metric(
            "Lowest voltage at the device", f"{_format_number(min(voltages), digits=3)} V",
            f"{_format_number(abs(margin), digits=2)} mV {position} the saved minimum of {_format_number(lower)} V",
        )
    advanced = [
        _metric("Peak load power", f"{_format_number(max(powers) if powers else None, digits=3)} W", "Measured at the electronic load"),
        _metric("Estimated lead resistance", f"{_format_number(resistance * 1000 if resistance is not None else None, digits=1)} mΩ",
                "Apparent value at highest measured current"),
    ]
    current_errors = [(abs(measured - requested) / requested * 100, index)
                      for index, sample in enumerate(samples)
                      if (requested := sample.requested_current_a) is not None and requested > 0
                      and (measured := sample.value("load_current_a")) is not None]
    if current_errors:
        error_pct, index = max(current_errors)
        advanced.append(_metric("Largest current error", f"{_format_number(error_pct, digits=1)} %", names[index]))
    current_gaps = [(abs(gap), index) for index, sample in enumerate(samples)
                    if (gap := sample.current_gap_a()) is not None]
    if current_gaps:
        gap_a, index = max(current_gaps)
        advanced.append(_metric("Largest instrument current gap", f"{_format_number(gap_a * 1000, digits=1)} mA", names[index]))
    if baseline_v is not None:
        advanced.append(_metric("No-load supply voltage", f"{_format_number(baseline_v, digits=3)} V", "Measured baseline"))
        advanced.append(_metric("Supply droop", f"{_format_number(supply_droop, digits=2)} %", "At highest measured load current"))
    return ('<section class="metrics" aria-label="Run highlights">' + "".join(primary) + '</section>'
            '<details class="technical-card"><summary>Instrument details and estimates</summary>'
            '<p class="note">These secondary readings help investigate differences. Sequential readings, instrument '
            'offsets, contacts, and remote sensing affect the estimates.</p>'
            '<div class="metrics">' + "".join(advanced) + '</div></details>')


def _test_explanation(summary: Mapping[str, Any], samples: list[Sample], outcome: str) -> tuple[str, str]:
    parameters = summary.get("parameters")
    parameters = parameters if isinstance(parameters, dict) else {}
    voltage = _number(parameters.get("voltage_v"))
    lower = _number(parameters.get("min_acceptable_voltage_v"))
    upper = _number(parameters.get("max_expected_voltage_v"))
    valid_window = lower is not None and upper is not None and lower <= upper
    title = f"{_format_number(voltage)} V power delivery test" if voltage is not None else "Power delivery test"
    voltages = [sample.value("load_voltage_v") for sample in samples if sample.value("load_voltage_v") is not None]
    targets = [sample.requested_current_a for sample in samples if sample.requested_current_a is not None]
    simulated = summary.get("data_source") == "simulated"
    instruction = ("The electronic load stands in for a device plugged into the power supply. "
                   "It asks for different amounts of current while we measure the voltage at both ends of the wires. "
                   "This shows whether the device receives the chosen voltage as demand changes, "
                   "and the voltage difference between the supply and the device.")
    instructions = [instruction]
    if targets:
        instruction = (f"This run requests {_format_number(min(targets) * 1000, digits=3)} to "
                       f"{_format_number(max(targets) * 1000, digits=3)} mA")
        instruction += ", then reduces the demand again." if "Reducing demand" in _sweep_directions(samples) else "."
        instruction += (f" There are {len(targets)} saved readings at {len(set(targets))} current settings. "
                        "These are separate readings after each settling wait, not a capture of fast changes.")
        instructions.append(instruction)
    if valid_window:
        instructions.append(f"The saved test settings choose {_format_number(lower)}–{_format_number(upper)} V "
                            "as the acceptable range. This is a test setting, not a product certification.")
    if simulated:
        heading = "Illustration only — your bench has not been tested"
        conclusion = ("These generated readings show how to use the report. They cannot tell you whether "
                      "your supply, wires, or connectors pass. Run the recipe with the instruments connected to get that answer.")
    elif not voltages:
        heading = "No device-voltage result yet"
        conclusion = "No voltage readings from the electronic load were saved, so this report cannot assess the voltage delivered to a device."
    elif not valid_window:
        heading = "Voltage recorded; no acceptable range was saved"
        conclusion = (f"The device voltage ranged from {_format_number(min(voltages), digits=3)} to "
                      f"{_format_number(max(voltages), digits=3)} V. The saved run has no voltage window to compare against.")
    else:
        outside = sum(not lower <= value <= upper for value in voltages)
        heading = ("Device voltage went outside the chosen range" if outside else
                   "Device voltage stayed in the chosen range" if outcome == "pass" else
                   "Available device-voltage readings are within range")
        conclusion = (f"{outside} of {len(voltages)} saved device-voltage readings are outside " if outside else
                      f"All {len(voltages)} saved device-voltage readings are within ")
        conclusion += (f"{_format_number(lower)}–{_format_number(upper)} V. "
                       f"The measured range was {_format_number(min(voltages), digits=3)}–{_format_number(max(voltages), digits=3)} V. ")
        conclusion += ("The recorded run passed its checks." if outcome == "pass" and not outside else
                       "These voltage readings alone do not establish an overall pass. Review the saved run outcome and other checks.")
    source_description = f"Provides {_format_number(voltage)} V" if voltage is not None else "Provides electrical power"
    flow = ('<div class="bench-flow" role="group" aria-label="Power supply connected through wires to the electronic load">'
            '<div><b>Power supply</b><span>' + _escape(source_description) + '</span></div>'
            '<span class="flow-arrow" aria-hidden="true">→</span><div><b>Wires and connectors</b><span>Carry power to the device</span></div>'
            '<span class="flow-arrow" aria-hidden="true">→</span><div><b>Electronic load</b><span>Stands in for your circuit</span></div></div>')
    explanation = ('<section class="purpose-card" aria-label="Test purpose and result"><div class="eyebrow">What this test does</div>'
                   '<h2>Does enough voltage reach the device?</h2>'
                   + "".join('<p>' + _escape(paragraph) + '</p>' for paragraph in instructions) + flow
                   + '<div class="conclusion"><h3>' + _escape(heading) + '</h3><p>' + _escape(conclusion) + '</p></div>'
                   '<details class="method"><summary>How to read the two voltage curves</summary>'
                   '<p class="note">If both voltages fall together, inspect the supply settings and current limit. '
                   'If the supply stays steady while the device voltage falls, inspect the wires and connections. '
                   'The difference includes instrument offsets and sequential reading effects; it cannot identify a bad component on its own.</p>'
                   '</details></section>')
    return title, explanation


def _tabular_data(samples: list[Sample]) -> tuple[list[str], list[list[Any]]]:
    preferred = [
        "supply_voltage_v", "load_voltage_v", "supply_current_a", "load_current_a",
        "supply_power_w", "load_power_w",
    ]
    labels = set().union(*(sample.values.keys() for sample in samples)) if samples else set()
    fields = [field for field in preferred if field in labels]
    fields.extend(sorted(labels - set(fields)))
    requested = any(sample.requested_current_a is not None for sample in samples)
    headings = ["Point", "Step", "Status", "Timestamp"]
    if requested:
        headings.append("Requested load current (A)")
    headings.extend(_field_label(field) for field in fields)
    has_gap = "supply_current_a" in labels and "load_current_a" in labels
    has_drop = "supply_voltage_v" in labels and "load_voltage_v" in labels
    has_resistance = has_drop and "load_current_a" in labels
    if has_gap:
        headings.append("Supply − load current (mA)")
    if has_drop:
        headings.append("Voltage drop (mV)")
    if has_resistance:
        headings.append("Estimated lead resistance (mΩ)")
    baseline_v = _baseline_supply_v(samples)
    if baseline_v is not None:
        headings.append("Supply droop from no-load (%)")
    rows: list[list[Any]] = []
    for index, sample in enumerate(samples):
        cells: list[Any] = [index + 1, sample.label, sample.status, sample.timestamp]
        if requested:
            cells.append(sample.requested_current_a)
        cells.extend(sample.value(field) for field in fields)
        if has_gap:
            gap = sample.current_gap_a()
            cells.append(_number(gap * 1000) if gap is not None else None)
        if has_drop:
            drop = sample.voltage_drop_v()
            cells.append(_number(drop * 1000) if drop is not None else None)
        if has_resistance:
            resistance = sample.lead_resistance_ohm()
            cells.append(_number(resistance * 1000) if resistance is not None else None)
        if baseline_v is not None:
            cells.append(_supply_droop_percent(sample, baseline_v))
        rows.append(cells)
    return headings, rows


def _csv_data(samples: list[Sample]) -> str:
    """Export full precision values; imported text cannot become spreadsheet formulas."""
    headings, rows = _tabular_data(samples)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    for row in [headings, *rows]:
        writer.writerow([
            "'" + cell if isinstance(cell, str) and cell.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
            else cell for cell in row
        ])
    return base64.b64encode(buffer.getvalue().encode("utf-8-sig")).decode("ascii")


def _table(samples: list[Sample], *, simulated: bool = False) -> str:
    headings, rows = _tabular_data(samples)
    headings[1] = "Demand during this reading"
    names = _sample_names(samples)
    rendered = []
    for index, cells in enumerate(rows):
        row_class = ' class="failed"' if samples[index].status.lower() in {"fail", "error"} else ""
        rendered_cells = []
        for column, cell in enumerate(cells):
            display = _format_number(cell, digits=6) if isinstance(cell, float) or cell is None else str(cell)
            if column == 1:
                display = f'<button class="point-link" type="button" data-select="{index}">{_escape(names[index])}</button>'
            else:
                display = _escape(display)
            rendered_cells.append(f"<td>{display}</td>")
        rendered.append(f'<tr data-row="{index}"{row_class}>' + "".join(rendered_cells) + "</tr>")
    if not rows:
        rendered.append(f'<tr><td colspan="{len(headings)}" class="empty">No measured samples are available.</td></tr>')
    table = (
        '<section class="data-card" id="measurements"><div class="section-heading"><div>'
        '<div class="eyebrow">The source of every plot</div><h2>Measured points</h2></div>'
        '<label class="search-label" hidden>Filter readings <input id="point-search" type="search" placeholder="Demand, result, or value…"></label></div>'
        f'<p id="table-count" class="note">{len(samples)} points · acquisition order · scroll horizontally for all values</p>'
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Measured point data"><table>'
        '<thead><tr>' + "".join(f'<th scope="col">{_escape(label)}</th>' for label in headings) + '</tr></thead>'
        '<tbody>' + "".join(rendered) + '</tbody></table></div>'
        '<p id="no-matches" class="empty" hidden>No points match this filter.</p>'
        '<details class="method"><summary>How these values are calculated</summary><p class="note">'
        'Voltage drop is supply voltage minus load voltage. Estimated lead resistance is '
        'drop divided by measured load current when current is above zero. Instrument offset, contacts, '
        'and remote sensing affect this apparent value. Requested current, when shown, comes from the '
        'execution log; the comparison plots use measured load current. Supply droop uses a recorded supply reading '
        'with the load off, before the loaded readings, as its baseline. Supply and load current readings are taken sequentially, '
        'so instrument offsets and timing can affect their difference. The CSV keeps full numeric precision; '
        'this table displays up to six decimal places. Original step IDs are retained in the CSV download.</p></details></section>'
    )
    return _example_copy(table) if simulated else table


def _example_copy(markup: str) -> str:
    """Label the example's presentation without changing archived data or script."""
    return (markup.replace("Measured points", "Example readings")
            .replace("Measured", "Example").replace("measured", "example"))


_REPORT_CSS = r"""
.mobile-axes {
  display:none
}
:root {
  color-scheme:dark;
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;
  background:#09111b;
  color:#e4edf6;
  font-synthesis:none
}
* {
  box-sizing:border-box
}
body {
  margin:0;
  background:radial-gradient(ellipse at 12% 0%,#16313c55,transparent 50%)
}
[hidden] {
  display:none!important
}
a {
  color:#60e0ca;
  text-underline-offset:4px
}
button,input {
  font:inherit
}
button,a,input,svg,summary {
  -webkit-tap-highlight-color:transparent
}
button {
  cursor:pointer
}
button:disabled {
  opacity:.35;
  cursor:default
}
button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible,svg:focus-visible,.table-scroll:focus-visible {
  outline:2px solid #64ead2;
  outline-offset:4px
}
.shell {
  max-width:1280px;
  margin:auto;
  padding:36px 28px 56px
}
.topline,.header-main,.section-heading,.inspection-head,.point-nav {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:20px
}
.topline {
  padding-bottom:24px;
  border-bottom:1px solid #294050
}
.brand {
  font-size:.9rem;
  font-weight:750;
  letter-spacing:.05em
}
.brand b {
  color:#64ead2
}
.offline {
  color:#97acbe;
  font-size:.75rem
}
.offline:before {
  content:'';
  display:inline-block;
  width:6px;
  height:6px;
  margin-right:8px;
  border-radius:100%;
  background:#64ead2
}
.header-main {
  padding:34px 0 28px;
  align-items:flex-start
}
.eyebrow {
  color:#61d9c5;
  font-size:.67rem;
  letter-spacing:.17em;
  text-transform:uppercase;
  font-weight:750
}
h1 {
  font-size:clamp(1.85rem,4vw,3rem);
  letter-spacing:-.04em;
  margin:10px 0;
  line-height:1.15;
  overflow-wrap:anywhere
}
h2 {
  font-size:1.15rem;
  letter-spacing:-.02em;
  margin:7px 0 0
}
h3 {
  font-size:1rem;
  margin:0;
  letter-spacing:-.01em
}
.meta {
  color:#97acbe;
  font-size:.82rem;
  line-height:1.8
}
.meta code {
  font-size:.8rem;
  color:#c4d3df;
  overflow-wrap:anywhere
}
.badge {
  display:inline-flex;
  align-items:center;
  padding:6px 10px;
  border:1px solid #3a4a5d;
  border-radius:7px;
  background:#263449;
  color:#dbeafe;
  font-size:.7rem;
  font-weight:750;
  letter-spacing:.04em
}
.badge.pass {
  background:#14362e;
  color:#6fe4c8;
  border-color:#285848
}
.badge.fail {
  background:#4b232e;
  color:#fda4af;
  border-color:#774251
}
.header-actions {
  display:flex;
  gap:8px;
  padding-top:15px;
  flex-shrink:0
}
.button {
  border:1px solid #35505e;
  border-radius:8px;
  background:#162a36;
  color:#ddecf5;
  padding:10px 14px;
  text-decoration:none;
  font-weight:650;
  font-size:.78rem;
  white-space:nowrap
}
.button:hover {
  background:#234251;
  border-color:#568a96
}
.button.primary {
  background:#61dbc1;
  color:#09221d;
  border-color:#61dbc1
}
.button.primary:hover {
  background:#8becd6
}
.metrics {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(195px,1fr));
  gap:10px;
  margin:0 0 28px
}
.metric {
  padding:17px 18px;
  border:1px solid #263b4b;
  border-radius:12px;
  background:linear-gradient(130deg,#142332,#101c28)
}
.metric-label {
  color:#a9bac9;
  font-size:.72rem
}
.metric-value {
  font-size:1.6rem;
  font-weight:680;
  letter-spacing:-.035em;
  margin:7px 0;
  font-variant-numeric:tabular-nums
}
.metric-detail {
  color:#839bac;
  font-size:.66rem;
  line-height:1.5
}
.section-heading {
  margin:0 0 16px
}
.section-copy {
  color:#a0b4c4;
  font-size:.78rem;
  line-height:1.6;
  margin:8px 0 0
}
.charts {
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  gap:16px
}
.chart-card,.data-card,.inspector {
  background:#101d2a;
  border:1px solid #293e4e;
  border-radius:14px
}
.chart-card {
  padding:22px;
  min-width:0
}
.chart-card.featured {
  grid-column:1/-1
}
.chart-heading p {
  color:#97acbe;
  font-size:.76rem;
  margin:7px 0 16px;
  line-height:1.5
}
.chart-card svg {
  display:block;
  width:100%;
  height:auto;
  overflow:visible;
  border-radius:8px;
  touch-action:pan-y
}
.plot-wrap {
  position:relative
}
.plot-surface {
  fill:#0c1723
}
.grid {
  stroke:#294052;
  stroke-dasharray:3 6
}
.axis {
  stroke:#486075
}
.tick,.axis-label {
  fill:#9cb1c2;
  font:12px system-ui,sans-serif
}
.axis-label {
  font-weight:550
}
.cursor-line {
  stroke:#d4ede7;
  stroke-width:1;
  stroke-dasharray:4 4;
  pointer-events:none
}
.data-point {
  transition:r .08s
}
.data-point.is-active {
  r:6;
  stroke:#e8fff9;
  stroke-width:2.5
}
.legend {
  display:flex;
  gap:18px;
  flex-wrap:wrap;
  margin:10px 0 0 8px;
  color:#b9c6d8;
  font-size:.72rem
}
.legend-item {
  display:inline-flex;
  align-items:center;
  gap:7px
}
.legend i {
  width:8px;
  height:8px;
  border-radius:50%;
  display:inline-block
}
.plot-tooltip {
  position:absolute;
  z-index:4;
  pointer-events:none;
  background:#193143f5;
  color:#edf7fe;
  backdrop-filter:blur(8px);
  border:1px solid #628291;
  border-radius:10px;
  padding:11px 13px;
  font-size:.72rem;
  box-shadow:0 12px 32px #0007;
  min-width:185px;
  max-width:min(285px,95%);
  line-height:1.65
}
.tip-title {
  font-weight:750;
  color:#77e6cf;
  margin-bottom:4px;
  overflow-wrap:anywhere
}
.tip-row {
  display:flex;
  justify-content:space-between;
  gap:20px
}
.tip-row span:first-child {
  color:#acbfce
}
.tip-row span:last-child {
  font-variant-numeric:tabular-nums;
  font-weight:600
}
.inspector {
  margin:16px 0 30px;
  padding:18px 22px;
  border-color:#34594f;
  background:linear-gradient(110deg,#122b2c,#10202e 75%)
}
.inspection-head {
  margin-bottom:15px
}
.selected-title {
  font-size:.9rem;
  margin:6px 0 0;
  overflow-wrap:anywhere
}
.point-nav {
  gap:10px;
  color:#b7cbd8;
  font-size:.73rem
}
.point-nav .button {
  padding:6px 12px
}
.selected-grid {
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  gap:14px
}
.selected-grid dt {
  color:#98b2bf;
  font-size:.68rem;
  margin-bottom:5px
}
.selected-grid dd {
  font-size:1.1rem;
  font-variant-numeric:tabular-nums;
  margin:0;
  letter-spacing:-.02em
}
.point-scrubber {
  display:flex;
  align-items:center;
  gap:12px;
  margin-top:15px;
  padding-top:12px;
  border-top:1px solid #2e4b53
}
.point-scrubber label {
  color:#a6c0cb;
  font-size:.7rem;
  flex-shrink:0
}
input[type=range] {
  width:100%;
  accent-color:#63ddc5;
  cursor:pointer
}
.selected-meta {
  font-size:.68rem;
  color:#8eacbd;
  margin:12px 0 0
}
.data-card {
  padding:22px;
  margin-top:20px
}
.search-label {
  display:flex;
  gap:10px;
  align-items:center;
  color:#9eb6c6;
  font-size:.73rem
}
.search-label input {
  min-width:160px;
  max-width:240px;
  background:#0b1824;
  border:1px solid #3b5465;
  color:#e6f0f8;
  border-radius:7px;
  padding:9px 11px;
  font-size:.75rem
}
.table-scroll {
  overflow:auto;
  max-height:520px;
  border:1px solid #263d4d;
  border-radius:9px;
  scrollbar-color:#4e6878 #101d2a
}
table {
  width:100%;
  border-collapse:separate;
  border-spacing:0;
  white-space:nowrap;
  font-variant-numeric:tabular-nums
}
th,td {
  text-align:right;
  padding:11px 13px;
  border-bottom:1px solid #26394a;
  font-size:.73rem
}
th {
  position:sticky;
  top:0;
  z-index:1;
  background:#192b3b;
  color:#b5c8d6;
  font-weight:600
}
td:nth-child(2),th:nth-child(2),td:nth-child(3),th:nth-child(3),td:nth-child(4),th:nth-child(4) {
  text-align:left
}
tbody tr:hover,tbody tr.selected {
  background:#1a3542
}
tbody tr.selected td:first-child {
  box-shadow:inset 3px 0 #60e0ca
}
tbody tr.failed {
  background:#392332
}
.point-link {
  color:#d9eef6;
  background:none;
  border:0;
  padding:0;
  text-align:left;
  font-size:inherit;
  text-decoration:underline;
  text-decoration-color:#3e6072;
  text-underline-offset:4px
}
.note,.empty {
  color:#96acbf;
  font-size:.74rem;
  line-height:1.7
}
.method {
  margin-top:16px
}
.method summary {
  cursor:pointer;
  color:#adbfcd;
  font-size:.75rem
}
.method .note {
  max-width:960px
}
.purpose-card,.technical-card {
  border:1px solid #2d4858;
  border-radius:12px;
  padding:22px;
  margin-bottom:24px;
  background:#10212e
}
.purpose-card p {
  color:#b6cad8;
  line-height:1.75;
  font-size:.86rem;
  max-width:1000px
}
.bench-flow {
  display:flex;
  align-items:center;
  gap:12px;
  margin:20px 0;
  font-size:.78rem
}
.bench-flow div {
  border:1px solid #2d4858;
  border-radius:8px;
  padding:14px;
  flex:1
}
.bench-flow b,.bench-flow div span {
  display:block
}
.bench-flow div span {
  color:#abc0d0;
  line-height:1.5;
  margin-top:6px
}
.flow-arrow {
  color:#61dbc1;
  font-size:1.2rem
}
.conclusion {
  border-left:3px solid #61dbc1;
  padding:4px 0 4px 16px;
  margin-top:20px
}
.conclusion p {
  margin-bottom:0
}
.technical-card summary {
  cursor:pointer;
  color:#b6cad8;
  font-size:.85rem
}
.technical-card .metrics {
  margin:16px 0 0
}
.notices {
  border-left:3px solid #f5ae72;
  padding:6px 16px;
  margin:0 0 20px;
  background:#33291f;
  color:#f6d3b2;
  border-radius:0 8px 8px 0;
  font-size:.8rem;
  line-height:1.6
}
.notices p {
  margin:7px 0
}
footer {
  color:#7f9bac;
  font-size:.71rem;
  margin-top:26px;
  line-height:1.7
}
.sr-only {
  position:absolute;
  width:1px;
  height:1px;
  overflow:hidden;
  clip:rect(0,0,0,0);
  white-space:nowrap
}
.keyboard-hint {
  color:#779aaa;
  font-size:.68rem
}
kbd {
  font:inherit;
  background:#1a303e;
  border:1px solid #375363;
  border-radius:3px;
  padding:0 4px
}
noscript p {
  background:#203444;
  padding:12px;
  border-radius:8px;
  color:#cbdde8;
  font-size:.8rem
}
@media(min-width:1000px) {
  .featured .plot-wrap {
    max-width:1080px;
    margin:auto
  }
  .metrics .metric:nth-child(n+6) {
    padding:13px 18px
  }
  .metrics .metric:nth-child(n+6) .metric-value {
    font-size:1.3rem
  }
}
@media(max-width:760px) {
  .bench-flow {
    display:grid;
    gap:4px
  }
  .flow-arrow {
    transform:rotate(90deg);
    text-align:center
  }
  .shell {
    padding:22px 16px 36px
  }
  .header-main {
    display:block;
    padding:25px 0
  }
  .header-actions {
    padding-top:18px
  }
  .charts {
    grid-template-columns:minmax(0,1fr)
  }
  .chart-card {
    padding:16px 10px
  }
  .chart-heading,.legend {
    padding-left:8px
  }
  .selected-grid {
    grid-template-columns:repeat(3,minmax(0,1fr));
    row-gap:20px
  }
  .section-heading {
    align-items:flex-start;
    flex-wrap:wrap
  }
  .inspector,.data-card {
    padding:17px 14px
  }
  .inspection-head {
    gap:12px
  }
  .point-nav {
    gap:5px
  }
  .point-nav .button {
    padding:6px 9px
  }
  .metrics {
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:8px
  }
  .metric {
    padding:14px
  }
  .metric-value {
    font-size:1.45rem
  }
  .search-label {
    width:100%;
    justify-content:space-between
  }
  .search-label input {
    max-width:none;
    flex:1
  }
  .offline {
    font-size:.65rem
  }
  .keyboard-hint {
    display:none
  }
}
@media(prefers-reduced-motion:reduce) {
  * {
    transition:none!important
  }
}
@media(max-width:760px) {
  svg.interactive-chart {
    width:calc(100% - 16px);
    margin:0 8px;
    border-radius:0
  }
  .interactive-chart .tick {
    font-size:24px
  }
  .interactive-chart .axis-label {
    display:none
  }
  .mobile-axes {
    display:flex;
    gap:4px 14px;
    flex-wrap:wrap;
    color:#b1c5d3;
    font-size:.7rem;
    line-height:1.6;
    margin:0 0 12px
  }
}
@media print {
  :root {
    color-scheme:light;
    background:white;
    color:#102330
  }
  body {
    background:white
  }
  .shell {
    max-width:none;
    padding:0
  }
  .button,.plot-tooltip,.point-nav,.point-scrubber,.search-label,.keyboard-hint,.inspector {
    display:none!important
  }
  .metric,.chart-card,.data-card {
    background:white;
    border-color:#b7c4ce;
    break-inside:avoid
  }
  .metric-label,.metric-detail,.meta,.note,footer,.chart-heading p,.section-copy {
    color:#476071
  }
  .chart-card {
    padding:12px
  }
  .plot-surface {
    fill:#f0f5f8
  }
  .tick,.axis-label {
    fill:#375367
  }
  .grid {
    stroke:#c9d5de
  }
  .table-scroll {
    max-height:none;
    overflow:visible
  }
  th,td {
    font-size:6pt;
    padding:5px 3px
  }
  th {
    position:static;
    background:#edf3f6;
    color:#253f50
  }
  .point-link {
    color:#253f50
  }
  table {
    white-space:normal
  }
  .topline {
    padding-bottom:12px
  }
  .header-main {
    padding:18px 0
  }
  .metrics {
    gap:7px
  }
  .metric {
    padding:10px
  }
  .metric-value {
    font-size:1.15rem
  }
  .data-card {
    padding:10px
  }
  .legend {
    color:#375367
  }
}
"""


_REPORT_SCRIPT = r"""
(() => {
  'use strict';
  const samples = JSON.parse(document.getElementById('report-data').textContent);
  const simulated = document.documentElement.dataset.source === 'simulated';
  const charts = [...document.querySelectorAll('.interactive-chart')];
  const rows = [...document.querySelectorAll('tr[data-row]')];
  const inspector = document.getElementById('point-inspector');
  const range = document.getElementById('point-range');
  let selected = 0;
  const fmt = (n, digits = 6) => typeof n === 'number' && Number.isFinite(n)
    ? new Intl.NumberFormat('en-US', {maximumFractionDigits: digits}).format(n) : '—';
  const withUnit = (n, unit, digits = 6) => `${fmt(n, digits)} ${unit}`;
  const withCurrent = n => withUnit(typeof n === 'number' ? n * 1000 : null, 'mA', 9);
  const text = (id, value) => {document.getElementById(id).textContent = value;};
  const plotPoints = new Map(charts.map(chart => [chart, [...chart.querySelectorAll('.data-point')]]));
  function select(index, announce = false) {
    if (!samples.length) return;
    selected = Math.max(0, Math.min(samples.length - 1, index));
    const sample = samples[selected], values = sample.values;
    text('selected-title', sample.display_label);
    text('point-position', `${selected + 1} / ${samples.length}`);
    text('selected-current', withCurrent(values.load_current_a));
    text('selected-target', sample.load_enabled === false ? '0 mA · load off' : withCurrent(sample.requested_current_a));
    text('selected-voltage', withUnit(values.load_voltage_v, 'V'));
    text('selected-power', withUnit(values.load_power_w, 'W'));
    text('selected-drop', withUnit(sample.voltage_drop_mv, 'mV', 3));
    text('selected-meta', `Point ${selected + 1} · ${sample.direction || 'Saved reading'} · ${sample.status} · ${sample.timestamp || 'Timestamp unavailable'}`);
    range.value = String(selected);
    range.setAttribute('aria-valuetext', `Point ${selected + 1} of ${samples.length}: ${sample.display_label}`);
    document.getElementById('previous-point').disabled = selected === 0;
    document.getElementById('next-point').disabled = selected === samples.length - 1;
    rows.forEach(row => row.classList.toggle('selected', Number(row.dataset.row) === selected));
    charts.forEach(chart => {
      const points = plotPoints.get(chart);
      const active = points.filter(point => Number(point.dataset.sample) === selected);
      points.forEach(point => point.classList.toggle('is-active', active.includes(point)));
      const cursor = chart.querySelector('.cursor-line');
      cursor.setAttribute('visibility', active.length ? 'visible' : 'hidden');
      if (active.length) {
        cursor.setAttribute('x1', active[0].getAttribute('cx'));
        cursor.setAttribute('x2', active[0].getAttribute('cx'));
      }
    });
    if (announce) text('point-announcement', `Reading ${selected + 1} of ${samples.length}, ${sample.display_label}. Load ${withCurrent(values.load_current_a)}, ${withUnit(values.load_voltage_v, 'V')}, voltage drop ${withUnit(sample.voltage_drop_mv, 'mV', 3)}.`);
  }
  function hideTips() {document.querySelectorAll('.plot-tooltip').forEach(tip => {tip.hidden = true;});}
  function showTip(chart, index, clientX, clientY) {
    const sample = samples[index], card = chart.closest('.chart-card');
    const wrap = card.querySelector('.plot-wrap'), tip = card.querySelector('.plot-tooltip');
    const title = document.createElement('div');
    title.className = 'tip-title';
    title.textContent = `#${index + 1} · ${sample.display_label}`;
    const contents = [title];
    const values = [];
    if (card.id !== 'demand-chart') {
      values.push([simulated ? 'Example current' : 'Measured current', withCurrent(sample.values.load_current_a)]);
      if (sample.requested_current_a !== null) values.push(['Requested current', withCurrent(sample.requested_current_a)]);
    }
    plotPoints.get(chart).filter(point => Number(point.dataset.sample) === index).forEach(point => {
      values.push([point.dataset.series, withUnit(Number(point.dataset.value), card.dataset.unit, card.dataset.unit === 'mA' ? 9 : 6)]);
    });
    if (sample.load_enabled === false) values.push(['Load state', 'Switched off · 0 mA requested']);
    if (sample.direction) values.push(['Change in demand', sample.direction]);
    values.push(['Status', sample.status]);
    values.forEach(([label, value]) => {
      const line = document.createElement('div'); line.className = 'tip-row';
      const key = document.createElement('span'), val = document.createElement('span');
      key.textContent = label; val.textContent = value; line.append(key, val); contents.push(line);
    });
    tip.replaceChildren(...contents); tip.hidden = false;
    const box = wrap.getBoundingClientRect(), tipBox = tip.getBoundingClientRect();
    const desiredX = clientX - box.left + 16;
    const x = desiredX + tipBox.width > box.width ? clientX - box.left - tipBox.width - 16 : desiredX;
    tip.style.left = `${Math.max(0, Math.min(box.width - tipBox.width, x))}px`;
    tip.style.top = `${Math.max(0, Math.min(box.height - tipBox.height, clientY - box.top - 20))}px`;
  }
  charts.forEach(chart => {
    const points = plotPoints.get(chart);
    function inspect(event) {
      const matrix = chart.getScreenCTM(); if (!matrix) return;
      const loc = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      if (loc.x < Number(chart.dataset.left) || loc.x > Number(chart.dataset.right) || loc.y < Number(chart.dataset.top) || loc.y > Number(chart.dataset.bottom)) {hideTips(); return;}
      let nearest = null, best = Infinity;
      points.forEach(point => {
        const dx = loc.x - Number(point.getAttribute('cx')), dy = loc.y - Number(point.getAttribute('cy'));
        const distance = dx * dx + dy * dy;
        if (distance < best) {best = distance; nearest = point;}
      });
      if (!nearest) return;
      hideTips(); select(Number(nearest.dataset.sample));
      showTip(chart, selected, event.clientX, event.clientY);
    }
    chart.addEventListener('pointermove', inspect);
    chart.addEventListener('pointerdown', inspect);
    // A touch tap ends with pointerleave; keep its result visible after release.
    chart.addEventListener('pointerleave', event => {
      if (event.pointerType !== 'touch') hideTips();
    });
    chart.addEventListener('pointercancel', hideTips);
    // A tap on another chart can focus it after its pointerdown showed a tip.
    // Hiding only this chart's tip keeps the newly selected reading visible.
    chart.addEventListener('blur', () => {
      chart.closest('.chart-card').querySelector('.plot-tooltip').hidden = true;
    });
    chart.addEventListener('keydown', event => {
      let index;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') index = selected + 1;
      else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') index = selected - 1;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = samples.length - 1;
      else if (event.key === 'Escape') {hideTips(); return;}
      else return;
      event.preventDefault(); hideTips(); select(index, true);
      const point = points.find(item => Number(item.dataset.sample) === selected);
      const matrix = chart.getScreenCTM();
      if (point && matrix) {
        const screen = new DOMPoint(Number(point.getAttribute('cx')), Number(point.getAttribute('cy'))).matrixTransform(matrix);
        showTip(chart, selected, screen.x, screen.y);
      }
    });
  });
  if (samples.length) {
    inspector.hidden = false;
    range.max = String(samples.length - 1);
    range.addEventListener('input', () => {hideTips(); select(Number(range.value), true);});
    document.getElementById('previous-point').addEventListener('click', () => {hideTips(); select(selected - 1, true);});
    document.getElementById('next-point').addEventListener('click', () => {hideTips(); select(selected + 1, true);});
    document.querySelectorAll('[data-select]').forEach(button => button.addEventListener('click', () => {hideTips(); select(Number(button.dataset.select), true);}));
    select(0);
  }
  const search = document.getElementById('point-search');
  search.closest('label').hidden = false;
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase(); let count = 0;
    rows.forEach(row => {row.hidden = !Array.from(row.cells, cell => cell.textContent).join(' ').toLocaleLowerCase().includes(query); if (!row.hidden) count++;});
    text('table-count', `${count} of ${samples.length} points · acquisition order · CSV includes all points`);
    document.getElementById('no-matches').hidden = count !== 0 || !samples.length;
  });
  const print = document.getElementById('print-report');
  print.hidden = false; print.addEventListener('click', () => window.print());
  document.addEventListener('pointerdown', event => {
    if (!event.target.closest('.interactive-chart')) hideTips();
  });
  window.addEventListener('resize', hideTips);
})();
"""


def render_report(summary: Mapping[str, Any], samples: list[Sample], warnings: list[str]) -> str:
    """Return an offline HTML report. Imported strings are never executable markup."""
    recipe = str(summary.get("recipe") or ("Partial run" if not samples else "Measurement run"))
    setup = summary.get("setup") or "Unknown setup"
    default_outcome = (
        "completed" if summary.get("status") == "success"
        else "error" if summary.get("status") == "failed"
        else "incomplete"
    )
    outcome = str(summary.get("outcome") or default_outcome).lower()
    simulated = summary.get("data_source") == "simulated"
    if simulated:
        outcome = "simulated"
        warnings = ["SIMULATED PREVIEW — generated values for exploring the report. No hardware measurements were taken.", *warnings]
    outcome_class = "pass" if outcome == "pass" else "fail" if outcome in {"fail", "error"} else "neutral"
    dates = [str(summary.get(key) or "") for key in ("started_at", "finished_at")]
    date_line = " → ".join(date for date in dates if date) or "Run timing unavailable"
    error = summary.get("error")
    if error:
        warnings = [*warnings, f"Run error: {error}"]
    if outcome == "completed":
        warnings = [*warnings, "This older run has no acceptance outcome; completion does not establish that requested values were met."]
    notices = (
        '<div class="notices" role="note">' + "".join(f'<p>{_escape(message)}</p>' for message in warnings) + '</div>'
        if warnings else ""
    )
    charts = "".join([
        _plot("How current changed during the test", "Current (mA)", _demand_series(samples),
              chart_id="demand-chart", xlabel="Reading number (test order)", xunit="", reading_axis=True,
              description=("Read left to right in test order. Lines join saved readings; changes between readings are not shown. Requested current is the load setting; measured current is what it drew. Increasing then reducing demand makes a rise-and-fall shape here."
                           + (" The load-off reference is shown as 0 mA requested." if any(sample.load_enabled is False for sample in samples) else "")),
              zero_baseline=True, featured=True, round_y_ticks=True,
              point_notes={index: "Load switched off; 0 mA commanded, not an assumed measurement"
                           for index, sample in enumerate(samples) if sample.load_enabled is False}),
        _plot("Voltage difference between supply and device", "Voltage difference (mV)", _directional_drop_series(samples),
              chart_id="drop-chart", description="Across this graph is measured current, not test order. Returning to the same current moves left, so the two directions can overlap. Their separation shows whether the voltage difference changed; wires, contacts and instrument offsets all contribute.", zero_baseline=True, featured=True),
        _plot("Voltage reaching the device", "Measured voltage (V)", [
            ("At the device", _series(samples, "load_voltage_v")),
            ("At the supply", _series(samples, "supply_voltage_v")),
        ], chart_id="voltage-chart", description="Across this graph is measured current. Compare the voltage at the supply and the device at each demand; returning readings can overlap the earlier ones."),
        _plot("Power used by the device", "Measured power (W)", [("Device power", _series(samples, "load_power_w"))],
              chart_id="power-chart", description="Across this graph is measured current. See the power absorbed at each demand; returning to the same demand moves left along the graph.", zero_baseline=True),
    ])
    directions = _sweep_directions(samples)
    names = _sample_names(samples)
    if simulated:
        charts = _example_copy(charts)
        names = [_example_copy(name) for name in names]
    title, explanation = _test_explanation(summary, samples, outcome)
    source_label = "generated example readings" if simulated else "saved measurements"
    report_kind = "ILLUSTRATED EXAMPLE" if simulated else "RUN REPORT"
    csv_filename = "example-readings.csv" if simulated else "measured-points.csv"
    highlights = _summary_cards(samples, summary)
    if simulated:
        highlights = _example_copy(highlights)
    footer = ("Illustrated with generated data. These example readings do not describe a real bench run." if simulated else
              "Generated from saved records. The first chart separates requested and measured current; comparison charts use measured values.")
    exploration_title = "Explore the example readings" if simulated else "Explore the measurements"
    current_caption = "Example current drawn" if simulated else "Actual current drawn"
    data = json.dumps([
        {"label": sample.label, "display_label": names[index], "timestamp": sample.timestamp, "status": sample.status,
         "requested_current_a": sample.requested_current_a, "load_enabled": sample.load_enabled, "values": sample.values,
         "direction": directions[index],
         "voltage_drop_mv": _number(drop * 1000) if (drop := sample.voltage_drop_v()) is not None else None}
        for index, sample in enumerate(samples)
    ], ensure_ascii=True, allow_nan=False).replace("<", r"\u003c").replace(">", r"\u003e").replace("&", r"\u0026")
    script_hash = base64.b64encode(hashlib.sha256(_REPORT_SCRIPT.encode("utf-8")).digest()).decode("ascii")
    return f"""<!doctype html>
<html lang="en" data-source="{'simulated' if simulated else 'recorded'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'sha256-{script_hash}'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{_escape(title)} · Bench report</title><style>{_REPORT_CSS}</style></head>
<body><main class="shell">
<header><div class="topline"><div class="brand"><b>▰</b> BENCHCTL <span class="offline">/ {report_kind}</span></div><div class="offline">Offline · {source_label}</div></div>
<div class="header-main"><div><span class="badge {outcome_class}">{_escape(outcome.upper())}</span><h1>{_escape(title)}</h1>
<div class="meta">Setup: <code>{_escape(setup)}</code> · Recipe: <code>{_escape(recipe)}</code><br>{_escape(date_line)}</div></div>
<div class="header-actions"><a class="button primary" id="download-csv" download="{csv_filename}" href="data:text/csv;base64,{_csv_data(samples)}">↓ Download CSV</a><button class="button" type="button" id="print-report" hidden>Print / PDF</button></div></div></header>
{notices}{explanation}{highlights}
<div class="section-heading"><div><div class="eyebrow">{exploration_title}</div><h2>What changes as the device asks for more power?</h2><p class="section-copy" id="chart-help">Move your mouse over a graph or tap it to see a reading. Current is the device’s demand: 100 mA is 0.1 A. Use the slider below to replay the readings in order.</p></div><span class="keyboard-hint">Focus a chart · <kbd>←</kbd> <kbd>→</kbd> to explore</span></div>
<noscript><p>These plots and readings work offline. Enable JavaScript for hover, touch, and keyboard point inspection.</p></noscript>
<section class="charts" aria-label="Reading plots">{charts}</section>
<section class="inspector" id="point-inspector" aria-label="Selected reading" hidden>
<div class="inspection-head"><div><div class="eyebrow">At this demand</div><h3 class="selected-title" id="selected-title"></h3></div><div class="point-nav"><button class="button" id="previous-point" type="button" aria-label="Previous reading">←</button><span id="point-position"></span><button class="button" id="next-point" type="button" aria-label="Next reading">→</button></div></div>
<dl class="selected-grid"><div><dt>{current_caption}</dt><dd id="selected-current"></dd></div><div><dt>Current requested</dt><dd id="selected-target"></dd></div><div><dt>Voltage at device</dt><dd id="selected-voltage"></dd></div><div><dt>Power used</dt><dd id="selected-power"></dd></div><div><dt>Voltage difference</dt><dd id="selected-drop"></dd></div></dl>
<div class="point-scrubber"><label for="point-range">Follow the test</label><input id="point-range" type="range" min="0" max="0" value="0" step="1"></div><p class="selected-meta" id="selected-meta"></p><p class="sr-only" id="point-announcement" aria-live="polite" aria-atomic="true"></p></section>
{_table(samples, simulated=simulated)}<footer>{footer}<br>One self-contained file · no network connection or instrument access required.</footer>
</main><script id="report-data" type="application/json">{data}</script><script type="text/javascript">{_REPORT_SCRIPT}</script></body></html>
"""


def generate_report(run_dir: str | Path, output: str | Path | None = None) -> Path:
    """Write and return a standalone HTML report for a run directory."""
    directory = Path(run_dir)
    summary, samples, warnings = _read_run(directory)
    target = Path(output) if output is not None else directory / "report.html"
    if target.resolve() in {
        (directory / SUMMARY_FILENAME).resolve(),
        (directory / MEASUREMENTS_FILENAME).resolve(),
        (directory / "execution.jsonl").resolve(),
        (directory / "measurements.csv").resolve(),
    }:
        raise ReportError("report output would overwrite run data")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_report(summary, samples, warnings), encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"cannot write {target}: {exc}") from exc
    return target


def find_latest_run(recipe_name: str, results_dir: str | Path = DEFAULT_RESULTS_DIR) -> Path:
    """Find the newest saved run whose summary names the exact recipe."""
    base = Path(results_dir)
    if not base.is_dir():
        raise ReportError(f"results directory does not exist: {base}")
    candidates: list[tuple[float, Path]] = []
    try:
        directories = list(base.iterdir())
    except OSError as exc:
        raise ReportError(f"cannot list results directory {base}: {exc}") from exc
    for directory in directories:
        if not directory.is_dir():
            continue
        summary_path = directory / SUMMARY_FILENAME
        if not summary_path.is_file():
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict) or summary.get("recipe") != recipe_name:
            continue
        raw_time = summary.get("finished_at") or summary.get("started_at")
        try:
            stamp = datetime.fromisoformat(str(raw_time))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            finished = stamp.timestamp()
        except (TypeError, ValueError, OverflowError):
            try:
                finished = directory.stat().st_mtime
            except OSError:
                continue
        candidates.append((finished, directory))
    if not candidates:
        raise ReportError(f"no saved run for recipe {recipe_name!r} under {base}")
    return max(candidates, key=lambda item: (item[0], item[1].name))[1]
