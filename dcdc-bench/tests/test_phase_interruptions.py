"""Interrupted phase-scoped simulations preserve partial evidence and never claim completion."""
import json
import signal

import pytest

from dcdc_bench.domain import RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE
from dcdc_bench.planning import build_plan
from dcdc_bench.storage import verify_integrity
from dcdc_bench.supply_profiles import run_supply_profile_mock
from dcdc_bench.uvlo import run_uvlo_mock
from test_supply_profiles import RAMP_LEVELS, STAIRCASE_LEVELS, profiles
from test_uvlo import approved_plan


@pytest.mark.parametrize("kind", ["uvlo_input_ramp", SLOW_SUPPLY_RAMP_TEST_TYPE, RESET_STAIRCASE_TEST_TYPE])
@pytest.mark.parametrize("stop_signal,expected_status", [(signal.SIGINT, "aborted"), (signal.SIGTERM, "interrupted")])
def test_stop_preserves_completed_points_and_partial_cycle(tmp_path, kind, stop_signal, expected_status):
    if kind == "uvlo_input_ramp":
        plan, execute = approved_plan(), run_uvlo_mock
    else:
        levels = RAMP_LEVELS if kind == SLOW_SUPPLY_RAMP_TEST_TYPE else STAIRCASE_LEVELS
        plan, execute = build_plan(*profiles(kind, levels)), run_supply_profile_mock
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    sent = []

    def interrupt_second_point(quantity, value, point, phase):
        if point["point_id"] == "p0002" and phase == "acquiring" and quantity == "Iin_A":
            sent.append(stop_signal)
            signal.raise_signal(stop_signal)
        return value

    path = execute(plan, tmp_path, reading_override=interrupt_second_point)
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [json.loads(row) for row in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert sent == [stop_signal]
    assert run["execution_status"] == expected_status
    assert run["errors"]
    assert run["points"][0]["qualification"] == "valid"
    assert run["points"][0]["acquisition_cycle_ids"]
    assert run["points"][1]["qualification"] == "inconclusive"
    assert run["points"][1]["acquisition_cycle_ids"] == []
    assert all(point["qualification"] == "not-run" for point in run["points"][2:])
    partial = [row for row in samples if row["point_id"] == "p0002" and row["phase"] == "acquiring"]
    assert [row["quantity"] for row in partial] == ["Vin_V"]
    assert all(item["state"] == "OFF" and item["verified"] for item in run["shutdown"].values())
    assert {number: signal.getsignal(number) for number in previous} == previous
