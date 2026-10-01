"""Honest automotive test catalog: clause list, capability tokens and per-clause verdicts.

The seeded real bench profile lives in the gitignored workspace, so the tests
carry an inline replica of the fields that matter (source envelope, load,
approved protective controls). When the workspace file is present it is
checked against the replica as well.
"""
import os
from pathlib import Path

import pytest

from dcdc_bench import standard_recipes as R
from dcdc_bench import standards as S
from dcdc_bench.domain import BenchProfile, DutProfile
from dcdc_bench.planning import REAL_HARDWARE_NOT_APPROVED, load_profile

ROOT = Path(__file__).resolve().parents[1]
# The seeded profile is gitignored; DCDC_SEEDED_BENCH_PROFILE points a checkout without it at a read-only copy.
WORKSPACE_REAL_BENCH = Path(os.environ.get("DCDC_SEEDED_BENCH_PROFILE",
                                           ROOT / "workspace" / "profiles" / "bench" / "rigol-local-limited.json"))


def _binding(instrument: str, quantity: str, unit: str, location: str) -> dict:
    return {"instrument_id": instrument, "quantity": quantity, "unit": unit, "location": location}


# Replica of workspace/profiles/bench/rigol-local-limited.json (purpose-limited DP821A CH1 / DL3031A bench).
SEEDED_REAL_BENCH = {
    "schema_version": "1.0", "bench_id": "rigol-local-limited", "mode": "real",
    "source": {"instrument_id": "source", "adapter": "benchctl_rigol_dp800", "channel": 1, "capabilities_confirmed": True,
               "min_voltage_V": 0.0, "max_voltage_V": 35.8, "max_current_A": 1.0, "max_power_W": 35.8},
    "load": {"instrument_id": "load", "adapter": "benchctl_rigol_dl3000", "capabilities_confirmed": True, "mode": "CC",
             "min_voltage_V": 0.15, "max_voltage_V": 15.0, "max_current_A": 2.55, "max_power_W": 34.0,
             "min_current_A": 0.0, "remote_sense_supported": True, "remote_sense_required": False},
    "measurements": {"Vin_V": _binding("source", "Vin_V", "V", "source_terminals"),
                     "Iin_A": _binding("source", "Iin_A", "A", "source_output"),
                     "Vout_V": _binding("load", "Vout_V", "V", "load_input_terminals_local_sense"),
                     "Iout_A": _binding("load", "Iout_A", "A", "load_input")},
    "protective_controls": {"approved": True, "policy_id": "supervised-24V-450mA-500mA-720s-v1", "source_current_limit_A": 1.0,
                            "dut_input_overvoltage_V": 26.0, "dut_output_overvoltage_V": 13.2, "output_overcurrent_A": 2.55},
    "measurement_boundary": "source-to-load-terminal path (input and output wiring included)",
}

EXPECTED_ISO16750_2_CLAUSES = {
    "4.1": "General",
    "4.2": "Direct current (DC) supply voltage",
    "4.3": "Overvoltage",
    "4.3.1": "Long term overvoltage",
    "4.3.1.1": "Long term overvoltage: alternator regulator failure at (Tmax - 20) K",
    "4.3.1.2": "Long term overvoltage: jump start (12 V systems only)",
    "4.3.2": "Transient overvoltage",
    "4.4": "Superimposed alternating voltage",
    "4.5": "Slow decrease and increase of supply voltage",
    "4.6": "Discontinuities in supply voltage",
    "4.6.1": "Drops or interrupts in supply voltage",
    "4.6.1.1": "Momentary drop in supply voltage",
    "4.6.1.2": "Micro interruption in supply voltage",
    "4.6.2": "Reset behaviour at voltage drop",
    "4.6.3": "Starting profile",
    "4.6.4": "Load dump",
    "4.7": "Reversed voltage",
    "4.8": "Ground reference and supply offset",
    "4.9": "Open circuit tests",
    "4.9.1": "Single line interruption",
    "4.9.2": "Multiple line interruption",
    "4.10": "Short circuit/overload protection",
    "4.10.2": "Short circuit in signal lines and load circuits",
    "4.10.3": "Overloading of load circuits",
    "4.11": "Withstand voltage",
    "4.12": "Insulation resistance",
    "4.13": "Electromagnetic compatibility",
}
RUNNABLE = ("4.2", "4.3.1.1", "4.5", "4.6.2")


@pytest.fixture(scope="module")
def real_bench() -> BenchProfile:
    return BenchProfile.model_validate(SEEDED_REAL_BENCH)


@pytest.fixture(scope="module")
def mock_bench() -> BenchProfile:
    return load_profile(ROOT / "profiles" / "bench" / "mock.yaml", BenchProfile)


@pytest.fixture(scope="module")
def dut() -> DutProfile:
    return load_profile(ROOT / "profiles" / "dut" / "12t12-4a.yaml", DutProfile)


def iso(number: str) -> S.Clause:
    return S.ISO16750_2.clause(number)


def statuses(bench: BenchProfile, dut: DutProfile, system: str) -> list[tuple[str, str, str]]:
    return [(e.clause.standard_id, e.clause.number, e.feasibility.status)
            for category in S.catalog(bench, dut, system) for e in category.entries]


