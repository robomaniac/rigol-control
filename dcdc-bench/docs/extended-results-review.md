# Independent results review: 12T12-4A extended test

**Verdict:** the completed run supports a guarded, partial-power DC
characterization at 24 V input and 50–500 mA requested output current. Its
accepted results reproduce from the preserved raw readings. This is not a
full-rating, thermal, transient, or calibrated-efficiency qualification.

## Evidence reviewed

- Run: `20260927T093948.075493Z_real_42e971`.
- Acquisition: **2026-09-27 09:39:48–09:48:11 UTC**, 503.537 seconds including
  preflight, startup, measurement, and shutdown.
- Local evidence: `runs/real-extended/20260927T093948.075493Z_real_42e971/`.
- Analysis: `a-4a0763ae9add`, formula version `settled-dc-1.1`.
- Method: source CH1 at 24 V, increasing load from 50 to 500 mA, a continuous
  hold at 500 mA, then decreasing load from 450 to 50 mA.
- Scope: **37 observation windows across 10 distinct requested currents**;
  10 increasing-load windows, 18 hold windows, and 9 decreasing-load windows.

An independent Python standard-library calculation read the finalized JSON
and JSONL files directly. It did not invoke the production analysis functions,
open an instrument, alter acquisition evidence, or rerun the test.

## Integrity and measurement qualification

| Check | Result |
| --- | --- |
| Acquisition SHA-256 manifest | All 8 covered files match, including the SCPI transcript |
| Plan identity | Stored plan and run hashes agree; schema-normalized plan contents reproduce that hash |
| Raw evidence | 1,744 readings in 436 complete four-channel cycles |
| Accepted evidence | 1,324 readings in 331 complete cycles; 8–9 accepted cycles per window |
| Other retained evidence | 380 settling readings and 40 startup readings; excluded from point means |
| Acquisition duration per window | 10.092–10.788 s; every window meets the 10 s minimum |
| New-load settling duration | 5.587–6.016 s; repeated hold windows inherit the preceding settled condition |
| Maximum accepted four-query span | 80.240 ms, below the 750 ms limit |
| Maximum span across all recorded cycles | 84.934 ms |
| Readback guards | No input/output voltage, current, requested-load, CV-mode, or load-status violation |
| Voltage stability | Every acquired window meets the 50 mV span criterion; all newly settled load points meet it too |
| SCPI transcript | No recorded transport error or nonzero instrument error response |
| Execution | Completed; no recorded errors |
| Shutdown | Source, load, and independent deadline program each read back OFF |

The four channels are queried sequentially. These spans describe query timing,
not simultaneous sampling or independently verified ADC freshness. Every raw
numerical value agrees with its retained SCPI response.

The independent plan-hash check normalized two schema-declared float defaults
from JSON integer `0` to `0.0`: `auxiliary_input_power_estimate_W` and
`input_wiring_drop_allowance_V`. The file manifest hashes the exact stored bytes;
the plan hash uses schema-normalized JSON. Neither check required changing the
saved evidence.

## Independently recomputed results

For each qualified window, channel means were formed from its accepted complete
cycles, then calculated as:

`Pin = mean(Vin) × mean(Iin)`  
`Pout = mean(Vout) × mean(Iout)`  
`path loss = Pin − Pout`  
`path efficiency = 100 × Pout / Pin`

These are settled DC calculations, not waveform-based instantaneous power.
All 37 production-analysis channel means and derived power, efficiency, and
nominal-voltage-error values matched the independent calculations exactly at
the stored numerical precision.

| Observation | Result |
| --- | --- |
| Window-mean input voltage | 24.003–24.005 V |
| Window-mean input current | 38.800–298.467 mA |
| Window-mean output voltage | **12.07993–12.13868 V** |
| Window-mean output current | 49.932–499.441 mA |
| Observed path efficiency | **65.06–84.25%** |
| Highest observed path efficiency | 84.2455%, final 500 mA hold window `p0028` |
| Maximum observed output power | **6.03362 W** |
| Observed path loss | 0.32323–1.13158 W |
| Increasing-load voltage span | 0.48214% of 12 V nominal, across 50–500 mA requested |
| Decreasing-load voltage span | 0.42294% of 12 V nominal, across 450–50 mA requested |

