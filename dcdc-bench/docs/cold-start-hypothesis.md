# 12 V cold-start hypothesis and supervised test plan

**Status: written hypothesis and test PROPOSAL. Nothing in this document
authorizes energizing the converter.** The plan in Section 5 requires the
owner's explicit approval, approved DUT/bench profiles and a fresh wiring
confirmation before any run. This document was prepared by an automated agent
role from the retained evidence only; no instrument was contacted and no code
or run folder was changed.

Prepared 2026-09-27 UTC against branch `dcdc-bench-hardening`. It answers item
2 of the "Next bounded task" in [implementation_status.md](implementation_status.md):
*write the 12 V cold-start hypothesis and test plan before another attempt.*

Path conventions: run folders are under `dcdc-bench/runs/`; `scpi.jsonl` line
numbers are 1-based; `c0000NN` is an `acquisition_cycle_id` in
`raw/samples.jsonl`; times after "enable" are measured from the
`source_enabled_with_deadline` event in `raw/events.jsonl` to the cycle's first
`query_start_utc`.

## 1. Summary

- The retained evidence contains **one** automated direct 12 V cold-start
  attempt: `runs/real-voltage-sweep/20260927T184902.863440Z_real_e0fab9`
  (below: **e0fab9**). It ended 6.9 s after the source was enabled with the
  source terminal voltage at **2.661 V** and source current at **1.0005 A**
  against a 1.000 A setting (`scpi.jsonl` lines 186–187; cycle `c000006`).
- Before that collapse the output had risen to **8.115 V** (`c000003`, +3.29 s)
  and then stayed at **7.986–7.982 V** (`c000004`–`c000005`, +4.45 s to
  +5.56 s) while the source current read **1.3–1.9 mA** in four of five cycles
  and **0.4809 A** in one (`c000004`).
- The electronic load was switched **ON** at +5.647 s (`scpi.jsonl` line 177,
  `:SOUR:INP:STAT ON`) while the output was at about 7.98 V, below the 10.8 V
  pre-load gate that [voltage-efficiency-test.md](voltage-efficiency-test.md)
  step 2 describes. The collapse reading is the **first** cycle after that
  enable. This ordering is the single most important fact in the evidence and
  is not mentioned in the existing narrative.
- The same converter cold-started at **15 V** (`runs/real-startup-descent/…_b44da1`),
  **24 V** (every 24 V run, including the pilot with a **0.15 A** source
  limit; source-only startup cycles are tabulated below for two of them) and
  **35.8 V**, with the load disabled during startup. At 15 V the output also
  passed through **7.12 V / 7.95 V** (+2.2 s / +3.5 s) before reaching
  **12.146 V** at +4.8 s. At 24 V it read 12.146 V by +2.1 s.
- Ranked hypotheses (Section 4): the load enable at a non-regulating ~8 V
  output is the best-supported *proximate trigger*; an incomplete or slow
  startup at 12 V (hard threshold, Vin-dependent delay, or behaviour near
  Vin ≈ Vout — indistinguishable with these instruments) is the best-supported
  *underlying condition*; the source current limit is the *mechanism* of the
  final collapse but is contradicted as its initiating cause; lead drop cannot
  be assessed; a hard UVLO start threshold above 12 V is consistent but weakly
  contradicted by the output reaching 8 V at all.
- The top discriminating test is a repeat 12 V cold start with the load
  **disabled for the whole bounded startup window**, preceded by 15/14/13.5/
  13/12.5 V cold starts from OFF (Section 5).

## 2. The "failed twice" statement

[implementation_status.md](implementation_status.md) and the
[README](../README.md) state that the converter "has failed direct 12 V
cold-start twice". A search of every `run.json`/`plan.json` under
`dcdc-bench/runs/` and `dcdc-bench/workspace/` finds exactly one real run whose
plan requests 12 V input and whose startup was attempted at 12 V: **e0fab9**.
The continuation `…_eb3bcd` did not repeat 12 V (its 12 V phase status is
`previous-attempt-unqualified`, `run.json` `method.voltage_efficiency_sweep.phases[0]`).
The workspace job `20260928T003420Z_c05e4f63` with 12/24/30 V targets is
`data_source: simulated` (`real_hardware_opened: false`). The 15 V descent run
reached a *measured* 12.0089 V input (`p0004`) while already running; that is
not a cold start.

