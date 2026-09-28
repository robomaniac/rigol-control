# Extended-test verification record

Date: 27 September 2026. Bench: Raspberry Pi 3B+, Rigol DP821A CH1,
and load reporting DL3031A. The physical load model/modification and full
measurement uncertainty remain unverified.

## Preflight and independent shutoff

The configured source/load serials matched. Both outputs were off, with
0 V at the source and approximately 0.000736 V at the disabled load.
The load used local sensing and its questionable-condition register was zero.

With 0 V programmed, a five-second source delay program enabled the channel,
then disabled it without further commands. Configuration and readbacks are
retained locally in `Data/Logs/extended-preflight.jsonl` and
`Data/Logs/extended-timer-proof.json`. The extended worker separately verifies
its own 720-second, one-cycle, end-OFF program before each start.

## First extended attempt

Run: `20260927T093111.072469Z_real_7a0fd6`.

This attempt qualified 19 of 37 observation windows before aborting during
the 500 mA hold. Cycle `c000239` spanned 777.600 ms, exceeding the 750 ms
qualification limit. The four query calls used 24.954 ms; gaps between them
used 752.646 ms. Per-reading persistence was occurring between those queries.
The exact split between storage synchronization and host scheduling was not
separately instrumented. There was no recorded electrical guard violation.

The independent reviewer verified all eight acquisition hashes and the final
OFF states of the source, load, and source delay program. The attempt is
preserved; it is not merged into the repeat's results.

The corrected worker captures all four readings before disk synchronization.
It retains partial readings after a later query failure and accepts no cycle
until all its raw records are durable. The original timing and electrical
limits remain unchanged.

## Code review and tests before the repeat

The senior reviewer examined identity matching, process locks, fixed limits,
protection readbacks, measurement qualification, deadlines, interruption, and
independent shutdown. Found defects were corrected before the real run:

- Cleanup cannot command an instrument whose configured serial was not verified.
- An early abort does not reference an uninitialized hold timer.
- Cleanup tolerates repeated termination signals.
- Failed source OFF verification preserves the independent source deadline.
- Successful deadline cancellation is followed by another source OFF/readback.
- Partial hold duration remains recorded after an abort.

The fixed runner passed 32 initial fake-instrument tests and then **34 tests**
after the persistence change. The latter includes 300 ms injected storage
delays and a failed third measurement query. Real driver classes are exercised
over an in-memory SCPI transport; these tests do not access the bench.

Separate report/analysis and original pilot regression checks passed
**55 tests**, including two identity-mismatch cases and matching-load return
comparison qualification. These counts overlap later full-suite runs and
must not be summed as distinct tests.

## Connection reliability

User lingering was enabled and verified; the report server now survives logout.
The acquisition service runs once with `Restart=no`, a 690-second service
deadline, and a 20-second stop timeout. The worker's own deadline is 660 seconds;
the source-side limit is independent of the host.

No browser or PDF build runs concurrently with acquisition. See the measured
resource/storage findings in [Pi reliability](../../Documentation/Pi-Reliability.md).

## Completed repeat

Run: `20260927T093948.075493Z_real_42e971`.
Analysis: `a-4a0763ae9add`.

The repeat completed all **37 observation windows**, with **331 accepted
complete cycles**, in **503.537 seconds**. The sustained-load interval lasted
**185.667 seconds**. There were no execution errors. Source, load, and source
delay program were independently verified OFF.

The independent results reviewer recomputed the measurements from raw records,
verified the acquisition hashes, and matched every production mean and power/
efficiency value exactly. Maximum accepted four-query span was **80.240 ms**,
below the unchanged 750 ms limit.

After shutdown, the full ordinary regression suite passed:

```text
214 passed, 10 deselected in 102.87s
```

Command: `.venv/bin/python -m pytest dcdc-bench/tests -m 'not browser and not pdf' -q`.
See [code review](extended-code-review.md) and
[independent measurement review](extended-results-review.md).

The first document-build revision failed during its 45-second browser startup
allowance. A direct browser check succeeded in 27.26 seconds; starting the
browser with the local Plotly runtime took about a minute. The report-only
startup allowance was raised to 120 seconds. This does not change any acquisition
deadline, measurement timing limit, or finalized evidence. Temporary extra swap
is used only for serial document generation/review, after outputs are off.

