# Rigol Bench Control

Check whether a power supply and its connecting wires deliver enough voltage
for a circuit. A Rigol electronic load stands in for the circuit, letting you
repeat the same test without connecting a real board. Run it from a Raspberry
Pi or Linux computer and inspect the results in an offline HTML report.

**Status:** working bench prototype · **Python:** 3.11+ · **Verified bench:** DP821A + DL3031A

[Open the real 5 V power test](05_Data/power-test-report.html) · [Measured CSV](05_Data/power-test-results.csv) · [Simulated example](05_Data/sweep-preview.html) ·
[Demo YAML](08_Software/recipes/load_sweep.yaml) · [Wiring](01_Electrical/Wiring.md)

![Measured supply-to-load voltage difference](04_Media/demo-load-sweep.svg)

This original three-point chart is a measured snapshot from the bench. The
new measured report contains 21 loaded readings plus a starting reference.
See [data provenance](05_Data/README.md) for which run each artifact contains.
GitHub displays the SVG directly; download the HTML report and open it in a
browser to use its controls.

## Start here

You can open the saved reports without installing anything or connecting hardware.
The **real 5 V power test** contains 22 readings from the DP821A and DL3031A.
The separate simulated example illustrates the same display with invented values.
Move over a chart for readings, use the point slider or arrow keys to follow the
run, search the measurement table, or download its full-precision CSV.
The current overview follows the reading numbers, so you can see demand rise
and then fall. The other graphs compare results at the same current; their
outward and return traces sit beside each other.

To run the software, work from the **repository root**:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp -n 08_Software/config/lab.example.yaml 08_Software/config/lab.yaml
```

The local `lab.yaml` is ignored by Git. Replace its two `.invalid` hostnames
with your instruments' addresses. Read their identities, then put the returned
serials in `expected_serial` to pin subsequent commands to those instruments:

```bash
benchctl identify --setup main_bench
```

Serial pinning is optional in the schema; an unset serial does **not** block
control commands. Set both before using the bench. The example uses operating
limits for this 5 V demo, not the instruments' full ratings.

Validate the complete sweep without contacting hardware:

```bash
benchctl run 08_Software/recipes/load_sweep.yaml --setup main_bench --dry-run
```

For a completely offline first check, add
`--config 08_Software/config/lab.example.yaml` to that command.

## Demo: will your circuit still receive 5 V?

Imagine a small circuit that needs 5 V and draws between 50 and 300 mA.
Before connecting it, we can check the supply and wires using the electronic
load as a stand-in. The load draws the current we ask for, just as the circuit
would. At 5 V, 50 mA is about 0.25 W and 300 mA is about 1.5 W.

**The useful question:** when the circuit asks for more current, does enough
voltage still reach its end of the wires?

### What happens during the test

1. Set the supply to **5 V** and measure it before the load draws current.
2. Ask the load to draw **50 mA**, wait four seconds, and measure voltage at
   both the supply and the load.
3. Repeat in **25 mA steps up to 300 mA**, then work back down to 50 mA.
4. Check the readings and turn the load and supply output off.

That is 21 loaded readings at 11 current levels, plus the starting reference.
The load briefly turns off between levels while its setting changes, with a
half-second pause before enabling it again. This checks settled voltage; it does not capture fast dips during a sudden change.
Allow roughly two minutes, including communication with the instruments.

For this example, we choose **4.75–5.25 V** as the acceptable range for a 5 V
circuit. Use the voltage range required by your own circuit when adapting it.
This is a chosen test limit, not a claim of USB certification.

### What the result tells you

| Result | What it helps you check |
| --- | --- |
| Lowest voltage at the device end | Did enough voltage reach the circuit throughout the test? |
| Voltage at the supply | Did the source itself hold its voltage as demand increased? |
| Difference between the two readings | Are the wires or contacts worth investigating? Instrument offsets also contribute. |
| Readings while reducing demand | Do repeated current levels give similar results? |

For example, a reading named **“250 mA · Reducing demand”** means the load is
asking for 250 mA on the way back down. Its voltage is what a circuit would
receive at that point. The report keeps raw file identifiers in the exported
data so the main view can use these readable descriptions.

**Why two graph shapes?** The current overview uses reading number on its
horizontal axis: reading 1 is the starting reference, reading 12 reaches
300 mA, and reading 22 returns to 50 mA. That makes a rise-and-fall shape.
The voltage and power graphs use current on the horizontal axis, with rounded
mA tick marks. Returning to 250 mA puts a reading back at the same horizontal
position as the earlier 250 mA reading. This makes the two directions easy to
compare. Tick labels are rounded; the saved readings retain their precision.

### Real bench result

The [measured 21-point test](05_Data/power-test-report.html) passed on
26 September 2026 UTC. Voltage at the device stayed between **4.978736 and
4.989864 V**, within the chosen 4.75–5.25 V range. The largest difference between
the supply and device readings was **26.264 mV**. Peak measured demand was
**299.28 mA**, using **1.490034 W**.

The run took about **105 seconds**. All acceptance checks passed; a separate
readback afterward confirmed both the load input and CH1 output were off.
The [original three-point report](05_Data/demo-report.html) and chart remain
available, and the [simulated example](05_Data/sweep-preview.html) stays separate.

### Connect and run

With both outputs off, connect CH1 positive to load positive and CH1 negative
to load negative. Follow the [wiring and protection settings](01_Electrical/Wiring.md).
The supply allows **up to 500 mA**; this demo requests at most **300 mA**.
The current limit is a ceiling, not a current forced into the load.
The recipe attempts to turn the load off, then CH1 off when execution exits.
Configure the instruments' hardware protection settings separately.

The actual runnable script is
[08_Software/recipes/load_sweep.yaml](08_Software/recipes/load_sweep.yaml):

```yaml
# 5 V power delivery test: does enough voltage reach a device as demand rises?
# The electronic load stands in for a device, drawing 50 to 300 mA in 25 mA
# steps, then reducing demand. We measure voltage at both ends of the wires.
# There are 21 loaded readings at 11 current levels, plus an unloaded reference.
# This demo accepts 4.75–5.25 V; choose bounds appropriate for your own circuit.
# Check wiring/protection settings first. The load briefly turns off between
# readings, so this checks settled voltage rather than fast changes in demand.
# Run from the project root; report with: benchctl report --latest load_sweep
schema_version: 1
name: load_sweep

