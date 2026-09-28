# Merge code review: nine parallel increments on `dcdc-bench-hardening`

Reviewed head: `0ec41fd` ("Integrate the nine parallel increments and settle their seams"), diff base `6630e8c`.
Reviewer: independent read-only pass. Date: 2026-09-28.

## Scope and method

- Change set: `git diff 6630e8c..HEAD --stat` — 72 files, +13 931 / −87; 15 new modules
  (`uncertainty`, `uvlo`, `mock_uvlo`, `thermal`, `mock_thermal`, `comparison`,
  `reporting/comparison`, `reporting/pdf_check`, `reporting/sensor_placement`, `doctor`,
  `publish`, `attachments`, `annotations`, `annotation_editor`, `resources`) and ~10 changed
  ones (`job_service`, `analysis`, `reporting/renderer`, `domain`, `planning`, `runner`,
  `services`, `cli`, `ui`, `ui_models`, `adapters`, `bringup`, `extended`).
- Rules applied: implementation brief §1 (engineering rules, evidence hierarchy), §7
  (ownership, protective behavior, doctor is read-only), §8.4 (immutability), §9.2
  (uncertainty policy), §12.1 (shared report model; validation errors block publication).
- Method: reading and call-path tracing only. No test suite, demo, render, UI or instrument
  was run (host is a memory-limited shared Pi; the coordinator asked for reading only after a
  host reset). Every finding cites `file:line` at head `0ec41fd`. Where a claim depends on
  runtime behavior I could not observe, it is stated as a scenario, not an observation.
- Note: this worktree was on `main` (`565c761`) when the review started; it was reset to
  `0ec41fd` before any file was read.

## Findings, ranked by severity

No Blocker: none of the findings lets acquisition run concurrently with a render, lets two
report workers run, or lets a real bench bind the mock thermal/UVLO providers. Seven Majors.

### Major

**M1 — `cancel()` of a `report-queued` job races the dispatcher (lost cancel / resurrected job).**
`dcdc-bench/src/dcdc_bench/job_service.py:499-508`. The new `REPORT_QUEUED` branch of `cancel()`
does a read-modify-write of `job.json` *without* `self.lock`, whereas `dispatch_reports()`
(366-401) and `_defer()` (424-438) read-modify-write the same file under the lock.
Scenario A: the 2 s dispatcher tick reads the record (state `report-queued`), passes the lease
and memory gate; the operator's `cancel()` writes `state=cancelled`; the dispatcher then
writes `state=queued` (395-397) and launches — the cancel is silently lost and the render runs.
Scenario B: `_defer()` reads the record, `cancel()` writes `cancelled`, `_defer()` writes back
`report-queued` with a deferral reason (434-435) — a cancelled job is resurrected into the
queue. Fix: wrap the branch in `with self.lock:` and re-read `job.json` inside it (the same
pattern `retry_report` uses at 334-351).

**M2 — Comparison difference-uncertainty reads a budget table that the analysis never writes.**
`dcdc-bench/src/dcdc_bench/comparison.py:328-337` (`_standard_uncertainty`) expects
`analysis["uncertainty"]["standard"][point_id][quantity]`. `evaluate_run_budget`
(`dcdc-bench/src/dcdc_bench/uncertainty.py:356-372`) emits no `standard` key; per-point
standard uncertainties live at `points[pid]["quantities"][name]["standard"]` and
`points[pid]["channels"][q]["standard"]`. `tests/test_comparison.py:98-100` hand-builds the
nonexistent shape, so the tests pass against a fixture the product never produces.
Scenario: two runs with fully evaluated budgets are compared; every pair reports
`"not evaluated" / "no evaluated standard uncertainty ... in both analyses"`, no
resolvability verdict, and the UNC-03 covariance path is dead. Fail-safe direction (nothing is
fabricated), but the feature is inert and its test does not test the integration.
Fix: read through `uncertainty.evaluated_quantity(budget, pid, quantity)["standard"]` (which
also checks `schema_version`), and rebuild the test fixture with `evaluate_run_budget`.

