# Handoff: rigol-control and dcdc-bench

Written 2026-09-28 for the project owner and for any future Claude Code
session that has lost the original conversation. Everything a new session
needs to continue safely is either in this file or linked from it. Read it
top to bottom before changing anything; it takes ten minutes.

## 1. What this repository is

Two Python projects share one repository and one virtual environment:

- `Software/` — **benchctl**, the owner's instrument-control library and CLI
  for Rigol DP800-series supplies and DL3000-series loads over LXI/VXI-11.
  Stable, 445 tests, verified on a DP821A and a DL3031A.
- `dcdc-bench/` — the DC-DC converter characterization bench built on top of
  benchctl through thin adapters: typed DUT/bench/recipe profiles, a
  feasibility planner, a deterministic mock bench, evidence-preserving run
  folders, deterministic analysis, offline interactive HTML + vector PDF
  reports, and a loopback-only NiceGUI bench page. Its governing
  specification is [dcdc-bench/docs/implementation-brief.md](dcdc-bench/docs/implementation-brief.md)
  (byte-identical to the owner's master copy `~/1README.md`). Treat every
  `MUST` in it as an acceptance requirement.

The first device under test is a **12T12-4A** converter (9–36 V in, 12 V / 4 A
out, user-supplied ratings). The bench source is **DP821A CH1 (0–60 V, 0–1 A)**,
so full 48 W output cannot be tested anywhere in the input range; the planner
says so and never clips a request silently.

Milestone position (stated identically in
[implementation_status.md](dcdc-bench/docs/implementation_status.md),
[acceptance.md](dcdc-bench/docs/acceptance.md) and the README): **M0 reached;
M1 substantially reached; M2 partial; an M3 workflow slice demonstrated but
M3 not complete; M4 and M5 software present on mock and stored data only.**
The real gate to calling M3 done is M2 qualification (measurement freshness,
readback accuracy, uncertainty budget) —
see [m2-qualification-plan.md](dcdc-bench/docs/m2-qualification-plan.md).

## 2. The machine and the bench

| Fact | Value |
| --- | --- |
| Bench computer | Raspberry Pi, `aarch64`, hostname `rigol` (mDNS `rigol.local`), user `jerome`. Until 2026-09-28 a 1 GB model; the SD card is being moved to a **Raspberry Pi 4** with more RAM. |
| Checkout | `/home/jerome/rigol-control` (branch `dcdc-bench-hardening`) |
| Python environment | `/home/jerome/rigol-control/.venv` (Python 3.13); both projects are installed editable from this checkout. Always run Python as `/home/jerome/rigol-control/.venv/bin/python`. |
| Instruments | DP821A supply (CH1 only is used) and DL3031A load on the LAN. Addresses and expected serials live only in `Software/config/lab.yaml`, which is gitignored and must never be committed or quoted. |
| Bench UI service | user systemd unit `~/.config/systemd/user/benchctl-report.service` (linger enabled, starts at boot): `python -m dcdc_bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml --report-root Data --port 8081`, loopback only. Reach it from a laptop through `ssh -L 8081:127.0.0.1:8081 <user>@<pi-hostname>` or VS Code's port forwarding. |
| Rendering tools | Quarto 1.10.18 under `dcdc-bench/.tools/quarto-1.10.18` (gitignored); Kaleido needs a Chromium — Debian's `/usr/bin/chromium-headless-shell` works when memory allows (it failed under load on the 1 GB Pi). |
| Owner's editor | VS Code Remote SSH into the Pi; the SSH link was unreliable on the 1 GB Pi, which is why this file exists. |

## 3. What lives where

Committed and on GitHub (`https://github.com/robomaniac/rigol-control`,
branch `dcdc-bench-hardening`; `main` is the older supply-to-load demo and
its GitHub Pages site):

- all source, tests, profiles, templates and documentation of both projects.

**Only on the SD card** (gitignored on purpose — copy them if you ever move
to a fresh card instead of swapping this one):

| Path | Contents |
| --- | --- |
| `dcdc-bench/runs/` | every measured run folder (raw JSONL evidence, SCPI transcripts, analyses, report revisions) — the project's only copy of the real measurements |
| `dcdc-bench/workspace/` | saved UI profiles, previews and jobs |
| `Data/Runs/` | published/preview copies of reports served by the UI |
| `dcdc-bench/.tools/` | Quarto |
| `.venv/` | the Python environment |
| `Software/config/lab.yaml` | private instrument inventory (addresses, serials) |
| `~/.claude/projects/-home-jerome/memory/` | Claude Code's memory notes about this project (only loaded when Claude is started from `/home/jerome`) |

## 4. Branch state and how to verify it

Last verified state (2026-09-28, commit `cc98899` on `dcdc-bench-hardening`):

```sh
cd /home/jerome/rigol-control
git status                                   # expect: clean, on dcdc-bench-hardening
cd Software && ../.venv/bin/python -m pytest -q          # 445 passed (10 s on the Pi 4)
cd ../dcdc-bench && ../.venv/bin/python -m pytest -q -m "not browser and not pdf"   # 692 passed, 15 deselected (2 min 19 s on the Pi 4)
../.venv/bin/python -m pytest -q -m "browser or pdf"     # 14 passed, 1 skipped on the Pi 4 (system Chromium 153 + Quarto; ~4 min, builds a demo)
```

Run one pytest at a time; the suites spawn worker subprocesses and fsync every
record, so a loaded SD card makes them slow, and a very tight memory situation
can make Chromium refuse to start.

What the branch changed compared with `main` (all commit messages explain
their *why*; `git log --oneline main..dcdc-bench-hardening`):

- brought `dcdc-bench/` under version control;
- made saved-profile approvals load-bearing (`planning.missing_approvals`,
  enforced in the planner, `real_backend.prepare_real_plan`,
  `JobService.start` — which rebuilds the plan instead of trusting a cached
  preview — `extended._run_fixed_unlocked` and `bringup.run_bringup`);
- one shared protection-programming sequence on `bringup.RigolPilot`, a
  bounded `RigolDP800.set_voltage_live` instead of a raw SCPI interlock bypass,
  runtime-checkable section 5.2 contracts, a RUN-02 reconnect test;
- model-derived report narrative, `reports/<rev>/exports/`, hermetic tests;
- parallel sessions then added: M4 paired-run comparison, the approved UVLO
  input-ramp procedure, a mock-only thermal extension, read-only `doctor`, a
  publication gate with a redactor, a structured uncertainty budget, an
  automated PDF pagination check, WEB-08 fixtures, a report queue with a
  memory gate, CI, a contributing guide, a docs index, the cold-start
  hypothesis and the M2 qualification plan, and two merge reviews
  ([merge-code-review.md](dcdc-bench/docs/merge-code-review.md),
  [merge-security-review.md](dcdc-bench/docs/merge-security-review.md)).

## 5. Rules that must keep holding

These come from the brief and from the owner; a future session must not relax
them without the owner saying so explicitly.

1. **Never energize instruments on your own.** Real runs require the operator:
   saved-profile approvals (`execution_approval.real_hardware_enabled`,
   `wiring_and_polarity_confirmed`, `protective_controls.approved`) plus a
   fresh wiring/CH1/protections/serial confirmation at every Start. `--arm`
   on the fixed procedures is an operator action, never a script default.
   `cli.py run --mode real` stays disabled.
2. **Never push `main` or publish reports without being asked.** Pushing the
   working branch is fine when asked; force-pushes only on explicit request.
3. **Never commit `Software/config/lab.yaml`, run folders, workspace or
   anything with instrument serials or addresses.** Check with
   `git grep` against the values in `lab.yaml` before pushing (a 2026-09-28
   check found none; a test fixture that coincidentally equalled a bench
   address was changed).
4. **Evidence is immutable.** A corrected formula is a new analysis revision;
   a re-render is a new report revision; never edit a finalized run folder.
5. **Reports never invent conditions.** Narrative comes from the report model;
   mock and imported data stay labeled.
6. Keep this Pi's private details (`/home/jerome`, `rigol.local`, the
   username) out of new public files; use `<user>` / `<pi-hostname>`.

