# Running ISO 16750-2 supply profiles from inside the DP821A: Timer, Delayer, Monitor, Trigger, Recorder

Research note, 2026-09-30. The owner asked whether the Rigol DP821A's built-in
modes (Timer with cycles, Delayer, Monitor, Trigger, Recorder, Analyzer) could
execute some ISO 16750-2 section 4 supply profiles instead of, or next to,
stepping the source over the LAN from the Raspberry Pi at the ~1 s cadence
described in [iso16750-2.md](iso16750-2.md). This note records what the
manufacturer documents verify, what that means clause by clause, how the
project would keep its fail-closed behaviour if the instrument became the
sequencer, and what still has to be checked at the bench. No instrument was
connected while writing it.

Short answer: the Timer can run every DC-level profile the project already
plans (4.2, 4.6.2, the long holds of 4.3.1.1, the slow ramp of 4.5) with
instrument-side timing that no longer depends on the Pi being alive, and the
Monitor adds an instrument-side output-off cutoff. Nothing in the DP800
unlocks a single edge, pulse, ripple or interruption clause: the Timer and
Delayer time in whole seconds (1 s to 99999 s) and the DP821A CH1 output
itself takes up to 110 ms to rise under load and up to 800 ms to fall without
load. The project's `edge_10ms`, `pulse_ms`, `pulse_us` and `ac_superposition`
verdicts stand, now with datasheet numbers behind them.

## Sources

Fetched 2026-09-30 from rigol.com with `curl -L`, read with `pdftotext
-layout`, not redistributed. Page numbers below are PDF page numbers of these
files; the printed page number follows in parentheses where the page has one.

