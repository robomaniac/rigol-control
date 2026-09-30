# dcdc-bench documentation index

Every file in this folder, listed once with a one-line description taken from
the file itself. The [project README](../README.md) is the front door; this
page tells you which document to open next. Dates are the ones the documents
state; all reviews marked *agent-role* were performed by an automated agent
role in the same authoring pipeline, not by a human or external reviewer, and
say so in their first lines.

## Start here

| Document | What it is |
| --- | --- |
| [getting-started.md](getting-started.md) | For an engineer who has never seen this repository: what the software does, what to install, how to run it with no hardware, what must be true before any real converter test, and how to run and read a real test; every command checked with `--help`, hardware-touching ones marked **REAL HARDWARE**. |
| [bench-ui.md](bench-ui.md) | The local bench page: a saved converter plus input voltages and output loads, a check of what the equipment can reach, the measurements, then links to the interactive HTML report and printable PDF; starting the page, port forwarding and reconnect behaviour. |
| [configured-runs.md](configured-runs.md) | Configure and run a converter test from saved DUT, equipment and recipe profiles (data, not Python): the supported real procedure, its current physical envelope, the systemd launcher and where job evidence is saved. |
| [glossary.md](glossary.md) | Words the bench page, the reports and the guides use before they define them: path efficiency, qualified, the planner's status words, SYNTHETIC, revision, lease, memory gate, `report-queued`, the milestones M0–M5; each with where it comes from in the code. Linked from the page footer. |

## Design contract

| Document | What it is |
| --- | --- |
| [implementation-brief.md](implementation-brief.md) | The specification and coding-agent handoff for reusable DC–DC characterization and engineering reports: goals, the first DUT and bench envelope, architecture, module contracts (section 5), data contract, analysis and uncertainty, report model, acceptance IDs (section 14) and milestones (section 15). Written as a target, not a claim that the application exists. |
| [architecture.md](architecture.md) | Module map for an engineer new to the code: the data flow from profiles to HTML/PDF, one row per module with its entry points, what it must never do and the tests that cover it, plus the run-folder and job-workspace layouts. |
| [acceptance.md](acceptance.md) | Maps every Section 14 acceptance ID in the brief to its milestone and verification; rows marked **deferred** are not implemented claims; a calculation fixture proves its calculation, not the physical bench. States the milestone position identically to implementation status and the README. |
| [implementation_status.md](implementation_status.md) | Current milestone position against the brief's Section 15 exit criteria, the executed commands, platform, rendered artifacts, browser/PDF results, test totals, the next bounded task and the known limitations. |

## Engineering guides

| Document | What it is |
| --- | --- |
| [uncertainty-budget.md](uncertainty-budget.md) | The structured readback uncertainty budget written to `analysis/<analysis_id>/uncertainty.json`: each profile field, the formulas, what the bench owner must enter before a real bench produces a number, and what stays unquantified afterwards. Unknown inputs never become a numerical zero. |
| [simulation-plant.md](simulation-plant.md) | The simulated plant: equations and parameters of the synthetic converter, source and load, start-up and current-limit collapse, readback and thermal models, the run budget, the fit against the measured 12T12-4A and what is deliberately not modelled. |
| [doctor-and-publication.md](doctor-and-publication.md) | The read-only `doctor` command, the outputs-OFF readback-cadence probe and the approval-gated `publish` command; developed and tested against fake SCPI sessions only, with statements still needing bench confirmation labelled. |
| [pi-process-model.md](pi-process-model.md) | How acquisition and report rendering are separated into processes on the 1 GB bench Pi: the job state machine, the memory gate, descendant-process hygiene, what is logged where, the steady-state check procedure and the covering tests. |
| [engineering-figure-labels.md](engineering-figure-labels.md) | The report's engineering figure names (Efficiency, Load Regulation, Input Current, Power Loss, the time plots and the line-regulation figure), axis and legend conventions, and why regulation and dropout are different measurements. |
| [report-aesthetics-options.md](report-aesthetics-options.md) | Research, three figure-theme previews on already-issued evidence and decision questions about the report's look; the renderer, templates and issued reports are unchanged. |
| [github-readiness.md](github-readiness.md) | Read-only audit of the tracked tree before publication: scans for addresses, hostnames, serials, paths and credentials; sizes, line endings, version and Python-version statements; findings and the README changes they led to. |
| [cold-start-hypothesis.md](cold-start-hypothesis.md) | Written hypothesis and supervised test **proposal** for the failed 12 V startup, prepared from the retained evidence only; nothing in it authorizes energizing the converter. |
| [m2-qualification-plan.md](m2-qualification-plan.md) | Plan, not a record, for finishing M2 qualification: measurement freshness, readback accuracy, an evaluated uncertainty budget, the physical load's capability and a qualified enabled-no-load measurement; datasheet values are left to be transcribed, never invented. |

