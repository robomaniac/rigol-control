# Best-effort ISO 16750-2 runs on the existing bench: a proposal for review

Proposal, 2026-09-30, documents only: no code was changed, no instrument was
connected, nothing was rendered. It answers the owner's brief: ISO 16750-2 is
a reference an OEM follows, tightens or loosens; where a clause needs an edge
or an interruption this bench cannot produce, run the closest thing the Rigol
DP821A can do, record what the clause asks against what the bench did, and
leave the clauses that cannot be approximated at all greyed out.

Everything below is built on four project documents and the numbers they
verified: [iso16750-2.md](iso16750-2.md) (clause parameters and current
verdicts), [instrument-sequencing-dp800.md](instrument-sequencing-dp800.md)
(DP821A speed, Timer, Delayer, Monitor), [load-programs-dl3000.md](load-programs-dl3000.md)
(DL3031A readback limits, analog monitor outputs) and
[../m2-freshness-and-readback-evidence.md](../m2-freshness-and-readback-evidence.md)
(LAN round trips and poll cadence). Clause parameters are cited by clause
number only; the standard's text is not reproduced (brief §16). Nothing here
is a capability the documents do not state; where a behaviour is not
documented it is marked unverified and listed as a bench check.

**Basis tags** used on every number in this page:

| Tag | Meaning |
| --- | --- |
| `ISO` | parameter of ISO 16750-2:2023 as recorded in [iso16750-2.md](iso16750-2.md), cited by clause; `ISO-fig` marks a figure value to confirm on the printed copy |
| `DS5` | DP800 datasheet p. 5 via [instrument-sequencing-dp800.md](instrument-sequencing-dp800.md): DP821A CH1 "voltage programming control speed (1 % within the total variation range)" rise < 110 ms loaded / < 30 ms unloaded, fall < 110 ms loaded / < 800 ms unloaded; command processing time < 118 ms (Note 2, p. 6); OVP/OCP accuracy 0.5 % + 0.5 V / 0.5 % + 0.5 A; programming accuracy 0.1 % + 25 mV |
| `PG` | DP800 programming guide via the same note: Timer and Delayer group times are whole seconds, 1 s to 99999 s (sub-second acceptance unverified, bench check B1); Timer and Delayer cannot be enabled together; the Delayer has a V/I/P stop condition; whether a later Delayer ON group re-energises after a trip is unverified (bench check B5) |
| `LAN` | measured round trips of the project's own queries: 4.1 ms min, 5.4 ms median, 36 ms p95, 55 ms max (M2 evidence Table A4); poll period median 1.135-1.153 s (Table A1) |
| `DRV` | structure of `Software/src/benchctl/drivers/rigol_dp800.py`: every state change is one write, at least one `:SYST:ERR?` query and one readback query, so one `output_off` or `output_on` costs at least three round trips and `set_voltage_live` at least five (two pre-checks, write, drain, readback); `set_voltage_live` requires output ON and a caller-bounded step; `set_voltage` requires output OFF |
| `RB` | readback: DP821A and DL3031A values refresh about once per second; the DL3031A integrates over 200 ms (`:MEAS:TIME?` 10 PLC) (load-programs note §1.6; M2 evidence §A, §E) |
| `SEED` | seeded real bench profile replica in `tests/test_standards.py`: source 35.8 V / 1 A / 35.8 W; protective policy `supervised-24V-450mA-500mA-720s-v1`: source current limit 1.0 A, DUT input overvoltage guard 26 V, DUT output overvoltage 13.2 V, output overcurrent 2.55 A |
| `DUT` | `profiles/dut/12t12-4a.yaml`: 9-36 V input, 12 V / 4 A / 48 W, user-supplied ratings; isolation unknown; a failed direct 12 V cold start is recorded |
| `ENV` | real-path envelope ([../configured-runs.md](../configured-runs.md)): 540 s planning estimate, 660 s software deadline, 720 s one-shot source timer per input-voltage phase; polling 1-2 s |
| `MOCK` | synthetic plant parameters in `src/dcdc_bench/adapters.py`, labelled synthetic (not DUT characteristics): UVLO off below 8.6 V at the DUT input, hysteresis 0.5 V, standby 4 mA, cold-start delay 1 s, soft-start time constant 0.3 s, collapse hiccup period 0.37 s, load step 10 ms |
| `derived` | arithmetic on tagged numbers, shown inline |
| `UNV` | not stated in any document read; needs a bench check before it may be relied on |

## 1. Philosophy

- **The standard is a reference, not a gate.** The bench never issues a
  pass/fail against a clause and never assigns an ISO 16750-1 functional
  status class. It records what it commanded, what it can bound, what it
  observed at its polling cadence, and places that next to the clause's
  parameters. The engineer, who knows which OEM variant applies, judges.
- **What the bench did, against what the clause asks.** Every ISO 16750-2
  recipe, best-effort or not, carries a deviation sheet (section 2.2): one
  row per parameter the clause specifies, with the clause value, the bench
  value and its basis, the mechanism, whether the bench measured it, and a
  classification.
- **The brief's honesty rules still apply.** A stimulus the bench
  approximates is reported as approximated. A quantity the bench cannot
  measure stays "not measured"; it is never estimated into a number. So the
  owner's example "the ISO asks for 10 ms, this setup achieved 50 ms" is not a
  sentence this bench can write today: nothing on it measures an edge. What it
  can write is "the clause asks for edges of at most 10 ms; this bench's edge
  is the supply's own slew, datasheet-bounded below 110 ms loaded and 800 ms
  falling unloaded (`DS5`), not measured on this unit". The word "achieved" is
  reserved for values a scope or DAQ measured (section 5).
- **Ordinary polling stays ordinary polling** (brief §2): a 1 s readback
  cannot see a 100 ms event; the observed-state column of a best-effort run
  says what the polls saw and states that anything shorter than the poll
  interval is invisible to them (`RB`).
- **Nothing is relabelled.** A best-effort recipe that has lost the content
  of a clause (section 3: 4.3.2, 4.6.3) is not offered under that clause
  number.
- **Fail-closed first.** Best-effort recipes are opt-in, approval-gated like
  the UVLO ramp (brief §7.5), and run inside the same protective order as
  every real procedure (section 4).

