# A longer test of the 12T12-4A

This fixed procedure follows the first successful 24 V / 100 mA measurement.
It asks three practical questions:

1. Does the output stay near 12 V as current demand increases?
2. How does source-to-load-terminal efficiency change with load?
3. Does the voltage drift during three minutes at the highest tested load,
   and does it return to similar values as demand decreases?

## Procedure

The [YAML specification](../profiles/recipes/12t12-4a-extended.yaml) shows the
requested grid and acquisition policy. The fixed procedure in
[`extended.py`](../src/dcdc_bench/extended.py) supplies the reviewed electrical
limits, continuous hold behavior, startup checks, and shutdown deadline.
Editing that YAML does not change or arm this fixed procedure.

| Stage | What happens |
| --- | --- |
| Increasing load | 50 to 500 mA in 50 mA steps: ten operating points |
| Sustained load | At least 180 seconds at 500 mA, recorded in eighteen observation windows |
| Decreasing load | 450 back to 50 mA in 50 mA steps: nine operating points |

Input voltage stays at **24 V on CH1**. The highest nominal output power is
**6 W**. Each sweep point has at least five seconds of guarded settling followed
by a ten-second measurement window. Complete query cycles and their actual
timing are retained; a polling target is not a guarantee of ADC sample freshness.

The sustained-load windows continue at the same setpoint, without repeatedly
switching the converter off. Their first and last mean voltages describe
observed drift over the recorded interval. They do not establish a temperature
coefficient or thermal equilibrium: there is no temperature sensor in this setup.

## Fixed limits and shutdown

- Supply current limit: **0.45 A**; OVP: **26 V**; OCP: **0.50 A**.
- Output voltage guard: **10.8–13.2 V**; load current ceiling: **0.60 A**.
- A **65% efficiency assumption**, used only for planning, leaves the 500 mA
  endpoint inside the source's 90% current budget. Actual efficiency is measured.
- The worker stops at 660 seconds. The supply has a separately verified
  720-second, single-cycle delay program ending with its output **OFF**.
- Acquisition runs as a one-shot service with no automatic restart. SSH loss
  does not launch another test. Acquisition and browser/PDF rendering run
  separately on this Pi.
- Cleanup independently disables the load and supply, stops the source delay
  program, and records readback confirmation. An unknown shutdown state is
  reported as unknown, never as successful.

The source's automatic shutoff was checked before energizing the converter:
a five-second delay program at **0 V programmed** enabled the channel and then
disabled it without another command. Local evidence is in
`Data/Logs/extended-timer-proof.json` in the parent project. This verifies the
observed firmware behavior; it is not a certification of a safety interlock.

These are bounded characterization limits, not manufacturer acceptance limits.
The load's physical rating/modification and instrument readback uncertainty
remain unverified. The converter's nominal 48 W rating is not tested here.

## Run the fixed procedure

From the parent `rigol-control` checkout, after confirming the same DUT,
wiring, CH1 connection, polarity, and selected limits:

```sh
.venv/bin/python -m dcdc_bench.extended \
  --config Software/config/lab.yaml \
  --out dcdc-bench/runs/real-extended --arm
```

This command **operates real equipment**. It requires the parent `benchctl`
package and this subproject installed in the same Python environment, plus
the private inventory with both expected serial numbers. The general
`dcdc-bench run --mode real` command remains disabled.

On this Linux bench, acquisition is launched as a detached one-shot user
service so an SSH disconnect does not interrupt it:

```sh
systemd-run --user --unit=dcdc-12t12-extended \
  --property=Restart=no --property=RuntimeMaxSec=690 \
  --property=TimeoutStopSec=20 --working-directory="$PWD" \
  "$PWD/.venv/bin/python" -m dcdc_bench.extended \
  --config "$PWD/Software/config/lab.yaml" \
  --out "$PWD/dcdc-bench/runs/real-extended" --arm
journalctl --user -u dcdc-12t12-extended -f
```

Use a unique unit name for each deliberately started test. There is no
automatic restart or automatic resumption of partial runs. The user service
manager must persist after logout; see [Pi reliability](../../Documentation/Pi-Reliability.md).
To request an early stop, use `systemctl --user stop dcdc-12t12-extended`, then
check the saved shutdown evidence. Do not infer instrument state from the
SSH session or web page.

After acquisition finalizes with both outputs confirmed off, generate reports:

```sh
.venv/bin/dcdc-bench report dcdc-bench/runs/real-extended/<run_id> --formats html,pdf
```

## Read the graphs

The efficiency and voltage-versus-current curves separate increasing and
decreasing demand. Both visits to the same current share the same horizontal
position. The **current-versus-elapsed-time graph** instead shows the sequence:
rise, three-minute plateau, then fall.

Each accepted operating point is based on multiple voltage/current query cycles.
Hover and the point inspector expose the actual readings and conditions.
The CSV preserves numerical precision; displayed digits do not imply that level
of measurement accuracy.

Efficiency is measured from **supply terminals to load terminals**. It includes
both sets of connecting leads. Without Kelvin measurements at the converter,
the report cannot separate converter loss from wiring loss.

## What this test leaves open

This is a DC characterization at one input voltage and up to about 6 W output.
It does not measure ripple, transient response, startup waveforms, line
regulation, isolation, temperature, or full-power performance. Those require
different procedures and, for some measurements, additional instruments.
