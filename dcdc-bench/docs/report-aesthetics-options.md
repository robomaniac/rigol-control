# Report aesthetics options: research, three figure-theme previews, decision questions

Status: research and prototype only. The renderer, templates and issued reports are
unchanged. The previews are display experiments on already-issued evidence and are not
served as reports.

The owner's brief: the current HTML report "is not bad, but not perfect and not to my
liking in terms of aesthetics"; show different templates, ask questions, show research;
the graphs on the Pololu D24V7F6 page are a style they like.

## 1. Where the previews are

| Item | Location |
| --- | --- |
| Preview pages | `Data/Runs/theme-previews/` (git-ignored, served by the bench UI at `http://localhost:8081/Runs/theme-previews/index.html`) |
| Files | `index.html` (7 kB), `variant-a.html`, `variant-b.html`, `variant-c.html` (4.9 MB each; Plotly.js embedded once per page, no network access) |
| Source evidence | `dcdc-bench/runs/real-voltage-sweep/20260927T185631.575651Z_real_eb3bcd/reports/r0007/report_model.json` (MEASURED, 12T12-4A, 24 V and 35.8 V load sweeps, 27 qualified points) |
| Generator | `dcdc-bench/tools/theme_preview.py`; regenerate for any model with `python tools/theme_preview.py <report_model.json> <out_dir>` |

The generator uses only `plotly.graph_objects.Figure.to_html`. No browser, Kaleido,
Quarto, PDF, instrument or network access is involved. Every plotted value was checked to
equal the model value exactly; unqualified points would leave gaps and reserved
conditions (12 V in this run) create no trace. The Plotly bundle contains its own map
and MathJax URLs, exactly as the issued `report.html` does; scatter figures never
request them.

Each variant page renders the four registry figures (Efficiency, Input Current, Load
Regulation, Power Loss) in registry order and numbering, plus one compact Pololu-style
summary panel of the efficiency curves with an inside legend, and offers a
"single column / 2 x 2 grid" layout toggle for the dashboard question.

Limitation of this session: the previews could not be opened in a browser on the
memory-limited Pi, so legend-corner choices and footer spacing were verified from the
layout dictionaries, not from screenshots. The owner's first look is the visual check.

## 2. Research summary

### 2.1 Pololu D24V7F6 product page graphs (the owner's reference)

Source: <https://www.pololu.com/product/5594>; graph images `0J13782.800.jpg`
(efficiency), `0J13786.801.jpg` (quiescent current), `0J13787.801.jpg` (dropout).

- White background; light gray solid gridlines on both axes at every major tick; axes
  drawn as thin dark lines; gnuplot-like rendering.
- One thin (about 1.5 px) solid colored line per variant, no markers; six saturated
  hues across the family (black, green, orange, magenta, blue, gray).
- Legend inside the plot in a black-bordered white box, one or two columns, placed in
  the empty corner of each graph (bottom-right for efficiency, top-right for quiescent
  current, top-left for dropout); entries are conditions ("Vin = 9 V", "Vout = 3.3 V").
- Axis titles are lowercase quantity plus unit in parentheses: "output current (mA)",
  "efficiency (%)", "input voltage (V)", "dropout voltage (mV)"; plain sans-serif
  (Helvetica/Arial-like) about 13 px; centered title above the plot naming product and
  fixed condition ("Pololu D24V7F6 Regulator Efficiency, Vout = 6 V").
- Efficiency is plotted against output current from a non-zero floor (40-100 %), not
  0-100 %; quiescent current uses a log vertical axis with minor grid; dropout voltage
  is plotted against output current. Efficiency versus input voltage appears on other
  Pololu pages as one line per fixed load.

### 2.2 TI LMR33630 datasheet, section 7.8 "Typical Characteristics" (SNVSAN3F)

Source: <https://www.ti.com/lit/ds/symlink/lmr33630.pdf>, page 10.

- Six small plots per page in a 2 x 3 grid, each in a full four-sided black frame with
  medium gray gridlines on both axes.
- Three thin curves per plot distinguished by a fixed color scheme (black -40 C, red
  25 C, gray 125 C); no markers; legend inside a bordered box at bottom-right.
