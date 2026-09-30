"""Numerical review defects from the brief are synthetic regression fixtures."""
import csv
import io
import json
import math

import pytest

from dcdc_bench.analysis import (CSV_FIELDS, IMPLAUSIBLE_RATIO_FLAG, READBACK_LABEL, READBACK_METRIC_PREFIX,
    ReportModel, analyze_evidence, build_report_model, coverage_by_test,
    current_only_efficiency_uncertainty, dc_metrics, difference_standard_uncertainty, flag_reason,
    points_csv, regulation_span, transition_bracket)
from dcdc_bench.domain import Plan
from dcdc_bench.runner import run_mock
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


def test_no_load_readback_offset_sign_is_evidence_not_an_unexpected_sign():
    # With the load input OFF, the electronic load's zero-current readback can be
    # slightly negative; that offset is recorded, not judged as output current.
    negative_offset = dc_metrics(dict(Vin_V=24., Iin_A=.01, Vout_V=12.1, Iout_A=-.0004), 12., no_load=True)
    assert "unexpected_sign" not in negative_offset["metric_flags"]
    assert negative_offset["Pin_W"] == pytest.approx(.24) and negative_offset["efficiency_pct"] is None
    assert negative_offset["Pout_W"] is None and negative_offset["loss_W"] is None
    # A loaded observation with negative output current is still flagged.
    loaded = dc_metrics(dict(Vin_V=24., Iin_A=.01, Vout_V=12.1, Iout_A=-.0004), 12.)
    assert "unexpected_sign" in loaded["metric_flags"]
    # Other no-load sign faults remain flagged.
    assert "unexpected_sign" in dc_metrics(dict(Vin_V=24., Iin_A=-.01, Vout_V=12.1, Iout_A=0.), 12., no_load=True)["metric_flags"]


# --- DATA-06 continued: implausible ratios travel to the report as flagged evidence ---

PASS_THROUGH_P0002 = dict(Vin_V=12.01, Iin_A=.08835, Vout_V=11.9867925, Iout_A=.099394875)


def test_data06_flag_reason_states_computed_ratio_powers_and_current_disagreement():
    # The owner's pass-through check (supply wired straight to the load): the
    # load current readback exceeds the source current readback by 11 mA.
    derived = dc_metrics(PASS_THROUGH_P0002, 12.)
    assert derived["metric_flags"] == [IMPLAUSIBLE_RATIO_FLAG]
    assert flag_reason(PASS_THROUGH_P0002, derived, derived["metric_flags"]) == (
        "Implausible power ratio: computed efficiency 112.3 % exceeds 100 % (output power 1.191 W > input power 1.061 W); "
        "readings preserved, point not qualified. Input and output current readbacks differ by +11.0 mA.")
    # Nothing is clamped: the stored ratio and loss keep their impossible values.
    assert derived["efficiency_pct"] == pytest.approx(112.28388, abs=1e-4) and derived["loss_W"] < 0
    negative = dict(Vin_V=12., Iin_A=.1, Vout_V=12., Iout_A=-.02)
    derived = dc_metrics(negative, 12.)
    text = flag_reason(negative, derived, derived["metric_flags"])
    assert text.startswith("Implausible power ratio: computed efficiency -20.0 % is below 0 %")
    assert "Unexpected sign: Iout_A = -0.02 at a loaded point" in text


@pytest.fixture(scope="module")
def mock_run(tmp_path_factory):
    return run_mock(default_plan(), tmp_path_factory.mktemp("analysis-flags"))


