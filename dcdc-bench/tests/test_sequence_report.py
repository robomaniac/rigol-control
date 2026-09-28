"""Ramp/hold/return reports derive time and drift from qualified retained evidence."""
import copy

import pytest

from dcdc_bench.analysis import analyze_evidence, build_report_model
from dcdc_bench.domain import RawSample, TestDefinition as Definition
from dcdc_bench.planning import build_plan
from dcdc_bench.reporting.renderer import _body, _plot_figure
from dcdc_bench.services import default_plan


@pytest.fixture
def sequence():
    initial = default_plan()
    initial.recipe.tests = [Definition(id=stage, input_voltage_targets_V=[24.],
        output_current_targets_A=currents) for stage, currents in [
            ("increasing-load", [.05, .5]), ("sustained-load", [.5, .5]),
            ("decreasing-load", [.1, .05])]]
    initial.recipe.acquisition.minimum_complete_cycles = 2
    plan = build_plan(initial.dut, initial.bench, initial.recipe)
    run = {"run_id": "synthetic-sequence", "execution_status": "completed", "points": []}
    samples = []
    for index, point in enumerate(plan.points):
        cycles = []
        for cycle_index in range(2):
            cycle = f"{point.point_id}-{cycle_index}"
            cycles.append(cycle)
            values = dict(Vin_V=24., Iin_A=point.iout_target_A / 1.6,
                          Vout_V=12. + index * .001, Iout_A=point.iout_target_A)
            for offset, (quantity, value) in enumerate(values.items()):
                binding = plan.bench.measurements[quantity]
                start = 1000. + index * 20 + cycle_index * 9 + offset * .01
                samples.append(RawSample(sample_id=f"{cycle}-{quantity}", run_id=run["run_id"],
                    test_id=point.test_id, point_id=point.point_id,
                    channel_id=binding.instrument_id + quantity, instrument_id=binding.instrument_id,
                    quantity=quantity, value=value, unit=binding.unit, location=binding.location,
                    query_start_utc="2026-01-01T00:00:00Z", query_end_utc="2026-01-01T00:00:00.005Z",
                    query_start_monotonic_s=start, query_end_monotonic_s=start + .005,
                    acquisition_cycle_id=cycle, phase="acquiring",
                    acquisition_settings={"source_mode": "CV", "load_compliance": True}).model_dump())
        run["points"].append({"point_id": point.point_id, "qualification": "valid",
                              "acquisition_cycle_ids": cycles, "acquisition_elapsed_s": 10.})
    # Earlier startup evidence must not shift the accepted-query time origin.
    rejected = copy.deepcopy(samples[0])
    rejected.update(sample_id="startup-only", acquisition_cycle_id="startup", phase="starting",
                    query_start_monotonic_s=10., query_end_monotonic_s=10.005)
    samples.append(rejected)
    analysis = analyze_evidence(plan, run, samples)
    analysis["analysis_id"] = "sequence-fixture"
    return plan, run, analysis, samples


def test_sequence_times_and_signed_drift_follow_accepted_bin_evidence(sequence):
    before = copy.deepcopy(sequence[2])
    model = build_report_model(*sequence)
    assert sequence[2] == before
    first = model.points[0]
    assert first["elapsed_start_s"] == 0
    assert first["elapsed_end_s"] == pytest.approx(9.035)
    assert first["elapsed_s"] == pytest.approx(4.5175)
    assert model.points[2]["display_label"] == "Hold bin 1 · 500 mA"
    drift = next(metric for metric in model.metrics if metric.id == "hold-voltage-change")
    assert drift.value == pytest.approx(1.)
    assert "20.000 s" in drift.conditions
    assert drift.point_ids == [model.points[2]["point_id"], model.points[3]["point_id"]]
    assert drift.uncertainty["status"] == "unquantified"
    assert not any(metric.id.startswith("load-span-sustained-load") for metric in model.metrics)
    body = _body(model.model_dump())
    assert "See @fig-hold-voltage, @fig-demand-time." in body
    assert "hold observes short-term voltage drift" in body
    assert "thermal equilibrium" in body
    assert model.figures[0].id == "fig-demand-time"
    assert model.figures[0].title == "Output Current vs Time"
    assert model.figures[0].x_key == "elapsed_s"
    assert "Time is relative to the first accepted query" in model.figures[0].caption
    hold_figure = next(figure for figure in model.figures if figure.id == "fig-hold-voltage")
    assert hold_figure.title == "Output Voltage vs Time (Sustained Load)"
    assert hold_figure.y_key == "Vout_V" and hold_figure.y_label == "Output Voltage (V)"


