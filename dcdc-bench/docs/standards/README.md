# Automotive standards catalog

What the bench page's "Which test?" checklist is built from: which clauses of
which automotive standards this bench can honestly run, which need another
instrument, which belong to a different laboratory, and which the project
excludes by policy. The code is `src/dcdc_bench/standards.py`; the tests are
`tests/test_standards.py`.

Rules that apply to everything in this folder:

- Only technical facts are recorded: clause numbers, titles, levels,
  durations, rates, impedances and functional status classes, cited as
  "<standard>, clause <number>". No standard text is reproduced and no
  standard document is stored in the repository (implementation brief §16).
- A verdict is one of the following, each with a one-sentence reason a
  technician can read and, when it runs, the conditions that still apply
  (below-minimum steps need the approved UVLO-style recipe; rated load is
  unreachable from a 1 A source; temperature conditioning is absent):
  - `runs_here` — a procedure or test subset is available. Clause 4.2 is
    a **DC level subset**, ticked by default: the full timed profile is not
    implemented; the badge and report state the partial coverage;
  - `runs_after_approval` — the procedure exists on this bench and every
    clause parameter is met or approximated, but the generated recipe needs
    the owner's approval before it plans as executable: it steps below the
    converter's stated minimum (brief §7.5), or its longest phase exceeds the
    real path's 660 s / 720 s policy and the recipe declares its own
    `authorization.instrument_timed_bound_s` (owner decision 1 of 2026-10-01:
    approved per recipe), or its level equals the converter's maximum (owner
    decision 6). Badge "runs here after approval", tickable but never
    pre-ticked. Approval is recorded in the saved recipe file, not on the
    page: `authorization.uvlo_approved: true` and
    `authorization.protective_policy_id` naming the bench profile's
    `protective_controls.policy_id`, with `source_current_limit_A`,
    `dut_output_overvoltage_V` and `output_overcurrent_A` declared in that
    bench profile (`planning.uvlo_approval_gaps` lists whatever is missing;
    `standards.APPROVAL_HOW` is the sentence the page shows); the verdict's
    `approval_how` adds the bound or best-effort sentence where one applies;
  - `best_effort` — the bench can hold every level of the clause and command
    every timing, but at least one specified parameter (an edge time, a pulse
    or interruption duration, an open-circuit impedance) is realised by a
    mechanism whose achievable value lies outside the clause's tolerance or
    cannot be measured here ([best-effort-proposal.md](best-effort-proposal.md)).
    The clause record declares the substitute for every missing instrument
    token (the supply's own slew for edges, a LAN-commanded step or the
    supply's Timer/Delayer for timings, source output OFF for an open); the
    verdict carries the **deviation sheet**: one row per clause parameter with
    the clause value, the bench value and its basis, the mechanism, whether
    the bench measures it, and a classification by one mechanical rule (`met`
    / `approximated` / `not_met_but_documented` / `unknown_until_measured`,
    `domain.classify_deviation`). Badge "best effort (deviations recorded)",
    amber, tickable but never pre-ticked. Approval is the UVLO gate extended
    (owner decision 4): `authorization.best_effort_approved: true`,
    `authorization.accepted_deviations_sha256` equal to the hash of the
    recipe's deviation sheet (`planning.recipe_deviations_sha256`; an edited
    sheet invalidates the approval), the bench's protective policy id and
    its `dut_input_overvoltage_V` guard as well, plus `uvlo_approved`
    wherever the input goes below the DUT minimum (a drop level, output OFF);
    `planning.best_effort_approval_gaps` lists whatever is missing and
    `standards.BEST_EFFORT_APPROVAL_HOW` is the sentence the page shows.
    Terminal-side timings stay "commanded, not measured" until a scope or
    DAQ exists (owner decisions 3 and 5); the word "achieved" is reserved for
    measured values;
  - `mock_only` — the procedure exists on the synthetic plant only and the
    selected profile is a real bench: planning refuses the test type as "not
    yet approved for real hardware". Badge "mock only", not tickable. Today
    this is 4.3.1.1, 4.5, 4.6.2 and every best-effort clause on a real
    profile;
  - `needs_split` — retained for a recipe whose longest single stretch (a
    hold, a ramp direction, a staircase of declared holds) exceeds the real
    path's run envelope (one 660 s software deadline per run and a verified
    720 s one-shot source timer per input-voltage phase: `extended.py`,
    `real_backend.prepare_real_plan`, [configured-runs.md](../configured-runs.md))
    and that cannot declare its own bound. Since owner decision 1 every
    ISO 16750-2 recipe may declare `authorization.instrument_timed_bound_s`,
    so the long clauses (4.3.1.1, 4.5) carry the bound as an approval
    condition instead and no clause of this catalog produces `needs_split`;
  - `needs_instrument`, `not_on_this_bench`, `excluded_by_policy`,
    `outside_dut_rating`, `not_applicable` — as named, with the missing
    tokens or the rating in the reason.
