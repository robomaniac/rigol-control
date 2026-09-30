# Simulation review: power-electronics test engineer

Reviewed at commit `b38df08` (head of `dcdc-bench-hardening`), 2026-09-30. Nothing was
executed: no pytest, no render, no demo, no instrument. All statements below come from
reading source, profiles, documents and the already-rendered evidence named in the next
section. Paths are relative to `dcdc-bench/` unless stated otherwise.

## 1. Perspective and method

I read this as the engineer who would have to sign off a report produced by this bench:
does the simulated plant behave like a 9–36 V in / 12 V out converter on a 1 A source,
are the numbers labelled for what they are, and does a rehearsal on the mock prepare
somebody for what the real DP821A/DL3031A pair will actually do.

Sources examined:

- Plant: `src/dcdc_bench/adapters.py`, `mock_thermal.py`, `mock_uvlo.py`, `runner.py`,
  `planning.py`, `analysis.py`, `uncertainty.py`, `standards.py`, `supply_profiles.py`,
  `real_backend.py` (guard and startup gate only, for comparison), `uvlo.py` (guard).
- Profiles: `profiles/bench/mock.yaml`, `mock-thermal.yaml`, `rigol-dp821a-dl3031a.yaml`;
  `profiles/dut/12t12-4a.yaml`; `profiles/recipes/12t12-4a-quick.yaml`,
  `12t12-4a-uvlo.example.yaml`, `12t12-4a-thermal-mock.yaml`.
- Documents: `docs/implementation-brief.md` §2, §3, §9; `docs/instrument-specifications.md`;
  `docs/uncertainty-budget.md`; `docs/m2-freshness-and-readback-evidence.md`;
  `docs/engineering-figure-labels.md`; `docs/configured-runs.md`; `docs/standards/README.md`
  and `iso16750-2.md`; `docs/cold-start-hypothesis.md`.
- Rendered simulated evidence (read-only, main checkout): the fresh quick-recipe report
  `workspace/jobs/20260930T145556Z_3451819c/runs/20260930T145558.274647Z_183ecf39/reports/r0001/`
  (`report_model.json`, `exports/points.csv`, `report.html` as text) and the shipped
  source-limit example `examples/generated/setup-limited/20260929T161342.896178Z_30bef975/`.
- Real comparison (read-only): `runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/analysis/a-e2e7cc8e0d01/points.csv`
  (24 V and 35.8 V load sweeps of the physical 12T12-4A), plus the pass-through and
  cold-start evidence summarised in the two documents above.

Where I compare with ISO 16750-2 I rely on my own knowledge of the standard's structure
and headline levels; I do not quote its text and I mark where my recollection may be
out of date.

## 2. Findings

Ranking: **Blocker** = the owner will be misled about the one thing this bench is defined
by; **Major** = a reader who trusts the mock will carry a wrong expectation to the real
bench, or a "can/cannot" statement is not true; **Minor** = wording, consistency or
realism that should be fixed but does not mislead on its own.

### Blocker

**B1. The simulated source current-limit event is physically wrong, the sweep continues
past it, and the report summary does not mention it.**

- Physics. In CC the plant pins the source terminal at 90 % of the setpoint and solves a
  reduced output from the remaining power (`adapters.py:132-142`,
  `current_limit_voltage_fraction: 0.9` at `:20`). In the shipped example the limited
  point reads Vin 10.80 V, Iin 19.2 mA, Vout 1.73 V, Iout 30.5 mA with the converter
  "running" (`examples/generated/setup-limited/.../raw/samples.jsonl`, point p0002). A
  constant-power converter fed from a current-limited supply has no stable reduced
  operating point: its negative input impedance drives the input down until UVLO,
  then it restarts and hiccups. The only recorded real event did exactly that: source
  terminal 2.661 V at 1.0005 A against a 1.000 A setting
  (`docs/cold-start-hypothesis.md:23-27`). The mock teaches a benign signature
  (Vin ≈ 90 %, output partly alive) that the bench will never show.
