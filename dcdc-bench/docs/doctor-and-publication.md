# Doctor, readback-cadence probe and publication gate

Three operator commands added on the hardening branch. All three were
developed and tested against fake SCPI sessions only; **nothing in this
document was verified on the physical DP821A/DL3031A pair in this session.**
Statements about instrument behaviour below are read from the drivers'
source, the existing supervised procedures and the IEEE 488.2 standard, and
are labelled where they still need bench confirmation.

```bash
dcdc-bench doctor --bench profiles/bench/<real>.yaml --inventory <private lab.yaml> [--out diagnostics/x.json]
dcdc-bench doctor --bench ... --inventory ... --readback-cadence --seconds 10 [--poll-interval 0.05]
dcdc-bench publish runs/<run_id> --revision r0002 --out public/ --approval approval.yaml
```

Exit codes: `0` no findings; `4` diagnosis completed with findings (including
an unapproved profile); `2` refused (mock profile, wrong adapters, bad
inventory, outputs not verified OFF for the cadence probe, publication
refused). `compare` remains reserved.

## 1. `doctor` (brief 7.2)

### What it reads

The doctor opens both configured instruments (`psu_rigol_1`, `load_rigol_1`
in the private benchctl inventory) through the existing `VisaTransport` and
drivers, wrapped in `ReadOnlyTransport`, and reads:

| Role | Read via | Queries |
| --- | --- | --- |
| both | `identify()` | `*IDN?` |
| both | status byte | `*STB?` (bit 2 reported as `error_queue_nonempty`) |
| source | `get_output_enabled(1/2)` | `:OUTP? CH1`, `:OUTP? CH2` |
| source | `get_voltage_setpoint`, `get_current_limit` | `:SOUR1:VOLT?`, `:SOUR1:CURR?` |
| source | protection extensions (same strings as `bringup.RigolPilot`) | `:OUTP:OVP? CH1`, `:OUTP:OVP:VAL? CH1`, `:OUTP:OVP:QUES? CH1`, same for `OCP`, `:SYST:OTP?` |
| source | timers used by the extended procedure | `:TIMER?`, `:DELAY?`, `:INST:NSEL?`, `:OUTP:CVCC? CH1` |
| source | `measure_voltage/current(1)` | `:MEAS:VOLT? CH1`, `:MEAS:CURR? CH1` |
| load | `get_input_enabled`, `get_mode`, `get_current_setpoint` | `:SOUR:INP:STAT?`, `:SOUR:FUNC?`, `:SOUR:CURR:LEV:IMM?` |
| load | limits, sense, condition (same strings as `RigolPilot`) | `:SOUR:CURR:VLIM?`, `:SOUR:CURR:ILIM?`, `:SOUR:SENS?`, `:SOUR:FUNC:MODE?`, `:STAT:QUES:COND?` |
| load | `measure_voltage/current` | `:MEAS:VOLT?`, `:MEAS:CURR?` |

It then compares: reported serial against the inventory `expected_serial`
(blocking finding if missing or different); reported model/firmware/identity
against `physical_model`, `firmware`, `reported_identity` in the bench profile
when those are set; OVP value against `protective_controls.dut_input_overvoltage_V`;
load VLIM/ILIM against `dut_output_overvoltage_V`/`output_overcurrent_A`;
load sense against `load.remote_sense_required`. Enabled outputs, tripped
protection alarms (`QUES?` not `NO`), OTP disabled, timer/delayer not OFF,
fault bits in the load condition register and a non-empty error queue are
findings. A profile with `protective_controls.approved: false` is a blocking
finding: the doctor still reads, exits `4`, and real execution stays blocked.

The diagnosis JSON (default `dcdc-bench/diagnostics/doctor-<utc>.json`, or
`DCDC_DIAGNOSTICS_DIR`) contains every raw response, a per-query transcript
with monotonic start/end times, the profile/inventory hashes, the software
provenance and the query allowlist that was in force. It is a **local,
private diagnostic**: it contains endpoints and serials and is not an export.

### What it never does

- No `write()` at all: `ReadOnlyTransport.write` raises `DoctorRefusal`.
- No query outside `doctor.READ_ONLY_QUERIES`; the driver's state-changing
  methods (`output_on/off`, `input_on/off`, `set_*`, `all_outputs_off`) are
  never called, so no output-enable, setpoint or protection write can occur.
