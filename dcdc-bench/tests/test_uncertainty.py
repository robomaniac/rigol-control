"""Structured readback uncertainty budget (brief 9.2; UNC-01..04, CORE-06).

Every specification in this file is a synthetic fixture for the calculation.
None of these numbers describes the first DUT's bench.
"""
import json
import math

import pytest
from pydantic import ValidationError

from dcdc_bench.analysis import analyze_run, build_report_model, coverage_by_test, dc_metrics
from dcdc_bench.domain import (AccuracySpec, BenchProfile, CalibrationRecord, ChannelCorrelation, MeasurementBinding,
                               ReadbackSpecification, TemperatureCoefficient, UncertaintyPolicy,
                               unknown_readback_specification)
from dcdc_bench.planning import load_profile
from dcdc_bench.services import PROJECT_ROOT, default_plan
from dcdc_bench.uncertainty import (CHANNELS, DERIVED, LINEAR_MODEL_FLAG, SCHEMA_VERSION, channel_specification_review,
                                    channel_standard_uncertainty, difference_uncertainty, evaluate_point,
                                    evaluate_run_budget, evaluated_quantity, format_efficiency_label)

CAL = CalibrationRecord(status="within_interval", certificate="fixture-only",
                        note="synthetic fixture record; no instrument or certificate exists")


def fixture_spec(**terms) -> ReadbackSpecification:
    return ReadbackSpecification(status="unverified_user_entry", source="UNC calculation fixture", calibration=CAL,
                                 percent_of_range=0., resolution=0., **terms)


def unc01_bench() -> BenchProfile:
    bench = default_plan().bench.model_copy(deep=True)
    omitted = dict(percent_of_reading=0., absolute_offset=0.)  # the fixture deliberately omits voltage terms
    bench.measurements["Vin_V"].readback_specification = fixture_spec(**omitted)
    bench.measurements["Vout_V"].readback_specification = fixture_spec(**omitted)
    bench.measurements["Iin_A"].readback_specification = fixture_spec(percent_of_reading=.05, absolute_offset=.0001)
    bench.measurements["Iout_A"].readback_specification = fixture_spec(percent_of_reading=.10, absolute_offset=.0006)
    return bench


def reviews(bench, *, mode="mock", label="SYNTHETIC"):
    return {q: channel_specification_review(q, bench.measurements.get(q), bench_mode=mode, evidence_label=label)
            for q in CHANNELS}


def unc01_point(iin=.0078, iout=.030, vin=1.):
    vout = .4024 * vin * iin / iout if iout else 0.
    values = dict(Vin_V=vin, Iin_A=iin, Vout_V=vout, Iout_A=iout)
    return {"point_id": "p-unc01", "qualification": "valid", **values, **dc_metrics(values, 12.)}


def fixture_points(plan):
    points = []
    for request in plan.points:
        p = request.model_dump()
        p.update(qualification="valid", Vin_V=request.vin_target_V, Iin_A=.3, Vout_V=12., Iout_A=request.iout_target_A)
        p.update(dc_metrics(p, 12., no_load=p["iout_target_A"] == 0))
        points.append(p)
    return points


def report_model(plan, bench):
    plan = plan.model_copy(update={"bench": bench})
    points = fixture_points(plan)
    budget = evaluate_run_budget(plan, points, {}, evidence_label="SYNTHETIC")
    analysis = dict(points=points, coverage=coverage_by_test(points), analysis_id="fixture-only", formula_version="test",
                    aggregation="synthetic fixture", sign_convention="positive input/output", uncertainty=budget)
    return build_report_model(plan, {"run_id": "synthetic-fixture", "execution_status": "completed"}, analysis, []), budget


def test_unc01_fixture_reproduced_through_the_evaluator():
    result = evaluate_point(unc01_point(), reviews(unc01_bench()), policy=UncertaintyPolicy(), correlations={})
    assert result["status"] == "evaluated"
    iin = result["channels"]["Iin_A"]
    assert iin["terms"]["specification_limit"]["half_width"] == pytest.approx(.0005 * .0078 + .0001)
    assert iin["standard"] == pytest.approx((.0005 * .0078 + .0001) / math.sqrt(3))
    efficiency = result["quantities"]["efficiency_pct"]
    assert efficiency["status"] == "evaluated" and efficiency["unit"] == "percentage points" and efficiency["k"] == 2
    assert efficiency["expanded"] == pytest.approx(1.155512754, abs=1e-9)
    assert efficiency["label"] == "40.2% ± 1.2 percentage points"
    assert efficiency["independence_assumed"] is True
    assert result["metrology"] == "specification-bound only (unverified user entry)"


