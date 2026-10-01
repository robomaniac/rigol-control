# The simulated bench: plant model `coupled-dc-2.0`

**Everything described here is SYNTHETIC.** The plant is a small set of equations in
`src/dcdc_bench/adapters.py` (with `mock_uvlo.py` and `mock_thermal.py`) that the mock
runner drives instead of the DP821A/DL3031A pair. Its parameters were fitted to behaviour
recorded on the physical 12T12-4A sample so that a rehearsal on the simulated bench
prepares an operator for what the real bench does; no value in it is a property of the
DUT, an instrument identity, a calibration or a measurement. Every run that uses it is
labelled synthetic at every layer (adapter identity, run `data_source`, metric
qualification, figure captions, HTML banner). This page records what the plant models,
how well it matches the record, how the simulated bench differs from the real one, and
what it deliberately does not pretend.

Written after the power-electronics review
(`docs/simulation-review/electrical-engineer.md`, B1, M1, M2, M4, M5, m3, m5, m8) and the
QA review (`docs/simulation-review/qa.md`, M2). Evidence referenced below: the 24 V and
35.8 V load sweeps `runs/real-voltage-sweep/…_real_eb3bcd`, the failed 12 V cold start
`…_real_e0fab9` (`docs/cold-start-hypothesis.md`), the pass-through cross-check
`…_real_bed075` and the cadence study `docs/m2-freshness-and-readback-evidence.md`.

## 1. Electrical model

Symbols: `Vs` source setpoint (the source terminal voltage in CV), `Iin` source current,
`Vd` DUT input voltage, `Vo`/`Io` output voltage and current at the load terminals,
`Vn` nominal output, `P` module loss.

| Element | Equation | Parameter |
| --- | --- | --- |
| Input lead | `Vd = Vs − R_in · Iin` | `R_in = 0.06 Ω` (pass-through run implied 50–90 mΩ) |
| Output at the load terminals (local sense) | `Vo = (1 + δ) · Vn · s(t) − R_out · Io` | `δ = +1 %` (12.137 V recorded at 12 V nominal), `R_out = 0.10 Ω` (≈ 96 mV/A recorded, output leads included) |
| Module loss | `P = 0.30 W + 0.020 W/V · Vs + 0.25 W/A² · Io² + 0.07 · Vo · Io` | the review's indicative refit |
| Power balance (solved exactly) | `Vs · Iin − R_in · Iin² = Vo · Io + P` | `Vs · Iin = Vo·Io + P + R_in·Iin²` holds in every CV state |
| Electronic load | CC setpoint reached in a 10 ms linear step; below its minimum voltage it sinks nothing | `load_step_time_s = 0.010` (DL3031A slowest slew ≈ 1 ms to 1 A) |
| Soft start `s(t)` | `1 − exp(−(t − t0) / τ_ss)` from the start instant `t0` | `τ_ss = 0.3 s` |

Values for a 12 V nominal converter (true plant values, no readback artefacts):

| Vs | Io | Vo | Iin | loss | η plant | η recorded (eb3bcd) | loss recorded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 V | 0.10 A | 12.110 V | 0.0866 A | 0.87 W | 58.3 % | 72.6 % | 0.45 W |
| 24 V | 0.50 A | 12.070 V | 0.3044 A | 1.27 W | 82.6 % | 84.2 % | 1.13 W |
| 24 V | 0.90 A | 12.030 V | 0.5243 A | 1.76 W | 86.0 % | 86.5 % | 1.69 W |
| 24 V | 1.00 A | 12.020 V | 0.5796 A | 1.89 W | 86.4 % | — | — |
| 24 V | 1.725 A | 11.948 V | 0.9848 A | 3.03 W | 87.2 % | 87.1 % | 3.05 W |
| 35.8 V | 0.10 A | 12.110 V | 0.0647 A | 1.10 W | 52.3 % | 61.3 % | 0.76 W |
| 35.8 V | 1.00 A | 12.020 V | 0.3949 A | 2.12 W | 85.0 % | — | — |
| 35.8 V | 2.50 A | 11.870 V | 0.9605 A | 4.71 W | 86.3 % | 86.1 % | 4.81 W |
| 12 V | 0.50 A | 12.070 V | 0.5901 A | 1.05 W | 85.2 % | — | — |

