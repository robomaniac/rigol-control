# Configured workflow: agent-role results review

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

**Result: PASS.** The configured real run completed all three requested points
in **57.382 seconds**, with the power-supply output, electronic-load input, and
source shutdown timer subsequently verified **OFF**. No acquisition errors,
source CC responses, protection-trip responses, or load fault responses were
recorded.

- Job: `20260927T223820Z_bb4a479f`
- Run: `20260927T223823.159616Z_real_0038ff`
- Acquisition: 27 September 2026, 22:38:23–22:39:20 UTC
- Converter: **12T12-4A**; instruments: **DP821A CH1 / DL3031A**, local load sensing
- Official analysis compared: `a-3ec7d2d11a54`

## Recomputed measurements

The source was programmed to 24 V. Its accepted mean voltage was **24.006 V**
at all three points. Values below were independently recalculated from the
accepted raw acquisition cycles; startup and settling readings were excluded.

| Requested load | Measured load | Input current | Output voltage | Input power | Output power | Path efficiency | Accepted cycles |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.10 A | 0.09948 A | 0.06921 A | 12.13437 V | 1.66152 W | 1.20713 W | 72.65% | 8 |
| 0.25 A | 0.24924 A | 0.15900 A | 12.11738 V | 3.81695 W | 3.02014 W | 79.12% | 7 |
| 0.50 A | 0.49939 A | 0.29873 A | 12.08899 V | 7.17119 W | 6.03711 W | 84.19% | 8 |

Power uses the product of the accepted mean voltage and mean current, matching
the documented analysis calculation. Path losses were respectively
**0.45438 W, 0.79682 W, and 1.13408 W**. All means, powers, losses, and efficiencies
match the official analysis to the audit's numerical tolerance.

## Evidence checked

- All **eight finalized acquisition SHA-256 hashes** match the integrity
  manifest. The canonical plan hash is valid; preview, detached-job plan, and
  acquired plan are identical. The saved inventory fingerprint and operator
  confirmation remain bound to that plan.
- Recorded instrument identity responses match the confirmed source/load
  identities. The command order is one 24 V source setting, then
  **0.10 → 0.25 → 0.50 A** load settings.
- Readbacks confirm the **1 A source current setting**, **26 V source OVP**,
  **1.05 A source OCP**, enabled source protection, and **720 s shutdown timer**.
  Recorded load limit values are **13.2 V / 2.55 A**; the software output-voltage
  guard is **10.8–13.2 V**. These settings do not establish fast transient
  protection performance.
- **192 raw readings form 48 complete four-channel cycles**: 10 startup,
  15 settling, and 23 accepted acquisition cycles. Every raw value matches its
  timed SCPI response. Accepted cycles are unique, loaded, and correctly
  associated with their requested point.
- All **96 source-mode readbacks are CV**, including the queries before and
  after every accepted cycle. Each point meets the saved acquisition duration,
  cycle-count, settling, voltage-span, and query-skew criteria. The largest
  accepted four-channel query span is **80.35 ms**, below the 750 ms limit.
- Final raw queries independently confirm source **OFF**, load **OFF**, and
  source timer **OFF**, consistent with the finalized run and shutdown event.

## Scope and audit artifacts

This was a short acceptance run of the configured workflow, not another
source-limit sweep or a test of the converter's full 4 A rating. Results include
input/output wiring losses. Calibration uncertainty, ADC freshness, temperature,
and thermal equilibrium remain unquantified.

The coordinating agent exercised the UI callbacks and disconnected the client;
this agent-role review separately checks the resulting acquisition evidence. Browser
disconnect timing and report appearance require their separate acceptance
evidence. Automatic report rendering was still running during this audit.

The standard-library audit and machine-readable results are saved under the
run's `reviews/` directory as `independent_configured_workflow_audit.py` and
`independent-configured-workflow-audit.json`. No finalized acquisition files
were edited. No hardware queries, browser, rendering, or heavy tests were run
for this review.

## Report completion after the numerical audit

The job subsequently completed automatic HTML and PDF generation as report
revision `r0001`. Presentation revision `r0002` keeps the method and verified
shutdown table on one PDF page, without changing the measurements or analysis.
It is available as [interactive HTML](http://localhost:8081/Runs/12t12-workflow/report.html)
and [PDF](http://localhost:8081/Runs/12t12-workflow/report.pdf). The build manifest
records the source revision and artifact hashes. See the separate
[interface verification](bench-ui-verification.md) for UI coverage.

The current presentation revision is `r0003`, adding engineering labels, shared
curve styles and the nominal-voltage reference to that same saved analysis.