## 6. After the SD-card swap to the Raspberry Pi 4

The card carries the OS, the checkout, the venv, the evidence and the service,
so the same user, hostname and paths come back. Checklist:

```sh
hostname; uname -m; free -m                  # expect rigol, aarch64, several GB
systemctl --user status benchctl-report.service   # active (restart it if it shows old code: systemctl --user restart benchctl-report.service)
cd /home/jerome/rigol-control && git status && git log --oneline -1   # clean, cc98899 or later
.venv/bin/python -c "import dcdc_bench, benchctl; print(dcdc_bench.__file__, benchctl.__file__)"   # both resolve inside this checkout
swapon --show                                 # zram only; the old temporary swap file is no longer needed
```

Then run the two test suites from section 4. With the extra RAM the 15
browser/PDF checks should pass locally for the first time — record the result
in `implementation_status.md`.

Memory monitoring (installed 2026-09-28 to judge whether 2 GB is enough): the
user unit `bench-memory-monitor.service` runs
`dcdc-bench/tools/memory_monitor.py` every 30 s and appends to
`Data/Logs/memory-monitor.jsonl` (gitignored). Summarize with
`.venv/bin/python dcdc-bench/tools/memory_monitor.py --summary Data/Logs/memory-monitor.jsonl`;
watch `mem_available_min_mib`, `swap_used_max_mib`, `throttled_ever` and the
`largest_resident_processes_mib` table. VS Code's remote server plus each
Claude Code / Codex session costs several hundred MiB each; the bench software
itself is under 100 MiB idle. If the Pi 4 hostname or IP changed, update the
laptop's SSH config, not the repository. Nothing else needs migration.

