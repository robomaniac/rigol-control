# Getting started with dcdc-bench

This guide is for an engineer who has never seen this repository. It explains
what the software does, what to install, how to run it with **no hardware**,
what must be true **before** any real converter test, and how to run and read
a real test. Every command below was checked to parse with `--help`; the only
commands that touch instruments are marked **REAL HARDWARE**.

Work from the **repository root** (the folder that contains `dcdc-bench/`,
`Software/` and `pyproject.toml`) unless a step says otherwise.

Contents: [1. What this software does](#1-what-this-software-does) ·
[2. Prerequisites](#2-prerequisites) · [3. Install](#3-install) ·
[4. First run with no hardware](#4-first-run-with-no-hardware) ·
[5. Before any real test](#5-critical-before-any-real-test) ·
[6. Run a real test through the UI](#6-run-a-real-test-through-the-ui) ·
[7. Reading results](#7-reading-results) · [8. Troubleshooting](#8-troubleshooting) ·
[9. Where to read next](#9-where-to-read-next)

## 1. What this software does

1. `dcdc-bench` characterizes a DC–DC converter (the *DUT*) on a bench made of a
   Rigol **DP821A** power supply feeding the converter input from **channel 1**
   and a Rigol **DL3031A** electronic load drawing current from the converter
   output.
2. You describe the converter, the bench limits and the test grid (input
   voltages × output loads) in saved *profiles*; a planner expands every
   requested point and marks it `executable`, `assumption_limited`,
   `unsupported` or `approval_blocked` before anything is powered.
3. A separate worker process then steps through the executable points, waits
   for the output to settle, records time-stamped voltage and current readings
   from both instruments, and verifies that both outputs are OFF at the end.
4. A pure analysis stage computes path efficiency, power loss and output
   regulation from the preserved raw samples, and a renderer produces an
   interactive HTML report plus a matching vector PDF.
5. Everything runs locally on a Linux computer (the development bench is a
   Raspberry Pi) through a command line and a browser page that listens only on
   `localhost`.

What it does **not** do:

- **No hardware is touched until you explicitly arm a real job.** The
  simulated ("mock") bench imports no instrument driver. A real job needs a
  private instrument inventory, approvals saved in the DUT and bench profiles,
  and a fresh confirmation (wiring, CH1, protections, both serial numbers)
  bound to an immutable plan hash. The generic `dcdc-bench run --mode real`
  command is deliberately disabled (`cli.py`); real jobs go through the UI's
  job service or the fixed, explicitly `--arm`ed procedures described in the
  test documents.
- It does not measure no-load consumption, temperature, transients or ripple,
  does not use remote (4-wire) sensing and does not send arbitrary SCPI
  commands from the UI workflow ([configured-runs.md](configured-runs.md)).
- It does not certify measurement accuracy. Until the bench profile carries
  transcribed readback specifications, reports say uncertainty is
  **unquantified** ([uncertainty-budget.md](uncertainty-budget.md)).
- It is not a substitute for instrument protection settings or for a person at
  the bench. Guards are polled DC stop criteria, not transient protection.
- It publishes nothing and has no authentication; the UI binds to loopback and
  is reached through an SSH tunnel.

## 2. Prerequisites

| Item | What is needed | Notes |
| --- | --- | --- |
| Operating system | Linux. Verified: **Debian 13 ARM64 on a Raspberry Pi 3B+** ([implementation_status.md](implementation_status.md), [Pi-Reliability.md](../../Documentation/Pi-Reliability.md)). | Debian/Raspberry Pi OS or Ubuntu on x86_64/ARM64 use the same steps; only the Pi configuration is verified in this repository. Native Windows is **not** supported for hardware control because the instrument transport uses POSIX file locks (root README). The dcdc-bench README gives Windows commands for the *simulated demo only* (`py tools/setup.py`, `.venv\Scripts\dcdc-bench.exe demo --out examples/generated`) and marks them **unverified**. |
| Python | **3.11 or later** (`requires-python = ">=3.11"` in both `pyproject.toml` files). | The verification Pi used Python 3.13.5. |
| git | Any recent version. | |
| System packages | `chromium-headless-shell` and `poppler-utils`. | Chromium renders the static figures for every report build (HTML and PDF). `poppler-utils` is used by PDF inspection tests, not by acquisition. |
| Internet, once | For `pip` and for the pinned Quarto download in step 3.6. | |
| Network to the instruments | Both instruments on the LAN, reachable as VISA resources `TCPIP0::<host-or-ip>::INSTR` ([lab.example.yaml](../../Software/config/lab.example.yaml)). | LXI/VXI-11 Ethernet; the computer carries no load current ([Electrical/Wiring.md](../../Electrical/Wiring.md)). |
| Memory | A laptop is comfortable. A **1 GB Pi is marginal for report rendering**: the verification Pi needed **768 MiB of temporary disk swap in addition to its 904 MiB zram swap** while VS Code was connected (dcdc-bench README). | Acquisition is light; rendering is heavy. A memory gate refuses to render when `MemAvailable` < 150 MiB or `MemAvailable + SwapFree` < 600 MiB. Read [Pi-Reliability.md](../../Documentation/Pi-Reliability.md) and [pi-process-model.md](pi-process-model.md) before rendering on a Pi. |

## 3. Install

1. Clone the repository and enter it.

   ```bash
   git clone https://github.com/robomaniac/rigol-control.git && cd rigol-control
   git checkout dcdc-bench-hardening
   ```

   *What you should see:* a folder containing `dcdc-bench/`, `Software/`,
   `Documentation/`, `Electrical/`, `Data/` and `pyproject.toml`, and
   `git status` reporting `On branch dcdc-bench-hardening`. `main` also has
   the `dcdc-bench/` subproject (pull request #1 merged the branch on
   2026-09-29), but it lags the branch by dozens of commits, so the branch is
   the one to use until the next pull request updates `main`.

2. Check Python.

   ```bash
   python3 --version
   ```

   *What you should see:* `Python 3.11.x` or newer.

3. Create one virtual environment at the repository root.

   ```bash
   python3 -m venv .venv
   ```

   *What you should see:* a new `.venv/` folder (ignored by Git).

4. Install **both** packages into that environment.

   ```bash
   .venv/bin/python -m pip install -e . -e './dcdc-bench[ui,report,real]'
   ```

   Why both: `-e .` installs the parent **`benchctl`** package
   (`Software/src/benchctl`: the Rigol DP800/DL3000 drivers, VISA transport,
   inventory loader and serial verification). `-e './dcdc-bench[...]'` installs
   the bench itself. The extras are: `ui` (NiceGUI page), `report` (Plotly,
   Kaleido, pypdf) and `real`, which simply declares the dependency on
   `benchctl` so the real-hardware path is only usable when both packages are
   in the same environment ([dcdc-bench/pyproject.toml](../pyproject.toml)).

   *What you should see:* pip ends with `Successfully installed ... benchctl-0.1.0 ... dcdc-bench-0.1.0 ...`
   including `nicegui`, `plotly`, `kaleido`, `pyvisa` and `pyvisa-py`.

5. Install the system packages (Debian, Raspberry Pi OS, Ubuntu).

   ```bash
   sudo apt-get install --no-install-recommends chromium-headless-shell poppler-utils
   ```

   *What you should see:* apt installs both packages, or reports they are
   already the newest version.

6. Download the pinned Quarto release with the setup script.

   ```bash
   python3 dcdc-bench/tools/setup.py
   ```

   What it does ([tools/setup.py](../tools/setup.py)): creates a **second**
   environment at `dcdc-bench/.venv` with the `report,test` extras (the
   dcdc-bench README's demo instructions use that one; you can ignore it and
   keep using the root `.venv` from step 3), downloads **Quarto 1.10.18** for
   Linux x86_64/ARM64 or Windows x64 into `dcdc-bench/.tools/` after verifying
   the published SHA-256, and, only if no `chromium-headless-shell`, `chromium`
   or `google-chrome` is on `PATH`, runs `playwright install chromium` and
   writes the browser path to `dcdc-bench/.tools/browser-path.txt`. It never
   connects to instruments and does not change swap settings.

   *What you should see:* the last line `Environment ready. Run ... -m dcdc_bench demo --out .../examples/generated`.
   On an unsupported platform it stops with
   `Install Quarto 1.10.18 from quarto.org and set QUARTO_PATH`; do that
   instead and export `QUARTO_PATH=/path/to/quarto`.

7. Check that each tool is found.

   ```bash
   .venv/bin/dcdc-bench --help
   ```

   *What you should see:* `usage: dcdc-bench [-h] {validate,plan,run,demo,analyze,report,ui,compare,doctor,publish,pdf-check} ...`
   followed by a one-line description of each command. Every subcommand
   answers `--help` with its arguments, their defaults and what it does or
   does not touch (for example `.venv/bin/dcdc-bench run --help` says that
   `--mode real` and `--arm` are refused there). `python -m dcdc_bench --help`
   prints the same text.

   ```bash
   .venv/bin/benchctl --help
   ```

   *What you should see:* `Bench instrument control for Rigol supplies and loads.` with an `identify` subcommand.

   ```bash
   ls dcdc-bench/.tools/quarto-*/bin/quarto
   ```

   *What you should see:* one path such as `dcdc-bench/.tools/quarto-1.10.18/bin/quarto`.
   The renderer looks for Quarto in this order: `QUARTO_PATH`, `quarto` on
   `PATH`, then `dcdc-bench/.tools/quarto-*/bin/quarto` (`reporting/renderer.py`).

   ```bash
   command -v chromium-headless-shell
   ```

   *What you should see:* `/usr/bin/chromium-headless-shell`. The renderer
   prefers `BROWSER_PATH`, then `dcdc-bench/.tools/browser-path.txt`, then
   `chromium-headless-shell`, `chromium`, `google-chrome`.

   ```bash
   command -v pdftotext
   ```

   *What you should see:* `/usr/bin/pdftotext` (from `poppler-utils`).

   ```bash
   .venv/bin/python -m dcdc_bench.resources
   ```

   *What you should see:* a JSON snapshot with `mem_available_mib`,
   `swap_free_mib` and load averages. Note the value of `mem_available_mib`;
   rendering needs at least 150 MiB.

## 4. First run with no hardware

Nothing in this section opens an instrument. The mock bench is a simulated
converter, source and load.

1. Validate a plan from the checked-in profiles (pure planning; instant).

   ```bash
   .venv/bin/dcdc-bench validate --dut dcdc-bench/profiles/dut/12t12-4a.yaml --bench dcdc-bench/profiles/bench/mock.yaml --recipe dcdc-bench/profiles/recipes/12t12-4a-quick.yaml
   ```

   *What you should see:* JSON with `"requested": 21`,
   `"status_counts": {"executable": 19, "assumption_limited": 2}`, a
   64-character `plan_hash` and four warnings starting with
   `Planning estimates are not measurements or validated safety limits.`
   The two `assumption_limited` points are the 12 V / 0.75 A and 1 A requests
   that exceed the 1 A source budget at the assumed 80 % efficiency; they are
   kept in the plan with an explanation and skipped.

2. Generate the three simulated example reports.

   ```bash
   .venv/bin/dcdc-bench demo --out dcdc-bench/examples/generated
   ```

   **Memory and time.** This runs three mock acquisitions and six document
   builds (HTML and PDF each). On the 1 GB verification Pi the three run
   folders were created about **3.5 minutes apart** (run IDs `083115`,
   `083435`, `083852` in [implementation_status.md](implementation_status.md)),
   so budget **10–15 minutes** there, and it needed the 768 MiB of temporary
   swap described in section 2. **Run it on a laptop if you can.** If the
   memory gate refuses, the command exits with code 3 and
   `Not enough free memory to render safely (...)`; nothing is written.
   `--formats html` skips the Typst PDF build but still needs Quarto and
   Chromium, because the static figures are produced for every build.

   *What you should see:* `Mock normal: acquiring and rendering…`,
   `Saved dcdc-bench/examples/generated/normal/<run_id>`, the same for
   `setup-limited` and `aborted`, then `Open: /abs/path/dcdc-bench/examples/generated/index.html`.

3. Open the index in a browser.

   On a laptop, open `dcdc-bench/examples/generated/index.html` directly
   (JavaScript must be enabled; no server is needed). On a Pi reached over SSH:

   ```bash
   python3 -m http.server 8082 --bind 127.0.0.1 --directory dcdc-bench/examples/generated
   ```

   then forward port 8082 (VS Code **Ports** panel, or
   `ssh -L 8082:127.0.0.1:8082 <user>@<pi>`) and open `http://localhost:8082/`.

   *What you should see:* a page titled **DC–DC converter characterization**
   marked **SYNTHETIC — software demonstration only** with three entries, each
   linking an *Interactive report* and a *Canonical PDF*.

4. What the three examples show (dcdc-bench README):

   | Example | What to inspect |
   | --- | --- |
   | Normal test | Valid acquired points, planning exclusions, graphs and evidence |
   | Supply reaches its current limit | A simulated source enters current limiting; that point cannot support a nominal efficiency claim |
   | Test stopped early | An early stop preserves completed points, unrun points and shutdown evidence |

   Each run asks the simulated supply for **12, 24 and 30 V** and the
   simulated load for **0, 0.05, 0.1, 0.25, 0.5, 0.75 and 1 A**. In the HTML,
   hover the markers, choose curves and quantities, zoom, and export CSV/SVG/PNG.
   **Reset zoom** keeps your selections; **Restore default view** resets them.
   `report.pdf` is the canonical report revision.

5. Optional: the same pipeline step by step.

   ```bash
   .venv/bin/dcdc-bench plan --dut dcdc-bench/profiles/dut/12t12-4a.yaml --bench dcdc-bench/profiles/bench/mock.yaml --recipe dcdc-bench/profiles/recipes/12t12-4a-quick.yaml --out plan.json
   ```

   *What you should see:* the same JSON summary as `validate`, and a `plan.json` file.

   ```bash
   .venv/bin/dcdc-bench run --plan plan.json --mode mock --out dcdc-bench/runs
   ```

   *What you should see:* the run directory path `dcdc-bench/runs/<run_id>`
   (exit code 0 when completed, 4 otherwise). `--scenario setup-limited` or
   `aborted` reproduces the other two demo cases. This also renders reports,
   so the memory note above applies.

6. Optional: open the bench page with the simulated bench only.

   ```bash
   .venv/bin/dcdc-bench ui --root dcdc-bench/workspace
   ```

   Without `--inventory` no real bench can start; the button reads **Start
   simulated test**. Section 6 describes the page.

## 5. Critical before any real test

Read this whole section before wiring anything. Each item says *why* it matters
to this software.

1. **Confirm the converter's label and ratings, then fix the DUT profile.**
   The shipped profile [profiles/dut/12t12-4a.yaml](../profiles/dut/12t12-4a.yaml)
   describes a *12T12-4A: 9–36 V in, 12 V / 4 A out* with
   `ratings.origin: user_supplied` and `verified_from_sample_label: false`.
   Compare the sample's label with `input_voltage_min_V`,
   `input_voltage_max_V`, `output_voltage_nominal_V`,
   `output_current_rated_A` and `output_power_rated_W`, and set `sample_id`.
   In the UI, tick **I checked these ratings against the sample label**.
   *Why:* the planner excludes points outside the ratings, and the real worker
   derives its input-voltage hard guards from the rated minimum and maximum
   (`real_backend.py`). Wrong ratings mean wrong guards.

2. **Wire supply CH1 to the converter input and the load to the converter
   output, with both outputs OFF, and check polarity twice.**

   ```text
   DP821A CH1 (+) ── DUT input (+)        DUT output (+) ── DL3031A INPUT (+)
   DP821A CH1 (−) ── DUT input (−)        DUT output (−) ── DL3031A INPUT (−)
   ```

   Only **channel 1** is supported: `prepare_real_plan` rejects any other
   channel, and CH2's 8 V maximum is below this DUT's 9 V minimum (dcdc-bench
   README). [Electrical/Wiring.md](../../Electrical/Wiring.md) shows the
   terminal labelling and protection settings for the direct supply-to-load
   demo; for a converter test the DUT sits between the two instruments.
   *Why:* the software cannot detect reversed polarity or a CH2 connection.
   You will be asked to confirm **Converter input/output wiring and polarity
   are correct** and **The converter input is connected to power-supply
   channel 1** before every Start.

3. **Use local sensing.** The supported wiring is DP821A CH1 with **local load
   sensing**: `remote_sense_required` must be `false` for source and load,
   `Vout_V` is measured at `load_input_terminals_local_sense` and `Iout_A` at
   `load_input` ([configured-runs.md](configured-runs.md), `real_backend.py`).
   Do not enable remote sense on the DL3031A; the doctor reports `:SOUR:SENS?`
   against the profile. *Why:* the measurement boundary is the instrument
   terminals, so **path efficiency includes input and output wiring losses**.
   Use short, adequately sized leads and say so in the test notes.

4. **Create the private inventory `Software/config/lab.yaml` from the
   example; never commit it.**

   ```bash
   cp -n Software/config/lab.example.yaml Software/config/lab.yaml
   ```

   Replace both `.invalid` hostnames with the instruments' addresses
   (`TCPIP0::<host-or-ip>::INSTR`). Then read their identities
   (**REAL HARDWARE, read-only `*IDN?`**):

   ```bash
   .venv/bin/benchctl identify --setup main_bench
   ```

   *What you should see:* a block per device (`psu_rigol_1:`, `load_rigol_1:`)
   listing `resource`, `manufacturer`, `model` (`DP821A`, `DL3031A`), `serial`
   and `firmware`; a device that cannot be reached prints
   `<name>: FAILED (<resource>): ...` and the command exits 1. Put each serial
   into the matching `expected_serial`. The UI requires `psu_rigol_1` with driver
   `rigol_dp800` and `load_rigol_1` with driver `rigol_dl3000`, **both with
   `expected_serial` set**; otherwise the preview shows
   `Private inventory needs psu_rigol_1, rigol_dp800 and its expected serial`
   (`job_service.py`). `Software/config/lab.yaml` is listed in the root
   `.gitignore` because it contains addresses and serials.
   *Why:* every real worker calls `identify_and_verify` and stops with a
   serial mismatch before enabling anything; the UI also makes you type both
   serials at Start.

5. **Set the three saved approvals, and understand what each one asserts.**
   `planning.missing_approvals()` marks every real point `approval_blocked`
   until all three are `true`, and the preview lists what is missing:

   | Field | Where | What you are asserting |
   | --- | --- | --- |
   | `execution_approval.real_hardware_enabled` | DUT profile | This converter profile may be used on real hardware at all. UI: **This converter profile is approved for real hardware**. |
   | `execution_approval.wiring_and_polarity_confirmed` | DUT profile | The wiring plan and polarity for this converter were reviewed. UI: **The wiring plan and polarity for this converter were reviewed**. |
   | `protective_controls.approved` | bench profile | The protective limits saved in the bench profile were reviewed and approved for this bench. UI: **These protective limits were reviewed and are approved for this bench**. |

   The bench the UI seeds for real use, `rigol-local-limited`, ships with
   `approved: false`; the shipped DUT profile ships with both approvals
   `false`. Saved approvals are necessary but not sufficient: each Start still
   needs the fresh confirmation described in section 6.

6. **Review the protective limits and stay inside the reviewed envelope.**
   The bench profile's `protective_controls` are programmed into the
   instruments at the start of each phase by one shared sequence
   (`bringup.RigolPilot`) and are also planning ceilings:

   | Field | Meaning | Accepted by the real backend |
   | --- | --- | --- |
   | `source_current_limit_A` | DP821A CH1 current setting; OCP is set just above it (`min(1.05, 1.1 × limit + 0.005)`) | 0.05–1 A, ≤ saved source capability |
   | `dut_input_overvoltage_V` | DP821A OVP; every requested input must be *below* it | 1–36 V and ≤ DUT maximum input |
   | `dut_output_overvoltage_V` | DL3031A CC voltage limit and output hard guard | > nominal output and ≤ 13.2 V |
   | `output_overcurrent_A` | DL3031A CC current limit and output hard guard | 0.05–2.55 A, ≤ saved load capability |

   The seeded `rigol-local-limited` bench has 1 A source current, **26 V input
   OVP**, 13.2 V output guard, 2.55 A output guard and a 34 W load power
   limit; a request at 35.8 V is therefore `unsupported` until you raise the
   OVP guard deliberately. The full reviewed envelope (programmed input
   1–35.8 V, positive loads 0.05–2.5 A, ≤ 34 W, 5–15 s settling, ≤ 540 s
   planned acquisition, 660 s software deadline, 720 s one-shot source timer
   per input phase) is the table in
   [configured-runs.md](configured-runs.md#current-physical-envelope).
   *Why:* a 4 A rating does not make a 4 A test possible with a 1 A supply;
   the planner keeps such requests visible and skips them.

7. **Run the read-only doctor first (REAL HARDWARE, queries only).**

   ```bash
   .venv/bin/dcdc-bench doctor --bench dcdc-bench/workspace/profiles/bench/rigol-local-limited.json --inventory Software/config/lab.yaml
   ```

   The UI saves profiles as JSON under `dcdc-bench/workspace/profiles/` the
   first time it starts (section 4.6 or 6.1); the CLI loads profiles with a
   YAML parser, which reads that JSON. Point `--bench` at whichever real bench
   profile (JSON or YAML, `mode: real`, benchctl DP800/DL3000 adapters) you
   intend to use; a mock profile is refused with exit 2.

   *What you should see:* JSON with `diagnosis` (the report path, default
   `dcdc-bench/diagnostics/doctor-<utc>.json`), `exit_code`, `summary` and a
   `findings` list. **Exit 0** means no findings. **Exit 4** means findings:
   read each message; typical ones are a serial that differs from
   `expected_serial`, an output that is ON, a tripped OVP/OCP, OTP disabled,
   the source timer not OFF, a non-empty error queue, or
   `protective_controls.approved: false`. **Exit 2** means the doctor refused
   (mock profile, wrong adapters, unreadable inventory). The doctor sends no
   write, never turns anything off and does not clear the error queue
   ([doctor-and-publication.md](doctor-and-publication.md)); that document
   also states the doctor was verified against fake SCPI sessions only, not on
   the physical pair. Fix every finding on the front panels before continuing.

8. **Keep the physical disconnect within reach and stay at the bench.** Every
   recipe carries `allow_unattended: false` and `require_operator_arming:
   true`; the Start confirmation includes **I reviewed these limits and will
   supervise the run**. Software cleanup can fail on a connection, identity,
   process or power fault ([Electrical/Wiring.md](../../Electrical/Wiring.md)),
   and a disconnected browser or SSH session must never be read as "outputs
   OFF" ([bench-ui.md](bench-ui.md)). Never leave a real run unattended.

9. **Make sure the host is ready.** Check memory (`free -m`,
   `.venv/bin/python -m dcdc_bench.resources`), close browsers and editors you
   do not need, and confirm no other job or renderer is running
   (`pgrep -af 'dcdc_bench|quarto|chromium'`; with the systemd launcher,
   `systemctl --user list-units 'dcdc-job-*' --all --no-pager` should show 0
   units). Acquisition and rendering share one exclusive lease and fail
   closed when it is busy ([pi-process-model.md](pi-process-model.md)).

## 6. Run a real test through the UI

1. Start the page with the private inventory.

   ```bash
   .venv/bin/dcdc-bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml
   ```

   Defaults: host `127.0.0.1`, port **8082**, workspace `dcdc-bench/workspace`
   (ignored by Git). On the development Pi a persistent service already serves
   the same page on **8081** with the saved `/Runs/...` reports
   ([Pi-Reliability.md](../../Documentation/Pi-Reliability.md)); do not start a
   second copy on that port. For a persistent deployment, set
   `Environment=DCDC_JOB_LAUNCHER=systemd` in the service so every job runs
   as its own transient user unit and survives UI restarts and SSH drops
   ([configured-runs.md](configured-runs.md#surviving-ui-and-ssh-disconnects)).

   *What you should see:* NiceGUI startup lines ending with the listening
   address; the process stays in the foreground.

2. Forward the port from your computer.

   VS Code Remote-SSH: **Ports → Forward a Port → 8082**, then open the
   *Forwarded Address*. Without VS Code:

   ```bash
   ssh -L 8082:127.0.0.1:8082 <user>@<pi-hostname>
   ```

   *What you should see:* `http://localhost:8082/` shows **DC–DC Bench** as one
   page: **1 Which converter?**, **2 Simulated or real bench?**, **3 Which
   test?**, a **Run** section, **Reports**, and a bar fixed to the bottom with
   **Preview** and **Start**. A forward only reaches a running server; it does
   not start one
   ([Viewing-Local-Reports.md](../../Documentation/Viewing-Local-Reports.md)).

3. **Select.** Click the converter card; if it says *Not yet approved for the
   real bench*, choose **Edit**, tick the label check and the two approvals
   under **Real-bench approval for this converter**, and **Save converter**.
   Click the **Real bench** tile, then the **24 V converter tests** preset pill
   (`rigol-local-limited`); check the four protective limits in the small table
   and tick **I reviewed these limits — required once**. Click the **24 V small
   grid — 0.1 / 0.25 / 0.5 A** card (`real-24v-small-grid`: 24 V; 0.1, 0.25,
   0.5 A; 8 s per load), or **+ New test** and type your own comma-separated
   **Input voltages (V)** and **Output loads (A)**. Every voltage is paired
   with every load. The summary line and the bottom bar show the three choices.

4. **Preview.** Click **Preview** in the bottom bar.

   *What you should see:* a **Plan** panel with *Points that will run*
   `n / total`, *Skipped* with the grouped reasons, *Estimated time*, *Bench:
   Real — DP821A CH1 + DL3031A*, the limits line, and in red a **Before Start**
   list if anything blocks a real start (approvals, inventory, unsupported
   settings). Every requested point is listed with its **Plan** status and
   **Reason** under *All requested points and planning notes*. Excluded points
   stay in the saved plan and are skipped. Preview never enables an output.
   Changing any of the three selections marks the plan stale. Write the setup
   in **Notes for the report**; they appear as operator observations.

5. **Confirm.** Click **Start test on the real bench**. Under **Confirm the
   physical setup**, tick the three boxes and type both serial numbers exactly
   as configured (each field shows `configured: <serial>` from your inventory).

   *What you should see:* Start itself is enabled only when the preview has no
   errors and no other job is active; **Switch on and start** becomes enabled
   only when all boxes are ticked and both serials match.

6. **Start.** Click **Switch on and start** once. The service rebuilds the plan from
   the saved profiles, re-runs every real-plan check, verifies the inventory
   hash, takes the bench lease and launches a dedicated worker. The worker
   verifies both `*IDN?` serials against the inventory and the models against
   `DP821A`/`DL3031A`, switches both outputs OFF, programs the protections,
   proves an unloaded startup, then enables the load.

   *What you should see:* the header pill shows **Acquiring… point n of m**
   with the local start time and elapsed time, the three questions are locked,
   and the **Run** section moves through **Waiting to start →
   Acquiring measurements**, with `n / m load points accepted`, the requested
   input and load, live **Measured input / Supply current / Measured output /
   Load current**, **Stage**, **Elapsed seconds**, **Last measurement age (s)**
   and **Supply mode**. Live values are unqualified readings; the report applies
   qualification.

7. **Stop** (if needed). Click **Stop…** at the far right of the header, then
   **Confirm stop** (or **Keep running**). The worker performs its bounded
   cleanup and records the resulting states.

   *What you should see:* `Stop requested — waiting for the worker` in the
   header, *Stop requested: <local time>* in the Run section, then either
   **Supply output and electronic load are verified OFF.** or **Output shutdown
   is not fully verified. Check the instruments before touching the wiring.**
   Do not touch the wiring until you see the first message and have looked at
   the front panels. Closing the tab does not stop a test; reopening the page
   reattaches to it.

8. **Wait for the reports.** After acquisition the worker verifies source, load
   and the source timer OFF and exits; the job shows **Measurements saved —
   report queued**. The page's 2 s dispatcher launches a separate report-only
   process when **no job is active**, the bench lease is free **and** the
   memory gate passes (`MemAvailable` ≥ 150 MiB and `MemAvailable + SwapFree`
   ≥ 600 MiB by default). Otherwise the card shows `Waiting: <reason>`, for
   example `MemAvailable below 150 MiB`, and re-checks every 2 s. A new test may
   be started while reports are queued; acquisition has priority. Rendering
   takes several minutes on a Pi.

   *What you should see:* **Preparing HTML and PDF**, then **Complete** with
   links **Open interactive HTML**, **Open PDF** and **Report data JSON**.

9. **Find the evidence on disk.** Each job is one folder:

   ```text
   dcdc-bench/workspace/jobs/<job_id>/
     job.json, plan.json, request.json, launch.json, worker.log, resources.jsonl
     inventory.yaml                      private copy for this job (mode 0600)
     runs/<run_id>/
       request.json, plan.json, run.json, integrity.json, scpi.jsonl
       raw/samples.jsonl, raw/events.jsonl
       analysis/<analysis_id>/analysis.json, points.csv, metrics.json, uncertainty.json, validation.json
       reports/<rev>/report.html, report.pdf, report_model.json, build_manifest.json,
                     figures/, exports/points.csv, exports/points.meta.json
   ```

   Raw evidence is appended during acquisition and hashed in `integrity.json`;
   analysis and reports get their own identifiers and never rewrite it.

10. **Retry a report** without powering the converter again. On a finished job
    whose HTML or PDF failed, the Run section shows **Report generation needs
    attention: PDF. Saved measurements are preserved.** and the job's row in
    **Reports** offers **Regenerate report**; it queues a report-only worker (`report-queued`) and
    writes a new revision `rNNNN`. From a terminal, on this or another
    computer that has the run folder and the report tools:

    ```bash
    .venv/bin/dcdc-bench report dcdc-bench/workspace/jobs/<job_id>/runs/<run_id> --formats html,pdf
    ```

    *What you should see:* the new revision directory path. Copying a run
    folder to a laptop and rendering there is the recommended way to avoid
    memory trouble on a 1 GB Pi.

## 7. Reading results

- **Path efficiency** is measured output power divided by measured input power
  at the **instrument terminals**: `Vin`/`Iin` at the DP821A output and
  `Vout`/`Iout` at the DL3031A input with local sensing. The reported number
  therefore **includes input and output wiring losses**; it is not
  converter-terminal efficiency (`measurement_boundary` in each run,
  [engineering-figure-labels.md](engineering-figure-labels.md)). The other
  figures are **Load Regulation**, **Input Current** and **Power Loss**.
- **"Uncertainty unquantified"** means no readback uncertainty budget was
  evaluated: the bench profile's `readback_specification` terms are `unknown`
  until the bench owner transcribes the readback (not programming) accuracy for
  the exact model and range from the datasheets and records the calibration
  status ([uncertainty-budget.md](uncertainty-budget.md),
  [profiles/bench/rigol.example.yaml](../profiles/bench/rigol.example.yaml)).
  Displayed digits are analysis precision, not accuracy. Small differences
  between points do not establish significance, hysteresis or thermal
  equilibrium.
- **HTML**: open `report.html` offline with JavaScript enabled; hover markers,
  choose curves, zoom, inspect raw readings, export CSV/SVG/PNG. **PDF**:
  `report.pdf` is the canonical revision, built with Quarto/Typst from vector
  figures. `build_manifest.json` records tool versions, the memory-gate verdict
  and a `pdf_check` result.
- **CSV**: `reports/<rev>/exports/points.csv` with `points.meta.json`
  describing the columns; the analysis folder also holds `points.csv`,
  `metrics.json` and `uncertainty.json`.
- **Compare two runs** (reads run folders only; commands no instrument):

  ```bash
  .venv/bin/dcdc-bench compare <run_a> <run_b> --out comparisons/a-vs-b
  ```

  *What you should see:* the output folder path containing
  `comparison_model.json`, `comparison.md` and `figures/*.plotly.json`. Points
  are paired only when test id, requested input voltage (±0.01 V) and requested
  load (±0.001 A) match and both are `valid`; differences are **B − A** in
  percentage points; resolvability is evaluated only when both analyses carry
  an evaluated uncertainty budget (`comparison.py`).
- **Check a PDF**:

  ```bash
  .venv/bin/dcdc-bench pdf-check dcdc-bench/workspace/jobs/<job_id>/runs/<run_id>/reports/<rev>/report.pdf
  ```

  *What you should see:* a JSON result; exit code 4 when `status` is `fail`.

## 8. Troubleshooting

| Symptom | Meaning | Check |
| --- | --- | --- |
| Preview shows red lines starting `Real execution is blocked by saved-profile approvals: DUT profile execution_approval.real_hardware_enabled is false; ...` | One or more of the three approvals in section 5.5 is false. | Tick the approval boxes on **DUT and recipe** and **Bench**, then preview again. |
| Points listed as `unsupported` with reasons such as `only loaded 0.05–2.5 A observations are supported`, `output exceeds the supported 34 W envelope`, `input request must be below source OVP`, or an error `Estimated acquisition N s exceeds the 540 s planning budget; split the recipe` | The request is outside the real backend's envelope. | Compare with [configured-runs.md](configured-runs.md#current-physical-envelope); shrink the grid, raise the OVP guard deliberately, or split the recipe. |
| `Configure the private bench inventory before a real run` or `Private inventory needs psu_rigol_1, rigol_dp800 and its expected serial` | The UI was started without `--inventory`, or `lab.yaml` lacks the device names, drivers or serials. | `Software/config/lab.yaml`; restart the UI with `--inventory`. |
| `Confirmed instrument serials do not match the preview` / `Instrument confirmation does not match the saved inventory` | The typed serial differs from `expected_serial`. | Copy the serial shown as `... serial number configured:` exactly. |
| Job fails early with `serial mismatch for 'source': expected ..., got ...` or `This backend requires the verified DP821A model` | The instrument at the configured address is not the one in the inventory. | `dcdc-bench/workspace/jobs/<job_id>/worker.log` and `runs/<run_id>/raw/events.jsonl`; re-run `benchctl identify --setup main_bench`. |
| `A job is already acquiring or reporting; no automatic hardware queue` or `Bench is busy acquiring or rendering; retry explicitly after it finishes` | Another job holds the exclusive activity lease (`dcdc-bench/runs/.bench-activity.lock` unless `DCDC_ACTIVITY_LOCK` is set). | **Reports** for an active job; `pgrep -af dcdc_bench`, `pgrep -af quarto`, `pgrep -af chromium`; `systemctl --user list-units 'dcdc-job-*' --all --no-pager`. |
| The Run section stays at **Measurements saved — report queued** with `Waiting: MemAvailable below 150 MiB` (or the `+ SwapFree` variant, or `bench lease held`) | The dispatcher's memory gate or lease check refused; measurements are safe. | `free -m`, `.venv/bin/python -m dcdc_bench.resources`, `tail dcdc-bench/workspace/resource-log.jsonl`. Free memory (close VS Code/browsers), add temporary swap per [Pi-Reliability.md](../../Documentation/Pi-Reliability.md), or copy the run to a laptop and run `dcdc-bench report`. `DCDC_RENDER_MIN_AVAILABLE_MIB`/`DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB` change the thresholds (both `0` disables the gate; the kernel on the Pi boots with `cgroup_disable=memory`, so nothing else protects the host). |
| `dcdc-bench report` exits 3 with `Not enough free memory to render safely (...)` | Same gate, from the CLI; nothing was written. | As above. |
| Job ends **Needs attention** with `Acquisition preserved; report generation failed. See worker.log and build manifest.` | Rendering failed after a good acquisition. | `worker.log` and `runs/<run_id>/reports/<rev>/build_manifest.json` (`status`, `artifacts`, `resource_usage`); then **Regenerate report** in **Reports**. |
| PDF artifact status `failed-validation` in `build_manifest.json` (Run section: `Report generation needs attention: PDF`) | The PDF was produced but failed the pagination check (PDF-02). | `dcdc-bench pdf-check <report.pdf>` prints the findings; the HTML remains usable; retry after fixing. |
| `Quarto is unavailable. Install the reporting tools or set QUARTO_PATH.` | No Quarto found. | `ls dcdc-bench/.tools/quarto-*/bin/quarto`; re-run `python3 dcdc-bench/tools/setup.py` or set `QUARTO_PATH`. |
| Static figures fail or the browser is not found | No Chromium found. | `command -v chromium-headless-shell`; install it or set `BROWSER_PATH`. |
| `dcdc-bench: missing optional dependency (...); install the report extra and renderer tools` (exit 3) | Extras were not installed in this environment. | Repeat step 3.4 with the same `.venv`. |
| `Worker launch expired before acquisition; no automatic restart` or `Worker exited unexpectedly; inspect shutdown evidence before another real run` | The worker did not start within 120 s, or died. | `worker.log`, `launch.json`; look at the front panels before wiring changes; with systemd, `journalctl --user -u dcdc-job-<job_id>-*`. |
| Browser says connection refused | The tunnel or server is not there. | The **Ports** panel shows the remote port and its *Forwarded Address*; the `dcdc-bench ui` terminal is still running; use `--port` if 8082 is taken. |

## 9. Where to read next

- [bench-ui.md](bench-ui.md) — the bench page, port forwarding, reconnect behaviour.
- [configured-runs.md](configured-runs.md) — the supported real procedure, its envelope, the systemd launcher and saved evidence.
- [doctor-and-publication.md](doctor-and-publication.md) — what `doctor` reads, the readback-cadence probe, and the approval-gated `publish` command.
- [pi-process-model.md](pi-process-model.md) — acquisition/report process separation, the memory gate, logs and the steady-state check.
- [Documentation/Pi-Reliability.md](../../Documentation/Pi-Reliability.md) and [Documentation/Viewing-Local-Reports.md](../../Documentation/Viewing-Local-Reports.md) — the development Pi, temporary swap, lingering, and opening saved reports.
- [implementation_status.md](implementation_status.md) and [acceptance.md](acceptance.md) — what is verified, what is open, and the current milestone position.
- [engineering-figure-labels.md](engineering-figure-labels.md) and [uncertainty-budget.md](uncertainty-budget.md) — how to read the figures and what the uncertainty budget needs.
- [implementation-brief.md](implementation-brief.md) — the design contract the code follows.
- [Software/README.md](../../Software/README.md), [Documentation/Architecture.md](../../Documentation/Architecture.md) and [Electrical/Wiring.md](../../Electrical/Wiring.md) — the parent `benchctl` drivers, their control boundaries and the bench wiring/protection settings.
