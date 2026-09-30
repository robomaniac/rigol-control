# Bench page UI/UX review — the simulated experience before the owner's look

Reviewed on 2026-09-30 against the live loopback service (`http://127.0.0.1:8081/`,
code at `dcdc-bench-hardening` b38df08). This review was performed by an automated
agent in a senior UI/UX-designer role, not by a human reviewer. Nothing here opened
an instrument or started a job.

## 1. Perspective and method

The question asked: is the **Simulated bench** flow genuinely good, self-explanatory,
and explicit about what it can and cannot do, before the owner reviews it.

Method:

- Playwright with the system `chromium-headless-shell` on the Pi, one browser at a time,
  at 1440×900 and 390×844 (mobile emulation). Walk: initial page → converter cards →
  Simulated/Real tiles → "Which test?" cards → ISO 16750-2 card expanded and folded →
  select *Quick sweep — 12 / 24 / 30 V × 0–1 A* → **Preview** → open "All requested
  points" → change the converter (stale plan) → Reports → Edit/New test editors
  (cancelled) → Delete dialog (cancelled) → `/annotations` (chose the fresh simulated run)
  → the fresh design-A report of job `20260930T145556Z_3451819c`.
- **Start** was never pressed; no real-bench control was touched. No profile was written:
  Preview was only run with a recipe already bound to the selected converter, the
  12 V / 24 V class toggle, **Add as tests** and the approval checkbox were not clicked.
- Besides screenshots, a DOM inventory (roles, tab order, nested controls, headings,
  overflow, computed colours and font sizes) was taken on each state, and WCAG contrast
  ratios were computed for every text/background pair in the page CSS, including the
  dimmed (`opacity`) states.
- Intent sources: `docs/bench-ui.md`, `docs/getting-started.md`,
  `docs/report-aesthetics-options.md` (owner chose design A), `docs/engineering-figure-labels.md`,
  brief §2, §12.2, §13.1; code `src/dcdc_bench/ui.py`, `ui_models.py`, `standard_recipes.py`,
  `annotation_editor.py`, `templates/theme/report.css`.

Not observed (no job was active during the review and nothing was allowed to write):
the locked sections, header spinner and two-step Stop during a run; the greyed card that
"Add as tests" produces. Those statements below come from the code and `docs/bench-ui.md`.

Screenshots (all ≤ 300 KB, in `screenshots/`):

| # | File | What it shows |
| --- | --- | --- |
| 1 | [01-desktop-initial.png](screenshots/01-desktop-initial.png) | First screen at 1440×900: header, "Selected" strip, converter cards, tiles, fixed bar |
| 2 | [02-desktop-bench-tiles.png](screenshots/02-desktop-bench-tiles.png) | Simulated vs Real tiles; the selected limit preset pill with no readable label |
| 3 | [03-desktop-which-test.png](screenshots/03-desktop-which-test.png) | Section 3: saved tests by category and the seven standards cards |
| 4 | [04-desktop-iso16750-2-checklist.png](screenshots/04-desktop-iso16750-2-checklist.png) | ISO 16750-2 expanded: class toggle, rows, badges, a badge tooltip |
| 5 | [05-desktop-preview-and-reports.png](screenshots/05-desktop-preview-and-reports.png) | Preview result for the simulated Quick sweep, the Run stub and the Reports table |
| 6 | [06-phone-initial-checklist-reports.png](screenshots/06-phone-initial-checklist-reports.png) | 390×844: initial page, the checklist forcing a 685 px layout, Reports rows |
| 7 | [07-desktop-annotations.png](screenshots/07-desktop-annotations.png) | `/annotations` with the fresh simulated run chosen |
| 8 | [08-report-design-a-figure.png](screenshots/08-report-design-a-figure.png) | The fresh simulated report (HTML), Figure 1, for style comparison |

## 2. Heuristic evaluation

### 2.1 Visibility of system status

Good: the header pill "Idle — nothing switched on" (`role=status`) is the first thing the
eye lands on; the "Selected" strip and the fixed bar repeat the current choice; changing
the converter after a Preview immediately shows the amber "Settings changed — Preview again
before starting." and Start is disabled (observed). The Plan panel gives the counts
(19 / 21, skipped 2), the reason with its arithmetic, and "Ready. HTML and PDF reports are
generated automatically after acquisition."

