# Process model on the 1 GB bench Pi

This note describes how acquisition and report rendering are separated into
processes, why, and how to check that the host is back to steady state after
each task. The electrical limits, acquisition timing and the document
timeouts (`STATIC_*_TIMEOUT_S`, `DOCUMENT_TIMEOUT_S`) are unchanged by this
model.

## Before

```
benchctl-report.service (UI, NiceGUI)
└─ dcdc-job-<id> (transient user unit, Restart=no, RuntimeMaxSec=2700, KillMode=control-group)
   └─ python -m dcdc_bench.job_service --worker <job>      acquisition worker: drivers, run store
      └─ python -m dcdc_bench report <run> (own session)   waited for up to 1800 s by the worker
         └─ kaleido → python wrapper → chromium (+ renderers)   one tab, one image at a time
         └─ quarto (Deno) → pandoc → typst                    subprocess.run(timeout=600)
```

Problems found on the Pi:

1. After the outputs were verified OFF the acquisition worker stayed resident
   (drivers, `benchctl`, run state) while waiting for the report child, so the
   heaviest phase ran with the least memory.
2. `subprocess.run(timeout=...)` kills only Deno; Pandoc/Typst grandchildren
   could survive. Nothing verified that the Chromium tree was gone when
   Kaleido's `close()` timed out. The worker only swept its report process
   group on an exception, never on the normal path.
3. No resource telemetry (RSS, MemAvailable, swap, PID, duration) and no memory
   check before heavy rendering.
4. A second report request while the bench was busy was refused rather than
   queued.

## After

```
benchctl-report.service (UI)
├─ app.timer(2 s) → JobService.dispatch_reports()     the only place a render is launched
└─ dcdc-job-<id>-<n> (acquisition)                     exits at "report-queued" after verified OFF
   python -m dcdc_bench.job_service --worker <job>
   ... later, when idle and the memory gate passes ...
└─ dcdc-job-<id>-<m> (report-only)                     fresh process, no drivers loaded
   python -m dcdc_bench.job_service --worker <job> --report-only
   └─ python -m dcdc_bench report <run> (own session)   swept on every exit path
      └─ chromium tree (own session)                    terminated by pid if close() times out
      └─ quarto → pandoc → typst (own session)           killpg on timeout, swept afterwards
```

The `bench_activity` file lease still makes acquisition and rendering mutually
exclusive and still fails closed; nothing queues an armed hardware operation.
Under systemd each worker is its own transient unit, so the unit ends and
control-group cleanup runs when the acquisition worker exits at
`report-queued`, before any renderer starts.

### Job state machine

```
queued ──► acquiring ──► report-queued ──► queued (action=report-only) ──► reporting ──► completed | aborted | cancelled
   │           │              │  ▲                                             │
   │           │              │  └── deferred_reason/deferred_utc set while    └──► failed (report failed; measurements kept)
   │           │              │      the gate or lease refuses; state unchanged
   │           │              └──► cancelled (removed from the queue, nothing signalled)
   └──► failed / cancelled (launch failed, expired, or stopped before arming)
```

* `ACTIVE = {queued, acquiring, reporting}`: exactly one job may be in these
  states. `start()` refuses while any job is ACTIVE.
* `report-queued` is *pending, not active*: `start()` is allowed while only
  report-queued jobs exist (acquisition has priority), the dispatcher does
  nothing while any job is ACTIVE, and `status()` never marks such a job
  failed for having no PID.
* `retry_report(job)` requires a finalized run with both outputs verified OFF,
  never starts acquisition, and now *enqueues* (`report-queued`) instead of
  refusing when another job is active. Retrying a job that is itself ACTIVE is
  still refused.
* `cancel(job)` on a report-queued job sets `cancelled` and signals nothing.
* `dispatch_reports()` (under the service lock): if any job is ACTIVE → return;
  otherwise take the oldest `report-queued` job, probe the `report` lease,
  run the memory gate; on refusal write `deferred_reason`/`deferred_utc` into
  `job.json` and log `deferred` (once per change of reason, then at most every
  60 s); on success set `queued`/`action=report-only`, clear the deferral and
  launch a report-only worker. It is called from the UI's 2 s `app.timer` and
  once at UI startup — never from a request handler — so at most one
  dispatcher runs per UI process.

### Memory gate

| Variable | Default | Meaning |
| --- | --- | --- |
| `DCDC_RENDER_MIN_AVAILABLE_MIB` | 150 | Refuse when `MemAvailable` (from `/proc/meminfo`) is below this. |
| `DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB` | 600 | Refuse when `MemAvailable + SwapFree` is below this. |

Setting **both** to `0` disables the gate. The gate is checked in two places:

* `JobService.dispatch_reports()` before launching a report-only worker
  (refusal → the job stays `report-queued` with a visible `deferred_reason`).
* `services.report_run()` (used by `dcdc-bench report`, `dcdc-bench run`,
  the demo and the report-only worker) before anything is written. A refusal
  raises `ReportRenderError` (CLI exit 3) whose message includes the reason,
  the thresholds and the snapshot; no revision directory or placeholder is
  created. When rendering proceeds the verdict is written to
  `memory_gate.json` and copied into `build_manifest.json` under
  `memory_gate: {ok, reason, thresholds, snapshot}`.

