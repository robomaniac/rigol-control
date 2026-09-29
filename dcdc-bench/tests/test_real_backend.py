"""Configured hardware path exercised only through fake SCPI transports."""
import json

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
