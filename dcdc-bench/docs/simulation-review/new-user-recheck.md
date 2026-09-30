# New-user re-check of dcdc-bench after the fix wave

Written 2026-09-30 by the same first-time-user role that wrote
[new-user.md](new-user.md), re-walking the documentation in the order it sends
a first-time reader, at commit `24d9371` (head of `dcdc-bench-hardening`) in a
dedicated worktree. Scope and limits, unchanged from the first walk:

- **Read:** root `README.md`, `HANDOFF.md`, `dcdc-bench/README.md`,
  `dcdc-bench/docs/README.md`, `dcdc-bench/docs/getting-started.md`, the new
  `docs/glossary.md`, then `docs/bench-ui.md`; `git log --oneline` from
  `b38df08` to `24d9371` (64 commits) and `git diff` of every document above.
- **Ran (nothing touches an instrument):** `python -m dcdc_bench --help` and
  all eleven subcommand `--help`s; `curl -H 'Host: localhost'` against
  `http://127.0.0.1:8081/` and `/glossary` to confirm they answer.
- **Did not run:** `demo`, `run`, `report`, pytest, any render, any UI server,
  anything that opens an instrument. The bench page was judged from
  `src/dcdc_bench/ui.py`, `ui_models.py` and `job_service.py`, not from a
  browser.
- **Read as artifacts:** the fresh simulated report in the main checkout
  (`examples/generated/normal/20260930T162316…/reports/r0001/report.html`,
  rendered after the mock profile changed), read-only.

Line numbers refer to the files at `24d9371`.

## 1. The path, re-walked

| # | Document | Words (was) | Changed since `b38df08`? | What a newcomer meets now |
| --- | --- | ---: | --- | --- |
| 1 | `README.md` (root) | 2 677 (2 677) | **No** — byte-identical | Same header with three "Start" links (`Getting started`, `Contributing`, `Handoff for the owner and future coding sessions`), same body **Start here** installing only benchctl (`python -m pip install -e '.[dev]'`, line 97), same paragraph of measured results and undefined milestone codes (line 22). No glossary link. |
| 2 | `HANDOFF.md` | 2 576 (2 362) | Yes — header, §3, §4, §8 | Opens with "**Maintainer and agent material.** … If you are new to the project and want to install it, run the simulated bench or read a report, start with dcdc-bench/docs/getting-started.md instead; this file assumes you already know what the bench is." (lines 3–10). This is the one structural change to the reading order: a newcomer who follows the root header's Handoff link is now turned round in the first paragraph. §3 says pull request #1 merged the branch to `main` and that `main` lags by 49 commits; §4 gives one dated collected test count (812 of 828). §1 still has "byte-identical to the owner's master copy `~/1README.md`. Treat every `MUST` in it as an acceptance requirement" (lines 25–26); private paths and user name remain (§8 item 2 declares them low-sensitivity and already public). |
| 3 | `dcdc-bench/README.md` | 3 269 (3 193) | Only the test-total sentence (line 313) and the GitHub note in **What comes next** | **Start here** is unchanged: six-line quickstart with `python3 dcdc-bench/tools/setup.py  # pinned Quarto into dcdc-bench/.tools/` (line 27), `demo --out dcdc-bench/examples/generated  # three simulated reports; run on a laptop if you can` (28), `ui … # bench page on http://localhost:8082, simulated bench` (29); the 110-word status sentence is still pasted twice (lines 43 and 339); "**Select → Preview → Confirm → Start → Stop**" (38) and "**Select converter → … → open HTML/PDF**" (78) both remain; *path efficiency* at line 58 still has no definition or link. No glossary link. |
| 4 | `dcdc-bench/docs/README.md` (index) | 1 744 (1 505) | Yes | The **Start here** table gained a fourth row: "[glossary.md] Words the bench page, the reports and the guides use before they define them: path efficiency, qualified, the planner's status words, SYNTHETIC, revision, lease, memory gate, `report-queued`, the milestones M0–M5; each with where it comes from in the code. Linked from the page footer." (line 17). A **Simulation review round (2026-09-30)** section lists the five reviews (lines 101–112). Line 3 still promises "Every file in this folder, listed once"; the same four files are still missing (§4, C18). |
| 5 | `dcdc-bench/docs/getting-started.md` | 5 562 (5 239) | Yes — §1, §3.1, §3.7, §4.6 | The clone step now works (§3.1). §1's no-load bullet is rewritten. §4.6 is a real walkthrough of the simulation with a "What you should see after Start" block. §4.1, §4.5, §5.5, §5.8, §6.8 and §7 are as before. |
| 6 | `dcdc-bench/docs/glossary.md` | 1 528 (new) | New | Four tables: Measurement words (10), Planning words (7), Workflow words (13), Milestones M0–M5 (6), each with a "Where it comes from" column. Covers every term in §3 of my first review except the acceptance IDs (RUN-02, CMP-01/02, PDF-02, WEB-08). Also served at `/glossary` from the page footer. |
| 7 | `dcdc-bench/docs/bench-ui.md` | 3 160 (2 075) | Rewritten | Describes the current one-page layout truthfully: "Simulation" tile with envelope and a panel **What the simulation can and cannot do**; **Start simulation** vs **Start test on the real bench** (only the latter opens the confirmation); the four-step sequence; the operator-language wait reasons; `/annotations` for photographs. It is now half again as long; item 2 of **Run a test** is one ~330-word paragraph. |
| 8 | `dcdc-bench --help` + eleven subcommands | — | Yes | `usage: dcdc-bench …`, every command described, every argument has a help string (§3, C23). |
| 9 | `curl … :8081/` and `/glossary` | — | — | Both HTTP 200 (`/`: 22.6 kB, title `DC–DC Bench`; `/glossary`: 40.4 kB, same title). The `/glossary` route exists only in the new build, so the running service is on a build that includes the fix wave. |

