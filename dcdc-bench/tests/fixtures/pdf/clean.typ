// PDF-02 fixture: a well-paginated document. Same page geometry, header and
// numbering style as the issued reports. The long table is meant to split
// with several rows on each page; the figure keeps its caption.
#set page(paper: "a4", margin: (x: 18mm, y: 16mm), numbering: "1",
  header: text(size: 7pt, fill: rgb("516677"))[SYNTHETIC · FIXTURE-DUT · run-fixture-clean])
#set text(font: "Liberation Sans", size: 9.5pt, fill: rgb("183047"))
#show heading: it => { block(above: 1.2em, below: 0.5em, it) }
#set table(inset: 6pt, stroke: none)
#set par(justify: false)

#align(center)[#text(size: 14pt, weight: "bold")[DC–DC converter characterization · FIXTURE-DUT]]
#align(center)[#text(size: 12pt, weight: "bold")[SYNTHETIC · FIXTURE-DUT · run-fixture-clean · analysis-fixture]]

= Summary
This issued summary is fixed. Reader filters change exploratory views only. Three of three
requested operating points produced qualified synthetic DC results.

#table(
  columns: (30%, 40%, 30%),
  table.header([Result], [Value], [Conditions and evidence]),
  table.hline(),
  [Highest observed path efficiency], [86.20 %], [24 V input, 0.5 A requested load],
  [Lowest qualified load], [0.100 A], [24 V input],
  [Points], [3], [all qualified],
)

== Coverage
Only qualified measurements are shown. Best observed efficiency describes the measured grid;
it is not an interpolated optimum.

= Results
== Efficiency
#figure(
  box(image("fixture-plot.svg", width: 100%)),
  caption: [SYNTHETIC. Fixture vector plot of path efficiency against output current. Markers are qualified DC means.],
)

Measured values are aggregated settled DC point results. No waveform, thermal, calibration or
uncertainty claim is inferred from ordinary DC polling.

#pagebreak()

= Appendix: point results
Every requested operating point of the issued model in report order.

#table(
  columns: (25%, 25%, 50%),
  table.header([Point], [Requested load], [Qualification and reason]),
  table.hline(),
  ..for i in range(1, 61) { ([p#i], [#i mA], [valid; settled within the declared window]) }
)

Uncertainty: no applicable validated uncertainty budget is supplied.

*Run:* run-fixture-clean \
*Analysis:* analysis-fixture
