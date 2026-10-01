// PDF-02 fixture for the best-effort deviation sheet (renderer._deviation_sheet_section):
// the renderer emits the sheet's heading, then `#block(breakable: false)[ table,
// basis legend, poll note, statement ]`, the pattern already used for the DUT
// section. Here the page is filled so that only the heading and about one row
// would fit at the bottom of page 1. The unbreakable block moves whole to
// page 2 and the sticky heading travels with it: the compiled fixture must
// report neither `orphan-heading` nor `table-split-after-first-row`, and page 2
// must hold the heading and the complete seven-column table.
#import "print-tables.typ": dcdc-paginate-table
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-deviation-sheet])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, sticky: true, it) }
#set table(inset: 6pt, stroke: none)
#set par(justify: false)

#let body-width = 210mm - 36mm
#let body-height = 297mm - 32mm
#let columns = (12%, 14%, 22%, 11%, 11%, 12%, 18%)
#let header = table.header([Parameter], [Clause asks], [This bench], [Mechanism], [Measured by], [Classification], [Note])
#let rows = (
  ([drop level (V)], [4.5 ± 0.2 V (ISO)], [commanded 4.5 V; may not be reached before the restore command; unloaded fall < 800 ms (DS5); not measured at the converter], [LAN voltage step], [not measured], [unknown until measured], [The converter drops out below 9 V and draws standby current, so the fall approaches the unloaded case; depth at the converter not measured]),
  ([drop duration (s)], [100 ± 5 ms (ISO)], [commanded 100 ms; host-timed 103 ms; bounded 0–270 ms (derived)], [LAN voltage step], [host clock (write timestamps)], [unknown until measured], [Two LAN writes, each 4–55 ms transport (LAN) and up to 118 ms processing (DS5); interval between the two write timestamps on the Pi]),
  ([edge max (s)], [at most 10 ms (ISO)], [< 110 ms loaded (DS5); not measured at the converter], [supply slew], [not measured], [not met, documented], [The supply's loaded fall and rise bound exceeds the clause edge]),
  ([recovery (s)], [10 ± 0.5 s (ISO)], [commanded 10 s; host-timed 10.021 s; bounded 10–10.173 s (derived)], [LAN voltage step], [host clock (write timestamps)], [met], [LAN worst case +173 ms lies inside ± 0.5 s]),
  ([operating mode], [3.4 (ISO)], [bounded light load; not measured at the converter], [steady level], [not measured], [approximated], [Operating mode 3.4 realised as a fixed light load within the bench envelope]),
)

// Fill page 1 so that the heading and roughly one table row would still fit below.
#let introduction(body) = context {
  let head-only = measure(block(width: body-width, table(columns: columns, header, table.hline()))).height
  let head-and-one = measure(block(width: body-width, table(columns: columns, header, table.hline(), ..rows.at(1)))).height
  let heading-height = measure(block(width: body-width, heading(level: 2, outlined: false, numbering: none)[Deviations])).height + 1.7em
  block(width: 100%, height: body-height - heading-height - head-and-one - 0.3 * head-only, body)
}

#introduction[
  = Results
  Metrics from qualified channel means over accepted complete acquisition cycles.
  Positive power enters the input boundary and leaves the output boundary.
]

#show table: dcdc-paginate-table

== Deviations from ISO 16750-2 clause 4.6.1.1, variant A
#block(breakable: false)[
  #table(columns: columns, header, table.hline(), ..rows.flatten())

  Basis tags: ISO = ISO 16750-2 clause text or figure; DS5 = supply datasheet bound; derived = derived from the tagged bounds; SEED = seeded bench profile or protective policy.

  Observed output states come from about 1 s polling; states shorter than the poll interval are not visible to this bench.

  *No clause-compliance result is claimed; the sheet records deviations.*
]

Uncertainty: no applicable validated uncertainty budget is supplied.