## 2. The status model

### 2.1 A new verdict: `best_effort`

Proposed addition to `FeasibilityStatus` in `standards.py` and to the verdict
list in [README.md](README.md), between `runs_here` / `runs_after_approval`
and `needs_instrument`:

- `best_effort` — "runs here as an approximation; deviations recorded". The
  bench can hold every level of the clause within the DUT rating and the
  bench envelope and can command every timing, but at least one specified
  parameter (edge time, interruption or pulse duration, open-circuit
  impedance) is realised by a mechanism whose achievable value is outside
  the clause's tolerance or cannot be measured by this bench. The verdict
  carries the clause's deviation sheet. Badge "best effort (deviations
  recorded)", amber, tickable but never pre-ticked, exactly like
  `runs_after_approval`; it plans as `approval_blocked` until the saved recipe
  is approved (section 4.4). On a real profile it reads `mock_only` until a
  real procedure exists, as 4.5 and 4.6.2 do today; the "proposed verdict"
  column of section 3 is the verdict once the procedure exists on both
  benches.

How `feasibility()` would decide (today's order is applicability, policy
exclusion, missing facility, missing instrument, DUT rating, envelope,
conditions):

1. Policy exclusions, facility tokens and `not_applicable` are unchanged and
   come first. `excluded_by_policy` is never softened into best effort.
2. When instrument tokens are missing, the clause record is consulted for a
   declared approximation: a new per-clause field
   `best_effort: dict[token, mechanism]` naming, for each missing token, the
   mechanism this bench substitutes (`edge_10ms` -> "supply slew, DS5
   bounds"; `pulse_ms` -> "LAN-commanded step, host-timestamped";
   `line_switch_10Mohm` -> "source output OFF/ON"). Tokens with no honest
   substitute are never declared: `ac_superposition`, `pulse_us`,
   `negative_voltage`, `low_source_impedance_pulse`,
   `floating_offset_source`, `short_circuit_fixture`. If any missing token
   lacks a declared substitute the verdict stays `needs_instrument`. The
   declaration is per clause on purpose: 4.4 and 4.6.3 stay grey even though
   their tokens overlap with clauses that get a best-effort path.
3. The DUT-rating, source-envelope and approved-guard checks run as for a
   runnable clause (so 4.3.2 at 24 V still ends as `outside_dut_rating`, and a
   26 V level still carries the guard condition).
4. The deviation sheet is built from `recipe_parameters()` and the tagged
   bounds (section 2.2). If every row is `met` or `approximated` the verdict is
   `runs_here` / `runs_after_approval` (this is how an instrument-timed 4.5 or
   4.6.2 comes out); otherwise `best_effort`. `needs_approval` follows the
   existing rule (any level below the DUT minimum, including 0 V during an
   interruption).
5. `Feasibility` gains `deviations: list[Deviation]`; `missing` keeps the
   tokens the bench lacks so the page can still say which instrument would
   convert the rows into measured values.

### 2.2 The deviation sheet

One `Deviation` record per parameter the clause specifies: level, hold time,
edge time, repetition, rest or recovery time, interruption time, impedance,
operating mode, temperature.

| Field | Content |
| --- | --- |
| `parameter` | the clause's parameter name as recorded in `standards.py` (`drop_level_V`, `edge_max_s`, ...) |
| `clause_value`, `clause_tolerance` | the recorded value and the tolerance that applies: clause-specific (60 +/- 6 s) or the clause 4.1 general tolerances (time +/- 5 %, voltage +/- 0.2 V) (`ISO`) |
| `bench_value`, `bench_basis` | the value this bench commands or is bounded to, with its tag: a datasheet bound (`DS5`), the instrument clock (`PG`), measured LAN jitter (`LAN`), the driver's round-trip count (`DRV`), or "none" |
| `mechanism` | `lan_output_off_on`, `lan_voltage_step`, `timer_group`, `delayer_group`, `steady_level` |
| `measured_by_bench` | `false` for every terminal-side timing and level transition (the supply readback refreshes about once per second, `RB`); `true` only when a scope or DAQ channel is bound in the bench profile (section 5). Host-side write timestamps are recorded in a separate `host_interval_s` field and never make a terminal-side quantity "measured" |
| `classification` | one of four words, decided by the mechanical rule below |

Classification rule (the only place a judgement is encoded):

- `met` — a measurement, or a bound (datasheet, instrument clock) that lies
  entirely inside the clause tolerance. Example: a 60 +/- 6 s hold commanded
  over LAN; worst case 60 s + 55 ms jitter + 118 ms processing (`LAN`, `DS5`)
  is inside +/- 6 s.
- `approximated` — the clause's quantity is produced by a different kind of
  mechanism, the mechanism's relevant figure is recorded, and the figure that
  can be compared is inside tolerance. Examples: a 1 V/s ramp realised as 1 V
  steps of 1 s (average rate exact to the instrument clock, `PG`); an open
  circuit realised as source output OFF (OFF-state impedance `UNV`, and the
  sheet says so).
- `not_met_but_documented` — the bound or the measurement lies entirely
  outside the tolerance. Example: an edge of at most 10 ms against a supply
  whose best datasheet case is < 30 ms (unloaded rise, `DS5`).
- `unknown_until_measured` — no bound exists, or the bound straddles the
  tolerance. Example: a 100 ms interruption commanded as two LAN writes; each
  may take 0-118 ms to act (`DS5`) and 4-55 ms to arrive (`LAN`), so the
  terminal-side interval lies anywhere from near 0 to about 270 ms
  (`derived`), which straddles 100 +/- 5 ms. The report says "commanded, not
  measured".

A `met` row always names the bound or the measurement that justifies it.

### 2.3 Exactly how the sheet appears in the report

Following the default document structure (brief §12.3):

1. **Results, under the test's own subsection** (one subsection per performed
   test): after the conditions and before the figure, a table titled
   "Deviation sheet, ISO 16750-2 clause N" with the columns Parameter, Clause
   asks, Bench did (basis), Mechanism, Measured here, Classification. Below it
   one fixed line: "Observed output states come from about 1 s polling;
   states shorter than the poll interval are not visible to this bench." The
   observed-state table that follows is the existing level/point table of
   `supply_profiles.py` (output on / off / indeterminate per level, with the
   expected-off scoping shown).
