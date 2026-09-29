# M2 qualification plan

**Status: plan, not a record of completed qualification.** Prepared
2026-09-27 UTC by an automated agent role from the retained evidence, without
contacting instruments or changing code, runs or profiles. It addresses item 1
of the "Next bounded task" in [implementation_status.md](implementation_status.md):

> Finish M2 qualification: measurement freshness (independent readback timing,
> not query spans), readback accuracy at the ranges to be claimed, an evaluated
> uncertainty budget, the physical load's capability, and a qualified
> enabled-no-load measurement.

Where a datasheet number is needed it is written as *to be transcribed from
R1/R4, page …*; no specification value is invented here. R1–R4 are the Rigol
documents listed in [implementation-brief.md §18](implementation-brief.md#18-sources-and-reference-artifacts).
Paths are relative to `dcdc-bench/`.

## 1. What M2 requires

Brief §15, M2 exit: "saved measurements agree with observed bench behavior,
point provenance is complete, and the approved stop procedure has been
demonstrated. Record what was and was not independently checked." Brief §17
lists the bench-confirmation items still open that M2 must close for the
claims being made: *acquisition capability* (freshness, polling/update rates,
timing skew, queried voltage/power meaning, status observability), *exact
equipment* (physical model, firmware, usable ratings and ranges), *measurement
qualification* (applicable specifications/calibration; whether an external
meter is available) and *wiring* (sense points, pigtail boundary).

What is already demonstrated and is **not** re-planned here: verified stop
procedure and OFF readbacks in every real run; complete point provenance
(SCPI transcript, per-query timing, integrity manifests); agreement of saved
means with independent recomputation (three agent-role audits). What remains
is the five-item metrology gate below. The one common thread: the bench
profile that every real run declares
(`workspace/profiles/bench/rigol-local-limited.json`) has `accuracy`,
`measurement_range`, `resolution` and `programming_accuracy` set to `null` for
all four channels, `physical_model: null` for both instruments and, at the same
time, `capabilities_confirmed: true`. Every saved analysis carries
`uncertainty.json` = `{"status": "unquantified", "reason": "No applicable
complete readback uncertainty budget evaluated", "bands": null}`
(for example `runs/real-startup-descent/…_b44da1/analysis/a-64db20585452/`).
Qualification means turning those nulls into transcribed, sourced values and
the "unquantified" status into an evaluated budget — or into an explicit,
reasoned "not applicable".

## 2. Gap A — measurement freshness

### What "qualified" means

Evidence that each `:MEAS:…?` response reflects a conversion made within a
declared latency of the query, and that the four readings of one cycle refer to
a declared, bounded time window — distinct from how long the SCPI round trip
took (brief §7.2 "fresh, plausible readings", §7.3 "stale samples … cannot
become ordinary valid points", §17 "Freshness, polling/update rates, timing
skew"). The qualified statement has the form: *readback refresh interval
≤ T_r, command-to-readback latency ≤ T_l, both measured on this firmware; the
acquisition polling interval (≈1 s) and the accepted four-query span limit
(750 ms) are each larger than T_r*.

### Evidence that exists now

- Every sample carries `acquisition_settings.adc_freshness: "not independently
  verified"` (`raw/samples.jsonl`, all runs).
- What *is* recorded is round-trip timing. From `query_start/end_monotonic_s`
  over the real runs: single-query durations average 4.6–10.7 ms per channel,
  with maxima of 34–55 ms (`Vin_V`), 12–39 ms (`Iin_A`), 6–45 ms (`Vout_V`),
  5–43 ms (`Iout_A`); per-cycle four-query spans have medians of 22–30 ms and
  maxima of 50.6 ms (e0fab9, 6 cycles), 74.1 ms (b44da1, 106 cycles), 80.7 ms
  (eb3bcd, 359 cycles) and 98.7 ms (75a478, 333 cycles, all cycles; the
  accepted-cycle maximum reported in the [source-limit review](source-limit-results-review.md)
  is 79.50 ms). These numbers bound *skew between channels*; they say nothing
  about the instruments' internal update rate.
- Coarse evidence that readbacks are not frozen at the 1 s scale: consecutive
  cycles in b44da1 read 0.005 → 7.121 → 7.951 → 12.146 V (`c000001`–`c000004`);
  the load-disabled snapshot (`runs/load-disabled-diagnostic.json`) shows the
  source current falling 0.0687 → 0.0156 A when the load was switched off; in
  e0fab9 `c000006` all four channels moved together within one 29 ms quartet.
  None of this resolves refresh at the tens-of-milliseconds scale or shows
  whether two queries 5 ms apart return the same conversion.
- The load's `:STAT:QUES:COND?` and the source's `:OUTP:CVCC?` are polled
  around each quartet; the CVCC flag read CV on both sides of the e0fab9
  collapse quartet (see [cold-start-hypothesis.md §3.3](cold-start-hypothesis.md)),
  so the flag's latency/averaging is itself an open observability question.

### Procedure to establish it

Software-only first (no bench time):

1. From existing `scpi.jsonl` files, count runs of identical consecutive
   responses per channel within stable windows and the shortest interval at
   which a value changed. This gives a lower bound on refresh cadence from
   data already on disk; it cannot give the upper bound because polling was
   ~1 Hz.
2. Search R1 and R4 for a stated measurement update rate or sampling period
   for `:MEAS` readbacks (*to be transcribed from R1, page …* and *R4, page …*;
   if absent, record "not specified by the manufacturer").

Bench, owner authorization required, **no DUT connected** (source CH1 wired
directly to the load, low power, e.g. within the existing profile envelope):

3. Burst test: with a stable setpoint, issue ≥ 50 back-to-back `:MEAS:VOLT?`/
   `:MEAS:CURR?` queries per instrument and record the dwell time between
   value changes → refresh interval T_r per instrument and channel.
4. Step test: command a load-current step (or source-voltage step within
   limits) and record the time from command acknowledgement to the first
   changed readback on each affected channel → latency T_l. Repeat ≥ 10 times.
5. Status latency: during the step test, poll `:OUTP:CVCC?` to see how quickly
   it follows a deliberate, bounded entry into current limit **on the
   source-into-load fixture only** (never with the DUT); if the owner does not
   approve deliberate CC entry, record the flag's latency as unknown.
6. Record T_r, T_l, firmware, date and the SCPI transcript in the bench
   profile (`measurements.*` gains `refresh_interval_s` / `latency_s` fields or
   a `notes` entry) and in `docs/`; replace the sample annotation with a
   reference to that record.

Pass condition: T_r and T_l both documented and both smaller than the
declared polling interval, or the polling interval raised to satisfy them.

## 3. Gap B — readback accuracy at the ranges to be claimed

### What "qualified" means

For each of the four channels: the manufacturer's **readback** (measurement)
accuracy at the **range actually used**, with its read-percentage, full-scale
or offset term, temperature and warm-up conditions, source document and page;
kept separate from programming accuracy and from display resolution (brief
§3.3 last paragraph, §9.2); plus the calibration status of each instrument
(date, certificate or "unknown"). Stored in the bench profile's
`measurements.<channel>.accuracy`, `.measurement_range`, `.resolution`,
`.programming_accuracy`.

### Evidence that exists now

- One transcribed term: [voltage-efficiency-test.md](voltage-efficiency-test.md)
  cites R1 printed page 5 for DP821A CH1 "voltage programming and readback
  accuracy of ±(0.1% + 25 mV)". Because R1 lists programming and readback
  separately, the transcription should be re-checked against R1 page 5 before
  it is entered as a *readback* term; until then it is *to be confirmed*.
- Nothing is transcribed for DP821A CH1 **current** readback, or for DL3031A
  voltage or current readback (*to be transcribed from R1, page …* and *R4,
  page …*).
- The load is programmed to `:SOUR:CURR:RANG MIN` in every real run
  (`bringup.py` `apply_load_cc_limits`). Which physical CC range that selects
  on a DL3031A, and whether the readback specification depends on it, is *to be
  transcribed from R4, page …*. Brief §3.3 explicitly forbids applying a low
  CC programming range's accuracy to current readback without documentation.
- Ranges actually used in qualified (loaded) points: Vin 9.1077–35.797 V;
  Iin about 0.039–0.9873 A; Vout 11.886–12.137 V; Iout 0.0497–2.4993 A.
  Unqualified readings extend lower: source-only no-load Iin 0.0156–0.0253 A,
  startup Iin down to 0.0013 A, startup Vout up to 12.146 V. Displayed resolution of the raw SCPI
  responses: source 1 mV / 0.1 mA (`12.009`, `0.0016`), load 1 µV / 1 µA
  (`12.145664`, `0.011009`). Resolution is not accuracy.
- Calibration: no calibration record for (supply serial: private inventory) or (load serial: private inventory) exists
  in the repository; status **unknown**.
- Two recorded readback anomalies that must be explained before an accuracy
  claim at light load:
  1. **~11 mA `Iout` readback with the load input OFF** (`:SOUR:INP:STAT? → 0`):
     b44da1 `c000002`–`c000005` (0.010929–0.011017 A), e0fab9 `c000003`
     (0.010929 A), eb3bcd `c000002`/`c000003`/`c000005` (0.011025–0.011200 A),
     7a0fd6 `c000001`/`c000002`/`c000004`, bring-up 78961c `c000001`
     (0.011256 A at Vout 0.0 V). Other OFF cycles in the same runs read
     0.000000 A. Whether this is an offset, an auto-zero behaviour, or a
     transient of the load's ADC is unknown; it is the same order as 10 % of
     the 0.1 A qualified points.
  2. **Residual load-terminal voltage with both outputs OFF** of 0.0017 V to
     0.2956 V across runs (`outputs_off_readbacks` events; root postflight in
     the [voltage-efficiency review](voltage-efficiency-results-review.md)),
     which may be retained charge, not a readback error, but has not been
     separated from one.
- The operator's Fluke multimeter readings exist only as operator observations
  (578d4f `operator_observations`: "approximately 12 V … 0.0993 A at 12.133 V");
  its model and accuracy are not recorded.

### Procedure to establish it

Software-only:

1. Transcribe into the bench profile, with page references: DP821A CH1
   voltage readback and current readback terms and conditions (*R1, page …*);
   DL3031A voltage readback and current readback terms per range, the range
   selected by `RANG MIN`, and the minimum operating voltage (*R4, page …*).
   Enter `measurement_range` for each channel as actually used. Keep
   `programming_accuracy` separate.
2. Analyse the existing logs for the 11 mA artifact: timing relative to the
   load's output-voltage rise, whether it appears only while Vout is changing,
   and whether it ever appears in accepted cycles. Report the result in the
   review docs; if it appears only with the input OFF during voltage rise, it
   can be excluded from loaded-point accuracy claims with a stated reason.
3. Record calibration status as "unknown; no certificate on file" for both
   instruments unless the owner supplies documents.

Bench, owner authorization required:

4. **No-DUT plausibility cross-check** (not calibration): source into load at
   three points inside the envelope, compare each instrument's readback with
   the owner's DMM (record its model, range and accuracy, *to be transcribed
   from its manual*). Agreement within the combined stated limits supports the
   transcribed terms; disagreement is a finding, not a correction factor.
5. **Zero and offset check**: with the source ON into the load and the load
   input OFF, record ≥ 30 `:MEAS:CURR?` responses from the load to see whether
   the 11 mA reading recurs and under what condition.
6. If a calibrated reference becomes available, a formal verification at the
   used ranges replaces step 4.

Pass condition: all four `accuracy` fields populated with sourced terms and
conditions; calibration status recorded; the 11 mA artifact explained or
bounded with an explicit exclusion rule.

## 4. Gap C — evaluated uncertainty budget

### What "qualified" means

Per brief §9.2: a structured budget listing every term (read-percentage,
range/full-scale, absolute offset, calibration interval, temperature,
acquisition condition) with its source; rectangular limits converted to
standard uncertainty a/√3; combined through the declared measurement model
without dividing systematic terms by √N; expanded uncertainty U = k·u_c with k
stated and not automatically called a 95 % interval; efficiency uncertainty in
**percentage points**; loss uncertainty propagated separately in watts; a
near-zero-current check; and, where any term is unknown, the status
"unquantified" with no bands (UNC-02). The calculation path already exists and
is regression-tested with the UNC-01 fixture (`docs/acceptance.md` UNC-01 to
UNC-04); what is missing is the *first DUT's actual terms*.

### Evidence that exists now

- `uncertainty.json` status `unquantified` in every real analysis; reports
  show no bands (UNC-02 behaviour confirmed by the reviews).
- The measurement model is the product of channel means:
  η = (V̄out · Īout) / (V̄in · Īin). For independent channels the relative
  standard uncertainty is
  `u_rel(η)² = u_rel(Vin)² + u_rel(Iin)² + u_rel(Vout)² + u_rel(Iout)²`,
  and with a rectangular limit `a_x = p_x·x + c_x` for channel x,
  `u_rel(x) = (p_x + c_x / x) / √3`. Loss: `u(Ploss)² = u(Pin)² + u(Pout)²`
  with `u(P)/P = √(u_rel(V)² + u_rel(I)²)`.

### Which channel dominates at the light-load points

This follows from the model without any specification value: every channel
enters `u_rel(η)` with sensitivity 1, so the dominant channel is the one with
the largest `p_x + c_x/x`, and `c_x/x` grows as the reading shrinks. The
smallest readings in the qualified data are on the **input-current channel**:
Īin = 0.0688 A at the 24 V / 0.1 A pilot (`runs/real-bringup/…_578d4f`),
0.1114 A at 15 V / 0.1 A (b44da1 `p0001`), and the source-only no-load
readings of 0.0158–0.0163 A at 24 V (eb3bcd `c000002`–`c000005`) and
0.0250 A at 15 V. Output current at the same points is 0.099 A; voltages are
≥ 9.1 V. So for any input-current offset term c_Iin of 0.1 mA or more,
c_Iin/Īin at the no-load reading is ≥ 0.63 %, already larger than the
voltage channel's 25 mV / 24 V = 0.10 %. Unless R1's current readback offset
is well below 0.1 mA (*to be transcribed*), **the DP821A current readback
dominates efficiency uncertainty at the light-load points and dominates input
power at enabled-no-load**; output current is the second candidate; the two
voltage channels are minor. The 11 mA load-readback artifact (Gap B) would, if
it applied to loaded readings, be a 11 % term at 0.1 A and would dominate
everything; its exclusion must therefore be justified before the light-load
budget means anything.

Single-term illustration using the one transcribed value, **conditional on
its confirmation as a readback term**: a limit of 0.1 % + 25 mV at Vin =
24.006 V gives a half-width of 0.0490 V (0.204 %), standard 0.118 %; at
Vin = 12.0089 V, 0.0370 V (0.308 %), standard 0.178 %; at Vin = 9.1077 V,
0.0341 V (0.374 %), standard 0.216 %. At the pilot's η = 72.95 % the Vin term
alone contributes about 2 × 72.95 × 0.00118 ≈ **0.17 percentage points** to a
k = 2 expanded interval. This is one term of four and is *not* a budget.

### Budget template (terms marked unknown until entered)

| Channel | Reading range used | Read % term p | Offset / FS term c | Conditions | Source | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Vin (DP821A CH1) | 9.1–35.8 V | 0.1 % (to be confirmed as readback) | 25 mV (to be confirmed) | to be transcribed | R1 page 5 (per voltage-efficiency-test.md) | to be confirmed |
| Iin (DP821A CH1) | 0.0013–0.9873 A | unknown | unknown | unknown | to be transcribed from R1, page … | unknown |
| Vout (DL3031A, local sense) | 6.4–12.15 V | unknown | unknown | unknown | to be transcribed from R4, page … | unknown |
| Iout (DL3031A, `RANG MIN`) | 0–2.50 A | unknown | unknown | unknown; range identity unknown | to be transcribed from R4, page … | unknown |
| Calibration interval, both | — | — | — | no certificate on file | owner | unknown |
| Temperature coefficient, both | — | — | — | ambient not measured | R1/R4 | unknown |
| Wiring boundary | — | — | — | path, not module terminals; not an uncertainty term but a definition | run.json `measurement_boundary` | declared |

### Procedure

Software-only, after Gap B step 1: enter the terms in the bench profile; the
analysis computes `u_rel` per channel per point, `u_c`, U (k = 2, labelled
"k = 2, coverage not claimed as 95 %"), loss uncertainty in W, and the
near-zero check (flag points where c_Iin/Īin > a declared fraction, for
example 10 %, as "insufficient resolution"); unknown terms keep the whole
budget `unquantified`. Bench time: none beyond Gap B. Owner decision: the
declared k and the near-zero flag threshold.

## 5. Gap D — physical load capability

### What "qualified" means

The DL3031A's physical ratings and operating limits (voltage, current, power,
minimum operating voltage in CC, CC ranges and their thresholds, any derating)
transcribed from R4 with page references and checked against the unit's label,
firmware and any modification; the wiring's rating (lead gauge, length,
connectors) and the sense arrangement recorded; the bench profile's
`load.*` fields set from those sources and `capabilities_confirmed` made true
by evidence rather than assertion. Brief §3.2: "a changed identity string is
not evidence of a higher certified rating"; §17 "usable ratings and ranges".