## Report refinements and focused checks

The final method table distinguishes settling after a changed load from hold
windows that inherit the preceding settled state. All 18 inherited flags match
the run record; original timings remain in the model. New-load settling is
displayed as 5.59–6.02 seconds and the accepted query-span range as 33.7–80.2 ms.

After these method and pagination changes, the focused analysis/report checks
passed **21 tests** in 9.73 seconds:

```sh
.venv/bin/python -m pytest dcdc-bench/tests/test_sequence_report.py \
  dcdc-bench/tests/test_method_and_refs.py dcdc-bench/tests/test_reporting.py -q
```

This is a later rerun of a subset of the ordinary suite, not 21 additional
distinct tests. The full browser/PDF demo suite from the earlier M1 milestone
was not rerun here. The measured extended report instead received the actual
artifact checks described in the [UI review](extended-ui-review.md).

That review exercised pointer hover/click, keyboard selection, stage and metric
filters, full-precision CSV with metadata, and vector export on revision r0002.
It caught narrow-screen legend overlap and an orphaned PDF table tail. Revision
r0003 corrected both; all seven PDF pages were visually inspected. A subsequent
HTML caption-overlap finding led to matching the chart container height to its
Plotly layout and adding a desktop/mobile geometry regression.

The completed revision **r0004** has an 8,611,928-byte self-contained HTML and
a 138,307-byte, seven-page PDF. Both artifact SHA-256 values match their successful
build manifest. An independent entire-model comparison against r0003 found
exactly one changed field: `report_revision`. Every extracted PDF word and its
bounding-box coordinates match the visually approved r0003 PDF, apart from the
revision token. The final layout correction changes HTML presentation only.

The final offline Chromium check on r0004 passed at 1365 px, then 390 px,
then 1365 px again: all five SVGs and their containers were 465 px high,
captions followed the charts, legends stayed above the observations, and the
document did not overflow horizontally. The exact newly added caption-geometry
regression function also passed against this measured report in the same
browser. This was a focused artifact check, not a rerun of the whole demo suite.
There were no JavaScript errors or external network requests. The browser was
closed before cleanup and packaging.

Temporary report-build swap was disabled and its file removed after the final
browser closed. `/proc/swaps` then listed only the original `/dev/zram0`.
No permanent swap configuration was changed. The downloadable archive contains
the final HTML/PDF, vector figures, full-precision point CSV and metadata,
original acquisition evidence, and these review records. The original timing-
aborted attempt remains separate on the Pi.

## Hover readability follow-up — r0005

The user identified an oversized tooltip that obscured the curve. The earlier
interaction review had confirmed access to the data but had missed this usability
problem. Hover now contains three lines: test context, the plotted horizontal
value, and the plotted vertical value. It uses a white background, dark text,
left alignment, and no duplicate series-name bubble. Display rounding is local
to hover; point results and exported data retain their prior precision.

The detailed point inspector now includes input voltage/current, output deviation,
and the recorded time interval as well as its existing measurements. No evidence
was removed to make the tooltip smaller.

Revision r0005 was generated by the normal report builder. Its HTML is 8,613,136
bytes and its PDF is 138,308 bytes; artifact and JavaScript source hashes match
the successful build manifest. The independent results reviewer found that its
entire report model differs from r0004 only in `report_revision`. All seven PDF
pages retain exactly the same extracted text and word coordinates, apart from
that revision token. The senior source review found no change to data or exports.

The exact new compact-hover browser regression passed on the issued r0005:
desktop/mobile tooltip bounds and colors, three lines, alternate horizontal
quantity labels, mouse/keyboard inspector access, and unchanged full-precision
CSV/model values. The reviewer also moved the actual pointer to the user's
300 mA decreasing-load point with all three curves visible. Its tooltip measured
155.3 × 57.2 px on both screen sizes, showed 299.6 mA and 81.44%, and fit inside
the viewport. Both screenshots were visually inspected. This was a focused
follow-up, not a rerun of the complete browser suite.
