"""Configured hardware path exercised only through fake SCPI transports."""
import json
from types import SimpleNamespace

import pytest

from dcdc_bench.domain import TestDefinition as Definition
from dcdc_bench.extended import extended_plan
from dcdc_bench.planning import build_plan, verify_plan_hash
from dcdc_bench.real_backend import prepare_real_plan, run_real, ConfiguredProcedure
from dcdc_bench.extended import ExtendedAbort
from dcdc_bench.storage import verify_integrity, RunStore
from test_voltage_sweep import bench
from test_extended import writes


@pytest.fixture(autouse=True)
def isolated_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("DCDC_ACTIVITY_LOCK", str(tmp_path / "activity.lock"))


def plan(*, volts=(24.,), loads=(.1, .25), nominal=12., high=13.2):
    base = extended_plan()
    base.dut.ratings.output_voltage_nominal_V = nominal
    base.bench.source.max_current_A = base.bench.protective_controls.source_current_limit_A = 1.
    base.bench.protective_controls.dut_output_overvoltage_V = high
    base.bench.protective_controls.output_overcurrent_A = base.bench.load.max_current_A = 2.55
    base.bench.load.max_power_W = 34.
    base.recipe.tests = [Definition(id="configured", input_voltage_targets_V=list(volts), output_current_targets_A=list(loads))]
    base.recipe.acquisition.duration_s = 5.
    base.recipe.acquisition.target_poll_interval_s = 1.
    return prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))


def confirmed(p):
    return {"plan_hash": p.plan_hash, "wiring_and_polarity": True, "channel1": True,
            "protections_reviewed": True, "source_serial": "FAKE-source", "load_serial": "FAKE-load"}


def test_configurable_plan_retains_exclusions_and_is_hash_stable():
    p, errors, seconds = plan(loads=(0., .1, .25, 4.))
    assert not errors and seconds < 540 and verify_plan_hash(p)
    # A 0 A first request is a distinct enabled no-load observation, not an exclusion (plan Gap E).
    assert [row.status for row in p.points] == ["executable", "executable", "executable", "unsupported"]
    assert "enabled no-load observation (load input OFF)" in p.points[0].reason
    assert "efficiency not applicable" in p.points[0].reason
    rebuilt, errors, _ = prepare_real_plan(build_plan(p.dut, p.bench, p.recipe))
    assert not errors and rebuilt.plan_hash == p.plan_hash


def test_profile_driven_multiple_voltages_use_off_transitions_and_preserve_evidence(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(volts=(24., 20.))
    assert not errors
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and len(run["executed_point_ids"]) == 4
    assert all(point["qualification"] == "valid" for point in run["points"])
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())
    assert [x for x in writes(fake, "source") if x.startswith(":SOUR1:VOLT ")] == [":SOUR1:VOLT 24.0", ":SOUR1:VOLT 20.0"]
    verify_integrity(path)


def test_new_five_volt_dut_uses_profile_guards_not_twelve_volt_constants(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch, query_overrides={("load", ":MEAS:VOLT?"): "5.0",
                                                      ("load", ":SOUR:CURR:VLIM?"): "5.5"})
    p, errors, _ = plan(nominal=5., high=5.5)
    assert not errors
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed"
    assert ":SOUR:CURR:VLIM 5.5" in writes(fake, "load")
    assert run["method"]["output_lower_stop_V"] == 4.5


def test_excluded_first_request_is_not_energized_or_mislabeled(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(loads=(4., .1))
    assert p.points[0].status == "unsupported"
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    rows = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert run["points"][0]["qualification"] == "not-run"
    assert {r["point_id"] for r in rows} == {"p0002"}


@pytest.mark.parametrize("field,value", [("plan_hash", "wrong"), ("channel1", False), ("source_serial", "wrong")])
def test_bad_confirmation_never_opens_instruments(tmp_path, monkeypatch, field, value):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan()
    confirmation = confirmed(p)
    confirmation[field] = value
    with pytest.raises(ValueError):
        run_real(p, fake.config, fake.out, confirmation=confirmation)
    assert fake.commands == []


def test_unapproved_saved_profiles_never_open_instruments(tmp_path, monkeypatch):
    from dcdc_bench.extended import _run_fixed
    fake = bench(tmp_path, monkeypatch)
    base = extended_plan()
    base.dut.execution_approval.real_hardware_enabled = False
    base.bench.protective_controls.approved = False
    p, errors, _ = prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))
    assert any("real_hardware_enabled is false" in e for e in errors)
    assert any("protective_controls.approved is false" in e for e in errors)
    with pytest.raises(ValueError, match="real_hardware_enabled is false"):
        run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    assert fake.commands == []

    class Unapproved:
        adapter = None

        def plan(self):
            return p

    with pytest.raises(ExtendedAbort, match="approvals are missing"):
        _run_fixed(fake.config, fake.out, arm=True, procedure=Unapproved())
    assert fake.commands == [] and not fake.out.exists()