The "twice" wording entered in commit `2757fd0` ("Reconcile dcdc-bench status
docs…"), replacing a sentence whose "Both attempts retain their own raw
evidence" referred to e0fab9 and its 24/36 V continuation. The b44da1
authorization text ("User explicitly requested **reproducing** 15 V startup then
continued operation toward 9 V") implies the operator observed a 15 V start by
hand, so a manual front-panel 12 V failure may have occurred; **it is not
recorded anywhere in the repository**. This document therefore treats the
second failure as *unrecorded* and analyses the one recorded attempt. The
coordinator should either add the operator's account as an operator
observation (with date and conditions) or reword the claim to "one recorded
automated attempt and one unrecorded operator observation".

## 3. Evidence

### 3.1 Configuration in force for the recorded 12 V attempt (e0fab9)

| Item | Value | Source |
| --- | --- | --- |
| Source | RIGOL DP821A, serial DP8G223300053, firmware 00.01.16, CH1 | `raw/events.jsonl` `identity_verified` |
| Load | RIGOL DL3031A, serial DL3A222600546, firmware 00.01.04.00.05 | same |
| Programmed input | 12.000 V (readback `12.000`) | `scpi.jsonl` 34–36 |
| Source current setting | 1.000 A (readback `1.0000`) | `scpi.jsonl` 38–40 |
| Source OVP / OCP | 13.0 V ON / 1.05 A ON, both `QUES? → NO` | `scpi.jsonl` 19–32 |
| Source OTP | ON | `scpi.jsonl` 62–64 |
| Independent source cutoff | DELAY group, 720 s, end state OFF, `DELAY ON` at 18:49:07.048 | `scpi.jsonl` 65–95 |
| Load mode | FIX / CC, level 0.1 A, `:SOUR:CURR:RANG MIN`, `:SOUR:CURR:SLEW:BOTH MIN`, VLIM 13.2 V, ILIM 2.55 A | `scpi.jsonl` 43–61 |
| Load sense | `:SOUR:SENS? → 0` (local sensing) | `scpi.jsonl` 13 |
| Software guards | input-current hard stop 1.02 A; phase end ≥ 0.995 A; input headroom stop programmed − 0.5 V; recorded `output_guard_V` [10.8, 13.2] (how the 10.8 V floor was applied in the code that ran is not recoverable, see below); output current guard 2.55 A | `run.json` `method`, `raw/events.jsonl` `protection_verified` |
| Measurement boundary | "source-to-load-terminal path (input and output wiring included)"; Vin at source terminals, Vout at load terminals, local sense | `run.json` `measurement_boundary`; sample `location` fields |
| Software | git commit `565c761`, `dirty: true`; `voltage_sweep.py` SHA-256 `bed7b36f…` | `run.json` `software` |
| Authorization text | "User explicitly requested 12/24/36 V efficiency testing … and the previously authorized 1 A source current setting" | `run.json` `authorization` |

The current `src/dcdc_bench/voltage_sweep.py` (SHA-256 `2e972aa4…`) differs
from the file that ran. Its `guard()` now raises
`"Converter output did not reach 10.8 V during source-only startup; load was not
enabled"` after five source-only cycles below 10.8 V. The transcript shows the
run that produced e0fab9 enabled the load in that situation, so the gate as
now written was not in force. Git cannot date the change because the code was
uncommitted at run time (`dirty: true`; the first commit of `voltage_sweep.py`
is `615f021`, after the run).

### 3.2 Timeline of the recorded 12 V attempt

Source enabled (`:OUTP? CH1 → ON`, `scpi.jsonl` 96) at 18:49:07.0716 UTC.
All values are the raw SCPI responses; `mode` is `:OUTP:CVCC? CH1` immediately
before and after each quartet.

| Cycle | t after enable | Vin_V | Iin_A | Vout_V | Iout_A | Source mode | Load input | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `c000001` | +1.043 s | 12.009 | 0.0016 | 0.001642 | 0.000000 | CV / CV | OFF | Output not yet rising |
| `c000002` | +2.174 s | 12.010 | 0.0019 | 5.169786 | 0.000000 | CV / CV | OFF | Rising |
| `c000003` | +3.291 s | 12.010 | 0.0013 | 8.115308 | 0.010929 | CV / CV | OFF | Peak observed output; 10.9 mA Iout readback with load OFF (see 3.5) |
| `c000004` | +4.449 s | 12.009 | **0.4809** | 7.985602 | 0.000000 | CV / CV | OFF | Single high input-current reading; output not rising |
| `c000005` | +5.563 s | 12.010 | 0.0013 | 7.982230 | 0.000000 | CV / CV | OFF | Output slowly falling |
| — | +5.647 s | | | | | | **ON** | `:SOUR:INP:STAT ON` (`scpi.jsonl` 177); readback `1` (179) |
| `c000006` | +6.681 s | **2.661** | **1.0005** | 6.384208 | 0.056747 | CV / CV | ON | Collapse; `BenchBoundary` raised |
| — | +6.773 s | | | | | | | `:OUTP CH1,OFF` (196); source, load and DELAY verified OFF by 18:49:13.997 (`events.jsonl` `shutdown`) |

Per-cycle four-query spans were 17.4–50.6 ms (computed from
`query_start/end_monotonic_s`), so each row is a near-simultaneous DC snapshot
at roughly 1.1 s intervals; nothing between rows was observed.

### 3.3 How the run stopped and what the source status said

The recorded error is `BenchBoundary: Supply current ceiling or input-voltage
headroom reached; excluded from efficiency results` (`run.json` `errors`;
point `p0001` `qualification: inconclusive`). In the guard that produced it,
this branch fires when a CC mode is read **or** `Iin_A ≥ 0.995` **or**
`Vin_V < programmed − 0.5`. At `c000006` the last two were true
(1.0005 A ≥ 0.995 A; 2.661 V < 11.5 V). The two `:OUTP:CVCC? CH1` queries
bracketing that quartet both returned **CV** (`scpi.jsonl` 183 at 13.7437 and
193 at 13.8331; the measurements were at 13.7601–13.7811).

Consequence: **no CC indication is recorded**, as the
[voltage-efficiency results review](voltage-efficiency-results-review.md) already
states. A DP821A CH1 programmed to 12.000 V that reads 2.661 V at 1.0005 A
against a 1.0000 A setting is electrically at its current limit at the instant
of those two readbacks; whether `:OUTP:CVCC?` lags, averages, or caught a CV
instant in an oscillating condition is **not established**. The task
description's phrase "CV→CC transition" is therefore an inference from the
V/I readings, not a logged status change. The M2 plan lists this as a
status-observability question.

### 3.4 Startups that succeeded, for comparison

Times are from each run's `source_enabled_with_deadline` event; the load was
OFF during every row unless stated.

| Vin programmed | Run / point | +1.0 s | +2.2 s | +3.3–3.5 s | +4.4–4.8 s | Stable no-load Iin | Load enable → first loaded cycle | First loaded Iin |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **12.0 V** | e0fab9 `p0001` | 0.0016 V | 5.170 V | **8.115 V** | **7.986 V** (Iin 0.4809 A) | — (never regulated) | enable at +5.65 s (Vout ≈ 7.98 V) → `c000006` at +6.68 s | 1.0005 A at 2.661 V |
| **15.0 V** | b44da1 `p0001` (`c000001`–`c000009`) | 0.0051 V | **7.121 V** | **7.951 V** | **12.146 V** (Iin 0.0253 A) | 0.0250–0.0253 A (`c000004`–`c000008`, 4.83 s span, 0.921 mV output spread) | enable at +9.84 s (Vout 12.145 V) → `c000009` at +10.91 s | 0.1117 A at 15.006 V |
| **24.0 V** | eb3bcd `p0009` (`c000001`–`c000006`) | 0.0056 V | **12.146 V** | 12.146 V | 12.146 V | 0.0158–0.0163 A (`c000002`–`c000005`) | enable between +5.7 and +6.9 s → `c000006` at +6.89 s | 0.0695 A at 24.006 V |
| **24.0 V** | 7a0fd6 `p0001` (`c000001`–`c000006`), 0.45 A source limit | 0.0007 V | **12.145 V** | 12.145 V | 12.145 V | 0.0158–0.0164 A | enable between +5.6 and +6.7 s → `c000006` at +6.72 s | 0.0391 A at 0.05 A load |
| **24.0 V** | 578d4f pilot, **0.15 A source limit**, OCP 0.18 A | (source-only cycles not recorded; first recorded cycle `c000001` is loaded: 24.006 V, 0.0690 A, 12.1399 V, 0.0622 A) | | | | | | 0.0690 A |
| **35.8 V** | eb3bcd `p0022` (`c000176`–`c000182`) | 0.117 V | **11.544 V** | **12.144 V** | 12.143 V | 0.0166–0.0175 A (`c000177`–`c000180`) | enable between +5.5 and +6.7 s → `c000181` at +6.66 s | 0.0551 A |

Observations that follow directly from the table:

1. Every successful startup reached ≥ 12.14 V with the load OFF and the source
   still in CV; the highest source-only input current read during any of them
   was **25.3 mA** (15 V). The 24 V pilot started into a **0.15 A** current
   limit without any recorded limit interaction. So a sustained startup demand
   above 1 A is **not** a general property of this converter's startup at
   15–35.8 V.
2. At 15 V the output paused near **7–8 V** for at least two cycles (+2.2 s to
   +3.5 s) at 1.7 mA input before stepping to 12.146 V; at 12 V it reached
   8.115 V at +3.3 s and had not stepped up by +5.56 s. At 24 V and 35.8 V no
   pause near 8 V was resolved at ~1.1 s sampling.
3. Steady-state light-load input current at a **measured 12.0089 V** input is
   **0.1394 A** (b44da1 `p0004`, 99.5 mA load) and **0.1791 A** at 9.108 V
   (`p0007`). The 1.0005 A drawn at collapse is therefore a startup or fault
   transient, not the converter's steady 12 V / 0.1 A requirement.

### 3.5 Other recorded observations relevant to the hypotheses

- **Single 0.4809 A input reading (e0fab9 `c000004`, +4.45 s):** the source
  stayed at 12.009 V and the output did not rise (7.986 → 7.982 V). The DP800
  `:MEAS:CURR?` value is an instrument average over an unknown window; a brief
  higher-current burst or a partial start attempt is compatible with this
  reading. Nothing else was recorded about it.
- **~11 mA output-current readback with the load input OFF:** e0fab9
  `c000003` (0.010929 A); b44da1 `c000002`–`c000005` (0.011009, 0.010929,
  0.010969, 0.011017 A); eb3bcd `c000002`, `c000003`, `c000005` (0.011168,
  0.011025, 0.011200 A); 7a0fd6 `c000001`, `c000002`, `c000004`; bring-up
  78961c `c000001` (0.011256 A at Vout 0.0 V). The load's `:SOUR:INP:STAT?`
  returned `0` in each case. This is a readback artifact or offset of the
  DL3031A on its programmed range, not converter current; it is intermittent
  (other OFF cycles read 0.000000). It is listed in the M2 plan as a
  readback-accuracy item and does not bear on the collapse.
- **First loaded cycle reads 54–83 mA, not 100 mA:** e0fab9 `c000006`
  0.0567 A; b44da1 `c000009` 0.0828 A; eb3bcd `c000006` 0.0795 A and
  `c000181` 0.0537 A. All four runs programmed `:SOUR:CURR:SLEW:BOTH MIN`. The
  low first reading is common to successful and failed starts and is not
  diagnostic.
- **Residual output voltage with everything OFF:** 0.001657 V before e0fab9
  (`outputs_off_readbacks`), 0.005134 V before b44da1, 0.128524 V before the
  pilot 578d4f, 0.29555 V in the root postflight after eb3bcd (review). The
  operator also saw ~0.178 V after the pilot and a slow discharge on a Fluke
  meter (implementation_status.md, historical record). The converter's internal
  discharge time is **unknown**; "cold" in this document means both outputs
  verified OFF and load-terminal residual below a declared value.
- **Load-disabled diagnostic** (`runs/load-disabled-diagnostic.json`,
  2026-09-27T06:05:47Z): with the source ON at 24.006 V and the load switched
  OFF the source current fell from 0.0687 A to **0.0156 A** and the output read
  12.14235 V. This is one snapshot, not a qualified point.

### 3.6 What was NOT measured

- No oscilloscope, no current probe: inrush, switching activity, output ripple,
  and any oscillation between the source's current limit and the converter are
  unobserved. Everything is ~1 Hz sequential DC readback with an unknown
  instrument averaging window.
- No voltage at the **DUT terminals**; Vin is at the DP821A CH1 terminals and
  Vout at the DL3031A terminals with local sense (`:SOUR:SENS? → 0`). Lead
  resistance, lead length and connector types are not recorded.
- No **DUT-terminal** input current independent of the source's readback.
- No source status other than `:OUTP:CVCC?`, `:OUTP:OVP:QUES?`,
  `:OUTP:OCP:QUES?` at ~1 Hz; the DP800's CV/CC flag semantics (latency,
  averaging) are not documented in this repository.
- Internal topology, controller, UVLO thresholds, soft-start scheme, hiccup or
  retry behaviour, and any input-side fuse or protection of the 12T12-4A are
  **unknown** (`profiles/dut/12t12-4a.yaml` `construction.topology: unknown`).
  The 9–36 V range is user-supplied and not verified from the sample label.
- Ambient and case temperature; time since the previous energization
  (e0fab9 began at 18:49:02 UTC; the previous real run, 75a478, ended at
  17:37 UTC).
- Whether the converter would have started at 12 V given more than 5.6 s with
  the load OFF. The recorded window ended when the load was enabled.
- The second reported failure (Section 2).

### 3.7 Inconsistencies found between existing documents and the evidence

1. [voltage-efficiency-test.md](voltage-efficiency-test.md) step 2 says the
   procedure "require[s] at least 10.8 V output before enabling the load at
   100 mA". The e0fab9 transcript enabled the load at ~7.98 V
   (`scpi.jsonl` 169 vs 177). The doc describes the *current* code, not the run.
2. The [README](../README.md#efficiency-at-different-input-voltages) says the
   attempt "produced about 8 V output with the load disabled, then stopped when
   input voltage collapsed"; it omits that the load was switched on ~1.0 s
   before the collapse reading. The
   [results review](voltage-efficiency-results-review.md) "What happened at 12 V"
   likewise does not mention the load enable.
3. "Failed direct 12 V cold-start twice" (implementation_status.md, README):
   one recorded attempt (Section 2).
4. The task brief for this document describes the stop as a "CV→CC transition";
   the log records CV before and after (Section 3.3).

## 4. Hypotheses

Each hypothesis is stated as a black-box mechanism. "Supports" and
"contradicts" refer only to the evidence in Section 3. None is established.

### (e) Load enable at a non-regulating ~8 V output triggered the collapse

**Mechanism.** With the output stalled near 8 V and the converter not yet
regulating, the DL3031A was switched to CC 0.1 A. The load pulled the output
down (6.384 V one second later) and whatever the converter did in response —
a hard start attempt, a retry, or an overload response — demanded more than
1 A from the source, which then fell to 2.661 V.

**Supports.** The collapse reading is the first cycle after `:SOUR:INP:STAT ON`
(+5.647 s → +6.681 s). For the preceding 5.56 s with the load OFF the source
never left 12.009–12.010 V and read ≤ 1.9 mA in four of five cycles. In every
successful run the load was enabled only after the output had been at
≥ 12.14 V for several cycles, and the first loaded input current was
0.039–0.112 A.

**Contradicts.** Nothing recorded. But (e) explains only the *collapse*; it
does not explain why the output had stalled at ~8 V for ≥ 2.3 s at 12 V when it
did not stall that long at 15 V. It is a proximate trigger, not a root cause.

**Discriminating observation.** Repeat the 12 V cold start with the load
**disabled for the full bounded window** (30 s). If the output reaches ≥ 12.1 V
and holds, (e) was the trigger and the underlying condition is a slow start
(c2). If the output stays near 8 V for 30 s with the source in CV, (e) is moot
and (b)/(c1) remain. If the source collapses without any load, (a)/(b) startup
demand is implicated instead.

### (c) Startup does not complete at 12 V: hard threshold (c1) or Vin-dependent delay (c2)

**Mechanism.** (c1) An internal start threshold above 12 V with a lower
operating threshold (hysteresis), so the converter never starts at 12 V but
keeps running down to at least 9.1 V once started. (c2) Startup at lower Vin
takes longer (for example a pre-charge or bias stage that completes more slowly
as Vin falls), so 12 V would have started given more than 5.6 s.

**Supports.** The stall at 7.98–8.12 V for ≥ 2.3 s at 1.3 mA input is
directly observed at 12 V; the same 7–8 V pause is visible at 15 V but ends by
+4.8 s; it is not resolved at 24 V or 35.8 V. Operation continued to 9.108 V
after a 15 V start (b44da1), which is consistent with hysteresis but, as the
[startup/descent review](startup-descent-results-review.md) states, only
establishes the operating range, not a start threshold.

**Contradicts.** For (c1): the output rose to 8.1 V and the source read
0.48 A once, so some internal activity occurred at 12 V; a converter fully held
off by UVLO would be expected to leave the output near 0 V — unless the 8 V is
a pre-charge path, which is unknown. For (c2): nothing contradicts it; the
window simply ended.

**Discriminating observation.** Cold starts at 13.5, 13, 12.5 and 12 V, each
from OFF with the load OFF for 30 s. A voltage at which the output reaches
≥ 12.1 V only after more than ~6 s separates (c2) from (c1); a voltage below
which the output never exceeds ~8 V in 30 s while the source stays in CV
brackets (c1). (c1) and (c2) cannot be separated by the recorded evidence.

### (b) Start behaviour near Vin ≈ Vout draws more current than at 15 V

**Mechanism.** The converter holds 12.13 V at both 15 V and 9.1 V input, so it
steps down and steps up. Whatever it does at start when Vin ≈ Vout (topology
unknown) could demand more input current, or take longer, than at 15 V or 24 V.

**Supports.** The failure is at the one tested Vin close to Vout. The 0.4809 A
reading at `c000004` shows a demand at 12 V not seen in any source-only cycle
at 15–35.8 V (max 25.3 mA).

**Contradicts.** The demand did not exceed 1 A while the load was OFF (source
stayed at 12.01 V through +5.56 s), so (b) alone did not cause the collapse
within the observed window. A single averaged reading cannot show the peak.

**Discriminating observation.** Same bracketing as (c); additionally, later and
separately approved, a cold start at 11 V or 10 V (below Vout). Success below
Vout with failure at 12–12.5 V would point to a Vin ≈ Vout region rather than
a monotonic threshold. A current probe on the input lead would show the actual
start demand; a source with > 1 A at 12 V would show whether the start
completes when the demand is met (Section 5.6). With the present instruments,
(b), (c1) and (c2) are indistinguishable.

### (a) Startup/inrush demand exceeded the 1 A source limit, so the source entered current limit and Vin collapsed

**Mechanism.** A source-limit interaction: the converter's demand at some
moment exceeded 1.000 A; the DP821A limited current, Vin fell, and a
step-up-capable converter facing a falling input keeps drawing current, so the
state latches at ~2.66 V / 1.0 A until the software turned the source off.

**Supports.** The final state (2.661 V at 1.0005 A against a 1.0000 A setting,
programmed 12.000 V) is a current-limited source by definition, irrespective
of the CV flag. It is not necessarily a DUT fault.

**Contradicts as the initiating cause.** For the first 5.56 s after enable the
input current read ≤ 1.9 mA except for one 0.4809 A sample, and Vin never
dropped below 12.009 V; the 24 V pilot started into a 0.15 A limit. So a
generic "inrush at output enable" did not trip the limit at 12 V within the
resolution of ~1 Hz averaged readbacks. The > 1 A demand appeared only after
the load was enabled at a non-regulating output.

**Discriminating observation.** A scope or current probe on the input lead
during a 12 V start (with and without load) shows whether demand exceeds 1 A
and for how long. A source with more than 1 A available at 12 V, or the same
source with the load kept OFF, separates "the source could not supply the
start" from "the converter did not start".

### (d) Input-lead drop under startup current lowered the DUT-terminal voltage below an internal threshold

**Mechanism.** Vin is measured at the source terminals. If the leads drop a
significant voltage under a startup current burst, the converter sees less
than 12 V at its terminals during the burst even though the source reads
12.01 V.

**Supports.** Nothing recorded supports it; lead resistance is unknown.

**Contradicts.** During the stall the input current was 1.3–1.9 mA, so lead
drop was negligible then; the stall itself is not explained by lead drop.
During the 0.4809 A sample the source still read 12.009 V, but the DUT
terminal voltage at that instant is unknown. Brief §6.3 warns that at low
input voltages source-terminal Vin is an inadequate statement of DUT voltage.

**Discriminating observation.** Measure input-lead resistance de-energized
(four-wire) and record lead length/gauge; log or observe the DUT-terminal input
voltage during a start (operator DMM reading is acceptable as an operator
observation; a logged channel is better). A DUT-terminal reading that stays
within a few tens of millivolts of the source during the whole start rules (d)
out for this wiring.

### Ranking by consistency with the recorded evidence

| Rank | Hypothesis | Role | Verdict on current evidence |
| --- | --- | --- | --- |
| 1 | (e) load enable at ~8 V | Proximate trigger of the collapse | Directly supported by ordering; contradicted by nothing; explains the collapse, not the stall |
| 2 | (c2) slow start at 12 V / (b) Vin ≈ Vout start behaviour | Underlying condition | Stall directly observed; window ended before either could be confirmed or excluded |
| 3 | (a) source current limit | Mechanism of the final state | Certain as the end state; contradicted as the initiating cause within the observed 5.6 s |
| 4 | (c1) hard start threshold above 12 V | Underlying condition | Consistent with 15 V start and 9.1 V operation; weakly contradicted by the 8 V rise and 0.48 A reading |
| 5 | (d) lead drop | Contributing factor | No evidence for or against; negligible during the stall |

(b), (c1) and (c2) are indistinguishable with sequential ~1 Hz DC readbacks
at the source and load terminals; only the bracketing test (time and voltage
resolution) and, ideally, a current probe or DUT-terminal voltage measurement
can separate them.

## 5. Supervised test plan — PROPOSAL

This section proposes a procedure. It **does not authorize** energizing the
converter. Before any run the owner must: approve this plan in writing; set
`execution_approval.real_hardware_enabled` and
`wiring_and_polarity_confirmed` on the DUT profile and
`protective_controls.approved` on the bench profile (currently `false` in
`profiles/dut/12t12-4a.yaml` and `workspace/profiles/bench/rigol-local-limited.json`);
confirm CH1 wiring, polarity, protections and both serial numbers at Start
(existing UI requirement); and confirm that the software gate in Section 3.1
(no load enable below 10.8 V) is the version that will run.

The plan is written so that its first stage repeats an already-demonstrated
condition (15 V) and moves toward 12 V in steps; each step is a separate cold
start from verified OFF.

### 5.1 Objective and declared criteria

Bracket the lowest source-terminal voltage at which this sample cold-starts
into an unloaded, regulating output within a bounded window, under a declared
criterion, and record how the start proceeds (time to first ≥ 10.8 V, time to
stability, any pause near 8 V, no-load input current). Then, separately and
only if the owner approves, observe whether a 0.1 A load can be applied at the
lowest successful start voltage.

Declared start criterion (proposal; mirrors the 15 V run's recorded settings
in b44da1 `run.json` `method.startup_descent`): **five consecutive source-only
readings with Vout ≥ 10.8 V spanning ≥ 4.0 s with output spread ≤ 50 mV, the
source in CV before and after every quartet, within 30 s of enable.** A start
that meets this is "started"; one that does not is "not started under the
criterion". Neither is a threshold measurement (Section 5.7).

### 5.2 Sequence

Start voltages, in order: **15.0, 14.0, 13.5, 13.0, 12.5, 12.0 V**. Optional
additional steps of 12.25 / 11.75 V may be proposed after the first pass.

For each start voltage V:

1. Both outputs verified OFF (`:OUTP? CH1`, `:SOUR:INP:STAT?`), source timer and
   DELAY OFF; load-terminal residual voltage ≤ **0.5 V** (the transition check
   already used in voltage-efficiency-test.md) — record the actual value and,
   if higher, how long it takes to fall below 0.5 V. Record the elapsed time
   since the previous source OFF; propose a minimum of **60 s** OFF between
   attempts so that "cold" is comparable between steps (the internal discharge
   time is unknown; the operator saw a slow discharge after the pilot).
2. Program and verify protections (Section 5.3), programmed voltage V, current
   setting 1.000 A, 720 s DELAY cutoff.
3. Enable the source. Poll a four-channel cycle every ~1 s for up to **30 s**
   with the load **OFF**. Record every cycle as `phase: starting`.
4. Stop criteria during the window (any one ends the attempt, source OFF first):
   - source `Iin_A ≥ 0.995 A` or `Vin_V < V − 0.5` or any CC readback →
     "source boundary during unloaded start" (distinct outcome from "did not
     start");
   - `Vout_V > 13.2 V` or `Vin_V > V + 0.5` or nonfinite reading or transport
     error or protection flag → hard abort of the whole plan;
   - start criterion met → record "started at V", record the stable no-load
     Iin/Vout window, then source OFF (no load in this stage);
   - 30 s elapsed without the criterion → record "not started under the
     criterion at V" and source OFF.
5. Verify source OFF, DELAY OFF, load OFF; record residual output voltage and
   the time it takes to fall below 0.5 V (this is also data about the output
   capacitance/discharge, currently unknown).
6. Continue to the next voltage only if the previous attempt ended in "started"
   or "not started"; a "source boundary" outcome pauses the plan for the
   owner's decision (it means the converter drew > 1 A with no load, which is
   hypothesis (a)/(b) and changes the risk picture).

Stage 2 (separate approval): at the lowest V that "started", repeat the cold
start and, after the criterion is met, enable the load at 0.1 A with
`ILIM 0.15 A` (as in b44da1) and acquire one qualified window. This tests
whether the descent-run operating point at ~12 V can also be reached from a
cold start.

Stage 3 (separate approval, only if 12 V "started" in Stage 1): repeat 12 V
twice more to see whether the outcome is repeatable, since one recorded
failure and one success would otherwise be a coin toss.

### 5.3 Protective settings (proposal)

| Setting | Value | Basis |
| --- | --- | --- |
| Source current setting | 1.000 A | Same as all runs since 75a478; the bench profile's capability |
| Source OCP | 1.05 A | Same as e0fab9/b44da1 |
| Source OVP | V + 1.0 V (16 V at 15 V … 13 V at 12 V) | e0fab9 used 13 V at 12 V; b44da1 used 16 V at 15 V |
| Input readback stop | Vin > V + 0.5 V; Vin < V − 0.5 V | voltage-efficiency-test.md fixed limits |
| Input current hard guard | 1.02 A | `method.input_current_absolute_guard_A` |
| Output guard | −0.05 … 13.2 V | existing guard |
| Load | OFF throughout Stage 1; CC 0.1 A, `RANG MIN`, `SLEW MIN`, VLIM 13.2 V, ILIM 0.15 A in Stage 2 | b44da1 settings |
| Independent cutoff | DELAY 720 s per energization, verified ON before enable | existing |
| Software deadline | 30 s window per attempt; whole plan ≤ 660 s | configured-runs envelope |
| Supervision | Operator present with the source's front-panel OFF reachable; no unattended mode | brief §7.4 |

### 5.4 What to record

Per attempt: every startup cycle (Vin, Iin, Vout, Iout, CVCC before/after,
load state, `query_start/end` times), the source-enable timestamp, time to
first Vout ≥ 10.8 V, time to criterion, duration and level of any pause in
the 5–9 V region, the maximum Iin during the window, the stable no-load Iin and
Vout means if the criterion is met (these are candidate *enabled-no-load*
observations for M2 — see the M2 plan), residual output voltage and decay time
after OFF, elapsed OFF time before the attempt, and ambient temperature if a
thermometer is available (otherwise "not measured"). Operator observations
(DMM at the DUT input terminals, audible or visible behaviour) go into
`operator_observations`, separately from samples.

### 5.5 What the outcomes would mean

| Outcome at 12 V (load OFF, 30 s) | Interpretation |
| --- | --- |
| Started, within ~5 s like 15 V | The recorded failure was most likely the load enable at 8 V (e); repeatability check (Stage 3) still needed |
| Started after > 6 s | Slow start at 12 V (c2); the e0fab9 window was too short; the procedure's fixed five-cycle pre-load window is inadequate near 12 V |
| Not started; output near ~8 V, source CV, Iin small | Incomplete start (c1 or b); a hard-threshold bracket between 12 V and the lowest "started" voltage under this criterion |
| Not started; source boundary with load OFF | Startup demand > 1 A at 12 V (a/b); requires a higher-current source or current probe before any further 12 V attempt |
| Started at 12.5 V but not 12.0 V (or similar) | A DATA-04-style bracket (Section 5.7) |

### 5.6 What additional instruments would add

- **A source with > 1 A available at 12 V** (not present; brief §3.2) would
  separate "could not be supplied" from "did not start" if a 12 V attempt ends
  at the source boundary with the load OFF. Its current limit would still be
  set deliberately (for example 2 A) with OCP, and its readback accuracy would
  need the same qualification as the DP821A's. It would not by itself explain
  the 8 V stall.
- **An oscilloscope with a current probe (or a shunt) on the input lead** would
  show the actual start demand and duration, any oscillation with the source
  limit, and whether the 0.4809 A sample was a burst. A second channel at the
  DUT input terminals measures lead drop directly (hypothesis d). Scope
  procedures are M5 scope in the brief and need their own approved recipe.
- **A logged DUT-terminal input voltage** (external DMM channel) is the M2
  "closer module-terminal boundary" from brief §3.3 and tests (d) without a
  scope.

### 5.7 Mapping to a DATA-04-style bracket

DATA-04 in the brief (§14.2) and `docs/acceptance.md` define the convention for
a UVLO-type result: "on at 9.1 V and off at 9.0 V produces a bracket/declared
convention, not an unsupported exact threshold". Applied here:

- If the converter "started" at V_hi and "not started" at V_lo under the
  declared criterion, report **"cold start succeeded at V_hi and did not
  complete within 30 s at V_lo (source-terminal voltage, load OFF, criterion
  as declared)"** as a bracket [V_lo, V_hi]. Do not report a threshold, a UVLO
  value, or a DUT-terminal voltage.
- The *operating* bracket already recorded is different and must be kept
  separate: continued operation at 100 mA down to a measured 9.1077 V after a
  15 V start (b44da1 `p0007`), with no loss of regulation observed and no
  lower bound found.
- The step size (0.5 V near 12 V) is the bracket's resolution; finer steps are
  a later proposal. Repeatability (Stage 3) is part of the bracket's
  credibility; a single success and a single failure at the same voltage is
  reported as such.

### 5.8 Recipe outline (YAML, proposal, not executable)

The existing recipes (`profiles/recipes/*.yaml`) only define
`steady_state_load_sweep` tests. The outline below uses a new test type that
**does not exist in the code**; the planner would reject it today. It is
written in the same shape so that, if the owner approves, the implementation
target is clear. `execution_mode: mock` and all approvals `false` are
deliberate.

```yaml
# PROPOSAL ONLY. Test type cold_start_bracket is NOT implemented; this file is
# not executable and must not be armed. See docs/cold-start-hypothesis.md §5.
schema_version: '1.0'
recipe_id: 12t12-4a-cold-start-bracket-proposal
dut_profile_id: 12t12-4a
execution_mode: mock
tests:
- id: cold-start-bracket
  type: cold_start_bracket            # not implemented
  input_voltage_targets_V: [15.0, 14.0, 13.5, 13.0, 12.5, 12.0]
  output_current_targets_A: [0.0]     # load input OFF for the whole window
  derived_results:
  - cold_start_outcome_per_voltage    # started / not-started / source-boundary
  - time_to_output_above_10p8_V
  - unloaded_startup_input_current    # candidate enabled-no-load observation
  - cold_start_bracket_declared_convention
  required_quantities: [Vin_V, Iin_A, Vout_V, Iout_A]
  optional_quantities: [source_mode, dut_terminal_Vin_V]   # second is not available today
startup:
  settings_origin: draft_requires_owner_approval
  window_s: 30.0
  poll_interval_s: 1.0
  criterion:
    minimum_output_V: 10.8
    stable_sample_count: 5
    minimum_stable_span_s: 4.0
    maximum_vout_span_V: 0.05
    require_source_cv_brackets: true
  load_enabled_during_startup: false
  minimum_off_time_between_attempts_s: 60.0
  maximum_residual_output_V_before_attempt: 0.5
  pause_plan_on_source_boundary: true
planning:
  efficiency_estimate_fraction: 1.0
  source_current_budget_fraction: 1.0
  infeasible_point_policy: record_and_skip
  assumption_status: planning_only_not_measured
settling:
  policy: electrical
  settings_origin: draft_requires_bench_validation
  minimum_dwell_s: 5.0
  window_s: 4.0
  minimum_fresh_samples: 5
  maximum_vout_span_V: 0.05
  timeout_s: 30.0
acquisition:
  duration_s: 8.0
  target_poll_interval_s: 1.0
  minimum_complete_cycles: 5
  maximum_interchannel_skew_s: 0.75
  settings_origin: draft_requires_driver_timing_validation
authorization:
  require_operator_arming: true
  allow_unattended: false
  protective_policy_id: null          # to be issued with the owner's approval
  owner_plan_approval: false
  dut_real_hardware_enabled: false
  dut_wiring_and_polarity_confirmed: false
  bench_protective_controls_approved: false
```

## 6. What this document does not establish

- The cause of the recorded 12 V failure. It establishes the recorded
  sequence and which hypotheses that sequence supports or contradicts.
- Whether the converter can cold-start at 12 V given more time, or at any
  voltage below 15 V.
- A UVLO threshold, a start threshold, hysteresis, inrush current, or any
  internal mechanism.
- The existence or conditions of the second reported failure.
- That the proposed 30 s window, 0.5 V residual limit or 60 s OFF time are
  correct for this converter; they are declared conventions to be approved.
- Any authorization to energize the converter.

## 7. Evidence index

| Evidence | Path (relative to `dcdc-bench/`) |
| --- | --- |
| Recorded 12 V attempt | `runs/real-voltage-sweep/20260927T184902.863440Z_real_e0fab9/` (`run.json`, `raw/samples.jsonl`, `raw/events.jsonl`, `scpi.jsonl`) |
| 24 V / 35.8 V continuation and its startups | `runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/` |
| 15 V start and descent to 9.1 V | `runs/real-startup-descent/20260927T212200.072951Z_real_b44da1/` (`analysis/a-64db20585452/points.csv`) |
| 24 V pilot and its stopped attempts | `runs/real-bringup/20260927T055756.092377Z_real_890f71/`, `…T055903.309087Z_real_78961c/`, `…T060729.553484Z_real_7dfc6c/`, `…T061038.184185Z_real_578d4f/` |
| 24 V extended runs (0.45 A source limit) | `runs/real-extended/20260927T093111.072469Z_real_7a0fd6/`, `…T093948.075493Z_real_42e971/` |
| 24 V source-limit search | `runs/real-source-limit/20260927T173043.388477Z_real_75a478/` |
| Load-disabled snapshot | `runs/load-disabled-diagnostic.json` |
| Current startup gate | `src/dcdc_bench/voltage_sweep.py` `guard()` |
| Procedure and reviews | `docs/voltage-efficiency-test.md`, `docs/voltage-efficiency-results-review.md`, `docs/startup-descent-results-review.md`, `docs/source-limit-results-review.md`, `docs/engineering-figure-labels.md`, `docs/configured-runs.md` |