2. **First-page summary**, one deterministic sentence per ISO 16750-2 test,
   built from the sheet by a template with no free text:
   "ISO 16750-2 clause {n} asks for {clause summary from the recorded
   parameters}; this bench produced {commanded stimulus} ({k} parameters met,
   {m} approximated, {p} not met, {q} not measured; see the deviation
   sheet)." For 4.6.1.1 variant A of section 3: "ISO 16750-2 clause 4.6.1.1
   asks for a drop from Usmin to 4.5 V for 100 ms with edges of at most 10 ms;
   this bench produced a voltage step to 4.5 V commanded for 100 ms over LAN
   (achieved depth and interval not measured; supply fall time
   datasheet-bounded < 110 ms loaded / < 800 ms unloaded; 0 parameters met, 0
   approximated, 2 not met, 2 not measured; see the deviation sheet)."
3. **Appendix: qualification and provenance**: every `not_met_but_documented`
   and `unknown_until_measured` row is appended to the run's
   `metrology_limitations`, which the renderer already prints as the appendix
   bullet list (`analysis.py` collects `run["metrology_limitations"]` into
   `model["limitations"]`).
4. **Data exports**: `run.json["method"]["best_effort"]["deviations"]` holds
   the sheet verbatim next to the command list or instrument program and the
   host-side timestamps of every write; the CSV/JSON bundle includes it.
5. **Never**: a functional status class, a pass/fail word, or the verb
   "achieved" in a row with `measured_by_bench: false`.

## 3. Clause-by-clause compromise table

"Current" is the seeded real profile's verdict from [iso16750-2.md](iso16750-2.md).
"Proposed" is the verdict once the procedures of section 6 exist and the
owner's policy answers of section 7 are in; where an answer changes the
verdict both outcomes are shown. "Grey" means not tickable: `needs_instrument`,
`excluded_by_policy`, `outside_dut_rating`, `not_on_this_bench`,
`not_applicable`. Where this proposal disagrees with the expected shape given
in the brief, the row says so and the note below argues it.

