# New-user walk of dcdc-bench (simulation review)

Written 2026-09-30 by an engineer role that had never seen this repository,
following the documentation literally in the order it sends a first-time
reader, at commit `b38df08` (head of `dcdc-bench-hardening`) in a dedicated
worktree. Scope and limits of this review:

- **Read:** root `README.md`, `HANDOFF.md`, `dcdc-bench/README.md`
  ("Start here" and onward), `dcdc-bench/docs/README.md`,
  `dcdc-bench/docs/getting-started.md`, then `docs/bench-ui.md` because both
  the index and the guide send you there next.
- **Ran (nothing touches an instrument):** `--help` for the CLI and all eleven
  subcommands; `validate` and `plan` against the shipped mock profiles;
  `python -m dcdc_bench.resources`; `benchctl --help`; one `curl` against the
  loopback bench page to confirm it answers.
- **Did not run:** `demo`, `run`, `report`, any render, pytest, or anything
  that opens an instrument (shared, memory-limited Pi). The bench page was
  therefore judged from its source (`src/dcdc_bench/ui.py`,
  `ui_models.py`, the user-facing strings in `job_service.py`), not from a
  browser.
- **Read as artifacts:** one generated simulated report
  (`examples/generated/normal/<run>/reports/r0001/report.html`, its
  `exports/points.csv` and `points.meta.json`) and the demo `index.html`.

Line numbers below refer to the files at `b38df08`.

## 1. The path I took

Reading-time estimates assume an engineer reading technical prose at about
200 words per minute and pausing at every command block.

| # | Where the documentation sent me | Words | Newcomer time | What happened |
| --- | --- | ---: | ---: | --- |
| 1 | `README.md` (repository root) | 2 677 | 15 min | The header offers three "Start" links: *Getting started* (the dcdc-bench guide), *Contributing*, *Handoff*. The README's own **Start here** section is a different product (benchctl 5 V demo) with a different install command. Paragraph 4 is a wall of measured converter results and milestone codes (M0–M5) with no definitions. |
| 2 | `HANDOFF.md` (linked from the root header) | 2 362 | 12 min | Written for the owner and "future Claude Code sessions". Rules for AI agents, Pi hostnames, systemd units, memory monitor. Useful as a maintainer map; wrong audience for a first-time user, and it sends you to four more documents. |
| 3 | `dcdc-bench/README.md` → **Start here** | 3 193 | 18 min | Six-line quickstart, then a 110-word status sentence, then "What it does and what it does not do" (dense, undefined terms: *path efficiency*, *qualified*, *approvals*, *M2 qualification*). Sends you to `docs/getting-started.md` first, `docs/bench-ui.md`, `docs/configured-runs.md`, `docs/README.md`. |
| 4 | `dcdc-bench/docs/README.md` (index) | 1 505 | 8 min | Tables of every document; two thirds are "agent-role" reviews of specific runs. The **Start here** table (three rows) is the useful part. Claims to list every file; four are missing (§2, C18). |
| 5 | `dcdc-bench/docs/getting-started.md` | 5 239 | 30 min to read; 1.5–2 h to perform §3–§4 on a laptop (plus 10–15 min for `demo` on a 1 GB Pi per its own estimate) | The best document on the path: numbered steps, "What you should see" after each, REAL HARDWARE flags. Its first step (`git clone`) lands on `main`, which has no `dcdc-bench/` (C22). |
| 6 | `dcdc-bench/docs/bench-ui.md` | 2 075 | 10 min | Describes the page well; contradicts the page footer on photograph annotations (C41). |
| 7 | `dcdc-bench --help` and eleven subcommand `--help`s | — | 2 min | Top-level list matched the guide's §3.7 prediction. Six subcommands have no description and no argument has a help string (C23). |
| 8 | `validate` and `plan` on `profiles/dut/12t12-4a.yaml` + `profiles/bench/mock.yaml` + `profiles/recipes/12t12-4a-quick.yaml` | — | 1 min | Output matched the guide's §4.1 prediction exactly: `"requested": 21`, `"executable": 19, "assumption_limited": 2`, a 64-character `plan_hash`, four warnings, the first being `Planning estimates are not measurements or validated safety limits.` The two limited points are 12 V / 0.75 A and 12 V / 1 A as stated. |
| 9 | `curl -s -H 'Host: localhost' http://127.0.0.1:8081/` | — | 1 min | HTTP 200, `<title>DC–DC Bench</title>`, a NiceGUI shell (19.5 kB). The service is on 8081 as `HANDOFF.md` says; the dcdc-bench README quickstart says 8082 (C7). |
| 10 | `ui.py` (1 592 lines) and `ui_models.py` (440 lines), every label and message | — | 30 min (a browser user would need 10 min) | See §2, C26–C41. |
| 11 | Simulated report text, CSV, metadata, demo index | — | 10 min | Synthetic status is recognisable in under five seconds (C43); the boundary phrase is not (C44). |

