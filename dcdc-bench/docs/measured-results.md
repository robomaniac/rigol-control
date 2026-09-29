# Measured results on the connected 12T12-4A

These are the measured-run narratives that used to sit in the
[dcdc-bench README](../README.md), moved here unchanged when the README was
shortened. Every number, claim and caveat is as it was written; only the
relative link targets were adjusted for this folder. The README keeps a
one-row-per-run summary table under "Measured results so far".

> **Local links.** The `http://localhost:8081/...` report, PDF and ZIP links
> below are local to the owner's bench: they point at the persistent report
> server on the development Pi (`benchctl-report.service`, loopback only) and
> only work through the SSH port forward described in
> [Viewing local reports](../../Documentation/Viewing-Local-Reports.md). They
> do not resolve from GitHub or from another computer. The run folders they
> serve are ignored by Git and have not been published.

All runs below were acquired on 2026-09-27 (UTC) on the reviewed DP821A CH1 /
DL3031A bench, in this order: the supervised pilot, the longer 24 V test, the
source-limit test, the input-voltage comparison (12 V startup attempt, then the
24 V / near-36 V continuation), the 15 V start and input descent, and the
three-point configured run through the bench interface.

Contents:
[First real measurement](#first-real-measurement) ·
[Longer real converter test](#longer-real-converter-test) ·
[Test near the supply limit](#test-near-the-supply-limit) ·
[Efficiency at different input voltages](#efficiency-at-different-input-voltages) ·
[Start at 15 V, then reduce the input](#start-at-15-v-then-reduce-the-input) ·
[Completed test through the interface](#completed-test-through-the-interface)

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

## Longer real converter test

The **12T12-4A** completed an **8 minute 24 second** test at **24 V input**:
increase demand from **50 to 500 mA**, hold 500 mA for **185.7 seconds**, then
step back down to 50 mA. It asks whether voltage stays near 12 V, how efficiency
changes with demand, and whether the output returns to a similar value.

**[Test procedure and commands](extended-test.md)** ·
**[Actual YAML specification](../profiles/recipes/12t12-4a-extended.yaml)** ·
[Agent-role results review](extended-results-review.md)

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
the timing or electrical limits. See the [verification record](extended-verification.md),
[agent-role code review](extended-code-review.md), and
[report UI/UX review](extended-ui-review.md).

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

[Procedure and commands](source-limit-test.md) ·
[Actual YAML specification](../profiles/recipes/12t12-4a-source-limit.yaml) ·
[Independent measurement review](source-limit-results-review.md) ·
[Code review](source-limit-code-review.md)

The report plots input current separately from output demand, retains the raw
readings, and distinguishes unused conditional load settings from failed
measurements. Dotted lines connect qualified stage boundaries on the time
graph; they add no measured samples. Hover, point inspection and CSV exports
remain available. Efficiency includes wiring losses, and measurement
uncertainty has not been quantified.

## Efficiency at different input voltages

**[Open the interactive efficiency report](http://localhost:8081/Runs/12t12-efficiency/report.html)** ·
[PDF](http://localhost:8081/Runs/12t12-efficiency/report.pdf) ·
[Offline ZIP](http://localhost:8081/Runs/12t12-efficiency-download.zip) ·
[Test YAML](../profiles/recipes/12t12-4a-voltage-efficiency.yaml) ·
[Procedure](voltage-efficiency-test.md)

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

The earlier 12 V startup produced about 8 V output during its unloaded startup window; the load was then enabled at that output voltage and, one second later, the input collapsed to **2.661 V** with input current at **1.0005 A**. It produced no qualified efficiency window. Its cause is not established (see the [cold-start hypothesis](cold-start-hypothesis.md)), and these results do not verify the full stated 9–36 V range. The continuation did not repeat that startup; both original runs are in the ZIP.

The continuation completed **27 qualified windows and 204 accepted reading
cycles in 428 seconds**, with a **1.000 A supply setting**. Both outputs and the
source timer were verified **OFF**, including a separate query afterward.
Efficiency includes wiring losses. These short DC windows do not establish
thermal equilibrium, measurement uncertainty, or the converter's 4 A rating.

The report has separate equipment model, serial, firmware and manufacturer
columns, aligned DUT tables, and a clearly labeled account of the earlier
startup stop. See the [code review](voltage-efficiency-code-review.md),
[agent-role results review](voltage-efficiency-results-review.md), and
[report UI review](voltage-efficiency-ui-review.md).

These are **local Pi reports**, using the forwarded port shown in VS Code.
Download and extract the ZIP to read without SSH. They are not yet published
GitHub Pages examples.

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
at low input. See [the measurements and complete method](startup-descent-results-review.md).

## Completed test through the interface

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
[Agent-role results review](configured-workflow-results-review.md) ·
[Interface verification](bench-ui-verification.md)

Report figures use standard engineering labels and consistent colors, line
patterns and markers. See [figure terminology and voltage definitions](engineering-figure-labels.md)
for load regulation, line regulation, and the separate meaning of dropout voltage.

This short run verifies the configurable workflow. The wider measured sweeps
and their limits are documented below. Report generation takes several minutes
on this Pi; its **Reporting** state follows acquisition and verified shutdown.
