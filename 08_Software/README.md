# Software

Python 3.11 or newer controls Rigol DP800 supplies and DL3000 electronic loads over LAN using PyVISA and the pure Python VISA backend. Run the commands below from the **repository root** on Linux, macOS, or WSL.

## Install and verify without hardware

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

Tests use fake instruments and do not connect to the bench. Dashboard tests bind a local HTTP port. Runtime dependencies are declared in the root [`pyproject.toml`](../pyproject.toml); the HTML report uses inline CSS, JavaScript, and SVG and needs no plotting service or browser package.

The shipped example config uses reserved `.invalid` hostnames. It is sufficient to validate the complete demo plan offline:

```bash
benchctl run 08_Software/recipes/load_sweep.yaml \
  --setup main_bench \
  --config 08_Software/config/lab.example.yaml \
  --dry-run
```

This expands the 21 loaded points and validates all setpoints without touching hardware. For live setup and the wiring procedure, follow the [project README](../README.md).

## Preview without a bench

Open [the 5 V power test example](../05_Data/sweep-preview.html), or rebuild it:

```bash
python 08_Software/create_preview.py
```

It shows how to check whether enough voltage reaches a circuit as it draws
more current. The electronic load stands in for that circuit, requesting
50–300 mA. The example is labelled SIMULATED and contains illustrative values.
The [real 21-point report](../05_Data/power-test-report.html) contains the measured
test, including its unloaded reference; the [original three-point report](../05_Data/demo-report.html)
preserves the earlier run shown in the README chart.

## Where to make changes

| Directory | Contents |
| --- | --- |
| [`src/benchctl/`](src/benchctl/) | CLI, validation, instrument drivers, runner, results, and reports. |
| [`tests/`](tests/) | Fake transport/driver tests and report/CLI integration tests. |
| [`config/`](config/) | Shareable inventory example and explicit safety profiles; private `lab.yaml` is ignored. |
| [`recipes/`](recipes/) | Runnable YAML; `load_sweep.yaml` tests 5 V delivery as current demand changes. |

See [Architecture](../00_Documentations/Architecture.md) for the module map and control boundaries. Default file locations are centralized in `src/benchctl/paths.py`; CLI options can select a different config or results directory.

## Working on recipes and drivers

Recipes use named parameters and a fixed action vocabulary. A `sweep` block expands into ordinary actions before safety validation. Keep load reconfiguration between input-off and input-on actions, allow measurements to settle, and put shutdown actions in `finally`. The demo measures from 0.05 A to 0.30 A and back in 0.025 A increments, with a separate no-load baseline. It pauses half a second after configuring each load level before enabling the input, then waits four seconds before recording readings.

For a new driver, implement the typed methods used by the runner, register it, and add explicit config/profile support. Test the exact SCPI commands and readback failure behavior with a fake transport before attempting a live run. Setpoint limits belong in `safety.py` and profiles; SCPI syntax and response parsing belong in the driver.

For report changes, generate HTML from a saved run and inspect hover, touch/keyboard navigation, small-screen layout, and export. Report code must not open instrument connections. Keep measured values and requested setpoints distinct, and label simulated previews explicitly.

```bash
benchctl report --latest load_sweep
```

The command prints the generated HTML path. It uses the latest saved run by its exact recipe name; no hardware needs to be connected.