Reading before the first command that produces anything (`validate`, guide
line ~211) is about the same 13 000 words as before if the reader follows
every link; it is about 10 700 words if the reader obeys HANDOFF's new
first-paragraph redirect. Nothing on the two READMEs moved.

## 2. Top 5 from the first review

| # | Change asked for | Verdict | What I found |
| --- | --- | --- | --- |
| 1 | **One entry point that works from a fresh clone** (C22, C1, C9, C5) | **Partially** | C22 fixed (below). C1 not fixed: root README header and body still describe two products with two install lines. C9 not fixed: `tools/setup.py` still builds `dcdc-bench/.venv` (`venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")`, lines 27–28), no tools-only mode; the guide still says "creates a **second** environment … you can ignore it" (§3.6 lines 141–144). C5 partially: HANDOFF labels itself for maintainers and redirects newcomers; the root README link label and position are unchanged. |
| 2 | **Resolve the four places where I could not tell what is simulated** (C20, C21, C31, C41) | **Fixed** (one residual sentence) | All four resolved with the wording quoted in §3. Residual: guide §1 line 59 still says "reports say uncertainty is **unquantified**" with no "(real bench; the simulation shows an example budget)" qualifier, 230 lines above §4.6 where the demo's ± is finally explained. |
| 3 | **One vocabulary and a glossary** (C24, C11, C4, C16, C29, C3, C44) | **Partially** | `docs/glossary.md` exists with the paragraph I asked for on jobs/runs/analyses/revisions, the M0–M5 table, *lease*, *qualified*, *path efficiency*; it is linked from the docs index, guide §1 and §4.6, bench-ui.md and the page footer. The page now shows the planner's own words with a legend (`PLAN_STATUS_LEGEND`, `ui_models.py` 158–165). The report summary boundary is in words (C44). Not done: neither README links the glossary; the report and CSV still call an `assumption_limited` point `unsupported` (the consolidation lists this as open, "C49"); the glossary already has two lines the same fix wave made stale (§4, N1). |
| 4 | **Make "Start simulated test" honest about what follows** (C26, C36, C34, C37) | **Fixed** | Button is **Start simulation** (`START_LABELS`, `ui_models.py` 433). Plan panel ready line: "Ready. HTML and PDF reports are queued after acquisition (minutes on a Raspberry Pi) and appear as links under Run and in Reports." (`ui.py` 1285). Plan estimate: "Measurements: seconds (virtual clock) · Report: typically 1–4 min on a Raspberry Pi" or the planner's own seconds (`simulation_time_text`). Run panel shows the four steps of `SIMULATION_SEQUENCE` (470–476) with the current one marked: "Acquiring measurements — seconds — the model runs on a virtual clock" → "Measurements saved — report queued — waits until no test is running and enough memory is free" → "Preparing HTML and PDF — typically one to four minutes on a Raspberry Pi, longer while memory is short" → "Complete — the links appear under Run and in Reports". Header pill is prefixed by `MODE_PREFIX` ("Simulation: " / "Real bench: ", 334). `deferred_text` (337–370) turns `MemAvailable below 150 MiB` into "Waiting for free memory: 96 MiB available, 150 MiB needed" and `bench lease held` into "Waiting for the bench: another acquisition or report is still running"; the raw reason stays in a tooltip. The guide's §4.6 repeats all of this as "What you should see after Start" (lines 305–320). |
| 5 | **Align safety text and the CLI reference with reality** (C27, C23) | **Partially** | C23 fixed outright. C27 partially: a test now exists (`tests/test_ui.py` 1720, `test_every_bold_ui_label_quoted_in_the_guide_exists_in_the_page_source`) but it reads only the §4.6 step-6 and §6 walkthroughs; §5's labels, which are the safety checklist, are outside it and three of them still do not match the page, and the supervision pledge is still promised (details under C27). |

