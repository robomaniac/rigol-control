# Acceptance coverage

This maps every Section 14 ID in [the implementation brief](implementation-brief.md)
to its milestone and verification. A calculation fixture proves its stated
calculation; it does not validate the physical bench. All acquisition exercised
in M1 uses the coupled synthetic plant.

The executed commands, platform, rendered artifacts, and current browser/PDF
results are recorded in [implementation status](implementation_status.md).
Rows marked **deferred** are not implemented acceptance claims.

**Status as of 2026-09-28 (branch dcdc-bench-hardening): M0 reached; M1 substantially reached; M2 partial (software side implemented: structured uncertainty budget, read-only `doctor`, outputs-OFF readback-cadence probe; the real bench's freshness, readback accuracy and uncertainty stay unquantified until datasheet/calibration terms are entered and qualified on the bench; enabled-no-load unqualified); an M3 workflow slice demonstrated but M3 not complete by the spec's exit criteria; M4 software implemented on mock and stored data (paired-run comparison, sensor-placement editor with attachment hygiene, synthetic thermal channel with thermal settling) but M4 exit not met (no real temperature adapter; no comparison document rendered); M5 partial (UVLO input-ramp procedure on the synthetic plant only; full-power source, scope tests and public examples not started).** This is the same
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
| CORE-06 | M0/M2 | `test_CORE06_programming_accuracy_cannot_become_readback_accuracy` (planning) and `test_uncertainty.py::test_core06_programming_accuracy_is_never_used_for_readback`: incompatible accuracy roles fail validation; the budget evaluator consults only `readback_specification` (`programming_accuracy_consulted: false` recorded per channel), an `AccuracySpec` cannot be bound as a readback specification, and a channel with only programming accuracy is `not_evaluated`. The real bench's readback specification is `unknown` until the owner transcribes R1/R4 readback terms; its uncertainty remains unquantified. |
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
| RUN-07 | M0/M4 | `test_planning.py::test_RUN07_required_temperature_missing_is_unsupported_optional_not_invented` and `test_thermal.py::test_RUN07_required_temperature_missing_is_unsupported_and_optional_is_not_invented`: a required temperature quantity or declared thermal settling without bound sensor channels makes every point `unsupported` with an explicit reason; optional temperature on an electrical test runs without inventing a channel. `test_thermal.py::test_RUN07_real_bench_cannot_bind_the_synthetic_temperature_provider`: the `mock_thermal` adapter is rejected by `BenchProfile` when `mode: real`, `MockThermalProvider.for_bench` refuses a real bench, and the real backend still declines non-electrical quantities. Mock-only M4 slice: synthetic first-order case/ambient channels, a separate `ThermalSettlingPolicy` (slope window, minimum observation, timeout → `inconclusive` with the series retained), rise above time-aligned ambient, separate temperature figures and a settling time-series figure (`test_thermal.py`). **Real temperature adapter and validated thermal criteria remain deferred.** |
| RUN-08 | M1 | Synthetic persistence-failure scenario stops acquisition. Permanent storage failure cannot promise a durable final report. |
| RUN-09 | M5 (mock) | **Implemented on the synthetic plant only** (`test_uvlo.py`): `uvlo_input_ramp` steps input down to a declared floor and back at a fixed light load. `test_run09_expected_off_steps_are_recorded_states_not_faults`: off-steps inside the declared expected-off phases are qualified observations (`output_state: off`, `output_off_expected: true`), not faults. `test_run09_absolute_limit_stops_the_run_even_inside_the_expected_off_phase`: an injected output overcurrent during an expected-off step aborts with `absolute-protective-limit` and verified-OFF shutdown. `test_run09_normal_phase_minimum_vout_rule_still_trips`: output-off outside the declared phase stops the run under `normal-regulation-rule`. Planning refuses the type without `authorization.uvlo_approved` plus a matching bench protective policy (and the hardware approvals for real); unknown types still fail; below-floor and out-of-range steps are refused, not clipped; no global ignore_safety flag. **No hardware UVLO run; the procedure requires review before any real use and has no real execution context.** |
| RUN-10 | M0/M1 | Import/planning/analysis/report paths use no real driver sessions. `test_real_cli_arm_and_future_commands_fail_without_touching_hardware` rejects real mode and arming before reading a plan. The pipeline checks `real_hardware_opened=false`. Hardening branch approval gates: `test_real_backend.py::test_unapproved_saved_profiles_never_open_instruments` (`prepare_real_plan` returns preview errors before any instrument session); `test_job_service.py::test_seeded_real_profile_requires_saved_approvals_then_is_feasible` (the seeded `rigol-local-limited` bench profile ships unapproved and becomes feasible only after both saved approvals); `test_job_service.py::test_stale_supported_preview_cannot_start_an_unapproved_real_job` (`JobService.start` rebuilds the plan from saved profiles and re-runs `prepare_real_plan` rather than trusting a cached preview). Each Start still requires the fresh wiring/CH1/protections/serial confirmation. Read-only `doctor` (brief 7.2): `test_doctor.py::test_approved_profile_outputs_off_reads_everything_without_writing`, `test_unapproved_profile_exits_nonzero_with_message_and_still_never_writes`, `test_enabled_output_is_reported_never_turned_off_and_cadence_is_refused`, `test_read_only_transport_refuses_writes_and_non_allowlisted_queries` and `test_doctor_never_uses_the_write_paths_of_the_real_drivers` run the real DP800/DL3000 drivers over a fake session that raises on any write and assert the transcript is a subset of `doctor.READ_ONLY_QUERIES`, that `*RST`/`*CLS`/`SYST:ERR?`/output-enable/setpoint/protection writes are absent and `check_errors` is never called; `test_mock_profile_is_refused_before_any_connection` opens no session for a mock profile; the `--readback-cadence` probe refuses unless both outputs read OFF. Fake SCPI only; not executed on the physical bench. |

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
| DATA-04 | M1 helper / M5 procedure (mock) | `test_analysis.py::test_data04_transition_is_bracket_not_exact` (9.0–9.1 V helper) plus `test_uvlo.py::test_data04_analysis_reports_brackets_not_exact_thresholds` and `test_data04_bracket_helper_on_the_brief_fixture_and_unresolved_ramps`: a synthetic ramp yields a descending turn-off bracket (last-on 8.75 V, first-off 8.5 V), an ascending turn-on bracket (last-off 9.0 V, first-on 9.5 V) and hysteresis as a bracket difference [0.25, 1.0] V, every `exact_*` field null; unresolved and step-widened cases carry notes. The convention is recorded in the analysis, figure caption and summary. Hardware UVLO sequence **deferred**. |
| DATA-05 | M1 | `test_data05_independent_test_coverage`: independent requested/qualified counts for load, line and UVLO synthetic fixtures. |
| DATA-06 | M1 | `test_data06_no_load_invalid_signs_and_unclamped_ratios`: no-load efficiency not applicable, nonpositive input flagged, implausible ratios retained and flagged. |
| DATA-07 | M1 | `test_DATA07_new_analysis_and_report_revisions_preserve_acquisition`: changed formula version gets a new analysis ID; repeat analysis is idempotent; previous report models and hashed acquisition files remain unchanged. `test_report_identity.py::test_matching_prior_formula_revision_remains_selectable` checks explicit selection of an earlier formula revision. Rendering is stubbed in these orchestration tests. |
| DATA-08 | M1 | `test_data08_references_and_declared_conditions_validated` plus parameterized `test_analysis_rejects_a_worker_claim_of_validity_without_matching_evidence`: references, selected conditions, instrument identity, phase, source mode, status and accepted-cycle presence are checked. `test_report_identity.py` checks report selection against run identity, acquisition hashes, requested conditions and preserved sample/cycle references. |
| UNC-01 | M1 fixture / M2 evaluator | `test_unc01_current_only_regression` (helper) and `test_uncertainty.py::test_unc01_fixture_reproduced_through_the_evaluator`: explicitly independent rectangular current limits (0.05 % + 0.1 mA, 0.10 % + 0.6 mA; voltage terms declared zero) produce 1.155512754 percentage points through the structured evaluator (`40.2% ± 1.2 percentage points`, k = 2). It is a calculation check, not the first DUT's budget. |
| UNC-02 | M1 / M2 | `test_unc02_absent_budget_no_fabricated_bands` and `test_uncertainty.py::test_unc02_unknown_term_yields_not_evaluated_and_no_bands_in_report_model`: any unknown required term (status, %reading, %range/range, offset, resolution, calibration status) yields `not_evaluated` with reasons and no value/expanded keys; report model, figures, hover and metrics carry bands/± only for evaluated quantities; the fully unknown real profile shows "Uncertainty is unquantified" with the blocking terms and no bands or resolved-difference verdicts. `test_comparison.py::test_unc02_missing_budget_means_not_evaluated_without_bands` covers the comparison path. |
| UNC-03 | M1 helper / M2 model / M4 comparison | `test_unc03_covariance_changes_difference` (helper), `test_uncertainty.py::test_unc03_covariance_changes_the_difference_and_the_efficiency_budget` (declared `readback_correlations` change the propagated efficiency uncertainty; independence recorded whenever no correlation is declared) and `test_comparison.py::test_unc03_covariance_respected_and_independence_recorded`: with evaluated budgets in both analyses the pair difference uses `u_delta^2 = u_A^2 + u_B^2 - 2*cov`; a supplied covariance changes `u_delta`, an invalid one fails, and independence is recorded as an explicit assumption only when assumed. Unquantified budgets yield "not evaluated", no bands and no resolvability verdict. |
| UNC-04 | M1 / M2 | `test_unc04_systematic_terms_have_no_sample_count_scaling` and `test_uncertainty.py::test_unc04_systematic_terms_are_never_divided_by_sample_count`: specification, resolution and temperature terms are identical for n = 5 and n = 5000 readings; only the separately recorded Type A repeatability (s/√n) changes, and it can be excluded by policy. |
| CMP-01 | M4 (stored data) | `test_comparison.py::test_cmp01_pairs_by_qualified_conditions_not_array_index`, `test_cmp01_unpaired_16v_versus_18v_availability_and_repeated_conditions`, `test_cmp01_interpolation_is_off_by_default_and_labeled_when_enabled`, `test_pairing_requires_same_boundary_and_never_joins_by_position`: `dcdc-bench compare` pairs by boundary, test type/id, requested Vin/Iout within declared tolerances and valid qualification; reversed point order pairs correctly; "16 V requested input: run A only" / "18 V …: run B only" reported; repeated and ambiguous conditions listed unpaired; interpolation off by default and labeled INTERPOLATED when enabled, excluded from measured-point metrics. Demonstrated read-only on two stored real 24 V runs (6 pairs, 47 unpaired; `examples/generated/comparison-real-24v/`). **HTML/PDF rendering of comparison documents not yet exercised.** |
| CMP-02 | M4 | `test_comparison.py::test_cmp02_prose_states_counts_and_extremes_without_causal_claims`: deterministic prose states paired counts, the largest observed difference with its conditions, unpaired availability and differing DUT/bench/method fields; no causal, technology, "cooler", superiority or "difference is real" wording in summary, prose, captions, metrics or body (also scanned on the real demo output). |

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
| WEB-08 | M1 | **Covered; browser run pending.** `test_documents.py::test_web08_log_mode_excludes_zero_and_negative_current_points_explicitly` (browser) uses a synthetic fixture with a 0 A and a −0.4 mA point: log current mode draws them as gaps with no substituted value, the status line reports the omitted count, selected-curves CSV keeps `0` and `-0.0004`, visible-range bounds are finite positive values, a zero-crossing zoom is dropped rather than transformed, and both points return in linear mode. `test_report_javascript.py::test_log_current_view_omits_nonpositive_points_without_substituting_values` checks the same shipped code paths (including zoom-bound handling) without a browser and passes on the Pi; the browser test runs on a laptop or CI. |
| WEB-09 | M1 | Follow issued figure references and inspect actual point/raw evidence, including keyboard interaction. `test_method_and_refs.py` additionally checks structured summary references and reordering without hard-coded figure numbers; actual link navigation remains a browser gate. |
| WEB-10 | M1 | Change filters and confirm issued summary/model/revision stay unchanged. |
| WEB-11 | M4 | Sensor markers are normalized image coordinates bound to the original image SHA-256 in `reports/<rev>/annotations.json`; saving always creates a new report revision and leaves `integrity.json` and `attachments/manifest.json` byte-identical (`test_annotations.py::test_saving_annotations_creates_a_new_report_revision_and_preserves_acquisition`, `test_attachments.py::test_post_run_attachment_writes_documentation_revisions_and_leaves_acquisition_untouched`). The shipped report.js recomputes marker pixel positions from normalized coordinates on load and resize (`test_shipped_script_positions_markers_from_normalized_coordinates_on_load_and_resize`). A changed or missing original is refused when loading, in the editor and at render time. The real-browser resize/reload/keyboard check `test_annotations_browser.py::test_WEB11_markers_stay_on_the_same_physical_spot_across_resize_and_reload` is **browser-marked and not yet executed** on the Pi. |
| WEB-12 | M1/M4 | M1 text/configuration/embedded JSON escaping unchanged (`test_unknown_configuration_nonfinite_numbers_and_yaml_objects_rejected`). M4 asset import (`tests/test_attachments.py`): type decided by content sniffing, not extension; per-type byte and pixel limits enforced from headers; `..`, separators, absolute/drive paths, NUL and hidden names rejected; SVG with `<script>`, `on*` handlers, foreignObject/iframe/object/embed, external or `javascript:` href/xlink:href/use, `@import`/external `url()`, DOCTYPE/entities or stylesheet PIs rejected; PDF with JavaScript, OpenAction, Launch or AA rejected; encrypted PDF rejected. Captions, sensor IDs and labels are HTML-escaped in the report body and Markdown-escaped in print tables; the editor overlay escapes labels. |
| EXP-01 | M1 | Export SVG and PNG with run, DUT, conditions, boundary and synthetic label intact. |
| PDF-01 | M1 | Inspect PDF objects/drawings for genuine vector line plots; a PDF container around a screenshot does not pass. |
| PDF-02 | M1 | **Automated.** `reporting/pdf_check.py` inspects every page of the issued PDF (pdftohtml positions plus pypdf tagged structure and drawing geometry) and records the full result in `build_manifest.json` (`pdf_check`); any error finding marks the PDF `failed-validation` and fails the build while keeping the file. Detects orphan headings, captions separated from figures, lone last table rows or headers alone at a page break, text outside the page box, missing page numbers or run identity, blank pages; extraction failures are findings. `tests/test_pdf_check.py`: Typst-compiled fixtures (clean passes; orphan heading, lone row, clipped text, caption without figure detected) and hand-built cases, plus renderer manifest tests. Also `dcdc-bench pdf-check <report.pdf>`. Issued PDFs re-checked read-only on 2026-09-28: bringup r0004, extended r0007, source-limit r0002, startup-descent r0005 and all mock demos pass; **voltage-sweep r0007 fails** (the last regulation-metrics row sits alone on page 7; pages 6–7 were not in the manual inspection) and needed a presentation revision. Since 2026-09-28 the print theme (`templates/theme/print-tables.typ`, appended to the PDF header include by the renderer) keeps a table whose measured height is at most half a page unbreakable and moves the last two rows of a taller table into a non-repeating Typst footer, which Typst lays out as one unit, so a lone final row cannot occur; headings stick to the block that follows them. `tests/test_print_tables.py` compiles both cases with the bundled Typst against control documents that fail. |
| PDF-03 | M1 | Compare HTML/PDF with the shared report-model revision, figure ordering, captions, and numerical values. |
| PUB-01 | M1/M3 | Reports are local by default: `ReportProfile.publication_enabled` is fixed false and generated HTML carries `noindex`. The only publication path is `dcdc-bench publish <run> --revision rNNNN --out <dir> --approval <yaml>` (`publish.py`): `test_publish.py::test_refused_without_approval_record_and_source_untouched`, `test_incomplete_or_mismatched_approval_is_refused`, `test_redacted_copy_strips_endpoints_paths_serials_and_keeps_numbers` (VISA resources, private IPs, hostnames, internal paths and serials removed from a synthetic run; numeric evidence untouched; non-allowlisted attachments excluded; `publication_manifest.json` records source hashes and redaction counts/field names, never values; source tree unchanged), `test_noindex_retained_by_default_and_injected_if_missing`, `test_public_true_removes_noindex_only_when_approved`, `test_cli_publish_prints_target_and_uses_no_subprocess`. A completed run never triggers Git, GitHub or hosting. `noindex` is not access control. |

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