Totals: about **1 h 25 min of reading** before the first command that produces
anything (`validate`, at getting-started line 203, roughly 13 000 words into
the path); the quickstart command that produces something *visible* (`demo`)
is one the guide itself says to run on a laptop instead.

Order problems in the path: the root README points a benchctl reader at the
dcdc-bench guide and a dcdc-bench reader at a maintainer handoff; the
dcdc-bench README's quickstart precedes its own "What it does" section; the
getting-started guide defines *path efficiency* in its last content section
(§7) after using the term from §1.

## 2. Confusion log

Severity: **Blocker** (a first-time user cannot proceed), **Major** (a
first-time user proceeds with a wrong belief about what is simulated, what is
real, or what the tool can do), **Minor** (friction or copy-editing).

### Root README.md

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C1 | `README.md` lines 15–16 vs the **Start here** section (lines 81–121) | One start and one install command. | The header's **Start** link opens `dcdc-bench/docs/getting-started.md` (install: `pip install -e . -e './dcdc-bench[ui,report,real]'`), while the README's own **Start here** installs `pip install -e '.[dev]'` (benchctl only) and describes the 5 V demo. A reader who follows the README body never gets dcdc-bench installed. | Major | Header: "**Start:** [5 V supply-to-load demo](#start-here) · [DC–DC converter bench](../getting-started.md)". Use the combined install line in both places. |
| C2 | `README.md` lines 18–42 | An overview paragraph. | Twenty-four lines of measured results ("reached **1.725 A output** while drawing **0.987 A**"), milestone codes and a warning that the local URL "does not work from GitHub". Links such as `#completed-test-through-the-interface` land on six `<a name>` anchors stacked on one line above a table in `dcdc-bench/README.md`, not on a section. | Minor | Move results to `dcdc-bench/docs/measured-results.md` (they already live there) and keep two sentences here. |
| C3 | `README.md` line 22 and everywhere after | Plain words. | "M0 reached; M1 substantially reached; M2 partial; an M3 workflow slice demonstrated; M4 and M5 software present on mock and stored data only." The milestone codes are defined only in `implementation-brief.md` §15, which no start page links at first use. | Major | Add a one-line legend at first use, e.g. "(M0 skeleton, M1 mock pipeline, M2 measurement qualification, M3 real workflow, M4 comparison/thermal, M5 full power)", or link the brief section. |
| C4 | `README.md` line 36 | — | "stopped without a **qualified** efficiency result". *Qualified* is used across all documents and the report and is never defined. | Minor | Glossary entry (§3) linked from the first use. |
| C5 | `README.md` line 16 → `HANDOFF.md` | A user-facing handoff. | A file "for the project owner and for any future Claude Code session", with agent rules ("Never energize instruments on your own"), Pi hostnames, home-directory paths and the username — which its own rule 6 says to keep out of new public files. | Major | Label the link "Maintainer handoff (owner and coding agents)"; move it next to *Contributing*; strip or genericise the private details. |

### HANDOFF.md

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C6 | §4 "Branch state and how to verify it" | Current numbers. | "Last verified state (2026-09-28, commit `cc98899`) … 692 passed", while §9 says "Suite: 832 non-browser tests" and HEAD is `b38df08`. | Minor | Refresh §4 or state that the counts are historical. |
| C7 | §2 table (UI service on `--port 8081`) vs `dcdc-bench/README.md` line 29 ("bench page on http://localhost:8082") | One port. | Two ports: the persistent service on 8081; a manually started page on 8082. The getting-started guide explains this only in §6.1 (the real-test section). | Minor | In the dcdc-bench quickstart: "On the development Pi a service already serves this page on 8081; use that instead of starting a second copy." |
| C8 | §1 | — | "Treat every `MUST` in it as an acceptance requirement"; "byte-identical to the owner's master copy `~/1README.md`". Irrelevant to a user; puzzling. | Minor | Keep in a maintainer section only. |

