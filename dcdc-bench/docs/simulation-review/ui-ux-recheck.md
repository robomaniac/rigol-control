# Bench page UI/UX re-check — after the fix wave

Re-checked on 2026-09-30 against the live loopback service (`http://127.0.0.1:8081/`,
Host `localhost`) running `dcdc-bench-hardening` 24d9371 (the service was restarted at
09:20 PDT; `ui.py`, `ui_models.py`, `standard_recipes.py`, `standards.py`,
`annotation_editor.py` and `job_service.py` in the served checkout are byte-identical to the
reviewed tree). This re-check was performed by an automated agent in the same senior
UI/UX-designer role as [ui-ux.md](ui-ux.md), not by a human reviewer. Nothing here opened an
instrument or started a job.

## 1. Method

- Playwright with the system `chromium-headless-shell`, two short sessions (one browser at a
  time), 1440×900 and 390×844 (mobile emulation, 2×). Walk: first screen → tiles → standards
  cards → ISO 16750-2 checklist opened and folded → *Quick sweep — 12 / 24 / 30 V × 0–1 A*
  selected **with the Space key** → **Preview** → points table → another test selected (stale
  plan) → Reports → `/annotations` (fresh simulated run chosen). Phone: first screen, checklist,
  Reports.
- **Start**, **Add as tests**, the 12 V / 24 V class toggle and the approval checkbox were never
  pressed. Preview was only run with the recipe already bound to the selected converter
  (`workspace/profiles/recipe/12t12-4a-quick.json` → `dut_profile_id: 12t12-4a`), so no profile
  was written.
- Every text/background pair quoted below is a computed WCAG contrast that includes inherited
  `opacity`; geometry is `getBoundingClientRect`; roles and states are read from the DOM.
- Inputs: the first review's B1–B3, M1–M11, m1–m12 and Top 5; the "Bench page" and "Standards
  catalog" rows of [README.md](README.md); commits b4800b9, e535478, 1c84d89; the constants
  `SIMULATION_CAN/CANNOT`, `REAL_CAN/CANNOT`, `SIMULATION_SEQUENCE`, `PLAN_STATUS_LEGEND` in
  `ui_models.py`.
- Not observed (no job may be started): the running header pill "Simulation: Acquiring…",
  the sequence's *current* step, the section lock and the two-step Stop, and the greyed card
  that "Add as tests" produces for an approval-first clause. Statements about them come from
  the code.

Screenshots (all ≤ 300 KB, in `screenshots/`):

| # | File | What it shows |
| --- | --- | --- |
| 1 | [recheck-01-desktop-first-screen.png](screenshots/recheck-01-desktop-first-screen.png) | 1440×900 first screen: readable "24 V converter tests" pill, "⋯" menus, Start hint |
| 2 | [recheck-02-phone-first-screen.png](screenshots/recheck-02-phone-first-screen.png) | 390×844 first screen: one-row header, "SELECTED" on one line, full-width bar buttons |
| 3 | [recheck-03-desktop-simulation-tile.png](screenshots/recheck-03-desktop-simulation-tile.png) | The two tiles: synthetic envelope table and the two can/cannot panels |
| 4 | [recheck-04-desktop-iso-checklist.png](screenshots/recheck-04-desktop-iso-checklist.png) | ISO 16750-2 checklist: §4.5 amber "runs here after approval", unticked, with its note |
| 5 | [recheck-05-desktop-preview.png](screenshots/recheck-05-desktop-preview.png) | Plan after Preview: heading visible, time estimate, planner status word, after-Start sequence |
| 6 | [recheck-06-phone-checklist.png](screenshots/recheck-06-phone-checklist.png) | 390 px checklist: single-column rows, layout still 390 px wide |

## 2. Blockers

