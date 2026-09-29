"""Selected reports must bind analysis and raw evidence from the same run.

Small stored acquisitions exercise the public reporting service without a
worker, instrument transport, browser, or static renderer.
"""
import csv
import io
import json

import pytest

from dcdc_bench.analysis import analyze_run, points_csv
from dcdc_bench.domain import RawSample
from dcdc_bench.planning import build_plan
from dcdc_bench.services import default_plan, report_run
from dcdc_bench.storage import RunStore, atomic_json


@pytest.fixture
def stored_run(tmp_path):
    initial = default_plan()
    initial.recipe.tests[0].input_voltage_targets_V = [24.]
    initial.recipe.tests[0].output_current_targets_A = [.1, .2]
    initial.recipe.acquisition.minimum_complete_cycles = 1
    plan = build_plan(initial.dut, initial.bench, initial.recipe)

    def create(name, input_current=.1):
        run = {"run_id": name, "execution_status": "completed", "points": [],
               "data_source": "simulated", "real_hardware_opened": False}
        store = RunStore(tmp_path / name)
        store.initialize({}, plan.model_dump(), run)
        for index, point in enumerate(plan.points):
            cycle = f"{point.point_id}-cycle-1"
            run["points"].append({"point_id": point.point_id, "qualification": "valid",
                                  "acquisition_cycle_ids": [cycle]})
            values = {"Vin_V": 24., "Iin_A": input_current + index * .1,
                      "Vout_V": 12., "Iout_A": point.iout_target_A}
            for offset, (quantity, value) in enumerate(values.items()):
                binding = plan.bench.measurements[quantity]
                start = index + offset * .002
                sample = RawSample(
                    sample_id=f"{cycle}-{quantity}", run_id=name,
                    test_id=point.test_id, point_id=point.point_id,
                    channel_id=binding.instrument_id + quantity,
                    instrument_id=binding.instrument_id, quantity=quantity,
                    value=value, unit=binding.unit, location=binding.location,
                    query_start_utc="2026-01-01T00:00:00Z",
                    query_end_utc="2026-01-01T00:00:00.001Z",
                    query_start_monotonic_s=start, query_end_monotonic_s=start + .001,
                    acquisition_cycle_id=cycle, phase="acquiring",
                    acquisition_settings={"source_mode": "CV", "load_compliance": True},
                )
                store.append("samples", sample.model_dump())
        store.finalize(run)
        return store.path, analyze_run(store.path)

    return create


@pytest.fixture
def rendered(monkeypatch):
    import dcdc_bench.reporting
    models = []
    monkeypatch.setattr(dcdc_bench.reporting, "render_report",
                        lambda model, output, **kwargs: models.append(model))
    return models


def _assert_rejected(run_dir, analysis_dir, rendered, message):
    with pytest.raises(ValueError, match=message):
        report_run(run_dir, analysis_dir=analysis_dir, formats=("html",))
    assert not (run_dir / "reports").exists()
    assert rendered == []


def test_same_plan_different_run_analysis_cannot_mix_metrics_with_selected_raw(stored_run, rendered):
    run_a, analysis_a = stored_run("run-a", input_current=.1)
    run_b, analysis_b = stored_run("run-b", input_current=.12)
    a = json.loads((analysis_a / "analysis.json").read_text())
    b = json.loads((analysis_b / "analysis.json").read_text())
    assert (run_a / "plan.json").read_bytes() == (run_b / "plan.json").read_bytes()
    assert [point["point_id"] for point in a["points"]] == [point["point_id"] for point in b["points"]]
    assert a["points"][0]["efficiency_pct"] != b["points"][0]["efficiency_pct"]
    _assert_rejected(run_a, analysis_b, rendered, "run_id")


def test_explicit_analysis_still_checks_raw_evidence_integrity(stored_run, rendered):
    run_dir, analysis_dir = stored_run("raw-tampered")
    raw = run_dir / "raw/samples.jsonl"
    with raw.open("a") as handle:
        handle.write("\n")
    _assert_rejected(run_dir, analysis_dir, rendered, "acquisition integrity mismatch")


@pytest.mark.parametrize("field,value,message", [
    ("evidence_hash", "0" * 64, "evidence_hash"),
    ("analysis_id", "a-unrelated", "identifier"),
    ("formula_version", "", "formula_version"),
])
def test_selected_analysis_provenance_is_required(stored_run, rendered, field, value, message):
    run_dir, analysis_dir = stored_run("provenance")
    path = analysis_dir / "analysis.json"
    analysis = json.loads(path.read_text())
    analysis[field] = value
    atomic_json(path, analysis)
    _assert_rejected(run_dir, analysis_dir, rendered, message)


@pytest.mark.parametrize("field,value,message", [
    ("run_id", "another-run", "different run"),
    ("analysis_id", "another-analysis", "different run"),
    ("test_id", "another-test", "conditions"),
    ("vin_target_V", 30., "conditions"),
    ("iout_target_A", .75, "conditions"),
    ("accepted_sample_ids", ["unpreserved-sample"], "sample references"),
    ("acquisition_cycle_ids", ["unpreserved-cycle"], "cycles"),
])
def test_analysis_point_identity_conditions_and_evidence_refs_are_checked(
        stored_run, rendered, field, value, message):
    run_dir, analysis_dir = stored_run("point-identity")
    path = analysis_dir / "analysis.json"
    analysis = json.loads(path.read_text())
    analysis["points"][0][field] = value
    atomic_json(path, analysis)
    _assert_rejected(run_dir, analysis_dir, rendered, message)


@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_analysis_point_set_must_match_requested_plan(stored_run, rendered, change):
    run_dir, analysis_dir = stored_run("point-set")
    path = analysis_dir / "analysis.json"
    analysis = json.loads(path.read_text())
    if change == "missing":
        analysis["points"].pop()
    else:
        analysis["points"].append(analysis["points"][0])
    atomic_json(path, analysis)
    _assert_rejected(run_dir, analysis_dir, rendered, "each requested point exactly once")


def test_matching_selected_analysis_reports_same_values_as_analysis_exports(stored_run, rendered):
    run_dir, analysis_dir = stored_run("matching")
    directory = report_run(run_dir, analysis_dir=analysis_dir, formats=("html",))
    model = rendered[0]
    assert model["run_id"] == "matching"
    assert directory == run_dir / "reports/r0001"
    assert model["metrics"] == json.loads((analysis_dir / "metrics.json").read_text())
    expected_csv = list(csv.DictReader(io.StringIO((analysis_dir / "points.csv").read_text())))
    assert list(csv.DictReader(io.StringIO(points_csv(model["points"])))) == expected_csv


def test_matching_prior_formula_revision_remains_selectable(stored_run, rendered):
    run_dir, _ = stored_run("formula-revision")
    custom_analysis = analyze_run(run_dir, version="reviewed-formula-revision")
    report_run(run_dir, analysis_dir=custom_analysis, formats=("html",))
    assert rendered[0]["provenance"]["formula_version"] == "reviewed-formula-revision"
