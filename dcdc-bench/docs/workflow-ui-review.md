# Operator workflow code review

This review was performed by an automated agent role in the same authoring pipeline, not by a human or external reviewer.

Reviewed on 27 September 2026. Scope: `ui.py`, `ui_models.py`, the supporting
`JobService` state/artifact metadata, and `docs/bench-ui.md`.

**Outcome:** the six findings from the initial review are resolved by the
current code. No remaining blocking issue was found in this targeted static
review. **Browser acceptance remains pending the coordinating agent's run.**
This review did not start a browser, run tests, render a report, or access
instruments.

| Initial finding | Resolution verified in code |
| --- | --- |
| A delayed profile load could replace visible settings behind an accepted preview. | Pending loads disable Preview and Start. Selection tokens discard superseded loads; applying a load invalidates the preview. Saving checks the generation after each asynchronous operation. |
| Existing `/Runs/*-download.zip` links would fail on the replacement report server. | The startup publication allowlist includes files as well as directories; direct published files resolve through the same route. |
| Cancellation before acquisition claimed measurements were preserved and reports had failed. | Terminal jobs without a run directory say that no measurements were acquired. Missing-format warnings require a run directory. |
| Viewing an old run cleared the busy state of a known active job. | The active job identifier is tracked separately from the displayed run; polling checks that active job while history is selected. Preview refreshes the job list. |
| A delayed status response could show readings from one job with Stop targeting another. | Polling captures the selected job identifier and discards stale responses. Selection clears old controls; Stop is bound to the displayed snapshot's job identifier. |
| Saved run titles omitted the converter model. | New jobs persist `dut_model`, which the report list uses in its title. Older jobs retain the generic fallback. |

HTML, PDF, and report-data links require the corresponding artifact status to
be successful. The backend checks that their files exist. Report generation is
shown separately from acquisition, and retry uses saved evidence after verified
shutdown. The backend independently rechecks profile and inventory hashes,
plan identity, physical confirmations, and global activity before starting.

The documented workflow matches the implementation: choose the bench and
converter, enter voltages and loads, preview limits and exclusions, confirm the
real setup, start, inspect progress, then open HTML or PDF. The documentation
explains SSH forwarding, the optional existing 8081 report links, independent
worker ownership, cold starts at each input condition, and current unsupported
measurements/assets. Published aliases are snapshotted at startup and require a
server restart after changing their targets.

Publishing helpers are currently inside `ui.py`; no separate
`published_reports.py` file was present in the reviewed checkout.

## Remaining acceptance work

The coordinating agent owns browser checks of the visible controls, profile
switches, reconnect/progress, published downloads, and report interactions.
Static review does not establish their rendered appearance, browser behavior,
or performance on the Pi. A job created in a separate client can make another
client's display briefly stale; the backend's global start check remains the
authority and refuses a second active job.
