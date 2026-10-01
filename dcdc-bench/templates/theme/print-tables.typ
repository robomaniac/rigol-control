// Print theme: table pagination for the PDF (implementation brief §12.6,
// acceptance PDF-02). Quarto emits every Markdown table as a bare Typst
// `table` with a repeating `table.header`. Typst breaks such a table freely
// between rows, so even a three-row table can leave its last row alone under
// a repeated header at the top of the next page, and a long table can open
// with its header and a single row at the bottom of a page. The renderer
// appends this file to the Quarto header include (`print-header.typ`); the
// rule applies to every table of the document.
//
// * A table whose laid-out height is at most half the page body is wrapped in
//   an unbreakable block: it never splits and moves whole to the next page
//   when the current page is too full (leaving at most half a page free). The
//   decision uses the measured height, so it follows the installed fonts and
//   the page geometry exactly; no row-count or page-count heuristic is used.
// * A taller table stays breakable (Typst repeats its header on every page),
//   with two guards:
//   - its last two body rows move into a non-repeating `table.footer`. Typst
//     lays a footer out as one unit, so the final page of the table can never
//     hold a single data row. Typst tags footer rows as ordinary data rows (TD
//     cells inside TFoot); the pagination check counts them as body rows;
//   - its header and first two body rows are measured against the space left
//     on the current page (`here().position()`). When they would not fit, a
//     table that fits on one page is wrapped in an unbreakable block, so it
//     moves whole to the next page together with the sticky heading above it
//     (a column break here would strand that heading); a table taller than a
//     page gets a weak column break instead, unless a heading sits directly
//     above it, in which case the split stays a warning rather than becoming
//     an orphan-heading error. Either way a table never opens with a single
//     row at the bottom of a page (the check's `table-split-after-first-row`).
//     Typst lays the document out repeatedly until introspection settles, so
//     the decision must not flip once the table has moved: a table (or the
//     heading directly above it) that already starts a page takes the same
//     action, which is then a no-op (an unbreakable block that fits, or a weak
//     column break in an empty column).
//
// Tables that already carry a footer, use spans or explicit cell positions,
// or have fewer than three body rows are left unchanged.

// Largest table height, as a share of the page body, that is kept on one page.
#let dcdc-keep-together-ratio = 0.5
// Largest table height, as a share of the page body, that may still be moved
// whole to the next page when its head would not fit on the current one; the
// rest of the page must hold the sticky heading that travels with it.
#let dcdc-move-whole-ratio = 0.9
// Body rows that must share the first page with the header of a breakable table.
#let dcdc-leading-rows = 2
// A heading whose top lies within this distance above a table is "directly above" it.
#let dcdc-heading-gap = 40pt
// Content whose top lies within this distance of the page body's top starts the page.
#let dcdc-top-tolerance = 12pt

#let dcdc-margin-side(margin, side, axis, fallback) = {
  let value = if type(margin) == dictionary {
    margin.at(side, default: margin.at(axis, default: margin.at("rest", default: fallback)))
  } else {
    margin
  }
  if value == auto { value = fallback }
  if type(value) == relative { value = value.length }
  value
}

#let dcdc-margin-fallback() = 2.5 / 21 * calc.min(page.width, page.height)

// Width and height of the page body (the area inside the margins), as laid out.
#let dcdc-page-body() = {
  let fallback = dcdc-margin-fallback()
  let left = dcdc-margin-side(page.margin, "left", "x", fallback)
  let right = dcdc-margin-side(page.margin, "right", "x", fallback)
  let top = dcdc-margin-side(page.margin, "top", "y", fallback)
  let bottom = dcdc-margin-side(page.margin, "bottom", "y", fallback)
  (page.width - left - right, page.height - top - bottom)
}

// Height still free on the current page below the current position (context).
#let dcdc-remaining-height() = {
  let bottom = dcdc-margin-side(page.margin, "bottom", "y", dcdc-margin-fallback())
  page.height - bottom - here().position().y
}

// Top edge of a heading that starts on this page within `dcdc-heading-gap`
// above here, or `none` when no heading sits directly above (context).
#let dcdc-heading-top-above() = {
  let before = query(selector(heading).before(here()))
  if before.len() == 0 { return none }
  let top = before.last().location().position()
  if top.page == here().page() and here().position().y - top.y < dcdc-heading-gap { top.y } else { none }
}

#let dcdc-paginate-table(it) = context {
  let is-cell(child) = child.func() == table.cell
  if it.children.any(child => child.func() == table.footer) { return it }
  let (width, height) = dcdc-page-body()
  let table-height = measure(block(width: width, it)).height
  if table-height <= dcdc-keep-together-ratio * height {
    return block(breakable: false, it)
  }
  let columns = it.columns
  let count = if type(columns) == int { columns } else if type(columns) == array { columns.len() } else { 1 }
  let cells = it.children.filter(is-cell)
  let plain = cells.all(cell => cell.fields().keys().all(key => key not in ("colspan", "rowspan", "x", "y")))
  if not plain or count < 1 or calc.rem(cells.len(), count) != 0 or cells.len() < 3 * count { return it }
  // The last two rows must be plain cells with nothing (no line, no header) between them.
  let split = it.children.len() - 2 * count
  if not it.children.slice(split).all(is-cell) { return it }
  let fields = it.fields()
  let _ = fields.remove("children")
  let _ = fields.remove("label", default: none)
  let paginated = table(..fields, ..it.children.slice(0, split), table.footer(repeat: false, ..it.children.slice(split)))
  // The head: everything before the first body cell (header, lines), then the
  // first `dcdc-leading-rows` rows. It is measured as a header plus a
  // non-repeating footer holding those rows: same height, and a table that
  // carries a footer is returned unchanged above, so the measurement does not
  // re-enter this rule.
  let first = it.children.position(is-cell)
  let stop = first
  let seen = 0
  for (index, child) in it.children.enumerate() {
    if index >= first and is-cell(child) { seen += 1 }
    if seen >= dcdc-leading-rows * count { stop = index + 1; break }
  }
  let head = table(..fields, ..it.children.slice(0, first),
    table.footer(repeat: false, ..it.children.slice(first, stop)))
  let head-height = measure(block(width: width, head)).height
  let heading-top = dcdc-heading-top-above()
  let anchor = if heading-top == none { here().position().y } else { heading-top }
  let body-top = dcdc-margin-side(page.margin, "top", "y", dcdc-margin-fallback())
  let starts-page = anchor <= body-top + dcdc-top-tolerance
  if not starts-page and head-height + 1.5 * text.size <= dcdc-remaining-height() { return paginated }
  if table-height <= dcdc-move-whole-ratio * height { return block(breakable: false, paginated) }
  if heading-top == none { colbreak(weak: true) }
  paginated
}

#show table: dcdc-paginate-table
