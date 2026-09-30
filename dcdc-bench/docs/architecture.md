# dcdc-bench architecture: a module map

This page is for an engineer who is new to the code and wants to know where a
change belongs. It describes what each module in `src/dcdc_bench/` and
`src/dcdc_bench/reporting/` does, what it must never do, and which tests cover
it. The design intent behind these boundaries is in the
[implementation brief](implementation-brief.md), sections
[4 (architecture)](implementation-brief.md#4-selected-architecture-and-technology)
and [5 (module boundaries and contracts)](implementation-brief.md#5-module-boundaries-and-extension-contracts);
the acquisition/report process separation on the bench Pi is in the
[Pi process model](pi-process-model.md). Neither is repeated here. Nothing on
this page is a claim about hardware verification; for what has actually been
measured and verified see [implementation status](implementation_status.md).

The one sentence to remember: **the run folder is the contract between
acquisition and reporting.** Acquisition writes append-only evidence and stops;
analysis reads it and writes versioned results; rendering reads a validated
report model and never touches the evidence. Anything that talks to an
instrument lives in one dedicated worker process and is reached only through
`JobService` or an explicitly armed fixed procedure.

## Data flow

```text
profiles/                     DUT, bench, recipe and report YAML (the UI saves JSON copies
  dut/ bench/ recipes/ report/   under workspace/profiles/<kind>/); loaded by planning.load_profile
        │                        into the typed models of domain.py
        ▼
planning.build_plan ───────► domain.Plan          every requested point retained with a status and a
        │                                          reason; plan_hash; verify_plan_hash and
        │                                          missing_approvals gate any real arming
        ▼
one worker process owns the instruments (never the UI, never a request handler)
  ├─ mock: runner.run_mock → adapters.MockBench (+ mock_thermal, mock_uvlo / uvlo)
  └─ real: real_backend.run_real → ConfiguredProcedure → the extended.py lifecycle
           (preflight, arming, source deadline, settling, verified OFF)
           fixed supervised procedures: bringup, extended, source_limit,
           voltage_sweep, startup_descent → the parent benchctl DP800 / DL3000 drivers
        │   storage.RunStore.append(...)  raw/*.jsonl with fsync, then finalize → integrity.json
        ▼
runs/<run_id>/                the contract between acquisition and reporting (layout below)
        │
        ▼
analysis.analyze_run ──────► analysis/<analysis_id>/   metrics.json, points.csv, validation.json;
        │                                               uncertainty.evaluate_run_budget → uncertainty.json;
        │                                               thermal.* for temperature channels
        ▼
analysis.build_report_model ► analysis.ReportModel   FigureSpec / TableSpec / SummaryEvidence / ReportMethod
        │
        ▼
reporting.renderer.render_report ► reports/<revision>/
        │   static SVG figures (Plotly → Kaleido → Chromium), Quarto → HTML with templates/web/report.js
        │   and templates/theme/report.css, Quarto → Typst PDF, write_exports → exports/points.csv,
        │   reporting.sensor_placement from annotations.json, build_manifest.json (tool hashes,
        │   resource usage, memory gate verdict)
        ├─ reporting.pdf_check.check_pdf     pagination check of an issued PDF (PDF-02)
        ├─ publish.publish_run               approval-gated, redacted copy of one issued revision
        └─ comparison.compare_runs → reporting.comparison.write_comparison
                                             paired analyses from two finalized runs (CMP-01/02)
```

On top of that pipeline sits the local job service and UI:

```text
cli.main            validate | plan | run | demo | analyze | report | ui | compare | doctor | publish | pdf-check
   │                (configuration and analysis paths import no real driver)
   └─► services.*   load_plan_inputs, default_plan, execute, report_run, demo — shared by CLI and UI

ui.run_ui (NiceGUI, loopback only; one page: converter / bench / test cards, Preview, Start, Run, Reports; /annotations page)
   └─► job_service.JobService     list/load/save/delete/rename_profile, catalog, feasibility, preview, start, status, list_jobs, cancel,
          │                        retry_report, dispatch_reports, add_attachment, resolve_file
          ├─ workspace/jobs/<job_id>/   job.json, plan.json, request.json, launch.json, worker.log …
          ├─ launches `python -m dcdc_bench.job_service --worker <job>` detached or as a transient
          │  systemd unit (DCDC_JOB_LAUNCHER); the worker calls runner.run_mock or real_backend.run_real,
          │  writes runs/<run_id>/ inside the job folder and exits at state `report-queued`
          └─ a 2 s app.timer calls dispatch_reports(): when no job is ACTIVE and resources.MemoryGate
             passes, a fresh report-only worker (--report-only, no drivers loaded) runs
             services.report_run → reporting.renderer.render_report

activity.bench_activity   one file lease; acquisition and rendering are mutually exclusive and fail closed
resources.*               /proc snapshots, the memory gate, descendant sweeps, resources.jsonl telemetry
```

The job state machine, the memory-gate thresholds, the descendant-process
hygiene and the steady-state check are specified in the
[Pi process model](pi-process-model.md#job-state-machine).

## Modules in `src/dcdc_bench/`

"Must never do" combines each module's own docstring with the relevant row of
the brief's [contract table 5.2](implementation-brief.md#52-required-contracts)
where the module implements one of those contracts. Test names are files in
`tests/`; a module used by nearly every pipeline test lists only its focused
tests.

| Module | Role | Key public entry points | Must never do | Covered by |
| --- | --- | --- | --- | --- |
| `domain.py` | Versioned Pydantic contracts: DUT, bench, recipe and report profiles, planned points and plans, raw samples, policies (settling, acquisition, UVLO ramp, thermal settling, uncertainty), approvals, and the `Protocol` classes the other layers implement. | `DutProfile`, `BenchProfile`, `TestRecipe`, `ReportProfile`, `Plan`, `PlannedPoint`, `RawSample`, `ExecutionApproval`, `ReadbackSpecification`, `UvloRampPolicy`, `ThermalSettlingPolicy`; protocols `SourceAdapter`, `LoadAdapter`, `MeasurementProvider`, `TestProcedure`, `RunStore` | Open an instrument on import (docstring). It validates and describes; it does not act. | `test_contracts.py`, `test_planning.py` |
| `planning.py` | Pure feasibility planning: load a profile with safe YAML, expand the requested grid, keep every request with a status and reason, hash the plan, check saved approvals and UVLO policy gaps. | `load_profile`, `build_plan`, `verify_plan_hash`, `missing_approvals`, `uvlo_approval_gaps`, `uvlo_step_reasons` | Open connections or change targets; clip a request instead of refusing it; treat an estimate as a safety limit. | `test_planning.py`, `test_protective_planning.py` |
| `adapters.py` | The deterministic coupled DC plant: the mock source, load and measurement provider behind every demo and most tests. | `MockBench`, `PlantState` | Connect to hardware (docstring). As `SourceAdapter`/`LoadAdapter` (5.2): report generation or DUT-specific analysis; assuming all loads share the same ranges. As `MeasurementProvider` (5.2): implicitly replacing a missing measurement with a setpoint. | `test_runner.py`, `test_contracts.py`, `test_thermal.py` |
| `mock_thermal.py` | Synthetic temperature provider for the mock bench. | `MockThermalProvider`, `ThermalState` | Be presented as a hardware claim (docstring). | `test_thermal.py` |
| `mock_uvlo.py` | Synthetic under-voltage lockout wrapped around the mock plant. | `UvloMockBench`, `SyntheticUvlo` | Stand in for a real UVLO measurement. | `test_uvlo.py` |
| `runner.py` | Bounded, process-owned mock acquisition: spawn the single instrument owner, drive settling and acquisition, honour stop requests, return the finalized (possibly partial) run. | `run_mock`, `Clock`, `CommunicationTimeout` | Contain a real-instrument backend (docstring). As `TestProcedure` (5.2): direct model-specific SCPI strings. | `test_runner.py`, `test_pipeline.py`, `test_job_service.py`, `test_uvlo.py` |
| `uvlo.py` | The UVLO input-ramp procedure (brief 7.5, RUN-09) with a phase-scoped guard policy; synthetic plant only so far. | `UvloInputRampProcedure`, `run_uvlo_mock`, `UvloStop`, `ProtectiveLimitFault`, `RegulationRuleStop`, `SourceBoundaryStop` | Clip a step below the declared floor; report an exact threshold instead of a bracket. | `test_uvlo.py` |
| `storage.py` | Append-only acquisition evidence with fsync, atomic JSON finalization and integrity hashes. | `RunStore` (`initialize`, `append`, `finalize`), `atomic_json`, `verify_integrity`, `PersistenceError` | Numerical or scientific conclusions (5.2 `RunStore`); let a reader change acquisition files; write NaN or infinity. | `test_storage.py`, and every test that writes a run |
| `activity.py` | One cross-process file lease that keeps acquisition and rendering mutually exclusive. | `bench_activity`, `activity_path` | Queue an armed hardware operation; fail open when busy. | `test_report_queue.py` |
| `bringup.py` | The explicitly armed one- or two-point pilot on the benchctl drivers (the first real measurement); also the recording transport reused by later procedures. | `run_bringup`, `pilot_plan`, `RigolPilot`, `RecordingTransport`, `main` | Run without explicit arming; widen its fixed points. | `test_bringup.py`, `test_protective_planning.py`, `test_uncertainty.py` |
| `extended.py` | The explicitly armed fixed 24 V, 50–500 mA ramp/hold/return characterization, and the shared real-acquisition lifecycle (preflight, identity checks, source deadline, settling, verified OFF) that the later fixed procedures reuse. | `run_extended`, `extended_plan`, `ExtendedRigol`, `ExtendedAbort`, `main` | Let a caller widen its timing or electrical limits; start without both outputs verified OFF. | `test_extended.py`, `test_doctor.py`, `test_source_limit.py`, `test_voltage_sweep.py`, `test_startup_descent.py` |
| `source_limit.py` | Fixed 24 V test approaching the DP821A CH1 1 A input-current ceiling with adaptive load steps. | `run_source_limit`, `source_limit_plan`, `SourceLimitProcedure`, `SourceLimitRigol`, `BenchBoundary` | Raise the programmed supply-current limit; exceed the 2.000 A load bound. | `test_source_limit.py`, `test_contracts.py` |
| `voltage_sweep.py` | Explicitly armed efficiency comparison at 12 V, 24 V and near 36 V, plus the 24 V / near-36 V continuation. | `run_voltage_sweep`, `voltage_sweep_plan`, `VoltageSweepProcedure`, `VoltageContinuationProcedure`, `VoltageSweepRigol`, `VoltageContinuationRigol`, `main` | Program above 35.8 V; cancel the source timer before OFF is verified. | `test_voltage_sweep.py`, `test_voltage_report.py` |
| `startup_descent.py` | Fixed 15 V unloaded startup followed by an energized light-load input descent to 9.1 V. | `run_startup_descent`, `startup_descent_plan`, `StartupDescentProcedure`, `StartupDescentRigol`, `main` | Turn the supply off between steps; determine a cold-start threshold. | `test_startup_descent.py` |
| `real_backend.py` | Profile-driven, bounded DC acquisition on the verified two-instrument bench: the configured procedure that UI jobs run, built on the `extended.py` lifecycle. | `prepare_real_plan`, `run_real`, `ConfiguredProcedure` | Accept a plan the job service has not validated and freshly confirmed (docstring); support anything but the declared DP821A CH1 / DL3031A local-sensing DC procedure. | `test_real_backend.py`, `test_contracts.py`, `test_annotation_editor.py` |
| `doctor.py` | Read-only bench diagnosis (identities, states, protections against the profile) and the outputs-OFF readback-cadence probe. | `run_doctor`, `ReadOnlyTransport`, `DoctorRefusal`, `diagnostics_dir` | Write to an instrument (writes never reach the transport; queries are allowlisted); save diagnostics inside a run folder. | `test_doctor.py` |
| `analysis.py` | Pure settled-DC calculations and versioned analysis of preserved evidence; builds the shared report model consumed by every renderer. | `analyze_run`, `analyze_evidence`, `build_report_model`, `dc_metrics`, `regulation_span`, `points_csv`, `coverage_by_test`, `transition_bracket`, `uvlo_ramp_brackets`; models `ReportModel`, `FigureSpec`, `TableSpec`, `MetricResult`, `SummaryEvidence`, `ReportMethod`, `PointTiming` | Hardware or UI imports (5.2 `Analyzer`); designate accepted cycles itself (the worker does); use off-state readings for efficiency or no-load claims. | `test_analysis.py`, `test_method_and_refs.py`, `test_sequence_report.py`, `test_report_identity.py`, `test_evidence_labels.py`, `test_voltage_report.py` |
| `uncertainty.py` | The structured readback uncertainty budget (brief 9.2) written to `uncertainty.json`. | `evaluate_run_budget`, `evaluate_point`, `propagate`, `channel_standard_uncertainty`, `sensitivity_coefficients`, `difference_uncertainty`, `format_efficiency_label` | Turn an unknown term into zero; read a programming (setting) accuracy; open an instrument (docstring, [uncertainty-budget.md](uncertainty-budget.md)). | `test_uncertainty.py` |
| `thermal.py` | Pure thermal analysis (brief section 10): sensor placements, settling-slope verdicts, temperature data sources and the report contribution. | `evaluate_thermal_window`, `least_squares_slope`, `thermal_policy_for`, `annotate_thermal_points`, `thermal_report_contribution`, `apply_placements`, `placements_from_annotations` | Hardware or UI imports (docstring). | `test_thermal.py` |
| `comparison.py` | Paired comparison of stored analyses from two finalized runs (M4, CMP-01/CMP-02, UNC-03): pairing by condition, interpolation disclosure, paired uncertainty. | `compare_runs`, `load_run`, `select_analysis`, `pair_points`, `interpolate_unpaired`, `evaluate_pair_uncertainty`, `build_comparison_model`, `ComparisonReportModel` | Re-acquire, or compute from anything other than stored, integrity-checked analyses. | `test_comparison.py` |
| `services.py` | Application operations shared by the CLI and the UI: load profiles into a plan, execute a plan, render a run, run the demo. | `load_plan_inputs`, `default_plan`, `execute`, `report_run`, `demo` | Instrument logic (brief 5.1: "shared application operations; not instrument logic"); render when the memory gate refuses. | `test_pipeline.py`, `test_documents.py`, `test_analysis.py` |
| `publish.py` | Approval-gated, redacted static publication copy of one issued report revision. | `publish_run`, `load_approval`, `PublicationApproval`, `Redactor` | Publish without every approval field explicit; report redacted values rather than counts. | `test_publish.py` |
| `attachments.py` | Content-addressed evidence assets (photographs, documents) with import hygiene: filename normalization, media-type sniffing, validation. | `AssetStore`, `validate_asset`, `sniff_media_type`, `normalize_filename` | Modify or reference acquisition evidence; accept an asset that fails validation. | `test_attachments.py`, `test_annotations.py` |
| `annotations.py` | Sensor-placement annotations bound to the exact hash of the original image. | `bind_annotations`, `load_annotations`, `validate_annotations`, `annotation_document`, `marker_overlay_svg`, `nudge_marker`, `nearest_marker` | Accept markers not bound to the exact original image. | `test_annotations.py`, `test_annotation_editor.py` |
| `annotation_editor.py` | The UI's `/annotations` page for finished runs: upload a photograph, place sensor markers, save a new report revision. | `register_annotation_editor`, `eligible_jobs`, `image_assets`, `existing_annotations`, `asset_summary` | Touch the acquisition evidence (saving creates a report revision only). | `test_annotation_editor.py` |
| `resources.py` | Host resource telemetry from `/proc`, the render memory gate, and descendant-process hygiene (session survivors, group termination). | `snapshot`, `MemoryGate`, `log_event`, `try_log_event`, `session_survivors`, `terminate_group`, `children_peak_rss_mib`, `main` | Change an outcome: telemetry skips a missing path and swallows I/O errors. | `test_resources.py`, `test_report_queue.py`, `test_reporting_resources.py` |
| `job_service.py` | Local UI facade and detached job owner: saved profiles and previews, job folders, worker launch (detached or transient systemd unit), status, cancel, report retry and the report dispatcher. | `JobService` (`list_profiles`, `load_profile`, `save_profile`, `preview`, `start`, `status`, `list_jobs`, `cancel`, `retry_report`, `dispatch_reports`, `add_attachment`, `resolve_file`), `worker` | Let a UI request control instruments (docstring); start acquisition from `retry_report`; allow two ACTIVE jobs; launch a render from a request handler. | `test_job_service.py`, `test_run02_reconnect.py`, `test_report_queue.py` |
| `ui_models.py` | Small pure presentation helpers for the bench page. | `plan_rows`, `edited_dut`, `edited_recipe`, `target_values`, `state_label`, `job_title`, `artifact_url`, `shutdown_label`, `recipe_title`, `recipe_grid`, `card_meta`, `limits_rows`, `skip_reasons`, `report_rows` | GUI, transport, worker or filesystem effects (docstring). | `test_ui.py` |
| `ui.py` | The local NiceGUI bench workflow (one page: **Which converter?**, **Simulated or real bench?**, **Which test?**, a Preview/Start bar, Run, Reports), loopback only, serving published run files. | `run_ui`, `require_loopback`, `published_file` | Own hardware (ownership stays in `JobService` workers, docstring); bind beyond loopback; block the event loop with instrument I/O (brief 4.1). | `test_ui.py`, browser-marked tests |
| `cli.py` | The small argparse CLI: `validate`, `plan`, `run`, `demo`, `analyze`, `report`, `ui`, `compare`, `doctor`, `publish`, `pdf-check`. | `main`, `parser` | Import real drivers on configuration or analysis paths (docstring). | `test_pipeline.py`, `test_ui.py`, `test_comparison.py`, `test_pdf_check.py`, `test_report_queue.py` |
| `__init__.py`, `__main__.py` | Package docstring; `python -m dcdc_bench` dispatches to `cli.main`. | — | — | — |

## Modules in `src/dcdc_bench/reporting/`

| Module | Role | Key public entry points | Must never do | Covered by |
| --- | --- | --- | --- | --- |
| `reporting/__init__.py` | Offline document rendering package; re-exports the renderer entry points. | `render_report`, `validate_report_model`, `ReportRenderError` | Import instrument code (docstring). | `test_reporting.py` |
| `reporting/renderer.py` | Quarto documents from one already-analyzed model: static SVG figures through Kaleido/Chromium, HTML with the embedded Plotly interaction script, Typst PDF, the issued CSV exports and the build manifest (tool and theme hashes, resource usage, memory-gate verdict). | `render_report`, `validate_report_model`, `write_exports`, `ReportRenderError` | Recompute independent efficiency or regulation formulas (5.2 `ReportRenderer`); depend on instruments; create a placeholder PDF or claim success when a tool is missing; carry a voltage, current, step, window or rating literal in prose. | `test_documents.py`, `test_reporting.py`, `test_report_javascript.py`, `test_report_retry.py`, `test_reporting_resources.py`, `test_evidence_labels.py`, `test_software_provenance.py`, `test_method_and_refs.py`, `test_sequence_report.py` |
| `reporting/sensor_placement.py` | The "Sensor placement" report section built from a revision's `annotations.json`. | `sensor_placement_html`, `sensor_placement_markdown`, `static_overlay_svg`, `with_sensor_placement` | Read markers from anywhere but the bound annotations document. | `test_annotations.py`, `test_annotations_browser.py` |
| `reporting/comparison.py` | Comparison documents, figures and exports from a validated comparison model. | `write_comparison`, `comparison_body`, `plot_comparison_figure`, `write_comparison_exports` | Recompute pairing or uncertainty; read raw runs. | `test_comparison.py` |
| `reporting/pdf_check.py` | Automated pagination check of an issued PDF (acceptance PDF-02): text lines, regions, orphaned headings, split tables. | `check_pdf`, `extract_document`, `analyze`, `PdfCheckResult`, `main` | Modify the PDF or the revision it belongs to. | `test_pdf_check.py` |

Test markers (from `pyproject.toml`): `browser` (real offline Chromium
interaction), `pdf` (Quarto/Typst vector PDF checks) and `integration`
(subprocess integration). The ordinary suite is
`python -m pytest tests -m 'not browser and not pdf'`; `tests/conftest.py`
disables the memory gate by default so the suite does not depend on the test
host's free memory.

## Other folders that the code depends on

| Folder | Contents |
| --- | --- |
| `profiles/` | Checked-in YAML: `dut/12t12-4a.yaml`; `bench/mock.yaml`, `bench/mock-thermal.yaml`, `bench/rigol.example.yaml` (blocked from execution); `recipes/` for the quick grid, rated grid, extended, source-limit, voltage-efficiency, thermal-mock and UVLO example procedures; `report/engineering.yaml`. |
| `templates/` | `characterization.qmd` (the Quarto document), `theme/report.css`, `theme/print-theme.typ` (the PDF "datasheet" theme: Letter/A4 page, header band with evidence label and local recording time, footer with run identity and page x of y, hanging section numbers, hairline tables, "Figure N." captions; applied through the `theme/typst-show.typ` Quarto template partial, which replaces Quarto's own `#show: article(...)` block), `theme/print-tables.typ` (PDF-02 table pagination), `web/report.js` (the offline interaction script embedded in each HTML report). The renderer writes the identity dictionary the theme reads into `print-header.typ` (Quarto header include) and copies the partial next to `report.qmd`. |
| `tools/` | `setup.py` (virtual environment, pinned Quarto with SHA-256 check, browser detection) and `theme_preview.py` (the figure-theme previews described in [report-aesthetics-options.md](report-aesthetics-options.md)). |
| `tests/` | The pytest suite and `fixtures/`. |
| `workspace/`, `runs/`, `examples/generated/`, `diagnostics/`, `.tools/` | Created at run time and ignored by Git: the UI workspace, CLI run folders, demo output, `doctor` reports and the downloaded Quarto. |

The `benchctl` package that the real procedures wrap lives in the parent
repository under `Software/`; its control boundaries are described in
[Software/README.md](../../Software/README.md) and
[Documentation/Architecture.md](../../Documentation/Architecture.md).

## Run folder layout

Every acquisition, mock or real, CLI or UI, produces one run folder. This is
the layout the README's "Evidence and reports" section documents:

```text
runs/<run_id>/
  request.json, plan.json, run.json, integrity.json
  raw/
    samples.jsonl, events.jsonl, point_events.jsonl
  attachments/manifest.json
  analysis/<analysis_id>/
    analysis.json, points.csv, points.metadata.json
    metrics.json, uncertainty.json, validation.json
  reports/<revision>/
    report_model.json, annotations.json
    report.html, report.pdf, figures/, build_manifest.json
    exports/points.csv, exports/points.meta.json
```

Real runs additionally keep `scpi.jsonl`, the recorded instrument traffic.
Raw evidence is appended during acquisition and hashed at finalization;
analysis checks those hashes. A formula version change produces a new
`analysis_id`; re-rendering produces a new `reports/rNNNN` revision. Neither
rewrites `raw/`. Three raw-sample keys are shorter than the brief's wording
(`location`, `measurement_range`, `query_start_utc`/`query_end_utc`); the
README's "Evidence and reports" section lists the mapping.

## Job workspace layout

The bench interface works inside `--root` (by convention
`dcdc-bench/workspace/`, ignored by Git). `JobService` creates it:

```text
workspace/
  .service.lock                     JobService's own file lock
  resource-log.jsonl                one start/end line per worker and dispatcher task
  profiles/
    dut/<name>.json, bench/<name>.json, recipe/<name>.json
                                    saved profiles (seeded from profiles/ on first start;
                                    the CLI's YAML loader reads this JSON too)
  previews/<plan_hash>.json         the last preview per plan hash: points, counts, warnings,
                                    estimated seconds, required confirmations, profile hashes
  jobs/<job_id>/                    <job_id> = <UTC timestamp>_<8 hex>
    job.json                        state machine record (queued → acquiring → report-queued →
                                    reporting → completed | aborted | cancelled | failed), pid,
                                    run_dir, report_dir, error, deferred_reason
    plan.json, request.json         the confirmed plan and the operator's confirmation, notes,
                                    attachment references and profile/inventory hashes
    launch.json                     launch request time, pid or systemd unit name
    worker.log                      the worker's stdout/stderr
    resources.jsonl                 per-job telemetry (acquisition, report-only, report-process)
    inventory.yaml                  real jobs only: private copy of the instrument inventory (mode 0600)
    cancel.request                  present while a stop has been requested
    runs/<run_id>/                  the run folder described above
```

Profile files are stored by kind (`dut`, `bench`, `recipe`); the UI's
`/jobs/<job_id>/files/<path>` route serves only files that `resolve_file`
confirms are inside the job folder. What each state means, when a render is
dispatched and which environment variables tune the memory gate are in the
[Pi process model](pi-process-model.md).

## Where a change belongs

- **Another converter:** a new `profiles/dut/*.yaml` (or a profile saved from
  the UI). No Python.
- **Another source or load:** an adapter implementing `SourceAdapter` /
  `LoadAdapter` from `domain.py`, with capability tests; procedures and
  reporting stay as they are.
- **A better measurement:** rebind roles and uncertainty metadata in the bench
  profile; keep the measurement boundary.
- **A new test:** a procedure plus its result schema, analyzer contribution
  and report contribution, using `services.py` and `storage.RunStore`; never
  a second instrument owner.
- **A new report style:** `templates/` and `reporting/renderer.py`, never raw
  data or the metric functions in `analysis.py`.
- **A new UI:** call `JobService` and `services.*`; consume the same
  `job.json` and report-model schemas.

These are the extension rules of brief
[section 5.3](implementation-brief.md#53-extending-the-system), restated with
the module names as they exist today.
