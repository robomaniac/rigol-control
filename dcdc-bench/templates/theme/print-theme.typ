// Print theme "datasheet" for the PDF (implementation brief §12.2, §12.3,
// §12.6): US Letter or A4, one accent colour, Liberation Sans 9 pt, numbered
// sections with the number hanging in the left margin and the text indented
// (the organisation of instrument-vendor user's guides), a header band with
// the document title and DUT on the left and the evidence label, recording
// time and running section on the right, a footer with the run identity and
// "Page x of y", hairline tables with a light-blue header row, and
// "Figure N." captions kept with their figure. No vendor mark, no cover page.
//
// The renderer writes `#let dcdc-id = (...)` (title, DUT, evidence label,
// recorded time, run id, revision, paper) immediately before this file inside
// print-header.typ, which Quarto inserts as a header include. Quarto's own
// `#show: doc => article(...)` block is replaced through the `typst-show.typ`
// template partial (templates/theme/typst-show.typ), which calls
// `dcdc-report` below instead; Quarto's `#set page(paper, margin, numbering)`
// from its page partial still runs, and every argument it sets is overridden
// by the `set page` inside `dcdc-report`, which executes after it.

#let dcdc-blue = rgb("13375e")
#let dcdc-blue-light = rgb("dce8f5")
#let dcdc-ink = rgb("1f2933")
#let dcdc-grey = rgb("5b6770")
#let dcdc-hair = luma(190)
#let dcdc-link = rgb("0b5fa5")
// Section numbers hang in this strip left of the text column; the header,
// footer, title block and the "About this report" table span it as well.
#let dcdc-hang = 10mm

#let dcdc-full-width(body) = pad(left: -dcdc-hang, body)

// Plain text of a content tree (cell bodies are text, space and sequence elements).
#let dcdc-plain-text(body) = {
  if body == none { "" } else if type(body) == str { body } else if body == [ ] { " " } else if body.has("text") {
    body.text
  } else if body.has("children") { body.children.map(dcdc-plain-text).join("") } else if body.has("body") {
    dcdc-plain-text(body.body)
  } else { "" }
}

// The level-1 section a page belongs to: the first one starting on the page,
// otherwise the last one before it (a continuing section).
#let dcdc-running-section() = context {
  let page-number = here().page()
  let starting = query(selector(heading.where(level: 1)).after(here())).filter(h => h.location().page() == page-number)
  let chosen = if starting.len() > 0 { starting.first() } else {
    let before = query(selector(heading.where(level: 1)).before(here()))
    if before.len() > 0 { before.last() } else { none }
  }
  if chosen == none { return }
  let number = if chosen.numbering != none {
    numbering(chosen.numbering, ..counter(heading).at(chosen.location())) + " "
  } else { "" }
  number + dcdc-plain-text(chosen.body)
}

// The page-1 "About this report" table (emitted by the renderer as the first
// Markdown table) spans the full width and shows its last row, Traceability,
// in small grey type: identifiers stay present but are not the first thing read.
#let dcdc-is-about-table(it) = {
  if it.children.len() == 0 { return false }
  let head = it.children.first()
  if head.func() != table.header or head.children.len() == 0 { return false }
  dcdc-plain-text(head.children.first()) == "About this report"
}

#let dcdc-about-table(it) = {
  if not dcdc-is-about-table(it) { return it }
  let columns = it.columns
  let count = if type(columns) == int { columns } else if type(columns) == array { columns.len() } else { 1 }
  let body-cells = it.children.filter(child => child.func() == table.cell).len()
  let last-row = calc.quo(body-cells, count)
  dcdc-full-width({
    show table.cell: cell => if cell.y == last-row { set text(size: 7.6pt, fill: dcdc-grey); cell } else { cell }
    block(breakable: false, above: 0.4em, below: 1.2em, it)
  })
}

