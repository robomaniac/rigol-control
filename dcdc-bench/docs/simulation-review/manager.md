# Engineering-manager review of dcdc-bench (simulation review)

Prepared 2026-09-30 from the tracked tree at `b38df08` (head of
`dcdc-bench-hardening`) plus read-only looks at the bench computer's ignored
folders, the local report server and the GitHub Actions history. Method:
reading, `grep`, `ls`, `git log`, `gh run view` and three HTTP probes of the
loopback report server. **No pytest, render, demo, UI job or instrument
connection was started.** Where a claim could only be confirmed by running
code, the verdict below says so. Private bench details (addresses, serials,
the owner's home path and hostname) are deliberately not repeated here.

## 1. Executive summary

1. The software is real and unusually well documented: a simulated bench runs
   end to end to interactive HTML and vector PDF today, and six measured runs
   of the 12T12-4A converter exist with SCPI transcripts and independent
   recomputation audits.
2. The stated milestone position (M0 done; M1 substantially; M2 partial; M3
   slice; M4/M5 mock-only) is honest and is byte-identical in the three
   documents that must agree. I found no over-claim of hardware capability
   anywhere in the tree.
3. What is not qualified is measurement quality: with the instruments' own
   readbacks, efficiency at 0.1 A carries about ±28 percentage points (k = 2),
   and the load reads 11 mA above the source on a plain wire. No efficiency
   number below roughly 0.5 A should be shown to anyone as a converter result.
4. CI exists but has never passed: every one of the 25 runs since it was added
   is red. The Python 3.13 job is green; the Python 3.11 job fails six tests
   on a 3.13-only keyword, so "Python 3.11 or later" is currently untrue for
   the test suite; two mobile-layout browser tests fail on CI's Chromium.
5. Several documents are a day behind the repository: the branch was merged to
   `main` via PR #1 on 2026-09-29 while the handoff still lists it as pending;
   the security review's promised Resolution section does not exist although
   its fixes landed; four different test totals are in print; one cited
   evidence folder (`comparison-real-24v`) has been deleted by a later demo.
6. The only copy of every real measurement is on one SD card in one Pi, with
   no backup procedure. That is the largest single risk to the project.
7. Bus factor is one: one human author, 71 of 107 recent commits co-authored
   by an AI assistant, every review written by an "agent role". Nothing has
   been read by a second engineer.
8. The simulation can be demonstrated today over the existing port forward
   without rendering anything: the three synthetic reports are already served,
   and the one-page bench UI's Preview switches nothing on.
9. The next two weeks should be split: week one is software and paperwork with
   no bench time (CI, backup, doc reconciliation, license); week two is one
   owner-authorized 24 V session that closes M2 step 5, preceded by the
   external-current-reference decision.
10. Do not call M3 done, do not quote light-load efficiency, and do not
    describe the ISO 16750-2 checklist as compliance testing.

## 2. Verified versus claimed

Verdicts: **verified** (I saw the artifact or the fact), **partially** (the
artifact exists but the claim is broader, stale or platform-dependent),
**unverified** (no artifact found, or contradicted).

| # | Claim (where) | Evidence found | Verdict |
| --- | --- | --- | --- |
| 1 | Milestone paragraph "stated identically" in README, acceptance.md, implementation_status.md | `sha256` of the bold paragraph is `6810fe41…` in all three files; the README's second (unbolded) copy also matches byte for byte | **verified** |
| 2 | M0 complete: CORE-01…06 have named tests (acceptance.md) | `test_planning.py` (19 tests) contains `test_CORE01_…`, `test_CORE02_…`; `test_uncertainty.py::test_core06_programming_accuracy_is_never_used_for_readback` exists | **verified** (existence; CI 3.13 green at head) |
| 3 | M1: "one demo command works without hardware"; three synthetic reports | `examples/generated/{normal,setup-limited,aborted}` rebuilt 2026-09-29 09:12–09:15 on the Pi; `/Runs/dcdc-mock-demo/index.html` served (HTTP 200); CI's render step succeeds on Ubuntu | **verified** |
| 4 | "14 of 15 browser/PDF gates passed on the Pi 4" (status, acceptance) | Recorded in status with platform; on CI (Playwright Chromium, Ubuntu) the same selection is 13 passed / 2 failed / 1 skipped: `test_web_chart_captions_remain_below_svg_on_desktop_and_mobile` and `test_web_compact_hover_desktop_mobile_and_alternate_axis` fail at 390 px | **partially** (platform-dependent) |
| 5 | "CI added" (github-readiness #33: Done; status) | `.github/workflows/ci.yml` exists; `gh run list`: 25 of 25 runs on the branch since 2026-09-29T05:00Z concluded `failure`; latest run: 3.13 tests job green, 3.11 tests job red, documents job red (informational) | **partially** |
| 6 | "Python 3.11 or later" (README, CONTRIBUTING, `requires-python >= 3.11`, CI matrix) | 3.11 job: `TypeError: Path.read_text() got an unexpected keyword argument 'newline'` in 6 tests (`test_comparison`, `test_report_javascript`, `test_reporting`); 7 `read_text(... newline=)` sites in `tests/`, none in `src/` | **unverified** (false for the suite; product code may be fine) |
| 7 | Test totals: 653 (README), 692 (status, HANDOFF §4), 832 (HANDOFF §9) | Static count: 43 files, 565 `def test_`, 66 `parametrize` decorators. CI 3.11 at head: 788 passed, 6 failed, 2 skipped, 28 deselected = 824 collected. No verification record accompanies the 832 figure | **partially** (four numbers, none tied to `b38df08` in the status doc) |
| 8 | Merge code review: 7 Majors and 5 minors fixed in `053504f` with named tests | Commit exists; all sampled fix tests exist: `test_report_queue::test_cancel_racing_dispatch_…`, `test_comparison::test_unc03_evaluated_budgets_…`, `test_job_service::test_armed_mock_uvlo_job_…`, `test_uvlo::test_m4_off_step_…`, `test_pdf_check::test_missing_pdftohtml_…`, `test_publish::test_revision_without_a_successful_build_…`, `test_ui::test_run_panel_offers_stop_…`, `test_doctor::test_mid_run_refusal_…`. m5, m6, m8, m9, m10 explicitly not fixed | **verified** (existence) |
| 9 | Merge security review: "fixes in progress and recorded in its Resolution section when complete" (status) | Fixes landed (`2582508` "Salvage the security-review fixes", merged as `bcdc58f`): `publish.py` allowlist for the sensor-placement `data:` photo, EXIF/GPS stripping, `ui.RequestBodyLimit`, `doctor --out` no-overwrite, symlink refusal, YAML anchor refusal, each with a test in `test_publish.py` / `test_ui.py` / `test_doctor.py`. The review document has **no** Resolution section (headings: Threat model, Findings, Verified defenses, Gaps, Reproduction) | **partially** (code yes, record no) |
| 10 | RUN-02 "covered at the mock/application-services level" | `test_run02_reconnect.py` has 2 tests; one is `@pytest.mark.integration` and therefore never runs in CI (integration is excluded) | **partially** (local-only coverage) |
| 11 | Read-only `doctor` run on the real bench 2026-09-29, 515 queries, 0 writes | `dcdc-bench/diagnostics/doctor-20260929T162448….json` + `.scpi.jsonl` and a second pair at `…T203350…` exist; `test_doctor.py` (16 tests) pins write refusal | **verified** (existence; transcript not audited here) |
| 12 | M2 plan step 4 pass-through run by the owner (status, HANDOFF, evidence §F) | `workspace/jobs/20260929T203714Z_0a11d40f` (`mode: real`, `state: completed`) with run `…_real_bed075` | **verified** (existence) |
| 13 | Six measured runs on 2026-09-27 with evidence folders | `runs/`: real-bringup (4), real-extended (2), real-source-limit (1), real-startup-descent (1), real-voltage-sweep (2); UI job `bb4a479f` completed; `Data/Runs/12t12-*` six served reports, `12t12-workflow` HTTP 200 | **verified** (existence) |
| 14 | CMP-01 "demonstrated read-only on two stored real 24 V runs (`examples/generated/comparison-real-24v/`)" (status, acceptance) | Folder does not exist; `examples/generated` was rebuilt by the demo on 2026-09-29 and holds only the three mock runs | **unverified** (evidence lost) |
| 15 | Datasheet readback terms transcribed with page references (M2 step 1) | `docs/instrument-specifications.md` (page-referenced table) and `profiles/bench/rigol-dp821a-dl3031a.yaml` exist; calibration status recorded unknown | **verified** (existence; transcription not checked against R1/R4 here) |
| 16 | Saved-profile approvals are load-bearing; a stale preview cannot start a real job | `test_real_backend::test_unapproved_saved_profiles_never_open_instruments`, `test_job_service::test_stale_supported_preview_cannot_start_an_unapproved_real_job` exist | **verified** (existence) |
| 17 | `publish` uses no git/network and redacts endpoints, paths, serials | `test_publish.py` (21 tests) incl. `test_redacted_copy_strips_endpoints_paths_serials_and_keeps_numbers`, `test_cli_publish_prints_target_and_uses_no_subprocess` | **verified** (existence) |
| 18 | "`main` is the older supply-to-load demo; merging into `main` is an open owner decision" (HANDOFF §3, §8.5) | `origin/main` = `03c4e41` "Merge pull request #1 from robomaniac/dcdc-bench-hardening"; PR #1 state MERGED 2026-09-29T05:08Z. The 26 commits of 2026-09-29 are only on the branch | **unverified** (stale; GitHub Pages now serves the merged tree) |
| 19 | Enabled-no-load acquisition change "awaits an independent safety review before any real run" (status, M2 row) vs "independently reviewed as safe" (HANDOFF §9; commit `523dab4`) | Both statements in print; the commit exists | **partially** (contradiction; the status wording is the safe one) |
| 20 | Standards catalog: "never copy the standard's text" | `docs/standards/README.md` states the rule; `standards.py:158-165` holds one-line paraphrases of the ISO 16750-1 functional status classes A–E; clause parameters only elsewhere | **verified**, with a caution (paraphrases are still derived text) |
| 21 | 12 V cold start "failed twice" corrected to one recorded attempt | Status "Latest measured evidence" now says one automated attempt; cold-start-hypothesis §2 documents the correction | **verified** |
| 22 | Mock pipeline opens no instruments; loopback-only UI with Host check | `test_pipeline` checks `real_hardware_opened=false`; `RequestBodyLimit` middleware present; status records foreign Host/Origin → 400. I probed only the happy path (HTTP 200 on loopback) | **verified** by record, not re-probed |
| 23 | Local report server up and serving | `benchctl-report.service` active; `/`, `/Runs/dcdc-mock-demo/index.html`, `/Runs/12t12-workflow/report.html` all HTTP 200 | **verified** live |

Sampling note: 23 claims traced; 13 verified, 7 partially, 3 unverified. The
three unverified items are documentation staleness and a lost demo folder, not
hardware or safety over-claims.

## 3. Risk register

Likelihood / impact: H, M, L.

| # | Category | Risk | L | I | Mitigation |
| --- | --- | --- | --- | --- | --- |
| R1 | Single machine | The only copy of every real measurement (`runs/`, `workspace/`, `diagnostics/`, `Data/Runs/`) lives on one SD card that has already stalled and been swapped once; venv, Quarto and the UI service share it | M | H | This week: `tar` + checksum of the four folders to a laptop or NAS; then a weekly `rsync` job; record the procedure in HANDOFF §3 |
| R2 | Technical (metrology) | Internal readbacks give ±28 pp (k = 2) at 24 V / 0.1 A; load reads +11 mA vs source on a wire; light-load efficiency is unqualifiable and could be quoted by accident (the reports show the numbers) | H | H | Owner decision on an external DMM/shunt; until then the report banner and any slide must say "uncertainty unquantified" and light-load efficiency must not be quoted |
| R3 | Process | CI has never been green (25/25 red); "Python 3.11+" is untrue for the suite; two browser tests are platform-dependent | H | M | Fix the 7 `read_text(newline=)` sites or raise the floor to 3.13 everywhere; fix or platform-mark the two 390 px tests; add a CI badge only once green |
| R4 | Process | Documents lag the tree by a day (PR #1 merged; no security Resolution; four test totals; `comparison-real-24v` gone; status dated 09-28 with 09-29 content; M2 row vs HANDOFF on the no-load review). A reviewer who spots one will distrust the rest | H | M | One reconciliation commit before the review (Section 6); adopt "one CI-derived test total, quoted with commit hash" |
| R5 | Safety | Procedures apply different startup gates: the configured backend and `voltage_sweep.py` gate the load on Vout ≥ 10.8 V after five source-only cycles; `extended.py::_guard` and `bringup.py` enable the load after 5 s with only upper guards (M2 plan, "Status after step 3"). The recorded 12 V collapse followed a load enable at ~8 V | M | H | Route the fixed procedures through the same startup gate or retire them from real use; make the UI's configured path the only real entry point |
| R6 | Safety | `NO_LOAD_IIN_SPAN_A = 2 mA` and the 15–35 s no-load load-on delay are software defaults awaiting the owner; every saved real plan hash changed, so a stale mental model of "what Start does" is possible | M | M | Owner confirms or changes the constant before the 24 V session; operator re-Previews (already enforced) |
| R7 | Technical | Code-review items left as policy: systemd `RuntimeMaxSec=2700` can kill a long thermal acquisition and leave shutdown UNKNOWN (m8); zero-width "evaluated" uncertainty is constructible (m6); thermal window off by one poll (m5) | L | M | Derive the cap from the plan or apply it to report workers only; `resolution: gt=0`; fix before any thermal work |
| R8 | Technical | Volatile evidence locations: `examples/generated` is wiped by every demo; the comparison demonstration was lost that way | H | L | Never cite `examples/generated` as evidence; write demonstrations under a durable, indexed path |
| R9 | Process (velocity) | 107 commits and ~11 k inserted lines in four days, all reviewed by agent roles; the two merge reviews found 7 majors and 1 high on freshly merged code, which suggests more remain in the 09-29 additions (one-page UI +1765 lines, `standards.py` +851, none yet independently reviewed) | M | M | Freeze features for a week; request one human read of `ui.py`, `standards.py`, `supply_profiles.py`; run the two review roles on `72a428d..b38df08` |
| R10 | Bus factor | One human, no second maintainer, the master spec (`~/1README.md`) is outside the repo, the review-role reviewers are the same tooling that wrote the code | H | H | Nominate a second reader for the owner's review; keep HANDOFF current (it is the mitigation that exists); confirm the brief is byte-identical to the master copy at each review |
| R11 | Single machine (capacity) | Five agent worktrees and a UI job ran on the 2 GB Pi today; the status records ~1 GiB compressed swap during renders; the 1 GB Pi reset unclean under similar load | M | M | One heavy job at a time; render demos on a laptop or pre-render before meetings |
| R12 | Legal / sharing | No `LICENSE`; readiness #1 raises a GPL-3.0 provenance question for adapted driver code; five ISO functional-status paraphrases in code | M | M | Owner picks a license after checking provenance; keep standards content to clause numbers and parameters |
| R13 | Safety (residual) | Real UVLO / slow ramp / reset staircase exist as mock-only types; `prepare_real_plan` refuses them, but they are one approval flag away from a real path that has no real execution context | L | H | Keep the refusal test pinned; require a written procedure review before any real UVLO-style recipe |

## 4. Demo script: showing the simulation honestly

Audience: a stakeholder over screen share. Duration: 15 minutes. Nothing in
this script energizes an instrument or renders a new document.

**Pre-flight (the day before, 5 minutes).** Confirm `systemctl --user
is-active benchctl-report.service` says `active`; forward port 8081 (VS Code
Ports or `ssh -L 8081:127.0.0.1:8081 <user>@<pi-hostname>`); open
`http://localhost:8081/Runs/dcdc-mock-demo/index.html` and `http://localhost:8081/`
once. Make sure no agent session, test run or render is active on the Pi
during the meeting. If you want to show a live simulated run, start it and let
its report finish **before** the meeting (acquisition takes seconds on the
virtual clock; rendering takes minutes and must pass the memory gate). A
completed simulated job already exists in Reports from 2026-09-30.

**Part 1: the synthetic reports (6 minutes).**

1. Open `/Runs/dcdc-mock-demo/index.html`. Point at the banner
   **SYNTHETIC — software demonstration only**. Say: "Every number on these
   three pages comes from a software model of a converter; the model is
   labelled everywhere, including the CSV exports."
2. Open **Normal → Interactive report**. Show: the "About this report" table
   (plain-language identity, revision, evidence type Synthetic); hover a
   marker (raw readings behind the mean); tick and untick input-voltage
   curves; zoom and **Reset zoom** (selections kept) versus **Restore default
   view**; export CSV. Say: "The issued summary text does not change while I
   explore; the PDF is the canonical revision."
3. Open **Normal → Canonical PDF**. Say: "Vector figures, same report model as
   the HTML, checked automatically for pagination defects."
4. Open **Supply reaches its current limit**. Say: "The simulated source went
   into current limiting at one point; the software refuses to call that an
   efficiency measurement and says why."
5. Open **Test stopped early**. Say: "An early stop keeps the completed
   points, lists the unrun points and records the shutdown readbacks."

**Part 2: the bench page (7 minutes).**

6. Open `http://localhost:8081/`. Walk the one page top to bottom. **Which
   converter?**: the 12T12-4A card (9–36 V in, 12 V / 4 A out, ratings marked
   user-supplied). **Simulated or real bench?**: click the **Simulated bench —
   nothing is switched on** tile. Do not click the real tile's Start; you may
   point at its four protective limits and the "I reviewed these limits"
   approval to explain the gate.
7. **Which test?**: select the quick 21-point card, press **Preview**. Show
   the plan panel: 19 executable, 2 kept-but-skipped 12 V points with the
   reason (1 A source budget at an assumed 80 % efficiency). Say: "The planner
   never clips a request silently; skipped points appear in the report as not
   run."
8. Expand the **ISO 16750-2:2023** card; flip the 12 V / 24 V badge. Show one
   **runs here** row (§4.2), one **procedure not yet implemented** row
   (§4.3.1.1 with its stated reason) and one greyed row (load dump, excluded
   by policy). Do not press **Add as tests** unless you intend to save
   recipes. Say: "This is a feasibility checklist for this bench, cited by
   clause number. It is not a compliance test, and the ramp/staircase items
   run on the simulated bench only."
9. Open **Reports**, pick the completed simulated job, **Open HTML**. Say:
   "Same pipeline, driven from the page; the worker owns the run, so closing
   the browser does not stop or restart anything."

**Part 3, optional: one measured report (2 minutes).** Open
`/Runs/12t12-workflow/report.html` only if the audience asks what real data
looks like. Say exactly: "Three points at 24 V input, 0.1–0.5 A, measured at
the instrument terminals including wiring losses; measurement uncertainty is
not yet quantified, so treat the percentages as indicative."

**Do not claim:** that M3 is complete; any efficiency figure below ~0.5 A
load; the 48 W rating (unreachable with a 1 A source); 12 V start-up behaviour
(one recorded attempt collapsed); calibration or traceability; ISO
compliance; a browser-click acquisition on hardware; green CI; thermal or
UVLO results on hardware; that the demo reports describe the 12T12-4A.

**Prepared answers.** "Why simulated?": because the measurement chain is not
yet qualified (M2), and the brief forbids showing unqualified numbers as
results. "When real?": after one authorized 24 V session and an external
current reference decision (Section 5). "Who reviewed it?": automated review
roles plus the owner; no second human yet (Section 3, R10).

## 5. Recommended two-week plan

Week 1 is software and paperwork only; no bench time and no energizing.

| Day | Task | Output | Needs |
| --- | --- | --- | --- |
| 1 | Back up `runs/`, `workspace/`, `diagnostics/`, `Data/Runs/` with checksums to a second machine; write the procedure into HANDOFF §3 | Off-Pi copy; documented restore | Owner: destination |
| 1–2 | Make CI green: replace the 7 `Path.read_text(newline=)` test usages (or set `requires-python >= 3.13` in both `pyproject.toml`, README, CONTRIBUTING and drop 3.11 from the matrix); fix or platform-mark the two 390 px browser tests | First green run; badge | Owner: Python floor |
| 2 | Reconciliation commit: security review Resolution section (cite `bcdc58f` / `2582508` and tests); one CI-derived test total with commit hash in README, status and HANDOFF; HANDOFF §3/§8 marks PR #1 merged and `main` updated; re-date the status paragraph (all three files together); align the M2 row with the no-load safety-review outcome; add this file to `docs/README.md` | Documents match the tree | — |
| 3 | Re-run `dcdc-bench compare` on the two stored 24 V runs into a durable path and cite that; delete the parked theme branch (design A chosen) | CMP-01 evidence restored | Owner: confirm branch deletion |
| 3–4 | Unify the startup gate across `extended.py`, `bringup.py` and the configured backend, or mark the fixed procedures "not for real use"; fix code-review m6 and m8 | Consistent load-enable rule | — |
| 4–5 | Agent-role code and security reviews of `72a428d..b38df08` (one-page UI, standards, supply profiles, print theme); fix majors | Third review pair | — |
| 5 | Owner decision meeting (table below); rehearse Section 4 | Decisions recorded in HANDOFF §8 | Owner |
| 6–7 | If an external current reference is approved: add `measurements.*.external_reference` to the bench profile schema and an operator-observation entry path; if not: mark light-load points `unquantified` permanently in the report banner | Schema + tests | Owner: reference meter |
| 8 | Bench, no DUT (M2 step 4 extras, owner present): freshness burst test with outputs ON through a new read-only probe; DMM plausibility check at three points | Freshness T_r / T_l recorded in the bench profile | Owner authorization |
| 9 | Bench, DUT at 24 V (M2 step 5, owner present): re-Preview, one enabled-no-load window, one 0.1 A point; verified OFF; results-review role | First evaluated real budget, or a recorded reason why not | Owner authorization; `NO_LOAD_IIN_SPAN_A` confirmed |
| 10 | Re-evaluate M2 and M3 exit criteria against brief §15 in writing; decide whether to schedule the 12 V cold-start stage 1 (load disabled, 15 → 12 V) as a separate authorized session | Updated milestone paragraph | Owner: cold-start plan |

**Owner decisions needed (by day 5):**

| Decision | Options | Blocks |
| --- | --- | --- |
| License | Choose after checking whether any adapted code is GPL-3.0 (readiness #1); or state "all rights reserved, private" | Any sharing of the repository; the `license` field in both `pyproject.toml` |
| External current reference | (a) DMM in series on the output lead (plus the input lead if two meters) with model, range and accuracy recorded as an operator observation; (b) precision shunt + DMM; (c) none, accepting that light-load efficiency stays unquantified | Qualifying efficiency below ~0.5 A; resolving the 11 mA disagreement |
| 24 V bench session | Date, who is present, which profiles; approve or change `NO_LOAD_IIN_SPAN_A = 2 mA` and the longer no-load load-on delay | M2 step 5; any M3 claim |
| 12 V cold-start test plan | Approve stage 1 of cold-start-hypothesis §5 (load disabled, 15 / 14 / 13.5 / 13 / 12.5 / 12 V from OFF, 30 s window, 60 s OFF between) as a reviewed recipe; or defer | Any 12 V condition in the sweep UI |
| Python floor | 3.11 (fix tests) or 3.13 (change four documents and the CI matrix) | Green CI |
| Backup destination | Laptop folder, NAS or a second SD card image | R1 |
| Parked theme branch | Delete (design A chosen) or finish | Repository hygiene |
| 34-item characterization list | Provide the file so it can be cross-checked against IEC/ISO clause by clause (HANDOFF §9 item 0) | Standards checklist completeness |

## 6. Top 5 changes before the owner's review

1. **Make CI green, or make the Python claim true.** Replace the seven
   `Path.read_text(newline=…)` calls in `tests/` (3.13-only) or raise the
   documented floor to 3.13 in `pyproject.toml` (both), README, CONTRIBUTING
   and the CI matrix; fix or platform-mark the two 390 px browser tests. Today
   every run since CI was added is red, which contradicts "Python 3.11 or
   later" and undermines every other verification statement.
2. **Back up the evidence off the Pi.** `runs/`, `workspace/`, `diagnostics/`
   and `Data/Runs/` are the only copy of every real measurement; copy them
   with checksums to a second machine and write the procedure into HANDOFF.
   Re-create the lost `comparison-real-24v` demonstration in a durable
   location so the CMP-01 claim has an artifact again.
3. **One reconciliation commit for the documents.** Add the security review's
   Resolution section (fixes are in `bcdc58f` / `2582508` with tests); replace
   the four test totals with one CI-derived figure tied to a commit hash;
   record in HANDOFF and the README that PR #1 was merged to `main` on
   2026-09-29 and that GitHub Pages now serves that tree; re-date the status
   paragraph in all three files together; make the M2 row and HANDOFF agree on
   the enabled-no-load safety review; index this file in `docs/README.md`.
4. **Decide the license and record the provenance check.** No `LICENSE`
   exists and the readiness audit raises a GPL-3.0 question for adapted driver
   code; until decided, the repository cannot be shown to anyone outside as
   reusable, and both `pyproject.toml` files remain without a `license` field.
5. **Pre-flight the demonstration and freeze features for the review week.**
   Confirm the served mock demo and one completed simulated UI job open over
   the port forward; delete the parked theme branch (design A was chosen);
   confirm `NO_LOAD_IIN_SPAN_A`; and run the two review roles over
   `72a428d..b38df08` (one-page UI, standards catalog, supply profiles, print
   theme), which no review has yet read.

## Appendix: facts gathered

- Commits since 2026-09-25: 107 (74 non-merge); by day 3 / 35 / 43 / 26
  (09-26 through 09-29); one human author under three identities; 71 commit
  messages carry `Co-Authored-By: Claude Fable 5.1`.
- Tests: `dcdc-bench/tests` 43 files, 565 `def test_`, 66 `parametrize`
  decorators, 16 browser/pdf-marked functions plus one browser-marked module,
  11 integration-marked. `Software/tests` 15 files, 339 `def test_` (CI: 445
  passed). CI 3.11 job at head: 788 passed, 6 failed, 2 skipped, 28
  deselected.
- CI failures: `Path.read_text(newline=)` in `test_comparison.py`,
  `test_report_javascript.py`, `test_reporting.py` (3.11); 390 px layout
  assertions in `test_documents.py` (documents job).
- Evidence on the bench computer (ignored by Git): 10 run folders under
  `dcdc-bench/runs/` across five real procedures; 7 UI jobs (3 real, 4 mock;
  one mock completed 2026-09-30); 4 doctor diagnostics; six `12t12-*` reports
  plus `dcdc-mock-demo` under `Data/Runs/`.
- Branches: `origin/main` = `03c4e41` (PR #1 merged 2026-09-29); five
  `worktree-agent-*` checkouts present; `worktree-agent-a6546934fb2137254`
  unmerged (report themes).
- Not run: pytest, demo, render, UI jobs, instrument connections. Not audited:
  SCPI transcripts, datasheet transcription accuracy, the 09-29 UI/standards
  code.