The increasing and decreasing spans cover different endpoint ranges; their
difference is not a direct measure of hysteresis. “Highest observed” selects
the largest recorded ratio and does not establish a statistically distinct
optimum.

### Sustained load and return to the starting current

The eighteen 500 mA hold windows span **185.667 s** of continuous acquisition.
Their first and last voltage means were **12.080769 V** and **12.079928 V**:
an observed change of **−0.841 mV** over **175.454 s between accepted-query
midpoints**. The observation duration and the midpoint-comparison interval are
different quantities.

At the starting and final 50 mA requested load, mean output voltage changed
from **12.138676 V** to **12.136928 V**, or **−1.748 mV**. Actual mean output
currents were **49.932 mA** and **50.103 mA**, respectively. This comparison
matches the requested condition; the measured currents and input voltages
were not identical.

The return-path means were 1.002–1.748 mV below the increasing-load means at
the nine shared requested currents. These small signed differences are useful
observations for follow-up testing. With uncertainty and temperature
unquantified, they are not evidence of statistically significant drift,
hysteresis, or a temperature coefficient.

## Interpretation limits

- The measurement boundary runs from **supply terminals to load terminals**.
  Input and output lead losses are included. Reported path loss cannot be
  identified entirely as converter heat.
- Electrical stop limits were satisfied. No manufacturer acceptance limits
  were supplied, so output-voltage accuracy and efficiency requirements remain
  **not evaluated**, rather than pass/fail.
- Displayed digits preserve readable observations; they do not establish
  instrument accuracy, calibration validity, ADC independence, or uncertainty.
- No temperature was measured. A three-minute hold does not establish thermal
  equilibrium or thermal capability.
- Only one input voltage and about 6 W output were tested. The owner-provided
  48 W rating, line regulation, no-load consumption, ripple, transients,
  isolation, and protection thresholds were not qualified.
- The earlier attempt `20260927T093111.072469Z_real_7a0fd6` stopped at its query
  timing guard and remains preserved separately. Its partial measurements were
  not combined with this completed run. Moving durable cycle writes outside
  the four-query sequence reduced host-side timing interference while keeping
  the 750 ms qualification limit unchanged.

## Report consistency

The final `reports/r0005/report_model.json` model was independently checked
against the previously reviewed raw-data calculation and report model:

- All 37 point means, derived results, accepted-cycle counts, and plotted
  elapsed-time coordinates match.
- All five summary metrics match, including their signed hold and return
  voltage differences. Their referenced evidence points and conditions agree.
- Coverage is correctly reported as 10 increasing-load, 18 hold, and 9
  decreasing-load windows, all qualified.
- The summary distinguishes 37 observation windows from 10 distinct requested
  conditions. The recorded 185.667 s hold duration, inherited settling, actual
  midpoint-comparison intervals, and verified shutdown states are carried into
  the report model.
- All 18 hold-window flags for inherited settling match the finalized
  acquisition. The other 19 windows have new-load settling durations of
  5.587–6.016 s; excluding inherited hold intervals from this range correctly
  describes the procedure. The final method presentation expresses query skew
  in milliseconds; this does not change its numerical value or qualification.
- Measurement uncertainty remains unquantified; unset requirements remain not
  evaluated. The summary makes no thermal-equilibrium, hysteresis,
  statistical-significance, or rated-power claim.

The final revision preserves all previously reviewed point values, metrics,
figures, raw evidence, summary claims, coverage, and shutdown states unchanged.
An entire-model comparison with r0003 found exactly one changed field:
`report_revision`. The r0004 presentation adjustment changes no result or
measurement-method evidence.

**Results review complete for r0005:** no unresolved numerical or
measurement-claim finding for this report model. Rendering, layout, and
interactive behavior are covered by the separate report UI/UX review.

### Follow-up: compact tooltip presentation in r0005

An independent entire-model comparison of r0005 against r0004 found exactly
one changed field: `report_revision`. All **37 observation windows**, **five
summary metrics**, and **1,744 raw readings** remain identical, together with
their timing, qualifications, conditions, references, and uncertainty statements.
Display rounding and moving details from the hover tooltip into the point
inspector do not change the preserved measurement evidence. This follow-up
checked the report model; tooltip behavior and detail visibility require the
separate UI/UX check.
