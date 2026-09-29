"""Paired-run comparison (M4): CMP-01 pairing, CMP-02 prose, UNC-03 covariance, integrity and read-only sources.

Every fixture run here is synthetic and labeled SYNTHETIC. No instrument is
opened; run folders are written directly through the evidence store.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import shutil
from pathlib import Path

import pytest

from dcdc_bench.analysis import FORMULA_VERSION, analyze_run
from dcdc_bench.cli import main
from dcdc_bench.comparison import (ComparisonReportModel, PairingPolicy, build_comparison_model, compare_runs,
                                   load_run, pair_points)
from dcdc_bench.domain import RawSample
from dcdc_bench.planning import build_plan
from dcdc_bench.reporting.comparison import comparison_body, plot_comparison_figure, write_comparison
from dcdc_bench.services import default_plan
from dcdc_bench.storage import RunStore

# CMP-02: comparison prose never attributes, ranks technology or declares a difference real.
FORBIDDEN = ("because", "due to", "caused", "causes", "technology", "cooler", "superior", "inferior",
             "better", "worse", "outperform", "significant", "is real", "proves", "confirms", "universally")


def make_run(root: Path, name: str, *, tests, efficiency, vout=lambda vin, iout: 12. - .02 * iout, readback=True) -> Path:
    """Finalized synthetic run folder with one analysis revision; mirrors the store layout.

    ``readback=True`` keeps the mock bench's synthetic readback specifications, so
    ``analyze_run`` writes an evaluated budget through ``evaluate_run_budget``;
    ``readback=False`` removes them, so the budget is honestly ``not_evaluated``.
    """
    initial = default_plan()
    dut, bench, recipe = initial.dut, initial.bench, initial.recipe
    if not readback:
        for binding in bench.measurements.values():
            binding.readback_specification = None
    dut.profile_id = "synthetic-comparison-fixture"
    dut.identity.model = "Synthetic comparison fixture"
    dut.ratings.origin = "synthetic_regression_fixture"
    recipe.dut_profile_id = dut.profile_id
    template = recipe.tests[0]
    recipe.tests = [template.model_copy(update={"id": test_id, "input_voltage_targets_V": list(vins),
                                                "output_current_targets_A": list(loads)})
                    for test_id, vins, loads in tests]
    plan = build_plan(dut, bench, recipe)
    run_id = f"synthetic-{name}"
    run = {"schema_version": "1.0", "run_id": run_id, "data_source": "simulated", "execution_status": "completed",
           "lifecycle_state": "FINALIZED", "created_utc": f"2026-01-0{1 if name.endswith('a') else 2}T00:00:00+00:00",
           "duration_s": 100., "plan_hash": plan.plan_hash, "scenario": "normal", "points": [],
           "shutdown": {role: {"state": "OFF", "verified": True} for role in ("source", "load")},
           "model": {"version": "fixture", "seed": 1, "parameters": {}},
           "clock": {"mode": "virtual", "note": "synthetic fixture; virtual timestamps"},
           "software": {"fixture": name}, "measurement_boundary": bench.measurement_boundary,
           "real_hardware_opened": False, "errors": [], "method": {"fixture": name}, "instrument_identities": {}}
    samples = []
    for n, point in enumerate(plan.points):
        cycles = []
        eta = efficiency(point.vin_target_V, point.iout_target_A)
        vout_value = vout(point.vin_target_V, point.iout_target_A)
        iin = vout_value * point.iout_target_A / (eta / 100.) / point.vin_target_V
        for index in range(recipe.acquisition.minimum_complete_cycles):
            cycle = f"{point.point_id}-c{index}"
            cycles.append(cycle)
            values = {"Vin_V": point.vin_target_V, "Iin_A": iin, "Vout_V": vout_value, "Iout_A": point.iout_target_A}
            for offset, (quantity, value) in enumerate(values.items()):
                binding = bench.measurements[quantity]
                started = n * 100. + index + offset * .002
                samples.append(RawSample(sample_id=f"{cycle}-{quantity}", run_id=run_id, test_id=point.test_id,
                    point_id=point.point_id, channel_id=binding.instrument_id + ":" + quantity,
                    instrument_id=binding.instrument_id, quantity=quantity, value=value, unit=binding.unit,
                    location=binding.location, query_start_utc="2026-01-01T00:00:00Z",
                    query_end_utc="2026-01-01T00:00:00.001Z", query_start_monotonic_s=started,
                    query_end_monotonic_s=started + .001, acquisition_cycle_id=cycle, phase="acquiring",
                    acquisition_settings={"source_mode": "CV", "load_compliance": True}).model_dump())
        run["points"].append({"point_id": point.point_id, "qualification": "valid", "reason": "synthetic fixture",
                              "acquisition_cycle_ids": cycles})
    path = root / run_id
    store = RunStore(path)
    snapshot = plan.model_dump(mode="json")
    store.initialize({"dut": snapshot["dut"], "bench": snapshot["bench"], "recipe": snapshot["recipe"]}, snapshot, run)
    with (path / "raw/samples.jsonl").open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, separators=(",", ":"), allow_nan=False) + "\n")
    store.finalize(run)
    analyze_run(path)
    return path


def tree_hashes(run_dir: Path) -> dict[str, str]:
    return {str(path.relative_to(run_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(run_dir.rglob("*")) if path.is_file()}


def all_text(model: ComparisonReportModel, body: str) -> str:
    parts = [*model.summary, *model.prose, *model.limitations, body,
             *(f.caption + " " + f.title for f in model.figures),
             *(m.label + " " + m.conditions + " " + m.formula for m in model.metrics),
             *(row["statement"] for row in model.availability), *(row["reason"] for row in model.unpaired)]
    return "\n".join(parts).lower()


def eta_a(vin, iout):
    return 80. + 10. * iout + (vin - 24.) * .1


def eta_b(vin, iout):
    return 81. + 9. * iout + (vin - 24.) * .1


TESTS_A = [("steady-load", [16., 24.], [.25, .5]), ("hold", [24.], [.5, .5, .5])]
# Run B lists its loads in a different order and adds loads/conditions run A lacks,
# so joining by array position would pair the wrong conditions.
TESTS_B = [("steady-load", [18., 24.], [.5, .25, .75, .375]), ("hold", [24.], [.5])]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Two runs whose analyses carry evaluated budgets (the mock bench declares synthetic readback specifications)."""
    root = tmp_path_factory.mktemp("comparison-fixture")
    return make_run(root, "run-a", tests=TESTS_A, efficiency=eta_a), make_run(root, "run-b", tests=TESTS_B, efficiency=eta_b)


