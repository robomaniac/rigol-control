# Local bench workflow verification

Reviewed on 27 September 2026 on the Raspberry Pi running the real DP821A CH1
and DL3031A bench. This verifies the local operator page and its independent
acquisition worker. The measured converter is the 12T12-4A sample.

## Implemented workflow

The page provides four named tabs: **Bench**, **DUT and recipe**, **Run**, and
**Reports**. An operator can choose saved profiles, enter input voltages and
output loads, review the executable grid and exclusions, confirm the real
setup, start a job, inspect progress, request a safe stop, and open the generated
reports. Editing a setting clears the accepted preview and its confirmations.

The worker owns the instruments independently of the browser. It checks the
saved plan and equipment identities again before acquisition. Report links
appear only when the corresponding artifact is successfully generated.
Report-only retry preserves the measurements and does not repeat acquisition.

## Verification performed

| Check | Evidence and result |
| --- | --- |
| Ordinary regression suite | Coordinating agent recorded 378 passed, 13 deselected. |
| Focused UI/job checks after review fixes | Coordinating agent recorded 39 passed. |
| Final focused UI/report checks | Coordinating agent recorded 57 passed, including the real-job shutdown requirement for the source deadline timer. |
| Actual rendered page | Chromium loaded the production page on port 8081, displayed the saved converter and recipe, and captured a desktop screenshot. No page errors or failed requests were recorded in this successful read-only inspection. |
| Accessible controls | The rendered accessibility tree contains the four named tabs, labeled converter/recipe fields, and the Preview button. Icon text does not replace these accessible names. |
| Actual preview callback | A Socket.IO client exercised the production NiceGUI controls and obtained the reviewed three-point real preview, with an estimated 62 seconds of acquisition. |
| Actual Start callback | The coordinating agent supplied the approved confirmations through the production NiceGUI callbacks. Job `20260927T223820Z_bb4a479f` acquired all three requested load points after the controlling client disconnected. |
| Shutdown | The real job verified the source output, load input and source deadline timer OFF. |
| Automatic reports | The completed job produced HTML and PDF from its saved real measurements. Its final presentation revision, `r0002`, serves HTML (6,377,868 bytes) and PDF (105,627 bytes). |
| Saved report links | The production Reports tab served HTML, PDF and report-model JSON successfully. The browser verified HTTP 200 responses, the PDF signature, three qualified points and the expected run identifier. |
| Reopen completed run | The browser selected View run and displayed Complete, 3 / 3 accepted load points, the final readings, verified OFF, and report links. |
| Mobile layout | At a 390 px viewport, both the completed run and converter/recipe page had a 390 px document width. The forms stack into one column and the four readings into two columns. Screenshots were visually inspected. Tabs use their own horizontal navigation when space is limited. |
| Control/report separation | The served HTML has a sandbox policy without same-origin access. A foreign WebSocket origin and a foreign HTTP Host were both rejected with HTTP 400. |

The real workflow used **24 V input and 0.1, 0.25 and 0.5 A output loads**.
Its purpose was to verify the operator-to-worker-to-report path; the larger
voltage and load characterizations remain separate evidence.

The successful browser inspection covered rendered controls and accessibility.
The successful real Start used the same NiceGUI event callbacks through a
Socket.IO client. It is not presented as a successful automated browser click
through the complete real acquisition sequence.

The resulting run is
`20260927T223823.159616Z_real_0038ff`, beneath
`workspace/jobs/20260927T223820Z_bb4a479f/runs/`.

## Issues found and corrected

- The default three-second page setup timeout was too short on the busy Pi.
  The page now returns a loading frame before reading profiles, waits for the
  client connection, and handles a deleted client without applying incomplete
  data to the controls.
- Explicit accessible names were added to tabs and action buttons.
- The progress bar's default raw fraction label was suppressed. The readable
  accepted-point count remains below the bar. This final one-property change
  was checked against NiceGUI's installed implementation after the screenshots;
  the retained screenshots show the earlier small `1` label at completion.
- Asynchronous profile loads, preview creation and status polling now discard
  stale results. A pending profile load cannot leave Start enabled behind a
  different visible converter or recipe.
- Active acquisition is tracked separately from the selected historical run.
- Cancellation before acquisition no longer claims that measurements were
  preserved or that report generation failed.
- Published report aliases and existing download ZIP files remain available on
  the same forwarded port. HTML reports are sandboxed separately from bench
  controls; the control server accepts same-origin connections on loopback.

The separate [workflow code review](workflow-ui-review.md) records the targeted
review of these fixes. [Operator instructions](bench-ui.md) describe startup,
port forwarding, current measurement limits, reconnecting, and saved evidence.

## Retained evidence and scope

The final read-only Reports browser exited successfully. It recorded no page
errors. Its audit, script, log and three screenshots are retained in the run's
`reviews/ui-workflow/` directory:

- `reports-audit.json`: served artifact sizes, three-point qualification,
  accessible tab names, Host/Origin rejection and mobile geometry.
- `completed-run.png`: desktop completed run and report links.
- `mobile-completed-run.png`: completed run at 390 px.
- `mobile-recipe-final.png`: converter and recipe form at 390 px.

The initial desktop/ARIA inspection and the successful NiceGUI protocol
acceptance are retained separately by the coordinating agent in the same run's
reviews. The final browser fetched the HTML/PDF artifacts without opening
another heavy report-rendering session. Detailed report plot and PDF layout
reviews are separate from this operator-page acceptance.

No instrument access was performed by the frontend review agent. The
coordinating agent owned the approved physical acquisition and monitored its
shutdown. Browser processes were closed before acquisition and report rendering
to avoid competing for the Pi's limited memory.

## Later report presentation revision

Configured report `r0003` retains this acquisition and analysis, with the newer
engineering figure labels, curve styles and nominal-voltage reference. The
artifact sizes and browser evidence above describe their recorded revisions.
See [style verification](engineering-style-verification.md) for the later checks.
