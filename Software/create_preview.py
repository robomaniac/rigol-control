"""Rebuild the clearly labelled offline UI preview without contacting hardware.

Run from the repository root after installing the package:
    python Software/create_preview.py
These illustrative numbers are not instrument measurements or calibration data.
"""

from decimal import Decimal
from pathlib import Path

from benchctl.report import Sample, render_report


def create_preview(output: Path = Path("Data/sweep-preview.html")) -> Path:
    targets = [float(Decimal("0.05") + i * Decimal("0.025")) for i in range(11)]
    targets += targets[-2::-1]
    samples = [Sample("no_load", "", "simulated", {
        "supply_voltage_v": 5.005, "supply_current_a": 0.0004,
        "supply_power_w": 0.002,
    }, load_enabled=False)]
    for index, target in enumerate(targets, start=1):
        current = round(target - 0.001, 6)
        supply_voltage = 5.005
        # A small return offset makes the two directions visible in the UI.
        # This is an illustrative model, not an inference about the real bench.
        drop = 0.012 + 0.08 * current + (0.0015 if index > 11 else 0)
        load_voltage = round(supply_voltage - drop, 6)
        supply_current = round(current - 0.014, 6)
        samples.append(Sample(f"point_{index}_{target}_a", "", "simulated", {
            "supply_voltage_v": supply_voltage,
            "supply_current_a": supply_current,
            "supply_power_w": round(supply_voltage * supply_current, 6),
            "load_voltage_v": load_voltage,
            "load_current_a": current,
            "load_power_w": round(load_voltage * current, 6),
        }, requested_current_a=target, load_enabled=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report({
        "recipe": "load_sweep_preview", "setup": "Offline preview · no instruments",
        "data_source": "simulated",
        "parameters": {
            "voltage_v": 5.0, "current_limit_a": 0.5,
            "min_acceptable_voltage_v": 4.75, "max_expected_voltage_v": 5.25,
            "load_start_a": 0.05, "load_stop_a": 0.30, "load_step_a": 0.025,
            "configure_settle_s": 0.5,
            "settle_s": 4.0,
        },
    }, samples, []), encoding="utf-8")
    return output


if __name__ == "__main__":
    print(f"Simulated preview written: {create_preview()}")
