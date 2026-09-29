// PDF-02 fixture: a heading forced to the bottom of page 1 while its
// introductory paragraph starts on page 2.
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-orphan])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, it) }
#set par(justify: false)

= Summary
This issued summary is fixed. Reader filters change exploratory views only.

= Setup and method
#pagebreak()
The supply powers the converter input at 24 V. The electronic load draws 0.1, 0.25 and 0.5 A
from the converter output. Input and output power are measured at the declared boundary.
