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
    assert [row.status for row in p.points] == ["unsupported", "executable", "executable", "unsupported"]
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
    p, errors, _ = plan(loads=(0., .1))
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