def test_efficiency_label_is_in_percentage_points():
    assert format_efficiency_label(92.6, .4) == "92.6% ± 0.4 percentage points"
    assert format_efficiency_label(92.61, .043) == "92.610% ± 0.043 percentage points"
    with pytest.raises(ValueError):
        format_efficiency_label(92.6, 0.)


def test_unc02_unknown_term_yields_not_evaluated_and_no_bands_in_report_model():
    bench = unc01_bench()
    bench.measurements["Iin_A"].readback_specification = unknown_readback_specification("Iin_A")
    result = evaluate_point(unc01_point(), reviews(bench), policy=UncertaintyPolicy(), correlations={})
    assert result["status"] == "partially_evaluated" and result["metrology"] == "unquantified"
    assert result["channels"]["Iin_A"]["status"] == "not_evaluated"
    assert any("specification status unknown" in reason for reason in result["channels"]["Iin_A"]["reasons"])
    for name in ("Pin_W", "efficiency_pct", "loss_W"):
        quantity = result["quantities"][name]
        assert quantity["status"] == "not_evaluated"
        assert "Iin_A standard uncertainty not evaluated" in quantity["reasons"]
        assert not {"value", "standard", "expanded", "lower", "upper", "label"} & quantity.keys()
    assert result["quantities"]["Pout_W"]["status"] == "evaluated"
    # Report model: bands only for the quantities that were evaluated (here Vout only);
    # efficiency, loss and input power carry no band, ± text or metric uncertainty.
    model, budget = report_model(default_plan(), bench)
    assert budget["status"] == "partially_evaluated"
    for figure in model.figures:
        if figure.y_key in ("efficiency_pct", "loss_W", "Pin_W", "Iin_A"):
            assert figure.lower_key is None and figure.upper_key is None
        elif figure.y_key == "Vout_V":
            assert (figure.lower_key, figure.upper_key) == ("Vout_V_lower", "Vout_V_upper")
    assert not any(key.startswith(("efficiency_pct_", "loss_W_", "Pin_W_", "Iin_A_")) and key.endswith(("_lower", "_upper", "_uncertainty_label"))
                   for point in model.points for key in point)
    assert all(metric.uncertainty["expanded"] is None for metric in model.metrics)
    assert model.uncertainty["status"] == "partially_evaluated"
    assert set(model.uncertainty["banded_quantities"]) == {"Vin_V", "Vout_V", "Iout_A", "Pout_W"}
    assert any("Not evaluated" in line and "Iin_A" in line for line in model.limitations)
    assert not any("percentage points" in line for line in model.summary)
    # Every channel unknown: no band anywhere, nothing evaluated, explicit unquantified statement.
    for quantity in CHANNELS:
        bench.measurements[quantity].readback_specification = unknown_readback_specification(quantity)
    model, budget = report_model(default_plan(), bench)
    assert budget["status"] == "not_evaluated" and budget["summary"]["evaluated_points"] == 0
    assert all(figure.lower_key is None and figure.upper_key is None for figure in model.figures)
    assert not any(key.endswith(("_lower", "_upper", "_uncertainty_label")) for point in model.points for key in point)
    assert all(metric.uncertainty["expanded"] is None for metric in model.metrics)
    assert model.uncertainty["status"] == "not_evaluated" and model.uncertainty["evaluated_point_ids"] == []
    assert any("Uncertainty is unquantified" in line and "Vin_V: specification status unknown" in line
               and "Iout_A: specification status unknown" in line for line in model.limitations)
    assert all(result["metrology"] == "unquantified" for result in budget["points"].values())


