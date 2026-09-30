"""The bench page's automotive-standards checklist and the recipes it generates.

Reads ``standards.catalog`` for the selected bench, converter and system class
and turns it into what the page shows: one card per standard, and for
ISO 16750-2 one row per clause with a badge (``runs here``, ``procedure not
yet implemented``, or the grey reason). ``build_recipe`` turns a tickable
clause into a saved-recipe dict for ``JobService.save_profile('recipe', ...)``:

* clause 4.2 -> an existing-type ``steady_state_load_sweep`` at UA, Usmin and
  Usmax with a small load grid (levels outside the bench envelope stay in the
  plan and the planner explains them; nothing is dropped);
* clause 4.5 -> ``slow_supply_ramp`` (mock only): observation levels every
  1 V from UA down to the floor and back, walked in 20 mV live steps every
  2.4 s (0.5 V/min);
* clause 4.6.2 -> ``reset_staircase`` (mock only): Usmin alternating with the
  5 % lows of Usmin, held >= 5 s / >= 10 s.

Profiles that step below the DUT's stated minimum ship unapproved
(``authorization.uvlo_approved`` false): the planner blocks them until the
owner approves the recipe under the bench's protective policy (brief 7.5),
exactly as the shipped UVLO example does. Nothing here opens an instrument.
"""
from __future__ import annotations

from typing import Any

from . import standards as S
from .domain import RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE, BenchProfile, DutProfile, TestRecipe

STANDARDS_GROUP = "Automotive supply standards"
ISO16750_2_CATEGORY = "ISO 16750-2 supply profiles"
STANDARD_CARD_TITLES = {
    S.ISO16750_2_ID: "ISO 16750-2:2023 — electrical loads",
    S.ISO7637_2_ID: "ISO 7637-2:2011 — conducted transients",
    S.CISPR25_ID: "CISPR 25:2021 — emissions",
    S.ISO11452_ID: "ISO 11452 — radiated immunity",
    S.ISO10605_ID: "ISO 10605:2023 — electrostatic discharge",
    S.ISO16750_3_ID: "ISO 16750-3:2023 — mechanical loads",
    S.ISO16750_4_ID: "ISO 16750-4:2023 — climatic loads",
}
CLAUSE_SHORT_NAMES = {"4.2": "supply voltage range", "4.3.1.1": "long-term overvoltage hold",
                      "4.5": "slow decrease and increase", "4.6.1.2": "micro-interruptions", "4.6.2": "reset staircase"}
SHORT_INSTRUMENT_NAMES = {
    S.EDGE_10MS: "10 ms edges", S.NEGATIVE_VOLTAGE: "bipolar source", S.AC_SUPERPOSITION: "AC ripple source",
    S.PULSE_MS: "ms pulse generator", S.PULSE_US: "µs switch", S.LOW_SOURCE_IMPEDANCE_PULSE: "low-impedance pulse generator",
    S.LINE_SWITCH: "10 MΩ line switch", S.FLOATING_OFFSET_SOURCE: "floating offset source",
    S.SHORT_CIRCUIT_FIXTURE: "short-circuit fixture", S.HIPOT_TESTER: "hipot tester", S.INSULATION_TESTER: "insulation tester",
    S.TRANSIENT_GENERATOR: "transient generator", S.EMC_CHAMBER: "EMC chamber", S.ESD_SIMULATOR: "ESD simulator",
    S.SHAKER: "shaker", S.CLIMATIC_CHAMBER: "climatic chamber",
}
BADGE_LABELS = {"runs_here": "runs here", "procedure_pending": "procedure not yet implemented",
                "not_on_this_bench": "not on this bench", "outside_dut_rating": "outside DUT rating",
                "excluded_by_policy": "excluded by policy", "not_applicable": "not applicable"}