The kernel here boots with `cgroup_disable=memory`, so a `systemd-run` memory
limit would not protect the host; the gate is a userland substitute, not a
hard limit.

### Descendant hygiene

* `_render_process` (worker → report CLI): the child runs in its own session;
  after it exits on **every** path (normal, timeout, cancel) the worker scans
  `/proc/*/stat` for processes whose pgrp or session equals the child's pid,
  logs `survivors` with the count, terminates leftovers (SIGTERM → grace →
  SIGKILL), logs `survivors` again, and records the child's peak RSS from
  `getrusage(RUSAGE_CHILDREN).ru_maxrss`.
* `_run_tool` (renderer → Quarto): `Popen(start_new_session=True)`,
  `communicate(timeout=DOCUMENT_TIMEOUT_S)`; on timeout `killpg` SIGTERM then
  SIGKILL of the tool's group, then a session sweep. Per format
  `build_manifest.json` records
  `resource_usage[fmt] = {pid, duration_s, peak_child_rss_mib, survivors,
  survivors_remaining, timed_out, returncode}`.
* `_write_static_figures`: if `browser.close()` exceeds
  `STATIC_CLOSE_TIMEOUT_S`, the Chromium group leader pid is read from
  `browser.subprocess.pid` (Kaleido subclasses choreographer's `Browser`; the
  browser wrapper is started with `start_new_session=True`) and its group is
  terminated; when the attribute is unavailable the parent's session sweep
  still applies.

### What is logged where

All lines are JSON with `utc`, `monotonic_s`, `pid`, `task`, `phase`,
`mem_total_mib`, `mem_available_mib`, `mem_available_plus_swap_free_mib`,
`swap_total_mib`, `swap_free_mib`, `swap_used_mib`, `rss_mib`, `load_*`, plus
`duration_s` on `end`, and `child_pid`, `child_peak_rss_mib`, `count`,
`processes`, `reason`, `job_id` where applicable. `phase` is one of
`start`, `end`, `deferred`, `refused`, `survivors`.

| File | Written by | Tasks |
| --- | --- | --- |
| `<workspace>/resource-log.jsonl` | every worker, the dispatcher | `acquisition`, `report-only` (start/end), `dispatch` (start/deferred) |
| `<workspace>/jobs/<job>/resources.jsonl` | the same, per job | as above plus `report-process` (start/survivors/end) |
| `<run>/reports/rNNNN/resources.jsonl` | the renderer | `static-figures` (start/end/survivors), `quarto-html`, `quarto-pdf` (start/survivors/end) |
| `<run>/reports/rNNNN/build_manifest.json` | the renderer | `resource_usage`, `memory_gate` |

`python -m dcdc_bench.resources` prints one snapshot as JSON.

## Steady-state check procedure

Run on the Pi, before starting a task and again after it reports finished.

```sh
cd /home/jerome/rigol-control
# 1. Baseline
free -m
.venv/bin/python -m dcdc_bench.resources
tail -n 3 dcdc-bench/workspace/resource-log.jsonl
systemctl --user list-units 'dcdc-job-*' --all --no-pager     # expect: 0 loaded units

# 2. Run the task (UI test, retry, or `dcdc-bench report <run>`), then wait
#    until the job is completed/aborted/failed/cancelled in the UI.

# 3. After
systemctl --user list-units 'dcdc-job-*' --all --no-pager     # expect: 0 loaded units
tail -n 6 dcdc-bench/workspace/resource-log.jsonl             # one start + one end per worker; end.duration_s present
JOB=dcdc-bench/workspace/jobs/<job-id>
grep '"survivors"' "$JOB"/resources.jsonl | tail -n 2         # last report-process survivors line: "count": 0
REPORT=$(ls -d "$JOB"/runs/*/reports/r* | tail -n 1)
python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print({k: (v['survivors'], v['survivors_remaining'], v['peak_child_rss_mib'], v['duration_s']) for k, v in m.get('resource_usage', {}).items()}); print(m.get('memory_gate', {}).get('reason'))" "$REPORT/build_manifest.json"
pgrep -af 'chromium|chrome|quarto|pandoc|typst|dcdc_bench' || echo "no renderer or worker processes"
free -m
```

Pass criteria: no `dcdc-job-*` unit remains loaded; the last `survivors`
line of the job shows `count: 0` and every `resource_usage[fmt].survivors_remaining`
is empty; `pgrep` finds no renderer or worker process other than the UI; the
`end` line's `mem_available_mib` and `free -m` `available` are back near the
baseline (allow for page cache). A `deferred` line with `reason` explains a
job that is still `report-queued`.

## Tests

`tests/test_resources.py` and `tests/test_report_queue.py` cover the snapshot
and gate with injected `/proc` text, the acquisition worker stopping at
`report-queued` without spawning a renderer, the dispatcher (idle → one
launch; acquiring → nothing; gate failure → logged deferral; live report
worker → nothing), retry queuing, the `_render_process` and `_run_tool`
sweeps with a `sleep` orphan, the Chromium group termination with a fake
browser, and `report_run` refusing without free memory. No Quarto or
Chromium is started; `tests/conftest.py` disables the gate by default so the
suite does not depend on the test host's free memory.
