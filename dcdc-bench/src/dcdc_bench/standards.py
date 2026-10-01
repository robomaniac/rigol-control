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

Verdicts
--------
``runs_here``
    A procedure or explicitly bounded subset is available (4.2 is a DC-level
    subset on either bench; inspect coverage and conditions).
``runs_after_approval``
    The procedure exists on this bench and every parameter of the clause is
    met or approximated, but the generated recipe needs the owner's approval
    before it plans as executable: it steps below the DUT's stated minimum
    (brief §7.5), or its longest phase exceeds the real path's 660 s / 720 s
    policy and the recipe declares its own ``instrument_timed_bound_s``
    (owner decision 1 of 2026-10-01), or its level equals the converter's
    stated maximum (36.0 V exactly only with ``program_clause_level_exactly``,
    otherwise the 35.8 V margin setting, recorded as approximated; owner
    decision 6). Approval is recorded in the saved recipe file, not on the
    bench page; the verdict's ``approval_how`` says exactly where.
``best_effort``
    The bench can hold every level of the clause and command every timing,
    but at least one specified parameter (an edge time, a pulse or
    interruption duration, an open-circuit impedance) is realised by a
    mechanism whose achievable value lies outside the clause's tolerance or
    cannot be measured here (docs/standards/best-effort-proposal.md). The
    clause record declares the substitute for every missing instrument token
    (``Clause.best_effort``); the verdict carries the deviation sheet
    (``deviations``, ``deviation_summary``). Tickable, never pre-ticked,
    approval-gated like the UVLO ramp (``BEST_EFFORT_APPROVAL_HOW``); on a
    real profile it reads ``mock_only`` until a real procedure exists.
``mock_only``
    The procedure exists on the synthetic plant only and the profile is a
    real bench: planning refuses the test type as not yet approved for real
    hardware (``planning.REAL_HARDWARE_NOT_APPROVED``). 4.3.1.1, 4.5, 4.6.2
    and every best-effort clause today.
``needs_split``
    Retained for a recipe whose longest single stretch exceeds the real
    path's run envelope (one 660 s software deadline per run and a verified
    720 s one-shot source timer per input-voltage phase: ``extended.py``,
    ``real_backend.prepare_real_plan``, docs/configured-runs.md) and that
    cannot declare its own bound. Since owner decision 1 every ISO 16750-2
    recipe may declare ``authorization.instrument_timed_bound_s``, so the
    long clauses (4.3.1.1, 4.5) carry that as an approval condition instead
    and no clause of this catalog produces ``needs_split`` any more.
``needs_instrument`` / ``not_on_this_bench`` / ``excluded_by_policy`` /
``outside_dut_rating`` / ``not_applicable``
    As their names say; each carries the missing tokens or the rating.

Mock and real profiles of the same instrument class earn the same tokens,
but their verdicts differ where the procedure exists on the synthetic plant
only, where the real path's deadline applies, and where an approved
protective guard (``protective_controls.approved``) adds a condition.

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
UVLO-style recipe path. A level equal to the DUT maximum is refused for the
generic DC recipes because the endpoint method is not approved (the project
programs 35.8 V for a nominal 36 V); for the overvoltage holds (4.3.1.1,
4.3.2) the owner approves the endpoint per recipe (decision 6 of 2026-10-01):
the default recipe programs the margin setting and records it as
approximated, ``program_clause_level_exactly`` programs the clause value.
Ordinary supply/load polling is never labelled as a ripple, transient,
inrush or load-step measurement.

Best-effort deviation sheets (docs/standards/best-effort-proposal.md §2.2)
----------------------------------------------------------------------------
``deviation_sheet(number, system, dut, variant=..., program_clause_level_exactly=...)``
builds one ``DeviationSheet`` per best-effort clause and variant from
``recipe_parameters()`` and the tagged bounds below (``DS5`` DP800 datasheet
p. 5, ``LAN`` measured round trips, ``PG`` programming guide, clause 4.1
general tolerances). The classification is ``domain.classify_deviation``;
nothing here overrides it.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .domain import (LINE_INTERRUPTION_TEST_TYPE, MICRO_INTERRUPTION_TEST_TYPE, MOMENTARY_DROP_TEST_TYPE,
                     RESET_STAIRCASE_TEST_TYPE, SLOW_SUPPLY_RAMP_TEST_TYPE, TRANSIENT_HOLD_TEST_TYPE, BenchProfile, Contract,
                     DeviationAchievable, DeviationEntry, DeviationRequired, DeviationSheet, DutProfile, classify_deviation)

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
# Owner decision 6 (2026-10-01): for the overvoltage holds the endpoint is the owner's call per recipe.
EXACT_LEVEL_RECIPE_KINDS: frozenset[str] = frozenset({"overvoltage_hold", "transient_overvoltage"})
EXACT_LEVEL_NOTE = ("equals the converter's stated maximum; programmed exactly only with program_clause_level_exactly, "
                    "otherwise {margin:g} V (approximated)")  # .format(margin=...) with the programmed margin level
POLICY_CITATION = "implementation brief §2 and §7.5"

# --- Tagged bounds of the deviation sheets (docs/standards/best-effort-proposal.md, basis tags) -----------------
BASIS_ISO = "ISO 16750-2:2023"
BASIS_ISO_GENERAL = "ISO 16750-2:2023 clause 4.1 general tolerance"
BASIS_ISO_FIGURE = "ISO 16750-2:2023 figure value, confirmed by the owner 2026-10-01"
BASIS_DS5 = "DS5: DP800 datasheet p. 5"
BASIS_LAN = "LAN: measured round trips of the project's own queries (M2 evidence Table A4)"
BASIS_PG = "PG: DP800 programming guide, Timer/Delayer group times in whole seconds"
BASIS_UNV = "UNV: not stated in any document read"
BASIS_HOST = "host clock: the bench computer counts and timestamps its own commands"
# DP821A CH1 voltage programming control speed (1 % settle): rise < 110 ms loaded / < 30 ms unloaded,
# fall < 110 ms loaded / < 800 ms unloaded; command processing < 118 ms; programming accuracy 0.1 % + 25 mV.
DS5_RISE_S = (0.030, 0.110)
DS5_FALL_S = (0.110, 0.800)
DS5_COMMAND_PROCESSING_S = 0.118
DS5_PROGRAMMING_FRACTION, DS5_PROGRAMMING_OFFSET_V = 0.001, 0.025
# Measured LAN round trips: 4.1 ms min, 55 ms max.
LAN_ROUND_TRIP_S = (0.004, 0.055)
# Worst-case skew of an interval between two LAN commands: one transport maximum plus one processing maximum.
LAN_INTERVAL_SKEW_S = round(LAN_ROUND_TRIP_S[1] + DS5_COMMAND_PROCESSING_S, 3)
GENERAL_TIME_TOLERANCE = 0.05       # clause 4.1: frequency and time +/- 5 %
GENERAL_VOLTAGE_TOLERANCE_V = 0.2   # clause 4.1: voltage +/- 0.2 V
# Instrument-timed bounds the long recipes declare (owner decision 1): the hold or ramp direction plus margin.
INSTRUMENT_TIMED_BOUND_S = {"4.3.1.1": 3700.0, "4.5": {"12V": 1800.0, "24V": 3400.0}}
# Bench observation windows the best-effort recipes declare (bench choices, not clause parameters).
DROP_RECOVERY_WINDOW_S = 5.0
INTERRUPTION_RECOVERY_WINDOW_S = 10.0
OVP_SUGGESTION_MARGIN_V, OVP_SUGGESTION_FLOOR_V = 2.0, 14.0

# The real path's run envelope (docs/configured-runs.md): the real workers stop at one software deadline per run
# (extended.SOFTWARE_DEADLINE_S) and every input-voltage phase carries a verified one-shot source timer
# (extended.HARDWARE_DEADLINE_S); real_backend.prepare_real_plan refuses an acquisition estimate above the
# planning budget. The synthetic plant runs on a virtual clock and has none of these bounds.
REAL_PLANNING_BUDGET_S = 540.0
REAL_SOFTWARE_DEADLINE_S = 660.0
REAL_SOURCE_TIMER_S = 720.0
# planning.REAL_HARDWARE_NOT_APPROVED begins with these words; the catalog repeats them rather than importing planning.
REAL_HARDWARE_REFUSAL = "not yet approved for real hardware"
# Where the brief §7.5 approval of a below-minimum profile is recorded (planning.uvlo_approval_gaps checks every item).
APPROVAL_HOW = ("Approval happens in the saved recipe, not on the bench page: set authorization.uvlo_approved to true and "
                "authorization.protective_policy_id to the bench profile's protective_controls.policy_id, and declare "
                "source_current_limit_A, dut_output_overvoltage_V and output_overcurrent_A in that bench profile; the "
                "recipe is written unapproved and every level below the DUT minimum plans as approval_blocked until then")