## 7. Parked work in progress (do not delete blindly)

Resolved on 2026-09-28 (Pi 4 session):

- The ten uncommitted files left in the `agent-abeda9ea` worktree were the
  security-review fixes (upload/PDF budgets, publish allowlist and EXIF
  stripping, request-body limits, doctor `--out` guard) that had never reached
  the branch; they were salvaged, tested per file and **merged** (`bcdc58f`).
  Worktree and branch removed.
- `worktree-agent-a6546934fb2137254` (tip `c150360`, two commits) is kept as a
  **branch only**: four selectable report themes plus a new
  efficiency-vs-input figure, ~415 lines over 9 files, no tests, and it
  pre-empts the owner's open questions in
  [report-aesthetics-options.md](dcdc-bench/docs/report-aesthetics-options.md).
  Finish it only after the owner picks a theme direction; otherwise delete
  the branch deliberately (`git branch -D`, it is unmerged).

## 8. Decisions waiting for the owner

From [github-readiness.md](dcdc-bench/docs/github-readiness.md), all
low-sensitivity and all now public on the branch:

1. **License** — the repository has no `LICENSE` file; the owner chooses.
2. **Owner-machine details** (`/home/jerome`, `jerome`, `rigol.local`) in
   `Documentation/Pi-Reliability.md` and `Documentation/VS-Code-File-Watching.md`
   — genericize or accept.
3. **`http://localhost:8081/...` links** in the READMEs — label as local-only
   or replace with relative links.
4. **12 V cold start** — the converter failed twice to start at 12 V input;
   [cold-start-hypothesis.md](dcdc-bench/docs/cold-start-hypothesis.md)
   ranks the likely causes and proposes discriminating tests. Nothing in it
   authorizes energizing; that decision is the owner's.
5. **Merging** `dcdc-bench-hardening` into `main` (a pull request link is
   printed by `git push`); GitHub Pages currently serves `main`.

## 9. Next bounded tasks, in order

