// PDF-02 fixture: the theme's table rule (templates/theme/print-tables.typ)
// applied to the layout of split-table-unguarded.typ, where exactly the
// header and one body row of a nine-row table (about two thirds of the page
// body) would fit at the bottom of page 1 under a sticky heading. The rule
// measures the head against the space left and, because the table fits on
// one page, wraps it in an unbreakable block: the table and its heading move
// whole to page 2, no page holds a single row, and the heading is not
// orphaned. The compiled fixture must report neither
// `table-split-after-first-row` nor `orphan-heading`.
#import "print-tables.typ": dcdc-paginate-table
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-split-guarded])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, sticky: true, it) }
#set table(inset: 6pt, stroke: none)
#set par(justify: false)

#let body-width = 210mm - 36mm
#let body-height = 297mm - 32mm
#let columns = (30%, 25%, 45%)
#let header = table.header([Metric], [Value], [Actually covered conditions])
#let row(i) = ([Load regulation span], [0.10#i % of nominal],
  [#i V requested input; covered load 0–1 A over a settled window of thirty samples with the source in constant-voltage mode and the load in constant-current mode])
#let rows = range(1, 10).map(row)

// Same introduction block as the control fixture; the tables it measures are
// built before the table rule below is in force.
#let introduction(body) = context {
  let head-only = measure(block(width: body-width, table(columns: columns, header, table.hline()))).height
  let head-and-one = measure(block(width: body-width, table(columns: columns, header, table.hline(), ..rows.at(0)))).height
  let one-row = head-and-one - head-only
  let heading-height = measure(block(width: body-width, heading(level: 2, outlined: false, numbering: none)[Regulation])).height + 1.7em
  block(width: 100%, height: body-height - heading-height - head-and-one - 0.5 * one-row, body)
}

#introduction[
  = Results
  Only qualified measurements are shown. Best observed efficiency describes the measured grid;
  it is not an interpolated optimum.
]

#show table: dcdc-paginate-table

== Regulation
#table(columns: columns, header, table.hline(), ..rows.flatten())

Uncertainty: no applicable validated uncertainty budget is supplied.
