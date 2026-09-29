"""Voltage comparisons must retain measured values and exact point evidence.

All readings in this module are synthetic fixtures; no transport is opened.
"""
import copy

import pytest

from dcdc_bench.analysis import analyze_evidence, build_report_model
from dcdc_bench.domain import RawSample, TestDefinition as Definition
from dcdc_bench.planning import build_plan
from dcdc_bench.services import default_plan
from dcdc_bench.voltage_sweep import VoltageSweepProcedure


@pytest.fixture
def voltage_evidence():
    base = default_plan()
    base.recipe.tests = [Definition(id=f"efficiency-{voltage:g}v", input_voltage_targets_V=[voltage],
                                   output_current_targets_A=[.4, .5, .6]) for voltage in (12., 24., 36.)]
    base.recipe.planning.efficiency_estimate_fraction = 1.
    base.recipe.planning.source_current_budget_fraction = 1.
    base.recipe.acquisition.minimum_complete_cycles = 5
    base.recipe.acquisition.duration_s = 8.
    plan = build_plan(base.dut, base.bench, base.recipe)
    metadata = VoltageSweepProcedure.metadata()
    run = {**metadata, "run_id": "synthetic-voltage-comparison", "data_source": "simulated",
           "real_hardware_opened": False, "clock": {"mode": "virtual"},
           "execution_status": "completed", "points": [],
           "executed_point_ids": [point.point_id for point in plan.points]}
    samples = []
    vin_by_nominal = {12.: 12.02, 24.: 24.01, 36.: 35.79}
    eta_by_nominal = {12.: .77, 24.: .81, 36.: .85}
    for index, point in enumerate(plan.points):
        accepted = []
        vin = vin_by_nominal[point.vin_target_V]
        iout, vout = point.iout_target_A - .001, 12. - index * .002
        # Efficiency is deliberately not monotonic in load: the shared .5 A
        # comparison must not accidentally select each curve's best point.
        eta = eta_by_nominal[point.vin_target_V] + (.015 if point.iout_target_A == .4 else 0.)
        values = {"Vin_V": vin, "Iin_A": vout * iout / (vin * eta), "Vout_V": vout, "Iout_A": iout}
        for cycle_index in range(5):
            cycle_id = f"{point.point_id}-accepted-{cycle_index}"
            accepted.append(cycle_id)
            for offset, (quantity, value) in enumerate(values.items()):
                binding = plan.bench.measurements[quantity]
                start = 1000. + index * 20. + cycle_index * 1.7 + offset * .01
                samples.append(RawSample(sample_id=f"{cycle_id}-{quantity}", run_id=run["run_id"],
                    test_id=point.test_id, point_id=point.point_id,
                    channel_id=binding.instrument_id + quantity, instrument_id=binding.instrument_id,
                    quantity=quantity, value=value, unit=binding.unit, location=binding.location,
                    query_start_utc="2026-01-01T00:00:00Z", query_end_utc="2026-01-01T00:00:00.005Z",
                    query_start_monotonic_s=start, query_end_monotonic_s=start + .005,
                    acquisition_cycle_id=cycle_id, phase="acquiring",
                    acquisition_settings={"source_mode": "CV", "load_compliance": True}).model_dump())
        run["points"].append({"point_id": point.point_id, "qualification": "valid",
                              "acquisition_cycle_ids": accepted, "settling_elapsed_s": 5.4,
                              "acquisition_elapsed_s": 8.25})
        # Earlier, rejected startup evidence must not set the accepted time
        # origin or contaminate means. It still proves this point was attempted.
        startup = copy.deepcopy(samples[-20])
        startup.update(sample_id=f"{point.point_id}-startup", acquisition_cycle_id=f"{point.point_id}-startup",
                       phase="starting", value=1., query_start_monotonic_s=10. + index * 20.,
                       query_end_monotonic_s=10.005 + index * 20.)
        samples.append(startup)
    for phase in run["method"]["voltage_efficiency_sweep"]["phases"]:
        ids = [p.point_id for p in plan.points if p.vin_target_V == phase["nominal_input_V"]]
        phase.update(status="completed", stop_reason="Synthetic declared grid completed",
                     executed_point_ids=ids, qualified_point_ids=ids)
    return plan, run, _analysis(plan, run, samples), samples


def _analysis(plan, run, samples):
    result = analyze_evidence(plan, run, samples)
    result["analysis_id"] = "voltage-fixture"
    return result


def _row(model, nominal):
    return next(row for row in model.execution["voltage_comparison"] if row["nominal_input_V"] == nominal)


