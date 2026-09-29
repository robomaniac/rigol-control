# M2 evidence from existing logs: readback cadence, the 11 mA off-state current, range logging

Plan step 2 of [m2-qualification-plan.md](m2-qualification-plan.md) (§2 Gap A, §3 Gap B, §8 item 2).
**Scope: log analysis only** — no instrument touched, no data corrected; nothing here is a calibration
or a specification value. Statements labelled *inference* are readings of the logs, not instrument
properties; the bench tests of plan step 4 remain necessary.

Inputs: `runs/real-*/*/scpi.jsonl` and `raw/samples.jsonl` of the ten real run directories of
2026-09-27 (four bring-up attempts, two extended, source-limit, startup-descent, two voltage-sweep;
5,980 samples, 25,112 transcript records). Tool: `tools/readback_cadence.py <runs-root|run_dir...>`
(standard library, deterministic; prints every table below plus per-run detail). *Settled window* =
consecutive cycles of one point in phase `acquiring`; *identical* = byte-equal `raw_response`; *poll
interval* = Δ `query_start_monotonic_s`; *round trip* = `query_end − query_start`; the transcript
`timestamp` marks query completion (0.6–1.9 ms before `query_end_utc`). Query strings confirmed:
source `:MEAS:VOLT? CH1`, `:MEAS:CURR? CH1`; load `:MEAS:VOLT?`, `:MEAS:CURR?`.

## A. Readback cadence and freshness (Gap A)

Table A1 — identical consecutive polls in settled windows: fraction; longest identical run (polls / s).
Median poll interval 1.135–1.153 s in every run (min 1.086 s). 578d4f (4 pairs) is pooled only.

| Run | pairs/ch | Vin_V | Iin_A | Vout_V | Iout_A |
| --- | --- | --- | --- | --- | --- |
| 7a0fd6 extended | 159 | 0.786; 9 / 9.40 | 0.522; 9 / 9.06 | 0.126; 4 / 3.51 | 0.057; 2 / 1.10 |
| 42e971 extended | 294 | 0.759; 9 / 9.16 | 0.527; 9 / 9.24 | 0.133; 3 / 2.31 | 0.041; 3 / 2.71 |
| 75a478 source-limit | 191 | 0.827; 26 / 29.60 | 0.513; 8 / 7.99 | 0.183; 3 / 2.27 | 0.094; 3 / 2.32 |
| b44da1 startup-descent | 41 | 0.756; 8 / 7.90 | 0.268; 4 / 3.49 | 0.220; 3 / 2.24 | 0.049; 2 / 1.13 |
| eb3bcd voltage-sweep | 177 | 0.921; 8 / 7.88 | 0.514; 7 / 7.34 | 0.130; 3 / 2.28 | 0.028; 2 / 1.14 |
| pooled | 866 | 0.813 | 0.507 | 0.145 | 0.054 |

Table A2 — |Δ| between consecutive settled polls, in units of the last printed digit (pooled, 5 runs).

| Channel (digit) | 0 | 1 | 2 | 3–10 | 11–100 | 101–1000 | Effective step (*inference*) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Vin_V (1 mV) | 700 | 162 | 0 | 0 | 0 | 0 | 1 mV = printed digit |
| Iin_A (0.1 mA) | 438 | 385 | 36 | 3 | 0 | 0 | 0.1 mA = printed digit |
| Vout_V (1 µV) | 126 | 0 | 0 | 0 | 690 | 46 | ≈ 14.5–15 µV (Δ = 14/15, 29/30, 44/45, 59/60 µV) |
| Iout_A (1 µA) | 46 | 0 | 0 | 83 | 579 | 154 | ≈ 8 µA (Δ = 8, 16, 24, 32, 40, 48, 56 µA) |

Table A3 — identical Vout *and* Iout in the same cycle pair, observed vs expected if the channels
repeat independently: load 7 vs 7.0 (per run 0/1.1, 2/1.6, 4/3.3, 0/0.4, 1/0.6; 862 pairs); source
351 vs 356.1. One held conversion served to both channels would make them coincide far above chance.

Table A4 — round trip `query_end − query_start`, 1,495 samples per channel, ms (transcript `duration_s`
medians 3.8–4.4 ms; the ≈1 ms difference is host-side timestamping).

| Channel | min | median | p95 | max | Channel | min | median | p95 | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| source Vin_V | 4.1 | 5.4 | 36.1 | 55.2 | load Vout_V | 4.0 | 5.1 | 23.8 | 45.1 |
| source Iin_A | 4.1 | 5.1 | 13.0 | 53.1 | load Iout_A | 4.1 | 4.9 | 18.8 | 43.1 |