def test_unc03_covariance_changes_the_difference_and_the_efficiency_budget():
    a = {"status": "evaluated", "value": 92.6, "standard": .2, "unit": "percentage points"}
    b = {"status": "evaluated", "value": 91.9, "standard": .2, "unit": "percentage points"}
    independent = difference_uncertainty(a, b, k=2)
    assert independent["standard"] == pytest.approx(math.sqrt(.08)) and independent["independence_assumed"] is True
    assert independent["expanded"] == pytest.approx(2 * math.sqrt(.08))
    correlated = difference_uncertainty(a, b, correlation=1.)
    assert correlated["standard"] == pytest.approx(0.) and correlated["independence_assumed"] is False
    with pytest.raises(ValueError):
        difference_uncertainty(a, b, correlation=1.5)
    assert difference_uncertainty(a, {"status": "not_evaluated"})["status"] == "not_evaluated"
    # Declared channel correlation on the bench changes the propagated efficiency uncertainty.
    bench = unc01_bench()
    voltage = fixture_spec(percent_of_reading=.05, absolute_offset=.002)
    bench.measurements["Vin_V"].readback_specification = voltage
    bench.measurements["Vout_V"].readback_specification = voltage
    plan = default_plan()
    independent_budget = evaluate_run_budget(plan.model_copy(update={"bench": bench}), [unc01_point()], {},
                                             evidence_label="SYNTHETIC")
    bench.readback_correlations = [ChannelCorrelation(quantity_a="Vin_V", quantity_b="Vout_V", coefficient=1.,
                                                      justification="fixture: shared voltage reference")]
    correlated_budget = evaluate_run_budget(plan.model_copy(update={"bench": bench}), [unc01_point()], {},
                                            evidence_label="SYNTHETIC")
    assert independent_budget["correlations"]["independence_assumed"] is True
    assert correlated_budget["correlations"]["independence_assumed"] is False
    u_ind = independent_budget["points"]["p-unc01"]["quantities"]["efficiency_pct"]["standard"]
    u_cor = correlated_budget["points"]["p-unc01"]["quantities"]["efficiency_pct"]["standard"]
    assert u_cor < u_ind
    assert correlated_budget["points"]["p-unc01"]["quantities"]["efficiency_pct"]["independence_assumed"] is False
    with pytest.raises(ValidationError):
        ChannelCorrelation(quantity_a="Vin_V", quantity_b="Vin_V", coefficient=.5, justification="same channel")
    with pytest.raises(ValidationError):
        bench.readback_correlations = [ChannelCorrelation(quantity_a="Vin_V", quantity_b="Tcase_C", coefficient=.5,
                                                          justification="unbound channel")]


def test_unc04_systematic_terms_are_never_divided_by_sample_count():
    spec = fixture_spec(percent_of_reading=.05, absolute_offset=.0001)
    few = channel_standard_uncertainty(spec, .0078, unit="A", samples=[.0078] * 5)
    many = channel_standard_uncertainty(spec, .0078, unit="A", samples=[.0078] * 5000)
    assert few["systematic_standard"] == many["systematic_standard"] == pytest.approx(.0001039 / math.sqrt(3))
    assert few["standard"] == many["standard"]
    assert few["systematic_scaling_with_n"] == "none"
    noisy = channel_standard_uncertainty(spec, .0078, unit="A", samples=[.0077, .0079] * 50)
    assert noisy["systematic_standard"] == few["systematic_standard"]
    assert noisy["repeatability"]["status"] == "evaluated" and noisy["repeatability"]["n"] == 100
    assert noisy["repeatability"]["standard_error_of_mean"] == pytest.approx(
        noisy["repeatability"]["sample_standard_deviation"] / 10)
    assert noisy["standard"] > noisy["systematic_standard"]
    recorded_only = channel_standard_uncertainty(spec, .0078, unit="A", samples=[.0077, .0079] * 50,
                                                 include_repeatability=False)
    assert recorded_only["standard"] == recorded_only["systematic_standard"]
    assert recorded_only["repeatability"]["included_in_combined"] is False
    single = channel_standard_uncertainty(spec, .0078, unit="A", samples=[.0078])
    assert single["repeatability"]["status"] == "not_evaluated" and single["standard"] == single["systematic_standard"]


