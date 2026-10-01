# A switch box between the DP821A and the converter: design document

Design document, 2026-10-01, documents only: no code was changed, no
instrument was connected, no part was ordered. It develops the owner's idea
recorded in [best-effort-proposal.md](best-effort-proposal.md) §8 ("A switch
box"): a relay (or MOSFET) switch between the Rigol DP821A and the converter
under test, so that the ISO 16750-2 interruption and line-switch clauses can
be run with a real open circuit and the switch's own edges instead of the
supply's slew (DP821A CH1: rise < 110 ms loaded, fall < 800 ms unloaded,
datasheet bounds, [instrument-sequencing-dp800.md](instrument-sequencing-dp800.md)).

Everything here is built on the project's documents: the clause parameters of
[iso16750-2.md](iso16750-2.md), the instrument facts of the DP800 and DL3000
studies, the best-effort status model and the owner's decisions of
2026-10-01, the capability tokens of `src/dcdc_bench/standards.py`, the
envelope of [../configured-runs.md](../configured-runs.md) and the protective
rules of [../implementation-brief.md](../implementation-brief.md) §7. Clause
parameters are cited by clause number only (brief §16). No part numbers are
given: the box is described by the classes and ratings to look for, and every
figure that depends on a part the owner has not yet chosen, or on a converter
property the DUT profile does not record, is marked as such.

**Basis tags** used on numbers in this page:

| Tag | Meaning |
| --- | --- |
| `ISO` | parameter of ISO 16750-2:2023 as recorded in [iso16750-2.md](iso16750-2.md), cited by clause; `ISO-fig` marks a figure value (4.6.1.1's 4.5 V / 100 ms, confirmed by the owner on 2026-10-01) |
| `DP` | DP800 facts via [instrument-sequencing-dp800.md](instrument-sequencing-dp800.md): CH1 0-60 V / 0-1 A, CH2 0-8 V / 0-10 A (brief §3.2); CH1 slew bounds above; CH2 rise < 15 ms, fall < 20 ms loaded / < 400 ms unloaded; command processing < 118 ms; digital I/O D0-D3 standard on the DP821A, input high 2.5-3.3 V / low 0-0.8 V, output high 2.6-3.5 V / low 0-0.4 V; Timer and Delayer whole seconds 1-99999 s; OVP/OCP accuracy 0.5 % + 0.5 V / 0.5 % + 0.5 A |
| `DL` | DL3000 facts via [load-programs-dl3000.md](load-programs-dl3000.md): readback integrates 200 ms and refreshes about once a second; input resistance 350 kOhm with the input OFF; minimum operating voltage 1.3 V; rear analog Vmon/Imon outputs (scaling unverified); digital I/O 3.3 V; isolation of terminals from earth not stated |
| `LAN` | measured round trips of the project's queries: 4.1 ms min, 5.4 ms median, 36 ms p95, 55 ms max; poll period median 1.135-1.153 s (M2 evidence, via the proposal) |
| `ENV` | real-path envelope ([../configured-runs.md](../configured-runs.md)): programmed input 1-35.8 V, supply current limit 0.05-1 A, output current 0.05-2.5 A, 34 W, 660 s software deadline, 720 s one-shot source timer per phase, 1-2 s polling |
| `DUT` | `profiles/dut/12t12-4a.yaml`: 9-36 V input, 12 V / 4 A / 48 W, isolation unknown. **Input capacitance, input filter and reverse-polarity protection are not recorded**; where they matter below the text says so |
| `MOCK` | synthetic plant parameters (`adapters.py`): UVLO off below 8.6 V, hysteresis 0.5 V, standby 4 mA, cold-start delay 1 s, soft start 0.3 s, input lead 0.06 Ohm; all labelled synthetic |
| `class` | a value typical of a component class (PCB power relay, signal relay, logic-level MOSFET, Raspberry Pi 4 GPIO); it bounds nothing until the chosen part's datasheet or an acceptance test replaces it |
| `derived` | arithmetic on tagged numbers, shown inline |
| `UNV` | not stated in any document read; a bench check before it may be relied on |

## 0. Short answer

A two-pole normally-open relay in the converter's input leads, driven from
the Raspberry Pi's GPIO through an opto-isolated driver and gated by a
hardware heartbeat, gives this bench a true open circuit (4.9.1 method 1 on
either line, 4.9.2) and interruptions from about 100 ms upward (4.6.1.2's
100 ms, 1 s and 2 s steps), with the intervals stamped by the host clock. A
second relay selecting between CH1 and CH2 (CH2 preset to 4.5 V behind a
diode and a bleeder) turns 4.6.1.1 at 12 V into a switch-timed drop whose
edges no longer belong to the supply. Nothing in the box measures the
waveform at the converter terminals, so every terminal-side row of a
deviation sheet still reads "switch commanded; interval host-timed; terminal
waveform not measured" until a scope or DAQ exists (owner decision 5). The
sub-10 ms interruptions (10 ms, 1 ms, 100 us) need a MOSFET stage and a
microcontroller timebase, and the 100 us class also needs a scope to prove
the transition; that is the upgrade path, not the first build. The DPDT
reversal for 4.7 is drawn but stays a policy exception the owner must approve
while accepting converter damage. The box does not help 4.3.1.2, 4.3.2, 4.4,
4.6.3 or 4.8.

## 1. Purpose and what it unlocks

### 1.1 Clause by clause

"Today" is the real profile's verdict in [iso16750-2.md](iso16750-2.md) with
the best-effort changes of the proposal §3 and §8. "With the box" assumes the
first build (relay, GPIO) unless the row says MCU or MOSFET. The mechanism
names are the ones proposed for the deviation sheet (section 4.3).

| Clause | What the clause needs (`ISO`) | Today | With the box | Sheet rows that change |
| --- | --- | --- | --- | --- |
| 4.9.1 single line interruption, method 1 | one line open for 10 +/- 1 s, >= 10 MOhm, transition <= 10 ms; outputs active and inactive; mode 3.4 | `best_effort`, positive line only, open approximated by output OFF (OFF-state impedance `UNV`) | relay pole K1a opens the positive line, pole K1b the return line: both cases of method 1. 10 +/- 1 s host-timed (GPIO write to GPIO write, `LAN`-class jitter is irrelevant, Pi scheduling jitter of a few ms `class`): `met` as a host-clock measurement. Open >= 10 MOhm: `met` once acceptance test A7 has measured the open resistance and it is recorded in the bench profile. Transition <= 10 ms: the contact break is a sub-millisecond mechanical event preceded by the relay's release delay (`class` 2-10 ms, host-stamped); the voltage waveform at the DUT terminals is not measured: `unknown_until_measured` | open circuit from `approximated` to `met`; return-line case from not offered to offered |
| 4.9.1 method 2 | bursts of 100 us opens every 1 ms for 10 s, twice, transition <= 10 us | grey | **not with a relay.** MOSFET stage plus MCU timebase plus a scope to prove the 10 us transition (section 3.3) | none in the first build |
| 4.9.2 multiple line interruption | whole connector open for 10 +/- 1 s, >= 10 MOhm; modes 2.1 and 3.4 | `best_effort`, same stimulus as 4.9.1 on a two-wire input | K1a and K1b open together: both input lines of the two-wire input are open at the switch, not only de-energised. Mode 2.1 as converter enabled with the load input OFF, mode 3.4 bounded (1 A source) | as 4.9.1 |
| 4.6.1.2 micro interruption, case 1 | interruptions 10 us, 100 us, 1 ms, 10 ms, 100 ms, 1 s, 2 s; recovery >= 5 s; switch reaction <= 10 us; open >= 10 MOhm; base UB 12 / 24 V; mode 3.4 | `best_effort`, 100 ms `unknown` (two LAN writes), 1-2 s `met` by the Delayer only, <= 10 ms not offered | **relay + GPIO**: 1 s and 2 s `met` on the host clock (relay operate/release asymmetry `class` <= 10 ms is inside +/- 50 ms); 100 ms `unknown_until_measured` until acceptance test A5 characterises this relay's operate and release times, then `approximated` with the measured bound; 10 ms not offered (a 5-15 ms `class` operate time with bounce is the same size as the interval). **MOSFET + MCU**: 10 ms and 1 ms `approximated` with the MCU clock as the basis; 100 us only with a scope; 10 us not offered. Open >= 10 MOhm `met` as 4.9.1; switch reaction <= 10 us `not_met_but_documented` for a relay, scope-dependent for a MOSFET | 100 ms from two LAN writes to one host-timed switch interval; 1-2 s no longer Delayer-only; the >= 10 MOhm row |
| 4.6.1.2 case 2 | interruption >= 100 ms until reset; recovery 100 us, 1 ms, 10 ms, 100 ms, 1 s, 10 s | 1-10 s recoveries only | recoveries 100 ms and above with the relay; 1-10 ms with MOSFET + MCU; 100 us scope-dependent | as case 1 |
| 4.6.1.1 momentary drop, 12 V | from Usmin 9 V to 4.5 V (`ISO-fig`) for 100 ms (`ISO-fig`), edges <= 10 ms; mode 3.4 | `best_effort`, variant B (1 s supply-timed) default, variant A (100 ms commanded) depth unknown | **selector relay K2**: CH1 at 9 V on one contact, CH2 preset to 4.5 V on the other (CH2 is 0-8 V / 10 A, `DP`, so it can source the level and the standby draw). The DUT side moves to CH2 for the commanded 100 ms. Duration: host-timed, `unknown_until_measured` until A5, then `approximated`. Depth: 4.5 V is a regulated level, no longer a slew that may not arrive: `met` as a bound once the CH2-branch drop (section 2.6) is measured at acceptance. Edges: the up edge is CH1 reconnecting a regulated 9 V onto the DUT's input capacitance (sub-ms `class`); the down edge is the DUT-side capacitance discharging into the bleeder of section 2.6, not the switch itself: both `unknown_until_measured`, but the datasheet-bound "not met" (< 110 ms / < 800 ms) disappears | all four rows; variant A becomes the honest default and variant B is no longer needed |
| 4.6.1.1, 24 V | from Usmin 10 V to 9 V (`ISO-fig`) for 100 ms | `best_effort` variant B | **not unlocked**: 9 V exceeds CH2's 8 V range (`DP`). Option for the owner: CH2 at 8 V, a 1 V deeper drop than the clause (outside the +/- 0.2 V tolerance, `not_met_but_documented`); otherwise this variant stays supply-timed | level row only if the owner accepts 8 V |
| 4.7 reversed voltage | case 1: -4 V for 60 s from Usmin 10.5 V, edges <= 10 ms, recovery 120 s; case 2: -14 V for 60 s from UB 12 V, fall <= 10 ms, rise <= 1000 ms; 24 V: -26 V (level to be verified on the owner's copy) | `excluded_by_policy` (brief §2, §7.5) | **physically possible with a DPDT reversal relay K3** (section 2.7): CH1 programmed to +4 / +14 / +26 V, then K3 transfers the polarity; the fall is a contact transfer, the rise is a transfer back (inside 1000 ms). **It remains fault injection excluded by the brief.** This document designs it only as a policy-exception recipe: the owner approves it explicitly, accepting that the converter may be damaged or destroyed; the DP821A current limit of 1 A (OCP 1.05 A latched, as the procedures program it) bounds the reverse dissipation to 4 / 14 / 26 W and 240 / 840 / 1560 J over 60 s (`derived`); the load is OFF and physically disconnected during the reversal (section 2.9) | the clause would move from `excluded_by_policy` to a new `policy_exception` state, never to `best_effort` |

### 1.2 What the box does not unlock

- **4.3.1.2 jump start** (26 V for 60 s from 10.8 V, edges <= 10 ms) and
  **4.3.2 transient overvoltage** (18 V from 16 V, 400 ms, 1 ms edges): both
  levels of each clause are above CH2's 8 V (`DP`), so a selector between two
  sources cannot hold them; a single channel cannot be at two levels at once.
  They stay as the proposal and the owner's decision 7 left them (jump start
  and 4.3.2 best effort by supply slew).
- **4.4 superimposed AC**: a switch has no ripple to offer.
- **4.6.3 starting profile**: more than two levels (US1, US, the base), 5-50 ms
  segments between them and a 2 Hz component. Switching between CH1 and CH2
  gives two levels; the third and the sub-second level changes would again be
  the supply's slew. Stays grey pending the owner's answer on a one-second
  approximation (proposal §8).
- **4.8 ground and supply offset**: dropped by the owner (decision 2).
- **4.6.4 load dump, 4.10.x short circuit and overload**: excluded by policy;
  the box has no role.
- **Any measurement.** The box changes what is commanded, not what is
  observed. Supply and load readbacks still refresh about once a second
  (`DP`, `DL`); anything shorter than the poll interval remains invisible to
  them, and the rule of brief §2 (no waveform claims from DC polling) is
  unchanged. "Achieved" stays reserved for scope- or DAQ-measured values
  (owner decision 3).
- **Mode 3.4 (rated load)** stays unreachable from a 1 A source; every
  verdict keeps that condition.

### 1.3 Capability tokens and the claim wording

Tokens are granted by `standards.capabilities()` only from a declared
`bench.switch` block (section 4.4), never inferred from a relay module's
presence or an identity string. Proposed rules:

| Token | Granted when | Not granted when |
| --- | --- | --- |
| `line_switch_10Mohm` (exists) | `switch.kind` is `relay` or `mosfet_bidirectional`, the poles cover the line the clause names, and `switch.acceptance.open_resistance_Mohm >= 10` is recorded | the acceptance record is missing; a single MOSFET (its body diode is a conductor in one direction, section 2.8) |
| `switch_interrupt_host_timed` (new) | `switch.control: gpio`; the planner compares an interval with `switch.min_interval_s` (0.1 s for a relay) | intervals below `min_interval_s` |
| `switch_interrupt_mcu_timed` (new) | `switch.control: mcu`; `min_interval_s` 0.01 s with a relay, 1e-4 s with a MOSFET stage | without the MCU's firmware hash in the acceptance record |
| `two_source_selector` (new) | `switch.selector: true` and the CH2 branch's measured level offset is recorded (section 2.6) | the 24 V drop level (9 V) exceeds CH2's range: the planner refuses by level, not by token |
| `polarity_reversal_switch` (new) | `switch.reversal_fitted: true` **and** the recipe carries the 4.7 policy exception of section 2.7 | always otherwise; `negative_voltage` stays a source property and is never granted by a switch |
| `edge_10ms`, `pulse_ms`, `pulse_us` (exist) | **not granted by the box.** `pulse_ms` would make 4.3.2 and 4.6.3 look feasible, which the box cannot deliver; `edge_10ms` and `pulse_us` describe a terminal waveform that nothing here measures. 4.6.1.1 and 4.6.1.2 instead gain an alternative requirement set (`Clause.needs_any`, section 4.4): `two_source_selector + switch_interrupt_*` for 4.6.1.1, `line_switch_10Mohm + switch_interrupt_*` for 4.6.1.2 | - |

Claim wording, chosen by `switch.control` and written by the deviation-sheet
template without free text:

- GPIO: "switch commanded; interval host-timed (Raspberry Pi monotonic clock,
  GPIO write to GPIO write); terminal waveform not measured".
- MCU: "switch commanded; interval MCU-timed (crystal timebase, firmware
  `<hash>`); terminal waveform not measured".
- With a bound capture channel (owner decision 5, not yet): the row becomes
  `measured_by_bench: true` and may say "measured".

## 2. Electrical design

### 2.1 Topology

```
                         supply side                 |   switch box                      |  converter side
                                                     |                                   |
 DP821A CH1+ ---[TVS_s across CH1+/CH1-]-------------+------ K2:NC --+                   |
                                                     |               |                   |
 DP821A CH2+ --->|---+--- node B ---------------------+------ K2:NO --+-- K2:COM --- K1a (NO) --+-- [K3 pole 1] --- DUT IN+
          Schottky   |                               |                                       |
                    R_b (bleeder, to the return bus) |                           [TVS_d across DUT IN+/IN-]
                     |                               |                                       |
 CH1- ---+-----------+--- return bus ----------------+----------------------------- K1b (NO) --+-- [K3 pole 2] --- DUT IN-
 CH2- ---+                                           |                                   |
                                                     |   coils: K1a, K1b, K2, (K3)       |
                                                     |   driver: opto-isolated, own supply|
                                                     |   heartbeat gate on K1a/K1b       |
```