@pytest.fixture(scope="module")
def bare_runs(tmp_path_factory):
    """The same two runs on a bench without readback specifications: the budget is honestly not evaluated."""
    root = tmp_path_factory.mktemp("comparison-bare")
    return (make_run(root, "run-a", tests=TESTS_A, efficiency=eta_a, readback=False),
            make_run(root, "run-b", tests=TESTS_B, efficiency=eta_b, readback=False))


@pytest.fixture(scope="module")
def model(bare_runs):
    a, b = bare_runs
    return build_comparison_model([load_run(a, None, "A"), load_run(b, None, "B")], PairingPolicy())


def test_cmp01_pairs_by_qualified_conditions_not_array_index(model):
    pairs = {(p["test_id"], p["vin_target_V"], p["iout_target_A"]): p for p in model.pairs}
    assert set(pairs) == {("steady-load", 24., .25), ("steady-load", 24., .5)}
    # Run A p0003 is (24 V, 0.25 A); run B's third point is (18 V, 0.75 A). Conditions, not positions, decide.
    assert (pairs[("steady-load", 24., .25)]["point_id_a"], pairs[("steady-load", 24., .25)]["point_id_b"]) == ("A:p0003", "B:p0006")
    assert (pairs[("steady-load", 24., .5)]["point_id_a"], pairs[("steady-load", 24., .5)]["point_id_b"]) == ("A:p0004", "B:p0005")
    for pair in model.pairs:
        assert pair["delta_eta_pp"] == pytest.approx(eta_b(24., pair["iout_target_A"]) - eta_a(24., pair["iout_target_A"]), abs=1e-9)
        assert pair["delta_eta_pp"] == pair["eta_b_pct"] - pair["eta_a_pct"]
        assert pair["delta_loss_W"] == pair["loss_b_W"] - pair["loss_a_W"]
        assert pair["delta_Vout_V"] == pair["Vout_b_V"] - pair["Vout_a_V"]
    largest = next(m for m in model.metrics if m.id == "largest-efficiency-difference")
    assert largest.value == pytest.approx(.75, abs=1e-9) and largest.unit == "percentage points"
    assert "0.25 A requested load" in largest.conditions
    assert model.evidence_label == "SYNTHETIC"
    assert all(run.evidence_label == "SYNTHETIC" for run in model.runs)