def test_hold_cannot_be_inferred_from_one_qualified_bin_or_missing_timestamps(sequence):
    plan, run, analysis, samples = sequence
    analysis["points"][2]["qualification"] = "inconclusive"
    model = build_report_model(plan, run, analysis, samples)
    assert model.points[2]["elapsed_s"] is None
    assert not any(metric.id == "hold-voltage-change" for metric in model.metrics)
    for point in analysis["points"]:
        point["accepted_sample_ids"] = []
    model = build_report_model(plan, run, analysis, samples)
    assert all(point["elapsed_s"] is None for point in model.points)


def _adaptive_sequence(sequence):
    plan, run, analysis, samples = copy.deepcopy(sequence)
    plan.recipe.tests = [test for test in plan.recipe.tests if test.id != "sustained-load"]
    plan.points = [p for p in plan.points if p.test_id != "sustained-load"]
    ids = {p.point_id for p in plan.points}
    run["points"] = [p for p in run["points"] if p["point_id"] in ids]
    analysis["points"] = [p for p in analysis["points"] if p["point_id"] in ids]
    samples = [s for s in samples if s["point_id"] in ids]
    run["executed_point_ids"] = [p.point_id for p in plan.points]
    run["method"] = {"source_limit_search": {"input_current_limit_A": 1.,
        "target_input_current_A": .98, "output_current_cap_A": 2., "stop_reason": "fixture boundary"}}
    return plan, run, analysis, samples


def test_adaptive_report_shows_source_current_and_no_invented_hold(sequence):
    data = _adaptive_sequence(sequence)
    model = build_report_model(*data)
    figure_ids = {figure.id for figure in model.figures}
    assert "fig-demand-time" in figure_ids and "fig-source-current" in figure_ids
    assert "fig-hold-voltage" not in figure_ids
    current_figure = next(figure for figure in model.figures if figure.id == "fig-source-current")
    assert current_figure.title == "Input Current"
    assert (current_figure.x_key, current_figure.y_key) == ("Iout_A", "Iin_A")
    metric = next(m for m in model.metrics if m.id == "highest-qualified-input-current")
    assert metric.value == pytest.approx(.5 / 1.6)
    assert metric.point_ids == [data[0].points[1].point_id]
    body = _body(model.model_dump())
    assert "@fig-hold-voltage" not in body
    assert "hold observes" not in body and "Each hold bin" not in body
    assert "Regulation and return results" in body
    assert "The 1 A limit belongs to the supply" in body
    assert "100% defines an ideal-power ceiling only" in body


def test_adaptive_unrequested_candidates_remain_evidence_without_breaking_curves(sequence):
    plan, run, analysis, samples = _adaptive_sequence(sequence)
    unused = analysis["points"][1]
    unused.update(qualification="not-run", accepted_sample_ids=[], accepted_cycle_count=0)
    pid = unused["point_id"]
    next(p for p in run["points"] if p["point_id"] == pid).update(qualification="not-run", acquisition_cycle_ids=[])
    samples = [s for s in samples if s["point_id"] != pid]
    run["executed_point_ids"].remove(pid)
    model = build_report_model(plan, run, analysis, samples)
    assert len(model.points) == len(plan.points)
    assert all(pid not in series.point_ids for figure in model.figures for series in figure.series)
    assert "3 attempted windows" in model.summary[0]
    assert "1 conditional load candidates were not requested" in _body(model.model_dump())


@pytest.mark.parametrize("order", ["duplicate", "unknown", "omitted", "string", "reversed"])
def test_adaptive_execution_order_cannot_hide_or_duplicate_evidence(sequence, order):
    data = _adaptive_sequence(sequence)
    ids = data[1]["executed_point_ids"]
    if order == "duplicate":
        ids.append(ids[0])
    elif order == "unknown":
        ids.append("unknown")
    elif order == "omitted":
        ids.pop()
    elif order == "reversed":
        ids.reverse()
    else:
        data[1]["executed_point_ids"] = "not a list"
    with pytest.raises(ValueError, match="Recorded execution order"):
        build_report_model(*data)