**M3 — `uvlo_input_ramp` is planner-"implemented" but unreachable from every product entry point.**
`dcdc-bench/src/dcdc_bench/planning.py:17` adds the type to `IMPLEMENTED_TEST_TYPES`, so an
approved mock UVLO recipe previews as `executable` and `JobService.start()` arms a job. The
worker (`job_service.py:650-653`) and `services.execute()` (`services.py:150-152`) call
`runner.run_mock`, which now raises for any non-sweep test (`runner.py:130-134`).
`uvlo.run_uvlo_mock` has no caller outside `tests/` (grep of `src/`); `runner.py:132` only
mentions it in a comment. Scenario: operator previews `12t12-4a-uvlo.example.yaml` with the
approval block filled in, confirms, presses Start → job immediately `failed:
ValueError: run_mock executes steady_state_load_sweep tests only`. No hardware risk (mock only),
but the increment's headline procedure is not wired. Fix: dispatch by test type in `worker()`
and `execute()` (all-UVLO plan → `run_uvlo_mock`), or drop the type from
`IMPLEMENTED_TEST_TYPES` until wired.

**M4 — A UVLO off-step with a slightly negative readback is silently un-bracketed.**
`dcdc-bench/src/dcdc_bench/analysis.py:474-477` demotes any point with `metric_flags` to
`inconclusive` *before* `_uvlo_analysis` runs (495-497). `dc_metrics` sets `unexpected_sign`
whenever any mean is `< 0` (232-233). For an output-off step, Vout≈0/Iout≈0 with a small
negative offset therefore yields `qualification="inconclusive"`; `_uvlo_analysis` then sets
`state=None` for a non-valid point (407), the worker-vs-analysis disagreement check (409-411)
is skipped because `state is None`, and `uvlo_ramp_brackets` records
"no output-off step was observed on the descending ramp" (312-313) — contradicting the
worker's recorded `output_state="off"` and the point's own reason text. The mock avoids this
only because `MockBench.read` adds a positive offset. Latent for the real DUT: DP821A/DL3031A
readbacks at 0 V / 0 A commonly read a few counts negative. Fix: classify UVLO steps from the
accepted `Vout_V` mean irrespective of `metric_flags`, and do not treat `unexpected_sign` on an
expected-off step as demoting; if a step cannot be classified, raise rather than emit a
bracket note that contradicts the evidence.

**M5 — A missing checker tool turns every PDF into `failed-validation` and the job into `failed`.**
`dcdc-bench/src/dcdc_bench/reporting/pdf_check.py:466-470` (no `pdftohtml`) and `:259-266`
(no `pypdf`) add *error*-severity findings; `PdfCheckResult.status` (214-219) becomes `fail`;
`_record_pdf_check` (`reporting/renderer.py:1143-1160`) sets the PDF artifact to
`failed-validation`; `_render_report` (1489-1497) raises `ReportRenderError`; the CLI exits
non-zero and the worker marks the job `failed: report generation failed` (`job_service.py:671-673`).
The UI links only `status == "success"` artifacts (`job_service.py:470-472`, `ui.py:526`), so
the kept PDF is invisible. `pdftohtml` is a system package (poppler-utils), not in
`pyproject.toml`. Blocking an unverified PDF is consistent with §12.1, but the manifest
conflates "checker unavailable" with "pagination defect", and the operator loses the PDF.
Present on this host (`/usr/bin/pdftohtml`), so not a Blocker. Fix: a distinct
`unverified` artifact status for tool-unavailable findings, surfaced as a warning in the UI
with the PDF still linked; keep `failed-validation` for real pagination errors.

