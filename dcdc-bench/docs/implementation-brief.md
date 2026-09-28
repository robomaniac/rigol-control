# dcdc-bench

## Implementation brief: reusable DC-DC characterization and engineering reports

**Status:** specification and coding-agent handoff, not a claim that the application already exists. Commands and repository paths below describe the target implementation. Update implementation status as features actually pass their acceptance tests.

**First device under test:** `12T12-4A`, described by the project owner as Cocar / Ekylin / Bgoodvision, with **9-36 V input and 12 V, 4 A, 48 W output**. These are user-supplied ratings, not independently verified manufacturer specifications.

**Primary goal:** configure a test, run it safely using existing Python instrument drivers, and automatically generate a trustworthy interactive HTML report and a matching publication-quality PDF. Make the measurement engine, analysis, and reporting independently usable.

> Acquire once. Preserve the evidence. Analyze explicitly. Render repeatedly. Never let the appearance of a report imply stronger evidence than the measurements provide.

---

## Contents

1. [Instructions for the coding agent](#1-instructions-for-the-coding-agent)
2. [Product goals and first-release scope](#2-product-goals-and-first-release-scope)
3. [First DUT and the actual bench envelope](#3-first-dut-and-the-actual-bench-envelope)
4. [Selected architecture and technology](#4-selected-architecture-and-technology)
5. [Module boundaries and extension contracts](#5-module-boundaries-and-extension-contracts)
6. [Configuration and first test recipes](#6-configuration-and-first-test-recipes)
7. [Run execution and protective behavior](#7-run-execution-and-protective-behavior)
8. [Data contract and revision model](#8-data-contract-and-revision-model)
9. [Analysis and measurement uncertainty](#9-analysis-and-measurement-uncertainty)
10. [Thermal measurements and documentation](#10-thermal-measurements-and-documentation)
11. [Comparison reports](#11-comparison-reports)
12. [Report model, layout, and interactions](#12-report-model-layout-and-interactions)
13. [Bench interface and target commands](#13-bench-interface-and-target-commands)
14. [Validation and regression tests](#14-validation-and-regression-tests)
15. [Implementation milestones](#15-implementation-milestones)
16. [Publication, security, and maintainability](#16-publication-security-and-maintainability)
17. [Decisions still requiring bench confirmation](#17-decisions-still-requiring-bench-confirmation)
18. [Sources and reference artifacts](#18-sources-and-reference-artifacts)

---

## 1. Instructions for the coding agent

Read this document before making architectural changes. Treat `MUST` as an acceptance requirement, not a suggestion. Implement in small, demonstrable increments, with mock hardware first.

### Start here

1. Inspect the supplied repository, existing driver library, example reports, dependency files, and tests. Identify what actually exists. Do not assume a package name, driver method, SCPI command, instrument address, or report generator from prose alone.
2. Write a short reuse plan in `docs/implementation_status.md`: reusable code, missing interfaces, known limitations, and the next milestone. Do not replace functioning instrument drivers without evidence that they cannot support the required adapter.
3. Establish the configuration/data contracts and a deterministic mock bench. Implement one complete run-to-report path before adding many test types.
4. Convert the review findings in Section 14 into tests. The previous reports are visual references and deliberately problematic fixtures, not trusted numerical ground truth.
5. Do not connect to or energize real equipment without explicit authorization and a validated bench profile. Missing real-hardware details must not prevent mock development.

### Engineering rules

- Reuse the owner's existing Python instrument-control library through thin adapters.
- Keep hardware control out of the UI, analysis, and report templates.
- Keep DUT-specific ratings and instrument-specific details out of generic test logic.
- Use one shared analysis model for tables, summaries, plots, captions, exports, HTML, and PDF.
- Do not build a giant script, three separate reporting applications, a cloud platform, or a generalized laboratory framework before the first working test.
- Prefer a small local registry and typed interfaces over a complex plugin-discovery system.
- Never fabricate calibration records, hardware capabilities, raw samples, vendor curves, test results, or verification claims.
- Unknown fields remain unknown. A documented assumption is not a measured fact.
- Mock and imported demonstration data must remain visibly labeled in every report and standalone export.
- Do not ask an LLM at runtime to invent conclusions from plots. Initial automatic prose is deterministic; author interpretation is separately identified and versioned.
- Keep a running record of implemented, tested, partially implemented, and deferred features. Report exactly which commands/tests were executed and on which platform.

### Evidence hierarchy

The latest project-owner requirements govern product behavior. Actual DUT identification, wiring verification, instrument documentation, and calibration records govern hardware operation. The existing reports supply design references and regression cases. Numerical examples and proposed defaults in this README are explicitly marked as such.

Do not import facts from unrelated projects. In particular, the fictional SB60 boards, 5 V output, 60 V DUT limit, four DMMs, temperatures, serial numbers, switching frequencies, and controller identities in the example reports do not describe the first real DUT.

## 2. Product goals and first-release scope

### Desired user experience

**Select DUT -> select bench -> choose tests and limits -> preview feasible points -> authorize the run -> watch progress -> receive HTML/PDF/data automatically.**

A repeat run should usually require selecting a saved recipe and confirming the physical sample and setup, not editing Python.

| Capability | First usable release | Later extension |
|---|---|---|
| Instrument control | Existing source/load drivers through adapters; deterministic mocks | Additional supplies, loads, DMMs, shunts, temperature loggers, scopes |
| Tests | Functional check; steady-state load and input sweeps; efficiency; path/module loss; voltage regulation; enabled no-load consumption | Thermal-soak recipes, repeatability, approved UVLO tests, waveform-based tests |
| Report | One shared characterization template, offline HTML, controlled PDF, CSV/JSON | Comparison and richer evidence exploration using the same components |
| UI | Saved profiles, validation, plan, start/stop, progress, report access | Sensor-placement editor and richer comparison controls |
| Data | Portable versioned run folders | Optional searchable index; no database service required |
| Sharing | Local portable files; synthetic public example | Explicitly approved GitHub Pages publication |

The first end-to-end milestone may be CLI-driven. The normal bench workflow must become a simple UI workflow; the CLI and UI must call the same application services.

### Not in the initial release

No unattended fault injection, short-circuit or thermal-shutdown testing, automatic hardware purchasing, automatic topology identification, waveform claims from DC polling, cloud dependency, or automatic publication of every run. No forced migration to PyICe, PyMeasure, or OpenHTF.

Ripple, startup overshoot, inrush, and load-transient response require an appropriately configured acquisition instrument and method. Do not label ordinary supply/load polling as any of those measurements.

## 3. First DUT and the actual bench envelope

### 3.1 DUT identity

| Field | Initial value | Evidence status |
|---|---|---|
| Model text | `12T12-4A` | User supplied |
| Brand/search aliases | Cocar, Ekylin, Bgoodvision | User supplied; not proof of identical internals |
| Input operating range | 9-36 V DC | User supplied; confirm against the actual sample label |
| Nominal output | 12 V DC | User supplied |
| Rated output current | 4 A | User supplied; derating conditions unknown |
| Rated output power | 48 W | Consistent with 12 V x 4 A; not yet tested |
| Internal topology, controller, frequency | Unknown | Do not infer from a marketplace title |
| Isolation, reverse-current behavior, protection thresholds | Unknown | Confirm what matters to the wiring and recipe |
| Sample serial/revision | Operator supplied, or an assigned local sample ID | Photograph the actual module and label |
| Schematic | Not supplied | Report unavailable, not a fabricated schematic |

Maintaining 12 V with input below and above 12 V would require step-up and step-down behavior. That is behavior to characterize; it does not establish a particular internal circuit topology. Test this device initially as a black-box converter.

An authoritative first-party datasheet for this exact sample was not established during preparation. Preserve the owner's 9-36 V information as user-supplied rather than silently replacing it with specifications from a similarly named listing. Do not import advertised efficiency, waterproofing, temperature, or protection claims without a traceable source.

### 3.2 Source and load constraints

The source discussed is a Rigol DP821/DP821A-family unit. Factory documentation specifies **CH1: 0-60 V, 0-1 A**, and **CH2: 0-8 V, 0-10 A**. Remote sense belongs to CH2, not CH1. [R1, R2]

The physical load model must be confirmed: earlier bench descriptions and example reports use different DL3000 model names. Store the physical model, reported identity, firmware, and any modification separately. A changed identity string is not evidence of a higher certified rating or improved readback accuracy.

**Consequences for the first DUT:**

- CH1 cannot test 48 W output anywhere within a 9-36 V input range. At 36 V and 1 A, even ideal input power is only 36 W.
- CH2 alone is below the stated 9 V minimum input. Do not use it as this DUT's source.
- The generic project's future 60 V capability does not authorize applying 60 V to this 36 V-rated DUT.
- Do not automatically parallel or series outputs or instruments. Combined-source configurations are outside the initial supported bench.
- A second supply is not assumed to exist or to be suitable.

For illustration only, at an assumed 90% efficiency:

`Iin = Pout / (Vin * eta)`

| Vin | Input current for 48 W output, assuming eta = 0.90 |
|---:|---:|
| 9 V | 5.93 A |
| 12 V | 4.44 A |
| 24 V | 2.22 A |
| 36 V | 1.48 A |

For example, `48 W / (9 V * 0.90) = 5.93 A`. This exceeds the CH1 limit by almost six times. This is a planning calculation, not a claim about the module's efficiency.

Full-power testing later requires a source with adequate current at the actual low input voltage. At 80% assumed efficiency, 48 W output at 9 V requires approximately 6.67 A before extra margin. A source's headline wattage alone does not establish that operating point.

### 3.3 Measurement arrangement for the existing-instrument profile

Use the source/load's existing readings for the initial characterization, with their limitations exposed. External precision channels are optional extensions, not prerequisites for building the system.

- Source CH1 power leads connect to the DUT input through the approved wiring/protection arrangement.
- Load power leads connect to the DUT output.
- Load `S+` connects at DUT output positive; `S-` connects at DUT output negative, separately from the current-carrying leads. Enable and verify the load's remote-sense mode. Rigol documents this mode under Utility > System > Sense. [R3]
- Do not connect the supply's CH2 sense terminals to CH1 or to this DUT's 9-36 V input.
- Confirm from documentation and a bench check what each queried voltage/power value represents. Do not assume an internal load power value uses the intended sense location; calculate power from the selected measurement channels.

With source-terminal Vin and DUT-output Vout, the result is **source-to-DUT-output path efficiency**, including input-lead/protection losses. Label it that way. Do not call the corresponding power difference exclusively module heat.

A later external voltage measurement at the DUT input allows a closer module-terminal boundary, while retaining other suitable readbacks. Factory pigtails are included or excluded according to the physical sense locations; document them explicitly.

The bench profile must distinguish **programming ranges and accuracy** from **measurement ranges and accuracy**. In particular, do not apply a DL3000 low CC programming range's accuracy or full-scale term to current readback without documentation that it applies. [R4]

## 4. Selected architecture and technology

### 4.1 Default stack

| Layer | Selected approach |
|---|---|
| Core | Python, typed models, small composable services; target Python 3.11+ unless existing drivers impose a documented constraint |
| Configuration | Pydantic validation; human-editable YAML; versioned JSON snapshots |
| Hardware | Thin adapters over the existing library; no driver rewrite by default |
| Execution | Dedicated instrument-owning worker process; a small command/event interface |
| Analysis | Pure Python/NumPy functions with explicit units and provenance |
| Bench UI | NiceGUI; no blocking instrument I/O on the UI event loop |
| Figures | Shared Plotly specifications and a project-wide graph theme |
| Documents | Quarto for structure/cross-references; Typst PDF output with vector figure assets |
| Static interaction | Local browser JavaScript, embedded data/assets, no Python callback requirement |
| Verification | pytest plus browser interaction/offline tests with Playwright; rendered PDF inspection |

Quarto supports cross-references and Typst output; Plotly supports interactive HTML and static vector exports. Those capabilities are building blocks, not automatic implementation of our custom editor, CSV exports, or comparison logic. [R5-R9]

If an actual, working source generator already exists in the repository and passes the report acceptance tests, reuse it behind `ReportRenderer` and record that decision. The supplied HTML outputs alone do not establish the original generator. Do not implement and maintain two competing document engines merely to keep options open.

Pin and test compatible versions. Use the same Plotly.js version for the delivered HTML and browser tests. Install any required static-export/browser tooling explicitly; a missing renderer must not be reported as a successful PDF build. [R6]

### 4.2 Separation of responsibilities

```text
CLI or NiceGUI
    -> application services
        -> plan validator
        -> dedicated bench worker -> instrument adapters -> existing drivers
        -> run-folder writer

Finalized or explicitly partial run folder
    -> deterministic analysis -> versioned analysis results
        -> shared ReportModel / FigureSpec
            -> offline interactive HTML
            -> static vector figures -> publication PDF
            -> numerical exports / comparison inputs
```

The run folder is the contract between acquisition and reporting. The report generator must run with no hardware present. A UI refresh cannot create a second instrument owner or restart a sweep.

### 4.3 Laptop and Raspberry Pi operation

Support local execution first, and the same runner on a Raspberry Pi controlling LAN instruments. The laptop browser can access the Pi UI through an appropriate local connection or SSH port forwarding. Configuration decides instrument addresses; no source code edits should be necessary.

Do not require rendering tools on the Pi to acquire measurements. The run folder can be rendered on the laptop or in CI. Keep the renderer independent so ARM dependency limitations do not block acquisition.

Default the control UI to loopback. A publicly hosted report never exposes the bench-control API. Do not build a new cloud control service for this project.

## 5. Module boundaries and extension contracts

### 5.1 Suggested repository layout

```text
dcdc-bench/
  README.md
  pyproject.toml
  src/dcdc_bench/
    domain/          # configuration, readings, states, result schemas
    adapters/        # existing-library adapters and mock instruments
    planning/        # grid expansion, capability checks, feasibility
    runner/          # state machine, ownership, acquisition, stop handling
    storage/         # append-only evidence, validation, finalization
    analysis/        # aggregation, metrics, uncertainty, comparisons
    reporting/       # ReportModel, FigureSpec, template data, renderers
    ui/              # NiceGUI views using application services
    services.py      # shared application operations; not instrument logic
    cli.py
  profiles/
    dut/12t12-4a.yaml
    bench/mock.yaml
    bench/rigol.example.yaml
    recipes/12t12-4a-quick.yaml
    recipes/12t12-4a-rated-grid.yaml
  templates/
    characterization.qmd
    comparison.qmd
    theme/
    web/             # reusable interaction code, styles, bundled assets
  tests/
    unit/
    integration/
    browser/
    fixtures/
  examples/          # clearly synthetic, redistributable sample runs
  docs/
    implementation_status.md
    driver_integration.md
    decisions/
  runs/              # ignored by version control by default
```

Group small modules sensibly. This is a separation guide, not a demand to create dozens of empty files before implementing anything.

### 5.2 Required contracts

| Contract | Responsibilities | Must not contain |
|---|---|---|
| `SourceAdapter` | Identify, capabilities, configure supported limits/setpoints, output control, readings, status, bounded close | Report generation or DUT-specific analysis |
| `LoadAdapter` | Identify, capabilities, mode/setpoint, sense setting, input control, readings, status | Assumption that all loads share the same ranges or response |
| `MeasurementProvider` | Supply a named quantity with unit, location, timestamp, range, uncertainty metadata | Implicit replacement of a missing measurement with a setpoint |
| `TestProcedure` | Expand/execute a defined test using services; declare capabilities, expected states, and result type | Direct model-specific SCPI strings |
| `RunStore` | Persist evidence and revisions; validate/hash finalized artifacts | Numerical or scientific conclusions |
| `Analyzer` | Convert evidence to deterministic metrics with provenance | Hardware or UI imports |
| `ReportRenderer` | Render a validated report model to the chosen format | Recompute independent efficiency or regulation formulas |

The same instrument can implement control and measurement roles. A measurement role can later be rebound to a DMM or calibrated shunt without modifying an efficiency test.

No single universal adapter must pretend to support every instrument feature. Capabilities are explicit; unsupported actions fail validation before a run, rather than being silently ignored.

### 5.3 Extending the system

- **New DUT:** add a profile and sample identity, not a new test-runner class.
- **New source or load:** add an adapter and capability tests; reuse procedures and reporting.
- **Better measurement:** change role bindings and uncertainty metadata; preserve the measurement boundary.
- **New test:** add a procedure/result schema/analyzer/report contribution using the existing execution services.
- **New report style:** change the renderer/theme, not raw data or metric functions.
- **New UI:** call the same application services and consume the same event/result schemas.

Adding a second DUT must not require finding and replacing `12T12-4A` inside generic Python or JavaScript.

## 6. Configuration and first test recipes

### 6.1 Four separate configuration objects

| Object | Contains |
|---|---|
| `DutProfile` | Model, sample identity, claimed ratings and sources, known operating constraints, optional topology/configuration, documents |
| `BenchProfile` | Physical equipment, actual capabilities, connection endpoints, measurement-role bindings, locations, protective controls |
| `TestRecipe` | Requested tests, point grids, order, settling/acquisition policies, planning assumptions, approval requirements |
| `ReportProfile` | Title/theme, selected sections, language/units, default views, publication and export settings |

Separate normal operating ratings, absolute protective limits, test-specific expected behavior, and acceptance requirements. They are not interchangeable.

An unknown temperature rating, voltage tolerance, or internal topology must not be filled from the old SB60 report. Missing safety-critical approvals block real execution; missing nonessential description fields show as unknown.

### 6.2 Initial DUT profile example

This is the configuration contract to implement. It is deliberately not armed for hardware.

```yaml
schema_version: "1.0"
profile_id: "12t12-4a"
identity:
  model: "12T12-4A"
  brand_aliases: ["Cocar", "Ekylin", "Bgoodvision"]
  actual_brand_on_label: null
  sample_id: null
  revision: null
  label_photo_asset_id: null
ratings:
  origin: "user_supplied"
  verified_from_sample_label: false
  input_voltage_min_V: 9.0
  input_voltage_max_V: 36.0
  output_voltage_nominal_V: 12.0
  output_current_rated_A: 4.0
  output_power_rated_W: 48.0
  derating_conditions: null
construction:
  topology: "unknown"
  isolation: "unknown"
  controller_part_number: null
  switching_frequency_Hz: null
  enable_interface: "unknown"
  enclosure: "unknown"
acceptance:
  output_voltage_tolerance_pct: null
  minimum_efficiency_pct: null
  maximum_surface_temperature_C: null
execution_approval:
  real_hardware_enabled: false
  wiring_and_polarity_confirmed: false
  protective_policy_id: null
```

Do not treat null acceptance limits as automatic passes or automatic hardware safety thresholds. A characterized device can have no pass/fail requirements while still requiring an approved protective policy.

### 6.3 First sequence

**Stage A: supervised bring-up.** Propose 24 V input, load initially off, followed by 0.1 A output load after verifying output behavior. These values are within the owner-supplied rating and are a proposed first check, not a validated startup procedure. Confirm polarity, current limiting, wiring, output limits, and accessible disconnect before arming.

**Stage B: partial-power quick characterization.** Proposed requested grid:

```yaml
schema_version: "1.0"
recipe_id: "12t12-4a-quick"
dut_profile_id: "12t12-4a"
execution_mode: "mock"
tests:
  - id: "steady-load"
    type: "steady_state_load_sweep"
    input_voltage_targets_V: [12.0, 24.0, 30.0]
    output_current_targets_A: [0.0, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0]
    derived_results:
      - "efficiency"
      - "power_loss"
      - "load_regulation"
      - "enabled_no_load_consumption"
      - "line_regulation_on_common_valid_grid"
planning:
  efficiency_estimate_fraction: 0.80
  source_current_budget_fraction: 0.90
  infeasible_point_policy: "record_and_skip"
  assumption_status: "planning_only_not_measured"
settling:
  policy: "electrical"
  settings_origin: "draft_requires_bench_validation"
  minimum_dwell_s: 5.0
  window_s: 5.0
  minimum_fresh_samples: 5
  maximum_vout_span_V: 0.05
  timeout_s: 30.0
acquisition:
  duration_s: 5.0
  target_poll_interval_s: 0.5
  minimum_complete_cycles: 5
  maximum_interchannel_skew_s: 0.5
  settings_origin: "draft_requires_driver_timing_validation"
authorization:
  require_operator_arming: true
  allow_unattended: false
  protective_policy_id: null
```

The draft settling tolerance is a stability check, not a 50 mV accuracy claim or output acceptance band. Validate polling freshness, instrument response, and achievable timing; do not invent samples to meet the requested count. Persist actual sample counts and timing.

**Stage C: rated-envelope request, not automatic execution.** A later recipe may request input points at 9, 10, 11, 11.5, 12, 12.5, 13, 15, 18, 24, 30, and 36 V and loads through 4 A. The planner must preserve the requested grid while marking unsupported points. Operation near 12 V input is interesting for this 12 V output module, but no mode transition is assumed to occur at exactly 12 V.

Do not start by testing the 9 V and 36 V endpoints. At the low endpoint, input cable drop makes source-terminal voltage an inadequate statement of DUT voltage; at the high endpoint, accuracy and overshoot require headroom. Approve an endpoint measurement/control method before including it in a real run. A 35 V source setting is not a measured 36 V DUT point.

### 6.4 Feasibility planning

For each requested point, check DUT ratings, approved test limits, voltage/current/power capabilities, load operating envelope, measurement ranges, thermal policy, and required channels.

A basic planning estimate is:

`Iin_est_A = (Vout_nominal_V * Iout_requested_A) / (Vin_assumed_at_DUT_V * eta_estimate)`

Compare with the usable source-current budget. Account for any separately modeled auxiliary consumption and wiring allowance without double-counting them. At no load, zero requested output power does not imply zero input power; record that its input draw is not established.

An illustrative 80% efficiency estimate and 0.9 A source budget give nominal output-current ceilings of 0.54 A at 9 V, 0.72 A at 12 V, 1.44 A at 24 V, and 2.16 A at 36 V. These are planning estimates, not validated safe maxima or actual DUT capability.

The planner must distinguish a point exceeding a physical rating from one skipped because of a conservative planning budget. A poor efficiency estimate can still cause current limiting at a point predicted feasible; actual status always governs validity.

The preview shows requested, executable, assumption-limited, unsupported, and approval-blocked points with reasons. Do not silently lower a requested load and report it as if the original point was measured.

## 7. Run execution and protective behavior

### 7.1 Ownership and lifecycle

Only one worker owns a bench at a time, enforced beyond a browser-local flag. Use an OS/process-level lock and instrument identity checks. Two tabs, two UI clients, or a concurrent CLI cannot issue independent commands to the same owned instruments.

Suggested lifecycle:

```text
IDLE -> VALIDATING -> PLAN_READY -> AWAITING_ARM
     -> CONNECTING -> PREFLIGHT -> RUNNING
     -> STOPPING -> FINALIZING -> COMPLETED / ABORTED / ERROR
```

Record instrument output state independently, including `UNKNOWN`. A completed report job is not evidence that hardware is de-energized. A failed PDF job is not a failed electrical test.

`RUNNING` includes explicit configuring, settling, acquiring, and point-finalizing phases. Persist phase transitions and reasons.

### 7.2 Before energizing

- Validate approved profile/plan identity and hash; changed limits require fresh approval.
- Identify expected instruments and compare physical/reported configuration with the approved bench.
- Verify safe initial output/load state rather than assuming it from a previous connection.
- Set and verify supported protective settings before enabling outputs.
- Verify sense configuration and measurement-role availability.
- Confirm the setup's electrical boundary, polarity, grounding, wiring protection, and disconnect arrangement.
- Confirm any warm-up/calibration prerequisites used by the selected uncertainty model; record deviations.
- Confirm required sensors are returning fresh, plausible readings.

A read-only `doctor` command must not enable outputs, reset instruments, or clear evidence of faults. Driver connection side effects must be documented and tested.

### 7.3 At each point

Apply setpoints according to the approved sequence, monitor status, wait for the declared settling condition, collect fresh readings with timestamps, validate the acquisition, and save immediately. Give startup a bounded, separately defined phase: do not apply steady-state minimum-output checks before the permitted startup interval has elapsed, and do not apply load until the approved sequence allows it. Read source CV/CC and load compliance/protection status where supported. Mark unsupported status observability explicitly.

Current limiting, unachieved setpoints, invalid sense readings, stale samples, range overload, excessive skew, and unsettled operation cannot become ordinary valid nominal operating points.

Do not silently continue indefinitely after a communication or safety fault. Recoverable point failures and run-fatal failures have explicit policies. Retrying an ambiguous output-enable command requires state reconciliation, not blind repetition.

### 7.4 Stop, fault, and disconnect handling

Use bounded command timeouts and cooperative cancellation. Blocking driver calls stay out of the UI event loop. A separate worker process provides isolation; it does not itself make the hardware safe.

Provide distinct controlled-stop and urgent-fault procedures. Their output/load ordering must be approved for the bench/DUT; do not assume one universal order is safe for every converter.

Shutdown attempts are independent: an error communicating with one instrument must not prevent attempting the defined protective action on another. Record each command, acknowledgment, readback, and uncertainty about final state. A returned SCPI command alone is not proof of zero voltage.

Source current limiting and latched overcurrent protection are different functions; configure only documented capabilities. Source overvoltage protection is not independent protection of the converter output. A worker crash, cable removal, or power failure can prevent software shutdown. Real unattended mode remains disabled until an appropriate independent protective/disconnect strategy has been reviewed. A watchdog in the same crashed process is not independent protection.

After interruption, preserve partial data and generate an explicitly incomplete report when possible. Never auto-resume hardware output on UI reload, process restart, or opening an old run.

### 7.5 Test-specific expected states

For a future approved UVLO test, output-off is expected during part of the ramp. Scope the normal minimum-Vout rule to the appropriate phase while maintaining absolute current, voltage, and other protective limits.

Do not use a global `ignore_safety` flag. Unknown input-voltage conditions beyond the established normal range require a separate approved recipe. Current-limit, short-circuit, reverse-power, and thermal-shutdown tests are opt-in later features.

## 8. Data contract and revision model

### 8.1 Portable run package

```text
runs/<run_id>/
  request.json                 # immutable submitted request
  plan.json                    # resolved grid, checks, assumptions, approvals
  run.json                     # acquisition identity and finalized as-run metadata
  raw/
    samples.jsonl              # append-only individual instrument readings
    events.jsonl               # commands/status/transitions/faults
    point_events.jsonl         # planned and completed point states
  attachments/
    originals/                 # evidence assets, never destructively edited
    manifest.json              # hashes, identities, captions, ownership
  integrity.json               # finalized evidence hashes and schema versions
  analysis/<analysis_id>/
    analysis.json              # formula versions, assumptions, selections, provenance
    points.csv                 # aggregated operating-point results
    metrics.json
    uncertainty.json
    validation.json
  reports/<report_revision>/
    report_model.json
    annotations.json
    report.html
    report.pdf
    figures/
    exports/
    build_manifest.json
```

File naming can be simplified, but preserve the distinctions. JSON Lines provides streaming records; CSV is an interchange/export view, not the only raw evidence store. Optional indexes are rebuildable and must not become the sole copy of measurements.

Write data incrementally with a documented durability policy. Finalize structured files atomically. Disk-write errors must not leave a running test pretending measurements are being preserved. Mark truncated/unfinalized records on recovery rather than silently treating them as complete.

### 8.2 Identity and provenance

Use stable IDs for runs, samples, points, test instances, instruments, measurement channels, attachments, analysis revisions, reports, and comparisons. Timestamps use UTC with timezone information; durations use a monotonic clock.

A raw reading includes at least:

| Field | Meaning |
|---|---|
| `sample_id`, `run_id`, `test_id`, `point_id` | Traceability to its acquisition context |
| `channel_id`, `instrument_id` | Which physical/virtual measurement produced it |
| `quantity`, `value`, `unit` | Explicit physical quantity; canonical numeric units |
| `location_id` | Source terminals, DUT input, DUT output, case sensor, etc. |
| `query_started_utc`, `query_completed_utc`, monotonic bounds | Observed timing; do not invent an internal measurement timestamp |
| `device_timestamp` | Optional, only if provided and understood |
| `range_id`, `resolution`, acquisition settings | Actual selection or explicitly unknown |
| `raw_response`, `status`, `quality_flags` | Original evidence and parse/validity result |

Record per-reading start/end times and per-acquisition-cycle identifiers. Independent instrument polls are not simultaneous merely because they occur within the same function.

Keep requested setpoints separate from measured values and from corrected values. Preserve original raw readings when applying a documented correction. JSON must not contain nonstandard `NaN` or infinity values; use null plus a reason/status. CSV missing numeric values are empty, not the string `null` or a fabricated zero.

### 8.3 States and coverage

Use separate concepts:

- **Run execution:** completed, aborted, error, interrupted.
- **Point acquisition:** valid, setup-limited, unsupported, not-run, inconclusive, error.
- **Requirement result:** pass, fail, not-evaluated, not-applicable, with a requirement ID and decision rule.
- **Measurement qualification:** quantified uncertainty, specification-bound only, unquantified, boundary-limited, etc.

A complete acquisition can have unquantified uncertainty. A DUT can be characterized without pass/fail criteria. A source-limited point is not a failed DUT requirement.

Calculate coverage per test and aggregate explicitly. The load-sweep count cannot stand in for separate line-sweep, UVLO, and thermal acquisition counts. Shared samples used for several derived analyses must not be presented as independently acquired multiple times.

### 8.4 Immutability and revisions

Finalize acquisition evidence as immutable. Retain derived results as versioned outputs rather than recalculating history in place. A corrected formula creates a new analysis revision; changed prose, figure selection, or captions create a new report revision referencing the relevant analysis.

Record software commit, dependency lock identity, schema versions, analysis/formula version, template/theme version, data hashes, and rendering versions. Deterministic numerical content is required; byte-identical PDFs are not required if build timestamps differ and those differences are documented.

Revised attachments/annotations reference original asset hashes and do not alter acquisition truth. Post-run photos or notes belong to a new documentation/report revision or a content-addressed asset store with a new revision manifest; do not rewrite the finalized acquisition manifest and hashes to make an attachment appear to have existed during acquisition. Importing a legacy aggregate-only report cannot recreate nonexistent raw samples; mark its evidence level accordingly.

## 9. Analysis and measurement uncertainty

### 9.1 Metric definitions

For qualified, settled DC measurements, define:

```text
Pin_W         = Vin_V * Iin_A
Pout_W        = Vout_V * Iout_A
eta_pct       = 100 * Pout_W / Pin_W
Ploss_W       = Pin_W - Pout_W
Vout_error_pct = 100 * (Vout_V - Vout_nominal_V) / Vout_nominal_V
```

Each quantity uses the selected measurement boundary. External bias sources belong in input power if the report claims efficiency including them. No external bias is assumed for the first module unless actually present.

Use an explicit aggregation method: for the initial settled-DC profile, compute qualified channel means over the accepted acquisition window and calculate metrics from those means. Record the method and timing qualifications. For later synchronized waveform measurements, mean instantaneous power is a different method; do not interchange it silently with the product of independently averaged DC readings.

For each voltage/current sweep, distinguish voltage span from absolute nominal error:

```text
load_regulation_span_pct =
    100 * (max(Vout) - min(Vout)) / Vout_nominal
    # within a specified fixed-input sweep and qualified load range

line_regulation_span_pct =
    100 * (max(Vout) - min(Vout)) / Vout_nominal
    # within a specified fixed-load sweep and qualified input range
```

Store the dataset selector, actual conditions, point IDs, formula, and covered range with every metric. Do not claim full-range regulation from a partial grid. A separate endpoint-based definition or mV/A slope must have its own name.

No-load reports emphasize **enabled, no-external-load board/path input consumption**. Do not automatically call it controller quiescent current or attribute it entirely to switching losses. No-load efficiency is displayed as not applicable in the default report.

Never clamp an efficiency above 100% or a negative loss to a plausible value. Preserve and flag it; investigate measurement timing, boundary, error, sign, and calculation. If Pin is nonpositive or inadequately established, suppress the ratio with an explicit reason while retaining readings.

Compute with retained precision, round only for presentation, and avoid excessive displayed precision. Report the highest measured point, not a universal maximum. Ties and unresolved differences need appropriate wording.

### 9.2 Uncertainty policy

Design for proper uncertainty without making a finished precision budget a prerequisite for the first qualitative bench run.

Use a structured budget referencing applicable measurement specifications, ranges, conditions, calibration information, corrections, and statistical observations. Keep standard uncertainty, expanded uncertainty, error bounds, and repeatability distinct. Unknown inputs cannot produce a numerical zero-uncertainty result.

A justified rectangular error limit of half-width `a` corresponds to standard uncertainty `a/sqrt(3)`. Combine standard contributions using the declared measurement model, including covariance where appropriate. Expanded uncertainty is `U = k * u_c`; do not automatically describe every `k=2` interval as a validated 95% confidence interval. [R10, R11]

Our implementation requirements:

- Store read-percentage, range/full-scale, absolute-offset, calibration-interval, temperature, and acquisition-condition terms explicitly.
- Do not confuse output setting accuracy with readback accuracy, resolution, or number of display digits.
- Do not assign random uncertainty numbers or one blanket percentage to every point.
- Do not reduce systematic specification/calibration contributions by `sqrt(N)` just because readings were averaged.
- Log actual ranges. Unknown or modified instrument applicability means qualification is required, not invented precision.
- Label efficiency uncertainty in **percentage points**, e.g. `92.6% +/- 0.4 percentage points`, not an ambiguous relative percent.
- Loss uncertainty needs its own propagation; do not reuse efficiency uncertainty in watts.
- Near zero input current, assess whether the linear approximation and symmetric intervals remain meaningful. If not, flag insufficient resolution or use a separately validated nonlinear method.
- If a budget is not evaluated, show that fact, omit validated-looking bands, and avoid measurement-resolution verdicts.
- External DMM/shunt channels are pluggable improvements. Four meters are not a blanket requirement.

The instrument selection question is: what uncertainty is needed to resolve the intended engineering difference, and which channel dominates it? It is not: how many digits appear on a meter's front panel?

### 9.3 Automatic prose

Automatic narrative may state computed observations and coverage, with clickable figure references. For example: highest measured efficiency at specified conditions, output span over a specified range, or points unavailable because the source budget was exceeded.

Separate author-entered **interpretation**, **hypothesis**, and **recommended next test** from computed observations. Do not infer transistor loss mechanisms, feedback-loop causes, mode transitions, or vendor-curve agreement without relevant evidence. A trend in efficiency does not identify a unique internal cause.

## 10. Thermal measurements and documentation

Temperature is optional for the electrical MVP. A thermal test requires a real configured acquisition channel; missing sensors must not be replaced by model-generated values in a real run.

Store sensor ID, instrument/channel, sensor type, measured surface, attachment method, ambient reference, calibration/status, and location on a photograph. Use normalized image coordinates associated with the exact original image hash, so resizing does not move the marker to a different physical location.

For a sealed or potted first DUT, attach to a documented accessible case location. Do not label it U1 or junction temperature. Internal component positions are unknown unless actually documented. Opening the enclosure can change the thermal conditions and must create a distinct setup.

Record both absolute temperature and rise above time-aligned ambient. Record board/module orientation, mounting, airflow, enclosure condition, and any heatsink. A missing ambient reference means no valid rise calculation, not an assumed room temperature.

Separate:

- **Electrical settling:** sufficient for a qualified quick DC sweep, with actual temperature logged when available.
- **Thermal settling:** a documented slope/window criterion, electrical validity, ambient monitoring, minimum observation, and maximum timeout.

Do not enforce the old synthetic report's thermal rule on every electrical point. Proposed thermal criteria require validation for the module, sensor, and setup. Preserve the time series and show at least one settling plot in a thermal report.

A slope of case/surface rise versus total measured loss is an empirical relationship for the stated boundary and setup. It is not automatically component thermal resistance or a junction-temperature estimator. Source-path loss that includes input wiring is not isolated module dissipation.

Several thermocouples do not constitute a measured thermal image. Show actual sensor positions, not an invented continuous temperature field.

## 11. Comparison reports

Comparison uses existing run and analysis revisions; it does not command instruments.

Match explicit conditions and provenance: output configuration, target point, actual achieved conditions within declared tolerances, measurement boundary, methodology, thermal state, mounting/airflow, instrument applicability, and relevant DUT mode/settings.

Default to paired measured points only. Display unmatched points separately and do not silently interpolate, extrapolate, or join by array position. An optional interpolated comparison must be explicitly enabled, labeled, and excluded from measured-point claims unless a suitable analysis is defined.

Use `delta_eta_pp = eta_B_pct - eta_A_pct`. Keep a zero reference line and a prominently placed difference plot. Color identifies the selected operating condition; line style/marker identifies the device. Device A being higher and device B being higher use symmetric neutral treatment, not green versus warning amber.

If a validated difference budget exists, compute from standard uncertainties and documented shared contributions. For two quantities, the difference model includes `u_delta^2 = u_A^2 + u_B^2 - 2*cov(A,B)`; independence is an explicit assumption, not automatic because there are two run folders. [R11]

Without a suitable budget, use descriptive differences and `not evaluated` for resolvability. Do not say a difference is real because it exceeds display resolution. A per-point uncertainty statement does not establish superiority across all devices or conditions.

Compare implementations as tested. If switch technology, frequency, magnetics, layout, or cooling differ, disclose them. Do not call an observed gap a technology limit or a floor on the technology difference.

A lower surface-temperature rise at one point does not imply a universally cooler design or lower junction temperature. Identify the sensor and actual condition; retain regions where the ordering reverses.

## 12. Report model, layout, and interactions

### 12.1 Shared report model

Use typed, serializable objects such as `MetricResult`, `FigureSpec`, `TableSpec`, `EvidenceRef`, and `ReportModel`. Do not build every view from unrelated ad hoc arrays.

A `MetricResult` includes its value, unit, formula/version, selector, covered conditions, point IDs, qualification, uncertainty reference, and figure/table evidence IDs.

A `FigureSpec` includes stable ID, source dataset/selection, units, series/point IDs, uncertainty source, default view, caption conditions, and export metadata. Assign human-readable figure numbers from one ordered registry shared by HTML and PDF. References target stable anchors, never manually typed numbers that break when a figure is inserted.

The report renderer consumes validated results. It must not independently recalculate line regulation or invent narrative conditions. A report validation error must be visible and block an ordinary issued publication, not be hidden by an attractive template.

### 12.2 Visual direction to retain

Use the restrained document layout from the reviewed reports: clear headings, compact identity metadata, a readable sidebar in HTML, light grids, visible measured-point markers, and strong blue/teal/purple-style trace colors. The owner's inspiration is the modern software-generated EPC plots, particularly EPC90120 pages 9-11, combined with TI-like document organization. [R14]

Prioritize sharp vector figures, legible type, clear spacing, and concise captions. Do not copy vendor logos or imply affiliation. Preserve this direction rather than redesigning the project into a dashboard of decorative cards.

### 12.3 Default document structure

| Section | Contents |
|---|---|
| First-page summary | Identity, evidence type, important results/conditions, coverage, significant limitations, short computed narrative |
| DUT | Ratings with sources/status, actual sample photo, configuration, available schematic or an honest unavailable notice |
| Setup and method | Connection diagram generated from the actual bench, measurement boundary, equipment, ranges, acquisition/settling, environment |
| Results | One subsection per performed test: purpose, conditions, figure, relevant metrics, qualification |
| Interpretation | Optional author observations/hypotheses/next tests, separate from automatic findings |
| Appendix | Excluded points, uncertainty assumptions, selected detail; full data/configuration available as linked/bundled artifacts |

Do not devote the first page only to a cover and a long contents list. Do not include empty pages for unperformed tests. List important not-evaluated capabilities compactly. Full dense raw tables are optional appendices, not mandatory tiny text in every report.

The equipment section reflects actual channel bindings. It cannot always show four DMMs simply because the demonstration did. A setup diagram must include enabled sense paths and distinguish them from power leads.

### 12.4 Interactive HTML requirements

The standalone HTML must work from `file://` with external network requests blocked. Embed the plotting library, required data, styles, and display assets. No CDN, remote fonts, telemetry, or Python callback is required to review it. A static website build may share local assets, but downloadable standalone mode must remain self-contained. [R5, R8]

Required interactions:

1. Detailed point hover with actual readings/conditions/units and qualification. Call aggregated values point results, not raw acquisition windows.
2. Click or otherwise select a point to inspect available raw samples and timing. Clearly identify evidence that is absent or supplied in a companion data package.
3. Filter by input condition, DUT/run, selected metric, and available temperature channels without modifying issued findings.
4. Keep trace checkboxes, legend toggles, uncertainty bands, filters, and exports synchronized through one view-state model.
5. Provide **Reset zoom** and **Restore default view** as distinct actions. The latter restores filters, trace visibility, axes, log state, hover mode, and sensor highlighting.
6. Preserve actual measured markers. Interpolated cursor values, if offered, are labeled as interpolated, not measurements.
7. Log-current mode explicitly excludes nonpositive points from that view; keep no-load results accessible elsewhere. Do not replace zero with an arbitrary small number.
8. Default axis limits include all selected valid data and applicable uncertainty bands. Invalid/absent segments cannot be joined as though measured continuously.
9. Clickable sensor markers and figure cross-references connect the document to its evidence. Keyboard access and readable labels are required.
10. Issued summary/metrics remain fixed while a reader explores. An exploratory selection is a view, not a new approved conclusion.

Use linked separate graphs for efficiency, voltage, and temperature where their units differ. Avoid a confusing collection of arbitrary secondary axes.

### 12.5 Numerical and figure exports

Use explicit actions:

| Action | Required behavior |
|---|---|
| Export selected curves | All points in selected traces after non-zoom condition filters |
| Export visible range | Selected traces filtered to current visible axis bounds, with inclusive boundary semantics documented |
| Export SVG | Vector plot, axes, legend, and contextual footer |
| Export PNG | Same view and context, suitable resolution |
| Save view | Portable view-state JSON referencing the report/analysis IDs, not changed measurements |
| Generate issued report | Canonical approved/default view from the versioned report model |
| Print current view | Explicitly labeled exploratory print; not silently the canonical PDF |

CSV must use unique column names, stable units, correct quoting, empty missing values, and retained numerical precision. Include point/run/analysis IDs. Provide conditions and view selection in a JSON sidecar or a clearly documented metadata-comment option; do not make ordinary CSV parsers guess where the header begins. Prevent spreadsheet formula injection in untrusted text fields without altering stored evidence.

A figure exported alone must retain DUT/run identity, figure ID, relevant conditions, boundary/method qualification, and synthetic-data marking where applicable. It must not become an unexplained curve separated from its caption.

Ensure asynchronous plot updates finish before reading state or exporting. Exact library versions used for release tests must match shipped assets.

### 12.6 PDF requirements

Generate the canonical PDF from the same report model and selection as canonical HTML. Export ordinary line plots as vector SVG/PDF and preserve them through document assembly. Avoid WebGL plot types for these publication figures; exporting a vector container does not by itself make a raster plot vector. [R6]

PDF acceptance requires selectable text, readable plots, page numbering, report/run identity, working internal references/bookmarks where supported, and actual links to HTML/data when a destination exists. Never invent a publication URL.

Keep figures with captions, keep a heading with its introductory content, repeat table headers as needed, and avoid a lone final table row on another page. Do not force every small section to start a new page or prevent a large table from splitting at all.

Render and visually inspect every page in release tests. Include an object-level check on vector fixtures so graphs cannot silently regress to PNG screenshots. Photographs may remain raster.

### 12.7 Local report editor

The bench/editor UI, not the public static viewer, owns persistent uploads and author changes. Support photos, schematic pages, setup images, captions, notes, and sensor placement in a reusable asset/annotation model.

Store original assets immutably. Move sensor markers using normalized coordinates; save edits as a new documentation/report revision. A missing schematic is shown as missing rather than a nonfunctional filename link.

Saving a personalized static copy may be a later feature, but it must clearly distinguish changed presentation from original evidence. Opening the published report must never grant access to instruments or silently overwrite a run.

## 13. Bench interface and target commands

### 13.1 UI design

Use four main areas: **Bench**, **DUT and recipe**, **Run**, **Reports**. Keep advanced acquisition/uncertainty settings in expandable sections while exposing consequential limits and measurement boundaries before Start.

The plan preview is mandatory and readable: show source/load identity, requested grid, feasible subset, missing approvals, assumptions, and likely coverage. Do not hide a 48 W source limitation in a debug log.

During a run show actual conditions, point/overall progress, instrument mode/status, elapsed time, settling state, last measurement age, events, and Stop. UI feedback must distinguish a requested stop from confirmed shutdown and from an unknown hardware state.

Do not put slow report rendering in the acquisition loop. After finalization, automatically enqueue configured analysis/HTML/PDF generation and show success or failure for each artifact.

### 13.2 CLI contract

These commands are targets to implement, not claims of existing executables:

```bash
dcdc-bench demo --out examples/generated
dcdc-bench validate --dut profiles/dut/12t12-4a.yaml --bench profiles/bench/mock.yaml --recipe profiles/recipes/12t12-4a-quick.yaml
dcdc-bench plan --dut profiles/dut/12t12-4a.yaml --bench profiles/bench/mock.yaml --recipe profiles/recipes/12t12-4a-quick.yaml --out plan.json
dcdc-bench run --plan plan.json --mode mock --out runs
dcdc-bench doctor --bench config/bench.local.yaml
dcdc-bench run --plan approved-plan.json --mode real --arm
dcdc-bench analyze runs/<run_id>
dcdc-bench report runs/<run_id> --formats html,pdf
dcdc-bench compare runs/<run_a> runs/<run_b> --out comparisons/<comparison_id>
dcdc-bench ui --bench config/bench.local.yaml
```

Define real arming semantics explicitly: `--arm` is not a bypass for missing approval, capabilities, or protective policy. Validate the selected mode against the plan. The demo never opens real instrument connections or requires them.

Use stable exit codes and helpful actionable errors. Document installation once it is implemented, including Windows and Pi/Linux setup, optional hardware backends, and rendering dependencies. Do not publish example clone URLs for a nonexistent repository.

Aim for one documented setup command per platform and one command to generate an offline demo. Users should not edit internal files to add a device or rerender data.

## 14. Validation and regression tests

Treat these as executable acceptance cases, tracked against the milestone that introduces each feature. M1 does not need an implemented thermal editor or comparison engine, but its contracts must support them. Values taken from old reports are **synthetic regression fixtures**, not reference measurements of the new DUT.

### 14.1 Domain, planner, and acquisition

| ID | Test | Acceptance |
|---|---|---|
| CORE-01 | First DUT profile | Stores 9-36 V, 12 V, 4 A, 48 W with user-supplied origin; no SB60 defaults |
| CORE-02 | 48 W on CH1 | Rejected across the 9-36 V range even with eta = 1.0 |
| CORE-03 | CH2 selection | Cannot be the sole source for a DUT with stated 9 V minimum |
| CORE-04 | Sense capability | CH1 remote-sense request fails validation; load sense is separately configured |
| CORE-05 | Requested versus achievable | Infeasible points remain in coverage with reason; no silent setpoint clipping |
| CORE-06 | Range metadata | Programming accuracy cannot be substituted for readback accuracy |
| CORE-07 | Data-driven reuse | A second different-output DUT and a mock alternate source run without editing generic test/report code |
| RUN-01 | Duplicate starts | Two clients cannot acquire ownership or energize independently |
| RUN-02 | Browser refresh | Does not restart, duplicate, or automatically abort/rearm the hardware sequence |
| RUN-03 | Communication timeout | Bounded failure; partial evidence saved; defined shutdown attempts made independently |
| RUN-04 | Worker crash/disconnect | No false claim that outputs are off; restart requires reconciliation and fresh arming |
| RUN-05 | Current limiting | Invalidates the nominal point; no efficiency claim at an unachieved input condition |
| RUN-06 | Unsettled/stale/overrange data | Correct point qualification with raw readings retained |
| RUN-07 | Missing thermal channel | A required thermal test cannot run; an optional electrical test does not invent temperature |
| RUN-08 | Persistence failure | Run cannot continue pretending acquisition is durable; failure is surfaced |
| RUN-09 | Test-scoped rules | Approved UVLO expected-off phase does not trip a normal regulation rule; absolute guards still apply |
| RUN-10 | No real side effects | Mock, plan, import, report, and ordinary CI never energize real instruments |

### 14.2 Analysis and report consistency

| ID | Test | Acceptance |
|---|---|---|
| DATA-01 | Arithmetic identity | From one data source, Pin, Pout, loss, efficiency, tables, hover, and exports agree within defined numerical tolerance |
| DATA-02 | Line-regulation regression | (5.0186 - 4.9995) / 5.0 * 100 = 0.382%; caption and summary cover 12-60 V, not the old 0.29% value |
| DATA-03 | First available point | A curve beginning at 18 V cannot have a caption saying 16 V |
| DATA-04 | UVLO bracket | Ramp down: on at 9.1 V and off at 9.0 V produces a bracket/declared convention, not an unsupported exact threshold |
| DATA-05 | Per-test coverage | Extra line and UVLO sweeps cannot be concealed under the load-grid's 37/39 count |
| DATA-06 | No-load and invalid ratios | No-load eta is not applicable; negative/nonpositive Pin and implausible eta are preserved/flagged, not clamped |
| DATA-07 | Revised analysis | Formula changes produce a new revision; previous issued results remain reproducible |
| DATA-08 | Evidence validation | Every figure/metric references existing points and declared conditions; missing references fail report validation |
| UNC-01 | Old light-load uncertainty | With explicit independent rectangular current limits, the fixture below produces about 1.16 percentage points from currents alone, not 0.11 |
| UNC-02 | Missing budget | No fabricated bands or difference-resolution verdicts |
| UNC-03 | Shared error | Difference calculation respects a supplied covariance model; independence is recorded when assumed |
| UNC-04 | Repeated sampling | Increasing N does not automatically shrink systematic contributions |
| CMP-01 | Matching | Pair by qualified conditions/IDs, not array index; report unpaired 16 V versus 18 V availability |
| CMP-02 | Interpretation | No automatic technology-causation or universal-cooler conclusion from board comparisons |

`UNC-01` uses eta = 40.24%, Iin = 7.8 mA, Iout = 30 mA, input-current error limit `(0.05% of reading + 0.1 mA)`, and output-current error limit `(0.10% of reading + 0.6 mA)`:

```text
input limit  = 0.0005 * 7.8 + 0.1 = 0.1039 mA
output limit = 0.0010 * 30  + 0.6 = 0.6300 mA
U_eta = 2 * 40.24 / sqrt(3)
        * sqrt((0.1039 / 7.8)^2 + (0.63 / 30)^2)
      = 1.155512754 percentage points, displayed as approximately 1.16
```

This fixture deliberately specifies its assumptions and omits voltage terms. It is a test of the calculation, not the first DUT's actual uncertainty budget.

### 14.3 Browser, export, and PDF

| ID | Test | Acceptance |
|---|---|---|
| WEB-01 | Offline | All plots, filtering, exports, and embedded display assets work with external network requests blocked |
| WEB-02 | Exact version | Browser test uses the shipped Plotly.js version, not an unrecorded substitute |
| WEB-03 | Visibility | Legend, checkbox, main trace, band, and exported selected curves always agree |
| WEB-04 | Reset behavior | Reset zoom and Restore default view perform their separately documented actions |
| WEB-05 | Export scope | Zoom to 0.5-1 A: visible-range export contains that range; selected-curves export retains all selected points |
| WEB-06 | CSV schema | No duplicate eta/loss headers; escaping, numeric missing values, units, metadata, and IDs verified |
| WEB-07 | Axis clipping | The old 39.1575% point is visible in the default efficiency view, not cropped by a 40% minimum |
| WEB-08 | Log mode | Nonpositive points are handled explicitly; transforms do not corrupt exported bounds |
| WEB-09 | Evidence links | Summary figure references navigate correctly; raw evidence availability is honest |
| WEB-10 | Issued versus exploratory | Filtering changes views but not the issued summary or original report revision |
| WEB-11 | Sensor annotations | Marker coordinates survive resize, asset reload, and saved revision; incorrect asset hashes are detected |
| WEB-12 | Injection | Untrusted captions, asset names, JSON strings, and imported configuration cannot execute code |
| EXP-01 | Standalone figure | SVG/PNG retain run/DUT/conditions and synthetic marking |
| PDF-01 | Vector preservation | A vector-line-plot fixture remains vector in the PDF; no graph-sized raster replacement |
| PDF-02 | Pagination | Every rendered page inspected; no clipped text, orphan headings/captions, or lone continuation row caused by avoid-all splitting |
| PDF-03 | Cross-format identity | Canonical HTML/PDF use the same numeric results, conditions, figure registry, and analysis revision |
| PUB-01 | Publication gate | Synthetic/private runs do not become indexed or published simply because a run completes |

Test the worker and adapters with a deterministic mock plant, not merely precalculated graph arrays. Model source current limiting, measurement noise/offset/range, load response, and configurable settling. Inject timeouts, stale data, malformed responses, and report-render failure. Use a virtual clock for fast unit tests and real timing for selected integration tests.

Mock output must remain physically consistent with its declared model while being clearly synthetic. Store model version and seed; do not tune independent random numbers until charts look plausible.

## 15. Implementation milestones

### M0: audit and contracts

Deliver repository reuse inventory, typed profile/result schemas, first DUT and mock bench profiles, a feasible-point planner, and core constraint tests. Document unknown real-driver APIs rather than guessing them.

**Exit:** the full request can be represented and validated without hidden constants in the runner.

### M1: complete mock-to-report path

Implement mock adapters, worker lifecycle, streaming evidence, deterministic steady-state analysis, and one report template. Generate standalone HTML and a matching vector PDF automatically after a run. Include setup-limited and aborted example runs.

**Exit:** one demo command works without hardware; numerical, offline, export, and basic PDF checks pass. This is the first vertical slice, not a screenshot-only prototype.

### M2: supervised real point

Adapt existing drivers, validate their actual settings/readback/status/timing, and complete the bench protective profile. Perform the approved no-load/24 V/0.1 A bring-up sequence only after explicit user authorization.

**Exit:** saved measurements agree with observed bench behavior, point provenance is complete, and the approved stop procedure has been demonstrated. Record what was and was not independently checked.

### M3: partial-power sweep and simple UI

Run the approved small grid, distinguish setup limitations from DUT behavior, and generate reports without manual copying. Add reusable profile/recipe forms, run progress, report access, and attachment metadata.

**Exit:** an engineer can repeat a qualified limited-power run using the UI, and a new DUT can be configured without source edits.

### M4: comparisons and thermal extension

Implement paired-run comparison from stored analysis, difference plots, local photo/sensor annotation, real temperature adapters as available, and separate thermal settling. Preserve the same report/data contracts.

**Exit:** comparison and temperature claims pass their respective evidence/uncertainty checks; changing a report or adding an image never reruns instruments.

### M5: expanded capability

Only after the earlier path is dependable: full-power source profile, reviewed uncertainty improvements, approved UVLO recipe, scope captures/dynamic tests, richer imports, and explicitly approved public examples.

Do not implement every advanced test before the first real steady-state sweep. Do not turn source replacement or a four-DMM purchase into a prerequisite for the software milestones.

## 16. Publication, security, and maintainability

### Public and private outputs

Public reports use descriptive titles, semantic HTML headings, readable initial-HTML summaries/tables/captions, and links from a report index. Public stable URLs, canonical metadata, and a sitemap are added only after a real hosting destination exists.

Use GitHub Pages for approved static reports, not the Python instrument-control process. GitHub Pages hosts static HTML/CSS/JavaScript. [R12]

Default reports to private/local workflow and synthetic examples to `noindex`. Indexing is an explicit publication choice. `noindex` is not access control; confidential data require an access-controlled destination, not a publicly reachable file with a robots tag. [R13]

Publishing uses an allowlist/approval record and must not be triggered merely by the existence of a run folder. No automatic push to the owner's GitHub account is authorized by this README.

### Data and application hygiene

Escape/sanitize text and embedded JSON. Treat imported run files as data: no `eval`, pickle loading, arbitrary Python execution, or command strings from recipes. Validate asset types, dimensions, sizes, paths, and SVG contents. Reject path traversal and executable active content in attachments.

Keep local instrument IPs, credentials, internal paths, and private photographs out of public exports unless explicitly approved. Retain an internal full record and a traceable redacted publication copy. Do not misrepresent redacted data as complete raw evidence.

Do not redistribute third-party fonts, manufacturer documents, or code without checking licenses. Reference manufacturer styling, not their branding. The owner should choose the repository license before publication; do not claim a license grant for the existing driver library.

### Maintainability

Use a `src` package, documented public interfaces, type hints, meaningful exceptions, structured logs, linting, and versioned schemas. Dependency upgrades run the browser/PDF regression suite before release. Keep heavy rendering/UI dependencies separable from headless acquisition when practical.

A schema migration never destructively rewrites original evidence. A cached report index is rebuildable. Contributors without instruments can run the full mock pipeline and report tests.

After implementation, keep this README's quick-start/status accurate. Detailed design sections may move into linked repository documentation without discarding their acceptance requirements.

## 17. Decisions still requiring bench confirmation

These do not block mock development. Resolve the safety-critical subset before real operation and expose missing items clearly in the UI.

| Item | Required evidence or decision |
|---|---|
| Existing driver integration | Actual repository/module/API, supported transports, timeout behavior, connection side effects |
| Exact equipment | Physical source/load model labels, firmware, reported identities, modifications, usable ratings and ranges |
| First DUT sample | Label/photo, wire functions/polarity, sample ID, user-confirmed normal range and output claim |
| Wiring and grounding | Sense points, pigtail boundary, protective wiring/disconnect, grounding/isolation implications |
| Protective policy | Approved current limit, voltage protection, applicable thermal limit or supervised-only restriction, startup/stop behavior |
| Acquisition capability | Freshness, polling/update rates, timing skew, queried voltage/power meaning, status observability |
| Acceptance requirements | Actual output tolerance or efficiency/temperature limits, if pass/fail is desired |
| Measurement qualification | Applicable instrument specifications/calibration; whether any external meter is available |
| Optional temperature | Logger, sensor type, placement, ambient channel, attachment and electrical compatibility |
| Publication | Repository/license, approved examples, real public URL, private-data handling |

Do not demand answers to every future feature before implementing M0/M1. Do not energize equipment merely because the mock demonstration passed.

## 18. Sources and reference artifacts

### Project reference files

When supplied alongside this README, inspect these as design references and regression fixtures:

- `SB60-A_characterization_report.html`: document layout, point data, plot controls, sensor map, and known consistency/export problems.
- `SB60_A_vs_B_comparison_report.html`: shared-color overlays, difference plots, paired-condition presentation, and known uncertainty/interpretation problems.
- `SB60-A_characterization_report.pdf`: document structure and examples of rasterized plots/pagination problems.
- Earlier A/B/C example reports, if available: alternative presentation and documentation-editing ideas, not validated hardware results.
- The colleague's proposal, if available: architecture rationale. Its blanket four-DMM requirement, simplified accuracy claims, never-store-derived-data rule, and automatic-publication proposal were not adopted.

These files may be absent in a fresh checkout. This README contains the necessary implementation requirements and regression values; do not invent missing artifacts or assume the original generator is available.

### External references

Links below document specific capabilities or metrology principles. Project architecture, thresholds marked as draft, and implementation choices are proposed requirements, not quotations from these sources. Consult the applicable revision and exact hardware when implementing a driver or uncertainty model.

- **R1. Rigol DP800 datasheet:** channel ratings and model-specific readback specifications. https://www.rigol.com/dam/global/downloads/brochures/en/data-sheet/dc-powers/DP800_DataSheet_EN.pdf
- **R2. Rigol DP800 user guide:** sense support and operating procedures, especially CH2 sense. https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/dc-powers/DP800_UserGuide_EN.pdf
- **R3. Rigol DL3000 user guide:** remote-sense wiring and mode; see printed page 2-85 and its polarity diagram. https://www.rigol.com/dam/global/downloads/brochures/en/user-manual/dc-load/DL3000_UserGuide_EN.pdf
- **R4. Rigol DL3000 datasheet:** distinguish control/programming specifications from readback specifications. https://www.rigol.com/dam/global/downloads/brochures/en/data-sheet/dc-load/DL3000_DataSheet_EN.pdf
- **R5. Plotly interactive HTML export:** https://plotly.com/python/interactive-html-export/
- **R6. Plotly static image export:** formats and rendering dependencies. https://plotly.com/python/static-image-export/
- **R7. Quarto Typst output:** https://quarto.org/docs/output-formats/typst.html
- **R8. Quarto HTML basics:** standalone resources and HTML output. https://quarto.org/docs/output-formats/html-basics.html
- **R9. Quarto cross-references:** https://quarto.org/docs/authoring/cross-references
- **R10. NIST TN 1297, Type B evaluation:** https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-4-type-b-evaluation-standard-uncertainty
- **R11. NIST TN 1297, combined standard uncertainty:** https://www.nist.gov/pml/nist-technical-note-1297/nist-tn-1297-5-combined-standard-uncertainty
- **R12. GitHub Pages:** https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- **R13. Google Search, control what you share:** https://developers.google.com/search/docs/crawling-indexing/control-what-you-share
- **R14. EPC90120 quick start guide, visual reference:** https://epc-co.com/epc/Portals/0/epc/documents/guides/EPC90120_qsg.pdf

---

## First instruction to execute

**Implement M0, then the M1 mock-to-report vertical slice. Reuse existing drivers and report source if actually provided, keep the first real DUT profile separate from synthetic fixtures, and turn the listed review defects into regression tests. Do not operate real hardware or publish files. Finish each increment with commands run, test evidence, artifacts produced, known limitations, and the next bounded task.**