### dcdc-bench/README.md

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C9 | **Start here** lines 23–30, `tools/setup.py` | One virtual environment. | Line 25 installs both packages into the root `.venv`; line 27 then runs `tools/setup.py`, which (per its source) creates a **second** environment at `dcdc-bench/.venv` with only the `[report,test]` extras (no `ui`, no benchctl) and downloads Quarto. **Try the demonstration** then uses `.venv/bin/dcdc-bench demo` "from this directory", i.e. the second environment. The guide (§3.6) concedes "you can ignore it". | Major | Give `setup.py` a `--tools-only` mode (Quarto + browser only) and call that from both READMEs, or state in one sentence "setup.py is for the Quarto download; ignore the environment it creates". |
| C10 | **Start here** line 28 | What the demo produces. | "three simulated reports; run on a laptop if you can" — where they land and how to open them is five screens later. | Minor | "…writes `dcdc-bench/examples/generated/index.html`; open it in a browser." |
| C11 | "What it does…" line 58; root README; guide §1 | A definition at first use. | *path efficiency* is used from the first paragraph and defined only in getting-started §7 (line 585). | Major | At first use: "path efficiency — output power ÷ input power measured at the *instrument* terminals, so it includes the losses in both pairs of leads". |
| C12 | **Status** line 43 and **What comes next** line 339 | A short status. | One 110-word sentence, pasted twice verbatim. | Minor | Keep it once, as a bulleted list. |
| C13 | **What comes next** lines 343–344 | — | "…and to write the / act on the written [12 V cold-start hypothesis]…" — a sentence fragment. | Minor | Copy-edit. |
| C14 | "Use the bench interface" line 78 vs "Start here" line 38 | One flow summary. | "Select converter → choose voltages and loads → preview limits → Start → watch progress → open HTML/PDF" and "Select → Preview → Confirm → Start → Stop"; neither says that the simulated bench has no *Confirm*. | Minor | One summary: "Select → Preview → (real bench only: Confirm) → Start → reports appear under Run and Reports". |
| C15 | "Try the demonstration" line 124 vs Start here line 28 | Same output path. | `--out examples/generated` (relative to `dcdc-bench/`) vs `--out dcdc-bench/examples/generated` (relative to the root) — the same place written two ways, from two working directories. | Minor | State the working directory once and use one form. |
| C16 | "Evidence and reports" lines 250–275 | Named identifiers. | `runs/<run_id>/`, `analysis/<analysis_id>/`, `reports/<revision>/`, and in the UI `jobs/<job_id>/` — four identifiers whose relationship is only implied ("A formula version changes the analysis ID; rerendering creates a new report revision"). | Major | One paragraph: "A *job* is one press of Start; it holds one *run* (the evidence); a run can have several *analyses* (one per formula version) and several *report revisions* rNNNN (one per render)." |
| C17 | "More commands" lines 177–189 | — | "All of these run without instruments except `doctor`" is good. `publish … --approval approval.yaml` gives no hint what an approval file is until you open `doctor-and-publication.md`. | Minor | Add "(a small YAML the owner writes; see …)". |

### dcdc-bench/docs/README.md (index)

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C18 | Line 3: "Every file in this folder, listed once" | A complete index. | Not listed: `instrument-specifications.md`, `m2-freshness-and-readback-evidence.md`, `standards/README.md`, `standards/iso16750-2.md` (and now this folder). | Minor | Add the rows, or add a test that compares the folder with the index. |
| C19 | Whole page | Guidance on what to skip. | Roughly two thirds of the rows are "agent-role" reviews of individual measured runs. Nothing tells a newcomer that these are audit trail, not reading material. | Minor | A heading above them: "Audit trail — read only if you are checking a specific run". |