# Where a best-effort recipe's approval is recorded (planning.best_effort_approval_gaps checks every item; owner decision 4).
BEST_EFFORT_APPROVAL_HOW = ("Approval happens in the saved recipe, not on the bench page: set authorization.best_effort_approved "
                            "to true, authorization.accepted_deviations_sha256 to the hash of the recipe's deviation sheet "
                            "(planning.recipe_deviations_sha256; a change to the sheet invalidates it) and "
                            "authorization.protective_policy_id to the bench profile's protective_controls.policy_id, and declare "
                            "source_current_limit_A, dut_input_overvoltage_V, dut_output_overvoltage_V and output_overcurrent_A in "
                            "that bench profile; the recipe is written unapproved and plans as approval_blocked until then, and "
                            "wherever the input goes below the DUT minimum (a drop level, output OFF) authorization.uvlo_approved "
                            "is needed as well")
# Where the approval of a recipe longer than the real path's policy is recorded (owner decision 1; planning checks the bound).
LONG_BOUND_APPROVAL_HOW = ("The recipe declares its own per-phase bound in authorization.instrument_timed_bound_s ({bound:g} s "
                           "for this recipe, above the real path's {deadline:g} s software deadline and {timer:g} s source timer) and "
                           "the operator approves that recipe; the planner refuses a phase longer than the declared bound and "
                           "plans the recipe as approval_blocked until it is approved")
# Recipe kind of a clause -> the saved-recipe test type its generated recipe uses.
RECIPE_TEST_TYPES: dict[str, str] = {"steady_min_max": "steady_state_load_sweep", "slow_ramp": SLOW_SUPPLY_RAMP_TEST_TYPE,
                                     "reset_staircase": RESET_STAIRCASE_TEST_TYPE, "overvoltage_hold": TRANSIENT_HOLD_TEST_TYPE,
                                     "jump_start": TRANSIENT_HOLD_TEST_TYPE, "transient_overvoltage": TRANSIENT_HOLD_TEST_TYPE,
                                     "momentary_drop": MOMENTARY_DROP_TEST_TYPE, "long_interruptions": MICRO_INTERRUPTION_TEST_TYPE,
                                     "line_interruption": LINE_INTERRUPTION_TEST_TYPE}
# Default variant of the clauses whose recipe offers more than one (owner decisions 7 and 8).
DEFAULT_VARIANTS: dict[str, str | None] = {"4.6.1.1": "B", "4.3.2": "A", "4.6.1.2": "case1-1s", "4.9.1": "method-1-positive-line"}
# Every variant a clause's recipe generates, in recipe order.
CLAUSE_VARIANTS: dict[str, list[str]] = {"4.6.1.1": ["B", "A"], "4.3.2": ["A", "B"],
                                         "4.6.1.2": ["case1-100ms", "case1-1s", "case1-2s", "case2-100ms", "case2-1s", "case2-10s"],
                                         "4.9.1": ["method-1-positive-line"]}
# Substitutes a clause may declare for a missing instrument token (proposal §2.1 step 2). Tokens absent here have no
# honest substitute and keep their clause at needs_instrument.
SUBSTITUTE_MECHANISMS: dict[str, str] = {
    EDGE_10MS: "the supply's own slew (DS5 1 % settle bounds), not a defined edge",
    PULSE_MS: "a LAN-commanded voltage step or output OFF/ON, host-timestamped; whole seconds by the supply's Timer or Delayer",
    LINE_SWITCH: "source output OFF/ON (the OFF-state impedance is not stated)",
    PULSE_US: "not substituted: the sub-100 ms cases are not offered (coverage partial)",
}

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

FeasibilityStatus = Literal["runs_here", "runs_after_approval", "best_effort", "mock_only", "needs_split", "needs_instrument",
                            "not_on_this_bench", "excluded_by_policy", "outside_dut_rating", "not_applicable"]
# Statuses whose clause can be ticked on the bench page (its recipe is generated and planned on this bench).
RUNNABLE_STATUSES: frozenset[str] = frozenset({"runs_here", "runs_after_approval", "best_effort"})
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
    # ``mock_only`` means the whole procedure exists on the synthetic plant only (a real profile gets the
    # ``mock_only`` verdict); a procedure that runs on real hardware with a mock-only part names that part.
    procedure_status: Literal["real_fixed", "mock_only", "recipe", "planned"] | None = None
    mock_only_part: str | None = None
    # For a clause the bench could run but has no procedure for yet: the concrete
    # requirement a procedure would have to meet (shown on the checklist row).
    procedure_gap: str | None = None
    # Best-effort declaration (proposal §2.1 step 2): for each instrument token the bench lacks, the mechanism this
    # bench substitutes. Every missing token must be declared or the verdict stays needs_instrument; a token whose
    # declaration begins with "not substituted" marks the part of the clause that is not offered (coverage partial).
    best_effort: dict[str, str] = Field(default_factory=dict)
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
    # The generated recipe needs the owner's approval before it plans as executable: it steps below the DUT's stated
    # minimum (brief §7.5), carries a best-effort deviation sheet, declares a per-phase bound above the real path's
    # policy, or programs a level equal to the converter's maximum. ``approval_how`` says where that is recorded.
    needs_approval: bool = False
    approval_how: str | None = None
    # Longest single stretch (hold, ramp direction or staircase) the recipe needs; compared with the real path's deadline.
    longest_phase_s: float | None = None
    # Best-effort clauses: the declared deviation sheet of the default variant and its one-line summary.
    deviations: list[DeviationEntry] = Field(default_factory=list)
    deviation_summary: str | None = None


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


def programmed_level_V(clause_level_V: float, dut: DutProfile, *, program_clause_level_exactly: bool = False) -> float:
    """The level a recipe programs for a clause level: the clause value, or the project's margin setting at the DUT maximum.

    A clause level equal to the converter's stated maximum is programmed at
    ``ENDPOINT_MARGIN_V`` below it (35.8 V for 36 V) unless the recipe declares
    ``program_clause_level_exactly`` (owner decision 6). Levels above the
    maximum are never programmed; callers refuse them first.
    """
    if clause_level_V >= dut.ratings.input_voltage_max_V and not program_clause_level_exactly:
        return round(dut.ratings.input_voltage_max_V - ENDPOINT_MARGIN_V, 4)
    return clause_level_V


def ovp_suggestion_V(top_level_V: float) -> float:
    """The source OVP a best-effort recipe suggests: just above its top level (proposal §4.1), at least 14 V."""
    return max(round(top_level_V + OVP_SUGGESTION_MARGIN_V, 2), OVP_SUGGESTION_FLOOR_V)