- Procedure. `runner.py:409-410` ends settling on the first CC reading and marks the
  point `setup-limited` (`:483-485`), then the loop moves on to the next, higher load at
  the same input (`:506-507` breaks only on abort). The example shows p0002 limited and
  p0003–p0005 (higher loads) qualified `valid`. The real workers stop the phase on any
  non-CV reading or on Iin ≥ 0.995·limit (`real_backend.py:251`,
  "Increasing load stops for that input condition near the source-current boundary"
  in `analysis.py:880-881`). A rehearsal on the mock therefore teaches "the run
  continues after a limit event"; the real bench does the opposite.
- Narration. The setup-limited report's summary reads "18 of 21 requested operating
  points produced qualified synthetic DC results" and lists efficiency, spans and the
  acceptance sentence; the current-limit event appears only as `setup-limited: 1` in the
  coverage table. Brief §9.3 explicitly names "points unavailable because the source
  budget was exceeded" as summary prose. The point's own reason is good
  ("source entered current limiting; requested input condition not achieved") but a
  reader of the summary never sees it.
- Fix (three parts, all in the mock and analysis, no hardware):
  1. Replace the 90 % rule with a collapse: when `needed_current > limit`, set
     Iin = limit + a few hundred µA (the real readback sat at 1.0005 A), let the DUT
     input fall until the synthetic UVLO opens (`mock_uvlo.py` already has the latch),
     output 0 V, then re-arm and hiccup at a fixed period. `UvloMockBench` should be the
     default plant for every mock run so this coupling exists everywhere, not only in
     the UVLO/supply-profile procedures.
  2. In `runner.py`, on `limiting` stop the input-voltage phase (skip remaining loads at
     that Vin with reason "source boundary reached at a lower load") exactly as
     `real_backend.guard()` does; keep the point-level `setup-limited` qualification.
  3. In `build_report_model`, add a summary sentence per `setup-limited` point ("The
     source entered current limiting at 12 V, 0.05 A requested; higher loads at 12 V
     were not attempted") and carry the `source-current-limited` flag into the figure
     caption the way implausible-ratio points already are (`analysis.py:1290`).

### Major

**M1. The loss model is about three times too optimistic for this DUT class and the
input-voltage dependence is too weak.**

- Mock: `Pmodule = 0.09 + 0.006·Vin + 0.03·Iout² + 0.025·Pout`, input lead 0.2 Ω
  (`adapters.py:12-18, 44-46`). Fresh report: 95.24 % at 24 V / 1 A (loss 0.60 W),
  94.25 % at 12 V / 0.5 A, 78.3 % at 12 V / 0.05 A. Extrapolated to 4 A the module
  part is 1.8 W, i.e. ≈ 96 % at rated load.
- Real 12T12-4A (eb3bcd, local sense, wiring inside the boundary): 86.5 % at 24 V /
  0.9 A (loss 1.69 W), 84.2 % at 0.5 A (1.13 W), 87.1 % at 1.725 A (3.05 W); 61.3 % at
  35.8 V / 0.1 A versus 72.6 % at 24 V / 0.1 A; 86.1 % at 35.8 V / 2.5 A (4.81 W). The
  real device is flat at 86–87 % from 0.9 A upward and loses ≈ 0.3 W more at 36 V than at
  24 V; the mock gains 0.6 point per 12 V and keeps rising toward 96 %.
- Consequence: the load at which the 1 A source bites moves. At 12 V the mock reaches
  Iin = 1 A near 0.95 A output; a device of the recorded class reaches it near 0.85 A.
  The planning budget (80 % / 90 %, `planning.py:194-198`) is conservative enough that
  no planned point ever hits CC on the mock, so the natural limit path is never
  exercised without the injected 20 mA fault (`runner.py:364-366`, `adapters.py:132`).
- The 0.2 Ω input lead is also 2–4× the ≈ 50–90 mΩ the pass-through run implied
  (`docs/m2-freshness-and-readback-evidence.md:194`).
- Fix: re-fit `MODEL_PARAMETERS` to eb3bcd, keeping the same form and keeping the
  docstring's "not a DUT claim". Indicative values that reproduce the recorded losses
  within ≈ 10 %: base 0.30 W, 0.020 W/V, 0.25 W/A², 7 % of Pout, input lead 0.06 Ω
  (checks: 24 V / 1.725 A → 2.97 W vs 3.05 W measured; 36 V / 2.5 A → 4.66 W vs 4.81 W;
  24 V / 0.5 A → 1.26 W vs 1.13 W). Bump `MODEL_VERSION` so old synthetic examples are
  distinguishable. Remove the claim that the mock is "power-conserving" only if the
  new fit is; the current one is, and that property should stay.

**M2. No startup model and no startup gate in the mock; the 12 V cold-start history is
invisible to planning and to the simulated report.**

- `runner.py:368-373` cold-starts every point: source ON, load ON in the same instant,
  output at 12 V from the first read (`adapters.py:125` has no time dependence). The
  real workers run five source-only cycles and refuse to enable the load unless Vout ≥
  0.9·nominal (`real_backend.py:260-272`, `configured-runs.md:65-67`). The mock never
  rehearses that gate, the "load will not be enabled" stop, or the recorded failure
  signature (output plateau near 8 V at 12 V input, collapse after load enable;
  `docs/cold-start-hypothesis.md:28-36`). The same converter started at 15, 24 and
  35.8 V, so the plausible underlying condition is a start threshold above the 8.6 /
  9.1 V run threshold the mock uses (`mock_uvlo.py:17-18`).
- The DUT profile has no field for known behaviour, so a 12 V request plans as
  `executable` on the mock and `approval_blocked` (for approvals only) on the real
  bench; nothing warns that this input has a failure history.
- Fix: (a) give the plant a startup: soft-start over 2–4 s and a configurable
  `start_threshold_dut_input_V` distinct from the run threshold (default ≈ 12.5 V so
  a 12 V cold start stalls near 8 V as recorded, 15 V starts); (b) make `run_mock`
  perform the same source-only gate and load-enable step as `real_backend`, ideally by
  sharing one procedure object; (c) add `known_behaviours` to `DutProfile` (free text
  plus optional `cold_start_failed_at_V`) that `build_plan` surfaces as a warning at
  matching inputs in both modes.

**M3. The standards catalog says "runs here" for two ISO 16750-2 clauses that the
software refuses on the real bench, and ignores the run-duration envelope.**

- `standards.feasibility()` returns `runs_here` for 4.5 and 4.6.2 on any profile with a
  DC source (`standards.py:457-556`); the "synthetic plant only" condition is added only
  for `standard_id == BENCH_ID` (`:541-542`), never for ISO clauses whose
  `procedure_status` is `mock_only` (`:625-633`, `:657-666`). Yet `planning.py:132-133`
  marks these test types unsupported on a real bench ("not yet approved for real
  hardware") and `supply_profiles.py:94-95` raises. `docs/standards/iso16750-2.md:74,79`
  prints "runs here" for both; `:132-133` says "None of these recipes exists yet as an
  executable procedure", which contradicts `supply_profiles.py`, which does execute them
  on the mock. The UI recipe text does say "Synthetic plant only: not yet approved for
  real hardware" (`standard_recipes.py:246,266`), which mitigates but does not repair the
  verdict.
- Duration: the 4.5 ramp is 1680 s per direction (`iso16750-2.md:140`,
  `standards.py:389-404`), the 4.3.1.1 hold 3600 s. The real envelope is a 540 s
  planning estimate, 660 s software deadline and a 720 s one-shot source timer
  (`configured-runs.md:54-55`). 4.3.1.1 correctly gets a `procedure_gap` for this;
  4.5 gets `runs_here` with no such condition.
- "The mock and real profiles give the same verdicts" (`docs/standards/README.md:60`,
  `iso16750-2.md:61`) is only true when the real profile has no approved guard: the
  26 V condition on 4.2 (24 V) comes from `protective_controls.approved` (`standards.py:303-308`),
  which the mock profile lacks entirely (`profiles/bench/mock.yaml` has no block).
- Fix: add a `mock_only` feasibility status (or a mandatory condition) whenever
  `clause.procedure_status == "mock_only"` regardless of `standard_id`; compare the
  recipe's total duration with the bench's declared deadline and downgrade to
  `needs_procedure` when it does not fit; correct the two sentences in the docs.

**M4. The thermal mock's 40 s time constant flatters the thermal-settling criterion.**

- `mock_thermal.py:23-24`: 8 °C/W, τ = 40 s. A potted 48 W module (≈ 50–100 g of case)
  at 8 °C/W has τ of the order of 10 min, not 40 s. With the recipe's criterion
  (slope ≤ 0.5 °C/min over a 60 s window, `12t12-4a-thermal-mock.yaml:31-33`) the mock
  declares "met" at about 110 s, when the case is within 6 % of its final rise. A plant
  with τ = 600 s and a 16 °C final rise (2 W at 8 °C/W) satisfies the same slope test
  at ≈ 700 s while still ≈ 5 °C below equilibrium, i.e. the slope-only criterion passes
  prematurely on anything slow, and the mock is tuned so that this never shows.
- No real thermal claim is made anywhere (planning refuses thermal settling without
  bound channels, `planning.py:155-167`; the mock adapter cannot bind to a real
  profile, `mock_thermal.py:63-67`), so this is a rehearsal defect, not a report defect.
- Fix: τ configurable with a default in the 300–900 s range and a heat capacity
  parameter; then either lengthen `minimum_observation_s`/`timeout_s` in the thermal
  recipe or add a second criterion (predicted remaining rise from the fitted
  exponential below a threshold). Keep the "SYNTHETIC first-order case model" label.

**M5. Readbacks are unrealistically clean, so the real bench's dominant metrology
problems are never rehearsed.**

- Mock samples are 15-digit floats with Gaussian noise of 0.4 mV / 30 µA / 0.3 mV /
  20 µA and offsets of 3 mV / −0.8 mA / 1 mV / +0.1 mA (`adapters.py:22-25, 152-158`);
  every poll is a fresh conversion; interchannel skew is a fixed 8 ms (`runner.py:248`).
- The real bench returns quantised strings (1 mV / 0.1 mA on the source, ≈ 15 µV /
  8 µA effective steps on the load), repeats identical values on 76–92 % of consecutive
  source polls, has a bistable 0 / ≈ 11 mA load current readback with the input OFF,
  and a +11.0 to +11.3 mA load-vs-source current disagreement under load that produced
  112 % "efficiency" at 0.1 A in the pass-through run
  (`docs/m2-freshness-and-readback-evidence.md:31-38, 92-99, 184-193`).
- Consequently the `implausible_power_ratio` demotion (`analysis.py:260-262`), the
  readback cross-check and the freshness reasoning are exercised on the mock only by
  the artificial `stale`/`overrange` scenarios, never by the plant.
- Fix: quantise readbacks to the declared `resolution` and hold each channel's value
  for a configurable refresh period (≈ 1.1 s); add a `readback-offset` scenario that
  applies +11 mA to Iout under load and a 0 / 11 mA alternation with the load input
  OFF; make round trips 4–50 ms so the skew logic sees realistic numbers.

### Minor

**m1. The fresh demo report cannot show the uncertainty wording because the seeded
workspace bench profile has no readback specifications.** `workspace/profiles/bench/mock-dp821-envelope.json`
has `readback_specification: null` on all four channels, so the report says
"Uncertainty is unquantified" and the k = 2 / percentage-point labels are never rendered;
the repo profile `profiles/bench/mock.yaml:44-138` carries labelled `synthetic_example`
terms and the older setup-limited example shows the intended text
("95.24% ± 0.37 percentage points (k = 2, specification-bound only (synthetic example))";
I recomputed 0.37 pp from the four synthetic terms and it agrees). Fix: re-seed the
workspace profile from `mock.yaml` or state in the demo why the budget is withheld.

**m2. The demo report contradicts itself on label verification and its DUT carries real
approvals.** `workspace/profiles/dut/12t12-4a.json` has `verified_from_sample_label: true`,
`real_hardware_enabled: true`, `wiring_and_polarity_confirmed: true` and no
`label_photo_asset_id`; the repo profile has all three false (`profiles/dut/12t12-4a.yaml:15, 34-35`).
The report table prints "Sample-label verification: yes" while the hard-coded limitation
says "DUT ratings were supplied by the owner and are not verified against the sample
label" (`analysis.py:1709`). Fix: make the limitation conditional on the flag, require a
label photo asset before the flag can be true, and reset the demo DUT's approvals to false.

**m3. The mock's measurement boundary is not the real bench's.** `mock.yaml:87-92, 145`
declares remote sense at the DUT output and boundary "source-to-DUT-output path"; the
real profile is local sense at the load terminals, "input and output wiring included"
(`rigol-dp821a-dl3031a.yaml:176, 270`). The demo report therefore describes S+/S− leads
at the DUT output that the real report will not have. Fix: add a mock profile that
mirrors the real boundary (local sense, output lead resistance in the plant) and use it
for owner-facing demos; keep the remote-sense mock for exercising that branch.

**m4. Span metrics are headlined without an uncertainty statement.** "Largest line
regulation span: 0.003% of nominal" (`analysis.py:1683`) is a noise-floor number on the
mock (the plant has no Vin dependence at all, `adapters.py:125`) and would be below the
DL3031A's 30 mV full-scale term on the real bench. Brief §9.2 asks to avoid resolution
verdicts when the budget is not evaluated. Fix: append "(uncertainty unquantified)" as
the no-load sentence does (`:1677`), or suppress the headline when the span is below the
declared resolution.

**m5. Static output and load dynamics are too tidy.** Vout is exactly nominal at no load
with 25 mΩ output resistance (`adapters.py:125`); the real unit sits at +1.1 % (12.137 V)
and falls ≈ 96 mV/A including output leads. The electronic load's current follows a
0.55 s exponential (`adapters.py:19, 124`) whereas the DL3031A's slowest programmed slew
(`:SOUR:CURR:SLEW:BOTH MIN`, 0.001 A/µs) reaches 1 A in about 1 ms. Fix: add a setpoint
offset (+1 %) and 50–100 mΩ so `vout_error_pct` and any acceptance tolerance are exercised
with non-trivial numbers; make the load step in ≤ 10 ms and give the converter, not the
load, the slow dynamics.

**m6. The mock runner does not share the real guard.** `run_mock` has no hard limits and
no near-limit rule (Iin ≥ 0.995·limit stops the real phase, `real_backend.py:251`); a
mock point at 0.999 A in CV is `valid`. The UVLO/supply-profile procedures do share a
guard with absolute limits (`uvlo.py:155-186`). Fix: route `run_mock` through the same
`guard()` with the profile's `protective_controls`, and give `mock.yaml` a declared,
approved protective block so the demo exercises guard declaration as the real bench does.

**m7. Standards documentation accuracy.** `iso16750-2.md:104-106` says the 2023 edition
adds jump start (4.3.1.2) and transient overvoltage (4.3.2) as new; in my recollection
of the 2012 edition both already existed (jump start as the second test case of the
long-term overvoltage clause, transient overvoltage as its own clause), so only the
numbering is new. The 24 V reversed-voltage level at `:82` (−26 V) differs from my
recollection of −28 V for the earlier edition; confirm on the printed 2023 copy and mark
it the way figure values are marked. The verdicts themselves (excluded by policy) do not
depend on either point.

**m8. Timing realism of the mock cadence.** Two-millisecond queries and an 8 ms quartet
(`runner.py:248`, fresh report method "maximum cycle skew 8 ms") versus 4–55 ms real
round trips at a ≈ 1.1 s poll period (`m2-freshness…md:44-50`). Harmless for
qualification, but the recipe's `maximum_interchannel_skew_s` and the "draft, requires
driver timing validation" origin never get a realistic test on the mock.

## 3. Question-by-question evidence

**Q1. Physical plausibility and synthetic labelling.**
Power conservation holds (`adapters.py:126-131` solves the input quadratic exactly; the
CC branch conserves what is available). Efficiency rises monotonically with load and
falls mildly with input voltage: 78.3 / 72.4 / 69.8 % at 0.05 A and 94.2 / 94.0 / 93.6 %
at 0.5 A for 12 / 24 / 30 V. Direction right, magnitude too optimistic (M1). Load
regulation 25 mV/A and zero line dependence; the real unit also shows < 1 mV between 24
and 35.8 V at fixed load, so the zero line dependence is defensible, the offset and slope
are not (m5). No-load draw 12.7 / 9.0 / 8.2 mA (0.152 / 0.215 / 0.246 W) is plausible for
a small module; no real no-load reading of the converter exists yet to compare
(`m2-freshness…md:113-114`). Source limiting is the wrong shape (B1). Thermal 8 °C/W is
plausible, τ = 40 s is not (M4). UVLO 8.6 V off / 9.1 V on at the DUT input after lead
drop, 4 mA standby, is plausible and decided at the right node (`mock_uvlo.py:17-20,
53-57`). Labelling is thorough: `identify()` returns `data_source: simulated`
(`adapters.py:67-69`), every profile note says SYNTHETIC (`mock.yaml:31-33, 146-153`),
the run carries the model parameters (`runner.py:166`), metrics carry
`qualification: synthetic observation` (`analysis.py:60`), the evidence label cannot be
reclassified by a display change (`analysis.py:417-430`), every figure caption starts
with "SYNTHETIC." and the HTML banner says "Synthetic (simulated) — values come from a
software model, not from hardware" (`reporting/renderer.py:360`). I found no synthetic
number presented as a measurement. The one place where a reader could still be misled is
a synthetic model parameter (the 90 % collapse) shaping a result without being narrated
(B1).

**Q2. Metric definitions and wording.**
`dc_metrics` matches brief §9.1 exactly (`analysis.py:229-263`): Pin, Pout, loss,
efficiency, signed `vout_error_pct`; efficiency above 100 % or negative loss is preserved
and flagged, never clamped (`:260-262`), and the pass-through run proved it
(`m2-freshness…md:187-193`). No-load efficiency is "not applicable" and no-load Pout/loss
are withheld with reasons (`:248-256`); the report says so in three places. Regulation
span (`:266-268`) is separate from deviation, labelled "% of nominal", with covered range
in the conditions. Path wording is consistent: "Highest observed path efficiency",
"Power loss = Pin − Pout across the declared boundary, including its wiring losses"
(`:1399`), the plan warning about lead losses (`planning.py:309`), the limitation that
path loss "is not solely module heat" (`:1710`). Uncertainty: percentage points
(`uncertainty.py:50, 95-98`), systematic terms never divided by n (`:52-53`), k recorded
and explicitly "not validated 95 % confidence intervals" (`domain.py:268`,
`analysis.py:1177, 1191`, `renderer.py:830`), programming accuracy never read
(`uncertainty.py:106-129`), `synthetic_example` refused on a real bench or MEASURED
evidence (`:120-121`). Overclaims found: the label-verification contradiction (m2) and
the span headline without an uncertainty qualifier (m4). Nothing else in the fresh
report reads as more than it is.

**Q3. The "can and cannot" story.**
1 A vs 48 W: brief §3.2 arithmetic is reproduced by the planner; at 12 V the budget is
0.72 A (`planning.py:193-198`; fresh report p0006/p0007 `unsupported`), physical ceiling
`min(Vin·1 A, 60 W)` (`:187-189, 240-243`), and every report states the grid "does not by
itself qualify the claimed 48 W rating, ripple, transient or thermal behavior"
(`analysis.py:1715`). Input guard: planning refuses targets above the declared
`dut_input_overvoltage_V` and above the DUT rating without clipping (`:213-231`); the
catalog refuses a level equal to the DUT maximum (`standards.py:511-514`) and adds a
condition above the approved guard (`:531-533`). No ripple/transient/inrush claims: brief
§2 rule is repeated in the catalog docstring, `supply_profiles.py:27-32` and the report
("No waveform, thermal, calibration or uncertainty claim is inferred from ordinary DC
polling"). No thermal claims without sensors: `planning.py:155-167` and
`mock_thermal.py:63-67`; the fresh report says "Temperatures: not acquired". ISO 16750-2
spot-check against my knowledge of the standard's structure (levels only, not text):
4.1 tolerances, 4.2 code ranges and UA/t1/t2, 4.3.1.1 18 / 36 V for 60 min, 4.3.1.2 26 V
for 60 s (12 V only), 4.3.2 18 / 36 V pulses, 4.5 0.5 V/min to 0 V and back, 4.6.1.1
4.5 / 9 V drops (correctly marked as figure values), 4.6.2 5 % steps with 5 s / 10 s
holds, 4.6.3 cranking levels and times, 4.6.4 test A ranges, 4.7 case 1 −4 V, 4.11 /
4.12 500 V after humid heat — all consistent with what I know, and every verdict that
depends on a missing capability (pulse edges, AC superposition, negative voltage, line
switch, hipot, chamber) is correct in kind. The two verdict defects are M3 (mock-only
procedures shown as "runs here", duration envelope ignored); the two textual doubts are
m7.

**Q4. Safety stance of the simulation.**
The mock cannot reach hardware (`adapters.py:1`, `runner.py:126-127, 173`
`real_hardware_opened: False`), a real profile is `approval_blocked` until DUT approvals,
wiring confirmation and an approved protective policy exist (`planning.py:45-54, 266-270`),
and the UVLO and supply-profile paths refuse to run in either mode without the approval
block and declared absolute limits (`planning.py:57-76`, `uvlo.py:93-99`,
`supply_profiles.py:96-104`). Those gates are real. Where the mock can still create a
false belief: (i) a 12 V simulated run always succeeds and the sweep continues after a
limit event, while the physical record is a collapse at 12 V and a hard stop (B1, M2);
(ii) the demo DUT profile ships with real-hardware approvals and label verification set
without evidence (m2), which is exactly the checkbox the real gate relies on; (iii) the
generic mock sweep needs no protective controls at all (`mock.yaml`, m6), so a user can
rehearse a whole campaign without ever declaring the limits the real bench insists on.

**Q5. What to add, and what never to pretend.**
Add, in this order: the CC collapse/hiccup with Iin just above the limit and phase stop
(B1); a startup model with a start threshold above the run threshold and the shared
source-only gate (M2); quantised, held readbacks with the 11 mA load-offset scenario
(M5); a local-sense mock boundary with separate input and output lead resistances so
wiring drop is visible in Vin − Vout and in the cross-check (m3); a realistic thermal
time constant (M4); re-fitted losses, a +1 % setpoint offset and ≈ 0.1 Ω output path
(M1, m5); the shared guard including the near-limit rule (m6); a real-cadence option
(1.1 s polls, 4–50 ms round trips) for skew and freshness rehearsal (m8). The simulated
UVLO and supply profiles already exist and are gated correctly; the only change I would
make there is to make `UvloMockBench` the default plant. Never pretend: pulse edges,
ripple, interruptions shorter than the command cadence, inrush or load-step response
(single-quadrant supply polled at 1 s); temperatures without bound sensors; calibration
or a quantified uncertainty from synthetic terms on anything labelled MEASURED; that the
mock's efficiency, UVLO threshold or start behaviour are properties of the 12T12-4A;
instrument identities or serials; that a clause "runs here" when the executor refuses
it; and that a successful mock run says anything about the safety of the same recipe on
the bench.

## 4. What is sound

- A single power-conserving plant shared by source, converter and load, deterministic
  by seed, with every parameter recorded in `run.json` and in the report provenance.
- Consistent synthetic labelling at every layer: adapter identity, profile notes, run
  `data_source`, metric qualification, figure captions, HTML banner, limitations, and an
  evidence label that display code cannot change.
- Metric definitions and wording that follow brief §9.1 to the letter: path efficiency,
  wiring inside the boundary, no clamping, no-load not applicable, span separate from
  deviation, percentage points, k = 2 never called 95 %.
- The uncertainty evaluator: readback only, rectangular terms, resolution and
  temperature terms, repeatability recorded separately, unknown terms produce
  `not_evaluated` with reasons, synthetic terms refused for real or MEASURED evidence.
  The 0.37 pp example reproduces from the declared terms.
- Analysis re-validates every accepted cycle (four quantities, CV mode, load compliance,
  skew, phase) and raises rather than trusting the worker (`analysis.py:700-712`).
- Planning: every exclusion retained with its reason, nothing clipped, real execution
  blocked by saved approvals, supply profiles refused on real hardware, thermal settling
  refused without bound sensors, no-load draw declared unknown rather than zero.
- The UVLO latch decides at the DUT input after the modelled lead drop, with hysteresis
  larger than the lead drop so it cannot chatter; the ramp and staircase procedures
  apply absolute limits everywhere and scope the regulation rules to phases where the
  output is expected on.
- The datasheet transcription keeps programming and readback columns apart with page
  citations and records the calibration status as unknown, so the real budget stays
  `not_evaluated` honestly.
- The standards catalog's capability-token design correctly refuses everything that
  needs edges, pulses, ripple, negative voltage, switches or other laboratories, and the
  policy exclusions for fault-injection tests are stated with their citation.

## 5. Top 5 changes before the owner's review

1. **Make the source current-limit event real and stop the phase on it** (B1): collapse
   to UVLO/hiccup with Iin just above the limit instead of a 90 % plateau; phase stop as
   the real guard does; a summary sentence and caption flag for every `setup-limited`
   point. Regenerate `examples/generated/setup-limited`.
2. **Add startup to the plant and the source-only gate to the mock runner** (M2): a
   start threshold above the run threshold so a 12 V cold start stalls as recorded, the
   same five-cycle gate as `real_backend`, and a DUT-profile `known_behaviours` warning
   the planner shows at 12 V in both modes.
3. **Fix the catalog verdicts** (M3): a `mock_only` status or mandatory condition for
   every clause whose procedure exists only on the synthetic plant, a duration check
   against the bench deadline, and the two corrected sentences in
   `docs/standards/README.md:60` and `iso16750-2.md:61, 132-133`.
4. **Re-fit the plant to the recorded DUT class and the real boundary** (M1, m3, m5):
   losses of the order of 1.7 W at 24 V / 0.9 A, +1 % output offset, ≈ 0.1 Ω output
   path, ≈ 0.06 Ω input lead, a local-sense mock profile that mirrors
   `rigol-dp821a-dl3031a.yaml`, new `MODEL_VERSION`.
5. **Make the demo honest about itself** (m1, m2, m4): seed the workspace mock bench
   from `profiles/bench/mock.yaml` so the k = 2 / percentage-point wording renders, reset
   the demo DUT's approvals and label-verification flags (and tie the flag to a photo
   asset), and qualify the span headline with "(uncertainty unquantified)".
