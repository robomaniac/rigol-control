# Configure and run a converter test

The local bench UI saves DUT, equipment and recipe profiles. A profile is data:
creating one does not contact an instrument. A new converter can use the same
workflow without editing Python, within the supported limits below.

## Start the UI

From the checkout, using its installed virtual environment:

```sh
.venv/bin/python -m dcdc_bench ui --root dcdc-bench/workspace \
  --inventory Software/config/lab.yaml --host 127.0.0.1 --port 8082
```

Use the actual path to your private benchctl inventory. It must name
`psu_rigol_1` and `load_rigol_1` with their expected serial numbers and DP800 /
DL3000 driver types. Never publish that private file with your profiles.
Forward the selected port through SSH, then open `http://localhost:8082`.

1. Select or save a DUT, bench and recipe. Start with the mock bench for a
   complete simulated run, or `rigol-local-limited` / `real-24v-small-grid` for
   the supported physical bench.
2. Preview the plan. Review the requested input voltages, output currents,
   exclusions, measurement boundary, equipment serials and protective settings.
   Editing a saved profile invalidates that preview.
3. For real acquisition, confirm CH1 wiring/polarity, protective settings and
   both serial numbers against that exact plan. Press Start once. There is no
   automatic hardware queue or automatic acquisition retry.
4. Follow the requested condition and recent queried readings. Live values are
   unqualified observations; the final report applies point qualification.
   Stop requests bounded cleanup and preserves any partial evidence.
5. After source, load and independent source timer are verified OFF, a separate
   process builds HTML and PDF. A report failure preserves the acquisition.
   **Retry report** makes a new report revision without powering the DUT again.

Setup notes are saved with the run and appear as operator observations in the
report. The service API also accepts attachment *references* (role, name,
caption, location); these are metadata, not uploaded or embedded image files.

## Current physical envelope

| Setting | Supported policy |
|---|---|
| Instruments | Verified Rigol DP821A CH1 and DL3031A; local load sensing |
| Input | Programmed 1–35.8 V, within the DUT rating with DC accuracy margin |
| Nominal output | 1–12 V; explicit upper guard no higher than 13.2 V |
| Supply current limit | Explicit 0.05–1 A; cannot exceed the saved bench capability |
| Output current | Positive loads 0.05–2.5 A; guard at most 2.55 A |
| Output power | At most 34 W using the configured upper voltage guard |
| Settling | 5–15 s dwell, 4–15 s window, at least 5 queried readings |
| Acquisition | 5–15 s minimum, at least 5 complete cycles; 1–2 s polling |
| Query timing | Maximum interchannel span at most 750 ms |
| Run duration | Planning estimate at most 540 s; software deadline 660 s |
| Independent cutoff | Verified 720 s one-shot source timer per input-voltage phase |

The saved DUT and bench ratings can impose tighter limits. Unsupported and
assumption-limited requests remain visible in the plan and report. A 0 A
request is an enabled no-load observation: it must be the first request of its
input-voltage phase, the load input stays OFF, input consumption is reported and
efficiency is not applicable; it is not yet qualified on the bench. Temperature,
arbitrary SCPI commands, remote sensing and dynamic tests are not implemented in
this workflow. Unknown acceptance requirements stay unevaluated.

Each input-voltage phase starts from both outputs OFF, checks residual source
voltage, configures protections and proves unloaded startup before enabling the
load. This is a cold-start sweep. The separately reviewed warm-start/descent
procedure is not silently selected for a converter that cannot cold-start at a
requested input voltage. Boundary or hard-guard failures stop the run.

These are polled DC stop criteria, not guarantees against fast overshoot or
transient damage. The report preserves the actual queried values, their timing,
qualification and the source/load-terminal measurement boundary.

## Surviving UI and SSH disconnects

For a persistent Linux UI service, set:

```ini
Environment=DCDC_JOB_LAUNCHER=systemd
```

Each job then runs in its own transient user service, with `Restart=no`, a
2700 s total lifetime limit and its own process group. Closing the browser,
disconnecting SSH or restarting the UI service does not stop that job. User
service persistence after logout depends on the host's user-manager/linger
configuration. A failed launch leaves a cancellation marker; workers starting
more than 120 s after the launch request refuse to acquire.

The default `detached` launcher is useful from a developer terminal and creates
a new session. It does not provide isolation from a parent service's cgroup
shutdown. It is therefore not the persistent UI deployment setting. A failed
systemd launch never falls back to this launcher automatically.

All fixed and configured real procedures share an exclusive activity file lock
with rendering. An acquisition or report that finds it busy fails explicitly;
it does not wait to start hardware later. `DCDC_ACTIVITY_LOCK` can override the
path, but all cooperating processes must use the same value.

## Saved evidence

The workspace keeps JSON profiles, immutable plan previews and one directory per
job. `job.json` describes orchestration; `worker.log` records process output.
Each acquisition has its own request/plan snapshots, raw samples, events, final
run record and SHA-256 integrity manifest. Report revisions remain underneath
the acquisition. Cancellation, reporting failures and retrying a report do not
overwrite completed acquisition evidence.
