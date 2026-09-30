# Automotive standards catalog

What the bench page's "Which test?" checklist is built from: which clauses of
which automotive standards this bench can honestly run, which need another
instrument, which belong to a different laboratory, and which the project
excludes by policy. The code is `src/dcdc_bench/standards.py`; the tests are
`tests/test_standards.py`.

Rules that apply to everything in this folder:

- Only technical facts are recorded: clause numbers, titles, levels,
  durations, rates, impedances and functional status classes, cited as
  "<standard>, clause <number>". No standard text is reproduced and no
  standard document is stored in the repository (implementation brief §16).
- A verdict is one of `runs_here`, `needs_instrument`, `not_on_this_bench`,
  `excluded_by_policy`, `outside_dut_rating` or `not_applicable`, each with a
  one-sentence reason a technician can read and, when it runs, the conditions
  that still apply (below-minimum steps need the approved UVLO-style recipe;
  rated load is unreachable from a 1 A source; temperature conditioning is
  absent).
- Reverse voltage, short circuit, overload and load dump stay excluded even if
  an instrument existed (brief §2 and §7.5). A level equal to the DUT maximum
  is refused: the endpoint method is not approved (the project programs 35.8 V
  for a nominal 36 V).
- Ordinary supply/load polling is never labelled as a ripple, transient, inrush
  or load-step measurement (brief §2).

## Documents

| Document | What it is |
| --- | --- |
| [iso16750-2.md](iso16750-2.md) | ISO 16750-2:2023 section 4, clause by clause: 12 V and 24 V parameters, functional status class, capability needed, bench verdict for the 12T12-4A, the capability-token mapping and the recipe numbers for the clauses that run here. |

## Categories on the bench page

| # | Category | Entries | Candidate for this bench |
| --- | --- | --- | :-: |
| 1 | Normal operating voltage | VIN sweep, efficiency, load/line regulation, dropout and minimum-input behaviour, mapped to the existing `steady_state_load_sweep` recipes, the fixed real workers (`voltage_sweep.py`, `extended.py`, `startup_descent.py`) and the mock-only UVLO ramp (`uvlo.py`) | yes |
| 2 | ISO 16750-2 supply profiles | every test clause of section 4 as a checklist item | yes (4.2, 4.3.1.1 at 12 V, 4.5, 4.6.2; the >= 1 s part of 4.6.1.2) |

The bench page renders this catalog as the "Automotive supply standards" group of "Which test?" (`src/dcdc_bench/standard_recipes.py`): the ISO 16750-2 card expands into the clause checklist, and "Add as tests" turns 4.2 into a `steady_state_load_sweep` recipe and 4.5 / 4.6.2 into the mock-only `slow_supply_ramp` / `reset_staircase` recipes (`src/dcdc_bench/supply_profiles.py`); 4.3.1.1 and 4.6.1.2 show "procedure not yet implemented" with the requirement a procedure would have to meet. See [docs/bench-ui.md](../bench-ui.md#automotive-standards-in-which-test).
| 3 | ISO 7637-2 transients | one entry: pulses 1, 2a, 2b, 3a, 3b (ISO 7637-2:2011, clause 5.6) | no: transient generator |
| 4 | EMC | CISPR 25, ISO 11452 (all parts), ISO 10605 | no: EMC chamber, ESD simulator |
| 5 | Environmental | ISO 16750-3 mechanical, ISO 16750-4 climatic | no: shaker, climatic chamber |

## Printing the catalog

```python
from dcdc_bench import standards
from dcdc_bench.domain import BenchProfile, DutProfile
from dcdc_bench.planning import load_profile

bench = load_profile("profiles/bench/mock.yaml", BenchProfile)
dut = load_profile("profiles/dut/12t12-4a.yaml", DutProfile)
for category in standards.catalog(bench, dut, "12V"):
    for entry in category.entries:
        print(category.number, entry.clause.number, entry.feasibility.status, entry.feasibility.reason)
```

The mock and real profiles give the same verdicts: capability tokens describe
the class of instrument a profile declares (a single-quadrant, LAN-polled DC
supply), not whether it is simulated.
