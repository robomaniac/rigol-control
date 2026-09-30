"""Test-only records exercise measured labels without opening any hardware."""
import json

import pytest

from dcdc_bench.analysis import (analyze_evidence, analyze_run, build_report_model,
                                 coverage_by_test, dc_metrics)
from dcdc_bench.reporting.renderer import _body
from dcdc_bench.services import default_plan
from dcdc_bench.storage import RunStore


def evidence_fixture(measured):
    plan = default_plan()
    run = {"run_id": "test-only-evidence-fixture", "execution_status": "completed"}
    if measured:
        plan.bench.mode = "real"
        plan.recipe.execution_mode = "real"
        plan.bench.notes = []
        plan.bench.measurement_boundary = "source-to-load-terminal path including input and output wires"
        plan.bench.measurements["Vout_V"].location = "load_terminals"
        plan.bench.measurements["Iout_A"].location = "load_input"
        plan.bench.load.remote_sense_required = False
        for device in (plan.bench.source, plan.bench.load):
            device.reported_identity = "Test-only instrument identity"
        run.update(data_source="measured", real_hardware_opened=True, clock={"mode": "wall"},
                   measurement_boundary=plan.bench.measurement_boundary,
                   metrology_limitations=["Device conversion freshness is not independently verified."])
    else:
        # Backward-compatible old fixture records have no data_source field.
        run.update(clock={"mode": "virtual"}, model={"seed": 1})
    points = []
    for request in plan.points:
        point = request.model_dump()
        point.update(qualification="valid", Vin_V=request.vin_target_V,
                     Iin_A=.3, Vout_V=12., Iout_A=request.iout_target_A)
        point.update(dc_metrics(point, 12., no_load=request.iout_target_A == 0))
        points.append(point)
    analysis = dict(points=points, coverage=coverage_by_test(points), analysis_id="test-only",
                    formula_version="test-only", aggregation="Test-only numerical fixture",
                    sign_convention="positive input and output")
    return plan, run, analysis


def test_measured_report_uses_measured_labels_and_actual_boundary():
    plan, run, analysis = evidence_fixture(True)
    model = build_report_model(plan, run, analysis, [])
    assert model.evidence_label == "MEASURED"
    assert all(metric.qualification == "measured observation" for metric in model.metrics)
    assert all(figure.caption.startswith("MEASURED.") for figure in model.figures)
    assert "qualified measured DC results" in model.summary[0]
    assert "synthetic" not in " ".join(model.summary + model.limitations).lower()
    assert "virtual-clock" not in " ".join(model.limitations).lower()
    assert "mock_model" not in model.provenance
    assert "load terminals" in " ".join(model.limitations)
    assert "senses DUT output" not in " ".join(model.limitations)
    assert run["metrology_limitations"][0] in model.limitations
    assert model.boundary == run["measurement_boundary"]
    body = _body(model.model_dump())
    assert "**Qualification:** measured observations" in body
    assert "synthetic observations" not in body


def test_legacy_mock_report_stays_synthetic_and_records_virtual_clock():
    plan, run, analysis = evidence_fixture(False)
    model = build_report_model(plan, run, analysis, [])
    assert model.evidence_label == "SYNTHETIC"
    assert all(metric.qualification == "synthetic observation" for metric in model.metrics)
    assert all(figure.caption.startswith("SYNTHETIC.") for figure in model.figures)
    assert model.provenance["mock_model"] == {"seed": 1}
    assert any("Virtual-clock" in line for line in model.limitations)
    assert "**Qualification:** synthetic observations" in _body(model.model_dump())


def test_legacy_recipe_mode_does_not_reclassify_evidence():
    """The bench decides real vs simulated; a recipe's legacy execution_mode is planning metadata only."""
    plan, run, analysis = evidence_fixture(True)
    plan.recipe.execution_mode = "mock"
    assert build_report_model(plan, run, analysis, []).evidence_label == "MEASURED"
    plan.recipe.execution_mode = None
    assert build_report_model(plan, run, analysis, []).evidence_label == "MEASURED"


@pytest.mark.parametrize("change", ["simulated-as-real", "measured-as-mock", "missing-real-label",
                                   "hardware-opened", "virtual-measurement", "unknown-label"])
def test_evidence_mode_disagreement_blocks_analysis_and_report(change):
    plan, run, analysis = evidence_fixture(True)
    if change == "simulated-as-real":
        run["data_source"] = "simulated"
    elif change == "measured-as-mock":
        plan.bench.mode = "mock"
    elif change == "missing-real-label":
        del run["data_source"]
    elif change == "hardware-opened":
        run["real_hardware_opened"] = False
    elif change == "virtual-measurement":
        run["clock"]["mode"] = "virtual"
    else:
        run["data_source"] = "estimated"
    with pytest.raises(ValueError):
        analyze_evidence(plan, run, [])
    with pytest.raises(ValueError):
        build_report_model(plan, run, analysis, [])


@pytest.mark.parametrize("measured", [False, True])
def test_analysis_csv_metadata_preserves_evidence_type(tmp_path, measured):
    plan, run, _ = evidence_fixture(measured)
    run_dir = tmp_path / "test-only-evidence"
    store = RunStore(run_dir)
    store.initialize({}, plan.model_dump(), run)
    store.finalize(run)
    directory = analyze_run(run_dir)
    expected = "MEASURED" if measured else "SYNTHETIC"
    analysis = json.loads((directory / "analysis.json").read_text())
    metadata = json.loads((directory / "points.metadata.json").read_text())
    assert analysis["evidence_label"] == metadata["evidence_label"] == expected
    assert analysis["boundary"] == metadata["boundary"] == plan.bench.measurement_boundary


def test_load_off_current_offset_does_not_become_output_power_or_loss():
    result = dc_metrics(dict(Vin_V=24., Iin_A=.018, Vout_V=12.04, Iout_A=.011096),
                        12., no_load=True)
    assert result["Pin_W"] == pytest.approx(.432)
    assert result["Pout_W"] is None
    assert result["loss_W"] is None
    assert result["efficiency_pct"] is None
    assert "load-off current" in result["output_power_reason"]
    assert result["loss_reason"]