def test_cmp01_unpaired_16v_versus_18v_availability_and_repeated_conditions(model):
    statements = [row["statement"] for row in model.availability]
    assert "16 V requested input: run A only (2 valid points)" in statements
    assert "18 V requested input: run B only (4 valid points)" in statements
    assert any(s.startswith("steady-load at 24 V:") and "0.375 A, 0.75 A only in run B" in s for s in statements)
    assert any("3 repeated observations at 0.5 A in run A (not paired)" in s for s in statements)
    unpaired = {row["point_id"]: row for row in model.unpaired}
    assert {"A:p0001", "A:p0002"} <= set(unpaired) and all("no valid run B point" in unpaired[p]["reason"] for p in ("A:p0001", "A:p0002"))
    assert all("repeated condition in run A" in unpaired[f"A:p000{n}"]["reason"] for n in (5, 6, 7))
    assert "repeated or ambiguous" in unpaired["B:p0009"]["reason"]
    assert all(row["eligible"] for row in model.unpaired)
    assert {p["point_id"] for p in model.pairs}.isdisjoint(unpaired)
    unpaired_table = next(t for t in model.tables if t.id == "table-unpaired")
    assert set(unpaired_table.point_ids) == set(unpaired)
    assert any("16 V requested input: run A only" in text for text in model.summary)
    assert any("18 V requested input: run B only" in text for text in model.summary)


def test_cmp01_interpolation_is_off_by_default_and_labeled_when_enabled(runs):
    a, b = runs
    assert PairingPolicy().interpolation_enabled is False
    loaded = [load_run(a, None, "A"), load_run(b, None, "B")]
    default = build_comparison_model(loaded, PairingPolicy())
    assert default.interpolated == [] and "fig-delta-efficiency-interpolated" not in {f.id for f in default.figures}
    assert "INTERPOLATED" not in comparison_body(default.model_dump())
    enabled = build_comparison_model(loaded, PairingPolicy(interpolation_enabled=True))
    assert len(enabled.interpolated) == 1
    row = enabled.interpolated[0]
    assert (row["run_label"], row["interpolated_run"], row["iout_target_A"]) == ("B", "A", .375)
    assert row["bracket_point_ids"] == ["A:p0003", "A:p0004"] and row["qualification"] == "interpolated"
    assert row["eta_interpolated_pct"] == pytest.approx((eta_a(24., .25) + eta_a(24., .5)) / 2, abs=1e-9)
    assert row["delta_eta_pp"] == pytest.approx(eta_b(24., .375) - row["eta_interpolated_pct"], abs=1e-9)
    assert "INTERPOLATED" in row["label"] and "not a measurement" in row["label"]
    # Measured-point claims are unchanged: same pairs, same metrics, interpolated ids never referenced by a metric.
    assert enabled.pairs == default.pairs
    assert [m.value for m in enabled.metrics] == [m.value for m in default.metrics]
    assert all(row["point_id"] not in m.point_ids for m in enabled.metrics)
    figure = next(f for f in enabled.figures if f.id == "fig-delta-efficiency-interpolated")
    assert "INTERPOLATED" in figure.title and "not measurements" in figure.caption
    body = comparison_body(enabled.model_dump())
    assert "INTERPOLATED comparisons (not measured)" in body and "interp-B-0001" in body


def test_cmp02_prose_states_counts_and_extremes_without_causal_claims(model):
    body = comparison_body(model.model_dump())
    text = all_text(model, body)
    for word in FORBIDDEN:
        assert word not in text, word
    joined = " ".join(model.summary)
    assert "2 paired measured points" in joined
    assert "Largest observed efficiency difference (run B minus run A): +0.75 percentage points" in joined
    assert "24 V requested input, 0.25 A requested load (steady-load)" in joined
    assert "Difference resolvability: not evaluated" in joined
    assert "fields differ between the runs" in joined and "recipe.tests" in joined
    assert "no observed difference is attributed to a mechanism, component or design choice" in joined
    assert "SYNTHETIC" in body and "synthetic-run-a" in body and "synthetic-run-b" in body
    assert "| Pair | Test |" in body and "pair-B-0001" in body
    assert "## Availability of unpaired points" in body and "## Disclosures: recorded fields that differ" in body
    assert "No author interpretation has been supplied" in body