# --- clause list -----------------------------------------------------------

def test_iso16750_2_clause_list_is_complete():
    listed = {c.number: c.title for c in S.ISO16750_2.clauses}
    assert listed == EXPECTED_ISO16750_2_CLAUSES
    assert S.ISO16750_2.edition == "2023" and S.ISO16750_2.id == "ISO 16750-2:2023"
    tests = {c.number for c in S.ISO16750_2.tests()}
    assert tests == set(EXPECTED_ISO16750_2_CLAUSES) - {"4.1", "4.3", "4.3.1", "4.6", "4.6.1", "4.9", "4.10", "4.13"}
    for item in S.ISO16750_2.tests():
        assert item.purpose and item.requires and item.functional_status, item.number
        assert item.requires <= S.ALL_TOKENS, item.number
        assert set(item.parameters) <= set(S.SYSTEMS)
        assert set(item.parameters) == item.systems, item.number


def test_owner_numbering_matches_2023_edition():
    assert iso("4.6.2").title == "Reset behaviour at voltage drop"
    assert iso("4.6.4").title == "Load dump"
    assert iso("4.7").title == "Reversed voltage"
    assert any("matches the 2023 numbering" in note for note in S.ISO16750_2.notes)


def test_functional_status_classes_one_line_each():
    assert set(S.FUNCTIONAL_STATUS_CLASSES) == set("ABCDE")
    for text in S.FUNCTIONAL_STATUS_CLASSES.values():
        assert text and "\n" not in text and len(text) < 140


def test_12v_and_24v_parameters_differ_where_the_standard_differs():
    p42 = iso("4.2").parameters
    assert p42["12V"]["codes_Usmin_Usmax_V"]["C"] == [9.0, 16.0] and p42["24V"]["codes_Usmin_Usmax_V"]["E"] == [10.0, 32.0]
    assert p42["12V"]["UA_V"] == 14.0 and p42["24V"]["UA_V"] == 28.0
    assert p42["12V"]["t2_s"] == p42["24V"]["t2_s"] == 60.0
    p4311 = iso("4.3.1.1").parameters
    assert (p4311["12V"]["level_V"], p4311["24V"]["level_V"]) == (18.0, 36.0)
    assert p4311["12V"]["duration_s"] == p4311["24V"]["duration_s"] == 3600.0
    assert iso("4.3.1.2").systems == {"12V"} and "24V" not in iso("4.3.1.2").parameters
    p432 = iso("4.3.2").parameters
    assert (p432["12V"]["trise_s"], p432["24V"]["trise_s"]) == (0.001, 0.002)
    assert p432["12V"]["ttrans_s"] == p432["24V"]["ttrans_s"] == 0.4
    p44 = iso("4.4").parameters
    assert p44["12V"]["Upp_by_severity_V"]["1 alternator without battery"] == 6.0
    assert p44["24V"]["Upp_by_severity_V"]["1 alternator without battery"] == 10.0
    assert p44["12V"]["Upp_by_severity_V"]["2 alternator"] == p44["24V"]["Upp_by_severity_V"]["2 alternator"] == 3.0
    p45 = iso("4.5").parameters
    assert (p45["12V"]["start_V"], p45["24V"]["start_V"]) == (14.0, 28.0)
    assert p45["12V"]["rate_V_per_min"] == p45["24V"]["rate_V_per_min"] == 0.5
    p4611 = iso("4.6.1.1").parameters
    assert (p4611["12V"]["drop_level_V"], p4611["24V"]["drop_level_V"]) == (4.5, 9.0)
    assert "figure" in p4611["12V"]["figure_values"].lower()
    assert iso("4.6.2").parameters["12V"] == iso("4.6.2").parameters["24V"]
    p463 = iso("4.6.3").parameters
    assert (p463["12V"]["tfall_ms"], p463["24V"]["tfall_ms"]) == (5.0, 10.0)
    assert len(p463["12V"]["levels"]) == 4 and len(p463["24V"]["levels"]) == 3
    p464 = iso("4.6.4").parameters
    assert p464["12V"]["test_A_no_suppression"]["US_V"] == [79.0, 101.0]
    assert p464["24V"]["test_A_no_suppression"]["US_V"] == [151.0, 202.0]
    p47 = iso("4.7").parameters
    assert p47["12V"]["test_case_1"]["Ureversed_V"] == -4.0 and p47["12V"]["test_case_2"]["Ureversed_V"] == -14.0
    assert "test_case_1" not in p47["24V"] and p47["24V"]["test_case_2"]["Ureversed_V"] == -26.0
    assert (iso("4.8").parameters["12V"]["US_V"], iso("4.8").parameters["24V"]["US_V"]) == (13.0, 26.0)


# --- capabilities ------------------------------------------------------------

def test_capability_tokens_for_the_dc_supply_class(real_bench, mock_bench):
    expected = {S.DC_STEADY, S.DC_STEP_1S, S.DC_RAMP_SLOW}
    assert S.capabilities(real_bench) == expected
    assert S.capabilities(mock_bench) == expected, "tokens describe the instrument class, not simulated vs real"
    for token in (S.NEGATIVE_VOLTAGE, S.AC_SUPERPOSITION, S.PULSE_MS, S.PULSE_US, S.LOW_SOURCE_IMPEDANCE_PULSE, S.EMC_CHAMBER):
        assert token not in S.capabilities(real_bench)
    assert set(S.TOKEN_DESCRIPTIONS) == S.ALL_TOKENS
    assert not (S.INSTRUMENT_TOKENS & S.FACILITY_TOKENS)
    for token in S.ALL_TOKENS:
        assert f"``{token}``" in S.__doc__, f"{token} is not documented in the module docstring"