The fit reproduces the recorded losses within about 5 % from 0.9 A upward and the
≈ 0.2–0.3 W extra loss at 36 V. It **overestimates light-load loss** (0.87 W against 0.45 W
at 24 V / 0.1 A): the review's fixed terms (0.30 W + 0.020 W/V) are larger than the
recorded light-load loss. This is a known limitation of the indicative model, kept as
specified; a refit with a smaller fixed term and a larger proportional term (for example
0.15 W + 0.012 W/V + 0.25 W/A² + 8.5 %) would land within 3 points at every recorded
load and is the obvious next refinement.

What the report shows differs slightly from the table because the load's current
readback carries the recorded +11 mA offset (section 4): 84.7 % at 24 V / 0.5 A, 87.5 %
at 24 V / 1.0 A and 86.1 % at 35.8 V / 1.0 A. Those readback values sit on the recorded
ones, which were taken with the same instrument.

At 12 V the plant meets the 1 A source between 0.85 and 0.9 A output (the recorded class:
≈ 0.85 A; the previous plant: ≈ 0.95 A). The planning budget (80 % / 90 %) still keeps
every planned 12 V point at or below 0.72 A, so the natural limit is reached only by a
recipe that raises the budget or by the injected `setup-limited` scenario.

## 2. Startup, UVLO and the source current-limit collapse

The converter has memory: a UVLO latch, a start state and a collapse state. Every
transition is recorded in `run.json` (`synthetic_transitions`).

**UVLO latch** (`synthetic-uvlo-1.0`, unchanged): off when `Vd < 8.6 V`, on again when
the DUT input with the converter off (`Vs − 4 mA · R_in`) reaches `9.1 V`; off it draws
`4 mA` and delivers nothing. Decided at the DUT input after the lead drop.

**Cold start** (`StartupModel`): when the source is enabled from OFF the converter waits
`cold_start_delay_s = 1.0 s`, then soft-starts if the DUT input is at or above the start
threshold. The threshold is the UVLO turn-on level unless the DUT profile records a
failed direct cold start (`known_behaviours.cold_start_failed_at_V`), in which case the
runner places it `0.5 V` above the highest recorded failed input: `12.5 V` for the
12T12-4A profile, which records the 12 V failure of run e0fab9. Between the turn-on level
and the start threshold the converter **stalls** at `0.665 · Vn` (7.98 V at 12 V nominal,
the recorded plateau) with standby input current; enabling the load at a stalled output
collapses the input into the source limit exactly as recorded. A restart after a UVLO trip
with the source still on re-arms at the turn-on level with the soft start and no delay,
so the same converter "starts at 15 V, runs down to 9.1 V and fails a direct 12 V start".
The true start threshold of the physical sample is unknown (cold-start-hypothesis §4); the
12.5 V figure only reproduces the record.

**Source current-limit collapse** (B1): when the demanded input current exceeds the
source setting (or the injected 20 mA of the `setup-limited` scenario) there is no
reduced operating point. The source enters CC at `I_lim + 0.5 mA`, the converter trips and
the source terminal falls to `Vs_cc = 2.66 Ω · Iin` — `2.661 V at 1.0005 A`, the recorded
event — with `Vo = 0`, the load flagged out of compliance and the module loss equal to the
power dissipated in the DUT's input network. The collapse persists while the operating
point still demands more than the limit; a periodic re-fire attempt (`0.37 s` period,
10 % duty) shows on `Vin` as a ramp toward the turn-on level and back. Lowering the load
or the input clears it and the converter restarts through the soft start.

## 3. What the mock runner does with it

`runner.run_mock` mirrors `real_backend.ConfiguredProcedure`:

- Every **input-voltage phase** cold-starts from both outputs OFF: configure, source ON,
  then a **five-cycle source-only startup gate** at 1 s intervals with the load input OFF.
  If the output is below `0.9 · Vn` after the fifth cycle the phase ends with the real
  wording, "Output below startup/operating threshold; load will not be enabled or
  increased": the active point is `inconclusive`, the remaining loads of that phase
  `not-run`. A passed gate is recorded on the phase's first point (`startup_gate`).
- The load input is enabled once per phase, followed by five loaded startup cycles; later
  loads of the same phase are live CC setpoint changes, as on the DL3031A. A `0 A` request
  is an enabled no-load observation with the load input OFF.