requires:
  supply: {kind: power_supply}
  load: {kind: electronic_load}

parameters:
  supply_channel: 1
  voltage_v: 5.0
  current_limit_a: 0.50
  load_start_a: 0.05
  load_stop_a: 0.30
  load_step_a: 0.025
  load_tolerance_a: 0.02
  supply_tolerance_a: 0.03
  min_acceptable_voltage_v: 4.75
  max_expected_voltage_v: 5.25
  max_load_power_w: 2.0
  configure_settle_s: 0.5
  settle_s: 4.0

steps:
  # Start from a known off state before changing either instrument's settings.
  - action: load.input_off
  - action: supply.output_off
    channel: "${parameters.supply_channel}"
  - action: supply.configure
    channel: "${parameters.supply_channel}"
    voltage_v: "${parameters.voltage_v}"
    current_limit_a: "${parameters.current_limit_a}"
  - action: supply.output_on
    channel: "${parameters.supply_channel}"
  - action: wait
    seconds: "${parameters.settle_s}"

  # Baseline for voltage droop: load input is still off.
  - action: measure
    save_as: no_load
    values:
      supply_voltage_v:
        source: supply.voltage
        channel: "${parameters.supply_channel}"
        expect: {min: "${parameters.min_acceptable_voltage_v}", max: "${parameters.max_expected_voltage_v}"}
      supply_current_a:
        source: supply.current
        channel: "${parameters.supply_channel}"
        expect: {min: 0.0, max: 0.03}
      supply_power_w: {source: supply.power, channel: "${parameters.supply_channel}"}

  # The parser expands and validates every point before contacting hardware.
  # Keep the load off while changing CC setpoints. Each enable also checks
  # measured voltage/current/power before waiting for the final reading.
  - action: sweep
    start: "${parameters.load_start_a}"
    stop: "${parameters.load_stop_a}"
    step: "${parameters.load_step_a}"
    return_to_start: true
    steps:
      - action: load.input_off
      - action: load.configure_cc
        current_a: "${sweep.value}"
        max_voltage_v: "${parameters.max_expected_voltage_v}"
      # Allow the instrument to finish changing mode/current before enabling.
      - action: wait
        seconds: "${parameters.configure_settle_s}"
      - action: load.input_on
      - action: wait
        seconds: "${parameters.settle_s}"
      - action: measure
        save_as: "point_${sweep.index}_${sweep.value}_a"
        values:
          supply_voltage_v:
            source: supply.voltage
            channel: "${parameters.supply_channel}"
            expect: {min: "${parameters.min_acceptable_voltage_v}", max: "${parameters.max_expected_voltage_v}"}
          supply_current_a:
            source: supply.current
            channel: "${parameters.supply_channel}"
            expect: {target: "${sweep.value}", tolerance: "${parameters.supply_tolerance_a}"}
          supply_power_w: {source: supply.power, channel: "${parameters.supply_channel}"}
          load_voltage_v:
            source: load.voltage
            expect: {min: "${parameters.min_acceptable_voltage_v}", max: "${parameters.max_expected_voltage_v}"}
          load_current_a:
            source: load.current
            expect: {target: "${sweep.value}", tolerance: "${parameters.load_tolerance_a}"}
          load_power_w:
            source: load.power
            expect: {min: 0.0, max: "${parameters.max_load_power_w}"}

finally:
  - action: load.input_off
  - action: supply.output_off
    channel: "${parameters.supply_channel}"