### dcdc-bench/docs/getting-started.md

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C20 | §1 lines 50–52: "It does not measure no-load consumption" | A true statement about capability. | The README says it "calculates … enabled-no-load consumption"; the planner's own warning reads "No-load input consumption must be measured; it is not inferred from output current"; the simulated report has a table **Enabled with no external load** with input-current numbers; a seeded real recipe is titled "24 V — no-load window, then 0.1 A". I could not tell whether the tool measures no-load or not. | Major | "It reports the input consumption at 0 A load ('enabled with no external load'); it does not measure controller quiescent current, and no efficiency is computed at 0 A." |
| C21 | §1 line 51: "does not use remote (4-wire) sensing"; §5.3 "Use local sensing" | The simulated bench to mirror the real one. | `profiles/bench/mock.yaml` has `load.remote_sense_required: true`; the simulated report's *Setup and method* says "Remote sense: required" and "Separate load S+ / S− sense leads terminate at the DUT output". The demo therefore depicts a wiring the real bench does not use, and nothing in the report says so. | Major | Either set the mock load to local sense like the real bench, or add a report line "The synthetic bench assumes load remote sense; the DP821A/DL3031A bench uses local sense and its efficiency includes lead losses." |
| C22 | §3.1 lines 77–86 | A clone that works. | `git clone …` checks out `main`, which has no `dcdc-bench/`. The guide's remedy is "ask the project owner which branch to check out" and it says the branch "had not been pushed" — `HANDOFF.md` §3 says it is on GitHub as `dcdc-bench-hardening`. | Blocker | `git clone -b dcdc-bench-hardening https://github.com/robomaniac/rigol-control.git` (or the branch that is merged to `main` by the time the owner reviews), and delete the "ask the owner" sentence. |
| C23 | §3.7 line 157 and the line-1 promise "every command below was checked to parse with `--help`" | `--help` as a reference. | The top-level list matched. But `validate`, `plan`, `run`, `demo`, `analyze` and `report` have **no description**, and **no argument anywhere has a help string** (`--dut DUT`, `--formats FORMATS`, `--arm`, `--scenario`). `run --mode real` is accepted by the parser and refused at run time ("M1 supports mock execution only"). `benchctl --help`, by contrast, describes every subcommand. Also `python -m dcdc_bench --help` prints `usage: __main__.py`. | Major | Add `help=` to every subparser and argument (`--formats html,pdf`; `--arm` "operator arming for the fixed procedures; refused here"); set `prog="dcdc-bench"`. |
| C24 | §4.1 lines 206–212; `plan.json`; CSV; UI | One name per status. | The same two points are `assumption_limited` in the CLI JSON and plan, **Outside planning budget** in the UI plan table (`ui_models.plan_rows`), and `unsupported` in the report and CSV `qualification` column. The plan reason ends "request retained **without clipping**", which is unexplained. | Major | One vocabulary shown everywhere with the internal name in parentheses once; expand "without clipping" to "the request is kept in the plan and skipped; it is not reduced to fit". |
| C25 | §4.5 line 274: `run --plan plan.json --mode mock --out dcdc-bench/runs` | A scratch location. | `dcdc-bench/runs/` is, per `HANDOFF.md` §3, "the project's only copy of the real measurements". A newcomer's first mock run lands next to the measured evidence, distinguishable only by a field inside the files. | Major | `--out dcdc-bench/examples/generated/manual` (or `dcdc-bench/workspace/runs-mock`), and a sentence "never write practice runs into `dcdc-bench/runs/`". |
| C26 | §4.6 lines 282–289: "the button reads **Start simulated test**" | What happens after pressing it. | Nothing. From `job_service.worker`: the job goes *Acquiring measurements* → *Measurements saved — report queued* (possibly "Waiting: MemAvailable below 150 MiB" for as long as the Pi is busy) → *Preparing HTML and PDF* (minutes) → *Complete*, and the report appears as links under **Run** and in the **Reports** table, with a "Report ready" toast. The Plan panel meanwhile says "Estimated time: simulated · seconds". | Major | In §4.6 and in the Plan panel: "Simulated acquisition takes seconds on a virtual clock; the HTML and PDF report is queued behind free memory and takes several minutes on a Pi; links appear under Run and in Reports." |
| C27 | §5.2 line 322, §5.5 table, §5.8 line 429 (bold UI labels) | The guide's bold labels to match the checkboxes. | Guide: "**The converter input is connected to power-supply channel 1**" — UI: "The converter is on DP821A CH1 (not CH2) and the load input". Guide: "**This converter profile is approved for real hardware**" — UI: "This converter is approved for the real bench". Guide: "**These protective limits were reviewed and are approved for this bench**" — UI: "I reviewed these limits — required once" / "Limits approved for this preset". Guide: the Start confirmation includes "**I reviewed these limits and will supervise the run**" — UI: "I reviewed the protective limits: 1 A supply · 26 V input · 13.2 V / 2.55 A output"; **no supervision statement exists in the UI**. | Major | Generate the guide's labels from `ui.py` constants or add a test that each bold UI label in the guide occurs in `ui.py`; decide whether the supervision pledge belongs in the UI (the guide implies it does). |
| C28 | §6.8 line 549 | — | "**Open interactive HTML**" — the link reads "Open HTML" (`ui_models.report_link_rows`). | Minor | Match. |
| C29 | §5.9 line 440 "one exclusive **lease**"; §8 "bench lease held" | A definition. | None. It is the file lock `dcdc-bench/runs/.bench-activity.lock` (or `DCDC_ACTIVITY_LOCK`), held during acquisition and rendering. | Minor | Glossary entry; first use: "lease (a lock file that lets only one acquisition or render run at a time)". |
| C30 | §6.10 line 571 "(`report-queued`)" | — | The UI never shows the string `report-queued`; it shows "Measurements saved — report queued". | Minor | Drop the internal name or say "(internal state `report-queued`)". |
| C31 | §7 lines 592–600: "**Uncertainty unquantified** means no readback uncertainty budget was evaluated…" | The demo to behave as described. | The simulated report shows "95.24 % **± 0.37 percentage points** (k = 2, specification-bound only (synthetic example))" and shaded bands. Nothing in the guide says the demo's ± comes from invented specification numbers in `mock.yaml` (`status: synthetic_example`) while a real bench will show "not evaluated". A newcomer sees a precise ± in the demo and expects one from the bench. | Major | Guide §4.4: "The demo's ± values come from *example* specifications written into the mock bench profile; they demonstrate the budget's format, not any instrument's accuracy. A real bench shows 'not evaluated' until datasheet terms are transcribed." Report: replace the nested parentheses with "(k = 2; from example specifications of the synthetic bench)". |
| C32 | §2 Memory row; §4.2; §8 | Advice for the current machine. | Everything is framed for a 1 GB Pi needing "768 MiB of temporary disk swap"; `HANDOFF.md` §2 says the card moved to a Pi 4; `python -m dcdc_bench.resources` today reports 1 845 MiB total with 780 MiB of swap already in use. | Minor | Keep the 1 GB notes as a sub-bullet; lead with "check `python -m dcdc_bench.resources`; rendering needs ≥ 150 MiB available and ≥ 600 MiB available + free swap". |
| C33 | §4.1 line 208 "four warnings starting with `Planning estimates…`" | — | Reads as "all four begin with that phrase"; only the first does. | Minor | "four warnings, the first being …". |