def recipe_parameters(clause: Clause, system: str, dut: DutProfile) -> dict[str, Any] | None:
    """Concrete levels, holds and ramp rates a recipe would need; None when nothing runs here.

    Computed from the standard's parameters and the DUT ratings only. Levels
    above the DUT's maximum give None: no recipe is derived for a level the
    project refuses. A level equal to the maximum is kept for the overvoltage
    holds (``EXACT_LEVEL_RECIPE_KINDS``) with ``programmed_level_V`` the margin
    setting and ``exact_level_V`` the clause value (owner decision 6).
    """
    _check_system(system)
    if clause.recipe_kind is None or system not in clause.systems:
        return None
    ratings = dut.ratings
    dut_min, dut_max = ratings.input_voltage_min_V, ratings.input_voltage_max_V
    params = clause.parameters.get(system, {})

    if clause.recipe_kind == "steady_min_max":
        code, usmin, usmax, notes = select_supply_code(system, dut)
        if usmax >= dut_max:
            return None
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "supply_code": code,
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
        if level > dut_max:
            return None
        programmed = programmed_level_V(level, dut)
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "level_V": level,
            "programmed_level_V": programmed, "exact_level_V": level, "level_equals_dut_maximum": level == dut_max,
            "base_V": UA_V[system], "duration_s": float(params["duration_s"]), "duration_tolerance_s": round(params["duration_s"] * GENERAL_TIME_TOLERANCE, 3),
            "repeats": 1, "mechanism": "supply_timer", "instrument_timed_bound_s": INSTRUMENT_TIMED_BOUND_S["4.3.1.1"],
            "ovp_suggestion_V": ovp_suggestion_V(programmed),
            "operating_mode": "3.4 (bounded by the 1 A source)", "functional_status": "C minimum",
            "temperature": "(Tmax - 20) K conditioning is not provided; the hold runs at room temperature and the "
                           "report records that deviation",
            "notes": ["a reviewed protective policy must set the DUT input overvoltage guard above the level",
                      "the base level UA before and after the hold is the project's choice of operating point; the clause "
                      "specifies the level and the duration only"]
                     + ([EXACT_LEVEL_NOTE.format(margin=programmed)] if level == dut_max else []),
        }

    if clause.recipe_kind == "jump_start":
        level = clause.peak_voltage_V[system]
        if level > dut_max:
            return None
        programmed = programmed_level_V(level, dut)
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "level_V": level,
            "programmed_level_V": programmed, "exact_level_V": level, "level_equals_dut_maximum": level == dut_max,
            "base_V": float(params["Usmin_V"]), "duration_s": float(params["ttrans_s"]), "duration_tolerance_s": float(params["ttrans_tolerance_s"]),
            "rest_s": float(params["trest_s"]), "rest_tolerance_s": round(params["trest_s"] * GENERAL_TIME_TOLERANCE, 3),
            "edge_max_s": float(params["trise_max_s"]), "repeats": int(params["n"]), "mechanism": "lan_voltage_step",
            "ovp_suggestion_V": ovp_suggestion_V(programmed),
            "operating_mode": "2.2 or 2.3 approximated as the converter enabled with the load input OFF or a light load",
            "functional_status": "C minimum",
            "temperature": "Tmin conditioning is not provided; the hold runs at room temperature and the report records that deviation",
            "notes": ["the level needs a reviewed protective policy whose DUT input overvoltage guard lies above it"],
        }

    if clause.recipe_kind == "transient_overvoltage":
        level = clause.peak_voltage_V[system]
        if level > dut_max:
            return None
        _code, _usmin, usmax, _notes = select_supply_code(system, dut)
        programmed = programmed_level_V(level, dut)
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "level_V": level,
            "programmed_level_V": programmed, "exact_level_V": level, "level_equals_dut_maximum": level == dut_max,
            "base_V": usmax, "duration_s": float(params["ttrans_s"]), "duration_tolerance_s": round(params["ttrans_s"] * GENERAL_TIME_TOLERANCE, 3),
            "rest_s": float(params["trest_s"]), "rest_tolerance_s": round(params["trest_s"] * GENERAL_TIME_TOLERANCE, 3),
            "edge_max_s": float(params["trise_s"]), "repeats": int(params["n"]),
            "variants": {"A": {"duration_s": float(params["ttrans_s"]), "mechanism": "lan_voltage_step",
                               "label": "clause-timed 400 ms plateau commanded over LAN"},
                         "B": {"duration_s": 1.0, "mechanism": "supply_timer", "label": "longer 1 s plateau timed by the supply"}},
            "ovp_suggestion_V": ovp_suggestion_V(programmed),
            "operating_mode": "3.4 (bounded by the 1 A source)", "functional_status": "B minimum",
            "notes": ["owner decision 7 (2026-10-01): hold the level as fast as the supply allows, 400 ms or longer, five times"]
                     + ([EXACT_LEVEL_NOTE.format(margin=programmed)] if level == dut_max else []),
        }

    if clause.recipe_kind == "momentary_drop":
        _code, usmin, _usmax, notes = select_supply_code(system, dut)
        if usmin > dut_max:
            return None
        drop = float(params["drop_level_V"])
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "from_V": usmin, "drop_level_V": drop,
            "drop_duration_s": float(params["drop_duration_s"]),
            "drop_duration_tolerance_s": round(params["drop_duration_s"] * GENERAL_TIME_TOLERANCE, 4),
            "edge_max_s": float(params["edge_max_s"]), "repeats": 1, "recovery_window_s": DROP_RECOVERY_WINDOW_S,
            "variants": {"A": {"duration_s": float(params["drop_duration_s"]), "mechanism": "lan_voltage_step",
                               "label": "clause-timed 100 ms drop commanded over LAN"},
                         "B": {"duration_s": 1.0, "mechanism": "supply_timer", "label": "supply-timed 1 s drop (default)"}},
            "ovp_suggestion_V": ovp_suggestion_V(usmin),
            "operating_mode": "3.4 (bounded by the 1 A source)", "functional_status": "B minimum",
            "below_dut_minimum": drop < dut_min,
            "approval": "a drop level below the DUT minimum needs the approved UVLO-style recipe (brief §7.5)",
            "notes": notes + ["drop level and duration are figure values confirmed by the owner (2026-10-01)"],
        }

    if clause.recipe_kind == "line_interruption":
        base = UB_V[system]
        if base > dut_max:
            return None
        method = params.get("method_1", params)
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "base_V": base,
            "interruption_s": float(method["interruption_s"]), "interruption_tolerance_s": float(method["tolerance_s"]),
            "open_resistance_ohm": float(method["open_resistance_ohm"]),
            "transition_max_s": float(method["transition_max_s"]) if "transition_max_s" in method else None,
            "repeats": 1, "recovery_window_s": INTERRUPTION_RECOVERY_WINDOW_S, "mechanism": "lan_output_off",
            "method": "method 1 on the positive line only" if clause.number == "4.9.1" else "the whole connector, realised as the positive line",
            "not_covered": ("method 2 (100 us bursts) and the return line" if clause.number == "4.9.1"
                            else "a two-wire input has only the positive line to interrupt"),
            "ovp_suggestion_V": ovp_suggestion_V(base),
            "operating_mode": ("3.4 (bounded by the 1 A source); outputs active / inactive as load ON / OFF variants"
                               if clause.number == "4.9.1" else "2.1 approximated as the converter enabled with the load input OFF; 3.4 bounded"),
            "functional_status": "C minimum",
            "approval": "output OFF takes the input to 0 V, below the DUT minimum: the approved UVLO-style recipe path applies (brief §7.5)",
        }

    if clause.recipe_kind == "slow_ramp":
        start = UA_V[system]
        if start >= dut_max:
            return None
        step_v, step_s = 0.02, 2.4  # 0.5 V/min, inside the 25 mV step ceiling and representable at 10 mV resolution
        steps = int(round(start / step_v))
        return {
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "start_V": start, "floor_V": 0.0,
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
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "supply_code": code, "Usmin_V": usmin,
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
            "clause": clause.citation, "system": system, "recipe_kind": clause.recipe_kind, "coverage": "partial", "base_V": base,
            "test_case_1": {"interruption_s": [round(1.0 + 0.1 * k, 1) for k in range(11)],
                            "recovery_s": "at least 5 s and until the DUT is fully serviceable"},
            "test_case_2": {"interruption_s": 1.0, "recovery_s": [float(k) for k in range(1, 11)]},
            # What the best-effort recipe offers (proposal §3, owner decision 7): the clause's own decade steps from
            # 100 ms up. 100 ms over LAN (commanded, not measured); 1 s and 2 s, and the 1 s and 10 s recoveries, timed
            # by the supply's Delayer in whole seconds.
            "offered": {"case1-100ms": {"interruption_s": 0.1, "recovery_s": 5.0, "mechanism": "lan_output_off"},
                        "case1-1s": {"interruption_s": 1.0, "recovery_s": 5.0, "mechanism": "supply_delayer"},
                        "case1-2s": {"interruption_s": 2.0, "recovery_s": 5.0, "mechanism": "supply_delayer"},
                        "case2-100ms": {"interruption_s": 1.0, "recovery_s": 0.1, "mechanism": "lan_output_off"},
                        "case2-1s": {"interruption_s": 1.0, "recovery_s": 1.0, "mechanism": "supply_delayer"},
                        "case2-10s": {"interruption_s": 1.0, "recovery_s": 10.0, "mechanism": "supply_delayer"}},
            "recovery_minimum_s": 5.0, "repeats": 1, "open_resistance_ohm": 1e7, "switch_reaction_max_s": 1e-5,
            "not_covered": "interruptions from 10 us to 10 ms and recoveries from 100 us to 10 ms (not offered)",
            "method_deviation": "the source output is switched OFF/ON by LAN command or by the supply's Delayer instead of a "
                                "series switch opening to 10 MOhm within 10 us; the output-off edge is not characterised",
            "ovp_suggestion_V": ovp_suggestion_V(base),
            "operating_mode": "3.4 (bounded by the 1 A source)",
            "functional_status": "C minimum for interruptions longer than 100 us",
            "approval": "output OFF takes the input to 0 V, below the DUT minimum: the approved UVLO-style recipe path applies (brief §7.5)",
        }
    return None


