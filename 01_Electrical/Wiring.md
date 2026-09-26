# Bench wiring

The measured demo uses a Rigol DP821A supply and DL3031A electronic load over
LXI/VXI-11 Ethernet. The Pi runs `benchctl`; it carries no load current.

With supply output and load input off:

```text
DP821A CH1 (+) ───── DL3031A INPUT (+)
DP821A CH1 (−) ───── DL3031A INPUT (−)
```

Check the terminal labels and polarity. This demo assumes local sensing; remote
sense wiring is a separate setup. Review the [DP800 user guide](https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/dc-powers/DP800_UserGuide_EN.pdf)
and [DL3000 user guide](https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/dc-load/DL3000_UserGuide_EN.pdf)
for your actual models and wiring.

## Settings used for this bench

| Setting | Value |
| --- | --- |
| CH1 voltage / current limit | 5.0 V / 0.50 A |
| CH1 overvoltage protection | Enabled, 6 V |
| CH1 overcurrent protection | Enabled, 1 A |
| Load operating mode / current range | CC / 6 A |
| Load CC voltage / current limit | 6 V / 0.50 A |
| Current requested by the test load | 50 → 300 → 50 mA |
| Voltage accepted by the current recipe | 4.75–5.25 V |

The supply current setpoint is the primary current bound here. The separate
DP800 OCP threshold has coarse accuracy at this scale; see the
[DP800 data sheet](https://www.rigol.com/dam/global/downloads/brochures/en/data-sheet/dc-powers/DP800_DataSheet_EN.pdf).
These are settings for the verified demo bench, not automatic configuration
for every DP800/DL3000 model. The recipe does not configure hardware protections.
Verify these values before each live run. The recipe leaves the load off for
half a second after each configuration change, then allows four seconds for
the enabled load to settle before recording a reading.

## Shutdown and failure behavior

The recipe requests load input off before changing CC setpoints and requests
load off followed by CH1 off on completion or an execution error. A connection,
identity, process, power or logging failure can prevent cleanup. Inspect front
panels after an error; software alone cannot establish a safe physical state.
The [architecture notes](../00_Documentations/Architecture.md) describe these limits.
