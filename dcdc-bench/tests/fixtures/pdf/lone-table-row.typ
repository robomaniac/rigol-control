// PDF-02 fixture: with this page geometry and Typst 0.15 the 38-row table
// spills exactly its last row onto page 2 (under the repeated header).
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-lone-row])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, it) }
#set table(inset: 6pt, stroke: none)
#set par(justify: false)

= Appendix: point results
Every requested operating point of the issued model in report order.

#table(
  columns: (25%, 25%, 50%),
  table.header([Point], [Requested load], [Qualification and reason]),
  table.hline(),
  ..for i in range(1, 39) { ([p#i], [#i mA], [valid; settled within the declared window]) }
)

Uncertainty: no applicable validated uncertainty budget is supplied.