def longest_phase_s(params: dict[str, Any] | None) -> tuple[float, str] | None:
    """The longest single stretch a recipe needs, with its name, for the real-path deadline check.

    Declared holds and ramps only: settling and acquisition come on top. A
    slow ramp is one uninterrupted walk per direction; a staircase's lows and
    recoveries are one continuous sequence; a 4.2 sweep restarts per level, so
    its longest stretch is the t2 hold. None when the recipe has no stretch.
    """
    if not params:
        return None
    kind = params.get("recipe_kind")
    if kind == "slow_ramp":
        return float(params["duration_per_direction_s"]), "ramp per direction"
    if kind == "overvoltage_hold":
        return float(params["duration_s"]), "hold"
    if kind == "reset_staircase":
        lows = [v for v in params["low_levels_V"] if v > 0]
        return round(len(lows) * params["low_hold_s"] + (len(lows) + 1) * params["recovery_hold_s"], 1), "staircase of declared holds"
    if kind == "steady_min_max":
        return float(params["t2_s"]), "hold at one level"
    if kind in ("jump_start", "transient_overvoltage"):
        return max(float(params["duration_s"]), float(params["rest_s"])), "hold or rest"
    if kind == "momentary_drop":
        return float(params["recovery_window_s"]), "recovery observation after the drop"
    if kind == "long_interruptions":
        return max(max(case["interruption_s"], case["recovery_s"]) for case in params["offered"].values()), "interruption or recovery"
    if kind == "line_interruption":
        return max(float(params["interruption_s"]), float(params["recovery_window_s"])), "interruption or recovery"
    return None


# ---------------------------------------------------------------------------
# Deviation sheets (docs/standards/best-effort-proposal.md §2.2)
# ---------------------------------------------------------------------------

CLASSIFICATION_WORDS = {"met": "met", "approximated": "approximated", "not_met_but_documented": "not met (documented)",
                        "unknown_until_measured": "not measured (commanded)"}
# Clauses whose recipe carries a deviation sheet (every best-effort test type).
SHEET_CLAUSES: tuple[str, ...] = ("4.3.1.1", "4.3.1.2", "4.3.2", "4.6.1.1", "4.6.1.2", "4.9.1", "4.9.2")


def _programming_bound(level_V: float) -> list[float]:
    accuracy = DS5_PROGRAMMING_FRACTION * level_V + DS5_PROGRAMMING_OFFSET_V
    return [round(level_V - accuracy, 4), round(level_V + accuracy, 4)]


def _timed_bound(seconds: float, mechanism: str) -> tuple[list[float], str]:
    """The interval a commanded duration is bounded to, with its basis: whole seconds by the instrument, +/- skew over LAN."""
    if mechanism in ("supply_timer", "supply_delayer"):
        return [seconds, seconds], f"{BASIS_PG}; executed by the instrument clock (clock accuracy not stated)"
    skew = LAN_INTERVAL_SKEW_S
    return ([round(max(0.0, seconds - skew), 3), round(seconds + skew, 3)],
            f"{BASIS_LAN} 4-55 ms and {BASIS_DS5} command processing < 118 ms: +/- {skew * 1000:g} ms on an interval between two commands")


def _entry(parameter: str, unit: str | None, required: DeviationRequired, achievable: DeviationAchievable, mechanism: str,
           measured_by: str, note: str | None = None) -> DeviationEntry:
    return DeviationEntry(parameter=parameter, unit=unit, required=required, achievable=achievable, mechanism=mechanism,
                          measured_by=measured_by, classification=classify_deviation(required, achievable), note=note)


def _level_entry(parameter: str, clause_V: float, programmed_V: float, mechanism: str, measured_by: str, *,
                 basis: str = BASIS_ISO, note: str | None = None) -> DeviationEntry:
    substitute = programmed_V != clause_V
    required = DeviationRequired(value=clause_V, tolerance=GENERAL_VOLTAGE_TOLERANCE_V, basis=f"{basis}; {BASIS_ISO_GENERAL} +/- 0.2 V")
    achievable = DeviationAchievable(value=programmed_V, bound=_programming_bound(programmed_V),
                                     basis=f"{BASIS_DS5}: programming accuracy 0.1 % + 25 mV", substitute=substitute)
    if substitute:
        note = (f"programmed at the project's {programmed_V:g} V margin setting below the converter's stated maximum; "
                "program_clause_level_exactly programs the clause value (owner decision 6)" + (f"; {note}" if note else ""))
    return _entry(parameter, "V", required, achievable, mechanism, measured_by, note)


def _time_entry(parameter: str, clause_s: float, tolerance_s: float | None, commanded_s: float, mechanism: str, *,
                kind: str = "nominal", basis: str = BASIS_ISO, note: str | None = None) -> DeviationEntry:
    required = DeviationRequired(value=clause_s, tolerance=tolerance_s, kind=kind, basis=basis)
    bound, bound_basis = _timed_bound(commanded_s, mechanism)
    achievable = DeviationAchievable(value=commanded_s, bound=bound, basis=bound_basis, substitute=commanded_s != clause_s and kind == "nominal")
    measured_by = "host_clock" if mechanism.startswith("lan_") else "none"
    if measured_by == "none":
        note = "timed by the instrument; the host observes the program state at its ~1 s polls" + (f"; {note}" if note else "")
    else:
        note = "host-side command interval only; the interval at the converter terminals is not measured" + (f"; {note}" if note else "")
    return _entry(parameter, "s", required, achievable, mechanism, measured_by, note)


def _edge_entry(parameter: str, clause_max_s: float, direction: str, mechanism: str) -> DeviationEntry:
    figures = DS5_RISE_S if direction == "rise" else DS5_FALL_S
    words = "rise < 110 ms loaded / < 30 ms unloaded" if direction == "rise" else "fall < 110 ms loaded / < 800 ms unloaded"
    required = DeviationRequired(value=clause_max_s, kind="maximum", basis=BASIS_ISO)
    achievable = DeviationAchievable(value=None, bound=list(figures),
                                     basis=f"{BASIS_DS5}: voltage programming control speed (1 % settle), {words}")
    return _entry(parameter, "s", required, achievable, mechanism, "none",
                  "the supply's own slew, not a defined edge; the datasheet 1 % settle figures are treated as the edge figure "
                  "and are not measured on this unit")


def _count_entry(n: int, mechanism: str) -> DeviationEntry:
    required = DeviationRequired(value=float(n), tolerance=0.0, basis=BASIS_ISO)
    achievable = DeviationAchievable(value=float(n), bound=[float(n), float(n)], basis=BASIS_HOST)
    return _entry("repetitions", None, required, achievable, mechanism, "host_clock")


def _open_circuit_entry(minimum_ohm: float, mechanism: str) -> DeviationEntry:
    required = DeviationRequired(value=minimum_ohm, kind="minimum", basis=BASIS_ISO)
    achievable = DeviationAchievable(value=None, bound=None, basis=f"{BASIS_UNV}: OFF-state impedance of the DP821A output", substitute=True)
    return _entry("open_resistance_ohm", "ohm", required, achievable, mechanism, "none",
                  "source output OFF stops sourcing; it is not a demonstrated >= 10 MOhm open, and the converter's input "
                  "capacitance discharges into its own draw and whatever the OFF output presents")