def test_unc02_missing_budget_means_not_evaluated_without_bands(model):
    assert model.difference_uncertainty["status"] == "not evaluated"
    assert model.difference_uncertainty["budgets"] == {"A": "not_evaluated", "B": "not_evaluated"}
    assert model.difference_uncertainty["assumption"]["independence_assumed"] is False
    for pair in model.pairs:
        assert {entry["status"] for entry in pair["uncertainty"].values()} == {"not evaluated"}
        assert not any("u_delta" in entry for entry in pair["uncertainty"].values())
    for metric in model.metrics:
        assert metric.uncertainty["expanded"] is None and metric.uncertainty["status"] in ("not evaluated", "unquantified")
    assert any("no bands are drawn" in text for text in model.limitations)


def test_unc03_evaluated_budgets_resolve_the_pair_difference_and_covariance_changes_it(runs):
    """M2: the pair difference reads the budget evaluate_run_budget actually writes (per-point quantities/channels)."""
    a, b = runs
    loaded = [load_run(a, None, "A"), load_run(b, None, "B")]
    assert loaded[0].analysis["formula_version"] == FORMULA_VERSION
    budgets = [run.analysis["uncertainty"] for run in loaded]
    assert all(budget["schema_version"] == "uncertainty-budget-1.0" and budget["status"] == "evaluated" for budget in budgets)
    assert all("standard" not in budget for budget in budgets), "no flat table exists; nothing may read one"
    independent = build_comparison_model(loaded, PairingPolicy())
    assert independent.difference_uncertainty["status"] == "evaluated"
    assert independent.difference_uncertainty["budgets"] == {"A": "evaluated", "B": "evaluated"}
    assert independent.difference_uncertainty["assumption"]["independence_assumed"] is True
    assert "assumption, not a result" in independent.difference_uncertainty["assumption"]["statement"]
    pair = independent.pairs[0]
    point_a, point_b = budgets[0]["points"][pair["source_point_id_a"]], budgets[1]["points"][pair["source_point_id_b"]]
    for quantity, table in (("efficiency_pct", "quantities"), ("loss_W", "quantities"), ("Vout_V", "channels")):
        u_a, u_b = point_a[table][quantity]["standard"], point_b[table][quantity]["standard"]
        entry = pair["uncertainty"][quantity]
        assert entry["status"] == "evaluated" and (entry["u_a"], entry["u_b"]) == (u_a, u_b) and u_a > 0 and u_b > 0
        assert entry["u_delta"] == pytest.approx(math.sqrt(u_a ** 2 + u_b ** 2))
        assert entry["covariance"] == 0 and entry["covariance_basis"] == "independence assumed (cov = 0)"
        assert entry["k"] == 2 and entry["expanded"] == pytest.approx(2 * entry["u_delta"])
    largest = next(m for m in independent.metrics if m.id == "largest-efficiency-difference")
    assert largest.uncertainty["status"] == "evaluated" and largest.uncertainty["standard"] > 0
    assert "Independence between the two runs is assumed" in " ".join(independent.summary)
    assert not any("no bands are drawn" in text for text in independent.limitations)
    u_a, u_b = point_a["quantities"]["efficiency_pct"]["standard"], point_b["quantities"]["efficiency_pct"]["standard"]
    # One supplied covariance applies to every pair, so it must be admissible (|cov| <= u_a*u_b) for all of them.
    products = [budgets[0]["points"][p["source_point_id_a"]]["quantities"]["efficiency_pct"]["standard"]
                * budgets[1]["points"][p["source_point_id_b"]]["quantities"]["efficiency_pct"]["standard"]
                for p in independent.pairs]
    cov = min(products)
    shared = build_comparison_model(loaded, PairingPolicy(),
                                    covariance={"quantities": {"efficiency_pct": cov}, "note": "shared error fixture"})
    entry = shared.pairs[0]["uncertainty"]["efficiency_pct"]
    assert entry["covariance_basis"] == "supplied" and entry["covariance"] == pytest.approx(cov) and cov > 0
    assert entry["u_delta"] == pytest.approx(math.sqrt(u_a ** 2 + u_b ** 2 - 2 * cov))
    assert entry["u_delta"] < independent.pairs[0]["uncertainty"]["efficiency_pct"]["u_delta"]
    assert shared.difference_uncertainty["assumption"]["independence_assumed"] is False
    assert shared.pairs[0]["uncertainty"]["loss_W"]["covariance_basis"] == "independence assumed (cov = 0)"
    with pytest.raises(ValueError, match="Invalid covariance"):
        build_comparison_model(loaded, PairingPolicy(), covariance={"quantities": {"efficiency_pct": 2 * max(products)}})
    text = all_text(shared, comparison_body(shared.model_dump()))
    for word in FORBIDDEN:
        assert word not in text, word