| Clause | Current (real) | Proposed | Deviation sheet summary | Mechanism |
| --- | --- | --- | --- | --- |
| 4.2 DC supply voltage | `runs_here` (24 V: 28 V and 32 V above the 26 V guard) | `runs_here` | levels met (programming 0.1 % + 25 mV, `DS5`, inside +/- 0.2 V); t1 30 s / t2 60 s met once the hold profile is realised (today each level is a separate cold-started point, recorded as a deviation); 1 V/s rise and fall approximated as 1 V steps of 1 s (LAN +/- 55 ms jitter, `LAN`, or Timer groups exact, `PG`); modes 3.3/3.4 at Tmin/Tmax not met (no chamber; bounded load, `SEED`), documented | LAN steps today; Timer program per the DP800 note |
| 4.3.1.1 long-term overvoltage, 12 V | `needs_split` | `runs_here` with an approved longer instrument-timed bound (Timer group 18 V x 3600 s, `PG`); fallback `best_effort` by splitting into eight 450 s holds (a 600 s hold would exceed the 540 s planning estimate, `ENV`) | level 18 V met (below the 26 V guard, `SEED`); hold 3600 s +/- 180 s met by the Timer, exceeds the 720 s bound (`ENV`) until the owner approves about 3700 s; split variant: cumulative 3600 s in eight segments (8 x 450 s, `derived`) with output OFF and a cold start between them, approximated, gap durations recorded, thermal continuity not evaluated; (Tmax - 20) K conditioning not met, documented; mode 3.4 bounded | Timer; or LAN holds per phase |
| 4.3.1.1, 24 V | `outside_dut_rating` | grey, unchanged | 36 V equals the DUT ceiling (`DUT`); endpoint method not approved | none |
| 4.3.1.2 jump start, 12 V | `needs_instrument` (edge) | `best_effort` (disagrees with the DP800 note's "not recommended"; argued below) | 26 V met (programmed; equals the 26 V guard, `SEED`, so a reviewed policy with a raised guard is needed first); 60 +/- 6 s met (LAN worst case +173 ms, `derived` from `LAN` + `DS5`; Timer exact); edges <= 10 ms not met (rise and fall loaded < 110 ms, `DS5`); rest 120 s met; Tmin not met (no chamber), documented; mode 2.2/2.3 approximated as converter enabled with the load input OFF or a light load | LAN `set_voltage_live` 10.8 -> 26 -> 10.8 V, or a 3-group Timer program |
| 4.3.1.2, 24 V | `not_applicable` | grey, unchanged | 12 V systems only (`ISO`) | none |
| 4.3.2 transient overvoltage, 12 V | `needs_instrument` (pulse_ms) | grey, `needs_instrument` (disagrees with "best_effort or grey": grey, argued below); opt-in only under a different title | level 18 V met; 400 +/- 20 ms unknown (LAN interval 400 ms +/- 173 ms worst, `derived`, straddles; a Timer group cannot be shorter than 1 s, `PG`); edges 1 ms not met (< 110 ms loaded, `DS5`); 1 s +/- 50 ms rest unknown over LAN; 5 pulses met; mode 3.4 bounded | LAN voltage steps only |
| 4.3.2, 24 V | `needs_instrument` | grey, `outside_dut_rating` | 36 V equals the DUT ceiling (`DUT`) | none |
| 4.4 superimposed AC | `needs_instrument` | grey, unchanged | 10 Hz-200 kHz (`ISO`) against >= 1 s per Timer point or per LAN step (`PG`, `LAN`): about five orders of magnitude (`derived`); no honest substitute | none |
| 4.5 slow decrease and increase | `mock_only` (1680 s / 3360 s per direction > 660 s) | `runs_after_approval` with an approved longer bound, LAN or Timer (disagrees with "best_effort via LAN": every parameter is met, the blocker is the duration policy) | rate 0.5 +/- 0.1 V/min met: 20 mV / 2.4 s with 55 ms jitter is 2.3 % (`derived` from `LAN`) or 25 mV / 3 s Timer exact (`PG`); step <= 25 mV met; floor 0 V and all levels below 9 V need the UVLO-style approval; mode 3.2 approximated (bounded load grid); 1680 s / 3360 s per direction (`ENV`) needs the longer bound or `needs_split` | LAN live steps (mock today) or Timer staircase |
| 4.6.1.1 momentary drop | `needs_instrument` (pulse_ms, edge) | `best_effort`, two variants in one recipe | **A, clause-timed**: 4.5 V (`ISO-fig`) commanded for 100 ms (`ISO-fig`): depth unknown (fall unloaded < 800 ms, `DS5`, may not reach 4.5 V before the restore command), interval unknown (straddles), edges <= 10 ms not met, mode 3.4 bounded. **B, supply-timed** (recommended default): 4.5 V held 1 s: depth met as a bound (settled within 1 % after <= 800 ms, so at the level for at least about 0.2 s and at most 1 s, `derived` from `DS5`), duration 1 s vs 100 +/- 5 ms not met, edges not met, mode bounded. 24 V: Usmin 10 V -> 9 V (`ISO-fig`), same sheet; 9 V equals the DUT minimum so no UVLO approval by today's rule | A: LAN `set_voltage_live` down and up; B: LAN or a 3-group Timer program |
| 4.6.1.2 micro interruption | `needs_instrument` (partial >= 1 s) | `best_effort`, coverage partial | interruptions 1 s and 2 s and recoveries 1 s and 10 s met by the Delayer (whole seconds exact, `PG`; needs B5); the same over LAN is unknown (1 s +/- 173 ms straddles +/- 50 ms); 100 ms interruption and 100 ms recovery commanded over LAN: unknown (host OFF-to-ON spacing floor about 10 ms median / 110 ms worst, `derived` from `DRV` + `LAN`; terminal side +/- 118 ms, `DS5`); 10 ms and below: not offered, grey (two writes cannot be spaced 10 ms apart reliably at a 36 ms p95 round trip, `LAN`); recovery >= 5 s met; open >= 10 MOhm approximated by output OFF (OFF-state impedance `UNV`); switch <= 10 us not met; mode 3.4 bounded | Delayer ON/OFF groups; LAN `output_off` / `output_on` for 100 ms |
| 4.6.2 reset behaviour | `mock_only` | `runs_after_approval` once a real procedure exists (not best effort) | 5 % steps of Usmin met; holds >= 5 s / >= 10 s met; the clause records no edge; levels below 9 V need the UVLO-style approval; the 295 s of declared holds fit the envelope (`ENV`); mode 3.4 bounded | LAN steps (mock today) or Timer program |
| 4.6.3 starting profile | `needs_instrument` (pulse_ms) | grey, unchanged (argued below) | tfall 5 ms, t1 15 ms, t2 50 ms, trise 40-100 ms, 2 Hz component (`ISO`) cannot be expressed in >= 1 s segments; a 1 s-segment version loses the clause's content | none |
| 4.6.4 load dump | `excluded_by_policy` | grey, unchanged | fault injection (brief §2, §7.5); also 79-101 V (`ISO`) against a 36 V DUT and a 60 V source | none |
| 4.7 reversed voltage | `excluded_by_policy` | grey, unchanged | reverse power (brief §7.5); single-quadrant supply | none |
| 4.8 ground and supply offset | `needs_instrument` | grey unless the owner approves CH2 in series (owner question 2); applicability itself unknown | US 13 V / 26 V (`ISO`; 26 V equals the guard, `SEED`); +/- 1.0 +/- 0.1 V offsets would need CH2 in series: a combined-source configuration excluded by brief §3.2, CH1/CH2 isolation not stated (`UNV`), negative offset needs reversed wiring; whether the DUT has two or more supply or ground paths is unknown (`DUT` isolation unknown) | none today |
| 4.9.1 single line interruption | `needs_instrument` | `best_effort`, method 1 on the positive line only; method 2 grey | 10 +/- 1 s met (LAN worst case +173 ms, `derived`; Delayer exact); open >= 10 MOhm approximated by output OFF (meaning below); transition <= 10 ms unknown (command acts within < 118 ms, `DS5`; fall shape after OFF `UNV`); 100 us bursts not offered; the return line cannot be opened (no series switch); outputs active / inactive as load ON / OFF variants; mode 3.4 bounded | LAN `output_off` 10 s `output_on`, or Delayer |
| 4.9.2 multiple line interruption | `needs_instrument` | `best_effort` | same as 4.9.1 method 1; for a two-wire input it is the same stimulus; mode 2.1 approximated as converter enabled with the load input OFF, mode 3.4 bounded | same |
| 4.10.2 / 4.10.3 short circuit, overload | `excluded_by_policy` | grey, unchanged | brief §2, §7.5; the 1 A source limit is reached before any output limit (load-programs note §3) | none |
| 4.11 / 4.12 | `not_on_this_bench` | grey, unchanged | hipot / insulation tester and a climatic chamber | none |
| 4.1 / 4.3 / 4.3.1 / 4.6 / 4.6.1 / 4.9 / 4.10 / 4.13 | `not_applicable` | unchanged | headings and informative clauses | none |

Net change: four clauses move from grey to `best_effort` (4.3.1.2 at 12 V,
4.6.1.1, 4.6.1.2, 4.9.1 method 1, 4.9.2), two stay grey although the brief
expected a possible best-effort path (4.3.2, 4.6.3), two long-duration
clauses (4.3.1.1 at 12 V, 4.5) become fully compliant runs if a longer
instrument-timed bound is approved, and 4.8 becomes an owner question.

### Notes on the rows where judgement was needed

**4.3.1.2 jump start, why best effort is worth offering.** The hold answers
the question the clause exists for: does the converter operate at 26 V for
60 s and return to normal at 10.8 V. What is lost is the edge stress:
15.2 V in <= 10 ms is at least 1.5 V/ms (`derived` from `ISO`); the supply's
loaded bound of < 110 ms (`DS5`) gives at least 0.14 V/ms, so the stress is
at least eleven times lower (`derived`). The sheet says exactly that, and an
OEM variant that cares about the edge will read it as not covered. The level
needs a protective policy with a guard above 26 V (section 4), and 26 V is
inside the 36 V rating (`DUT`).

**4.3.2 transient overvoltage, why grey.** For a 9-36 V converter, 16 -> 18 V
with >= 110 ms edges is an in-range level change indistinguishable from a 4.2
step; the clause's content is the 1 ms edge and the 400 ms pulse shape, and
both are lost (one not met, one unknown). The 400 ms pulse also lies below the
poll period, so the observed-state column would be blind. Offering it as
4.3.2 would relabel a repeated 2 V step (brief §2). If the owner wants that
exercise it should be a generic "repeated input step" recipe under category 1,
not an ISO clause.

**4.6.1.1 momentary drop, why two variants.** Variant A is the owner's
framing (100 ms commanded). Its honest sheet is almost entirely "not
measured": the DUT drops out below 9 V (`DUT`) and draws only standby current,
so the fall approaches the unloaded case (< 800 ms, `DS5`) and 4.5 V may never
be reached before the restore command arrives. Variant B holds the drop long
enough (1 s) that the datasheet bound guarantees the level was reached, so the
report can state a bounded time at level; it trades the clause's 100 ms for a
documented 1 s. Both variants in one recipe let the engineer see both. The
figure values 4.5 V and 100 ms are to be confirmed on the printed copy
(`ISO-fig`).

**4.6.1.2, where the honest floor is.** Not "about 50 ms achieved": the
smallest interruption this bench should command is the clause's own 100 ms
decade step, classified `unknown_until_measured`, because the two LAN writes
each carry 4-55 ms of transport (`LAN`) and up to 118 ms of processing
(`DS5`) and nothing measures the result. Anything shorter is not offered.
Conversely the >= 1 s subset is `met` only when the Delayer times it (whole
seconds exact, `PG`); over LAN a 1 s interruption straddles the +/- 5 %
tolerance and is `unknown`. That is the practical reason to build the Delayer
path for this clause (after bench check B5, because its later ON groups
re-energise the DUT).

**4.6.3 starting profile, why grey.** A version with 1 s minimum segments
would be 12 V -> US1 (1 s) -> US (t3) -> 12 V with the 15 ms and 50 ms
segments, the 5 ms fall and the 2 Hz component removed. For the 12T12-4A
every 12 V US1 level (8 / 4.5 / 3 / 6 V) is below the 9 V minimum and three of
the four US levels (6.5 / 5 / 6.5 V) are too (`ISO`, `DUT`); only level I's
9.5 V is above it. The 1 s version therefore asks "does the converter stop at
3-8 V and restart at 9.5 V or 12 V", which the 4.6.2 staircase and the UVLO
ramp already answer at the same 1 s granularity. The cranking content (the
2 Hz current pulses and the dip structure) is gone, so nothing may carry the
4.6.3 number. The 24 V levels (US1 10 / 8 / 6 V, US 20 / 15 / 10 V) lead to
the same conclusion.

**4.9, what output OFF does and does not mean.** Output OFF stops the supply
from sourcing; it is not a demonstrated >= 10 MOhm open. Whether the DP821A
opens a relay, disables its output stage or actively discharges it, and what
impedance the OFF output presents, is not stated in the documents read
(`UNV`); the `DS5` speed figures bound setpoint changes, not an OFF command.
The DUT's input capacitance therefore discharges into the converter's own
draw and into whatever the OFF output presents. On reconnection the DUT sees
the supply's rise (unloaded < 30 ms, then loaded < 110 ms, `DS5`) instead of a
switch closing onto an already-regulated source, so the reconnection inrush
is lower than with a real line switch. Two one-time checks make the sheet
better: a DMM across CH1 with everything OFF (impedance), and a scope on the
OFF transition (bench check B6 extended). With a two-wire input only the
positive line can be interrupted, which is 4.9.2's stimulus; the return-line
case of 4.9.1 needs a series switch and stays uncovered.

## 4. Safety and protective settings per best-effort clause

The order of brief §7 and of `extended.py` is unchanged: identity checks,
outputs verified OFF, protections programmed and read back before anything is
energised, unloaded startup proven before the load is enabled, absolute limits
at every poll, independent shutdown attempts per instrument, output state
recorded as `UNKNOWN` when a verification fails. The DL3031A keeps its
`VLIM` 13.2 V and `ILIM` 2.55 A (`SEED`) as the output-side protection; the
source OVP is never treated as protection of the converter output (brief §7.4).

### 4.1 Levels and guards

The OVP must sit above the top level of the recipe by more than its accuracy
band (0.5 % + 0.5 V, `DS5`) so it cannot trip on the intended level, and below
the DUT's 36 V (`DUT`) by the project's endpoint margin: the OVP value is never
above 35.8 V, and no recipe level ever reaches 36 V. The policy's
`dut_input_overvoltage_V` guard must be at or above the OVP band's upper edge
for the recipe to plan without the guard condition.

| Clause | Top level at the DUT input | Lowest level | OVP proposal (`derived` from `DS5`) | Source current limit / OCP | Load limits (`SEED`) |
| --- | --- | --- | --- | --- | --- |
| 4.3.1.2 | 26 V (`ISO`) | 10.8 V | 28 V, acts between 27.36 V and 28.64 V; needs a reviewed policy with a guard >= 29 V (the seeded 26 V guard equals the level) | 1.0 A / 1.05 A as the existing procedures program | 13.2 V / 2.55 A; light load or input OFF for mode 2.x |
| 4.6.1.1 | Usmin 9 V (12 V) or 10 V (24 V) | 4.5 V / 9 V (`ISO-fig`) | 14 V, acts between 13.43 V and 14.57 V, inside the 26 V guard | 1.0 A / 1.05 A | 13.2 V / 2.55 A; bounded grid |
| 4.6.1.2 | UB 12 V / 24 V | 0 V (output OFF) | 14 V (12 V base) or 26 V (24 V base; acts between 25.37 V and 26.63 V) | 1.0 A / 1.05 A | 13.2 V / 2.55 A |
| 4.9.1 / 4.9.2 | UB 12 V / 24 V | 0 V (output OFF) | as 4.6.1.2 | 1.0 A / 1.05 A | 13.2 V / 2.55 A; load OFF variant for "outputs inactive" and mode 2.1 |
| 4.3.1.1 split fallback | 18 V | 18 V | 20 V, acts between 19.4 V and 20.6 V, inside the 26 V guard | 1.0 A / 1.05 A | 13.2 V / 2.55 A |

Levels below 9 V (4.6.1.1 at 12 V; every interruption, since output OFF is
0 V) need `authorization.uvlo_approved` under the existing rule.

### 4.2 Expected-off scoping (brief §7.5)

The `SupplyProfilePolicy` pattern is reused: output-off is an expected,
recorded state only where the recipe declares it; everywhere else the
minimum-output rule stops the run; absolute limits are never scoped.

- 4.6.1.1: the drop level is below `expected_off_below_V`, so output-off
  during the drop is recorded, not faulted; after the restore the minimum
  output rule applies once the declared startup interval has elapsed.
- 4.6.1.2 and 4.9: output-off is expected during the interruption and for a
  declared `recovery_window_s` after output ON (bounded by the clause's
  recovery time); an output still off after the window stops the run with the
  observation recorded ("did not recover within N s"), which is a result, not
  a bench fault.
- 4.3.1.2: no expected-off phase; the minimum-output rule applies throughout
  (with the load input OFF the rule is the enabled-no-load observation). A
  converter that shuts down at 26 V stops the run and the report records it.

### 4.3 What the Pi polls and what stops the run

Each cycle at the usual ~1 s: `:MEAS:ALL? CH1` (or the existing V and I
queries), the load's V and I, `:OUTP? CH1`, `:OUTP:OVP:QUES? CH1`,
`:OUTP:OCP:QUES? CH1`, and `:DELAY?` while a Delayer program runs. Stops:

- any absolute limit (input current, voltages, output current) at any poll;
- an output OFF the Pi did not command and that the Delayer schedule does
  not predict for that instant (+/- 1 s + 118 ms tolerance, `PG`, `DS5`);
- an output not back ON within 1 s + 118 ms after a Delayer ON group or a LAN
  `output_on` whose readback did not verify;
- a latched OVP/OCP flag; the DL3031A questionable-status fault mask;
- the output-not-recovered rule of section 4.2;
- the 660 s software deadline (`ENV`). For LAN-timed recipes the 720 s
  one-shot Delayer cutoff stays armed as today. For Delayer-timed recipes the
  Delayer is the sequencer and cannot also be the cutoff (`PG`), so the
  independent bound is the program itself: finite cycles, end state OFF,
  total duration below the policy bound, exactly as the DP800 note's safety
  design states; a program with later ON groups is allowed only after bench
  check B5. The Monitor (`>V` between the top level and the OVP, `>C` at the
  limit; `<V` unusable because interruptions visit 0 V) is an optional
  instrument-side cutoff after bench checks R2 and B4, with its unspecified
  reaction time stated in the run record.

### 4.4 What an approval must record

In the saved recipe (`<workspace>/profiles/recipe/<recipe_id>.json`), the
UVLO pattern extended:

- `authorization.best_effort_approved: true` and
  `authorization.protective_policy_id` naming a bench policy whose
  `source_current_limit_A`, `dut_input_overvoltage_V`,
  `dut_output_overvoltage_V` and `output_overcurrent_A` are declared and whose
  guard covers the recipe's OVP band (section 4.1);
- `authorization.accepted_deviations`: the list of sheet rows classified
  `not_met_but_documented` or `unknown_until_measured`, with a hash of the
  sheet; a change to the clause parameters or the bounds invalidates the
  approval, as a changed plan hash does today;
- `authorization.uvlo_approved: true` where any level is below the DUT
  minimum (section 4.1);
- for Delayer- or Timer-timed recipes the bench profile's declared sequencer
  and `max_program_s` (DP800 note), and the recorded results of bench checks
  B1-B5 that the recipe depends on.

The bench page shows the recipe unticked with the catalog's sentence saying
where approval happens, as `runs_after_approval` does today
(`standards.APPROVAL_HOW` gains a best-effort variant).

## 5. What "measured" would require

One instrument converts most `unknown_until_measured` rows into measured
values: a two- to four-channel oscilloscope or a DAQ with single-shot capture.
Requirements derived from the clauses, not from any product:

- Sample rate: a 10 ms edge judged to +/- 5 % needs about 0.5 ms resolution,
  so >= 10 kS/s (`derived` from `ISO`); the 100 us cases of 4.6.1.2 and 4.9.1
  method 2 would need >= 1 MS/s, and they stay grey for other reasons (no
  switch), so 10-100 kS/s is enough for every best-effort clause.
- Record length: a 100 ms event with its 5 s recovery context at 10 kS/s is
  about 50 k samples per channel (`derived`).
- Channels: (A) DUT input voltage at the DUT terminals, which also moves the
  measurement boundary closer to the module than the source terminals (brief
  §3.3); (B) DUT output voltage, directly or from the DL3031A's rear analog
  "Voltage Monitoring Output" (load-programs note §1.6; scaling `UNV`);
  (C) load current from the DL3031A's analog "Current Monitoring Output"
  (scaling `UNV`); (D) optionally source current through a shunt, which the
  bench does not have.
- Trigger: the scope's own edge trigger on channel A; or the DP821A digital
  I/O trigger output configured on OUTOFF or a `<V` threshold (DP800 note;
  presence of the terminal is bench check R2); or a Pi GPIO toggled at the
  write.
- Grounding: whether the DL3031A monitor outputs and the DP821A output are
  isolated from earth and from each other is not stated (`UNV`, raised in
  both instrument notes); a wiring review precedes any connection.

What it captures per clause: 4.6.1.1 depth, time at level, fall and rise
times (all four unknown or bounded rows become measured); 4.6.1.2 the
terminal-side OFF-to-ON interval, the fall shape after OFF, whether the
converter output rode through or dropped and for how long; 4.3.1.2 both edges
and the 26 V level at the DUT pins; 4.9 the transition after OFF, the
reconnection edge and the output behaviour; 4.3.2, if it were ever opted in,
the pulse width and edges. 4.5 and 4.6.2 need nothing new; they are DC.

Bench check B6 of the DP800 note (10 V steps up and down, loaded and unloaded,
on a scope) would additionally turn the `DS5` bounds into values measured on
this unit on a stated date. That is a characterisation, not a per-run
measurement: the sheet's `measured_by_bench` stays false unless a capture
channel is bound in the run's bench profile (a new acquisition role,
`transient_capture`, as the load-programs note proposed), and the capture file
is stored under `raw/` with its own timebase statement and the scope's
datasheet accuracy.