def test_cancel_during_acquisition_preserves_partial_evidence_and_verified_off(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan()
    cancel = tmp_path / "cancel"
    append = RunStore.append
    def record(store, stream, row):
        result = append(store, stream, row)
        if stream == "samples" and row["phase"] == "acquiring":
            cancel.touch()
        return result
    monkeypatch.setattr(RunStore, "append", record)
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p), cancel=cancel)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "cancellation" in run["errors"][0]
    assert all(s["state"] == "OFF" and s["verified"] for s in run["shutdown"].values())
    assert not any(p["qualification"] == "valid" for p in run["points"])
    verify_integrity(path)


def test_preexisting_cancel_opens_nothing(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan()
    cancel = tmp_path / "cancel"
    cancel.touch()
    with pytest.raises(RuntimeError, match="cancellation"):
        run_real(p, fake.config, fake.out, confirmation=confirmed(p), cancel=cancel)
    assert fake.commands == []


def test_real_margin_and_temperature_limit_are_not_silently_ignored():
    p, _, _ = plan(volts=(9., 24., 36.))
    assert p.points[0].status == "unsupported" and p.points[-1].status == "unsupported"
    base = extended_plan()
    base.dut.acceptance.maximum_surface_temperature_C = 80.
    _, errors, _ = prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))
    assert any("Temperature" in error for error in errors)


def test_dut_minimum_guard_is_stricter_than_setpoint_headroom():
    p, errors, _ = plan(volts=(9.1,))
    assert not errors
    procedure = ConfiguredProcedure(p, confirmed(p))
    with pytest.raises(ExtendedAbort, match="headroom"):
        procedure.guard({"Vin_V": 8.9, "Iin_A": .2, "Vout_V": 12., "Iout_A": .1}, .1)


def test_protective_settings_cannot_exceed_smaller_saved_equipment_limits():
    p, _, _ = plan()
    p.bench.source.max_current_A = .5
    p.bench.load.max_current_A = .5
    p.bench.load.max_voltage_V = 12.5
    _, errors, _ = prepare_real_plan(build_plan(p.dut, p.bench, p.recipe))
    assert "Source current setting exceeds the saved bench capability" in errors
    assert "Output current guard exceeds the saved load capability" in errors
    assert "Output voltage guard exceeds the saved load capability" in errors


@pytest.mark.parametrize("window,samples,poll,timeout", [(15., 5, 1., 5.), (5., 15, 2., 29.), (5., 5, 1., 5.)])
def test_impossible_settling_timeout_is_refused_before_instrument_access(tmp_path, monkeypatch, window, samples, poll, timeout):
    fake = bench(tmp_path, monkeypatch)
    base, _, _ = plan(loads=(.1,))
    base.recipe.settling.window_s = window
    base.recipe.settling.minimum_fresh_samples = samples
    base.recipe.settling.timeout_s = timeout
    base.recipe.acquisition.target_poll_interval_s = poll
    checked, errors, _ = prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))
    assert any("Settling timeout must exceed" in error for error in errors)
    with pytest.raises(ValueError, match="Settling timeout must exceed"):
        run_real(checked, fake.config, fake.out, confirmation=confirmed(checked))
    assert fake.commands == []
    assert not fake.out.exists()


def test_settling_timeout_allows_window_samples_and_communication_margin():
    base, _, _ = plan(loads=(.1,))
    base.recipe.settling.window_s = 15.
    base.recipe.settling.minimum_fresh_samples = 15
    base.recipe.acquisition.target_poll_interval_s = 2.
    base.recipe.settling.timeout_s = 35.
    _, errors, _ = prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))
    assert not errors