def test_envelope_reads_numeric_bounds(real_bench, mock_bench):
    real = S.envelope(real_bench)
    assert (real.max_voltage_V, real.max_current_A, real.max_power_W) == (35.8, 1.0, 35.8)
    assert real.protective_input_ceiling_V == 26.0
    mock = S.envelope(mock_bench)
    assert mock.max_voltage_V == 60.0 and mock.protective_input_ceiling_V is None


# --- feasibility --------------------------------------------------------------

@pytest.mark.parametrize("number,system,status", [
    ("4.2", "12V", "runs_here"), ("4.2", "24V", "runs_here"),
    ("4.5", "12V", "mock_only"), ("4.5", "24V", "mock_only"),
    ("4.6.2", "12V", "mock_only"), ("4.6.2", "24V", "mock_only"),
    ("4.3.1.1", "12V", "needs_split"), ("4.3.1.1", "24V", "outside_dut_rating"),
    ("4.3.1.2", "12V", "needs_instrument"), ("4.3.1.2", "24V", "not_applicable"),
    ("4.3.2", "12V", "needs_instrument"), ("4.3.2", "24V", "needs_instrument"),
    ("4.4", "12V", "needs_instrument"), ("4.4", "24V", "needs_instrument"),
    ("4.6.1.1", "12V", "needs_instrument"), ("4.6.1.2", "12V", "needs_instrument"),
    ("4.6.3", "12V", "needs_instrument"), ("4.6.3", "24V", "needs_instrument"),
    ("4.6.4", "12V", "excluded_by_policy"), ("4.6.4", "24V", "excluded_by_policy"),
    ("4.7", "12V", "excluded_by_policy"), ("4.7", "24V", "excluded_by_policy"),
    ("4.8", "12V", "needs_instrument"), ("4.9.1", "12V", "needs_instrument"), ("4.9.2", "24V", "needs_instrument"),
    ("4.10.2", "12V", "excluded_by_policy"), ("4.10.3", "24V", "excluded_by_policy"),
    ("4.11", "12V", "not_on_this_bench"), ("4.12", "24V", "not_on_this_bench"),
    ("4.1", "12V", "not_applicable"), ("4.3", "12V", "not_applicable"), ("4.13", "24V", "not_applicable"),
])
def test_iso16750_2_verdicts_on_the_seeded_real_bench(real_bench, dut, number, system, status):
    verdict = S.feasibility(iso(number), real_bench, dut, system)
    assert verdict.status == status, verdict.reason
    assert verdict.clause_number == number and verdict.system == system


def test_missing_tokens_and_reasons_name_the_gap(real_bench, dut):
    assert S.feasibility(iso("4.4"), real_bench, dut, "12V").missing == [S.AC_SUPERPOSITION]
    assert S.feasibility(iso("4.6.3"), real_bench, dut, "12V").missing == [S.PULSE_MS]
    assert "AC ripple" in S.feasibility(iso("4.4"), real_bench, dut, "12V").reason
    overvoltage_24 = S.feasibility(iso("4.3.1.1"), real_bench, dut, "24V")
    assert S.ENDPOINT_REASON in overvoltage_24.reason and "36 V" in overvoltage_24.reason
    for number in ("4.6.4", "4.7", "4.10.2", "4.10.3"):
        reason = S.feasibility(iso(number), real_bench, dut, "12V").reason
        assert "§2" in reason and "§7.5" in reason, number
    reverse = S.feasibility(iso("4.7"), real_bench, dut, "12V")
    assert reverse.missing == [S.NEGATIVE_VOLTAGE], "policy wins even though the instrument is also missing"


def test_runnable_verdicts_carry_their_conditions(real_bench, mock_bench, dut):
    reset_12 = S.feasibility(iso("4.6.2"), mock_bench, dut, "12V")
    assert reset_12.status == "runs_after_approval" and reset_12.coverage == "full" and reset_12.needs_approval
    assert any("UVLO" in c and "§7.5" in c for c in reset_12.conditions)
    assert S.APPROVAL_HOW in reset_12.conditions
    assert any("1 A source" in c for c in reset_12.conditions)
    reset_12_real = S.feasibility(iso("4.6.2"), real_bench, dut, "12V")
    assert reset_12_real.status == "mock_only" and reset_12_real.coverage == "none"
    assert any("UVLO" in c and "§7.5" in c for c in reset_12_real.conditions), "the conditions travel with the verdict"
    dc_12 = S.feasibility(iso("4.2"), real_bench, dut, "12V")
    assert dc_12.status == "runs_here" and dc_12.coverage == "partial" and not dc_12.needs_approval
    assert any("t1/t2 holds and 1 V/s transitions are not reproduced" in c for c in dc_12.conditions)
    assert not any("UVLO" in c for c in dc_12.conditions), "code C's 9 V minimum is not below the DUT minimum"
    assert any("9.1 V" in c for c in dc_12.conditions)
    dc_24 = S.feasibility(iso("4.2"), real_bench, dut, "24V")
    assert any("26 V" in c for c in dc_24.conditions), "32 V exceeds the approved input overvoltage guard"
    assert not any("26 V" in c for c in S.feasibility(iso("4.2"), mock_bench, dut, "24V").conditions), \
        "the mock profile declares no approved guard, so the condition exists on the real profile only"
    slow_24 = S.feasibility(iso("4.5"), real_bench, dut, "24V")
    assert slow_24.status == "mock_only" and any("UVLO" in c for c in slow_24.conditions)
    micro = S.feasibility(iso("4.6.1.2"), real_bench, dut, "12V")
    assert micro.status == "needs_instrument" and micro.coverage == "partial"