def test_comparison_selects_exact_requested_half_amp_and_measured_input(voltage_evidence):
    before = copy.deepcopy(voltage_evidence)
    model = build_report_model(*voltage_evidence)
    for nominal, measured_vin, expected_efficiency in ((12, 12.02, 77.), (24, 24.01, 81.), (36, 35.79, 85.)):
        row = _row(model, nominal)
        reference = next(point for point in model.points if point["point_id"] == row["reference_point_id"])
        assert row["reference_load_A"] == reference["iout_target_A"] == .5
        assert reference["Iout_A"] == pytest.approx(.499)
        assert row["reference_measured_input_V"] == pytest.approx(measured_vin)
        assert row["reference_efficiency_pct"] == pytest.approx(expected_efficiency)
        assert row["peak_efficiency_pct"] == pytest.approx(expected_efficiency + 1.5)
        assert row["peak_efficiency_point_id"] != row["reference_point_id"]
        assert row["highest_load_A"] == pytest.approx(.599)
    assert voltage_evidence == before, "Building the report must not modify the retained plan, run, or analysis"


@pytest.mark.parametrize("exclusion", ["not-run", "setup-limited", "inconclusive", "absent-request"])
def test_missing_or_invalid_half_amp_reference_is_never_interpolated(voltage_evidence, exclusion):
    plan, run, _, samples = copy.deepcopy(voltage_evidence)
    reference = next(point for point in plan.points if point.vin_target_V == 24 and point.iout_target_A == .5)
    outcome = next(point for point in run["points"] if point["point_id"] == reference.point_id)
    if exclusion == "absent-request":
        plan.points = [point for point in plan.points if point.point_id != reference.point_id]
        next(test for test in plan.recipe.tests if test.id == reference.test_id).output_current_targets_A = [.4, .6]
        run["points"].remove(outcome)
    else:
        outcome.update(qualification=exclusion, acquisition_cycle_ids=[])
    if exclusion in ("not-run", "absent-request"):
        run["executed_point_ids"].remove(reference.point_id)
        samples = [sample for sample in samples if sample["point_id"] != reference.point_id]
    analysis = _analysis(plan, run, samples)
    model = build_report_model(plan, run, analysis, samples)
    row = _row(model, 24)
    assert row["qualified_points"] == 2
    assert row["reference_point_id"] is None
    assert row["reference_efficiency_pct"] is None
    assert row["reference_measured_input_V"] is None
    assert row["peak_efficiency_pct"] is not None and row["highest_load_A"] is not None


def test_nominal_and_programmed_voltage_labels_do_not_change_power_calculation(voltage_evidence):
    model = build_report_model(*voltage_evidence)
    row = _row(model, 36)
    assert row["nominal_input_V"] == 36 and row["programmed_input_V"] == 35.8
    assert "36 V nominal" in row["label"] and "35.8 V set" in row["label"]
    reference = next(point for point in model.points if point["point_id"] == row["reference_point_id"])
    assert reference["vin_target_V"] == 36 and reference["programmed_input_V"] == 35.8
    assert reference["Vin_V"] == pytest.approx(35.79)
    assert reference["Pin_W"] == pytest.approx(35.79 * reference["Iin_A"])
    assert reference["efficiency_pct"] == pytest.approx(100 * reference["Pout_W"] / reference["Pin_W"])
    series = next(figure for figure in model.figures if figure.id == "fig-efficiency").series
    assert [item.label for item in series] == ["12 V input", "24 V input", "36 V nominal (35.8 V set)"]
    assert [item.vin_target_V for item in series] == [12, 24, 36]
    assert any("near 36 V" in note and "35.8" in " ".join(model.summary) for note in model.summary)
    assert any("not an exact 36.000 V test" in note for note in model.method.procedure_notes)


def test_accepted_query_timing_excludes_startup_and_preserves_actual_duration(voltage_evidence):
    model = build_report_model(*voltage_evidence)
    point = model.points[0]
    assert point["elapsed_start_s"] == 0
    assert point["elapsed_end_s"] == pytest.approx(6.835)
    assert point["elapsed_s"] == pytest.approx(3.4175)
    timing = next(item for item in model.method.achieved_points if item.point_id == point["point_id"])
    assert timing.accepted_cycle_count == 5
    assert timing.settling_elapsed_s == 5.4
    assert timing.acquisition_elapsed_s == 8.25
    assert timing.accepted_query_span_s == pytest.approx(6.835)
    assert timing.maximum_accepted_interchannel_skew_s == pytest.approx(.035)
    assert len(model.raw_samples[point["point_id"]]) == 21