def test_cancellation_during_configuration_never_enables_source(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan()
    cancel = tmp_path / "cancel"
    from dcdc_bench.extended import ExtendedRigol
    configure = ExtendedRigol.configure
    def configured(pilot):
        configure(pilot)
        cancel.touch()
    monkeypatch.setattr(ExtendedRigol, "configure", configured)
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p), cancel=cancel)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted"
    assert ":DELAY ON" not in writes(fake, "source")
    assert all(item == {"state": "OFF", "verified": True} for item in run["shutdown"].values())


def test_operator_notes_are_preserved_and_visible_in_report_model(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan(loads=(.1,))
    attachments = [{"role": "setup_photo", "name": "Bench view", "caption": "Local sensing", "location": "lab/photo.jpg"}]
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p), notes="Short leads; board horizontal.", attachments=attachments)
    run = json.loads((path / "run.json").read_text())
    assert run["operator_observations"][0] == "Short leads; board horizontal."
    assert run["attachment_descriptors"] == attachments
    from dcdc_bench.analysis import analyze_run, build_report_model
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    rows = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    model = build_report_model(p, run, analysis, rows, "r0001")
    assert model.provenance["operator_observations"] == run["operator_observations"]
    verify_integrity(path)


# ---------------------------------------------------------------------------
# Startup gate (plan section 1 prerequisite) and enabled no-load (plan Gap E).
# ---------------------------------------------------------------------------

def test_startup_gate_permits_four_source_only_cycles_then_requires_output_in_band():
    p, _, _ = plan()
    procedure = ConfiguredProcedure(p, confirmed(p))
    low = {"Vin_V": 24., "Iin_A": .02, "Vout_V": 3., "Iout_A": .001}
    for _ in range(4):
        procedure.guard(low, .1, loaded=False, startup=True)
    with pytest.raises(ExtendedAbort, match="load will not be enabled"):
        procedure.guard(low, .1, loaded=False, startup=True)
    assert procedure.source_only_cycles == 5 and procedure.lower_output == pytest.approx(10.8)
    # Outside startup the band applies at once, loaded or not; a no-load cycle demands no current match.
    fresh = ConfiguredProcedure(p, confirmed(p))
    with pytest.raises(ExtendedAbort, match="load will not be enabled"):
        fresh.guard(low, 0., loaded=False)
    fresh.guard({**low, "Vout_V": 10.8}, 0., loaded=False)


@pytest.mark.parametrize("loads", [(.1,), (0., .1)])
def test_startup_gate_failure_aborts_before_any_load_command(tmp_path, monkeypatch, loads):
    fake = bench(tmp_path, monkeypatch, query_overrides={("load", ":MEAS:VOLT?"): "5.0"})
    p, errors, _ = plan(loads=loads)
    assert not errors
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted"
    assert "Output below startup/operating threshold" in run["errors"][0]
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    rows = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert {r["phase"] for r in rows} == {"starting"} and len({r["acquisition_cycle_id"] for r in rows}) == 5
    assert all(r["acquisition_settings"]["load_enabled"] is False for r in rows)
    assert run["points"][0]["qualification"] == "inconclusive"
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_no_load_after_a_loaded_point_is_unsupported_not_acquired():
    p, errors, _ = plan(loads=(.1, 0.))
    assert not errors
    assert [row.status for row in p.points] == ["executable", "unsupported"]
    assert "first request of its input-voltage phase" in p.points[1].reason
    p, _, _ = plan(loads=(0., 0.))
    assert [row.status for row in p.points] == ["executable", "unsupported"]
    p, _, _ = plan(volts=(24., 20.), loads=(0., .1))
    assert [row.status for row in p.points] == ["executable"] * 4