def test_other_standards_are_not_on_this_bench(real_bench, dut):
    for standard_id in (S.ISO7637_2_ID, S.CISPR25_ID, S.ISO11452_ID, S.ISO10605_ID, S.ISO16750_3_ID, S.ISO16750_4_ID):
        for item in S.STANDARDS[standard_id].tests():
            for system in S.SYSTEMS:
                verdict = S.feasibility(item, real_bench, dut, system)
                assert verdict.status == "not_on_this_bench", (standard_id, verdict.reason)
                assert set(verdict.missing) & S.FACILITY_TOKENS
    pulses = S.STANDARDS[S.ISO7637_2_ID].tests()[0].parameters["12V"]
    assert {"pulse_1", "pulse_2a", "pulse_2b", "pulse_3a", "pulse_3b"} <= set(pulses)


def test_every_reason_is_one_plain_sentence(real_bench, mock_bench, dut):
    seen = 0
    for bench in (real_bench, mock_bench):
        for system in S.SYSTEMS:
            for category in S.catalog(bench, dut, system):
                for entry in category.entries:
                    reason = entry.feasibility.reason
                    assert reason.strip() and reason.endswith(".") and reason[0].isupper(), reason
                    assert ". " not in reason and "\n" not in reason and len(reason) < 320, reason
                    seen += 1
    assert seen == 4 * (4 + 19 + 1 + 3 + 2)


def test_endpoint_rule_and_bench_envelope(real_bench, dut):
    at_ceiling = dut.model_copy(update={"ratings": dut.ratings.model_copy(update={"input_voltage_max_V": 16.0})})
    verdict = S.feasibility(iso("4.2"), real_bench, at_ceiling, "12V")
    assert verdict.status == "outside_dut_rating" and S.ENDPOINT_REASON in verdict.reason
    below = dut.model_copy(update={"ratings": dut.ratings.model_copy(update={"input_voltage_max_V": 15.0})})
    verdict = S.feasibility(iso("4.2"), real_bench, below, "12V")
    assert verdict.status == "outside_dut_rating" and "exceeds" in verdict.reason
    wide = dut.model_copy(update={"ratings": dut.ratings.model_copy(update={"input_voltage_max_V": 60.0})})
    verdict = S.feasibility(iso("4.3.1.1"), real_bench, wide, "24V")
    assert verdict.status == "not_on_this_bench" and "35.8 V" in verdict.reason
    assert S.recipe_parameters(iso("4.2"), "12V", at_ceiling) is None


def test_system_argument_is_validated(real_bench, dut):
    with pytest.raises(ValueError):
        S.feasibility(iso("4.2"), real_bench, dut, "48V")
    with pytest.raises(ValueError):
        S.recipe_parameters(iso("4.2"), "48V", dut)
    with pytest.raises(KeyError):
        S.ISO16750_2.clause("4.99")


# --- recipe parameters ----------------------------------------------------------

