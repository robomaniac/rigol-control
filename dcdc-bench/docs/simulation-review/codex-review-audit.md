# Audit of the Codex review fixes (commit `031b122`)

Independent check of `Documentation/Project-Review-2026-09-30.md` and the
commit that applied its working-tree fixes verbatim,
`031b122` "Apply the Codex review's working-tree fixes" (41 files,
+1469/−140), as it stands on `dcdc-bench-hardening` at `b9adf70` after the
follow-ups `ff46bfe` (print-event skip) and the merge `b6d59df`
(one standards card, one selected test). Line numbers below are at `b9adf70`.

## Method

- Read `git diff 031b122^ 031b122` hunk by hunk against the review's
  "Findings corrected" table; for each row located the change and the named
  regression test and reasoned whether the test would fail without the change.
- Two rows were checked by reverting the hunk in a scratchpad copy of the
  `031b122` tree (`git archive`, never the worktree): the pre-fix `uvlo.py`
  was driven with the regression's own SIGINT override; the pre-fix
  `uncertainty.py`/`domain.py` were run against the new `test_uncertainty.py`.
- Focused test files were run one at a time under the agent lock with the
  required-job marker selection: `test_phase_interruptions` 6,
  `test_uncertainty` 23, `test_publish` 51, `test_storage` 10,
  `test_phase_budget` 7, `test_real_backend` 39, `test_report_javascript` 8,
  `test_standards` 58 (+1 skip), `test_analysis` 22, `test_reporting` 57
  (+1 skip), `test_ui` 82, `test_planning`+`test_supply_profiles`+`test_uvlo`
  53, and `test_run02_reconnect.py -m integration` 1 (26 s). All passed.
- Offline re-checks of the review's "Verification" section: collect-only
  counts at `e8f59ac`, `031b122` and `b9adf70`; the review's own JUnit files
  under `dcdc-bench/test-artifacts/review-20260930-*`; a relative-link
  checker over every tracked Markdown file; `verify_integrity` over all 20
  local `integrity.json`; `publish._verify_issued_files` over all 41 local
  report revisions; the shipped recipes and generated ISO recipes through
  `prepare_real_plan`/`prepare_mock_plan`; `pip check`.
- No instrument session, render, demo or UI server. The browser and PDF
  claims are judged from the review's recorded artifacts, not re-run.

Verdicts: **Confirmed** (change does what the row says and the test
discriminates), **Partially**, **Not confirmed**, **Risk** (correct but
introduces a hazard worth noting).

## Findings corrected — row by row

### P1 — Stop during a simulated UVLO/ramp/staircase finalized `run.json` as completed

| | |
| --- | --- |
| Claim | SIGINT records `aborted`, SIGTERM `interrupted`; partial samples and earlier points survive; OFF verification and handler restoration checked. |
| Where | `src/dcdc_bench/uvlo.py:450-459` installs SIGINT/SIGTERM handlers on the main thread and registers their restoration on the `ExitStack`; `:495-510` `except BaseException` maps `KeyboardInterrupt`→`aborted`, `WorkerTerminated`→`interrupted`, else `error`, and marks the active point `inconclusive`; `:515` sets `SIG_IGN` before OFF verification and `store.finalize`. Budget hooks `uvlo.py:102`, `supply_profiles.py:105`. |
| Test | `tests/test_phase_interruptions.py` (3 procedures × 2 signals). 6 passed. Pre-fix reproduction in the scratchpad copy: `KeyboardInterrupt` escaped `run_uvlo_mock`, `run.json` said `execution_status: completed`, `integrity.json` was written, `errors == []` — exactly the defect described. |
| Runner / job-service agreement | Same mapping as `runner.py:684-688` (`WorkerTerminated`/terminate → `interrupted`, `KeyboardInterrupt` → `aborted`). After the fix the phase-scoped owner returns its directory like `run_mock` does; `job_service.worker` then runs `_verified_off` (both outputs OFF, verified — satisfied by the `finally` block), records `report-queued` with `acquisition_cancelled` from the `cancel.request` marker and the report-only worker later saves `cancelled`. Pre-fix the `KeyboardInterrupt` propagated into the worker's own handler: job `cancelled`, run `completed`, no report queued. `cancel()` is idempotent (one SIGINT), and `SIG_IGN` covers a repeated signal during finalization. |
| Verdict | **Confirmed.** Low-severity note: the interrupted active point is `inconclusive` here but `not-run`/`error` in `runner.py:692`; the two mock paths now use different words for "cut short". `except BaseException` also absorbs `SystemExit` as `error`. |