def test_enabled_no_load_first_request_is_acquired_with_the_load_input_off(tmp_path, monkeypatch):
    from dcdc_bench.analysis import analyze_run, build_report_model
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(loads=(0., .1))
    assert not errors and p.points[0].status == "executable"
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and run["executed_point_ids"] == ["p0001", "p0002"]
    first, second = run["points"]
    assert first["qualification"] == "valid" and first["observation"] == "enabled_no_load"
    assert first["load_input_state"] == "OFF" and first["load_readback_offset_A"] == pytest.approx(.001)
    assert first["iin_span_A"] == 0 and first["startup_gate"].startswith("passed")
    assert len(first["acquisition_cycle_ids"]) >= 5
    assert second["qualification"] == "valid" and second["observation"] == "loaded" and second["load_input_state"] == "ON"
    assert run["method"]["enabled_no_load"]["load_input_state"].startswith("OFF")
    rows = [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]
    assert all(r["acquisition_settings"]["load_enabled"] is False for r in rows if r["point_id"] == "p0001")
    assert all(r["acquisition_settings"]["load_enabled"] is True for r in rows
               if r["point_id"] == "p0002" and r["phase"] != "starting")
    assert writes(fake, "load").count(":SOUR:INP:STAT ON") == 1
    # The load's CC setpoint was programmed to the first loaded request while its input was OFF.
    assert [float(c.split()[-1]) for c in writes(fake, "load") if c.startswith(":SOUR:CURR:LEV:IMM ")] == [.1]
    # Analysis: input consumption with the load input OFF; efficiency not applicable; loss not module-only.
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    point = analysis["points"][0]
    assert point["observation"] == "enabled_no_load" and point["load_input_state"] == "OFF"
    assert point["efficiency_pct"] is None and point["efficiency_reason"] == "not applicable: enabled with no external load"
    assert point["Pout_W"] is None and point["loss_W"] is None
    assert "not attributed to the module alone" in point["loss_reason"]
    assert point["enabled_no_load_consumption_W"] == pytest.approx(point["Vin_V"] * point["Iin_A"])
    assert point["enabled_no_load_consumption_W"] == pytest.approx(24 * .01, rel=1e-6)
    assert point["load_readback_offset_A"] == pytest.approx(.001) and point["Iout_A"] == pytest.approx(.001)
    assert point["requirements"]["efficiency"] == "not-applicable"
    assert analysis["points"][1]["observation"] == "loaded" and analysis["points"][1]["enabled_no_load_consumption_W"] is None
    budget = analysis["uncertainty"]["points"]["p0001"]
    assert budget["observation"] == "enabled_no_load" and budget["required_terms"] == ["Vin_V", "Iin_A"]
    assert budget["budget_status"] == "unquantified"
    assert budget["missing_terms"] and all(m.startswith(("Vin_V:", "Iin_A:")) for m in budget["missing_terms"])
    assert budget["terms"]["Iin_A"]["status"] == "unquantified"
    assert budget["terms"]["Iin_A"]["programming_accuracy_consulted"] is False
    model = build_report_model(p, run, analysis, rows, "r0001")
    metric = next(m for m in model.metrics if m.id == "enabled-no-load-input-consumption-p0001")
    assert metric.unit == "W" and metric.value == point["enabled_no_load_consumption_W"]
    assert "load input OFF" in metric.conditions and "not output current" in metric.conditions
    assert "not module-only loss" in metric.conditions and metric.uncertainty["expanded"] is None
    assert any(line.startswith("Enabled no-load path input consumption:") and "unquantified" in line for line in model.summary)
    assert not any(key.endswith("_uncertainty_label") for key in model.points[0])
    assert any("At qualified no-load points, input consumption is reported" in line for line in model.limitations)
    verify_integrity(path)


