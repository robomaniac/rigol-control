# DC–DC bench

Configure a converter test, preserve the readings, and produce an interactive
engineering report and a matching vector PDF.

[Start here](#start-here) · [Status](#status) ·
[What it does and what it does not do](#what-it-does-and-what-it-does-not-do) ·
[Use the bench interface](#use-the-bench-interface) · [Try the demonstration](#try-the-demonstration) ·
[More commands](#more-commands) · [Measured results so far](#measured-results-so-far) ·
[Profiles and planning](#profiles-and-planning) · [Evidence and reports](#evidence-and-reports) ·
[Architecture and verification](#architecture-and-verification) · [What comes next](#what-comes-next) ·
[Documentation](#documentation)

## Start here

**New to this repository? Read [Getting started](docs/getting-started.md) first.**
It covers installation, a demo that needs no hardware, the checklist that must be
complete before any real converter test, and the browser workflow, one command
at a time, with what you should see after each.

The short version, from the **repository root** (nothing here touches an instrument):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . -e './dcdc-bench[ui,report,real]'
sudo apt-get install --no-install-recommends chromium-headless-shell poppler-utils
python3 dcdc-bench/tools/setup.py                              # pinned Quarto into dcdc-bench/.tools/ (the dcdc-bench/.venv it also creates is optional)
.venv/bin/dcdc-bench demo --out dcdc-bench/examples/generated  # three simulated reports; run on a laptop if you can
.venv/bin/dcdc-bench ui --root dcdc-bench/workspace            # bench page on http://localhost:8082, simulated bench
```

The `pip` line is the one install for both packages: `benchctl` from the
repository root and the bench with its `ui`, `report` and `real` extras.
`tools/setup.py` is for the pinned Quarto download (and a Playwright Chromium
when no system Chromium is found); the second environment it creates at
`dcdc-bench/.venv` is optional and none of the commands here use it.

A real test additionally needs the private `Software/config/lab.yaml` with both
instrument serials, the three saved approvals in the DUT and bench profiles, a
read-only `dcdc-bench doctor` pass, and a fresh wiring / CH1 / protection /
serial confirmation at every Start; see
[Getting started, section 5](docs/getting-started.md#5-critical-before-any-real-test).
Then start the page with `--inventory Software/config/lab.yaml` and follow
**Select → Preview → Confirm → Start → Stop**. The simulated bench (the default
without `--inventory`) has no Confirm step — **Preview**, then **Start
simulation** — and labels every output SYNTHETIC. On a 1 GB Pi the demo and
report rendering take several minutes and have needed extra swap; acquisition
is light.

## Status

**Status as of 2026-09-28 (branch dcdc-bench-hardening): M0 reached; M1 substantially reached; M2 partial (software side implemented: structured uncertainty budget, read-only `doctor`, outputs-OFF readback-cadence probe; the real bench's freshness, readback accuracy and uncertainty stay unquantified until datasheet/calibration terms are entered and qualified on the bench; enabled-no-load unqualified); an M3 workflow slice demonstrated but M3 not complete by the spec's exit criteria; M4 software implemented on mock and stored data (paired-run comparison, sensor-placement editor with attachment hygiene, synthetic thermal channel with thermal settling) but M4 exit not met (no real temperature adapter; no comparison document rendered); M5 partial (UVLO input-ramp procedure on the synthetic plant only; full-power source, scope tests and public examples not started).**
This position is stated identically in [acceptance coverage](docs/acceptance.md)
and [implementation status](docs/implementation_status.md). The current test
total is the one figure quoted in
[Architecture and verification](#architecture-and-verification) below.

The codes are the milestones of the
[implementation brief, section 15](docs/implementation-brief.md#15-implementation-milestones);
the [glossary](docs/glossary.md#milestones-m0m5) tabulates their exit criteria:

- **M0** — audit and contracts: typed profile and result schemas, the first DUT and mock bench profiles, the feasible-point planner and core constraint tests.
- **M1** — complete mock-to-report path: mock adapters, worker lifecycle, streaming evidence, deterministic analysis and one report template, so one demo command produces standalone HTML and a matching vector PDF without hardware.
- **M2** — supervised real point: adapted drivers validated, the bench protective profile complete, the approved no-load / 24 V / 0.1 A bring-up after explicit authorization.
- **M3** — partial-power sweep and simple UI: the approved small grid, setup limits distinguished from DUT behaviour, reports without manual copying, profile and recipe forms, progress and report access.
- **M4** — comparisons and thermal extension: paired-run comparison, difference plots, photo and sensor annotation, temperature adapters and separate thermal settling.
- **M5** — expanded capability: full-power source profile, reviewed uncertainty improvements, the approved UVLO recipe, scope captures, richer imports and approved public examples.

## What it does and what it does not do

It describes the converter and the bench as data (the first profile describes
your **12T12-4A: 9–36 V input, 12 V / 4 A output**, with ratings marked as user
supplied; another converter is another profile, not a Python class), plans a
grid of input voltages and output loads against explicit capabilities and
guards while retaining every requested point with its reason, acquires settled
DC readings from a deterministic simulated bench (the normal demonstration) or,
when explicitly armed, from the reviewed DP821A CH1 / DL3031A bench through
bounded real recipes, appends the evidence during acquisition and hashes it at
finalization, calculates [path efficiency](docs/glossary.md#measurement-words)
(output power ÷ input power at the instrument terminals, so the losses in both
pairs of leads are inside the number), power loss, regulation and
enabled-no-load consumption with a structured uncertainty budget, and renders
an offline interactive HTML report and a matching vector PDF from one report
model after verified shutdown.

It does not claim a browser-click acquisition: a bounded three-point real job
completed through the UI's application services and continued after the
client disconnected. It energizes nothing without the three saved approvals in
the DUT and bench profiles, a read-only `doctor` pass and a fresh wiring / CH1
/ protection / serial confirmation at every Start; the older generic CLI
`run --mode real` remains disabled. Current readback uncertainty, calibration
and ADC freshness have not been independently established, every efficiency
figure includes input and output wiring losses, and M2 qualification remains
the gate before M3 can be called complete. The available 1 A supply cannot
test the stated 48 W rating anywhere within 9–36 V. Real temperature
acquisition, a real UVLO run, a rendered comparison document and published
measured artifacts are future work.

## Use the bench interface

**Select converter → choose voltages and loads → preview limits → Start → watch progress → open HTML/PDF.**
On the simulated bench — the default when the page starts without
`--inventory` — the button reads **Start simulation** and nothing is confirmed;
on the real bench it reads **Start test on the real bench** and opens
**Confirm the physical setup** before anything is switched on. Both end in
reports labelled **Simulation · synthetic data** or **Real bench · measured**.

From the parent repository root, install both the existing instrument drivers
and the interface dependencies, then start the page:

```sh
python -m pip install -e . -e './dcdc-bench[ui,report,real]'
dcdc-bench ui --root dcdc-bench/workspace --inventory Software/config/lab.yaml
```

The default local URL is `http://localhost:8082`; forward that port through
SSH when the server is on a Pi, and omit `--inventory` to use simulated
equipment. The report toolchain also needs Quarto/Typst and Chromium, described
below. On this development bench, the persistent service uses the already
forwarded **[port 8081](http://localhost:8081/)** *(local bench only; reachable through an SSH port forward)* and preserves existing
`/Runs/` report links. Real jobs run in separate services with automatic
restart disabled; browser or UI-server reconnection does not restart
acquisition, and **Stop…** → **Confirm stop** asks the worker to switch both
outputs off and record the resulting states. The current real procedure starts
separately at each input voltage; it does not apply the continuously powered
startup sequence of the
[15 V start and input descent](docs/measured-results.md#start-at-15-v-then-reduce-the-input).
Report generation takes several minutes on this Pi; its **Reporting** state
follows acquisition and verified shutdown.

Evidence lands under `workspace/`, which is local and ignored by Git: saved
profiles as JSON in `workspace/profiles/<kind>/`, and one folder per job,
`workspace/jobs/<job_id>/`, holding `job.json`, `plan.json`, `request.json`,
`launch.json`, `worker.log`, `resources.jsonl`, a private `inventory.yaml`
for a real job, and the run folder `runs/<run_id>/` laid out as in
[Evidence and reports](#evidence-and-reports). Each run keeps its own
configuration snapshot; a report-only retry uses those stored measurements.
Read the [bench interface guide](docs/bench-ui.md) and the
[supported real procedure](docs/configured-runs.md) for limits and
deployment. Report figures use standard engineering labels and consistent
colors, line patterns and markers; see
[figure terminology and voltage definitions](docs/engineering-figure-labels.md)
for load regulation, line regulation, and the separate meaning of dropout voltage.

## Try the demonstration

Use Python 3.11 or later. From the repository root, after the `pip` line in
[Start here](#start-here):

```sh
sudo apt-get install --no-install-recommends chromium-headless-shell poppler-utils   # Debian/Pi, once
python3 dcdc-bench/tools/setup.py                                                    # pinned Quarto only
.venv/bin/dcdc-bench demo --out dcdc-bench/examples/generated
```

The setup script downloads the pinned official Quarto release into
`dcdc-bench/.tools/`, verifying its published SHA-256 (Quarto includes Typst);
the second environment it creates at `dcdc-bench/.venv` is optional and unused
here. Chrome/Chromium renders the vector figures before both the HTML and the
PDF build (the renderer prefers `chromium-headless-shell`, an installed
`chromium` or `google-chrome` also works, and `BROWSER_PATH` selects another
executable; `poppler-utils` serves the PDF inspection tests, not acquisition).
A source checkout is required for the included profiles and templates. The
Windows commands (from `dcdc-bench/`: `py tools/setup.py`, then
`.venv\Scripts\dcdc-bench.exe demo --out examples/generated`, which use that
optional environment) are provided for contributors; release verification for
this increment is on Debian 13 ARM64.

The demo asks a simulated supply for **12, 24 and 30 V** and a simulated load
for **0, 0.05, 0.1, 0.25, 0.5, 0.75 and 1 A**. At each feasible point it waits
for a stable output, records several complete sets of readings and calculates
path efficiency, the power lost between the measured boundaries, how close the
output stays to nominal as load and input change, and input consumption while
enabled with no external load. The planner retains all **21 requested
points**; with a 1 A source, an assumed 80% efficiency and a 90% current
budget, two 12 V points are excluded by the planning budget. These assumptions
are not measured efficiency or an approved protective policy. Three examples
are produced: **Normal** (valid acquired points, planning exclusions, graphs
and evidence), **Setup limited** (a simulated source enters current limiting;
that point cannot support a nominal efficiency claim) and **Aborted** (an early
stop preserves completed points, unrun points and shutdown evidence).

Open **`dcdc-bench/examples/generated/index.html`** when the command completes. Every
report works offline with JavaScript enabled and no Python server: choose
input curves and quantities, hover the actual markers, inspect raw readings,
zoom, export CSV/SVG/PNG and save a view; **Reset zoom** keeps your selections
and **Restore default view** resets them; the issued summary does not change
while you explore, a current-view print is exploratory, and `report.pdf` is
the canonical report revision. On the 1 GB verification Pi the demo and
rendering take several minutes and needed **768 MiB of temporary disk swap in
addition to its existing 904 MiB zram swap** while VS Code was connected; the
setup script does not change swap settings, so provide that memory first, run
rendering and browser tests sequentially, or copy the run folder to a computer
with more RAM and use `dcdc-bench report` there. Acquisition is much lighter
than rendering and runs with just `pip install -e .`; the optional `report`
dependencies and Quarto can live on a separate computer that receives the run
folder. Step-by-step commands, what to expect from each, and how to serve a
report still on the Pi over a forwarded port are in
[Getting started, section 4](docs/getting-started.md#4-first-run-with-no-hardware);
for this Pi's report server on port 8081 and prepared offline bundles see
[Open a report from the Pi](../Documentation/Viewing-Local-Reports.md). The
prepared mock examples are at `/Runs/dcdc-mock-demo/index.html` on that
server, or download `Data/Runs/dcdc-mock-demo-download.zip` from the parent
project's Explorer and open its `index.html` (all three reports, PDFs, CSV
results and acquisition evidence; local to this checkout, and the demo command
creates the equivalent in a fresh clone).

## More commands

All of these run without instruments except `doctor`, which connects read-only
and never writes to an instrument. None of them energize the converter.

```sh
dcdc-bench compare <runA> <runB> --out <dir>        # pair stored analyses by condition; CMP-01/02
dcdc-bench doctor --bench <bench.yaml> --inventory Software/config/lab.yaml   # read-only identities, states, protections
dcdc-bench doctor --bench <bench.yaml> --inventory ... --readback-cadence --seconds 20  # outputs-OFF readback cadence
dcdc-bench pdf-check <report.pdf>                   # PDF-02 pagination check of an issued document
dcdc-bench publish <run> --revision r0001 --out <dir> --approval approval.yaml  # redacted copy, approval required
dcdc-bench report <run> --annotations annotations.json   # new revision with sensor placement markers
```

The bench UI adds an `/annotations` page for uploading a photograph and placing
sensor markers; saving creates a new report revision and never touches the
acquisition evidence. Mock-only procedures added on this branch are the UVLO
input ramp (`profiles/recipes/12t12-4a-uvlo.example.yaml`, shipped unapproved)
and the thermal recipe (`profiles/recipes/12t12-4a-thermal-mock.yaml`). See
[doctor and publication](docs/doctor-and-publication.md),
[the uncertainty budget](docs/uncertainty-budget.md),
[the Pi process model](docs/pi-process-model.md),
[the cold-start hypothesis](docs/cold-start-hypothesis.md) and
[the M2 qualification plan](docs/m2-qualification-plan.md).

## Measured results so far

<a name="first-real-measurement"></a><a name="longer-real-converter-test"></a><a name="test-near-the-supply-limit"></a><a name="efficiency-at-different-input-voltages"></a><a name="start-at-15-v-then-reduce-the-input"></a><a name="completed-test-through-the-interface"></a>

Every real run so far measured the connected 12T12-4A on the reviewed DP821A
CH1 / DL3031A bench on 2026-09-27 (UTC). Efficiency is path efficiency at the
instrument terminals and includes wiring losses; measurement uncertainty is
unquantified; none of these tests exercises the stated 12 V / 4 A rating. The
full narratives, run-folder paths and local report links are in
[Measured results](docs/measured-results.md); those report links are local to
the owner's bench and need the SSH port forward.

| Date (UTC) | Run | Headline numbers | Review |
| --- | --- | --- | --- |
| 2026-09-27 06:10 | Supervised pilot: 24 V input, 100 mA load, 150 mA supply limit; one operating point | 12.136 V at 99.33 mA; 1.653 W in, 1.205 W out; **72.95%** | No separate review; [narrative and evidence path](docs/measured-results.md#first-real-measurement) |
| 2026-09-27 09:39 | Longer test: 24 V; 50→500 mA ramp, 185.7 s hold at 500 mA, return to 50 mA; 8 min 24 s | 37 of 37 windows, 331 accepted cycles; 12.080–12.139 V; **65.06–84.25%**; −1.748 mV after the return | [Results review](docs/extended-results-review.md) |
| 2026-09-27 17:30 | Near the supply limit: 24 V with a 1.000 A supply setting; load raised from 100 mA to 1.725 A; 22 windows in 6 min 46 s | 0.987 A supply current; **1.725 A at 11.886 V (about 20.5 W)**; **86.5%** | [Results review](docs/source-limit-results-review.md) |
| 2026-09-27 18:49 / 18:56 | Efficiency versus input voltage: the 12 V startup attempt stopped without a qualified result; continuation at 24 V and 35.8 V programmed (near 36 V), 27 windows, 204 cycles, 428 s | At 500 mA: **84.24%** (24 V) and **81.99%** (35.8 V); highest qualified output 2.499 A; 29.75 W at 11.904 V drawing 0.966 A | [Results review](docs/voltage-efficiency-results-review.md) |
| 2026-09-27 21:22 | Start unloaded at 15 V, enable 100 mA, reduce the input through 15 … 9.1 V without switching off; seven conditions | **12.134 V at 99.5 mA** at both 12.009 V and 9.108 V measured input; 51 audit checks passed | [Results review](docs/startup-descent-results-review.md) |
| 2026-09-27 22:38 | Configured three-point run through the bench interface: 24 V; 100, 250 and 500 mA; 57.4 s; worker continued after the client disconnected | 12.134 / 12.117 / 12.089 V; **72.65 / 79.12 / 84.19%** | [Results review](docs/configured-workflow-results-review.md) · [Interface verification](docs/bench-ui-verification.md) |

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
dcdc-bench run --plan plan.json --mode mock --out examples/generated/practice
```

Write practice runs under `examples/generated/` (ignored by Git), as above, or
use the page's simulated bench. Never use `runs/` — the command's default
`--out` — for practice: `dcdc-bench/runs/` holds the project's only copy of the
real measurements, and a simulated run would land beside them.

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
general `run --mode real` path remains disabled while M2 is incomplete. The
module-by-module map, with each module's entry points, forbidden dependencies
and covering tests, is in [Architecture](docs/architecture.md); the
acquisition/report process separation is in [the Pi process model](docs/pi-process-model.md).

Current test total (2026-09-30, `dcdc-bench-hardening` at the end of the simulation review round): the full run `pytest dcdc-bench/tests -m 'not browser and not pdf'` passed **875 tests** with 16 browser/PDF gates deselected on the bench Raspberry Pi 4. That count includes tests parametrised over the Pi's local, git-ignored run folders; a clean clone collects 934 at `b9adf70` (903 in CI's required selection), which is why CI totals are lower than bench totals. This is the one figure to quote; the numbers below are dated checkpoints and are not added together. On 2026-09-28 the ordinary suite passed 653 tests with 15 browser/PDF tests deselected (Raspberry Pi, 478 s); at an earlier checkpoint it passed 378 tests with 13 deselected, and a focused UI, job and report regression passed 57. The configured real run passed a
separate **67-check evidence audit**, and the startup/descent run passed 51 checks.
At the earlier M1 checkpoint the ordinary suite passed **214 tests**, one
complete mock demo command finished successfully with five visually reviewed
pages in each of its three PDFs, and all **10 browser/PDF gates** passed:
offline operation, actual hover and controls, data/figure downloads, escaped
text, vector PDFs and shared report identities. Later reports receive their
own browser/PDF reviews; those ten gates are not claimed as rerun for them.
On this aarch64 Pi the browser/PDF tests now run on a laptop or CI.

```sh
python -m pytest tests -m 'not browser and not pdf'
python -m pytest tests -m 'browser or pdf'
```

See [interface verification](docs/bench-ui-verification.md) for browser
coverage and the actual UI-callback hardware check,
[implementation status](docs/implementation_status.md) for executed commands,
platform, acceptance coverage and limitations, and the
[implementation brief](docs/implementation-brief.md), which remains the design contract.

## What comes next

The milestone position is stated once, in the bold paragraph under [Status](#status).

The next bounded task, before any further energizing, is to finish M2
qualification — measurement freshness, useful readback accuracy, an evaluated
uncertainty budget and the physical load's capabilities — and to act on the written [12 V cold-start hypothesis](docs/cold-start-hypothesis.md) and [M2 qualification plan](docs/m2-qualification-plan.md), which await the owner's review.

The NiceGUI bench workflow is implemented for the supported steady-state
procedure, with saved-profile approvals now load-bearing and refresh/reconnect
(RUN-02) covered at the mock/application-services level. Also completed on
this branch: `reports/<rev>/exports/` (issued CSV plus a metadata sidecar) and
a model-driven narrative, so no voltage, current, step, window or DUT-rating
literal remains in the analysis or renderer prose; each sentence reads the
recorded method, plan and DUT profile. Also on this branch, on mock or stored data only: the UVLO input-ramp procedure (RUN-09), paired-run comparison (`compare`, CMP-01/02), the automated PDF pagination check (PDF-02), a synthetic thermal channel, the attachment store with the `/annotations` sensor-placement editor, the read-only `doctor` command, the approval-gated `publish` command and a memory-safe job/report process model for the Pi. Real temperature acquisition, a real UVLO run and a rendered comparison document remain future work. For the current test total see
[Architecture and verification](#architecture-and-verification) above and the
[implementation status](docs/implementation_status.md). The branch is on
GitHub; pull request #1 merged it into `main` on 2026-09-29, and `main` lags
the branch until the next pull request (see `HANDOFF.md`, sections 3 and 8).
No report has been published. The original project's license has not been
changed or extended by this subproject.

## Documentation

Every file in `docs/` is listed once, with a one-line description, in the
[documentation index](docs/README.md). Start with
[Getting started](docs/getting-started.md); read [Architecture](docs/architecture.md)
before changing the code.