Honest note: until such a channel is bound, every terminal-side timing row of
every best-effort run reads "commanded, not measured", the summary sentence
counts it as not measured, and the report never uses "achieved".

## 6. Mock-first plan

### 6.1 What the synthetic plant has and what it needs

Has (`MOCK`): a latching UVLO comparator at the DUT input (off below 8.6 V,
on again 0.5 V higher), cold-start delay 1 s and soft start with a 0.3 s time
constant, a constant-power collapse into the current-limited source shaped on
run e0fab9, a readback model with per-channel hold and quantisation, a
sanctioned live input step (`UvloMockBench.set_live_voltage`), and a 10 ms
load step. All labelled synthetic.

Needs adding, each labelled synthetic in the run record:

1. **Live output OFF/ON** on `UvloMockBench` (`set_output(enabled, now)`): OFF
   takes the plant's source voltage to 0 V, ON restores the setpoint; every
   change recorded like `live_changes`.
2. **A source slew model**: setpoint changes and ON transitions follow a
   first-order path with loaded and unloaded time constants parameterised
   from the `DS5` 1 % settle bounds (rise 110 / 30 ms, fall 110 / 800 ms); the
   fall after OFF uses a separate parameter marked unverified. The UVLO
   comparator must then be evaluated along the path (at step times and at the
   analytically solved crossing time), not only at query time, or a 100 ms
   drop between two polls would never reach the plant's latch.