def test_no_load_only_plan_never_issues_a_load_enable(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(loads=(0.,))
    assert not errors
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and run["points"][0]["qualification"] == "valid"
    assert run["points"][0]["observation"] == "enabled_no_load"
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    assert [float(c.split()[-1]) for c in writes(fake, "load") if c.startswith(":SOUR:CURR:LEV:IMM ")] == [.05]
    assert run["shutdown"]["load"] == {"state": "OFF", "verified": True}
    assert run["method"]["enabled_no_load"]["iin_span_A"] == .002
    verify_integrity(path)


def test_unstable_no_load_input_current_is_not_qualified_and_the_load_stays_off(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    from dcdc_bench.extended import ExtendedRigol
    original, calls = ExtendedRigol.read, {"n": 0}

    def wobbling(pilot, quantity):
        value = original(pilot, quantity)
        if quantity == "Iin_A" and not fake.sessions["load"].enabled:
            calls["n"] += 1
            return value + (.005 if calls["n"] % 2 else 0.)
        return value

    monkeypatch.setattr(ExtendedRigol, "read", wobbling)
    p, _, _ = plan(loads=(0., .1))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "no-load span" in run["errors"][0]
    assert run["points"][0]["qualification"] == "inconclusive"
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())


# ---------------------------------------------------------------------------
# Independent safety review closure: load-enable ordering in the transcript,
# runtime defenses, zero-current readback offsets, no-load-window aborts, the
# time estimate and the per-sample load input readback.
# ---------------------------------------------------------------------------

def samples(path):
    return [json.loads(line) for line in (path / "raw/samples.jsonl").read_text().splitlines()]


def transcript_positions(fake, rows):
    """Map each Iout_A sample to the transcript index of the load current query that produced it."""
    iout_rows = [r for r in rows if r["quantity"] == "Iout_A"]
    queries = [i for i, c in enumerate(fake.commands) if c == ("load", "query", ":MEAS:CURR?")]
    # Every load current query on this path belongs to exactly one guarded cycle.
    assert len(queries) == len(iout_rows)
    return {r["sample_id"]: i for r, i in zip(iout_rows, queries)}, iout_rows


def test_load_enable_follows_the_fifth_source_only_cycle_in_the_transcript(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(loads=(.1, .25))
    assert not errors
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and all(pt["qualification"] == "valid" for pt in run["points"])
    enables = [i for i, c in enumerate(fake.commands) if c == ("load", "write", ":SOUR:INP:STAT ON")]
    assert len(enables) == 1
    positions, iout_rows = transcript_positions(fake, samples(path))
    unloaded = [r for r in iout_rows if r["acquisition_settings"]["load_enabled"] is False]
    loaded = [r for r in iout_rows if r["acquisition_settings"]["load_enabled"] is True]
    # Exactly the five source-only starting cycles were completed before the enable command was written.
    assert len(unloaded) == 5 and {r["phase"] for r in unloaded} == {"starting"}
    assert max(positions[r["sample_id"]] for r in unloaded) < enables[0] < min(positions[r["sample_id"]] for r in loaded)
    # The same ordering holds on the sample clock, and the five loaded starting cycles follow the enable.
    assert max(r["query_end_monotonic_s"] for r in unloaded) < min(r["query_start_monotonic_s"] for r in loaded)
    assert len([r for r in loaded if r["phase"] == "starting"]) == 5


def test_each_voltage_phase_enables_the_load_once_and_never_inside_its_no_load_window(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, errors, _ = plan(volts=(24., 20.), loads=(0., .1))
    assert not errors and [row.status for row in p.points] == ["executable"] * 4
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "completed" and run["executed_point_ids"] == ["p0001", "p0002", "p0003", "p0004"]
    assert [pt["observation"] for pt in run["points"]] == ["enabled_no_load", "loaded"] * 2
    assert all(pt["qualification"] == "valid" for pt in run["points"])
    enables = [i for i, c in enumerate(fake.commands) if c == ("load", "write", ":SOUR:INP:STAT ON")]
    assert len(enables) == 2 and writes(fake, "load").count(":SOUR:INP:STAT ON") == 2
    positions, iout_rows = transcript_positions(fake, samples(path))
    window = lambda point_id: [positions[r["sample_id"]] for r in iout_rows if r["point_id"] == point_id]
    for no_load_id, loaded_id, enable in (("p0001", "p0002", enables[0]), ("p0003", "p0004", enables[1])):
        # The phase's gate, no-load settling and no-load acquisition all precede its single enable;
        # every loaded cycle of the phase follows it.
        assert max(window(no_load_id)) < enable < min(window(loaded_id))
        assert all(r["acquisition_settings"]["load_enabled"] is False for r in iout_rows if r["point_id"] == no_load_id)
        assert all(r["acquisition_settings"]["load_enabled"] is True for r in iout_rows if r["point_id"] == loaded_id)
    # The first phase's enable is not carried into the second phase's no-load window.
    assert enables[0] < min(window("p0003"))


def test_no_load_point_aborts_when_the_load_input_reports_on_after_the_gate(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    gate = ConfiguredProcedure.startup_gate

    def gate_then_load_turns_on_externally(procedure, ctx, point):
        gate(procedure, ctx, point)
        fake.sessions["load"].enabled = True  # e.g. a front-panel press; no command was written

    monkeypatch.setattr(ConfiguredProcedure, "startup_gate", gate_then_load_turns_on_externally)
    p, _, _ = plan(loads=(0., .1))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "requires the load input OFF" in run["errors"][0]
    assert [pt["qualification"] for pt in run["points"]] == ["inconclusive", "not-run"]
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    assert {r["phase"] for r in samples(path)} == {"starting"}
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_no_load_request_after_a_loaded_point_aborts_even_when_the_planner_is_bypassed(tmp_path, monkeypatch):
    from dcdc_bench.extended import _run_fixed
    from dcdc_bench.planning import _hash_payload
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan(loads=(.1, 0.))
    assert [row.status for row in p.points] == ["executable", "unsupported"]
    forged = p.model_copy(deep=True)
    forged.points[1].status = "executable"
    forged.plan_hash = _hash_payload(forged.model_dump(mode="json", exclude={"plan_hash"}))
    path = _run_fixed(fake.config, fake.out, arm=True, procedure=ConfiguredProcedure(forged, confirmed(forged)))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "not acquired after a loaded point" in run["errors"][0]
    assert [pt["qualification"] for pt in run["points"]] == ["valid", "inconclusive"]
    assert writes(fake, "load").count(":SOUR:INP:STAT ON") == 1
    assert not any(r["point_id"] == "p0002" for r in samples(path))
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())


def test_enable_load_refuses_a_no_load_request_without_touching_the_load():
    p, _, _ = plan(loads=(0., .1))
    procedure = ConfiguredProcedure(p, confirmed(p))

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"load.{name} must not be used for a no-load request")

    with pytest.raises(ExtendedAbort, match="never enabled for an enabled no-load observation"):
        procedure.enable_load(SimpleNamespace(load=Untouchable()), {"iout_target_A": 0.})
    assert procedure.load_enabled is False


@pytest.mark.parametrize("key", ["load_enabled", "load_input_readback"])
def test_analysis_rejects_a_valid_no_load_claim_whose_samples_show_the_load_enabled(tmp_path, monkeypatch, key):
    from dcdc_bench.analysis import analyze_evidence
    from dcdc_bench.domain import Plan
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan(loads=(0.,))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    saved = Plan.model_validate_json((path / "plan.json").read_text())
    run = json.loads((path / "run.json").read_text())
    rows = samples(path)
    assert analyze_evidence(saved, run, rows)["points"][0]["qualification"] == "valid"
    tampered_cycle = run["points"][0]["acquisition_cycle_ids"][2]
    tampered = [{**r, "acquisition_settings": {**r["acquisition_settings"], key: True}}
                if r["acquisition_cycle_id"] == tampered_cycle else r for r in rows]
    with pytest.raises(ValueError, match="enabled no-load point with the load input enabled"):
        analyze_evidence(saved, run, tampered)


@pytest.mark.parametrize("response, offset", [("0.011", .011), ("-0.0004", -.0004)])
def test_zero_current_readback_offset_is_evidence_not_output_current(tmp_path, monkeypatch, response, offset):
    from dcdc_bench.analysis import analyze_run
    fake = bench(tmp_path, monkeypatch, query_overrides={("load", ":MEAS:CURR?"): response})
    p, _, _ = plan(loads=(0.,))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    point = run["points"][0]
    assert run["execution_status"] == "completed" and point["qualification"] == "valid"
    assert point["observation"] == "enabled_no_load" and point["load_input_state"] == "OFF"
    assert point["load_readback_offset_A"] == pytest.approx(offset)
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    analysis = json.loads((analyze_run(path) / "analysis.json").read_text())
    result = analysis["points"][0]
    assert result["qualification"] == "valid" and "unexpected_sign" not in result["metric_flags"]
    assert result["load_readback_offset_A"] == pytest.approx(offset) and result["Iout_A"] == pytest.approx(offset)
    assert result["efficiency_pct"] is None and result["Pout_W"] is None and result["loss_W"] is None
    assert result["enabled_no_load_consumption_W"] == pytest.approx(result["Vin_V"] * result["Iin_A"])
    assert result["enabled_no_load_consumption_W"] == pytest.approx(24 * .01, rel=1e-6)
    verify_integrity(path)


def test_cancel_during_the_no_load_window_aborts_with_outputs_off_and_no_load_enable(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan(loads=(0., .1))
    cancel = tmp_path / "cancel"
    append = RunStore.append

    def record(store, stream, row):
        result = append(store, stream, row)
        if stream == "samples" and row["point_id"] == "p0001" and row["phase"] == "acquiring":
            cancel.touch()
        return result

    monkeypatch.setattr(RunStore, "append", record)
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p), cancel=cancel)
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "cancellation" in run["errors"][0]
    assert [pt["qualification"] for pt in run["points"]] == ["inconclusive", "not-run"]
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    rows = samples(path)
    assert all(r["acquisition_settings"]["load_enabled"] is False for r in rows) and "acquiring" in {r["phase"] for r in rows}
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_output_sag_during_no_load_settling_aborts_before_any_load_enable(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    from dcdc_bench.extended import ExtendedRigol
    gate, read, state = ConfiguredProcedure.startup_gate, ExtendedRigol.read, {"gated": False}

    def gate_then_sag(procedure, ctx, point):
        gate(procedure, ctx, point)
        state["gated"] = True

    def sagging(pilot, quantity):
        value = read(pilot, quantity)
        return 10.7 if quantity == "Vout_V" and state["gated"] else value  # below 0.9 x 12 V = 10.8 V

    monkeypatch.setattr(ConfiguredProcedure, "startup_gate", gate_then_sag)
    monkeypatch.setattr(ExtendedRigol, "read", sagging)
    p, _, _ = plan(loads=(0., .1))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    run = json.loads((path / "run.json").read_text())
    assert run["execution_status"] == "aborted" and "Output below startup/operating threshold" in run["errors"][0]
    assert [pt["qualification"] for pt in run["points"]] == ["inconclusive", "not-run"]
    assert ":SOUR:INP:STAT ON" not in writes(fake, "load")
    rows = samples(path)
    assert len([r for r in rows if r["phase"] == "settling"]) == 4 and "acquiring" not in {r["phase"] for r in rows}
    assert all(s == {"state": "OFF", "verified": True} for s in run["shutdown"].values())
    verify_integrity(path)


def test_time_estimate_budgets_the_loaded_startup_cycles_that_follow_a_no_load_acquisition():
    seconds = lambda **kw: plan(**kw)[2]
    # Same eligible point count and phase count; the no-load-first phase enables its load later.
    assert seconds(loads=(0., .1, .25)) == seconds(loads=(.05, .1, .25)) + 5
    # A phase with no loaded request never enables the load, so nothing is added.
    assert seconds(loads=(0.,)) == seconds(loads=(.1,))
    assert seconds(volts=(24., 20.), loads=(0., .1)) == seconds(volts=(24., 20.), loads=(.05, .1)) + 10
    p, errors, estimate = plan(volts=(24., 20.), loads=(0., .1))
    assert not errors and estimate < 540 and verify_plan_hash(p)


def test_samples_record_the_load_input_readback_beside_the_requested_flag(tmp_path, monkeypatch):
    fake = bench(tmp_path, monkeypatch)
    p, _, _ = plan(loads=(0., .1))
    path = run_real(p, fake.config, fake.out, confirmation=confirmed(p))
    rows = samples(path)
    assert rows and all("load_input_readback" in r["acquisition_settings"] for r in rows)
    assert all(r["acquisition_settings"]["load_input_readback"] is False for r in rows if r["point_id"] == "p0001")
    assert all(r["acquisition_settings"]["load_input_readback"] is True for r in rows if r["point_id"] == "p0002")
    # The readback agrees with the requested flag in every preserved cycle (verify_running aborts otherwise).
    assert all(r["acquisition_settings"]["load_input_readback"] is r["acquisition_settings"]["load_enabled"] for r in rows)
    verify_integrity(path)