| Item | Verdict | Evidence |
| --- | --- | --- |
| **B1** Selected limit-preset pill unreadable (1.0:1) | **Fixed** | `preset_pill` now renders the selected pill `unelevated color=primary text-color=white` (ui.py 934) and the sheet has `.bench-pill.on,.bench-pill.on .q-btn__content{color:#fff}`. Computed: `rgb(255,255,255)` on `rgb(21,96,143)`, **6.77:1**; label "24 V converter tests" readable in screenshot 1. Residual: the pill text is still 10 px (Quasar `size=sm dense`). |
| **B2** Reports "When" overprints "Run" | **Fixed** | `.bench-report-row` grid is `max-content minmax(0,1.4fr) max-content max-content minmax(220px,1fr)` (ui.py 122); computed columns 168.9 / 275.1 / 159.3 / 84.7 / 220 px. First row: When cell right edge 411 px, Run cell left edge 423 px — no overlap on any of the 7 rows. On the phone the row collapses to one column and the header row is hidden. |
| **B3** "runs here" promised what the simulated bench refused | **Fixed** (readability residual, §5) | Catalog statuses `runs_here` / `runs_after_approval` / `mock_only` / `needs_split` (standards.py 236–239; standard_recipes.py 66–71). DOM: §4.5 and §4.6.2 carry the badge **"runs here after approval"** with class `bench-badge-partial` (amber, 6.67:1), `aria-checked="false"`, enabled; only §4.2 is pre-ticked (green "runs here", 9.06:1). Card meta "19 clauses: 1 clause runnable now, 2 after approval"; footer "1 of 19 clauses runnable now on this bench · 2 after approval". The row note names the place: "Approval happens in the saved recipe, not on the bench page: set authorization.uvlo_approved to true and authorization.protective_policy_id to the bench profile's protective_controls.policy_id…" (the "say where approval is done" alternative of the original fix). No in-page approval control was added, by design (brief §7.5: approving is the owner's act). |

## 3. Top 5 changes

| # | Asked | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Fix the pill label and the Reports column | **Fixed** | B1 and B2 above. |
| 2 | Give the Simulated tile the Real tile's anatomy | **Fixed** | Tile "Simulation" has a `role=table` "Synthetic envelope": *Synthetic source 0–60 V · 1 A · 60 W* · *Synthetic load constant current, up to 40 A* · *Protective limits none — only the planning budget bounds the plan* · *Readback uncertainty synthetic example specification, not an instrument*, then "What the simulation can and cannot do" with 5 ✓ and 4 ✗ lines (`SIMULATION_CAN/CANNOT`); the Real tile gets the matching 3 ✓ / 4 ✗ panel (`REAL_CAN/CANNOT`). Contrast: keys 5.97:1, values 13.53:1, ✓ lines 9.06:1, ✗ lines 10.3:1, heads 12.37:1. Both tiles are 724 px tall (`align-items:stretch`): the empty column under the old stub is gone (screenshot 3). The 1 A / 60 W source now predicts the plan's "2 points assumption_limited … source-current budget 90 %". |
| 3 | Stop badging §4.5 / §4.6.2 as "runs here" | **Fixed** | B3 above. |
| 4 | Survive a phone; keep the Plan heading visible | **Fixed** | Phone: header 126 → **53 px** (subtitle `display:none`, pill on the title row), `.bench-summary-key` `white-space:nowrap`, 19 px tall, "SELECTED" on one line; opening the checklist keeps `innerWidth` / `scrollWidth` at **390 px** (was 685), clause rows are one column (`304px`), 0 badges clipped, `visualViewport.scale` 1 (screenshot 6). Desktop: `.bench-plan{scroll-margin-top:84px}` (72 px on the phone); after Preview the "Plan" heading's top is at 129 px with the header bottom at 69 px — fully visible (screenshot 5). Content area on the phone 592 → 659 px even though the bar grew to 132 px with the hint line. |
| 5 | Rebuild card interaction for keyboard and touch | **Partially** | Done: 14 card faces are real `<button class="bench-card-select">` with **0** nested interactive elements and 0 `div[role=button]` containing buttons; **Space** selected the Quick sweep card (`aria-pressed` → `true`); one "⋯" menu per card (7, each 32×32 px, `aria-haspopup=menu`, `aria-label="Actions for …"`); tiles are a `role=radiogroup` "Simulation or real bench" with two `role=radio` and arrow/Enter/Space handlers (ui.py 954–959); no dimmed block remains (§4 M5); the disabled Start explains itself. Not done: Preview is still the **last** tab stop (index 61 of 62 focusables, down from 81) and Start, when enabled, follows it; no "Skip to Preview" link. |

## 4. Majors and minors, briefly

| Item | Verdict | Evidence |
| --- | --- | --- |
| M1 Simulated tile envelope | Fixed | Top 5 #2. |
| M2 Plan under the sticky header | Fixed | Top 5 #4. |
| M3 Card keyboard interaction | Partially | Top 5 #5 (tab order). |
| M4 10 px links in 22×23 px targets | Fixed | Links replaced by one 32×32 px menu button per card; on the phone the menus are 32×32 at x = 322. The Real tile's preset pills keep 10 px text. |
| M5 Dimmed states below AA | Fixed | Greyed standards cards `opacity` 1, note text 4.92:1; untickable clause labels 5.94:1 (only Quasar's own `.disabled{opacity:.75}` remains), clause notes 5.0:1, grey badges 5.3:1; Real details `opacity` 1, keys 5.97:1; stale note 6.67:1; focus ring `3px solid #15608f` measured on a focused card face, **6.77:1** (was 2.1:1). |
| M6 Six red paragraphs for other laboratories | Partially | Now grey `bench-card-note` "Not on this bench: …" at 4.92:1 instead of red, cards no longer dimmed. Still six separate 218 px cards (same height as the ISO card) rather than one compact "Other laboratories" card. |
| M7 Approval checkbox inside the Real radio | Fixed (functional) | `box.on('click.stop', …)` (ui.py 1018): ticking cannot switch the bench. The checkbox is still nested inside the `role=radio` element (ARIA nesting), so assistive technology may still announce it as part of the radio. Not exercised (it writes a profile). |
| M8 Start disabled without a reason | Fixed | Hint `role=status` "Preview first — Start unlocks after a fresh plan." (5.24:1) under the bar on arrival and again after the plan goes stale; hidden once Start is enabled; "Locked while a test runs on the bench…" and "The plan cannot start: see the Before Start list…" exist in `start_hint()` (ui.py 1210–1223). No tooltip on the button itself. |
| M9 Checklist breaks the phone layout | Fixed | Top 5 #4. |
| M10 Phone chrome, broken "SELECTED" | Fixed | Top 5 #4. |
| M11 `/annotations` unaware of Simulation | Fixed | Options read "12T12-4A · 07:55:56 PDT (2026-09-30) · Simulation · synthetic data · Complete" / "… · Real bench · measured · …" (`run_option_text`); the uploader has the `disabled` class until a run is chosen; the empty notice is hidden (`offsetParent` null); choosing the simulated run shows the amber notice "Simulation run — photographs describe a physical setup; add them only if this run documents a real bench. No saved sensor markers for this run yet." (6.42:1) and unlocks the uploader. |
| m1 Test card repeats the grid, no test type | Not fixed | Card still "Quick sweep — 12 / 24 / 30 V × 0–1 A" / "12 / 24 / 30 V × 0–1 A" / "21 points · simulated". |
| m2 "Estimated time — simulated · seconds" | Fixed (wording nit, §5) | "Measurements: about ~42 s (simulated) · Report: typically 1–4 min on a Raspberry Pi". |
| m3 Points table wraps "12 V" | Fixed | Input, load, estimated and plan cells carry `nowrap` (`white-space:nowrap`); only Reason wraps. |
| m4 "Stopped" vs "Acquisition stopped" | Not fixed | `state_label` unchanged (ui_models.py 236–237); both words appear in Reports and in the `/annotations` options. |
| m5 Phone Bench badge stretched | Fixed | `.bench-report-row .bench-badge{justify-self:start}`; badge 159 px wide in a 322 px column. |
| m6 Badge tooltip duplicating the note | Fixed | Tooltip only when a row has no note (ui.py 1136). |
| m7 Dialogs `persistent` | Not fixed | ui.py 528. |
| m8 File name asked before the human name | Not fixed | ui.py 697, 770. |
| m9 No `<h1>`–`<h3>`, empty `lang` | Not fixed | 0 headings on `/`; `document.documentElement.lang` is `""`. |
| m10 One vocabulary | Fixed | "Simulation" on the tile, the Start button, the plan ("Simulation — nothing switched on"), Reports ("Simulation · synthetic data") and `/annotations`; a glossary is linked from the footer (`/glossary`, HTTP 200). |
| m11 "+ New test" far from the saved tests | Fixed | It is the 8th card, before the first standards card (9th). |
| m12 Mixed radii | Partially | `.bench-card` on `/annotations` is now 8 px like the page cards; the report's controls stay 6 px. |

## 5. Regressions and new observations from the changes

No functional regression was found: 0 console errors and 0 page errors on both viewports, no
horizontal overflow at 390 px, the stale-plan flow ("Settings changed — Preview again before
starting.", Start disabled, hint shown) and the Reports rows behave as before.

1. **"about ~42 s".** `simulation_time_text` writes "Measurements: about {duration_text}"
   and `duration_text` already prefixes "~", so the stat reads "about ~42 s" (screenshot 5).
   Drop one hedge.
2. **The §4.5 / §4.6.2 note is a wall of text.** The B3 fix appends the approval sentence to the
   `; `-joined conditions, producing a ~600-character, six-line 13 px paragraph in which "Approval
   happens in the saved recipe…" sits in the middle (screenshot 4). Lead with the approval
   sentence on its own line (or as the badge's tooltip target) and fold the remaining conditions
   behind a "details" expander; the §4.2 note has the same shape at three lines.
3. **The tile says the same thing three times.** Sub-line "Nothing is switched on. Synthetic
   readings, real report layout; every output is labelled SYNTHETIC." is then repeated by
   ✓ "Labels every output SYNTHETIC…" and ✓ "Touches no instrument: … nothing is switched on."
   One of the three can go (the sub-line could shrink to "A software model; every output is
   labelled SYNTHETIC.").
4. **Question 2 is now a full screen.** Both tiles are 724 px tall at 1440×900; the page is
   honest but the operator scrolls past ~800 px of bench facts to reach "Which test?". If this
   proves heavy in use, the can/cannot panels could open from a single "What it can and cannot do"
   disclosure that is expanded by default on first visit only.
5. **Pre-existing, now more visible:** the sticky header is `rgba(255,255,255,.97)`, so text
   scrolled under it ghosts through faintly (top edge of screenshots 4 and 5). An opaque header
   would remove it.
6. The phone bar grew from 126 to 132 px for the hint line; since the header shrank by 73 px the
   net content area still grew (592 → 659 px). Not a regression, recorded for the record.

## 6. Verdict for the owner

**Ready to review.** All three blockers are fixed with measured evidence (pill 6.77:1 instead of
1.0:1; When/Run cells no longer overlap; §4.5 and §4.6.2 are amber "runs here after approval",
unticked, counted separately and say where approval is recorded), and four of the Top 5 are
fully fixed; the fifth (card interaction) is fixed except that Preview/Start remain the last tab
stops with no skip link. Of the eleven majors, nine are fixed, M6 is grey-not-red but still six
cards, and M7 is fixed functionally while the checkbox stays nested in the radio. Six minors
remain open (test-type on cards, "Stopped" vs "Acquisition stopped", `persistent` dialogs,
file-name-first editors, no `<h1>`/`lang`, mixed radii) and the fixes introduced two small
wording issues worth a one-line change each: "about ~42 s" and the six-line §4.5 note that buries
the approval sentence. Nothing found blocks the owner's walkthrough of the Simulation flow.