### P1 — Correlation coefficients could form an impossible covariance; negative variance clamped; repeatability cancelled

| | |
| --- | --- |
| Claim | Require a positive-semidefinite correlation matrix and unique pairs; correlate only systematic contributions; reject materially negative variance; versions `settled-dc-1.4`, `readback-budget-1.1`. |
| Where | `domain.py:311-337` pivoted Schur-complement PSD check (no numerical dependency); `domain.py:403-412` unique pairs including reversed, matrix validated on `BenchProfile`; `uncertainty.py:210-236` `propagate` puts the total channel variance on the diagonal and `r·u_B,i·u_B,j` off it, checks finiteness and `0 ≤ u_B ≤ u_c`, uses `fsum`, raises when variance < −1e-12·Σ\|terms\|; `:360` systematic map; `:40` and `analysis.py:27` version bumps; `docs/uncertainty-budget.md` formulas updated. |
| Test | `tests/test_uncertainty.py` 23 passed at HEAD. Against the pre-fix `uncertainty.py`+`domain.py`: the 4 new tests fail, the other 19 (UNC-01…04 fixtures included) pass — the regressions discriminate and the existing fixtures hold under both implementations. |
| Metrology | Brief §9.2 asks to "combine standard contributions using the declared measurement model, including covariance where appropriate" [R10, R11]; TN 1297 §5 gives u_c² = ΣΣ c_i c_j u(x_i,x_j). `ChannelCorrelation` is documented as the correlation "between two readback channels' systematic errors" (`domain.py:298`), so applying r to u_B only is the arithmetic the contract already declared; pre-fix r multiplied the total u including the Type A standard error, which let a shared reference cancel independent scatter (new test: the 90·√2·0.01 pp floor). The matrix diag(u_A²)+D·R·D is PSD whenever R is, so the negative-variance guard can only trip on rounding, and its tolerance is relative. Version bumps are warranted: budgets with both repeatability and a declared correlation change value. |
| Verdict | **Confirmed.** Model-scope caveat (not a defect): Type A covariance between simultaneously sampled channels (common-mode drift inside the window) cannot be declared; the budget record states this scope explicitly. No shipped bench profile declares correlations, so profile loading is unaffected. |

### P1 — Publication accepted modified bytes; incomplete integrity manifests accepted