def test_core06_programming_accuracy_is_never_used_for_readback():
    bench = unc01_bench()
    programming = AccuracySpec(applies_to="programming", reading_fraction=.001, offset=.01, unit="A",
                               source="example-only", conditions="CC programming range")
    binding = bench.measurements["Iout_A"]
    binding.programming_accuracy = programming
    binding.readback_specification = None
    bench.load.programming_accuracy = {"current": programming}
    review = channel_specification_review("Iout_A", binding, bench_mode="mock", evidence_label="SYNTHETIC")
    assert review["evaluable"] is False and review["programming_accuracy_consulted"] is False
    assert review["reasons"] == ["Iout_A: readback_specification not declared"]
    result = evaluate_point(unc01_point(), reviews(bench), policy=UncertaintyPolicy(), correlations={})
    for name in ("Pout_W", "efficiency_pct", "loss_W"):
        assert result["quantities"][name]["status"] == "not_evaluated"
    assert result["quantities"]["Pin_W"]["status"] == "evaluated"
    with pytest.raises(ValidationError):
        MeasurementBinding(instrument_id="load", quantity="Iout_A", unit="A", location="dut_output",
                           readback_specification=programming)
    with pytest.raises(ValidationError):
        ReadbackSpecification(role="programming", status="unverified_user_entry", source="x")


def test_loss_uncertainty_is_propagated_separately_in_watts():
    result = evaluate_point(unc01_point(), reviews(unc01_bench()), policy=UncertaintyPolicy(), correlations={})
    loss, efficiency = result["quantities"]["loss_W"], result["quantities"]["efficiency_pct"]
    point = unc01_point()
    u_iin, u_iout = (.0005 * .0078 + .0001) / math.sqrt(3), (.001 * .030 + .0006) / math.sqrt(3)
    expected = math.hypot(point["Vin_V"] * u_iin, point["Vout_V"] * u_iout)
    assert loss["unit"] == "W" and loss["model"] == "Vin_V * Iin_A - Vout_V * Iout_A"
    assert loss["standard"] == pytest.approx(expected)
    assert loss["expanded"] == pytest.approx(2 * expected)
    assert loss["sensitivity_coefficients"] == pytest.approx(
        {"Vin_V": point["Iin_A"], "Iin_A": point["Vin_V"], "Vout_V": -point["Iout_A"], "Iout_A": -point["Vout_V"]})
    assert loss["label"].endswith(" W") and "percentage" not in loss["label"]
    assert loss["expanded"] != pytest.approx(efficiency["expanded"] / 100 * point["Pin_W"])


def test_near_zero_current_flags_questionable_linear_approximation_instead_of_symmetric_bands():
    policy = UncertaintyPolicy()
    small = evaluate_point(unc01_point(iin=.0005), reviews(unc01_bench()), policy=policy, correlations={})
    iin = small["channels"]["Iin_A"]
    assert iin["status"] == "evaluated" and iin["relative_standard"] > policy.linear_model_relative_uncertainty_bound
    efficiency = small["quantities"]["efficiency_pct"]
    assert efficiency["status"] == "not_evaluated" and LINEAR_MODEL_FLAG in efficiency["flags"]
    assert any(LINEAR_MODEL_FLAG in reason and "Iin_A" in reason for reason in efficiency["reasons"])
    assert "expanded" not in efficiency and "lower" not in efficiency
    pin = small["quantities"]["Pin_W"]
    assert pin["status"] == "evaluated" and LINEAR_MODEL_FLAG in pin["flags"]
    zero = evaluate_point(unc01_point(iout=0.), reviews(unc01_bench()), policy=policy, correlations={})
    assert zero["channels"]["Iout_A"]["relative_standard"] is None
    assert zero["quantities"]["efficiency_pct"]["status"] == "not_evaluated"
    assert any("undefined at a zero mean" in reason for reason in zero["quantities"]["efficiency_pct"]["reasons"])


