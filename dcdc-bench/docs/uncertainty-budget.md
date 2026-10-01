# Readback uncertainty budget

This document explains the structured measurement-uncertainty budget that the
analysis writes to `analysis/<analysis_id>/uncertainty.json` for every analysis
revision (implementation brief, section 9.2). It covers each profile field, the
formulas, what the bench owner must enter before a real bench produces a
number, and what stays unquantified even after that.

The evaluator lives in `src/dcdc_bench/uncertainty.py`. It never opens an
instrument and never reads a programming (setting) accuracy.

## What the budget does and does not claim

- Unknown inputs never become a numerical zero. If any required term for a
  quantity is unknown, that quantity is `not_evaluated` with a reason list.
- Standard uncertainty, expanded uncertainty, error limits and repeatability
  are kept distinct and stored separately.
- Expanded uncertainty is `U = k * u_c`. `k` is recorded (default 2) and is
  **not** described as a validated 95 % confidence interval: effective degrees
  of freedom and distribution shape are not evaluated.
- Efficiency uncertainty is expressed in **percentage points**, for example
  `92.6% ± 0.4 percentage points`. Loss uncertainty is in watts and has its
  own propagation; the efficiency number is never rescaled into watts.
- A report shows shaded bands, `±` text and a metric uncertainty only for
  quantities whose status is `evaluated` (UNC-02, WEB-03).
- A `synthetic_example` specification is accepted only on a mock bench. On a
  real bench or for MEASURED evidence the evaluator refuses it.

## Profile fields

Each measurement channel in a `BenchProfile` (`measurements.Vin_V`,
`Iin_A`, `Vout_V`, `Iout_A`) carries an optional `readback_specification`.
Percent terms are in **percent** exactly as printed in a datasheet: `0.05`
means 0.05 %, not a fraction.

| Field | Meaning | Required for evaluation |
|---|---|---|
| `role` | Always `readback`. Programming accuracy lives in the separate `programming_accuracy` field and is never consumed here (CORE-06). | fixed |
| `status` | Provenance: `unknown`, `unverified_user_entry`, `datasheet_quoted`, `calibrated`, `synthetic_example`. | must not be `unknown` |
| `source` | Document title, URL and page/table, certificate number, or `unknown`. Required for `datasheet_quoted` and `calibrated`. | yes for quoted/calibrated |
| `source_candidates` | Documents to consult while the entry is still unknown (the R1/R4 datasheet URLs from the brief). | no |
| `unit` | Must equal the bound channel unit (`V` or `A`). | no (checked when set) |
| `percent_of_reading` | Reading-proportional error limit in percent. Enter `0` explicitly if the datasheet has none. | yes |
| `percent_of_range` | Range- or full-scale-proportional error limit in percent. Enter `0` explicitly if none. | yes |
| `range_value` | The actual readback range or full scale in the channel unit, used with `percent_of_range`. | yes when `percent_of_range` > 0 |
| `absolute_offset` | Fixed error limit in the channel unit (for example `0.0001` A for 0.1 mA). Enter `0` if none. | yes |
| `resolution` | Readback resolution in the channel unit (display digits are not accuracy). Enter `0` only if the datasheet resolution is genuinely below every other term and you record why. | yes |
| `temperature_coefficient` | Optional drift term: `percent_of_reading_per_C`, `percent_of_range_per_C`, `absolute_per_C`, `reference_temperature_C`, `reference_band_C`, `source`. Applied per degree beyond the reference band; needs an observed ambient temperature (`run.json: ambient_temperature_C`), otherwise the channel is `not_evaluated`. | optional |
| `calibration.status` | `unknown`, `factory_only`, `within_interval`, `overdue`. Datasheet terms are conditional on the calibration interval, so `unknown` and `overdue` block evaluation. | must not be `unknown`/`overdue` |
| `calibration.last_calibration_date`, `interval_months`, `certificate`, `note` | Declared record. Software never verifies or invents a certificate. `calibrated` status requires `within_interval` and a certificate. | no |
| `applicable_conditions` | Free text: temperature band, warm-up, time since calibration, range selection the specification applies to. | no |
| `distribution` | `rectangular` (the only supported model). | fixed |
| `distribution_justification` | Why the limit is treated as a rectangular bound. | no |

