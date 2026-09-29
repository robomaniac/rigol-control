# Engineering figure labels and voltage definitions

The report uses engineering figure names: **Efficiency**, **Load Regulation**,
**Input Current**, and **Power Loss**. Axes identify the plotted quantities and
units; legends and captions identify input conditions and the measurement
boundary. Time plots use **Output Current vs Time**, **Output Voltage vs Time
(Sustained Load)**, and **Input Voltage vs Time**.

For the energized input descent, the voltage figure is **Output Voltage vs Input
Voltage (Line Regulation)**. Its horizontal coordinate is measured input
voltage. The caption retains the 15 V startup history, fixed 100 mA load, and
9.1 V programmed endpoint.

## Regulation and dropout are different measurements

| Quantity | Definition in this project | Presentation |
| --- | --- | --- |
| Output voltage | Accepted mean output voltage at the load terminals | V; plotted against output current for load regulation, or input voltage at fixed load for line regulation |
| Output deviation from nominal | `100 × (Vout − Vout_nominal) / Vout_nominal` | Signed %; a positive value means the observed output is above nominal |
| Load regulation span | `100 × (max(Vout) − min(Vout)) / Vout_nominal` over the acquired load range at one input condition | Nonnegative % of nominal; range and conditions accompany the metric |
| Line regulation span | The same normalized span over the qualified common input grid at fixed requested load | Nonnegative % of nominal; input range and startup history remain part of the result |
| Buck dropout voltage | Minimum input headroom above the target output needed to maintain regulation under the stated load and criterion | V, plotted against output current only after those thresholds have been measured |

For example, a hypothetical 12 V converter producing 12.12 V has a **+1% output
deviation**. If its output spans 12.12–12.18 V across a load sweep, the
**regulation span is 0.5% of nominal**. Neither calculation identifies a dropout
threshold.

The project's current curves include the wiring inside the declared
source-to-load measurement boundary. Their efficiency and power loss are path
measurements. Load-terminal voltage variation can include output wiring drop.

## Manufacturer references

Pololu's D24V90F5 page defines buck dropout in terms of the input voltage
headroom required to maintain the target output, and plots it against output
current. That graph requires finding the minimum regulating input for each
load. Its output-voltage-versus-load plot is a separate measurement. See
[Pololu: Typical dropout voltage and light-load behavior](https://www.pololu.com/product/2866).

TI's LM27403EVM guide uses separate **Efficiency**, **Load Regulation**, and
**Line Regulation** figures. The regulation graphs plot absolute output voltage
in volts against output current or input voltage, respectively. See Figures
4–7, pages 11–12 of
[TI SNVU233A](https://www.ti.com/lit/pdf/snvu233).

TI's TPSM63610EVM guide likewise plots output voltage in volts under its load
regulation heading, alongside efficiency plots with output current as the
horizontal axis. This is the convention used for our load-regulation figures.
See Section 3.1, pages 8–9 of
[TI SLVUCF1A](https://www.ti.com/lit/ug/slvucf1a/slvucf1a.pdf).

## What our existing measurements establish

The acquired load sweeps show output voltage, efficiency, and loss at the
tested operating points. The 15 V startup followed by a descent to 9.1 V shows
continued operation at the tested light load and startup history. It does not
locate the loss-of-regulation boundary, a cold-start threshold, or UVLO.

No dropout curve or dropout number is generated from these runs. A future
threshold procedure would need an explicit regulation criterion, adequate
source headroom, and measurements bracketing the boundary at each load. The
buck headroom definition should not be assumed to characterize a converter
with unknown topology or one capable of operating below its output voltage.

These label changes preserve figure identifiers, source data, calculations,
and summary cross-references. Existing issued report revisions remain unchanged;
newly generated report revisions use the updated wording.

## Curve styles and reference lines

The same input condition has the same color, line pattern and marker across
HTML, PDF and exported plots, including reports showing only a subset of the
conditions.

| Input condition | Color | Line | Marker |
| --- | --- | --- | --- |
| 12 V | Blue | Solid | Circle |
| 24 V | Vermilion | Dashed | Square |
| 36 V nominal | Magenta | Dotted | Diamond |

The near-36 V test retains its recorded 35.8 V setpoint. A reserved style does
not create a curve for an unmeasured condition. Increasing-load, sustained-load
and decreasing-load stages use distinct styles in sequence reports.

Output-voltage figures include the declared nominal voltage as a gray reference
line. Their initial vertical range includes both the nominal value and measured
values, so a very small measured span does not fill the whole plot. Input-current
figures include the recorded supply current setting when it is available.
Reference lines are display aids, not additional measurements or pass/fail
limits. Interactive zoom and axis controls remain available.
