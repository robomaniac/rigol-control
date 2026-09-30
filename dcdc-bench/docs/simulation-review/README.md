# Simulation review round (2026-09-30)

Five independent reviewer roles examined the simulated bench ("Simulation")
before the owner's review: the live page at loopback port 8081, the fresh
simulated report `workspace/jobs/20260930T145556Z_3451819c` (rendered through
the real service path: acquisition, automatic report queue, memory gate, HTML
and PDF in 64 s at a 238 MiB peak), the code, and the documentation. Each
review is a separate document with ranked findings and a "Top 5 changes"
list. This page consolidates them and records who is fixing what.

| Role | Document | Blockers | Majors | Minors |
| --- | --- | :-: | :-: | :-: |
| UI/UX designer | [ui-ux.md](ui-ux.md) (with [screenshots](screenshots/)) | 3 | 11 | 12 |
| Power-electronics test engineer | [electrical-engineer.md](electrical-engineer.md) | 1 | 5 | 8 |
| First-time user | [new-user.md](new-user.md) | 1 | ~17 | rest of 50 |
| Engineering manager | [manager.md](manager.md) | — | risk register | — |
| QA / test engineer | [qa.md](qa.md) | 0 | 4 | 13 |

## Where the reviews agree

1. **The simulation must say what it is and is not, on the page.** Every
   role asked for a visible can/cannot panel on the Simulated tile (synthetic
   plant, SYNTHETIC on every output, no instrument touched; cannot measure
   your converter, cannot prove safety, no ripple/transient/thermal claims)
   and a matching envelope summary on the Real tile.
2. **The simulated plant must behave like the recorded bench.** The mock
   source-current-limit event kept the converter running at a reduced output;
   the one real event collapsed to 2.661 V at 1.0005 A. The mock skipped the
   real procedures' source-only startup gate and could not reproduce the
   recorded 12 V cold-start failure. Efficiency was fitted about 9 points
   above the measured 86–87 %.
3. **State must follow the bench, not a job id.** F5 during "report queued",
   a second tab, or an old report rendering after a new Start showed an idle
   header; double-clicking Confirm stop sent two interrupts.
4. **One vocabulary and a glossary.** The same skipped point was
   `assumption_limited` (CLI), "Outside planning budget" (UI) and
   `unsupported` (report); *path efficiency*, *qualified*, *revision*,
   *lease*, *approval_blocked* were never defined where a newcomer first
   meets them.
5. **Repository hygiene.** CI has been red on Python 3.11 since the workflow
   was added (seven `Path.read_text(newline=)` sites in tests); the only copy
   of every real measurement was on one SD card (an archive now exists at
   `Data/Runs/evidence-backup-2026-09-30.tar.gz`, 82 MB, for the owner to
   download); several documents carried stale statements (test totals, the
   merged pull request, a missing security-review resolution).

## Fix assignments

| Scope | Owner | Source findings |
| --- | --- | --- |
| Plant and runner realism: current-limit collapse and phase stop, soft-start and source-only gate, refit to the measured DUT, quantised/held readbacks with the recorded load offset, thermal time constant, bounded simulated runs with SIGTERM finalisation, `docs/simulation-plant.md` | plant implementer (adapters.py, runner.py, mock profiles) | EE B1, M1–M5, m3, m5; QA M2 |
| Bench page: Simulation identity and can/cannot panels, page follows the bench, single-shot Stop/Start/Regenerate, no silent profile overwrite, operator-language validation, first-screen bugs (pill contrast, Reports column), phone layout, keyboard/touch access, `/annotations` clarity, `docs/glossary.md` | page implementer (ui.py, ui_models.py, job_service.py) | UI/UX B1, B2, majors; QA M1, M3, M4, m1, m2, m6, m7, m9; new-user items 2–5 |
| Standards catalog: `mock_only` / approval-required status for ISO 16750-2 §4.5 and §4.6.2, duration check against the 660 s / 720 s limits, corrected sentences, unverifiable edition claims marked as such | standards implementer (standards.py, supply_profiles.py, docs/standards/) | EE M3; UI/UX B3 |
| CI green on 3.11, tolerant 390 px browser assertions, PDF small-table keep-together and duplicate warning, lost comparison demo re-created, document reconciliation, CLI help text | hygiene implementer | manager items 1, 3; new-user items 1, 5; coordinator |

## Owner decisions the reviews surfaced (not fixed by agents)

- License (no `LICENSE` file; GPL-3.0 provenance question for adapted driver code).
- An external current reference (DMM + shunt) to resolve the ≈11 mA load-readback offset; without it light-load efficiency stays unquantified.
- Backup destination off the Pi for `dcdc-bench/runs/`, `workspace/`, `Data/Runs/`.
- The next 24 V bench session and the 12 V cold-start test plan (both need the owner's authorization and arming at the bench).
- Python floor: keep 3.11 (tests fixed) or declare 3.13.
- Delete the parked theme branch `worktree-agent-a6546934fb2137254` (design A was chosen).
- The owner's 34-item characterization list for the IEC/ISO cross-check.

Resolutions are appended to each review document by the implementer that
closes its findings; this page is updated when the round ends.
