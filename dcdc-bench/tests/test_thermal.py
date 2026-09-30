"""Thermal extension with MOCK hardware only (brief section 10, RUN-07). Nothing here opens an instrument."""
from __future__ import annotations

import copy
import json
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

import pytest
from pydantic import ValidationError

from dcdc_bench.adapters import MockBench
from dcdc_bench.analysis import analyze_run, build_report_model
from dcdc_bench.domain import (MOCK_THERMAL_ADAPTER, BenchProfile, DutProfile, MeasurementProvider, RawSample,
                               SensorPlacement, TemperatureSensor, TestRecipe, ThermalSettlingPolicy)
from dcdc_bench.mock_thermal import THERMAL_MODEL_PARAMETERS, MockThermalProvider
from dcdc_bench.planning import build_plan, load_profile
from dcdc_bench.reporting import renderer, validate_report_model
from dcdc_bench.runner import run_mock
from dcdc_bench.services import default_plan
from dcdc_bench.storage import verify_integrity
from dcdc_bench.thermal import (THERMAL_PHASE, annotate_thermal_points, annotations_from_sensors, apply_placements,
                                evaluate_thermal_window, placements_from_annotations, thermal_report_contribution)

PROFILES = Path(__file__).resolve().parents[1] / "profiles"
FORBIDDEN_CAPTION_TERMS = re.compile(r"(?i)junction|thermal resistance|secondary axis|θ|theta")
SPEC_RAW_FIELDS = {"sample_id", "run_id", "test_id", "point_id", "channel_id", "instrument_id", "quantity", "value", "unit",
                   "location", "query_start_utc", "query_end_utc", "query_start_monotonic_s", "query_end_monotonic_s",
                   "device_timestamp", "measurement_range", "resolution", "acquisition_settings", "raw_response", "status",
                   "quality_flags"}


def profiles():
    return (load_profile(PROFILES / "dut/12t12-4a.yaml", DutProfile),
            load_profile(PROFILES / "bench/mock-thermal.yaml", BenchProfile),
            load_profile(PROFILES / "recipes/12t12-4a-thermal-mock.yaml", TestRecipe))


def thermal_plan(currents=(.25, .5), *, slope=2., window=10., minimum=10., timeout=120., poll=2.):
    """Fast virtual-clock variant of the shipped thermal profiles with unique instrument ids."""
    dut, bench, recipe = profiles()
    suffix = uuid.uuid4().hex
    bench.source.instrument_id += suffix
    bench.load.instrument_id += suffix
    thermal_id = "synthetic-thermal" + suffix
    for quantity, binding in bench.measurements.items():
        binding.instrument_id = (bench.source.instrument_id if quantity in ("Vin_V", "Iin_A")
                                 else bench.load.instrument_id if quantity in ("Vout_V", "Iout_A") else thermal_id)
    for sensor in bench.temperature_sensors:
        sensor.instrument_id = thermal_id
    test = recipe.tests[0]
    test.output_current_targets_A = list(currents)
    test.thermal_settling = ThermalSettlingPolicy(surface_quantity="Tcase_C", ambient_quantity="Tambient_C",
        slope_threshold_C_per_min=slope, window_s=window, minimum_observation_s=minimum, timeout_s=timeout,
        minimum_samples=3, poll_interval_s=poll)
    recipe.settling.minimum_dwell_s = .3
    recipe.settling.window_s = .1
    recipe.settling.minimum_fresh_samples = 3
    recipe.settling.timeout_s = 1.
    recipe.acquisition.duration_s = .25
    recipe.acquisition.target_poll_interval_s = .05
    recipe.acquisition.minimum_complete_cycles = 3
    return build_plan(dut, bench, recipe)