### The bench page (from `ui.py`, `ui_models.py`, `job_service.py`)

Is "Simulation" obvious? Mostly yes, on the page body: the default tile is
**Simulated bench** with "Nothing is switched on. Synthetic readings, real
report layout."; the header idle pill says "Idle — nothing switched on"; the
Plan panel says "Bench: Simulated — nothing switched on"; the Start button
reads "Start simulated test"; the Run panel says "Simulated test · no real
instruments"; the Reports table has a **Bench** column (Simulated/Real). The
gaps are below.

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C34 | Header activity pill, `ui_models.activity_text` / `ui.show_activity` | The simulated/real distinction in the one place everyone looks. | During a simulated job the header reads "Acquiring… point 2 of 21 · 12T12-4A · started … · elapsed …" with no "simulated"; only the Run panel further down says so. On a shared bench page a passer-by cannot tell. | Minor | Prefix "Simulated: " / "Real bench: " in `activity_text`. |
| C35 | Converter card meta, `ui.render_converters` | Nothing about approvals while simulating. | "Not yet approved for the real bench" is shown under every converter even with the Simulated bench selected; a simulation-only user wonders what they must approve. | Minor | Show the approval line only when the Real tile is selected, or grey it with "(real bench only)". |
| C36 | Plan panel ready line, `ui.render_plan` line 1109 | Where the report will appear. | "Ready. HTML and PDF reports are generated automatically after acquisition." — no mention of the queue, the delay or where the links appear. | Minor | "…are queued after acquisition (minutes on a Pi) and appear as links under Run and in Reports." |
| C37 | Run panel while `report-queued`, `ui.show_status` lines 1326–1328; `resources.MemoryGate` | Plain language. | "…Report generation is queued and starts automatically when no test is running and enough memory is free. Waiting: **MemAvailable below 150 MiB**." `MemAvailable` is a `/proc/meminfo` field name; "bench lease held: …" is the other reason. (The phrase "deferred: memory" from the brief does not appear anywhere; `deferred_reason` is rendered as "Waiting: <reason>".) | Minor | "Waiting: the bench computer has less than 150 MiB of free memory" / "Waiting: another acquisition or report is running". Keep the raw reason in a tooltip. |
| C38 | Reports table, `ui.render_reports` | — | **Regenerate report** is offered on every finished job, including *Complete* ones; a newcomer reads it as "the report is stale". | Minor | Tooltip "Makes a new report revision rNNNN from the saved measurements; nothing is re-measured." |
| C39 | Tests footer, `ui.render_tests` line 914 | — | "Simulated vs real is not part of a test **any more** — it comes from question 2." The history is not the newcomer's. | Minor | "Whether a test runs simulated or real is decided by question 2." |
| C40 | Plan table, `ui_models.plan_rows` | — | Status labels **Ready / Outside planning budget / Needs approval / Not supported** are good plain words, but they differ from the CLI and the report (C24). | — | Covered by C24. |
| C41 | `docs/bench-ui.md` lines 222–224 vs the page footer (`ui.py` line 1566) and README "More commands" | Consistent capability claims. | bench-ui.md: "Adding or repositioning photographs and schematics through the UI … is **not currently available**". The page footer links "Sensor placement editor — add photographs and sensor markers to a finished run" (`/annotations`), and the README says the UI adds an `/annotations` page. | Major | Update bench-ui.md: "Photographs and sensor markers are added on the separate `/annotations` page; each save creates a new report revision and never edits measurements." |
| C42 | `curl` of `http://127.0.0.1:8081/` | The documented default. | Answers (HTTP 200, title "DC–DC Bench"); this is the service port from `HANDOFF.md`, not the 8082 default from the READMEs. | — | Covered by C7. |

