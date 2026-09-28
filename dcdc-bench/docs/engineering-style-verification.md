# Engineering figure style verification

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Reviewed on 27 September 2026 against measured run
`20260927T185631.575651Z_real_eb3bcd`, presentation revision **r0005**.

## Presentation changes

Figures use **Efficiency**, **Input Current**, **Load Regulation** and
**Power Loss**. HTML and static plots share these condition styles:

| Input condition | Color | Line | Marker |
| --- | --- | --- | --- |
| 12 V | Blue `#0072B2` | Solid | Circle |
| 24 V | Vermilion `#D55E00` | Dashed | Square |
| 36 V nominal | Magenta `#CC33AA` | Dotted | Diamond |

Only 24 V and nominal 36 V have measured curves in this run; nominal 36 V was
programmed to 35.8 V. Reserving the 12 V style creates no trace. The earlier
unsuccessful 12 V startup remains explained in the summary.

Regulation plots include **Nominal 12 V**; input-current plots include the
recorded **Supply limit 1 A**. Initial ranges include the reference, qualified
values and supplied display bands. These references do not establish measured
tolerances. Interactive zoom overrides the defaults, and Reset restores them.

## Passed checks

- **19 focused renderer tests:** stable colors/shapes in subsets and standalone
  reports, stage styles, preserved measurements/gaps, shared HTML/static
  payloads, valid references and invalid-reference rejection.
- **Actual offline browser:** concise headings; absent-12-V explanation;
  matching Plotly colors/dashes/markers in all four figures; no fabricated
  12 V curve; reference shapes, labels and ranges; manual zoom and Reset.
- **Issued artifacts:** HTML/PDF hashes match the successful manifest. All
  canonical SVGs contain both expected curve colors and dash patterns; the
  regulation and current figures retain their reference labels.
- **Evidence unchanged:** point results and embedded raw samples are exactly
  equal between r0004 and r0005.
- **Visual review:** the canonical regulation figure has clear orange/magenta
  curves and a readable nominal reference. Its reviewed image is retained.

## Browser scope and retained evidence

The six-minute browser budget expired after the checks above. Cold launch and
initialization consumed approximately 5 minutes 47 seconds. The browser
closed; no page errors or external requests were recorded. This is a partial
browser run, not a full interaction-suite pass.

Legend-click, compact-hover, interactive SVG-export and mobile screenshot
repetitions were not reached. Those existing interactions had earlier review;
this revision's JavaScript was inspected for registry use, zoom precedence and
preservation of reference annotations during SVG export. Source inspection and
canonical SVG checks are not presented as a browser export test. No browser
screenshots were captured in this bounded run.

The run's `reviews/engineering-style/` directory contains `audit.json`,
`static-checks.json`, the acceptance script and log, and
`canonical-load-regulation.png`. The coordinating agent owns report
publication. No hardware was accessed or acquisition repeated for this review.

## Issued revisions and downloads

| Local report alias | Current revision | Document build |
| --- | --- | --- |
| `12t12-efficiency` | `r0005` | Canonical Plotly/Quarto build |
| `12t12-startup` | `r0005` | Verified canonical figure cache; native document revision |
| `12t12-workflow` | `r0003` | New canonical figures; native document revision |
| `12t12-extended` | `r0007` | New canonical figures; native document revision |
| `12t12-source-limit` | `r0002` | New canonical figures; native document revision |

All five successful manifests and HTML/PDF/vector hashes were verified before
publication. Points, calculated metrics, summaries and analysis identifiers
match their prior issued revisions exactly. Native revisions additionally
verify unchanged PDF content outside the updated figures; their build manifests
record the source documents, figure cache/rendering and derivation script.
The earlier revisions remain retained. Startup `r0004` is an explicitly recorded
interrupted document build and is not served.

The existing comparison, extended-test and source-limit ZIP bundles now contain
the corresponding new reports. Their measurement and analysis entries were
verified unchanged. The completed workflow job links to `r0003`.

The separate analysis/sequence/startup regression selection passed **63 tests**.
This is separate from the 19 renderer checks above; it is not a rerun of the
whole project's earlier acceptance suite.