- **K1a, K1b**: the disconnect, one normally-open pole per input line.
  De-energised = both lines open = converter disconnected. Both coils are
  driven through the heartbeat gate (section 3.1); K1b is wired so that a
  link can bypass it when only the positive line is to be switched.
- **K2**: the selector for 4.6.1.1, SPDT, break-before-make. De-energised
  (NC) = CH1, the normal source; energised (NO) = the CH2 branch at the drop
  level. A driver failure therefore leaves the normal source selected, and
  K1 remains the fail-safe element regardless of K2's state.
- **CH2 branch**: Schottky diode and bleeder R_b, section 2.6. Fitted only
  when the selector is used; otherwise CH2 stays unconnected as today.
- **K3** (optional, 4.7 only): DPDT wired as a polarity reverser, de-energised
  = normal polarity. Section 2.7.
- **TVS_s, TVS_d**: suppressors across the supply-side terminals and across
  the DUT input terminals, deliberately not across any contact (section 2.3).
- **Returns**: CH1- and CH2- meet on the box's return bus. Whether they may
  be tied is bench check S2 (section 2.9).

### 2.2 Switching DC at up to 36 V and 2.5 A: the contact

The box must break up to 35.8 V DC (`ENV`) at up to 2.5 A (the output
envelope; the supply's own limit is 1 A, but the acceptance tests and a future
higher-current source should not oblige a rebuild) and make onto a capacitive
load. Three facts decide the contact class:

1. **The rating that matters is the DC rating, not the AC figure.** A relay
   marked "10 A 250 VAC" is routinely rated 10 A only up to about 30 VDC; above
   that its DC breaking capacity falls steeply because a DC arc has no zero
   crossing to extinguish it (`class`: many general-purpose relays fall to a
   fraction of an ampere by 60-110 VDC). 36 V sits in the knee of such curves.
   Look for a datasheet that states the DC breaking capacity at **>= 36 VDC
   and >= 3 A resistive**, or that publishes the DC load curve; if the chosen
   relay is rated only to 30 VDC, either restrict the box to 12 V-system
   clauses (levels <= 16 V plus the 26 V jump start, which the box does not
   serve anyway) or wire **two contacts in series** on each line, which
   doubles the arc gap. Not every manufacturer publishes a series derating;
   when none exists, the series pair is a bench-verified arrangement, not a
   rated one, and the acceptance tests (A6) must show no contact damage after
   the cycle count. The planner refuses any recipe level above
   `switch.contact_rating_V_dc` (section 4.4), so this choice decides which
   clauses the box may serve.
2. **Relay classes that fit** (choose by the DC figures above, in this order
   of preference): a PCB or panel **power relay with a DC-rated contact**
   (`class` 5-16 A, AgSnO2 or AgNi contacts, 12 V or 24 V coil, often with a
   2-pole version whose second pole gives the read-back contact of section
   4.1); an **automotive 12 V-coil power relay** (`class` 20-40 A at 14 VDC)
   is convenient for the 12 V-system clauses but many are not characterised
   above 16-24 VDC, so it serves the 24 V-system clauses only with a stated
   rating; a **DC-rated signal relay** (`class` 2-3 A at 30 VDC) is marginal
   for the arc at 36 V and the inrush of section 2.4 and is listed only
   because the task asked which classes to consider: not recommended as the
   disconnect.
3. **Contact resistance and the voltage tolerance.** Clause 4.1 allows
   +/- 0.2 V at the DUT terminals (`ISO`). At 2.5 A that is 80 mOhm for the
   whole added path (`derived`); at the supply's 1 A limit it is 200 mOhm.
   Relay contact resistance is specified as a maximum (`class` 50-100 mOhm
   initial) and is usually far lower when measured; two contacts in series
   double it; connectors and 1.5 mm^2 wire (`class` about 12 mOhm/m) add to
   it. CH1 has no remote sense (brief §3.2), so the supply cannot compensate
   the drop. The acceptance test A4 measures the closed-switch drop at 2.5 A
   and the recorded value enters the bench profile; the planner adds it to
   the level deviation row, and the longer-term answer is to move the Vin
   measurement to the DUT side of the box (owner question 8).

A MOSFET stage avoids the arc, the bounce and the wear, at the cost of the
reference, body-diode and gate-drive problems of section 2.8. The first build
is a relay.

### 2.3 Coil suppression, snubbers and the 10 MOhm budget

- **Flyback diode across every coil** (relay driver boards include one; verify
  on the chosen board). It lengthens the release time by a few milliseconds
  (`class`); a diode in series with a Zener or a TVS across the coil releases
  faster. The acceptance test A5 measures whatever the chosen arrangement
  gives.
- **Nothing across the contact.** The open circuit must present >= 10 MOhm
  (4.6.1.2, 4.9.1, 4.9.2, `ISO`). At 36 V that is a total leakage budget of
  3.6 uA across the open switch, 1.2 uA at a 12 V base (`derived`). A TVS or
  RC snubber across the contact would leak into that budget (`class` TVS
  leakage at stand-off is specified in microamperes) and would make the open
  circuit a resistor. Place suppressors across the **terminals** instead:
  TVS_s across CH1+/CH1- upstream of the switch absorbs the energy of the
  supply-side lead inductance when the contact opens (with `class` 1 uH per
  metre of lead at 2.5 A the stored energy is a few microjoules, `derived`;
  the supply's own output capacitor absorbs most of it; the TVS is insurance
  against the arc voltage), and TVS_d across DUT IN+/IN- downstream catches
  the kick of the converter's input filter inductance, if it has one (`DUT`
  does not record an input filter), which otherwise pulls the DUT-side node
  negative when the contact opens. Stand-off >= 40 V, clamp below whatever the
  converter's own input rating allows; the `DUT` records only the 36 V
  operating maximum, so clamp selection waits for the module datasheet
  (owner question 6).
- **The arc itself** at 36 V / 2.5 A is within a DC-rated contact's design;
  the TVS does not prevent it, the gap does. Contact life under DC break is
  the acceptance cycle count's business (A6).

### 2.4 Inrush on reconnection

Closing a contact between a regulated source and a discharged input
capacitance is a near-short for microseconds: the peak current is set by the
loop resistance and inductance, not by the DP821A's 1 A limit, which acts
after its regulator responds (transient response specified as recovery to
within 15 mV in < 50 us after a load change, `DP`; the output capacitor
supplies the first microseconds). Illustration only, because the converter's
input capacitance is not recorded (`DUT`): with 100 mOhm of loop resistance
and 36 V the theoretical peak is 360 A, lasting of order R x C, about 2 us per
20 uF (`derived`); real leads and the capacitor's ESR make it lower and
longer. This is exactly what a vehicle's switch delivers, so it is the
stimulus the clauses intend; the box must survive it, not soften it:

- choose a contact with an **inrush or capacitive-load rating** (`class`:
  lamp, "tungsten" or TV ratings, AgSnO2 contacts) and derate the steady
  rating accordingly;
- do **not** add a series inrush resistor or NTC: 1 Ohm would drop 2.5 V at
  2.5 A, far outside the +/- 0.2 V tolerance;
- keep the supply-side and DUT-side leads short and of equal gauge; the loop
  inductance is what limits di/dt;
- record in the deviation sheet that the reconnection inrush was not
  measured; a scope on a shunt or on the DL3031A Imon output is the only way
  to measure it (proposal §5).

Contact welding under inrush is the failure that defeats the fail-safe rule
(a welded K1 cannot open). The read-back contact of section 4.1 does not see a
weld on the power pole; the DUT-side voltage sense (upgrade in section 4.1)
does, and the acceptance test A6 checks for it after the cycle count.

### 2.5 Bounce and what the converter sees

On closure a relay contact bounces for `class` 1-5 ms, several make/break
events before it settles. For the converter each early break is a
micro-interruption while its input capacitance is partly charged: it may
begin a start-up, lose input, and start again, drawing an inrush each time.
The 12T12-4A's profile records a failed direct 12 V cold start (`DUT`) and
the synthetic plant models a 1 s delay and 0.3 s soft start (`MOCK`); whether the real converter's controller is upset by a
5 ms bounce train is unknown and is one of the things the box lets the owner
find out. On opening there is no bounce, but the arc stretches the break by
up to a millisecond (`class`).