- Reverse voltage, short circuit, overload and load dump stay excluded even if
  an instrument existed (brief §2 and §7.5). A level equal to the DUT maximum
  is refused for the generic DC recipes: the endpoint method is not approved
  (the project programs 35.8 V for a nominal 36 V). For the overvoltage holds
  (4.3.1.1, 4.3.2) the owner approves the endpoint per recipe (decision 6):
  the default recipe programs 35.8 V and the sheet records it as
  approximated; `program_clause_level_exactly` programs 36.0 V.
- Ordinary supply/load polling is never labelled as a ripple, transient, inrush
  or load-step measurement (brief §2).

## Documents

| Document | What it is |
| --- | --- |
| [iso16750-2.md](iso16750-2.md) | ISO 16750-2:2023 section 4, clause by clause: 12 V and 24 V parameters, functional status class, capability needed, bench verdict for the 12T12-4A, the capability-token mapping and the recipe numbers for the clauses that run here. |
| [instrument-sequencing-dp800.md](instrument-sequencing-dp800.md) | What the DP821A's own Timer, Delayer, Monitor, Trigger I/O and Recorder can and cannot do for ISO 16750-2 section 4 (whole-second timing, measured rise/fall bounds, Timer/Delayer exclusivity), with a clause-by-clause instrument-timed verdict, a fail-closed `SupplyProgram` design and the bench checks it needs; sourced to the DP800 datasheet, user guide and programming guide by page. |
| [load-programs-dl3000.md](load-programs-dl3000.md) | What the DL3031A's own transient (continuous/pulse/toggle), list, OCP/OPP and battery modes can and cannot do on this bench: a bus-fired CC pulse is a defined stimulus with an unmeasured response until a scope or DAQ is added; the OCP application cannot replace the software source-limit search because the 1 A supply limit is reached first; the fail-closed arming design and the read-only bench checks; sourced to the DL3000 user guide, datasheet and programming guide by page. |
| [best-effort-proposal.md](best-effort-proposal.md) | The `best_effort` verdict with its per-clause deviation sheet, so clauses this bench can only approximate run with the deviations recorded in the report ("commanded, not measured" until a scope or DAQ exists); clause-by-clause compromise table, protective settings, mock-first plan, and the owner's decisions of 2026-10-01 (§8) that the catalog, recipes and planner now follow. |
| [switch-box-design.md](switch-box-design.md) | Design document for the owner's proposed relay/MOSFET switch box between supply and converter: what it unlocks per clause (true open for 4.9.x, interruptions for 4.6.1.2, a two-source drop for 4.6.1.1), fail-safe disconnect with a hardware heartbeat, DC contact ratings and suppression, Pi-GPIO first build with an MCU upgrade path, the `SwitchAdapter` contract, bench checks and acceptance tests; 4.7 reversal only as an owner-approved policy exception. |