## Measured runs and their reviews

All runs were acquired on 2026-09-27 (UTC) on the reviewed DP821A CH1 / DL3031A
bench with the connected 12T12-4A. The narratives that used to be in the README
are collected in [measured-results.md](measured-results.md) (its
`http://localhost:8081/...` links are local to the owner's bench).

### Longer 24 V test (run `20260927T093948.075493Z_real_42e971`)

| Document | What it is |
| --- | --- |
| [extended-test.md](extended-test.md) | The fixed procedure and commands: three practical questions (regulation with load, efficiency with load, drift during a three-minute hold and return), the YAML grid and acquisition policy. |
| [extended-verification.md](extended-verification.md) | Agent-role verification record: preflight and independent shutoff, bench identities, the run's evidence and shutdown checks. |
| [extended-results-review.md](extended-results-review.md) | Agent-role results review; verdict: a guarded, partial-power DC characterization at 24 V and 50–500 mA whose accepted results reproduce from the raw readings. |
| [extended-code-review.md](extended-code-review.md) | Agent-role code review of `extended.py`, its use of the drivers, transport locking, run storage and the related analysis/renderer changes; no unresolved acquisition blocker. |
| [extended-ui-review.md](extended-ui-review.md) | Agent-role UI and UX review of the issued report (revision r0006) in an offline browser; no blocking findings remain. |

### Test near the supply's 1 A limit (run `20260927T173043.388477Z_real_75a478`)

| Document | What it is |
| --- | --- |
| [source-limit-test.md](source-limit-test.md) | The fixed procedure: 24 V input, load raised in 100 mA then 25 mA steps until the supply delivers about 0.98 A, a 30 s endpoint observation, return to 100 mA, both outputs OFF. |
| [source-limit-verification.md](source-limit-verification.md) | Agent-role verification of the acquisition: preflight, protection readbacks, the independent 720 s source cutoff and shutdown evidence. |
| [source-limit-results-review.md](source-limit-results-review.md) | Agent-role results review; the recorded acquisition and numerical analysis pass: 0.9873 A supply current, 1.7247 A at 11.8857 V delivered. |
| [source-limit-code-review.md](source-limit-code-review.md) | Agent-role code review of `source_limit.py`, its shared lifecycle and the source-search analysis/renderer changes; no unresolved blocking issue. |
| [source-limit-ui-review.md](source-limit-ui-review.md) | Agent-role UI and UX review of the issued report (r0001): stage guides, source-current figure, point inspector, exports, desktop/mobile layout. |

### Efficiency versus input voltage (startup attempt `20260927T184902.863440Z_real_e0fab9`, continuation `20260927T185631.575651Z_real_eb3bcd`)

| Document | What it is |
| --- | --- |
| [voltage-efficiency-test.md](voltage-efficiency-test.md) | The fixed procedure at 12 V, 24 V and near 36 V (35.8 V programmed, 35.93 V readback stop) with shared 100–700 mA requests and a 1.000 A source limit; why the upper condition keeps margin below 36 V. |
| [voltage-efficiency-code-review.md](voltage-efficiency-code-review.md) | Agent-role pre-live code review of `voltage_sweep.py` and the comparison changes; the 24 V / near-36 V continuation cleared. |
| [voltage-efficiency-results-review.md](voltage-efficiency-results-review.md) | Agent-role results review: 122 checks passed, all 27 continuation points qualified, the retained 12 V startup attempt accounted for. |
| [voltage-efficiency-ui-review.md](voltage-efficiency-ui-review.md) | Agent-role UI and UX review of the issued report (r0004): equipment table columns, aligned DUT tables, the explained startup stop. |
| [engineering-style-verification.md](engineering-style-verification.md) | Agent-role verification of the engineering figure style (names, colors, line patterns, markers) against this run's presentation revision r0005. |

### Start at 15 V, then reduce the input (run `20260927T212200.072951Z_real_b44da1`)

| Document | What it is |
| --- | --- |
| [startup-descent-results-review.md](startup-descent-results-review.md) | Agent-role review of the seven-condition descent from 15 V to 9.1 V under a 100 mA load: the converter kept about 12.13 V; method, measurements and limits of the claim. |

### Configured three-point run through the bench interface (job `20260927T223820Z_bb4a479f`, run `20260927T223823.159616Z_real_0038ff`)

| Document | What it is |
| --- | --- |
| [configured-workflow-results-review.md](configured-workflow-results-review.md) | Agent-role results review; PASS: all three requested points completed in 57.382 s with source, load and shutdown timer verified OFF. |
| [bench-ui-verification.md](bench-ui-verification.md) | Agent-role verification of the local operator page and its independent acquisition worker on the real bench: tabs, profile saving, preview, confirmation, progress, safe stop and report links. |
| [configured-backend-code-review.md](configured-backend-code-review.md) | Agent-role review of `real_backend.py`, `job_service.py` and `activity.py` with the fixed acquisition lifecycle; corrections made during review, no open blocking finding. |
| [workflow-ui-review.md](workflow-ui-review.md) | Agent-role operator-workflow code review of `ui.py`, `ui_models.py` and the `JobService` state metadata: six initial findings and how the code resolves each. |

## Merge reviews

| Document | What it is |
| --- | --- |
| [merge-code-review.md](merge-code-review.md) | Independent read-only code review (2026-09-28) of the nine parallel increments merged at `0ec41fd`, diff base `6630e8c`: 72 files, 15 new modules; findings ranked by severity against the brief's rules, each citing `file:line`; no blocker, seven majors; no tests, demo, render, UI or instrument run. |
| [merge-security-review.md](merge-security-review.md) | Independent defensive review of the attachments, annotation editor, publication, doctor, PDF-check and dispatcher surfaces merged at `0ec41fd`: threat model for owner-operated loopback bench software, then findings confirmed with small standalone Python probes against the real validators and route table (no pytest, renders, UI server or instruments). Its Resolution section (2026-09-30) records which findings commit `2582508` fixed and the three lows still open. |

## Simulation review round (2026-09-30)

Agent-role reviews of the simulated bench before the owner's review, each from
the standpoint of a particular reader; all five roles reported and their
findings were consolidated and assigned to implementers (see the first row).

| Document | What it is |
| --- | --- |
| [simulation-review/README.md](simulation-review/README.md) | Consolidated findings of the five reviewer roles and the fix assignments. |
| [simulation-review/ui-ux.md](simulation-review/ui-ux.md) | UI/UX designer's heuristic review of the bench page with screenshots. |
| [simulation-review/electrical-engineer.md](simulation-review/electrical-engineer.md) | Power-electronics engineer's review of the simulated plant, metrics and standards verdicts. |
| [simulation-review/new-user.md](simulation-review/new-user.md) | First-time user's walkthrough with a confusion log and glossary. |
| [simulation-review/manager.md](simulation-review/manager.md) | Engineering manager's verified-vs-claimed table, risk register and two-week plan. |
| [simulation-review/qa.md](simulation-review/qa.md) | QA engineer's observable-state table, robustness findings and proposed tests. |