def test_recipe_parameters_for_the_runnable_clauses(dut):
    dc_12 = S.recipe_parameters(iso("4.2"), "12V", dut)
    assert dc_12["supply_code"] == "C" and (dc_12["Usmin_V"], dc_12["Usmax_V"]) == (9.0, 16.0)
    assert dc_12["levels_V"] == [14.0, 9.0, 14.0, 16.0, 14.0] and dc_12["t2_s"] == 60.0 and dc_12["ramp_V_per_s"] == 1.0
    dc_24 = S.recipe_parameters(iso("4.2"), "24V", dut)
    assert dc_24["supply_code"] == "E" and dc_24["levels_V"] == [28.0, 10.0, 28.0, 32.0, 28.0]

    over_12 = S.recipe_parameters(iso("4.3.1.1"), "12V", dut)
    assert (over_12["level_V"], over_12["duration_s"]) == (18.0, 3600.0)
    assert S.recipe_parameters(iso("4.3.1.1"), "24V", dut) is None, "36 V equals the DUT ceiling"

    for system, start, steps in (("12V", 14.0, 700), ("24V", 28.0, 1400)):
        slow = S.recipe_parameters(iso("4.5"), system, dut)
        assert (slow["start_V"], slow["floor_V"], slow["rate_V_per_min"]) == (start, 0.0, 0.5)
        assert slow["step_V"] <= slow["max_step_V"] == 0.025
        assert slow["step_V"] / slow["step_interval_s"] * 60 == pytest.approx(0.5)
        assert slow["steps_per_direction"] == steps and slow["duration_per_direction_s"] == pytest.approx(steps * 2.4)
        assert slow["total_duration_s"] == pytest.approx(2 * start / 0.5 * 60)

    reset_12 = S.recipe_parameters(iso("4.6.2"), "12V", dut)
    lows = reset_12["low_levels_V"]
    assert len(lows) == 20 and lows[0] == pytest.approx(8.55) and lows[-1] == 0.0
    assert all(b < a for a, b in zip(lows, lows[1:]))
    assert (reset_12["low_hold_s"], reset_12["recovery_hold_s"], reset_12["recovery_level_V"]) == (5.0, 10.0, 9.0)
    assert reset_12["levels_below_dut_minimum"] == 20
    reset_24 = S.recipe_parameters(iso("4.6.2"), "24V", dut)
    assert reset_24["Usmin_V"] == 10.0 and reset_24["low_levels_V"][0] == pytest.approx(9.5)
    assert reset_24["levels_below_dut_minimum"] == 18

    micro = S.recipe_parameters(iso("4.6.1.2"), "12V", dut)
    assert micro["coverage"] == "partial" and micro["base_V"] == 12.0
    assert micro["test_case_1"]["interruption_s"][0] == 1.0 and micro["test_case_1"]["interruption_s"][-1] == 2.0
    assert micro["test_case_2"]["recovery_s"] == [float(k) for k in range(1, 11)]
    assert "10 MOhm" in micro["method_deviation"]


def test_recipe_parameters_are_none_for_everything_else(real_bench, dut):
    with_recipe = set(RUNNABLE) | {"4.6.1.2"}
    for item in S.ISO16750_2.clauses:
        for system in S.SYSTEMS:
            recipe = S.recipe_parameters(item, system, dut)
            expected_some = item.number in with_recipe and not (item.number == "4.3.1.1" and system == "24V")
            assert (recipe is not None) == expected_some, (item.number, system)
    for standard_id, standard in S.STANDARDS.items():
        if standard_id == S.ISO16750_2_ID:
            continue
        for item in standard.clauses:
            assert S.recipe_parameters(item, "12V", dut) is None
    for item in S.GENERIC_TESTS:
        assert S.recipe_parameters(item, "12V", dut) is None
    for category in S.catalog(real_bench, dut, "12V"):
        for entry in category.entries:
            if entry.clause.standard_id == S.ISO16750_2_ID and entry.feasibility.status in (*S.RUNNABLE_STATUSES, "mock_only", "needs_split"):
                assert entry.recipe is not None, entry.clause.number


# --- catalog ------------------------------------------------------------------------

def test_catalog_has_the_owners_five_categories(real_bench, dut):
    categories = S.catalog(real_bench, dut, "12V")
    assert [c.number for c in categories] == [1, 2, 3, 4, 5]
    assert [c.title for c in categories] == ["Normal operating voltage", "ISO 16750-2 supply profiles", "ISO 7637-2 transients",
                                             "EMC", "Environmental"]
    assert [c.candidate_for_bench for c in categories] == [True, True, False, False, False]
    assert [len(c.entries) for c in categories] == [4, 19, 1, 3, 2]
    iso_numbers = [e.clause.number for e in categories[1].entries]
    assert iso_numbers == [c.number for c in S.ISO16750_2.tests()]
    assert {e.clause.standard_id for e in categories[3].entries} == {S.CISPR25_ID, S.ISO11452_ID, S.ISO10605_ID}
    assert {e.clause.standard_id for e in categories[4].entries} == {S.ISO16750_3_ID, S.ISO16750_4_ID}


def test_generic_tests_map_to_existing_procedures(real_bench, dut):
    generic = S.catalog(real_bench, dut, "12V")[0].entries
    by_title = {e.clause.title: e for e in generic}
    assert set(by_title) == {"Input-voltage (VIN) sweep at fixed loads", "Efficiency versus output load",
                             "Load and line regulation", "Dropout and minimum-input behaviour"}
    for entry in generic:
        assert entry.feasibility.status == "runs_here", entry.clause.title
        assert entry.clause.procedure and entry.clause.procedure_status
    assert "steady_state_load_sweep" in by_title["Input-voltage (VIN) sweep at fixed loads"].clause.procedure
    assert "voltage_sweep.py" in by_title["Input-voltage (VIN) sweep at fixed loads"].clause.procedure
    assert "efficiency" in by_title["Efficiency versus output load"].clause.procedure
    assert "load_regulation" in by_title["Load and line regulation"].clause.procedure
    dropout = by_title["Dropout and minimum-input behaviour"]
    assert dropout.clause.procedure_status == "real_fixed", "the fixed startup/descent worker runs on the real bench"
    assert "uvlo.py" in dropout.clause.mock_only_part
    assert "startup_descent.py" in dropout.clause.procedure and "uvlo.py" in dropout.clause.procedure
    assert any("synthetic plant only" in c for c in dropout.feasibility.conditions)
    assert {e.clause.procedure_status for e in generic} == {"real_fixed"}
    assert all(e.clause.mock_only_part is None for e in generic if e.clause.number != "1.4")