Consequences: the "interruption" commanded as one open interval is, at the
contact, one open interval plus a bounce train at its end; the deviation
sheet records the bounce as "not measured; relay class <= 5 ms" in the first
build, as a count from the read-back contact with the MCU or the Pi's edge
interrupts in the upgrade, and as a waveform only with a scope. The 4.6.1.2
"switch reaction <= 10 us" row is `not_met_but_documented` for any relay.

### 2.6 The 4.6.1.1 selector branch

The drop asks the DUT input to go from Usmin to 4.5 V in <= 10 ms and back
(`ISO`, `ISO-fig`). Switching the DUT from CH1 (9 V) to CH2 (4.5 V) gives a
regulated drop level, but two details decide whether the edges are real:

- **CH2 cannot sink.** The DP821A is single-quadrant. When K2 transfers, the
  DUT's input capacitance is at about 9 V and CH2 is set to 4.5 V: the
  capacitance can only discharge through whatever load the DUT side has. Below
  its 9 V minimum the converter is in UVLO and draws a standby current
  (`MOCK` uses 4 mA; the real figure is unknown, `DUT`), so without help the
  fall from 9 V to 4.5 V would take C x dV / I, for example 20 uF x 4.5 V /
  4 mA = 22 ms (`derived`, illustration): the switch would not have produced
  the edge. Hence the **bleeder R_b** on node B, the CH2 side of K2: when K2
  transfers, the DUT-side capacitance discharges into R_b with a time constant
  R_b x C_in (10 Ohm x 20 uF = 0.2 ms, illustration) and then sits at CH2's
  level. R_b is on the CH2 branch, not across the DUT, so it loads nothing
  while CH1 is selected. At 4.5 V, 10 Ohm draws 0.45 A and dissipates 2 W
  (`derived`); rate the resistor >= 5 W and set CH2's current limit to cover
  R_b plus the converter's standby draw with margin (about 1 A), with CH2 OVP
  just above its setpoint.
- **CH2 is back-driven for a moment.** For the R_b x C_in time the node is
  above CH2's setpoint. Whether the DP800 tolerates a voltage above its 8 V
  range on an energised CH2 output, and whether its OVP would trip and switch
  CH2 OFF (which would ruin the level), is not documented (`UNV`). The
  **Schottky diode** from CH2+ to node B blocks the back-drive entirely at the
  cost of its forward drop (`class` 0.3-0.5 V at 0.5 A), which varies with
  current. CH2 is therefore set to 4.5 V plus the measured drop, and the
  acceptance test A8 measures the node B level with a DMM at the bleeder
  current; the result enters the bench profile as the selector's level offset
  and the level row of the sheet carries it. The no-diode variant (CH2 driven
  directly, relying on the sub-millisecond back-drive being harmless) is bench
  check S6, to be done on the pass-through fixture, never with the converter.
- **The up edge** is CH1, regulated at 9 V and unloaded during the drop,
  reconnecting onto the DUT capacitance at 4.5 V through K2's NC contact: the
  inrush of section 2.4 at a 4.5 V difference, sub-millisecond (`class`),
  unmeasured.
- **The transfer gaps.** K2 is break-before-make: for its transfer time
  (`class` a few ms) the DUT side is connected to neither channel and
  discharges only through the converter's standby draw, which at these
  capacitances is negligible over a few ms (`derived` from the illustration
  above). Both gaps lie inside the commanded 100 ms.
- **Grounds.** CH1- and CH2- are tied on the return bus so that the DUT-
  reference does not move when K2 transfers. Bench check S2 first.

At 24 V the drop level is 9 V (`ISO-fig`), above CH2's range; the selector is
not fitted for that system or CH2 is set to 8 V as a recorded deviation
(section 1.1).

### 2.7 The 4.7 reversal: a policy exception, not a feature

A DPDT relay K3 downstream of K1, wired as a polarity reverser, applies CH1's
programmed +4 V, +14 V or +26 V to the converter with reversed polarity for
the clause's 60 s. The brief excludes reverse-power tests (§2, §7.5) and the
standards catalog keeps 4.7 `excluded_by_policy` even if an instrument
existed. This design keeps that: K3 is drawn so the owner can see what it
costs, and it is fitted only if the owner answers question 2 with yes. If
fitted:

- it runs only under a recipe whose authorization block names a **policy
  exception** (`authorization.policy_exceptions: ["iso16750-2_4.7_reverse_voltage"]`)
  with the owner's recorded acceptance that the converter may be damaged or
  destroyed, next to `best_effort_approved` and the protective policy id; the
  planner refuses the recipe otherwise, and the bench page shows the clause in
  a distinct "policy exception" state, never as best effort;
- the DP821A current limit bounds the energy: 1 A at -4 / -14 / -26 V is
  4 / 14 / 26 W, 240 / 840 / 1560 J over 60 s (`derived`); what the converter
  does with it depends on its reverse protection, which `DUT` does not
  record: a series diode draws nothing, a shunt diode or an unprotected
  electrolytic takes the full 1 A; vented capacitors are possible, so the
  test is attended, with eye protection, as the brief requires of everything;
- the load is OFF and its leads are **physically disconnected** from the
  converter output before K3 transfers: if the converter is non-isolated
  (`DUT` isolation unknown) its output negative is its input negative, which
  the reversal lifts to +4 / +14 / +26 V against CH1-, and whether the
  DL3031A's input terminals float from earth is not stated (`DL`);
- K3 de-energised = normal polarity; K1 open before and after every transfer
  (section 4.5), so the reversal is never applied as a hot transfer;
- the -26 V level for 24 V systems is itself to be verified on the owner's
  copy ([iso16750-2.md](iso16750-2.md)).

### 2.8 Notes for a MOSFET stage (upgrade, not the first build)

- **Body diode.** A single MOSFET in the positive line conducts from DUT side
  to supply side through its body diode whenever the DUT side is the higher
  potential, which happens during the 4.6.1.1 drop (DUT capacitance at 9 V
  against the 4.5 V branch) and during any 4.7 reversal. A true open needs two
  MOSFETs back to back (common source), and that pair's leakage must fit the
  3.6 uA budget of section 2.3 (`class` logic-level MOSFET drain leakage is
  specified in microamperes at rated voltage: check it).
- **Reference and gate drive.** A high-side N-channel pair needs an isolated
  or charge-pump gate supply because the on state is indefinite (a bootstrap
  driver cannot hold it); a P-channel high-side needs a level shifter and
  parts with Vds comfortably above 36 V (`class` >= 60 V). A low-side switch
  in the return is simplest to drive but moves the converter's negative away
  from the return bus, with the alternate-path question of section 2.9.
- **Drop.** Rds(on) at 2.5 A must stay well inside the 80 mOhm budget:
  `class` < 20 mOhm per device, two in series, plus wiring.
- **Clamps**: across the terminals as in section 2.3, not drain to source; use
  parts with an avalanche rating for what remains.
- **Edge speed**: a gate driver switches the pair in well under a microsecond
  (`class`); the DUT-terminal edge is then set by the lead inductance, the
  input capacitance and the bleeder, and only a scope says what it was.
- **Thermal**: at 2.5 A and 40 mOhm the pair dissipates 0.25 W (`derived`);
  no heatsink, but the inrush of section 2.4 passes through it: choose a pulse
  current rating accordingly.

### 2.9 Isolation, ground reference and the load's sense leads

- **Control to power isolation.** The Pi's 3.3 V GPIO never meets the power
  side: the driver board's optocouplers and a coil supply separate from the
  Pi's 5 V (a small 12 V adapter, or the board's own isolated supply) keep
  the two sides without a shared conductor. The same rule applies to the MCU
  variant and to any DP821A trigger line (whose common's relation to CH1- is
  `UNV`).
- **Supply channel isolation.** The DP800 datasheet says only that "some
  channels are isolated" (`DP`); whether CH1- and CH2- of the DP821A are
  isolated from each other and from earth is not stated. Tying them on the
  return bus (section 2.6) is bench check **S2**: with both outputs OFF, a
  DMM between CH1- and CH2- and between each and the chassis earth terminal.
  Equal potential or isolation are both acceptable; a defined non-zero
  relationship (for example a series-tracking link) is not.