- Axis titles "Quantity (unit)" in title case ("Input Voltage (V)", "Quiescent Current
  (uA)"); vertical axes start at a meaningful floor rather than zero.
- Test conditions printed in small text directly under the plot ("VFB = 1.2 V";
  "IOUT = 0 A  VOUT = 5 V  fSW = 400 kHz"), then a bold caption "Figure 7-1. Non-Switching
  Input Supply Current" (section-figure numbering). Arial throughout; the document
  organisation is numbered sections with tables of conditions.

### 2.3 EPC90120 quick start guide, pages 9-11 (R14 in the implementation brief)

Source: <https://epc-co.com/epc/Portals/0/epc/documents/guides/EPC90120_qsg.pdf>.

- White page, blue header band, uppercase bold section headings ("EFFICIENCY and POWER
  LOSSES"); Figure 14 places efficiency and power loss side by side.
- Heavier lines (about 2.5 px) in two hues (blue, red) for the switching-frequency
  variants; no markers; legend inside bottom-right with line samples and no box.
- Bold axis titles with subscripts ("Efficiency (%)", "I_Load (A)"); medium gray grid on
  both axes; four-sided frame; efficiency axis zoomed (86-98 %).
- Derating curves use bold titles above each plot ("Thermal Derating Curves: 500 LFM"),
  solid versus dashed line styles, direct labels on the curves ("with heatsink"), and a
  boxed legend; captions are italic, centered, "Figure 16: Typical thermal derating...".

### 2.4 Dataviz method (skill guidance) applied to this project

- Color does one job; here it identifies the input condition (categorical, fixed order,
  never cycled). Identity must never rest on color alone: a legend is always present and
  marker shape or line style is the second channel.
- Palettes are computed, not eyeballed: OKLCH lightness band (0.43-0.77 light,
  0.48-0.67 dark), chroma >= 0.10, CVD separation dE >= 8 target (6-8 only with secondary
  encoding) under Machado 2009 protan/deutan simulation, normal-vision floor dE >= 15,
  marks >= 3:1 against the surface. Lines can cross, so the all-pairs list applies.
- Node is not installed on this host, so `validate_palette.js` was ported line-for-line
  to Python (same constants and matrices) and a small OKLCH search was run per variant.
  The port lives inside `tools/theme_preview.py` (`palette_report`) so the index page
  reports the numbers for whatever palette is configured.
- Other rules retained: recessive hairline grid, thin marks, text in ink colors (never a
  series color), a dark mode is separately stepped rather than an automatic flip, and
  dashed gridlines are discouraged (Variant C uses them deliberately; see questions).

### 2.5 Palette measurements

All-pairs, protan/deutan worst case, OKLab dE x 100.

| Palette (12 V / 24 V / 36 V slots) | Surface | Worst CVD dE | Worst normal dE | Min contrast | Verdict |
| --- | --- | --- | --- | --- | --- |
| Current renderer `#0072B2` `#D55E00` `#CC33AA` | white | 5.0 (blue-magenta) | 22.8 | 3.87:1 | FAIL all-pairs; PASS adjacent (19.9) |
| Variant A `#1157a4` `#40a35c` `#a63c0c` | white | 13.5 | 27.5 | 3.18:1 | PASS |
| Variant A dark `#4064b9` `#00a672` `#a24e10` | `#1a1a19` | 13.1 | 25.0 | 3.01:1 | PASS |
| Variant B `#2c57cd` `#1ca288` `#c65102` | white | 12.9 | 26.1 | 3.19:1 | PASS |
| Variant B dark `#315dd4` `#27a98e` `#c65102` | `#1a1a19` | 13.7 | 26.3 | 3.02:1 | PASS |
| Variant C `#114d9a` `#19825b` `#954200` | white | 9.0 | 20.9 | 4.79:1 | PASS |

Finding: every hand-picked blue + purple/magenta pair (the current palette and the
"teal/purple" direction) collapses to dE 2-5 under protan/deutan simulation because
purple loses its red component. The current renderer is still safe today because 12 V
and 36 V never sit adjacent in the ordered legend and dash/marker encode the condition
as well, but a 12 V versus 36 V comparison on one axis would rely on those. All three
variants therefore give the middle slot a green or teal hue. The renderer's slots 4-6
(`#009E73`, `#00A6C8`, `#805400`) also fail the normal-vision floor between green and
cyan (dE 12.5) and cyan sits at 2.88:1 on white.

## 3. What the report looks like today (facts from the code)

| Element | Static figures (`renderer._plot_figure`) | Interactive (`templates/web/report.js` `layout()`/`traces()`) | Document |
| --- | --- | --- | --- |
| Palette | `COLORS` = `#0072B2` blue (12 V), `#D55E00` vermilion (24 V), `#CC33AA` magenta (36 V), then `#009E73`, `#00A6C8`, `#805400`; `TRACE_PATTERNS` solid/circle, dash/square, dot/diamond via `_condition_styles` | same registry, embedded as `condition_styles` in the payload | swatches in the controls |
| Lines / markers | width 2, marker size 9 | width 2.5, marker size 7 | - |
| Grid / frame | `plotly_white`, grid `#e6edf1`, no zero line, no frame | same | - |
| Legend | horizontal above the plot (`y` 1.12) | horizontal above the plot (`y` 1.03) | condition checkboxes with swatches |
| Typography | DejaVu Sans/Arial 16 px, title 19 px, ink `#183047` | system-ui 12 px | `report.css`: system-ui 15 px, ink `#183047`, muted `#516677`, rules `#dce4e9`, accents blue `#15608f` and teal `#168477`; Typst PDF: DejaVu Sans/Liberation Sans 9.5 pt |
| Footer / evidence | three-line footer annotation at `y` -0.24 (evidence label, DUT, run, analysis, figure id, conditions, boundary) | figure caption + evidence banner in the page | evidence banner (teal border; amber for synthetic) |
| References | dashed gray nominal / supply-limit line with label, y-range including the reference | same | - |
| Size | 1080 x 530 px | responsive, 465 px high | Quarto HTML with left TOC; Typst A4 |

## 4. The three variants

Common to all three (the fixed part): every qualified point is a visible marker;
unqualified points leave gaps; figure registry order and numbering; axis titles with units
from the model; evidence label badge at the top-right of every figure plus the existing
three-line footer (evidence label, DUT, run ID, analysis ID, figure id, plotted
conditions, boundary "source-to-load-terminal path (input and output wiring included)");
reference lines only where the model supplies them; the same condition keeps the same
slot across figures and reports; brief section 12.2 direction (restrained document, light
grids, visible measured markers, no decorative cards).

### Variant A - "Datasheet classic" (Pololu / TI)

| Aspect | Value |
| --- | --- |
| Palette | `#1157a4` blue (12 V), `#40a35c` green (24 V), `#a63c0c` brick (36 V); dark steps `#4064b9` `#00a672` `#a24e10` |
| Lines / markers | 1.6 px solid; 5 px circle / square / diamond with a 1 px surface ring |
| Grid / frame | 1 px solid `#d9d9d9` on both axes; four-sided `#333333` frame, outside ticks |
| Legend | inside the plot, white box with 1 px `#444444` border, placed automatically in the emptiest corner of each figure |
| Typography | Arial / Helvetica / Liberation Sans 13 px labels, 15 px centered title, ink `#1a1a1a`, muted `#555555` |
| Page | 1040 px column, 1 px `#c8c8c8` frame around each figure (TI-like), plain captions |

### Variant B - "Modern engineering" (EPC)

| Aspect | Value |
| --- | --- |
| Palette | ordered cool to warm by input voltage: `#2c57cd` blue (12 V), `#1ca288` teal (24 V), `#c65102` orange (36 V); dark steps `#315dd4` `#27a98e` `#c65102` |
| Lines / markers | 2.6 px solid; 7 px circle / square / diamond; optional 12 %-alpha halo under each line (no legend entry, no hover, not a measurement) |
| Grid / frame | horizontal hairlines only (`#e3e8ed`), plot panel `#f8fafc` on white paper, open frame (`#c9d2da` axis lines, no ticks) |
| Legend | horizontal below the plot; footer below the legend |
| Typography | system-ui 15 px labels, bold 18 px left-aligned title, ink `#183047`, muted `#516677` (matches the current CSS variables) |
| Page | 1120 px column, no figure frames, italic captions (EPC style), 600 px figure height |

### Variant C - "Print-first monochrome-plus-accent"

| Aspect | Value |
| --- | --- |
| Palette | `#114d9a` navy (12 V), `#19825b` dark green (24 V), `#954200` dark rust (36 V); OKLCH L 0.43 / 0.54 / 0.48 so a grayscale copy still separates them; every mark >= 4.8:1 on white; no dark-mode design |
| Lines / markers | 2 px solid / dashed / dotted by condition; 8 px circle / square / diamond |
| Grid / frame | dashed 1 px `#a8a8a8` on both axes; 1.2 px black four-sided frame with outside ticks |
| Legend | inside the plot, opaque white box with 1.2 px black border, emptiest corner |
| Typography | Liberation Sans / DejaVu Sans 14 px (the faces the Typst PDF already uses), ink `#000000` |
| Page | 1040 px column, 1 px `#555555` figure frames, 2 px black rule under headings |

Summary panel (all variants): the efficiency figure re-drawn at 430 px height inside a
760 px box, title "Efficiency vs output current - measured input conditions", legend
inside (Variant B keeps its legend below), one-line footer with evidence label, DUT, run
ID and boundary. It reuses the same qualified points; it is a display variant, not an
extra measurement.

## 5. Mapping to the existing renderer

| Change | Where | Notes |
| --- | --- | --- |
| Palette and patterns | `renderer.COLORS`, `renderer.TRACE_PATTERNS` (single source for static figures, interactive payload `colors` / `condition_styles`, and control swatches) | Variant A/B: patterns become all-solid (or stay as they are for a stronger second channel). Tests and the engineering-style verification assert the current hex values and dash patterns in SVGs and must be updated together. |
| Figure layout (static) | `renderer._plot_figure` `update_layout`: `font`, `title.x/xanchor`, `legend`, `xaxis`/`yaxis` (`gridcolor`, `griddash`, `showline`, `mirror`, `ticks`), `plot_bgcolor`, `margin`, trace `line.width`, `marker.size`; footer annotation `y` | Inside legends need a corner heuristic like `theme_preview.emptiest_corner` (reference `y_range` aware). Variant B needs a larger bottom margin (legend + footer). |
| Figure layout (interactive) | `templates/web/report.js` `layout()` (same keys) and `traces()` (`line.width`, `marker.size`, halo trace) and the export layout near line 306 | The halo (Variant B) must be marked like transition guides (`meta.isTransition`-style flag) so exports and point tables skip it. Legend-click handlers key on `meta.conditionKey`; the halo must carry none. |
| Document CSS | `templates/theme/report.css` variables `--ink`, `--muted`, `--rule`, `--blue`, `--teal`, `--wash`, body `font-family`, `.quarto-figure` / `figcaption` rules, `.evidence-banner` | Variant A/C: Arial/Liberation Sans body and framed figures; Variant B: no change beyond caption italics. |
| PDF | `print-header.typ` generated in `renderer._render_report` (`#set text(font: ("DejaVu Sans", "Liberation Sans"))`), figure SVGs from `_static_figures` | Serif option would be a Typst font change plus a matching Plotly font family for the static SVGs. |
| Evidence badge | new annotation in `_plot_figure` and `layout()` | Optional; the footer already carries the label. |

Effort estimates (one engineer, including test updates and re-verification of static
SVG/PDF hashes for one run): Variant A about 1 day; Variant C about 1 day (dash
patterns already exist; grid dash and frame are layout keys); Variant B about 1.5-2
days (legend-below spacing in both renderers, halo exclusion from exports, panel tint in
PDF). A dark HTML option adds roughly 1 day (CSS variables plus Plotly layout swap and a
validated dark palette; A and B already have one). None of this touches analysis,
models or issued revisions; reports would gain a new presentation revision.

## 6. Decision questions for the owner

1. Legend inside the plot (Pololu/TI, saves vertical space, needs a free corner) or
   outside (current: horizontal above; Variant B: below)?
2. Color by input voltage as an ordered cool-to-warm ramp (Variant B) or fixed
   per-condition hues (current blue/vermilion/magenta; Variants A/C)?
3. Markers on every measured point (current, all variants) or sparse markers with a
   marker-per-N rule while keeping every point in hover/table?
4. Offer a dark HTML option (validated dark steps exist for A and B; C is print-only)
   or stay light-only?
5. Serif or sans in the PDF (Typst currently uses DejaVu Sans / Liberation Sans; all
   previews are sans)?
6. One figure per quantity in sequence (current) or a 2 x 2 dashboard grid of the four
   figures on the first page (toggle available on each variant page)?
7. Add a Pololu-style "efficiency vs input voltage at fixed loads" figure? This run has
   only two input conditions (24 V and 35.8 V), so it needs the planned multi-voltage
   run first.
8. Keep the boxed (four-sided) plot frame of A/C or the open EPC-like frame of B?
9. Keep the three-line footer inside each figure (survives SVG/PNG export) or move
   identity into the HTML caption?

Additional points the owner may want to rule on: whether the current magenta slot
should be replaced regardless of theme (palette finding in section 2.5); whether dashed
gridlines (Variant C, print request) are acceptable against the dataviz guidance for
solid hairlines; and whether the Variant B halo is welcome or reads as decoration.

## 7. Sources

- Pololu, "6V, 600mA Step-Down Voltage Regulator D24V7F6", <https://www.pololu.com/product/5594>
  (graphs: typical efficiency, quiescent current, typical dropout voltage).
- Texas Instruments, LMR33630 datasheet SNVSAN3F, section 7.8 Typical Characteristics,
  <https://www.ti.com/lit/ds/symlink/lmr33630.pdf>.
- EPC, EPC90120 Quick Start Guide, pages 9-11, <https://epc-co.com/epc/Portals/0/epc/documents/guides/EPC90120_qsg.pdf>
  (implementation brief R14; section 12.2 "Visual direction to retain").
- Project decisions: `docs/engineering-figure-labels.md`, `docs/engineering-style-verification.md`,
  `docs/implementation-brief.md` section 12.
- Dataviz skill: color formula, reference palette, marks and anatomy, anti-patterns;
  `validate_palette.js` checks 2-5 (ported to Python in `tools/theme_preview.py`).
