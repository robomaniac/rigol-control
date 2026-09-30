// PDF-02 fixture, control case for split-table-guarded.typ: the same page
// geometry, a sticky level-2 heading, and a nine-row table with wrapped
// condition text (about two thirds of the page body) placed so that exactly
// its header and first body row fit at the bottom of page 1. Without the
// theme's table rule Typst opens the table there and continues on page 2:
// the checker's `table-split-after-first-row`.
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-split-unguarded])
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

// The introduction sits in a block of computed height that leaves room for
// the heading, the table header and one and a half body rows, so the header
// and exactly one row fit before the page ends. Nothing here depends on a
// laid-out position, so the layout settles in one pass.
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

== Regulation
#table(columns: columns, header, table.hline(), ..rows.flatten())

Uncertainty: no applicable validated uncertainty budget is supplied.