- **Boundary stop**: any cycle whose source is not in CV, or whose clean `Iin` reading is at
  or above `0.995 × I_lim`, makes the point `setup-limited` and ends the phase; the higher
  loads at that input are `not-run` with the real guard's sentence ("Source
  headroom/current boundary reached; nominal-input efficiency is unqualified"). One
  deviation from the real guard: because the plant's source readbacks are held for about
  1.1 s, the mock takes a single **confirming cycle 1.2 s after the first boundary
  reading** (phase `boundary`, kept as `boundary_observation`) so the retained event is a
  fresh conversion; the real bench's ≥ 1 s cadence gives it that for free.
- The report summary gains one deterministic sentence per current-limited phase ("The
  source entered current limiting at 24 V, 0.05 A requested (p0009); 5 higher loads at 24 V
  (…) were not attempted.") and each figure caption says where a series stops and why
  (flag `source-current-limited`).
- The planner warns, in both modes, when a requested input is at or below a recorded
  failed cold-start level (`planning.known_behaviour_warnings`).

## 4. Readbacks and timing

`ReadbackModel` shapes how the synthetic instruments report the plant:

| Aspect | Model | Recorded basis |
| --- | --- | --- |
| Quantisation | source 1 mV / 0.1 mA, load 0.1 mV / 0.1 mA; a bound channel's declared `resolution` overrides | displayed digits (R1/R4); m2 evidence Table A2 |
| Refresh | each channel holds its conversion: source 1.1 s, load 50 ms | source strings repeat across the ≈ 1.1 s poll; the load refreshed within 0.19 s |
| Offsets and noise | +3 mV / −0.8 mA / +1 mV / +0.1 mA; σ 0.4 mV / 30 µA / 0.3 mV / 20 µA | unchanged synthetic terms |
| Load current, loaded | **+11 mA** on top of the plant current | pass-through run bed075: +11.0 to +11.3 mA at every load |
| Load current, input OFF | alternates exactly `0 A` and ≈ `11 mA` between conversions | m2 evidence §B and §E |
| Round trip | `4 ms + Exp(4 ms)`, capped at 55 ms, drawn from the seeded stream | Table A4: 4–5 ms median, 13–36 ms p95, 55 ms worst |

Consequences a rehearsal now shows: repeated identical source readings at a 0.5 s poll,
light-load efficiency biased upward by `11 mA / Io` (22 % of a 0.05 A request), a no-load
`Iout` mean near 5 mA that the analysis keeps as a load-off offset, and interchannel skews
of tens of milliseconds. On a pass-through DUT (`construction.topology` starting with
"none") the +11 mA produces the >100 % "efficiency" the real cross-check produced; on the
converter it cannot exceed 100 % and only biases the light-load points.

The UVLO ramp and the ISO 16750-2 supply-profile procedures (`uvlo.py`,
`supply_profiles.py`) drive `UvloMockBench`, which keeps an **instantaneous start and
clean, unquantised readbacks**: those recipes declare their own bounded startup interval
(0.3 s in their tests) and apply the minimum-output rule at every settling cycle after a
live step, so the cold-start and readback models above belong to the steady-state sweep
runner. The UVLO latch and the collapse are shared by both plants.

## 5. Thermal model (`first-order-case-2.0`)

Case rise follows a first-order lag on the plant's module loss: `8 °C/W`, time constant
`τ = 600 s` (`8 °C/W × 75 J/°C`; a potted 48 W module has a case of the order of 50–100 g),
ambient 23 °C drifting 0.3 °C/h, noise 0.02 °C. The previous 40 s constant let the
slope-only settling criterion pass while the case was still far from equilibrium. A slope
criterion `s` on this plant is met while `s · τ` of rise remains: 0.5 °C/min leaves 5 °C of
a 10 °C rise, so the shipped mock thermal recipe now declares `0.05 °C/min` over a 300 s
window (≈ 0.5 °C, 5 %, reached near 1950 s of model time within a 2700 s timeout). The
virtual clock makes that free; on a real sensor the numbers need validation for the
actual module and attachment. Test fixtures that need a fast case pass an explicit
`thermal_parameters={"case_time_constant_s": 20}` and are honest for that constant.

## 6. Run budget (QA M2)

The mock worker fsyncs every JSONL record, so its wall time follows the record count and
host I/O. `planning.mock_run_estimate` counts the records a plan will write (executable
points × channels × polls to the settling timeout plus acquisition, thermal polls, five
gate cycles per phase and five loaded startup cycles per loaded phase) and derives:

- `typical_s = 15 s + 5 ms/record` (2–3 ms per record measured on the bench Pi 4 at idle,
  2026-09-30, rounded up),
- `deadline_s = 120 s + 100 ms/record`, the runner's own hung-owner deadline sized for a
  loaded SD card.

A plan is **refused** when `deadline_s` exceeds `MOCK_RUN_BUDGET_S = 2400 s` (the transient
unit's `RuntimeMaxSec=2700` minus a 300 s margin), i.e. above about 22 800 records: the
QA reproduction cases (an 840-point grid, a 3600 s dwell) are refused at planning time
(`prepare_mock_plan` errors, the plan warning, and `run_mock` before any directory is
created); every shipped recipe fits (the rated grid at about 21 200 records is the
largest). `run_mock` traps SIGTERM in both processes: the plant owner finalizes the run
as `interrupted` with outputs verified OFF and `integrity.json` written; the parent
records the request and waits for that finalization.

## 7. How the simulated bench differs from the real one

| | Simulated bench (`mock.yaml`, `mock-rigol-local-sense.yaml`) | Real bench (`rigol-dp821a-dl3031a.yaml`) |
| --- | --- | --- |
| Boundary | source-to-load-terminal path, local load sense, 0.06 Ω + 0.10 Ω of modelled wiring | same boundary; actual wiring, unquantified |
| Ranges | `mock.yaml`: none declared (planning never refuses on range); `mock-rigol-local-sense.yaml`: the real 60 V / 1 A / 150 V / 60 A ranges and displayed resolutions | declared ranges and resolutions |
| Readback budget | labelled `synthetic_example` terms so the ± wording renders | datasheet terms, `not_evaluated` while calibration is unknown |
| Guards | none required; the plant cannot be damaged | approved protective policy, OVP/OCP, hard guards |
| Clock | virtual (model time) | wall clock, 660 s software deadline, 720 s source timer |
| Boundary stop | first non-CV or near-limit reading + one confirming cycle 1.2 s later | first non-CV or near-limit reading |
| Startup | five source-only cycles, in band from cycle 5 | same |
| Failure scenarios | injected (`setup-limited`, `stale`, `timeout`, …) | real |

The remote-sense variant `mock-remote-sense.yaml` keeps the earlier DUT-output-sense
boundary for exercising that branch of planning and reporting; the owner-facing demo uses
the local-sense bench so no S+/S− leads are depicted that the real bench lacks.

## 8. What the plant deliberately does not model

- Ripple, switching noise, transients, load-step or line-step response, inrush; hold-up only
  through the single-capacitor model of section 10, which exists so the best-effort
  procedures have something to interrupt; the load steps in 10 ms and the converter in 0.3 s
  because the DC bench polls at ≥ 1 s.
- Any waveform-level or EMC behaviour, protection trips other than UVLO and the source
  current limit, temperature dependence of the losses, ageing.
- Thermal images, sensor placement, a real case: the thermal channels are a first-order
  lag with a chosen time constant, selectable only on a mock bench.
- Instrument identities, serials, firmware, calibration; a quantified uncertainty of a
  measurement (the readback specifications are labelled synthetic examples).
- The physical sample's true start threshold, UVLO thresholds and efficiency: the plant
  reproduces the recorded points and the recorded failure, not the device.
- That a successful simulated run says anything about the safety of the same recipe on
  the real bench.

## 10. Input hold-up, live output commands and instrument programs (best-effort procedures)

The best-effort ISO 16750-2 procedures (`best_effort_procedures.py`: transient hold, momentary
drop, micro and line interruption; `docs/standards/best-effort-proposal.md` §6) need the plant to
do three things the steady-state and ramp plants never did: lose its supply for a commanded
interval, take a command some milliseconds after it was issued, and run a Delayer or Timer
program on its own clock. All three are additive and **off by default**: a `MockBench` built
without a `HoldUpModel` behaves exactly as before, and nothing here is a DUT property.

**Hold-up (`HoldUpModel`, `HOLD_UP_MODEL_PARAMETERS`).** One capacitor `C` at the DUT input,
default `470 µF`. It is invisible while the supply holds the node. When the supply stops holding
it — live output OFF (an interruption) or a setpoint below the node (a drop: a lab supply cannot
sink) — the node decays through the converter's own draw:

| Phase | Law | Why |
| --- | --- | --- |
| Converter running | constant input power `P`, fixed at the operating point when the supply let go: `V(t)² = V0² − 2·P·t/C` | a regulating converter draws constant power; the hold-up time to the UVLO turn-off is `t = C·(V0² − Vuvlo²)/(2·P)` |
| After the UVLO trip | constant standby current `I`: `V(t) = Vtrip − I·t/C` | the converter is off and draws 4 mA |
| Node reaches the floor | the segment ends; the floor is the setpoint (output live) or 0 V (output off) | the supply holds the node again, or there is nothing left |

At 12 V and 0.1 A the plant draws about 1.84 W, so `470 µF` rides through about **9 ms** before
tripping at 8.6 V: a 100 ms interruption or a 100 ms drop to 4.5 V trips the converter, which
then restarts through the soft start (`StartupModel()`: 1 s cold-start delay only on the first
start, `τ = 0.3 s`) once the supply is back. A recipe's plant may declare a larger value
(`run_best_effort_mock(..., hold_up=HoldUpModel(input_capacitance_F=0.01))`): **10 mF rides
through about 190 ms**, so the same 100 ms interruption leaves the output in band and nothing on
the bench observes the event, which is exactly what the "invisible to polling" statement in the
run record describes. The UVLO comparator is evaluated **along the path**, not only at query
time: pending commands are replayed in order whenever the plant is evaluated, the decay segment is
evolved to each command's effective instant and to the query instant, and a trip is placed at the
analytically solved crossing time (`uvlo.transitions[].monotonic_s`), so an interruption between
two polls still reaches the latch.

What the synthetic instruments report while the supply is not holding the node: the source
channel shows `0 V / 0 A` with mode `OFF` when its output is off (the DP800 records a disabled
channel as 0; its OFF-state impedance is unverified), and the node voltage with `0 A` in `CV` when
it is live but back-driven; the load sees whatever the converter delivers (nothing after a trip,
so the sample is flagged `load-out-of-compliance`). The DUT-pin voltage in `PlantState` is the
true node value, which no instrument on the bench measures.

**Command latency.** `UvloMockBench.command_latency_s()` draws one LAN round trip from the
readback model's distribution (the recorded `4 ms + Exp(4 ms)`, capped at 55 ms, when the
procedure builds the plant with `ReadbackModel.clean(**ReadbackModel.recorded_round_trips())`);
`set_live_voltage(..., effective_at=)` and `set_output(enabled, now, effective_at=)` queue the
change for that instant. The procedure stamps `commanded_at` before the write and
`acknowledged_at` after the driver's error drain and readback (5 round trips for a live voltage
step, 3 for output OFF/ON), which is what the real path's host clock can know; the effective
instant is plant truth, kept under `synthetic_plant_truth` in the run record and labelled so.
The supply's command processing time (< 118 ms, DS5) is not modelled.