def evidence(path: Path):
    verify_integrity(path)
    run = json.loads((path / "run.json").read_text())
    samples = [RawSample.model_validate_json(line).model_dump()
               for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    return run, samples


def analysed(path: Path):
    """Analysis and report model without rendering (no Quarto, Typst or browser)."""
    from dcdc_bench.domain import Plan
    directory = analyze_run(path)
    analysis = json.loads((directory / "analysis.json").read_text())
    plan = Plan.model_validate_json((path / "plan.json").read_text())
    run, samples = evidence(path)
    return plan, run, samples, analysis, build_report_model(plan, run, analysis, samples)


# The shipped plant has a 600 s case time constant (first-order-case-2.0); this virtual-clock fixture passes an
# explicit 20 s so its 2 C/min criterion is met near 50 s with the case at about 92 % of its final rise, instead
# of being flattered by a threshold the slow plant satisfies from the first window.
FAST_THERMAL = {"case_time_constant_s": 20.}


@pytest.fixture(scope="module")
def settled_run(tmp_path_factory):
    plan = thermal_plan()
    path = run_mock(plan, tmp_path_factory.mktemp("thermal-met"), thermal_parameters=FAST_THERMAL)
    return plan, path


# ---------------------------------------------------------------------------
# RUN-07 and provider selection
# ---------------------------------------------------------------------------

def test_RUN07_required_temperature_missing_is_unsupported_and_optional_is_not_invented():
    dut, _, recipe = profiles()
    electrical_bench = load_profile(PROFILES / "bench/mock.yaml", BenchProfile)
    plan = build_plan(dut, electrical_bench, recipe)
    assert plan.points and all(p.status == "unsupported" for p in plan.points)
    for point in plan.points:
        assert "Required measurement Tcase_C is unavailable; no substitute value is permitted" in point.reason
        assert "Thermal settling requires a bound ambient temperature channel Tambient_C" in point.reason
    # An electrical test may list temperature as optional: it runs, and nothing invents the channel.
    recipe.tests[0].thermal_settling = None
    recipe.tests[0].required_quantities = ["Vin_V", "Iin_A", "Vout_V", "Iout_A"]
    recipe.tests[0].optional_quantities = ["Tcase_C", "Tambient_C"]
    plan = build_plan(dut, electrical_bench, recipe)
    assert all(p.feasible for p in plan.points)
    assert not {"Tcase_C", "Tambient_C"} & set(plan.bench.measurements)
    assert plan.bench.temperature_sensors == []


def test_RUN07_real_bench_cannot_bind_the_synthetic_temperature_provider():
    _, bench, _ = profiles()
    data = bench.model_dump(mode="json")
    data["mode"] = "real"
    with pytest.raises(ValidationError, match="cannot be bound in a real bench profile"):
        BenchProfile.model_validate(data)
    real = load_profile(PROFILES / "bench/rigol.example.yaml", BenchProfile)
    assert real.mode == "real" and real.temperature_sensors == []
    with pytest.raises(ValueError, match="only for a mock bench profile"):
        MockThermalProvider.for_bench(real, MockBench(12., 1., .15))
    other = bench.temperature_sensors[0].model_copy(update={"adapter": "some-real-thermocouple-adapter"})
    with pytest.raises(ValueError, match="only mock_thermal sensors"):
        MockThermalProvider([other], MockBench(12., 1., .15))
    # A mock bench declaring a non-synthetic adapter has no provider: planned as unsupported, not modelled.
    dut, mixed, recipe = profiles()
    mixed.temperature_sensors[0].adapter = "some-real-thermocouple-adapter"
    plan = build_plan(dut, mixed, recipe)
    assert all(p.status == "unsupported" and "only the synthetic temperature adapter" in p.reason for p in plan.points)


def test_sensor_metadata_binds_channels_and_refuses_undocumented_internal_labels():
    _, bench, _ = profiles()
    case = bench.temperature_sensors[0]
    assert case.role == "surface" and case.ambient_reference == "Tambient" and case.placement is None
    assert case.measured_surface == "case top, accessible external location"
    for label in ("U1 junction", "junction temperature", "U3 case"):
        with pytest.raises(ValidationError, match="surface_documentation"):
            TemperatureSensor.model_validate({**case.model_dump(mode="json"), "measured_surface": label})
    documented = TemperatureSensor.model_validate({**case.model_dump(mode="json"), "measured_surface": "U1 case (opened enclosure)",
                                                   "surface_documentation": "photo asset abc; enclosure opened: distinct setup"})
    assert documented.surface_documentation
    with pytest.raises(ValidationError, match="does not reference another ambient"):
        TemperatureSensor.model_validate({**bench.temperature_sensors[1].model_dump(mode="json"), "ambient_reference": "Tambient"})
    data = bench.model_dump(mode="json")
    data["temperature_sensors"][0]["ambient_reference"] = "missing-sensor"
    with pytest.raises(ValidationError, match="undeclared ambient sensor"):
        BenchProfile.model_validate(data)
    data = bench.model_dump(mode="json")
    del data["measurements"]["Tambient_C"]
    with pytest.raises(ValidationError, match="no measurement binding"):
        BenchProfile.model_validate(data)
    data = bench.model_dump(mode="json")
    data["measurements"]["Tcase_C"]["unit"] = "K"
    with pytest.raises(ValidationError, match="must use unit 'C'"):
        BenchProfile.model_validate(data)
    with pytest.raises(ValidationError, match="must differ"):
        ThermalSettlingPolicy(surface_quantity="Tcase_C", ambient_quantity="Tcase_C", slope_threshold_C_per_min=.5,
                              window_s=60., minimum_observation_s=60., timeout_s=900.)
    with pytest.raises(ValidationError, match="timeout must allow"):
        ThermalSettlingPolicy(surface_quantity="Tcase_C", ambient_quantity="Tambient_C", slope_threshold_C_per_min=.5,
                              window_s=60., minimum_observation_s=120., timeout_s=90.)


def test_placement_round_trips_the_marker_editor_annotations_schema():
    _, bench, _ = profiles()
    image = "ab" * 32
    annotations = {"schema_version": "1.0", "image_asset_sha256": image,
                   "markers": [{"sensor_id": "Tcase", "x_norm": 0.42, "y_norm": 0.61, "label": "case top marker"},
                               {"sensor_id": "Tambient", "x_norm": 0.0, "y_norm": 1.0, "label": "ambient probe"}]}
    placed = apply_placements(bench.temperature_sensors, copy.deepcopy(annotations))
    assert placed[0].placement == SensorPlacement(image_asset_sha256=image, x_norm=.42, y_norm=.61, label="case top marker")
    assert annotations_from_sensors(placed) == annotations
    assert set(placements_from_annotations(annotations)) == {"Tcase", "Tambient"}
    with pytest.raises(ValueError, match="schema_version"):
        placements_from_annotations({**annotations, "schema_version": "2.0"})
    with pytest.raises(ValidationError):
        placements_from_annotations({**annotations, "markers": [{"sensor_id": "Tcase", "x_norm": 1.5, "y_norm": .5}]})
    with pytest.raises(ValidationError):
        placements_from_annotations({**annotations, "image_asset_sha256": "not-a-sha256"})
    with pytest.raises(ValueError, match="undeclared sensors"):
        apply_placements(bench.temperature_sensors, {**annotations, "markers": [{"sensor_id": "Tghost", "x_norm": .1, "y_norm": .1}]})
    moved = placed[1].model_copy(update={"placement": placed[1].placement.model_copy(update={"image_asset_sha256": "cd" * 32})})
    with pytest.raises(ValueError, match="exactly one original image"):
        annotations_from_sensors([placed[0], moved])
    with pytest.raises(ValueError, match="No sensor carries"):
        annotations_from_sensors(bench.temperature_sensors)


# ---------------------------------------------------------------------------
# Synthetic thermal model and the settling criterion
# ---------------------------------------------------------------------------

def test_mock_thermal_model_is_first_order_tracks_loss_and_is_labelled_synthetic():
    _, bench, _ = profiles()
    plant = MockBench(12., 1., .15, seed=1)
    provider = MockThermalProvider.attach(bench, plant, seed=1)
    assert plant.thermal is provider and isinstance(provider, MeasurementProvider)
    assert provider.identify()["data_source"] == "simulated" and "SYNTHETIC" in provider.identify()["note"]
    plant.configure(24., .5, 0.)
    plant.source_on()
    plant.load_on()
    ambient0, state0 = plant.read("Tambient_C", 0.)
    case0, _ = plant.read("Tcase_C", 0.)
    assert state0.data_source == "synthetic" and state0.role == "ambient"
    assert abs(ambient0 - THERMAL_MODEL_PARAMETERS["ambient_initial_C"]) < .1
    rises = []
    # first-order-case-2.0: tau is 600 s (8 C/W x 75 J/C), so equilibrium takes about an hour of model time.
    assert THERMAL_MODEL_PARAMETERS["case_time_constant_s"] == 600. == (
        THERMAL_MODEL_PARAMETERS["case_rise_per_module_loss_C_per_W"] * THERMAL_MODEL_PARAMETERS["case_heat_capacity_J_per_C"])
    for t in (200., 400., 800., 4000.):
        case, state = plant.read("Tcase_C", t)
        ambient, _ = plant.read("Tambient_C", t)
        rises.append(case - ambient)
        assert state.sensor_id == "Tcase" and state.module_loss_W > 0
    assert rises == sorted(rises) and rises[0] > 0
    loss = plant.state(4000.).module_loss_W
    expected = THERMAL_MODEL_PARAMETERS["case_rise_per_module_loss_C_per_W"] * loss + THERMAL_MODEL_PARAMETERS["case_offset_C"]
    assert rises[-1] == pytest.approx(expected, abs=.15)
    assert rises[0] < .75 * rises[-1]
    plant.load_off()
    plant.source_off()
    cooled, _ = plant.read("Tcase_C", 8000.)
    assert cooled - plant.read("Tambient_C", 8000.)[0] < rises[-1]
    # Electrical readings are unaffected by the attached provider.
    assert plant.read("Vin_V", 0.)[1].source_mode == "OFF"


def test_slope_only_settling_is_honest_only_when_the_recipe_slope_suits_the_plant_time_constant():
    """M4: with tau = 600 s a slope criterion is met while slope x tau of rise remains; the shipped recipe declares
    a slope that leaves about 5 %, and the old 0.5 C/min over 60 s would have declared 'met' at half the rise."""
    _, _, recipe = profiles()
    policy = recipe.tests[0].thermal_settling
    tau = THERMAL_MODEL_PARAMETERS["case_time_constant_s"]
    plant = MockBench(12., 1., .15, seed=1)
    plant.configure(24., .5, 0.)
    plant.source_on(0.)
    plant.load_on(0.)
    final_rise = THERMAL_MODEL_PARAMETERS["case_rise_per_module_loss_C_per_W"] * plant.state(30.).module_loss_W
    remaining_at_criterion = policy.slope_threshold_C_per_min / 60. * tau
    assert remaining_at_criterion / final_rise < .06, (remaining_at_criterion, final_rise)
    assert (.5 / 60. * tau) / final_rise > .45, "the previous 0.5 C/min criterion is not honest on a 600 s plant"
    initial_slope = final_rise / tau * 60.
    time_to_criterion = tau * math.log(initial_slope / policy.slope_threshold_C_per_min)
    assert policy.minimum_observation_s <= time_to_criterion + policy.window_s <= policy.timeout_s
    # The fast virtual-clock fixture is honest for its own tau: 2 C/min on a 20 s plant leaves 2/60*20 = 0.67 C.
    assert (2. / 60. * FAST_THERMAL["case_time_constant_s"]) / final_rise < .1


def test_thermal_window_criterion_met_versus_not_met():
    policy = ThermalSettlingPolicy(surface_quantity="Tcase_C", ambient_quantity="Tambient_C", slope_threshold_C_per_min=.5,
                                   window_s=20., minimum_observation_s=30., timeout_s=120., minimum_samples=4, poll_interval_s=5.)
    flat = [(t, 3.0 + .001 * t) for t in (0., 5., 10., 15., 20.)]
    steep = [(t, .05 * t) for t in (0., 5., 10., 15., 20.)]
    assert evaluate_thermal_window(flat, policy, 40.).met
    assert evaluate_thermal_window(flat, policy, 40.).slope_C_per_min == pytest.approx(.06)
    late = evaluate_thermal_window(flat, policy, 10.)
    assert not late.met and "minimum observation" in late.reason
    short = evaluate_thermal_window(flat[:2], policy, 40.)
    assert not short.met and "insufficient" in short.reason
    narrow = evaluate_thermal_window([(t, 3.) for t in (0., 5., 10., 15.)], policy, 40.)
    assert not narrow.met and "window not yet filled" in narrow.reason
    unsettled = evaluate_thermal_window(steep, policy, 40.)
    assert not unsettled.met and "exceeds" in unsettled.reason and unsettled.slope_C_per_min == pytest.approx(3.)
    assert not evaluate_thermal_window([], policy, 0.).met


# ---------------------------------------------------------------------------
# Acquisition: thermal settling met, and timeout stays inconclusive
# ---------------------------------------------------------------------------

def test_thermal_settling_met_qualifies_points_and_logs_temperature_with_full_raw_fields(settled_run):
    plan, path = settled_run
    run, samples = evidence(path)
    assert run["execution_status"] == "completed", run["errors"]
    assert run["thermal_model"]["data_source"] == "simulated" and run["thermal_model"]["adapter"] == MOCK_THERMAL_ADAPTER
    for point in run["points"]:
        assert point["qualification"] == "valid", point
        settling = point["thermal_settling"]
        assert settling["status"] == "met" and settling["window_samples"] >= 3
        assert abs(settling["final_slope_C_per_min"]) <= 2.
        assert settling["elapsed_s"] >= 10. and point["settling_elapsed_s"] < settling["elapsed_s"]
    thermal_id = plan.bench.measurements["Tcase_C"].instrument_id
    temperatures = [s for s in samples if s["quantity"] in ("Tcase_C", "Tambient_C")]
    assert temperatures and {s["phase"] for s in temperatures} == {"settling", THERMAL_PHASE, "acquiring"}
    for sample in temperatures:
        assert SPEC_RAW_FIELDS <= set(sample)
        assert sample["unit"] == "C" and sample["instrument_id"] == thermal_id and sample["status"] == "ok"
        assert sample["acquisition_cycle_id"].startswith("t")
        assert sample["acquisition_settings"]["data_source"] == "synthetic"
        assert sample["acquisition_settings"]["sensor_id"] in ("Tcase", "Tambient")
        assert sample["raw_response"] and sample["query_end_monotonic_s"] > sample["query_start_monotonic_s"]
    assert {s["location"] for s in temperatures} == {"dut_case_top_external", "ambient_air_near_dut"}
    cycles = defaultdict(list)
    for sample in samples:
        cycles[sample["acquisition_cycle_id"]].append(sample)
    for point in run["points"]:
        for cycle_id in point["acquisition_cycle_ids"]:
            assert {s["quantity"] for s in cycles[cycle_id]} == {"Vin_V", "Iin_A", "Vout_V", "Iout_A"}
    events = [json.loads(line) for line in (path / "raw/events.jsonl").read_text().splitlines()]
    assert any(e["event"] == "point_phase" and e["phase"] == THERMAL_PHASE for e in events)
    assert next(e for e in events if e["event"] == "identified")["identities"]["thermal"]["data_source"] == "simulated"


def test_thermal_settling_timeout_is_inconclusive_and_retains_the_time_series(tmp_path):
    plan = thermal_plan((.5,), slope=.001, window=4., minimum=4., timeout=12., poll=2.)
    path = run_mock(plan, tmp_path)
    run, samples = evidence(path)
    assert run["execution_status"] == "completed", run["errors"]
    point = run["points"][0]
    assert point["qualification"] == "inconclusive"
    assert "thermal settling slope criterion not met before timeout" in point["reason"]
    assert point["acquisition_cycle_ids"] == [] and point["settled"] is True
    assert point["thermal_settling"]["status"] == "timeout" and point["thermal_settling"]["elapsed_s"] >= 12.
    retained = [s for s in samples if s["quantity"] == "Tcase_C" and s["phase"] == THERMAL_PHASE]
    assert len(retained) >= 6 and all(s["status"] == "ok" for s in retained)
    assert not any(s["phase"] == "acquiring" for s in samples)
    plan_loaded, run, samples, analysis, model = analysed(path)
    analysed_point = analysis["points"][0]
    assert analysed_point["qualification"] == "inconclusive" and analysed_point["efficiency_pct"] is None
    assert analysed_point["Tcase_C"] is None and analysed_point["Tcase_rise_C"] is None
    assert analysed_point["Tcase_rise_status"] == "not_evaluated"
    sensor = analysed_point["thermal"]["sensors"][0]
    assert analysed_point["thermal"]["qualification"] == "inconclusive"
    assert "not thermally qualified" in sensor["absolute_reason"]
    assert "not an equilibrium value" in sensor["last_observed_status"] and math.isfinite(sensor["last_observed_C"])
    ids = {f.id for f in model.figures}
    assert "fig-thermal-settling" in ids and not any(f.startswith("fig-temperature") for f in ids)
    assert any("timed out and remain inconclusive" in text and "1 timed out" in text for text in model.summary)
    assert model.thermal["points"][0]["thermal_qualification"] == "inconclusive"


def test_electrical_only_recipe_is_unchanged(tmp_path):
    original = default_plan()
    bench, recipe = original.bench.model_copy(deep=True), original.recipe.model_copy(deep=True)
    suffix = uuid.uuid4().hex
    bench.source.instrument_id += suffix
    bench.load.instrument_id += suffix
    for quantity, binding in bench.measurements.items():
        binding.instrument_id = bench.source.instrument_id if quantity in ("Vin_V", "Iin_A") else bench.load.instrument_id
    recipe.tests[0].input_voltage_targets_V = [24.]
    recipe.tests[0].output_current_targets_A = [.05]
    recipe.settling.minimum_dwell_s = .3
    recipe.settling.window_s = .1
    recipe.settling.minimum_fresh_samples = 3
    recipe.settling.timeout_s = 1.
    recipe.acquisition.duration_s = .25
    recipe.acquisition.target_poll_interval_s = .05
    recipe.acquisition.minimum_complete_cycles = 3
    plan = build_plan(original.dut, bench, recipe)
    assert plan.bench.temperature_sensors == [] and plan.recipe.tests[0].thermal_settling is None
    path = run_mock(plan, tmp_path)
    run, samples = evidence(path)
    assert run["execution_status"] == "completed" and run["points"][0]["qualification"] == "valid"
    assert "thermal_settling" not in run["points"][0] and "thermal_model" not in run
    assert {s["quantity"] for s in samples} == {"Vin_V", "Iin_A", "Vout_V", "Iout_A"}
    _, _, _, analysis, model = analysed(path)
    assert "thermal" not in analysis["points"][0]
    assert model.thermal is None and [f.id for f in model.figures] == ["fig-efficiency", "fig-voltage", "fig-loss"]
    assert not any("SYNTHETIC temperature" in text for text in model.limitations)


# ---------------------------------------------------------------------------
# Analysis and report model
# ---------------------------------------------------------------------------

def test_analysis_reports_absolute_and_rise_above_time_aligned_ambient(settled_run):
    _, path = settled_run
    plan, run, samples, analysis, model = analysed(path)
    points = analysis["points"]
    assert len(points) == 2
    for point in points:
        assert point["qualification"] == "valid" and math.isfinite(point["Tcase_C"]) and math.isfinite(point["Tcase_rise_C"])
        assert point["Tcase_rise_status"] == "evaluated" and point["thermal"]["qualification"] == "settled"
        detail = point["thermal"]["sensors"][0]
        assert detail["data_source"] == "synthetic" and detail["ambient_sensor_id"] == "Tambient"
        assert detail["rise_C"] == pytest.approx(detail["absolute_C"] - detail["ambient_C"])
        assert detail["window_samples"] >= 1 and detail["ambient_window_samples"] >= 1
        assert 20. < detail["ambient_C"] < 26.
    assert points[1]["loss_W"] > points[0]["loss_W"] and points[1]["Tcase_rise_C"] > points[0]["Tcase_rise_C"]
    csv_header = (Path(analyze_run(path)) / "points.csv").read_text().splitlines()[0]
    assert "NaN" not in json.dumps(analysis) and "efficiency_pct" in csv_header


def test_rise_is_not_evaluated_without_an_ambient_reference(settled_run):
    _, path = settled_run
    plan, run, samples, analysis, _ = analysed(path)
    no_ambient = plan.model_copy(deep=True)
    no_ambient.bench.temperature_sensors[0].ambient_reference = None
    grouped = defaultdict(list)
    for sample in samples:
        grouped[sample["point_id"]].append(sample)
    points = copy.deepcopy(analysis["points"])
    annotate_thermal_points(no_ambient, run, grouped, points)
    for point in points:
        assert math.isfinite(point["Tcase_C"])
        assert point["Tcase_rise_C"] is None and point["Tcase_rise_status"] == "not_evaluated"
        detail = point["thermal"]["sensors"][0]
        assert detail["ambient_C"] is None and "room temperature is not assumed" in detail["rise_reason"]
    contribution = thermal_report_contribution(no_ambient, run, points, samples, [], "SYNTHETIC", plan.bench.measurement_boundary)
    assert not any(f.id.startswith("fig-temperature-rise-loss") for f in contribution["figures"])
    assert contribution["metrics"] == []
    assert any("room temperature is not assumed" in text for text in contribution["limitations"])


def test_report_model_keeps_temperature_on_separate_figures_with_honest_captions(settled_run):
    _, path = settled_run
    plan, run, samples, analysis, model = analysed(path)
    dumped = model.model_dump(mode="json")
    validate_report_model(copy.deepcopy(dumped))
    figures = {f.id: f for f in model.figures}
    assert {"fig-efficiency", "fig-voltage", "fig-loss", "fig-temperature-tcase",
            "fig-temperature-rise-loss-tcase", "fig-thermal-settling"} <= set(figures)
    temperature = figures["fig-temperature-tcase"]
    rise = figures["fig-temperature-rise-loss-tcase"]
    settling = figures["fig-thermal-settling"]
    assert (temperature.x_key, temperature.y_key) == ("Iout_A", "Tcase_C")
    assert (rise.x_key, rise.y_key) == ("loss_W", "Tcase_rise_C")
    assert "empirical relationship for the stated boundary and setup" in rise.caption
    assert "case top, accessible external location" in temperature.caption
    # Temperature never shares a figure with efficiency or voltage; every figure has one y quantity.
    for figure in model.figures:
        assert FORBIDDEN_CAPTION_TERMS.search(figure.caption + " " + figure.title) is None, figure.id
        assert "y2" not in figure.model_dump_json()
        if figure.y_key in ("efficiency_pct", "Vout_V", "loss_W", "Iin_A"):
            assert "Temperature" not in figure.y_label
        if figure.id.startswith("fig-temperature") or figure.id == "fig-thermal-settling":
            assert figure.y_key not in ("efficiency_pct", "Vout_V", "loss_W") and "°C" in figure.y_label
    assert settling.series == [] and {s.quantity for s in settling.sample_series} == {"Tcase_C", "Tambient_C"}
    for series in settling.sample_series:
        assert len(series.x) >= 2 and series.x == sorted(series.x) and all(math.isfinite(v) for v in series.y)
        assert series.point_id == "p0001"
    retained = [s for s in samples if s["point_id"] == "p0001" and s["quantity"] == "Tcase_C"]
    assert len(next(s for s in settling.sample_series if s.quantity == "Tcase_C").y) == len(retained)
    static = renderer._plot_figure(dumped, dumped["figures"][dumped["figures"].index(
        next(f for f in dumped["figures"] if f["id"] == "fig-thermal-settling"))], 6)
    assert len(static.data) == 2 and list(static.data[0].x) == settling.sample_series[0].x
    assert not hasattr(static.layout, "yaxis2") and all(trace.yaxis in (None, "y") for trace in static.data)
    assert static.layout.yaxis.title.text == "Temperature (°C)"
    metric = next(m for m in model.metrics if m.id == "highest-observed-surface-rise")
    assert metric.qualification == "synthetic observation" and metric.unit == "°C"
    assert metric.uncertainty["status"] == "unquantified" and metric.figure_ids == ["fig-temperature-rise-loss-tcase"]
    assert FORBIDDEN_CAPTION_TERMS.search(metric.label + metric.formula) is None
    assert any(text.startswith("Temperature (SYNTHETIC): 2 of 2") for text in model.summary)
    assert any(reference.metric_ids == [metric.id] for reference in model.summary_evidence)


def test_report_model_labels_synthetic_temperature_everywhere(settled_run):
    _, path = settled_run
    plan, run, samples, analysis, model = analysed(path)
    assert model.evidence_label == "SYNTHETIC"
    assert model.thermal["data_source"] == "synthetic" and "SYNTHETIC" in model.thermal["label"]
    assert model.thermal["provider"]["data_source"] == "simulated"
    for sensor in model.thermal["sensors"]:
        assert sensor["data_source"] == "synthetic" and sensor["adapter"] == MOCK_THERMAL_ADAPTER
        assert not re.search(r"(?i)\bU\d+\b|junction", sensor["measured_surface"])
        assert sensor["placement"] is None
    assert set(model.thermal["settling_policies"]) == {"thermal-steady-load"}
    assert all(entry["thermal_qualification"] == "settled" for entry in model.thermal["points"])
    limitations = " ".join(model.limitations)
    assert "SYNTHETIC temperature" in limitations and "first-order mock thermal model" in limitations
    assert "drafts that require validation" in limitations
    assert "No schematic, board photograph or temperature channels were supplied" not in limitations
    for point in model.points:
        assert point["thermal"]["data_source"] == "synthetic"
    assert renderer._temperature_note(model.model_dump(mode="json")) is None
    assert "Temperatures: not acquired" not in renderer._controls_html(model.model_dump(mode="json"))