## Categories on the bench page

| # | Category | Entries | Candidate for this bench |
| --- | --- | --- | :-: |
| 1 | Normal operating voltage | VIN sweep, efficiency, load/line regulation, dropout and minimum-input behaviour, mapped to the existing `steady_state_load_sweep` recipes, the fixed real workers (`voltage_sweep.py`, `extended.py`, `startup_descent.py`) and the mock-only UVLO ramp (`uvlo.py`) | yes |
| 2 | ISO 16750-2 supply profiles | every test clause of section 4 as a checklist item | yes: DC level subset of 4.2 on either bench; 4.3.1.1, 4.5 and 4.6.2 on the simulated bench only, after approval; 4.3.1.2, 4.3.2, 4.6.1.1, 4.6.1.2, 4.9.1 and 4.9.2 as best-effort recipes on the simulated bench only, after approval with their deviation sheets |
| 3 | ISO 7637-2 transients | one entry: pulses 1, 2a, 2b, 3a, 3b (ISO 7637-2:2011, clause 5.6) | no: transient generator |
| 4 | EMC | CISPR 25, ISO 11452 (all parts), ISO 10605 | no: EMC chamber, ESD simulator |
| 5 | Environmental | ISO 16750-3 mechanical, ISO 16750-4 climatic | no: shaker, climatic chamber |