Weak: **Start** is disabled on arrival with no explanation (opacity .7, `cursor:not-allowed`,
no tooltip); a first-time operator must discover that Preview is the gate. The plan stat
"Estimated time — simulated · seconds" reads like a placeholder. After Preview the page
scrolls the Plan panel under the sticky header, so the "Plan" heading is hidden and the
stats appear cut off at the top (screenshot 5).

### 2.2 Match with the operator's mental model

The one-page order (converter → bench → test → Preview → Start) matches brief §2 exactly
and the numbered circles make the sequence obvious. Cards say what a test is in bench
terms ("24 V × 0.1 / 0.25 / 0.5 A · 3 points").

Mismatches:

- The **Simulated tile is a 100 px stub** ("Nothing is switched on. Synthetic readings,
  real report layout.") while the Real tile lists its four protective limits and preset
  pills. Yet the simulated plan skips 2 of 21 points because of a 1 A synthetic source the
  operator has never been shown. What the synthetic plant models, and what it cannot tell
  you about the real sample (12 V cold start, readback error), is not stated on the page.
- In the ISO 16750-2 checklist, §4.5 and §4.6.2 carry a green **"runs here"** badge and
  are ticked by default, but the tests they generate ship unapproved
  (`authorization.uvlo_approved: false`) and are planned as not executable until the recipe
  is approved — and the page has no control for that approval (`grep uvlo ui.py` finds
  nothing). The contradiction is disclosed only in a 13 px footnote under the list.
- Test cards repeat the grid twice (title and subtitle) but never say the test *type*
  (steady-state sweep vs no-load window).
- Six standards cards shout in red that CISPR 25, ISO 11452, ISO 10605, ISO 16750-3/4 and
  ISO 7637-2 cannot run here. That is honest, but red is the colour of "you did something
  wrong"; these are "not this laboratory" facts and occupy more space than the runnable
  tests.

### 2.3 Clear Simulation vs Real distinction

Strong points: real vs simulated is decided in one place (question 2); the Start label
changes ("Start simulated test" / "Start test on the real bench"); the Real tile says
"Start can switch outputs on"; amber is reserved for Real (selected tile, Reports badge),
teal/grey for Simulated; the plan says "Simulated — nothing switched on"; the report says
"SYNTHETIC evidence" in its subtitle and "Evidence: Synthetic (simulated) — values come from
a software model, not from hardware." in its first table (screenshot 8). The fresh
coordinator job is listed in Reports as "12T12-4A · Quick sweep — 12 / 24 / 30 V × 0–1 A ·
Simulated · Complete 19 / 19 points" with Open HTML / Open PDF (screenshot 5).

Gaps: the selected **limit-preset pill has invisible text** (§3, B1), so the one line that
tells the operator *which* protective limits the real bench would use is unreadable. The
vocabulary drifts: "Simulated", "synthetic", "SYNTHETIC", "nothing switched on", "no real
instruments" all appear for the same idea. `/annotations` lists runs without a
Simulated/Real marker, inviting a photograph of a physical setup onto a synthetic run.

### 2.4 Error prevention and recovery

Good: Preview is mandatory; the plan is invalidated by any change; the real Start opens a
separate confirmation with serials; Delete asks "Delete this saved converter? Past runs keep
their own copy." and names the item; profile validation errors surface as notifications.

Weak: the approval checkbox sits *inside* the `role=radio` Real tile without `click.stop`
(the pills and "Change limits…" do stop), so a tap on it while Simulated is selected both
clears the approval and switches the bench (from the DOM; not exercised because it writes a
profile). Dialogs are `persistent` (line 481), so Escape does not cancel (probe). The disabled Start
gives no reason. "Stopped" (operator cancel) and "Acquisition stopped" (fault abort) are
indistinguishable in Reports.

### 2.5 Consistency with the report's design A

The page and `report.css` share their tokens (ink `#183047`, muted `#516677`, rule
`#dce4e9`, blue `#15608f`, teal `#168477`, `system-ui`), so the bench page and the HTML
report read as one family (screenshots 5 and 8). Two caveats:

- Per `HANDOFF.md` the owner's design A (datasheet / TI-like, one accent colour) is
  productised in the **PDF theme** and the "About this report" table; the HTML figures
  still draw the earlier palette (`#0072B2` / `#D55E00` / `#009E73` measured in the
  report's swatches) with the legend above the plot. So "consistent with design A" can only
  mean the document idiom today: restrained, ruled headings, key–value tables. The bench
  page departs from that idiom with 999 px pills, 26 px numbered discs, 8 px cards with 2 px
  borders, filled primary buttons and coloured badges — a web-app look next to a datasheet
  report. The report's own controls are 1 px `#abc0cf` outlined white buttons with 4 px
  radius (`report.css .report-controls button`); the bench page's secondary actions
  (Refresh saved runs, View run, Regenerate report, pills) could adopt that style.
- Radii differ inside the app: `.bench-card-item` 8 px, `.bench-card` on `/annotations`
  12 px, report controls 6 px.

### 2.6 Accessibility

- **Roles.** Cards are `<div role=button aria-pressed>` that *contain* three or four real
  `<button>`s (8 such nests counted) — interactive content inside a button is invalid ARIA
  and confuses screen readers. The two tiles are `role=radio` with `aria-checked` but no
  `role=radiogroup` and no arrow-key handling. There are **no `<h1>`–`<h3>` elements** on
  `/` or `/annotations` (all headings are styled `<div>`s) and `<html lang>` is empty.
- **Focus order.** 81 focusable elements; DOM order is card, Rename, Edit, Delete, card, …
  It takes ~48 Tab presses to pass the last test card and the bar's **Preview / Start are
  the very last stops**, after every Reports row. **Space does not activate a card** (only
  `keydown.enter` is bound; probe: selection unchanged after Space). The focus ring
  `#88b9d5` on white is 2.1:1.
- **Contrast** (computed): body text, badges, links and the idle pill pass AA (5.2–9.2:1).
  Everything that is dimmed by `opacity` fails or nearly fails: greyed standards cards
  (`opacity:.62`) → reason 3.4:1, meta 2.6:1; untickable clause notes (`opacity:.72`) →
  2.9:1; the Real tile's details when Simulated is selected (`opacity:.6`) → keys 2.6:1;
  stale plan stats (`opacity:.4`) → 2.3:1; the selected pill → **1.0:1** (bug). The card
  links render at **10 px** in 22×23 px targets (Quasar `size=sm dense` overrides the
  12.5 px rule).
- **Phone width (390 px).** The base page has no horizontal overflow (scrollWidth 390) and
  the tiles, cards and Reports stack correctly. But the sticky header (126 px: title,
  subtitle, status pill wrapping) plus the fixed bar (126 px) leave 592 px for content;
  "SELECTED" is broken mid-word ("SELE / CTED"); and **opening the ISO 16750-2 checklist
  widens the layout to 685 px** (measured `innerWidth` 390 → 685), which zooms the whole
  page out to ~57 % and clips the badges and levels (screenshot 6, middle).

## 3. Findings

Line numbers refer to `dcdc-bench/src/dcdc_bench/ui.py` unless another file is named.

### Blocker

**B1. The selected limit-preset pill has no readable label.** `render_bench` builds the
pills with `ui.button(...).props('flat dense no-caps size=sm')` (lines 848 and 866); Quasar's
`flat` adds `text-primary`, whose `!important` colour beats `.bench-pill.on{…color:#fff}`
(line 73). Computed: text `rgb(21,96,143)` on background `rgb(21,96,143)`, 1.0:1
(screenshot 2: a blank blue capsule). The operator cannot read which of the three
protective-limit presets the real bench would use; only the table below hints at it.
*Fix:* `pill.props('text-color=white')` when `on` (or `color=None` and
`.bench-pill.on .q-btn__content{color:#fff}`), or replace the pills with `ui.toggle`, which
already handles the selected colour.

**B2. The Reports "When" column overprints "Run" in every row.** `.bench-report-row`
uses `grid-template-columns:150px 1fr 100px 150px minmax(220px,1fr)` (line 98) and
`.bench-report-when{white-space:nowrap}` (line 100); "07:55:56 PDT (2026-09-30)" needs
~185 px at 13.5 px, so it runs into "12T12-4A · Quick sweep…" (screenshot 5, every row).
*Fix:* first column `auto` (or 190 px), or render the time on two lines
(`07:55:56 PDT` / `2026-09-30`) without parentheses and let the cell wrap.

**B3. "runs here" promises what the simulated bench then refuses.** `standard_recipes.badge`
(lines 79–80) returns `runs_here` + tickable for §4.5 and §4.6.2 whenever the catalog verdict
is `runs_here`, so the checklist (lines 959–989) ticks them by default and the card counts
"3 of 19 clauses runnable on this bench". The recipes `build_recipe` writes carry
`authorization.uvlo_approved: false` (`standard_recipes.py:183`), and `docs/bench-ui.md`
states their card "stays greyed with the planner's reason until the recipe is approved".
No approval control exists on the page. The operator is walked into "Add as tests" and then
told the new tests cannot run, with the explanation in a 13 px footnote (lines 987–989).
*Fix:* badge those two clauses **"runs here after approval"** in amber, leave them unticked
by default, count them separately ("1 runnable now, 2 after approval"), and add the missing
control — an "Approve this profile for the simulated bench (it steps below the converter's
stated minimum)" checkbox in the test editor's *Planning assumptions* expansion that sets
`authorization.uvlo_approved` — or, if approval must stay outside the UI, say where it is
done in the same sentence.

### Major

**M1. The Simulated tile hides the envelope that decides the plan.** Lines 838–850 render
only a title and one sentence. The simulated bench profile
(`workspace/profiles/bench/mock-dp821-envelope.json`) is a synthetic source of 0–60 V, 1 A,
60 W with no protective limits, and its notes say the profiles "model a coupled converter
and source/load … not observations of the physical DUT". Preview then skips 2 of 21 points
("Requested load exceeds the planning budget (0.72 A output at assumed efficiency 80 % and
source-current budget 90 %)") with nothing on the tile that predicts it. *Fix:* give the tile
the Real tile's anatomy: an "Envelope" key–value block (Source 0–60 V · 1 A · 60 W (DP821A
CH1 published envelope); Load synthetic CC; Protective limits none; Readback uncertainty
unquantified), a preset pill row when more than one mock bench exists, and two short lines:
"Shows: the workflow, the plan, the analysis and the report on a model converter." /
"Cannot show: this sample's behaviour, 12 V cold start, real readback errors." Also fill the
empty column under the tile (`.bench-tiles` `align-items:start`, line 63) instead of
leaving 350 px of white next to the Real tile (screenshot 2).