### Evidence that exists now

- Identity from `*IDN?` in every run: `RIGOL TECHNOLOGIES,DL3031A,
  (load serial: private inventory),00.01.04.00.05`. No label photo, no modification record.
- The bench profile declares `max_current_A 2.55`, `max_voltage_V 15.0`,
  `max_power_W 34.0`, `min_voltage_V 0.15`, `mode CC`,
  `remote_sense_supported true`, `remote_sense_required false`,
  `capabilities_confirmed true`, `physical_model null`. These are
  purpose-limits chosen for the envelope
  ([configured-runs.md](configured-runs.md#current-physical-envelope)), not
  transcribed ratings; the "confirmed" flag is presently an assertion.
- Demonstrated operation (observations, not ratings): 2.4993 A at 11.904 V,
  29.75 W (eb3bcd `p0035`); 1.7247 A at 11.886 V (75a478 `p0066`); minimum
  loaded voltage observed 6.384 V at 0.0567 A during the e0fab9 collapse.
- Sense: `:SOUR:SENS? → 0` (local) in every run; the brief's target
  arrangement (S+/S− at the DUT output, R3 page 2-85) is not wired. All Vout
  values are load-terminal, so output-lead drop is inside the "path"
  boundary.
- Source side, for completeness: DP821A CH1 0–60 V / 0–1 A per R1/R2 (already
  in brief §3.2); bench profile caps it at 35.8 V / 1.0 A; no CH1 remote sense.

### Procedure

Software-only: transcribe DL3031A ratings (*R4, page …*) — voltage, current,
power, minimum CC operating voltage, CC range boundaries and which one
`RANG MIN` selects, slew-rate range for `SLEW MIN` — into `load.*`, set
`physical_model` from the label, add the wiring description (gauge, length,
connector type, pigtail boundary) to the bench profile notes, and keep the
purpose-limits as a separate `protective_controls` layer. Bench, **no
energizing**: photograph the load's label and rear panel, measure and record
lead lengths and gauge, confirm the S+/S− terminals are unconnected (as
`SENS? → 0` implies), and, if the owner wants the module-terminal boundary,
plan the remote-sense rewiring per R3 as a separate approved change (it alters
every subsequent Vout and must not be mixed silently with local-sense runs).
Pass condition: `load.*` populated from R4 and the label; `capabilities_confirmed`
justified by those entries; wiring recorded.

## 6. Gap E — qualified enabled-no-load measurement

### What "qualified" means

Brief §9.1: the quantity is "**enabled, no-external-load board/path input
consumption**" — Pin with the converter energized and regulating and the load
input OFF — not quiescent current, not switching loss, and with efficiency
shown as *not applicable* (DATA-06). Brief §6.4: until measured, "record that
its input draw is not established". To be qualified it must meet the same
acquisition rules as a loaded point: a declared no-load stage after the
startup criterion, dwell, ≥ 8 s and ≥ 5 complete cycles, CV brackets, a
stability criterion on **Iin** (there is no Iout to stabilise) and on Vout,
the load state recorded as OFF (and *which* OFF: input disabled, as opposed to
CC 0 A, which is a different condition), the residual/offset readbacks
explained, and the Gap B/C terms available so that Pin carries an uncertainty
or an explicit "unquantified".

### Evidence that exists now, and why none of it qualifies

| Observation | Values | Why it is not a qualified enabled-no-load point |
| --- | --- | --- |
| Off-state readbacks (both outputs OFF) | Vout 0.0017–0.2956 V, Vin 0.000 V | Converter not energized; these are residual/stale readings by definition (the events say so) |
| `runs/load-disabled-diagnostic.json` | source ON 24.006 V, Iin **0.0156 A**, Vout 12.14235 V, Iout 0.0, load OFF | One snapshot; no cycles, no dwell, no CV bracket, no timing, no integrity manifest; explicitly a diagnostic |
| Source-only startup cycles, 24 V | eb3bcd `c000002`–`c000005`: Iin 0.0158–0.0163 A, Vout 12.1453–12.1460 V (~3.5 s); 7a0fd6 `c000002`–`c000005`: 0.0158–0.0164 A | Phase `starting`, excluded by design; 4 cycles over 3.5 s, below the 8 s / 5-cycle rule; no settling dwell after the output reached 12.14 V; three of the four eb3bcd cycles carry the 11 mA Iout artifact |
| Source-only startup cycles, 15 V | b44da1 `c000004`–`c000008`: Iin 0.0250–0.0253 A, Vout 12.1447–12.1457 V, 4.83 s span, 0.921 mV spread | Closest to qualified: 5 cycles, CV brackets, Vout stability gate met — but only 4.8 s, no Iin stability criterion declared, phase `starting`, and the procedure's declared purpose was a startup gate |
| Source-only startup cycles, 35.8 V | eb3bcd `c000177`–`c000180`: Iin 0.0166–0.0175 A | Same as 24 V; first cycle still rising (11.54 V) |
| 12 V attempt | e0fab9 `c000001`–`c000005`: Iin 0.0013–0.4809 A, Vout ≤ 8.12 V | Converter never regulated; not a no-load operating point at all |

Two further reasons apply to all of them: the analysis code does not produce a
no-load point ("No-load … not implemented in this workflow",
[configured-runs.md](configured-runs.md)), and with Iin at 16–25 mA any
unknown current-offset term is a large fraction of the reading (Gap C
near-zero check), so a qualified value also needs the Gap B/C terms.

### What a qualified enabled-no-load point requires

1. A declared no-load stage in the procedure: after the startup criterion is
   met with the load input OFF, dwell ≥ 5 s, then acquire ≥ 8 s and ≥ 5 cycles
   with CV brackets, Vout span ≤ 50 mV and a declared Iin span criterion
   (owner to declare; the observed spreads above are 0.3–0.6 mA).
2. Load state recorded as `input OFF` with `:SOUR:INP:STAT? → 0` in every cycle;
   Iout recorded but reported as "load input OFF; readback offset see Gap B",
   never used as Pout; efficiency marked not applicable.
3. Pin = V̄in · Īin with the Gap C budget or the explicit `unquantified`.
4. Reported as "enabled, no-external-load path input consumption at the source
   terminals", with the startup history (which input voltage, cold start) and
   the boundary. The residual output voltage before enable and the ambient
   temperature (or "not measured") accompany it.
5. Software support: a procedure stage and analysis path for `Iout` absent
   points (DATA-06 already covers the presentation rules); tests with fake SCPI
   first.

The natural first physical instance is at **24 V**, where the converter has
started in four runs and the startup phase already showed 15.8–16.4 mA. It
can be combined with the cold-start bracketing plan
([cold-start-hypothesis.md §5](cold-start-hypothesis.md)) — every successful
unloaded start in that plan yields a candidate no-load window if the stage in
item 1 is added — but the 24 V point should come first because it does not
depend on the unresolved 12 V behaviour.

## 7. Bench time versus software-only

| Item | Software-only (no authorization) | Bench without DUT (owner authorization; no DUT risk) | Bench with DUT (owner authorization; energizes the converter) |
| --- | --- | --- | --- |
| A. Freshness | Log analysis of repeated values; R1/R4 search | Burst and step tests source→load; CVCC latency if approved | — |
| B. Readback accuracy | Transcribe R1/R4 with pages; enter ranges; log analysis of the 11 mA artifact; record calibration status | DMM plausibility check at 3 points; zero/offset check with load input OFF | — |
| C. Uncertainty | Enter terms; compute per point; near-zero flag; k declared | — | — |
| D. Load capability | Transcribe R4 ratings; label/wiring entries; separate purpose-limits from ratings | Label photo, lead measurement, sense-terminal check (no energizing) | Remote-sense rewiring later, as a separate approved change |
| E. Enabled-no-load | Procedure stage + analysis path + fake-SCPI tests | — | First qualified point at 24 V; then as a by-product of each successful cold start in the bracketing plan |
| Prerequisite fix | Confirm the startup gate (no load enable below 10.8 V) is the code that runs | — | — |

## 8. Proposed order

1. **Software-only, documentation**: transcribe R1 and R4 terms and ratings
   with page references into the bench profile (B, D); re-check the existing
   ±(0.1 % + 25 mV) transcription as programming vs readback; record
   calibration status as unknown; make `capabilities_confirmed` follow from the
   entries. No hardware.
2. **Software-only, log analysis**: the 11 mA load-readback artifact and the
   repeated-value cadence from existing `scpi.jsonl` files (A, B). No hardware.
3. **Software-only, code**: uncertainty terms → per-point budget with
   `unquantified` fall-through (C); enabled-no-load stage and analysis path
   with fake-SCPI tests (E); confirm the startup gate (Section 1 prerequisite).
   No hardware.
4. **Bench, no DUT** (owner authorization): freshness burst/step tests, DMM
   plausibility check, zero/offset check, label photo and wiring record
   (A, B, D). The converter stays disconnected.
5. **Bench, DUT at 24 V** (owner authorization): one qualified enabled-no-load
   window at 24 V, then one loaded 0.1 A point in the same run to compare with
   the pilot (E, and a first end-to-end check of the budget from step 3).
6. **Bench, DUT, cold-start bracketing** per
   [cold-start-hypothesis.md §5](cold-start-hypothesis.md): separate proposal
   and approval; yields additional no-load windows at each successful start
   voltage.

Only after steps 1–5 does the metrology gate close; step 6 addresses item 2 of
the bounded task and is not a prerequisite for M2 but is a prerequisite for any
12 V condition in M3.

## 9. What this plan does not establish

- Any specification value, calibration state, refresh rate or rating of either
  instrument; all are marked to be transcribed or unknown.
- That the 11 mA load-readback artifact is harmless; it is unexplained.
- That the existing light-load points (0.1 A, 0.05 A) will survive an
  evaluated budget with a useful uncertainty; the dominance argument above
  says they are the most exposed.
- Converter-terminal efficiency; every existing and planned value is at the
  source and load terminals with local sense until the remote-sense change is
  approved.
- Authorization for any bench step; steps 4–6 require the owner's approval and
  approved profiles.

## 10. Evidence index

| Evidence | Path |
| --- | --- |
| Bench profile with null accuracy fields | `workspace/profiles/bench/rigol-local-limited.json` |
| Unquantified uncertainty record | `runs/real-startup-descent/20260927T212200.072951Z_real_b44da1/analysis/a-64db20585452/uncertainty.json` |
| Sample annotation and per-query timing | `raw/samples.jsonl` in every run (`acquisition_settings.adc_freshness`, `query_start/end_monotonic_s`) |
| Load-disabled snapshot | `runs/load-disabled-diagnostic.json` |
| Source-only startup cycles at 15 / 24 / 35.8 V | `runs/real-startup-descent/…_b44da1`, `runs/real-voltage-sweep/…_eb3bcd`, `runs/real-extended/…_7a0fd6` |
| 11 mA off-state readbacks | same runs plus `runs/real-bringup/20260927T055903.309087Z_real_78961c` and `runs/real-voltage-sweep/…_e0fab9` |
| Highest demonstrated load points | `runs/real-voltage-sweep/…_eb3bcd` `p0035`; `runs/real-source-limit/…_75a478` `p0066` |
| Load programming (`RANG MIN`, `SLEW MIN`) | `src/dcdc_bench/bringup.py` `apply_load_cc_limits`; every `scpi.jsonl` |
| Transcribed voltage term | `docs/voltage-efficiency-test.md` (R1 printed page 5) |
| Requirement IDs UNC-01…04, DATA-04, DATA-06 | `docs/acceptance.md`; `docs/implementation-brief.md` §14.2 |
