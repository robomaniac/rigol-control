# DL3031A built-in load programs: what the load can do for this bench

Research note, documents only: no instrument was connected, no VISA session was
opened and `Software/config/lab.yaml` was not read. It answers the owner's
question "the DL3031A can program transient, OCP, OPP, battery, there is pulse;
can we configure it then trigger that pulse?" for two uses: the load's role in
ISO 16750-2 supply tests (a representative or stepped output load) and the
project's deferred dynamic tests (load-step response, current-limit discovery).
Every parameter below is quoted from the Rigol documents listed first, with
printed page numbers; anything the documents do not state is marked
**unverified** and appears again in the read-only bench check at the end.

Short answer: yes. The DL3031A has a CC-only transient generator with three
modes (continuous, pulsed, toggled), a 512-step list, and OCP/OPP/battery test
applications; all of them are parameterised over SCPI, armed with
`:SOUR:TRAN:STAT 1` and fired with `:TRIG` or `*TRG` once `:TRIG:SOUR BUS` is
selected. What the load *cannot* do is measure the DUT's response to its own
step: its readback integrates over 200 ms and refreshes about once a second, so
a programmed load step on this bench is a defined stimulus with an unmeasured
response until a scope or DAQ is added. The OCP test cannot replace the
software source-limit search on this bench because the supply's 1 A input
limit is reached long before any output current limit of the converter.

## Sources

| Ref | Document | Edition obtained | Printed pages cited as | Obtained from |
| --- | --- | --- | --- | --- |
| UG | Rigol DL3000 User Guide (brief §18 R3) | Oct. 2025, 167 PDF pages | `UG 2-19` | rigol.com URL in brief §18 |
| DS | Rigol DL3000 Data Sheet (brief §18 R4) | DSJ01109-1110 2025.11, 9 PDF pages | `DS p. 3` (printed = PDF − 1, as in [instrument-specifications.md](../instrument-specifications.md)) | rigol.com URL in brief §18 |
| PG | Rigol DL3000 Programming Guide | Apr. 2019, 96 PDF pages | `PG 2-25` | `download.rigol.com/en/Manual/DC Power&Loads/DL3000/DL3000_ProgrammingGuide_EN.pdf`; the same file is linked from the Rigol NA product page. The `rigol.com/dam/...programming-guide/dc-load/...` path returns 404 |
| PG-2017 | Rigol DL3000 Programming Guide | Mar./Aug. 2017, 84/86 pages (distributor mirrors) | not cited | lacks `:SOURce:SENSe`, the OCP/OPP/BATTary groups and `FUNCtion:MODE OCP|OPP`; the project's `:SOUR:SENS?` and `:SOUR:CURR:SLEW:BOTH` already work on the bench, so the 2019 edition is the one that matches the instrument |
| DP-PG | Rigol DP800 Programming Guide | PGH03108-1110, Dec. 2015, 218 PDF pages | `DP-PG 2-29` | distributor mirror (`m.testlink.co.kr`); the rigol.com and Batronix URLs return 404. A newer edition may exist: **unverified** |
| DP-UG | Rigol DP800 User Guide (brief §18 R2) | Jun. 2016 copy, 130 PDF pages | `DP-UG` | already in the scratchpad from an earlier session |

Not obtained: a DL3000 programming guide newer than Apr. 2019 (the current
rigol.com link is broken), the DL3000 firmware release notes, and any Rigol
statement of trigger latency, readback refresh rate or transient-mode behaviour
of the `VLIM`/`ILIM` limits. The DL3000 Performance Verification Manual was
downloaded but not used (calibration procedures only).

Project context read: [README.md](README.md), [iso16750-2.md](iso16750-2.md),
`src/dcdc_bench/standards.py`, `src/dcdc_bench/source_limit.py`,
`src/dcdc_bench/bringup.py` (`RigolPilot`), `src/dcdc_bench/extended.py`
(the source delayer deadline), `Software/src/benchctl/drivers/rigol_dl3000.py`,
[configured-runs.md](../configured-runs.md),
[m2-freshness-and-readback-evidence.md](../m2-freshness-and-readback-evidence.md),
[source-limit-results-review.md](../source-limit-results-review.md),
implementation brief §2, §3, §7, §18.

## 1. Feature table

Model-specific values are for the DL3031A. "Default" is the factory default of
UG Table 2-3 (UG 2-106 to 2-108), identical in PG Appendix A (PG 5-1, 5-2); note
that the defaults for every transient mode are **A_Level 4 A, B_Level 1 A**,
outside the project's 2.5 A envelope, and that `*RST` restores them (PG 2-6).
The driver never sends `*RST`; keep that rule.

### 1.1 Static CC mode (what the project uses today)

