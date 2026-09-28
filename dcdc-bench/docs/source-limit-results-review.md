# Independent results review: approaching the supply's 1 A input limit

Run: `20260927T173043.388477Z_real_75a478`  
Official analysis: `a-d0697ec66a0e`  
Review date: 2026-09-27 UTC

## Verdict

**The recorded acquisition and numerical analysis pass this independent evidence audit.** The test reached **0.9873 A measured supply current** with the supply set to 24 V and a 1.000 A current limit. It delivered **1.7247 A at 11.8857 V** to the electronic load. The supply remained in constant-voltage operation, and source output, load input and the source deadline were all verified OFF at completion.

This verifies the observed operating points and their calculations. It does not certify the converter's full 4 A rating, absolute measurement accuracy, thermal equilibrium or compliance with a product specification.

## What actually ran

The load requests were 100 mA through 1.6 A in 100 mA steps, then 1.625, 1.650, 1.675, 1.700 and 1.725 A in 25 mA steps. The final request returned directly to 100 mA. That is 21 increasing-load points and one separate return point. There was no descending sweep or separate long hold in this run.

At 1.725 A requested output, the first nine accepted cycles gave 0.9873556 A mean input current, exceeding the 0.98 A stopping target. The same uninterrupted acquisition was extended to a nominal 30 seconds, producing 26 accepted cycles. The final input-current mean was 0.9872846 A. No higher load was commanded and no boundary recovery was needed.

The endpoint acquisition loop lasted **30.7488 s**; the interval from its first accepted query start to its last accepted query end was **29.6220 s**. Those are different timing definitions. The complete run lasted **405.8771 s**, approximately 6 minutes 46 seconds.

## Independently recomputed endpoint

| Quantity | Result |
| --- | ---: |
| Requested load current | 1.725 A |
| Supply-terminal voltage | 24.0040 V |
| Supply current | 0.9872846 A |
| Load-terminal voltage | 11.8856578 V |
| Load current | 1.7247275 A |
| Input power | 23.6987799 W |
| Output power | 20.4995209 W |
| Path power loss | 3.1992590 W |
| Terminal-to-terminal path efficiency | 86.5003% |

These values use the mean of each measured channel over accepted complete cycles. Input and output powers are products of the respective channel means; efficiency is 100 times their ratio. Displayed digits support reproducing the calculations and do not imply equivalent absolute accuracy.

The largest individual input-current readback anywhere in the run was **0.9874 A**. The highest numerical efficiency mean was **86.5042%** at the 1.700 A request. Its difference from the final point is only about 0.004 percentage points; with unquantified uncertainty, that does not establish a meaningful efficiency advantage.

Qualified mean output voltage ranged from **12.1319549 V** initially to **11.8856578 V** at maximum load, a 246.30 mV reduction at the load terminals. The final 100 mA point was 2.40 mV below the initial 100 mA point. Wiring is included in these measurements, so the reduction cannot be assigned wholly to converter regulation, and the return difference does not establish hysteresis or a significant thermal change.

## Evidence checks

- All eight SHA-256 hashes in the finalized acquisition manifest match. They were checked again after the audit.
- All 1,332 raw readings form 333 complete cycles of exactly four distinct quantities: input voltage/current and output voltage/current.
- All 333 cycles match the corresponding raw SCPI values. Each quartet is bracketed by source CV readbacks: 666 CV responses in total, with no recorded source CC response.
- The 213 accepted cycles contain 852 readings across 22 qualified points. Startup and settling readings were excluded from the qualified means.
- Every accepted cycle has matching point/test identities, the correct requested load, an enabled load, good sample status and finite values. Qualified readbacks satisfy the configured current, voltage and acquisition-span guards.
- The longest accepted four-query span was **79.50 ms**, below the 750 ms acquisition-span limit.
- The command log, change events and explicit execution order agree. The 56 unused conditional candidates were never commanded and are retained as unused candidates, not interpreted as failed measurements.
- All 50 instrument error-queue queries returned no error. All 666 load condition-register queries returned zero.
- The recorded endpoint trigger, its initial cycle membership, the final contiguous endpoint window and the final endpoint means match independent recomputation.
- All four channel means, both powers, loss and efficiency for every qualified point match official analysis `a-d0697ec66a0e`, as do accepted cycle memberships and point coverage.
- Final SCPI readbacks independently support the recorded OFF states for source output, load input and source deadline.

## Interpretation limits

This is a source-to-load terminal measurement, including input and output wiring losses. Calibration, measurement uncertainty and instrument ADC freshness were not independently established. Sequential SCPI queries are not simultaneous waveform measurements. No temperature sensor was present, and the short endpoint observation does not establish thermal equilibrium.

The source stayed in CV and the current target stopped the search before CC. Consequently, this run establishes a useful operating point near the supply's current setting; it does not determine the exact source CC transition, the converter's overload limit or operation at 4 A output. Ripple, switching transients, line regulation and no-load power were not evaluated by these qualified loaded points.

## Reproducible audit artifacts

Within the run folder, `reviews/independent_results_audit.py` performs the audit using only the Python standard library. It reads acquisition files and the official analysis; it never opens hardware or rewrites finalized acquisition evidence. Its results, individual assertions, verified hashes and all independently recomputed point values are in `reviews/independent-results-audit.json`.

The review artifacts are outside the acquisition integrity scope. No browser or report-rendering process was used for this results audit.
