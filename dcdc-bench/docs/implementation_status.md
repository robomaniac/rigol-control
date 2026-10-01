# Implementation status

## Current position

**Status as of 2026-09-28 (branch dcdc-bench-hardening): M0 reached; M1 substantially reached; M2 partial (software side implemented: structured uncertainty budget, read-only `doctor`, outputs-OFF readback-cadence probe; the real bench's freshness, readback accuracy and uncertainty stay unquantified until datasheet/calibration terms are entered and qualified on the bench; enabled-no-load unqualified); an M3 workflow slice demonstrated but M3 not complete by the spec's exit criteria; M4 software implemented on mock and stored data (paired-run comparison, sensor-placement editor with attachment hygiene, synthetic thermal channel with thermal settling) but M4 exit not met (no real temperature adapter; no comparison document rendered); M5 partial (UVLO input-ramp procedure on the synthetic plant only; full-power source, scope tests and public examples not started).**

This position follows the exit criteria in
[Section 15 of the brief](implementation-brief.md#15-implementation-milestones)
and is stated identically in [acceptance.md](acceptance.md) and the
[README](../README.md). The demonstrated M3 slice is real: the UI Start
callback completed a three-point acquisition after client disconnect, verified
OFF and produced HTML/PDF automatically. It does not satisfy M3 because M2
qualification is a prerequisite and remains open. This reconciliation was
performed by an automated agent role against the current code, not by a human
or external reviewer.

| Milestone | Status | Delivered and remaining |
| --- | --- | --- |
| M0 — contracts and planning | Complete | Typed DUT/bench/recipe profiles, constraint checks and feasible-point planning for the initial steady-state scope. |
| M1 — mock run to HTML/PDF | Substantially reached | Normal, setup-limited and aborted mock runs; retained evidence, interactive reports and vector PDFs with recorded acceptance checks at the initial checkpoint. On 2026-09-28 the 15 browser/PDF-marked gates ran on the bench computer (Raspberry Pi 4, system Chromium): 14 passed, 1 skipped (sequence-report figure absent from the demo); the run exposed and fixed a missing table scroll wrapper at 390 px and a PDF-02 lone-table-row in the normal demo. Remaining M1 caveat: the demo is synthetic by design. |
| M2 — supervised real point | Partial | Loaded bring-up, protection readbacks, timing, provenance and verified shutdown work in fixed and configured real procedures. Software side added on this branch: the structured readback uncertainty budget (`uncertainty.py`; real profiles carry `status: unknown` until datasheet/calibration terms are entered), the read-only `doctor` command and the outputs-OFF readback-cadence probe (fake-SCPI tested only), the written [M2 qualification plan](m2-qualification-plan.md) and the [12 V cold-start hypothesis](cold-start-hypothesis.md). Plan steps 1–3 (software-only) were completed on 2026-09-29: DP821A/DL3031A datasheet readback and programming terms transcribed with page references into [instrument-specifications.md](instrument-specifications.md) and the sourced profile `profiles/bench/rigol-dp821a-dl3031a.yaml` (calibration status unknown); the historical SCPI transcripts analysed in [m2-freshness-and-readback-evidence.md](m2-freshness-and-readback-evidence.md) (load readback ≲1.15 s, source readback resolution-bound, load zero-current readback bistable 0 / ≈11 mA, no instrument range ever logged); per-point budget records with an `unquantified` fall-through and an enabled-no-load acquisition/analysis path added with fake-SCPI tests; the acquisition change to the configured real path passed its independent (agent-role) safety review, closed in commit `523dab4` on 2026-09-29 (ordering tests, offset sign, time estimate, load readback evidence), as HANDOFF section 9 records; the `NO_LOAD_IIN_SPAN_A = 2 mA` settling criterion and the longer load-on delay still need the owner's confirmation before the next real run. The owner-authorized read-only `doctor` run on the real bench (2026-09-29, 515 queries, 0 writes) confirmed identities and OFF states and reproduced the ≈10 mA zero-current readback with the source OFF. Consequence already visible from the datasheet terms alone: at 24 V / 0.1 A the efficiency bound is about ±28 percentage points (k = 2), dominated by the load's 30 mA full-scale current term and the source's 10 mA offset; below ≈0.5 A the internal readbacks cannot qualify efficiency without an external current measurement. Plan step 4 was run by the owner through the bench UI on 2026-09-29 (converter disconnected, supply CH1 wired straight to the load, 12 V at 0 / 0.1 / 0.25 / 0.5 A, profile `passthrough-check`): the load's current readback sits +11.0 to +11.3 mA above the source's at every loaded level and the lead drop is 19–43 mV ([evidence §F](m2-freshness-and-readback-evidence.md)); the analysis flagged the three loaded points as implausible power ratios, and the report now draws flagged points as open markers with a computed explanation plus a readback cross-check metric (formula version `settled-dc-1.3`). Still open on the bench (plan step 5, owner authorization): one qualified enabled-no-load window and a 0.1 A point at 24 V with the converter connected; and the hardware decision on an external current reference for light-load points. |
| M3 — partial-power sweep and UI | Workflow slice demonstrated; not complete | Saved forms, hashed preview, fresh confirmations and the actual UI Start callback completed a bounded three-point real acquisition through the application services, continued after client disconnect, verified OFF and generated HTML/PDF automatically. Desktop/mobile forms and saved reports passed browser review. Another 5 V DUT profile was exercised without Python edits using fake SCPI. RUN-02 refresh/reconnect is now covered at the mock/application-services level. Not complete by the Section 15 exit criteria: M2 qualification is a prerequisite, the sweep is bounded far below rated power, and the real Start used Socket.IO callbacks so a browser-click acquisition is not claimed. `reports/<rev>/exports/` and the model-driven narrative are complete on this branch. |
| M4 — paired-run comparison and thermal tools | Software implemented on mock and stored data; exit not met | `dcdc-bench compare` pairs stored analyses by qualified conditions (CMP-01/02; demonstrated read-only on two real 24 V runs), the attachment store with import hygiene and the `/annotations` sensor-placement editor produce new report revisions (WEB-11/WEB-12), and a synthetic thermal channel with a separate thermal-settling policy exercises RUN-07 on the mock plant. Not met: no real temperature adapter or validated thermal criteria, no comparison HTML/PDF rendered. The browser-marked WEB-11 check passed on the bench computer on 2026-09-28 (system Chromium, 320 px narrow viewport). |
| M5 — expanded tests and capability | Partial (mock only) | The approved UVLO input-ramp procedure with a phase-scoped guard policy runs on the synthetic plant (RUN-09, DATA-04 brackets) and ships an unapproved example recipe. Full-power operation, scope/dynamic procedures, qualified uncertainty improvements on the real bench and approved public examples remain future work. |

### Latest measured evidence

- Configured job **`20260927T223820Z_bb4a479f`** completed **3/3 qualified
  points** at 24 V input and 0.1, 0.25 and 0.5 A output loads in **57.381708 s**.
  The controlling UI client disconnected after Start; the dedicated worker
  continued, verified source/load/timer OFF and automatically generated HTML
  and PDF revision `r0001`. Presentation revision `r0002` then refined PDF
  pagination with native Typst, preserving the acquisition and results.
  Open the [workflow HTML](http://localhost:8081/Runs/12t12-workflow/report.html)
  or [PDF](http://localhost:8081/Runs/12t12-workflow/report.pdf). See
  [bench workflow verification](bench-ui-verification.md).
- The **15 V startup followed by a continuous input-voltage descent**
  completed **7/7 qualified conditions** in 135.47 s. With the load held near
  100 mA, the lowest condition measured **9.108 V input → 12.134 V output at
  99.5 mA**. The converter first established stable output at 15 V; this does
  not establish cold-start operation at 9 V or a UVLO threshold. Source, load
  and the independent source timer were verified OFF. See the
  [agent-role startup/descent results review](startup-descent-results-review.md).
- Startup report: [interactive HTML](http://localhost:8081/Runs/12t12-startup/report.html)
  and [PDF](http://localhost:8081/Runs/12t12-startup/report.pdf), final presentation revision `r0005`,
  analysis `a-64db20585452`. These are local bench links; use the actual
  forwarded port shown in VS Code.
- The extended 24 V test completed 37 observation windows, including an increase
  to 500 mA, a sustained-load interval and a return sweep. See
  [extended verification](extended-verification.md).
- A subsequent 24 V source-limit test reached a 1.725 A output request. See
  [source-limit verification](source-limit-verification.md).
- The earlier voltage-efficiency continuation completed **27 qualified points**:
  13 at 24 V through 1.725 A output, and 14 near 36 V (programmed 35.8 V) through
  2.5 A output. The 24 V phase reached its mean input-current target; the near-36 V
  phase completed its declared grid. It did not establish a maximum output rating.
- The separate 12 V startup attempt stopped on input-voltage collapse and current
  near the 1 A source limit. It produced **no qualified 12 V efficiency curve**.
  The retained evidence holds **one** automated 12 V cold-start attempt (run `…_e0fab9`); an earlier statement of two failures is not supported by recorded evidence. In that attempt the load was enabled at about 7.98 V output and, one second later, the input collapsed to 2.661 V with input current at the 1 A setting; the source read CV before and after. The cause is unestablished; see the [cold-start hypothesis](cold-start-hypothesis.md).
- Voltage-comparison report: local `/Runs/12t12-efficiency/report.html` and `report.pdf`,
  revision `r0005`, analysis `a-e2e7cc8e0d01`. See the
  [agent-role results audit](voltage-efficiency-results-review.md),
  [code review](voltage-efficiency-code-review.md) and
  [UI/UX review](voltage-efficiency-ui-review.md).

These real measurements use local sensing and include wiring losses. They do
not establish converter-terminal efficiency with remote sensing, calibrated
uncertainty, thermal equilibrium or the full 4 A rating. Source and load were
verified OFF at the end of the latest run. Qualified means exclude startup
observations and, for the descent experiment, voltage-transition observations.

### Implemented operator workflow

The [configured run guide](configured-runs.md) describes the new local workflow:
save DUT/bench/recipe profiles, preview an immutable plan, confirm the physical
setup and serial numbers, then start a dedicated worker. Saving a changed
profile invalidates its old preview. Status exposes the requested condition
and recent unqualified readings; Stop preserves partial evidence and requests
verified shutdown.

The deployed UI uses the existing remote port **8081**, with the bench page at
`/` and the existing `/Runs/...` report links retained. Each production job uses
its own bounded systemd user service with no acquisition restart. A separate
report process starts only after all required outputs are verified OFF. An
exclusive activity lock prevents acquisition and heavy reporting from running
together. Failed reports can be retried without re-energizing the DUT.

This initial real backend supports the verified DP821A CH1 / DL3031A bench,
local sensing and positive-load DC sweeps, with explicit profile limits inside
the [documented envelope](configured-runs.md#current-physical-envelope).
Each input-voltage phase cold-starts the converter. The fixed warm-start
descent above is a separate procedure. Setup notes reach the report; saved
attachment references are metadata, not an image-upload or photo editor.

### Engineering report presentation

The current reports use **Efficiency**, **Load Regulation**, **Input Current**
and **Power Loss**, with consistent colors, markers and line patterns across
HTML/PDF. Nominal-voltage and recorded supply-limit references provide context.
These are presentation revisions using the same saved analyses and measurements.
See [terminology](engineering-figure-labels.md) and
[style verification](engineering-style-verification.md) for the reference
documents, checks and browser coverage.

### Next bounded task

The two documents the previous gate asked for now exist and await the owner's
review: the [12 V cold-start hypothesis and supervised test proposal](cold-start-hypothesis.md)
and the [M2 qualification plan](m2-qualification-plan.md). Neither authorizes
energizing the converter. Before any further real run, the next bounded task is:

1. Owner review of both documents, including the bench-time items they name:
   measurement freshness under load (the outputs-OFF cadence probe is not that),
   readback accuracy at the ranges to be claimed (transcribe R1/R4 readback
   terms and calibration status into the bench profile so the budget can
   evaluate), the physical load's capability, and a qualified enabled-no-load
   window at 24 V.
2. If the owner approves, the load-disabled cold-start bracketing 15 → 12 V
   proposed in the hypothesis document, as a reviewed recipe with protective
   limits, not the ordinary sweep.

Only after that gate: complete M3 by the Section 15 exit criteria. M4 and M5
software is present on mock and stored data (comparison, sensor placement,
synthetic thermal channel, UVLO procedure); what remains there is real
temperature acquisition, a real UVLO run under a reviewed policy, a rendered
comparison document and the browser-marked gates on a laptop or CI. The
physically qualified DUT/bench envelope expands only with reviewed procedures
and equipment limits; the separate warm-start experiment does not add
warm-start behavior to the ordinary cold-start UI sweep.

Completed on this branch on 2026-09-27: `reports/<rev>/exports/` (issued
`points.csv` and `points.meta.json`, written atomically) and the model-driven
narrative. The analysis and renderer no longer contain hard-coded voltage,
current, step, window or DUT-rating literals; procedure notes, summary
sentences, captions and series labels read the recorded `method` record, the
plan and the DUT profile, and omit a clause when an older record lacks the
field rather than inventing it.

### Hardening on this branch

Changes on `dcdc-bench-hardening` since the measured evidence above was
recorded (commit subjects, not hashes):

- **Add dcdc-bench: DC-DC characterization bench with mock/real runs and
  reports** — the subproject is under version control.
- **Make saved-profile approvals load-bearing for real hardware** —
  `DutProfile.execution_approval.real_hardware_enabled` /
  `.wiring_and_polarity_confirmed` and `BenchProfile.protective_controls.approved`
  are checked by `planning.missing_approvals()`, surface as the planner's
  `approval_blocked` reason, and are enforced in `real_backend.prepare_real_plan`
  (preview errors), `extended._run_fixed_unlocked` and `bringup.run_bringup`.
  The seeded UI bench profile `rigol-local-limited` ships unapproved; the DUT
  and bench forms have approval checkboxes. Each Start still requires the fresh
  wiring/CH1/protections/serial confirmation.
- **Share one verified protection sequence across all real procedures** —
  OVP/OCP, load CC limits and OTP are programmed once in `bringup.RigolPilot`
  (`apply_source_protections`, `apply_load_cc_limits`, `enable_source_otp`);
  fixed procedures supply values only. Drift guard:
  `tests/test_bringup.py::test_protection_programming_scpi_lives_only_in_the_shared_adapter`.
- **Make the section 5.2 contracts runtime-checkable and pin implementations
  to them** — SourceAdapter, LoadAdapter, MeasurementProvider, TestProcedure,
  RunStore, Analyzer and ReportRenderer are `@runtime_checkable` Protocols in
  `domain.py`; `tests/test_contracts.py` checks that `MockBench`,
  `storage.RunStore`, the `*Procedure` classes and `RigolPilot` conform.
- **Add RUN-02 regression test: browser refresh reattaches to the single
  worker** — `tests/test_run02_reconnect.py`.
- **Route live input-voltage steps through a bounded driver method** — the
  startup/descent step calls the new `benchctl` method
  `RigolDP800.set_voltage_live(channel, V, max_step_v=1.0)` instead of writing
  raw `:SOUR1:VOLT` around the driver's output-OFF interlock (tests in
  `Software/tests/test_dp800.py`).
- **Re-validate real plans at start and gate bring-up like the other
  procedures** — `JobService.start` rebuilds the plan from the saved profiles
  and re-runs `prepare_real_plan` instead of trusting a cached preview;
  `bringup.run_bringup` takes the single-owner bench lease.
- **Derive the remaining analysis narrative from recorded methods** — the
  source-limit, voltage-sweep and startup-descent notes, summary sentences,
  figure captions and series labels take their input conditions, reduced
  setpoints, supply limit, step sizes, window durations, return load, planning
  efficiency and the DUT's rated current from `run.json` `method` records and
  the plan. Rebuilding the latest issued report model of each of the three real
  runs reproduced every number; only deliberately reworded sentences differ.
  Regression: `tests/test_sequence_report.py::test_adaptive_note_states_the_plans_own_efficiency_assumption`.

- **Add the structured readback uncertainty budget with not_evaluated reasons for unknown terms** — `uncertainty.py` builds a schema-versioned `uncertainty.json` per analysis revision from typed `readback_specification` terms (a/√3 rectangular limits, resolution, optional temperature term, Type A repeatability recorded separately, declared covariance, U = k·u_c with k stated and not called a 95 % interval, efficiency in percentage points, loss propagated separately in watts, near-zero-current flag, unknown terms → `not_evaluated` with reasons). Reports show bands/± only when evaluated. The mock profile carries a labeled synthetic example; `rigol.example.yaml` and the seeded real benches carry `status: unknown` with the R1/R4 datasheet URLs, so **the real bench remains unquantified until the owner transcribes readback (not programming) terms and calibration status** (`docs/uncertainty-budget.md`). Formula version `settled-dc-1.2`. Tests: `tests/test_uncertainty.py`.
- **Add the approved UVLO input-ramp procedure with a phase-scoped guard policy** — RUN-09 on mock hardware only: `uvlo.py` (`UvloInputRampProcedure`, `run_uvlo_mock`) and `mock_uvlo.py` (synthetic latching UVLO on a `MockBench` subclass); the `uvlo_input_ramp` test type with a declared `uvlo` block and `authorization.uvlo_approved`; planner refusal/approval gating and floor/range refusals; `run_mock` refuses non-steady-state types; DATA-04 brackets and a UVLO figure/summary in `analysis.py`; `profiles/recipes/12t12-4a-uvlo.example.yaml` ships unapproved (17/17 approval_blocked). Plans serialized before this commit no longer pass `verify_plan_hash` (new fields), which is the intended fresh-approval behavior. Tests: `tests/test_uvlo.py`.
- **Add paired-run comparison from stored analyses (M4: CMP-01, CMP-02, UNC-03)** — `dcdc-bench compare <runA> <runB> --out <dir> [--analysis-a/-b ID] [--tolerance-vin V] [--tolerance-iout A] [--interpolate] [--covariance JSON] [--overwrite]` in `comparison.py` + `reporting/comparison.py` (renderer.py only dispatches `kind == "comparison"`); pairs by qualified conditions/IDs never by index, lists unpaired points per run, `delta_eta_pp = eta_B − eta_A` plus Δloss/ΔVout, difference plots with a zero line, resolvability via `u_delta² = u_A² + u_B² − 2·cov` only with evaluated budgets, otherwise "not evaluated"; writes model JSON, Markdown body, CSV exports + metadata, Plotly figure JSON and a manifest; sources stay read-only. Real read-only demo at `examples/generated/comparison-real-24v/` (extended run `…_real_42e971`, analysis `a-4a0763ae9add`, vs source-limit run `…_real_75a478`, analysis `a-d0697ec66a0e`, at 24 V), re-created 2026-09-30 after the 2026-09-29 demo build had wiped the folder: 6 pairs, 103 unpaired points (31 from the extended run, 72 from the source-limit run; the 2026-09-28 demonstration reported 47 unpaired against the analyses current then), largest Δη −0.47 pp at 0.1 A, uncertainty not evaluated, same DUT model on different days. `examples/generated` is rebuilt by every `demo`, so this folder is a demonstration, not durable evidence. Tests: `tests/test_comparison.py`.
- **Add read-only doctor, the outputs-OFF readback-cadence probe and the approval-gated publish command** — `doctor.py` runs the real drivers through a `ReadOnlyTransport` whose `write()` raises and whose `query()` allows only an explicit list (identities, output/input states, protections, sense, timers, `*STB?`; never `SYST:ERR?`, which would pop the fault evidence); `--readback-cadence` refuses unless both outputs read OFF and saves an idle readback-path observation under `diagnostics/` that is explicitly not a loaded-freshness qualification. `publish.py` produces an approval-record-gated redacted copy with `publication_manifest.json`, keeps `noindex` unless `public: true`, and uses no git or network. Verified with fake SCPI only (`tests/test_doctor.py`, `tests/test_publish.py`); `docs/doctor-and-publication.md`.
- **Add the synthetic thermal channel and thermal settling (M4, mock only)** — sensor metadata (`TemperatureSensor`, `SensorPlacement` compatible with `annotations.json` 1.0), the first-order `mock_thermal` provider attached to the mock plant only, a separate `ThermalSettlingPolicy` in the runner (timeout → `inconclusive`, time series retained, no fabricated equilibrium), per-point absolute temperature and rise above time-aligned ambient (no ambient → not evaluated), separate temperature / rise-vs-loss / settling figures, `profiles/bench/mock-thermal.yaml` and `recipes/12t12-4a-thermal-mock.yaml`. No real temperature adapter; criteria are drafts. Tests: `tests/test_thermal.py`.
- **Add the attachment store, import hygiene and the sensor-placement editor (M4, WEB-11/WEB-12)** — content-addressed `attachments/originals/<sha256>.<ext>` with content-sniffed type/size/dimension/SVG/PDF checks (`attachments.py`); post-finalization assets go to `attachments/revisions/<n>.json`, never into `integrity.json`; exact-schema `annotations.json` bound to the image hash and saved only as a new report revision (`report_run(annotations=)`, `dcdc-bench report --annotations`, `JobService.retry_report(job_id, annotations)`); a "Sensor placement" report section (markers positioned by report.js from normalized coordinates, a static SVG overlay for the PDF, everything escaped); the NiceGUI `/annotations` editor. Tests: `tests/test_attachments.py`, `tests/test_annotations.py`, `tests/test_annotation_editor.py`; the browser-marked WEB-11 test and a Quarto/Typst build of the new section are not yet executed on the Pi.
- **Add the automated PDF pagination check and the WEB-08 nonpositive-current fixtures** — `reporting/pdf_check.py` runs after every PDF build and is recorded in `build_manifest.json`; an error finding marks the document `failed-validation` while keeping it. Re-checking the issued PDFs read-only confirmed the recorded page counts and the earlier table fixes, and found one defect the manual reviews missed: the voltage-sweep report (r0002–r0007) left the last regulation-metrics row alone on page 7; the print theme `templates/theme/print-tables.typ` (2026-09-28) now keeps tables up to half a page unbreakable and moves the last two rows of a taller table into one non-repeating footer, so a lone final row cannot occur (`tests/test_print_tables.py`). WEB-08 has a browser fixture with 0 A and negative-current points plus a Node check of the shipped script. `dcdc-bench pdf-check <report.pdf>`. Tests: `tests/test_pdf_check.py`.
- **Harden the job and report process model for the 1 GB Pi** — the acquisition worker exits at `report-queued` after verified OFF so drivers leave RAM; the UI's 2 s dispatcher launches one report-only worker only when no job is active, the bench lease is free and the memory gate passes (`DCDC_RENDER_MIN_AVAILABLE_MIB` = 150, `DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB` = 600; both 0 disables), with the deferral reason visible in the job; `retry_report` queues instead of refusing; Quarto runs in its own session with the same timeout and its group is swept; the report child's session is swept on every exit path and the Chromium tree is stopped if Kaleido's close times out; per-task RSS/MemAvailable/swap/duration telemetry goes to `resource-log.jsonl`, `resources.jsonl` and `build_manifest.json` (`docs/pi-process-model.md`). Acquisition timing and electrical limits are unchanged. Tests: `tests/test_resources.py`, `tests/test_report_queue.py`; the RUN-02 integration test now covers acquisition → report-queued → dispatch → completed with a real detached worker.
- **Write the 12 V cold-start hypothesis and the M2 qualification plan** — from stored evidence only, no hardware: `docs/cold-start-hypothesis.md` (ranked hypotheses; the single recorded 12 V attempt enabled the load at ~7.98 V output 1.0 s before the collapse) and `docs/m2-qualification-plan.md`. The documents also corrected two statements in the status docs: only one automated 12 V attempt exists, and the earlier narrative omitted the load enable.
- **Integrate the nine parallel increments and settle their seams** — merged in sequence with conflicts resolved by keeping both sides; the retry path binds annotations and then queues; job status treats a launch younger than five seconds whose process is alive as starting, closing a fork/exec race that could flash "worker exited unexpectedly".
- **Independent reviews of the merged increments and their fixes** — [merge-code-review.md](merge-code-review.md) (no blocker, 7 majors, 10 minors, 5 nits; every major and five minors fixed in the commit its Resolution section cites: the report-queue cancel race, the comparison reading a budget table the analysis never wrote, the unreachable mock UVLO dispatch and a real UVLO plan that could have run as a sweep, off-steps with slightly negative readbacks, a missing checker tool now yielding `unverified` instead of a failed job, `publish` refusing non-successful builds unless the approval says `allow_unverified`, and the systemd launcher forwarding every `DCDC_*` variable) and [merge-security-review.md](merge-security-review.md) (one high, seven mediums, eight lows; the high, all seven mediums and five lows fixed in commit `2582508`, merged as `bcdc58f`, each with a test; its Resolution section, added 2026-09-30, lists the three lows still open: the `include_pdf` flag name, bidi/zero-width controls in captions, and the PID-reuse window of the post-exit sweep).
- **Documentation restructured for newcomers** — [docs/README.md](README.md) indexes every document; [architecture.md](architecture.md) maps modules, contracts and covering tests; the six measured-run narratives moved verbatim to [measured-results.md](measured-results.md); the subproject README shrank from 549 to 362 lines with the status paragraph kept byte-identical across the three status documents.
- **Simulation review round and fixes (2026-09-30)** — five reviewer roles (UI/UX, power-electronics test engineer, first-time user, engineering manager, QA) reviewed the simulated bench and its fresh report; their documents and the consolidated findings are under [docs/simulation-review/](simulation-review/README.md). Four implementers then made the simulated plant physically honest (current-limit collapse, cold-start gate, refit to the measured converter, quantised/held readbacks, physical thermal constant, budgeted runs; [simulation-plant.md](simulation-plant.md)), made the bench page's Simulation self-explanatory and bench-following with two can/cannot panels and a [glossary](glossary.md), corrected the standards catalog's verdict words, fixed CI on Python 3.11, and closed the PDF-02 small-table split at the Typst level. The page and the report keep the SYNTHETIC label on every simulated output.
- **Codex review, its audit and follow-ups (2026-09-30/10-01)** — an OpenAI Codex run reviewed the tree and left fixes that were committed as `031b122` after the suites passed ([Project-Review-2026-09-30.md](../../Documentation/Project-Review-2026-09-30.md)); an independent [audit](simulation-review/codex-review-audit.md) confirmed its P1 fixes (cancellation finalisation for phase-scoped simulations, positive-semidefinite correlation and no clamped variance in the budget, publication refusing modified bytes) and all P2 rows, found its "repaired links" had rewritten quoted passages (restored) and its test totals inflated by the Pi's local run folders (documents now give bench and clean-clone counts). Its uncontroversial remaining items were then implemented: Reports paging and filter beyond 30 runs, Run-panel updates in place so keyboard focus survives polls, keyboard creation of the first sensor marker, generic report wording following the evidence label, and the DUT documentation note kept with its tables in the PDF. Left to the owner: collapsing reference panels by default, making the browser/PDF CI job required, wheel packaging.
- **Bench page after the owner's review** — other-laboratory standards removed from the page (one footnote and a read-only `/standards` route), the ISO 16750-2 card styled as an editor with exactly one selected test at any time, the Reports list rebuilt as one aligned grid in a 1280 px layout, the raw-samples table scrolling instead of breaking header letters, and a report-only retry no longer refused for jobs saved before a schema change. The owner's question about ISO 16750-2 approximations is answered by the [best-effort proposal](standards/best-effort-proposal.md) and the two instrument studies ([DP800](standards/instrument-sequencing-dp800.md), [DL3000](standards/load-programs-dl3000.md)); the owner's decisions of 2026-10-01 are recorded in the proposal's §8 and implemented by the next entry.
- **Best-effort ISO 16750-2 on the simulated bench (2026-10-01)** — the proposal's `best_effort` verdict runs end to end on the synthetic plant, mock only. `standards.py` declares a deviation sheet per clause (4.3.1.2, 4.3.2, 4.6.1.1, 4.6.1.2, 4.9.1, 4.9.2; 4.3.1.1 and 4.5 keep an instrument-timed bound), `standard_recipes.py` writes each recipe unapproved with its sheet, `planning.py` gates it on `authorization.best_effort_approved` plus the accepted sheet hash (and the UVLO approval wherever a level is below the converter's stated minimum), `best_effort_procedures.py` runs the four test types (`transient_hold`, `momentary_drop`, `micro_interruption`, `line_interruption`) with host-clock command timestamps or the supply's Timer/Delayer and finalizes the planner's stimulus-level point (acquired when a hold is long enough to settle, otherwise inconclusive with the reason stated), and the report prints the sheet with an achieved column in HTML, PDF and `exports/deviations.json`. Every terminal-side timing is commanded, not measured; a real bench refuses the types. Open owner questions: 4.6.3, 4.7 and the trigger lines ([proposal §7](standards/best-effort-proposal.md)); from the integration review, the 4.6.1.1 base at 12 V (Usmin 9.0 V is below the synthetic plant's 9.1 V turn-on, so a simulated run stops at the startup gate with that reason recorded) and the 4.3.2 rest between pulses (longer than the clause's 1 s because the output is observed after each pulse; recorded in the run) — see HANDOFF.md §8.
- **Review of the best-effort feature (2026-10-01)** — the 4.6.1.1 variant A sheet now records the drop depth as not measured (a 100 ms window is shorter than the supply's worst-case fall; proposal §3), the 4.3.2 rest row says that the bench's observation after each pulse lengthens the time at base between pulses and the run records that interval (host-timed, or the programmed rest group) instead of the declared rest, Preview (`planning.prepare_mock_plan`) lists the same stimulus refusals as the worker (`best_effort_procedures.stimulus_refusals`), a recipe that runs several variants of one clause renders one sheet whose rows are labelled by variant, and the report shows basis tags (DS5, LAN, PG, ...) with their legend instead of the full basis strings (kept verbatim in `exports/deviations.json`). Open for the owner: the generated 4.6.1.1 and 4.6.2 recipes start at Usmin 9.0 V, which the synthetic plant (turn-on 9.1 V at the converter input) never starts from, so those runs end at the startup gate; and whether the 4.3.2 rest between pulses should be the clause's 1 s (observation after the last pulse only) rather than the present rest plus observation.

`ui` is implemented. The older generic CLI `run --mode real` still rejects
hardware execution; configured real jobs use `JobService` through the UI.
`doctor`, `compare`, `publish` and `pdf-check` are implemented; `doctor` and its cadence probe have run only against fake SCPI.

### Current verification record

Current test total (2026-09-30, `dcdc-bench-hardening` at the end of the simulation review round): the full run `pytest dcdc-bench/tests -m 'not browser and not pdf'` passed **875 tests** with 16 browser/PDF gates deselected on the bench Raspberry Pi 4. That count includes tests parametrised over the Pi's local, git-ignored run folders; a clean clone collects 934 at `b9adf70` (903 in CI's required selection), which is why CI totals are lower than bench totals. This is the one figure the README and HANDOFF quote; the run totals below are dated checkpoints. GitHub Actions run 36745805562 on commit `af52981` (2026-09-30) passed all three jobs: fake-instrument tests on Python 3.11 and 3.13, and the informational browser/PDF gate job (demo rendered on the runner, PDF-02 check passed, browser gates 15 passed, 1 skipped), the first fully green run since the workflow was added. The same gates ran locally on the Raspberry Pi 4 against the regenerated demo the same day: `pytest dcdc-bench/tests -m 'browser or pdf'` → 15 passed, 1 skipped, 142 s (system Chromium 153, Quarto 1.10.18).
CI note: the Python 3.11 job had failed on seven `Path.read_text(newline=)`
test sites (3.13-only), fixed on 2026-09-30; the two 390 px browser gates
that failed on CI's Chromium were made font-tolerant the same day and have
not yet been re-run there.

On 2026-09-28 (late evening), on the bench computer after its move to a
Raspberry Pi 4 Model B with 2 GB, the branch tip passed every executable
gate: `Software/` (benchctl) **445 passed** (10 s); dcdc-bench non-browser
`pytest -m 'not browser and not pdf'` **692 passed**, 15 deselected (139 s;
a 2026-09-28 run total, superseded by the collected figure above);
and the browser/PDF gates `pytest -m 'browser or pdf'` **14 passed, 1 skipped**
(248 s including a fresh three-scenario demo build). The skip is the
sequence-report time-figure check, which the M0/M1 demo cannot exercise. This
is the first complete execution of the browser/PDF section; it found one
layout defect (the excluded-points table lacked its scroll wrapper at 390 px)
and one PDF-02 finding (a lone table row in the normal demo), both fixed on
the branch before this record. One historical count is retained, labeled as
such: on 2026-09-27, before this branch's work, the non-browser dcdc-bench
suite passed 393/393 and the benchctl suite 435/435. Earlier per-selection
counts have been removed from this document because overlapping selections at
different revisions cannot be summed.

Verification platform: Raspberry Pi 4 Model B Rev 1.1, 2 GB, aarch64, Debian
with Python 3.13, Debian `chromium-headless-shell` 153 (Chrome for Testing has
no linux-arm64 build, so Playwright drives the system browser through the
renderer's `_browser_path()`), Quarto 1.10.18 under `dcdc-bench/.tools/`.
Host telemetry for the run is in `Data/Logs/memory-monitor.jsonl`
(`tools/memory_monitor.py --summary`): MemAvailable never fell below 446 MiB
and firmware reported no throttling, but compressed swap reached about 1 GiB
while the render, the editor server and two coding assistants were resident.
On the previous 1 GB Pi the same browser run could not start Chromium under
load.

| Check | Recorded result |
| --- | --- |
| Ordinary regression suite | Passed at each recorded revision; current figure in the branch's final verification record. |
| Configured real workflow | Three qualified points; continued after UI client disconnect; source/load/timer OFF; automatic HTML/PDF succeeded. |
| Agent-role configured-run audit | Recomputation from preserved acquisition evidence agreed with the official analysis; see the [results review](configured-workflow-results-review.md). |
| Agent-role startup/descent audit | Recomputation agreed for the separate seven-condition run; see the [results review](startup-descent-results-review.md). |
| Another DUT without Python edits | A 5 V DUT profile was exercised through fake SCPI; no second physical DUT acquisition is claimed. |
| Final PDF pagination | The reviewed layout revisions keep the startup report at six pages and configured workflow at five. Method, complete shutdown table and note stay together; presentation revisions preserve the measurements and figures. |
| Served Reports browser links | Actual served HTML, PDF and report-model endpoints returned HTTP 200. |
| Final saved-run/mobile browser review | Passed: three qualified points and verified OFF visible; desktop and 390 px run/form layouts inspected, with document width 390 px. Foreign Host and Origin requests returned HTTP 400. |

The separate systemd launcher smoke also completed a pre-cancelled mock job
without creating acquisition evidence or rendering. See the
[agent-role backend code review](configured-backend-code-review.md) and
[bench UI verification](bench-ui-verification.md) for the scope and distinction
between browser inspection and actual Socket.IO callback execution.

Earlier voltage and extended work recorded their own focused selections and
evidence audits in the linked review documents; those per-selection counts are
not repeated here and are not a rerun of the historical browser/PDF acceptance
suite.

The converter application and its new measured reports remain local/unpublished.
The existing parent-project public demo is a separate deliverable.

## Historical record — initial M0/M1 and supervised pilot

The sections below retain the original acceptance record. The current milestone
status and later test results are summarized above.

### Authorized increment at the initial checkpoint

The initial scope was M0 contracts and M1 mock acquisition → analysis →
interactive HTML / vector PDF. The user subsequently confirmed the connected
12T12-4A, polarity and supply CH1, and explicitly requested a live test. That
later instruction authorized a separate supervised pilot.

The pilot completed one 24 V / 0.1 A operating point with a 0.15 A supply current
limit. At this initial checkpoint, general real recipe execution was disabled;
publication, the bench UI, thermal editing, comparisons and UVLO were later
milestones. No repository push or report publication was performed at that
checkpoint. The source brief is preserved in
[implementation-brief.md](implementation-brief.md).

## Historical repository audit and reuse plan

The parent project is a functioning `benchctl` library under `Software/src/benchctl`.
This subproject leaves that package and its real configurations intact.

| Existing source | Reuse decision |
|---|---|
| `drivers/rigol_dp800.py`, `drivers/rigol_dl3000.py` | Reused by the separate supervised pilot through a thin adapter. Constructors accept injected transports and do not connect. Wider M2 integration remains unfinished. |
| `interfaces.py`, `transport.py` | Reused finite transport timeouts, identification and error/readback checks. The pilot also records actual SCPI responses. |
| `runner.py`, `results.py` | Retain for existing recipes. New M1 contracts need per-query timing, accepted acquisition cycles, an independent worker and immutable analysis revisions. |
| `report.py` | Actual generator exists, but its custom SVG report describes a direct 5 V source/load test. It has no Quarto/Typst PDF pipeline or converter evidence model. Keep the existing demo; use the selected Quarto engine for converter documents. |
| `Media/demo-load-sweep.svg` | Preserve unchanged. |
| Existing tests | Preserve; new package has independent tests and no real driver imports in its mock path. |

## Historical real pilot and initial M2 work list

Source APIs observed: `identify`, `set_voltage(channel, value)`,
`set_current_limit(channel, value)`, `output_on/off(channel)`,
`get_output_enabled(channel)`, `measure_voltage/current/power(channel)`.
Load APIs observed: `identify`, `set_mode`, `set_current`, `input_on/off`,
`get_input_enabled`, `measure_voltage/current/power`.

The pilot in `src/dcdc_bench/bringup.py` wraps these APIs and adds explicit
protection and state readbacks. It checks source CV mode, local load sensing,
source OVP/OCP and load limits; records query timing; and independently shuts
down and verifies the load and supply. The pilot is separate from the generic
CLI and requires explicit arming. Its limited execution does not validate the
full recipe engine for hardware use.

The connected instruments identify as DP821A and DL3031A. The load's physical
capabilities are not inferred from its reported model. This pilot used only
the small operating range required for the authorized point.

### Recorded result

Local run: `runs/real-bringup/20260927T061038.184185Z_real_578d4f/`.
Acquisition finished on **2026-09-27 at 06:11:01 UTC**, with five accepted
measurement cycles and both outputs verified OFF.

| Quantity | Mean or derived result |
|---|---:|
| Input voltage | 24.006 V |
| Input current | 0.06884 A |
| Output voltage at load terminals | 12.1363608 V |
| Output current | 0.0993278 A |
| Input power | 1.65257304 W |
| Output power | 1.205478018 W |
| Approximate path efficiency | 72.9455% |

The values above retain analysis precision for traceability; they are not an
accuracy specification. This boundary includes input and output wiring.
Readback uncertainty, calibration and ADC freshness are unquantified, and this
point does not establish a rated power limit, efficiency curve or thermal
performance. The user's multimeter and front-panel observations are retained
as operator observations, separately from automated samples.

Earlier attempts stopped on a load-limit configuration error, an output-voltage
guard and an unexpected off-state voltage reading. Each attempt remains in its
own run folder with shutdown evidence. The successful run measured only the
loaded point; it does not turn those off-state readings into a no-load result.
Existing raw evidence is preserved. Analysis and reports receive their own
identifiers and revisions.

After the run, the operator observed approximately 0.178 V with the outputs
off. After disconnecting the supply from the converter input, the operator's
Fluke multimeter showed the converter output discharging slowly. This is
consistent with stored capacitor charge and does not, by itself, indicate a
converter fault. This is a subsequent operator observation, not an automated
discharge measurement. A verified OFF command does not establish zero terminal
voltage; discharge verification is a separate condition.

### Work listed before the first wider sweep

- Establish readback accuracy and measurement freshness at the selected ranges.
- Confirm the physical load's ratings and the intended voltage-sense wiring.
- Validate protective settings and shutdown behavior across the proposed sweep.
- Complete real adapter integration and the general worker lifecycle.

Programming accuracy is not a substitute for readback accuracy. A successful
100 mA pilot is not approval to run the rated grid.

## Initial validation record

**M0 and M1 acceptance: COMPLETE on the verification platform below** (statement as made at the initial checkpoint; the current position above supersedes it).

The implementation includes typed profiles and plans, a mock acquisition
worker, retained raw evidence, versioned analysis, and a shared HTML/PDF report
model. A complete demo command has produced normal, setup-limited and aborted
mock HTML/PDF reports and exited successfully. This records the working
generation path; numerical, offline interaction, export and PDF checks passed.

Additional implemented checks preserve declared versus observed acquisition
timing, resolve summary links through typed metric/figure references, reject
plans conflicting with explicit protective limits, and prevent mixing an
analysis with another run's raw evidence. New acquisition provenance records
Git commit/dirty state and source hashes; new build manifests also identify the
renderer, CSS and interaction JavaScript. Unknown values remain unknown, and
earlier finalized acquisition records are not rewritten.

Verification platform: Debian 13 ARM64 on a Raspberry Pi, Python 3.13.5. The
report toolchain uses Quarto 1.10.18, Plotly 7.1.0 (Plotly.js 4.1.1), Kaleido
1.4.0 and Chromium Headless Shell 153.0.8010.52. Source checkout setup is
documented; Windows instructions have not been verified.

| Check | Current record |
|---|---|
| Full suite at this initial checkpoint, excluding browser/PDF checks | Passed with browser/PDF checks deselected, in 60.59 s. Per-selection count removed; see the current verification record. |
| Complete mock demo command | Exited 0; normal, setup-limited and aborted HTML/PDF reports generated. |
| Bring-up and storage checks | Passed with fake instruments, including guarded startup and SCPI transcript integrity for future runs. |
| Supervised real pilot | One valid loaded point; load OFF and source OFF both verified. |
| Real HTML/PDF generation | Successful revision `r0004`, sharing analysis `a-5e0e50434006`; both local HTTP endpoints returned 200. |
| Final browser/PDF acceptance | The browser/PDF acceptance selection passed in 765.24 s. All three HTML files opened offline with the recorded Plotly runtime. Real hover, legend/checkbox/band synchronization, zoom/log bounds, CSV precision and actual CSV/metadata downloads, SVG/PNG exports, escaped text and fixed issued summaries passed. PDF text, vector drawing operators, shared identities and artifact hashes passed. |
| PDF visual inspection | All 15 pages of the three final mock PDFs passed inspection, five per report. The five pages of real revision `r0004` were also inspected. The three mock PDFs have selectable text and no rasterized plot images. |
| Offline mock bundle | ZIP verified: 104 files, 7,183,437 bytes. The local index, ZIP and aborted PDF returned HTTP 200 to HEAD requests. |
| GitHub publication | Not performed. Generated runs are local and ignored by Git. |

Commands executed from the parent checkout:

```sh
.venv/bin/python -m pytest dcdc-bench/tests -m 'not browser and not pdf' -q
.venv/bin/dcdc-bench demo --out dcdc-bench/examples/generated
env DCDC_DEMO_DIR=~/rigol-control/dcdc-bench/examples/generated \
  .venv/bin/python -m pytest dcdc-bench/tests/test_documents.py \
  -m 'browser or pdf' -vv -o faulthandler_timeout=240
```

Rendering and browser/PDF tests run sequentially on this Pi, after acquisition
has finished. The completed demo did not open real instruments.

See [acceptance.md](acceptance.md) for the requirement mapping. Per-selection
pass counts from this checkpoint have been removed; the current verification
record above keeps the single retained historical count and the pointer to the
branch's final record. M2 remains incomplete: a passing mock does not qualify
the real bench or authorize a wider live test.

### Final mock artifacts

The demo index is `examples/generated/index.html`. Final report directories,
relative to `examples/generated/`, are:

| Example | Saved revision |
|---|---|
| Normal | `normal/20260927T083115.018949Z_e77d3ca4/reports/r0001/` |
| Setup limited | `setup-limited/20260927T083435.365603Z_fd0a8924/reports/r0001/` |
| Aborted | `aborted/20260927T083852.864787Z_66962730/reports/r0003/` |

Each contains `report.html`, `report.pdf`, figure assets, the report model and
build metadata. The containing run folder retains acquisition and analysis
evidence. Earlier failed/interrupted build revisions remain separate.

### Report access

The local preview index is `/Runs/dcdc-mock-demo/index.html` on remote port
8081. The parent project's ignored archive
`Data/Runs/dcdc-mock-demo-download.zip` contains all three examples, their PDFs,
CSV results and acquisition evidence. Download and extract it, then open
`index.html` on your computer to review it without an SSH tunnel. These are
local artifacts, not files supplied by a fresh clone or published to GitHub.

The saved real report is available through the local preview server at
`/Runs/12t12-first-test/report.html` and `report.pdf`. The ignored archive
`Data/Runs/12t12-first-test-download.zip` in the parent project contains an
offline copy, PDF, CSV and report metadata. See the
[viewing guide](../../Documentation/Viewing-Local-Reports.md).

### Resource requirements and earlier interruptions

Earlier rendering attempts were interrupted during periods of heavy memory
pressure on this 1 GB Pi. Host restarts were observed, but the inspected kernel
journal did not establish their cause. Later attempts produced the static
figures but stopped before document conversion when memory was insufficient.
Those incomplete revisions are not successful report builds.

The completed builds used Chromium Headless Shell, one figure at a time, and
inserted the local Plotly runtime/raw-evidence JSON after Quarto's document
conversion. This keeps several megabytes of script/data out of Pandoc. While
VS Code was connected, the verification host also needed **768 MiB of temporary
disk swap in addition to its existing 904 MiB zram swap**. After the initial
tests passed, that temporary swap was disabled and its file removed. Later
report work required it again: at that recovery checkpoint, the 768 MiB
`test-artifacts/report-render.swap` file and zram are both active.

The setup script does not configure swap. The tested Debian/Pi prerequisites
are `chromium-headless-shell` and `poppler-utils`; `BROWSER_PATH` can select an
existing compatible browser. See the [setup instructions](../README.md#try-the-demonstration).
Provide sufficient memory before running a full report build on a small Pi, or
copy the run folder to a computer with more RAM and render there. Rendering is
independent of acquisition and never operates instruments.