Bench-level fields:

| Field | Meaning |
|---|---|
| `uncertainty_policy.coverage_factor` | `k` used for every expanded uncertainty (default 2). |
| `uncertainty_policy.coverage_factor_note` | Recorded verbatim in the budget; states that `k = 2` is not a validated 95 % interval. |
| `uncertainty_policy.linear_model_relative_uncertainty_bound` | If any channel's relative standard uncertainty exceeds this (default 0.1), efficiency is flagged `insufficient resolution / linear approximation questionable` and no symmetric interval is reported for it. Products (Pin, Pout, loss) carry the flag as information. |
| `uncertainty_policy.include_repeatability_in_combined` | Whether the Type A term enters `u_c` (default true). It is recorded separately either way. |
| `readback_correlations` | Declared correlations between channels' systematic errors: `quantity_a`, `quantity_b`, `coefficient` in [-1, 1], `justification`. When empty, independence is assumed and recorded. |

Schema rules that reject inconsistent entries: an `unknown` specification
cannot carry numbers; a quoted or calibrated one must cite a source; a
synthetic one must say "synthetic" in its source; `percent_of_range` needs
`range_value`; the unit must match the bound channel. Correlation pairs must
be unique and the complete correlation matrix must be positive semidefinite;
coefficients individually inside [-1, 1] are not sufficient.

## Formulas

Per channel mean `x̄` (the accepted-window mean the analysis already uses):

```text
a_spec   = |x̄| * percent_of_reading/100 + range_value * percent_of_range/100 + absolute_offset
u_spec   = a_spec / sqrt(3)                 # rectangular error limit [R10]
u_res    = (resolution / 2) / sqrt(3)       # rectangular quantization half-width
excess   = max(0, |T_ambient - T_ref| - band)
a_temp   = excess * (|x̄| * pct_rd_per_C/100 + range_value * pct_rg_per_C/100 + abs_per_C)
u_temp   = a_temp / sqrt(3)                 # 0 when no coefficient is declared
u_B      = sqrt(u_spec² + u_res² + u_temp²) # systematic; never divided by n (UNC-04)
u_A      = s / sqrt(n)                      # repeatability of the n accepted readings, recorded separately
u_c(x̄)  = sqrt(u_B² + u_A²)                # u_A included only per policy
```

Derived quantities use the declared model with first-order sensitivity
coefficients `c_i` and the declared systematic covariance
`u(x_i, x_j) = r_ij u_Bi u_Bj` for different channels
[R11]:

```text
u_c² = Σ_i Σ_j c_i c_j u(x_i, x_j)
u(x_i, x_i) = u_c(x̄_i)²       # total channel variance on the diagonal
u(x_i, x_j) = r_ij*u_Bi*u_Bj   # systematic covariance; i != j

Pin  = Vin*Iin                  c = {Vin: Iin, Iin: Vin}
Pout = Vout*Iout                c = {Vout: Iout, Iout: Vout}
eta  = 100*Vout*Iout/(Vin*Iin)  c = {Vout: 100*Iout/Pin, Iout: 100*Vout/Pin,
                                     Vin: -eta/Vin,       Iin: -eta/Iin}      # percentage points
loss = Vin*Iin - Vout*Iout      c = {Vin: Iin, Iin: Vin, Vout: -Iout, Iout: -Vout}  # watts
U    = k * u_c
```

Repeatability remains independent between channels in this model. A shared
systematic error cannot cancel its contribution. A materially negative
propagated variance is rejected rather than reported as zero.

