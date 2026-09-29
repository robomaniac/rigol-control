# Source-limit report: UI and UX review

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Date: 27 September 2026.  
Run: `20260927T173043.388477Z_real_75a478`  
Analysis: `a-d0697ec66a0e`; report revision: `r0001`.

**Result: no blocking findings in the focused checks below.**

The actual issued HTML was exercised offline after both instrument outputs were
confirmed off. The review covers the new chronological stage guides, source
current figure, point inspector, selected-curve exports and desktop/mobile
layout. It does not claim a repeat of the entire historical browser suite.

## What the reader sees

- The time graph shows demand increasing to about 1.725 A, then a direct return
  to about 100 mA. One neutral dotted line joins those stage endpoints. It has no
  extra markers, hover result or legend entry. The caption says: “Dotted lines
  join stage boundaries; no extra samples.”
- “How close did the supply get to its 1 A limit?” plots measured supply current
  against measured output current. Input and output current are distinguished
  on the axes and in the tooltip.
- At the endpoint `p0066`, the actual pointer displayed three lines: increasing
  demand at 24 V, output current 1.725 A, and input current 987.3 mA. The tooltip
  was white with dark text, approximately 150.5 × 57.2 px on both screen sizes.
- Clicking that marker selected its nine aggregate results and recorded time
  interval. The inspector showed 987.285 mA input current, 86.5003% path
  efficiency, and the 332.597–362.219 s accepted-query span. Display rounding
  does not rewrite the underlying values.
- The point selector retains all 78 conditional candidates: 22 executed windows
  and 56 settings not run. The plotted curves reference only the 22 executed
  windows; the return is one measurement, not an invented descending sweep.

## Actual browser checks

The exact regression
`test_web_time_stage_guides_follow_filters_without_creating_observations` passed
against this issued report in the existing offline browser:

| Check | Result |
| --- | --- |
| Stage guide endpoints | Exactly the two retained measurements; no fabricated IDs or samples. |
| Actual stage checkbox | Hiding a stage removes its guide; no connection is invented around it. |
| Actual horizontal-axis selector | Guides disappear for output-power x and return for elapsed time. |
| Selected-curves CSV | Unchanged through filtering/reset; no guide becomes a data row. |
| Exported SVG | Contains the neutral dotted guide as a vector path. |
| Embedded report model | Byte-equivalent JSON before and after the interactions. |
| Desktop, 1365 px | Document width 1365 px; legend above data; caption below the chart SVG. |
| Mobile, 390 px | Document width 390 px; legend above data; caption below the chart SVG. |
| Runtime isolation | No JavaScript page errors or external network requests. |

The reviewer inspected all four new screenshots: demand over time and actual
source-current hover, each at desktop and mobile widths. The labels, endpoint,
return, compact tooltip and captions remain readable.

The 33 focused sequence/report unit tests also passed. Those tests cover failed
or omitted windows, changed input voltage, nonfinite values, chronological
adjacency, malformed execution records, conditional candidates never commanded,
and preservation of observations/metrics. The reviewer implemented the guide
presentation; the separate code and results reviews cover the acquisition and
evidence model.

## PDF and host performance

The parent reviewed every page of the seven-page PDF and verified the HTML/PDF
hashes against the build manifest. That review found no clipped text, missing
references, orphan page or invented hold/descending-sweep figure; see
[verification](source-limit-verification.md).

The first browser attempt, opening the older extended report, exceeded its
150 s navigation deadline on the 1 GB Pi. Its browser was closed before a
bounded retry. With the source-limit report first and 300 s startup limits,
the actual checks above completed. No report artifacts were edited for the
retry. This resource limitation should not be confused with an interaction
test pass on the failed attempt.

## Older ramp/hold/return report

The same browser then opened revision `r0006` of run
`20260927T093948.075493Z_real_42e971`, after closing the source-limit page.
The exact transition regression passed there too. Its two guides join the
ascent to the hold, and the hold to the return; all 37 measured windows retain
their original IDs and values. Desktop/mobile screenshots were inspected and
show a continuous sequence with separate stage colors, unobscured legends and
readable captions. The parent separately checked the changed PDF demand figure
and confirmed the older model differs only by revision and caption text.

Both reports completed with no JavaScript errors or external requests. The
context and browser closed in `finally`; the audit process exited successfully.

## Local evidence

These review files live under the ignored run directory:

- [Machine-readable audit](../runs/real-source-limit/20260927T173043.388477Z_real_75a478/reviews/ux-stage-transitions/transition-audit.json)
- [Desktop demand graph](../runs/real-source-limit/20260927T173043.388477Z_real_75a478/reviews/ux-stage-transitions/demand-desktop.png)
- [Mobile demand graph](../runs/real-source-limit/20260927T173043.388477Z_real_75a478/reviews/ux-stage-transitions/demand-mobile.png)
- [Desktop actual hover](../runs/real-source-limit/20260927T173043.388477Z_real_75a478/reviews/ux-stage-transitions/source-current-desktop.png)
- [Mobile actual hover](../runs/real-source-limit/20260927T173043.388477Z_real_75a478/reviews/ux-stage-transitions/source-current-mobile.png)
- [Older report transition audit](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-stage-transitions/transition-audit.json)
- [Older report mobile graph](../runs/real-extended/20260927T093948.075493Z_real_42e971/reviews/ux-stage-transitions/demand-mobile.png)
