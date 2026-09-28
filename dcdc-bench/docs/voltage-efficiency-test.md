# Compare converter efficiency at different input voltages

This fixed procedure measures the connected **12T12-4A** at **12 V**, **24 V** and **near 36 V** input. At each input voltage it increases the current drawn by the electronic load, then calculates output power divided by input power from the measured DC readings.

All three planned grids share **100–700 mA output requests**, allowing comparison at the same output demand where qualified measurements are available. Additional loads extend each curve within the available source power. The DP821A CH1 remains set to a **1.000 A input-current limit** throughout. The converter's stated 4 A output rating cannot be exercised with this source at these input voltages.

## The upper input condition

The requested 36 V condition is deliberately programmed to **35.8 V**, with a **35.93 V maximum readback**. The report must identify it as **near 36 V**, show the programmed setting, and retain the actual measured input voltage.

The [Rigol DP800 datasheet](https://www.rigol.com/dam/global/downloads/brochures/en/data-sheet/dc-powers/DP800_DataSheet_EN.pdf), printed page 5, gives DP821A CH1 voltage programming and readback accuracy of ±(0.1% + 25 mV) under its stated conditions. This motivated the conservative margin below the owner's stated 36 V upper operating limit. Calibration is unverified. The source's OVP setting and polling guards do **not** establish a precise transient ceiling; exact 36 V and overshoot qualification require additional evidence.

## What the procedure does

1. Verify the configured source and load serial numbers, protections, local sensing and both outputs OFF.
2. Start the first voltage with a verified independent source shutoff timer. Observe five source-only cycles and require at least 10.8 V output before enabling the load at 100 mA.
3. Observe five settling cycles, then acquire at least eight seconds and five complete four-channel cycles at each attempted load.
4. End that voltage phase when its load grid is complete, mean source current reaches 0.98 A, or a source/headroom boundary is observed.
5. Verify source OFF before cancelling its timer; verify load OFF and residual source voltage at or below 0.5 V before changing input voltage. A bounded two-second OFF-only wait allows source discharge.
6. Start the next voltage at 100 mA with freshly verified protections and a new independent source timer.
7. Turn both outputs OFF and preserve all original readings, including any excluded boundary observations.

| Nominal input condition | Programmed input | Conditional output loads |
|---|---:|---|
| 12 V | 12.000 V | 0.1–0.8 A in 0.1 A increments |
| 24 V | 24.000 V | 0.1–0.7 A in 0.1 A increments, then 0.9, 1.1, 1.3, 1.5, 1.65, 1.725 A |
| Near 36 V | 35.800 V | 0.1–0.7 A in 0.1 A increments, then 0.9, 1.2, 1.5, 1.8, 2.1, 2.3, 2.5 A |

There are **35 conditional requests**. An unattempted request remains in the plan and exports with a reason. It is not converted to a zero measurement or a failed DUT test.

## Fixed operating limits

| Setting | Value |
|---|---:|
| Source current setting | 1.000 A |
| Source OCP | 1.05 A |
| Hard input-current readback stop | 1.02 A |
| End phase at input-current readback | 0.995 A |
| End phase after qualified mean input current | 0.98 A |
| Source OVP at 12 / 24 / near 36 V | 13 / 26 / 36 V |
| Maximum input readback at 12 / 24 / near 36 V | 12.5 / 24.5 / 35.93 V |
| Lower input-voltage boundary | 0.5 V below that phase's programmed setting |
| Loaded output-voltage window | 10.8–13.2 V |
| Output-current guard | 2.55 A |
| Independent source shutoff | 720 s from each phase start |
| Global software deadline | 660 s for the complete run |
| Latest start of a new voltage phase / measurement point | 590 / 620 s elapsed |

Source constant-current mode, low input headroom, an input reading at or above 0.995 A, or output below 10.8 V ends the current phase. Its boundary point remains unqualified and does not enter an efficiency curve. Source power is removed before explanatory checkpoints. A subsequent voltage phase is allowed only after all OFF checks succeed.

Overvoltage, excessive measured current, nonfinite readings, transport errors, instrument protection faults and failed OFF checks terminate the whole test. There is no retry or recovery load after a hard fault.

## Run

From the repository root, using the private bench inventory:

```bash
.venv/bin/python -m dcdc_bench.voltage_sweep \
  --config Software/config/lab.yaml \
  --out dcdc-bench/runs/real-voltage-sweep \
  --arm
```

The [recipe](../profiles/recipes/12t12-4a-voltage-efficiency.yaml) documents the requests. The armed command accepts no arbitrary voltage/current limits or recipe. Run acquisition in a detached, non-restarting supervised service so SSH disconnection does not kill its terminal. Keep browser/PDF work separate from acquisition.

The source-to-load-terminal efficiency includes wiring losses. This run compares DC behavior; it does not measure temperature, ripple, switching transients, the 9 V endpoint, or full rated output. Separate windows at different voltages retain separate point IDs and raw cycles.

## Continue after a preserved 12 V startup boundary

If the first 12 V startup aborts at the source-current/voltage boundary and both outputs are verified OFF, the fixed continuation can acquire **only the unchanged 24 V and near-36 V phases**. It never repeats 12 V, raises the current setting, or imports old samples into the new run.

```bash
.venv/bin/python -m dcdc_bench.voltage_sweep \
  --config Software/config/lab.yaml \
  --out dcdc-bench/runs/real-voltage-sweep \
  --continue-after-12v-startup PATH_TO_FINALIZED_12V_STARTUP_RUN \
  --arm
```

The prerequisite must be the intact, finalized measured run from the complete fixed voltage plan: only its first 12 V point attempted, no accepted efficiency windows, a recorded startup source boundary, and source/load/timer verified OFF. Its plan, hashed evidence, raw boundary readings and instrument serials are checked before opening hardware. A hard-fault abort or a different instrument inventory does not qualify.

The continuation has **27 conditional requests** and its own raw evidence, timer, global deadline and final integrity manifest. Report metadata retains the prior run ID, evidence-manifest hash and startup values. The 12 V comparison is explicitly unavailable; no 12 V efficiency curve is inferred from that startup failure. Fresh startup at 24 V still has to pass the source-only output-voltage gate before the electronic load is enabled.
