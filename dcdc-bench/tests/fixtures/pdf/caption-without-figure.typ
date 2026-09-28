// PDF-02 fixture: caption-like text on a page that carries no figure drawing.
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-caption])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, it) }
#set par(justify: false)

= Results
Metrics from qualified channel means over accepted complete acquisition cycles.

#pagebreak()

Figure 1: SYNTHETIC. A caption whose figure did not reach this page.

Measured values are aggregated settled DC point results.