def test_unknown_real_profiles_yield_not_evaluated_for_every_quantity():
    example = load_profile(PROJECT_ROOT / "profiles/bench/rigol.example.yaml", BenchProfile)
    from dcdc_bench.bringup import pilot_plan
    from dcdc_bench.extended import extended_plan
    for bench in (example, extended_plan().bench, pilot_plan().bench):
        assert bench.mode == "real"
        for quantity, binding in bench.measurements.items():
            spec = binding.readback_specification
            assert spec is not None and spec.status == "unknown" and spec.source == "unknown"
            assert spec.percent_of_reading is None and spec.absolute_offset is None and spec.resolution is None
            document = "DP800_DataSheet_EN.pdf" if quantity in ("Vin_V", "Iin_A") else "DL3000_DataSheet_EN.pdf"
            assert any(document in candidate for candidate in spec.source_candidates)
            assert spec.calibration.status == "unknown"
    plan = default_plan().model_copy(update={"bench": example})
    points = fixture_points(plan)
    budget = evaluate_run_budget(plan, points, {}, evidence_label="MEASURED")
    json.dumps(budget, allow_nan=False)
    assert budget["schema_version"] == SCHEMA_VERSION
    assert budget["status"] == "not_evaluated" and budget["metrology"] == "unquantified"
    assert budget["summary"]["evaluated_points"] == 0 and budget["summary"]["partially_evaluated_points"] == 0
    assert any("readback" in reason or "unknown" in reason for reason in budget["reasons"])
    for result in budget["points"].values():
        assert result["status"] == "not_evaluated" and result["metrology"] == "unquantified"
        for name in (*CHANNELS, *DERIVED):
            item = result["channels"][name] if name in CHANNELS else result["quantities"][name]
            assert item["status"] == "not_evaluated" and item["reasons"]
            assert not {"value", "standard", "expanded", "lower", "upper"} & item.keys()
            assert evaluated_quantity(budget, result["point_id"], name) is None
    # A synthetic example specification is refused on a real bench or for measured evidence.
    mock = default_plan().bench
    assert mock.measurements["Vin_V"].readback_specification.status == "synthetic_example"
    for mode, label in (("real", "MEASURED"), ("mock", "MEASURED"), ("real", "SYNTHETIC")):
        review = channel_specification_review("Vin_V", mock.measurements["Vin_V"], bench_mode=mode, evidence_label=label)
        assert review["evaluable"] is False and any("synthetic" in reason for reason in review["reasons"])


def test_specification_schema_rejects_inconsistent_provenance():
    with pytest.raises(ValidationError, match="unknown readback specification cannot carry numeric terms"):
        ReadbackSpecification(status="unknown", percent_of_reading=.1)
    with pytest.raises(ValidationError, match="must cite"):
        ReadbackSpecification(status="datasheet_quoted", source="unknown", percent_of_reading=.1)
    with pytest.raises(ValidationError, match="synthetic"):
        ReadbackSpecification(status="synthetic_example", source="DP800 datasheet", percent_of_reading=.1)
    with pytest.raises(ValidationError, match="range value"):
        ReadbackSpecification(status="unverified_user_entry", source="x", percent_of_range=.1)
    with pytest.raises(ValidationError, match="calibration record"):
        ReadbackSpecification(status="calibrated", source="cert 1", percent_of_reading=.1)
    with pytest.raises(ValidationError, match="unit does not match"):
        MeasurementBinding(instrument_id="load", quantity="Iout_A", unit="A", location="dut_output",
                           readback_specification=ReadbackSpecification(status="unverified_user_entry", source="x", unit="V"))
    spec = ReadbackSpecification(status="datasheet_quoted", source="fixture document p. 1", percent_of_reading=.1)
    assert spec.missing_terms() == ["percent_of_range not declared", "absolute_offset not declared",
                                    "resolution not declared",
                                    "calibration status unknown; specification terms are conditional on the calibration interval"]
    overdue = fixture_spec(percent_of_reading=.05, absolute_offset=0.)
    overdue.calibration = CalibrationRecord(status="overdue")
    assert overdue.missing_terms() == ["calibration interval exceeded; specification terms are not applicable"]
    assert channel_standard_uncertainty(overdue, 1., unit="A")["status"] == "not_evaluated"


def test_temperature_term_needs_an_observed_ambient_and_applies_beyond_the_band():
    coefficient = TemperatureCoefficient(percent_of_reading_per_C=.01, reference_temperature_C=23., reference_band_C=5.,
                                         source="fixture")
    spec = fixture_spec(percent_of_reading=.05, absolute_offset=.0001, temperature_coefficient=coefficient)
    assert channel_standard_uncertainty(spec, 1., unit="A")["status"] == "not_evaluated"
    inside = channel_standard_uncertainty(spec, 1., unit="A", ambient_C=26.)
    outside = channel_standard_uncertainty(spec, 1., unit="A", ambient_C=33.)
    assert inside["terms"]["temperature"]["standard"] == 0.
    assert outside["terms"]["temperature"]["excess_C"] == pytest.approx(5.)
    assert outside["terms"]["temperature"]["half_width"] == pytest.approx(5 * .0001)
    assert outside["standard"] > inside["standard"]