### The simulated report and CSV (`examples/generated/normal/…/reports/r0001/`)

| # | Where | What I expected | What I found | Severity | Suggested wording or step |
| --- | --- | --- | --- | --- | --- |
| C43 | `index.html`; report header; Summary; figure captions; `exports/points.csv` column 3; `points.meta.json` | To know within five seconds that it is synthetic. | Yes. Index: "**SYNTHETIC — software demonstration only.** … No real equipment was connected. These are not measurements of your converter." Report subtitle: "SYNTHETIC · 12T12-4A · <run_id> · <analysis_id>". Summary first line: "SYNTHETIC — source-to-DUT-output path." Every figure caption starts "SYNTHETIC." The appendix says "these observations come from a deterministic plant model, not the physical 12T12-4A" and "Virtual-clock timestamps represent simulated model time". CSV: `evidence_type = SYNTHETIC` on every row; metadata: `"evidence_type": "SYNTHETIC"`. | — | Good; keep. |
| C44 | Summary line "SYNTHETIC — source-to-DUT-output path." | To understand the second half. | I did not, until *Setup and method* three screens later. "source-to-DUT-output path" is the *measurement boundary* (the `measurement_boundary` string in the bench profile): the readings are taken at the supply's terminals and at the load's terminals, so everything between — both lead pairs and the converter — is inside the number. Read cold, it looks like a product or mode name joined by hyphens. | Major | "SYNTHETIC data · measured from the supply terminals to the converter output (lead losses included)". Keep the machine string in the appendix. |
| C45 | Summary bullet "95.24 % ± 0.37 percentage points (k = 2, specification-bound only (synthetic example))" | Readable uncertainty. | Nested parentheses; *k = 2* (coverage factor) and *specification-bound* are not explained on the page until the appendix. | Minor | "± 0.37 percentage points (95 %-style expanded uncertainty, from the synthetic bench's example specifications)". |
| C46 | *Device under test* table | — | "Owner-provided aliases: Cocar, Ekylin, Bgoodvision", "Rated output 4.0 A / 48.0 W", "Rating origin: user_supplied" — looks like a real product page beside a 95 % efficiency headline. The SYNTHETIC labels mitigate; the DUT block itself carries no such label. | Minor | Add "(profile data; not measured in this synthetic run)" to the DUT block heading. |
| C47 | *Setup and method* → "Load … Remote sense: required", "Separate load S+ / S− sense leads terminate at the DUT output" | The real bench's wiring. | Covered by C21: the demo describes remote sense, the real bench uses local sense. | — | See C21. |
| C48 | *Acquisition method* → "Timing basis: virtual … simulated acquisition; virtual timestamps are model time, not hardware observations" | — | Clear and honest. | — | Keep. |
| C49 | Appendix table: p0006/p0007 "unsupported — Requested load exceeds the planning budget (0.72 A output at assumed efficiency 80 % and source-current budget 90 %); request retained without clipping" | The plan's own word. | The plan said `assumption_limited`; the report says `unsupported`. | — | Covered by C24. |
| C50 | `exports/points.csv` | — | Columns `programmed_input_V` and `input_condition_label` are empty for every row of the mock run; `points.meta.json` explains them, so this is fine. The `evidence_type` column in position 3 is the right place. | — | Keep. |