# Fixed light load for the mock supply profiles; rated-load mode 3.4 is not reachable from the 1 A source.
PROFILE_LOAD_A = 0.1
DC_LOAD_GRID_A = [0.1, 0.25, 0.5]
RAMP_OBSERVATION_STEP_V = 1.0
# The purpose-limited real backend's source envelope starts at 1 V; the standard's 0 V end level is not a
# positive source setpoint the planner accepts, so the profiles end at this floor and record the deviation.
RAMP_FLOOR_V = 1.0
DEFAULT_OUTPUT_TOLERANCE_PCT = 10.0


def _models(bench: BenchProfile | dict, dut: DutProfile | dict) -> tuple[BenchProfile, DutProfile]:
    bench_model = bench if isinstance(bench, BenchProfile) else BenchProfile.model_validate(bench)
    dut_model = dut if isinstance(dut, DutProfile) else DutProfile.model_validate(dut)
    return bench_model, dut_model


def default_system(dut: DutProfile | dict) -> str:
    """The converter's remembered system class, else 12 V."""
    remembered = dut.system_voltage_class if isinstance(dut, DutProfile) else dut.get("system_voltage_class")
    return remembered if remembered in S.SYSTEMS else "12V"


def badge(entry: S.CatalogEntry) -> dict[str, Any]:
    """Badge kind, label and whether the row can be ticked, from the clause's verdict and procedure state."""
    clause, verdict = entry.clause, entry.feasibility
    if verdict.status == "runs_here" and clause.procedure_status in ("recipe", "mock_only") and entry.recipe is not None:
        return {"kind": "runs_here", "label": BADGE_LABELS["runs_here"], "tickable": True, "text": None}
    if clause.procedure_gap and verdict.status in ("runs_here", "needs_instrument"):
        return {"kind": "procedure_pending", "label": BADGE_LABELS["procedure_pending"], "tickable": False,
                "text": clause.procedure_gap}
    if verdict.status == "needs_instrument":
        names = [SHORT_INSTRUMENT_NAMES.get(token, token) for token in verdict.missing if token in S.INSTRUMENT_TOKENS]
        label = "needs " + (", ".join(names[:2]) if names else "another instrument")
        return {"kind": "needs_instrument", "label": label, "tickable": False, "text": verdict.reason}
    return {"kind": verdict.status, "label": BADGE_LABELS.get(verdict.status, verdict.status.replace("_", " ")),
            "tickable": False, "text": verdict.reason}


def levels_text(entry: S.CatalogEntry, system: str) -> str:
    """The clause's concrete levels for this system and converter, one short phrase."""
    recipe, number = entry.recipe, entry.clause.number
    if recipe is None:
        params = entry.clause.parameters.get(system, {})
        if number == "4.3.1.1" and "level_V" in params:
            return f"{params['level_V']:g} V for {params['duration_s'] / 60:g} min"
        return ""
    if number == "4.2":
        return (f"code {recipe['supply_code']}: UA {recipe['UA_V']:g} V, Usmin {recipe['Usmin_V']:g} V, "
                f"Usmax {recipe['Usmax_V']:g} V; t1 {recipe['t1_s']:g} s, t2 {recipe['t2_s']:g} s")
    if number == "4.3.1.1":
        return f"{recipe['level_V']:g} V for {recipe['duration_s'] / 60:g} min"
    if number == "4.5":
        return (f"{recipe['start_V']:g} V → {RAMP_FLOOR_V:g} V → {recipe['start_V']:g} V at {recipe['rate_V_per_min']:g} V/min "
                f"({recipe['step_V'] * 1000:g} mV every {recipe['step_interval_s']:g} s)")
    if number == "4.6.1.2":
        return f"base {recipe['base_V']:g} V; interruptions of 1 s and longer only"
    if number == "4.6.2":
        lows = recipe["low_levels_V"]
        positive = [v for v in lows if v > 0]
        return (f"code {recipe['supply_code']}: Usmin {recipe['Usmin_V']:g} V, lows {positive[0]:g} … {positive[-1]:g} V "
                f"in 5 % steps; holds ≥ {recipe['low_hold_s']:g} s / ≥ {recipe['recovery_hold_s']:g} s")
    return ""