| Item | Verified value | SCPI | Source |
| --- | --- | --- | --- |
| Ranges | low 0–6 A, high 0–60 A; switch only with the input OFF | `:SOUR:CURR:RANG {<A>\|MIN\|MAX}`; the range applies to CC **and** transient operation | UG 2-20; PG 2-22 |
| Programming resolution / accuracy | 1 mA; 0.05 % + 0.003 A (6 A range), 0.05 % + 0.03 A (60 A range) | `:SOUR:CURR:LEV:IMM` | DS p. 3 |
| Static slew (rise and fall) | 0.001–1 A/µs, resolution 0.001 A/µs, accuracy 5 % + 10 µs; default 0.001 A/µs | `:SOUR:CURR:SLEW[:BOTH]` | DS p. 4; PG 2-22; UG 2-106 |
| Slew behaviour | transition time = ΔI / slew for large steps; small steps are limited by the load's small-signal bandwidth; "actual time" is 10–90 % | – | UG 2-81, 2-82 |
| Attainable slew vs input voltage | 9 V and above 5 A/µs; 8 V 4; 7 V 2.5; 6 V 1.25; 5 V 0.5; 3 V 0.2 A/µs (DS Note 7; the DL3031A's own ceiling is 1 A/µs) | – | DS p. 5 |
| Von (start sinking above this voltage) | 0–150 V, default 0 V; with Von Latch ON (default) the load keeps sinking when the voltage falls below Von, with it OFF the load stops | `:SOUR:CURR:VON`; the latch has no documented SCPI command (**unverified**) | UG 2-79; PG 2-24; PG 5-2 |
| V_Limit / C_Limit (the load's OVP/OCP thresholds) | 0–155 V / 0–70 A; power-on 155 V / 70 A | `:SOUR:CURR:VLIM`, `:SOUR:CURR:ILIM` | UG 2-5, 2-6 ("Set V_Limit", "Set C_Limit"); PG 2-24; doctor run in the M2 evidence §E |
| Minimum operating voltage | 1.3 V at 60 A; input resistance 350 kΩ with the input off | – | DS p. 3, p. 4 |

### 1.2 Transient (dynamic) generator

| Item | Verified value | SCPI | Source |
| --- | --- | --- | --- |
| Applies to | CC mode only | `:SOUR:FUNC CURR` first | UG 2-19 |
| Modes | **Con**: repetitive A/B stream after one trigger. **Pul**: one pulse per trigger (B → A for the width, then back to B; the trigger function then disables itself). **Tog**: each trigger toggles between A and B and the load stays where it is | `:SOUR:CURR:TRAN:MODE {CONT\|PULS\|TOGG}` | PG 2-25; UG 2-26, 2-31, 2-33, 2-38 |
| Levels | A (high) and B (low), both inside the selected range; defaults 4 A / 1 A | `:SOUR:CURR:TRAN:ALEV`, `:SOUR:CURR:TRAN:BLEV` (`? MIN`/`? MAX` supported) | PG 2-25, 2-26 |
| Rising / falling slew | A/µs, same range as 1.1; defaults 0.001 A/µs | `:SOUR:CURR:SLEW:POS`, `:SOUR:CURR:SLEW:NEG` | PG 2-23; DS p. 4 |
| Con timing | frequency 0.001 Hz–30 kHz (DL3031A), "frequency resolution 0.8 %", accuracy ±0.5 %, duty 5–95 % in 1 % steps; SCPI frequency unit **kHz**, period unit **ms**, duty an integer 1–100 | `:SOUR:CURR:TRAN:FREQ`, `:PER`, `:ADUT`, or `:AWID`/`:BWID` | DS p. 3; PG 2-27, 2-28 |
| Pul width | unit ms in the PG example (UG: "s or ms"); default 2 s; numeric range not printed: query `? MIN`/`? MAX` (**unverified**) | `:SOUR:CURR:TRAN:AWID` | PG 2-26; UG 2-28; UG 2-107 |
| Pulse count | Pul: exactly one per trigger. Con: runs "if the trigger is always enabled" until the trigger function is disabled; no count parameter is documented | `:SOUR:TRAN:STAT 0` stops it | UG 2-24, 2-31 |
| Arm | "trigger function" on = pressing TRAN; the load then waits for the selected trigger source | `:SOUR:TRAN[:STAT] {0\|1}`; query `?` | PG 2-21; UG 2-81 |
| Fire | with source BUS, `:TRIG[:IMM]` or `*TRG` performs one trigger operation; `*WAI` synchronises | `:TRIG:SOUR {BUS\|EXT\|MANU}` (default MANU), `:TRIG`, `*TRG`, `*WAI` | PG 2-17, 2-8 |
| Side effect of arming | enabling the trigger with the input OFF **turns the input on automatically** at Level B; enabling the input first makes the load sink Level B and wait | – | UG 2-24, 2-30, 2-37, 2-44 |
| External trigger | rear digital I/O: input terminal 3.3 V or 5 V, output terminal 3.3 V; input modes ON/OFF, TRAN, Disable; "a low pulse" triggers; input changes must be more than 200 ms apart; output is a level that follows input ON/OFF or TRAN and "can be used to trigger an external device such as a digital oscilloscope"; standard on the DL3031A | `:TRIG:SOUR EXT`; the mode selection is a Utility setting with no documented SCPI (**unverified**) | UG 1-10, 2-95; PG 2-17 |
| Trigger latency, jitter | not stated anywhere (**unverified**) | – | – |

### 1.3 List

| Item | Verified value | SCPI | Source |
| --- | --- | --- | --- |
| Modes and ranges | CC 0–6 / 0–60 A; CV 0–15 / 0–150 V; CR 0.08–15 Ω / 2 Ω–15 kΩ; CP has no range | `:SOUR:LIST:MODE {CC\|CV\|CR\|CP}`, `:SOUR:LIST:RANG` | UG 2-40; PG 2-33, 2-34 |
| Cycles | 0–99999, 0 = infinite; total steps = steps × cycles | `:SOUR:LIST:COUN` | UG 2-41; PG 2-34 |
| Steps | 2–512 per cycle, numbered from 0 | `:SOUR:LIST:STEP` | UG 2-41; PG 2-35 |
| Per step | level; dwell **0.00005 s to 3600 s** (unit s); slew in A/µs (CC only) | `:SOUR:LIST:LEV <step>,<v>`, `:SOUR:LIST:WID <step>,<s>`, `:SOUR:LIST:SLEW <step>,<A/µs>` | UG 2-43; PG 2-35, 2-36 |
| End state | OFF (input off when done) or LAST; disabled when infinite | `:SOUR:LIST:END {OFF\|LAST}` | UG 2-41; PG 2-36 |
| Trigger | one trigger starts the list (BUS/TRAN/DIGIO); there is no per-step trigger; if the trigger is turned off mid-list the next trigger **continues from where it stopped**; parameters cannot be changed while it runs | `:TRIG:SOUR BUS`, `:TRIG` | UG 2-42, 2-44 |
| Running indicator | questionable-status bit 7 "RUN, runs in List mode" (weight 128) | `:STAT:QUES:COND?` | PG 1-7 |
| Persistence | list data is stored in non-volatile memory (survives power-off); defaults 2 steps of 2 A, 1 s, 0.001 A/µs | – | UG 2-39; UG 2-108 |
| Readback per step | "the last sampling value stably displayed for each step in the last cycle" is shown in the on-screen parameter list; no SCPI query for it is documented (**unverified**) | – | UG 2-43 |
| Recording | `Record` writes CSV to a USB stick only | – | UG 2-45 |
| Mode restrictions for this DUT | CV mode "should be used with a CC source"; with a CV source "the current should be limited to 0.2 A" (DS Note 3), so a CV list is excluded for a converter output. CR/CP: "input voltage/current should not be smaller than 10 % of the full scale" (DS Note 4); which full scale is meant is **unverified**, so CP at 12 V needs confirmation before use | – | DS p. 5 |

### 1.4 OCP and OPP test applications

| Item | OCP | OPP | Source |
| --- | --- | --- | --- |
| Principle | after Vin > Von plus a delay, current steps up every step-delay; the load compares the DUT voltage with the protection voltage; when the voltage falls below it "OCP occurred"; pass if that current lies within [C_Min, C_Max]; if nothing happens before the protection time, the load stops and fails | same with power steps | UG 2-46, 2-54 |
| Parameters | range; Von (0–150 V); Delay_Von (ms); C_Start (A); C_Step (A); Delay_Step (ms); OCP_V (V); C_Max, C_Min (A); T_Limit (**µs**) | Von; Delay_Von; P_Start, P_Step (W); Delay_Step (ms); OPP_V; P_Max, P_Min; T_Limit (µs) | UG 2-47 to 2-49, 2-55 to 2-57 |
| SCPI | `:SOUR:OCP:RANG`, `:VON`, `:VOND`, `:ISET`, `:IST`, `:IDEL`, `:IMAX`, `:IMIN`, `:VOCP`, `:TOCP` | `:SOUR:OPP:VON`, `:VOND`, `:PSET`, `:PST`, `:PDEL`, `:PMAX`, `:PMIN`, `:VOPP`, `:TOPP` | PG 2-40 to 2-48 |
| Defaults | range 60 A; Von 0.01 V; delay 500 ms; start 0 A; step **1 A**; step delay 500 ms; protection voltage 0.5 V; max 10 A, min 9 A; time 500 µs | start 0 W; step 1 W; 500 ms; 0.5 V; 100 / 90 W; 500 µs | UG 2-108 |
| Starting it remotely | select the mode, then turn the input on (the UG's step 5 "Turn on the channel input" starts the test) | same | PG 2-20 (`:SOUR:FUNC:MODE {FIX\|LIST\|WAV\|BATT\|OCP\|OPP}`); UG 2-52, 2-59 |
| Result | screen prompt "OCP test passed!" or one of three failure prompts; the rear digital output is 0 for pass, 1 for fail (when Digital Out is set accordingly); the input turns off at the end. **No SCPI query of the trip current or the verdict is documented** (**unverified**) | same | UG 2-46, 2-52, 2-59 |

### 1.5 Battery test

CC discharge until a cut-off voltage, a capacity (mAh) or a time is reached;
`:SOUR:BATT:RANG`, `:LEV:IMM`, `:VST`, `:CST`, `:TIM`, `:VON`, `:VEN`, `:CEN`,
`:TEN` (PG 2-36 to 2-40); readback `:MEAS:CAP?`, `:MEAS:WATT?`, `:MEAS:DISC?`
(PG 2-15, 2-16); UG 2-61. **Relevance to a converter DUT: none.** A converter is
not an energy store; the stop conditions describe a battery, and the only
quantity the mode adds (integrated Wh) can be computed from the project's
sampled power with its timing recorded. Excluded from the proposal.

### 1.6 Protection, sense, status, readback

| Item | Verified value | SCPI | Source |
| --- | --- | --- | --- |
| Protections | OCP, OVP, OPP, OTP, local/remote reverse voltage; each turns the input off, beeps and shows a prompt | OCP/OVP thresholds are `ILIM`/`VLIM` (1.1); OPP and OTP have no settable value documented | UG 2-83, 2-84; DS p. 4 |
| Status word | bit weights: VF 1, OC 2, RS 4 (remote-sense terminal connection), OP 8, RUN 128, RRV 512, UNR 1024, LRV 2048, OV 4096, PS 8192, VON 16384 (the project's fault mask 15883 is these minus RS, RUN and VON) | `:STAT:QUES:COND?` (live), `:STAT:QUES?` (latched) | PG 1-7, 2-9, 2-10 |
| Remote sense | S+/S− at the DUT output; "can be enabled or disabled in any working mode" | `:SOUR:SENS {0\|1}`; `:SOUR:SENS?` | UG 2-85; PG 2-49 |
| Readback integration | `:MEAS:TIME?` returns the integration time, "10 PLC, 200 ms" | `:MEAS:VOLT?`, `:MEAS:CURR?`, `:MEAS:POW?` | PG 2-16 |
| Readback resolution / accuracy | 0.1 mA, ±(0.05 % + 0.05 % FS) current (FS 60 A, so ±30 mA fixed); 0.1 mV, ±(0.05 % + 0.02 % FS) voltage | – | DS p. 4 |
| Observed refresh | about 1.0–1.15 s between distinct values, round trips 4–5 ms median, 55 ms max | project logs, no Rigol statement | M2 evidence §A, §E |
| Min/max capture | "reads the maximum/minimum input voltage/current"; the capture window and its reset are not stated (**unverified**) | `:MEAS:VOLT:MAX?`, `:MIN?`, `:MEAS:CURR:MAX?`, `:MIN?` | PG 2-14 |
| Waveform cache | 400 consecutive points of the waveform-display cache; display window 8 s to 80 h (Roll), so at best about 20 ms per point; "Fast" mode exists for Con only and is set in ms by knob | `:FETC:WAV?` / `:MEAS:WAV?`; `:SOUR:WAV:TIM {ADD\|SUB}` | PG 2-16, 2-48; UG 2-75, 2-76 |
| Analog monitors | rear "Voltage Monitoring Output" and "Current Monitoring Output" terminals (analog) | Utility items `Vmon_EXT`, `Imon_EXT`, default OFF | DS p. 1 rear-panel figure; UG 1-11; PG 5-2 |
| USB logging | waveform `Record` and List `Record` write CSV to a USB stick; the system "Log" stores key presses and prompts, not measurements | – | UG 2-76, 2-45, 2-96 |
| Dangerous remote controls | `:SYST:KEY <n>` simulates any front-panel key, including 33 SHORT and 32 ON/OFF; the SHORT function shorts the input terminals | never issue `:SYST:KEY`, `:DEBug:KEY` or `*RST` | PG 2-50; UG 2-80 |

## 2. What a bus-triggered pulse looks like end to end

Arming and firing sequence as the documents describe it (the exact state
transitions must be confirmed on the pass-through fixture before any converter
is connected, see §8):

1. Input OFF. `:SOUR:FUNC CURR`; `:SOUR:FUNC:MODE FIX`; `:SOUR:CURR:RANG MIN`
   (6 A); `:SOUR:CURR:VLIM`/`:ILIM` to the guards; read all back (the existing
   `apply_load_cc_limits`).
2. `:SOUR:CURR:TRAN:MODE PULS`; `ALEV`, `BLEV`, `SLEW:POS`, `SLEW:NEG`, `AWID`;
   `:TRIG:SOUR BUS`. Read every value back; `:SOUR:TRAN:STAT?` must be 0.
3. Source ON with the delayer deadline (as today), then `:SOUR:INP:STAT ON`
   with `:SOUR:CURR:LEV:IMM` = B_Level and verify the point is stable in FIX
   mode. The input is already ON, so arming cannot energise anything by itself
   (UG 2-30 describes exactly this order).
4. Arm: `:SOUR:TRAN:STAT 1`; read back 1. The load sinks B and waits.
5. Fire: `:TRIG` (or `*TRG`). The load ramps B → A at `SLEW:POS`, holds A for
   the width, ramps A → B at `SLEW:NEG`, and in Pul mode disables the trigger
   function itself (UG 2-31). Poll `:SOUR:TRAN:STAT?` until 0, bounded by a
   software timeout of width plus margin.
6. Evidence: `:STAT:QUES:COND?` before and after, `:MEAS:CURR?`/`:VOLT?`
   polls, optionally `:MEAS:VOLT:MIN?` and `:MEAS:CURR:MAX?` (meaning
   unverified).

Timing claims that the documents support: the edge is defined by the
programmed slew with 5 % + 10 µs accuracy (DS p. 4), e.g. a 0.5 A step at the
default 0.001 A/µs takes about 500 µs, at 0.1 A/µs about 5 µs plus the
small-signal limit. Timing claims the documents do **not** support: when the
step happens relative to the `:TRIG` write (no latency figure), and what the
DUT output did during it (200 ms integration, about 1 s refresh). A pulse
shorter than roughly a second is invisible to the polled readback except as a
smeared mean; the min/max registers may catch it if their window covers the
pulse, which is unverified.

## 3. OCP/OPP test versus the software source-limit search (question 3)

Which limit is reached first on this bench is settled by the measured run, not
by the DUT's rating. The supply is programmed to 1.000 A (OCP 1.05 A) and the
input is at most 35.8 V, so the input power is at most 35.8 W. The real 24 V
search ([source-limit-results-review.md](../source-limit-results-review.md))
stopped at **1.725 A requested output with 0.987 A mean input current**, in
CV, with 86.5 % path efficiency; the planner's load grid stops at 2.5 A and the
power guard at 34 W. The converter's own output current limit is unknown but
cannot be below its 4 A rating if the rating is honest. Therefore on this bench
the **supply's 1 A input limit is reached first at every input voltage**: about
1.7 A output at 24 V, at most about 2.5–2.7 A at 35.8 V, well under 1 A at 12 V.

Consequences for the DL3031A OCP test:

- Its trip criterion is "DUT voltage below OCP_V". When the supply enters
  constant current, the converter's input voltage sags, a 9–36 V buck-boost
  draws more current to hold its output, and the input collapses to UVLO; the
  output then falls through OCP_V and the load reports "OCP occurred" at that
  step current. That number is the **source boundary**, not a DUT overcurrent
  threshold, and the load has no way to know the difference: it cannot read
  `:OUTP:CVCC? CH1`, which is exactly the observable the software search uses
  to stop (`source_limit.py`, `BenchBoundary` on CC or on input headroom).
- The test steps every Delay_Step (default 500 ms) and judges within T_Limit
  (µs). The software search holds each candidate for a 10 s acquisition with a
  50 mV settling criterion and a 30 s endpoint window, and records every cycle.
- The verdict is a screen prompt and a digital-output level; no documented
  SCPI query returns the trip current, so the evidence would be the project's
  own polling anyway.
- It runs autonomously once the input is on, with 1 A steps by default; the
  envelope (2.5 A, 34 W) would have to be enforced by `IMAX` and `ILIM` alone.
- Current-limit tests are opt-in later features (brief §7.5) and ISO 16750-2
  clause 4.10.3 is excluded by policy.

Verdict: the OCP/OPP applications do not replace the software source-limit
search and should not be used on this bench as a "DUT current-limit discovery".
The one honest use would be, with another supply capable of the rated input
current, a supervised bounded probe with `IMAX` set at the approved ceiling; that
is a different bench and a different policy. The OPP application has the same
structure (power steps) and the same verdict.

## 4. Mapping: project tests and ISO 16750-2 roles

Legend for "How": **built-in** = the load's own program, armed and fired over
the bus; **LAN-stepped** = today's `:SOUR:CURR:LEV:IMM` writes at about 1 s
(the edge is the load's static slew, default 0.001 A/µs); **instrument** = needs
a scope/DAQ or another instrument. The claim wording is what a report may say.

| Test or role | How | Feasible on this bench? | Honest claim wording |
| --- | --- | --- | --- |
| ISO 16750-2 4.2 DC supply voltage, mode 3.2 (normal operating load) | LAN-stepped CC (runs today) or a fixed CP level (DS Note 4 caveat, 100 mW resolution) | yes, as today; mode 3.4 (maximum load) unreachable from a 1 A source | "load held at X A (CC) at the load terminals; the standard's maximum-load mode was not reachable" |
| 4.2, 4.5, 4.6.2 with a *stepped* functional load between supply steps | **built-in** List in CC (e.g. 0.1 → 0.5 → 0.1 A, dwells ≥ 1 s, end state OFF or LAST) fired by `:TRIG` after each supply step; or LAN-stepped | feasible once the program path exists (§6); the supply steps stay LAN-stepped; 4.5 and 4.6.2 remain mock-only until approved | "a programmed load pattern [levels, dwells, slew] was applied after each supply step; the converter's response was observed by 1 s polling only" |
| 4.6.2 reset behaviour: letting the load release a collapsing output | `:SOUR:CURR:VON` above the collapse level with Von Latch OFF makes the load stop sinking when Vout falls below Von (UG 2-79) | the latch setting has no documented SCPI (**unverified**); until then, light load only | "the load was configured to stop sinking below X V" only after the latch state is read back |
| 4.6.3 starting profile, 4.3.2, 4.6.1.1 (ms pulses **on the supply**) | the load's generator does not help: these pulses are on the input side | **instrument** (as in `standards.py`) | unchanged: needs instrument |
| 4.4 superimposed AC, 4.8 offsets, 4.9 open circuit | – | **instrument** | unchanged |
| 4.10.3 overload of load circuits (100 %, 150 % of rated current) | the OCP application could step to 6 A in principle | excluded by policy, and unreachable: the source limits the output to about 1.7 A at 24 V | not run |
| Deferred: load-step response (Vout deviation and recovery) | **built-in** Tog or Pul with programmed slew; LAN-stepped gives the same edge with a 1 s timebase | the *stimulus* is feasible (slew 0.001–1 A/µs, levels bounded by Vin and the 1 A source); the *measurement* needs a scope on the DUT output and on the load's Imon output | "a load step from A to B at S A/µs was applied by the load's transient generator (slew accuracy 5 % + 10 µs per DS); the output voltage seen by the load's 200 ms-integrated readback stayed between min and max; this is not a transient response measurement (brief §2)" |
| Deferred: repetitive dynamic load (Con, e.g. 100 Hz 10–50 % duty) | **built-in** Con | feasible as a stress stimulus; thermal and source effects bound the mean current; nothing of the ripple is measurable | "a continuous A/B load stream at f Hz, D % duty was applied; only mean readbacks were recorded" |
| Deferred: current-limit discovery (DUT OCP threshold) | OCP application or software search | **not reachable** on this bench (§3): the first limit is the supply's 1 A | "the output current at which the supply reached its 1 A limit was X A; the converter's current limit was not reached" |
| Enabled no-load and light-load efficiency | unchanged | the ±30 mA full-scale readback term dominates below 0.5 A (M2 evidence) | unchanged |

New capability tokens this suggests for `standards.py`, granted only by a bench
profile that declares the load's program support (never inferred from the
identity string, brief §3.2): `load_step_programmed` (edge defined by the load's
slew specification, response unmeasured) and, for a future scope,
`transient_capture`. The existing `dc_step_1s` family stays for the supply.

## 5. Synchronising the load with the supply (question 6)

- **Load side:** `:TRIG:SOUR BUS`, arm with `:SOUR:TRAN:STAT 1`, fire with
  `:TRIG` or `*TRG` (PG 2-17, 2-8). No trigger delay parameter exists on the
  load.
- **Source side (DP821A):** the DP800 trigger system is installed on the "A"
  models (DP-PG 2-142). With `:TRIG:SOUR BUS` and `:INIT`, a `*TRG` changes CH1
  to the "trigger voltage/current" set by `:TRIG:IN:VOLT CH1,<V>` (or
  `:VOLT:TRIG`), after an integer delay of 0–3600 s (DP-PG 2-29, 2-30, 2-150,
  2-157, 2-158). This is a documented bus-triggered supply step; it is a third
  way to step the source, not faster in itself than a `:VOLT` write, but it
  lets both instruments be armed first and fired back to back.
- **Skew estimate, Pi over LAN:** two consecutive writes from the worker; the
  skew is one write latency plus each instrument's unspecified trigger-to-output
  latency. The project's measured round trips are 4–5 ms median, 13–36 ms at
  p95 and 55 ms worst (M2 evidence Table A4), so the typical skew is of order
  5–10 ms, tens of milliseconds are ordinary, and there is no upper bound
  (pyvisa-py, Linux scheduling on a Pi, the instruments' parsers). That is far
  from the ISO 16750-2 edge tolerances (≤ 10 ms edges, +/-5 % on times) and
  cannot be promised; it can only be **measured** with a scope on the DP821A
  output and the DL3000 Imon terminal, or on the two digital-I/O lines.
- **Hardware trigger:** the DL3000 digital output (3.3 V level on TRAN or
  ON/OFF, UG 2-95) could drive the DP821A digital-I/O trigger input
  (`:TRIG:IN:RESP`, `:TRIG:IN:TYPE`, DP-PG 2-143 to 2-150), or the reverse,
  removing the LAN from the skew. Both logic grounds would be tied together;
  whether either port is isolated from its instrument's input terminals is
  **unverified**, so this needs a wiring review before anything is connected.
- **DP800 timer instead of LAN steps:** `:TIMEr:PARAmeter` holds up to 2048
  groups with 1 s to 99999 s each (DP-PG 2-132), enough for a 4.2 profile, but
  "the timer and delayer cannot be enabled at the same time" (DP-PG 2-133). A
  source timer profile would therefore forfeit the project's verified 720 s
  delayer cutoff unless the timer's own end state is accepted as the
  independent cutoff, which is a separate review. Not proposed here.

## 6. Safety design: keeping fail-closed behaviour with an autonomous program

A pulse or list runs inside the load after one command; the worker cannot stop
it between samples the way it stops a LAN-stepped sweep. The design below keeps
the protective order of brief §7 and adds what the autonomy requires.

1. **Opt-in and approval.** A new test type (`load_step_program`) is refused on
   a real profile until the bench profile declares the load's program support
   and the recipe carries an authorization block naming the protective policy,
   exactly as `runs_after_approval` / `mock_only` work today. Mock first.
2. **Protections before programs.** With both outputs OFF: `VLIM` and `ILIM`
   programmed and read back (today's `apply_load_cc_limits`), range MIN,
   `:SOUR:FUNC:MODE FIX`, `:SOUR:TRAN:STAT?` = 0, `:TRIG:SOUR BUS` read back.
   Whether `VLIM`/`ILIM` act during transient operation is **unverified**; until
   a fixture test shows the trip, the envelope is enforced by the program bounds
   alone, so those bounds must be conservative.
3. **Bounds from the envelope, derived per input voltage.** A_Level ≤ the
   planner's load cap (2.5 A) and ≤ the output current the 1 A source can feed
   at that Vin with the worst-case efficiency the planner already uses; the
   *mean* current of a Con stream (duty-weighted) and the *peak* both pass the
   check; A_Level × Vout guard ≤ 34 W; B_Level ≥ the light-load floor; width
   and dwells such that the whole program fits the 660 s software deadline and
   the 720 s delayer; slew starts at the minimum (0.001 A/µs) and may only be
   raised by a recipe change with fresh approval. List end state is always OFF
   or LAST as declared; cycles are finite (0 = infinite is refused).
4. **Read back the whole program before arming.** Every parameter is queried
   and compared with the plan (1 mA, 0.001 A/µs, timing within the resolution
   the `? MIN` query reports); a mismatch aborts before the input is enabled.
   The non-volatile list memory means a stale list from an earlier session is
   possible, so the comparison is mandatory, not a formality.
5. **Order of operations.** Source ON with the delayer deadline, load input ON
   at B_Level in FIX mode, stable point verified, then arm, then fire. Arming
   never happens with the input OFF because the load would switch it on by
   itself (UG 2-24).
6. **Timeouts and stop.** A software timeout of the program duration plus a
   margin; on expiry, on any guard breach, on a questionable-status fault bit,
   or on a communication error: `:SOUR:TRAN:STAT 0` (verify 0), then
   `:SOUR:INP:STAT OFF` (verify), then the approved source stop; each step is
   attempted independently (brief §7.4). The delayer remains the independent
   cutoff for the source; there is no independent cutoff for the load other
   than its own `ILIM`/`VLIM`/OTP.
7. **Evidence.** Program readback (every parameter), arm and fire timestamps
   (monotonic and UTC), `:SOUR:TRAN:STAT?` transitions, status words before and
   after, the polled readbacks with the 200 ms integration noted, min/max
   registers if their behaviour is confirmed, and the stop reason. The report
   labels the result a programmed stimulus with an unmeasured response.

What cannot be guaranteed: that the program stops if the LAN drops after
firing (a Con stream continues until the load's own protections or the source
delayer act); that the readback captured the pulse at all; the trigger latency
and the skew to any supply step; the converter's fast response (overshoot,
ringing) to an edge of 1 A/ms or faster; and that `VLIM`/`ILIM` protect during
transient operation until the fixture test proves it.

## 7. Implementation outline and effort

- **benchctl driver `rigol_dl3000.py`** (mechanism only, as today): read-only
  `get_trigger_source`, `get_transient_enabled`, `get_function_mode`,
  `get_transient_program`, `get_list_program`, `query_limit(command, MIN|MAX)`,
  `measure_extrema`; state-changing with readback and error-queue drain
  `set_trigger_source`, `configure_transient(mode, a, b, slew_pos, slew_neg,
  width|period, duty)`, `configure_list(steps, count, end_state)`,
  `transient_enable`/`transient_disable`, `trigger`. No `*RST`, no `:SYST:KEY`.
  About 1 day including the fake-SCPI transient/list state machine.
- **Contracts (`domain.py`)**: `LoadProgram` (kind, levels, slews, timing,
  trigger source fixed to BUS, end state, finite cycles) under a new
  `TestDefinition.type = "load_step_program"`; `LoadCapabilities` gains
  `programs_supported: bool = False`, `slew_range_A_per_us`,
  `program_min_width_s` (from the `? MIN` bench check); `ProtectiveControls`
  gains `load_program_peak_current_A` and `load_program_max_duration_s`.
  About 1 day with tests.
- **Planning and standards**: the per-Vin A_Level ceiling, the deadline split,
  the mock-only refusal on real profiles, the `load_step_programmed` token and
  the "stimulus only" wording in `standards.py`. About 1 day.
- **Worker and evidence**: the §6 sequence in a fixed procedure first (like
  `source_limit.py`), events `load_program_readback`, `load_program_armed`,
  `load_program_fired`, `load_program_stopped`; mock plant: extend
  `MockBench.set_load_current` (it already has `load_step_time_s`) with a
  slew-limited two-level program. About 1.5 days.
- **Report**: a "programmed load step" section drawing the polled readbacks
  with the integration caveat and the program parameters as a table. About
  0.5–1 day.
- **Bench**: one read-only query session (§8), then one supervised session on
  the pass-through fixture (supply CH1 wired to the load, converter
  disconnected, as in M2 evidence §F) to confirm the arm/fire semantics, the
  `VLIM`/`ILIM` behaviour during a pulse and the readback's view of a 1 s pulse;
  only then a light converter pulse. Software total about 5–6 engineer-days
  before the bench sessions.

## 8. Open questions for a read-only bench check

Queries only, no writes, no `*RST`, outputs OFF; record each raw response and
the error queue after each query. These resolve every **unverified** mark above
that a document cannot.

1. `*IDN?` firmware string, `*OPT?`, `:SYST:VERS?`: which SCPI version and
   whether the firmware is newer than the Apr. 2019 guide.
2. Transient limits on this unit: `:SOUR:CURR:TRAN:AWID? MIN`, `? MAX`,
   `BWID? MIN/MAX`, `FREQ? MIN/MAX`, `PER? MIN/MAX`, `ADUT? MIN/MAX`,
   `ALEV? MIN/MAX`, `BLEV? MIN/MAX`, `:SOUR:CURR:SLEW:POS? MIN/MAX`,
   `:SOUR:CURR:SLEW:NEG? MIN/MAX`, `:SOUR:CURR:SLEW? MIN/MAX`. Also the units the
   queries return (ms versus s for widths, kHz for frequency).
3. Current state left by previous sessions: `:TRIG:SOUR?`,
   `:SOUR:TRAN:STAT?`, `:SOUR:CURR:TRAN:MODE?`, `ALEV?`, `BLEV?`,
   `:SOUR:FUNC:MODE?`, `:SOUR:CURR:RANG?`, `:SOUR:CURR:VON?`,
   `:SOUR:CURR:SLEW?`.
4. The non-volatile list: `:SOUR:LIST:MODE?`, `RANG?`, `COUN?`, `STEP?`,
   `END?`, `LEV? 0`, `WID? 0`, `SLEW? 0` (and step 1).
5. OCP/OPP parameters as stored: `:SOUR:OCP:RANG?`, `VON?`, `ISET?`, `IST?`,
   `IDEL?`, `IMAX?`, `IMIN?`, `VOCP?`, `TOCP?`; `:SOUR:OPP:PSET?` and the
   rest. Confirms that none of these are armed and documents the defaults.
6. Readback mechanics: `:MEAS:TIME?` (expect 200), `:MEAS:VOLT:MAX?`,
   `:MEAS:VOLT:MIN?`, `:MEAS:CURR:MAX?`, `:MEAS:CURR:MIN?` repeated three times
   a few seconds apart with the input OFF, to see whether the registers hold,
   reset, or follow the live value; `:FETC:WAV?` once, to see whether it
   answers outside the waveform display and how many values it returns.
7. Status: `:STAT:QUES:COND?`, `:STAT:OPER:COND?`, `:SOUR:SENS?`.
8. Which of the above the firmware rejects (error queue), which is the only
   way to learn the actual command set versus the 2019 guide.

Questions that need a non-read-only fixture session (not now): the exact
arm/fire state transitions in Pul and Tog mode; whether `:SOUR:TRAN:STAT 0`
stops a Con stream; whether `ILIM`/`VLIM` trip during a pulse; the trigger
latency with a scope on Imon; whether the `Von Latch` state can be set or read
over SCPI; whether the per-step list readbacks can be queried.