## 3. Blocker and Majors from the confusion log

Verdict words: **Fixed** (the wording a newcomer meets now says the right
thing at the place I was confused), **Partially** (fixed in one place, still
wrong or missing in another the reader also passes), **Not fixed**.

| # | Sev. | Verdict | Exact new wording found (or what is unchanged) |
| --- | --- | --- | --- |
| C22 | Blocker | **Fixed** | Guide §3.1 (lines 82–92): `git clone https://github.com/robomaniac/rigol-control.git && cd rigol-control` / `git checkout dcdc-bench-hardening`, then "*What you should see:* a folder containing `dcdc-bench/`, … and `git status` reporting `On branch dcdc-bench-hardening`. `main` also has the `dcdc-bench/` subproject (pull request #1 merged the branch on 2026-09-29), but it lags the branch by dozens of commits, so the branch is the one to use until the next pull request updates `main`." The "ask the project owner" sentence is gone. HANDOFF §3 (lines 56–62) says the same. |
| C1 | Major | **Not fixed** | Root README unchanged: line 15 "**Start:** [Getting started](dcdc-bench/docs/getting-started.md) · [Contributing](CONTRIBUTING.md) · [Handoff for the owner and future coding sessions](HANDOFF.md)"; **Start here** (line 81) still installs `python -m pip install -e '.[dev]'` (97) and describes the 5 V demo. A reader following the README body still never installs dcdc-bench. |
| C3 | Major | **Partially** | The glossary has the table I asked for ("## Milestones M0–M5 … From implementation-brief.md §15", six rows with exit criteria). But the root README (line 22), HANDOFF §1 (lines 33–37) and the dcdc-bench README **Status** (line 43) still use "M0 reached; M1 substantially reached; M2 partial; …" with no legend and no link to the glossary or the brief's §15. First use is still undefined. |
| C5 | Major | **Partially** | HANDOFF now opens "**Maintainer and agent material.** Written 2026-09-28 (last reconciled 2026-09-30) for the project owner and for any future Claude Code session … If you are new to the project and want to install it, run the simulated bench or read a report, start with [dcdc-bench/docs/getting-started.md] instead; this file assumes you already know what the bench is." The root README link label ("Handoff for the owner and future coding sessions") and its place in the **Start** list are unchanged; `~/1README.md`, "Treat every `MUST`…" (lines 25–26) and the `/home/jerome`, `jerome`, `rigol.local` details remain, with HANDOFF §8 item 2 stating they are low-sensitivity and already public. |
| C9 | Major | **Not fixed** | `tools/setup.py` unchanged (creates `dcdc-bench/.venv` with `[report,test]`, downloads Quarto). dcdc-bench README line 27 comment still "# pinned Quarto into dcdc-bench/.tools/" without saying a second environment is created; guide §3.6 (141–144) still "creates a **second** environment at `dcdc-bench/.venv` … you can ignore it and keep using the root `.venv` from step 3". |
| C11 | Major | **Partially** | Glossary: "**Path efficiency** — Output power ÷ input power with both measured at the *instrument* terminals: `Vin`/`Iin` at the supply output, `Vout`/`Iout` at the load input. The losses in both pairs of leads are inside the number, so it is not converter-terminal efficiency." First uses are still bare: dcdc-bench README line 58 ("calculates path efficiency, power loss, regulation and enabled-no-load consumption"), guide §1 item 4 line 33 ("computes path efficiency, power loss and output regulation"); the guide's own definition is still §7 line 616. The guide's first glossary link is at line 56 (the no-load bullet), 23 lines after the term. |
| C16 | Major | **Partially** | Glossary "**Job / run / analysis / report revision** — A *job* is one press of Start (`workspace/jobs/<job_id>/`). It holds one *run* (the immutable evidence, `runs/<run_id>/`). A run can have several *analyses* (one per formula version) and several *report revisions* (`r0001`, `r0002`, …, one per render)." — exactly the paragraph I asked for. The README's **Evidence and reports** section (lines 250–275) is unchanged and does not link it, so a reader of the README still has only "A formula version changes the analysis ID; rerendering creates a new report revision" (274). |
| C20 | Major | **Fixed** | Guide §1 (lines 50–56): "It does not measure temperature, transients or ripple, does not use remote (4-wire) sensing and does not send arbitrary SCPI commands from the UI workflow. A requested 0 A load is recorded as *enabled with no external load*: the input consumption with the converter powered and the load input OFF. That is not the controller's quiescent current, no efficiency is computed at 0 A, and on the real bench the observation is not yet qualified ([glossary])." Glossary entry **Enabled with no external load** says the same. The "does not measure no-load consumption" clause is gone. |
| C21 | Major | **Fixed** | `profiles/bench/mock.yaml` line 30 `remote_sense_required: false` with the comment "Local sense, as on the physical DP821A/DL3031A bench (no S+/S- leads are wired there). The remote-sense branch is exercised by profiles/bench/mock-remote-sense.yaml instead."; measurement locations `load_input_terminals_local_sense` (90) and `load_input` (116); `measurement_boundary: source-to-load-terminal path (input and output wiring included; load in local sense)` (147); note "The boundary mirrors the physical bench: local load sensing at the load terminals, so input and output wiring losses (0.06 ohm and 0.10 ohm in the plant) are inside path efficiency; no S+/S- leads are depicted." The fresh demo report's *Setup and method* now reads "Load remote sense is not requested by this profile." The glossary, however, still says the opposite (N1). |
| C23 | Major | **Fixed** | `usage: dcdc-bench [-h] {validate,…}` with "DC–DC bench: test planning, acquisition and engineering reports. Every command below runs without an instrument unless it says otherwise." Every command has a description (e.g. `validate  Check DUT, bench and recipe profiles and print the feasible-plan summary (writes nothing)`; `doctor  Read-only bench diagnosis; never writes to an instrument`). Every argument has help: `--dut DUT  DUT profile YAML: the converter's ratings, limits and declared measurement path`; `--formats FORMATS  Report formats to render, comma-separated: html, pdf or html,pdf (default: html,pdf)`; `--arm  Operator arming for the fixed real procedures; refused by this command`. `run --help` says "M1 supports mock execution only: --mode real and --arm are accepted by the parser and refused at run time (exit code 2). Real tests run from the bench page (`dcdc-bench ui`) or the fixed, owner-armed procedures." `ui --help`: "--port PORT  TCP port, 1024–65535 (default: 8082; the development Pi's service uses 8081)". `python -m dcdc_bench --help` prints `usage: dcdc-bench`, not `__main__.py`. Guide §3.7 (162–168) now predicts this. |
| C24 | Major | **Partially** | The page now uses the planner's words. `plan_rows` shows `status_display = point['status']` (`executable` / `assumption_limited` / `approval_blocked` / `unsupported`) and `PLAN_STATUS_LEGEND` (158–165) explains once: "`assumption_limited` — kept in the plan but skipped: the planning budget (assumed efficiency × share of the supply current) says the supply cannot feed it; the request is not reduced to fit". "Ready / Outside planning budget / Needs approval / Not supported" are gone. The plan reason's "request retained without clipping" is now explained in the glossary ("The request is *not reduced to fit* ('retained without clipping')"). Still two vocabularies: the report appendix and the CSV `qualification` column keep `unsupported` for a planner-`assumption_limited` point; the glossary's `unsupported` entry documents this ("The report labels every skipped point `unsupported` in its appendix, with the planner's reason") and the consolidation lists it as open. |
| C25 | Major | **Not fixed** | Guide §4.5 line 284 still `.venv/bin/dcdc-bench run --plan plan.json --mode mock --out dcdc-bench/runs`, and line 287 "*What you should see:* the run directory path `dcdc-bench/runs/<run_id>`". `run --help` default is `runs` (relative). A practice run still lands beside the measured evidence (HANDOFF §3: "the project's only copy of the real measurements"). |
| C26 | Major | **Fixed** | Guide §4.6 (305–320): "*What you should see after Start:* the header pill reads **Simulation: Acquiring… point 2 of 21** (the mode word leads every phrase), and the **Run** section lists the four steps with the current one marked: **Acquiring measurements** (seconds, on a virtual clock) → **Measurements saved — report queued** (waits until no test is running and enough memory is free; a held-back report says, for example, **Waiting for free memory: 96 MiB available, 150 MiB needed**) → **Preparing HTML and PDF** (typically one to four minutes on a Raspberry Pi) → **Complete**, when **Open HTML** and **Open PDF** appear under **Run** and in the **Reports** row labelled **Simulation · synthetic data**." The page constants match (`SIMULATION_SEQUENCE`, `SIMULATION_TIME_ESTIMATE`, the ready line at `ui.py` 1285, `REPORT_BENCH_LABELS`). |
| C27 | Major | **Partially** | New test `test_every_bold_ui_label_quoted_in_the_guide_exists_in_the_page_source` (`tests/test_ui.py` 1720–1741) checks the bold labels of "6. Optional: open the bench page" and "## 6. Run a real test through the UI" against `ui.py`, `ui_models.py`, `job_service.py`, with one declared exception (`KNOWN_GUIDE_MISMATCHES = {'Open interactive HTML': …}`). **Section 5 is outside the test** and still disagrees with the page: §5.2 line 354 "**The converter input is connected to power-supply channel 1**" vs the page's `'The converter is on ' + <DP821A> + ' (not CH2) and the load input'` (`ui.py` 1374); §5.5 line 401 "UI: **This converter profile is approved for real hardware**" vs `'This converter is approved for the real bench'` (710); line 403 "UI: **These protective limits were reviewed and are approved for this bench**" vs `'I reviewed these limits — required once'` / `'Limits approved for this preset'` (1014); §5.8 line 460 "the Start confirmation includes **I reviewed these limits and will supervise the run**" vs `'I reviewed the protective limits: ' + limits_summary(bench)` (1375) — **there is still no supervision statement in the UI**; the closest is `REAL_CANNOT`'s "Run unsupervised: an operator stays at the bench…", which is a description, not a pledge. §5.2 line 353's "**Converter input/output wiring and polarity are correct**" does match (1373). |
| C31 | Major | **Fixed** (residual) | Three places now say it. Page: `SIMULATION_CANNOT` last line "Give an instrument uncertainty: any ± in its report comes from the synthetic specification, not from an instrument."; `SYNTHETIC_UNCERTAINTY_NOTE` under a simulated report's links: "Any ± in this report is uncertainty from the synthetic specification, not an instrument: the mock bench profile carries example readback specifications so the budget can be demonstrated."; the Simulation tile's envelope row "Readback uncertainty — synthetic example specification, not an instrument" (per bench-ui.md). Guide §4.6 (314–317): "Any ± in that report is uncertainty from the synthetic specification, not an instrument: the mock bench profile carries example readback specifications so the budget's format can be demonstrated." Glossary **k = 2, expanded uncertainty, specification-bound**: "In the simulation the specifications are *examples* written into the mock bench profile." Residual: guide §1 line 59 "reports say uncertainty is **unquantified**" has no simulation exception; the report's nested parentheses survive, moved from the Summary bullet to the Qualification line (C45). |
| C41 | Major | **Fixed** | bench-ui.md, **Reconnect and evidence**: "Photographs and sensor markers are added on the separate **Sensor placement editor** page (`/annotations`, linked from the footer): choose a finished run (each option says *Simulation · synthetic data* or *Real bench · measured*; the uploader unlocks once a run is chosen, and a simulated run carries a caution that photographs describe a physical setup), upload a photograph, place the markers, and **Save as new report revision**. Each save creates a new report revision; finalized measurements are never edited by this page or by that one." The "not currently available" sentence is gone; the footer link text is unchanged (`ui.py` 1818). |
| C44 | Major | **Fixed** | Fresh demo report Summary first line: "**SYNTHETIC — Input measured at the supply terminals, output at the load terminals; wiring losses are included in the path.**" Built by `renderer._measurement_points` (343–350) from the binding locations via `LOCATION_PHRASES` (59–66) and the declared path text; the machine string stays in *Setup and method* ("Declared path: …", 865) and `report_model.json` (`measurement_boundary`, 1310). |