def test_mock_and_real_verdicts_differ_only_where_procedure_deadline_or_guard_differ(real_bench, mock_bench, dut):
    """Both profiles earn the same tokens (the same instrument class; the mock's wider 60 V envelope changes nothing for
    a 36 V DUT because the rating is checked first), so every status difference is one of two things: the procedure
    exists on the synthetic plant only (4.5, 4.6.2) or the real path's run deadline applies (4.3.1.1 at 12 V). The
    approved 26 V guard of the real profile adds a condition to 4.2 at 24 V, not a status."""
    assert S.capabilities(mock_bench) == S.capabilities(real_bench)
    for system in S.SYSTEMS:
        mock = {(sid, n): s for sid, n, s in statuses(mock_bench, dut, system)}
        real = {(sid, n): s for sid, n, s in statuses(real_bench, dut, system)}
        assert set(mock) == set(real)
        differing = {key: (mock[key], real[key]) for key in mock if mock[key] != real[key]}
        expected = {(S.ISO16750_2_ID, "4.5"): ("runs_after_approval", "mock_only"),
                    (S.ISO16750_2_ID, "4.6.2"): ("runs_after_approval", "mock_only")}
        if system == "12V":
            expected[(S.ISO16750_2_ID, "4.3.1.1")] = ("runs_here", "needs_split")
        assert differing == expected, differing


# --- mock-only procedures, approval and the real path's deadline -----------------------

def test_mock_only_procedures_are_mock_only_on_a_real_bench_and_after_approval_on_the_mock(real_bench, mock_bench, dut):
    assert REAL_HARDWARE_NOT_APPROVED.startswith("is " + S.REAL_HARDWARE_REFUSAL), "the catalog repeats planning's refusal words"
    for number, test_type in (("4.5", "slow_supply_ramp"), ("4.6.2", "reset_staircase")):
        assert iso(number).procedure_status == "mock_only" and S.RECIPE_TEST_TYPES[iso(number).recipe_kind] == test_type
        for system in S.SYSTEMS:
            real = S.feasibility(iso(number), real_bench, dut, system)
            assert real.status == "mock_only" and real.coverage == "none", (number, system, real.reason)
            assert test_type in real.reason and "synthetic plant only" in real.reason and S.REAL_HARDWARE_REFUSAL in real.reason
            assert real.needs_approval and S.APPROVAL_HOW in real.conditions
            assert not any(c.startswith("Synthetic plant only") for c in real.conditions), "the verdict itself says so"
            mock = S.feasibility(iso(number), mock_bench, dut, system)
            assert mock.status == "runs_after_approval" and mock.coverage == "full", (number, system, mock.reason)
            assert "approved" in mock.reason and "§7.5" in mock.reason and mock.needs_approval
            assert S.APPROVAL_HOW in mock.conditions
            assert any(c.startswith("Synthetic plant only") and test_type in c and S.REAL_HARDWARE_REFUSAL in c for c in mock.conditions)
    assert "authorization.uvlo_approved" in S.APPROVAL_HOW and "protective_controls.policy_id" in S.APPROVAL_HOW
    for field in ("source_current_limit_A", "dut_output_overvoltage_V", "output_overcurrent_A"):
        assert field in S.APPROVAL_HOW, "every field planning.uvlo_approval_gaps checks is named"


def test_approval_verdict_follows_the_dut_minimum_not_the_clause(real_bench, mock_bench, dut):
    """4.2 needs no approval for the 12T12-4A (code C's 9 V is the DUT minimum). A converter whose minimum no supply code
    fits inside gets the reference code and, because its Usmin is below that minimum, the approval verdict on either bench."""
    for bench in (real_bench, mock_bench):
        assert S.feasibility(iso("4.2"), bench, dut, "12V").status == "runs_here"
    picky = dut.model_copy(update={"ratings": dut.ratings.model_copy(update={"input_voltage_min_V": 11.0})})
    for bench in (real_bench, mock_bench):
        verdict = S.feasibility(iso("4.2"), bench, picky, "12V")
        assert verdict.status == "runs_after_approval" and verdict.needs_approval, verdict.reason
        assert any("No 12V supply code fits" in c for c in verdict.conditions)
        assert any("11 V minimum" in c and "UVLO" in c for c in verdict.conditions)


