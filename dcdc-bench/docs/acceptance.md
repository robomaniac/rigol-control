# Acceptance coverage

This maps every Section 14 ID in [the implementation brief](implementation-brief.md)
to its milestone and verification. A calculation fixture proves its stated
calculation; it does not validate the physical bench. All acquisition exercised
in M1 uses the coupled synthetic plant.

The executed commands, platform, rendered artifacts, and current browser/PDF
results are recorded in [implementation status](implementation_status.md).
Rows marked **deferred** are not implemented acceptance claims.

**Status as of 2026-09-27 (branch dcdc-bench-hardening): M0 reached; M1
substantially reached; M2 partial (freshness, readback accuracy and uncertainty
unquantified; enabled-no-load unqualified); an M3 workflow slice demonstrated
(bounded three-point real job through the UI's application services) but M3
not complete by the spec's exit criteria; M4/M5 not started.** This is the same
position stated in [implementation status](implementation_status.md) and the
[README](../README.md). Rows below name coverage, not pass counts; for the
current totals see the branch's final verification record.

## Core contracts and planning

| ID | Milestone | Coverage |
| --- | --- | --- |
| CORE-01 | M0 | `test_planning.py::test_CORE01_owner_facts_are_separate_from_synthetic_fixtures`: owner-supplied 9–36 V, 12 V, 4 A, 48 W; unknown identity/construction remain unknown. |
| CORE-02 | M0 | `test_CORE02_48w_rejected_at_every_requested_voltage_even_ideal_efficiency`: all 12 rated-grid voltages fail CH1 physical power with efficiency set to 1. |
| CORE-03 | M0 | `test_CORE03_ch2_below_dut_minimum`: CH2's 8 V maximum fails the 9 V minimum. |
| CORE-04 | M0/M2 | `test_CORE04_ch1_sense_rejected_but_load_sense_independent`: capability validation. Physical load sense enable/readback is **deferred to M2**. |
| CORE-05 | M0 | `test_CORE05_full_requests_retained_with_physical_and_assumption_reasons` and `test_quick_grid_and_planning_limits`: retain targets and distinguish physical from budget exclusions. `test_protective_planning.py` additionally rejects requests exceeding explicit input-voltage, nominal-output-voltage or output-current guards without clipping. Hardening branch: `test_planning.py::test_real_execution_never_claimed_ready_and_example_has_no_ratings_for_unknown_load` checks that saved DUT/bench profiles lacking `execution_approval` / `protective_controls.approved` yield the planner's `approval_blocked` reason through `planning.missing_approvals()` and are never claimed ready for real execution. |
| CORE-06 | M0 | `test_CORE06_programming_accuracy_cannot_become_readback_accuracy`: incompatible accuracy roles fail validation. Actual bench readback uncertainty is unquantified. |
| CORE-07 | M1 | `test_pipeline.py::test_CORE07_second_output_voltage_and_alternate_source_complete_worker_to_report`: a separate synthetic 5 V profile and 3 A source complete the worker/analysis/report-model path. |

Explicit voltage/current guards use inclusive planning ceilings (`target <= guard`).
`test_explicit_guard_equality_is_inclusive_but_does_not_approve_real_operation`
checks equality in mock and real plans; it does not establish physical operating
headroom, transient protection or approval to energize. The same test module
checks that the default mock coverage and pure construction of both fixed pilot
plans remain valid. No instrument commands are issued by these tests.

Section 5.2 contracts: `test_contracts.py` checks SourceAdapter, LoadAdapter,
MeasurementProvider, TestProcedure, RunStore, Analyzer and ReportRenderer as
`@runtime_checkable` Protocols in `domain.py`, with `MockBench`,
`storage.RunStore`, the `*Procedure` classes and `RigolPilot` conforming and an
incomplete fake rejected. Conformance is structural; it does not qualify
hardware.

## Worker and acquisition

| ID | Milestone | Coverage / limit |
| --- | --- | --- |
| RUN-01 | M1 | Mock worker acquires OS/process locks for both source and load resources. Concurrent-owner fault checks belong to the runner verification suite; no hardware owner has been tested. |
| RUN-02 | M3 | **Covered at the mock/application-services level** (`test_run02_reconnect.py`): `test_run02_refresh_while_running_reattaches_to_the_single_worker` replays the bench page's (re)load sequence through `JobService` against a real detached mock worker — no second worker or run is created and the job is neither aborted nor re-armed; `test_run02_opening_an_old_completed_job_starts_nothing_and_changes_nothing` covers opening an old completed job. This meets the M3 prerequisite at that level. A literal browser-click refresh during acquisition is not claimed, and no hardware owner has been exercised this way. |
| RUN-03 | M1/M2 | Synthetic query-timeout scenario preserves partial evidence and attempts independent shutdown. Real-driver timing and physical shutdown behavior are **deferred to M2**. |
| RUN-04 | M1/M2 | Synthetic worker-crash scenario records `UNKNOWN` output state. No automatic restart path exists. Physical reconnection/reconciliation/fresh arming are **deferred to M2**. |
| RUN-05 | M1 | Synthetic `setup-limited` scenario marks current-limited points invalid; the pipeline independently rejects accepted samples reporting CC. |
| RUN-06 | M1 | Synthetic stale, overrange, malformed, and unsettled scenarios retain raw samples and qualify points. Pipeline tests reject invalid acquisition status or settling samples accepted as measurements. |
| RUN-07 | M0/M4 | `test_RUN07_required_temperature_missing_is_unsupported_optional_not_invented`: missing required quantity blocks a plan; optional temperature is absent. Actual thermal adapter and procedure are **deferred to M4**. |
| RUN-08 | M1 | Synthetic persistence-failure scenario stops acquisition. Permanent storage failure cannot promise a durable final report. |
| RUN-09 | M5 | **Deferred, still not implemented on the hardening branch:** no approved UVLO procedure or phase-specific guard policy is implemented. Unknown procedure types fail planning. The bracket arithmetic helper is not a hardware test. |
| RUN-10 | M0/M1 | Import/planning/analysis/report paths use no real driver sessions. `test_real_cli_arm_and_future_commands_fail_without_touching_hardware` rejects real mode and arming before reading a plan. The pipeline checks `real_hardware_opened=false`. Hardening branch approval gates: `test_real_backend.py::test_unapproved_saved_profiles_never_open_instruments` (`prepare_real_plan` returns preview errors before any instrument session); `test_job_service.py::test_seeded_real_profile_requires_saved_approvals_then_is_feasible` (the seeded `rigol-local-limited` bench profile ships unapproved and becomes feasible only after both saved approvals); `test_job_service.py::test_stale_supported_preview_cannot_start_an_unapproved_real_job` (`JobService.start` rebuilds the plan from saved profiles and re-runs `prepare_real_plan` rather than trusting a cached preview). Each Start still requires the fresh wiring/CH1/protections/serial confirmation. |

Hardening-branch notes for this section: protection programming (OVP/OCP,
load CC limits, OTP) lives only in `bringup.RigolPilot`
(`apply_source_protections`, `apply_load_cc_limits`, `enable_source_otp`);
`test_bringup.py::test_protection_programming_scpi_lives_only_in_the_shared_adapter`
guards against drift. The startup/descent live input-voltage step calls
`RigolDP800.set_voltage_live(channel, V, max_step_v=1.0)` in `benchctl`
(`Software/tests/test_dp800.py`) rather than writing raw `:SOUR1:VOLT` around
the output-OFF interlock. `bringup.run_bringup` takes the single-owner bench
lease. None of these tests operate instruments.

## Numerical analysis and evidence

| ID | Milestone | Coverage |
| --- | --- | --- |
| DATA-01 | M1 | `test_pipeline.py::test_DATA01_worker_raw_analysis_table_export_and_figure_reference_identical_values`: actual worker samples, accepted means, powers, loss, efficiency, report model and CSV agree. Browser hover/export identity is additionally checked in browser verification. |
| DATA-02 | M1 | `test_DATA02_review_fixture_flows_into_actual_report_metric_caption_and_summary`: independent synthetic 5 V raw cycles produce 0.382%, with 12–60 V in report metric, caption and summary. |
| DATA-03 | M1 | `test_DATA03_missing_first_requested_point_does_not_claim_full_covered_range`: retain unmeasured 16 V; label actual qualified 18–24 V; withhold a full-grid line metric. |
| DATA-04 | M1 helper / M5 procedure | `test_analysis.py::test_data04_transition_is_bracket_not_exact`: 9.0–9.1 V observed interval, no exact threshold. Hardware UVLO sequence **deferred**. |
| DATA-05 | M1 | `test_data05_independent_test_coverage`: independent requested/qualified counts for load, line and UVLO synthetic fixtures. |
| DATA-06 | M1 | `test_data06_no_load_invalid_signs_and_unclamped_ratios`: no-load efficiency not applicable, nonpositive input flagged, implausible ratios retained and flagged. |
| DATA-07 | M1 | `test_DATA07_new_analysis_and_report_revisions_preserve_acquisition`: changed formula version gets a new analysis ID; repeat analysis is idempotent; previous report models and hashed acquisition files remain unchanged. `test_report_identity.py::test_matching_prior_formula_revision_remains_selectable` checks explicit selection of an earlier formula revision. Rendering is stubbed in these orchestration tests. |
| DATA-08 | M1 | `test_data08_references_and_declared_conditions_validated` plus parameterized `test_analysis_rejects_a_worker_claim_of_validity_without_matching_evidence`: references, selected conditions, instrument identity, phase, source mode, status and accepted-cycle presence are checked. `test_report_identity.py` checks report selection against run identity, acquisition hashes, requested conditions and preserved sample/cycle references. |
| UNC-01 | M1 fixture | `test_unc01_current_only_regression`: explicitly independent rectangular current limits produce 1.155512754 percentage points. It is not the first DUT's uncertainty budget. |
| UNC-02 | M1 | `test_unc02_absent_budget_no_fabricated_bands`: no uncertainty bands or resolved-difference verdict without an evaluated budget. |
| UNC-03 | M1 helper / M4 comparison | `test_unc03_covariance_changes_difference`: supplied covariance changes the difference uncertainty and invalid covariance fails. Full paired-run comparison is **deferred**. |
| UNC-04 | M1 | `test_unc04_systematic_terms_have_no_sample_count_scaling`: repeating observations does not divide the supplied systematic budget by √N. |
| CMP-01 | M4 | **Deferred, not implemented on the hardening branch:** no comparison command, condition pairing, interpolation, or difference report yet. |
| CMP-02 | M4 | **Deferred, not implemented on the hardening branch:** no comparison interpretation engine. Initial deterministic prose reports measured/derived observations and limitations. |

### Method metadata and software provenance

These checks cover the evidence and revision requirements in brief Sections 7,
8.4 and 12; they do not replace browser/PDF acceptance.

- **Declared and achieved timing:**
  `test_method_and_refs.py::test_method_preserves_policy_phase_durations_and_observed_query_spans`
  checks that the report preserves declared acquisition/settling policies,
  recorded phase durations and timing calculated from accepted raw queries.
  `test_unknown_phase_duration_is_not_replaced_by_declared_setting` keeps
  unavailable durations and clock basis unknown. Query spans are separately
  labeled; they are not instrument ADC update rates. The setup table summarizes
  qualified points, while the report model retains each point's timing.
- **Structured summary references:**
  `test_summary_references_use_metric_registry_and_survive_figure_reordering`
  resolves summary evidence through metric and figure IDs. The same module
  rejects missing references and verifies that plain summary text cannot insert
  active markup or its own cross-reference syntax.
- **Selected analysis identity:** `test_report_identity.py` rejects mixing two
  runs of the same plan, changed acquisition files even with an explicit
  analysis selection, missing/duplicate points, changed conditions, and
  unpreserved sample/cycle references. A matching selected analysis retains the
  values used by its numerical exports. These tests use stored synthetic
  evidence and a renderer stub; they do not claim successful document output.
- **Software and render source identity:** `test_software_provenance.py` checks
  acquisition Git commit and dirty state, including untracked files; missing Git
  or failed reads remain explicitly unknown. Source-file hashes identify local
  code beyond a commit. Render manifests separately hash the renderer, theme CSS
  and interaction JavaScript, alongside the document template, and a failed
  build still records its intended sources. This metadata applies to new
  acquisition/build records; earlier finalized evidence is not rewritten.

## Browser, export and PDF gates

These require the delivered browser assets and actual renderer binaries. Unit
tests alone do not establish that an offline HTML or PDF works. Consult the
current artifact-specific results in implementation status; the list below is
the verification scope, not a substitute for that evidence. On this aarch64
Raspberry Pi, Chrome for Testing has no linux-arm64 build, so the 13
`browser`/`pdf`-marked tests (WEB-*, EXP-01, PDF-*) must run on a laptop or CI
(the brief §4.3 ARM limitation); the initial-checkpoint record used Debian's
`chromium-headless-shell` on the Pi.

| ID | Milestone | Gate / additional unit coverage |
| --- | --- | --- |
| WEB-01 | M1 | Open the produced HTML with external requests blocked; operate plots, filters and exports. |
| WEB-02 | M1 | Check the shipped embedded `Plotly.version` against the recorded distribution, using that same page for browser tests. |
| WEB-03 | M1 | Change checkbox and Plotly legend visibility; verify the common view state and exported curves. No uncertainty band is drawn when the budget is unknown. |
| WEB-04 | M1 | Confirm Reset zoom preserves selection and Restore default view resets all view settings. |
| WEB-05 | M1 | Zoom to inclusive 0.5–1 A; visible-range CSV must obey those bounds while selected-curves CSV retains the other selected points. |
| WEB-06 | M1 | Browser CSV schema/metadata/export check; `test_web06_csv_unique_units_empty_missing_and_escaped_text` also verifies CSV escaping, formula-injection defense and empty numeric missing values. |
| WEB-07 | M1 | Render a separate synthetic 39.1575% fixture; verify default axis bounds include the point. |
| WEB-08 | M1 | **Partially covered:** `test_documents.py::test_web05_web06_web08_scope_csv_and_log_bounds` verifies that switching to the log current axis preserves the 0.5–1 A visible range and its export transformation. The fixture contains no zero- or negative-current point, so explicit exclusion of nonpositive log-axis points is not yet verified in a browser. |
| WEB-09 | M1 | Follow issued figure references and inspect actual point/raw evidence, including keyboard interaction. `test_method_and_refs.py` additionally checks structured summary references and reordering without hard-coded figure numbers; actual link navigation remains a browser gate. |
| WEB-10 | M1 | Change filters and confirm issued summary/model/revision stay unchanged. |
| WEB-11 | M4 | **Deferred:** no photo/sensor marker editor or asset-revision UI exists in M1. |
| WEB-12 | M1/M4 | M1 imported text/configuration/embedded JSON must be escaped and cannot execute. YAML object constructors and unknown configuration fields are rejected in `test_unknown_configuration_nonfinite_numbers_and_yaml_objects_rejected`. Rich asset import/editor cases are **deferred to M4**. |
| EXP-01 | M1 | Export SVG and PNG with run, DUT, conditions, boundary and synthetic label intact. |
| PDF-01 | M1 | Inspect PDF objects/drawings for genuine vector line plots; a PDF container around a screenshot does not pass. |
| PDF-02 | M1 | Render and inspect every page of the issued PDFs for clipping, headings, captions, and pagination. **Automated pagination check not implemented**; recorded page inspections were manual (see implementation status). |
| PDF-03 | M1 | Compare HTML/PDF with the shared report-model revision, figure ordering, captions, and numerical values. |
| PUB-01 | M1 | Reports are local; publication configuration is fixed false and generated synthetic HTML has `noindex`. No run triggers Git, GitHub or hosting operations. `noindex` is not access control. |

## Failure isolation

`test_render_failure_does_not_rewrite_completed_acquisition` injects an actual
renderer error through the application service. The worker remains completed,
its output-off evidence and acquisition hashes remain valid, and no successful
HTML/PDF file is fabricated. Failed rendering is separate from execution.

## Running the Python checks

From the parent checkout after setup:

```bash
.venv/bin/python -m pytest dcdc-bench/tests/test_planning.py \
  dcdc-bench/tests/test_analysis.py dcdc-bench/tests/test_pipeline.py -q
```

This command does not require real instruments, PDF binaries, a browser, or a
network connection. Additional runner/browser/PDF commands and dependencies are
listed with their executed results in implementation status.