| | |
| --- | --- |
| Claim | Require core acquisition coverage and verify hashes; reject escaping paths; verify recorded issued-artifact hashes before creating the destination; `allow_unverified` does not waive a hash mismatch. |
| Where | `storage.py:100-122` (required `run.json`, `plan.json`, `request.json`, `raw/samples.jsonl`; `algorithm == sha256`; resolved-path containment, so a symlink out of the run is refused even with matching bytes); `publish.py:171-222` `_verify_issued_files`; `publish.py:483` `verify_integrity(run_dir)`; `:500` issued hashes; `:548` `target.mkdir` only after both. `voltage_sweep.py` reorders coverage check before verification (message preserved). |
| `allow_unverified` | Waives only *absence*: no build manifest (`:180-184`), unreadable manifest (`:186-190`), no recorded HTML hash (`:197-198`). The mismatch raise at `:220` is unconditional. `test_publication_rejects_changed_evidence_and_issued_artifacts_before_writing` is parametrised over 8 files × `allow_unverified ∈ {False, True}` and asserts the destination was never created and the run tree is byte-identical. |
| Legitimate revisions | Ran `_verify_issued_files(allow_unverified=False)` over all 41 local report revisions: every `status: success` revision passes (9–14 recorded hashes each, including the three demo reports at 12). Only revisions with status `interrupted`/`failed`/`building` lack an HTML hash, and publication already refuses those on build status. `verify_integrity` passes on all 20 local acquisition folders (the review counted ten). `request.json` and `algorithm` have been written by `RunStore` since the first format, so no finalized run is newly refused. Fixture tests had to call `issue_test_report` after editing `report.html`: a report edited in place after issuance can no longer be published without reissue, which is the intent. |
| Verdict | **Confirmed.** Minor forward-compatibility hazard: `publish.py:186` raises on any artifact format other than `html`/`pdf`. |

### P1 — Old Preview stayed startable during asynchronous changes; late responses overwrote newer selections

| | |
| --- | --- |
| Claim | Invalidate before I/O; discard superseded responses; guard callbacks during Start/acquisition. |
| Where | `ui.py:551-562` `changed()` bumps `generation`, clears preview/confirm, re-renders; `:564-611` `select`/`select_mode`/`select_bench` refuse while `active`/`start_busy`, call `changed()` before the first `await`, re-check the generation after; `:527-549` `reload`/`refresh_feasibility` drop a response whose generation or (dut, bench, recipes) tuple is stale; `:665-697` `save_and_select` and `delete_profile` the same; `:482-488` `notify` on the stable client. |
| Test | `tests/test_ui.py`: `test_selection_invalidates_before_io_and_discards_late_feasibility[dut\|mode\|bench]`, `test_profile_save_invalidates_before_io_and_does_not_replace_newer_selection`, `test_running_lock_refuses_selection_callbacks…`. 82 passed. Pre-fix `changed()` ran after `await refresh_feasibility()`, so the assertion "Start disabled during the await" would fail. |
| Interaction with `b6d59df` | The merge keeps Codex's ordering: `select('recipe')` folds the ISO editor and clears its ticks, then `changed()`, then `render_tests()` (`ui.py:579-583`); `add_as_tests` keeps the late-response guard after `refresh_feasibility()` and only then folds the editor and selects the last generated test (`:1340-1349`). The editor card (`expanded=`) is never `selected`, so single-selection holds. `toggle_standard` (`:1233`) does no I/O and never touches `generation`; it is not guarded by `active`/`start_busy` and relies on `inert`, so a queued socket event during a run could re-render the tests panel (render only, no state hazard). All seven `save_and_select` callers catch the new `ValueError`. The second `changed()` at the end of `add_as_tests` is redundant but harmless. |
| Verdict | **Confirmed.** |

### P2 — Impossible settling windows passed real preflight

| | |
| --- | --- |
| Where | `real_backend.py:99-106`: minimum = max(dwell, window, samples·poll); refuse `timeout ≤ minimum` before any instrument access. The loop at `:333-340` sleeps one poll before every settling query and checks the timeout after it, so with any transport time the point cannot settle. |
| Test | `tests/test_real_backend.py` (3 impossible windows + 1 margin case). 39 passed. All seven shipped recipes carry `timeout_s: 30` against a 5 s minimum; through both real profiles none trips the new check (remaining preflight errors are the expected approval/inventory ones). |
| Verdict | **Confirmed.** "Guaranteeing a failed attempt" is slightly over-stated at exact equality with an ideal zero-time transport; the refusal is conservative and the message says so. |

### P2 — A small ramp grid could expand to eight million intermediate steps