def test_pairing_requires_same_boundary_and_never_joins_by_position():
    def point(label, pid, test_id, vin, iout, eta, qualification="valid"):
        return {"point_id": f"{label}:{pid}", "source_point_id": pid, "run_label": label, "test_id": test_id,
                "test_type": "steady_state_load_sweep", "vin_target_V": vin, "iout_target_A": iout,
                "qualification": qualification, "efficiency_pct": eta, "loss_W": 1., "Vout_V": 12., "Vin_V": vin,
                "Iout_A": iout, "evidence_label": "SYNTHETIC"}
    a = [point("A", "p1", "load", 16., .5, 80.), point("A", "p2", "load", 24., .5, 82.)]
    b = [point("B", "p1", "load", 24., .5, 83.), point("B", "p2", "load", 18., .5, 81., qualification="inconclusive")]
    pairs, unpaired = pair_points(a, b, PairingPolicy(), same_boundary=True, label_a="A", label_b="B")
    assert [(p["point_id_a"], p["point_id_b"]) for p in pairs] == [("A:p2", "B:p1")]
    reasons = {row["point_id"]: row["reason"] for row in unpaired}
    assert "no valid run B point at 16 V, 0.5 A (load)" in reasons["A:p1"]
    assert reasons["B:p2"].startswith("qualification inconclusive")
    pairs, unpaired = pair_points(a, b, PairingPolicy(), same_boundary=False, label_a="A", label_b="B")
    assert pairs == [] and all("boundary differs" in row["reason"] for row in unpaired if row["eligible"])
    # A wide tolerance that makes two run-B points candidates is ambiguous, not silently resolved.
    b2 = [point("B", "p1", "load", 24., .5, 83.), point("B", "p3", "load", 24., .52, 83.5)]
    pairs, unpaired = pair_points(a, b2, PairingPolicy(requested_load_tolerance_A=.05), same_boundary=True, label_a="A", label_b="B")
    assert pairs == [] and any("ambiguous: 2 run B points" in row["reason"] for row in unpaired)


def test_figures_use_condition_color_run_style_and_zero_reference(model):
    dumped = model.model_dump()
    assert dumped["figures"][0]["id"] == "fig-delta-efficiency"
    delta = plot_comparison_figure(dumped, dumped["figures"][0], 1)
    zero_lines = [shape for shape in delta.layout.shapes if shape.y0 == 0 and shape.y1 == 0 and shape.type == "line"]
    assert len(zero_lines) == 1
    low, high = delta.layout.yaxis.range
    assert low == pytest.approx(-high) and high > max(abs(p["delta_eta_pp"]) for p in model.pairs)
    assert all(isinstance(trace.marker.color, str) for trace in delta.data), "sign is never color-coded"
    assert list(delta.data[0].y) == [p["delta_eta_pp"] for p in model.pairs]
    overlay = plot_comparison_figure(dumped, next(f for f in dumped["figures"] if f["id"] == "fig-cmp-efficiency"), 4)
    by_name = {trace.name: trace for trace in overlay.data}
    a_24 = by_name["Run A (SYNTHETIC) · steady-load · 24 V"]
    b_24 = by_name["Run B (SYNTHETIC) · steady-load · 24 V"]
    assert a_24.line.color == b_24.line.color
    assert (a_24.line.dash, a_24.marker.symbol) != (b_24.line.dash, b_24.marker.symbol)
    assert by_name["Run A (SYNTHETIC) · steady-load · 16 V"].line.color != a_24.line.color
    footer = delta.layout.annotations[-1].text
    for expected in ("SYNTHETIC", "synthetic-run-a", "synthetic-run-b", "fig-delta-efficiency", model.comparison_id):
        assert expected in footer


