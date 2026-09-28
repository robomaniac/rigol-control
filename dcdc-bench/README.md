# DC–DC bench

Configure a converter test, preserve the readings, and produce an interactive
engineering report and a matching vector PDF.

**Status as of 2026-09-27 (branch dcdc-bench-hardening): M0 reached; M1
substantially reached; M2 partial (freshness, readback accuracy and uncertainty
unquantified; enabled-no-load unqualified); an M3 workflow slice demonstrated
(bounded three-point real job through the UI's application services) but M3
not complete by the spec's exit criteria; M4/M5 not started.** The first
profile describes your **12T12-4A: 9–36 V input, 12 V / 4 A output**, with ratings
marked as user supplied. The normal demonstration uses simulated instruments.
A separate, explicitly armed pilot measured the connected converter at
24 V input and 100 mA output. A subsequent fixed test completed a 50–500 mA
sweep, a three-minute hold, and a return sweep at 24 V.
The latest [input-voltage comparison](#efficiency-at-different-input-voltages)
measured 27 load points at 24 V and near 36 V, reaching 2.5 A output.
The separately preserved 12 V startup attempt stopped without a valid efficiency
result; the converter has failed direct 12 V cold-start twice and the cause is
unestablished. The local bench interface runs bounded real recipes for the
reviewed DP821A CH1 / DL3031A setup, with automatic HTML/PDF reports. A bounded
three-point real job completed through the UI's application services and
continued after the client disconnected; a browser-click acquisition is not
claimed. Saved DUT and bench profiles must now carry explicit approvals before
any real plan is feasible. M2 qualification remains the gate before M3 can be
called complete. The older generic CLI `run --mode real` remains disabled.
The complete mock demo produces all three HTML/PDF reports. All 15 mock PDF
pages passed visual review, and the offline browser/PDF gates passed at the
initial checkpoint; on this aarch64 Pi they now run on a laptop or CI. For
current test totals see the branch's final verification record.

## Contents

- [Use the bench interface](#use-the-bench-interface)
- [Start at 15 V, then reduce the input](#start-at-15-v-then-reduce-the-input)
- [Try the demonstration](#try-the-demonstration)
- [What the demonstration does](#what-the-demonstration-does)
- [First real measurement](#first-real-measurement)
- [Longer real converter test](#longer-real-converter-test)
- [Test near the supply limit](#test-near-the-supply-limit)
- [Efficiency at different input voltages](#efficiency-at-different-input-voltages)
- [Profiles and planning](#profiles-and-planning)
- [Evidence and reports](#evidence-and-reports)
- [Architecture and verification](#architecture-and-verification)
- [What comes next](#what-comes-next)

## Use the bench interface

**Select converter → choose voltages and loads → preview limits → Start → watch progress → open HTML/PDF.**

From the parent repository root, install both the existing instrument drivers
and the interface dependencies:

```sh
python -m pip install -e . -e './dcdc-bench[ui,report,real]'
dcdc-bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml
```

The default local URL is `http://localhost:8082`. When the server is on a Pi,
forward that port through SSH. Omit `--inventory` to use simulated equipment.
The report toolchain also needs Quarto/Typst and Chromium, described below.

On this development bench, the persistent service uses the already forwarded
**[port 8081](http://localhost:8081/)** and preserves existing `/Runs/` report links.
Real jobs run in separate services with automatic restart disabled. Browser or
UI-server reconnection does not restart acquisition. **Stop test safely** asks
the worker to switch both outputs off and record the resulting states.

Profiles and job evidence are local and ignored by Git. Each run keeps its own
configuration snapshot. A report-only retry uses those stored measurements.
The current real procedure starts separately at each input voltage; it does
not apply the continuously powered startup sequence described below.

Read the [bench interface guide](docs/bench-ui.md) and
[supported real procedure](docs/configured-runs.md) for limits and deployment.

### Completed test through the interface

The saved 12T12-4A profile was tested at **24 V input** with **100, 250 and
500 mA** output loads. All three points qualified in **57.4 seconds**. The
worker continued after the client disconnected, verified the source, load and
source timer OFF, then automatically generated both report formats.

| Requested load | Output voltage | Path efficiency, including wiring |
| --- | ---: | ---: |
| 100 mA | 12.134 V | 72.65% |
| 250 mA | 12.117 V | 79.12% |
| 500 mA | 12.089 V | 84.19% |

[Interactive report](http://localhost:8081/Runs/12t12-workflow/report.html) ·
[PDF](http://localhost:8081/Runs/12t12-workflow/report.pdf) ·
[Agent-role results review](docs/configured-workflow-results-review.md) ·
[Interface verification](docs/bench-ui-verification.md)

Report figures use standard engineering labels and consistent colors, line
patterns and markers. See [figure terminology and voltage definitions](docs/engineering-figure-labels.md)
for load regulation, line regulation, and the separate meaning of dropout voltage.

This short run verifies the configurable workflow. The wider measured sweeps
and their limits are documented below. Report generation takes several minutes
on this Pi; its **Reporting** state follows acquisition and verified shutdown.

## Start at 15 V, then reduce the input

The connected converter failed the earlier direct 12 V startup. Following the
operator's observation, this test started **unloaded at 15 V**, waited for five
stable output readings, enabled a **100 mA load**, then reduced input through
15, 14, 13, 12, 11, 10 and **9.1 V** without turning the supply off.

All seven conditions produced qualified readings. At measured **12.009 V input**,
the output was **12.134 V at 99.5 mA**. At the lowest measured **9.108 V input**,
it was still **12.134 V at 99.5 mA**. Source, load and the source timer were
verified OFF afterward. The independent audit passed 51 checks.

On the development bench: [interactive report](http://localhost:8081/Runs/12t12-startup/report.html)
· [PDF](http://localhost:8081/Runs/12t12-startup/report.pdf).
These are local results, not public GitHub Pages links.

This demonstrates continued operation after that startup sequence at light
load. It does not determine the cold-start threshold or full-load capability
at low input. See [the measurements and complete method](docs/startup-descent-results-review.md).

## Try the demonstration

Use Python 3.11 or later. From this directory, set up the local environment:

```sh
python3 tools/setup.py
.venv/bin/dcdc-bench demo --out examples/generated
```

On Windows, use `py tools/setup.py`, then
`.venv\Scripts\dcdc-bench.exe demo --out examples/generated`.
The Windows instructions are provided for contributors; release verification
for this increment is on Debian 13 ARM64. A source checkout is required for
the included profiles and templates.

The setup command installs Python dependencies and downloads the pinned official
Quarto release, verifying its published SHA-256. Quarto includes Typst. Static
figures also require Chrome/Chromium. On Debian/Pi, install these system packages
once before setup:

```sh
sudo apt-get install --no-install-recommends chromium-headless-shell poppler-utils
```

The renderer prefers `chromium-headless-shell`, which avoids loading the desktop
browser interface. An installed `chromium` or `google-chrome` also works; set
`BROWSER_PATH` to select another executable. `poppler-utils` is needed for PDF
inspection tests, not acquisition. On a Pi with limited RAM, run rendering and
browser tests sequentially. Acquisition can run
with just `pip install -e .`; the optional `report` dependencies and Quarto can
be installed on a separate computer that receives the run folder.

The 1 GB verification Pi needed **768 MiB of temporary disk swap in addition to
its existing 904 MiB zram swap** while VS Code was connected. The setup script
does not change swap settings. For that configuration, provide the extra memory
before a full document build, or copy the run folder to a computer with more RAM
and use `dcdc-bench report` there. Acquisition is much lighter than rendering.

Open **`examples/generated/index.html`** in a browser after the command completes.
Every report works offline after copying it to your computer. HTML plots need
JavaScript enabled; no Python server is required when opening a local file.

For a report still on the Pi:

```sh
python3 -m http.server 8082 --bind 127.0.0.1 --directory examples/generated
```

In VS Code's **Ports** panel, forward **8082** and open the displayed local URL.
SSH must remain connected while using this tunnel. Download the report to view
it without a tunnel. This server serves static files only.

For this Pi's existing report server on port 8081 and prepared offline bundles, see
[Open a report from the Pi](../Documentation/Viewing-Local-Reports.md): download
the HTML/PDF bundle, restore forwarding, or find the actual local port.

The prepared mock examples are at **`/Runs/dcdc-mock-demo/index.html`** on that
server. To avoid another SSH tunnel, download
**`Data/Runs/dcdc-mock-demo-download.zip`** from the parent project's Explorer,
extract it locally, and open `index.html`. It includes all three reports, PDFs,
CSV results and acquisition evidence. This bundle is local to this checkout;
the demo command creates equivalent examples in a fresh clone.

## What the demonstration does

It asks a simulated supply for **12, 24 and 30 V**, and asks a simulated load to
draw **0, 0.05, 0.1, 0.25, 0.5, 0.75 and 1 A** from the converter output.
At each feasible point it waits for a stable output, records several complete
sets of voltage/current readings, and calculates:

- How much input power reaches the output: **path efficiency**.
- How much power is lost between the measured boundaries.
- How close the output stays to its nominal voltage as load/input changes.
- Input consumption while enabled with no external load.

The planner retains all **21 requested points**. With a 1 A source, an assumed
80% efficiency and a 90% current budget, two 12 V points are excluded by the
planning budget. These assumptions are not measured efficiency or an approved
protective policy.

The command creates three examples:

| Example | What to inspect |
|---|---|
| Normal | Valid acquired points, planning exclusions, graphs and evidence |
| Setup limited | A simulated source enters current limiting; that point cannot support a nominal efficiency claim |
| Aborted | An early stop preserves completed points, unrun points and shutdown evidence |

Use the graph controls to choose input curves and quantities, hover over actual
markers, inspect raw readings, zoom, export CSV/SVG/PNG, and save a view.
**Reset zoom** keeps your selections; **Restore default view** resets them.
The issued summary remains unchanged while you explore. A current-view print
is exploratory; `report.pdf` is the canonical report revision.

## First real measurement

After you confirmed the wiring, polarity and CH1 connection and requested a
live test, the separate supervised pilot ran the **12T12-4A at 24 V input with
a 100 mA output load**. The supply current limit was **150 mA**. It collected
five accepted sets of readings after startup and settling:

| Measurement | Mean reading |
|---|---:|
| Supply voltage | 24.006 V |
| Supply current | 68.84 mA |
| Voltage at the load | 12.136 V |
| Load current | 99.33 mA |
| Input power | 1.653 W |
| Output power | 1.205 W |
| Approximate path efficiency | **72.95%** |

Both the **load input and supply output were verified OFF** at the end.
This is one operating point, not a sweep or a test of the 48 W rating.
The voltage measurements are at the instrument terminals, so the efficiency
includes input and output wiring losses. Current readback uncertainty,
calibration and ADC freshness have not been independently established; the
displayed digits do not imply that level of accuracy.

The local evidence is in
`runs/real-bringup/20260927T061038.184185Z_real_578d4f/`, with derived results in
`analysis/a-5e0e50434006/` inside that folder. Earlier stopped attempts are kept
separately. These run folders are ignored by Git and have not been published.
Your multimeter and front-panel observations are recorded separately from the
automatically acquired samples. Off-state readings were not used to claim
no-load power or efficiency.

## Test near the supply limit

How much can this converter deliver using the existing supply? The real test
increased the output load from **100 mA to 1.725 A**, while the DP821A CH1 stayed
at **24 V with a 1.000 A current setting**. It used smaller load steps near the
supply limit, observed the highest load for **30 seconds**, then checked the
return to 100 mA. Both outputs were verified **OFF** afterward.

At the highest load, the measured means were **0.987 A supply current**,
**1.725 A output current**, and **11.886 V at the load**—about **20.5 W output**.
Its measured path efficiency was **86.5%**. The run completed **22 observation
windows** (21 increasing loads and one direct return to 100 mA) in **6 min 46 s**.
The supply's 1 A input-side limit does not mean a 1 A converter output limit.
This test approaches the bench's available input power; it does not test the
converter's stated 12 V / 4 A rating.

**[Open the interactive report](http://localhost:8081/Runs/12t12-source-limit/report.html)** ·
[PDF](http://localhost:8081/Runs/12t12-source-limit/report.pdf) ·
[Download the complete offline report](http://localhost:8081/Runs/12t12-source-limit-download.zip)

These are local Pi links using your forwarded port. Download and extract the
ZIP to view the report without SSH. Use the local port shown in VS Code if it
differs from 8081. These measured artifacts have not been published to GitHub.

[Procedure and commands](docs/source-limit-test.md) ·
[Actual YAML specification](profiles/recipes/12t12-4a-source-limit.yaml) ·
[Independent measurement review](docs/source-limit-results-review.md) ·
[Code review](docs/source-limit-code-review.md)

The report plots input current separately from output demand, retains the raw
readings, and distinguishes unused conditional load settings from failed
measurements. Dotted lines connect qualified stage boundaries on the time
graph; they add no measured samples. Hover, point inspection and CSV exports
remain available. Efficiency includes wiring losses, and measurement
uncertainty has not been quantified.

## Longer real converter test

The **12T12-4A** completed an **8 minute 24 second** test at **24 V input**:
increase demand from **50 to 500 mA**, hold 500 mA for **185.7 seconds**, then
step back down to 50 mA. It asks whether voltage stays near 12 V, how efficiency
changes with demand, and whether the output returns to a similar value.

**[Test procedure and commands](docs/extended-test.md)** ·
**[Actual YAML specification](profiles/recipes/12t12-4a-extended.yaml)** ·
[Agent-role results review](docs/extended-results-review.md)

On this Pi's forwarded report server:
**[Open the interactive converter report](http://localhost:8081/Runs/12t12-extended/report.html)** ·
[PDF](http://localhost:8081/Runs/12t12-extended/report.pdf) ·
[Offline ZIP](http://localhost:8081/Runs/12t12-extended-download.zip).
Use the actual local port displayed in VS Code's **Ports** panel if it differs.
To read without SSH, download `Data/Runs/12t12-extended-download.zip`, extract
it on your own computer, and open `report.html`.
These links serve local measured artifacts; they have not been published to GitHub.

| Result | Measured observation |
| --- | ---: |
| Completed observation windows | 37 of 37, across 10 distinct load settings |
| Accepted complete reading cycles | 331 |
| Mean output voltage across windows | 12.080–12.139 V |
| Observed path efficiency | 65.06–84.25% |
| Largest mean output power | 6.034 W |
| Voltage change across hold-bin endpoint means | −0.841 mV |
| Voltage difference after returning to 50 mA | −1.748 mV |

Both outputs and the supply's automatic shutoff program were verified **OFF**.
The tiny voltage differences are observations with **unquantified uncertainty**;
they do not establish statistical significance, hysteresis, or thermal equilibrium.
Efficiency includes wiring losses. This is a partial-power test, not qualification
of the 48 W rating. No temperature, ripple, transient, or no-load test was performed.

The successful run is
`runs/real-extended/20260927T093948.075493Z_real_42e971/`.
An earlier attempt stopped safely on host-side query timing; its evidence is
preserved separately. The persistence ordering was corrected without widening
the timing or electrical limits. See the [verification record](docs/extended-verification.md),
[agent-role code review](docs/extended-code-review.md), and
[report UI/UX review](docs/extended-ui-review.md).

## Efficiency at different input voltages

**[Open the interactive efficiency report](http://localhost:8081/Runs/12t12-efficiency/report.html)** ·
[PDF](http://localhost:8081/Runs/12t12-efficiency/report.pdf) ·
[Offline ZIP](http://localhost:8081/Runs/12t12-efficiency-download.zip) ·
[Test YAML](profiles/recipes/12t12-4a-voltage-efficiency.yaml) ·
[Procedure](docs/voltage-efficiency-test.md)

Does the converter waste more power when its input voltage changes? This test
raises the electronic load at each input condition and compares measured output
power with measured input power. Shared load points let you compare the same
output demand. **Teal means 24 V; purple means near 36 V** across every graph.
Hover for readings, hide a voltage curve, or export the selected graph and data.

| Input condition | Path efficiency at 500 mA requested output | Highest qualified output current |
| --- | ---: | ---: |
| 12 V | No qualified result: startup stopped | — |
| 24 V | 84.24% | 1.725 A |
| 36 V nominal, **35.8 V programmed** | 81.99% | 2.499 A |

The upper setting leaves margin below the stated 36 V operating limit. Measured
input was **24.006 V and 35.797 V** at the comparison points; calculations use
those readings. At its highest tested load, the upper-voltage condition delivered
**29.75 W** at **11.904 V**, drawing **0.966 A** from the supply.

The earlier 12 V startup produced about 8 V output with the load disabled, then
stopped when input voltage collapsed to **2.661 V** and input current reached
**1.0005 A**. It produced no qualified efficiency window. Its cause is not
established, and these results do not verify the full stated 9–36 V range.
The continuation did not repeat that startup; both original runs are in the ZIP.

The continuation completed **27 qualified windows and 204 accepted reading
cycles in 428 seconds**, with a **1.000 A supply setting**. Both outputs and the
source timer were verified **OFF**, including a separate query afterward.
Efficiency includes wiring losses. These short DC windows do not establish
thermal equilibrium, measurement uncertainty, or the converter's 4 A rating.

The report has separate equipment model, serial, firmware and manufacturer
columns, aligned DUT tables, and a clearly labeled account of the earlier
startup stop. See the [code review](docs/voltage-efficiency-code-review.md),
[agent-role results review](docs/voltage-efficiency-results-review.md), and
[report UI review](docs/voltage-efficiency-ui-review.md).

These are **local Pi reports**, using the forwarded port shown in VS Code.
Download and extract the ZIP to read without SSH. They are not yet published
GitHub Pages examples.

## Profiles and planning

The four independent inputs are DUT, bench, recipe and report profiles.

- [First DUT](profiles/dut/12t12-4a.yaml)
- [Mock bench](profiles/bench/mock.yaml)
- [Real bench example, blocked from execution](profiles/bench/rigol.example.yaml)
- [Quick 21-point recipe](profiles/recipes/12t12-4a-quick.yaml)
- [Rated-grid request](profiles/recipes/12t12-4a-rated-grid.yaml)

```sh
dcdc-bench plan --dut profiles/dut/12t12-4a.yaml \
  --bench profiles/bench/mock.yaml \
  --recipe profiles/recipes/12t12-4a-quick.yaml --out plan.json
dcdc-bench run --plan plan.json --mode mock --out runs
```

Change the YAML to describe another DUT; no converter-specific Python class is
needed. Unknown tolerances and uncertainty remain unknown. This source cannot
test 48 W output anywhere within 9–36 V: even at 36 V its 1 A input ceiling is
only 36 W. CH2's 8 V maximum is below this DUT's stated minimum.

Explicit voltage/current guards also constrain the plan. Requested points above
those guards are retained with an explanation and skipped. Equality is allowed
by the planning check; it does not establish physical operating headroom or
authorize a real test.

## Evidence and reports

```text
runs/<run_id>/
  request.json, plan.json, run.json, integrity.json
  raw/
    samples.jsonl, events.jsonl, point_events.jsonl
  attachments/manifest.json
  analysis/<analysis_id>/
    analysis.json, points.csv, points.metadata.json
    metrics.json, uncertainty.json, validation.json
  reports/<revision>/
    report_model.json, annotations.json
    report.html, report.pdf, figures/, build_manifest.json
    exports/points.csv, exports/points.meta.json
```

Raw samples carry every field the brief's §8.2 table requires; three use
shorter keys than the brief's wording: `location` (brief: `location_id`),
`measurement_range` (`range_id`) and `query_start_utc` / `query_end_utc`
(`query_started_utc` / `query_completed_utc`). Tools reading `samples.jsonl`
should use the keys as written; existing finalized evidence is not renamed.

Raw evidence is appended during acquisition and hashed at finalization. Analysis
checks those hashes. A formula version changes the analysis ID; rerendering
creates a new report revision. The HTML embeds the data and Plotly runtime.
The PDF is built with Quarto/Typst and vector SVG figures, not screenshots.

Reports retain the declared settling/acquisition policy and observed query
timing separately. Missing phase durations remain unknown. Summary links point
to the same figure registry in HTML and PDF. Selecting an existing analysis
checks its run, evidence hashes, conditions and raw-sample references before
creating a report revision.

New acquisition records include the Git commit, dirty state and source hashes;
missing Git metadata stays unknown. Each new report build records its renderer,
theme and interaction-script hashes. Earlier finalized evidence is preserved.

```sh
dcdc-bench analyze runs/<run_id>
dcdc-bench report runs/<run_id> --formats html,pdf
```

An explicitly requested `--formats html` build is supported. A requested PDF
build with missing tools fails clearly; it does not create a placeholder PDF or
claim success. Acquisition status remains separate from report status.

## Architecture and verification

```text
CLI / local NiceGUI interface → saved profiles → typed plan and confirmation
  → dedicated mock or bounded real worker → append-only evidence
  → pure analysis → shared metrics / figures / report model
  → Quarto HTML + Plotly interaction / Typst vector PDF
```

The configured real backend and the fixed supervised procedures wrap the
existing parent `benchctl` instrument drivers. Acquisition and rendering share
a process lock; reports start after verified shutdown. On this Pi, each UI job
has its own service, so restarting the interface does not restart a test.
The mock pipeline imports no real transport and opens no instruments. The
general `run --mode real` path remains disabled while M2 is incomplete.

The current ordinary suite passed **378 tests**, with 13 browser/PDF tests
deselected. A subsequent focused UI, job and report regression passed **57 tests**;
these overlapping counts are not added. The configured real run passed a
separate **67-check evidence audit**, and the startup/descent run passed 51 checks.
See [interface verification](docs/bench-ui-verification.md) for browser coverage
and the actual UI-callback hardware check.

At an earlier checkpoint, the ordinary suite passed **214 tests**. One complete mock demo command
finished successfully, and each of its three PDFs has five visually reviewed
pages. All **10 browser/PDF gates** also passed: offline operation, actual hover
and controls, data/figure downloads, escaped text, vector PDFs and shared report
identities in the earlier M1 verification. The extended report receives its
own browser/PDF review; those earlier ten gates are not claimed as rerun here.

```sh
python -m pytest tests -m 'not browser and not pdf'
python -m pytest tests -m 'browser or pdf'
```

See [implementation status](docs/implementation_status.md) for executed commands,
platform, acceptance coverage and limitations. The complete
[implementation brief](docs/implementation-brief.md) remains the design contract.

## What comes next

Status as of 2026-09-27 (branch dcdc-bench-hardening): M0 reached; M1
substantially reached; M2 partial; an M3 workflow slice demonstrated but M3 not
complete by the brief's Section 15 exit criteria; M4/M5 not started.

The next bounded task, before any further energizing, is to finish M2
qualification — measurement freshness, useful readback accuracy, an evaluated
uncertainty budget and the physical load's capabilities — and to write the
12 V cold-start hypothesis for the two unexplained 12T12-4A failures.

The NiceGUI bench workflow is implemented for the supported steady-state
procedure, with saved-profile approvals now load-bearing and refresh/reconnect
(RUN-02) covered at the mock/application-services level. Also completed on
this branch: `reports/<rev>/exports/` (issued CSV plus a metadata sidecar) and
a model-driven narrative, so no voltage, current, step, window or DUT-rating
literal remains in the analysis or renderer prose; each sentence reads the
recorded method, plan and DUT profile. Not implemented: the approved UVLO runtime rule
(RUN-09), cross-run comparison (CMP-01/02) and the automated PDF pagination
check (PDF-02). Automatic publication, temperature acquisition and an
image/annotation editor remain future work. For current test totals see the
branch's final verification record. No repository push or report publication
has been performed for this increment. The original project's license has not
been changed or extended by this subproject.