def test_real_path_deadline_marks_long_recipes_needs_split(real_bench, mock_bench, dut):
    hold_real = S.feasibility(iso("4.3.1.1"), real_bench, dut, "12V")
    assert hold_real.status == "needs_split" and hold_real.longest_phase_s == 3600.0 and hold_real.coverage == "none"
    assert "3600 s hold" in hold_real.reason and "660 s software deadline" in hold_real.reason and "720 s source timer" in hold_real.reason
    hold_mock = S.feasibility(iso("4.3.1.1"), mock_bench, dut, "12V")
    assert hold_mock.status == "runs_here" and hold_mock.longest_phase_s == 3600.0, "the virtual clock has no deadline"
    assert any(c.startswith("On the real path the 3600 s hold exceeds the 660 s software deadline") for c in hold_mock.conditions)
    for system, per_direction in (("12V", 1680.0), ("24V", 3360.0)):
        ramp_real = S.feasibility(iso("4.5"), real_bench, dut, system)
        assert ramp_real.status == "mock_only" and ramp_real.longest_phase_s == per_direction, "mock-only wins; the deadline is a condition"
        assert any(f"Its {per_direction:g} s ramp per direction also exceeds" in c for c in ramp_real.conditions)
        ramp_mock = S.feasibility(iso("4.5"), mock_bench, dut, system)
        assert any(f"On the real path the {per_direction:g} s ramp per direction exceeds" in c for c in ramp_mock.conditions)
    staircase = S.feasibility(iso("4.6.2"), real_bench, dut, "12V")
    assert staircase.longest_phase_s == 295.0, "19 lows x 5 s + 20 recoveries x 10 s of declared holds"
    assert not any("exceeds" in c for c in staircase.conditions)
    dc = S.feasibility(iso("4.2"), real_bench, dut, "12V")
    assert dc.longest_phase_s == 60.0 and not any("exceeds" in c for c in dc.conditions)
    assert S.feasibility(iso("4.6.1.2"), real_bench, dut, "12V").longest_phase_s is None


def test_longest_phase_s_reads_the_recipe_kind(dut):
    assert S.longest_phase_s(None) is None
    assert S.longest_phase_s(S.recipe_parameters(iso("4.5"), "12V", dut)) == (1680.0, "ramp per direction")
    assert S.longest_phase_s(S.recipe_parameters(iso("4.3.1.1"), "12V", dut)) == (3600.0, "hold")
    assert S.longest_phase_s(S.recipe_parameters(iso("4.6.2"), "24V", dut)) == (295.0, "staircase of declared holds")
    assert S.longest_phase_s(S.recipe_parameters(iso("4.2"), "24V", dut)) == (60.0, "hold at one level")
    assert S.longest_phase_s(S.recipe_parameters(iso("4.6.1.2"), "12V", dut)) is None
    for number in ("4.2", "4.3.1.1", "4.5", "4.6.2", "4.6.1.2"):
        assert S.recipe_parameters(iso(number), "12V", dut)["recipe_kind"] == iso(number).recipe_kind


def test_real_path_constants_match_the_real_workers_without_importing_them():
    """The catalog repeats the real workers' envelope as numbers; this pins them to the source without importing a driver module."""
    assert (S.REAL_PLANNING_BUDGET_S, S.REAL_SOFTWARE_DEADLINE_S, S.REAL_SOURCE_TIMER_S) == (540.0, 660.0, 720.0)
    extended = (ROOT / "src" / "dcdc_bench" / "extended.py").read_text(encoding="utf-8")
    assert f"SOFTWARE_DEADLINE_S, HARDWARE_DEADLINE_S = {int(S.REAL_SOFTWARE_DEADLINE_S)}, {int(S.REAL_SOURCE_TIMER_S)}" in extended
    backend = (ROOT / "src" / "dcdc_bench" / "real_backend.py").read_text(encoding="utf-8")
    assert f"if seconds > {int(S.REAL_PLANNING_BUDGET_S)}:" in backend


# --- bench page rows and cards (standard_recipes) ---------------------------------------

def test_bench_page_rows_badge_mock_only_and_after_approval_and_never_pretick_them(real_bench, mock_bench, dut):
    mock_rows = {row["number"]: row for row in R.clause_rows(mock_bench, dut, "12V")}
    real_rows = {row["number"]: row for row in R.clause_rows(real_bench, dut, "12V")}
    assert len(mock_rows) == len(real_rows) == 19
    assert mock_rows["4.2"]["badge"] == "runs_here" and mock_rows["4.2"]["badge_label"] == "DC level subset"
    assert "not reproduced" in mock_rows["4.2"]["text"]
    assert "t1" not in mock_rows["4.2"]["levels"]
    assert mock_rows["4.2"]["tickable"] and mock_rows["4.2"]["ticked_by_default"] and not mock_rows["4.2"]["needs_approval"]
    assert mock_rows["4.2"]["approval"] is None and mock_rows["4.2"]["test_type"] == "steady_state_load_sweep"
    for number, test_type in (("4.5", "slow_supply_ramp"), ("4.6.2", "reset_staircase")):
        row = mock_rows[number]
        assert row["badge"] == "runs_after_approval" and row["badge_label"] == "runs here after approval"
        assert row["tickable"] and not row["ticked_by_default"] and row["needs_approval"]
        assert row["approval"] == S.APPROVAL_HOW == row["text"] and row["test_type"] == test_type
        real_row = real_rows[number]
        assert real_row["badge"] == "mock_only" and real_row["badge_label"] == "mock only" and real_row["status"] == "mock_only"
        assert not real_row["tickable"] and not real_row["ticked_by_default"] and real_row["test_type"] is None
        assert "synthetic plant only" in real_row["text"] and S.REAL_HARDWARE_REFUSAL in real_row["text"]
        assert real_row["needs_approval"] and real_row["approval"] == S.APPROVAL_HOW
    assert real_rows["4.3.1.1"]["badge"] == "procedure_pending" and real_rows["4.3.1.1"]["status"] == "needs_split"
    assert real_rows["4.3.1.1"]["badge_label"] == "procedure not yet implemented" and "540 s" in real_rows["4.3.1.1"]["text"]
    assert mock_rows["4.3.1.1"]["badge"] == "procedure_pending" and mock_rows["4.3.1.1"]["status"] == "runs_here"
    assert set(R.BADGE_LABELS) >= {"runs_here", "runs_after_approval", "mock_only", "needs_split", "procedure_pending"}
    assert R.TICKABLE_BADGES == ("runs_here", "runs_after_approval") and set(R.TICKABLE_BADGES) == S.RUNNABLE_STATUSES
    for rows in (mock_rows, real_rows):
        assert all(row["tickable"] or not row["ticked_by_default"] for row in rows.values())
        assert all(row["badge"] in R.TICKABLE_BADGES or not row["tickable"] for row in rows.values())