def test_unattempted_requests_stay_in_tables_but_not_curves_and_failed_attempts_stay_visible(voltage_evidence):
    plan, run, _, samples = copy.deepcopy(voltage_evidence)
    unused_id, failed_id = plan.points[2].point_id, plan.points[5].point_id
    run["executed_point_ids"].remove(unused_id)
    samples = [sample for sample in samples if sample["point_id"] != unused_id]
    for point in run["points"]:
        if point["point_id"] in (unused_id, failed_id):
            point.update(qualification="not-run" if point["point_id"] == unused_id else "setup-limited",
                         acquisition_cycle_ids=[])
    model = build_report_model(plan, run, _analysis(plan, run, samples), samples)
    assert len(model.points) == 9 and len(model.execution["executed_point_ids"]) == 8
    assert "7 qualified synthetic load windows from 8 attempted windows" in model.summary[0]
    assert unused_id in model.tables[0].point_ids and failed_id in model.tables[0].point_ids
    for figure in model.figures:
        ids = [pid for series in figure.series for pid in series.point_ids]
        assert unused_id not in ids and failed_id in ids
    unused = next(point for point in model.points if point["point_id"] == unused_id)
    failed = next(point for point in model.points if point["point_id"] == failed_id)
    assert unused["execution_index"] is None and failed["execution_index"] is not None
    assert failed["qualification"] == "setup-limited" and failed["efficiency_pct"] is None
    assert failed["elapsed_s"] is None and len(model.raw_samples[failed_id]) == 21
    assert _row(model, 24)["highest_load_A"] == pytest.approx(.499)


@pytest.mark.parametrize("corruption", ["duplicate", "unknown", "omit-acquired", "omit-failed", "reverse"])
def test_voltage_execution_order_cannot_hide_or_reorder_raw_evidence(voltage_evidence, corruption):
    plan, run, analysis, samples = copy.deepcopy(voltage_evidence)
    ids = run["executed_point_ids"]
    if corruption == "duplicate":
        ids.append(ids[0])
    elif corruption == "unknown":
        ids.append("unplanned-point")
    elif corruption == "reverse":
        ids.reverse()
    elif corruption == "omit-failed":
        missing = ids.pop()
        next(point for point in run["points"] if point["point_id"] == missing).update(
            qualification="inconclusive", acquisition_cycle_ids=[])
        analysis = _analysis(plan, run, samples)
    else:
        ids.pop()
    with pytest.raises(ValueError, match="Recorded execution order"):
        build_report_model(plan, run, analysis, samples)


def test_continuation_keeps_prior_startup_outside_current_results(voltage_evidence):
    plan, run, _, samples = copy.deepcopy(voltage_evidence)
    omitted = {p.point_id for p in plan.points if p.vin_target_V == 12}
    plan.points = [p for p in plan.points if p.point_id not in omitted]
    plan.recipe.tests = [t for t in plan.recipe.tests if t.id != "efficiency-12v"]
    run["points"] = [p for p in run["points"] if p["point_id"] not in omitted]
    run["executed_point_ids"] = [pid for pid in run["executed_point_ids"] if pid not in omitted]
    samples = [s for s in samples if s["point_id"] not in omitted]
    sweep = run["method"]["voltage_efficiency_sweep"]
    sweep["phases"][0].update(status="previous-attempt-unqualified", stop_reason="Earlier startup aborted",
                              qualified_point_ids=[], executed_point_ids=[])
    sweep["prior_input_attempt"] = {"run_id": "synthetic-prior-startup", "integrity_sha256": "a" * 64,
        "qualified_points": 0, "reason": "Synthetic boundary", "nominal_input_V": 12.,
        "execution_status": "aborted", "last_startup_cycle":
        {"Vin_V": 2.661, "Iin_A": 1.0005, "Vout_V": 6.384208, "Iout_A": .056747}}
    model = build_report_model(plan, run, _analysis(plan, run, samples), samples)
    assert len(model.points) == 6
    assert all(p["vin_target_V"] != 12 for p in model.points)
    assert _row(model, 12)["reference_efficiency_pct"] is None
    assert _row(model, 12)["qualified_points"] == 0
    assert _row(model, 12)["phase_status"] == "previous-attempt-unqualified"
    assert all(s.vin_target_V != 12 for f in model.figures for s in f.series)
    assert "separate 12 V startup attempt stopped" in " ".join(model.summary)
    assert "2.661 V input" in " ".join(model.summary)
    assert "cause is not established" in " ".join(model.summary)
    assert "synthetic-prior-startup" in " ".join(model.method.procedure_notes)
    assert model.execution["voltage_efficiency_sweep"]["prior_input_attempt"]["integrity_sha256"] == "a" * 64