#let dcdc-report(doc) = {
  set document(title: dcdc-id.title + " · " + dcdc-id.dut, author: "dcdc-bench")
  set page(
    paper: dcdc-id.paper,
    margin: (left: 16mm + dcdc-hang, right: 16mm, top: 24mm, bottom: 18mm),
    columns: 1,
    numbering: none,
    header-ascent: 30%,
    footer-descent: 30%,
    header: dcdc-full-width({
      set text(size: 7.2pt, fill: dcdc-grey)
      grid(
        columns: (1fr, auto),
        column-gutter: 8mm,
        align: (left + bottom, right + bottom),
        [#text(size: 8.4pt, weight: "bold", fill: dcdc-blue)[#dcdc-id.title] \ #dcdc-id.dut],
        [#text(weight: "bold", fill: dcdc-ink)[#dcdc-id.evidence]#if dcdc-id.recorded != "" [ · Recorded #dcdc-id.recorded] \ #dcdc-running-section()],
      )
      v(2pt)
      line(length: 100%, stroke: 0.5pt + dcdc-blue)
    }),
    footer: dcdc-full-width(context {
      set text(size: 7.2pt, fill: dcdc-grey)
      line(length: 100%, stroke: 0.3pt + dcdc-hair)
      v(2pt)
      grid(
        columns: (1fr, auto),
        column-gutter: 8mm,
        [Run #dcdc-id.run · Report revision #dcdc-id.revision],
        [Page #counter(page).display() of #counter(page).final().first()],
      )
    }),
  )
  set text(font: "Liberation Sans", size: 9pt, fill: dcdc-ink, lang: "en", region: "US")
  set par(justify: false, leading: 0.58em, spacing: 0.85em)
  show link: set text(fill: dcdc-link)
  show strong: set text(fill: dcdc-ink)

  // Sections "1", "1.1", "1.1.1": the number hangs in the margin strip, the
  // heading text starts at the text column, level 1 carries a thin rule. A
  // sticky heading travels with the block after it (brief §12.6).
  set heading(numbering: "1.1")
  show heading: it => {
    let size = if it.level == 1 { 12.5pt } else if it.level == 2 { 10.2pt } else { 9.3pt }
    let colour = if it.level <= 2 { dcdc-blue } else { dcdc-ink }
    let above = if it.level == 1 { 1.6em } else if it.level == 2 { 1.25em } else { 1.1em }
    let below = if it.level == 1 { 0.75em } else if it.level == 2 { 0.55em } else { 0.45em }
    block(above: above, below: below, sticky: true, width: 100%, {
      set text(size: size, weight: "bold", fill: colour)
      if it.numbering != none {
        place(top + left, dx: -dcdc-hang, counter(heading).display(it.numbering))
      }
      it.body
      if it.level == 1 {
        v(2pt)
        line(length: 100%, stroke: 0.6pt + dcdc-blue)
      }
    })
  }

  // Tables: hairline horizontal rules only, light-blue bold header row.
  set table(
    inset: (x: 5pt, y: 3.6pt),
    stroke: (x, y) => (bottom: 0.35pt + dcdc-hair),
    fill: (x, y) => if y == 0 { dcdc-blue-light },
  )
  set table.hline(stroke: 0.6pt + dcdc-blue)
  show table: set text(size: 8.4pt)
  show table.cell.where(y: 0): set text(weight: "bold", fill: dcdc-blue)
  show table: set block(above: 0.7em, below: 0.9em)
  show table: dcdc-about-table
  // A captioned table would carry its caption above (vendor-guide convention);
  // the issued tables are labelled by their headings and carry none today.
  show figure.where(kind: table): set figure.caption(position: top)

  // Figures: "Figure N." then the caption in small grey type, below the figure.
  set figure.caption(separator: [.])
  show figure.caption: it => context {
    set text(size: 7.8pt, fill: dcdc-grey)
    set par(leading: 0.5em)
    text(weight: "bold", fill: dcdc-ink)[#it.supplement #it.counter.display(it.numbering)#it.separator]
    [ ]
    it.body
  }
  show figure: set block(above: 0.8em, below: 1.2em)

  set list(indent: 0.4em, body-indent: 0.55em, spacing: 0.5em, marker: text(fill: dcdc-blue)[•])

  // The body emits hard page breaks between its major sections; a datasheet
  // flows continuously, so each becomes a small gap (brief §12.6: do not force
  // every section onto a new page). Pagination rules keep headings, figures
  // and tables whole.
  show pagebreak: it => v(0.8em)

  // First page: title block, then the body (whose first table is "About this report").
  dcdc-full-width(block(below: 0.9em, width: 100%, {
    text(size: 16pt, weight: "bold", fill: dcdc-blue)[#dcdc-id.title]
    v(2pt)
    text(size: 10.5pt, fill: dcdc-ink)[#dcdc-id.dut]
    if dcdc-id.subtitle != "" {
      v(1pt)
      text(size: 8.4pt, fill: dcdc-grey)[#dcdc-id.subtitle]
    }
    v(3pt)
    line(length: 100%, stroke: 0.6pt + dcdc-blue)
  }))
  doc
}
