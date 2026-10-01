# Open a report from the Pi

The interactive HTML and PDF are saved files. You can download them once and
open them on your computer, or view them through your VS Code SSH connection.

## Download once, then open without SSH

For the latest **test near the supply's 1 A limit**, download
**`Data/Runs/12t12-source-limit-download.zip`**, extract it, and open
**`report.html`** or **`report.pdf`**. This real run reached about 1.725 A on
the converter output while drawing 0.987 A from the 24 V supply. The archive
also includes CSV results, raw readings, and review records.

For the longer **12T12-4A converter test**, download
**`Data/Runs/12t12-extended-download.zip`**, extract it on your computer, and
open **`report.html`** or **`report.pdf`**. It contains the 50–500 mA sweep,
three-minute hold, return sweep, CSV results, and preserved run evidence.
This is a local checkout artifact, not a file included in a fresh clone.

For the first **12T12-4A real measurement**:

1. In VS Code's Explorer, open `Data/Runs/` in this repository.
2. Right-click **`12t12-first-test-download.zip`** and select **Download**.
3. Save the ZIP on your own computer and extract it.
4. Open **`report.html`** in your browser for the interactive report, or
   **`report.pdf`** for the printable report. The CSV contains the measured data.

Open the extracted HTML file, not its preview inside the ZIP. JavaScript must
be enabled for the interactive graphs. This copy needs no server, port
forwarding or SSH connection. The download is a snapshot; download a new copy
after a report update. These local measurement files are ignored by Git.

## View through VS Code while connected

The Pi's local **NiceGUI bench application uses remote port 8081**. Open `/`
for saved profiles, plan previews, test progress and reports. The existing
`/Runs/...` report URLs still work on that same port. See the
[configured run guide](../dcdc-bench/docs/configured-runs.md) for the supported
hardware workflow and its current limits.

User lingering was enabled on this bench on 27 September 2026, so its user
services can stay running after logout and start at boot. Production test jobs
run in separate bounded services and can continue through a UI restart or SSH
disconnect. The browser still needs a connection to view their progress.
Your computer also needs an SSH tunnel to that port:

1. Connect VS Code to the Pi with **Remote–SSH**.
2. Press **Ctrl+Shift+P**, select **Forward a Port**, and enter **8081**.
3. Open the **Ports** panel. If hidden, run **Ports: Focus on Ports View** from
   the Command Palette.
4. Find remote port **8081** and use its **Forwarded Address**. Append one of:

   - `/` — the local bench application
   - `/Runs/12t12-workflow/report.html` — completed test through the new interface: 24 V input, 100/250/500 mA loads
   - `/Runs/12t12-workflow/report.pdf`
   - `/Runs/12t12-startup/report.html` — start at 15 V, then reduce input toward 9 V at a 100 mA load
   - `/Runs/12t12-startup/report.pdf`
   - `/Runs/12t12-efficiency/report.html` — efficiency at 24 V and near 36 V input
   - `/Runs/12t12-efficiency/report.pdf`
   - `/Runs/12t12-first-test/report.html`
   - `/Runs/12t12-first-test/report.pdf`
   - `/Runs/12t12-extended/report.html` — the longer measured converter test
   - `/Runs/12t12-extended/report.pdf`
   - `/Runs/12t12-source-limit/report.html` — the newer test near the supply limit
   - `/Runs/12t12-source-limit/report.pdf`
   - `/Runs/dcdc-mock-demo/index.html` — the four synthetic DC–DC examples (three load sweeps and the ISO 16750-2 §4.3.1.2 best-effort jump start with its deviation sheet)

For example, if Forwarded Address is `localhost:8083`, the interactive report
is at `http://localhost:8083/Runs/12t12-first-test/report.html`. VS Code may
choose a different local port if 8081 is already occupied; use the address it
actually displays. [VS Code port forwarding documentation](https://code.visualstudio.com/docs/remote/ssh#_forwarding-a-port-creating-ssh-tunnel).

### Remember the port after reconnecting

On **your computer**, open **Settings → User**, search for **Remote: Restore
Forwarded Ports**, and enable it. Equivalently, add this to your local User
`settings.json`:

```json
"remote.restoreForwardedPorts": true
```

VS Code remembers forwarded ports for reconnection. SSH must still be
connected; restoring the setting does not keep a tunnel alive while
disconnected. [VS Code forwarding settings](https://code.visualstudio.com/docs/remote/ssh#_temporarily-forwarding-a-port).

## If the page still fails

- **Connection refused:** check that SSH is connected, remote port 8081 appears
  in **Ports**, and the browser uses its current Forwarded Address. This error
  happens before the browser can request the report file.
- **404 / file not found:** the server is reachable; check the report path,
  including the capital `R` in `Runs`.
- **Standalone static preview on port 8082:** if you started the temporary
  server from the [DC–DC bench README](../dcdc-bench/README.md#try-the-demonstration),
  keep its terminal running and forward 8082 instead. That manual server still
  works independently of the deployed application on 8081. A manually started
  `dcdc-bench ui` also defaults to 8082; choose a free port when using both.

The download option above avoids tunnel interruptions when you only want to
read a finished report.

## Download the three DC–DC examples

In VS Code's Explorer, download **`Data/Runs/dcdc-mock-demo-download.zip`**,
extract it on your computer, and open **`index.html`** in your browser.

The examples show a normal run, a supply reaching its current limit, and an
early stop. Each includes interactive HTML, a matching PDF, CSV results and
the saved acquisition evidence. All three use **simulated instruments**; they
are separate from the real 24 V / 100 mA measurement above. The archive is a
local snapshot created for this checkout, not a file included in a fresh clone.
Use the [demo command](../dcdc-bench/README.md#try-the-demonstration) to create
examples in another checkout.
