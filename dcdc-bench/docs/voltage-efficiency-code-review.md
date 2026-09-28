# Voltage-efficiency test: independent code review

Reviewed 2026-09-27. **Pre-live verdict: the fixed 24 V / near-36 V continuation is cleared; no unresolved blocking issue was found in the reviewed source.** Acquisition results and rendered report quality require their separate reviews.

## Scope and operating policy

Reviewed `src/dcdc_bench/voltage_sweep.py`, its use of the existing `extended.py` lifecycle, the fake-SCPI tests, and voltage-comparison changes in `analysis.py`, `reporting/renderer.py`, and the report JavaScript. The reviewer did not operate hardware or run tests/renderers during acquisition.

- The source current setting remains 1.000 A. Existing current, voltage, timing, identity, locking, and independent shutdown guards are retained.
- The upper condition is **35.8 V programmed**, with a **35.93 V sampled readback stop** and 36 V OVP. It is labeled nominal/near 36 V, with actual input readings retained. The [Rigol datasheet](https://www.rigol.com/dam/global/downloads/brochures/en/data-sheet/dc-powers/DP800_DataSheet_EN.pdf), printed page 5, specifies DP821A CH1 programming/readback accuracy of ±(0.1% + 25 mV) under its stated conditions. OVP accuracy is much coarser; this policy does not certify a transient voltage ceiling or instrument calibration.
- Source OFF must be verified before cancelling its timer. Source OFF is reissued and checked, load OFF is verified, and residual source voltage must fall to 0.5 V or below before reconfiguration. Residual polling occurs only while OFF and has a bounded wait.
- Each voltage phase verifies its own 720-second source deadline; the existing 660-second software alarm is not restarted between phases. Source-boundary observations remain unqualified. Hard faults stop the run.

## Initial 12 V attempt

Read the preserved run, raw samples, events, and SCPI log for `20260927T184902.863440Z_real_e0fab9`. The run aborted during startup with **no accepted efficiency window**. Earlier load-OFF readings showed output near 8 V. Its last startup cycle contained:

| Quantity | Recorded value |
|---|---:|
| Input voltage | 2.661 V |
| Input current | 1.0005 A |
| Output voltage | 6.384208 V |
| Output current | 0.056747 A |

Both source mode queries around that cycle returned **CV**. The evidence establishes collapsed input voltage and current near the programmed limit; it does not establish sustained CC operation or a specific converter fault mechanism. These startup readings must not be used to calculate a qualified efficiency result. The shutdown record and SCPI replies confirm source, load, and source deadline OFF.

## Continuation controls

The continuation has **27 conditional requests at 24 V and near 36 V only**. Its first source request is 24 V with 26 V OVP, and its first raw point belongs to the 24 V phase. It never retries 12 V or imports the earlier run's acquisition cycles.

Before opening instruments, the continuation verifies the prior integrity manifest covers the required evidence, checks its hashes and original fixed plan, requires the finalized measured 12 V startup-boundary abort with no accepted cycles or later attempts, checks OFF states and raw electrical bounds, and matches instrument identities to the configured inventory. The prior run ID and integrity-manifest hash are retained separately.

The startup guard was tightened after reviewing the failed attempt: the fifth source-only observation must show at least 10.8 V output before the load can be enabled. No electrical guard was relaxed.

## Reporting and verification

Qualified comparison values use actual channel means. The common 0.5 A reference requires a single qualified requested-load point; missing results stay unavailable. No interpolation or averaging of separate visits is introduced. Execution order is checked against preserved outcomes and raw query chronology. Invalid attempted evidence remains visible, and the previous 12 V attempt remains separate from current-run results.

Reviewed corrections also distinguish highest **qualified** load from attempted load, preserve the 35.8 V setting in metric labels/hover/CSV, and describe eight-second acquisition as a qualification policy rather than a claim about every aborted attempt.

The implementing agent reports **28 voltage-sweep/continuation fake-SCPI tests passed in 33.34 seconds**. These cover unchanged prior evidence, no 12 V command in continuation, prerequisite rejection before instrument access, startup gating, OFF failures, residual decay, timer verification, hard faults, boundary exclusions, and deadline interruption. This supersedes its earlier 18-test result; the counts are not added. The reviewer inspected the relevant source and tests but did not independently rerun them.

## Report recovery review

The first report build for continuation run `20260927T185631.575651Z_real_eb3bcd` timed out during Quarto HTML generation after producing its static vectors. Reviewed the isolated recovery script `/tmp/recover-voltage-report.py`: it verifies the prior model hash, requires complete old/new model equality except `report_revision`, checks figure order and every source SVG/PDF hash, and copies those vectors into the new revision. Static figure footers contain run and analysis identifiers, not the report revision, so this reuse does not introduce a stale revision label.

The failed `r0001` remains unchanged. The recovery produced fresh HTML and PDF for `r0002`; it did not reuse the partial HTML. Quarto's document timeout is now 600 seconds, independently of all acquisition deadlines. The root agent reports that the previous process tree had stopped before launch and that the isolated retry had a 1500-second service limit.

**Recovery verification completed:** the root agent verified all eight destination SVG/PDF hashes against the source files and the new manifest, the preserved source manifest hash, both final HTML/PDF artifact hashes, and unchanged acquisition integrity hashes. The generated HTML is 8,227,820 bytes and the PDF is 140,743 bytes. A read-only inspection confirmed that the final manifest records both document builds as successful, `destination_hashes_verified: true`, original rendering versions/source hashes, and explicit reuse without a new static-browser session. The reviewer did not independently rerun these hash checks.

**Presentation review completed:** the [UI review](voltage-efficiency-ui-review.md) records the actual desktop/mobile interactions and PDF inspections. It found and corrected long-hash overflow on mobile and a split DUT table in the PDF. Revision `r0003` contains those presentation repairs; `r0004` makes the exact method-prose correction from “differ between the three curves” to “differ between input conditions,” together with revision labels. No measurements or figure data changed.

The parent verified embedded-model identity, precise HTML/Typst transformations, unchanged vector hashes, and final artifact hashes. The revisions preserve their source manifests, scripts and compiler provenance. No additional hardware operation was required by these document changes. Actual browser coverage and the limited derivation of the final revision are distinguished in the UI review.