Independence (`r_ij = 0`) is recorded as an assumption whenever no
correlation is declared. `difference_uncertainty(a, b, correlation=r)` gives
`sqrt(u_a² + u_b² - 2 r u_a u_b)` for comparisons (UNC-03).

The UNC-01 regression fixture (eta = 40.24 %, Iin = 7.8 mA with
0.05 % + 0.1 mA, Iout = 30 mA with 0.10 % + 0.6 mA, voltage terms deliberately
zero) reproduces `U_eta = 1.155512754` percentage points through this
evaluator. That fixture is a calculation check, not the first DUT's budget.

## Output: `uncertainty.json`

```text
schema_version        "uncertainty-budget-1.0"
method_version        "readback-budget-1.1"
status                evaluated | partially_evaluated | not_evaluated
metrology             quantified uncertainty | specification-bound only[ (…)] | unquantified
coverage_factor, coverage_factor_note, policy
measurement_model     the formulas above
channels              per-channel review: evaluable, reasons, status, source, specification,
                      programming_accuracy_consulted (always false)
correlations          declared list and independence_assumed
systematic_terms      statement that systematic terms are not divided by n
repeatability         how Type A is recorded/combined
unquantified_aspects  see below
reasons               run-level reasons when not evaluated
points.<point_id>     status, metrology, reasons,
                      channels.<q>: terms, systematic_standard, repeatability, standard,
                                    relative_standard, expanded, lower, upper, label
                      quantities.<name>: value, unit, standard, expanded, k, lower, upper,
                                    label, sensitivity_coefficients, independence_assumed,
                                    model, flags   — or status not_evaluated with reasons
```

The per-point `metrology` follows the weakest specification status among the
four channels: `calibrated` → `quantified uncertainty`; `datasheet_quoted` →
`specification-bound only`; `unverified_user_entry` and `synthetic_example`
say so in parentheses; anything not evaluable → `unquantified`. The same
string is written into each analysis point's `metrology` field.

## What the bench owner must fill in for the real bench

`profiles/bench/rigol.example.yaml`, the seeded UI profile
`rigol-local-limited`, and the fixed supervised procedures all carry
`status: unknown` with `source_candidates` pointing to the R1 (DP800) and R4
(DL3000) datasheets. Nothing numeric is pre-filled. For each of the four
channels:

1. Identify the exact instrument model, firmware and the readback range the
   channel actually uses at the tested operating points.
2. From the **readback / measurement** specification table (not the
   programming or setting accuracy, see brief section 3.3 and R4), transcribe
   `percent_of_reading`, `percent_of_range` with its `range_value`,
   `absolute_offset` and `resolution`. Enter `0` explicitly where a term does
   not exist.
3. Set `status: datasheet_quoted` (or `calibrated` with a certificate) and
   `source` to the document title, revision, URL and page or table.
4. Record `calibration.status` (`factory_only`, `within_interval` or
   `overdue`), the date, interval and certificate if any. `unknown` keeps the
   budget `not_evaluated`.
5. Note `applicable_conditions` (temperature band, warm-up) and, if you want
   drift budgeted, the `temperature_coefficient` plus an
   `ambient_temperature_C` entry in the run metadata.
6. Optionally declare `readback_correlations` with a justification when two
   channels share a reference or converter.

Until then every real-bench report states that the uncertainty is
unquantified and shows no bands.

## What remains unquantified even with a filled specification

- ADC conversion freshness and the independence of successive polled
  readbacks (whether two queries return two conversions) are not modeled.
- Calibration is a declared status only; no certificate or as-found data is
  verified by software, and drift within the interval is not budgeted beyond
  the datasheet terms.
- Lead and contact drops between the sense location and the declared boundary
  are not corrected or budgeted; the boundary label carries that limitation.
- Inter-channel timing is bounded by the accepted skew, not budgeted.
- A datasheet specification describes the instrument population, not this
  unit; the result is therefore "specification-bound only", not a calibrated
  measurement uncertainty.
