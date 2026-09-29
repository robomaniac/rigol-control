// PDF-02 fixture: text placed beyond the right and bottom page edges.
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-clipped])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, it) }
#set par(justify: false)

= Summary
This issued summary is fixed. Reader filters change exploratory views only.

#place(dx: 500pt, dy: 100pt)[Text placed beyond the right page edge]
#place(dx: 0pt, dy: 800pt)[Text placed beyond the bottom page edge]
