# Contributing

Two Python packages live in this repository:

- **`benchctl`** (`Software/`, installed from the repository root) drives Rigol
  DP800-series supplies and DL3000-series electronic loads over LAN and runs
  bounded YAML recipes.
- **`dcdc-bench`** (`dcdc-bench/`) plans, runs and reports DC–DC converter
  characterizations on top of `benchctl`, with a deterministic mock bench.

## Set up

Python 3.11 or newer on Linux, macOS or WSL (the transport uses POSIX file
locks, so native Windows is not supported for live control).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e . -e './dcdc-bench[ui,report,real,test]'
```

Nothing above contacts an instrument. The document toolchain (Quarto 1.10.18
with bundled Typst, a Chromium build, `poppler-utils`) is only needed to render
HTML/PDF reports; `python dcdc-bench/tools/setup.py` installs the pinned Quarto
release after verifying its published SHA-256 and, when no system Chromium is
present, a Playwright Chromium.

## Run the tests

```bash
python -m pytest Software/tests -q
python -m pytest dcdc-bench/tests -q -m 'not browser and not pdf and not integration'
python -m pytest dcdc-bench/tests/test_run02_reconnect.py -q -m integration
```

Both suites use fake instruments only. Markers are registered in
`dcdc-bench/pyproject.toml`:

| Marker | Needs | Runs in CI |
| --- | --- | --- |
| `browser` | Playwright Chromium, offline | Second job, allowed to fail |
| `pdf` | Quarto 1.10.18 / Typst, `pdftohtml` | Second job, allowed to fail |
| `integration` | Subprocess workers or the bundled Typst binary | Worker reconnect: required job; document fixtures: second job |

With the tools installed, the release gates read a completed demo:

```bash
dcdc-bench demo --out dcdc-bench/examples/generated
DCDC_DEMO_DIR="$PWD/dcdc-bench/examples/generated" \
  python -m pytest dcdc-bench/tests -q -m 'browser or pdf or integration' \
  --ignore=dcdc-bench/tests/test_run02_reconnect.py
```

## Rules

1. **Mock first.** Every feature is implemented and tested against fake
   transports (`Software/tests`) or the mock bench (`dcdc-bench`) before any
   real-hardware path exists. Tests never open a VISA session.
2. **No hardware in CI.** The GitHub Actions workflow runs fake-instrument
   tests only. Real runs are the bench owner's decision, made at the bench,
   and are never a pull-request check.
3. **No private bench data.** Instrument addresses, serial numbers and the
   private inventory stay out of Git. `Software/config/lab.yaml`,
   `dcdc-bench/runs/`, `dcdc-bench/workspace/`, `dcdc-bench/diagnostics/`,
   `Data/Runs/` and `Data/Logs/` are ignored on purpose; use the reserved
   `.invalid` hostnames and RFC 5737 addresses in fixtures.
4. **Limits are explicit.** Setpoint limits live in
   `Software/config/safety_profiles.yaml` and in profile YAML; they are never
   inferred from a reported model string. Software limits complement, never
   replace, the instruments' own OVP/OCP/OPP.
5. **Evidence is append-only.** Do not rewrite finalized run evidence, issued
   analyses or report revisions; add a new revision.
6. **Pins are deliberate.** `dcdc-bench` pins exact dependency versions
   (`pyproject.toml`, `requirements-tested.txt`). Bump them on purpose and say
   so in the commit.

## Review documents under `dcdc-bench/docs/`

Each increment leaves its records next to the code, named `<topic>-<kind>.md`:

| Suffix | Contents |
| --- | --- |
| `-test.md` | The procedure and the exact commands that were run |
| `-verification.md` | What was verified, on which platform, with which tools |
| `-code-review.md` | Code review findings and their resolution |
| `-results-review.md` | Independent recomputation of measured results from the preserved evidence |
| `-ui-review.md` | Browser/UI inspection, desktop and mobile |

The milestone position is stated in `implementation_status.md` and repeated
verbatim in `acceptance.md` and `dcdc-bench/README.md`; change all three
together. `implementation-brief.md` is the design contract and is not edited
to match the code.

## Style

`.editorconfig` covers indentation and line endings (4-space Python, LF, final
newline; the committed CSVs keep their RFC 4180 CRLF records). Keep measured
values and requested setpoints distinct, and label simulated data explicitly.

## Pull requests

Branch from `main`, keep commits focused, run both test commands above, and
describe what was verified and how. Do not include generated runs, reports or
tool downloads.