| | |
| --- | --- |
| Where | `planning.py:362-371` `live_step_count` (Decimal, no allocation); `:374-415` `phase_scoped_mock_estimate`; `:418-422` `require_phase_scoped_mock_budget`; `:425-443` `prepare_mock_plan` now budgets phase-scoped plans; `supply_profiles.py:68` uses the count; constructors refuse before any folder (`uvlo.py:102`, `supply_profiles.py:105`). |
| Cross-check | Against the procedures: one startup loop per test, one dwell loop (⌈dwell/poll⌉ cycles) and one acquisition loop (max(⌈duration/poll⌉, minimum cycles)) per level, one `cycle` per live ramp step (`supply_profiles.py:231-236`); records = 4·(cycles+steps) + 2·levels + 12·tests. The UVLO example has 17 points for 17 targets (no hidden doubling): 1 446 records, 265 s deadline. |
| Test | `tests/test_phase_budget.py` 7 passed (8 000 000 steps refused with `live_steps` monkeypatched to assert). Generated §4.5/§4.6.2 recipes for 12 V and 24 V fit on all four mock benches (typical 35–92 s). |
| Verdict | **Confirmed.** |

### P2 — Editing or approving real-bench limits switched modes or removed the editor

| | |
| --- | --- |
| Where | `ui.py:965, :975` `select_saved=False`; `render_bench` stops `click`/`keydown` at the real-bench details container. |
| Test | `test_editing_real_limits_preserves_simulation_and_inputs_stop_tile_events`; the review's browser record (`review-20260930-browser-final/result.json`, checks 2–3). |
| Verdict | **Confirmed** at callback level; the browser part rests on the review's record. |

### P2 — Saving limits refreshed away its event slot; notification raised

| | |
| --- | --- |
| Where | `ui.py:482-488` `notify` under `with client:`; `scroll_to` likewise. |
| Test | `test_save_rename_delete_notifications_survive_deleted_event_slots` (real `ui.notify`, forced `gc.collect`). |
| Verdict | **Confirmed.** |

### P2 — Keyboard input bypassed the CSS-only running lock; Recent events collapsed on every poll

| | |
| --- | --- |
| Where | `ui.py:1391` native `inert` on the three editor sections; callback guards in every selection/editor handler; `events_open` per job (`:452`, expansion `value`/`on_value_change`). |
| Test | `test_running_lock_refuses_selection_callbacks_and_recent_events_stay_open` dispatches callbacks past `inert` and polls twice. |
| Verdict | **Confirmed.** (`events_open` is never pruned; negligible.) |

### P2 — Served reports could not print because CSP prohibited modals

| | |
| --- | --- |
| Where | `ui.py:217` adds `allow-modals`; `allow-same-origin` stays absent (asserted in `test_file_headers_…` and the served-report browser test, `window.origin == "null"`). `report.js:438` calls `window.print()`, which a sandboxed document needs `allow-modals` for. |
| Browser evidence | The served-report test passed on the Pi's Chromium (result.json check 7), but `ff46bfe` skips the `beforeprint/afterprint` wait where the headless browser never dispatches those events (Chrome for Testing on CI). |
| Verdict | **Confirmed**, with a small widening: `allow-modals` also permits `alert`/`confirm`/`prompt`/`beforeunload` prompts from report scripts (shipped offline `report.js` + Plotly only). The print permission is observed on the Pi only, not on CI. |

### P2 — Quarto's tab/reader-mode helpers raised errors without persistent storage

| | |
| --- | --- |
| Where | `templates/web/report-head.js`: probes `window.localStorage.length` inside `try` and returns if it works (native storage and its getter untouched); only on a thrown access it defines a Map-backed, document-lifetime `localStorage`. Embedded inline as `<script id="dcdc-report-head">` in `metadata.html` (`renderer.py:1699-1702`), included by `templates/characterization.qmd:15` `include-in-header`; hashed in `render_sources_sha256` (`:1647`). |
| Properties | Offline (inline, no fetch). No CSP change beyond the modal token above; the served CSP is `sandbox …` with no `script-src`. `sessionStorage` is not touched (the browser test asserts it still throws `SecurityError`); the origin stays opaque. It also shadows a browser privacy-mode denial, as its comment says. |
| Test | `tests/test_report_javascript.py` 8 passed through Playwright's bundled Node (native untouched; Storage semantics; re-entry; per-document lifetime); `test_software_provenance` hashes the new source. |
| Verdict | **Confirmed.** |

