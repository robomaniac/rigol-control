# Extended DC–DC report: UI and UX review

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Run: `20260927T093948.075493Z_real_42e971`  
Analysis: `a-4a0763ae9add`  
Final report revision: `r0006`  
Review date: 2026-09-27 UTC

**Final result: no blocking UI or UX findings remain in the reviewed scope.**

An automated agent-role report reviewer inspected the report source, then exercised the
actual generated HTML in one offline Chromium browser after the supply and load
were confirmed off. The reviewer implemented the point-inspector improvement
below after reporting it; the parent agent and the agent-role code reviewer reviewed that change.

## Findings and changes

| Finding | Change / status |
| --- | --- |
| The keyboard point selector exposed raw queries but omitted the aggregate values available on mouse hover. | Added a semantic, keyboard-accessible results table: output voltage/current, input/output power, path loss and path efficiency. Current below 1 A displays in mA. Missing values are explicit; CSV retains original precision. Verified in revision `r0002`. |
| The section heading mentioned no-load results although this protocol starts at 50 mA. | Changed to “Regulation and sustained-load results”; explicitly states that no-load consumption was not measured. Verified in `r0002`. |
| Narrow-screen controls could exceed their columns. | Parent corrected the grid sizing. At 390 px, the document measured exactly 390 px wide. The raw-query table scrolls within its own container. |
| At 390 px, the demand chart's three-row legend obscures the 500 mA ramp peak and much of the hold plateau. | Reserved room above the plot and anchored the legend's bottom. Confirmed in `r0003`: the entire peak/hold is visible; all legends sit above their plotted data. |
| The chart's painted SVG could be taller than the space reserved in document flow, obscuring caption lines. | Set the graph element's explicit height from the same Plotly layout used to draw it. Final `r0004` passed actual SVG/caption geometry and visual checks at 1365 px, 390 px and after resizing back to 1365 px. The exact added browser regression function also passed against this issued report. |
| PDF page 2 contains the tail of the DUT ratings table before the forced Setup page break. | Moved the extended report's page break before the DUT section and allowed DUT/Setup to flow together. All seven pages of `r0003` were visually inspected: the orphan is gone and there is no clipping, overlapping text, blank page or split caption. |

## Interaction checks on revision r0002

- All five interactive figures loaded offline, with Figure 1–5 captions and
  descriptive question headings.
- All 37 point choices have readable stage/load labels, including numbered hold
  bins. The source IDs remain available for evidence traceability.
- Moving the actual mouse onto a 350 mA marker displayed the measured values,
  qualification, stage and recorded time-bin limits. Clicking selected the same
  evidence point (`p0031`) and exposed its 56 raw query records.
- Actual checkboxes and the metric dropdown isolated the sustained-load figure.
  Its CSV contained the 18 hold windows and the metadata described the selected
  scope and measurement boundary.
- The actual CSV button downloaded both data and metadata; data matched the
  full-precision report export. The actual SVG button produced an 11,688-byte
  vector file containing the run identity.
- The issued summary remained unchanged after filtering.
- Keyboard End/Enter on the point selector chose the last 50 mA window
  (`p0037`) and displayed the aggregate result table, including 50.103 mA actual
  output current. No mouse hover was required to read its results.
- The prominent PDF link points to the companion `report.pdf`.
- Desktop width was 1365/1365 px; mobile width was 390/390 px. There were no
  JavaScript page errors or external network requests.

The first audit attempt contained a Playwright accessor error while reading SVG
hover text (`inner_text` instead of `text_content`). It was corrected and the
completed checks above were run against the unchanged issued report.

## PDF visual review

Revision `r0003` was rasterized at 85 dpi and every page was inspected:

| Page | Contents | Visual result |
| --- | --- | --- |
| 1 | Summary, coverage, qualification | Clear hierarchy; complete tables and figure references. |
| 2 | Complete DUT identity/ratings and setup | The previous orphaned table tail is fixed. |
| 3 | Acquisition method and test procedure | Timing units, stage table and shutdown records are readable. |
| 4 | Demand over time and efficiency | Both plots, labels and captions fit. |
| 5 | Output voltage and path loss | Both plots, labels and captions fit. |
| 6 | Sustained-load voltage and regulation | Expanded voltage scale is explained; results table fits. |
| 7 | Interpretation and qualification/provenance | Complete limitations and issued revision; no orphaned continuation. |

The correction for `r0004` changes HTML layout only. The parent verified all seven
PDF pages have exactly the same extracted words and bounding-box coordinates as
the visually approved `r0003`, except the report revision token. The final HTML
and PDF SHA-256 hashes also match their build manifest. The PDF visual review
therefore carries forward to the final revision.

## Final HTML layout verification

The issued `r0004` was checked in one offline browser at 1365 px desktop width,
390 px mobile width, and after returning to 1365 px. For all five figures, the
container and SVG were both 465 px tall, and each caption began at or after its
SVG's bottom edge. Every displayed legend stayed above the data plot. The full
500 mA peak and sustained-load plateau remained visible on mobile. Screenshots
confirmed that the desktop captions were completely readable after resizing.

