# QA review of the simulated-bench flow

Agent-role QA/test review of the one-page bench UI on the *Simulated bench* tile,
performed by reading and tracing code at commit `b38df08` of
`dcdc-bench-hardening`. No UI server, renderer, demo or job was run and no
instrument was touched. Line numbers refer to that commit.

## Method

- Traced, end to end, the path a click takes: `ui.py` (page handlers, poll,
  Stop, Reports, `/annotations` registration) → `ui_models.py` (pure
  presentation) → `job_service.py` (`preview`, `start`, `cancel`,
  `dispatch_reports`, `retry_report`, `status`, the worker) →
  `services.acquire_mock` → `runner.run_mock` (spawned mock plant,
  cancellation) → `activity.bench_activity` (lease) → `resources.MemoryGate`.
- Confirmed the simulated path never reaches `real_backend.py`: it is imported
  only under `plan.bench.mode == "real"` (`job_service.py:344, 445, 744, 864`);
  `acquire_mock` dispatches to `runner`, `uvlo` or `supply_profiles`, none of
  which import a driver. The inventory read at page load (`inventory_models`)
  is `benchctl.config.load_config`, a YAML/pydantic parser.
- Mapped the six test files named in the brief against the observable states
  below (coverage column of the state table; gaps in "Proposed tests").
