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
   real bench. Click a card to select it. **Rename** changes the displayed
   model name, **Edit** opens the converter fields (ratings, the label check
   and the two real-bench approvals), **Delete** asks *Delete this saved
   converter? Past runs keep their own copy.* **+ Add a converter** opens the
   same fields for a new profile. The saved file name never changes.
2. **Simulated or real bench?** Two tiles. *Simulated bench — nothing is
   switched on* runs the synthetic plant. *Real bench — DP821A CH1 + DL3031A*
   (models from the bench profile or the private inventory) shows the saved
   **limit presets** as pills with plain names (*24 V converter tests*, *Wide
   input up to 36 V*, *Pass-through wire check (12 V)*), the four protective
   limits (supply current limit, input over-voltage, output voltage guard,
   output current guard) always visible, **Change limits…** (saving new limits
   clears that preset's approval) and **I reviewed these limits — required
   once**, which is stored on the bench profile. Real versus simulated comes
   from this tile only; a test no longer carries an execution mode, and a saved
   test that still does is planned as the bench says, with a note in the plan.
3. **Which test?** Cards grouped by category (default *Normal operating
   voltage*; tests filed under a standard show its clause as a badge), each
   with its plain name, the grid (`24 V × 0 / 0.1 A`) and `N points · ~62 s`
   on the real bench (the backend's own time arithmetic) or `N points ·
   simulated` (the simulated bench runs on a virtual clock). A test the planner
   cannot run on the selected bench is greyed with the planner's first reason.
   **Rename**, **Duplicate**, **Edit** and **Delete** per card; **+ New test**
   opens the grid fields (input voltages and loads as comma-separated numbers,
   dwell, measurement time, planning assumptions) plus the name, category and
   optional standard clause. A test belongs to whichever converter is selected
   when it is previewed; the saved copy follows.

### Automotive standards in Which test?

Below the saved tests, the group **Automotive supply standards** shows one
card per standard from the catalog in `docs/standards/`: ISO 16750-2:2023,
ISO 7637-2, CISPR 25, ISO 11452, ISO 10605, ISO 16750-3 and ISO 16750-4. A
standard this bench cannot run is greyed with its one-sentence reason (a
transient generator, an EMC chamber, a shaker, a climatic chamber). The
ISO 16750-2 card carries a **12 V system** / **24 V system** badge and its
footer counts *N of M clauses runnable on this bench* for the selected
converter and bench.

Selecting the ISO 16750-2 card expands it into a **clause checklist** and
ticks every runnable clause; selecting it again folds it. The **12 V / 24 V**
toggle switches every row to the other system's parameters (supply codes,
UA, levels) and is remembered on the converter profile
(`system_voltage_class`, default 12 V). Each row shows the clause, its levels
for this converter, and a badge:

- **runs here** (green, ticked, untickable individually): §4.2, §4.5 and
  §4.6.2 for the 12T12-4A on either system class.
- **procedure not yet implemented** (amber, not tickable) with the concrete
  requirement: §4.3.1.1 (*60-min hold exceeds the 540 s run budget; needs a
  long-hold procedure*, 12 V only; at 24 V its 36 V level equals the DUT
  ceiling) and §4.6.1.2 (*>=1 s interruptions only; needs an interruption
  procedure*).
- **needs \<instrument\>**, **not on this bench**, **outside DUT rating**,
  **excluded by policy** or **not applicable** (grey, not tickable), with the
  catalog's reason under the row and as a tooltip. Load dump, reversed
  voltage, short circuit and overload stay excluded by policy (brief §2, §7.5).

**Add as tests** saves one recipe per ticked clause under the category
*ISO 16750-2 supply profiles*, titled like `ISO 16750-2 §4.2 — supply voltage
range (12 V system)` with the clause as its badge:

- §4.2 becomes an ordinary `steady_state_load_sweep` at UA, Usmin and Usmax
  (14 / 9 / 16 V for code C at 12 V; 28 / 10 / 32 V for code E at 24 V) with a
  0.1 / 0.25 / 0.5 A load grid. A level above the bench envelope or the
  input over-voltage guard stays in the plan and Preview explains it; nothing
  is dropped. Each level is a separate cold-started DC point; the standard's
  t1/t2 hold profile is not reproduced.
- §4.5 becomes a `slow_supply_ramp` and §4.6.2 a `reset_staircase`. Both run
  on the **simulated bench only**: the real bench refuses them at Preview as
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
points will run, how many are skipped and why (identical reasons grouped), the
estimated time on the real bench, the bench in use, and in red the **Before
Start** list: missing converter or limit approvals, a missing inventory, or
settings the real backend does not support. Every requested point stays in
the saved plan and is listed in the report as not run. Then **Start simulated
test**, or **Start test on the real bench**, which first opens the physical
confirmation (wiring and polarity, CH1, limits reviewed, both instrument
serials); only **Switch on and start** arms the job, and the worker verifies
the connected identities before it enables outputs. Changing any of the three
selections, or saving a profile, marks the plan stale and disables Start until
you Preview again.

While a job is queued, acquiring or generating its report, the header pill
shows a spinner with a short phrase (`Acquiring… point 2 of 4`, `Generating
report…`), the local start time and the elapsed time; the three questions are
locked; and **Stop…** sits at the far right of the header, never where Start
was. It asks **Confirm stop** or **Keep running**; a confirmed stop is recorded
and the Run section shows *Stop requested: <local time>* once the worker has
seen it. Wait for both outputs to be reported as verified OFF before changing
wiring. The **Run** section shows measured voltage and current, progress,
measurement age, shutdown status, recent events and the report links of the
selected run.

After acquisition the worker exits with both outputs verified OFF and the job
shows **Measurements saved — report queued**. The page starts a separate report
process automatically when no test is running and enough memory is free; while
it waits, the reason (for example `MemAvailable below 150 MiB`) is shown in the
Run section. A new test may be started while reports are queued. **Reports**
lists every saved run in bench-local time with the run (converter · test),
bench (Real or Simulated), status and **Open HTML**, **Open PDF**, **View run**
and **Regenerate report**, which queues a new report from the preserved
measurements without running the instruments again. The list refreshes itself
from the same two-second poll and a `Report ready: <run id>` notice appears;
**Refresh saved runs** is only needed for runs created outside this page. Every
time the page shows is the bench computer's local clock with its zone
abbreviation, e.g. `13:40:12 PDT (2026-09-29)`; the evidence files keep
recording UTC. See [the process model](pi-process-model.md) for the memory
thresholds and logs.

Profiles are saved when you press Save in an editor, tick or clear a limit
approval, rename, duplicate or delete. Deleting or renaming a profile that an
active job was started from is refused; finished jobs keep their own plan
snapshot, so their reports are unaffected.

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

Notes for the report can describe the setup today. Adding or repositioning photographs
and schematics through the UI requires a separate report revision/asset workflow
and is not currently available; finalized measurements are never edited by this
page.
