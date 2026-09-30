"""Honest automotive test catalog: which standard clauses this bench can run.

The bench page groups tests by purpose; a standard appears as a checklist whose
clauses are individually tickable. This module is the data behind that page.
It never opens an instrument and imports only the project's contracts.

What it contains
----------------
* ``Standard`` / ``Clause`` records for ISO 16750-2:2023 section 4 (every
  clause, with the 12 V and 24 V parameters as technical facts), one entry for
  ISO 7637-2 and one entry each for CISPR 25, ISO 11452, ISO 10605,
  ISO 16750-3 and ISO 16750-4. Clause numbers and titles are cited; the
  standard's text is not reproduced (implementation brief §16).
* Four generic "normal operating voltage" tests mapped to the procedures the
  project already has (``steady_state_load_sweep`` recipes, the fixed real
  workers, the startup/descent run and the mock-only UVLO ramp).
* ``capabilities(bench)``: the capability tokens a bench profile earns.
* ``feasibility(clause, bench, dut, system)``: one plain-sentence verdict.
* ``catalog(bench, dut, system)``: the owner's five categories with verdicts.
* ``recipe_parameters(clause, system, dut)``: concrete levels, holds and ramp
  rates for the clauses that run here.

Capability tokens (bench profile -> tokens)
-------------------------------------------
Tokens describe the *class* of instrument the profile declares, not whether it
is simulated: the mock bench emulates the same single-quadrant, LAN-polled DC
supply, so it earns exactly the same tokens as the real DP821A profile.

Granted from any profile whose source declares a positive ``max_voltage_V``:

``dc_steady``
    A programmed DC level held for 30 s or longer.
``dc_step_1s``
    Programmed DC level changes with holds of 1 s or more (the LAN command
    cadence is about 1 s). The step edge is the supply's own, uncharacterised
    slew; it is never presented as a defined pulse edge.
``dc_ramp_slow``
    A ramp of about 1 V/s or slower, realised as bounded live steps (at most
    1 V per step, at least 1 s per step). A 0.5 V/min ramp in 20 mV steps is
    inside this; a 1 V/s ramp is at its limit.

Never granted from today's profiles (the fields to declare them do not exist,
and the DP800 family cannot do them):

``edge_10ms``
    A rise or fall guaranteed to complete within 10 ms.
``negative_voltage``
    Output below 0 V. ``InstrumentCapabilities.min_voltage_V`` is constrained
    to be non-negative, so no profile can claim this; a bipolar source would
    need a new contract field.
``ac_superposition``
    Sinusoidal ripple superimposed on the DC level (10 Hz to 200 kHz).
``pulse_ms``
    Pulses and edges defined in milliseconds (cranking, transient overvoltage,
    momentary drop).
``pulse_us``
    Interruptions and edges defined in microseconds.
``low_source_impedance_pulse``
    A pulse generator with a defined 0.5 Ohm to 8 Ohm source impedance.
``line_switch_10Mohm``
    A series switch that opens to at least 10 MOhm within 10 ms (or 10 us).
``floating_offset_source``
    A second, floating source for +/-1 V ground and supply offsets.
``short_circuit_fixture``
    Switched shorts of signal and load lines to supply and ground.
``hipot_tester`` / ``insulation_tester``
    500 V AC withstand and 500 V DC insulation-resistance instruments.

Facility tokens (a missing one means the test belongs to a different lab, not
to a supply/load bench): ``iso7637_transient_generator``, ``emc_chamber``,
``esd_simulator``, ``shaker``, ``climatic_chamber``.

Numeric bounds come from the profile, not from tokens: ``envelope(bench)``
returns the source ``max_voltage_V``, ``max_current_A``, ``max_power_W`` and
the approved protective input ceiling.

Policy exclusions (implementation brief §2 and §7.5)
----------------------------------------------------
Reverse voltage, short circuit, overload and load dump are fault-injection
tests that this release excludes even if an instrument existed. Steps below
the DUT's stated minimum input are allowed only through the approved
UVLO-style recipe path; a level equal to the DUT maximum is refused because
the endpoint method is not approved (the project programs 35.8 V for a
nominal 36 V). Ordinary supply/load polling is never labelled as a ripple,
transient, inrush or load-step measurement.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .domain import BenchProfile, Contract, DutProfile

System = Literal["12V", "24V"]
SYSTEMS: tuple[str, ...] = ("12V", "24V")

# --- capability tokens -----------------------------------------------------
DC_STEADY = "dc_steady"
DC_STEP_1S = "dc_step_1s"
DC_RAMP_SLOW = "dc_ramp_slow"
EDGE_10MS = "edge_10ms"
NEGATIVE_VOLTAGE = "negative_voltage"
AC_SUPERPOSITION = "ac_superposition"
PULSE_MS = "pulse_ms"
PULSE_US = "pulse_us"
LOW_SOURCE_IMPEDANCE_PULSE = "low_source_impedance_pulse"
LINE_SWITCH = "line_switch_10Mohm"
FLOATING_OFFSET_SOURCE = "floating_offset_source"
SHORT_CIRCUIT_FIXTURE = "short_circuit_fixture"
HIPOT_TESTER = "hipot_tester"
INSULATION_TESTER = "insulation_tester"
TRANSIENT_GENERATOR = "iso7637_transient_generator"
EMC_CHAMBER = "emc_chamber"
ESD_SIMULATOR = "esd_simulator"
SHAKER = "shaker"
CLIMATIC_CHAMBER = "climatic_chamber"

INSTRUMENT_TOKENS: frozenset[str] = frozenset({
    DC_STEADY, DC_STEP_1S, DC_RAMP_SLOW, EDGE_10MS, NEGATIVE_VOLTAGE, AC_SUPERPOSITION, PULSE_MS,
    PULSE_US, LOW_SOURCE_IMPEDANCE_PULSE, LINE_SWITCH, FLOATING_OFFSET_SOURCE, SHORT_CIRCUIT_FIXTURE,
    HIPOT_TESTER, INSULATION_TESTER,
})
FACILITY_TOKENS: frozenset[str] = frozenset({TRANSIENT_GENERATOR, EMC_CHAMBER, ESD_SIMULATOR, SHAKER, CLIMATIC_CHAMBER})
ALL_TOKENS: frozenset[str] = INSTRUMENT_TOKENS | FACILITY_TOKENS

TOKEN_DESCRIPTIONS: dict[str, str] = {
    DC_STEADY: "a DC level held for 30 s or longer",
    DC_STEP_1S: "DC steps with holds of at least 1 s",
    DC_RAMP_SLOW: "a slow DC ramp of about 1 V/s or less in bounded steps",
    EDGE_10MS: "rise and fall edges guaranteed within 10 ms",
    NEGATIVE_VOLTAGE: "a negative (reversed) supply voltage",
    AC_SUPERPOSITION: "an AC ripple superimposed on the DC supply",
    PULSE_MS: "pulses with millisecond edges and durations",
    PULSE_US: "interruptions with microsecond edges and durations",
    LOW_SOURCE_IMPEDANCE_PULSE: "a pulse generator with a defined 0.5 Ohm to 8 Ohm source impedance",
    LINE_SWITCH: "a series line switch opening to at least 10 MOhm",
    FLOATING_OFFSET_SOURCE: "a floating source for +/-1 V ground and supply offsets",
    SHORT_CIRCUIT_FIXTURE: "a switched short-circuit fixture on the DUT lines",
    HIPOT_TESTER: "a 500 V AC withstand-voltage tester",
    INSULATION_TESTER: "a 500 V DC insulation-resistance tester",
    TRANSIENT_GENERATOR: "an ISO 7637-2 transient pulse generator",
    EMC_CHAMBER: "an EMC test chamber with its receivers and antennas",
    ESD_SIMULATOR: "an electrostatic-discharge simulator",
    SHAKER: "a vibration shaker and shock fixture",
    CLIMATIC_CHAMBER: "a climatic (temperature/humidity) chamber",
}

# Supply-voltage codes of ISO 16750-2:2023 Tables 3 and 4: code -> (Usmin, Usmax) in volts.
SUPPLY_CODES: dict[str, dict[str, tuple[float, float]]] = {
    "12V": {"A": (6.0, 16.0), "B": (8.0, 16.0), "C": (9.0, 16.0), "D": (10.5, 16.0)},
    "24V": {"E": (10.0, 32.0), "F": (16.0, 32.0), "G": (22.0, 32.0), "H": (18.0, 32.0)},
}
# ISO 16750-1 supply voltages: UA with the alternator in operation, UB with it stopped.
UA_V: dict[str, float] = {"12V": 14.0, "24V": 28.0}
UB_V: dict[str, float] = {"12V": 12.0, "24V": 24.0}

# Functional status classes of ISO 16750-1, one line each (paraphrased definitions).
FUNCTIONAL_STATUS_CLASSES: dict[str, str] = {
    "A": "every function works as designed during and after the test",
    "B": "every function works during the test, some may leave tolerance, all recover afterwards by themselves",
    "C": "some functions stop during the test and come back by themselves afterwards",
    "D": "some functions stop during the test and need a simple operator reset to come back",
    "E": "some functions stop and do not come back without repair or replacement",
}

# The endpoint margin the project already uses: a nominal 36 V is programmed at 35.8 V.
ENDPOINT_MARGIN_V = 0.2
ENDPOINT_REASON = "equals the DUT ceiling; endpoint method not approved"
POLICY_CITATION = "implementation brief §2 and §7.5"

ISO16750_2_ID = "ISO 16750-2:2023"
ISO7637_2_ID = "ISO 7637-2:2011"
CISPR25_ID = "CISPR 25:2021"
ISO11452_ID = "ISO 11452 (all parts)"
ISO10605_ID = "ISO 10605:2023"
ISO16750_3_ID = "ISO 16750-3:2023"
ISO16750_4_ID = "ISO 16750-4:2023"
BENCH_ID = "dcdc-bench"

CATEGORY_NORMAL = "normal_operating"
CATEGORY_ISO16750_2 = "iso16750_2_supply"
CATEGORY_ISO7637_2 = "iso7637_2_transients"
CATEGORY_EMC = "emc"
CATEGORY_ENVIRONMENTAL = "environmental"

FeasibilityStatus = Literal["runs_here", "needs_instrument", "not_on_this_bench", "excluded_by_policy",
                            "outside_dut_rating", "not_applicable"]
Coverage = Literal["full", "room_temperature_only", "partial", "none"]


class Clause(Contract):
    """One clause of a standard, or one of the bench's generic tests.

    ``parameters`` holds the technical test values per system ("12V"/"24V") as
    printed in the standard's tables; ``peak_voltage_V`` and
    ``minimum_voltage_V`` extract the highest positive level applied to the
    DUT input and the lowest level reached, for rating checks. ``requires``
    are hard capability tokens; ``environment`` are temperature or climatic
    conditions whose absence downgrades coverage instead of blocking.
    """
    standard_id: str
    number: str
    title: str
    category: str
    purpose: str
    kind: Literal["test", "heading", "informative"] = "test"
    systems: set[str] = Field(default_factory=lambda: set(SYSTEMS))
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    peak_voltage_V: dict[str, float] = Field(default_factory=dict)
    minimum_voltage_V: dict[str, float] = Field(default_factory=dict)
    uses_supply_code: bool = False
    requires: set[str] = Field(default_factory=set)
    environment: set[str] = Field(default_factory=set)
    functional_status: str = ""
    policy_exclusion: str | None = None
    recipe_kind: str | None = None
    procedure: str | None = None
    procedure_status: Literal["real_fixed", "mock_only", "recipe", "planned"] | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def citation(self) -> str:
        if self.standard_id == BENCH_ID:
            return f"{BENCH_ID} test {self.number}"
        return f"{self.standard_id}, clause {self.number}"


class Standard(Contract):
    id: str
    title: str
    edition: str
    clauses: list[Clause] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def clause(self, number: str) -> Clause:
        for item in self.clauses:
            if item.number == number:
                return item
        raise KeyError(f"{self.id} has no clause {number}")

    def tests(self) -> list[Clause]:
        return [item for item in self.clauses if item.kind == "test"]


class BenchEnvelope(Contract):
    """Numeric bounds read from the bench profile next to its capability tokens."""
    tokens: set[str]
    max_voltage_V: float | None = None
    max_current_A: float | None = None
    max_power_W: float | None = None
    protective_input_ceiling_V: float | None = None


class Feasibility(Contract):
    clause_number: str
    standard_id: str
    system: str
    status: FeasibilityStatus
    reason: str
    missing: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    coverage: Coverage = "none"


class CatalogEntry(Contract):
    clause: Clause
    feasibility: Feasibility
    recipe: dict[str, Any] | None = None


class Category(Contract):
    id: str
    number: int
    title: str
    description: str
    candidate_for_bench: bool
    entries: list[CatalogEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Bench capabilities
# ---------------------------------------------------------------------------

def capabilities(bench: BenchProfile) -> set[str]:
    """Tokens the profile's declared instrument class earns; see the module docstring.

    Simulated and real profiles of the same class earn the same tokens: a mock
    that emulates a single-quadrant DC supply cannot pretend to produce pulses.
    """
    tokens: set[str] = set()
    source = bench.source
    if source.max_voltage_V is not None and source.max_voltage_V > 0:
        tokens |= {DC_STEADY, DC_STEP_1S, DC_RAMP_SLOW}
    if source.min_voltage_V < 0:  # unreachable today: the contract forbids a negative minimum
        tokens.add(NEGATIVE_VOLTAGE)
    return tokens


def envelope(bench: BenchProfile) -> BenchEnvelope:
    guards = bench.protective_controls
    ceiling = guards.dut_input_overvoltage_V if guards.approved else None
    return BenchEnvelope(tokens=capabilities(bench), max_voltage_V=bench.source.max_voltage_V,
                         max_current_A=bench.source.max_current_A, max_power_W=bench.source.max_power_W,
                         protective_input_ceiling_V=ceiling)


# ---------------------------------------------------------------------------
# Supply code selection and recipe parameters
# ---------------------------------------------------------------------------

def select_supply_code(system: str, dut: DutProfile) -> tuple[str, float, float, list[str]]:
    """Choose the Table 3/4 code whose range fits inside the DUT's stated input range.

    Among fitting codes the lowest Usmin wins (widest coverage). If none fits,
    the code with the highest Usmin is returned together with a note; nothing
    is clipped silently.
    """
    _check_system(system)
    ratings = dut.ratings
    codes = SUPPLY_CODES[system]
    fitting = {code: (lo, hi) for code, (lo, hi) in codes.items()
               if lo >= ratings.input_voltage_min_V and hi <= ratings.input_voltage_max_V}
    notes: list[str] = []
    if fitting:
        code = min(fitting, key=lambda c: fitting[c][0])
    else:
        code = max(codes, key=lambda c: codes[c][0])
        notes.append(f"No {system} supply code fits inside the DUT's {ratings.input_voltage_min_V:g}-"
                     f"{ratings.input_voltage_max_V:g} V rating; code {code} is listed for reference only")
    lo, hi = codes[code]
    if lo == ratings.input_voltage_min_V:
        notes.append(f"Usmin {lo:g} V equals the DUT's stated minimum; the startup/descent procedure programmed "
                     f"{lo + 0.1:g} V for that nominal condition")
    return code, lo, hi, notes


def _staircase_levels(usmin: float) -> list[float]:
    levels = [round(usmin * (1 - 0.05 * k), 4) for k in range(1, 20)]
    return levels + [0.0]


def recipe_parameters(clause: Clause, system: str, dut: DutProfile) -> dict[str, Any] | None:
    """Concrete levels, holds and ramp rates a recipe would need; None when nothing runs here.

    Computed from the standard's parameters and the DUT ratings only. Levels
    that are not below the DUT's maximum give None: no recipe is derived for a
    level the project refuses.
    """
    _check_system(system)
    if clause.recipe_kind is None or system not in clause.systems:
        return None
    ratings = dut.ratings
    dut_min, dut_max = ratings.input_voltage_min_V, ratings.input_voltage_max_V

    if clause.recipe_kind == "steady_min_max":
        code, usmin, usmax, notes = select_supply_code(system, dut)
        if usmax >= dut_max:
            return None
        return {
            "clause": clause.citation, "system": system, "supply_code": code,
            "Usmin_V": usmin, "Usmax_V": usmax, "UA_V": UA_V[system],
            "levels_V": [UA_V[system], usmin, UA_V[system], usmax, UA_V[system]],
            "t1_s": 30.0, "t2_s": 60.0, "ramp_V_per_s": 1.0,
            "ramp_realisation": "1.0 V live steps at the 1 s command cadence",
            "operating_modes": ["3.2 at room temperature (runs here)",
                                "3.3 and 3.4 at Tmin and Tmax (needs a climatic chamber; not on this bench)"],
            "functional_status": "A",
            "below_dut_minimum": usmin < dut_min,
            "notes": notes + ["t1 and t2 are Table 2 values; their position in the profile follows Figure 1",
                              "rated-load mode 3.4 is bounded by the 1 A source; the planner decides the load grid"],
        }

    if clause.recipe_kind == "overvoltage_hold":
        level = clause.peak_voltage_V[system]
        if level >= dut_max:
            return None
        return {
            "clause": clause.citation, "system": system, "level_V": level, "duration_s": 3600.0,
            "operating_mode": "3.4 (bounded by the 1 A source)", "functional_status": "C minimum",
            "temperature": "(Tmax - 20) K conditioning is not provided; the hold runs at room temperature and the "
                           "report records that deviation",
            "notes": ["a reviewed protective policy must set the DUT input overvoltage guard above the level"],
        }

    if clause.recipe_kind == "slow_ramp":
        start = UA_V[system]
        if start >= dut_max:
            return None
        step_v, step_s = 0.02, 2.4  # 0.5 V/min, inside the 25 mV step ceiling and representable at 10 mV resolution
        steps = int(round(start / step_v))
        return {
            "clause": clause.citation, "system": system, "start_V": start, "floor_V": 0.0,
            "rate_V_per_min": 0.5, "rate_tolerance_V_per_min": 0.1, "max_step_V": 0.025,
            "step_V": step_v, "step_interval_s": step_s, "steps_per_direction": steps,
            "duration_per_direction_s": round(steps * step_s, 1), "total_duration_s": round(2 * steps * step_s, 1),
            "operating_mode": "3.2",
            "functional_status": {"inside Table 3/4 range": "A", "outside": "D minimum"},
            "below_dut_minimum_from_V": dut_min,
            "approval": "steps below the DUT minimum need the approved UVLO-style recipe (brief §7.5)",
        }

    if clause.recipe_kind == "reset_staircase":
        code, usmin, _usmax, notes = select_supply_code(system, dut)
        if usmin >= dut_max:
            return None
        lows = _staircase_levels(usmin)
        return {
            "clause": clause.citation, "system": system, "supply_code": code, "Usmin_V": usmin,
            "step_fraction_of_Usmin": 0.05, "low_levels_V": lows, "low_hold_s": 5.0, "recovery_level_V": usmin,
            "recovery_hold_s": 10.0, "functional_test": "at Usmin after every recovery hold",
            "operating_mode": "3.4 (bounded by the 1 A source)", "functional_status": "C minimum",
            "levels_below_dut_minimum": sum(1 for v in lows if v < dut_min),
            "approval": "steps below the DUT minimum need the approved UVLO-style recipe (brief §7.5)",
            "notes": notes,
        }

    if clause.recipe_kind == "long_interruptions":
        base = UB_V[system]
        if base >= dut_max:
            return None
        return {
            "clause": clause.citation, "system": system, "coverage": "partial", "base_V": base,
            "test_case_1": {"interruption_s": [round(1.0 + 0.1 * k, 1) for k in range(11)],
                            "recovery_s": "at least 5 s and until the DUT is fully serviceable"},
            "test_case_2": {"interruption_s": 1.0, "recovery_s": [float(k) for k in range(1, 11)]},
            "not_covered": "interruptions from 10 us to below 1 s and recoveries from 100 us to below 1 s",
            "method_deviation": "the source output is switched OFF/ON by LAN command instead of a series switch "
                                "opening to 10 MOhm within 10 us; the output-off edge is not characterised",
            "operating_mode": "3.4 (bounded by the 1 A source)",
            "functional_status": "C minimum for interruptions longer than 100 us",
        }
    return None


# ---------------------------------------------------------------------------
# Feasibility
# ---------------------------------------------------------------------------

def _check_system(system: str) -> None:
    if system not in SYSTEMS:
        raise ValueError(f"system must be one of {SYSTEMS}, not {system!r}")


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith(".") else text + "."


def _describe(tokens: list[str]) -> str:
    return "; ".join(TOKEN_DESCRIPTIONS.get(t, t) for t in tokens)


def feasibility(clause: Clause, bench: BenchProfile, dut: DutProfile, system: str) -> Feasibility:
    """One verdict per clause and system, with a sentence a technician can read.

    Check order: applicability, policy exclusion, missing facility, missing
    instrument, DUT rating, bench envelope, then the conditions that still
    apply to a clause that runs here.
    """
    _check_system(system)
    env = envelope(bench)
    ratings = dut.ratings
    base = dict(clause_number=clause.number, standard_id=clause.standard_id, system=system)

    if clause.kind != "test":
        what = "a heading" if clause.kind == "heading" else "informative"
        return Feasibility(**base, status="not_applicable", coverage="none",
                           reason=_sentence(f"{clause.citation} is {what}, not a test to run"))
    if system not in clause.systems:
        return Feasibility(**base, status="not_applicable", coverage="none",
                           reason=_sentence(f"{clause.citation} applies to {', '.join(sorted(clause.systems))} "
                                            f"systems only, not to a {system} system"))
    if clause.policy_exclusion:
        return Feasibility(**base, status="excluded_by_policy", coverage="none",
                           missing=sorted(clause.requires - env.tokens),
                           reason=_sentence(f"{clause.policy_exclusion} ({POLICY_CITATION})"))

    missing = sorted(clause.requires - env.tokens)
    facility = [t for t in missing if t in FACILITY_TOKENS]
    if facility:
        return Feasibility(**base, status="not_on_this_bench", missing=missing, coverage="none",
                           reason=_sentence(f"{clause.title} belongs to a different laboratory: it needs "
                                            f"{_describe(facility)}, not a supply and load bench"))
    if missing:
        partial = clause.recipe_kind == "long_interruptions" and DC_STEP_1S in env.tokens
        conditions = (["Only interruptions of 1 s and longer can be reproduced here, by switching the source output off "
                       "at the command cadence; recipe_parameters lists that subset as partial coverage"] if partial else [])
        return Feasibility(**base, status="needs_instrument", missing=missing, coverage="partial" if partial else "none",
                           conditions=conditions,
                           reason=_sentence(f"{clause.title} needs {_describe(missing)}, which the bench supply "
                                            f"cannot produce; the {env.max_voltage_V:g} V DC envelope alone does not cover it"
                                            if env.max_voltage_V else
                                            f"{clause.title} needs {_describe(missing)}, which the bench supply cannot produce"))

    peak = clause.peak_voltage_V.get(system)
    if clause.uses_supply_code:
        code, usmin, usmax, code_notes = select_supply_code(system, dut)
        peak = usmax if clause.recipe_kind == "steady_min_max" else usmin
        floor = clause.minimum_voltage_V.get(system, usmin)
        level_text = f"code {code} ({usmin:g} V to {usmax:g} V)"
    else:
        code_notes = []
        floor = clause.minimum_voltage_V.get(system)
        level_text = f"{peak:g} V" if peak is not None else "its levels"

    if peak is not None:
        if peak == ratings.input_voltage_max_V:
            return Feasibility(**base, status="outside_dut_rating", coverage="none",
                               missing=[f"{peak:g} V level vs DUT input maximum {ratings.input_voltage_max_V:g} V"],
                               reason=_sentence(f"The {peak:g} V level of {clause.citation} {ENDPOINT_REASON}"))
        if peak > ratings.input_voltage_max_V:
            return Feasibility(**base, status="outside_dut_rating", coverage="none",
                               missing=[f"{peak:g} V level vs DUT input maximum {ratings.input_voltage_max_V:g} V"],
                               reason=_sentence(f"The {peak:g} V level of {clause.citation} exceeds the DUT's rated "
                                                f"input maximum of {ratings.input_voltage_max_V:g} V"))
        if env.max_voltage_V is not None and peak > env.max_voltage_V:
            return Feasibility(**base, status="not_on_this_bench", coverage="none",
                               missing=[f"{peak:g} V level vs source maximum {env.max_voltage_V:g} V"],
                               reason=_sentence(f"The {peak:g} V level of {clause.citation} is above the source's "
                                                f"{env.max_voltage_V:g} V maximum"))

    conditions = list(code_notes)
    coverage: Coverage = "full"
    if floor is not None and floor < ratings.input_voltage_min_V:
        conditions.append(f"Levels below the DUT's stated {ratings.input_voltage_min_V:g} V minimum need the approved "
                          f"UVLO-style recipe with a reviewed protective policy (brief §7.5)")
    if peak is not None and env.protective_input_ceiling_V is not None and peak >= env.protective_input_ceiling_V:
        conditions.append(f"The {peak:g} V level is at or above the bench's approved DUT input overvoltage guard of "
                          f"{env.protective_input_ceiling_V:g} V; a reviewed protective policy must raise it first")
    if clause.environment - env.tokens:
        coverage = "room_temperature_only" if coverage == "full" else coverage
        conditions.append(f"Temperature conditioning needs {_describe(sorted(clause.environment - env.tokens))}; "
                          f"the electrical part runs at room temperature and the deviation is recorded")
    if env.max_current_A is not None and ratings.output_power_rated_W > 0:
        conditions.append(f"Rated-load operating mode 3.4 is not reachable from a {env.max_current_A:g} A source; the run "
                          f"uses the bounded load grid the planner accepts (brief §3.2)")
    if clause.standard_id == BENCH_ID and clause.procedure_status == "mock_only":
        conditions.append("The below-minimum part of this test exists on the synthetic plant only today")

    reason = (f"The bench source can hold {level_text} of {clause.citation} as DC levels within its "
              f"{env.max_voltage_V:g} V envelope and the DUT's {ratings.input_voltage_min_V:g}-{ratings.input_voltage_max_V:g} V rating"
              if env.max_voltage_V is not None else
              f"The bench source can hold {level_text} of {clause.citation} as DC levels")
    if clause.standard_id == BENCH_ID:
        reason = (f"{clause.title} is an ordinary DC supply and load measurement within the source's "
                  f"{env.max_voltage_V:g} V envelope and the DUT's {ratings.input_voltage_min_V:g}-{ratings.input_voltage_max_V:g} V rating"
                  if env.max_voltage_V is not None else f"{clause.title} is an ordinary DC supply and load measurement")
    return Feasibility(**base, status="runs_here", reason=_sentence(reason), conditions=conditions, coverage=coverage)


# ---------------------------------------------------------------------------
# ISO 16750-2:2023 section 4 (technical facts only; cited by clause number)
# ---------------------------------------------------------------------------

def _c(number: str, title: str, purpose: str, **kw: Any) -> Clause:
    kw.setdefault("standard_id", ISO16750_2_ID)
    kw.setdefault("category", CATEGORY_ISO16750_2)
    return Clause(number=number, title=title, purpose=purpose, **kw)


def _iso16750_2() -> Standard:
    both = set(SYSTEMS)
    clauses = [
        _c("4.1", "General", "Tolerances and sample count for all electrical tests.", kind="informative",
           parameters={s: {"tolerance_frequency_time_pct": 5.0, "tolerance_voltage_V": 0.2, "tolerance_current_pct": 2.0,
                           "tolerance_inductance_pct": 10.0, "tolerance_resistance_pct": 10.0, "minimum_DUTs": 2,
                           "measurement_point": "DUT terminals"} for s in both}),
        _c("4.2", "Direct current (DC) supply voltage",
           "Verify function at the minimum and maximum supply voltage of the chosen code.",
           parameters={
               "12V": {"codes_Usmin_Usmax_V": {k: list(v) for k, v in SUPPLY_CODES["12V"].items()} | {"Z": "as agreed"},
                       "UA_V": 14.0, "t1_s": 30.0, "t2_s": 60.0, "trise_V_per_s": 1.0, "tfall_V_per_s": 1.0,
                       "operating_modes": "3.3 and 3.4 at Tmin and Tmax; 3.2 at room temperature"},
               "24V": {"codes_Usmin_Usmax_V": {k: list(v) for k, v in SUPPLY_CODES["24V"].items()} | {"Z": "as agreed"},
                       "UA_V": 28.0, "t1_s": 30.0, "t2_s": 60.0, "trise_V_per_s": 1.0, "tfall_V_per_s": 1.0,
                       "operating_modes": "3.3 and 3.4 at Tmin and Tmax; 3.2 at room temperature"}},
           peak_voltage_V={"12V": 16.0, "24V": 32.0}, uses_supply_code=True,
           requires={DC_STEADY, DC_RAMP_SLOW}, environment={CLIMATIC_CHAMBER}, functional_status="A",
           recipe_kind="steady_min_max",
           notes=["Redundant supplies: every Usmin/Usmax combination across ports"]),
        _c("4.3", "Overvoltage", "Long-term and transient overvoltage on the supply.", kind="heading"),
        _c("4.3.1", "Long term overvoltage", "Alternator-failure and jump-start overvoltage holds.", kind="heading"),
        _c("4.3.1.1", "Long term overvoltage: alternator regulator failure at (Tmax - 20) K",
           "Simulate a failed alternator regulator raising the supply for an hour.",
           parameters={"12V": {"level_V": 18.0, "duration_s": 3600.0, "temperature": "Tmax - 20 K", "operating_mode": "3.4"},
                       "24V": {"level_V": 36.0, "duration_s": 3600.0, "temperature": "Tmax - 20 K", "operating_mode": "3.4"}},
           peak_voltage_V={"12V": 18.0, "24V": 36.0}, requires={DC_STEADY}, environment={CLIMATIC_CHAMBER},
           functional_status="C minimum; A where more stringent", recipe_kind="overvoltage_hold"),
        _c("4.3.1.2", "Long term overvoltage: jump start (12 V systems only)",
           "Simulate a jump start from a 24 V donor without its engine running.", systems={"12V"},
           parameters={"12V": {"Utrans_V": 26.0, "ttrans_s": 60.0, "ttrans_tolerance_s": 6.0, "trise_max_s": 0.01,
                               "tfall_max_s": 0.01, "trest_s": 120.0, "Usmin_V": 10.8, "n": 1,
                               "temperatures": "room temperature and Tmin", "operating_mode": "2.2 if needed for engine start, else 2.3"}},
           peak_voltage_V={"12V": 26.0}, requires={DC_STEADY, EDGE_10MS}, environment={CLIMATIC_CHAMBER},
           functional_status="C minimum; A where more stringent"),
        _c("4.3.2", "Transient overvoltage", "Simulate switching loads that inject current into the distribution system.",
           parameters={"12V": {"Utrans_V": 18.0, "ttrans_s": 0.4, "trise_s": 0.001, "tfall_s": 0.001, "trest_s": 1.0, "n": 5,
                               "base": "Usmax", "operating_mode": "3.4"},
                       "24V": {"Utrans_V": 36.0, "ttrans_s": 0.4, "trise_s": 0.002, "tfall_s": 0.002, "trest_s": 1.0, "n": 5,
                               "base": "Usmax", "operating_mode": "3.4"}},
           peak_voltage_V={"12V": 18.0, "24V": 36.0}, requires={PULSE_MS}, functional_status="B minimum; C by agreement"),
        _c("4.4", "Superimposed alternating voltage", "Check immunity to ripple from an alternator or a DC/DC converter.",
           parameters={
               "12V": {"f1_Hz": [10.0, 30000.0], "f2_Hz": [30000.0, 200000.0],
                       "Upp_by_severity_V": {"1 alternator without battery": 6.0, "2 alternator": 3.0,
                                             "3 DC/DC converter": 2.0, "4 DC/DC converter (f2)": 1.0},
                       "U0_V": "Usmax - Upp/2 and Usmin + Upp/2", "dwell_s": 2.0, "frequency_step": "logarithmic 2 %",
                       "Ipp_limit_A": {"f1": 15.0, "f2": 10.0}, "operating_mode": "3.2 (reference test in 3.3)"},
               "24V": {"f1_Hz": [10.0, 30000.0], "f2_Hz": [30000.0, 200000.0],
                       "Upp_by_severity_V": {"1 alternator without battery": 10.0, "2 alternator": 3.0,
                                             "3 DC/DC converter": 2.0, "4 DC/DC converter (f2)": 1.0},
                       "U0_V": "Usmax - Upp/2 and Usmin + Upp/2", "dwell_s": 2.0, "frequency_step": "logarithmic 2 %",
                       "Ipp_limit_A": {"f1": 15.0, "f2": 10.0}, "operating_mode": "3.2 (reference test in 3.3)"}},
           peak_voltage_V={"12V": 16.0, "24V": 32.0}, requires={AC_SUPERPOSITION},
           functional_status="A; impedance drift beyond the agreed tolerance counts as E",
           notes=["DUT input impedance is measured before and after; oscilloscope voltage and current probes within 10 cm of the DUT"]),
        _c("4.5", "Slow decrease and increase of supply voltage", "Simulate a gradual battery discharge and recharge.",
           parameters={"12V": {"start_V": 14.0, "floor_V": 0.0, "rate_V_per_min": 0.5, "rate_tolerance_V_per_min": 0.1,
                               "max_step_V": 0.025, "operating_mode": "3.2"},
                       "24V": {"start_V": 28.0, "floor_V": 0.0, "rate_V_per_min": 0.5, "rate_tolerance_V_per_min": 0.1,
                               "max_step_V": 0.025, "operating_mode": "3.2"}},
           peak_voltage_V={"12V": 14.0, "24V": 28.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0}, requires={DC_RAMP_SLOW},
           functional_status="A inside the Table 3/4 range; D minimum outside it", recipe_kind="slow_ramp"),
        _c("4.6", "Discontinuities in supply voltage", "Drops, interruptions, reset behaviour, cranking and load dump.", kind="heading"),
        _c("4.6.1", "Drops or interrupts in supply voltage", "Momentary drop and micro interruptions.", kind="heading"),
        _c("4.6.1.1", "Momentary drop in supply voltage", "Simulate a fuse element melting in a parallel circuit.",
           parameters={"12V": {"from": "Usmin", "drop_level_V": 4.5, "drop_duration_s": 0.1, "edge_max_s": 0.01, "operating_mode": "3.4",
                               "figure_values": "drop level and duration appear in Figure 7 only; confirm on the printed copy"},
                       "24V": {"from": "Usmin", "drop_level_V": 9.0, "drop_duration_s": 0.1, "edge_max_s": 0.01, "operating_mode": "3.4",
                               "figure_values": "drop level and duration appear in Figure 8 only; confirm on the printed copy"}},
           peak_voltage_V={"12V": 10.5, "24V": 22.0}, requires={PULSE_MS, EDGE_10MS},
           functional_status="B minimum; C by agreement"),
        _c("4.6.1.2", "Micro interruption in supply voltage",
           "Simulate contact faults, relay bounce and switch-over to a redundant supply.",
           parameters={s: {"base_V": UB_V[s],
                           "test_case_1": {"tmicro": "10 us to 2 s in decade steps of 10 us, 100 us, 1 ms, 10 ms, 100 ms",
                                           "trecovery_s": "at least 5 and until fully serviceable", "n": 1},
                           "test_case_2": {"tmicro_s": "at least 0.1 and until reset",
                                           "trecovery": "100 us to 10 s in decade steps of 100 us, 1 ms, 10 ms, 100 ms, 1 s", "n": 1},
                           "switch": "reaction time at most 10 us, open resistance at least 10 MOhm, checked with 1 kOhm and 10 Ohm references",
                           "operating_mode": "3.4"} for s in both},
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, requires={PULSE_US, LINE_SWITCH},
           functional_status="A for interruptions up to 100 us; C minimum above", recipe_kind="long_interruptions"),
        _c("4.6.2", "Reset behaviour at voltage drop", "Check reset behaviour of microcontroller equipment at stepped voltage drops.",
           parameters={s: {"start": "Usmin of the chosen code", "step_fraction_of_Usmin": 0.05, "low_hold_min_s": 5.0,
                           "recovery_hold_min_s": 10.0, "functional_test": "at Usmin after each recovery", "end_V": 0.0,
                           "operating_mode": "3.4"} for s in both},
           peak_voltage_V={"12V": 10.5, "24V": 22.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0}, uses_supply_code=True,
           requires={DC_STEP_1S}, functional_status="C minimum", recipe_kind="reset_staircase",
           notes=["Internal capacitor buffers: monitor or otherwise show that the internal supply follows each step"]),
        _c("4.6.3", "Starting profile", "Check behaviour during and after engine cranking, ten cycles.",
           parameters={
               "12V": {"levels": {"I warm crank": {"US1_V": 8.0, "US_V": 9.5, "t3_s": 1.0, "trise_ms": 40.0},
                                  "II cold crank, good battery": {"US1_V": 4.5, "US_V": 6.5, "t3_s": 10.0, "trise_ms": 100.0},
                                  "III cold crank, aged battery": {"US1_V": 3.0, "US_V": 5.0, "t3_s": 1.0, "trise_ms": 100.0},
                                  "IV": {"US1_V": 6.0, "US_V": 6.5, "t3_s": 10.0, "trise_ms": 100.0}},
                       "level_tolerance_V": -0.2, "tfall_ms": 5.0, "t1_ms": 15.0, "t2_ms": 50.0, "ripple_Hz": 2.0,
                       "cycles": 10, "recovery_s": 2.0, "base_V": 12.0, "operating_mode": "3.2"},
               "24V": {"levels": {"I": {"US1_V": 10.0, "US_V": 20.0, "t3_s": 1.0, "trise_ms": 40.0},
                                  "II": {"US1_V": 8.0, "US_V": 15.0, "t3_s": 10.0, "trise_ms": 100.0},
                                  "III": {"US1_V": 6.0, "US_V": 10.0, "t3_s": 1.0, "trise_ms": 40.0}},
                       "level_tolerance_V": -0.2, "tfall_ms": 10.0, "t1_ms": 50.0, "t2_ms": 50.0, "ripple_Hz": 2.0,
                       "cycles": 10, "recovery_s": 2.0, "base_V": 24.0, "operating_mode": "3.2"}},
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, requires={PULSE_MS},
           functional_status="A for cranking-relevant functions; otherwise per Table 11/12 by supply code"),
        _c("4.6.4", "Load dump", "Simulate the battery disconnecting while the alternator is charging.",
           parameters={
               "12V": {"test_A_no_suppression": {"US_V": [79.0, 101.0], "Ri_ohm": [0.5, 4.0], "td_ms": [40.0, 400.0],
                                                 "trise_ms": "10 (-5)", "pulses": "10 at 1 min intervals"},
                       "test_B_centralized_suppression": {"clamp_US_star_V": {"1": 27.0, "2": 30.0, "3": 32.0, "4": 35.0},
                                                          "pulses": "5 at 1 min intervals"},
                       "operating_mode": "3.4"},
               "24V": {"test_A_no_suppression": {"US_V": [151.0, 202.0], "Ri_ohm": [1.0, 8.0], "td_ms": [100.0, 350.0],
                                                 "trise_ms": "10 (-5)", "pulses": "10 at 1 min intervals"},
                       "test_B_centralized_suppression": {"clamp_US_star_V": "as specified by the customer (typically 58)",
                                                          "pulses": "5 at 1 min intervals"},
                       "operating_mode": "3.4"}},
           peak_voltage_V={"12V": 101.0, "24V": 202.0}, requires={LOW_SOURCE_IMPEDANCE_PULSE, PULSE_MS},
           functional_status="C minimum",
           policy_exclusion="Load dump is a fault-injection overvoltage transient that this release does not perform"),
        _c("4.7", "Reversed voltage", "Check withstand of a reversed battery connected through an auxiliary starting device.",
           parameters={
               "12V": {"test_case_1": {"Ureversed_V": -4.0, "duration_s": 60.0, "edges_max_s": 0.01, "from_Usmin_V": 10.5,
                                       "recovery_s": 120.0, "n": 1, "applicability": "unfused alternator circuit whose diodes withstand 60 s"},
                       "test_case_2": {"Ureversed_V": -14.0, "duration_s": 60.0, "tfall_max_s": 0.01, "trise_max_s": 1.0,
                                       "from_UB_V": 12.0, "recovery_s": 120.0, "n": 1}},
               "24V": {"test_case_2": {"Ureversed_V": -26.0, "duration_s": 60.0, "tfall_max_s": 0.01, "trise_max_s": 1.0,
                                       "from_UB_V": 24.0, "recovery_s": 120.0, "n": 1}}},
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, minimum_voltage_V={"12V": -14.0, "24V": -26.0}, requires={NEGATIVE_VOLTAGE},
           functional_status="A after replacing blown fuse-links",
           policy_exclusion="Reversed voltage is a reverse-power fault test that this release does not perform",
           notes=["Not applicable to alternators or to terminals with clamping diodes without external protection"]),
        _c("4.8", "Ground reference and supply offset", "Verify operation with +/-1 V offsets between separate supply and ground paths.",
           parameters={s: {"US_V": UB_V[s] + (UA_V[s] - UB_V[s]) / 2, "offset_V": 1.0, "offset_tolerance_V": 0.1,
                           "variations": 8, "operating_mode": "3.4",
                           "applicability": "DUTs with two or more supply or ground paths, by agreement"} for s in both},
           peak_voltage_V={"12V": 14.0, "24V": 27.0}, requires={FLOATING_OFFSET_SOURCE}, functional_status="A"),
        _c("4.9", "Open circuit tests", "Single and multiple line interruptions.", kind="heading"),
        _c("4.9.1", "Single line interruption", "Simulate a static or loose-contact open on one line.",
           parameters={s: {"method_1": {"interruption_s": 10.0, "tolerance_s": 1.0, "open_resistance_ohm": 1e7, "transition_max_s": 0.01,
                                        "conditions": "outputs active and inactive"},
                           "method_2": {"tint_us": 100.0, "tint_cycle_ms": 1.0, "burst_s": 10.0, "recovery_s": 10.0, "n": 2,
                                        "transition_max_us": 10.0},
                           "operating_mode": "3.4"} for s in both},
           requires={LINE_SWITCH, PULSE_US}, functional_status="C minimum; D by agreement"),
        _c("4.9.2", "Multiple line interruption", "Simulate unplugging the whole connector.",
           parameters={s: {"interruption_s": 10.0, "tolerance_s": 1.0, "open_resistance_ohm": 1e7,
                           "operating_modes": "2.1 and 3.4"} for s in both},
           requires={LINE_SWITCH}, functional_status="C minimum; D by agreement"),
        _c("4.10", "Short circuit/overload protection", "Shorts and overloads on inputs and outputs.", kind="heading"),
        _c("4.10.2", "Short circuit in signal lines and load circuits", "Short every signal and load line to Usmax and to ground.",
           parameters={s: {"to": "Usmax and ground", "duration_s": 60.0, "duration_tolerance_pct": 10.0,
                           "conditions": "outputs active; outputs inactive; positive supply disconnected", "operating_mode": "3.4"} for s in both},
           peak_voltage_V={"12V": 16.0, "24V": 32.0}, requires={SHORT_CIRCUIT_FIXTURE},
           functional_status="C minimum; D for fused or retry-limited outputs",
           policy_exclusion="Short-circuit testing is excluded from this release"),
        _c("4.10.3", "Overloading of load circuits", "Load each output at 100 % and 150 % of its current capacity.",
           parameters={s: {"levels_pct_of_capacity": [100.0, 150.0],
                           "duration": "ISO 8820 operating time at the upper tolerance plus 10 %; by agreement for electronic protection",
                           "operating_mode": "3.4"} for s in both},
           requires={DC_STEADY}, functional_status="C for electronic protection; D for fuses; E permitted for unprotected outputs",
           policy_exclusion="Overload and current-limit testing is an opt-in later feature"),
        _c("4.11", "Withstand voltage", "Dielectric withstand of galvanically isolated circuits after humid heat cycling.",
           parameters={s: {"test_voltage": "500 V AC at 50 or 60 Hz", "duration_s": 60.0,
                           "preconditioning": "humid heat cyclic test per ISO 16750-4:2023 5.6.2, then 0.5 h at room temperature",
                           "applies_to": "circuits with galvanic isolation or inductive elements", "operating_mode": "1.1 or 1.2"} for s in both},
           requires={HIPOT_TESTER, CLIMATIC_CHAMBER}, functional_status="C minimum; no breakdown or flash-over"),
        _c("4.12", "Insulation resistance", "Minimum insulation resistance between isolated circuits after humid heat cycling.",
           parameters={s: {"test_voltage_V_dc": 500.0, "reduced_by_agreement_V_dc": 100.0, "duration_s": 60.0, "limit_ohm": 1e7,
                           "preconditioning": "humid heat cyclic test per ISO 16750-4:2023 5.6.2, then 0.5 h at room temperature",
                           "operating_mode": "1.1 or 1.2"} for s in both},
           requires={INSULATION_TESTER, CLIMATIC_CHAMBER}, functional_status="insulation resistance above 10 MOhm"),
        _c("4.13", "Electromagnetic compatibility", "Pointer to CISPR 25, ISO 7637, ISO 10605, ISO 11451 and ISO 11452; not in this part's scope.",
           kind="informative"),
    ]
    return Standard(id=ISO16750_2_ID, title="Road vehicles - Environmental conditions and testing for electrical and "
                    "electronic equipment - Part 2: Electrical loads", edition="2023", clauses=clauses,
                    notes=["Owner's recollection (4.6.2 reset, 4.6.4 load dump, 4.7 reversed voltage) matches the 2023 numbering",
                           "UA/UB and the functional status classes come from ISO 16750-1"])


def _other_standards() -> list[Standard]:
    iso7637 = Standard(id=ISO7637_2_ID, title="Road vehicles - Electrical disturbances from conduction and coupling - "
                       "Part 2: Electrical transient conduction along supply lines only", edition="2011", clauses=[
        Clause(standard_id=ISO7637_2_ID, number="5.6", title="Test pulses 1, 2a, 2b, 3a and 3b on the supply lines",
               category=CATEGORY_ISO7637_2, purpose="Immunity to conducted transients from inductive loads, wiring and switching.",
               parameters={s: {"pulse_1": "negative, about 2 ms, from an inductive load being switched off",
                               "pulse_2a": "positive, about 50 us, 2 Ohm source, from current interruption in parallel wiring",
                               "pulse_2b": "positive, 0.2 s to 2 s, very low source impedance, from a motor acting as generator",
                               "pulse_3a": "negative bursts, about 100 ns per pulse, 50 Ohm source",
                               "pulse_3b": "positive bursts, about 100 ns per pulse, 50 Ohm source",
                               "note": "pulses 4 and 5 of older editions moved to ISO 16750-2 (starting profile, load dump)"} for s in SYSTEMS},
               requires={TRANSIENT_GENERATOR, PULSE_US, PULSE_MS, NEGATIVE_VOLTAGE, LOW_SOURCE_IMPEDANCE_PULSE},
               functional_status="per pulse and severity level, agreed between customer and supplier")])
    cispr = Standard(id=CISPR25_ID, title="Radio disturbance characteristics for the protection of on-board receivers", edition="2021", clauses=[
        Clause(standard_id=CISPR25_ID, number="6", title="Conducted and radiated emissions from components and modules",
               category=CATEGORY_EMC, purpose="Emission limits for on-board receivers.", requires={EMC_CHAMBER})])
    iso11452 = Standard(id=ISO11452_ID, title="Component test methods for electrical disturbances from narrowband radiated electromagnetic energy",
                        edition="all parts", clauses=[
        Clause(standard_id=ISO11452_ID, number="all parts", title="Radiated immunity (ALSE, BCI, stripline, TEM, portable transmitter)",
               category=CATEGORY_EMC, purpose="Immunity to narrowband radiated fields.", requires={EMC_CHAMBER})])
    iso10605 = Standard(id=ISO10605_ID, title="Test methods for electrical disturbances from electrostatic discharge", edition="2023", clauses=[
        Clause(standard_id=ISO10605_ID, number="all", title="Electrostatic discharge, powered and unpowered", category=CATEGORY_EMC,
               purpose="Immunity to ESD from occupants and handling.", requires={ESD_SIMULATOR})])
    iso16750_3 = Standard(id=ISO16750_3_ID, title="Environmental conditions and testing - Part 3: Mechanical loads", edition="2023", clauses=[
        Clause(standard_id=ISO16750_3_ID, number="4", title="Vibration, mechanical shock, free fall, surface strength, gravel bombardment",
               category=CATEGORY_ENVIRONMENTAL, purpose="Mechanical loads by mounting location.", requires={SHAKER})])
    iso16750_4 = Standard(id=ISO16750_4_ID, title="Environmental conditions and testing - Part 4: Climatic loads", edition="2023", clauses=[
        Clause(standard_id=ISO16750_4_ID, number="5", title="Temperature, temperature cycling, humidity, salt spray, water, dust",
               category=CATEGORY_ENVIRONMENTAL, purpose="Climatic loads by mounting location.", requires={CLIMATIC_CHAMBER})])
    return [iso7637, cispr, iso11452, iso10605, iso16750_3, iso16750_4]


def _generic_tests() -> list[Clause]:
    common = dict(standard_id=BENCH_ID, category=CATEGORY_NORMAL)
    return [
        Clause(number="1.1", title="Input-voltage (VIN) sweep at fixed loads", **common,
               purpose="DC behaviour across the DUT's stated input range at bounded loads.",
               requires={DC_STEADY}, recipe_kind=None, procedure_status="real_fixed",
               procedure="steady_state_load_sweep recipe with several input_voltage_targets_V "
                         "(profiles/recipes/12t12-4a-voltage-efficiency.yaml; fixed real worker voltage_sweep.py)",
               notes=["The upper endpoint is programmed with the project's margin (35.8 V for a nominal 36 V)"]),
        Clause(number="1.2", title="Efficiency versus output load", **common,
               purpose="Source-to-load efficiency and power loss at each accepted point.",
               requires={DC_STEADY}, procedure_status="real_fixed",
               procedure="steady_state_load_sweep with derived efficiency and power_loss "
                         "(fixed real workers extended.py and voltage_sweep.py; mock recipes 12t12-4a-quick.yaml)"),
        Clause(number="1.3", title="Load and line regulation", **common,
               purpose="Output voltage change with load and with input voltage on the common valid grid.",
               requires={DC_STEADY}, procedure_status="real_fixed",
               procedure="steady_state_load_sweep with derived load_regulation and line_regulation_on_common_valid_grid "
                         "(extended.py real run; mock recipes)"),
        Clause(number="1.4", title="Dropout and minimum-input behaviour", **common,
               purpose="Operation while the input descends toward and below the stated minimum.",
               requires={DC_STEP_1S}, procedure_status="mock_only",
               procedure="startup_descent.py (real, fixed: 15 V start then descent to a programmed 9.1 V, observation only) "
                         "and uvlo.py uvlo_input_ramp (mock only, approval-gated below the DUT minimum)",
               notes=["A descent is not a dropout threshold or a UVLO measurement until the approved ramp runs on the real bench"]),
    ]


ISO16750_2: Standard = _iso16750_2()
STANDARDS: dict[str, Standard] = {ISO16750_2.id: ISO16750_2, **{s.id: s for s in _other_standards()}}
GENERIC_TESTS: list[Clause] = _generic_tests()

CATEGORY_DEFINITIONS: list[tuple[str, int, str, str, bool]] = [
    (CATEGORY_NORMAL, 1, "Normal operating voltage",
     "VIN sweep, efficiency, regulation and dropout with the existing DC procedures.", True),
    (CATEGORY_ISO16750_2, 2, "ISO 16750-2 supply profiles",
     "Undervoltage, overvoltage, cranking, interruptions, reset behaviour and reversed voltage; each clause is a checklist item.", True),
    (CATEGORY_ISO7637_2, 3, "ISO 7637-2 transients", "Conducted transient pulses from a calibrated generator.", False),
    (CATEGORY_EMC, 4, "EMC", "CISPR 25, ISO 11452 and ISO 10605 in an EMC laboratory.", False),
    (CATEGORY_ENVIRONMENTAL, 5, "Environmental", "ISO 16750-3 mechanical and ISO 16750-4 climatic loads.", False),
]


def clause(standard_id: str, number: str) -> Clause:
    return STANDARDS[standard_id].clause(number)


def catalog(bench: BenchProfile, dut: DutProfile, system: str) -> list[Category]:
    """The owner's five categories, each entry carrying its verdict and, when it runs, its recipe numbers."""
    _check_system(system)
    by_category: dict[str, list[Clause]] = {cid: [] for cid, *_ in CATEGORY_DEFINITIONS}
    by_category[CATEGORY_NORMAL].extend(GENERIC_TESTS)
    for standard in STANDARDS.values():
        for item in standard.tests():
            by_category[item.category].append(item)
    categories = []
    for cid, number, title, description, candidate in CATEGORY_DEFINITIONS:
        entries = [CatalogEntry(clause=item, feasibility=feasibility(item, bench, dut, system),
                                recipe=recipe_parameters(item, system, dut)) for item in by_category[cid]]
        categories.append(Category(id=cid, number=number, title=title, description=description,
                                   candidate_for_bench=candidate, entries=entries))
    return categories
