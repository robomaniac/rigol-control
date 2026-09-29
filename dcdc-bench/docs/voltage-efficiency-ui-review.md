# Voltage-efficiency report: UI and UX review

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Date: 27 September 2026.  
Run: `20260927T185631.575651Z_real_eb3bcd`  
Analysis: `a-e2e7cc8e0d01`; final presentation revision: `r0004`.

**The focused interaction, equipment-table and corrected layout checks passed.**
The earlier 12 V startup produced no qualified efficiency result. The report
explains that outcome and plots the measured 24 V and nominal 36 V conditions;
the latter was programmed at 35.8 V.

## Equipment and table layout

- Connected equipment has five columns: **Role**, **Equipment Model**,
  **Serial Number**, **Firmware**, **Manufacturer**. Both rows were compared
  with the report's recorded instrument identities and visually inspected.
- DUT identity and ratings use the same 38/62 column proportions. Their value
  columns matched exactly at **567.390625 px** on the 1365 px desktop viewport
  and **153.234375 px** on the 390 px mobile viewport.
- On mobile, the equipment table scrolls inside its **348 px** container;
  its 660 px table does not expand the page.
- The first mobile check found a real defect: an unbroken provenance hash
  widened the document to 535 px. A bounded second browser session confirmed
  that wrapping long paragraph/list words reduces the document to exactly
  **390 px**. The original finding remains in the audit record.

## Curves and interaction

| Check | Observed result |
| --- | --- |
| Voltage colors | 24 V stays teal (`#168477`); nominal 36 V stays purple (`#7753a2`) in all four interactive and static figures. |
| Unqualified 12 V attempt | Explained in the summary and appendix, with no invented 12 V trace or efficiency value. |
| Filtering | Selecting nominal 36 V retains its color and excludes 24 V from the selected-curve CSV. |
| Real pointer hover | Three compact lines show the nominal/35.8 V condition, current and efficiency. The mobile tooltip measured about 153 × 57 px and remained on-screen. |
| Point inspection | Clicking the measured marker selects the matching point and exposes its nine aggregate results. |
| CSV button | Actual download matches the export API; programmed voltage, condition label and numerical precision survive. |
| SVG button | Actual download contains vector output, run identity and the nominal/35.8 V label. |
| Offline runtime | No JavaScript page errors or external requests in either browser session. |

For example, the inspected 0.5 A requested point at nominal 36 V showed
**499.4 mA / 81.99%** on hover. Its CSV retained `0.499448 A` and
`81.9855690415388%`, plus measured input `35.797 V` and programmed input
`35.8 V`. Formatting does not replace evidence with rounded values.

The reviewer inspected the desktop equipment image and the mobile DUT tables,
equipment table, both voltage curves and actual hover images. The two voltage
legends remain above the data; the compact tooltip leaves the curve readable.

## PDF and presentation revision

The eight-page PDF retains vector figures. The review checked PDF text,
equipment fields, absence of rasterized graphs and both voltage colors.
Pages 1, 2, 3 and 5 were visually inspected: summary, DUT tables, connected
equipment/method, and efficiency/source-current graphs.

Revision `r0002` split the DUT identity table between pages 1 and 2. The corrected
`r0003` starts the DUT section on page 2 and keeps both DUT tables together.
Their value-column positions are both **244.4504 pt**. The page count stays
eight, and no text is clipped in the inspected pages. The parent independently
rendered and inspected the corrected DUT page too.

The final browser retry exercised `r0002` with the exact wrapping rule later
included in `r0003`. A separate artifact check proved that `r0003` HTML differs
only by that CSS rule and revision strings, its report model differs only by
revision, and all eight SVG/PDF figure assets are unchanged. The native Typst
revision changes only the revision label and the DUT page break. The final
HTML/PDF hashes match their build manifest. This does not claim a third browser
session against `r0003`.

Final revision `r0004` changes “between the three curves” to “between input
conditions,” consistent with the missing qualified 12 V curve, plus the
revision labels. The parent verifies those exact deltas, final PDF text and
artifact hashes before packaging. It does not change measurements, curves or
layout rules. The browser and visual evidence above remains applicable; this
does not claim another browser session or a second full visual pass for `r0004`.

## Scope and host limitation

The 17 focused renderer and JavaScript tests passed, including missing fields,
escaping, voltage colors, continuation status, hover labeling and CSV precision.
This review did not repeat the entire historical browser test suite. The
reviewer implemented presentation changes; acquisition and results have
separate reviews.

Both browser sessions ran sequentially after outputs were verified OFF and
closed in `finally`. The 1 GB Pi experienced substantial page-loading delay
under memory/storage pressure. The bounded retry used one browser process.
Successful layout checks do not establish that this Pi can open the large
self-contained report promptly while its editor is consuming memory.

## Review evidence

- [Original desktop audit and retained mobile finding](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/audit.json)
- [Focused mobile retry](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/mobile-retry-audit.json)
- [Revision and PDF verification](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/r0003/audit.json)
- [Desktop equipment](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/desktop-equipment.png)
- [Mobile aligned DUT tables](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/mobile-dut-fixed.png)
- [Mobile voltage curves](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/mobile-both-voltage-curves.png)
- [Mobile compact hover](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/mobile-hover-fixed.png)
- [Corrected PDF DUT page](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/r0003/pdf-page-2.png)
- [PDF equipment page](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/r0003/pdf-page-3.png)
- [PDF efficiency and supply-current graphs](../runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reviews/ux-voltage/r0003/pdf-page-5.png)