**M6 — `publish_run` never reads `build_manifest.json` status; a failed/failed-validation revision can be published.**
`dcdc-bench/src/dcdc_bench/publish.py:232-267` checks approval identity and that
`report.html` exists (249-250); `build_manifest.json` is only copied
(`PUBLISHED_REPORT_FILES`, line 40; loop at 282-294). Scenario: HTML built, PDF failed its
pagination check → manifest `status: failed-validation` → `publish_run` produces a public
"issued" copy of that revision (with `include_pdf` it would even copy the failed PDF).
Brief §12.1: "A report validation error must be visible and block an ordinary issued
publication". Fix: refuse unless the revision's `build_manifest.json` has `status ==
"success"` (or require an explicit approval field acknowledging the failure).

**M7 — systemd launcher does not forward the new memory-gate environment; dispatcher and child gates diverge.**
`dcdc-bench/src/dcdc_bench/job_service.py:234-235` forwards only `DCDC_ACTIVITY_LOCK`,
`QUARTO_PATH`, `BROWSER_PATH`, `PATH`. The dispatcher's gate reads
`DCDC_RENDER_MIN_AVAILABLE_MIB` / `..._PLUS_SWAP_FREE_MIB` from the UI's environment
(`job_service.py:390`, `resources.py:20-23`); `services.report_run` re-reads them in the child
(`services.py:112-118`). Under `DCDC_JOB_LAUNCHER=systemd` the child sees defaults
(150/600 MiB). Scenario: operator sets both to 0 to disable the gate on a swap-less host; the
dispatcher launches, the child refuses with "Not enough free memory", job `failed`. Fix: add the
two variables to the forwarded list, or persist the dispatcher's thresholds in the job
directory and have `report_run` honor them. (`PYTHONPATH` is also not forwarded — pre-existing.)

### Minor

**m1 — No UI control to dequeue a `report-queued` job.** `dcdc-bench/src/dcdc_bench/ui.py:582-587`
shows Stop only for `queued/starting/running/acquiring/stopping/cancel_requested`; the
service supports `cancel()` for `report-queued` (`job_service.py:502-508`) but the operator
cannot reach it. Fix: a "Remove from report queue" button for that state.

**m2 — A malformed gate variable makes the queue hang with no recorded reason.**
`job_service.py:390` builds `MemoryGate()` per tick; `resources.py:121-129` raises
`ValueError` on a non-numeric value; `dispatch_reports` propagates, `ui.py:94-95` prints to
stderr every 2 s, and the job never receives a `deferred_reason`. Fix: catch and `_defer`
with the reason.

**m3 — `dispatch_reports` runs a full `list_jobs()` every 2 s while anything is deferred.**
`job_service.py:376` → `status()` per job incl. a 32 KiB tail read of each run's
`samples.jsonl` (448-463). With tens of saved jobs this is steady SD-card IO precisely during
the memory-pressure periods the gate exists for. Fix: a raw `job.json` state scan (as
`_report_queue` does) for the ACTIVE check.

**m4 — Off/indeterminate UVLO steps keep `Pout_W`/`loss_W` and receive bands for them.**
`analysis.py:484-489` nulls only `efficiency_pct`; `uncertainty.py:288-315` then evaluates
`Pout_W`/`loss_W` for a `valid` expected-off step, so standby "loss" points appear in
`fig-loss` alongside operating points with bands. Not fabrication, but misleading. Consider
`output_power_reason`/`loss_reason` for non-`on` states.

**m5 — Thermal window excludes the reading taken right after the last accepted cycle.**
`thermal.py:150-153, 173-174` use `[min start, max end]` of accepted *electrical* cycles;
`runner.py:447-448` reads temperature after each electrical cycle, so the last reading is
always outside the window. With `minimum_complete_cycles == 1` the point gets
`absolute_C=None` ("no temperature reading inside the accepted window"). Fix: accept thermal
rows whose `query_start` lies inside the window, or extend it by one poll interval.

**m6 — Zero-uncertainty "evaluated" bands are constructible.** `domain.py:143-147` allows
`percent_of_reading=percent_of_range=absolute_offset=resolution=0` with status
`datasheet_quoted`; `uncertainty.py:239-242, 281-282` then emits "± 0 … (all declared terms
are zero)" labels and zero-width bands marked `evaluated`. §9.2 forbids zero-uncertainty
results from unknown inputs; these are declared, but a zero readback resolution is not a
physical specification. Fix: `resolution: gt=0` and reject an all-zero limit.

**m7 — `run_doctor` loses the partial diagnosis on a `DoctorRefusal` mid-run.**
`doctor.py:138-139` re-raises the refusal; `atomic_json(target, diagnosis)` at 467 is after
the `try/finally`, so the transcript and findings collected so far are not written (the SCPI
log survives). Fix: write the diagnosis in the `finally` with `exit_code` set.

**m8 — Under systemd, a long thermal acquisition can be killed by `RuntimeMaxSec=2700`.**
`job_service.py:237` (pre-existing cap) now combines with per-point thermal timeouts
(`runner.py:140-141`); a grid of points × `thermal_settling.timeout_s` can exceed 45 min, and
systemd's kill leaves shutdown `UNKNOWN`. Fix: derive the cap from the plan, or apply it only
to report-only workers.

**m9 — `_run_tool` cannot reclaim pipes held by a grandchild that started its own session.**
`renderer.py:1210-1220`: after `_stop_group`, `communicate(timeout=15)` →
`terminate_group(child.pid)` matches only pgrp/session `== child.pid`; a `setsid` grandchild
is invisible, the second `communicate` raises `TimeoutExpired` out of `_run_tool` (format
marked failed — fail-closed), and the holder lives on. Document; consider `prctl(PR_SET_CHILD_SUBREAPER)`.

**m10 — Thermal figures share the electrical figures' `FigureSeries` *instances*.**
`thermal.py:286, 296` pass `series=series`; safe today because `_apply_uncertainty`
(`analysis.py:875-881`) mutates only `FigureSpec`, brittle if anyone mutates a series per
figure. Deep-copy.

### Nit

- `runner.py:132` comment points to `uvlo.run_uvlo_mock` as the procedure to use; nothing calls it (see M3).
- `resources.py:19` `PHASES` contains `"refused"`, which no caller logs.
- `analysis.py:869` `_apply_uncertainty` derives the ± label by splitting on `" ± "`; it works for every label `uncertainty.py` produces but is a format coupling — expose `expanded`/`unit` directly instead.
- `job_service.py:66-72` `_pid_starting` would treat a reused PID as "starting" within the 5 s grace; negligible with sequential Linux PIDs, noted for completeness.
- `test_comparison.py:98-100` should build its budget through `evaluate_run_budget` (ties to M2).

## Checked and found sound

- **Lease fails closed during a render.** The report child holds `bench_activity("report", timeout=0)` for the whole render (`reporting/renderer.py:1348-1351`); `start()` refuses on any ACTIVE job and probes the acquisition lease (`job_service.py:304-308`); CLI acquisitions take the lease with `timeout=0` (`extended.py:223`, `bringup.py:272`). The window between dispatch and the child taking the lease is covered by the job-level ACTIVE check for UI jobs; a CLI acquisition started in that window makes the *render* fail closed — the two never overlap.
- **At most one report-only worker.** `dispatch_reports` runs under the cross-process `FileLock`, flips the record to `queued` (ACTIVE) before `_launch` (395-400), and the UI has a single app-level dispatcher with a busy flag (`ui.py:84-100`). A second UI process on the same root is serialized by the lock and sees ACTIVE.
- **job.json write discipline while ACTIVE.** `retry_report`, `dispatch_reports`, `_defer`, `add_attachment` refuse or skip ACTIVE jobs; `cancel()` on ACTIVE only touches `cancel.request` and signals via `pidfd`. Only the `report-queued` cancel branch violates this (M1).
- **Cancelled acquisitions stay cancelled through the queue.** `acquisition_cancelled` is persisted (`job_service.py:661`) and honored by the report-only worker (675) even though the dispatcher unlinks `cancel.request` (394).
- **Launch grace.** `status()` treats a launch as "starting" only if `launch.requested_utc` is ≤ 5 s old *and* the pid exists and is not a zombie (475-485); the systemd path has no pid and falls to the 120 s expiry (486-488). `_pid_matches` is still required after the grace.
- **`_render_process`** inherits stdout/stderr (no pipes, so no grandchild deadlock on `wait()`), sweeps the session on every exit path via `finally` (609-610), and `_sweep_report_group` never masks the outcome (574-576).
- **`_run_tool`** kills the whole session (SIGTERM → SIGKILL) on timeout and raises `TimeoutExpired` *after* writing the render log (1461-1463), so a timed-out build is never a success. `STATIC_START/IMAGE/CLOSE_TIMEOUT_S = 120/90/15`, `DOCUMENT_TIMEOUT_S = 600` unchanged (`renderer.py:58-61`).
- **`_write_static_figures`** close-timeout branch terminates the Chromium tree and re-raises (1297-1302); venv is Python 3.13 so `TimeoutError` matches `asyncio.wait_for`.
- **`memory_gate.json`** is written by `report_run` into the revision directory before `render_report` (`services.py:143-146`) and picked up at `renderer.py:1378-1380`; `report_run` refuses before writing anything when the gate fails (112-118).
- **`_record_pdf_check`** records a checker crash as a failed check, never as an unverified success; the PDF is kept on disk.
- **Uncertainty cannot invent values.** `evaluated_quantity` checks `schema_version` and `status == "evaluated"` with finite `expanded` (`uncertainty.py:375-384`); `_apply_uncertainty` writes `_lower/_upper/_uncertainty_label` only for those, bands only when `figure.y_key ∈ banded_keys`, metric ± only when the selected point's quantity is evaluated (`analysis.py:849-905`); `ReportModel.uncertainty` defaults to `not_evaluated`; the renderer prints ± only for finite `expanded` (`renderer.py:607-611`). No clamping anywhere (`_quantity_result` is `value ± k·u_c`).
- **§9.2 policy.** Non-valid points are never evaluated (`uncertainty.py:262-267`); missing terms → `not_evaluated` with reasons, never zero (135-137, 291-311); systematic terms are not divided by n (160-171); repeatability is recorded separately and optionally included; efficiency in percentage points, loss in watts with its own propagation; near-zero handled by the declared relative bound — efficiency is *not* evaluated when it trips (297-305); `k` recorded and never described as 95 %.
- **UVLO off-steps never receive efficiency.** `_uvlo_analysis` nulls `efficiency_pct` and marks requirements `not-applicable` before the budget runs (`analysis.py:495-503`), so `evaluate_point` reports efficiency `not_evaluated` with the recorded reason (`uncertainty.py:292-295`). Off outside the expected phase → `inconclusive`. A known worker/analysis state disagreement raises (409-411). `uvlo_ramp_brackets` never interpolates and flags a non-positive hysteresis lower bound (335-336).
- **Domain/planning guards.** Mock thermal adapter rejected on a real bench (`domain.py:364-366`) and again in `MockThermalProvider.for_bench` (`mock_thermal.py:63-67`); mock mode refuses non-synthetic adapters and thermal tests without bound sensor channels (`planning.py:116-130`); UVLO requires `uvlo_approved`, a matching `protective_policy_id` and three declared absolute limits in *both* modes (`planning.py:53-72, 199-202`), real adds `missing_approvals`; steps below the floor are refused, never clipped (75-90); `run_uvlo_mock` refuses real profiles and any non-executable step (`uvlo.py:80-83, 297-298`); `guard()` applies absolute limits before any phase scoping (150-177); no global ignore-safety flag.
- **Runner thermal settling** starts only after electrical settling and not limiting, clears its window on any electrically invalid cycle, ends at timeout as `inconclusive` (never "met"), and records `thermal_settling` on every point of a thermal test (`runner.py:411-460, 500-504`).
- **Doctor is read-only.** `VisaTransport.open()` only opens a VISA session (`Software/src/benchctl/transport.py:69-84`); every driver method the doctor calls is a query; `ReadOnlyTransport.write` refuses and `query` is allowlisted (`doctor.py:69-94`); `SYST:ERR?`, `*CLS`, `*RST` are never issued; the cadence probe refuses unless both outputs read OFF (443-451); diagnostics are refused inside a run folder (97-105).
- **Immutability (§8.4).** `add_attachment` verifies integrity before and after (`job_service.py:418-420`); annotations are bound to an asset hash via `AssetStore.resolve` (`annotations.py:95-101`); the report copy of the photograph is re-hashed (`sensor_placement.py:134-135`); a hash mismatch is an error, never a skip; every label/caption is escaped.
- **Publication safety (except M6).** Approval must name the run and revision; the target may not lie inside the run folder; targets are immutable; the PDF is copied only under `include_pdf` with a "not text-redacted" warning.
- **`FORMULA_VERSION`** bumped to `settled-dc-1.2` (`analysis.py:26`) — warranted, the analysis output shape changed (uncertainty, uvlo, thermal).
- **UI understands the new state.** `state_label` has `report-queued` (`ui_models.py:92`), the Run panel shows the deferral reason (`ui.py:548-550`), and `report-queued` is correctly *not* counted as active for `can_start()` (`ui.py:617, 647-657`). Extra fields (`report_pending`, `queued_utc`, `dispatched_utc`, `action`) are ignored harmlessly.

## Residual risks

- Real UVLO execution does not exist; `UvloInputRampProcedure.execute` has only the mock context. Real off-state readbacks are exactly where M4 bites.
- The comparison module never renders documents itself (`write_comparison` writes Plotly JSON); the `kind == "comparison"` dispatch hooks in the shared renderer are exercised only by tests.
- `pdf_check` heuristics (orphan headings, lone table rows, sparse pages) are error-severity; a false positive fails an otherwise good report with no operator override other than editing the template.
- systemd launcher path: neither `PYTHONPATH` nor the memory-gate variables are forwarded (M7); the 45 min `RuntimeMaxSec` cap also applies to acquisition workers (m8).
- `dispatch_reports` IO cost while deferred (m3) is highest exactly when memory is low.
- Nothing here was executed. All statements are from reading the merged tree; the two most consequential integration claims (M2, M3) were confirmed by grep for callers/keys, not by running code.
