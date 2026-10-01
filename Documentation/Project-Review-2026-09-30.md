# Project review — 2026-09-30

Automated agent review: three parallel reviewers plus integration and browser
verification by the coordinating agent. This is not an external certification.
Baseline: `e8f59ac` on `dcdc-bench-hardening`. Fixes described here are local
working-tree changes from this review.

## Assessment

The project has useful engineering foundations: typed instrument operations,
explicit operating limits, detached acquisition workers, verified shutdown,
preserved measurements, separate analysis/report revisions, and offline reports.
The review nevertheless found defects in cancellation records, uncertainty
calculation, publication verification and asynchronous UI state that the existing
green test suites did not catch. Those defects are corrected below.

The remaining work is primarily operator navigation/accessibility, distribution
packaging and **physical measurement qualification**. Passing software tests
does not complete M2 or establish calibrated efficiency measurements.

## Scope

| Area | Review and verification |
| --- | --- |
| `Software/` | Drivers, recipe validation, instrument identity, transport locks, cleanup and the fake-instrument suite. |
| Acquisition and planning | Real preflight, settling, UVLO/supply-profile simulations, Stop/signals, job ownership, reconnect and report dispatch. |
| Data and reports | Measurement qualification, correlations, uncertainty propagation, recipe provenance, HTML/PDF content, artifact integrity and publication. |
| UI/UX | Selection → Preview → Start, mode changes, profile editing, progress, reload, keyboard locks, mobile layout and report printing. |
| Project maintenance | CI selection, dependency consistency, documentation links, installation boundaries and outstanding milestone gates. |

No instrument session was opened. Browser Start testing used an isolated
workspace with no inventory and a synthetic converter. No public upload or
Git push was performed; original measurements and issued reports were preserved.

## Findings corrected

P1 means a wrong result/status or a mismatch between the operator's selection
and the action offered. P2 means a broken workflow, unbounded resource use or
misleading report content. P3 is presentation/documentation consistency.

| Priority | Reproduced defect | Correction and regression |
| --- | --- | --- |
| P1 | Stop during a simulated UVLO/ramp/staircase could finalize `run.json` as completed with no accepted result. | SIGINT records aborted; SIGTERM records interrupted. Partial samples and earlier completed points survive; shutdown and signal-handler restoration are checked. `test_phase_interruptions.py`. |
| P1 | Individually valid correlation coefficients could form an impossible covariance matrix; a negative variance was clamped to zero. Correlation also incorrectly cancelled independent repeatability. | Require a positive-semidefinite correlation matrix and unique pairs; correlate only systematic contributions; reject materially negative variance. `test_uncertainty.py`. |
| P1 | Publication accepted modified acquisition/report bytes despite an earlier successful build; direct analysis/report verification also accepted incomplete integrity manifests. | Require core acquisition coverage and verify hashes, reject escaping paths, verify recorded issued-artifact hashes before creating a publication destination. `allow_unverified` does not waive a hash mismatch. `test_storage.py`, `test_publish.py`. |
| P1 | An old Preview could stay startable while selections or profiles changed asynchronously. Late responses could overwrite newer selections. | Invalidate before I/O; discard superseded responses; guard callbacks during Start/acquisition. Delayed-callback regressions in `test_ui.py`. |
| P2 | Impossible settling windows passed real preflight, guaranteeing a failed energized attempt. | Check timeout against dwell, window and minimum query count before opening equipment. `test_real_backend.py`. |
| P2 | A small visible ramp grid could expand to eight million intermediate steps and over 32 million durable records. | Estimate implicit steps without allocating them; apply the existing simulation budget in Preview and procedure constructors. Default ISO examples still fit. `test_phase_budget.py`. |
| P2 | Editing or approving real-bench limits while Simulation was selected could switch modes or remove the editor. | Isolate nested input events and preserve mode when saving limits. Actual browser and callback checks. |
| P2 | Saving limits refreshed away its event slot, then raised a NiceGUI exception when showing the success notification. | Notifications and post-refresh scrolling use the stable page client. Regression uses actual NiceGUI notifications with deleted/collected slot parents. |
| P2 | Keyboard input bypassed the CSS-only running lock; Recent events collapsed on every poll. | Native `inert` plus callback guards; preserve expansion per job. |
| P2 | Served reports could not invoke their Print current view button because CSP prohibited modals. | Permit modal printing while retaining opaque-origin sandboxing. Browser checked native beforeprint/afterprint events. |
| P2 | Quarto's tab/reader-mode helpers raised browser errors when served reports could not access persistent storage. | New report headers provide document-memory storage only when native access is denied. Opaque origin and native session-storage restrictions remain in place; the browser regression covers served reports as well as offline files. |
| P2 | ISO 4.2 was advertised as a runnable clause although its generated recipe only cold-starts at selected DC levels; the report omitted that limitation. | Badge now says DC level subset; coverage is partial. Recipe title, clause and description reach the shared HTML/PDF method content, including missing holds/transitions. |
| P2 | Generic report limitations contradicted verified DUT metadata and supplied attachment references; the DUT table discarded supplied construction details. | Derive statements from saved metadata, show supplied construction fields, and distinguish references from an embedded sensor photograph. `test_analysis.py`, `test_reporting.py`. |
| P2 | GitHub CI selected neither the detached-worker integration gate nor the integration-only PDF fixtures. | Worker/reconnect gate is in the required job; document integration fixtures join browser/PDF checks. |
| P3 | Idle claimed unverified hardware OFF; synthetic UI cards said Measured; documentation contained broken links and a split Markdown table. | Truthful idle/synthetic labels, repaired relative links and standards-table formatting. |