## 3. Glossary of terms I had to infer

Terms a first-time user meets before any document defines them. Definitions
below are what I inferred from code and artifacts; the owner should confirm.

| Term | Where first met | Inferred meaning |
| --- | --- | --- |
| **DUT** | Guide §1 | Device under test — the converter. Defined at first use; listed for completeness. |
| **Path efficiency** | Root README; dcdc-bench README para 1 | Output power ÷ input power with both measured at the *instrument* terminals (supply output, load input), so the losses in both lead pairs are inside the number. Defined only in guide §7. |
| **Measurement boundary / "source-to-DUT-output path"** | Report summary line | Where the four readings are taken; names the span the efficiency figure covers. Comes from `measurement_boundary` in the bench profile. |
| **Qualified / qualification** | Root README ("qualified efficiency result"); report; CSV column | Whether a point's readings met the settling and acquisition policy ("fresh complete cycles acquired after electrical settling") and can carry a nominal efficiency claim. Values seen: `valid`, `unsupported`; the UI adds "Live values are unqualified readings". |
| **executable / assumption_limited / approval_blocked / unsupported** | Guide §1; CLI JSON | Planner statuses per requested point: will run; kept but skipped because the planning budget (assumed efficiency × share of source current) says the supply cannot feed it; blocked until the three saved approvals are true; outside the bench or backend envelope. The UI shows Ready / Outside planning budget / Needs approval / Not supported; the report shows valid / unsupported. |
| **Planning budget** | Plan reason text | Assumed efficiency (default 80 %) and share of the source's current limit (default 90 %) used to decide which requested loads the 1 A supply can feed. Explicitly "not measured efficiency". |
| **"Request retained without clipping"** | Plan reason text | The requested point stays in the plan and report as skipped; it is not reduced to a smaller load that would fit. |
| **Job / run / analysis / report revision** | README "Evidence and reports"; UI | A *job* is one press of Start (`workspace/jobs/<job_id>/`); it holds one *run* (the immutable evidence, `runs/<run_id>/`); a run can have several *analyses* (`a-…`, one per formula version) and several *report revisions* (`r0001`, `r0002`, one per render). |
| **Revision** | README; UI "Regenerate report" | A new render of the same evidence; never a change to the evidence. |
| **Lease** | Guide §5.9, §8 | A lock file (`dcdc-bench/runs/.bench-activity.lock` or `DCDC_ACTIVITY_LOCK`) so only one acquisition or render runs at a time. "Bench lease held" = something else is running. |
| **Memory gate** | Guide §2, §6.8 | A refusal to start a render when `MemAvailable` < 150 MiB or `MemAvailable + SwapFree` < 600 MiB (environment-overridable). |
| **report-queued / Waiting: …** | Guide §6.10; UI | Job state after acquisition: measurements saved, outputs verified OFF, render not yet started; the UI shows "Measurements saved — report queued" and, if held back, "Waiting: <reason>" (memory gate or lease). |
| **Worker** | Guide §1, §6 | The separate process that owns the instruments (or the synthetic plant) for one job; the page only watches it. |
| **Profile** (DUT / bench / recipe / report) | dcdc-bench README | The four YAML/JSON inputs: converter ratings; equipment envelope and protective limits; the grid of input voltages × loads and timing; report styling. |
| **Preset** | UI question 2 | A saved *bench* profile with `mode: real`; the pills under the Real tile. |
| **Inventory** | Guide §5.4 | `Software/config/lab.yaml`: instrument addresses and expected serials; private; needed only for the real bench. |
| **Approvals (the three)** | dcdc-bench README; guide §5.5 | Saved booleans: DUT `real_hardware_enabled`, DUT `wiring_and_polarity_confirmed`, bench `protective_controls.approved`. Necessary before a real *preview* is supported; not sufficient for Start. |
| **Arm / `--arm`** | Guide §1; `run --help` | Operator action that lets a fixed real procedure energize; refused by the generic CLI. |
| **Doctor** | README; guide §5.7 | Read-only instrument check (`*IDN?`, output states, protections, error queue); exit 0 clean, 4 findings, 2 refused. |
| **M0 … M5** | Root README | Milestones from `implementation-brief.md` §15; never defined on the start pages. |
| **SYNTHETIC / MEASURED** | Report; CSV | `evidence_type` of a whole run: from the deterministic plant model, or from instruments. |
| **Virtual clock / timing basis: virtual** | Report; UI card meta | The simulated bench advances model time instead of waiting; its "durations" are not wall-clock. |
| **k = 2 / expanded uncertainty / specification-bound** | Report | Metrology terms: coverage factor 2 applied to a budget built only from declared instrument specifications (in the demo, invented example specifications). |
| **Enabled with no external load** | Report; README | Input consumption at a requested 0 A load with the converter powered; "not controller quiescent current". |
| **Local vs remote sense** | Guide §5.3; report | Whether the load measures voltage at its own terminals (local) or through separate sense leads at the DUT (remote). Real bench: local; mock profile: remote required. |
| **Agent-role review** | Docs index | A review written by an automated agent in the authoring pipeline, not by a person. |
| **RUN-02, CMP-01/02, PDF-02, WEB-08** | README, HANDOFF | Acceptance IDs from `implementation-brief.md` §14. |
| **Freshness** | README, HANDOFF, guide §7 | Whether an instrument's readback reflects a new ADC conversion rather than a repeated value; "unquantified" on the real bench. |
| **Window / cycle / phase** | README results table; report | Phase: one input-voltage condition; window: the acquisition interval for one load point; cycle: one complete set of the four readings within a window. |