### P2 — ISO 4.2 advertised as runnable; report omitted the limitation

| | |
| --- | --- |
| Where | `standards.py:622-626` coverage `partial` + condition, `:669-670` reason suffix; `standard_recipes.py:100-103` badge "DC level subset", `:131` levels text without t1/t2, `:176` summary, `:225-226` title; `analysis.py:863-869` recipe title, clause and scope reach the shared method notes. |
| Test | `test_standard_recipe_scope_survives_into_shared_html_pdf_body` asserts `_body` contains "DC level subset" and "1 V/s transitions are not reproduced"; `test_standards` 58 passed; `test_planning` title updated. The review's 24 V mock render record exists (`review-20260930-standard/result.json`, `success`, html+pdf). |
| Verdict | **Confirmed.** The clause's status word stays `runs_here` (label changed), consistent with the merge wording "N test subsets available". |

### P2 — Generic limitations contradicted DUT metadata; DUT table discarded construction

| | |
| --- | --- |
| Where | `analysis.py:1762-1770` statements from `ratings.origin`, `verified_from_sample_label` and construction; `renderer.py:847-877` construction row and attachment-reference / sensor-placement sentence, `sensor_placement_present=load_annotations(out) is not None` (`:1724`). |
| Test | `test_analysis` (2 new), `test_reporting` (3 new). 22 and 57+1 passed. |
| Verdict | **Confirmed.** |

### P2 — GitHub CI selected neither the detached-worker gate nor the integration-only PDF fixtures

| | |
| --- | --- |
| What changed | Before: required job `-m 'not browser and not pdf and not integration'`, documents job `-m 'browser or pdf'`, so nothing marked `integration` ran on CI. After: `.github/workflows/ci.yml:50-53` runs `test_run02_reconnect.py -m integration` in the required job (one test, both Python versions); `:156` the documents job runs `browser or pdf or integration` with the reconnect file ignored (13 `test_pdf_check`/`test_print_tables` tests needing the bundled Typst that the pinned Quarto install provides). `CONTRIBUTING.md` matches. |
| Cost | The reconnect test took 26 s here (detached mock worker on the wall clock, stub renderer); waits of 40/60/60 s at 0.2 s polling. Process-based and timing-based, so exposed to shared-runner stalls, but bounded and well under the job's 30 min. |
| Verdict | **Confirmed.** Slower by roughly half a minute; flakiness low-to-moderate — worth watching on the first runs rather than pre-empting. |

### P3 — Idle label, synthetic "Measured", broken links, split table

| | |
| --- | --- |
| Idle / synthetic labels | `ui.py:1930` "Idle — no job running"; `:1721` `reading_kind` Simulated/Measured; getting-started composed-label test updated. **Confirmed.** `HANDOFF.md` "failed twice" → "the recorded automated attempt" agrees with `cold-start-hypothesis.md` §2 (one recorded attempt). **Confirmed.** |
| "Repaired relative links" | **Risk / Not confirmed.** Every link edit in the commit sits inside *quoted* text: the "Proposed README changes" code blocks of `docs/github-readiness.md` (targets relative to the root `README.md`, now rewritten relative to `docs/`, so the proposals would break if applied), and the verbatim quotes of README line 15 in `docs/simulation-review/new-user.md` (C1) and `new-user-recheck.md` (C1), which now misquote the README (it still reads `dcdc-bench/docs/getting-started.md`, `CONTRIBUTING.md`, `HANDOFF.md`). Meanwhile 35 links that do not resolve in a clone remain: `extended-ui-review.md`, `source-limit-ui-review.md`, `voltage-efficiency-ui-review.md` point into the gitignored `dcdc-bench/runs/…/reviews/` folders that exist only on the Pi. |
| "Split Markdown table" | **Not confirmed.** No table-structure change is in the commit: the only table edits are the `integration` row of `CONTRIBUTING.md` and the new review document; `docs/standards/iso16750-2.md` changed the text of one row and added a paragraph. |

