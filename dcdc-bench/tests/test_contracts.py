"""Section 5.2 contracts are an enforced boundary, not documentation.

Class-shaped contracts are checked with ``isinstance`` against the
``@runtime_checkable`` Protocols in ``dcdc_bench.domain``. The callable
contracts (Analyzer, ReportRenderer) are checked by signature, because
``isinstance`` against a ``__call__`` Protocol admits any callable. No test
here opens an instrument; the only subprocess is one short mock acquisition.
"""
from __future__ import annotations

import inspect
import json
import typing
import uuid
from types import SimpleNamespace

import pytest

from dcdc_bench import domain, storage
from dcdc_bench.adapters import MODEL_VERSION, MockBench
from dcdc_bench.analysis import analyze_evidence
from dcdc_bench.bringup import RigolPilot
from dcdc_bench.domain import (Analyzer, LoadAdapter, LoadCapabilities, MeasurementProvider, Plan, RawSample,
                               ReportRenderer, SourceAdapter, SourceCapabilities)
from dcdc_bench.extended import extended_plan
from dcdc_bench.planning import build_plan
from dcdc_bench.real_backend import ConfiguredProcedure, prepare_real_plan
from dcdc_bench.reporting import render_report
from dcdc_bench.runner import run_mock
from dcdc_bench.services import default_plan
from dcdc_bench.source_limit import SourceLimitProcedure
from dcdc_bench.startup_descent import StartupDescentProcedure
from dcdc_bench.voltage_sweep import VoltageContinuationProcedure, VoltageSweepProcedure

# ``TestProcedure``/``TestDefinition`` are reached through the module so pytest does not try to collect them.
PROTOCOLS = (SourceAdapter, LoadAdapter, MeasurementProvider, domain.TestProcedure, domain.RunStore,
             Analyzer, ReportRenderer)

# Raw-reading fields the brief requires (section 8.2), spelled as ``domain.RawSample`` spells them.
SPEC_RAW_FIELDS = frozenset({
    "sample_id", "run_id", "test_id", "point_id", "channel_id", "instrument_id",
    "quantity", "value", "unit", "location",
    "query_start_utc", "query_end_utc", "query_start_monotonic_s", "query_end_monotonic_s",
    "quality_flags",
})

# bringup.RigolPilot conforms to the source/load contracts; any regression reappears here.
RIGOL_PILOT_GAPS = frozenset()


def protocol_members(protocol) -> set[str]:
    attrs = getattr(protocol, "__protocol_attrs__", None)
    if attrs is None:  # Python 3.11
        attrs = typing._get_protocol_attrs(protocol)  # type: ignore[attr-defined]
    return set(attrs)


def missing_members(obj, protocol) -> set[str]:
    return {name for name in protocol_members(protocol) if not hasattr(obj, name)}


def parameters(function) -> list[tuple[str, inspect._ParameterKind]]:
    """Names and kinds only; defaults and annotations may legitimately differ."""
    return [(p.name, p.kind) for p in inspect.signature(function).parameters.values() if p.name != "self"]


def mock_bench(current_limit: float = 1.) -> MockBench:
    # As runner._worker builds it: nominal Vout, source current limit, load minimum voltage, seed.
    return MockBench(12., current_limit, .15, seed=1)


def rigol_pilot() -> RigolPilot:
    # The constructor only stores driver/transport handles; nothing is opened or queried.
    return RigolPilot(SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace())


def configured_procedure() -> ConfiguredProcedure:
    # Mirrors tests/test_real_backend.py: a hash-stable configured real plan with executable points.
    base = extended_plan()
    base.dut.ratings.output_voltage_nominal_V = 12.
    base.bench.source.max_current_A = base.bench.protective_controls.source_current_limit_A = 1.
    base.bench.protective_controls.dut_output_overvoltage_V = 13.2
    base.bench.protective_controls.output_overcurrent_A = base.bench.load.max_current_A = 2.55
    base.bench.load.max_power_W = 34.
    base.recipe.tests = [domain.TestDefinition(id="configured", input_voltage_targets_V=[24.],
                                               output_current_targets_A=[.1, .25])]
    base.recipe.acquisition.duration_s = 5.
    base.recipe.acquisition.target_poll_interval_s = 1.
    plan, errors, _ = prepare_real_plan(build_plan(base.dut, base.bench, base.recipe))
    assert not errors
    return ConfiguredProcedure(plan, {"plan_hash": plan.plan_hash})


def one_point_mock_plan() -> Plan:
    original = default_plan()
    bench, recipe = original.bench.model_copy(deep=True), original.recipe.model_copy(deep=True)
    suffix = uuid.uuid4().hex  # private mock lock resources, as tests/test_runner.py does
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
    return build_plan(original.dut, bench, recipe)


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=lambda p: p.__name__)
def test_every_contract_is_runtime_checkable_and_states_what_it_must_not_contain(protocol):
    assert getattr(protocol, "_is_runtime_protocol", False), f"{protocol.__name__} is not @runtime_checkable"
    assert protocol.__doc__ and "Must not:" in protocol.__doc__


def test_mock_bench_serves_the_source_load_and_measurement_roles():
    bench = mock_bench()
    assert isinstance(bench, SourceAdapter)
    assert isinstance(bench, LoadAdapter)
    assert isinstance(bench, MeasurementProvider)
    assert parameters(bench.read)[:2] == parameters(MeasurementProvider.read)
    assert parameters(bench.configure) == parameters(SourceAdapter.configure) == parameters(LoadAdapter.configure)