def clause_rows(bench: BenchProfile | dict, dut: DutProfile | dict, system: str) -> list[dict[str, Any]]:
    """One row per ISO 16750-2 test clause for the checklist: badge, tickability, reason, conditions and levels."""
    bench_model, dut_model = _models(bench, dut)
    category = next(c for c in S.catalog(bench_model, dut_model, system) if c.id == S.CATEGORY_ISO16750_2)
    rows = []
    for entry in category.entries:
        kind = badge(entry)
        rows.append({"number": entry.clause.number, "title": entry.clause.title, "citation": entry.clause.citation,
                     "status": entry.feasibility.status, "badge": kind["kind"], "badge_label": kind["label"],
                     "tickable": kind["tickable"], "text": kind["text"], "reason": entry.feasibility.reason,
                     "conditions": list(entry.feasibility.conditions), "levels": levels_text(entry, system),
                     "test_type": {"4.2": "steady_state_load_sweep", "4.5": SLOW_SUPPLY_RAMP_TEST_TYPE,
                                   "4.6.2": RESET_STAIRCASE_TEST_TYPE}.get(entry.clause.number) if kind["tickable"] else None})
    return rows


def standard_cards(bench: BenchProfile | dict, dut: DutProfile | dict, system: str) -> list[dict[str, Any]]:
    """One card per standard in catalog order; a standard with no tickable clause carries its one-sentence reason."""
    bench_model, dut_model = _models(bench, dut)
    rows = clause_rows(bench_model, dut_model, system)
    runnable = sum(1 for row in rows if row["tickable"])
    cards = [{"id": S.ISO16750_2_ID, "title": STANDARD_CARD_TITLES[S.ISO16750_2_ID],
              "subtitle": "Section 4 supply profiles as a clause checklist", "runnable": runnable > 0,
              "reason": None if runnable else "No clause of section 4 can run on this bench for this converter",
              "runnable_count": runnable, "clause_count": len(rows), "expandable": True}]
    verdicts = {(e.clause.standard_id): e.feasibility for c in S.catalog(bench_model, dut_model, system) for e in c.entries}
    for standard_id, standard in S.STANDARDS.items():
        if standard_id == S.ISO16750_2_ID:
            continue
        verdict = verdicts.get(standard_id)
        cards.append({"id": standard_id, "title": STANDARD_CARD_TITLES.get(standard_id, standard_id),
                      "subtitle": "; ".join(c.title for c in standard.tests()), "runnable": False,
                      "reason": verdict.reason if verdict else "not on this bench", "runnable_count": 0,
                      "clause_count": len(standard.tests()), "expandable": False})
    return cards


# --- recipe generation ---------------------------------------------------------------------------

def _thresholds(dut: DutProfile) -> tuple[float, float]:
    nominal = dut.ratings.output_voltage_nominal_V
    tolerance = dut.acceptance.output_voltage_tolerance_pct or DEFAULT_OUTPUT_TOLERANCE_PCT
    return round(nominal * (1 - tolerance / 100), 3), round(nominal * 0.1, 3)


def _title(number: str, system: str) -> str:
    return f"ISO 16750-2 §{number} — {CLAUSE_SHORT_NAMES[number]} ({system[:-1]} V system)"


def recipe_id_for(number: str, system: str) -> str:
    return f"iso16750-2-{number.replace('.', '-')}-{system.lower()}"