- No `*RST`, `*CLS`, `*ESR?`, `*TST?`, `*RCL`, `*SAV`, `*TRG`.
- No `SYST:ERR?`: that query removes the entry it returns, which is exactly
  the fault evidence 7.2 says a doctor must not clear. Only the `*STB?`
  error-available bit is reported; the queue stays on the instrument for the
  operator. `*STB?` is the one query not previously used on this bench; its
  bit-2 meaning follows IEEE 488.2 and **is not yet bench-verified** (the
  doctor records the raw value either way, and a failed read is a finding,
  not an abort).
- It does not take the `bench_activity` lease; ownership is enforced by the
  transport's per-instrument `flock`, so the doctor fails closed with
  `DeviceLockError` while an acquisition owns an instrument.
- It never turns anything off, even when it finds an output ON.

`tests/test_doctor.py` runs the real `RigolDP800`/`RigolDL3000` drivers over
a fake session that raises on any `write`, and asserts the transcript is a
subset of the allowlist, every command is a query, forbidden tokens are
absent, and `check_errors` (the error-queue drain) is never invoked.

### Driver connection side effects (from source, not from prose)

| Where | Effect |
| --- | --- |
| `Software/src/benchctl/transport.py:69-84` `VisaTransport.open` | Takes an exclusive `flock` on `/tmp/benchctl-<resource>.lock` (`:63`, `:138-148`), opens the pyvisa resource and sets `session.timeout` (`:77-79`). **No SCPI is sent.** Link creation by pyvisa-py is protocol-level; not bench-verified here. |
| `transport.py:86-92` `close` | Closes the session, releases the lock. No SCPI. |
| `transport.py:159-180` `_log` | Appends every command to a JSONL file (default `Data/Logs/commands.jsonl`; the doctor passes `diagnostics/doctor-<utc>.scpi.jsonl`). Filesystem side effect only. |
| `drivers/rigol_dp800.py:60-61`, `drivers/rigol_dl3000.py:77-78` | Constructors store the transport; no commands. |
| `rigol_dp800.py:65-66`, `rigol_dl3000.py:82-83` `identify` | `*IDN?` only. |
| `rigol_dp800.py:68-96`, `rigol_dl3000.py:85-119` read-only methods | Single queries; none drains the error queue. |
| `interfaces.py:77-94` `drain_scpi_errors` | Loops `SYST:ERR?` until code 0: **removes queued errors**. Called by `check_errors` (`rigol_dp800.py:98-100`, `rigol_dl3000.py:121-123`) and by every state-changing method (`rigol_dp800.py:109,146,165,182,188`; `rigol_dl3000.py:140,155,166,182,187`). The doctor calls none of these. |
| `identity.py:47-53` `identify_and_verify` | `identify()` then a pure serial comparison. |
| `dcdc_bench/bringup.py:325-338`, `extended.py:288-298` | The **acquisition** connect path is not read-only: right after identity it issues `load.input_off()` and `supply.output_off(1)` (writes plus error-queue drains). The doctor therefore has its own connect path and does not reuse `_run_bringup_unlocked`/`_run_fixed_unlocked`. |
| grep of `Software/src/benchctl` | No `*RST`, `*CLS` or VISA `clear()` anywhere. |

## 2. Readback-cadence probe (`--readback-cadence`, M2 freshness)

Runs only after the doctor snapshot has read `:OUTP? CH1`, `:OUTP? CH2` and
`:SOUR:INP:STAT?` as OFF. If any is ON or unreadable the probe is **refused**
(`cadence.status = "refused"`, exit `2`) and nothing is turned off. It then
polls the four measure queries (`Vin_V`, `Iin_A`, `Vout_V`, `Iout_A`) for
`--seconds` (1–120) with `--poll-interval` (0.01–5 s) between rounds,
recording per-query monotonic start/end and the raw response.

Per channel it reports `query_count`, median/min/max query latency,
`distinct_value_change_count`, the list of intervals between consecutive
distinct-value changes (change time = query midpoint), their median/min/max,
and `estimated_readback_update_period_s` = median change interval (needs at
least three distinct consecutive values; otherwise `estimate_status` says
"not observable" — with outputs OFF a reading may not change at all).

How to interpret it: the estimate is an **outputs-OFF cadence observation of
the readback path** — how often the value returned over SCPI changes while
the instrument idles. It is **not** a loaded-measurement freshness
qualification, **not** an ADC update-rate specification and not an accuracy
statement. A change interval bounds the update period only if the underlying
reading changes between updates (identical consecutive updates are invisible),
and the resolution is limited by poll interval plus latency. The JSON carries
this statement verbatim. M2 freshness qualification still needs a loaded,
supervised observation with an independent stimulus; this probe only
establishes what the idle readback path does, which is the prerequisite
"independent readback timing, not query spans" measurement.

