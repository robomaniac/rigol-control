# Instrument specifications transcribed from R1 and R4

Status: software-only transcription (M2 qualification plan §8 step 1; Gaps B and D). Both
documents were fetched on 2026-09-29 from the brief §18 URLs. WebFetch could not decode either
PDF, so each was downloaded and extracted with `pdftotext -layout` and read page by page. No
instrument was touched. Values are copied as printed; no term has been converted between roles
(programming vs readback), ranges or forms. Where a document does not state a term it is written
*not stated*, never estimated.

| Document | Revision code (last page) | PDF pages | Printed page number |
|---|---|---|---|
| R1 Rigol DP800 datasheet `DP800_DataSheet_EN.pdf` | DSH03108-1110-202505 | 12 | equals PDF page (pp. 2–11) |
| R4 Rigol DL3000 datasheet `DL3000_DataSheet_EN.pdf` | DSJ01109-1110 2025.11 | 9 | PDF page − 1 (pp. 1–7) |

Page references below are **printed** page numbers. Forms: `%rd + offset` = ±(percentage of
reading — R1's wording is "Output Percentage" — plus an absolute offset); `%rd + %FS` =
±(percentage of reading + percentage of full scale); `%set + fixed` = ±(percentage of setting +
fixed value), R4 Note[1] stating that the fixed value is calculated from full scale.

## Programming versus readback

R1 prints programming and readback accuracy as separate columns of one table (header p. 4,
DP821A row p. 5). R4 prints CC/CV **programmable** accuracy per programming range (p. 3) and
**readback** current and voltage accuracy in separate tables, each with a single range (p. 4).
Only the readback rows enter `measurements.*.accuracy` and `readback_specification`; the
programming rows enter `programming_accuracy` and are never consumed as readback uncertainty
(brief §3.3 and §9.2; `uncertainty.py` reads `readback_specification` only).

## Rigol DP821A, CH1 (R1)

| Term | Value | Unit | Form | Page | Conditions / remarks |
|---|---|---|---|---|---|
| Output rating CH1 | 0–60 V / 0–1 A | V, A | rating | 4 | "DC Output (0 °C to 40 °C)"; one range, no sub-range |
| OVP / OCP setting range CH1 | 1 mV–66 V / 0.1 mA–1.1 A | V, A | rating | 4 | protection setting limits, not an accuracy |
| Channel power | 60 W (60 V × 1 A, derived) | W | derived | 1 | p. 1 states only "60V/1A \|\| 8V/10A … total power up to 140W" |
| Readback accuracy, voltage | 0.1 % + 25 mV | V | %rd + offset | 5 | heading "Annual Accuracy[1] (25 °C ± 5 °C)"; Note[1] p. 6: acquired via calibration under 25 °C after 1-hour warm-up |
| Readback accuracy, current | 0.15 % + 10 mA | A | %rd + offset | 5 | same heading and note |
| Programming accuracy, voltage | 0.1 % + 25 mV | V | %rd + offset | 5 | same heading and note |
| Programming accuracy, current | 0.2 % + 10 mA | A | %rd + offset | 5 | same heading and note |
| Readback resolution | 1 mV / 0.1 mA | V, A | resolution | 5 | programming 1 mV / 0.1 mA; display 1 mV / 0.1 mA |
| Temperature coefficient per °C | 0.01 % + 3 mV; 0.02 % + 3 mA | V, A | %rd + offset per °C | 5 | R1 does not say whether it applies to output or readback; not entered as a readback term |
| Stability[3] (output, 8 h) | 0.02 % + 1 mV; 0.1 % + 1 mA | V, A | %rd + offset | 6 | output variation after 30-min warm-up at constant load and ambient; not a readback term |
| General condition | > 30 min operation; 0–40 °C | – | text | 4, 6 | "All the specifications are guaranteed when the instrument has been working for more than 30 minutes" |
| Calibration interval | implied 1 year ("Annual Accuracy") | – | heading | 4 | no explicit interval sentence |

## Rigol DL3031A (R4)

| Term | Value | Unit | Form | Page | Conditions / remarks |
|---|---|---|---|---|---|
| Input rating | 0–150 V / 0–60 A / 350 W | V, A, W | rating | 3 | "DC Input (0 °C~40 °C)"; repeated p. 1 and order table p. 6 |
| Minimum operating voltage (DC) | 1.3 V @ 60 A | V | rating | 3 | only the full-current figure is stated |
| CC programming ranges | 0–6 A and 0–60 A | A | ranges | 3 | which range `:SOUR:CURR:RANG MIN` selects is *not stated* in R4 |
| CC programming accuracy[1] | 0.05 % + 0.003 A (0–6 A); 0.05 % + 0.03 A (0–60 A) | A | %set + fixed (fixed = 0.05 % FS) | 3, 5 | Note[1]: measured after 30-second sinking at the programmed value |
| CC programming resolution | 1 mA | A | resolution | 3 | |
| CC temperature coefficient[2] | 100 ppm/°C | – | ppm/°C on gain and zero | 3, 5 | Note[2]: within 0–20 °C and 30–40 °C |
| Readback accuracy, current | ±(0.05 % + 0.05 % FS), range 0–60 A | A | %rd + %FS | 4 | single readback row; FS = 60 A, so the FS term is 30 mA; **no low readback range is documented** |
| Readback accuracy, voltage | ±(0.05 % + 0.02 % FS), range 0–150 V | V | %rd + %FS | 4 | single readback row; FS = 150 V, so the FS term is 30 mV |
| Readback resolution | 0.1 mA / 0.1 mV | A, V | resolution | 4 | p. 1 "Min. readback resolution: 0.1 mV, 0.1 mA"; p. 6 option "Readback Resolution HIRES-DL3", Note[1]: A models ship with software options installed. SCPI replies carry 1 µA / 1 µV digits; digits are not accuracy |
| Readback temperature coefficient[2] | 50 ppm/°C (current); 20 ppm/°C (voltage) | – | ppm/°C on gain and zero | 4, 5 | reference band 25 °C ± 5 °C |
| Stability[8] | ±(0.01 % + 10 mA); ±(0.01 % + 10 mV) | A, V | %rd + offset | 4 | 8 h after 30-min steady sinking; not a readback term |
| Current slew rate[7] | 0.001–1 A/µs; resolution 0.001 A/µs; accuracy 5 % + 10 µs | A/µs | range | 4, 5 | Note[7]: attainable maximum falls with input voltage (9 V and above 5 A/µs … 3 V 0.2 A/µs) |
| General condition | 25 °C ± 5 °C with 30-min warm-up; operating 0–40 °C | – | text | 3, 5 | |
| Calibration interval | *not stated* | – | – | – | R4 has no interval or "annual" wording |

## Calibration status: unknown

No calibration certificate, calibration date or adjustment record has been seen for either
instrument: none is in the repository and none has been supplied by the owner. The new profile
therefore records `calibration.status: unknown` on every channel. The datasheet terms above are
conditional on the manufacturer's calibration interval, so the readback budget stays
`not_evaluated` until a status is declared with evidence (plan §3 step 3).

## Re-check of the existing ±(0.1 % + 25 mV) transcription

R1 p. 5, DP821A CH1 row: voltage **programming** 0.1 % + 25 mV and voltage **readback**
0.1 % + 25 mV. The two columns coincide, so the sentence in
[voltage-efficiency-test.md](voltage-efficiency-test.md) ("voltage programming and readback
accuracy of ±(0.1% + 25 mV)") is correct for both roles. The current columns differ
(programming 0.2 % + 10 mA, readback 0.15 % + 10 mA) and must not be interchanged. Neither
`profiles/bench/rigol.example.yaml` nor `extended_plan()` carries the number (both leave the
readback specification unknown), so nothing was mislabeled and neither file needed a correction.

## What remains unknown after this step

- Calibration status and interval of both units (no certificate seen).
- Which CC range `RANG MIN` selects on the DL3031A, and whether current **readback** depends on
  the selected range: R4 documents one readback row (FS 60 A) and no SCPI mapping. The 6 A
  programming range's 0.003 A term is **not** applied to readback (brief §3.3).
- Whether R1's temperature coefficient applies to readback; it is recorded but not budgeted.
- Physical identity: no label photograph, so `physical_model` stays null and
  `capabilities_confirmed` stays false although every rating is sourced (plan §5 label check).
- The ~11 mA `Iout` reading with the load input OFF lies inside R4's 30 mA full-scale term at
  zero, so R4 alone neither explains nor excludes it (plan §3 anomaly 1; §8 step 2).