```

After checking wiring, hardware limits and your local inventory:

```bash
benchctl run 08_Software/recipes/load_sweep.yaml --setup main_bench
benchctl report --latest load_sweep
```

The first command prints the run directory; the second prints the HTML file to
open. `report` only reads saved files. Every sweep point is expanded and checked
against the configured limits **before** an instrument connection opens.

### Actual files from the demo

The successful run produced the files below. Open the
[complete example run](05_Data/Example_Run/20260926T072124Z_load_sweep/) to inspect
the actual records from the **50 → 300 → 50 mA** test:

```text
05_Data/Example_Run/20260926T072124Z_load_sweep/
├── run.json
├── execution.jsonl
├── measurements.jsonl
├── measurements.csv
├── report.html
└── postflight.json
```

| File | What you will find |
| --- | --- |
| [run.json](05_Data/Example_Run/20260926T072124Z_load_sweep/run.json) | Test settings, start/end times, instrument models, and the final `pass` result. |
| [execution.jsonl](05_Data/Example_Run/20260926T072124Z_load_sweep/execution.jsonl) | Each action in order: change current, enable the load, wait, measure, and shut down. |
| [measurements.jsonl](05_Data/Example_Run/20260926T072124Z_load_sweep/measurements.jsonl) | All 22 readings, including the limits checked and each reading's result. |
| [measurements.csv](05_Data/Example_Run/20260926T072124Z_load_sweep/measurements.csv) | Those readings and checks in a spreadsheet-friendly table. |
| [report.html](05_Data/Example_Run/20260926T072124Z_load_sweep/report.html) | The interactive graphs and results, generated from these files. |
| [postflight.json](05_Data/Example_Run/20260926T072124Z_load_sweep/postflight.json) | The separate check confirming CH1 and the load input were off afterward. |

`JSONL` means one JSON record per line. This is a shareable copy of the real
run: instrument serial numbers are redacted; measurements and action records
are preserved. `postflight.json` was added by the separate shutdown check; the
normal recipe runner creates the other data files, and `benchctl report`
creates the HTML.

You can regenerate this example's report **without connecting instruments**:

```bash
benchctl report 05_Data/Example_Run/20260926T072124Z_load_sweep
```

## Explore the report

- Hover and tap inspection, crosshairs, keyboard navigation and an acquisition-order slider.
- Clear descriptions of readings while increasing and reducing demand.
- A plain-language result using the saved voltage limits, with the underlying readings available.
- A searchable measurement table and CSV download, with raw readbacks preserved.
- Clear pass/fail/incomplete status, including partial data when a run fails.

The [actual demo files](#actual-files-from-the-demo) above show what a run
contains. Your own raw runs and traffic logs stay local because they can contain
addresses and serials. See [05_Data](05_Data/README.md) for provenance, file
formats, timestamps, and instructions for opening the report over SSH.

## Commands

| Command | Use |
| --- | --- |
| `benchctl identify --setup main_bench` | Read instrument identities. |
| `benchctl measure --device psu_rigol_1` | Read supply voltage, current and power. |
| `benchctl run RECIPE --setup main_bench --dry-run` | Validate without hardware. |
| `benchctl run RECIPE --setup main_bench` | Execute the recipe and record results. |
| `benchctl report --latest load_sweep` | Build an offline report from the latest sweep. |
| `benchctl input-off --device load_rigol_1` | Request load shutdown. |
| `benchctl output-off --device psu_rigol_1 --channel 1` | Request CH1 shutdown. |
| `benchctl web` | Open the separate read-only live dashboard on port 8080. |

Rebuild the simulated preview with `python 08_Software/create_preview.py`.

Use `benchctl COMMAND --help` for manual setpoints and path overrides.
The software targets Linux/Pi; native Windows is not supported because the
transport uses POSIX instrument locks. The dashboard is unauthenticated and
binds to localhost by default. Use SSH forwarding for remote access.

## Project folders

Only the folders needed from the numbered project template are included:

```text
00_Documentations/   Architecture, limitations and GitHub publishing guide
01_Electrical/       Bench wiring and protection settings
04_Media/            README chart
05_Data/             Reports/CSV and Example_Run/; ignored local Runs/ and Logs/
08_Software/         src/, tests/, config/, recipes/, developer guide
pyproject.toml       Install and test entry point from the repository root
```

See the [developer guide](08_Software/README.md) and
[architecture](00_Documentations/Architecture.md) for the code map and extension points.

## Verify and publish

```bash
python -m pytest
```

Tests use fake instruments. See the [verification record](05_Data/Verification.md).
[Publishing to GitHub](00_Documentations/Publishing.md)
explains commit identity, ignored files, authentication and the first push.
Choose a license before inviting others to reuse the code.

## Next experiments

Repeat the test with a second set of wires and see which connection delivers
more voltage at the same current. Keep the operating envelope
within the verified hardware limits. Time-series logging and transient tests
would be separate recipes with different measurement requirements.
