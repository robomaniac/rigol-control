"""Mock worker → preserved evidence → analysis → issued report-model checks.

Numerical review fixtures here are synthetic and separate from the first DUT
profile. Browser and PDF rendering have their own end-to-end checks.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from statistics import mean

import pytest

from dcdc_bench.analysis import FORMULA_VERSION, analyze_evidence, analyze_run, build_report_model, points_csv
from dcdc_bench.cli import main
from dcdc_bench.domain import Plan, RawSample
from dcdc_bench.planning import build_plan
from dcdc_bench.runner import run_mock
from dcdc_bench.services import default_plan, execute, report_run
from dcdc_bench.storage import verify_integrity


def _read(run_dir: Path):
    plan = Plan.model_validate_json((run_dir / "plan.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    samples = [json.loads(line) for line in (run_dir / "raw/samples.jsonl").read_text().splitlines()]
    return plan, run, samples


def _hashes(run_dir: Path) -> dict[str, str]:
    manifest = json.loads((run_dir / "integrity.json").read_text())
    return {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in manifest["files"]}


@pytest.fixture(scope="module")
def normal_run(tmp_path_factory):
    return run_mock(default_plan(), tmp_path_factory.mktemp("pipeline-normal"))


def test_DATA01_worker_raw_analysis_table_export_and_figure_reference_identical_values(normal_run):
    plan, run, samples = _read(normal_run)
    assert run["execution_status"] == "completed"
    assert run["real_hardware_opened"] is False
    directory = analyze_run(normal_run)
    analysis = json.loads((directory / "analysis.json").read_text())
    model = build_report_model(plan, run, analysis, samples)
    csv_points = {p["point_id"]: p for p in csv.DictReader(io.StringIO(points_csv(model.points)))}
    assert sum(p["qualification"] == "valid" for p in model.points) == 19
    for point in model.points:
        if point["qualification"] != "valid":
            assert point["efficiency_pct"] is None
            continue
        accepted = [s for s in samples if s["sample_id"] in point["accepted_sample_ids"]]
        assert len(accepted) == 4 * point["accepted_cycle_count"]
        for quantity in ("Vin_V", "Iin_A", "Vout_V", "Iout_A"):
            assert point[quantity] == mean(s["value"] for s in accepted if s["quantity"] == quantity)
        assert point["Pin_W"] == point["Vin_V"] * point["Iin_A"]
        if point["iout_target_A"] == 0:
            assert point["efficiency_pct"] is None
            assert csv_points[point["point_id"]]["efficiency_pct"] == ""
            assert point["Pout_W"] is None and point["loss_W"] is None
            assert csv_points[point["point_id"]]["Pout_W"] == ""
            assert csv_points[point["point_id"]]["loss_W"] == ""
        else:
            assert point["Pout_W"] == point["Vout_V"] * point["Iout_A"]
            assert point["loss_W"] == point["Pin_W"] - point["Pout_W"]
            assert point["efficiency_pct"] == 100 * point["Pout_W"] / point["Pin_W"]
            assert float(csv_points[point["point_id"]]["efficiency_pct"]) == point["efficiency_pct"]
        assert all(float(csv_points[point["point_id"]][key]) == point[key]
                   for key in ("Vin_V", "Iin_A", "Vout_V", "Iout_A", "Pin_W", "Pout_W", "loss_W")
                   if point[key] is not None)
    assert {p["point_id"] for p in model.points} == set(model.tables[0].point_ids)
    assert all(series.point_ids for figure in model.figures for series in figure.series)
    assert model.provenance["mock_model"]["seed"] == run["model"]["seed"]
    assert model.provenance["mock_model"]["version"] == run["model"]["version"]


def test_DATA07_new_analysis_and_report_revisions_preserve_acquisition(normal_run, monkeypatch):
    import dcdc_bench.reporting
    original = _hashes(normal_run)
    first = analyze_run(normal_run)
    first_bytes = (first / "analysis.json").read_bytes()
    assert analyze_run(normal_run) == first
    second = analyze_run(normal_run, version=FORMULA_VERSION + "+regression-review")
    assert second != first
    assert (first / "analysis.json").read_bytes() == first_bytes
    a, b = (json.loads((path / "analysis.json").read_text()) for path in (first, second))
    assert a["evidence_hash"] == b["evidence_hash"]
    assert a["analysis_id"] != b["analysis_id"]
    captured = []
    # This isolates revision orchestration. Full renderer behavior is verified
    # by browser/PDF tests; this stub does not pretend to create a document.
    monkeypatch.setattr(dcdc_bench.reporting, "render_report", lambda model, output, **kw: captured.append(model))
    revision1 = report_run(normal_run, formats=("html",), analysis_dir=first)
    old_model = (revision1 / "report_model.json").read_bytes()
    revision2 = report_run(normal_run, formats=("html",), analysis_dir=second)
    assert revision1 != revision2
    assert (revision1 / "report_model.json").read_bytes() == old_model
    assert captured[0]["analysis_id"] == a["analysis_id"]
    assert captured[1]["analysis_id"] == b["analysis_id"]
    assert _hashes(normal_run) == original
    verify_integrity(normal_run)


def _numeric_fixture(vins=(12., 60.), missing=()):
    """Independent 5 V synthetic fixture with traceable complete raw cycles."""
    initial = default_plan()
    dut, bench, recipe = initial.dut, initial.bench, initial.recipe
    dut.profile_id = "synthetic-regulation-fixture"
    dut.identity.model = "Synthetic 5 V regression fixture"
    dut.ratings.origin = "synthetic_regression_fixture"
    dut.ratings.input_voltage_min_V = min(vins)
    dut.ratings.input_voltage_max_V = max(vins)
    dut.ratings.output_voltage_nominal_V = 5.
    dut.ratings.output_power_rated_W = 20.
    recipe.dut_profile_id = dut.profile_id
    recipe.tests[0].input_voltage_targets_V = list(vins)
    recipe.tests[0].output_current_targets_A = [.5]
    plan = build_plan(dut, bench, recipe)
    run = {"run_id": "synthetic-regulation-fixture", "execution_status": "completed", "points": []}
    samples = []
    for n, point in enumerate(plan.points):
        cycles = []
        if point.vin_target_V not in missing:
            for index in range(recipe.acquisition.minimum_complete_cycles):
                cycle = f"{point.point_id}-c{index}"
                cycles.append(cycle)
                values = {"Vin_V": point.vin_target_V, "Iin_A": 3. / point.vin_target_V,
                          "Vout_V": 4.9995 if n == 0 else 5.0186, "Iout_A": .5}
                for offset, (quantity, value) in enumerate(values.items()):
                    binding = bench.measurements[quantity]
                    started = n * 100. + index * 1. + offset * .002
                    samples.append(RawSample(sample_id=f"{cycle}-{quantity}", run_id=run["run_id"],
                        test_id=point.test_id, point_id=point.point_id, channel_id=binding.instrument_id+quantity,
                        instrument_id=binding.instrument_id, quantity=quantity, value=value, unit=binding.unit,
                        location=binding.location, query_start_utc="2026-01-01T00:00:00Z",
                        query_end_utc="2026-01-01T00:00:00.001Z", query_start_monotonic_s=started,
                        query_end_monotonic_s=started+.001, acquisition_cycle_id=cycle, phase="acquiring",
                        acquisition_settings={"source_mode": "CV", "load_compliance": True}).model_dump())
        run["points"].append({"point_id": point.point_id,
                              "qualification": "not-run" if point.vin_target_V in missing else "valid",
                              "reason": "synthetic fixture", "acquisition_cycle_ids": cycles})
    analysis = analyze_evidence(plan, run, samples)
    analysis["analysis_id"] = "synthetic-fixture-analysis"
    return plan, run, samples, analysis


def test_DATA02_review_fixture_flows_into_actual_report_metric_caption_and_summary():
    plan, run, samples, analysis = _numeric_fixture()
    model = build_report_model(plan, run, analysis, samples)
    metric = next(m for m in model.metrics if m.id.startswith("line-span-"))
    assert metric.value == pytest.approx(.382, abs=1e-12)
    assert "12–60 V" in metric.conditions
    assert any("0.382%" in sentence and "12–60 V" in sentence for sentence in model.summary)
    assert all("12–60 V" in f.caption for f in model.figures)
    assert "0.29%" not in model.model_dump_json()
    assert metric.point_ids == [p.point_id for p in plan.points]


def test_DATA03_missing_first_requested_point_does_not_claim_full_covered_range():
    plan, run, samples, analysis = _numeric_fixture(vins=(16., 18., 24.), missing=(16.,))
    model = build_report_model(plan, run, analysis, samples)
    assert model.points[0]["qualification"] == "not-run"
    assert model.points[0]["Vout_V"] is None
    assert all("18–24 V" in figure.caption and "16–24 V" not in figure.caption for figure in model.figures)
    assert not any(m.id.startswith("line-span-") for m in model.metrics)
    # The requested 16 V series remains explicit, preserving the gap/coverage.
    assert model.figures[0].series[0].point_ids == [plan.points[0].point_id]


def test_CORE07_second_output_voltage_and_alternate_source_complete_worker_to_report(tmp_path):
    initial = default_plan()
    dut, bench, recipe = initial.dut, initial.bench, initial.recipe
    dut.profile_id = "synthetic-other-dut"
    dut.identity.model = "Synthetic 5 V board"
    dut.ratings.origin = "synthetic_regression_fixture"
    dut.ratings.output_voltage_nominal_V = 5.
    dut.ratings.output_current_rated_A = 2.
    dut.ratings.output_power_rated_W = 10.
    bench.source.instrument_id = "synthetic-alternate-source"
    bench.source.max_current_A = 3.
    bench.source.max_power_W = 90.
    for quantity in ("Vin_V", "Iin_A"):
        bench.measurements[quantity].instrument_id = bench.source.instrument_id
    recipe.dut_profile_id = dut.profile_id
    recipe.tests[0].input_voltage_targets_V = [12.]
    recipe.tests[0].output_current_targets_A = [0., .1, .5]
    path = run_mock(build_plan(dut, bench, recipe), tmp_path)
    plan, run, samples = _read(path)
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    model = build_report_model(plan, run, analysis, samples)
    assert run["execution_status"] == "completed"
    assert all(p["qualification"] == "valid" for p in model.points)
    assert all(4.9 < p["Vout_V"] < 5.1 for p in model.points)
    assert model.title.startswith("Synthetic 5 V board")
    assert "12T12-4A" not in model.model_dump_json()
    assert any("10 W" in text for text in model.limitations)
    assert all(s["instrument_id"] == "synthetic-alternate-source" for s in samples if s["quantity"] in ("Vin_V", "Iin_A"))


@pytest.mark.parametrize("corruption", ["nonexistent-cycle", "wrong-instrument", "source-cc", "settling-cycle", "bad-status"])
def test_analysis_rejects_a_worker_claim_of_validity_without_matching_evidence(corruption):
    plan, run, samples, _ = _numeric_fixture()
    if corruption == "nonexistent-cycle":
        run["points"][0]["acquisition_cycle_ids"].append("unpreserved-cycle")
    elif corruption == "wrong-instrument":
        samples[0]["instrument_id"] = "undeclared-source"
    elif corruption == "source-cc":
        samples[0]["acquisition_settings"]["source_mode"] = "CC"
    elif corruption == "settling-cycle":
        samples[0]["phase"] = "settling"
    else:
        samples[0]["status"] = "stale"
    with pytest.raises(ValueError):
        analyze_evidence(plan, run, samples)


def test_render_failure_does_not_rewrite_completed_acquisition(tmp_path, monkeypatch):
    import dcdc_bench.reporting
    from dcdc_bench.reporting.renderer import ReportRenderError
    def fail(model, output, **kwargs):
        raise ReportRenderError("injected renderer failure")
    monkeypatch.setattr(dcdc_bench.reporting, "render_report", fail)
    plan = default_plan()
    plan.recipe.tests[0].input_voltage_targets_V = [24.]
    plan.recipe.tests[0].output_current_targets_A = [.1]
    plan = build_plan(plan.dut, plan.bench, plan.recipe)
    with pytest.raises(ReportRenderError, match="injected"):
        execute(plan, tmp_path, formats=("html",))
    path = next(p for p in tmp_path.iterdir() if p.is_dir())
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed"
    assert run["shutdown"]["source"]["state"] == "OFF"
    assert run["shutdown"]["load"]["state"] == "OFF"
    assert (path / "reports/r0001/report_model.json").exists()
    assert not (path / "reports/r0001/report.html").exists()
    assert not (path / "reports/r0001/report.pdf").exists()
    verify_integrity(path)


def test_real_cli_arm_and_future_commands_fail_without_touching_hardware(tmp_path, capsys):
    missing = str(tmp_path / "never-read-plan.json")
    assert main(["run", "--plan", missing, "--mode", "real"]) == 2
    assert "mock execution only" in capsys.readouterr().err
    assert main(["run", "--plan", missing, "--arm"]) == 2
    assert "not implemented or approved" in capsys.readouterr().err
    assert main(["compare"]) == 2
    assert "deferred" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())