3. **A command-latency model**: each command's effective time is its issue
   time plus a seeded draw from the measured round-trip distribution
   (4-55 ms, `LAN`) plus a seeded draw from 0-118 ms processing (`DS5`),
   deterministic under the virtual clock and the run seed.
4. **An input hold-up** on the synthetic converter: a ride-through time
   constant so that a 100 ms interruption may be ridden through and a 1 s one
   is not; this exercises the expected-off scoping and the "invisible to
   polling" statement. It is a simulation parameter, not a DUT property.
5. **Host-side timestamps** on every command in the mock context so the
   sheet's `host_interval_s` is filled the same way as on the real path.
6. **Delayer and Timer emulation** in the mock (ON/OFF or V/I/t groups
   executed by the virtual clock, end state OFF, exclusivity enforced) if the
   instrument-timed variants are pursued; the DP800 note's
   `source.sequencer.kind` declaration gates the token.

### 6.2 Procedures (synthetic plant only; the real path keeps refusing them)

- One new test type `supply_discontinuity` with a declared block
  (`kind: drop | interruption`, `base_V`, `level_V` for a drop or `output: off`
  for an interruption, `duration_s`, `recovery_s`, `repeat`,
  `timing: lan | delayer | timer`) reusing `SupplyProfilePolicy` for the
  expected-off scoping and the UVLO ramp's guard. 4.6.1.1 variants A and B,
  the 4.6.1.2 subsets and 4.9.1/4.9.2 are all instances of it.