def _evidence(run_dir):
    plan = Plan.model_validate_json((run_dir / "plan.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    samples = [json.loads(line) for line in (run_dir / "raw/samples.jsonl").read_text().splitlines() if line]
    return plan, run, samples


def test_data06_demoted_point_carries_computed_reason_and_flags_into_the_report(mock_run):
    plan, run, samples = _evidence(mock_run)
    requests = {p.point_id: p for p in plan.points}
    target = next(p["point_id"] for p in run["points"]
                  if p["qualification"] == "valid" and requests[p["point_id"]].iout_target_A > 0)
    worker_reason = next(p["reason"] for p in run["points"] if p["point_id"] == target)
    # Inflate the load's current readback for one loaded point so Pout > Pin.
    for sample in samples:
        if sample["point_id"] == target and sample["quantity"] == "Iout_A" and sample["value"] is not None:
            sample["value"] *= 1.3
    analysis = analyze_evidence(plan, run, samples)
    point = next(p for p in analysis["points"] if p["point_id"] == target)
    assert point["qualification"] == "inconclusive"
    assert point["quality_flags"] == [IMPLAUSIBLE_RATIO_FLAG]
    assert point["reason"].startswith("Implausible power ratio: computed efficiency ")
    assert "exceeds 100 %" in point["reason"] and "readings preserved, point not qualified" in point["reason"]
    assert "Input and output current readbacks differ by +" in point["reason"]
    assert point["reason"] != worker_reason
    assert point["efficiency_pct"] > 100 and point["loss_W"] < 0, "never clamped (brief 9.1)"
    assert all(p["quality_flags"] == [] for p in analysis["points"] if p["point_id"] != target)
    # points.csv carries the flag list as one column, next to the qualification.
    rows = {r["point_id"]: r for r in csv.DictReader(io.StringIO(points_csv(analysis["points"])))}
    assert CSV_FIELDS.index("quality_flags") == CSV_FIELDS.index("qualification") + 1
    assert rows[target]["quality_flags"] == IMPLAUSIBLE_RATIO_FLAG
    assert all(r["quality_flags"] == "" for pid, r in rows.items() if pid != target)

    analysis["analysis_id"] = "test-only"
    model = build_report_model(plan, run, analysis, samples)
    reported = next(p for p in model.points if p["point_id"] == target)
    assert reported["quality_flags"] == [IMPLAUSIBLE_RATIO_FLAG]
    assert all("quality_flags" in p for p in model.points)
    loaded = sum(1 for p in model.points if p["iout_target_A"] != 0)
    assert model.summary[1].startswith(f"1 of {loaded} loaded points show a physically impossible power ratio "
                                       "(output power above input power) and are not qualified; the readings are "
                                       "preserved in the table and explorer. The input and output current readbacks differ by +")
    assert "instrument readback disagreement at the declared boundary rather than converter behaviour" in model.summary[1]
    assert any(line.startswith(f"Points flagged {IMPLAUSIBLE_RATIO_FLAG} ({target})") for line in model.limitations)
    for fid in ("fig-efficiency", "fig-loss", "fig-voltage"):
        figure = next(f for f in model.figures if f.id == fid)
        assert f"Open markers are 1 point(s) flagged {IMPLAUSIBLE_RATIO_FLAG}" in figure.caption
        assert target in [pid for s in figure.series for pid in s.point_ids], "flagged points stay in the figure"
    peak = next(m for m in model.metrics if m.id == "highest-observed-efficiency")
    assert peak.point_ids != [target] and peak.value <= 100
    assert not any(m.id.startswith(READBACK_METRIC_PREFIX) for m in model.metrics), "no cross-check for a real converter"


def test_data06_report_without_flagged_points_adds_no_flag_prose():
    model = model_fixture()
    assert all(p["quality_flags"] == [] for p in model.points)
    assert not any("physically impossible" in text for text in model.summary)
    assert not any("Open markers" in figure.caption for figure in model.figures)
    assert not any(IMPLAUSIBLE_RATIO_FLAG in line for line in model.limitations)


def _pass_through_fixture():
    plan = default_plan()
    plan.dut.construction.topology = "none (direct connection)"
    points = []
    for request in plan.points:
        p = request.model_dump()
        iout = request.iout_target_A
        # Load reads 11 mA above the source at every loaded point; 20 mV drop along the leads.
        p.update(qualification="valid", Vin_V=request.vin_target_V, Vout_V=request.vin_target_V - .02,
                 Iout_A=iout, Iin_A=iout - .011 if iout else .001, quality_flags=[])
        p.update(dc_metrics(p, 12., no_load=iout == 0))
        if p["metric_flags"]:
            p.update(qualification="inconclusive", quality_flags=list(p["metric_flags"]))
        points.append(p)
    analysis = dict(points=points, coverage=coverage_by_test(points), analysis_id="fixture-only",
                    formula_version="test", aggregation="synthetic fixture", sign_convention="positive input/output")
    return plan, build_report_model(plan, {"run_id": "pass-through-fixture", "execution_status": "completed"}, analysis, [])


def test_pass_through_topology_emits_readback_cross_check_metrics_and_sentence():
    plan, model = _pass_through_fixture()
    loaded = [p for p in model.points if p["iout_target_A"] != 0]
    assert loaded and all(p["qualification"] == "inconclusive" for p in loaded), "Iout > Iin at 12 V is implausible"
    cross = [m for m in model.metrics if m.id.startswith(READBACK_METRIC_PREFIX)]
    assert len(cross) == 2 * len(loaded) + 6
    assert all(m.label.startswith(READBACK_LABEL) for m in cross)
    by_id = {m.id: m for m in cross}
    for point in loaded:
        current = by_id[f"{READBACK_METRIC_PREFIX}current-difference-{point['point_id']}"]
        assert current.value == pytest.approx(.011) and current.unit == "A"
        assert current.formula.startswith("Iout_A − Iin_A") and "not a correction" in current.formula
        assert current.point_ids == [point["point_id"]] and current.figure_ids == []
        drop = by_id[f"{READBACK_METRIC_PREFIX}voltage-drop-{point['point_id']}"]
        assert drop.value == pytest.approx(.02) and drop.unit == "V" and drop.formula.startswith("Vin_V − Vout_V")
    for statistic in ("mean", "min", "max"):
        assert by_id[f"{READBACK_METRIC_PREFIX}current-difference-{statistic}"].value == pytest.approx(.011)
        assert by_id[f"{READBACK_METRIC_PREFIX}voltage-drop-{statistic}"].value == pytest.approx(.02)
        assert set(by_id[f"{READBACK_METRIC_PREFIX}voltage-drop-{statistic}"].point_ids) == {p["point_id"] for p in loaded}
    sentence = next(text for text in model.summary if text.startswith(READBACK_LABEL + ":"))
    assert f"across {len(loaded)} loaded points the load current readback minus the source current readback is +11.0 mA on average (+11.0 to +11.0 mA)" in sentence
    assert "source-terminal voltage minus the load-terminal voltage is 20.0 mV on average (20.0 to 20.0 mV)" in sentence
    assert "no stored value is corrected" in sentence
    reference = next(item for item in model.summary_evidence if item.paragraph_index == model.summary.index(sentence))
    assert set(reference.metric_ids) == {f"{READBACK_METRIC_PREFIX}current-difference-mean", f"{READBACK_METRIC_PREFIX}voltage-drop-mean"}
    assert any("not a calibration" in line and "corrects no stored value" in line for line in model.limitations)
    # The flagged paragraph precedes it and states the consistent-sign disagreement.
    flagged = model.summary[1]
    assert flagged.startswith(f"{len(loaded)} of {len(loaded)} loaded points show a physically impossible power ratio")
    assert "differ by +11.0 mA to +11.0 mA" in flagged
    # Stored readings are untouched by the cross-check.
    assert all(p["Iout_A"] - p["Iin_A"] == pytest.approx(.011) for p in loaded)


def test_unknown_topology_emits_no_readback_cross_check():
    model = model_fixture()
    assert default_plan().dut.construction.topology == "unknown"
    assert not any(m.id.startswith(READBACK_METRIC_PREFIX) for m in model.metrics)
    assert not any(text.startswith(READBACK_LABEL) for text in model.summary)


def test_inconsistent_disagreement_sign_omits_the_readback_sentence():
    plan = default_plan()
    points = []
    for index, request in enumerate(plan.points):
        p = request.model_dump()
        iout = request.iout_target_A
        # Every loaded point reads Iout above Iin by 20 %, so all are flagged with one sign.
        p.update(qualification="valid", Vin_V=request.vin_target_V, Vout_V=request.vin_target_V,
                 Iout_A=iout, Iin_A=iout * .8 if iout else .001, quality_flags=[])
        p.update(dc_metrics(p, 12., no_load=iout == 0))
        if p["metric_flags"]:
            p.update(qualification="inconclusive", quality_flags=list(p["metric_flags"]))
        points.append(p)
    analysis = dict(points=points, coverage=coverage_by_test(points), analysis_id="fixture-only",
                    formula_version="test", aggregation="synthetic fixture", sign_convention="positive input/output")
    run = {"run_id": "mixed-fixture", "execution_status": "completed"}
    model = build_report_model(plan, run, analysis, [])
    flagged = [p for p in model.points if IMPLAUSIBLE_RATIO_FLAG in p["quality_flags"]]
    assert flagged and all(p["efficiency_pct"] > 100 for p in flagged)
    assert "current readbacks differ by +" in model.summary[1]
    # Reverse the sign on one flagged point (Iin above Iout, but a negative Vin makes Pin negative... keep
    # Pin positive): use a larger Vout so Pout > Pin while Iout < Iin. Signs now disagree.
    victim = flagged[0]["point_id"]
    for p in points:
        if p["point_id"] == victim:
            p.update(Iout_A=p["Iin_A"] * .9, Vout_V=p["Vin_V"] * 1.5)
            p.update(dc_metrics(p, 12.))
            assert IMPLAUSIBLE_RATIO_FLAG in p["metric_flags"]
            p.update(qualification="inconclusive", quality_flags=list(p["metric_flags"]))
    model = build_report_model(plan, run, analysis, [])
    paragraph = model.summary[1]
    assert paragraph.startswith(f"{len(flagged)} of ") and "(output power above input power)" in paragraph
    assert "current readbacks differ by" not in paragraph, "an inconsistent sign earns no readback sentence"
