# Use the local DC–DC test bench

The bench page takes a saved converter and a list of input voltages and output
loads, checks what the equipment can reach, runs the measurements, then links the
interactive HTML report and printable PDF.

## Start the page

From the repository root on the Pi (create the virtual environment if this is a
fresh checkout):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . -e './dcdc-bench[ui,report]'
.venv/bin/dcdc-bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml
```

Use your actual private inventory path. Omit `--inventory` to explore the saved
simulated bench without opening instruments. The default page is
<http://localhost:8082>; the server listens only on the Pi's loopback interface.
HTML/PDF generation also requires Quarto/Typst and Chromium. Follow the
[report-tool installation steps](../README.md#try-the-demonstration), including
the pinned Quarto setup, before starting a job that generates reports.

If the Pi already uses port 8081 for saved reports, the application can preserve
those links on the same forwarded port:

```bash
.venv/bin/dcdc-bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml --port 8081 --report-root Data
```

This preserves `/Runs/...` and existing top-level HTML/CSV/JSON/SVG links from
the explicitly published directories, files and aliases present when the
application starts. Restart the application after publishing a new alias or
changing its target. Use the configured port in the forwarding instructions below.

When connected with VS Code Remote SSH, open **Ports**, choose **Forward a Port**,
and enter **8082**. Open the displayed local address in your laptop's browser.
Alternatively, on the laptop:

```bash
ssh -L 8082:127.0.0.1:8082 <user>@<pi-hostname>
```

Keep the UI process running on the Pi. A port forward reaches an existing server;
it does not start one. VS Code's **Remote: Restore Forwarded Ports** setting can
restore the tunnel after reconnecting.

## Run a test

The page is one column with three questions, then **Preview** and **Start** in
a bar fixed to the bottom of the window. There are no tabs.

1. **Which converter?** One card per saved converter: model, ratings
   (`9–36 V in, 12 V / 4 A out`), sample id, and whether it is approved for the
   real bench. The card face is one button: click it, or focus it and press
   Enter or Space, to select it. Its **⋯** menu holds **Rename** (changes the
   displayed model name), **Edit** (the converter fields: ratings, the label
   check and the two real-bench approvals) and **Delete**, which asks *Delete
   this saved converter? Past runs keep their own copy.* and closes an editor
   that was open on that converter. **+ Add a converter** opens the same fields
   for a new profile and refuses a file name that is already saved (*A
   converter file named “12t12-4a” already exists. Nothing was overwritten.*)
   with two ways out: **Use a free file name** or **Open the existing
   converter**. Changing the file name in **Edit** moves the profile to the
   new name; saved tests that referenced the converter follow it.
2. **Simulated or real bench?** Two tiles forming one radio group (arrow keys
   move between them). *Simulation — Nothing is switched on. Synthetic
   readings, real report layout; every output is labelled SYNTHETIC.* shows
   the synthetic envelope in the same table the real tile uses (*Synthetic
   source 0–60 V · 1 A · 60 W*, *Synthetic load*, *Protective limits none —
   only the planning budget bounds the plan*, *Readback uncertainty synthetic
   example specification, not an instrument*), so a point the plan skips is
   predictable from the tile, and a panel **What the simulation can and cannot
   do**: it runs a deterministic synthetic converter, source and load on a
   virtual clock, reproduces realistic supply current limiting and start-up
   behaviour, labels every output SYNTHETIC, touches no instrument and uses the
   same report layout and workflow as the real bench; it cannot measure your
   converter, prove anything about safety, protective limits or a real
   start-up, show ripple, transients or thermal behaviour, or give an
   instrument uncertainty (any ± in its report comes from the synthetic
   specification). *Real bench — DP821A CH1 + DL3031A* (models from the bench
   profile or the private inventory) shows the saved **limit presets** as
   pills with plain names (*24 V converter tests*, *Wide input up to 36 V*,
   *Pass-through wire check (12 V)*; the selected pill is filled with a white
   label), the four protective limits (supply current limit, input
   over-voltage, output voltage guard, output current guard) always visible,
   **Change limits…** (saving new limits clears that preset's approval), **I
   reviewed these limits — required once**, which is stored on the bench
   profile and never also switches the tile, and its own panel **What the real
   bench can and cannot do** from [configured-runs.md](configured-runs.md):
   steady DC efficiency, regulation and power loss at 0.05–2.5 A and at most
   34 W, 1–35.8 V input with one cold start per input voltage, polled DC guards;
   it cannot reach the 48 W rating with the 1 A source, cannot run unsupervised
   (saved approvals plus a fresh confirmation before every Start), cannot
   measure temperature, ripple, transients or dynamic response, and cannot
   certify accuracy while uncertainty is unquantified. Simulation versus real
   comes from this tile only; a test no longer carries an execution mode, and
   a saved test that still does is planned as the bench says, with a note in
   the plan.
3. **Which test?** Cards grouped by category (default *Normal operating
   voltage*; tests filed under a standard show its clause as a badge), each
   with its plain name, the grid (`24 V × 0 / 0.1 A`) and `N points · ~62 s`
   on the real bench (the backend's own time arithmetic) or `N points ·
   simulated` (the simulation runs on a virtual clock). A test the planner
   cannot run on the selected bench is greyed with the planner's first reason
   in red. Each card's **⋯** menu offers **Rename**, **Duplicate**, **Edit**
   and **Delete**; **+ New test**, at the end of the saved tests, opens the grid
   fields (input voltages and loads as comma-separated numbers, dwell,
   measurement time, planning assumptions) plus the name, category and
   optional standard clause, and refuses an existing file name the same way
   as **+ Add a converter**. A cleared number is refused with *Enter a number
   for “Minimum settling time (s)”.*; a limit names the field you see (*“Minimum
   settling time (s)” must be at most 30 s, this test’s settling timeout.*). A
   test belongs to whichever converter is selected when it is previewed; the
   saved copy follows.

### Automotive standards in Which test?

Below the saved tests, the group **Automotive supply standards** shows one
card, ISO 16750-2:2023: the other automotive standards of the catalog in
`docs/standards/` (ISO 7637-2, CISPR 25, ISO 11452, ISO 10605, ISO 16750-3 and
ISO 16750-4) need other laboratories, so they are not offered as cards; one
footnote under the card says so and links the catalog, served read-only at
`/standards` from `docs/standards/README.md`. The ISO 16750-2 card carries a
**12 V system** / **24 V system** badge and prints the catalog's count for the
selected converter and bench, for example *19 clauses: 1 DC level subset
available, 2 after approval*.

Selecting the ISO 16750-2 card expands it into a **clause checklist** and
ticks the available DC level subset; selecting it again folds it. Exactly
one test is selected for Start at any time: selecting a test card in any group
deselects the previous one and folds the ISO 16750-2 checklist, and the header
and the bottom bar name that one test. The ISO 16750-2 card is an editor, not
a test: open, it is blue and dashed with an expand arrow (never green with a
check), it leaves the selection alone, and **Add as tests** folds it and
selects the last test it generated. The
**12 V / 24 V** toggle switches every row to the other system's parameters
(supply codes, UA, levels) and is remembered on the converter profile
(`system_voltage_class`, default 12 V). Each row shows the clause, its levels
for this converter, and the catalog's status word as a badge:

- **DC level subset** (green, ticked by default): §4.2 supplies the voltage
  levels for partial characterization on either system class. The standard's
  t1/t2 holds and 1 V/s transitions are not reproduced; no clause-compliance
  result is claimed.
- **runs here after approval** (amber, tickable but not ticked by default):
  §4.5 and §4.6.2. The recipes they generate step below the converter's stated
  minimum and are written unapproved, so their cards stay greyed with the
  planner's reason until approved. The row says where that approval is
  recorded, in the catalog's words: *Approval happens in the saved recipe, not
  on the bench page: set `authorization.uvlo_approved` to true and
  `authorization.protective_policy_id` to the bench profile's
  `protective_controls.policy_id`, and declare `source_current_limit_A`,
  `dut_output_overvoltage_V` and `output_overcurrent_A` in that bench
  profile.* On a real bench preset the same two clauses are **mock only**
  (amber, not tickable): the procedure exists on the synthetic plant only.
- **procedure not yet implemented** (amber, not tickable) with the concrete
  requirement: §4.3.1.1 (*60-min hold exceeds the 540 s run budget; needs a
  long-hold procedure*, 12 V only; at 24 V its 36 V level equals the DUT
  ceiling) and §4.6.1.2 (*>=1 s interruptions only; needs an interruption
  procedure*).
- **needs \<instrument\>**, **not on this bench**, **outside DUT rating**,
  **excluded by policy**, **needs split** or **not applicable** (grey, not
  tickable), with the catalog's reason under the row. Load dump, reversed
  voltage, short circuit and overload stay excluded by policy (brief §2, §7.5).

The checklist footer counts *N test subsets available now · 19 clauses reviewed · M
after approval*.

**Add as tests** saves one recipe per ticked clause under the category
*ISO 16750-2 supply profiles*, titled like `ISO 16750-2 §4.2 — DC level subset
(12 V system)` with the clause as its badge:

- §4.2 becomes an ordinary `steady_state_load_sweep` at UA, Usmin and Usmax
  (14 / 9 / 16 V for code C at 12 V; 28 / 10 / 32 V for code E at 24 V) with a
  0.1 / 0.25 / 0.5 A load grid. A level above the bench envelope or the
  input over-voltage guard stays in the plan and Preview explains it; nothing
  is dropped. Each level is a separate cold-started DC point; the standard's
  t1/t2 hold profile and 1 V/s transitions are not reproduced. The recipe's
  title, referenced clause and scope description travel into the HTML/PDF
  method section, including these deviations.
- §4.5 becomes a `slow_supply_ramp` and §4.6.2 a `reset_staircase`. Both run
  in the **simulation only**: the real bench refuses them at Preview as
  *not yet approved for real hardware*. The ramp walks UA down to 1 V and back
  in 20 mV live steps every 2.4 s (0.5 V/min) with a qualified observation at
  every 1 V; the staircase alternates Usmin with its 5 % lows, each low held
  at least 5 s and each recovery at least 10 s. Because both step below the
  converter's stated minimum, they take the approved UVLO-style path
  (brief §7.5): the saved recipe ships with `authorization.uvlo_approved:
  false` and its card stays greyed with the planner's reason until the recipe
  is approved under the bench's protective policy, exactly like the shipped
  UVLO example. The standard's 0 V end level is not requested (a 0 V source
  setpoint is outside the planner's positive-input rule); the report records
  that deviation.

The report for a ramp or staircase states, per level, whether the output was
in band, off (reset), recovered or not recovered, computed from the classified
states only and labelled as the synthetic plant, and says plainly that the
levels were commanded as bounded DC steps at the ~1 s cadence, that the ramp
is a staircase of live steps rather than a linear ramp, and that no edge or
transient was measured.

Choose **Preview**. Nothing is switched on. The plan panel shows how many
points will run, how many are skipped and why (identical reasons grouped,
each with the planner's own word: *2 points assumption_limited: Requested load
exceeds the planning budget …*), the estimated time (on the real bench from
the backend's arithmetic; in the simulation *Measurements: seconds (virtual
clock) · Report: typically 1–4 min on a Raspberry Pi*), the bench in use, and
in red the **Before Start** list: missing converter or limit approvals, a
missing inventory, or settings the real backend does not support. The table of
all requested points uses the same words as the CLI and the saved plan
(`executable`, `assumption_limited`, `approval_blocked`, `unsupported`) with a
legend beneath it; a request is never reduced to fit, and skipped points stay
in the saved plan and are listed in the report with the same reason. In the
simulation the ready line spells out what follows Start: *Acquiring
measurements* (seconds) → *Measurements saved — report queued* → *Preparing
HTML and PDF* (minutes on a Pi) → *Complete*, with the links under Run and in
Reports. Until a fresh plan exists the bottom bar says why Start is disabled
(*Preview first — Start unlocks after a fresh plan.*, *Locked while a test runs
on the bench.*, or *The plan cannot start: see the Before Start list*). Then
**Start simulation**, or **Start test on the real bench**, which first opens
the physical confirmation (wiring and polarity, CH1, limits reviewed, both
instrument serials); only **Switch on and start** arms the job, and the worker
verifies the connected identities before it enables outputs. Start is
single-shot: a second click before the service answers does nothing, and a
refused Start (a profile changed, another job holds the bench) marks the plan
stale (*Start was refused — Preview again before starting.*). Changing any of
the three selections, or saving a profile, also marks the plan stale and
disables Start until you Preview again.

The page follows the bench, not the job one tab happened to start. Every two
seconds it asks the service which job is working or waiting for its report;
a reload (F5), a second tab or a job started from the CLI attach to it, the
header, the lock and Start describe it, and the lock releases when it ends.
While a job is queued, acquiring or generating its report, the header pill
shows a spinner with a short phrase led by the mode word (`Simulation:
Acquiring… point 2 of 4`, `Real bench: Generating report…`), the local start
time and the elapsed time; the three questions are locked; and **Stop…** sits
at the far right of the header, never where Start was. It asks **Confirm
stop** or **Keep running**; **Confirm stop** asks the service once (a double
click, or a second tab, sends no second interrupt and keeps the first stop
time), the stop is recorded and the Run section shows *Stop requested: <local
time>* once the worker has seen it. Wait for both outputs to be reported as
verified OFF before changing wiring. The **Run** section shows the mode
(*Simulation · synthetic data · no instrument is touched* or *Real bench ·
measured data*), for a simulation the four-step sequence with the current step
marked, measured voltage and current, progress, measurement age, shutdown
status, recent events and the report links of the selected run; under a
simulated report's links it notes that any ± is uncertainty from the synthetic
specification, not an instrument.

After acquisition the worker exits with both outputs verified OFF and the job
shows **Measurements saved — report queued**. The page starts a separate report
process automatically when no test is running and enough memory is free; while
it waits, the reason is shown in operator words in the header, the Run section
and the Reports row: *Waiting for free memory: 96 MiB available, 150 MiB
needed*, *Waiting for free memory and swap: …*, or *Waiting for the bench:
another acquisition or report is still running* (the dispatcher's raw reason
and the time it last checked are a tooltip). A queued report does not lock the
bench: a new test may be started while reports are queued, and while an older
report renders the header and the lock follow that render. **Remove from
report queue** leaves the measurements saved; the job then reads *Removed from
the report queue*, never *needs attention*. **Reports** lists the newest 30
saved runs (it says so when there are more) in bench-local time with the run
(converter · test), bench (**Simulation · synthetic data** or **Real bench ·
measured**), status and **Open HTML**, **Open PDF**, **View run** and
**Regenerate report**, which makes a new report revision from the preserved
measurements without running the instruments again (its tooltip says so; it is
single-shot). The list refreshes itself from the same two-second poll and a
`Report ready: <run id>` notice appears; **Refresh saved runs** is only needed
for runs created outside this page. Every time the page shows is the bench
computer's local clock with its zone abbreviation, e.g. `13:40:12 PDT
(2026-09-29)`; the evidence files keep recording UTC. See [the process
model](pi-process-model.md) for the memory thresholds and logs.

Profiles are saved when you press Save in an editor, tick or clear a limit
approval, rename, duplicate or delete. Deleting or renaming a profile that an
active job was started from is refused; finished jobs keep their own plan
snapshot, so their reports are unaffected. **+ Add a converter** and **+ New
test** never write over an existing file name; **Edit** with a changed file
name moves the profile; deleting a profile closes an editor open on it.

## What this procedure measures

The current real procedure measures steady DC efficiency, output regulation and
power lost between the supply terminals and load terminals. It starts the
converter separately at each input voltage, turning both outputs OFF between
input conditions. It does **not** warm-start a low input condition from a higher
voltage. For example, this 12T12-4A sample failed a direct 12 V startup within the
available 1 A supply limit; selecting 12 V does not imply that startup will work.

The supply's 1 A input limit gives different maximum output loads at different
input voltages. The preview keeps requests beyond that budget visible. A 4 A
converter rating does not make a 4 A output test possible with this bench.
Planning efficiency is an estimate used to choose a feasible grid; it is not a
measurement. Settled real measurements determine the report's results.

The initial real backend supports the reviewed DP821A CH1 / DL3031A setup and
loaded steady DC points. Temperature, dynamic response and no-load acquisition
are not enabled by selecting an unsupported recipe; the preview explains why
those requests cannot start. Instrument addresses and expected identities stay
in the private inventory. This page does not edit transport settings.

## Reconnect and evidence

The acquisition worker owns the instruments independently of the browser.
Closing a tab does not cancel a test; reopening the page reattaches to active
progress. A disconnected UI must not be interpreted as verified shutdown.

Profiles, job state and run files live under the selected local workspace,
which is ignored by Git. Interactive reports are served in a browser sandbox
that permits plotting and exports but prevents report scripts from accessing
the instrument-control page. Publishing a report does not publish bench control.

Notes for the report can describe the setup today. Photographs and sensor
markers are added on the separate **Sensor placement editor** page
(`/annotations`, linked from the footer): choose a finished run (each option
says *Simulation · synthetic data* or *Real bench · measured*; the uploader
unlocks once a run is chosen, and a simulated run carries a caution that
photographs describe a physical setup), upload a photograph, place the
markers, and **Save as new report revision**. Each save creates a new report
revision; finalized measurements are never edited by this page or by that one.

The footer also links the [glossary](glossary.md): path efficiency, qualified,
the planner's status words, SYNTHETIC, revision, lease, memory gate,
`report-queued` and the milestones M0–M5.