Uncertainty corrections use analysis formula **`settled-dc-1.4`** and budget
method **`readback-budget-1.1`**. Reanalysis creates a new revision; existing
analyses and issued reports are not rewritten by this review.

## Remaining findings and recommended order

1. **P2 — Reports stops at the newest 30 runs.** `ui.py:render_reports`
   slices `jobs[:30]` without pagination or search. Add older-run navigation
   before the project accumulates a large test history.
2. **P2 — Polling replaces the Run panel.** `show_status()` still rebuilds
   controls every two seconds. Expansion state is preserved, but keyboard focus
   can disappear. Update stable elements in place, particularly report links
   and queue controls.
3. **P3 — First sensor marker requires a pointer.** The annotation editor can
   nudge existing markers by keyboard but cannot create its first marker that
   way. Add an Add marker button with editable coordinates.
4. **P3 — Some synthetic report controls still say Measured.** The report's
   SYNTHETIC evidence labels remain visible, but generic axis/hover wording
   should follow the data source consistently.
5. **Distribution gap — source checkout required.** Templates/default profiles
   are located relative to the checkout; wheel package-data declarations do
   not include those resources. The documented editable install works. Bundle
   resources and add a clean wheel-install smoke test before a package release.
6. **CI policy — document job is informational.** It is still allowed to fail.
   Make it required before treating browser/PDF results as a release gate.
7. **P3 — Too much reference material in the primary workflow.** Both bench
   capability explanations and unavailable standards cards are expanded by
   default. Collapsing secondary details would make ordinary test selection
   easier to scan, especially on a phone.
8. **P3 — PDF paragraph grouping.** In the new ISO subset example, the DUT
   documentation note falls at the top of page 2, away from its table. Keep
   that note with the DUT section when refining pagination. No clipping or
   PDF validation failure was observed.

Separate from these software findings, the bench's recorded readback disagreement
and light-load uncertainty remain an M2 qualification issue. Follow the
[qualification plan](../dcdc-bench/docs/m2-qualification-plan.md), including the
external current-reference decision. Standards parameters were not independently
reverified against licensed standards in this review. No full-clause compliance
claim is established by the generated DC subset.

For maintainability, the next structural change should separate UI state
transitions from rendering. The selection/save races demonstrate a concrete
reason for doing so. Avoid combining that refactor with new instrument modes.

## Verification

- Baseline instrument library: **445 passed**. The sandbox initially blocked
  12 local HTTP tests from binding sockets; all passed with localhost access.
- Baseline DC–DC suite: **876 passed, 16 browser/PDF gates deselected**.
- Complete DC–DC run after fixes: **948 passed, 1 skipped, 2 failed**.
  Both failures came from Playwright's service-worker blocker injecting an
  uncaught property access into the opaque-origin report; the second test
  inherited that error through a shared fixture. Correcting the test fixture
  retained native worker denial, offline checks and the report sandbox.
  The two affected browser tests then **both passed**.
- Full browser/HTML/PDF module with the corrected fixture: **15 passed,
  1 skipped**. The skip is the chronological-stage test: the default demo has
  a voltage/load grid, not a chronological demand sequence.
- Final report-content checks, including the last three metadata regressions:
  **82 passed**.
- Focused data/publication/standards/storage checks after fixes: **165 passed**.
- Independent backend checks: **86 passed**; uncertainty checks: **23 passed**.
  These overlap the full suites and must not be added to their totals.
- Installed Python dependencies: `pip check` reported no broken requirements.
- Relative file links in 70 Markdown documents: none broken. The 266 tracked
  files include neither the local bench inventory nor saved UI workspace;
  no tracked file exceeds 20 MiB. This path/size check is not a full secret scan.
- Ten historical acquisition folders passed the strengthened integrity check.
  Three existing demo reports each passed all 12 recorded artifact hashes.
- Browser: isolated UI, 1440 px desktop and 390 px mobile; limit editing and
  approval preserve Simulation, a single mock Start completes acquisition,
  reload does not duplicate the worker, event expansion persists, and served
  report printing invokes native print events. **All seven flow checks passed**,
  with no page errors, console errors, external requests or server exceptions.
  The smoke script waits for server-backed checkbox state after clicking;
  its first attempt asserted before the saved state had returned.
- A fresh **ISO 4.2 DC level subset, 24 V system** mock acquisition completed
  and produced validated HTML and PDF. Both include the omitted hold/transition
  scope; the PDF method page and served interactive report were inspected.
- The local UI service was restarted after confirming no active jobs. It is
  active and returns HTTP 200 on port 8081. No acquisition was started there.

Local logs, JUnit results and screenshots are under the gitignored
`dcdc-bench/test-artifacts/review-20260930-*` paths. Browser smoke script:
`review-20260930-browser-final/check.py` in that artifact directory. Its
`result.json` is the final acceptance record. The standards render's script,
final log and result are in `review-20260930-standard/`; the earlier diagnostic
attempt is retained separately. The complete-suite log preserves its initial
test-harness failures; `review-20260930-document-gates.log` records the corrected
report module's clean rerun. These overlapping checks are not additive totals.