- **Load isolation.** Whether the DL3031A input terminals and its rear analog
  monitor outputs float from earth is not stated (`DL`). It matters when K1b
  opens the return line of a non-isolated converter: if both CH1- and the
  load's negative were earth-referenced, the "open" return would have an
  alternate path through earth. Bench check **S3** (DMM, inputs OFF). Until
  it is answered, the return-line case of 4.9.1 is offered only with the
  load input OFF.
- **The DL3031A's sense leads stay where they are.** Today the real bench uses
  local sense and no S+/S- leads are wired (`profiles/bench/mock-rigol-local-sense.yaml`
  mirrors it); if remote sense is wired later it belongs at the converter
  output (brief §3.3). The box is in the input path and touches nothing on the
  output side, except that the 4.7 reversal requires the load disconnected.
- **Enclosure**: a metal box bonded to protective earth is correct whether or
  not the power circuit floats; the power circuit itself is left floating as
  the supply outputs are, pending S2 and S3.

### 2.10 Fail-safe rules

1. **De-energised means disconnected.** K1a and K1b are normally-open; no
   latching relay, no bistable circuit, no "remember last state" anywhere.
   Loss of coil supply, driver supply, GPIO drive, heartbeat or Pi power opens
   the converter's input within the relay's release time plus the heartbeat
   timeout (section 3.1).
2. **Boot-safe drive.** The GPIO must be low, or floating into a pull-down,
   from power-on through boot and after a crash; the driver must be
   active-high so that a floating input means open (section 3.1).
3. **One manual control only: DISCONNECT.** A labelled front-panel switch
   breaks the K1 coil circuit. There is no manual "force closed" override:
   that would defeat rule 1.
4. **State is read back, not assumed**: the GPIO output register in the first
   build, an auxiliary contact and a DUT-side voltage sense in the upgrade
   (section 4.1). An unverifiable state is `UNKNOWN`, as brief §7.1 requires
   of output states, and the run stops.
5. **The supply's protections stay armed and the Delayer cutoff stays
   armed.** The box is in series with, not instead of, OVP/OCP, the DL3031A
   limits and the 720 s one-shot source timer (`ENV`); for a Delayer-timed
   recipe the Delayer and the switch never time the same event.

## 3. Control options and their timing bounds

### 3.1 (a) Raspberry Pi GPIO through an opto-isolated relay driver (recommended first build)

- **Path**: a Python call writes a GPIO line (3.3 V logic, a few mA per pin
  `class`: never a coil directly) into an optocoupler on the driver board; the
  board's transistor energises the coil from its own supply.
- **Timing**: the interval between two GPIO writes is measured by the host's
  monotonic clock to microsecond resolution, so the sheet's `host_interval_s`
  is a real measurement (owner decision 3). What the host clock does not
  bound is the delay between the write and the contact: Linux scheduling
  jitter (`class`: a few ms typical, tens of ms when the Pi is loaded; the
  memory-pressure resets noted in the project's Pi constraints are the worst
  case) plus the relay's operate and release times. The interval error is
  the *difference* between operate and release delays plus the jitter
  difference between the two writes, `class` within +/- 10 ms. For 1 s and
  10 s intervals that is inside the clause tolerances (+/- 50 ms, +/- 1 s);
  for 100 ms it is +/- 10 %, outside +/- 5 % until acceptance test A5
  measures this relay and this Pi; 10 ms is not offered.
- **Jitter discipline**: the switch command runs in a dedicated thread or
  process that does no instrument I/O between the two writes (the LAN polls
  continue elsewhere), stamps `time.monotonic_ns()` before and after each
  write, and refuses an interval shorter than `switch.min_interval_s`.
  Elevating that thread's scheduling class is an optimisation to measure, not
  a guarantee to claim.
- **Boot-safe GPIO.** At reset the Pi's GPIO lines are inputs with a default
  pull that differs by pin (`class` for the BCM2711: the low-numbered bank
  pulls up, the higher-numbered pins pull down). Choose a pin whose reset
  default is pull-down, add an external pull-down at the driver input, and use
  an **active-high** driver input: many inexpensive relay modules are
  active-low (the relay energises when the input is pulled low or left
  floating with the jumper in one position), which would close K1 while the Pi
  boots. Bench check **S5** watches the coil LED or a meter through a full
  reboot with the box powered and nothing connected.
- **Hardware heartbeat gate** (recommended, cheap): a retriggerable
  monostable between the Pi and the K1 driver, retriggered by a second GPIO
  the acquisition loop toggles every poll (about 1.1 s, `LAN`). If the pulses
  stop for `switch.heartbeat_timeout_s` (5 s: at least three missed polls,
  `derived`) the gate drops and K1 opens, whatever the command line says. This
  is independent of the Pi's software in the sense brief §7.4 asks for ("a
  watchdog in the same crashed process is not independent protection"). The
  same gate output can drive a DP821A trigger input configured `LOW level ->
  output OFF` as the dead-man line the DP800 note proposes (its bench check
  B7), so one heartbeat opens the switch and turns the supply off.
- **Read-back in the first build**: the GPIO output register (proves the
  command reached the pin) and the heartbeat gate's state. The auxiliary
  contact and the DUT-side sense are the first upgrade (section 4.1).

### 3.2 (b) The DP821A's trigger lines D0-D3

What the DP800 study found (UG pp. 73-76 and PG pp. 169-182 via
[instrument-sequencing-dp800.md](instrument-sequencing-dp800.md)):

- Four independent lines, each configurable as a trigger **input** (rising or
  falling edge, high or low level; response: channel output ON, OFF or
  toggle) or a trigger **output** (a level or a square wave of 100 us to 2.5 s
  period and 10-90 % duty when the channel output turns on or off, when V, I
  or P crosses a value, or "automatically" when enabled). Logic levels match
  the Pi's 3.3 V. Standard on the DP821A; whether the rear terminal block is
  fitted on the bench unit is bench check R2 of that note.
- A trigger input controls the output state only; no document says it can
  start or stop the Timer or Delayer.
- **Can the Timer or Delayer toggle a D line?** Not directly: no document ties
  a line to a Timer or Delayer group. Indirectly, a Delayer OFF group turns
  the output off, and an output line conditioned `OUTOFF`/`OUTON` follows the
  output state; whether it follows a Delayer-caused change as it follows a
  manual one is not stated (**bench check S4**). Even if it does, the
  granularity is the Delayer's whole second and the output has gone OFF,
  which is the slew the box exists to avoid.
- As a **switch driver**, a D line conditioned "automatically" is set by a
  LAN command: the same path as a `:OUTP` write, with the instrument's
  command processing on top (< 118 ms is documented for output changes after
  a SOURce/APPLy command; whether it applies to trigger-output enabling is
  `UNV`). That is worse than a GPIO write, not better.
- The **square-wave output** (period 100 us to 2.5 s, duty 10-90 %) could in
  principle gate a MOSFET stage for 4.9.1 method 2 (100 us open every 1 ms is
  a 1 ms period at 10 % or 90 % duty, `derived` from `ISO`), with the 10 s
  burst bounded by the LAN enable and disable (+/- 1 s tolerance is generous).
  Its timing accuracy is not specified, its relation to CH1- is `UNV`, and the
  transition still needs a scope: a later experiment (**S7**), not a design
  input.

Verdict: the trigger lines are useful as a **dead-man input** (section 3.1)
and as a **hardware "output went OFF" event line** or scope trigger (proposal
§5); they do not improve switch timing. The `control: dp800_trigger` option
exists in the profile schema so a bench that chooses it is described
honestly, with `min_interval_s` 1 s.

### 3.3 (c) A microcontroller for deterministic pulses

