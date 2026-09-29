"""Report method and cross-references use retained evidence, without render tools."""
import copy

import pytest

from dcdc_bench.analysis import ReportModel, analyze_evidence, build_report_model
from dcdc_bench.domain import RawSample
from dcdc_bench.planning import build_plan
from dcdc_bench.reporting.renderer import _body
from dcdc_bench.services import default_plan


@pytest.fixture
def evidence():
    initial = default_plan()
    initial.recipe.tests[0].input_voltage_targets_V = [24.]
    initial.recipe.tests[0].output_current_targets_A = [.1, .5]
    plan = build_plan(initial.dut, initial.bench, initial.recipe)
    run = {"run_id": "method-test", "execution_status": "completed", "points": [],
           "clock": {"mode": "virtual", "note": "Synthetic model time; no hardware."}}
    samples = []
    for index, point in enumerate(plan.points):
        cycles = []
        for n in range(plan.recipe.acquisition.minimum_complete_cycles):
            cycle = f"{point.point_id}-c{n}"
            cycles.append(cycle)
            for offset, (quantity, value) in enumerate({"Vin_V": 24., "Iin_A": .3,
                    "Vout_V": 12., "Iout_A": point.iout_target_A}.items()):
                binding = plan.bench.measurements[quantity]
                started = index * 100. + n + offset * .002
                samples.append(RawSample(sample_id=f"{cycle}-{quantity}", run_id=run["run_id"],
                    test_id=point.test_id, point_id=point.point_id,
                    channel_id=binding.instrument_id + quantity, instrument_id=binding.instrument_id,
                    quantity=quantity, value=value, unit=binding.unit, location=binding.location,
                    query_start_utc="2026-01-01T00:00:00Z", query_end_utc="2026-01-01T00:00:00.001Z",
                    query_start_monotonic_s=started, query_end_monotonic_s=started + .001,
                    acquisition_cycle_id=cycle, phase="acquiring",
                    acquisition_settings={"source_mode": "CV", "load_compliance": True}).model_dump())
        run["points"].append({"point_id": point.point_id, "qualification": "valid",
                              "acquisition_cycle_ids": cycles, "settling_elapsed_s": 5.5,
                              "acquisition_elapsed_s": 5.2})
    analysis = analyze_evidence(plan, run, samples)
    analysis["analysis_id"] = "method-fixture"
    return plan, run, analysis, samples


def test_method_preserves_policy_phase_durations_and_observed_query_spans(evidence):
    plan, run, analysis, samples = evidence
    model = build_report_model(plan, run, analysis, samples)
    assert model.method.declared_acquisition == plan.recipe.acquisition
    assert model.method.declared_settling == plan.recipe.settling
    assert model.method.clock_mode == "virtual"
    for point in model.method.achieved_points:
        assert point.accepted_cycle_count == 5
        assert point.settling_elapsed_s == 5.5
        assert point.acquisition_elapsed_s == 5.2
        assert point.accepted_query_span_s == pytest.approx(4.007)
        assert point.maximum_accepted_interchannel_skew_s == pytest.approx(.007)
    body = _body(model.model_dump())
    assert "### Acquisition method" in body
    assert "5.5 s / 5.2 s" in body
    assert "**Timing basis:** virtual" in body
    assert "an instrument ADC update interval" in body
    assert run["points"][0]["acquisition_elapsed_s"] == 5.2


def test_unknown_phase_duration_is_not_replaced_by_declared_setting(evidence):
    plan, run, analysis, samples = evidence
    for point in run["points"]:
        del point["settling_elapsed_s"]
        del point["acquisition_elapsed_s"]
    del run["clock"]
    model = build_report_model(plan, run, analysis, samples)
    assert all(point.acquisition_elapsed_s is None for point in model.method.achieved_points)
    assert all(point.settling_elapsed_s is None for point in model.method.achieved_points)
    assert all(point.accepted_query_span_s is not None for point in model.method.achieved_points)
    assert model.method.clock_mode is None
    body = _body(model.model_dump())
    assert "not recorded / not recorded" in body
    assert "**Timing basis:** unknown" in body


def test_summary_references_use_metric_registry_and_survive_figure_reordering(evidence):
    model = build_report_model(*evidence)
    assert not any("See Figure" in text for text in model.summary)
    assert model.summary_evidence
    reference = model.summary_evidence[0]
    assert reference.metric_ids == ["highest-observed-efficiency"]
    data = model.model_dump()
    data["figures"].reverse()
    checked = ReportModel.model_validate(data)
    body = _body(checked.model_dump())
    assert "See @fig-efficiency." in body
    assert "See Figure 1" not in body


@pytest.mark.parametrize("change, message", [
    ("metric", "missing metric"), ("paragraph", "missing paragraph"),
    ("method-point", "missing point"),
])
def test_bad_method_and_summary_references_block_report(evidence, change, message):
    data = build_report_model(*evidence).model_dump()
    if change == "metric":
        data["summary_evidence"][0]["metric_ids"] = ["unknown-metric"]
    elif change == "paragraph":
        data["summary_evidence"][0]["paragraph_index"] = len(data["summary"])
    else:
        data["method"]["achieved_points"][0]["point_id"] = "unknown-point"
    with pytest.raises(ValueError, match=message):
        ReportModel.model_validate(data)


def test_plain_summary_text_cannot_inject_crossrefs_or_active_markup(evidence):
    data = build_report_model(*evidence).model_dump()
    paragraph = data["summary_evidence"][0]["paragraph_index"]
    data["summary"][paragraph] = '<img onerror="alert(1)"> @fig-loss [go](javascript:alert(1))'
    before = copy.deepcopy(data)
    body = _body(data)
    assert r"\<img" in body
    assert r"\@fig-loss" in body
    assert r"\[go\]" in body
    assert "See @fig-efficiency." in body
    assert data == before