**Programs (`program_delayer`, `program_timer`, `INSTRUMENT_TIMING_PARAMETERS`).** ON/OFF groups
(Delayer) or voltage/current/time groups (Timer) in whole seconds, 1 s to 99999 s, 1-2048
groups, 1-99999 cycles, end state applied when the program ends, never both programs at once —
the programming guide's rules (`docs/standards/instrument-sequencing-dp800.md`). The plant
executes the schedule on its own clock: each boundary lands within `±0.5 ms` of its nominal
instant so two boundaries differ by at most 1 ms from the programmed seconds (the real figure is
unverified, bench check B1). `program_status(now)` is what `:TIMER?` / `:DELAY?` would report;
`cancel_program()` is `:TIMER OFF` / `:DELAY OFF`. The procedure predicts every boundary from its
own program-start instant and the programmed seconds with a `173 ms` tolerance (command
processing plus LAN transport) and treats a source OFF outside a predicted window as a fault.

## 9. Parameter record

Every run stores the parameters its plant used in `run.json` (`model.parameters`: the
electrical constants, `uvlo`, `startup`, `source_current_limit`, `readback`, the source
current limit and load minimum voltage in force) and the method it followed
(`method.startup_gate`, `method.phase_stop`, `method.run_budget`), so a report can be
traced to the exact synthetic model that produced it. `MODEL_VERSION = "coupled-dc-2.0"`
distinguishes these runs from the earlier `coupled-dc-1.0` examples (90 % current-limit
plateau, instantaneous start, clean readbacks, 0.2 Ω lead, three-times-too-optimistic
losses).