A small MCU board (RP2040 or AVR class, USB serial to the Pi) receives a
command ("open for N us", "select CH2 for N us") and executes it from a
hardware timer: the interval is crystal-bounded (`class` 50 ppm, nanoseconds
on a 100 us pulse) and independent of Linux. It is the only route to 4.6.1.2's
10 ms and 1 ms steps (relay or, better, MOSFET), to 4.6.1.1 with a 100 ms
interval that is `approximated` rather than `unknown`, and to the 100 us
classes once a MOSFET stage and a scope exist. Requirements that keep it
fail-closed: pins default low at reset; the firmware refuses any interval
above a compiled maximum and any command without a fresh heartbeat; a
hardware watchdog resets it; it reports the executed interval and the
read-back contact's edge count (input capture) back to the Pi; the firmware
hash is part of the acceptance record and of every run's method block.

### 3.4 Recommendation and upgrade path

Build (a) first: relays K1a/K1b (and K2 if 4.6.1.1 at 12 V is wanted now),
opto-isolated driver with its own coil supply, heartbeat gate, Pi GPIO. It
unlocks 4.9.1 method 1 on both lines, 4.9.2, the 100 ms to 2 s steps of
4.6.1.2 and the 12 V 4.6.1.1 drop, with the host-clock wording. Upgrade by
replacing the GPIO driver with the MCU board behind the same `SwitchAdapter`
(section 4.1) and adding a back-to-back MOSFET pair in series with K1a for
the sub-10 ms classes; the relay keeps providing the >= 10 MOhm open when
both are open. Nothing in the software contract changes between the two
builds except `switch.control` and `min_interval_s`.

### 3.5 Timing bounds

| Quantity | (a) GPIO + relay | (c) MCU + relay | (c) MCU + MOSFET pair |
| --- | --- | --- | --- |
| Interval basis | host monotonic clock, two GPIO writes | MCU timer | MCU timer |
| Interval error, `class` | +/- (operate - release) +/- scheduling jitter: about +/- 10 ms | +/- (operate - release): a few ms | sub-microsecond |
| Shortest offered interval (`min_interval_s`) | 0.1 s | 0.01 s | 1e-4 s (1e-5 s not offered) |
| Bounce | 1-5 ms, not counted | counted via input capture on the read-back contact | none |
| Open resistance | relay contact: >= 10 MOhm expected, A7 measures | same | pair leakage: check against the 3.6 uA budget |
| Transition at the contact | sub-ms break; waveform unmeasured | same | sub-us; waveform unmeasured without a scope |
| Fail-safe | NO contacts + heartbeat gate | NO contacts + MCU watchdog + heartbeat | same; the MOSFET pair defaults OFF |

Every row of the first two columns keeps `measured_by: host_clock` or
`mcu_clock` for the interval and `none` for the terminal waveform.

## 4. Software contract

Mechanism in `Software/src/benchctl` (a `switch_gpio.py` driver, later a
`switch_mcu.py`), policy in `src/dcdc_bench`, as the existing split demands.

### 4.1 `SwitchAdapter`

Proposed protocol in `domain.py`, runtime-checkable like `SourceAdapter`:

```python
@runtime_checkable
class SwitchAdapter(Protocol):
    """Series switch between the source and the converter input.

    `open()`/`close()` act on the contacts (unlike SourceAdapter.close, which
    releases a transport; this protocol's teardown is `shutdown()`). Every
    method is bounded by the adapter's timeout, returns a SwitchEvent with host
    monotonic and UTC stamps taken immediately before and after the write, and
    raises SwitchStateUnknown when the read-back does not confirm the command.
    Must not: contain clause logic, time an interval it was not asked for, or
    close a contact on construction, reconnection or error.
    """

    def identify(self) -> dict[str, Any]: ...
    def switch_capabilities(self) -> SwitchCapabilities: ...
    def open(self, line: Literal["positive", "return", "both"] = "both", *, now: float) -> SwitchEvent: ...
    def close(self, *, now: float) -> SwitchEvent: ...
    def select(self, source: Literal["CH1", "CH2"], *, now: float) -> SwitchEvent: ...   # selector fitted only
    def reverse(self, enabled: bool, *, now: float, exception: PolicyException) -> SwitchEvent: ...  # K3 only
    def pulse_open(self, open_s: float, *, now: float) -> SwitchEvent: ...   # control == "mcu" only
    def state(self) -> SwitchState: ...
    def heartbeat(self) -> None: ...
    def shutdown(self) -> None: ...   # opens everything it can, then releases the driver
```

- `SwitchCapabilities`: `kind`, `control`, `poles`, `selector`,
  `reversal_fitted`, `contact_rating_V_dc`, `contact_rating_A_dc`,
  `contacts_in_series`, `min_interval_s`, `heartbeat_timeout_s`, and the
  acceptance record's measured values (section 4.4). Read from the bench
  profile and compared with the driver's identity; a mismatch fails
  validation before a run (brief §5.2).
- `SwitchEvent`: `command`, `line`, `requested_state`, `host_monotonic_ns_before`,
  `host_monotonic_ns_after`, `utc_before`, `readback_state`,
  `readback_kind: gpio_register | aux_contact | dut_side_sense | mcu_report | none`,
  `timeout_s`, and for `pulse_open` the MCU's reported executed interval and
  edge count.
- `SwitchState`: `positive`, `return` (`open | closed | unknown`), `selector`
  (`CH1 | CH2 | not_fitted | unknown`), `reversal` (`normal | reversed |
  not_fitted | unknown`), `heartbeat_ok`, `basis: commanded | sensed`.
- `select()` and `reverse()` refuse unless `switch_capabilities()` declares
  the hardware; `reverse()` additionally refuses without a `PolicyException`
  object that the planner only constructs from an approved recipe (section
  2.7). `pulse_open()` refuses `open_s < min_interval_s` and any value above
  the capability's maximum; with `control: gpio` it does not exist, and the
  procedure times the interval itself between `open()` and `close()`.
- `heartbeat()` is called by the acquisition loop every poll; the adapter
  pulses the gate line. The adapter never calls it on its own timer: a
  heartbeat that keeps itself alive is not a heartbeat.
- Read-back levels: `gpio_register` (first build; proves the command, not the
  contact), `aux_contact` (second pole of a 2-pole relay into an isolated
  GPIO input; proves the armature moved), `dut_side_sense` (an opto-coupled
  comparator on DUT IN+/IN- into a GPIO input; proves voltage presence or
  absence on the converter side, which is what the clause is about, and sees
  a welded contact). The sheet names the level used.

### 4.2 `MockSwitch` and the synthetic plant

A deterministic `MockSwitch` in `adapters.py`, seeded, on the virtual clock:

- parameters, all labelled synthetic: `operate_s`, `release_s`,
  `bounce_count`, `bounce_period_s`, `transfer_gap_s` (K2 break-before-make),
  `contact_resistance_ohm`, `open_resistance_ohm`, `selector_level_offset_V`
  (the diode drop of section 2.6), and fault injection flags `stuck_closed`,
  `stuck_open`, `driver_lost`, `heartbeat_lost_at_s`;
- `MockBench` gains a switch input: `source_voltage` reaching the plant is
  CH1's or CH2's level when the respective path is closed, and the DUT-side
  node otherwise follows a synthetic `input_capacitance_F` discharging into
  the converter's draw (the running load above UVLO, the `MOCK` 4 mA standby
  below it) and into the bleeder when K2 has transferred. The ride-through
  that results is a simulation parameter, not a DUT property: with the
  plant's standby draw a 100 uF synthetic capacitance rides 85 ms off load
  (100 uF x 3.4 V / 4 mA, `derived`) and well under a millisecond at 0.5 A;
  both exercise the expected-off scoping and the "invisible to polling"
  statement the proposal's §6.1 item 4 asked for;
- the UVLO comparator is evaluated along the discharge path (the analytically
  solved crossing time), not only at query time, exactly as the proposal's
  §6.1 item 2 requires, otherwise a 100 ms open between two polls never
  reaches the latch;
- bounce is modelled as `bounce_count` make/break pairs after closure, each
  restarting the cold-start delay if the converter had begun to start;
- `host_interval_s` is filled from the virtual clock the same way the real
  path fills it from `monotonic_ns`, so the sheet is built by one code path.

### 4.3 How the best-effort procedures call it

The proposal's `supply_discontinuity` test type gains
`mechanism: switch_box` next to `lan_output_off_on` and the Delayer, with
the sub-mechanisms `switch_box_open` (4.6.1.2, 4.9.x), `switch_box_select`
(4.6.1.1) and `switch_box_reverse` (4.7, policy exception). The deviation
sheet's `mechanism` column takes these names; `measured_by` is `host_clock`
or `mcu_clock` for intervals and `none` for every terminal-side row (owner
decision 3). Per clause:

- **4.9.1 / 4.9.2**: base level on CH1, load ON (3.4) or OFF (2.1 / outputs
  inactive); `open(line)` for 10 s by the procedure's clock, `close()`;
  recovery window per the recipe; the observed-state table marks output-off
  during the open as expected (`SupplyProfilePolicy` scoping, proposal §4.2).
- **4.6.1.2**: `open("both")`, wait the interval, `close()` for each decade
  step the capability allows; recovery >= 5 s; case 2 inverts the roles.
  With `control: mcu`, `pulse_open(interval)` replaces the pair and the MCU's
  reported interval goes into the sheet as `mcu_interval_s`.
- **4.6.1.1**: CH1 at Usmin, CH2 at 4.5 V plus the recorded offset, both ON
  and verified; `select("CH2")`, wait 100 ms, `select("CH1")`; the planner
  refuses the recipe when the drop level exceeds CH2's range.
- **4.7**: only with the policy exception; `open()`, `reverse(True)`,
  `close()`, hold, `open()`, `reverse(False)`, `close()`: the polarity never
  changes under a closed K1.

### 4.4 Bench profile and planning

```yaml
switch:                       # absent on today's profiles: no switch tokens
  kind: relay                 # relay | mosfet_bidirectional | relay_plus_mosfet
  control: gpio               # gpio | dp800_trigger | mcu
  poles: [positive, return]
  selector: true              # K2 and the CH2 branch fitted
  reversal_fitted: false      # K3; true only with the owner's policy exception
  contact_rating_V_dc: null   # the relay datasheet's DC figure, not the AC one
  contact_rating_A_dc: null
  contacts_in_series: 1
  min_interval_s: 0.1
  heartbeat_timeout_s: 5
  readback: gpio_register     # gpio_register | aux_contact | dut_side_sense | mcu_report
  acceptance:                 # from section 5.4; null until measured
    record: null              # path of the acceptance record, with date and operator
    open_resistance_Mohm: null
    contact_drop_mV_at_2p5A: null
    operate_s_max: null
    release_s_max: null
    bounce_s_max: null
    selector_level_offset_V: null
    firmware_hash: null       # mcu only
```

- `capabilities()` grants the tokens of section 1.3 from this block only;
  `envelope()` gains `switch_max_voltage_V` (`contact_rating_V_dc`) and
  `switch_max_current_A`; `feasibility()` refuses any recipe level above the
  former with an `outside_switch_rating` reason, so a 30 VDC relay makes the
  24 V-system interruption clauses `needs_instrument` with the reason stated.
- `Clause` gains `needs_any: list[set[str]]` so 4.6.1.1 and 4.6.1.2 can be
  satisfied by the switch token set without granting `pulse_ms` or
  `edge_10ms` (section 1.3).
- Planning keeps the proposal's rules: `best_effort_approved`, the accepted
  deviation sheet's hash, `uvlo_approved` wherever the input reaches 0 V
  (every open), and a protective policy whose guard covers the OVP band. The
  switch's acceptance record hash is part of the approved plan hash: a new
  relay or a re-measured drop invalidates approvals, as a changed limit does.

### 4.5 Safety sequence

The order of brief §7 and of `extended.py`, with the switch added. Which
stop order is safe for a given converter is approved per bench and DUT
(brief §7.4); the one below is the proposal.

1. **Preflight, read-only**: switch adapter identified and matched to the
   profile; `state()` reports both lines open (basis recorded); heartbeat
   gate idle; selector on CH1; reversal normal or not fitted; both supply
   outputs OFF; load input OFF; `:TIMER?` / `:DELAY?` OFF; no latched OVP/OCP.
2. **Protections programmed and read back with everything OFF**: CH1 OVP/OCP
   and current limit as the procedures do today; CH2 current limit (about 1 A)
   and OVP just above its setpoint when the selector is used; DL3031A VLIM /
   ILIM.
3. **Switch verified open before anything is energised.** Then CH1 ON (and
   CH2 ON for a selector recipe) into the open switch; the Delayer cutoff
   armed as today for LAN-timed recipes. The supply readback shows the supply
   terminals, not the DUT side: with the switch open the converter side is
   floating by design, and the residual-voltage check of today's procedures
   applies to the supply side; a `dut_side_sense` read-back extends it to the
   converter side.
4. **Heartbeat running, then `close()`** with read-back; the unloaded
   startup check as today; the load enabled only after it.
5. **Every interruption is bounded three times**: the procedure's own
   software timeout (interval plus margin) around each `open()`/`close()`
   pair; the heartbeat gate (5 s) if the worker stalls; the supply's 720 s
   Delayer cutoff and its OVP/OCP throughout. A `SwitchEvent` whose read-back
   does not confirm the command stops the run with the state recorded as
   `UNKNOWN`; the stop sequence runs regardless.
6. **Controlled stop**: `open("both")` and verify (the converter is
   de-energised with a defined edge), load OFF and verify, CH1 (and CH2) OFF
   and verify, Delayer OFF, heartbeat stopped last so the gate falls on its
   own as a final check. **Urgent fault**: the same three actions issued
   independently, errors on one never skipping another (brief §7.4), and the
   heartbeat stopped immediately so the gate opens K1 even if the GPIO write
   failed.
7. **Evidence**: every `SwitchEvent` in `raw/events.jsonl` with both stamps
   and the read-back; the acceptance record hash and the `switch` block in
   `run.json["method"]`; the deviation sheet with `switch_box_*` mechanisms;
   the end state "both lines open, read-back basis X" next to "source OFF
   verified" in the run record and the report.

## 5. Bench checks and a build list

### 5.1 Read-only checks before anything is built or connected

| # | Check | How (outputs OFF, nothing connected to the DUT) | Why |
| --- | --- | --- | --- |
| S1 (= DP800 R2) | Is the DP821A's rear digital I/O terminal fitted and the function installed? | look at the rear panel; `:TRIG:IN? D0` style queries from the DP800 note's R2 | decides whether the dead-man input and the event line of section 3 exist |
| S2 | CH1- to CH2- relationship; each to chassis earth | DMM resistance and DC voltage, both outputs OFF, then with outputs ON into nothing (voltage only) | permits tying the returns for the selector (section 2.6) |
| S3 | DL3031A input terminals and analog monitor outputs to earth | DMM, input OFF | the return-line open of 4.9.1 and the 4.7 wiring (section 2.9) |
| S4 | Does a trigger output conditioned OUTOFF/OUTON follow a Delayer-caused output change? | write check, outputs into nothing; only if S1 is yes and the owner wants the trigger lines characterised | closes the open question of section 3.2 |
| S5 | GPIO reset default and driver polarity | box powered, Pi rebooted, coil LED / meter on the coil watched through boot and a forced power cycle | rule 2 of section 2.10 |
| S6 | CH2 back-drive tolerance without the Schottky | pass-through fixture only (CH1 to the DL3031A), a capacitor of the DUT's class on node B, scope or at least DMM min/max | whether the diode and its offset can be omitted (section 2.6) |
| S7 | DP821A square-wave trigger output as a MOSFET gate for 4.9.1 method 2 | later, with the MOSFET stage and a scope | section 3.2; not part of the first build |

Also needed from documents, not from the bench: the 12T12-4A's input
capacitance, input filter and reverse-polarity protection from the module
datasheet (owner question 6), which size R_b, the clamps and the 4.7 energy
discussion.

### 5.2 Generic parts list (classes, not part numbers)