## 4. Top 5 changes before the owner's review

1. **One entry point that works from a fresh clone.** Fix the clone step
   (C22, the only Blocker: `git clone` lands on `main` without `dcdc-bench/`),
   make the root README header distinguish the two products and use one
   install line (C1), and stop `tools/setup.py` from creating a second
   environment in the quickstart, or say plainly that it only fetches Quarto
   (C9). Move `HANDOFF.md` behind a "maintainers" label (C5).

2. **Resolve the four places where I could not tell what the tool does or
   what is simulated.** No-load consumption is both "not measured" and
   tabulated (C20); the mock bench assumes remote sense that the real bench
   does not use, and the demo report shows that wiring unlabelled (C21); the
   demo shows ± uncertainty while the guide promises "unquantified" (C31);
   bench-ui.md says photographs cannot be added while the page links an editor
   for them (C41).

3. **One vocabulary and a glossary.** Point status is `assumption_limited` in
   the CLI, "Outside planning budget" in the UI and `unsupported` in the
   report and CSV (C24); *path efficiency*, *qualified*, *revision*, *lease*,
   *M0–M5* are used before they are defined (C11, C4, C16, C29, C3). Ship §3
   of this file as `docs/glossary.md`, link it from the first use in each
   README, and render the summary boundary phrase in words (C44).

4. **Make "Start simulated test" honest about what follows.** Say in the
   guide and in the Plan panel that simulated acquisition takes seconds on a
   virtual clock but the report is queued behind free memory and takes
   minutes, and where the links appear (C26, C36); prefix the header pill
   with "Simulated:" (C34); phrase the wait reason in plain words instead of
   `MemAvailable` (C37).

5. **Align safety text and the CLI reference with reality.** The guide's bold
   confirmation labels do not match the checkboxes, and it promises a
   supervision pledge the UI never asks for (C27) — add a test that every bold
   UI label in the guide exists in `ui.py`. Add `help=` strings to every
   `dcdc-bench` subcommand and argument so that `--help` answers the questions
   the guide says it was checked against (C23); `benchctl --help` already
   shows how.

What worked and should be kept: the guide's "What you should see" pattern
(its §3.7 and §4.1 predictions matched the CLI byte for byte); the REAL
HARDWARE markers; the SYNTHETIC labelling of the demo index, report header,
captions and CSV (C43); the "Timing basis: virtual" statement (C48); and the
page copy "Nothing is switched on. Synthetic readings, real report layout."
