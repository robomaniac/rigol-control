# Source-current-limit test: independent code review

Reviewed 2026-09-27. **Verdict: no unresolved blocking issue found in the reviewed fixed procedure and report changes.** This review does not certify the converter's ratings or instrument accuracy.

## Scope

Source review covered `src/dcdc_bench/source_limit.py`, its shared lifecycle in `extended.py`, associated fake-instrument tests, and the source-search changes in `analysis.py` and `reporting/renderer.py`. The reviewer did not operate hardware, run tests, or render reports during acquisition. Visual presentation and numerical results have separate independent reviews.

## Acquisition and shutdown

- The 1.000 A setting belongs to the 24 V supply feeding the converter. Output-load requests may exceed 1 A but cannot exceed 2.000 A. The 1.05 A OCP setting does not raise the programmed supply-current limit.
- The search changes from 100 mA to 25 mA output steps near 0.90 A measured input current. A 0.98 A mean triggers a contiguous 30-second endpoint observation. Trigger evidence is preserved separately from the final mean, which can differ.
- Constant-current operation, lost input-voltage headroom, and low output voltage produce unqualified boundary evidence. One direct return to 100 mA is allowed. The recovery observation precedes explanatory checkpoint writes. Hard electrical, transport, and instrument faults go directly to shutdown.
- Four electrical queries precede durable row writes; partial raw observations survive a subsequent query failure. Samples cannot qualify before persistence and guard checks. The 750 ms acquisition-span guard remains in force.
- Verified instrument identities gate control and cleanup. The inherited resource lock, signal handling, 660-second software deadline, and independent 720-second source deadline remain active. Source OFF is verified before cancelling its deadline, then reissued and checked; load OFF is attempted independently. Failed source shutdown retains the independent cutoff.

## Report correctness

- Declared candidate loads are distinguished from actual execution. Skipped candidates do not become plotted measurements; attempted invalid observations remain visible in the exclusions evidence.
- Execution-order validation rejects duplicate/unknown IDs, omissions of sampled, qualified, or failed zero-sample outcomes, and contradictions with raw first-query chronology.
- Supply input current and converter output current have separate labels and metrics. Source-boundary observations cannot enter qualified nominal-voltage efficiency results.
- The report distinguishes the endpoint trigger from its final average, does not invent a separate hold, and describes the return observation conditionally. Unmeasured no-load behavior and the measurement boundary remain explicit.

## Verification evidence

The implementing agent reported **48 source-limit and extended-procedure tests passed before live acquisition**. These cover fake-SCPI configuration and readbacks, boundary recovery, hard-fault shutdown, trigger drift, delayed explanatory persistence, execution provenance, and inherited cleanup behavior.

The root agent subsequently reported **33 report/sequence tests passed** after the execution-evidence and report-wording fixes. These counts are reported separately; they are not combined into a unique test total.

The root agent reported successful completion of `20260927T173043.388477Z_real_75a478` in **405.877 seconds**, reaching a **1.725 A requested output load** with **0.987285 A measured mean input current**, followed by verified source, load, and source-deadline OFF states. These are acquisition-status evidence supplied to this code review; the separate results audit establishes the final numerical interpretation and window count.