**M2. Preview scrolls the Plan under the sticky header.** `scroll_to` (lines 1153–1155)
calls `scrollIntoView({block:'start'})`; the header is 69 px (126 px on the phone) and
`.bench-plan` has `scroll-margin-top: 0` (probe), so the "Plan" heading disappears
(screenshot 5, top edge). The same applies to `.bench-confirm` and `.bench-run-section`.
*Fix:* `.bench-plan,.bench-confirm,.bench-run-section{scroll-margin-top:84px}` plus a
phone value, or scroll the heading with an offset.

**M3. Card interaction fails keyboard users.** Cards are `role=button` containers with
nested `<button>`s (lines 780–801); only `keydown.enter` is bound (lines 784, 807, 841,
854) so Space does nothing; the tiles have no `radiogroup`; Preview/Start are the last of 81
tab stops (lines 1568–1574). *Fix:* make the card title the `<button>` (stretch its hit
area over the card with `::after`), collapse Rename/Duplicate/Edit/Delete into one "⋯" menu
button per card, bind Space, wrap the tiles in `role=radiogroup` with arrow keys, and add a
"Skip to Preview" link after the header (or move the bar earlier in the DOM).

**M4. The card links are 10 px text in 22×23 px targets.** `link_button` (lines 775–777)
uses `size=sm dense`; the computed `.q-btn__content` font-size is 10 px and the Edit button
is 22×23 px, below the 24×24 px WCAG 2.2 minimum and hard to tap (phone tap sizes measured:
Rename 42×23, Edit 22×23, Delete 34×23). *Fix:* the "⋯" menu from M3, or `size=md` with
`min-height:32px` and 13 px text.