## Specific risks found

1. **Documentation regression from the link repair** (above): quotes and
   proposals in three documents now say something the README does not.
2. **Non-reproducible test totals.** The review's "948 passed, 1 skipped,
   2 failed" (951) and the commit message's "937 passed (17 deselected)" (954)
   come from the Pi, where `test_issued_real_models_still_render_and_export`
   parametrises over 25 gitignored local real-run revisions; the committed
   tree collects 930 (913 without browser/pdf). Details below.
3. **Qualification vocabulary** for a cut-short point: `inconclusive`
   (`uvlo.py:505`) versus `not-run`/`error` (`runner.py:692`).
4. **`allow-modals`** slightly widens what report scripts may do; opaque
   origin unchanged. Print-event evidence is Pi-only after `ff46bfe`.
5. **`_verify_issued_files` rejects unknown artifact formats**
   (`publish.py:186`) — a future renderer artifact would block publication
   until this list is extended.
6. **Required-job integration test** is wall-clock and subprocess based;
   passes in 26 s here; watch for flakes rather than remove it.
7. `except BaseException` in the phase-scoped owner also finalizes on
   `SystemExit` as `error` (acceptable, but different from the runner).

## Verification claims checked offline

| Claim | Result |
| --- | --- |
| Instrument library 445 passed | `Software/tests` collects 445. Consistent. |
| Baseline 876 passed, 16 deselected (892) | `e8f59ac` collects 852 / 868 with the same selection. The 24 extra cases are the Pi's local real-run revisions (25 parametrisations replacing the single `[NOTSET]` placeholder). Environment-dependent, not a tree property. |
| Complete run 948 + 1 + 2 = 951 | `031b122` collects 930. The review's JUnit (`review-20260930-complete.xml`, `tests="951"`) has 79 `test_reporting` cases where the tree has 58: +25 local revisions, −1 `[NOTSET]`, −3 DUT-body tests added after that run. **The 948 figure is not reproducible from the repository**; a clean clone gives 930 at `031b122` and 934 at `b9adf70` (917 without browser/pdf; 903 for the required-job selection). The commit message's 937/954 has the same origin. |
| "15 passed, 1 skipped" browser/PDF module; two Playwright failures fixed | Not runnable here. HEAD selects 17 browser/pdf tests; `ff46bfe` adds a further environment skip on CI browsers. The JUnit records the two `service_workers="block"` failures as described. |
| 82 / 165 / 86 / 23 focused counts | `final-content.xml` 82, `data.xml` 165, `test_uncertainty` 23 (re-run). `unit.xml` 876 is the baseline run. Consistent. |
| `pip check` clean | Reproduced: "No broken requirements found." |
| Relative links in 70 Markdown documents: none broken | 71 tracked `.md` at `031b122` (70 before the review document). Over 456 relative links, 35 do not resolve in a clone (all into gitignored `runs/`). True only on the Pi where those folders exist. |
| 266 tracked files; no inventory or workspace; none > 20 MiB | 266 at `e8f59ac` (271 at `031b122`, 277 at HEAD); `.gitignore` excludes `runs/` and `workspace/`; largest tracked file 254 KB. Consistent. |
| Ten historical acquisition folders pass; three demo reports pass 12 hashes | 20 of 20 local `integrity.json` pass the strengthened check; the three demo revisions verify 12 hashes each, and every other `success` revision (38) verifies 9–14. Consistent and stronger than claimed. |
| Seven browser flow checks; ISO 4.2 24 V render | `review-20260930-browser-final/result.json` lists seven checks with empty error lists; `review-20260930-standard/result.json` records `success` for html+pdf. Records exist; not re-run. |