- Checked the owner's deployment facts that decide several answers: the user
  unit `~/.config/systemd/user/benchctl-report.service` sets
  `Environment=DCDC_JOB_LAUNCHER=systemd`, so every worker is its own transient
  unit (`Restart=no`, `RuntimeMaxSec=2700`, `KillMode=control-group`,
  `job_service.py:385-390`); `filelock==4.0.4` (thread-local by default, so the
  in-process lease probe fails closed across NiceGUI's thread pool);
  `nicegui==3.17.1`.
- One test run: `dcdc-bench/tests/test_ui.py` (54 passed in 14 s) after
  adding the single trivial test described under "Proposed tests".
- The reproduction steps below are written for the page but were **not
  executed** here; each is derived from the traced code and says which lines
  produce the behaviour.

Verdict in one line: the simulated flow is fail-closed at the service (one
owner per bench, append-only evidence, no hardware path), but the page only
follows a job it started or was pointed at, so several ordinary situations
(refresh, a second tab, a queued report) leave the header and the controls
telling the operator something that is no longer true.

## The observable state machine

Job states come from `job.json` plus `JobService.status()` derivation; the
page maps them through `state_label`, `activity_text` and `job_actions`
(`ui_models.py:119-142, 231-257`). "Locked" means the three question sections
get `.bench-locked` (`ui.py:1064-1065`).

| State (how the page learns it) | Header pill | Run section | Reports row | Enabled | On F5 (page reload) | Covered by |
| --- | --- | --- | --- | --- | --- | --- |
| **Idle**, nothing previewed | `Idle — nothing switched on` | placeholder text | all saved runs, newest 30 | Preview (needs converter + bench + test); Start disabled; Rename/Edit/Duplicate/Delete/+ Add | same | `test_page_asks_three_questions…`, `test_idle_page…` |
| **Previewed** (`state['preview']` set) | Idle | placeholder | — | Start enabled iff `supported` and no errors (`ui.py:1051-1054`); Notes textarea | plan panel gone (client-side only); preview file stays under `previews/` | `test_card_selection…`, `test_a_test_the_planner_cannot_run…` |
| **Stale** (selection or any profile save after Preview) | Idle | — | — | Start disabled; panel dimmed with the note (`ui.py:422-433`) | as idle | `test_card_selection…` |
| **queued** (`start()` wrote job.json, worker not yet `acquiring`) | `Queued — waiting for the worker to start` + start time + elapsed | `Waiting to start` | `Waiting to start` | Stop… (arms) → Confirm stop / Keep running; questions locked; Preview/Start disabled | attaches (`ui.py:1584-1588`) | `test_header_shows_background_activity…` (state cycled by poll only) |
| **acquiring** | `Acquiring… point k of N` | live Vin/Iin/Vout/Iout, progress bar, `Measuring this condition`, recent events | `Acquiring measurements` + `k / N points` | Stop… ; locked | attaches | same; `test_run02_refresh…` (integration, service level) |
| **Stop requested** (`cancel.request` exists, state still acquiring) | `Stopping… waiting for both outputs to be verified OFF` | `Stop requested — waiting for the worker` | same | nothing (Stop area shows a label) | attaches | `test_stop_is_a_two_step_control…` |
| **report-queued** (acquisition worker exited, outputs verified OFF) | `Report queued — starts when the bench is idle` | `Measurements saved — report queued` + `Report queued: <time>`; **Remove from report queue** | `Measurements saved — report queued`; Remove from report queue | questions unlocked; Preview and a new Start allowed (by design, `job_service.py:49-51`) | **does not attach** — header says Idle, Run section shows the placeholder (Major M1) | dispatcher: `test_report_queue.py`; page: only via poll in `test_header_shows…` |
| **deferred** (report-queued with `deferred_reason`) | `Report queued — waiting: MemAvailable below 150 MiB` | same + `Waiting: <reason>.` | same as report-queued (**no reason shown**, minor m4) | same | same as report-queued | `test_dispatch_defers…` (service) — page not covered |
| **queued (action=report-only)** then **reporting** | `Queued — waiting for the worker to start`, then `Generating report…` | `Preparing HTML and PDF` + `Report started: <time>` + the "several minutes on a Raspberry Pi" note | `Preparing HTML and PDF` | **no Stop** (`job_actions` returns `[]` for reporting, minor m3); locked | attaches | `test_header_shows…` (poll), `test_run_panel_offers_stop…` |
| **completed** | Idle; toast `Report ready: <run id>` once | `Complete`, Open HTML / Open PDF / Report data JSON, verified-OFF line | `Complete` badge, Open HTML/PDF, View run, Regenerate report | Regenerate (queues a report-only worker, never acquisition) | idle; the run is reachable via View run | `test_reports_follow_the_job…`, `test_run02_opening_an_old…` |
| **completed, unverified PDF** (`manifest.status == "unverified"`) | Idle | `Complete` + warning box with `report_note`; link `Open PDF (not verified: checker tool missing)` | `Complete`; same link label | Regenerate | idle | `test_unverified_pdf_check…`, `test_kept_report_artifacts…` |
| **failed, PDF failed layout check** | Idle | `Needs attention` + error; `Open PDF (failed the layout check; kept for inspection)`; `Report generation needs attention: PDF` | `Needs attention` | Regenerate | idle | `test_failed_pdf_validation…` |
| **cancelled** (operator stop, report rendered) | Idle | `Stopped`; `Stop requested: <time>`; links to the partial report | `Stopped` | Regenerate | idle | `test_stop_is_a_two_step…`, `test_operator_stop_during_acquisition…` |
| **cancelled** (dequeued from the report queue) | Idle | `Stopped` + `Report generation was removed from the queue…` + misleading `Report generation needs attention: HTML, PDF` (minor m7) | `Stopped` | Regenerate | idle | `test_cancel_removes_a_queued_report…` (service) |
| **aborted** (`execution_status` error/aborted, report rendered) | Idle | `Acquisition stopped` | `Acquisition stopped` | Regenerate | idle | runner scenarios only (`test_controlled_abort…`) |
| **failed** (launch failed, launch expired, worker died, report failed) | Idle | `Needs attention` + `error` text | `Needs attention` | Regenerate iff a run dir exists | idle | `test_launch_is_detached…`, `test_expired_worker…`, `test_worker_import_failure…` |

### Scenario walk-throughs

**Browser refresh.** Page load lists jobs and attaches to the first whose
state is in `('queued','starting','running','acquiring','stopping',
'cancel_requested','analyzing','rendering','reporting')` (`ui.py:1584-1588`).
`report-queued` is missing from that tuple although `activity_text` treats it
as background work (`ui_models.py:231-232`), so an F5 in the window between
"outputs verified OFF" and the dispatcher's launch (normally 2–4 s; unbounded
while the memory gate or lease defers) lands on an idle header. Nothing on
the page ever polls again until the operator presses **View run** or
**Refresh saved runs**, because `poll()` returns immediately without a
`job_id` (`ui.py:1465-1466`). During `queued`/`acquiring`/`reporting` the
reload attaches correctly and `test_run02_refresh…` proves no second owner is
created.

