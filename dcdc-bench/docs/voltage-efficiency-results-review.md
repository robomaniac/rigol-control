# Independent review: efficiency versus input voltage

Reviewed 2026-09-27 UTC.

- Measured continuation: `20260927T185631.575651Z_real_eb3bcd`
- Official analysis: `a-e2e7cc8e0d01`
- Retained 12 V startup attempt: `20260927T184902.863440Z_real_e0fab9`

## Verdict

**The recorded results and numerical analysis pass this independent evidence audit: 122 checks passed.** All 27 requested operating points in the 24 V / near-36 V continuation were qualified. The acquisition completed in **427.91 seconds** with no recorded errors. Source output, load input and the source deadline were verified OFF at completion.

There is **no qualified 12 V efficiency curve**. The earlier 12 V startup stopped when measured input voltage collapsed and input current reached the configured source boundary. That evidence is preserved separately and must not be interpreted as a steady-state efficiency measurement or proof that the converter cannot operate from a suitable 12 V source.

## The useful comparison: the same 0.5 A load request

| Measured quantity | 24 V condition | Near-36 V condition |
| --- | ---: | ---: |
| Programmed supply voltage | 24.0 V | 35.8 V |
| Measured input voltage | 24.006 V | 35.797 V |
| Measured input current | 0.2987875 A | 0.2058750 A |
| Measured output voltage | 12.0983345 V | 12.0975488 V |
| Measured output current | 0.499403 A | 0.499448 A |
| Input power | 7.1726927 W | 7.3697074 W |
| Output power | 6.0419445 W | 6.0420965 W |
| Path power loss | 1.1307482 W | 1.3276108 W |
| Path efficiency | **84.2354%** | **81.9856%** |

At this matched load request, the observed path efficiency was **2.2498 percentage points higher at 24 V**. Output power was essentially the same, while measured input power was about 0.197 W higher near 36 V. These are observations from this run; the audit does not establish uncertainty bounds or statistical significance. Temperature was not measured, and the two voltage conditions were tested sequentially.

## Highest tested loads

| Result | 24 V condition | Near-36 V condition |
| --- | ---: | ---: |
| Qualified points | 13 | 14 |
| Highest requested output current | 1.725 A | 2.500 A |
| Measured input voltage | 24.00575 V | 35.79700 V |
| Measured input current | 0.987725 A | 0.9655714 A |
| Measured output voltage | 11.980737 V | 11.903798 V |
| Measured output current | 1.724669 A | 2.4993496 A |
| Input power | 23.7110794 W | 34.5645604 W |
| Output power | 20.6628057 W | 29.7517528 W |
| Path efficiency | 87.1441% | 86.0759% |
| Recorded reason for stopping | Mean input current reached the 0.98 A target | Declared load grid completed |

The near-36 V phase stopped at its planned **2.5 A output request**, with measured supply current below the 0.98 A target. It did not find the source current limit or the converter's maximum output current. Neither phase tested the converter at 4 A.

The largest individual input-current readbacks were 0.9878 A at 24 V and 0.9658 A near 36 V. All 718 source-mode checks in the continuation reported CV. The numerically highest near-36 V efficiency was 86.4746% at the 2.3 A output request; it fell to 86.0759% at 2.5 A. The 24 V phase's highest numerical efficiency was 87.1441% at its last point.

## What happened at 12 V

The retained startup attempt ended with these sequential readbacks:

| Quantity | Last startup cycle |
| --- | ---: |
| Input voltage | 2.661 V |
| Input current | 1.0005 A |
| Output voltage | 6.384208 V |
| Output current | 0.056747 A |

The source was programmed for 12 V with a 1.000 A current limit. Its last source-mode checks were **CV before and CV after** the quartet. Therefore, the defensible finding is an observed input-voltage collapse and current-boundary stop during startup; the log does **not** establish a recorded CC-mode indication. These startup readings are not a stable 12 V operating point and were excluded from efficiency calculations. No qualified point was recovered or fabricated from that attempt.

The continuation's reference identifies the prior run, verifies its integrity-manifest hash, and preserves the last startup readings. Its plan contains only the 27 new requests at nominal 24 V and nominal 36 V. The actual high-voltage programming was 35.8 V, and the corresponding measured input values remain labelled accurately.

## Evidence audit

- Verified every finalized acquisition SHA-256 entry for both runs, and verified both manifests again after recomputation.
- Matched all 1,436 continuation readings to 359 complete, ordered four-channel SCPI quartets. Every quartet has source-mode queries before and after it; all reported CV.
- Verified 204 accepted cycles, comprising 816 readings across 27 qualified points. The 540 settling readings and 80 startup readings were excluded from qualified averages.
- Verified unique sample identities, point/test identities, load enable state, requested current, finite values and good sample status.
- Verified at least five accepted cycles per qualified point, configured voltage/current guards, output-voltage stability within 50 mV and four-query spans within 750 ms. Acquisition loops lasted 8.0004–9.2550 seconds; these durations differ from the accepted-query spans recorded separately.
- Matched the actual load command order to all 27 executed plan points. There were no failed or unused conditional candidates in this continuation.
- Verified source/load/deadline OFF readbacks before voltage reprogramming, the two phase shutdown events, discharged-source transition checks, and only the authorized 24.0/35.8 V and 1.000 A source settings.
- Verified clear load condition registers and no recorded SCPI error-queue or transport errors.
- Independently recomputed all four channel means, input/output power, loss and efficiency for every qualified point. All match official analysis `a-e2e7cc8e0d01`, including accepted cycle memberships and complete point coverage.
- Verified final source, load and deadline OFF states against the SCPI log.

Root's separate read-only postflight at 19:04:12 UTC also recorded source OFF at 0 V / 0 A, timer and delayer OFF, and load OFF at 0 A with a clear condition register. Its residual load-terminal voltage was 0.29555 V. That postflight value is outside the measurement windows and is not included in efficiency calculations.

## What these results establish

The curves characterize measured DC operation at the source and load terminals over the tested ranges. Power is calculated from the product of qualified channel means, and efficiency is output power divided by input power. Wiring losses are included. Extra digits support reproducibility; they do not imply equivalent absolute accuracy.

Calibration, instrument uncertainty and ADC freshness remain unquantified. Sequential queries do not measure simultaneous switching waveforms. These short windows do not establish thermal equilibrium, and the test does not evaluate ripple, transients, the exact current-limit transition, the 9 V input endpoint or the full 4 A output rating.

## Reproduce the audit

The run's `reviews/independent_voltage_audit.py` uses only the Python standard library. It reads finalized acquisition files and the official analysis, opens no hardware and rewrites no acquisition evidence. Run it with the run-directory path and analysis ID `a-e2e7cc8e0d01`.

Its checks, both sets of verified hashes, point-by-point recomputation, 0.5 A comparison, endpoint results and exclusions are stored in `reviews/independent-voltage-results-audit.json`. The review files sit outside the finalized acquisition integrity scope.