def _transition_entry(clause_max_s: float, mechanism: str) -> DeviationEntry:
    required = DeviationRequired(value=clause_max_s, kind="maximum", basis=BASIS_ISO)
    achievable = DeviationAchievable(value=None, bound=None, basis=f"{BASIS_DS5}: the OFF command acts within < 118 ms; fall shape after OFF {BASIS_UNV}")
    return _entry("transition_s", "s", required, achievable, mechanism, "none",
                  "the DS5 speed figures bound setpoint changes, not an OFF command; no bound exists for the open transition")


def _switch_reaction_entry(clause_max_s: float, mechanism: str) -> DeviationEntry:
    required = DeviationRequired(value=clause_max_s, kind="maximum", basis=BASIS_ISO)
    achievable = DeviationAchievable(value=None, bound=[LAN_ROUND_TRIP_S[0], LAN_INTERVAL_SKEW_S],
                                     basis=f"{BASIS_LAN} 4-55 ms plus {BASIS_DS5} command processing < 118 ms")
    return _entry("switch_reaction_s", "s", required, achievable, mechanism, "none",
                  "a LAN command reaches the output after one round trip and its processing time; no series switch exists")


def _statement(number: str, asks: str, did: str, entries: list[DeviationEntry]) -> str:
    counts = {"met": 0, "approximated": 0, "not_met_but_documented": 0, "unknown_until_measured": 0}
    for entry in entries:
        counts[entry.classification] += 1
    met = counts["met"]
    return (f"ISO 16750-2 clause {number} asks for {asks}; this bench produced {did} "
            f"({met} parameter{'s' if met != 1 else ''} met, {counts['approximated']} approximated, "
            f"{counts['not_met_but_documented']} not met, {counts['unknown_until_measured']} not measured; see the deviation sheet).")


def deviation_sheet(number: str, system: str, dut: DutProfile, *, variant: str | None = None,
                    program_clause_level_exactly: bool = False) -> DeviationSheet:
    """The declared deviation sheet of a best-effort clause for this system and converter.

    One entry per parameter the clause records (level, hold or pulse duration,
    edges, rest or recovery, repetitions, open-circuit impedance, transition or
    switch reaction), built from ``recipe_parameters()`` and the tagged bounds;
    ``variant`` selects the realisation where the recipe offers more than one
    (``CLAUSE_VARIANTS``; None means the clause's default).
    """
    clause = ISO16750_2.clause(number)
    params = recipe_parameters(clause, system, dut)
    if params is None or number not in SHEET_CLAUSES:
        raise ValueError(f"{clause.citation} has no deviation sheet for a {system} system and this converter")
    variants = CLAUSE_VARIANTS.get(number)
    if variant is None:
        variant = DEFAULT_VARIANTS.get(number)
    if (variants is None and variant is not None) or (variants is not None and variant not in variants):
        raise ValueError(f"{clause.citation} has no variant {variant!r}")
    entries: list[DeviationEntry]
    if clause.recipe_kind == "overvoltage_hold":
        level = programmed_level_V(params["level_V"], dut, program_clause_level_exactly=program_clause_level_exactly)
        mechanism = params["mechanism"]
        entries = [_level_entry("level_V", params["level_V"], level, mechanism, "supply_readback",
                                note="the supply's ~1 s readback observes the held level at the source terminals"),
                   _time_entry("hold_s", params["duration_s"], params["duration_tolerance_s"], params["duration_s"], mechanism),
                   _count_entry(params["repeats"], mechanism)]
        asks = f"{params['level_V']:g} V held for {params['duration_s']:g} s"
        did = f"a {level:g} V level timed by the supply for {params['duration_s']:g} s from a {params['base_V']:g} V base"
    elif clause.recipe_kind == "jump_start":
        level = programmed_level_V(params["level_V"], dut, program_clause_level_exactly=program_clause_level_exactly)
        mechanism = params["mechanism"]
        entries = [_level_entry("level_V", params["level_V"], level, mechanism, "supply_readback",
                                note="the supply's ~1 s readback observes the held level at the source terminals"),
                   _time_entry("hold_s", params["duration_s"], params["duration_tolerance_s"], params["duration_s"], mechanism),
                   _edge_entry("edge_rise_s", params["edge_max_s"], "rise", mechanism),
                   _edge_entry("edge_fall_s", params["edge_max_s"], "fall", mechanism),
                   _time_entry("rest_s", params["rest_s"], params["rest_tolerance_s"], params["rest_s"], mechanism),
                   _count_entry(params["repeats"], mechanism)]
        asks = (f"{params['level_V']:g} V for {params['duration_s']:g} +/- {params['duration_tolerance_s']:g} s from "
                f"{params['base_V']:g} V with edges of at most {params['edge_max_s'] * 1000:g} ms and a {params['rest_s']:g} s rest")
        did = (f"a voltage step {params['base_V']:g} V -> {level:g} V -> {params['base_V']:g} V commanded over LAN and held "
               f"{params['duration_s']:g} s (edges are the supply's slew, datasheet-bounded, not measured)")
    elif clause.recipe_kind == "transient_overvoltage":
        level = programmed_level_V(params["level_V"], dut, program_clause_level_exactly=program_clause_level_exactly)
        chosen = params["variants"][variant]
        mechanism = chosen["mechanism"]
        entries = [_level_entry("level_V", params["level_V"], level, mechanism, "none",
                                note="a plateau shorter than or equal to the ~1 s readback refresh is not observed by the polls"),
                   _time_entry("pulse_s", params["duration_s"], params["duration_tolerance_s"], chosen["duration_s"], mechanism),
                   _edge_entry("edge_rise_s", params["edge_max_s"], "rise", mechanism),
                   _edge_entry("edge_fall_s", params["edge_max_s"], "fall", mechanism),
                   _time_entry("rest_s", params["rest_s"], params["rest_tolerance_s"], params["rest_s"], mechanism),
                   _count_entry(params["repeats"], mechanism)]
        asks = (f"{params['repeats']} pulses to {params['level_V']:g} V of {params['duration_s'] * 1000:g} ms from "
                f"{params['base_V']:g} V with {params['edge_max_s'] * 1000:g} ms edges and a {params['rest_s']:g} s rest")
        did = (f"{params['repeats']} voltage steps {params['base_V']:g} V -> {level:g} V -> {params['base_V']:g} V with a "
               f"{chosen['duration_s'] * 1000:g} ms plateau {'commanded over LAN' if mechanism.startswith('lan_') else 'timed by the supply'} "
               "(edges are the supply's slew, datasheet-bounded, not measured)")
    elif clause.recipe_kind == "momentary_drop":
        chosen = params["variants"][variant]
        mechanism = chosen["mechanism"]
        entries = [_level_entry("drop_level_V", params["drop_level_V"], params["drop_level_V"], mechanism, "none", basis=BASIS_ISO_FIGURE,
                                note="programmed level; whether the terminals reach it within the drop is covered by the duration row"),
                   _time_entry("drop_duration_s", params["drop_duration_s"], params["drop_duration_tolerance_s"], chosen["duration_s"],
                               mechanism, basis=BASIS_ISO_FIGURE),
                   _edge_entry("edge_fall_s", params["edge_max_s"], "fall", mechanism),
                   _edge_entry("edge_rise_s", params["edge_max_s"], "rise", mechanism)]
        asks = (f"a drop from Usmin {params['from_V']:g} V to {params['drop_level_V']:g} V for {params['drop_duration_s'] * 1000:g} ms "
                f"with edges of at most {params['edge_max_s'] * 1000:g} ms")
        did = (f"a voltage step to {params['drop_level_V']:g} V {'commanded for ' + format(chosen['duration_s'] * 1000, 'g') + ' ms over LAN' if mechanism.startswith('lan_') else 'held ' + format(chosen['duration_s'], 'g') + ' s by the supply timer'} "
               "(depth and interval at the terminals not measured; supply fall time datasheet-bounded < 110 ms loaded / < 800 ms unloaded)")
    elif clause.recipe_kind == "long_interruptions":
        case = params["offered"][variant]
        mechanism = case["mechanism"]
        interruption = _time_entry("interruption_s", case["interruption_s"], round(case["interruption_s"] * GENERAL_TIME_TOLERANCE, 4),
                                   case["interruption_s"], mechanism, basis=f"{BASIS_ISO} decade step; {BASIS_ISO_GENERAL} +/- 5 %")
        if variant.startswith("case1"):
            recovery = _time_entry("recovery_s", params["recovery_minimum_s"], None, case["recovery_s"], mechanism, kind="minimum",
                                   note="the clause asks for at least this and until the converter is fully serviceable")
        else:
            recovery = _time_entry("recovery_s", case["recovery_s"], round(case["recovery_s"] * GENERAL_TIME_TOLERANCE, 4), case["recovery_s"],
                                   mechanism, basis=f"{BASIS_ISO} decade step; {BASIS_ISO_GENERAL} +/- 5 %")
        entries = [_level_entry("base_V", params["base_V"], params["base_V"], mechanism, "supply_readback",
                                basis="ISO 16750-1 UB (alternator stopped), the base of ISO 16750-2:2023 clause 4.6.1.2",
                                note="the supply's ~1 s readback observes the base level at the source terminals"),
                   interruption, recovery, _open_circuit_entry(params["open_resistance_ohm"], mechanism),
                   _switch_reaction_entry(params["switch_reaction_max_s"], mechanism), _count_entry(params["repeats"], mechanism)]
        asks = (f"an interruption of {case['interruption_s']:g} s at {params['base_V']:g} V with a recovery of "
                f"{'at least ' if variant.startswith('case1') else ''}{case['recovery_s']:g} s through a switch opening to >= 10 MOhm within 10 us")
        did = (f"source output OFF for {case['interruption_s']:g} s then ON for {case['recovery_s']:g} s, "
               f"{'commanded over LAN (commanded, not measured)' if mechanism.startswith('lan_') else 'timed by the supply Delayer in whole seconds'}")
    else:  # line_interruption
        mechanism = params["mechanism"]
        entries = [_level_entry("base_V", params["base_V"], params["base_V"], mechanism, "supply_readback",
                                basis=f"ISO 16750-1 UB (alternator stopped), the base of ISO 16750-2:2023 clause {number}",
                                note="the supply's ~1 s readback observes the base level at the source terminals"),
                   _time_entry("interruption_s", params["interruption_s"], params["interruption_tolerance_s"], params["interruption_s"], mechanism),
                   _open_circuit_entry(params["open_resistance_ohm"], mechanism)]
        if params["transition_max_s"] is not None:
            entries.append(_transition_entry(params["transition_max_s"], mechanism))
        entries.append(_count_entry(params["repeats"], mechanism))
        asks = (f"{'one line' if number == '4.9.1' else 'the whole connector'} opened for {params['interruption_s']:g} +/- "
                f"{params['interruption_tolerance_s']:g} s to >= 10 MOhm" + (" within 10 ms" if params["transition_max_s"] else ""))
        did = (f"source output OFF for {params['interruption_s']:g} s on the positive line, commanded over LAN "
               "(the OFF-state impedance and the open transition are not measured)")
    return DeviationSheet(clause=number, variant=variant, entries=entries, statement=_statement(number, asks, did, entries))