**M5. Every dimmed state falls below AA.** `.bench-card-item.greyed{opacity:.62}` (line 45),
`.bench-clause-row.untickable{opacity:.72}` (line 58), `.bench-real-details{opacity:.6}`
(line 68), `.bench-panel.stale …{opacity:.4}` (line 85) and the focus ring `#88b9d5`
(line 43) give 3.4, 2.9, 2.6, 2.3 and 2.1:1. *Fix:* never dim whole blocks; mark
unavailability with a grey badge and a lighter border, keep text at `#5a6f7e` or darker,
and use `#15608f` for the focus outline.

**M6. Six red paragraphs for laboratories this bench will never be.** `card()` prefixes
"Cannot run on this bench: " (line 797) to the catalog reason, which itself repeats the
card's subtitle ("… Conducted and radiated emissions from components and modules belongs to
a different laboratory: it needs an EMC test chamber…", `standard_recipes.py:150`). The
result (screenshot 3) is six greyed cards of red text taking more space than the runnable
tests, and red reads as an operator error. *Fix:* one compact grey card "Other laboratories
(not this bench): ISO 7637-2 — transient generator · CISPR 25 / ISO 11452 — EMC chamber ·
ISO 10605 — ESD simulator · ISO 16750-3 — shaker · ISO 16750-4 — climatic chamber" with an
expander for the full sentences; reserve `.bench-card-reason` red for tests the operator
chose that cannot run *now*.