| Ref | Document | File identity | Pages |
| --- | --- | --- | --- |
| DS | DP800 Series Data Sheet (brief §18, R1) | `DP800_DataSheet_EN.pdf`, publication DSH03108-1110-202505 (p. 12), PDF dated 2025-05 | 12 |
| UG | DP800 Series User's Guide (brief §18, R2) | `DP800_UserGuide_EN.pdf`, publication UGH04109-1110 (p. 3), PDF dated 2016-06 | 130 |
| PG | DP800 Series Programming Guide | `DP800_ProgrammingGuide_EN.pdf`, publication PGH03109-1110 (p. 3), PDF dated 2021-07; current URL `https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/dc-powers/DP800_ProgrammingGuide_EN.pdf` (the `programming-guide/` path the brief's R1/R2 pattern suggests returns 404) | 218 |

All three documents were obtained; nothing below is marked unverified for
lack of a document. "Unverified" marks statements the documents do not make
and that need a bench check (listed at the end).

The project files read for context: `docs/standards/README.md`,
`docs/standards/iso16750-2.md`, `src/dcdc_bench/standards.py`,
`src/dcdc_bench/supply_profiles.py`, `docs/configured-runs.md`,
`docs/implementation-brief.md` §2, §3.2, §7, `src/dcdc_bench/extended.py`
(the 720 s one-shot delayer), `src/dcdc_bench/real_backend.py`,
`src/dcdc_bench/doctor.py`, `Software/src/benchctl/drivers/rigol_dp800.py`,
`profiles/bench/rigol-dp821a-dl3031a.yaml`.

## How the project already uses the instrument's sequencer

`extended.py` arms the Delayer as the independent 720 s cutoff before every
energised phase: `:INST:NSEL 1`, `:DELAY:GROUPS 1`, `:DELAY:CYCLES N,1`,
`:DELAY:ENDSTATE OFF`, `:DELAY:STOP NONE`, `:DELAY:PARAMETER 0,ON,720`, then
reads back `:DELAY:GROUPS?`, `:DELAY:CYCLES?`, `:DELAY:ENDSTATE?`,
`:DELAY:STOP?` and the definite-length block from `:DELAY:PARAMETER? 0,1`
(`_delay_parameter` rejects anything but exactly one group). `:DELAY ON` is the
command that energises the channel ("Independent deadline did not start with
source output ON" otherwise), and shutdown sends `:OUTP CH1,OFF` and verifies
it before `:DELAY OFF`, because a one-group ON program has no later ON edge
that could re-energise the DUT. `doctor.py` reads `:TIMER?` and `:DELAY?` and
flags anything but OFF. The run envelope is a 540 s planning estimate, a 660 s
software deadline and that 720 s instrument cutoff per input-voltage phase
([configured-runs.md](../configured-runs.md)).

The constraint that shapes everything below: **the Timer and the Delayer are
mutually exclusive** (UG p. 52 (2-16); PG p. 157 (2-133) "The timer and
delayer (:DELAY[:STATe]) cannot be enabled at the same time"). A Timer-driven
profile cannot keep today's Delayer cutoff; its independent time bound has to
come from the Timer program itself ending with output OFF, with the Monitor
and OVP/OCP as the level cutoffs.

## Feature table (what the documents verify)

| Feature | Verified parameters | SCPI (PG) |
| --- | --- | --- |
| **Timer** (standard on all DP800, DS p. 1) | Up to 2048 groups per cycle, each group = voltage, current, time (UG p. 51 (2-15), p. 53 (2-17)); groups 1-2048; cycles 1-99999 or infinite; end state `OFF` (output off) or `LAST` (stay at the last group); end state is meaningless with infinite cycles (UG p. 53). Time per group **1 s to 99999 s**: `<time>` is typed "Real, 1s to 99999s" for `:TIMEr:PARAmeter` (PG p. 156 (2-132)) but every read-back example returns whole seconds and the template interval is an Integer (PG p. 158 (2-134)); sub-second acceptance is **unverified**. Voltage and current range = the channel's range (so 1 mV / 0.1 mA on the DP821A CH1, DS p. 5). "The timing output is valid only when both the timer and the channel output are turned on"; parameters cannot be edited while the timer is ON (UG p. 61 (2-25); PG p. 157). Per-channel: select with `:INST:NSEL 1` first (PG p. 157). Built-in templates Sine, Pulse (two groups, width 1-99998 s, period 2-99999 s), Ramp, Stair Up/Dn/UpDn (10-2048 points, interval 1-99999 s), Exp Rise/Fall (UG pp. 54-60 (2-18 to 2-24)). Timer files `*.RTF` can be stored internally (`:MEM:STOR RTF,n`, PG p. 185 (3-3)). | `:TIMEr:GROUPs <1-2048>` (p. 155 (2-131)); `:TIMEr:CYCLEs {N|I}[,<1-99999>]` (p. 153 (2-129)); `:TIMEr:ENDState {OFF|LAST}` (p. 154 (2-130)); `:TIMEr:PARAmeter <0-2047>,<volt>,<curr>,<time>` and `:TIMEr:PARAmeter? <first>[,<count 1-2048>]` returning `#9<len>` + `n,V,I,t;` groups (p. 156 (2-132)); `:TIMEr[:STATe] {ON|OFF}` (p. 157 (2-133)); alias `:OUTPut:TIMEr {P8V|P30V|N30V},...` and `:OUTPut:TIMEr:STATe` (pp. 88-89 (2-64, 2-65)); templates `:TIMEr:TEMPlet:SELect {SINE|SQUARE|RAMP|UP|DN|UPDN|RISE|FALL}`, `:INTErval`, `:POINTs`, `:MAXValue`, `:MINValue`, `:OBJect {V|C},<fixed other quantity>`, `:PERIod`, `:WIDTh`, `:CONSTruct` (pp. 157-165 (2-133 to 2-141)). One SCPI command per manually edited group; a template program needs about eight commands regardless of length. Worked example: output ON first, then `:TIME ON` (p. 185 (3-3)). |
| **Delayer** (standard, DS p. 1) | Up to 2048 groups of {ON or OFF, delay}; groups 1-2048; cycles 1-99999 or infinite; end state `ON`, `OFF` or `LAST`; delay per group **Integer 1 s to 99999 s** (UG pp. 62-64 (2-26 to 2-28); PG p. 39 (2-15)). Automatic generation: state pattern `01P`/`10P`, times `FIX` on/off, `INC`/`DEC` from a base at a step (PG pp. 40, 42). **Stop condition**: the instrument watches V, I, P during delay output and ends the program (then applies the end state) on one of `<V`, `>V`, `<C`, `>C`, `<P`, `>P` (UG p. 65 (2-29); PG p. 41 (2-17)). Enabling the delayer changes the output state (PG p. 40 (2-16)). | `:DELAY:GROUPs`, `:DELAY:CYCLEs`, `:DELAY:ENDState {ON|OFF|LAST}`, `:DELAY:PARAmeter <n>,{ON|OFF},<time>` / `? <first>[,<count>]` (block format as the Timer), `:DELAY[:STATe]`, `:DELAY:STATe:GEN`, `:DELAY:TIME:GEN`, `:DELAY:STOP {NONE|<V|>V|<C|>C|<P|>P}[,<value>]` (pp. 36-42 (2-12 to 2-18)). |
| **Monitor** (standard on "+A" models, option AFK-DP800 otherwise, DS pp. 1, 11) | Per channel; several channels at once. Condition = logic combination (`AND`/`OR`/`NONE`) of `<V`/`>V`, `<C`/`>C`, `<P`/`>P` with set values (UG p. 72 (2-36)); value ranges 0 to the channel maximum, defaults 0.5 x rated V and I, 0.25 x rated P (PG pp. 71, 72, 75). Stop mode: any of **Output Off**, Warning (screen prompt), Beeper (UG p. 72; PG p. 73 (2-49)). **No reaction time, sampling rate or hysteresis is specified** anywhere in DS, UG or PG. | `:MONItor:VOLTage:CONDition {<V|>V|NONE},{AND|OR|NONE}`, `:MONItor:VOLTage[:VALue]`, `:MONItor:CURRent:CONDition`, `:MONItor:CURRent[:VALue]`, `:MONItor:POWER:CONDition {<P|>P|NONE}`, `:MONItor:POWER[:VALue]`, `:MONItor:STOPway {OUTOFF|WARN|BEEPER},{ON|OFF}` (query returns `OutputOff:ON,Warn:ON,Beep:OFF`), `:MONItor[:STATe]` (pp. 70-75 (2-46 to 2-51)); example p. 187 (3-5). |
| **Trigger I/O** (digital I/O standard on "+A" models, DS p. 1 and I/O table p. 6; option DIGITALIO-DP800 on non-A models, DS pp. 9, 11; mating connector "Terminal-Digital I/O-DP800", DS p. 11) | Rear-panel digital I/O with **4 independent data lines D0-D3**, each usable as trigger input or output (UG p. 73 (2-37)). **Input**: rising/falling edge or high/low level; high 2.5-3.3 V, low 0-0.8 V, 0.4 V noise tolerance; response = output **On, Off or Toggle** of the chosen channel(s); sensitivity low/mid/high (UG pp. 74-75 (2-38, 2-39); PG pp. 169-173). The trigger input controls the output relay state only; **no document says it can start or stop the Timer or Delayer**. **Output**: a line goes to a level (high 2.6-3.5 V, low 0-0.4 V) or a square wave (period 100 us to 2.5 s, duty 10-90 %) when the channel output turns on/off, or when V/I/P meets `>`, `<`, `=` a value, or automatically (UG pp. 75-76 (2-39, 2-40); PG pp. 175-180). Separate **software trigger system**: `:TRIG:SOUR {BUS|IMM}`, a trigger delay of **0-3600 s (Integer)**, triggered voltage/current amplitudes applied by `:INIT` + `*TRG` to the current channel and any coupled channels (PG pp. 53-55, 109, 116, 181-182; example p. 186 (3-4)). | `:TRIGger:IN[:ENABle] [Dn,]{ON|OFF}`, `:TRIGger:IN:TYPE [Dn,]{RISE|FALL|HIGH|LOW}`, `:TRIGger:IN:RESPonse [Dn,]{ON|OFF|ALTER}`, `:TRIGger:IN:SOURce [Dn,][CH1[,CH2]]`, `:TRIGger:IN:SENSitivity` (pp. 169-173 (2-145 to 2-149)); `:TRIGger:OUT:CONDition [Dn,]{OUTOFF|OUTON|>V|<V|=V|>C|<C|=C|>P|<P|=P|AUTO}[,<value>]`, `:TRIGger:OUT:SIGNal {LEVEL|SQUARE}`, `:TRIGger:OUT:PERIod 0.0001-2.5`, `:TRIGger:OUT:DUTY 10-90`, `:TRIGger:OUT:POLArity`, `:TRIGger:OUT:SOURce [Dn,]{CH1|CH2}`, `:TRIGger:OUT[:ENABle]` (pp. 175-180 (2-151 to 2-156)); `:TRIGger[:SEQuence]:SOURce`, `:TRIGger[:SEQuence]:DELay 0-3600`, `[:SOURce<n>]:VOLTage:TRIGgered`, `[:SOURce<n>]:CURRent:TRIGgered`, `:INITiate`, `*TRG`, `:INSTrument:COUPle` (pp. 53-55, 109, 116, 181-182). |
| **Recorder** (standard on all models, DS p. 1; UG p. 14 "background recording of the output state") | Samples V, I, P of every channel at a **record period of Integer 1 s to 99999 s** (default 1 s) into a `*.ROF` file; **2048 points** in internal memory (10 slots) or 614400 on a USB stick; period and destination must be set before `:REC ON`; **a channel whose output is OFF is recorded as 0**; the file is written when the recorder is turned OFF (UG p. 68 (2-32); PG pp. 102-105 (2-78 to 2-81)). The UG's front-panel procedure mentions pressing OK when stopping (p. 68); the PG's `:REC OFF` description does not (p. 105) - **unverified** whether a prompt blocks the SCPI path. No timestamp or clock field is documented for the file. | `:RECorder:PERIod <1-99999>`, `:RECorder:MEMory {1..10},<name>`, `:RECorder:MMEMory D:\<name>.ROF`, `:RECorder:DESTination?`, `:RECorder[:STATe] {ON|OFF}` (pp. 102-105); example p. 186 (3-4). |
| **Analyzer** (standard on "+A" models, option AFK-DP800 otherwise) | Opens a stored `*.ROF`, analyses V, C or P between a start and end time, returns Group count, Median, Mode, Average, Variance, Range, Min, Max, Mean deviation; **`:ANALyzer:VALue? <t>` returns V, I, P at one record time** - the only documented way to read record data over SCPI (`:MMEMory:LOAD` loads RSF/RTF/RDF files into the instrument, PG p. 67 (2-43); nothing transfers a file to the host). When a file holds more than 2048 groups the analysable end time is capped at `period x 2048` (PG p. 28 (2-4)). | `:ANALyzer:MEMory {1..10}`, `:ANALyzer:MMEMory <D:\file.ROF>`, `:ANALyzer:FILE?`, `:ANALyzer:STARTTime`, `:ANALyzer:ENDTime`, `:ANALyzer:CURRTime`, `:ANALyzer:OBJect {V|C|P}`, `:ANALyzer:ANALyze`, `:ANALyzer:RESult?`, `:ANALyzer:VALue? <time>` (pp. 26-31 (2-2 to 2-7)); example p. 187 (3-5). |
| **Protections and status** (for the safety design) | OVP/OCP settable 1 mV-66 V / 0.1 mA-1.1 A on the DP821A CH1 (DS p. 4), accuracy **0.5 % + 0.5 V / 0.5 % + 0.5 A** (DS p. 5): a 26 V OVP may act anywhere between about 25.4 V and 26.6 V. OVP/OCP turn the output off and latch a flag that `:OUTP:OVP:QUES?` / `:OUTP:OCP:QUES?` report as YES until cleared (PG pp. 78-85). Channel questionable summary register bits: 0 = CC (voltage unregulated), 1 = CV, 2 = OVP, 3 = OCP; both 0 and 1 false = output off (PG p. 20 (1-10)). `:MEASure:ALL? CH1` returns V, I and P in one query (PG p. 58 (2-34)). | `:OUTPut:OVP:VALue`, `:OUTPut:OVP[:STATe]`, `:OUTPut:OVP:QUES?`, `:OUTPut:OVP:CLEAR`, same for OCP (pp. 78-85); `:STATus:QUEStionable:INSTrument:ISUMmary1:COND?` (p. 20); `:OUTPut:CVCC?` (p. 77 (2-53)). |

### The DP821A CH1 output speed, which bounds every "edge" claim

DS p. 5, "Voltage Programming Control Speed (1% within the total variation
range)" (the heading is quoted as printed; the datasheet does not define it
further), DP821A CH1:

| | Full load | No load |
| --- | ---: | ---: |
| Rise | < 110 ms | < 30 ms |
| Fall | < 110 ms | < 800 ms |

(CH2: rise < 15 ms, fall < 20 ms loaded / < 400 ms unloaded.) The same table
appears in UG p. 125 (5-3). Two other numbers are often mistaken for a slew
spec: "Transient Response Time < 50 us" is the recovery to within 15 mV after
a full-to-half load change (DS p. 5), and "Command Processing Time < 118 ms" is
the maximum time for the output to change after an `APPLy`/`SOURce` command
(DS p. 5, Note 2 p. 6). None of these is a guaranteed 10 ms edge, and none has
been measured on the bench unit: the project's wording "the supply's own,
uncharacterised slew" stays correct, now with a datasheet upper bound. Note
the no-load fall of up to 800 ms: every downward step taken while the DUT is
in UVLO (drawing nothing) may use most of a second, so a 1 s hold at such a
level is not a 1 s hold at the target.

## Answers to the seven questions

1. **Timer.** 1-2048 groups x 1-99999 cycles, each group voltage/current/time,
   time in whole seconds from 1 s (sub-second unverified), end state output
   OFF or hold last; started by `:TIMER ON` with the output already ON (no
   external or hardware start source is documented); editable over SCPI one
   group per command (or by template); read back in one block with
   `:TIMER:PARAMETER? 0,<n>`. CH1 output speed as in the table above.
2. **Delayer.** On/off groups in whole seconds, 1 s minimum, so it cannot
   produce a 100 ms dropout or any micro-interruption; it can produce exactly
   timed 1 s and 2 s interruptions and 1-10 s recoveries, with its own V/I/P
   stop condition.
3. **Monitor.** Any AND/OR combination of `<`/`>` thresholds on V, I, P of a
   channel; action output OFF, screen warning, beeper; reaction time not
   specified. It is an instrument-side cutoff independent of the Pi and the
   LAN, but it runs in the same firmware as the Timer and watches the source
   terminals, not the converter output (brief §7.4: source OVP is not
   independent protection of the converter output). The DL3031A's CC-mode
   voltage and current limits that the project already programs stay the
   output-side protection.
4. **Trigger I/O.** On the DP800 family the digital I/O is standard on the "A"
   models and an option (DIGITALIO-DP800) on DP832/DP831/DP822/DP821/DP813/
   DP811; the DP821A has it (DS p. 1 and p. 6). Whether the bench unit's
   connector terminal is present and the function installed is a bench check.
   A trigger input can turn CH1 output ON, OFF or toggle it; it cannot start
   the Timer. A Pi GPIO (3.3 V logic) matches the documented input levels
   (high 2.5-3.3 V, low 0-0.8 V); whether the DL3031A can drive such a line is
   not answerable from the DP800 documents and is left to the DL3000 note.
   A trigger output can flag "output went OFF" or a V/I/P threshold to a Pi
   GPIO as a hardware event line.
5. **Recorder/Analyzer.** 1 s minimum period, 2048 points internal (about
   34 min at 1 s), readable only one point per `:ANALyzer:VALue?` query plus
   summary statistics. Its timebase is the instrument's own (period counts
   from `:REC ON`), free of LAN jitter, but it is the same 1 s granularity and
   the same readback ADC as `:MEAS`, so it does not resolve ms events or
   settle the project's ADC-freshness question
   ([m2-qualification-plan.md](../m2-qualification-plan.md) Gap A). What it
   adds is an instrument-side log that survives a Pi failure and a clean,
   evenly spaced record of what the output did during an autonomous program.
