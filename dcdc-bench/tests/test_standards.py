"""Honest automotive test catalog: clause list, capability tokens and per-clause verdicts.

The seeded real bench profile lives in the gitignored workspace, so the tests
carry an inline replica of the fields that matter (source envelope, load,
approved protective controls). When the workspace file is present it is
checked against the replica as well.
"""
import os
from pathlib import Path

import pytest

from dcdc_bench import standards as S
from dcdc_bench.domain import BenchProfile, DutProfile
from dcdc_bench.planning import load_profile

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
    ("4.5", "12V", "runs_here"), ("4.5", "24V", "runs_here"),
    ("4.6.2", "12V", "runs_here"), ("4.6.2", "24V", "runs_here"),
    ("4.3.1.1", "12V", "runs_here"), ("4.3.1.1", "24V", "outside_dut_rating"),
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


def test_runs_here_verdicts_carry_their_conditions(real_bench, dut):
    reset_12 = S.feasibility(iso("4.6.2"), real_bench, dut, "12V")
    assert reset_12.coverage == "full"
    assert any("UVLO" in c and "§7.5" in c for c in reset_12.conditions)
    assert any("1 A source" in c for c in reset_12.conditions)
    dc_12 = S.feasibility(iso("4.2"), real_bench, dut, "12V")
    assert dc_12.coverage == "room_temperature_only"
    assert not any("UVLO" in c for c in dc_12.conditions), "code C's 9 V minimum is not below the DUT minimum"
    assert any("9.1 V" in c for c in dc_12.conditions)
    dc_24 = S.feasibility(iso("4.2"), real_bench, dut, "24V")
    assert any("26 V" in c for c in dc_24.conditions), "32 V exceeds the approved input overvoltage guard"
    slow_24 = S.feasibility(iso("4.5"), real_bench, dut, "24V")
    assert any("UVLO" in c for c in slow_24.conditions)
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
            if entry.feasibility.status == "runs_here" and entry.clause.standard_id == S.ISO16750_2_ID:
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
    assert dropout.clause.procedure_status == "mock_only"
    assert "startup_descent.py" in dropout.clause.procedure and "uvlo.py" in dropout.clause.procedure
    assert any("synthetic plant only" in c for c in dropout.feasibility.conditions)
    assert {e.clause.procedure_status for e in generic} == {"real_fixed", "mock_only"}


def test_mock_bench_yields_the_same_statuses_as_the_real_bench(real_bench, mock_bench, dut):
    """Tokens describe the class of instrument a profile declares, not whether it is simulated.

    The mock emulates the same single-quadrant, LAN-polled DC supply; its wider
    60 V envelope changes nothing for a 36 V DUT because the DUT rating is
    checked first.
    """
    for system in S.SYSTEMS:
        assert statuses(mock_bench, dut, system) == statuses(real_bench, dut, system)


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
    assert (ROOT / "docs" / "standards" / "README.md").exists()
    assert "figure value" in page, "values that exist only in a figure of the standard are flagged"