Diagnostics are written under `diagnostics/` (never inside a run folder;
`diagnostics_dir()` refuses any path whose parents contain `run.json` or
`integrity.json`). `diagnostics/` is git-ignored.

## 3. Publication gate (`publish`, brief 16, PUB-01)

### The approval record

Publication happens only with an approval file; a completed run folder never
publishes anything, and the CLI exits `2` without one.

```yaml
schema_version: "1.0"
run_id: 20260927T093948.075493Z_real_42e971   # must equal run.json run_id
report_revision: r0002                         # must equal --revision
approver: "J. Reviewer"                        # free text, not blank
date: 2026-09-27                               # calendar date
public: false                                  # true removes noindex; explicit choice
attachments: [board-photo]                     # allowlist of attachments/manifest.json asset IDs
keep_serials: false                            # true keeps instrument serials
include_pdf: false                             # true copies report.pdf verbatim (cannot be text-redacted)
statement: "Optional approval text"
```

Unknown keys, a non-boolean `public`, a blank approver, an invalid date, a
mismatched run ID/revision, or an allowlisted attachment ID that is not in
the run are refusals. The copy is written to `<out>/<run_id>/<revision>/`,
never inside the run folder, and never over an existing copy.

### What redaction does

From `reports/<revision>/` it copies, as text with redaction: `report.html`,
`report_model.json`, `build_manifest.json`, `annotations.json`,
`report_profile.json`, `report.css`, `exports/*` and `figures/*.svg`.
Redaction removes, in order: whole VISA resource strings; exact known values
(endpoints and hostnames parsed from `scpi.jsonl` and profile `endpoint`
fields, serials from `run.json` identities and `*IDN?` responses, the run
folder's own path); private/link-local/loopback IPv4 with strict octets;
`.local/.lan/.home/.internal` hostnames; `/home /Users /root /mnt /media /srv`
and Windows drive paths. Replacements are `[REDACTED:<category>]`. JSON files
are walked field by field so numbers are untouched.

Not published: `raw/`, `scpi.jsonl`, `request.json`, `plan.json`, `run.json`,
`analysis/`, render intermediates and logs, binary figures, `report.pdf`
unless `include_pdf`, and any attachment not on the allowlist. Allowlisted
attachments are copied verbatim after their `sha256` is re-checked against
the run's attachment manifest; a mismatch is a refusal.

`publication_manifest.json` records the approval (and its hash), the sha256
of every source file read and of every published file, the run's
`integrity.json` verbatim, redaction totals per category, per-file counts and
the **field names** where JSON values were redacted (never the values), the
excluded files/attachment IDs with reasons, and an explicit `completeness`
statement that the copy is not complete raw evidence. The HTML gets a
`dcdc-publication` meta tag and a visible notice saying the same.

### What redaction does not guarantee

- `noindex` is retained by default and removed only for `public: true`.
  **`noindex` is not access control**: a robots tag asks crawlers not to
  index; anything confidential needs an access-controlled destination, not a
  publicly reachable file.
- Public IPv4 addresses and arbitrary hostnames are not pattern-redacted (a
  generic IPv4 pattern would corrupt numeric evidence such as
  `003.371.214.673` in report tables). Put every instrument endpoint in the
  inventory/transcript so it is removed by exact match, and review the copy.
- Free text written by an operator (notes, captions) is only redacted where
  it matches the patterns above. Review it.
- Binary files (`report.pdf`, images) cannot be text-redacted; they are
  included only by explicit approval and flagged in the manifest.
- The tool never invokes `git`, `gh`, a browser or the network
  (`tests/test_publish.py` monkeypatches `subprocess`, `os.system` and
  `socket` to fail). Hosting is a separate, human step; no push is
  authorised by producing a copy.
- The source run folder is opened read-only; the tests hash the tree before
  and after and re-run `verify_integrity`.

## Tests executed

```
PYTHONPATH=dcdc-bench/src:Software/src flock .../agent-pytest.lock .venv/bin/python -m pytest \
  dcdc-bench/tests/test_doctor.py dcdc-bench/tests/test_publish.py -q -p no:cacheprovider
```

Fake SCPI only; no instrument was connected, no `dcdc-bench ui` or `demo`
was run, and nothing under `dcdc-bench/runs/` was modified.