def test_phase_filters_and_colors_stay_distinct_at_same_input_voltage(sequence):
    model = build_report_model(*sequence).model_dump()
    demand = model["figures"][0]
    assert len({series["selection_key"] for series in demand["series"]}) == 3
    assert [series["label"] for series in demand["series"]] == [
        "Increasing demand · 24 V", "Sustained load · 24 V", "Decreasing demand · 24 V"]
    efficiency = next(spec for spec in model["figures"] if spec["id"] == "fig-efficiency")
    plot = _plot_figure(model, efficiency, 2)
    assert plot.data[1].mode == "markers"
    hold = next(spec for spec in model["figures"] if spec["id"] == "fig-hold-voltage")
    hold_plot = _plot_figure(model, hold, 5)
    assert hold_plot.data[0].line.color == plot.data[1].line.color
    assert hold_plot.data[0].mode == "lines+markers"
    assert list(hold_plot.data[0].x) == pytest.approx([44.5175, 64.5175])


def _transition_traces(plot):
    return [trace for trace in plot.data if trace.meta and trace.meta.get("isTransition")]


def test_time_plot_joins_stages_using_existing_endpoints_only(sequence):
    model = build_report_model(*sequence).model_dump()
    before = copy.deepcopy(model)
    plot = _plot_figure(model, model["figures"][0], 1)
    joins = _transition_traces(plot)
    assert len(joins) == 2
    for trace, indices in zip(joins, ((1, 2), (3, 4))):
        endpoints = [model["points"][index] for index in indices]
        assert list(trace.x) == [point["elapsed_s"] for point in endpoints]
        assert list(trace.y) == [point["Iout_A"] for point in endpoints]
        assert trace.mode == "lines" and trace.line.dash == "dot"
        assert trace.hoverinfo == "skip" and trace.showlegend is False
        assert trace.customdata is None and trace.connectgaps is False
    marker_ids = [pid for trace in plot.data if trace.customdata for pid in trace.customdata]
    assert marker_ids == [point["point_id"] for point in model["points"]]
    assert "Dotted lines join stage boundaries; no extra samples." in model["figures"][0]["caption"]
    assert model == before, "Drawing guides must not change observations, metrics or figure point IDs"


@pytest.mark.parametrize("change", [
    {"qualification": "inconclusive"}, {"qualification": "not-run"},
    {"elapsed_s": None}, {"elapsed_s": float("nan")}, {"elapsed_s": 0.},
    {"Iout_A": None}, {"Iout_A": float("inf")},
    {"vin_target_V": 30.}, {"vin_target_V": None},
    {"phase_label": None},
])
def test_stage_join_never_skips_unqualified_unknown_or_changed_input(sequence, change):
    model = build_report_model(*sequence).model_dump()
    model["points"][2].update(change)
    joins = _transition_traces(_plot_figure(model, model["figures"][0], 1))
    assert len(joins) == 1
    assert list(joins[0].x) == [model["points"][i]["elapsed_s"] for i in (3, 4)]


def test_stage_join_follows_the_actual_phase_boundary(sequence):
    model = build_report_model(*sequence).model_dump()
    model["points"][2]["phase_label"] = "Increasing demand"
    joins = _transition_traces(_plot_figure(model, model["figures"][0], 1))
    assert len(joins) == 2
    assert [list(guide.x) for guide in joins] == [
        [model["points"][i]["elapsed_s"] for i in pair] for pair in ((2, 3), (3, 4))]


def test_stage_join_does_not_bridge_a_point_omitted_from_the_figure(sequence):
    model = build_report_model(*sequence).model_dump()
    demand = model["figures"][0]
    demand["series"][1]["point_ids"].remove(model["points"][2]["point_id"])
    joins = _transition_traces(_plot_figure(model, demand, 1))
    assert len(joins) == 1
    assert list(joins[0].x) == [model["points"][i]["elapsed_s"] for i in (3, 4)]
    demand["series"].pop(1)
    assert not _transition_traces(_plot_figure(model, demand, 1))


def test_stage_join_requires_adjacency_in_recorded_time_too(sequence):
    model = build_report_model(*sequence).model_dump()
    extra = copy.deepcopy(model["points"][-1])
    extra.update(point_id="out-of-order-window", elapsed_s=35.)
    model["points"].append(extra)
    joins = _transition_traces(_plot_figure(model, model["figures"][0], 1))
    assert len(joins) == 1
    assert list(joins[0].x) == [model["points"][i]["elapsed_s"] for i in (3, 4)]


