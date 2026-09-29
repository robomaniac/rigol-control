# Measurements and reports

## Open the reports

- [Real 21-point power test](https://robomaniac.github.io/rigol-control/Data/power-test-report.html)
- [Simulated example](https://robomaniac.github.io/rigol-control/Data/sweep-preview.html)
- [Original three-point test](https://robomaniac.github.io/rigol-control/Data/demo-report.html)

These GitHub Pages links open interactive reports without the Pi, SSH, or port
forwarding. Opening an HTML file in GitHub's repository view shows its source
code. You can also download any report and open the file in your browser;
each report works offline.

### Local converter measurements

The **[configured workflow test](http://localhost:8081/Runs/12t12-workflow/report.html)**
used the new interface to test the 12T12-4A at 24 V input and 100, 250 and
500 mA loads. All three points qualified, the source and load were verified
OFF, and HTML/PDF reports were generated automatically. Path efficiency was
72.65%, 79.12% and 84.19%, including wiring losses.

[PDF](http://localhost:8081/Runs/12t12-workflow/report.pdf) ·
[Independent results review](../dcdc-bench/docs/configured-workflow-results-review.md) ·
[Open the local bench interface](http://localhost:8081/)

The **[15 V startup and input-descent test](http://localhost:8081/Runs/12t12-startup/report.html)**
started the converter at 15 V, then kept it powered while lowering input under a
100 mA load. All seven steps completed. At measured **9.108 V input**, the output
remained **12.134 V at 99.5 mA**. Both outputs were verified OFF afterward.

[PDF](http://localhost:8081/Runs/12t12-startup/report.pdf) ·
[Independent results review](../dcdc-bench/docs/startup-descent-results-review.md) ·
[Open the local bench interface](http://localhost:8081/)

The **[12T12-4A efficiency comparison](http://localhost:8081/Runs/12t12-efficiency/report.html)**
shows 27 measured load points at 24 V and near 36 V input, with a different color
for each voltage. At 500 mA output demand, path efficiency was **84.24%** and
**81.99%**, respectively. The upper-voltage sweep reached **2.5 A output**.
The 36 V nominal condition uses a **35.8 V setpoint**; actual voltage is measured.
The earlier 12 V startup stopped without a qualified efficiency result and is
documented separately in the same report.

[PDF](http://localhost:8081/Runs/12t12-efficiency/report.pdf) ·
[Offline ZIP, including both original runs](http://localhost:8081/Runs/12t12-efficiency-download.zip) ·
[Procedure and YAML](../dcdc-bench/README.md#efficiency-at-different-input-voltages)

The earlier **12T12-4A test near the supply limit** reached **1.725 A output**
while drawing **0.987 A from the 24 V supply**. It delivered about **20.5 W**
at **86.5% path efficiency**, including wiring losses.

[Interactive report](http://localhost:8081/Runs/12t12-source-limit/report.html) ·
[PDF](http://localhost:8081/Runs/12t12-source-limit/report.pdf) ·
[Offline ZIP](http://localhost:8081/Runs/12t12-source-limit-download.zip) ·
[Procedure and YAML](../dcdc-bench/README.md#test-near-the-supply-limit)

These are local Pi artifacts using your forwarded port, not published GitHub
Pages examples. Download and extract the ZIP to read it without SSH. See
[viewing local reports](../Documentation/Viewing-Local-Reports.md) if the port
shown in VS Code differs from 8081.

## Saved files

| File or folder | Contents |
| --- | --- |
| [power-test-report.html](power-test-report.html) | Real 5 V power delivery test: 21 loaded readings plus a starting reference. |
| [power-test-results.csv](power-test-results.csv) | Shareable measured readings from that same 21-point test. |
| [Example_Run/20260926T072124Z_load_sweep/](Example_Run/20260926T072124Z_load_sweep/) | Complete shareable copy of the real run: summary, action log, readings, CSV, report, and separate shutdown check. |
| [sweep-preview.html](sweep-preview.html) | Illustrated 5 V power delivery test: 21 load readings and a starting reference, clearly labelled as simulated. |
| [demo-report.html](demo-report.html) | Interactive report generated from the original measured three-point run. |
| [demo-results.csv](demo-results.csv) | Sanitized raw readings from that same run. |
| `Runs/` | Full local run records, ignored by Git. |
| `Logs/` | Local SCPI command traffic, ignored by Git. |

Rebuild the simulated preview with `python Software/create_preview.py`. It uses
illustrative values, not readings from the bench.

## Real 21-point test

Run `20260926T072124Z_load_sweep` began on 26 September 2026 at 07:21:24 UTC
(September 26 at 12:21:24 AM PDT). The DP821A CH1 supplied 5 V with a 0.50 A
current limit, while the DL3031A requested 50–300–50 mA in 25 mA steps.
There are 21 loaded readings at 11 current levels, plus an unloaded reference.

| Result | Measured value |
| --- | --- |
| Voltage at the device | 4.978736–4.989864 V |
| Largest supply-to-device voltage difference | 26.264 mV |
| Highest current drawn | 299.28 mA |
| Highest power used | 1.490034 W |
| Duration | About 105 seconds |

All acceptance checks passed, including the chosen **4.75–5.25 V** window.
Fresh identity checks and state readbacks after the run confirmed the load input
and CH1 output were **off**, with **0.0 V** at the load terminals. A shareable copy
of the full run is in `Example_Run/`; the private original remains in the ignored
local run folder. See [Verification](Verification.md) for
the earlier stopped attempt and the configuration change before this run.

## Actual run files

The [main README demo section](../README.md#actual-files-from-the-demo) links
each file and explains its purpose. These files are actual saved outputs from
the measured test, not examples with invented values.

In [the example run](Example_Run/20260926T072124Z_load_sweep/), only the two
instrument serial numbers in `run.json` have been replaced with `[redacted]`.
Manufacturer, model, firmware, settings, timestamps, measurements, and action
records are preserved. The regenerated `report.html` matches the original.
The extra `postflight.json` records the independent shutdown check; it is not
an automatic output of every recipe run.

Two CSV formats are available:

- The run's [measurements.csv](Example_Run/20260926T072124Z_load_sweep/measurements.csv)
  contains raw readings plus the acceptance bounds and per-value verdicts.
- [power-test-results.csv](power-test-results.csv) matches the report's CSV
  download, including requested current and calculated voltage differences.

Both contain the same 22 measured records. Rebuild the example's report from
the repository root, with no hardware connection:

```bash
benchctl report Data/Example_Run/20260926T072124Z_load_sweep
```

## Original three-point test

The original measured run is `20260925T064146Z_load_sweep`: DP821A CH1,
5 V / 0.50 A current limit, load requests 0.10 / 0.20 / 0.30 A. The saved acceptance range was 4.5–5.5 V. All acceptance
checks passed and both outputs were verified off afterward. The report UI has
been upgraded using those saved readings. The new 21-point run uses its own
4.75–5.25 V window; it does not change the historical data.

The chart in [Media](../Media/demo-load-sweep.svg) is unchanged. Its voltage
difference includes instrument offset and connection effects; derived lead
resistance is an apparent estimate, not a calibrated cable measurement. Supply
and load power/current are separate sequential instrument readbacks.

## Timestamps

`20260925T064146Z` means **2026-09-25 at 06:41:46 UTC**. `T` separates the date
and time; `Z` means UTC. In Los Angeles this was September 24 at 11:41:46 PM PDT.
UTC filenames sort in time order and avoid duplicated local times when clocks change.

## View over SSH

On the development Pi, the report server is managed by the user service
`benchctl-report.service`. It starts at login and runs independently of the
editor terminal. Check or restart it with:

```bash
systemctl --user status benchctl-report
systemctl --user restart benchctl-report
```

The service is local machine configuration, not part of the Python install.
The SSH port forward connects your computer's browser to that server. It closes
when SSH disconnects, even if the server is still running.

To restore it automatically when reconnecting, open **Settings** on your
computer (`Ctrl+,`), select the **User** tab, search for **Restore Forwarded
Ports**, and enable **Remote: Restore Forwarded Ports**. The equivalent setting
in your local user `settings.json` is:

```json
"remote.restoreForwardedPorts": true
```

Once a port is forwarded, VS Code can remember it for later sessions. This
setting restores the tunnel after reconnecting; it does not keep SSH connected
while the Pi or your computer is offline.

Open the HTML directly on your computer, or serve the shareable data folder:

```bash
python3 -m http.server 8081 --bind 127.0.0.1 --directory Data
```

For this manual command, keep the terminal running; skip it if the service is
already active. In your editor's SSH-connected window:

1. Press **Ctrl+Shift+P** and run **Ports: Focus on Ports View**.
2. Click **Forward a Port**, enter **8081**, and press **Enter**.
3. Click the globe / **Open in Browser** beside the forwarded port.
4. Add `/power-test-report.html` to the opened address. Normally this is
   `http://localhost:8081/power-test-report.html`.

If the editor assigns another local port, use the address shown in the Ports
view. `localhost` in your computer's browser means your computer; forwarding
connects it to the server on the Pi. See the
[official SSH forwarding instructions](https://code.visualstudio.com/docs/remote/ssh#_forwarding-a-port-creating-ssh-tunnel).

This serves saved files and does not contact the bench. The VS Code task
**benchctl: preview saved report** also starts the server.

To regenerate a report from a local run:

```bash
benchctl report --latest load_sweep
```

Keep `Runs/` and `Logs/` private unless reviewed: run summaries and traffic can
contain real identities and addresses. The committed HTML/CSV omit those fields.