def test_bench_page_card_counts_now_after_approval_and_mock_only_separately(real_bench, mock_bench, dut):
    mock_card = R.standard_cards(mock_bench, dut, "12V")[0]
    assert (mock_card["runnable_count"], mock_card["after_approval_count"], mock_card["mock_only_count"],
            mock_card["tickable_count"]) == (1, 2, 0, 3)
    assert mock_card["summary"] == "1 DC level subset available, 2 after approval" and mock_card["summary"] in mock_card["subtitle"]
    assert mock_card["runnable"] and mock_card["reason"] is None and mock_card["clause_count"] == 19
    for system in S.SYSTEMS:
        real_card = R.standard_cards(real_bench, dut, system)[0]
        assert (real_card["runnable_count"], real_card["after_approval_count"], real_card["mock_only_count"],
                real_card["tickable_count"]) == (1, 0, 2, 1), system
        assert real_card["summary"] == "1 DC level subset available, 2 mock only (simulated bench)" and real_card["runnable"]
    assert R.card_summary([]) == "0 DC level subsets available"
    # The page renders one standards card. The laboratories this bench will never be (transients, EMC, mechanical,
    # climatic) stay catalog entries and one footnote; they are not cards nobody can select.
    assert [card["id"] for card in R.standard_cards(mock_bench, dut, "12V")] == [S.ISO16750_2_ID]
    assert set(R.STANDARD_CARD_TITLES) == {S.ISO16750_2_ID}
    others = (S.ISO7637_2_ID, S.CISPR25_ID, S.ISO11452_ID, S.ISO10605_ID, S.ISO16750_3_ID, S.ISO16750_4_ID)
    assert all(standard_id in S.STANDARDS for standard_id in others), "the catalog itself keeps them"
    assert {e.clause.standard_id for c in S.catalog(mock_bench, dut, "12V") for e in c.entries} >= set(others)
    for name in ("ISO 7637-2", "CISPR 25", "ISO 11452", "ISO 10605", "ISO 16750-3/-4", "other laboratories", "standards catalog"):
        assert name in R.OTHER_LABORATORIES_NOTE, name


def test_generated_mock_only_recipes_ship_unapproved_and_say_where_approval_happens(mock_bench, dut):
    for number in ("4.5", "4.6.2"):
        recipe = R.build_recipe(number, "12V", dut, mock_bench)
        assert recipe["authorization"]["uvlo_approved"] is False, "approval is the owner's act (brief 7.5), never generated"
        assert S.APPROVAL_HOW in recipe["description"] and "not yet approved for real hardware" in recipe["description"]
    ramp = R.build_recipe("4.5", "12V", dut, mock_bench)
    assert "1680 s ramp per direction exceeds the real path's 660 s deadline" in ramp["description"]
    assert S.APPROVAL_HOW not in R.build_recipe("4.2", "12V", dut, mock_bench)["description"]


@pytest.mark.skipif(not WORKSPACE_REAL_BENCH.exists(), reason="seeded workspace bench profile is not present on this checkout")
def test_seeded_workspace_profile_matches_the_inline_replica(real_bench, dut):
    seeded = load_profile(WORKSPACE_REAL_BENCH, BenchProfile)
    assert S.capabilities(seeded) == S.capabilities(real_bench)
    assert S.envelope(seeded) == S.envelope(real_bench)
    for system in S.SYSTEMS:
        assert statuses(seeded, dut, system) == statuses(real_bench, dut, system)


def test_documentation_cites_every_clause_without_reproducing_text():
    page = (ROOT / "docs" / "standards" / "iso16750-2.md").read_text(encoding="utf-8")
    for number, title in EXPECTED_ISO16750_2_CLAUSES.items():
        assert f"| {number} | {title} |" in page, number
    assert "ISO 16750-2:2023, clause 4" in page
    assert "figure value" in page, "values that exist only in a figure of the standard are flagged"
    assert "to be verified against the owner's copy" in page, "edition history and the 24 V reversed level are not asserted"
    assert "None of these recipes exists" not in page and "same verdicts" not in page
    assert "mock only" in page and "runs here after approval" in page and "needs split" in page
    readme = (ROOT / "docs" / "standards" / "README.md").read_text(encoding="utf-8")
    assert all(status in readme for status in ("runs_after_approval", "mock_only", "needs_split")), "every verdict is defined"
    assert "same verdicts" not in readme
    assert "to be verified against the owner's copy" in iso("4.7").parameters["24V"]["to_verify"]
    assert any("to be verified against the owner's copy" in note for note in S.ISO16750_2.notes)
