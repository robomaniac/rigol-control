"""Numerical review defects from the brief are synthetic regression fixtures."""
import csv
import io
import math

import pytest

from dcdc_bench.analysis import (CSV_FIELDS, ReportModel, build_report_model, coverage_by_test,
    current_only_efficiency_uncertainty, dc_metrics, difference_standard_uncertainty,
    points_csv, regulation_span, transition_bracket)
from dcdc_bench.services import default_plan


def test_data01_arithmetic_retains_precision():
    result = dc_metrics({"Vin_V": 24.001, "Iin_A": .3, "Vout_V": 11.99, "Iout_A": .51}, 12)
    assert result["Pin_W"] == 24.001*.3
    assert result["Pout_W"] == 11.99*.51
    assert result["loss_W"] == result["Pin_W"]-result["Pout_W"]
    assert result["efficiency_pct"] == 100*result["Pout_W"]/result["Pin_W"]
    assert result["vout_error_pct"] == 100*(11.99-12)/12


def test_data02_line_span_fixture():
    assert regulation_span([5.0186, 4.9995], 5) == pytest.approx(.382)


def test_voltage_error_and_regulation_span_have_distinct_references():
    # Two outputs above nominal can have a small regulation span. Neither
    # quantity locates the input voltage at which regulation is lost.
    result = dc_metrics(dict(Vin_V=24., Iin_A=.1, Vout_V=12.12, Iout_A=.1), 12.)
    assert result['vout_error_pct'] == pytest.approx(1.)
    assert regulation_span([12.12, 12.18], 12.) == pytest.approx(.5)


def test_data04_transition_is_bracket_not_exact():
    bracket = transition_bracket(9.1, 9.0)
    assert bracket["lower_V"] == 9
    assert bracket["upper_V"] == 9.1
    assert bracket["exact_threshold_V"] is None


def test_data05_independent_test_coverage():
    points = [{"test_id": "load", "qualification": "valid"} for _ in range(37)]
    points += [{"test_id": "load", "qualification": "setup-limited"}]*2
    points += [{"test_id": "line", "qualification": "valid"}]*5
    points += [{"test_id": "uvlo", "qualification": "not-run"}]*2
    coverage = coverage_by_test(points)
    assert coverage["load"]["requested"] == 39
    assert coverage["line"]["requested"] == 5
    assert coverage["uvlo"]["not-run"] == 2


def test_data06_no_load_invalid_signs_and_unclamped_ratios():
    no_load = dc_metrics(dict(Vin_V=12., Iin_A=.01, Vout_V=12., Iout_A=0.),12.,no_load=True)
    assert no_load["Pin_W"] == .12 and no_load["efficiency_pct"] is None
    negative = dc_metrics(dict(Vin_V=12.,Iin_A=-.1,Vout_V=12.,Iout_A=.01),12.)
    assert negative["Pin_W"] < 0 and negative["efficiency_pct"] is None
    invalid = dc_metrics(dict(Vin_V=12.,Iin_A=.1,Vout_V=12.,Iout_A=.2),12.)
    assert invalid["efficiency_pct"] == 200
    assert invalid["loss_W"] < 0
    assert "implausible_power_ratio" in invalid["metric_flags"]
    missing = dc_metrics(dict(Vin_V=None,Iin_A=.1,Vout_V=12.,Iout_A=.2),12.)
    assert missing["efficiency_pct"] is None
    with pytest.raises(ValueError):
        dc_metrics(dict(Vin_V=math.nan,Iin_A=.1,Vout_V=12.,Iout_A=.2),12.)


def test_unc01_current_only_regression():
    value = current_only_efficiency_uncertainty(40.24,7.8,30,.0005*7.8+.1,.001*30+.6)
    assert value == pytest.approx(1.155512754,abs=1e-9)


def test_unc03_covariance_changes_difference():
    assert difference_standard_uncertainty(.4,.4,.4*.4) == pytest.approx(0)
    assert difference_standard_uncertainty(.4,.4) == pytest.approx(math.sqrt(.32))
    with pytest.raises(ValueError):
        difference_standard_uncertainty(.4,.4,.2)


def test_unc04_systematic_terms_have_no_sample_count_scaling():
    # Replicating the same observations leaves their means and systematic budget unchanged.
    from statistics import mean
    value = lambda n: current_only_efficiency_uncertainty(40.24,mean([7.8]*n),mean([30]*n),.1039,.63)
    assert value(1) == value(1000)


def model_fixture():
    plan = default_plan()
    points=[]
    for request in plan.points:
        p=request.model_dump()
        p.update(qualification="valid",Vin_V=request.vin_target_V,Iin_A=.3,Vout_V=12.,Iout_A=request.iout_target_A)
        p.update(dc_metrics(p,12,no_load=p["iout_target_A"]==0))
        points.append(p)
    analysis=dict(points=points,coverage=coverage_by_test(points),analysis_id="fixture-only",formula_version="test",
                  aggregation="synthetic fixture",sign_convention="positive input/output")
    return build_report_model(plan,{"run_id":"synthetic-fixture","execution_status":"completed"},analysis,[])


def test_data08_references_and_declared_conditions_validated():
    model=model_fixture()
    data=model.model_dump()
    data["figures"][0]["series"][0]["point_ids"].append("missing")
    with pytest.raises(ValueError,match="Missing figure point"):
        ReportModel.model_validate(data)
    data=model.model_dump()
    data["figures"][0]["series"][0]["vin_target_V"]=60.
    with pytest.raises(ValueError,match="condition"):
        ReportModel.model_validate(data)
    data=model.model_dump()
    data["metrics"][0]["figure_ids"]=["missing-figure"]
    with pytest.raises(ValueError,match="Missing evidence figure"):
        ReportModel.model_validate(data)


def test_unc02_absent_budget_no_fabricated_bands():
    model=model_fixture()
    assert all(m.uncertainty["expanded"] is None for m in model.metrics)
    assert any("unquantified" in line for line in model.limitations)


def test_web06_csv_unique_units_empty_missing_and_escaped_text():
    rows=list(csv.DictReader(io.StringIO(points_csv([dict(point_id='=evil()', reason='a,"b"\nnext', efficiency_pct=None, loss_W=-.5)]))))
    assert len(CSV_FIELDS) == len(set(CSV_FIELDS))
    assert rows[0]["point_id"] == "'=evil()"
    assert rows[0]["reason"] == 'a,"b"\nnext'
    assert rows[0]["efficiency_pct"] == ""
    assert rows[0]["loss_W"] == "-0.5"


def test_data03_caption_is_covered_range_not_assumed_first_point():
    model=model_fixture()
    voltage = next(figure for figure in model.figures if figure.id == 'fig-voltage')
    assert (voltage.title, voltage.x_key, voltage.y_key) == ('Load Regulation', 'Iout_A', 'Vout_V')
    assert voltage.y_label == 'Output Voltage (V)'
    assert 'Percent deviation from nominal is reported separately' in voltage.caption
    assert 'no dropout threshold was measured' in voltage.caption
    for metric in model.metrics:
        if metric.id.startswith("line-span"):
            assert "12–30 V" in metric.conditions
            assert "9–36" not in metric.conditions
