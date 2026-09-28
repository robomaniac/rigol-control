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

1. **Bench:** choose the simulated or real saved bench and review its limits.
2. **DUT and recipe:** choose the converter, confirm its ratings, then enter
   input voltages and output loads as comma-separated numbers. For example,
   `24, 35.8` and `0.1, 0.25, 0.5`. Every voltage is paired with every load.
3. Choose **Preview test and limits**. This saves your profiles locally and
   shows every requested point, including points excluded by the bench limits
   or planning assumptions. Preview never enables an output.
4. For real equipment, review the limits, confirm the wiring/channel and enter
   the configured instrument serial numbers. Choose **Start test**. The worker
   verifies the connected identities before it enables outputs.
5. **Run** shows measured voltage/current, progress, measurement age and shutdown
   status. **Stop test safely** requests shutdown; wait for both outputs to be
   reported as verified OFF before changing wiring.
6. After acquisition, the worker creates the reports. Open **interactive HTML**
   to inspect points and export plots, or **PDF** for a printable report.
   **Reports** retains completed and interrupted runs. If rendering fails,
   **Retry report generation** uses the preserved measurements without running
   the instruments again.

Changing any setting clears the preview and its confirmation. Preview again
before starting. Enter a different profile name to save a reusable variant.
Existing profile names update that saved configuration; issued run evidence
keeps its original snapshot.

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

Test notes can describe the setup today. Adding or repositioning photographs
and schematics through the UI requires a separate report revision/asset workflow
and is not currently available; finalized measurements are never edited by this
page.