What the logs support (*inference* unless stated as a count):
- Source: identical fractions 0.76–0.92 (Vin) and 0.27–0.53 (Iin) are what a stable setpoint looks like
  at 1 mV / 0.1 mA (every change is 1–2 digits). They carry **no information about refresh**; a
  fixed-setpoint burst on the source will be equally blind.
- Load: the printed 1 µV / 1 µA digits are finer than the readback step (≈15 µV, ≈8 µA) and noise spans
  several steps, so 13–22 % (Vout) and 3–9 % (Iout) identical polls are consistent with quantised noise
  about a stable value; Table A3 shows no coincident holding of the two channels. If one held conversion
  with period T_r > 1.14 s served both, the excess "both" count would be ≈ N·(1 − 1.14 s/T_r); 7 observed
  vs 7.0 expected limits it to a few pairs, i.e. T_r ≲ 1.15 s **under the shared-conversion assumption**.
  In b44da1 the last `settling` and first `acquiring` poll of a point were 0.107–0.185 s apart five
  times; the load Vout string changed in 4 of 5 (fresh conversions within ≤ 0.19 s), the source Vin string
  in 0 of 5 (1 mV digit, setpoint stable). n = 5: an observation, not a bound.
- Longest identical runs on the load in settled windows are 2–4 polls (1.1–3.5 s) and rare; on the
  source they span whole acquiring windows (9–26 polls) because of resolution.