The bench page renders this catalog as the "Automotive supply standards" group of "Which test?" (`src/dcdc_bench/standard_recipes.py`): the ISO 16750-2 card expands into the clause checklist and identifies the available DC level subset and separately counts approval-required, best-effort and mock-only procedures. "Add as tests" turns 4.2 into a `steady_state_load_sweep` recipe (separate cold starts; the t1/t2 holds and 1 V/s transitions are not reproduced, as the report now states), 4.5 / 4.6.2 into the `slow_supply_ramp` / `reset_staircase` recipes that `src/dcdc_bench/supply_profiles.py` executes on the synthetic plant, 4.3.1.1 / 4.3.1.2 / 4.3.2 into `transient_hold`, 4.6.1.1 into `momentary_drop` (variant B, the supply-timed 1 s drop, first; variant A, the clause's 100 ms over LAN, next to it), 4.6.1.2 into `micro_interruption` (one test per offered case: 100 ms over LAN, 1 s and 2 s by the supply's Delayer, recoveries 100 ms, 1 s, 5 s and 10 s) and 4.9.1 / 4.9.2 into `line_interruption` (the four best-effort types that `src/dcdc_bench/best_effort_procedures.py` executes on the synthetic plant, gated by `planning.best_effort_approval_gaps`); every one of those recipes carries its deviation sheet, is written unapproved on purpose (approving it is the owner's act, see `runs_after_approval` and `best_effort` above) and is offered unticked. See [docs/bench-ui.md](../bench-ui.md#automotive-standards-in-which-test).

## Printing the catalog

```python
from dcdc_bench import standards
from dcdc_bench.domain import BenchProfile, DutProfile
from dcdc_bench.planning import load_profile

bench = load_profile("profiles/bench/mock.yaml", BenchProfile)
dut = load_profile("profiles/dut/12t12-4a.yaml", DutProfile)
for category in standards.catalog(bench, dut, "12V"):
    for entry in category.entries:
        print(category.number, entry.clause.number, entry.feasibility.status, entry.feasibility.reason)
```

## Where each clause runs (12T12-4A)

Capability tokens are the same for the mock and the seeded real profile (both
declare a single-quadrant, LAN-polled DC supply), so the verdicts differ only
where the procedure exists on the synthetic plant only, where the real path's
run deadline applies, or where the real profile's approved guard adds a
condition. `tests/test_standards.py` pins exactly this set of differences.

| Clause | Simulated bench (`profiles/bench/mock.yaml`) | Seeded real bench (35.8 V / 1 A, approved 26 V input guard) | What is still needed |
| --- | --- | --- | --- |
| 4.2 | `runs_here`, partial DC level subset (room temperature only) | `runs_here`, partial DC level subset; at 24 V the 28 V and 32 V levels are above the 26 V guard and stay in the plan as unsupported | a reviewed protective policy raising the guard for the 24 V levels; a climatic chamber for modes 3.3/3.4 at Tmin/Tmax |
| 4.3.1.1 | `runs_after_approval`: `transient_hold` (3600 s timed by the supply) with the recipe's own 3700 s `instrument_timed_bound_s`; at 24 V the 36 V level is programmed at 35.8 V (approximated) or exactly with `program_clause_level_exactly` | `mock_only`: planning refuses the test type on real hardware; exact 36 V also exceeds the 35.8 V source | owner approval of the recipe and its bound (simulation); a real procedure for real hardware |
| 4.3.1.2 (12 V) | `best_effort`: `transient_hold` 10.8 V -> 26 V (60 s) -> 10.8 V over LAN; edges are the supply's slew (not met), level, hold and rest met | `mock_only`; the 26 V level is at the 26 V guard | approval with the deviation sheet; a reviewed policy with a guard above 26 V; a scope for the edges |
| 4.3.2 | `best_effort`: `transient_hold` Usmax -> level x 5 with a 400 ms plateau over LAN (A, not measured) or 1 s by the supply (B, not met); 1 ms edges not met | `mock_only` | approval with the deviation sheet; a scope for pulse width and edges |
| 4.5 | `runs_after_approval`: `slow_supply_ramp` runs on the synthetic plant once the saved recipe is approved; the recipe declares its 1800 s (12 V) / 3400 s (24 V) bound | `mock_only`: planning refuses the test type on real hardware | owner approval of the recipe and its bound (simulation); for real hardware a real procedure and approval |
| 4.6.1.1 | `best_effort`: `momentary_drop` Usmin -> 4.5 V (12 V) / 9 V (24 V) held 1 s by the supply (B, default) or commanded 100 ms over LAN (A); drop level met, duration not met (B) or not measured (A), edges not met | `mock_only` | approval with the deviation sheet (plus `uvlo_approved` at 12 V); a scope for depth, time at level and edges |
| 4.6.1.2 | `best_effort`, partial: `micro_interruption` with output OFF 100 ms over LAN (not measured) and 1 s / 2 s by the supply Delayer (met); recoveries 100 ms, 1 s, 5 s, 10 s; below 100 ms not offered; the open is output OFF (approximated), the switch reaction not met | `mock_only` | approval with the deviation sheet and `uvlo_approved`; a line switch for the sub-100 ms cases; Delayer bench check B5 |
| 4.6.2 | `runs_after_approval`: `reset_staircase` runs on the synthetic plant once the saved recipe is approved (295 s of declared holds fit the envelope) | `mock_only`: planning refuses the test type on real hardware | owner approval of the recipe (simulation); a real procedure and approval for real hardware |
| 4.9.1 | `best_effort`, partial: `line_interruption` method 1 on the positive line as output OFF 10 s (met), open approximated, transition not measured; method 2 and the return line not offered | `mock_only` | approval with the deviation sheet and `uvlo_approved`; a series switch for the return line and method 2 |
| 4.9.2 | `best_effort`: `line_interruption` as 4.9.1 (a two-wire input has only the positive line) | `mock_only` | approval with the deviation sheet and `uvlo_approved` |
| 4.4, 4.6.3, 4.8 | `needs_instrument` (no honest substitute: AC superposition, the cranking dip structure, a floating offset source; owner decisions 2 and 7) | same | AC superposition, pulses, floating source |
| 4.6.4, 4.7, 4.10.x | `excluded_by_policy` | same | out of scope for this release (brief §2, §7.5) |
| 4.11, 4.12 | `not_on_this_bench` | same | hipot / insulation tester and a climatic chamber |