- One new test type `overvoltage_hold` (base, level, hold, rest, repeat,
  timing) for 4.3.1.2, shared with the 4.3.1.1 long-hold and split variants
  (`standards.py` already has the `overvoltage_hold` recipe kind).
- Both build their deviation sheet at planning time from `standards.py` and
  write it into the plan; the procedure copies it into `run.json["method"]`
  and fills `host_interval_s` as it runs.

### 6.3 Tests

- `tests/test_standards.py`: the verdict table gains `best_effort` for
  4.3.1.2 at 12 V, 4.6.1.1, 4.6.1.2, 4.9.1 and 4.9.2 on the mock profile and
  `mock_only` on the seeded real profile until a real procedure exists;
  4.3.2, 4.4, 4.6.3 and 4.8 stay `needs_instrument`; every best-effort entry
  has one sheet row per recorded parameter; the classification rule is pinned
  with synthetic bounds (inside -> `met`, outside -> `not_met_but_documented`,
  straddling or absent -> `unknown_until_measured`, different kind ->
  `approximated`); no `met` row without a basis; `measured_by_bench` is false
  everywhere until a capture role is declared; the summary sentence equals the
  template (golden strings for 4.6.1.1 A and B); the existing documentation
  test (cites every clause, reproduces no text) covers this page.
- `tests/test_supply_discontinuity.py` (new, modelled on the supply-profile
  tests): refuses real profiles; refuses without `best_effort_approved` and a
  matching sheet hash; refuses levels below 9 V without `uvlo_approved`;
  output-off during the interruption and the recovery window is recorded, not
  faulted; output-off after the window stops the run with the observation;
  an uncommanded output OFF stops the run; `host_interval_s` is recorded; the
  plant's ride-through makes a 100 ms interruption invisible to polling and
  the method block says so; variant B's time-at-level bound appears, computed
  from the plant's slew parameters and labelled synthetic.
- `tests/test_reporting.py` and `tests/test_documents.py`: the deviation table
  appears under the test's results subsection, the summary sentence and the
  appendix bullets are present and identical between HTML and PDF, and the
  word "achieved" never appears when every row has `measured_by_bench: false`.
- `tests/test_ui.py`: badge label, never pre-ticked, approval sentence, card
  count ("N runnable now, M after approval, K best effort").

### 6.4 Effort and order

