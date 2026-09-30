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