def _base(number: str, system: str, dut: DutProfile, bench: BenchProfile) -> dict[str, Any]:
    return {"schema_version": "1.0", "recipe_id": recipe_id_for(number, system), "dut_profile_id": dut.profile_id,
            "execution_mode": None, "title": _title(number, system), "category": ISO16750_2_CATEGORY,
            "standard_clause": f"{S.ISO16750_2_ID} §{number}",
            "planning": {"efficiency_estimate_fraction": 0.8, "source_current_budget_fraction": 0.9,
                         "infeasible_point_policy": "record_and_skip", "assumption_status": "planning_only_not_measured",
                         "auxiliary_input_power_estimate_W": 0.0, "input_wiring_drop_allowance_V": 0.0},
            "settling": {"policy": "electrical", "settings_origin": "draft_requires_bench_validation", "minimum_dwell_s": 5.0,
                         "window_s": 5.0, "minimum_fresh_samples": 5, "maximum_vout_span_V": 0.05, "timeout_s": 30.0},
            "acquisition": {"duration_s": 5.0, "target_poll_interval_s": 0.5, "minimum_complete_cycles": 5,
                            "maximum_interchannel_skew_s": 0.5, "settings_origin": "draft_requires_driver_timing_validation"},
            "authorization": {"require_operator_arming": True, "allow_unattended": False,
                              "protective_policy_id": bench.protective_controls.policy_id, "uvlo_approved": False}}


def ramp_levels(start_V: float, floor_V: float, observation_step_V: float = RAMP_OBSERVATION_STEP_V) -> list[float]:
    """Observation levels of the 4.5 profile: start, every ``observation_step_V`` down to the floor, and back up."""
    down = [start_V]
    level = start_V
    while level - observation_step_V > floor_V + 1e-9:
        level = round(level - observation_step_V, 4)
        down.append(level)
    if down[-1] != floor_V:
        down.append(floor_V)
    return down + down[-2::-1]


def staircase_levels(usmin_V: float, lows_V: list[float]) -> list[float]:
    """The 4.6.2 sequence: Usmin, first low, Usmin, second low, ... ending on Usmin; the 0 V end level is not requested."""
    positive = [v for v in lows_V if v > 0]
    levels = [usmin_V]
    for low in positive:
        levels += [low, usmin_V]
    return levels