## Assessment of the eight remaining findings

| # | Finding | Agree? | Reasoning |
| --- | --- | --- | --- |
| 1 | P2 — Reports stops at the newest 30 runs | Agree, P2 | `ui.py:1787` `jobs[:30]` with a "Newest 30 of N" note; older runs are unreachable from the page (CLI only). |
| 2 | P2 — Polling replaces the Run panel | Agree, P2 | `show_status` calls `panel.clear()` on every 2 s poll (`ui.py:1686`); expansion state is preserved, keyboard focus is not. |
| 3 | P3 — First sensor marker needs a pointer | Agree, P3 | `annotation_editor.py` only nudges an existing marker with the arrow keys; there is no Add-marker control. |
| 4 | P3 — Some synthetic controls still say Measured | Agree, P3 | `report.js:34-35` `quantityLabels` and `renderer.py:1188-1189` `<option>` texts are hard-coded "Measured …" while `:77` and `:367` already switch on `evidence_label`. |
| 5 | Distribution gap — source checkout required | Agree | `pyproject.toml` package-data covers only `dcdc_bench.reporting` globs; `TEMPLATES = dcdc-bench/templates` (`renderer.py:37`) and `PROJECT_ROOT/profiles` (`services.py:19`) live outside `src/`. Matters only before a non-editable install; the documented editable install works. |
| 6 | CI policy — document job informational | Agree | `ci.yml:59` `continue-on-error: true`. Make it required only once the Quarto download step has proven stable; the owner's review README still lists "the browser gates' behaviour on CI" as open. |
| 7 | P3 — Too much reference material in the primary workflow | Disagree in part | The always-visible can/cannot panels were the first point on which all five reviewer roles agreed and are an owner-recorded resolution (`docs/simulation-review/README.md`, "Where the reviews agree" §1 and "Resolutions — Bench page: Done"); collapsing them reverses that decision. The other half (unavailable standards cards expanded by default) is already resolved by `b6d59df`: one ISO card, folded editor, other laboratories as a footnote to `/standards`. At most compact the panels on the 390 px layout. |
| 8 | P3 — PDF paragraph grouping | Plausible, unverified | Needs a render to check; no clipping or validation failure is claimed. P3 is right. |

The review's closing caveats (M2 qualification remains open; standards
parameters not independently reverified; no clause-compliance claim) agree
with the owner's recorded decisions and with the ISO document's "to be
verified against the owner's copy" markers.

## What to do next

1. Revert the link edits inside quoted text in `docs/github-readiness.md`
   ("Proposed README changes"), `docs/simulation-review/new-user.md` (C1)
   and `new-user-recheck.md` (C1); mark the 35 `runs/`-relative links in the
   three UI-review documents as local-only artifacts (or copy the few
   screenshots they cite into tracked `screenshots/`).
2. Correct the totals in `Documentation/Project-Review-2026-09-30.md` (and
   anywhere the commit message's 937 is repeated): clean clone 930 at
   `031b122` / 934 at `b9adf70`; the 951/954 figures hold only with the Pi's
   local `runs/`.
3. Decide one word for a cut-short point (`not-run` as in `runner.py`, or
   `inconclusive`) and align `uvlo.py:505`; one-line change plus a test.
4. Keep the can/cannot panels; drop the first half of remaining finding 7.
5. Watch the first CI runs of the reconnect gate; if it flakes, widen its
   `wait_until` budgets rather than removing it from the required job.
6. Then remaining findings 1, 2, 4, 5 in that order; 6 after the documents
   job has been green for a few runs.
7. Optional: note in `docs/uncertainty-budget.md` that Type A covariance
   between channels is outside the declared model (the budget record already
   states the scope).