6. **Clause verdicts** - the table in the next section.
7. **Safety design** - the section after it.

## Clause-by-clause verdicts: current (LAN-stepped) versus instrument-timed

Verdict names are those of `standards.py` and `docs/standards/README.md`. The
current column is the seeded real profile's verdict from
[iso16750-2.md](iso16750-2.md); parameters are the ones recorded there and are
cited by clause number only. "Policy bound" means the 720 s per phase and
660 s per run limits the project enforces today; whether an instrument-timed
program may run longer is the owner's decision, not a capability fact.

| Clause | Current verdict (real profile) | Instrument-timed realisation | Verdict with instrument timing | Token / contract change |
| --- | --- | --- | --- | --- |
| 4.2 DC supply voltage | `runs_here` by LAN steps (24 V: 28 V and 32 V above the 26 V guard) | Timer program of about 20 groups: holds of t1 = 30 s and t2 = 60 s at UA, Usmin, Usmax; the 1 V/s transitions as 1 V groups of 1 s (12 V code C: 14 -> 9 -> 14 -> 16 -> 14 V, about 225 s total). Monitor `>V` just above Usmax and `>C` at the current limit, end state OFF. | `runs_here`, instrument-timed: the 1 V/s rate becomes exact to the instrument's 1 s clock instead of the LAN cadence; the step edge is still the supply's < 110 ms / < 800 ms slew, inside each 1 s group. The 26 V guard condition at 24 V is unchanged. | add `dc_step_instrument_timed` (see below); the profile gains a declared sequencer |
| 4.3.1.1 long-term overvoltage, 12 V | `needs_split` (3600 s hold > 660 s deadline and 720 s timer) | One Timer group: 18 V for 3600 s (within the 99999 s range), end state OFF; Monitor `>V` between 18 V and the OVP. The instrument, not the Pi, ends the hold. | Still `needs_split` under the 720 s policy bound. Becomes a long-run candidate only if the owner approves an instrument-timed bound of 3600 s plus margin; the (Tmax - 20) K conditioning is still absent and recorded as a deviation. | none (bound is policy); `envelope()` would carry `max_program_s` |
| 4.3.1.1, 24 V | `outside_dut_rating` (36 V = DUT ceiling) | not attempted | unchanged | none |
| 4.3.1.2 jump start (12 V only) | `needs_instrument` (`edge_10ms`) | The Timer can hold 26 V for 60 s, but the transitions from and to 10.8 V are the supply's own slew (< 110 ms loaded; up to 800 ms falling unloaded), ten to eighty times the <= 10 ms the clause allows; 26 V also equals the approved guard. | unchanged `needs_instrument`; a deviation run is not recommended | none |
| 4.3.2 transient overvoltage | `needs_instrument` (`pulse_ms`) | 400 ms pulses with 1-2 ms edges cannot be expressed in whole seconds | unchanged | none |
| 4.4 superimposed AC | `needs_instrument` (`ac_superposition`) | The Sine template is a staircase with >= 1 s per point; 10 Hz to 200 kHz is out of reach by five orders of magnitude | unchanged | none |
| 4.5 slow decrease and increase | `mock_only` on real; 1680 s (12 V) / 3360 s (24 V) per direction exceed the deadline | Timer staircase at whole-second intervals: 25 mV every 3 s = 0.500 V/min (at the clause's 25 mV step ceiling) or 17 mV every 2 s = 0.51 V/min (inside it; 1 mV programming resolution, DS p. 5). 12 V: 14 -> 0 -> 14 V in one program of 1121 groups at 25 mV / 3 s (3360 s). 24 V: 1120 groups per direction, so one program per direction (3360 s each), because both directions would need 2241 > 2048 groups. The recorder needs a period of 2 s to keep 3360 s inside its 2048 internal points. The project's current 20 mV / 2.4 s realisation is not representable in whole seconds and would change. | Still `needs_split` under the 720 s policy bound (a direction cannot be split without pausing the ramp). With an approved long-run instrument-timed bound it becomes `runs_after_approval` exactly as on the simulated bench: levels below 9 V still need the UVLO-style approval of the saved recipe. | `dc_step_instrument_timed`; `SupplyProfilePolicy.step_interval_s` must be a whole number of seconds for this realisation |
| 4.6.1.1 momentary drop | `needs_instrument` (`pulse_ms`, `edge_10ms`) | 100 ms drop impossible in whole seconds; fall slew up to 800 ms unloaded | unchanged | none |
| 4.6.1.2 micro-interruption | `needs_instrument` (partial: the >= 1 s subset by LAN output OFF/ON) | Delayer program: ON (base level) for the recovery, OFF 1 s, ON >= 5 s, OFF 2 s ...; case 2: OFF 1 s then ON 1, 2, ... 10 s, each exactly timed by the instrument; `:DELAY:STOP >C,<limit>` as the built-in cutoff, end state OFF. Only 1 s and 2 s interruptions are representable (the LAN method's nominal 1.1-1.9 s steps are not), and the output-OFF state is still not a demonstrated >= 10 MOhm open with a <= 10 us transition. | unchanged `needs_instrument`, coverage partial; the >= 1 s subset becomes exactly timed and Pi-independent | optional `output_interrupt_instrument_timed_1s`; otherwise none |
| 4.6.2 reset behaviour | `mock_only` on real (295 s of declared holds fit the envelope) | Timer program of 41 groups (12 V code C): 9 V for 10 s, then 8.55, 8.10 ... 0.45, 0 V each 5 s alternating with 9 V for 10 s; about 310 s, inside 720 s; Monitor `>V` above 9 V and `>C` at the limit, end state OFF. The Pi performs the functional test during each 10 s recovery from its ~1 s polls. Downward steps into UVLO use the unloaded fall (< 800 ms) inside the 5 s hold. | `runs_after_approval` once a real instrument-timed procedure exists and is approved: the levels below 9 V need the UVLO-style approval, as on the simulated bench today | `dc_step_instrument_timed` |
| 4.6.3 starting profile | `needs_instrument` (`pulse_ms`) | 5-100 ms timings impossible | unchanged | none |
| 4.6.4 load dump, 4.7 reversed voltage, 4.10.x short circuit / overload | `excluded_by_policy` | not attempted; the DP821A is single-quadrant | unchanged | none |
| 4.8 ground and supply offset | `needs_instrument` (`floating_offset_source`) | CH2 wired in series as a +/-1 V offset would be a combined-source configuration (brief §3.2 excludes it), the UG does not state CH1/CH2 isolation (DS p. 1 only says "some channels are isolated"), and a negative offset needs reversed wiring | unchanged | none |
| 4.9.1 / 4.9.2 line interruption | `needs_instrument` (`line_switch_10Mohm`) | The Delayer can time the 10 s opens exactly, but output OFF is not a demonstrated >= 10 MOhm open and the transition is not shown to be <= 10 ms | unchanged | none |
| 4.11 / 4.12 | `not_on_this_bench` | - | unchanged | none |

Net effect: instrument timing changes **how well** the project runs the
clauses it can already hold as DC levels (4.2, 4.6.2, and 4.3.1.1 / 4.5 if a
longer bound is approved) and removes the Pi from the timing path; it changes
**no** `needs_instrument` verdict. A transient generator or a fast
programmable source is still needed for every edge, pulse, ripple and
interruption clause.

Proposed token: `dc_step_instrument_timed` - "DC levels sequenced by the
source's own timer: whole-second holds from 1 s, up to 2048 groups, program
ends with output OFF; the step edge is the supply's own slew (DP821A CH1
< 110 ms loaded rise/fall, < 800 ms unloaded fall, datasheet upper bounds, not
characterised)". Granted only when the bench profile declares a sequencer
(`source.sequencer.kind: dp800_timer`), so `mock.yaml` earns it only if it
emulates one. `envelope()` gains `max_program_s` from the profile so
`feasibility()` can compare `longest_phase_s` with the instrument-timed bound
instead of (or in addition to) the 660 s / 720 s constants.

## Safety design for an instrument-run program

The property to keep (brief §7.4): no state of the Pi, the LAN or the worker
process may leave the DUT energised without a bound, and no ambiguous state is
ever resolved by assumption. An autonomous Timer program is attended (the
operator stays at the bench, the Pi keeps polling and can stop it); the Pi
simply stops being the sequencer. The order below mirrors `extended.py`.

1. **Preconditions (read-only).** `*IDN?` names the DP821A; `:OUTP? CH1/CH2`
   OFF; `:TIMER?` and `:DELAY?` OFF; `:MONI?` read and recorded; no latched
   alarm (`:OUTP:OVP:QUES? CH1`, `:OUTP:OCP:QUES? CH1` = NO); load input OFF.
2. **Protections first, verified** - unchanged: `apply_source_protections`
   (OVP/OCP value + enable + QUES = NO read-back), `enable_source_otp`, the
   load's CC voltage and current limits. The program's highest level must sit
   below the OVP minus its 0.5 % + 0.5 V accuracy band, and the Monitor's
   `>V` threshold between the two so the Monitor, which can only be comparing
   the instrument's own readback (accuracy 0.1 % + 25 mV, DS p. 5), acts
   before the OVP.
3. **Program, then read it all back before anything is energised.**
   `:INST:NSEL 1` (verified), `:TIMER:GROUPS n`, `:TIMER:CYCLES N,1`,
   `:TIMER:ENDSTATE OFF`, one `:TIMER:PARAMETER k,V,I,t` per group, then
   `:TIMER:GROUPS?`, `:TIMER:CYCLES?` (must be `N,1`), `:TIMER:ENDSTATE?`
   (must be `OFF`) and `:TIMER:PARAMETER? 0,n` parsed with the same
   definite-length-block discipline as `_delay_parameter`: exactly n groups,
   each voltage within 1 mV and current within 0.1 mA of the plan, each time
   the planned whole number of seconds; any extra, missing or differing group
   aborts. The compiler refuses a program whose level exceeds the approved
   input guard, whose current exceeds `source_current_limit_A`, whose total
   duration (sum of group times x cycles) exceeds the bench profile's
   `max_program_s`, or whose levels below the DUT minimum lack the UVLO-style
   approval - the same rules planning applies today.
4. **Monitor as the instrument-side level cutoff.** `:MONI:VOLT:COND >V,OR`,
   `:MONI:VOLT <ceiling>`, `:MONI:CURR:COND >C,OR`, `:MONI:CURR <limit>`,
   `:MONI:POWER:COND NONE` (or `>P`), `:MONI:STOP OUTOFF,ON`, `WARN,ON`,
   `BEEPER,ON`, `:MONI ON`, each verified by its query. `<V` is not usable
   during profiles that visit 0 V. State honestly in the run record that the
   Monitor is independent of the Pi, not of the instrument's firmware, and
   that its reaction time is unspecified. (It can also be added to today's
   LAN-stepped procedures without the Timer, at low cost, after bench check
   B4 below.)
5. **Independent time bound.** With the Timer running, the Delayer is
   unavailable, so the bound is the program itself: finite cycles and end state
   OFF make the instrument de-energise the DUT at `total_duration_s` without
   any Pi action. The policy today caps that at 720 s per phase; programs
   longer than that need an owner-approved `max_program_s`, and the Pi's
   software deadline must then be at least the program length plus margin or
   it would stop a healthy program half-way.
6. **Start.** Set `:SOUR1:VOLT` and `:SOUR1:CURR` to group 0's values with the
   output OFF (existing cold-start path, read back), `:OUTP CH1,ON` (verified),
   `:REC ON` (if recording), then `:TIMER ON`; verify `:TIMER?` = ON and
   `:OUTP? CH1` = ON, record the Pi's monotonic and UTC time of the `:TIMER ON`
   write as the program's t0. Enable the load only after the unloaded startup
   check, as today.
7. **While it runs.** The Pi polls `:MEAS:ALL? CH1` (one query for V, I, P),
   the load's V and I, `:TIMER?`, `:OUTP? CH1` and `:OUTP:OVP:QUES?` /
   `:OUTP:OCP:QUES?` (or the ISUMmary1 condition register) each cycle at the
   usual ~1 s. It derives the expected level from the program and the elapsed
   time with a +/- 1 s plus 118 ms command-latency tolerance, and scopes the
   expected-off rule to that level exactly as `SupplyProfileProcedure` does by
   `level_kind`. Absolute limits apply at every poll; `:TIMER?` turning OFF
   before `total_duration_s`, an output OFF the Pi did not command, or an
   alarm flag ends the run as a fault with the cause recorded.
8. **Stop (controlled or urgent).** `:OUTP CH1,OFF` first and verify
   (de-energise), then `:TIMER OFF` and verify, then load input OFF, then
   `:REC OFF`, then `:MONI OFF`; each step with the transport's bounded
   timeout, each result recorded, independent attempts per instrument (an
   error on one never skips the other). If output OFF cannot be verified,
   leave the Timer running: it ends with output OFF at `total_duration_s`,
   and the record says `UNKNOWN` with that reason, as the Delayer path does.
   Whether `:TIMER OFF` mid-program leaves the setpoint at the current group
   or elsewhere is unverified (bench check B3), which is why output OFF comes
   first.
9. **Evidence of what the instrument did.** In `run.json["method"]`: the
   compiled program, the verbatim read-back block, the Monitor read-backs, the
   OVP/OCP values, `total_duration_s` and the policy bound, t0 of `:TIMER ON`
   and the time of every `:TIMER?` poll and of the stop sequence; in
   `scpi.jsonl` the full transcript as today; in `raw/samples.jsonl` the Pi's
   polls; in `raw/events.jsonl` `timer_on`, `timer_ended`, `monitor_tripped`,
   `timer_off`. After de-energising: `:ANAL:MEM <slot>`, `:ANAL:FILE?`,
   `:ANAL:STARTT`, `:ANAL:ENDT`, then `:ANAL:VAL? t` for every record time
   into `raw/instrument_record.jsonl` (`{t_s, Vin_V, Iin_A, Pin_W}` with the
   recorder period and t0 as its timebase statement) and `:ANAL:RES?` for V,
   C and P into a summary. The recorder uses a dedicated internal slot named in
   the bench profile; `:REC:DEST?` is recorded before and after so no user
   file is overwritten silently. Reading 2048 points one query at a time takes
   minutes and happens with everything OFF.
10. **What still cannot be guaranteed.** The Pi cannot see events shorter
    than its polling interval, and neither can the recorder (1 s). The
    supply's slew is bounded by the datasheet, not characterised on this unit.
    The Monitor's reaction time is unspecified, and it shares firmware with the
    Timer: a firmware fault could defeat both. Whether a Monitor, OVP or OCP
    trip stops the Timer or leaves it counting with the output OFF, and whether
    the output stays OFF for the remaining groups, is not documented (bench
    checks B2, B3); the design above does not depend on it only because Timer
    groups never turn the output ON, unlike Delayer groups, which do - a
    Delayer program for 4.6.1.2 with later ON groups needs B5 answered before
    it is allowed. The Pi's and the instrument's timebases are aligned only at
    t0. Everything the project says about ordinary polling (brief §2: no
    ripple, transient, inrush or load-step claims) applies to the instrument's
    record as well.

Creative additions worth a bench check, not part of the baseline: a Pi GPIO
driven into a trigger input configured `LOW` level -> output OFF as a dead-man
line (the line falls when the worker, the Pi or its power dies; while LOW the
output cannot be turned on), and a trigger output configured `OUTOFF` -> level
into a Pi GPIO as a sub-second "output went off" event line faster than the 1 s
poll. Both are independent of the LAN stack but still of the DP800 firmware.

## Implementation outline: a `SupplyProgram` adapter in the project's terms

Mechanism in benchctl, policy in dcdc_bench, as the existing split demands.

| Piece | Where | Content |
| --- | --- | --- |
| Contract | `src/dcdc_bench/domain.py` | `ProgramGroup(voltage_V, current_A, duration_s: int >= 1)`; `SupplyProgram(groups <= 2048, cycles = 1, end_state = "OFF", monitor: {voltage_ceiling_V, current_ceiling_A, power_ceiling_W | None}, recorder: {period_s: int, slot: 1-10, filename})` with derived `total_duration_s`; `BenchProfile.source.sequencer: {kind: "dp800_timer", max_program_s, recorder_slot}`; `SupplyProfilePolicy.realisation: "lan_steps" | "instrument_timed"` with `step_interval_s` required to be a whole number of seconds when instrument-timed. |
| Compiler | `src/dcdc_bench/supply_programs.py` (new) | `compile_program(test, policy, recipe_parameters) -> SupplyProgram` for `steady_state_load_sweep` recipes derived from 4.2 (holds and 1 V / 1 s groups), `slow_supply_ramp` (groups from `live_steps` at whole-second intervals) and `reset_staircase` (low/recovery groups); refuses levels above the guard or below the DUT minimum without approval, more than 2048 groups, totals above `max_program_s`; pure function, fully unit-testable. |
| Driver | `Software/src/benchctl/drivers/rigol_dp800.py` (or a sibling `rigol_dp800_sequencer.py`) | `timer_program(groups)`, `timer_readback(count) -> list[ProgramGroup]` with the `#9` block parser (generalising `_delay_parameter`), `timer_state()`, `timer_on()`, `timer_off()`, `monitor_configure(...)`, `monitor_readback()`, `monitor_off()`, `recorder_start(period, slot, name)`, `recorder_stop()`, `analyzer_open(slot)`, `analyzer_value(t)`, `analyzer_result(obj)`; every write followed by error-queue drain and read-back, no limit logic. |
| Procedure | `src/dcdc_bench/supply_profiles.py` + a real-path sibling of `SupplyProfileProcedure` | Level schedule from elapsed time instead of `ctx.step_input`; the same guards, `level_kind` scoping, attempt bookkeeping and point qualification; startup and load enable unchanged; stop order as in the safety design; record read-back as a finalisation step. |
| Planning and real path | `planning.py`, `real_backend.prepare_real_plan` | Lift `REAL_HARDWARE_NOT_APPROVED` for `slow_supply_ramp` / `reset_staircase` only when the bench declares the sequencer and the recipe is approved; compare `total_duration_s` with `max_program_s`; carry the warning that the source runs the program and the Pi only watches. |
| Catalog | `standards.py`, `docs/standards/*.md`, `tests/test_standards.py` | Token `dc_step_instrument_timed`, `envelope().max_program_s`, verdict text "instrument-timed", the clause table rows above. |
| Evidence | run folder | `run.json` method block, `raw/instrument_record.jsonl`, `raw/events.jsonl` entries, `scpi.jsonl`; report section "Source program" with the program, read-back and the recorder trace next to the Pi's polls. |

Effort estimate (one engineer, with the existing test harness): contract and
compiler 1 day; driver methods with fake-transport tests 1.5 days; real-path
procedure and stop sequence 2 days; planning, catalog and documentation
1-1.5 days; bench checks below half a day plus the owner's approval
decisions: about 6-7 working days before the first supervised 4.2 or 4.6.2
instrument-timed run, excluding any long-run policy change for 4.3.1.1 / 4.5.

## Open questions needing a bench check

Read-only (no state change; fit the `doctor` allowlist style, both outputs
OFF):

- R1. `*IDN?`, `:SYST:VERS?`: model DP821A and firmware version (the PG is the
  2021 edition; command behaviour may differ on older firmware).
- R2. Installed functions: `:MONI?`, `:MONI:STOP?`, `:TRIG:IN? D0`, `:REC?`,
  `:REC:PERI?`, `:REC:DEST?`, `:ANAL:FILE?` - a valid reply versus an error
  shows whether Monitor, Trigger, Recorder and Analyzer are present (also
  visible under Utility > Option, UG p. 104 (2-68)). Whether the rear
  digital I/O terminal block is fitted.
- R3. Current timer program and settings: `:TIMER?`, `:TIMER:GROUPS?`,
  `:TIMER:CYCLES?`, `:TIMER:ENDSTATE?`, `:TIMER:PARAMETER? 0,5` - confirms
  the block format and whether times read back as integers.
- R4. Current Monitor thresholds: `:MONI:VOLT:COND?`, `:MONI:VOLT?`,
  `:MONI:CURR:COND?`, `:MONI:CURR?`, `:MONI:POWER:COND?`, `:MONI:POWER?`.

Writes (outputs OFF, no DUT connected; need the owner's authorisation and a
resistor or the DL3031A as the load where output ON is required):

- B1. Timer parameter resolution: write a 3-group program including a 1 mV
  voltage and a 1.5 s time with the output OFF, read it back - does the
  instrument keep millivolts and accept or round fractional seconds?
- B2. Run a 3-group program into a resistor with the Recorder at 1 s and the
  Monitor armed above the top level: does `ENDSTATE OFF` turn the output off;
  does `:REC OFF` store the file without a front-panel prompt; does
  `:ANAL:VAL?` return the points; how long does reading 2048 points take?
- B3. Stop semantics: `:TIMER OFF` mid-program - does the setpoint stay at the
  current group; does the output stay ON? (Confirms the output-OFF-first
  order.)
- B4. Monitor and OVP trips during a running program (set `>V` below a
  programmed level): does the output go OFF, does `:TIMER?` stay ON, does the
  output stay OFF for the remaining groups, is `:OUTP:OVP:CLEAR` needed before
  the next ON? Reaction time measured with a scope against a DL3031A load
  step for a `>C` condition.
- B5. Delayer with later ON groups after a stop-condition or OVP trip: does
  any later group re-energise the output? (Gate for any 4.6.1.2 Delayer
  program.)
- B6. Output step speed of CH1 with a scope: 10 V steps up and down, loaded
  and unloaded - the first characterisation of the slew the project has only
  bounded from the datasheet.
- B7. Trigger input as a dead-man line from a Pi GPIO (`LOW` level -> output
  OFF): latency, behaviour on Pi reset, and whether a persistent LOW blocks
  `:OUTP CH1,ON` as intended.
