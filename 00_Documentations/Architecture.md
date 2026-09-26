# How benchctl works

benchctl runs finite YAML recipes through a small set of typed instrument actions. The software lives in [`08_Software`](../08_Software/README.md); the repository root holds the Python package configuration so installation and tests run from the root.

## Code map

Paths below are relative to `08_Software/src/benchctl/`.

| File | Responsibility |
| --- | --- |
| `cli.py`, `commands_*.py` | Parse command options, select devices, and present errors. |
| `config.py` | Validate the inventory and map setup roles to devices. |
| `recipes.py` | Resolve parameters, expand bounded sweeps, and validate actions and enable order. |
| `safety.py` | Validate requested and measured values against explicit profiles. |
| `identity.py` | Query identity and compare the serial when one is configured. |
| `runner.py` | Validate all setpoints before connecting, execute actions, record measurements, and attempt cleanup. |
| `drivers/` | Translate typed methods into Rigol SCPI, read back settings, and check error queues. |
| `transport.py` | Open VISA sessions, enforce a timeout, lock each resource, and log commands. |
| `results.py` | Save run summaries, measurement/event JSONL, and CSV. |
| `report.py` | Read saved results and generate a standalone interactive HTML report. |
| `web/server.py` | Serve a read-only dashboard with live instrument queries. |
| `paths.py` | Keep default config, run, and log locations together. |

The `supply` and `load` roles let a recipe work with different named devices. Ratings come from the selected safety profile; the software does not infer hardware limits from a model name. The DP800 driver currently handles channels 1 and 2.

## Control boundaries

Before opening a VISA connection, the runner resolves every sweep point, checks the action schema and enable order, and validates every requested setpoint, including cleanup actions. Sweeps are limited to 1,000 points and recipes to 10,000 expanded actions. A dry run performs these checks without connecting to instruments.

Every live command identifies its instrument. Serial pinning is **optional in the schema**: a non-null `expected_serial` must match; omitting it or setting it to null accepts the reported identity. Fill in the exact serial after initial identification to protect against contacting the wrong instrument at an address.

Supply configuration requires the selected output to be off. Manual load enable and recipe load configuration require the load input to be off before changing its mode or current. Enable actions in a recipe require successful configuration earlier in the same run. Driver writes check the SCPI error queue and verify supported settings/states by readback; measurement queries reject malformed and nonfinite numbers.

After a load is enabled, its voltage, current, and power are checked against the configured limits. Measurement expectations determine pass/fail at the recorded points. These checks are intermittent software checks: they cannot verify wiring, detect every transient, or replace front-panel protection settings. The recipes do not configure OVP/OCP or load protection limits.

The transport lock coordinates benchctl processes on the same computer using the same VISA resource string. It cannot exclude another computer, another program, or a front-panel operator. Runtime locking uses POSIX `flock`, so use Linux, macOS, or WSL rather than native Windows.

## Cleanup and failure behavior

After all connections and identity checks succeed, the recipe's `finally` actions are attempted on normal completion, step failure, or Ctrl-C. Each cleanup action is attempted even if an earlier cleanup action fails. An uncertain enable also triggers an immediate best-effort disable. Recipes must include the shutdown actions they need; the supplied sweep turns off the load and the selected supply channel.

Connection or identity failures occur before recipe execution and do not send recipe cleanup commands to unverified devices. A network loss, power loss, process kill, or hardware fault can prevent shutdown. Check the instrument panels after a failed or interrupted live run. Cleanup errors are recorded where possible and reported without replacing the original step error.

## Data and reports

Each run creates a directory in `05_Data/Runs/` containing `run.json`, `execution.jsonl`, and, when measurements exist, `measurements.jsonl` and `measurements.csv`. Raw VISA traffic is recorded in `05_Data/Logs/commands.jsonl`. Local runs and logs are ignored by Git because they can contain instrument addresses and serial numbers.

Report generation needs only saved files and never contacts hardware. The current overview shows requested and measured current against reading number. Comparison plots use measured load current and keep acquisition order, so an upward and downward sweep can be compared. Requested currents come from successful configuration events in the execution log. Human reading names combine this current with the direction of demand; internal record IDs remain available in CSV and raw data. Report conclusions use the voltage range saved with the run, so changing a recipe never rewrites historical acceptance limits. Simulated examples are labelled and do not receive a real bench verdict. Missing or damaged records are called out when possible, allowing inspection of partial runs.

Supply and load readings are sequential. Their voltage difference includes instrument offsets and connection effects; dividing it by load current gives an apparent resistance, not an isolated cable-resistance measurement. A pass means the recorded expectations were satisfied, not that the bench is calibrated.

The [21-reading measured report](../05_Data/power-test-report.html) and
[matching CSV](../05_Data/power-test-results.csv) contain the completed 5 V
test. The original [three-point report](../05_Data/demo-report.html),
[CSV](../05_Data/demo-results.csv), and [README chart](../04_Media/demo-load-sweep.svg)
remain as the earlier measured snapshot. These shareable artifacts are separate
from private run logs.