One engineer with the existing harness, mock only: contracts, `feasibility()`,
sheet and tests 1.5 days; plant additions (OFF/ON, slew, latency, hold-up,
sub-poll evaluation) 2 days; `supply_discontinuity` on the mock (4.6.1.1 A/B,
4.6.1.2 >= 100 ms, 4.9) 2 days; `overvoltage_hold` on the mock (4.3.1.2,
4.3.1.1 variants) 1 day; report (table, sentence, limitations, exports)
1 day; UI 0.5 day; documentation and catalog tests 1 day: about 9 working
days before anything touches the real path. The real path afterwards:
LAN-timed procedures reusing today's envelope and Delayer cutoff 2-3 days
plus the owner's approvals; Delayer- or Timer-timed variants need the DP800
note's adapter (its estimate 6-7 days) and bench checks B1-B7. Scope or DAQ
integration is not estimated here.

Order: (1) 4.6.1.1 and 4.6.1.2, the clauses the owner named, which share one
procedure; (2) 4.3.1.2; (3) 4.9.2, then 4.9.1 method 1 on the positive line;
(4) the instrument-timed upgrades of 4.2, 4.5, 4.6.2 and 4.3.1.1 on the DP800
note's own track.

## 7. Questions for the owner

1. **Longer instrument-timed bound.** Approve a per-recipe program bound
   above 720 s for attended Timer runs: about 3700 s for the 4.3.1.1 hold and
   about 3400 s per direction for 4.5 (`derived` from `ISO` + margin)? Yes or
   no, and how long. Without it 4.3.1.1 falls back to the split best-effort
   variant and 4.5 stays `needs_split` on the real bench.
2. **CH2 in series for 4.8.** Lift the brief §3.2 exclusion of combined
   sources for that one recipe, after an isolation check of CH1/CH2 (`UNV`)
   and a wiring review? And first: does the 12T12-4A have two or more supply
   or ground paths at all (its isolation is unknown)? If not, 4.8 does not
   apply to it.
3. **Wording.** Accept "commanded, not measured" in the summary sentence and
   the deviation sheet as the way best-effort results are stated, and the
   rule that "achieved" is reserved for scope- or DAQ-measured values?
4. **Approval gate.** Should best-effort recipes use the same per-recipe
   approval as the UVLO ramp (`best_effort_approved`, the accepted deviations
   with their hash, a reviewed protective policy), with `uvlo_approved` added
   wherever the input reaches 0 V?
5. **Scope or DAQ.** Is a capture instrument of the class in section 5
   (>= 2 channels, >= 10 kS/s single-shot, external trigger) to be acquired?
   Until then every terminal-side timing stays "not measured". Related: is
   the DP821A's rear digital I/O terminal fitted (bench check R2)?
6. **26 V policy.** Approve a protective policy for 4.3.1.2 with the OVP at
   28 V and the guard at or above 29 V (section 4.1), given the 36 V rating?
7. **4.3.2 and 4.6.3.** Confirm they stay grey, or ask for the generic
   "repeated input step" recipe under category 1 that section 3 describes,
   knowing it does not carry the clause numbers.
8. **4.6.1.1 default.** Variant B (1 s drop, depth bounded) as the default
   best-effort recipe with variant A (100 ms commanded, depth unknown) next to
   it, or A alone? And confirm the figure values 4.5 V and 100 ms on the
   printed copy.

## 8. Owner decisions (2026-10-01)

Recorded from the owner's review of this proposal. They govern the
implementation that follows; where they change a verdict in section 3 the
new verdict is stated here.

| Question | Decision | Consequence |
| --- | --- | --- |
| 1. Longer instrument-timed bound | **Approved per recipe.** Each recipe that needs more than the 660 s / 720 s policy declares its own bound and the operator approves that recipe. | 4.3.1.1 (12 V and 24 V) and 4.5 become compliant runs, not approximations, when the recipe is approved. |
| 2. CH2 in series for 4.8 | **Dropped.** Series CH2 yields a positive offset only (owner measured 5 V + 1 V = 6 V), never the negative one, and the series wiring is not documented as safe at the converter's maximum. | 4.8 stays grey until a floating offset source exists. |
| 3. "Commanded, not measured" wording | **Accepted.** | Deviation sheets use `measured_by: host_clock` for intervals the Pi timestamps itself and `none` for anything at the converter terminals until a scope or DAQ exists. |
| 4. Approval gate | **Same as UVLO.** `best_effort_approved: true` plus the accepted deviation sheet's hash in the saved recipe; the real path refuses the recipe otherwise. | Implemented mock-first; the real procedures stay refused until bench checks. |
| 5. Scope or DAQ | **Not yet.** | Every terminal-side timing stays `unknown_until_measured`. |
| 6. Protective policy at the clause level | **Owner's call, per recipe.** The owner regards the 0.2 V margin between 35.8 V and the converter's user-supplied 36 V maximum as immaterial. | A recipe may declare `program_clause_level_exactly: true` (36.0 V, 18 V at 12 V, 26 V for jump start) with OVP set just above; the default remains the margin setting, and the deviation sheet records which was used. |
| 7. Clauses to keep grey | **4.3.2 moves to best effort** (the owner's reading: hold the level as fast as the supply allows, 400 ms or longer, five times; same shape as jump start). 4.6.3 and 4.8 stay grey pending the owner's answer below. | New recipe for 4.3.2 at 12 V with the clause's 400 ms and a longer-plateau variant. |
| 8. 4.6.1.1 default | **Variant B (supply-timed 1 s drop) is the default; 4.5 V / 100 ms confirmed for variant A.** | As proposed. |

### A switch box (owner's idea)

The owner proposes a relay (or MOSFET) switch between the supply and the
converter: a true open circuit for 4.9.1 / 4.9.2 instead of "output OFF";
interruptions of about 10 ms with a relay (shorter with a MOSFET) for 4.6.1.2;
and 4.6.1.1 by switching the converter input between CH1 at the system
voltage and CH2 preset to 4.5 V, so the edges are the switch's and not the
supply's slew. It does not help 4.3.1.2 or 4.3.2 (both levels exceed CH2's
8 V). A DPDT reversal for 4.7 is physically possible but is the fault
injection the brief excludes; it is designed only as a policy exception the
owner must approve explicitly, accepting converter damage. Design document:
[switch-box-design.md](switch-box-design.md) (pending). Open owner questions:
4.6.3 grey or a one-second-segment approximation; 4.7 in or out; drive from
the Pi's GPIO or from the supply's trigger lines (is the digital I/O terminal
fitted?).
