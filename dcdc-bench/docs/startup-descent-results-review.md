# Agent-role review: start at 15 V, then reduce input without restarting

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Run: `20260927T212200.072951Z_real_b44da1`  
Analysis: `a-64db20585452`  
Reviewed: 2026-09-27 UTC

## Finding

**The converter continued producing approximately 12.13 V while the input was reduced from 15 V to near 9 V, with a 100 mA load request.** At the lowest qualified condition, measured source-terminal input was **9.1077 V** and load-terminal output was **12.1341 V at 99.53 mA**.

The experiment completed all seven planned conditions in 135.47 seconds, with no recorded errors. The source, electronic load and source deadline were all verified OFF afterward. The source remained in CV at every recorded measurement bracket.

This reproduces the user's observation under this startup history and light load. It does not establish the cold-start threshold, UVLO hysteresis, operation at exactly 9.000 V at the DUT pins, or full-load capability.

## Sequence and startup evidence

The source was configured for 15 V with a 1.000 A current limit, 1.05 A OCP and 16 V OVP. The load stayed OFF while the worker observed startup. The first three recorded output-voltage readings were 0.0051 V, 7.1206 V and 7.9514 V. Five subsequent consecutive readings were between 12.1447 V and 12.1457 V, spanning 4.828 seconds with only 0.921 mV spread.

The unloaded stability gate completed after **9.765 seconds of observation**. This interval includes the five-reading stability check and polling overhead; it is not a measured electrical startup-delay specification. Only after those stable readings did the load turn ON at 100 mA.

The source and load then remained continuously enabled while source voltage was set to 15, 14, 13, 12, 11, 10 and **9.1 V**. The last condition is labelled *near 9 V*: the 0.1 V programming margin and a 9.03 V source-terminal readback guard were explicit parts of the procedure. Lead losses and absolute voltage uncertainty remain unquantified.

Each transition was observed separately, then followed by five settling cycles and an acquisition window of at least eight seconds and five complete cycles. Transition readings were retained but never included in the qualified means.

## Independently recomputed results

| Programmed input | Measured input | Measured output | Measured output current | Path efficiency |
| --- | ---: | ---: | ---: | ---: |
| 15 V | 15.0054 V | 12.1350 V | 99.17 mA | 71.97% |
| 14 V | 14.0039 V | 12.1347 V | 99.28 mA | 72.02% |
| 13 V | 13.0080 V | 12.1345 V | 99.44 mA | 71.96% |
| 12 V | 12.0089 V | 12.1343 V | 99.47 mA | 72.12% |
| 11 V | 10.9990 V | 12.1342 V | 99.52 mA | 72.66% |
| 10 V | 10.0060 V | 12.1342 V | 99.55 mA | 73.51% |
| 9.1 V | 9.1077 V | 12.1341 V | 99.53 mA | 74.05% |

At the lowest input condition, measured input current was **0.17907 A**, calculated input power was **1.63093 W**, output power was **1.20766 W**, and terminal-to-terminal path loss was **0.42327 W**. Power uses the product of qualified channel means; path efficiency is output power divided by input power. Wiring losses are included.

The qualified output means varied by only about 0.91 mV across the descent. With unquantified measurement uncertainty and no temperature measurement, that small observed difference should not be described as a precise regulation specification or a statistically established change.

## Agent-role evidence checks

- All finalized acquisition hashes match and remain unchanged after auditing.
- The 424 raw readings form 106 complete four-channel cycles. Every value matches its timestamp-associated SCPI response.
- Every cycle has distinct source-mode queries before and after it: 212 measurement-bracketing CV responses. Six additional CV checks precede the six live voltage changes.
- The 48 accepted cycles across seven qualified points have correct identities, good sample status, finite values, CV source status and an enabled 100 mA requested load.
- Accepted cycles meet the configured voltage/current guards, minimum cycle counts, acquisition duration and output stability checks. The longest accepted four-query span was 74.08 ms, below the 750 ms limit.
- Startup and transition cycle IDs are disjoint from accepted acquisition IDs. The load-enable command follows the final stable unloaded reading.
- The actual voltage command sequence matches the fixed descent, with one continuously active source deadline and no intermediate source/load OFF command before the final qualified observation.
- All seven official sets of channel means, calculated powers, loss, efficiency and accepted cycle membership match independent recomputation.
- Final SCPI readbacks support source OFF, load OFF and deadline OFF; instrument error queues and load condition registers show no recorded fault.

## Relation to the earlier 12 V startup attempt

The earlier cold 12 V attempt (`20260927T184902.863440Z_real_e0fab9`) stopped without qualified results. This new run establishes that the already-started converter operated at a measured 12.0089 V input and continued down to a measured 9.1077 V input at this light load.

Those are different startup histories. The observations support investigating startup behavior separately from continued operation. They do not identify the cause of the earlier failed startup; inrush, source current limiting and the converter's internal startup behavior have not been distinguished by these sequential DC readings.

## Reproducibility and limits

The run's `reviews/independent_startup_descent_audit.py` uses only the Python standard library and performs no hardware access. Its checks, verified hashes and full-precision recomputed point results are in `reviews/independent-startup-descent-audit.json`. Review files are outside the immutable acquisition integrity scope.

Calibration, uncertainty and ADC freshness are unquantified. Sequential SCPI readings do not resolve electrical transients, switching ripple or exact startup timing. No temperature was measured. The report should describe observed continued operation at light load, with the startup history and near-9 V programming margin visible.

## Issued reports

[Interactive HTML](http://localhost:8081/Runs/12t12-startup/report.html) and
[PDF](http://localhost:8081/Runs/12t12-startup/report.pdf) serve revision `r0005`.
Presentation revisions keep the DUT section and the method/shutdown table
together in the PDF. Acquisition evidence and analysis `a-64db20585452` remain
unchanged; build manifests retain the revision chain and artifact hashes.

Revision `r0005` adds engineering figure labels, the shared curve styles and a
nominal output-voltage reference. The saved analysis and numeric results are unchanged.