| Item | Class and rating to look for | Notes |
| --- | --- | --- |
| K1a, K1b | 2-pole power relay, DC-rated contact >= 36 VDC / >= 3 A resistive with an inrush rating, AgSnO2 or AgNi, 12 V or 24 V coil; one pole power, one pole read-back | if only 30 VDC is available: two contacts in series per line (section 2.2) and a 12 V-only box until proven |
| K2 | same class, SPDT or DPDT, break-before-make | only with the selector |
| K3 | DPDT, same contact class | only with the owner's 4.7 exception |
| Driver | opto-isolated relay driver board, **active-high**, flyback diodes fitted, separate coil supply input (the "JD-VCC" style jumper removed) | section 3.1 |
| Coil supply | small 12 V (or 24 V) adapter sized for all coils energised, separate from the Pi's 5 V | isolation (section 2.9) |
| Heartbeat gate | retriggerable monostable (CMOS one-shot or 555-class in retriggerable configuration), 5 s, output ANDed with the K1 command | section 3.1 |
| Schottky diode | >= 1 A, >= 40 V reverse, low forward drop | CH2 branch |
| R_b | 10 Ohm class, >= 5 W, wirewound or thick film on a heatsinking surface | 2 W continuous at 4.5 V (`derived`); value finalised from C_in |
| TVS_s, TVS_d | stand-off >= 40 V, clamp per the module's input rating, leakage specified | across terminals, never across contacts |
| Wiring | 1.5 mm^2 (AWG 16) minimum for the power path, short and equal lengths; 0.5 mm^2 for coils and sense | drop budget (section 2.2) |
| Connectors | 4 mm safety sockets to the DP821A binding posts (CH1+, CH1-, CH2+, CH2-); screw or spring terminals to the converter pigtails; shrouded, labelled | polarity marked on the panel |
| Enclosure | metal, earth-bonded, with a labelled **DISCONNECT** toggle in the K1 coil circuit, coil-state LEDs per relay, GPIO and heartbeat connectors | section 2.10 |
| Upgrade: MCU | RP2040 or AVR class board, USB serial, hardware watchdog, input capture | section 3.3 |
| Upgrade: MOSFET pair | two logic-level N-channel, >= 60 V, < 20 mOhm, avalanche-rated, with an isolated gate driver | section 2.8 |
| Acceptance: dummy load | power resistor sized for 2.5 A at the test voltage (36 V / 15 Ohm is 86 W, so a resistor bank or a shorter duty), **or the DL3031A on the pass-through fixture in CC** | section 5.4 |
| Acceptance: capacitor | a film or electrolytic capacitor of the DUT's input class, with a bleeder, to stand in for C_in | once question 6 is answered |

### 5.3 Estimated cost band

Estimates, not quotes: relays, driver board, monostable parts, coil adapter,
diodes, TVS, resistor, connectors, wire and a small metal enclosure for the
GPIO build fall well under 100 EUR/USD in parts; the MCU board adds 10-30; a
MOSFET stage with an isolated gate driver adds 20-50. A scope or DAQ is a
separate decision (owner decision 5) and is not in the band. Labour: one
evening to wire and label, one bench session for section 5.4.

### 5.4 Acceptance tests before the box touches the converter

All with the converter disconnected; the DUT side goes to a DMM, then to a
dummy load (a resistor bank, or the DL3031A on the pass-through fixture used
for the M2 freshness evidence, with the caveat that an electronic load in CC
reports unregulated status while the switch is open and that its 350 kOhm
OFF-state input resistance (`DL`) makes it unusable for A7). Every command is
logged with both host stamps and the read-back from the first power-up on.

| # | Test | Pass condition |
| --- | --- | --- |
| A1 | Continuity, polarity, insulation: each pole open and closed with a DMM; control side to power side with an insulation tester or at least a DMM at its highest range | polarity matches the labels; no path between control and power sides |
| A2 | Fail-safe: box powered, no command: open. Command closed, then pull the GPIO lead: open. Command closed, stop the heartbeat: open within `heartbeat_timeout_s`. DISCONNECT toggle: open under any command. Pi rebooted with the box powered (S5): never closes | each condition observed on the read-back and on the DMM |
| A3 | First current: 12 V then 36 V into the dummy load at 0.5 A, 1 A, 2.5 A; hold 60 s each | no heating of contacts, wiring or R_b beyond expectation; supply readback matches the load |
| A4 | Contact drop: DMM across each closed pole and across the whole box at 2.5 A (or the 1 A the DP821A can supply, extrapolated and so labelled) | recorded in millivolts; entered in the profile; well inside the 80 mOhm budget or the shortfall recorded |
| A5 | Timing: 20 open/close cycles at 10 s, 1 s and 100 ms; the supply's and the load's 1 s readbacks confirm the whole-second opens (expect 9-10 zero polls per 10 s open); the read-back contact's edges, timestamped by GPIO interrupts (or MCU input capture), give operate, release and bounce figures | operate, release and bounce maxima recorded in the profile; the 100 ms interval's spread decides its sheet classification (section 1.1) |
| A6 | Wear: 200 interruption cycles at 2.5 A and 36 V into the resistive dummy load (or the highest current available), with a capacitor of the DUT's class across the load when question 6 is answered; then A4 again and a check that every pole still opens | contact drop unchanged within measurement; no weld; no visible damage |
| A7 | Open-circuit resistance: switch open, CH1 at the base voltage (12 V, 24 V, then 36 V), a 10 MOhm-input DMM on the DUT side and a 1 kOhm reference in parallel (as the clause's own reference check lists, `ISO` 4.6.1.2) | leakage current below 1.2 uA at 12 V and 3.6 uA at 36 V (`derived`), i.e. >= 10 MOhm; recorded in the profile |
| A8 | Selector branch (if fitted): CH2 at its setpoint, R_b loaded, DMM on node B: the level offset; K2 transfers with a capacitor of the DUT's class on the DUT side; the min/max of a DMM or a scope on CH2's terminals shows whether CH2 was back-driven | offset recorded; no CH2 OVP trip; CH2 stays ON |
| A9 | Reversal (only if K3 is fitted): polarity on the DUT side with a DMM after `reverse(True)` with K1 open; then K1 closed into a resistor | polarity as commanded; K1 never closed during a transfer (log) |
| A10 | End-to-end dry run of the 4.9.2 procedure on the mock bench with `MockSwitch`, then on the real bench with the dummy load | the run record shows every `SwitchEvent`, the deviation sheet with `switch_box_open`, and "both lines open" verified at the end |

Only after A1-A7 (and A8 if the selector is used) is the converter connected,
starting with 4.9.2 at 12 V and the load OFF.

## 6. Questions for the owner

1. **Control path.** GPIO through an opto-isolated driver with the heartbeat
   gate for the first build (recommended), with the MCU as the upgrade; or
   the MCU from the start because the 10 ms and 1 ms classes of 4.6.1.2 are
   wanted soon? The trigger lines are proposed only as the dead-man input and
   an event line, never as the switch driver (section 3.2); confirm, and
   whether S1 may be checked now.
2. **4.7 reversal.** Fit K3 and create the policy-exception state, accepting
   that the converter may be destroyed and that the load is disconnected for
   it; or leave 4.7 excluded as the brief has it? Independent of the answer,
   the -26 V level for 24 V systems needs verifying on the owner's copy.
3. **Dummy load for acceptance.** Is a resistor bank for 2.5 A at 36 V
   available, or do the acceptance tests use the DL3031A on the pass-through
   fixture (adequate for A3-A6 and A8, not for A7)? Who performs them and
   where is the record stored (the profile needs its path)?
4. **Contact rating versus the 24 V-system clauses.** Accept a relay rated
   at >= 36 VDC (or two contacts in series, bench-verified) so the box serves
   both systems, or a 30 VDC class and a 12 V-only box?
5. **Heartbeat gate.** Include it in the first build (recommended; it is the
   only element independent of the Pi's software) and also feed it to a
   DP821A trigger input as the dead-man line if S1 is yes?
6. **Converter facts.** Can the 12T12-4A's input capacitance, input filter
   and reverse-polarity protection be read from its datasheet and recorded in
   `profiles/dut/12t12-4a.yaml`? They size R_b, the clamps, the inrush
   discussion and the 4.7 energy estimate; until then those numbers stay
   illustrations.
7. **Selector branch.** Build K2 with the Schottky diode (level offset
   recorded) or test the diode-less variant first (S6)? And for 4.6.1.1 at
   24 V: offer CH2 at 8 V as a recorded deviation, or leave the 24 V variant
   supply-timed?
8. **Measurement point.** Move the Vin measurement to the DUT side of the box
   (a later DMM or DAQ channel, brief §3.3) so the box's drop leaves the
   measured level, or keep the source-terminal boundary and carry the
   measured drop in the deviation sheet?