def test_mock_bench_capabilities_and_status_are_thin_views_of_the_plant():
    bench = mock_bench(current_limit=.8)
    source, load = bench.source_capabilities(), bench.load_capabilities()
    assert isinstance(source, SourceCapabilities) and isinstance(load, LoadCapabilities)
    assert source.max_current_A == .8 and load.min_voltage_V == .15 and load.mode == "CC"
    assert (source.adapter, load.adapter) == ("mock_source", "mock_load")
    assert MODEL_VERSION in source.reported_identity and MODEL_VERSION in load.reported_identity
    assert source.physical_model is None and load.physical_model is None  # synthetic, never a hardware claim
    assert bench.status() == {"source_output": "OFF", "load_input": "OFF", "remote_sense_verified": False,
                              "source_voltage_setpoint_V": 0., "load_current_setpoint_A": 0., "closed": False}
    bench.configure(24., .5, 0.)
    bench.source_on()
    bench.load_on()
    status = bench.status()
    assert (status["source_output"], status["load_input"], status["remote_sense_verified"]) == ("ON", "ON", True)
    assert (status["source_voltage_setpoint_V"], status["load_current_setpoint_A"]) == (24., .5)
    bench.load_off()
    bench.source_off()
    bench.close()
    assert bench.status()["closed"] and bench.status()["source_output"] == bench.status()["load_input"] == "OFF"


def test_an_incomplete_fake_is_rejected_by_the_source_contract():
    fake = SimpleNamespace(identify=lambda: {}, configure=lambda vin, iout, now: None, source_on=lambda: None)
    assert not isinstance(fake, SourceAdapter)
    assert missing_members(fake, SourceAdapter) == {"source_capabilities", "source_off", "status", "close"}
    assert not isinstance(object(), LoadAdapter)
    assert not isinstance(object(), MeasurementProvider)


def test_rigol_pilot_conforms_to_the_source_and_load_contracts():
    pilot = rigol_pilot()
    gaps = missing_members(pilot, SourceAdapter) | missing_members(pilot, LoadAdapter)
    assert not gaps, f"RigolPilot lacks {sorted(gaps)}"
    assert isinstance(pilot, SourceAdapter) and isinstance(pilot, LoadAdapter)


def test_rigol_pilot_read_matches_the_measurement_provider_signature():
    assert parameters(rigol_pilot().read)[:2] == parameters(MeasurementProvider.read)


def test_rigol_pilot_gap_ledger_matches_the_recorded_xfail_reason():
    pilot = rigol_pilot()
    gaps = missing_members(pilot, SourceAdapter) | missing_members(pilot, LoadAdapter)
    assert gaps == RIGOL_PILOT_GAPS, "update RIGOL_PILOT_GAPS and the xfail reason together"


def test_storage_run_store_satisfies_the_run_store_contract(tmp_path):
    store = storage.RunStore(tmp_path / "run")
    assert isinstance(store, domain.RunStore)
    assert domain.RunStore is not storage.RunStore  # the brief's name stays on the Protocol
    store.initialize({}, {}, {"execution_status": "running"})
    store.append("events", {"event": "contract-check"})
    store.finalize({"execution_status": "completed"})
    storage.verify_integrity(store.path)
    partial = SimpleNamespace(path=store.path, append=store.append, finalize=store.finalize)
    assert not isinstance(partial, domain.RunStore)  # initialize is part of the contract


@pytest.mark.parametrize("factory", [
    SourceLimitProcedure, VoltageSweepProcedure, StartupDescentProcedure,
    lambda: VoltageContinuationProcedure({"run_id": "prior-run", "reason": "recorded elsewhere"}),
    configured_procedure,
], ids=["source-limit", "voltage-sweep", "startup-descent", "voltage-continuation", "configured"])
def test_in_tree_procedures_satisfy_the_test_procedure_contract(factory):
    procedure = factory()
    assert isinstance(procedure, domain.TestProcedure), missing_members(procedure, domain.TestProcedure)
    assert isinstance(procedure.plan(), Plan)
    assert isinstance(procedure.metadata(), dict) and isinstance(procedure.stage, str)
    assert isinstance(procedure.adapter, type) and issubclass(procedure.adapter, RigolPilot)


def test_recipe_test_definitions_are_data_not_procedures():
    definition = default_plan().recipe.tests[0]
    assert not isinstance(definition, domain.TestProcedure)
    assert set(definition.required_quantities) == {"Vin_V", "Iin_A", "Vout_V", "Iout_A"}


def test_analyzer_and_renderer_functions_match_their_callable_contracts():
    assert parameters(analyze_evidence) == parameters(Analyzer.__call__)
    assert parameters(render_report) == parameters(ReportRenderer.__call__)
    # Why signatures: a ``__call__`` Protocol accepts every callable, so isinstance proves nothing here.
    assert isinstance(analyze_evidence, Analyzer) and isinstance(len, Analyzer)


def test_raw_sample_schema_covers_the_brief_and_mock_read_cycles_emit_it(tmp_path):
    fields = RawSample.model_fields
    assert SPEC_RAW_FIELDS <= set(fields)
    assert all(fields[name].is_required() for name in SPEC_RAW_FIELDS - {"quality_flags"})
    directory = run_mock(one_point_mock_plan(), tmp_path)
    storage.verify_integrity(directory)
    records = [json.loads(line) for line in (directory / "raw/samples.jsonl").read_text().splitlines()]
    assert records
    for record in records:
        assert SPEC_RAW_FIELDS <= set(record), SPEC_RAW_FIELDS - set(record)
        sample = RawSample.model_validate(record)
        assert sample.quantity in ("Vin_V", "Iin_A", "Vout_V", "Iout_A") and sample.unit in ("V", "A")
        assert sample.value is not None or sample.quality_flags
        assert sample.query_end_monotonic_s >= sample.query_start_monotonic_s
    assert json.loads((directory / "run.json").read_text())["execution_status"] == "completed"
