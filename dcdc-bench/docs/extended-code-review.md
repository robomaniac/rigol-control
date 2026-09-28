# Extended characterization: independent code review

Reviewed: 27 September 2026.

## Scope and verdict

Reviewed the fixed 24 V, 50–500 mA ramp/hold/return procedure in
[`extended.py`](../src/dcdc_bench/extended.py), its use of the existing drivers,
transport locking and durable run storage, the pilot identity correction,
and the related analysis, report renderer, JavaScript and CSS changes.

**No unresolved acquisition blocker was found for this fixed procedure.**
This review does not qualify the general real-hardware backend, other electrical
limits, manufacturer acceptance, or measurement uncertainty. Browser/PDF visual
review and independent numerical review are recorded separately.

## Findings corrected

- Cleanup can control an instrument only after its configured serial is verified;
  an unverified transport is closed without sending control commands.
- Hold timing is initialized before startup, so an early abort preserves the
  original failure instead of raising an uninitialized-variable error.
- Cleanup protects its independent shutdown attempts against repeated termination
  signals, including SIGINT and SIGHUP.
- The source deadline stays armed if explicit source OFF cannot be verified.
  Successful cancellation is followed by another source OFF and final readback.
  A source failure does not prevent the load shutdown attempt.
- Actual hold duration is retained for partial and completed holds.
- Four measurement queries now precede per-record disk synchronization. Their
  original timestamps and raw responses remain separate. Partial cycles survive
  a later query failure; no cycle is accepted until every captured row is durable
  and the unchanged timing, electrical and instrument-status guards pass.

## Analysis and report checks

- The plan contains 37 observation windows at 10 distinct requested conditions.
  The summary distinguishes repeated hold windows from additional load settings.
- Time coordinates derive from accepted query timestamps. Startup readings do
  not move the time origin, and presentation annotations do not mutate analysis
  evidence.
- Hold drift and the first/final load comparison require qualified points,
  matching requested conditions and retained timing. Summaries reference the
  corresponding metrics and figures. Differences carry no statistical-significance
  or thermal-equilibrium claim.
- The method distinguishes commanded duration, recorded phase duration and query
  span. Hold bins explicitly inherit settling. Dwell wording comes from the plan;
  queried readings are not described as proven fresh ADC conversions.
- The keyboard point inspector presents the same aggregate values without requiring
  hover. Its semantic table uses `textContent`; mA conversion and rounding affect
  display only. Evidence and CSV precision are unchanged.
- Embedded JSON, report prose and Plotly labels follow the existing escaping
  boundaries. The mobile grid permits narrow controls with `minmax(0, 1fr)`.

The final no-load wording correction was verified: input consumption is reported
only when a qualified zero-current point exists. This loaded-only run explicitly
states that no-load consumption was not measured.

## Verification evidence

- Independently checked the pure plan, its hash and fixed electrical envelope.
- Reviewed the acquisition agent's 34 passing fake-instrument tests, including
  slow storage, partial-query failure, identity mismatch, interruption, guard
  failure and independent shutdown. These exercise real driver classes over a
  fake transport and do not contact equipment.
- Root reports that repeat run `20260927T093948.075493Z_real_42e971` completed
  all 37 windows in 503.54 s, including a 185.67 s hold, with no run errors and
  verified OFF states for source, load and source deadline. Numerical validation
  belongs to the separate results review.
- Root reports the full non-browser regression suite passed: **214 passed,
  10 deselected, 102.87 s**. Earlier subset counts overlap this suite and must not
  be added to its total. The deselected browser/PDF checks belong to the separate
  artifact review.

### Final report refinements

The following changes were source-reviewed after the full-suite run:

- Browser startup has a bounded 120-second allowance; image and close deadlines
  remain separate. This affects report generation only, after acquisition.
- The extended report's PDF page break now precedes the DUT section. Other report
  layouts retain their prior section break.
- `PointTiming` carries the recorded inherited-settling flag. Only explicitly
  flagged hold windows are excluded from the displayed **new-load settling**
  range; their original durations remain in the model. Three-significant-figure
  display and conversion of skew to milliseconds do not alter raw evidence.
- The interactive legend is anchored above the plotting area with additional
  top space and chart height. This changes layout, not traces or exports' data.

Root reports **21 focused report tests passed** after the method/page changes,
valid JavaScript syntax, and successful revision `r0003` HTML/PDF generation.
Those 21 checks overlap the full suite. The UI reviewer separately checks the
mobile layout and all seven PDF pages; this source review does not certify their
visual appearance.

Revision `r0004` additionally synchronizes the chart container's CSS height with
the exact Plotly layout used by `draw()`. The layout is computed once before
`Plotly.react`, so the document reserves the same height as the rendered chart
and the caption follows it. This source change preserves data, filters and export
semantics. The added browser regression checks caption position against the SVG
bottom at 390 px and 1365 px widths, plus horizontal overflow. Final-artifact
geometry verification is assigned to the UI reviewer; no browser checks were
run as part of this source-review follow-up.

**Final source-review verdict: no unresolved blocking finding in the reviewed
fixed acquisition and reporting changes.** Browser/PDF quality and independent
numerical validation remain separate review responsibilities.

The reviewer performed no instrument calls, browser runs, report rendering or
tests during live acquisition.
