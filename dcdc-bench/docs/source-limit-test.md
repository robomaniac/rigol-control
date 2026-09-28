# Test the converter near the supply's 1 A limit

This procedure keeps the converter input at **24 V** and increases the load on its **12 V output** until the DP821A delivers approximately **0.98 A at its output terminals**. That is the converter's **input current**. The electronic load can therefore draw more than 1 A from the converter output.

The supply is programmed to **1.000 A maximum**. The electronic load request is bounded to **2.000 A**: 24 V × 1 A supplies at most 24 W, equivalent to 2 A at an ideal 12 V output before conversion and wiring losses. The converter's stated 4 A rating is outside this test.

## What happens

1. Verify instrument serials, both outputs OFF, local sensing, protection readbacks, and an independent source shutoff timer.
2. Start at 24 V with a 100 mA output load.
3. Increase the output load in 100 mA steps. Once measured input current reaches 0.90 A, use 25 mA steps.
4. At each attempted point, observe settling and acquire at least ten seconds of guarded DC readings. When the input-current mean reaches 0.98 A, extend that same uninterrupted observation to thirty seconds.
5. Return to a separate 100 mA point and verify it, then turn both outputs OFF.

The 77 candidate loads in the YAML are a conditional search grid. Many candidates are intentionally skipped while using coarse steps, and remaining candidates are not attempted after the stopping condition. The report retains those requests and records the actual execution order.

There is no separate hold after returning to an earlier load. Separate visits have separate point IDs and are not averaged together.

## Boundaries and recovery

| Setting | Fixed value |
|---|---:|
| Supply voltage | 24 V |
| Supply programmed current limit | 1.000 A |
| Source OVP / OCP | 26 V / 1.05 A |
| Absolute input-current readback stop | 1.02 A |
| Stop increasing load at input current | 0.995 A |
| Nominal input-voltage window | 23.5–24.5 V |
| Output-voltage window | 10.8–13.2 V |
| Maximum requested output load | 2.000 A |
| Output-current guard | 2.05 A |
| Independent source / software deadlines | 720 s / 660 s |

The OCP threshold and readback guard do not authorize a current setting above 1.000 A.

If the source enters constant-current mode, input voltage loses headroom, or output voltage falls below the lower stop threshold, the failed observation remains unqualified. The worker makes **one** return to 100 mA and checks recovery before saving explanatory checkpoints. The actual recovery delay is recorded. Failed recovery ends the test.

Overvoltage, excessive measured current, malformed readings, communication errors, and instrument protection faults cause shutdown without a recovery attempt. Source-limit observations are not DUT failure verdicts and never enter nominal 24 V efficiency means.

## Run the fixed procedure

From the repository root, using the private bench inventory:

```bash
.venv/bin/python -m dcdc_bench.source_limit \
  --config Software/config/lab.yaml \
  --out dcdc-bench/runs/real-source-limit \
  --arm
```

The YAML in `profiles/recipes/12t12-4a-source-limit.yaml` documents requests. This command does not accept arbitrary recipe files or user-supplied limits. The general real backend remains separate.

Run acquisition in the existing supervised detached service so SSH loss does not kill its terminal. Do not run browser/PDF rendering while acquiring. The instrument-side timer remains the fallback if the Pi fails; failed source shutdown must not cancel that fallback.

## How to read the result

- **Input current** shows how close the supply came to its 1 A limit.
- **Output current** is the separate load on the converter's 12 V output.
- **Path efficiency** includes input/output wiring; it is not a calibrated measurement of the converter alone.
- The initial ten-second input-current mean that triggered the longer endpoint observation is retained separately from the final thirty-second mean, which can drift.
- The plan's 100% efficiency setting is solely the ideal power ceiling used to enumerate candidates. It is not an expected or measured efficiency.
- ADC freshness, calibration, readback uncertainty, temperature, ripple, transient behavior, and full rated performance remain unqualified.

The run contains original SCPI responses, query timestamps, rejected observations, execution order, final shutdown verification, and an integrity manifest.
