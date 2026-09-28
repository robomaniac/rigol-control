# Implementation status

## Current position

**Status as of 2026-09-27 (branch dcdc-bench-hardening): M0 reached; M1
substantially reached; M2 partial (freshness, readback accuracy and uncertainty
unquantified; enabled-no-load unqualified); an M3 workflow slice demonstrated
(bounded three-point real job through the UI's application services) but M3
not complete by the spec's exit criteria; M4/M5 not started.**

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
| M1 — mock run to HTML/PDF | Substantially reached | Normal, setup-limited and aborted mock runs; retained evidence, interactive reports and vector PDFs with recorded acceptance checks at the initial checkpoint. Open: the 13 browser/PDF-marked gates cannot run on this aarch64 Pi with the current toolchain and are re-verified on a laptop or CI; WEB-08's nonpositive-current exclusion has no browser fixture; the automated PDF-02 pagination check is not implemented. |
| M2 — supervised real point | Partial | Loaded bring-up, protection readbacks, timing, provenance and verified shutdown work in fixed and configured real procedures. Qualified enabled-no-load measurement, independent readback/freshness, uncertainty and physical load capability checks remain open. Saved-profile approvals, a single shared protection-programming sequence and a bounded live-voltage driver step were hardened on this branch; the metrology gate itself is unchanged. |
| M3 — partial-power sweep and UI | Workflow slice demonstrated; not complete | Saved forms, hashed preview, fresh confirmations and the actual UI Start callback completed a bounded three-point real acquisition through the application services, continued after client disconnect, verified OFF and generated HTML/PDF automatically. Desktop/mobile forms and saved reports passed browser review. Another 5 V DUT profile was exercised without Python edits using fake SCPI. RUN-02 refresh/reconnect is now covered at the mock/application-services level. Not complete by the Section 15 exit criteria: M2 qualification is a prerequisite, the sweep is bounded far below rated power, the real Start used Socket.IO callbacks so a browser-click acquisition is not claimed, and `reports/<rev>/exports/` plus the renderer's narrative literals are in progress. |
| M4 — paired-run comparison and thermal tools | Not started | No paired-run comparison command/editor, photo/sensor annotation UI or real temperature adapter. Different input-voltage curves within one run do not complete this milestone. |
| M5 — expanded tests and capability | Not started | Full-power operation, qualified uncertainty improvements, the approved UVLO runtime rule (RUN-09) and scope/dynamic procedures remain future work. |

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
  The 12T12-4A has failed direct 12 V cold-start twice; the cause remains
  unestablished. Both attempts retain their own raw evidence.
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

Before any further energizing of the converter, the next bounded task is:

1. Finish M2 qualification: measurement freshness (independent readback
   timing, not query spans), readback accuracy at the ranges to be claimed, an
   evaluated uncertainty budget, the physical load's capability, and a
   qualified enabled-no-load measurement.
2. Write the 12 V cold-start hypothesis. The converter failed direct 12 V
   cold-start twice with the cause unestablished; a written hypothesis and test
   plan precede another attempt.

Only after that gate: complete M3 by the Section 15 exit criteria, then M4
paired-run comparison (CMP-01/02), real temperature acquisition and
photo/sensor placement editing with traceable attachments, and M5 including
the approved UVLO runtime rule (RUN-09). The automated PDF pagination check
(PDF-02) is also not implemented. Existing attachment references do not
constitute image upload or annotation tools. The physically qualified DUT/bench
envelope expands only with reviewed procedures and equipment limits; the
separate warm-start experiment does not add warm-start behavior to the ordinary
cold-start UI sweep.

In progress on this branch, not done: `reports/<rev>/exports/` and replacing
the renderer's hard-coded narrative literals.

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

`ui` is implemented. The older generic CLI `run --mode real` still rejects
hardware execution; configured real jobs use `JobService` through the UI.
`doctor` and `compare` remain reserved commands.

### Current verification record

For the current test totals, see the branch's final verification record; this
document does not carry a running count. One historical count is retained,
labeled as such: on 2026-09-27, before this branch's work, the non-browser
dcdc-bench suite passed 393/393 and the `Software/` (benchctl) suite 435/435.
Earlier per-selection counts have been removed from this document because
overlapping selections at different revisions cannot be summed.

Verification platform: this Raspberry Pi is aarch64. Chrome for Testing has no
linux-arm64 build, so the 13 `browser`/`pdf`-marked tests (WEB-*, EXP-01,
PDF-*) are not run on the Pi in the current cycle and must run on a laptop or
CI — the ARM limitation anticipated in brief §4.3. Quarto 1.10.18 is installed
under `dcdc-bench/.tools/`. The historical record below used Debian's
`chromium-headless-shell` through the renderer's browser lookup at the initial
checkpoint.

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
env DCDC_DEMO_DIR=/home/jerome/rigol-control/dcdc-bench/examples/generated \
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