def test_recorded_execution_can_skip_only_uncommanded_candidates(sequence):
    model = build_report_model(*sequence).model_dump()
    demand = model["figures"][0]
    candidate = copy.deepcopy(model["points"][1])
    candidate.update(point_id="uncommanded-candidate", qualification="not-run", elapsed_s=None)
    model["points"].insert(2, candidate)
    # A not-run row alone cannot prove it is safe to join past it.
    assert len(_transition_traces(_plot_figure(model, demand, 1))) == 1
    attempted = [point["point_id"] for point in model["points"] if point is not candidate]
    model["execution"]["executed_point_ids"] = attempted
    before = copy.deepcopy(model)
    joins = _transition_traces(_plot_figure(model, demand, 1))
    assert len(joins) == 2
    assert list(joins[0].x) == [model["points"][i]["elapsed_s"] for i in (1, 3)]
    assert candidate["point_id"] not in attempted
    assert model == before
    # A failed actual attempt is a gap even when its elapsed time is unknown.
    candidate["qualification"] = "inconclusive"
    model["execution"]["executed_point_ids"].insert(2, candidate["point_id"])
    assert len(_transition_traces(_plot_figure(model, demand, 1))) == 1
    # Removing a failed attempt from the record invalidates the claimed order.
    model["execution"]["executed_point_ids"].remove(candidate["point_id"])
    assert len(_transition_traces(_plot_figure(model, demand, 1))) == 1


@pytest.mark.parametrize("record", ["wrong type", ["unknown-point"], [], [None]])
def test_invalid_execution_record_preserves_original_gaps(sequence, record):
    model = build_report_model(*sequence).model_dump()
    model["points"][2].update(qualification="inconclusive", elapsed_s=None)
    model["execution"]["executed_point_ids"] = record
    joins = _transition_traces(_plot_figure(model, model["figures"][0], 1))
    assert len(joins) == 1
    assert list(joins[0].x) == [model["points"][i]["elapsed_s"] for i in (3, 4)]


def test_duplicate_execution_ids_cannot_create_repeated_guides(sequence):
    model = build_report_model(*sequence).model_dump()
    attempted = [point["point_id"] for point in model["points"]]
    model["execution"]["executed_point_ids"] = attempted + attempted
    assert len(_transition_traces(_plot_figure(model, model["figures"][0], 1))) == 2


def test_executed_order_must_still_follow_adjacent_measurement_times(sequence):
    model = build_report_model(*sequence).model_dump()
    attempted = [point["point_id"] for point in model["points"]]
    attempted[2], attempted[3] = attempted[3], attempted[2]
    model["execution"]["executed_point_ids"] = attempted
    assert not _transition_traces(_plot_figure(model, model["figures"][0], 1))


def test_stage_guides_are_exclusive_to_the_time_demand_view(sequence):
    model = build_report_model(*sequence).model_dump()
    for index, spec in enumerate(model["figures"][1:], 2):
        assert not _transition_traces(_plot_figure(model, spec, index))
    demand = model["figures"][0]
    demand["x_key"] = "Iout_A"
    assert not _transition_traces(_plot_figure(model, demand, 1))


def test_return_comparison_requires_both_qualified_matching_endpoints(sequence):
    plan, run, analysis, samples = sequence
    run["method"] = {"hold_settling": "Hold inherits previous settling",
                     "sustained_load_actual_elapsed_s": 180.25,
                     "hardware_deadline_s": 720, "software_deadline_s": 660}
    for index, point in enumerate(run["points"]):
        inherited = index in (2, 3)
        point["settling_inherited_from_previous_point"] = inherited
        point["settling_elapsed_s"] = .000002 if inherited else 5.5
    model = build_report_model(plan, run, analysis, samples)
    returned = next(m for m in model.metrics if m.id == "return-voltage-change")
    assert returned.value == pytest.approx(5.)
    assert returned.point_ids == [model.points[0]["point_id"], model.points[-1]["point_id"]]
    assert returned.selector == {"vin_target_V": 24., "iout_target_A": .05}
    assert "observation windows" in model.summary[0]
    assert "3 distinct requested" in model.summary[0]
    assert "180.250 s" in " ".join(model.method.procedure_notes)
    assert model.method.achieved_points[2].settling_elapsed_s == .000002
    assert model.method.achieved_points[2].settling_inherited_from_previous_point
    body = _body(model.model_dump())
    assert "continuous hold bins do not restart it" in body
    assert "fresh samples" not in body
    assert "5.5 s / 10 s" in body
    analysis["points"][-1]["qualification"] = "inconclusive"
    model = build_report_model(plan, run, analysis, samples)
    assert not any(m.id == "return-voltage-change" for m in model.metrics)