def build_recipe(number: str, system: str, dut: DutProfile | dict, bench: BenchProfile | dict) -> dict[str, Any]:
    """A saved-recipe dict for a tickable ISO 16750-2 clause; validated against ``TestRecipe`` before it is returned."""
    bench_model, dut_model = _models(bench, dut)
    clause = S.ISO16750_2.clause(number)
    params = S.recipe_parameters(clause, system, dut_model)
    if params is None:
        raise ValueError(f"{clause.citation} derives no recipe for a {system} system and this converter")
    ratings = dut_model.ratings
    on_minimum, off_maximum = _thresholds(dut_model)
    data = _base(number, system, dut_model, bench_model)
    if number == "4.2":
        levels = [params["UA_V"], params["Usmin_V"], params["Usmax_V"]]
        data["tests"] = [{"id": f"iso16750-2-4-2-{system.lower()}", "type": "steady_state_load_sweep",
                          "input_voltage_targets_V": levels, "output_current_targets_A": list(DC_LOAD_GRID_A),
                          "derived_results": ["efficiency", "power_loss", "load_regulation", "line_regulation_on_common_valid_grid"]}]
        data["acquisition"].update(duration_s=8.0, target_poll_interval_s=1.0)
        data["description"] = (f"{clause.citation}: supply code {params['supply_code']} for a {system[:-1]} V system. Each level "
                               f"(UA {params['UA_V']:g} V, Usmin {params['Usmin_V']:g} V, Usmax {params['Usmax_V']:g} V) is a "
                               "separate cold-started DC point at each load of the small grid; the t1/t2 hold profile of Table 2 "
                               "and the 1 V/s transitions are not reproduced. A level outside the bench envelope or the "
                               "protective guard stays in the plan with the planner's reason. Room temperature only "
                               "(operating mode 3.2); rated-load mode 3.4 is not reachable from the 1 A source.")
    elif number == "4.5":
        start = params["start_V"]
        levels = ramp_levels(start, RAMP_FLOOR_V)
        data["tests"] = [{"id": f"iso16750-2-4-5-{system.lower()}", "type": SLOW_SUPPLY_RAMP_TEST_TYPE,
                          "input_voltage_targets_V": levels, "output_current_targets_A": [PROFILE_LOAD_A],
                          "supply_profile": {"floor_V": RAMP_FLOOR_V, "startup_interval_s": 5.0,
                                             "output_on_minimum_V": on_minimum, "output_off_maximum_V": off_maximum,
                                             "expected_off_below_V": ratings.input_voltage_min_V,
                                             "expected_on_above_V": ratings.input_voltage_min_V,
                                             "step_V": params["step_V"], "step_interval_s": params["step_interval_s"]}}]
        data["description"] = (f"{clause.citation}: {start:g} V down to {RAMP_FLOOR_V:g} V and back at "
                               f"{params['rate_V_per_min']:g} V/min, realised as {params['step_V'] * 1000:g} mV live steps every "
                               f"{params['step_interval_s']:g} s at the ~1 s command cadence, with a qualified observation every "
                               f"{RAMP_OBSERVATION_STEP_V:g} V at a fixed {PROFILE_LOAD_A:g} A load. Output-off is a recorded state "
                               f"below the converter's stated {ratings.input_voltage_min_V:g} V minimum; at or above it the output "
                               "must stay in band. The standard's 0 V end level is not requested (a 0 V source setpoint is outside "
                               f"the planner's positive-input rule); the profile ends at {RAMP_FLOOR_V:g} V and the report records "
                               "that deviation. Synthetic plant only: not yet approved for real hardware. Levels below the stated "
                               "minimum take the approved UVLO-style path (brief 7.5): approve this recipe under the bench's "
                               "protective policy before it will plan as executable.")
    elif number == "4.6.2":
        levels = staircase_levels(params["Usmin_V"], params["low_levels_V"])
        data["tests"] = [{"id": f"iso16750-2-4-6-2-{system.lower()}", "type": RESET_STAIRCASE_TEST_TYPE,
                          "input_voltage_targets_V": levels, "output_current_targets_A": [PROFILE_LOAD_A],
                          "supply_profile": {"floor_V": min(levels), "startup_interval_s": 5.0,
                                             "output_on_minimum_V": on_minimum, "output_off_maximum_V": off_maximum,
                                             "expected_off_below_V": ratings.input_voltage_min_V,
                                             "expected_on_above_V": ratings.input_voltage_min_V,
                                             "low_hold_s": params["low_hold_s"], "recovery_hold_s": params["recovery_hold_s"]}}]
        lows = [v for v in params["low_levels_V"] if v > 0]
        data["description"] = (f"{clause.citation}: supply code {params['supply_code']}, Usmin {params['Usmin_V']:g} V alternating "
                               f"with {len(lows)} lows from {lows[0]:g} V to {lows[-1]:g} V in 5 % steps of Usmin, each low held at "
                               f"least {params['low_hold_s']:g} s and each recovery at least {params['recovery_hold_s']:g} s at a fixed "
                               f"{PROFILE_LOAD_A:g} A load (rated-load mode 3.4 is not reachable from the 1 A source). Output-off is a "
                               f"recorded state at lows below the converter's stated {ratings.input_voltage_min_V:g} V minimum; at every "
                               "recovery level the output must be back in band. The standard's 0 V end level is not requested "
                               "(a 0 V source setpoint is outside the planner's positive-input rule); the report records that "
                               "deviation. Synthetic plant only: not yet approved for real hardware. Lows below the stated minimum "
                               "take the approved UVLO-style path (brief 7.5): approve this recipe under the bench's protective "
                               "policy before it will plan as executable.")
    else:
        raise ValueError(f"{clause.citation} has no recipe generator yet")
    return TestRecipe.model_validate(data).model_dump()