### Minors, in one line each

Fixed: C29 (glossary **Lease**; page "Waiting for the bench: …"), C34 (`MODE_PREFIX`), C36 (ready line), C37 (`deferred_text`), C38 (Regenerate tooltip "Makes a new report revision from the saved measurements; nothing is re-measured.", `ui.py` 1651), C39 ("Whether a test runs in the simulation or on the real bench is decided by question 2.", 1050).
Partially: C4 (*qualified* defined in the glossary; root README does not link it), C6 (HANDOFF §4 now leads with one dated collected count and calls the run block "dated"), C7 (`ui --help` names both ports; README quickstart line 29 still says 8082 with no note about the Pi's 8081 service), C14 (bench-ui.md now describes the true flow — Simulation has no confirmation; README lines 38 and 78 keep the two old summaries), C30 (guide §6.10 line 602 still bare `report-queued`; the glossary defines it), C45 ("87.48% ± 0.33 percentage points (k = 2)" in the metric cell is clean; the Qualification line now carries "uncertainty partially evaluated from declared readback specifications (specification-bound only (synthetic example)); ± values use k = 2 and are not validated 95 % intervals").
Not fixed: C2, C8, C10, C12 (status sentence still twice), C13 (fragment at line 344), C15, C17, C18 (still unindexed: `instrument-specifications.md`, `m2-freshness-and-readback-evidence.md`, `standards/README.md`, `standards/iso16750-2.md` — and the new glossary links the second of them), C19, C28 (now a declared exception in the test, "owned by the guide editor", rather than a one-word fix), C32, C33, C35 ("Not yet approved for the real bench" still under every converter card whatever the tile, `ui.py` 918).
Not re-checked: C46, C50 (report DUT block heading and CSV columns; no new render was inspected for them).

## 4. New confusion introduced by the fix wave

| # | Where | What I found | Suggested wording |
| --- | --- | --- | --- |
| N1 | `docs/glossary.md`, **Local vs remote sense** and **Measurement boundary** | "The real bench uses local sensing; the mock profile declares remote sensing." — `mock.yaml` now says `remote_sense_required: false` and mirrors the real bench. The boundary entry quotes "source-to-DUT-output path" as *the* string; `mock.yaml` now says "source-to-load-terminal path (input and output wiring included; load in local sense)" and only `domain.py`'s default (367) still reads "source-to-DUT-output path". The glossary was written in the same round that changed both. | "Both the real bench and the shipped mock profile use local sensing; `profiles/bench/mock-remote-sense.yaml` exercises the remote-sense branch." / "…the bench profile's `measurement_boundary` text (default `source-to-DUT-output path`; the shipped profiles spell out what is included)". |
| N2 | `docs/glossary.md` header | "the [getting-started guide] and [bench-ui.md] link it at first use." The guide's first uses of *path efficiency* (line 33) and of the four status words (lines 28–29) carry no link; its first glossary link is line 56. Neither README links it at all. | Either add the links at lines 28 and 33 (and in both READMEs) or say "link it from §1 and §4.6". |
| N3 | Guide §1 line 59 vs §4.6 lines 314–317 | §1: reports say uncertainty is **unquantified**; §4.6: "Any ± in that report is uncertainty from the synthetic specification". Both true, but the first is stated without its condition and comes first. | §1: "…reports for the **real** bench say uncertainty is **unquantified**; the simulation shows an example budget built from invented specifications (§4.6)." |
| N4 | `/glossary` page | Both `/` and `/glossary` answer with `<title>DC–DC Bench</title>`; two open tabs are indistinguishable. | Title "Glossary — DC–DC Bench". |
| N5 | `docs/bench-ui.md`, **Run a test** item 2 | A ~330-word paragraph that reproduces both can/cannot panels in prose, the preset pills, the limits, the approval checkbox and the mode rule; the standards checklist follows before **Preview** is reached (~2 300 words in). The document grew from 2 075 to 3 160 words. | Keep the tile description to one sentence each and refer to the panel ("the tile's **What the simulation can and cannot do** panel lists five things it does and four it cannot"); move the standards checklist to its own document or below **Reports**. |
| N6 | `dcdc-bench/README.md` **Status** line 45 vs **Architecture and verification** line 313 | "For current test totals see the branch's final verification record." vs "Current test total … **812 of 828 tests** … This is the one figure to quote". Two pointers to "the" figure on one page. | Delete the sentence at line 45 or point it at the section above. |
| N7 | `tests/test_ui.py` 1717 | The guide's remaining wrong label (C28, "Open interactive HTML") is now encoded as an accepted exception naming an owner, instead of being edited. The reader of §6.8 still meets a label that does not exist. | Change the guide word and delete the exception. |

## 5. Is "what the simulation can and cannot do" visible where it should be?

**On the bench page (first two screens):** yes, by source order. The page
builds header → **1 Which converter?** → **2 Simulated or real bench?** →
**3 Which test?** → Run → Reports → footer (`ui.py` 1762–1819). The
Simulation tile in question 2 carries, always open (no disclosure), the title
"Simulation", the line "Nothing is switched on. Synthetic readings, real
report layout; every output is labelled SYNTHETIC." (971), the synthetic
envelope table, and `can_cannot('What the simulation can and cannot do', …)`
(985) rendered as two columns "The simulation can" (five ✓ lines) and "It
cannot" (four ✗ lines): "Measure your converter: the numbers describe the
model, not the sample on the bench." / "Prove anything about safety,
protective limits or a real start-up." / "Show ripple, transients or thermal
behaviour." / "Give an instrument uncertainty: any ± in its report comes from
the synthetic specification, not from an instrument." With the shipped single
converter card, question 2 is the second block below the header. I did not
render the page, so the pixel position at a given window height is inferred,
not measured; the UI/UX review's screenshots are the place to confirm it.

**In the guide (first page, §1):** partially. §1 states "**No hardware is
touched until you explicitly arm a real job.** The simulated ('mock') bench
imports no instrument driver." and lists what the *software* does not do
(temperature, transients, ripple, remote sense, arbitrary SCPI, accuracy). It
does not state, as the tile does, that the simulation cannot measure your
converter or prove anything about safety, and its accuracy line (59) reads as
if the simulation, too, shows "unquantified". The can/cannot content first
appears in §4.6 (lines 299–300: "a panel **What the simulation can and cannot
do**"), about 3 400 words in, and the panel's lines are quoted nowhere in the
guide — only named. One sentence in §1, mirroring `SIMULATION_CANNOT`, would
close this.

## 6. Verdict for the owner

The fix wave fixed what was hardest and left what was easiest. The only
Blocker (the clone step) is gone; all four places where I could not tell what
was simulated are resolved in the page, the profile, the guide's §4.6 and
bench-ui.md; "Start simulation" now says what follows it, in what time, and
where the links appear; the CLI is a usable reference; a glossary exists and
is one click from the page footer. But the two documents a newcomer reads
first are untouched except for a test count: the root README still offers two
products with two install lines and undefined milestone codes, and the
dcdc-bench README still sends the reader through `setup.py`'s second
environment, a duplicated status sentence, two flow summaries that ignore the
simulation, and a practice-run path into `runs/` — none of them links the new
glossary. The guide's §5 safety checklist still quotes three labels the page
does not show and a supervision pledge the page never asks for, outside the
new label test's reach; and the glossary already contradicts the mock profile
on remote sense. I would not send the owner to review until one short pass
has: (a) put one install line, an M0–M5 legend and a glossary link on both
READMEs and replaced the `--out dcdc-bench/runs` step; (b) extended the label
test to §5 and either added the supervision checkbox to the page or removed the
pledge from the guide; (c) corrected the two stale glossary lines and the §1
"unquantified" sentence. Those are an afternoon's edits; after them a
first-time user can go from clone to a labelled synthetic report without
forming a wrong belief about what is real.

## 7. Follow-up pass

Written 2026-09-30, after this re-check, at the head of `dcdc-bench-hardening`.
The verdict's items (a)–(c) were done in one documentation pass: both READMEs
(one install line, an M0–M5 legend, glossary links, the practice-run path, the
duplicated status paragraph, the two flow summaries), guide §5 with the label
test extended to it, the glossary lines and the guide's §1 sentence. N1–N7:

| # | Resolution | Where |
| --- | --- | --- |
| N1 | **Fixed** — *Local vs remote sense* now says both the real bench and `mock.yaml` use local sensing and names `mock-remote-sense.yaml` as the remote-sense variant; *Measurement boundary* quotes the shipped `mock.yaml` string and calls `source-to-DUT-output path` the `domain.py` default that `mock-remote-sense.yaml` still carries. | `docs/glossary.md` |
| N2 | **Fixed** — the header now says where the links are (both READMEs at their first use of *path efficiency* / *qualified*, guide §1 and §4.6, bench-ui.md where it describes the footer), and the README and §1 links it names were added. | `docs/glossary.md`; root `README.md`; `dcdc-bench/README.md`; `docs/getting-started.md` §1 |
| N3 | **Fixed** — §1 now says reports from the real bench call uncertainty unquantified until the readback specifications are transcribed, and that the simulation's ± comes from a synthetic example specification (section 4.6). | `docs/getting-started.md` §1 |
| N4 | **Not fixed** — the `/glossary` page title is set in code (`ui.py`), outside this documentation pass. | `src/dcdc_bench/ui.py` |
| N5 | **Not fixed** — bench-ui.md's length is noted and the document is left as it is. | `docs/bench-ui.md` |
| N6 | **Fixed** — the **Status** sentence now points at the one test total in **Architecture and verification**, and the plain copy of the status paragraph in **What comes next** is replaced by a pointer to **Status**. | `dcdc-bench/README.md` |
| N7 | **Fixed** — §6.8 reads **Open HTML**, and `KNOWN_GUIDE_MISMATCHES` in the test is empty; the same test now also reads §5, whose three wrong labels were replaced by the page's (`The converter is on DP821A CH1 (not CH2) and the load input`, `This converter is approved for the real bench`, `I reviewed these limits — required once` / `Limits approved for this preset`) and whose supervision pledge was removed. | `docs/getting-started.md` §5, §6.8; `tests/test_ui.py` |
