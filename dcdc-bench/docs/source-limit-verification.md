# Source-limit test verification

Date: 27 September 2026. Run: `20260927T173043.388477Z_real_75a478`.
Analysis: `a-d0697ec66a0e`. Report: `r0001`.

## Acquisition

The user authorized approaching the existing DP821A CH1 1 A limit. The fixed
procedure kept 24 V input and increased the converter output load adaptively.
Read-only preflight confirmed the configured instrument identities, both
outputs off, local load sensing, and no recorded load fault. The worker then
verified protection readbacks and the independent 720 s source cutoff before
enabling the output.

The detached user service had `Restart=no`, a 690 s runtime limit and a 20 s
stop timeout; the worker deadline was 660 s. No browser or PDF build ran during
acquisition. The run completed in 405.877 s with no errors. Source, load and
source deadline were verified OFF.

The run qualified 22 windows: 21 increasing output loads and one direct return
to 100 mA. It retained 1,332 raw readings in 333 complete cycles; 213 cycles
qualified for the settled means. All 78 conditional requests remain recorded,
including the 56 settings that were not commanded.

At the highest requested output load, the measured means were:

| Quantity | Result |
|---|---:|
| Supply voltage / current | 24.004 V / 0.987285 A |
| Load voltage / current | 11.885658 V / 1.724728 A |
| Input / output power | 23.698780 W / 20.499521 W |
| Path efficiency | 86.5003% |

The endpoint acquisition loop lasted 30.749 s; its accepted queries span
29.622 s. These are different timing quantities. The highest numerical
efficiency occurred at 1.7 A requested load; no significant advantage over the
endpoint is established without an uncertainty budget.

## Independent checks

- [Senior code review](source-limit-code-review.md): fixed limits, identity
  gates, shutdown, one permitted recovery, and report evidence validation.
- 48 combined source-limit/extended fake-instrument tests passed before the
  live run.
- 33 sequence/report tests passed after the report changes. These include
  conditional coverage, source-current metrics and stage-transition guides.
- [Independent results review](source-limit-results-review.md): 50 audit
  assertions passed, all eight acquisition hashes matched, and independently
  recomputed channel means, powers and efficiency matched the official analysis.
- The parent visually inspected all seven pages of the generated PDF. Figures,
  captions, tables, references and page boundaries were present and readable;
  the time figure includes the dotted transition to the return measurement.
  The PDF contains no separate hold figure or invented descending sweep.
- Actual browser results are recorded separately in
  [the UI review](source-limit-ui-review.md).

## Rendering and connection limits

Rendering began only after verified shutdown. This 1 GB Pi needed temporary
768 MiB disk swap in addition to zram while the editor was connected. The
first HTML/PDF build completed successfully, but took about ten minutes under
memory/storage pressure. This is a report-build limitation, not acquisition
time. Generating reports on a computer with more RAM avoids putting that load
on the acquisition host. The detached acquisition and report-server services
survive logout; a client SSH port forward still requires a connection.

This run characterizes the available bench power, not the converter's stated
12 V / 4 A rating. Efficiency includes wiring; calibration, ADC freshness,
temperature, ripple and transient behavior remain unqualified.
