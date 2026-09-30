# Glossary

Words the bench page, the reports and the guides use before they define them.
Each entry says where the term comes from in the code or the evidence, so a
definition here can be checked rather than believed. The bench page links this
file from its footer (**Glossary**); the two READMEs link it at their first use
of *path efficiency* and *qualified*, the [getting-started guide](getting-started.md)
from section 1 and section 4.6, and [bench-ui.md](bench-ui.md) where it
describes the footer.

## Measurement words

| Term | Meaning | Where it comes from |
| --- | --- | --- |
| **DUT** | Device under test: the converter being characterized. | Guide §1; `profiles/dut/`. |
| **Path efficiency** | Output power ÷ input power with both measured at the *instrument* terminals: `Vin`/`Iin` at the supply output, `Vout`/`Iout` at the load input. The losses in both pairs of leads are inside the number, so it is not converter-terminal efficiency. | `analysis.py`; the run's `measurement_boundary`; [engineering-figure-labels.md](engineering-figure-labels.md). |
| **Measurement boundary** | The span the four readings cover: from the supply terminals to the converter output as seen by the load. Names what the efficiency figure includes. The text is the bench profile's `measurement_boundary`: the shipped mock profile spells it out as "source-to-load-terminal path (input and output wiring included; load in local sense)"; `domain.py`'s default for a profile that gives none is the older "source-to-DUT-output path", which `profiles/bench/mock-remote-sense.yaml` still carries. | `measurement_boundary` in the bench profile; `domain.py`; the report's *Setup and method*. |
| **Qualified / qualification** | Whether a point's readings met the settling and acquisition policy (fresh, complete cycles acquired after electrical settling) and may carry a nominal efficiency claim. Values seen: `valid`, `inconclusive`, `setup-limited`, `not-run`, `unsupported`. Live readings on the page are *unqualified*; the report applies qualification. | `analysis.py`; the CSV column `qualification`. |
| **Uncertainty unquantified** | No readback uncertainty budget was evaluated because the bench profile's `readback_specification` terms are `unknown`. Displayed digits are analysis precision, not accuracy. | [uncertainty-budget.md](uncertainty-budget.md). |
| **k = 2, expanded uncertainty, specification-bound** | Metrology terms: a coverage factor of 2 applied to a budget built only from declared instrument specifications (no calibration data). In the simulation the specifications are *examples* written into the mock bench profile. | `uncertainty.py`; `profiles/bench/mock.yaml` (`status: synthetic_example`). |
| **Enabled with no external load** | The input consumption recorded at a requested 0 A load with the converter powered and the load input OFF. It is not the controller's quiescent current, and no efficiency is computed at 0 A. On the real bench this observation is not yet qualified. | `runner.py`; [configured-runs.md](configured-runs.md). |
| **Local vs remote sense** | Whether the load measures voltage at its own terminals (local) or through separate sense leads at the DUT (remote). Both the real bench and the shipped mock profile (`profiles/bench/mock.yaml`, `remote_sense_required: false`) use local sensing; `profiles/bench/mock-remote-sense.yaml` is the variant that exercises the remote-sense branch. | Guide §5.3; the bench profile's `remote_sense_required`. |
| **Freshness** | Whether an instrument's readback reflects a new conversion rather than a repeated value. Unquantified on the real bench until measured. | [m2-freshness-and-readback-evidence.md](m2-freshness-and-readback-evidence.md). |
| **Phase / window / cycle** | Phase: one input-voltage condition (a cold start each). Window: the acquisition interval for one load point. Cycle: one complete set of the four readings within a window. | `runner.py`; `raw/samples.jsonl`. |

## Planning words (the same on the page, in the CLI and in the saved plan)