**Double-click.** *Preview* is guarded (`preview_busy`, `ui.py:1120`).
*Start* is not: two clicks before the disable reaches the browser run
`service.start` twice; the second waits on the service lock, sees the first
job `queued` and raises `A job is already acquiring or reporting; no
automatic hardware queue` — one job, one spurious red toast (m2). *Confirm
stop* is not guarded either and the second `cancel()` sends a second SIGINT
(Major M3). *Regenerate report* twice re-queues harmlessly or, if the
dispatcher launched in between, toasts `An acquisition/report job is already
active`. *Remove from report queue* twice is a no-op.

**Two tabs.** Each tab has its own `state`. Tab A starts a job; Tab B, which
has no `job_id`, never polls, so its header stays Idle, its questions stay
unlocked and (after a Preview) its Start stays enabled. Pressing it is refused
by the service (`job_service.py:457-458`) and nothing is launched — covered by
the new test — but Tab B then re-enables Start with the same stale plan
(`ui.py:1239-1243`, m1). If Tab B presses Preview while Tab A's job is active,
`remember_jobs` locks Tab B (`ui.py:1137-1140, 1390-1394`) and nothing ever
unlocks it except **Refresh saved runs** or F5. Two tabs pressing Start
together are serialized by the service lock; the loser is refused. Profile
edits in one tab invalidate the other's plan at Start with `A saved profile
changed; preview and confirm the new plan` (`job_service.py:436-437`).

**Stop during settling vs. acquiring.** `cancel()` writes `cancel.request`
with the UTC time and SIGINTs the worker (`job_service.py:706-716`);
`run_mock` catches the KeyboardInterrupt around `worker.join`, sets the
multiprocessing cancel event and waits (`runner.py:181-185`). The plant loop
checks the event between points (`runner.py:359`), each settling cycle
(`:387`) and each acquisition cycle (`:465`); the interrupted point is
qualified `not-run` / `cancelled before a complete acquisition window`
(`:479-482`), execution status `aborted`, both outputs commanded OFF and
verified (`:525-543`), then the worker records `report-queued` with
`acquisition_cancelled_utc` (`job_service.py:886-888`) and the report renders
as `cancelled`. Settling and acquiring behave identically; the only difference
is whether the current point has accepted cycles (it has none in either case).
Stop during `queued` (before exec) leaves a marker the worker honours
(`job_service.py:852-854`). Stop during `reporting` is not offered.

**Saving a profile mid-run.** Allowed by the service (`save_profile` has no
active check, `job_service.py:309-318`); the job runs from its `plan.json`
snapshot, so nothing changes for it. The page prevents it with
`pointer-events:none` only (`ui.py:107`); Tab + Enter still reaches every card
and editor (`ui.py:782-784, 805-807`, m5). Approving limits or toggling the
12 V / 24 V class also saves a profile and would go through the same way.

**Deleting a profile used by a queued job.** `queued`, `acquiring` and
`reporting` are refused with `The recipe profile 'x' is used by the active
job <id>; wait for it to finish` (`job_service.py:269-283`), shown as a toast.
A `report-queued` job is *pending, not active*: its profiles can be deleted;
the report-only worker needs only `plan.json`, and the Reports row falls back
to the title recorded at Start (`ui_models.py:426-428`). Correct by design.

**Network blip.** NiceGUI keeps the client for `reconnect_timeout=30 s`
(`ui.py:1592`); shorter blips resume the same page state and timer. Longer
ones delete the client; the browser reloads and the "Browser refresh" row
applies. The worker is unaffected (own session / own transient unit).

**Service restart mid-job.** With the owner's `DCDC_JOB_LAUNCHER=systemd`
each worker is a transient unit outside the UI's cgroup, so `systemctl --user
restart benchctl-report` leaves acquisition and rendering running; the new UI
process resumes dispatching at startup (`ui.py:262`) and a reload attaches
(except in report-queued, M1). `_seed()` recreates deleted seeded profiles on
every start (`job_service.py:172-206`), which the page's own hint text
announces. A UI process running by hand with the default `detached` launcher
also survives (`start_new_session=True`, `job_service.py:401-402`).

**Memory-gate deferral for a long time.** The oldest report-queued job gets
`deferred_reason`/`deferred_utc` and a log line at most every 60 s
(`job_service.py:605-623`); it never expires and never fails. The page shows
the reason in the header pill and the Run section **only while it is polling
that job**; the Reports row shows `Measurements saved — report queued` with no
reason (m4). There is no "try now"; the operator can wait or dequeue. A new
simulated test may be started meanwhile and takes priority.

## Input validation and the Preview

Profile forms (`ui.py:604-763`) apply `edited_dut` / `edited_recipe` and then
pydantic (`domain.py`, `extra="forbid", strict=True, allow_inf_nan=False`):

| Input | Result |
| --- | --- |
| Voltage/load lists: empty, `nan`, `inf`, negative, `1:5`, `1+2`, duplicates, >1000 values | Refused with an operator sentence (`ui_models.py:12-26`; `test_grid_rejects…`). `0` is allowed for loads only. |
| Ratings ≤ 0, min > max | Refused by pydantic; message is the field path plus text (`ui.py:361-366`). |
| Dwell/duration/percent cleared (`ui.number` → `None`) | `float(None)` → `TypeError` → toast `float() argument must be a string or a real number, not 'NoneType'` (`ui_models.py:36, 65-68`; m6). |
| Dwell > 30 s | Refused by `Settling timeout must allow the minimum dwell` — `timeout_s` is not a visible field (m6). |
| Efficiency 0 % or > 100 %, budget 0 % or > 100 % | Refused (`domain.py:628-629`). |
| Very long title/category/description | No length cap; the 2 MB profile cap applies (`job_service.py:312`). Cards wrap (`overflow-wrap:anywhere`). |
| HTML in names/titles/notes | Rendered through `ui.label` / Quasar text bindings — escaped; `ui.notify` uses plain text. Not re-checked inside the rendered report. |
| File name (`profile_id`/`recipe_id`) with spaces, `..`, > 101 chars | Refused by the pattern / `_name()` (`job_service.py:32, 68-71`). |
| Existing file name in **Add**/**New** | **Silently overwrites** the saved profile (M4). |
| Grid size | Per-axis ≤ 1000, per-recipe ≤ 10,000 points (`domain.py:586-587, 695-696`); no wall-time bound (M2). |

Preview (`job_service.py:336-363`, `ui.py:1067-1117`): every requested point
stays in the plan with `executable` / `assumption_limited` (`Outside planning
budget`) / `unsupported` (`Not supported`) / `approval_blocked` (`Needs
approval`); the panel shows `Points that will run k / N`, `Skipped`, identical
reasons merged with counts, the full table, and `Before Start` errors.
`supported` is false when no point is executable (`No feasible point is
available`), which disables Start. Verified in `test_card_selection…` (2 of
21 assumption-limited on the seeded quick sweep: 0.75 A and 1 A at 12 V exceed
the 0.72 A planning budget) and `test_a_test_the_planner_cannot_run…` (100 V
→ 0 / 7). On the simulated bench the estimated time reads `simulated ·
seconds` — see M2 for why that can be wrong.

## Concurrency (question 3)

- *Two simulated jobs from two tabs*: impossible. `start()` re-validates
  profile hashes, checks `ACTIVE` and probes the acquisition lease under one
  cross-process `FileLock` (`job_service.py:427-461`); the second caller is
  refused before a job directory exists. Covered at the service level by
  `test_run02_refresh…` and at the page level by the new test.
- *Start while a report is queued*: allowed by design (acquisition has
  priority; `job_service.py:49-51` and the "Job state machine" section of
  `pi-process-model.md`). The
  dispatcher waits while the new job is ACTIVE and then renders the oldest
  queued report first. Page consequence: while that older report renders, the
  page (polling the new job) says `Report queued — starts when the bench is
  idle` and keeps Start enabled; a Start is refused with the "already
  acquiring or reporting" toast (M1 family).
- *Lease orders*: acquisition worker holds `acquisition` for the whole mock
  run (`job_service.py:871`); the renderer holds `report` for the whole render
  (`reporting/renderer.py:1588`); the dispatcher probes `report` before
  launching (`:559`) and `start()` probes `acquisition` (`:460`), both with
  `timeout=0`. Every order fails closed; the dispatcher additionally re-reads
  `job.json` under the service lock so a cancel racing a dispatch cannot
  resurrect the job (`test_cancel_racing_dispatch…`). Two UI processes on the
  same workspace share `.service.lock`, so double dispatch is also excluded.

## Evidence integrity for simulated runs (question 4)

No UI action can delete, rename or overwrite a job or run directory:

- **Delete** removes only `profiles/<kind>/<name>.json`
  (`job_service.py:274-283`) after `_refuse_if_active`; the prompt text
  `Past runs keep their own copy` is accurate because each job carries
  `plan.json` and the run carries `plan.json`/`request.json` again.
- **Rename** on the page changes the display title or converter model through
  `save_profile` (`ui.py:560-573`); the file name never changes. The service's
  `rename_profile` (which does move a file, atomically, new-before-old) is not
  wired to the page.
- Job directories are `<UTC>_<uuid8>` (`job_service.py:462-464`); run
  directories are created with `mkdir(exist_ok=False)` (`storage.py:55`);
  report revisions `rNNNN` are created with a plain `mkdir` and increment on
  `FileExistsError` (`services.py:129-137`). `retry_report` only adds a
  revision; `add_attachment` verifies `integrity.json` before and after
  (`job_service.py:599-601`); `resolve_file` is read-only and confined to the
  job (`:721-730`).
- Runs are finalized once with `integrity.json` (`storage.py:76-97`); any
  later edit is detected (`verify_integrity`, `test_evidence_hash_detects_changes`).

Residual risks are about *unfinalized* evidence, not loss: a worker killed by
`RuntimeMaxSec` or a double SIGINT (M2, M3) leaves `run.json` at `running`
with no `integrity.json`; the Reports row still offers **Regenerate report**,
which fails with a raw `OSError` toast naming `integrity.json`. `previews/`
accumulates one JSON per plan hash forever (m10).

## Findings

Ranking: **Blocker** = evidence, hardware or the flow itself at risk; **Major**
= the operator is misled or blocked in an ordinary sequence; **Minor** =
polish, wording, hygiene.

### Blocker

None found. The simulated path has no route to `real_backend`, evidence is
append-only and hashed, and every concurrent order is refused at the service.

### Major

**M1 — The page only follows a job it started or was pointed at.**
`ui.py:1465-1466` (`poll` returns without `job_id`), `1584-1588` (attach list
omits `report-queued`), `1390-1394` and `1137-1140` (`state['active']` is
refreshed only by a Preview or a Reports refresh).
Reproduce: (a) Simulated bench → Preview → Start simulated test; when the pill
reads `Report queued…`, press F5 → header `Idle — nothing switched on`, Run
section shows the placeholder, the deferral reason (if any) is nowhere; the
report still renders and the Reports row eventually flips to Complete only
after **Refresh saved runs**. (b) Open two tabs; in A: Preview + Start; B keeps
`Idle`, unlocked, and after a Preview its Start is enabled; pressing it toasts
`A job is already acquiring or reporting; no automatic hardware queue` and B
re-enables Start. (c) In B press Preview *while* A's job runs → B locks its
three questions and stays locked after A finishes until Refresh saved runs.
Fix: poll a cheap `service.active_job()` (job.json records only, as
`_job_records` does) every tick regardless of `job_id`, attach on load to
`report-queued` too, and drive the header, the lock and `can_start()` from it.

**M2 — A simulated run has no wall-time bound or estimate and is hard-killed
at 45 minutes with unfinalized evidence.** The mock plant fsyncs every JSONL
record (`storage.py:65-74`); the runner's own comment says a flat deadline
"interrupted healthy runs on a loaded SD card" and sizes its timeout from the
record count (`runner.py:141-154`). The seeded 21-point sweep writes roughly
120 records per point; a 30 × 30 grid or a 3600 s `duration_s` (both accepted:
`domain.py:586-587, 653, 695-696`) writes 10⁵–10⁶ fsyncs. The owner's transient
units carry `RuntimeMaxSec=2700` with `KillMode=control-group`
(`job_service.py:385-390`): SIGTERM ends the worker and the plant child with
no finalize, `status()` then reports `failed` with `Worker exited
unexpectedly; inspect shutdown evidence before another real run`
(`job_service.py:671`) for a run that never touched hardware, and Regenerate
fails on the missing `integrity.json`. The card says only `N points ·
simulated` and the plan panel `simulated · seconds` (`ui_models.py:332-336`,
`ui.py:1087`). Wall time was not measured here.
Reproduce: + New test → Input voltages `9, 10, 11, … 36` (28 values), Output
loads `0, 0.05, …, 1.45` (30 values) → Save → Preview (840 requested points;
the planner skips the heavier loads at low input, several hundred still run)
→ Start; or the seeded test with `Measure each load for (s)` = 3600.
Fix: estimate the record count at Preview (the runner already computes it),
show it on the card and panel, refuse above the unit budget; have the worker
trap SIGTERM and finalize the run as `interrupted`; say "simulated" in the
dead-worker message when `mode == "mock"`.

**M3 — Double-clicking Confirm stop sends two SIGINTs and breaks the mock
cancel path.** `stop_confirmed` has no busy guard (`ui.py:1247-1254, 1282`);
`cancel()` rewrites the marker (losing the first stop time) and signals again
whenever the state is still ACTIVE (`job_service.py:701-716`). The second
KeyboardInterrupt lands inside `run_mock`'s own handler (`runner.py:183-185`),
propagates out of `acquire_mock` and is caught by the worker
(`job_service.py:910-911`), which records `cancelled` with `Operator cancelled
the job; inspect recorded shutdown status`, releases the lease and exits;
`multiprocessing` joins the plant child at interpreter exit, so the run is
finalized, but the report is never queued and the recorded stop time is the
second click's. If the second signal arrives before `cancel.set()` the plant
runs to completion under a job that says `Stopped`.
Reproduce: Start the seeded sweep → Stop… → double-click Confirm stop within
~100 ms → Reports row `Stopped`, no report links, Run section warns about
shutdown status; Regenerate report recovers the PDF/HTML.
Fix: disable the button on first click (or a `stop_busy` flag); make
`cancel()` idempotent while `cancel.request` exists (do not rewrite, do not
re-signal); wrap the handler in `run_mock` so a second KeyboardInterrupt still
waits for the child.

**M4 — "Add a converter" / "New test" silently overwrite an existing saved
profile.** The editors call `save_profile` (`ui.py:646-653, 723-731`), which
writes whatever identifier the form holds (`job_service.py:309-318`); nothing
checks `exists()` for a new profile. Past runs are unaffected, but the
converter's ratings and real-bench approvals are replaced without a prompt.
Reproduce: + Add a converter → `Save converter as` = `12t12-4a`, Minimum
input 20 → Save converter → the seeded 12T12-4A card now reads `20–36 V in`.
Related: Edit + changing the file name leaves the old file, producing two
cards.
Fix: `save_profile(kind, data, overwrite=False)` from the Add/New editors with
the message `A converter with this file name already exists`.

### Minor

- **m1** A refused Start (profile changed, job active) leaves the plan valid
  and Start enabled (`ui.py:1239-1243`); call `changed('Start was refused —
  Preview again.')` on `ValueError`.
- **m2** Start and Regenerate are not single-shot (`ui.py:1202-1216,
  1294-1302`); one job is created but a red toast appears on the second click.
- **m3** No Stop during `Generating report…` (`ui_models.py:121-123`); a stuck
  render waits for the 1800 s child timeout (`job_service.py:811`). Document,
  or offer "Stop report" that signals the report-only worker.
- **m4** The Reports row never shows `deferred_reason` (`ui_models.py:417-440`);
  with M1 a long deferral is invisible after a reload.
- **m5** `.bench-locked` is `pointer-events:none` only (`ui.py:107`); keyboard
  users can change selections and open editors during a run. Harmless to the
  job, contrary to the doc's "the three questions are locked".
- **m6** Editor errors in developer language: cleared number → `float()
  argument must be…` (`ui_models.py:36, 65-68`); dwell > 30 s names the hidden
  `timeout_s` (`domain.py:645-649`).
- **m7** A job the operator dequeued shows `Report generation needs attention:
  HTML, PDF` (`ui.py:1372-1378`); distinguish "no report was generated".
- **m8** Reports lists only the newest 30 runs without saying so
  (`ui.py:1405`); older runs are reachable only through `/annotations`.
- **m9** Delete/Rename leave an open editor for the same profile; Save
  recreates it (`ui.py:539-552` never calls `close_editor`).
- **m10** `previews/<hash>.json` is never pruned (`job_service.py:362`).
- **m11** Preview rewrites the saved recipe's `dut_profile_id`
  (`ui.py:1131-1135`); another tab previewing the same test with a different
  converter is invalidated with the generic `A saved profile changed`.
- **m12** Notes are truncated to 10,000 characters without notice
  (`job_service.py:466`).
- **m13** Mock-mode jobs surface real-bench wording: `inspect shutdown evidence
  before another real run` (`job_service.py:671`), `inspect recorded shutdown
  status` (`:911`).

## Proposed tests

Existing coverage is strong on the pure helpers, the service state machine
and the dispatcher; thin on the page's reaction to jobs it did not start and
on the real signal path of a mock cancel. Names with a one-line intent; "fails
today" marks a test that documents a finding above.

| Test (file) | Intent | Today |
| --- | --- | --- |
| `test_start_from_a_tab_that_missed_another_tabs_job_is_refused_and_launches_nothing` (test_ui.py) | Tab previewed while idle, another tab started a job; Start is refused, no job dir, no `Popen`. **Added in this commit**; passes. | passes |
| `test_page_load_attaches_to_a_report_queued_job_and_shows_its_deferral_reason` (test_ui.py) | F5 during report-queued/deferred shows the pill, the Run section and the reason. | fails (M1) |
| `test_an_idle_tab_discovers_a_job_started_elsewhere_within_one_poll` (test_ui.py) | With no `job_id`, one poll tick locks the questions and shows the pill when a job is active; unlocks when it ends. | fails (M1) |
| `test_confirm_stop_is_single_shot_and_cancel_is_idempotent` (test_ui.py + test_job_service.py) | Two clicks → one `cancel()`; a second `cancel()` with the marker present re-signals nothing and keeps the first stop time. | fails (M3) |
| `test_second_keyboard_interrupt_during_run_mock_cancel_still_finalizes_and_queues_the_report` (test_job_service.py) | Raise KeyboardInterrupt inside `run_mock`'s handler; the worker must still reach `report-queued`. | fails (M3) |
| `test_add_converter_or_new_test_refuses_an_existing_file_name` (test_ui.py) | Add with the seeded name → warning toast, file bytes unchanged. | fails (M4) |
| `test_simulated_card_and_plan_show_a_record_count_and_refuse_grids_beyond_the_run_budget` (test_ui.py / test_job_service.py) | 840-point grid or 3600 s duration is flagged at Preview, not discovered at minute 45. | fails (M2) |
| `test_worker_sigterm_finalizes_partial_evidence_before_exit` (test_job_service.py) | SIGTERM to the acquisition worker → `run.json` interrupted and `integrity.json` written. | fails (M2) |
| `test_stop_during_settling_and_during_acquisition_both_end_report_queued_verified_off` (test_runner.py) | Set the cancel event from a thread in each phase of an in-process `run_mock`; both give `not-run`, verified OFF, `report-queued`. | should pass (regression for Q1) |
| `test_refused_start_marks_the_plan_stale` (test_ui.py) | After `A saved profile changed…` Start is disabled until Preview. | fails (m1) |
| `test_double_click_start_creates_one_job_and_no_error_toast` (test_ui.py) | Two Start clicks in one tick → one job, no negative notice. | fails (m2) |
| `test_editor_errors_use_operator_language` (test_ui.py) | Cleared dwell, 0 % efficiency, dwell > 30 s each give a sentence naming a visible field. | fails (m6) |
| `test_dequeued_job_does_not_claim_a_failed_report` (test_ui.py) | Run section wording for a dequeued job. | fails (m7) |
| `test_keyboard_enter_cannot_change_selections_while_a_job_runs` (test_ui.py) | `keydown.enter` on a card while active is a no-op. | fails (m5) |
| `test_delete_closes_an_open_editor_for_the_same_profile` (test_ui.py) | Open Edit, Delete the card, Save is gone / does not recreate the file. | fails (m9) |
| `test_preview_with_only_assumption_limited_points_disables_start_and_lists_the_budget_reason` (test_ui.py) | Loads all above the 12 V budget → `0 / N`, `No feasible point is available`, one merged reason. | should pass (regression for Q2) |

## Top 5 changes before the owner's review

1. **Make the page follow the bench, not a job id** (M1, m4): poll a cheap
   `active_job()` every 2 s whatever `state['job_id']` is; include
   `report-queued` in the page-load attach list; show `deferred_reason` in the
   Reports row. This removes the Idle-header-while-working cases on refresh,
   in a second tab and while an older report renders.
2. **Single-shot Stop/Start/Regenerate and an idempotent `cancel()`** (M3,
   m2, m1): disable on first click; do not rewrite `cancel.request` or
   re-signal while it exists; make `run_mock` tolerate a second
   KeyboardInterrupt; mark the plan stale after any refused Start.
3. **Bound the simulated run** (M2, m13): estimate the fsync'd record count at
   Preview (the runner's arithmetic already exists), show it on the card and
   panel, refuse above the transient unit's budget, trap SIGTERM in the worker
   so a killed run is finalized as `interrupted`, and drop the real-bench
   wording from mock-mode messages.
4. **Refuse to overwrite an existing profile from Add / New** (M4, m9): an
   `overwrite=False` save from the add editors with an operator sentence; close
   an open editor when its profile is deleted.
5. **Operator-language validation in the editors** (m6, m7): translate the
   `float(None)` and `timeout_s` cases and distinguish "removed from the
   queue" from "report failed" in the Run section.
