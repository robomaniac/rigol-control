# Independent review: configured acquisition and local jobs

Review date: 2026-09-27 UTC.

## Scope and conclusion

Reviewed `src/dcdc_bench/real_backend.py`, `job_service.py`, `activity.py`, their integration with the shared fixed acquisition lifecycle, and the focused fake-bench tests. This was a separate review of the backend author's implementation. No hardware commands, browser or renderer were run by this review.

**No open blocking finding remains in the reviewed implementation after the corrections below.** The backend is deliberately limited to the declared DP821A CH1 / DL3031A local-sensing DC procedure. This conclusion does not certify arbitrary hardware profiles or instrument measurement accuracy.

## Findings corrected during review

| Finding | Correction reviewed |
| --- | --- |
| A setpoint-relative input guard could admit measured input below the DUT's declared minimum. For example, a 9.1 V request previously allowed an 8.9 V readback. | The lower guard now also includes the DUT minimum plus the declared readback margin, matching the treatment of the upper DUT boundary. |
| Cancellation arriving during instrument configuration could miss the initial cancellation check and permit source startup. | Cancellation is checked before startup and again immediately before the actual `:DELAY ON` source-enabling command. |
| A worker that exited during imports could leave a permanently queued job with no recorded PID. | A separate durable launch record preserves the launched PID without overwriting the worker's state. Status detects early exit, and both status and worker enforce the 120-second launch expiry. |
| A timed-out `systemd-run` call could have already created a service, allowing a late worker after the API reported failure. | Every launch exception now writes a durable cancellation marker. A late worker must check it before acquisition. |
| A custom activity-lock path could be lost across the systemd launcher, separating the UI's busy check from the worker's lease. | The launcher forwards the selected activity-lock and rendering-path environment settings explicitly. |
| Profile guard settings could exceed a smaller capability declared in the saved bench. | Source current setting and load current/voltage guard checks now reject settings above the saved capabilities, in addition to the fixed backend envelope. |
| Inherited preview policy labels could describe a different fixed procedure. | Prepared plans use the configured backend's actual policy identity. |

## Contracts checked

- Plan previews and profile saves perform no instrument I/O. Excluded points remain in the plan and evidence.
- Starting a real job requires confirmation of the exact plan hash, wiring/polarity, CH1, protections and both configured instrument serials. Profile and private-inventory changes invalidate stale previews.
- The worker rebuilds eligibility from saved profiles; it does not trust arbitrary executable flags. The inventory snapshot is checked again before acquisition.
- The first eligible point is selected explicitly, so an excluded first request is not energized or used to label later data.
- Electrical bounds come from the configured profile within the fixed supported envelope. Unsupported temperature, no-load and sensing requests are rejected explicitly.
- Real acquisition holds the same cross-process activity lease used by report rendering. A busy bench does not create an automatic hardware queue.
- Voltage phases use verified OFF transitions and fresh unloaded startup. The separate startup/descent experiment is the explicit path for continuously energized voltage changes.
- The existing acquisition lifecycle retains durable raw samples, point identities, independent source deadline and best-effort shutdown of both instruments. A source-OFF failure leaves its independent deadline uncancelled.
- Optional reports are built in a separate process after finalized evidence proves all required OFF states. Report retry cannot invoke acquisition.
- Cancellation addresses the recorded worker identity, and report cancellation terminates the owned report process group.
- Artifact resolution stays within the selected job's allowed directories. Live readbacks come from a bounded tail of complete raw cycles and are labelled unqualified.
- Operator notes and attachment references are recorded before finalizing acquisition evidence. Attachment references are descriptions; they are not an implemented image-upload workflow.

## Verification evidence and remaining scope

The backend author reported **25 focused backend/job-service tests passing in 36.53 seconds** after the principal review fixes, including launcher-environment and report-cancellation coverage. The reviewer inspected the regressions for lower input bounds, cancellation during configuration, early worker exit, launch expiry and launcher timeout. The subsequent coordinated ordinary suite passed **378 tests, with 13 browser/PDF tests deselected, in 220.54 seconds**, including the added saved-capability guard regression. A later focused UI/job-service run passed 39 tests. These are overlapping runs, not counts to add together.

The previously failing startup/descent report fixture was rerun separately and passed after the report model acquired an explicit common-load constraint for its cross-input series. That fixture verifies seven voltage-axis points, the 9.1 V actual programming label and exclusion of startup/transition cycles from accepted means.

The physical startup/descent result was acquired by the separately reviewed fixed procedure. See `startup-descent-results-review.md` for that evidence.

A subsequent configured real job, `20260927T223820Z_bb4a479f`, exercised the deployed NiceGUI selection, Preview, confirmation and Start callbacks using a lightweight Socket.IO client. It measured three points at 24 V input and requested loads of 0.1, 0.25 and 0.5 A. All three qualified after the client disconnected; source, load and source timer were verified OFF before the automatic report process began. This is physical integration evidence for the new reusable path. It is separate from browser rendering/accessibility checks and from the fixed startup experiment. See `configured-workflow-results-review.md` for the independent numerical review.
