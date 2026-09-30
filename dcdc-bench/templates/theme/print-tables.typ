// Print theme: table pagination for the PDF (implementation brief §12.6,
// acceptance PDF-02). Quarto emits every Markdown table as a bare Typst
// `table` with a repeating `table.header`. Typst breaks such a table freely
// between rows, so even a three-row table can leave its last row alone under
// a repeated header at the top of the next page. The renderer appends this
// file to the Quarto header include (`print-header.typ`); the rule applies to
// every table of the document.
//
// * A table whose laid-out height is at most half the page body is wrapped in
//   an unbreakable block: it never splits and moves whole to the next page
//   when the current page is too full (leaving at most half a page free). The
//   decision uses the measured height, so it follows the installed fonts and
//   the page geometry exactly; no row-count or page-count heuristic is used.
// * A taller table stays breakable (Typst repeats its header on every page),
//   but its last two body rows move into a non-repeating `table.footer`.
//   Typst lays a footer out as one unit, so the final page of the table can
//   never hold a single data row. Typst tags footer rows as ordinary data rows
//   (TD cells inside TFoot); the pagination check counts them as body rows.
//
// Tables that already carry a footer, use spans or explicit cell positions,
// or have fewer than three body rows are left unchanged.

// Largest table height, as a share of the page body, that is kept on one page.
#let dcdc-keep-together-ratio = 0.5

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

// Width and height of the page body (the area inside the margins), as laid out.
#let dcdc-page-body() = {
  let fallback = 2.5 / 21 * calc.min(page.width, page.height)
  let left = dcdc-margin-side(page.margin, "left", "x", fallback)
  let right = dcdc-margin-side(page.margin, "right", "x", fallback)
  let top = dcdc-margin-side(page.margin, "top", "y", fallback)
  let bottom = dcdc-margin-side(page.margin, "bottom", "y", fallback)
  (page.width - left - right, page.height - top - bottom)
}

#let dcdc-paginate-table(it) = context {
  let is-cell(child) = child.func() == table.cell
  if it.children.any(child => child.func() == table.footer) { return it }
  let (width, height) = dcdc-page-body()
  if measure(block(width: width, it)).height <= dcdc-keep-together-ratio * height {
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
  table(..fields, ..it.children.slice(0, split), table.footer(repeat: false, ..it.children.slice(split)))
}

#show table: dcdc-paginate-table