Done on the Pi 4 (2026-09-28/29): suites and browser/PDF gates verified
(section 4); parked worktrees resolved (section 7); M2 plan steps 1–3
(software-only) completed — datasheet terms transcribed
(`dcdc-bench/docs/instrument-specifications.md`, profile
`profiles/bench/rigol-dp821a-dl3031a.yaml`), historical readback evidence
analysed (`docs/m2-freshness-and-readback-evidence.md`), per-point budget with
an `unquantified` fall-through and an enabled-no-load stage added and
independently reviewed as safe; the owner-authorized read-only `doctor` run
confirmed identities, OFF states and the load's ≈10 mA zero-current readback.

Consequences the operator must know before the next real run:
- **Every saved real plan hash changed** (planner warnings text): re-run
  **Preview** before Start; stale previews are refused by design.
- With a **0 A first request** in a phase, the load now turns on 15–35 s after
  the source (source-only gate + no-load dwell/acquisition + loaded startup)
  instead of ~5 s.
- `NO_LOAD_IIN_SPAN_A = 2 mA` in `real_backend.py` is a proposed settling
  criterion for no-load windows — the owner must confirm or change it.
- Datasheet-bound readback accuracy gives about ±28 percentage points (k = 2)
  at 24 V / 0.1 A; light-load efficiency cannot be qualified from the internal
  readbacks alone. An external current measurement (DMM/shunt on the output
  lead, ideally the input lead too) is a hardware decision for the owner.

Also done on 2026-09-29: review follow-ups merged; **M2 plan step 4 run by the
owner** through the UI with the data-only pass-through profiles
(`passthrough-check` / `rigol-local-passthrough-12v` / `passthrough-12v-check`,
saved in `dcdc-bench/workspace/profiles/`): the load's current readback reads
+11.0…11.3 mA above the source's at every loaded level
(`docs/m2-freshness-and-readback-evidence.md` §F). The report now draws
flagged (implausible) points as open markers with a computed explanation and
a readback cross-check metric; the bench page shows a header activity
spinner, refreshes Reports automatically and displays bench-local time.

Remaining, in order:
1. **Owner hardware decision:** an external current reference (DMM + shunt on
   the output lead, ideally the input lead too) is the only way to resolve the
   ≈11 mA readback disagreement and qualify light-load efficiency.
2. **Bench, DUT at 24 V** (M2 plan step 5, owner authorization): reconnect the
   converter, re-Preview (plan hashes changed), one enabled-no-load window
   then one 0.1 A point through the UI's approvals and confirmation.
3. Optional step-4 extras not yet run: the sub-second freshness burst test
   (needs a new read-only probe with outputs ON) and the source 24 → 23 V step.
4. Only then revisit the M3 exit criteria; then the owner decides on the 12 V
   cold-start test plan (`docs/cold-start-hypothesis.md`).

## 10. For a future Claude Code session

Start Claude from `/home/jerome` so its memory notes load, or simply paste:

> Read `HANDOFF.md` in `/home/jerome/rigol-control`, then
> `dcdc-bench/docs/implementation_status.md`, `dcdc-bench/docs/acceptance.md`
> and `dcdc-bench/docs/github-readiness.md`. Verify the branch with the
> commands in HANDOFF section 4 before changing anything. Do not energize
> instruments, push `main`, or publish reports unless I ask.

Pitfalls learned the hard way:

- Use `/home/jerome/rigol-control/.venv/bin/python`; the system Python has
  none of the dependencies. In a git worktree, prefix
  `PYTHONPATH=<worktree>/dcdc-bench/src`, because the editable install points
  at the main checkout.
- The UI service snapshots the published report names at startup; a new
  folder under `Data/Runs/` needs `systemctl --user restart benchctl-report.service`.
- `sudo` prompts for a password and cannot be used non-interactively.
- Rendering needs memory: Kaleido's Chromium failed on the 1 GB Pi whenever
  agents, tests and the UI service ran together.
- Tests that patch `time.sleep` globally also capture subprocess polling;
  count only the sleeps you mean.
- Reviews in `dcdc-bench/docs/*-review.md` were written by automated agent
  roles, not by humans; they say so in their first lines.