def parameter_words(parameter: str) -> str:
    """``drop_duration_s`` -> ``drop duration``: the sheet's parameter name without its unit suffix."""
    for suffix in ("_s", "_V", "_ohm"):
        if parameter.endswith(suffix):
            parameter = parameter[: -len(suffix)]
            break
    return parameter.replace("_", " ")


def deviation_summary(sheet: DeviationSheet) -> str:
    """One line per sheet: each parameter with its classification word."""
    parts = []
    for entry in sheet.entries:
        value = entry.required.value
        shown = "" if value is None else (f" {value:g}" + (f" {entry.unit}" if entry.unit else ""))
        bound = {"maximum": "<=", "minimum": ">="}.get(entry.required.kind, "")
        parts.append(f"{parameter_words(entry.parameter)}{(' ' + bound) if bound else ''}{shown} {CLASSIFICATION_WORDS[entry.classification]}")
    return "; ".join(parts)


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
    # Proposal §2.1 step 2: a missing instrument token is acceptable only when the clause itself declares the
    # mechanism this bench substitutes; one undeclared token keeps the clause at needs_instrument.
    substituted = bool(missing) and all(token in clause.best_effort for token in missing)
    if missing and not substituted:
        return Feasibility(**base, status="needs_instrument", missing=missing, coverage="none",
                           reason=_sentence(f"{clause.title} needs {_describe(missing)}, which the bench supply "
                                            f"cannot produce; the {env.max_voltage_V:g} V DC envelope alone does not cover it"
                                            if env.max_voltage_V else
                                            f"{clause.title} needs {_describe(missing)}, which the bench supply cannot produce"))
    not_offered = [text for token, text in clause.best_effort.items() if token in missing and text.startswith("not substituted")]

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

    programmed_peak = peak
    endpoint_condition = None
    if peak is not None:
        if peak == ratings.input_voltage_max_V and clause.recipe_kind in EXACT_LEVEL_RECIPE_KINDS:
            # Owner decision 6: the endpoint is the owner's call per recipe for the overvoltage holds.
            programmed_peak = programmed_level_V(peak, dut)
            endpoint_condition = (f"The {peak:g} V level {EXACT_LEVEL_NOTE.format(margin=programmed_peak)}; programming {peak:g} V "
                                  f"exactly also needs a source whose maximum is at least {peak:g} V"
                                  + (f", which this bench's {env.max_voltage_V:g} V source is not"
                                     if env.max_voltage_V is not None and env.max_voltage_V < peak else ""))
        elif peak == ratings.input_voltage_max_V:
            return Feasibility(**base, status="outside_dut_rating", coverage="none",
                               missing=[f"{peak:g} V level vs DUT input maximum {ratings.input_voltage_max_V:g} V"],
                               reason=_sentence(f"The {peak:g} V level of {clause.citation} {ENDPOINT_REASON}"))
        if peak > ratings.input_voltage_max_V:
            return Feasibility(**base, status="outside_dut_rating", coverage="none",
                               missing=[f"{peak:g} V level vs DUT input maximum {ratings.input_voltage_max_V:g} V"],
                               reason=_sentence(f"The {peak:g} V level of {clause.citation} exceeds the DUT's rated "
                                                f"input maximum of {ratings.input_voltage_max_V:g} V"))
        if env.max_voltage_V is not None and programmed_peak > env.max_voltage_V:
            return Feasibility(**base, status="not_on_this_bench", coverage="none",
                               missing=[f"{programmed_peak:g} V level vs source maximum {env.max_voltage_V:g} V"],
                               reason=_sentence(f"The {programmed_peak:g} V level of {clause.citation} is above the source's "
                                                f"{env.max_voltage_V:g} V maximum"))

    conditions = list(code_notes)
    approvals: list[str] = []
    coverage: Coverage = "full"
    below_minimum = floor is not None and floor < ratings.input_voltage_min_V
    if below_minimum:
        conditions.append(f"Levels below the DUT's stated {ratings.input_voltage_min_V:g} V minimum need the approved "
                          f"UVLO-style recipe with a reviewed protective policy (brief §7.5)")
        conditions.append(APPROVAL_HOW)
        approvals.append(APPROVAL_HOW)
    if endpoint_condition:
        conditions.append(endpoint_condition)
    if programmed_peak is not None and env.protective_input_ceiling_V is not None and programmed_peak >= env.protective_input_ceiling_V:
        conditions.append(f"The {programmed_peak:g} V level is at or above the bench's approved DUT input overvoltage guard of "
                          f"{env.protective_input_ceiling_V:g} V; a reviewed protective policy must raise it first")
    if clause.environment - env.tokens:
        coverage = "room_temperature_only" if coverage == "full" else coverage
        conditions.append(f"Temperature conditioning needs {_describe(sorted(clause.environment - env.tokens))}; "
                          f"the electrical part runs at room temperature and the deviation is recorded")
    if clause.recipe_kind == "steady_min_max":
        coverage = "partial"
        conditions.append("DC level subset only: separate cold-started load sweeps at UA, Usmin and Usmax; "
                          "the t1/t2 holds and 1 V/s transitions are not reproduced. This is partial characterization, "
                          "not execution of the complete clause procedure.")
    if env.max_current_A is not None and ratings.output_power_rated_W > 0:
        conditions.append(f"Rated-load operating mode 3.4 is not reachable from a {env.max_current_A:g} A source; the run "
                          f"uses the bounded load grid the planner accepts (brief §3.2)")
    if clause.mock_only_part:
        conditions.append(f"{clause.mock_only_part} exists on the synthetic plant only today")

    # The deviation sheet of a best-effort-type recipe (proposal §2.2): its rows decide between a compliant run after
    # approval (every row met or approximated) and best effort (a row not met or not measured). The sheet is
    # bench-independent, so it travels with the mock_only verdict of a real profile as well.
    params = recipe_parameters(clause, system, dut)
    sheet = deviation_sheet(clause.number, system, dut) if clause.number in SHEET_CLAUSES and params is not None else None
    deviations = list(sheet.entries) if sheet else []
    summary = deviation_summary(sheet) if sheet else None
    shortfall = [e.parameter for e in deviations if e.classification in ("not_met_but_documented", "unknown_until_measured")]
    best_effort = substituted or bool(shortfall)
    if not_offered:
        coverage = "partial"
        conditions.append("Partial coverage: " + "; ".join(not_offered))
    if sheet is not None:
        conditions.append(f"Deviation sheet ({sheet.variant + ', default variant' if sheet.variant else 'declared'}): {summary}")
        conditions.append(BEST_EFFORT_APPROVAL_HOW)
        approvals.append(BEST_EFFORT_APPROVAL_HOW)

    # The real path's run envelope (owner decision 1: the recipe declares its own bound and is approved with it) and the
    # procedures that exist on the synthetic plant only.
    real = bench.mode == "real"
    test_type = RECIPE_TEST_TYPES.get(clause.recipe_kind or "", clause.recipe_kind or "this")
    stretch = longest_phase_s(params)
    longest = stretch[0] if stretch else None
    over_deadline = longest is not None and longest > REAL_SOFTWARE_DEADLINE_S
    if over_deadline:
        declared = INSTRUMENT_TIMED_BOUND_S.get(clause.number)
        bound = declared.get(system) if isinstance(declared, dict) else declared
        how = LONG_BOUND_APPROVAL_HOW.format(bound=bound if bound is not None else longest, deadline=REAL_SOFTWARE_DEADLINE_S,
                                             timer=REAL_SOURCE_TIMER_S)
        conditions.append(f"The {longest:g} s {stretch[1]} exceeds the real path's {REAL_SOFTWARE_DEADLINE_S:g} s software deadline "
                          f"and {REAL_SOURCE_TIMER_S:g} s source timer per phase (the synthetic plant's virtual clock has no such bound); "
                          f"{how[0].lower()}{how[1:]}")
        approvals.append(how)
    if clause.procedure_status == "mock_only" and not real:
        conditions.append(f"Synthetic plant only: planning refuses {test_type} on a real bench as {REAL_HARDWARE_REFUSAL}")
    needs_approval = bool(approvals)
    verdict: dict[str, Any] = dict(**base, conditions=conditions, needs_approval=needs_approval, missing=missing,
                                   approval_how=" ".join(dict.fromkeys(approvals)) if approvals else None,
                                   longest_phase_s=longest, deviations=deviations, deviation_summary=summary)

    if clause.procedure_status == "mock_only" and real:
        kind_words = "best-effort " if best_effort else ""
        return Feasibility(**verdict, status="mock_only", coverage="none",
                           reason=_sentence(f"The {kind_words}{test_type} procedure for {clause.citation} exists on the synthetic plant "
                                            f"only; planning refuses it on a real bench as {REAL_HARDWARE_REFUSAL}"))

    if best_effort:
        words = ", ".join(parameter_words(p) for p in shortfall) if shortfall else "the substituted parameters"
        reason = (f"The bench can only approximate {clause.citation}: {words} lie outside the clause tolerance or are not "
                  f"measured here (recorded in the deviation sheet), and the saved recipe plans as executable only after the "
                  f"owner approves it with the accepted deviations")
        return Feasibility(**verdict, status="best_effort", reason=_sentence(reason), coverage=coverage)

    reason = (f"The bench source can hold {level_text} of {clause.citation} as DC levels within its "
              f"{env.max_voltage_V:g} V envelope and the DUT's {ratings.input_voltage_min_V:g}-{ratings.input_voltage_max_V:g} V rating"
              if env.max_voltage_V is not None else
              f"The bench source can hold {level_text} of {clause.citation} as DC levels")
    if clause.standard_id == BENCH_ID:
        reason = (f"{clause.title} is an ordinary DC supply and load measurement within the source's "
                  f"{env.max_voltage_V:g} V envelope and the DUT's {ratings.input_voltage_min_V:g}-{ratings.input_voltage_max_V:g} V rating"
                  if env.max_voltage_V is not None else f"{clause.title} is an ordinary DC supply and load measurement")
    if clause.recipe_kind == "steady_min_max":
        reason += "; only a DC level subset is implemented, with no t1/t2 hold profile or 1 V/s transitions"
    if needs_approval:
        why = []
        if below_minimum:
            why.append(f"levels below the {ratings.input_voltage_min_V:g} V DUT minimum")
        if over_deadline:
            why.append(f"a {longest:g} s {stretch[1]} above the {REAL_SOURCE_TIMER_S:g} s policy bound")
        if endpoint_condition:
            why.append(f"a {peak:g} V level at the converter's maximum")
        if sheet is not None and not why:
            why.append("its declared deviation sheet")
        reason += f", and plans as executable only after the saved recipe is approved (brief §7.5) for {' and '.join(why)}"
        return Feasibility(**verdict, status="runs_after_approval", reason=_sentence(reason), coverage=coverage)
    return Feasibility(**verdict, status="runs_here", reason=_sentence(reason), coverage=coverage)


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
           recipe_kind="steady_min_max", procedure_status="recipe",
           procedure="steady_state_load_sweep recipe at UA, Usmin and Usmax with a small load grid (each level a "
                     "cold-started DC point; the t1/t2 hold profile is not reproduced)",
           notes=["Redundant supplies: every Usmin/Usmax combination across ports"]),
        _c("4.3", "Overvoltage", "Long-term and transient overvoltage on the supply.", kind="heading"),
        _c("4.3.1", "Long term overvoltage", "Alternator-failure and jump-start overvoltage holds.", kind="heading"),
        _c("4.3.1.1", "Long term overvoltage: alternator regulator failure at (Tmax - 20) K",
           "Simulate a failed alternator regulator raising the supply for an hour.",
           parameters={"12V": {"level_V": 18.0, "duration_s": 3600.0, "temperature": "Tmax - 20 K", "operating_mode": "3.4"},
                       "24V": {"level_V": 36.0, "duration_s": 3600.0, "temperature": "Tmax - 20 K", "operating_mode": "3.4"}},
           peak_voltage_V={"12V": 18.0, "24V": 36.0}, requires={DC_STEADY}, environment={CLIMATIC_CHAMBER},
           functional_status="C minimum; A where more stringent", recipe_kind="overvoltage_hold",
           procedure_status="mock_only",
           procedure="transient_hold recipe (synthetic plant only): the clause level held 3600 s from a UA base, timed by the "
                     "supply; the recipe declares its own instrument_timed_bound_s (owner decision 1); refused on real benches",
           notes=["at 24 V the 36 V level equals the converter's stated maximum: programmed at 35.8 V by default (approximated) "
                  "or exactly with program_clause_level_exactly (owner decision 6)"]),
        _c("4.3.1.2", "Long term overvoltage: jump start (12 V systems only)",
           "Simulate a jump start from a 24 V donor without its engine running.", systems={"12V"},
           parameters={"12V": {"Utrans_V": 26.0, "ttrans_s": 60.0, "ttrans_tolerance_s": 6.0, "trise_max_s": 0.01,
                               "tfall_max_s": 0.01, "trest_s": 120.0, "Usmin_V": 10.8, "n": 1,
                               "temperatures": "room temperature and Tmin", "operating_mode": "2.2 if needed for engine start, else 2.3"}},
           peak_voltage_V={"12V": 26.0}, minimum_voltage_V={"12V": 10.8}, requires={DC_STEADY, EDGE_10MS}, environment={CLIMATIC_CHAMBER},
           functional_status="C minimum; A where more stringent", recipe_kind="jump_start", procedure_status="mock_only",
           best_effort={EDGE_10MS: SUBSTITUTE_MECHANISMS[EDGE_10MS]},
           procedure="transient_hold recipe (synthetic plant only, best effort): 10.8 V -> 26 V -> 10.8 V commanded over LAN, "
                     "held 60 s, rest 120 s; the edges are the supply's slew and the deviation sheet says so"),
        _c("4.3.2", "Transient overvoltage", "Simulate switching loads that inject current into the distribution system.",
           parameters={"12V": {"Utrans_V": 18.0, "ttrans_s": 0.4, "trise_s": 0.001, "tfall_s": 0.001, "trest_s": 1.0, "n": 5,
                               "base": "Usmax", "operating_mode": "3.4"},
                       "24V": {"Utrans_V": 36.0, "ttrans_s": 0.4, "trise_s": 0.002, "tfall_s": 0.002, "trest_s": 1.0, "n": 5,
                               "base": "Usmax", "operating_mode": "3.4"}},
           peak_voltage_V={"12V": 18.0, "24V": 36.0}, minimum_voltage_V={"12V": 16.0, "24V": 32.0}, requires={PULSE_MS},
           functional_status="B minimum; C by agreement", recipe_kind="transient_overvoltage", procedure_status="mock_only",
           best_effort={PULSE_MS: SUBSTITUTE_MECHANISMS[PULSE_MS]},
           procedure="transient_hold recipe (synthetic plant only, best effort; owner decision 7): five steps Usmax -> level -> Usmax "
                     "with a 400 ms plateau commanded over LAN (variant A) or a 1 s plateau timed by the supply (variant B)"),
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
           functional_status="A inside the Table 3/4 range; D minimum outside it", recipe_kind="slow_ramp",
           procedure_status="mock_only",
           procedure="slow_supply_ramp recipe (supply_profiles.py, synthetic plant only): 20 mV live steps every 2.4 s "
                     "between 1 V observation levels; refused on real benches"),
        _c("4.6", "Discontinuities in supply voltage", "Drops, interruptions, reset behaviour, cranking and load dump.", kind="heading"),
        _c("4.6.1", "Drops or interrupts in supply voltage", "Momentary drop and micro interruptions.", kind="heading"),
        _c("4.6.1.1", "Momentary drop in supply voltage", "Simulate a fuse element melting in a parallel circuit.",
           parameters={"12V": {"from": "Usmin", "drop_level_V": 4.5, "drop_duration_s": 0.1, "edge_max_s": 0.01, "operating_mode": "3.4",
                               "figure_values": "drop level and duration appear in Figure 7 only; confirm on the printed copy"},
                       "24V": {"from": "Usmin", "drop_level_V": 9.0, "drop_duration_s": 0.1, "edge_max_s": 0.01, "operating_mode": "3.4",
                               "figure_values": "drop level and duration appear in Figure 8 only; confirm on the printed copy"}},
           peak_voltage_V={"12V": 10.5, "24V": 22.0}, minimum_voltage_V={"12V": 4.5, "24V": 9.0}, requires={PULSE_MS, EDGE_10MS},
           functional_status="B minimum; C by agreement", recipe_kind="momentary_drop", procedure_status="mock_only",
           best_effort={PULSE_MS: SUBSTITUTE_MECHANISMS[PULSE_MS], EDGE_10MS: SUBSTITUTE_MECHANISMS[EDGE_10MS]},
           procedure="momentary_drop recipe (synthetic plant only, best effort): Usmin -> drop level -> Usmin; variant B holds the "
                     "drop 1 s timed by the supply (default, owner decision 8), variant A commands the clause's 100 ms over LAN"),
        _c("4.6.1.2", "Micro interruption in supply voltage",
           "Simulate contact faults, relay bounce and switch-over to a redundant supply.",
           parameters={s: {"base_V": UB_V[s],
                           "test_case_1": {"tmicro": "10 us to 2 s in decade steps of 10 us, 100 us, 1 ms, 10 ms, 100 ms",
                                           "trecovery_s": "at least 5 and until fully serviceable", "n": 1},
                           "test_case_2": {"tmicro_s": "at least 0.1 and until reset",
                                           "trecovery": "100 us to 10 s in decade steps of 100 us, 1 ms, 10 ms, 100 ms, 1 s", "n": 1},
                           "switch": "reaction time at most 10 us, open resistance at least 10 MOhm, checked with 1 kOhm and 10 Ohm references",
                           "operating_mode": "3.4"} for s in both},
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0}, requires={PULSE_US, LINE_SWITCH},
           functional_status="A for interruptions up to 100 us; C minimum above", recipe_kind="long_interruptions",
           procedure_status="mock_only",
           best_effort={LINE_SWITCH: SUBSTITUTE_MECHANISMS[LINE_SWITCH],
                        PULSE_US: "not substituted: interruptions and recoveries below 100 ms are not offered (coverage partial)"},
           procedure="micro_interruption recipe (synthetic plant only, best effort, partial): source output OFF for 100 ms over LAN "
                     "(commanded, not measured) and for 1 s / 2 s timed by the supply Delayer, recoveries 100 ms, 1 s, 5 s and 10 s"),
        _c("4.6.2", "Reset behaviour at voltage drop", "Check reset behaviour of microcontroller equipment at stepped voltage drops.",
           parameters={s: {"start": "Usmin of the chosen code", "step_fraction_of_Usmin": 0.05, "low_hold_min_s": 5.0,
                           "recovery_hold_min_s": 10.0, "functional_test": "at Usmin after each recovery", "end_V": 0.0,
                           "operating_mode": "3.4"} for s in both},
           peak_voltage_V={"12V": 10.5, "24V": 22.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0}, uses_supply_code=True,
           requires={DC_STEP_1S}, functional_status="C minimum", recipe_kind="reset_staircase",
           procedure_status="mock_only",
           procedure="reset_staircase recipe (supply_profiles.py, synthetic plant only): Usmin and 5 % lows alternate with "
                     ">=5 s / >=10 s holds; refused on real benches",
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
                                       "from_UB_V": 24.0, "recovery_s": 120.0, "n": 1},
                       "to_verify": "the -26 V level is to be verified against the owner's copy of the standard; the "
                                    "power-electronics review recalls -28 V from an earlier edition"}},
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
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0},
           requires={LINE_SWITCH, PULSE_US}, functional_status="C minimum; D by agreement", recipe_kind="line_interruption",
           procedure_status="mock_only",
           best_effort={LINE_SWITCH: SUBSTITUTE_MECHANISMS[LINE_SWITCH],
                        PULSE_US: "not substituted: method 2 (100 us bursts) and the return line are not offered (coverage partial)"},
           procedure="line_interruption recipe (synthetic plant only, best effort): method 1 on the positive line as source output "
                     "OFF for 10 s commanded over LAN; the OFF-state impedance is not a demonstrated 10 MOhm open"),
        _c("4.9.2", "Multiple line interruption", "Simulate unplugging the whole connector.",
           parameters={s: {"interruption_s": 10.0, "tolerance_s": 1.0, "open_resistance_ohm": 1e7,
                           "operating_modes": "2.1 and 3.4"} for s in both},
           peak_voltage_V={"12V": 12.0, "24V": 24.0}, minimum_voltage_V={"12V": 0.0, "24V": 0.0},
           requires={LINE_SWITCH}, functional_status="C minimum; D by agreement", recipe_kind="line_interruption",
           procedure_status="mock_only", best_effort={LINE_SWITCH: SUBSTITUTE_MECHANISMS[LINE_SWITCH]},
           procedure="line_interruption recipe (synthetic plant only, best effort): the whole two-wire connector is the positive "
                     "line, source output OFF for 10 s commanded over LAN; the OFF-state impedance is not a demonstrated 10 MOhm open"),
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
                           "UA/UB and the functional status classes come from ISO 16750-1",
                           "Which sub-clauses are new in the 2023 edition, and the 24 V reversed-voltage level of 4.7, are to be "
                           "verified against the owner's copy of the standard; no edition history is asserted here"])


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
               requires={DC_STEP_1S}, procedure_status="real_fixed",
               procedure="startup_descent.py (real, fixed: 15 V start then descent to a programmed 9.1 V, observation only) "
                         "and uvlo.py uvlo_input_ramp (mock only, approval-gated below the DUT minimum)",
               mock_only_part="The below-minimum part of this test (the uvlo.py input ramp)",
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