There was no document overflow, JavaScript page error or external network
request. Run, analysis and revision identities matched the report model; the
point inspector still displayed measured results with current in mA.

The new regression
`test_web_chart_captions_remain_below_svg_on_desktop_and_mobile` was directly
invoked with this real report's existing browser tuple and passed. This was a
focused artifact check, not a rerun of the entire mock browser suite. The browser
and its process were closed afterward. The previously exercised hover, stage
filters and actual exports are recorded above; the final changes affect layout.

## Local review evidence

These files are local review artifacts under the ignored run directory:

- [Audit results](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/audit.json)
- [Desktop summary](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/desktop-summary.png)
- [Actual pointer hover](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/desktop-hover.png)
- [Selected sustained-load figure](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/desktop-hold.png)
- [Mobile controls](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/mobile-controls.png)
- [Mobile demand chart before the legend correction](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-r0002/mobile-demand.png)
- [Final layout audit](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/final-layout-audit.json)
- [Final desktop chart and complete caption](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/desktop_initial-demand-final.png)
- [Final mobile chart](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/mobile-demand-final.png)
- [Final desktop view after resizing](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/desktop_resized-demand-final.png)
- [Visually approved PDF page 2: complete DUT/setup](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/pdf-page-2.png)
- [Visually approved PDF page 4: demand and efficiency](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-final/pdf-page-4.png)

## Follow-up: compact hover in r0005

User feedback correctly identified an issue the earlier review missed: the
16-line colored hover panel was too dense and obscured the curve. The earlier
functional checks established that the data appeared, but did not adequately
judge whether that presentation was useful.

The replacement shows three lines: stage/input context, the plotted horizontal
quantity, and the plotted result. It uses a white background, dark text and a
subtle border, with no duplicate series bubble. Current below 1 A displays in mA
to one decimal; efficiency uses two decimals, voltage four decimals, power three
decimals and elapsed time one decimal. Other measurements moved to the point
inspector, which now has nine aggregate rows and the recorded time interval.

The final artifact was checked in one offline browser. Actual pointer hover on
the reported 300 mA return-path point (`p0032`) showed:

> Decreasing demand · 24 V  
> Output current: 299.6 mA  
> Path efficiency: 81.44%

The tooltip measured **155.3 × 57.2 px** at both 1365 px desktop width and 390 px
mobile width. Both screenshots were inspected: the card has three lines, fits
the viewport and leaves the curve largely visible. All three curves remained
selected during these captures.

The exact new
`test_web_compact_hover_desktop_mobile_and_alternate_axis` function passed
against the issued real report in that same browser. It checks actual pointer
hover bounds, three lines, neutral colors, absence of a duplicate series bubble,
the correct label/value after changing the horizontal axis to output power,
click and keyboard access to the inspector, and unchanged full-precision CSV
and model values. The old rounding-fixture expectations were updated for the
compact presentation; the entire browser suite was not rerun for this change.

There were no JavaScript page errors or external requests. The browser and audit
process closed after the focused checks. The parent verified the final artifact
hashes and that all seven PDF pages retain the previously approved words and
coordinates, apart from the revision token.

- [Compact-hover audit](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-hover/hover-audit.json)
- [Actual desktop hover](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-hover/hover-desktop.png)
- [Actual mobile-width hover](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-hover/hover-mobile.png)

This review checks presentation and interactions. Agent-role measurement review
is recorded separately; readable plots do not establish accuracy or uncertainty.

## Stage-boundary follow-up: revision r0006

The time graph now joins the three measured stages with small neutral dotted
guides. The guides use adjacent qualified endpoints only; they add no samples,
IDs, hover values or legend entries. The caption explicitly states this.

The exact `test_web_time_stage_guides_follow_filters_without_creating_observations`
regression passed against the issued `r0006`. Actual stage filtering removes
the corresponding guides without bridging a hidden stage; selecting a different
horizontal quantity removes them. CSV and model contents stay unchanged, and
the SVG export includes the dotted paths. All 33 focused sequence/report unit
tests passed, including invalid-window and conditional-execution cases.

Desktop and mobile screenshots were inspected: ascent, hold and return form a
continuous sequence, the stage colors remain distinct, legends stay above the
data, and captions remain below the chart. There was no document overflow,
JavaScript error or external request. The parent checked the updated PDF demand
figure and verified that model observations, raw samples and metrics are
identical to `r0005`; only revision and time-figure caption changed.

The first browser navigation attempt exceeded 150 s on the memory-constrained
Pi; that browser closed. A bounded retry completed both this report and the
new source-limit report in one browser with one page at a time, then closed
successfully. See [the companion UI review](source-limit-ui-review.md).

- [Transition audit](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-stage-transitions/transition-audit.json)
- [Desktop stage graph](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-stage-transitions/demand-desktop.png)
- [Mobile stage graph](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-stage-transitions/demand-mobile.png)