**M7. The approval checkbox is inside the Real radio tile.** Lines 880–883 create the
checkbox inside the `role=radio` element without `click.stop` (the pills at 848/866 and
`link_button` at 776 do stop). A tap on it while Simulated is selected would both write the
bench profile (approval cleared) and switch the bench to Real. Not exercised; from DOM
(`approve_inside_tile: true`) and code. *Fix:* `box.on('click.stop', …)` or move the
checkbox below the tile.

**M8. Start is disabled without saying why.** `widgets['start'].disable()` (line 1574) and
`render_bar` (lines 1058–1063) never expose the reason; the disabled button is a paler
version of the enabled one (screenshot 1 vs 5). *Fix:* a bar hint "Preview first — Start
unlocks after a fresh plan" (and "Locked while a test runs" when `state['active']`), plus a
tooltip on the disabled button.

**M9. The ISO checklist breaks the phone layout.** `.bench-clause-row` (line 57) has
`grid-template-columns:minmax(220px,1.4fr) auto minmax(160px,1fr)` — a 380 px minimum plus
gaps inside a 334 px column — and the phone media block (lines 114–117) has no rule for it.
Opening the card widens the layout to 685 px and zooms the page out (screenshot 6,
middle). *Fix:* at ≤ 650 px use `grid-template-columns:1fr` with the badge and levels on
their own lines, and `minmax(0,1fr)` everywhere.

**M10. Phone chrome and the broken "SELECTED".** The sticky header (title + subtitle + pill
wrapping, 126 px) and the fixed bar (126 px) leave 592 of 844 px; the `.bench-summary-key`
(line 37) inherits `overflow-wrap:anywhere` from `.bench-summary` (line 36) and breaks as
"SELE / CTED" (screenshot 6, left). *Fix:* hide the subtitle and put the pill on the title
row at ≤ 650 px; `white-space:nowrap` on the key, or drop the top strip (the bar repeats it).

**M11. `/annotations` does not know the run is simulated.** The selector text is
"12T12-4A · 07:55:56 PDT (2026-09-30) · Complete" (`annotation_editor.py:370`,
`ui_models.job_title`), the uploader is enabled before any run is chosen (probe), and an
empty `.bench-message` 20 px box renders under the selector (`annotation_editor.py:373`;
screenshot 7 shows the pale bar). Attaching a photograph of a physical setup to a synthetic
run is exactly the category error the page should prevent. *Fix:* append "· Simulated" /
"· Real" to each option, show "Simulated run — photographs describe a physical setup; add
them only if this run documents a real bench" when a mock run is chosen, disable the
uploader until a run is selected, and hide the notice when it is empty.

### Minor