def test_integrity_and_identity_failures_are_rejected(runs, tmp_path):
    a, b = runs
    damaged = tmp_path / "damaged"
    shutil.copytree(b, damaged)
    with (damaged / "raw/samples.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="integrity mismatch"):
        load_run(damaged, None, "B")
    bare = tmp_path / "bare"
    shutil.copytree(b, bare)
    shutil.rmtree(bare / "analysis")
    with pytest.raises(ValueError, match="no analysis revision"):
        load_run(bare, None, "B")
    foreign = tmp_path / "foreign"
    shutil.copytree(b, foreign)
    foreign_id = sorted((a / "analysis").glob("a-*"))[0].name
    shutil.copytree(a / "analysis" / foreign_id, foreign / "analysis" / foreign_id)
    with pytest.raises(ValueError, match="run_id does not match"):
        load_run(foreign, foreign_id, "B")
    with pytest.raises(ValueError, match="not found"):
        load_run(b, "a-000000000000", "B")
    with pytest.raises(ValueError, match="not a finalized run folder"):
        load_run(tmp_path / "missing", None, "B")
    with pytest.raises(ValueError, match="different acquisition"):
        build_comparison_model([load_run(a, None, "A"), load_run(a, None, "B")], PairingPolicy())


def test_cli_compare_writes_outputs_and_leaves_source_runs_untouched(bare_runs, tmp_path, capsys):
    a, b = bare_runs
    before = tree_hashes(a), tree_hashes(b)
    out = tmp_path / "comparison"
    assert main(["compare", str(a), str(b), "--out", str(out)]) == 0
    assert capsys.readouterr().out.strip() == str(out.resolve())
    assert (tree_hashes(a), tree_hashes(b)) == before
    for name in ("comparison_model.json", "comparison.md", "comparison_manifest.json", "exports/paired.csv",
                 "exports/unpaired.csv", "exports/run_points.csv", "exports/comparison.meta.json",
                 "figures/fig-delta-efficiency.plotly.json"):
        assert (out / name).is_file(), name
    written = ComparisonReportModel.model_validate_json((out / "comparison_model.json").read_text())
    assert written.kind == "comparison" and len(written.pairs) == 2 and written.pairing.interpolation_enabled is False
    paired = list(csv.DictReader(io.StringIO((out / "exports/paired.csv").read_text(encoding="utf-8", newline=""))))
    assert len(paired) == 2 and len(set(paired[0])) == len(paired[0])
    assert {row["evidence_type_a"] for row in paired} == {"SYNTHETIC"}
    assert all(row["u_delta_eta_pp"] == "" for row in paired), "no fabricated uncertainty"
    assert float(paired[0]["delta_eta_pp"]) == float(paired[0]["eta_b_pct"]) - float(paired[0]["eta_a_pct"])
    meta = json.loads((out / "exports/comparison.meta.json").read_text())
    assert meta["evidence_type"] == "SYNTHETIC" and meta["difference_uncertainty"]["status"] == "not evaluated"
    assert meta["interpolation"] == {"enabled": False, "rows": 0, "note": meta["interpolation"]["note"]}
    manifest = json.loads((out / "comparison_manifest.json").read_text())
    assert manifest["source_runs_modified"] is False and manifest["status"] == "success"
    assert "SYNTHETIC" in (out / "comparison.md").read_text(encoding="utf-8")
    assert main(["compare", str(a), str(b), "--out", str(out)]) == 2
    assert "already holds a comparison" in capsys.readouterr().err
    assert main(["compare", str(a), str(b), "--out", str(out), "--overwrite", "--interpolate", "--tolerance-iout", "0.002"]) == 0
    written = ComparisonReportModel.model_validate_json((out / "comparison_model.json").read_text())
    assert written.pairing.interpolation_enabled is True and written.pairing.requested_load_tolerance_A == .002
    assert (out / "exports/interpolated.csv").is_file() and len(written.interpolated) == 1
    assert (tree_hashes(a), tree_hashes(b)) == before


def test_write_comparison_rejects_non_comparison_models_and_invalid_references(model, tmp_path):
    dumped = model.model_dump()
    dumped["kind"] = "characterization"
    with pytest.raises(ValueError, match="comparison report model"):
        write_comparison(dumped, tmp_path / "x")
    broken = model.model_dump()
    broken["figures"][0]["series"][0]["point_ids"].append("missing")
    with pytest.raises(ValueError, match="missing point"):
        write_comparison(broken, tmp_path / "y")
    assert not (tmp_path / "y").exists()
    with pytest.raises(ValueError, match="Missing figure point"):
        ComparisonReportModel.model_validate(broken)