@pytest.fixture(scope="module")
def mock_run(tmp_path_factory):
    from dcdc_bench.runner import run_mock
    return run_mock(default_plan(), tmp_path_factory.mktemp("uncertainty-mock"))


def test_mock_profile_yields_evaluated_budget_labeled_synthetic(mock_run):
    directory = analyze_run(mock_run)
    budget = json.loads((directory / "uncertainty.json").read_text())
    analysis = json.loads((directory / "analysis.json").read_text())
    assert analysis["uncertainty"] == budget
    assert budget["schema_version"] == SCHEMA_VERSION and budget["status"] in ("evaluated", "partially_evaluated")
    assert budget["metrology"] == "specification-bound only (synthetic example)"
    assert budget["coverage_factor"] == 2 and "95 %" in budget["coverage_factor_note"]
    assert all(channel["status"] == "synthetic_example" and channel["programming_accuracy_consulted"] is False
               and "synthetic" in channel["source"] for channel in budget["channels"].values())
    loaded = [p for p in analysis["points"] if p["qualification"] == "valid" and p["iout_target_A"] > 0]
    assert loaded
    for point in loaded:
        result = budget["points"][point["point_id"]]
        assert result["status"] == "evaluated" and point["metrology"] == "specification-bound only (synthetic example)"
        efficiency = result["quantities"]["efficiency_pct"]
        assert efficiency["label"].endswith(" percentage points") and efficiency["value"] == point["efficiency_pct"]
        assert result["quantities"]["loss_W"]["unit"] == "W"
        for quantity in CHANNELS:
            assert result["channels"][quantity]["repeatability"]["n"] == point["accepted_cycle_count"]
    for point in analysis["points"]:
        if point["qualification"] == "valid" and point["iout_target_A"] == 0:
            assert "no external load" in budget["points"][point["point_id"]]["quantities"]["efficiency_pct"]["reasons"][0]
        if point["qualification"] != "valid":
            assert budget["points"][point["point_id"]]["status"] == "not_evaluated"
    plan = default_plan()
    run = json.loads((mock_run / "run.json").read_text())
    samples = [json.loads(line) for line in (mock_run / "raw/samples.jsonl").read_text().splitlines() if line]
    from dcdc_bench.domain import Plan
    model = build_report_model(Plan.model_validate_json((mock_run / "plan.json").read_text()), run, analysis, samples)
    efficiency_figure = next(figure for figure in model.figures if figure.id == "fig-efficiency")
    assert (efficiency_figure.lower_key, efficiency_figure.upper_key) == ("efficiency_pct_lower", "efficiency_pct_upper")
    assert "not validated 95 % confidence intervals" in efficiency_figure.caption
    loss_figure = next(figure for figure in model.figures if figure.id == "fig-loss")
    assert loss_figure.lower_key == "loss_W_lower"
    banded = [p for p in model.points if "efficiency_pct_lower" in p]
    assert {p["point_id"] for p in banded} == {p["point_id"] for p in loaded}
    assert all(p["efficiency_pct_lower"] < p["efficiency_pct"] < p["efficiency_pct_upper"] for p in banded)
    assert all(p["efficiency_pct_uncertainty_label"].startswith("± ") and "(k = 2)" in p["efficiency_pct_uncertainty_label"]
               for p in banded)
    peak = next(metric for metric in model.metrics if metric.id == "highest-observed-efficiency")
    assert peak.uncertainty["expanded"] is not None and peak.uncertainty["unit"] == "percentage points"
    assert peak.uncertainty["status"] == "specification-bound only (synthetic example)"
    assert any("percentage points" in line and "k = 2" in line for line in model.summary)
    assert model.uncertainty["status"] == budget["status"] and set(model.uncertainty["evaluated_point_ids"]) >= {p["point_id"] for p in loaded}
    assert any("synthetic example" in line and "not validated 95 %" in line for line in model.limitations)
    assert not any("Uncertainty is unquantified" in line for line in model.limitations)