**m1.** Test cards repeat the grid (title "Quick sweep — 12 / 24 / 30 V × 0–1 A", subtitle
"12 / 24 / 30 V × 0–1 A"; the `card(...)` call at lines 900–905). Show the test type instead ("Steady-state load
sweep · 21 points · simulated") and drop the duplicate.

**m2.** Plan stat "Estimated time — simulated · seconds" (line 1087). Write "Virtual clock —
no waiting" or omit the stat for the simulated bench.

**m3.** The points table wraps "12 V" as "12 / V" and "Outside planning budget" over three
lines (`ui.table`, lines 1114–1118, with `.q-table td{white-space:normal}` at line 110).
Set `nowrap` on Input, Load, Estimated and Plan; wrap only Reason.

**m4.** "Stopped" vs "Acquisition stopped" (`ui_models.py:139–140`) mean cancelled vs
aborted but read alike. Use "Stopped by operator" and "Stopped by a fault".

**m5.** On the phone the Bench badge stretches to the row width (line 1409; the label is a
block inside a `1fr` cell) and looks like a coloured bar (screenshot 6, right). Add
`justify-self:start`.

**m6.** The badge tooltip (line 978) repeats the note already printed under the row
(screenshot 4). Keep one.

**m7.** Dialogs are `persistent` (line 481): Escape does not cancel (probe). Allow Escape for
any dialog that has a Cancel button.

**m8.** Editors ask for the file name first ("Save converter as (file name,
letters/digits/-_.)", line 625; "Save test as …", line 690) before the human name. Derive
the file name from the plain name and show it as a hint.

**m9.** No real headings and no document language: `.bench-h2` are `<div>`s (0 `<h1>–<h3>`
on both pages), `<html lang="">`. Emit `<h1>`/`<h2>` elements and set `lang="en"`.

**m10.** One vocabulary for the same fact: tile "Nothing is switched on", header "Idle —
nothing switched on", card "· simulated", plan "Simulated — nothing switched on", run
"Simulated test · no real instruments", report "SYNTHETIC". Use "Simulated" on the page and
say once (on the tile) that reports label it SYNTHETIC.

**m11.** `+ New test` sits after the standards group (lines 911–913), far from the saved
tests it creates; put it at the end of the saved-tests grid.

**m12.** Radii: cards 8 px (line 42), `/annotations` cards 12 px (line 112), report controls
6 px. Pick one (6 px matches the report).

## 4. What already works well (with evidence)

- The order and vocabulary of the page match brief §2 and §13.1: "1 Which converter? →
  2 Simulated or real bench? → 3 Which test?", Preview mandatory, Start last; the header
  subtitle spells the sequence out.
- Simulated vs real is decided once, in question 2, and every downstream label follows: the
  Start button says "Start simulated test", the plan says "Simulated — nothing switched on",
  the Reports badge says "Simulated", and the report says "SYNTHETIC evidence" and "values
  come from a software model, not from hardware" (screenshots 5 and 8).
- The plan is honest and readable: "19 / 21", grouped skip reasons with the arithmetic that
  produced them, "Skipped points stay in the saved plan and are listed in the report as not
  run", and the planning caveats ("Planning estimates are not measurements or validated
  safety limits", "no-load input draw is unknown, not zero") are one click away.
- Stale-plan handling works as documented: changing the converter after a Preview instantly
  shows "Settings changed — Preview again before starting." and disables Start.
- The standards catalogue never bluffs: every clause states its concrete blocker ("needs
  10 ms edges", "excluded by policy", "60-min hold exceeds the 540 s run budget") and the
  card counts "3 of 19 clauses runnable on this bench".
- The Real tile keeps the four protective limits permanently visible and says "Start can
  switch outputs on"; amber is used only for Real.
- The coordinator's fresh simulated job appears in Reports without a manual refresh, labelled
  "12T12-4A · Quick sweep — 12 / 24 / 30 V × 0–1 A · Simulated · Complete 19 / 19 points"
  with local time and the "Times are local / evidence files record UTC" legend.
- Delete confirmations name the item and state the consequence ("Past runs keep their own
  copy"); Delete is the filled red button and Cancel the outlined one.
- No horizontal overflow at 390 px on the base page, no browser console errors during the
  whole walk, and the page finished loading on each of the four visits without hitting the
  Playwright waits.

## 5. Top 5 changes before the owner's review

1. Fix the two visible bugs on the first screen: give the selected limit-preset pill a white
   label (`text-color=white`, beating Quasar's `text-primary`) and stop the Reports "When"
   column from overprinting "Run" (`auto` column width or a two-line time).
2. Give the Simulated tile the Real tile's anatomy — the synthetic envelope (0–60 V, 1 A,
   60 W, no protective limits), what the model can show and cannot show — so a skipped
   simulated point is predictable from the tile, not a surprise in the plan.
3. Stop badging §4.5 and §4.6.2 as "runs here": mark them "runs here after approval",
   leave them unticked, and add the approval control (or name where approval happens) so
   "Add as tests" never produces tests the simulated bench immediately refuses.
4. Make the page survive a phone: single-column clause rows so the checklist cannot widen
   the layout to 685 px, a one-row header at ≤ 650 px, `white-space:nowrap` on "Selected",
   and `scroll-margin-top` so Preview does not hide the Plan heading under the sticky header.
5. Rebuild card interaction for keyboard and touch: one "⋯" menu per card instead of four
   10 px nested buttons, Space activation, a radiogroup for the tiles, AA-contrast
   non-runnable states instead of `opacity`, and a spelled-out reason on the disabled Start.