| Term | Meaning | Where it comes from |
| --- | --- | --- |
| `executable` | The requested point will run. | `planning.py`; `PlannedPoint.status`. |
| `assumption_limited` | Kept in the plan but skipped: the **planning budget** (assumed efficiency × share of the supply current) says the supply cannot feed the point. The request is *not reduced to fit* ("retained without clipping"). | `planning.py`. |
| `approval_blocked` | Kept in the plan but skipped until the saved approvals are true (the converter's two approvals and the bench limits' approval; for a below-minimum profile, the recipe's `authorization.uvlo_approved`). | `planning.py`; `missing_approvals`. |
| `unsupported` | Kept in the plan but skipped: outside what this bench or its backend can do (envelope, guard, procedure not implemented). The report labels every skipped point `unsupported` in its appendix, with the planner's reason. | `planning.py`; `real_backend.prepare_real_plan`. |
| **Planning budget** | Assumed efficiency (default 80 %) and share of the source's current limit (default 90 %) used to decide which requested loads a 1 A supply can feed. A planning assumption, never a measurement. | `planning.efficiency_estimate_fraction`, `planning.source_current_budget_fraction` in the recipe. |
| **Approvals (the three)** | Saved booleans: DUT `execution_approval.real_hardware_enabled`, DUT `execution_approval.wiring_and_polarity_confirmed`, bench `protective_controls.approved`. Necessary before a real preview is supported; not sufficient for Start, which also needs a fresh physical confirmation. | Guide §5.5; `domain.py`. |
| **Arm / `--arm`** | The operator action that lets a fixed real procedure energize the bench; refused by the generic CLI. The page's equivalent is **Switch on and start** after the confirmation. | `cli.py`; the fixed procedures. |

## Workflow words

| Term | Meaning | Where it comes from |
| --- | --- | --- |
| **Simulation** ("mock" bench) | The synthetic converter, source and load: a deterministic software model on a virtual clock. It touches no instrument and labels every output SYNTHETIC. It cannot measure your converter or prove anything about safety. | The Simulation tile; `adapters.py`, `runner.run_mock`. |
| **SYNTHETIC / MEASURED** (evidence label) | The `evidence_type` of a whole run: SYNTHETIC when the values come from the plant model, MEASURED when they come from instruments. Shown in the report subtitle, every figure caption, the CSV column `evidence_type` and `points.meta.json`. | `analysis.py`; the report model. |
| **Virtual clock / timing basis: virtual** | The simulation advances model time instead of waiting; its "durations" are not wall-clock. Acquisition therefore takes seconds; rendering the report takes real minutes. | `runner.py`; the report's *Acquisition method*. |
| **Profile** | One of the saved inputs: DUT (converter ratings), bench (equipment envelope and protective limits), recipe (the grid of input voltages × loads and timing), report (styling). Data, not Python. | `domain.py`; `workspace/profiles/`. |
| **Preset** | A saved bench profile with `mode: real`; the pills under the Real bench tile. | The bench page. |
| **Inventory** | The private `Software/config/lab.yaml`: instrument addresses and expected serials. Needed only for the real bench; never published. | Guide §5.4. |
| **Job / run / analysis / report revision** | A *job* is one press of Start (`workspace/jobs/<job_id>/`). It holds one *run* (the immutable evidence, `runs/<run_id>/`). A run can have several *analyses* (one per formula version) and several *report revisions* (`r0001`, `r0002`, …, one per render). | `job_service.py`; `storage.py`; `services.py`. |
| **Revision** | A new render of the same evidence (**Regenerate report** on the page). Never a change to the evidence. | `retry_report`. |
| **Worker** | The separate process that owns the instruments (or the synthetic plant) for one job. The page only watches it; closing the browser does not stop it. | `job_service.worker`. |
| **Lease** (bench activity lock) | A file lock (`dcdc-bench/runs/.bench-activity.lock`, or `DCDC_ACTIVITY_LOCK`) so only one acquisition or render runs at a time. "Waiting for the bench" on the page means it is held. | `activity.py`. |
| **Memory gate** | The refusal to start a render when the computer has less than 150 MiB available, or less than 600 MiB available plus free swap (defaults; `DCDC_RENDER_MIN_AVAILABLE_MIB`, `DCDC_RENDER_MIN_AVAILABLE_PLUS_SWAP_FREE_MIB`). The page shows it as "Waiting for free memory: 96 MiB available, 150 MiB needed". | `resources.MemoryGate`; [pi-process-model.md](pi-process-model.md). |
| `report-queued` | The job state after acquisition: measurements saved, both outputs verified OFF, the render not yet started. The page shows **Measurements saved — report queued** and, when held back, why. A new test may start while reports are queued. | `job_service.REPORT_QUEUED`. |
| **Doctor** | The read-only instrument check (`*IDN?`, output states, protections, error queue). Exit 0 clean, 4 findings, 2 refused. | `doctor.py`; [doctor-and-publication.md](doctor-and-publication.md). |
| **Agent-role review** | A review written by an automated agent in the authoring pipeline, not by a person. | [docs/README.md](README.md). |

## Milestones M0–M5

From [implementation-brief.md §15](implementation-brief.md#15-implementation-milestones); the status pages quote them by code.

| Code | Milestone | Exit criterion (short) |
| --- | --- | --- |
| **M0** | Audit and contracts: typed profile and result schemas, first DUT and mock bench profiles, the feasible-point planner, core constraint tests. | The full request can be represented and validated without hidden constants. |
| **M1** | Complete mock-to-report path: mock adapters, worker lifecycle, streaming evidence, deterministic analysis, one report template, standalone HTML and matching PDF. | One demo command works without hardware. |
| **M2** | Supervised real point: adapted drivers validated, the bench protective profile complete, the approved no-load / 24 V / 0.1 A bring-up after explicit authorization. | Saved measurements agree with the observed bench; provenance complete; the stop procedure demonstrated. |
| **M3** | Partial-power sweep and simple UI: the approved small grid, setup limits distinguished from DUT behaviour, reports without manual copying, profile and recipe forms, progress, report access. | An engineer can repeat a qualified limited-power run from the UI; a new DUT needs no source edits. |
| **M4** | Comparisons and thermal extension: paired-run comparison, difference plots, photo and sensor annotation, temperature adapters, thermal settling. | Comparison and temperature claims pass their evidence checks; adding an image never reruns instruments. |
| **M5** | Expanded capability: full-power source profile, reviewed uncertainty improvements, the approved UVLO recipe, scope captures, richer imports, approved public examples. | Only after the earlier path is dependable. |