Cannot be concluded from these logs: (1) whether any individual identical load reading is stale — at a
≈15 µV / 8 µA step a stable measurement returns the same string too; (2) any refresh property of the
source channels; (3) refresh structure below the ≈1.1 s poll period (five b44da1 intervals aside);
(4) latency T_l — setpoint writes precede the next poll by ≥ 1 s; (5) whether the load converts V and I
in one scan (Table A3's bound assumes it does).

## B. The ≈11 mA load current with the input OFF (Gap B, Gap E)

Table B1 — every load `:MEAS:CURR?` while `:SOUR:INP:STAT` was OFF (transcript state tracking; samples:
phase `starting`, load_enabled = false). Source output was ON for all 39 reads; **no OFF-state
load-current read with the source OFF exists** (`outputs_off_readbacks` events log voltages only), so
the source-state correlation asked for in the plan cannot be tested from logs.

| Run | Vin (V) | reads | 0.000000 | 10.9–11.3 mA | nonzero min–max (mA) | Vout during reads (V) |
| --- | --- | --- | --- | --- | --- | --- |
| 78961c bring-up | 24.005 | 1 | 0 | 1 | 11.256 | 0.000 |
| 7a0fd6 extended | 24.005 | 5 | 2 | 3 | 11.152–11.312 | 0.0007–12.145 |
| 42e971 extended | 24.004 | 5 | 2 | 3 | 11.136–11.296 | 0.088–12.144 |
| 75a478 source-limit | 24.006 | 5 | 1 | 4 | 10.985–11.192 | 0.0004–12.146 |
| b44da1 startup-descent | 15.005 | 8 | 4 | 4 | 10.929–11.017 | 0.005–12.146 |
| e0fab9 sweep (aborted) | 12.010 | 5 | 4 | 1 | 10.929 | 0.002–8.115 |
| eb3bcd sweep, 1st startup | 24.006 | 5 | 2 | 3 | 11.025–11.200 | 0.006–12.146 |
| eb3bcd sweep, 2nd startup | 35.797 | 5 | 5 | 0 | — | 0.117–12.144 |
| pooled | — | 39 | 20 | 19 | 10.929 / 11.136 / 11.312 (min/med/max) | — |

- Counts: the reading is **bistable** — exactly `0.000000` (20/39) or 10.93–11.31 mA (19/39), never
  anything else; sequences alternate irregularly (7a0fd6: 11, 11, 0, 11, 0 mA; b44da1: 0, 11, 11, 11,
  11, 0, 0, 0). The nonzero value is the same at 05:59 and 21:22 UTC and at 12, 15 and 24 V. It appears
  at Vout = 0.000 V (78961c, 75a478) and at 12.146 V, as does zero; no dependence on time since the
  `:SOUR:INP:STAT OFF` write (1.5–10.8 s). The 35.8 V startup read zero five times (n = 5, not evidence).
- *Inference*: with the input stage OFF no real 11 mA flows, and an exact `0.000000` on a channel whose
  step is ≈8 µA is a substituted value, not a conversion. The pattern is consistent with the instrument
  alternately reporting a gated zero and an un-zeroed ≈11.1 mA readback offset; the mechanism, and
  whether the offset also exists with the input ON, is unknown.
- Loaded phases: in settled windows the per-level mean of `Iout − requested` is −0.84 to +0.33 mA at
  every level 0.05–2.5 A (individual samples −1.1 to +0.4 mA), repeatable per level across runs (0.10 A:
  −0.67, −0.58, −0.66, −0.58, −0.58, −0.62 mA in 578d4f, 7a0fd6, 42e971, 75a478, b44da1, eb3bcd; 0.05 A:
  −0.17, +0.02; 0.20 A: −0.08 to +0.01). *Inference*: a level-dependent repeatable residual is a setpoint
  (programming) quantisation signature, not a readback offset. **No +11 mA appears in the readback under
  load.** Not excluded: an offset in a sense path shared by the CC loop and the readback makes the
  readback equal the setpoint while the true current is setpoint − offset; requested-vs-measured is blind
  to it. Only an independent reference (plan step 4 DMM cross-check) can close this.

Supported statement: *"With the load input OFF and the source ON, the DL3031A current readback returns
either exactly 0 A or 10.93–11.31 mA (median 11.14 mA); the states alternate between ≈1.1 s polls and do
not track Vout or elapsed time."* Not supported: a fixed zero offset of loaded readback, or harmlessness.
A shared-path offset of that size would be 22 % of the 0.05 A and 11 % of the 0.1 A points. For Gap E, no
`:MEAS:CURR?` with the input ON at a 0 A setpoint has ever been logged; that behaviour is unobserved.

## C. Range logging (spec §9.2 "log actual ranges", §8.2 `range_id`)

Present: `measurement_range: null`, `resolution: null` in all 5,980 samples; one `:SOUR:CURR:RANG MIN`
write per run (10 total, never queried back); one `:SOUR:SENS?` → `0` per run (kept as
`acquisition_settings.load_sense: "local"`); profile `measurements.*.measurement_range / resolution /
accuracy / programming_accuracy` all null (`workspace/profiles/bench/rigol-local-limited.json`).
Missing: any readback of the range in force on either instrument (load current *and* voltage, source
CH1), the programmed-CC-range vs measurement-range distinction, aperture/averaging, a per-sample `range_id`.

Software changes (no instrument access needed; values still to be transcribed from R1/R4 with pages):
`src/dcdc_bench/bringup.py` `cycle()` hard-codes `measurement_range=None, resolution=None` while
`runner.py`/`uvlo.py` copy `binding.measurement_range`/`.resolution` from the profile — make bring-up do
the same. After `apply_load_cc_limits`, query the range readback (load: expected `:SOUR:CURR:RANG?`, per
R4; source CH1 if R1 defines one), store the raw responses in an `instrument_ranges` event and in
`acquisition_settings`, populate the profile's `measurement_range` only from the documented *measurement*
range for that selection — never from the programming range (§3.3) — and add `range_id: str | None` to `RawSample`.

## D. Parameters this evidence suggests for plan step 4 (bench, no DUT)

- **Burst (T_r)**: back-to-back queries, no sleep; round trips are 4–5 ms median, 55 ms worst, so ≥ 400
  polls per channel (≈2–3 s) spans two refresh periods even at the 1.15 s upper estimate. Interleave the
  load's `:MEAS:VOLT?` and `:MEAS:CURR?` (V, I, V, I …) so the dwell between changes gives T_r per channel
  *and* shows whether V and I update together. The load's noise (several ≈15 µV / 8 µA steps) makes
  nearly every fresh conversion visibly different; the source's 1 mV / 0.1 mA digits will not — do not
  infer source refresh from a fixed-setpoint burst.
- **Step (T_l and source refresh)**: load 0.10 → 0.20 A (both levels have logged residual signatures; Iin
  moves ≈0.05 A ≈ 500 source digits) and source 24.0 → 23.0 V (1 V steps were used in b44da1), within the
  approved envelope; poll all four channels back-to-back for ≥ 3 s after the write; ≥ 10 repetitions.
- **Zero/offset check (11 mA)**: source ON into the load, input OFF: ≥ 30 reads at 1.1 s (reproduces the
  logged ≈50/50 bistable pattern) plus one ≥ 400-read burst to see whether the states flip at the refresh
  cadence; then source OFF, input OFF (the case the logs lack); then, if the procedure permits, input ON
  at 0 A setpoint (the Gap E condition, never observed). Interleave `:SOUR:INP:STAT?`.

Evidence: `runs/real-{bringup,extended,source-limit,startup-descent,voltage-sweep}/<timestamp>_real_<id>/`
(`scpi.jsonl`, `raw/samples.jsonl`, `raw/events.jsonl`); ids as in the tables. Reproduce with the tool above.
