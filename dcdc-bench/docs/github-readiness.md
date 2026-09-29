# GitHub readiness audit

Read-only audit of the tracked tree at `dcdc-bench-hardening` (`5eb13e8`) on
2026-09-28, performed by an automated agent role. No instrument, UI server,
demo, render or test run was started; the findings come from `git ls-files`,
`grep`, and reading the files named below. Line numbers refer to that commit.

Method: 207 tracked files, 2.83 MB in total. Every file was scanned for IPv4
addresses, `.local` hostnames, VISA resource strings, `/home/<user>` paths,
e-mail addresses, MAC addresses, instrument-serial patterns
(`DP8x…`, `DL3x…`) and credential-like keys; sizes, line endings, trailing
newlines, version strings and Python-version statements were checked; the
README, `implementation_status.md`, `acceptance.md`, `tools/setup.py` and
`tests/test_documents.py` were read in full.

## Findings

Severity: **High** blocks a clean public repository; **Medium** should be fixed
before or soon after the first public push; **Low** is cosmetic or a judgment
call; **OK** is a check that passed.

| # | Item | Location | Severity | Recommendation | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | No `LICENSE` file. Without one, GitHub shows "no license" and nobody may reuse the code. `Documentation/DC-DC-Characterization-Plan.md:376` notes that anything adapted from mbA2D/Test_Equipment_Control is GPL-3.0; `implementation-brief.md:915` says not to claim a grant for the existing driver library. | repository root | High | Owner chooses a license (check first whether any code was adapted from the GPL project). A README "License — to be chosen" placeholder is proposed below. | Owner decision |
| 2 | Real instrument serial numbers `DP8G…` (redacted here) and `DL3A…` (redacted here) are in tracked docs. The repository's own policy keeps serials private (`.gitignore` comment; `Data/README.md:105-106` redacts them in the example run; `Documentation/Publishing.md:29-33`). | `dcdc-bench/docs/cold-start-hypothesis.md:87-88`, `dcdc-bench/docs/m2-qualification-plan.md:154`, `:305` | Medium | Replace with `[redacted]` or a stable alias (`source S1`, `load L1`) before the first public push, or the owner accepts publishing them (they are not credentials; the risk is inventory disclosure). | Done by the coordinator on 2026-09-28: both documents now say "private inventory" instead of the serial |
| 3 | Absolute `/home/jerome/...` paths reveal the owner's username and checkout layout. | `Documentation/Pi-Reliability.md:45-46`; `Documentation/VS-Code-File-Watching.md:8,11,15,21,40`; `dcdc-bench/docs/implementation_status.md:372`; `dcdc-bench/docs/pi-process-model.md:153` | Low | Use `~/rigol-control` or `<checkout>`. | Done 2026-09-28 (forward edit; history unchanged) |
| 4 | Username `jerome` in `loginctl` examples; `owner="jerome@bench"` in a test fixture. | `Documentation/Pi-Reliability.md:113-114,117,122,162`; `dcdc-bench/tests/test_attachments.py:291` | Low | `<user>` placeholder in the docs; `operator@bench` in the fixture. | Docs part: Done 2026-09-28 (forward edit; history unchanged). Test fixture: Not done |
| 5 | mDNS hostname `rigol.local` of the development Pi. | `Documentation/Pi-Reliability.md:132`; `Documentation/VS-Code-File-Watching.md:21` | Low | `<pi-hostname>` as `dcdc-bench/docs/bench-ui.md:42` already does. | Done 2026-09-28 (forward edit; history unchanged) |
| 6 | Localhost-only report links (`http://localhost:8081/...`) that only resolve through the owner's SSH port forward. | `README.md:13`; `Data/README.md:16-59`; `dcdc-bench/README.md:64,90-91,115-116,265-267,297-299,331-333`; `dcdc-bench/docs/implementation_status.md:38-39,48-49`; `configured-workflow-results-review.md:82-83`; `startup-descent-results-review.md:69-70` | Medium | Either label every such link "local bench only" (most already have a nearby sentence) or replace with relative links to the review documents. Exact README snippet below. | Done 2026-09-28 (forward edit; history unchanged) for `README.md`, `Data/README.md` and `dcdc-bench/README.md`: links are labeled "local bench only" or the headline links point to the committed results reviews; report links inside the review documents themselves are unchanged |
| 7 | IPv4 addresses: only RFC 5737 documentation addresses (`192.0.2.10/.20`) in `Software/tests/*` and RFC 1918 `192.168.77.42` as a redaction fixture in `dcdc-bench/tests/test_publish.py:16,256`. No live address anywhere. | tests | OK | None. | Done |
| 8 | VISA resource strings: only `TCPIP0::*.example.invalid::INSTR` and the documentation IPs above. `Software/config/lab.example.yaml` ships `.invalid` hostnames and `expected_serial: null`. | `Software/config/lab.example.yaml:11,18` | OK | None. | Done |
| 9 | E-mail addresses: only `fixture@example.invalid` (`dcdc-bench/tests/test_software_provenance.py:19`). GitHub username `robomaniac` appears only in intended Pages/repository URLs. | — | OK | None. | Done |
| 10 | Tokens, passwords, MAC addresses: none. The `authorization:` keys in `dcdc-bench/profiles/recipes/*.yaml` are the `AuthorizationPolicy` profile field (`domain.py:554`), not credentials. | — | OK | None. | Done |
| 11 | `.gitignore` coverage: `Software/config/lab.yaml`, `Data/Runs/`, `Data/Logs/` (root); `runs/`, `workspace/`, `diagnostics/`, `test-artifacts/`, `examples/generated/`, `.tools/`, `*.local.yaml`, `.venv/` (`dcdc-bench/.gitignore`) were already covered. Missing: `.claude/worktrees/`, root `.tools/`, `.codex/`, `.agents/`. | `.gitignore`, `dcdc-bench/.gitignore` | Low | Added the missing entries. `git ls-files` confirms none of the private directories is tracked. | Done |
| 12 | Tracked `Data/` contents: the public 5 V demo (`power-test-report.html`, `demo-report.html`, `sweep-preview.html`, two CSVs), `Example_Run/20260926T072124Z_load_sweep/` with both serials `[redacted]` in `run.json`, and `Verification.md`. No address, hostname or serial found in the HTML/CSV. `Media/` is one SVG chart; `Electrical/` is one wiring note with bench settings. | `Data/`, `Media/`, `Electrical/` | OK / owner confirm | Intended to be public per `Documentation/Publishing.md:30-31`; the owner should confirm that stance still holds now that the repository also carries the converter work. | Owner decision |
| 13 | Large binaries: none over 1 MB. Largest tracked file is `Data/power-test-report.html` (101,628 bytes); total tracked size 2,832,478 bytes. | — | OK | None. | Done |
| 14 | `CONTRIBUTING.md` missing. | root | Medium | Added: setup, both test commands, marker table, mock-first rule, no hardware in CI, private-data rule, review-document convention. | Done |
| 15 | `CODE_OF_CONDUCT.md`, issue/PR templates, `SECURITY.md`: absent. | root | Low (optional) | Add later if outside contributions are wanted; not added. | Not done (optional) |
| 16 | `.editorconfig` missing. | root | Low | Added, matching the tree's conventions (4-space Python, 2-space JS/CSS/YAML/JSON, LF, final newline, CRLF preserved for `*.csv`). | Done |
| 17 | Packaging metadata: both `pyproject.toml` files lacked `keywords`, `classifiers` and `[project.urls]`; `dcdc-bench/pyproject.toml` lacked `readme`. Neither has a `license` field (correct until #1 is decided). | `pyproject.toml`, `dcdc-bench/pyproject.toml` | Low | Added additive fields only; no `license` classifier. Both validate with `tomllib`. | Done |
| 18 | Line endings: LF everywhere except three CSVs with CRLF (`Data/power-test-results.csv`, `Data/demo-results.csv`, `Data/Example_Run/.../measurements.csv`), which is the RFC 4180 output of Python's `csv` module. All text files end with a newline; no tabs in Python. | `Data/*.csv` | Low | Accepted; `.editorconfig` keeps CRLF for `*.csv`. Consider a `.gitattributes` with `*.csv -text` so Git never normalizes them. | Done (editorconfig); `.gitattributes` not added |
| 19 | `index.html` and `.nojekyll` at the root: the GitHub Pages entry point (`index.html` meta-refreshes to `Data/power-test-report.html` and links the repository) and the marker that stops Jekyll from processing the saved HTML reports (`Documentation/Publishing.md:70-71`). | `index.html`, `.nojekyll` | OK | Keep; explain in the README folder map (snippet below). | Proposed |
| 20 | `.codex/` and `.agents/` in the main checkout are empty, untracked directories left by AI coding tools (Codex CLI; agent configuration). `.claude/` holds only `worktrees/`. | main checkout | Low | Ignore them so accidental contents are never committed; added to `.gitignore`. | Done |
| 21 | `Documentation/` versus `dcdc-bench/docs/`: `Documentation/` holds the parent `benchctl` docs (`Architecture.md`, `Publishing.md`, `DC-DC-Characterization-Plan.md`) plus three notes about the owner's development Pi (`Pi-Reliability.md`, `VS-Code-File-Watching.md`, `Viewing-Local-Reports.md`); `dcdc-bench/docs/` holds the subproject brief, status, acceptance and per-increment reviews. | both | Low | Keep the split; describe it in the README folder map; label or move the three Pi notes (for example `Documentation/bench-notes/`) so newcomers do not mistake them for setup requirements. | Owner decision |
| 22 | `.vscode/tasks.json` is tracked and uses `${workspaceFolder}` paths only. | `.vscode/tasks.json` | OK | Keep (listed as intentional in `Documentation/Publishing.md:41`). | Done |
| 23 | `dcdc-bench/requirements-tested.txt:25` pins `setuptools @ file:///usr/share/python-wheels/...`, a Debian-local path that cannot install elsewhere. | `dcdc-bench/requirements-tested.txt:25` | Low | Drop that line or state that the file is a freeze record, not an install file. | Not done (outside the listed files) |
| 24 | `Documentation/Publishing.md:41` `git add` list omits `dcdc-bench`, `CONTRIBUTING.md`, `.editorconfig` and `.github`. | `Documentation/Publishing.md:41` | Low | Update the list after this branch merges. | Not done |
| 25 | README first screen: says what the 5 V demo is but not which hardware families are supported, the safety stance, or where a newcomer starts; no pointer to the dcdc-bench milestone position. | `README.md:1-27` | Medium | Snippets below (links to `dcdc-bench/docs/getting-started.md`, being written separately). | Proposed |
| 26 | README claims versus `implementation_status.md`: the converter claims at `README.md:10-25` (three-point workflow run with automatic HTML/PDF, 50–500 mA extended test, 1.725 A at 0.987 A from 24 V, 24 V and near-36 V curves to 2.5 A, 12 V start stopped, 15 V start held 12.134 V at 100 mA down to 9.108 V) match "Latest measured evidence" in `implementation_status.md:31-72`. | `README.md`, `implementation_status.md` | OK | None. | Done |
| 27 | README "Verify and publish" runs `python -m pytest`, which (root `testpaths`) covers `Software/tests` only. | `README.md:388-390` | Low | Snippet below adds the dcdc-bench command, the CI note and a link to `CONTRIBUTING.md`. | Proposed |
| 28 | README "Project folders" omits `dcdc-bench/`, `.github/`, `index.html`, `.nojekyll`. | `README.md:374-381` | Low | Snippet below. | Proposed |
| 29 | Python requirement: `README.md:8` "3.11+", `pyproject.toml:10` and `dcdc-bench/pyproject.toml:9` `>=3.11`, `tools/setup.py:25-26`, `Software/README.md:3`, `dcdc-bench/README.md:125` all agree. | — | OK | None. | Done |
| 30 | Version strings: `0.1.0` in `pyproject.toml:7`, `dcdc-bench/pyproject.toml:7`, `Software/src/benchctl/__init__.py:15`, `dcdc-bench/src/dcdc_bench/__init__.py:3`. | — | OK | None. | Done |
| 31 | The bold status paragraph is byte-identical in `dcdc-bench/README.md:6-10`, `docs/acceptance.md:12-16` and `docs/implementation_status.md:5-9`. `dcdc-bench/README.md:491-493` ("What comes next") carries a deliberately shortened variant without the M2 parenthetical and says "brief's Section 15" instead of "spec's". | three docs | OK | None; report only. | Done |
| 32 | Test-count statements differ: `dcdc-bench/README.md:449-451` reports "378 tests" and "57 tests", while `implementation_status.md:246-249` says counts are not carried and keeps one historical 393/393 figure. | `dcdc-bench/README.md`, `implementation_status.md` | Low | Align the README with the status document's policy when the final verification record is written. | Not done |
| 33 | No CI. | — | Medium | Added `.github/workflows/ci.yml` (design notes below). | Done |

## What changed on this branch

| File | Change |
| --- | --- |
| `.github/workflows/ci.yml` | New. Job `tests`: `ubuntu-latest`, Python 3.11 and 3.13, `pip install -e . -e './dcdc-bench[ui,report,real,test]'`, `pytest Software/tests -q`, `pytest dcdc-bench/tests -q -m 'not browser and not pdf and not integration'`. Job `documents` (`continue-on-error: true`, Python 3.13): apt `poppler-utils fonts-dejavu-core fonts-liberation`; `playwright install --with-deps chromium` and `BROWSER_PATH` set to Playwright's Chromium (as `tools/setup.py:60-65` does); Quarto 1.10.18 fetched and SHA-256-verified exactly as `tools/setup.py:38-53` does, extracted to `dcdc-bench/.tools/` (where `renderer._quarto()` and `test_pdf_check._typst()` look) and exported as `QUARTO_PATH`; version check; `dcdc-bench demo --out dcdc-bench/examples/generated`; `pytest dcdc-bench/tests -q -m 'browser or pdf' -o faulthandler_timeout=240` with `DCDC_DEMO_DIR` pointing at the demo; manifests, render logs and PDFs uploaded as a 7-day artifact. No cache, no stored secret (the built-in `github.token` is passed only to avoid the anonymous release-API rate limit). `permissions: contents: read`. |
| `.editorconfig` | New; see #16. |
| `CONTRIBUTING.md` | New; see #14. |
| `.gitignore` | Added `.tools/`, `.claude/worktrees/`, `.claude/settings.local.json`, `.codex/`, `.agents/`. |
| `pyproject.toml` | Added `keywords`, `classifiers`, `[project.urls]`. No `license`. |
| `dcdc-bench/pyproject.toml` | Added `readme`, `keywords`, `classifiers`, `[project.urls]`. No `license`. |
| `dcdc-bench/docs/github-readiness.md` | This document. |

Why the CI is shaped this way (from the tests, not from running them):

- `tests/test_documents.py:74-85` reads `DCDC_DEMO_DIR` and expects
  `<dir>/{normal,setup-limited,aborted}/*/reports/r*/report.html`, which is
  exactly what `services.demo()` writes.
- `test_pdf_build_manifest_reports_real_success` asserts
  `manifest["versions"]["quarto"] == "1.10.18"` and `manifest["status"] == "success"`;
  the renderer marks the PDF `failed-validation` when `pdftohtml` is missing
  (`reporting/pdf_check.py:464-468`, `renderer.py:1158-1166`), so
  `poppler-utils` is required, not optional, for the gates to pass.
- The `viewer` fixture (`test_documents.py:88-92`) launches Playwright's
  Chromium at `renderer._browser_path()`, which honours `BROWSER_PATH` first
  (`renderer.py:1169-1177`); Kaleido static figures use the same lookup, so one
  Playwright Chromium serves both.
- `integration`-marked tests need the bundled Typst binary or detached
  subprocess workers (`test_pdf_check.py:31-53`, `test_run02_reconnect.py:196`)
  and are excluded from the required job as instructed.
- The render memory gate (`resources.py`, defaults 150/600 MiB) is left at its
  defaults; a GitHub runner has ample memory, and the tests' `conftest.py`
  disables it for pytest anyway.

## Proposed README changes (not applied)

`README.md`, `implementation_status.md`, `acceptance.md` and the existing files
under `dcdc-bench/docs/` were not edited. The coordinator can apply these.

**1. First screen — replace `README.md:10-15`**

Old:

```markdown
**DC–DC converter work:** the separate [dcdc-bench project](dcdc-bench/README.md)
provides saved converter profiles, a local test interface, bounded real DC sweeps,
and interactive HTML/vector PDF reports. See [the bench workflow](dcdc-bench/docs/bench-ui.md).
On the development Pi, **[open the bench interface](http://localhost:8081/)**
using the existing port forward. Its [completed real workflow test](dcdc-bench/README.md#completed-test-through-the-interface)
includes the automatically generated HTML and PDF.
```

New:

```markdown
**Hardware:** Rigol DP800-series supplies and DL3000-series electronic loads over
LXI/VXI-11 (LAN); verified on a DP821A and a DL3031A. **Safety stance:** every
setpoint is checked against explicit, hand-maintained limits before a VISA
session opens; limits are never inferred from a model name; software limits
complement, never replace, the instruments' own OVP/OCP/OPP; tests and CI use
fake instruments only. **Start:** [Getting started](dcdc-bench/docs/getting-started.md)
· [Contributing](CONTRIBUTING.md).

**DC–DC converter work:** the separate [dcdc-bench project](dcdc-bench/README.md)
provides saved converter profiles, a local test interface, bounded real DC sweeps,
and interactive HTML/vector PDF reports. See [the bench workflow](dcdc-bench/docs/bench-ui.md)
and its milestone position in [implementation status](dcdc-bench/docs/implementation_status.md)
(M0 reached; M1 substantially reached; M2 partial; an M3 workflow slice
demonstrated; M4/M5 not started). Real converter runs additionally require
saved-profile approvals and a fresh wiring/serial confirmation at each Start.
The bench interface listens only on the bench computer's loopback interface
(`http://localhost:8081/` on the development Pi through an SSH port forward;
that address does not work from GitHub). Its [completed real workflow test](dcdc-bench/README.md#completed-test-through-the-interface)
includes the automatically generated HTML and PDF.
```

**2. Folder map — replace the code block at `README.md:374-381`**

Old:

```text
Documentation/   Architecture, limitations and GitHub publishing guide
Electrical/      Bench wiring and protection settings
Media/           README chart
Data/            Reports/CSV and Example_Run/; ignored local Runs/ and Logs/
Software/        src/, tests/, config/, recipes/, developer guide
pyproject.toml   Install and test entry point from the repository root
```

New:

```text
Documentation/   benchctl architecture, GitHub publishing guide, the DC–DC plan,
                 and bench-operator notes about the development Pi
Electrical/      Bench wiring and protection settings
Media/           README chart
Data/            Reports/CSV and Example_Run/; ignored local Runs/ and Logs/
Software/        benchctl: src/, tests/, config/, recipes/, developer guide
dcdc-bench/      DC–DC characterization subproject: own pyproject, tests, docs/
.github/         CI: fake-instrument tests on Python 3.11 and 3.13
index.html       GitHub Pages entry; redirects to the measured 5 V report
.nojekyll        Lets GitHub Pages serve the saved HTML reports unchanged
pyproject.toml   benchctl install and test entry point from the repository root
```

**3. Verify and publish — replace `README.md:386-395`**

Old:

```markdown
## Verify and publish

```bash
python -m pytest
```

Tests use fake instruments. See the [verification record](Data/Verification.md).
[Publishing to GitHub](Documentation/Publishing.md)
explains commit identity, ignored files, authentication and the first push.
Choose a license before inviting others to reuse the code.
```

New:

```markdown
## Verify and publish

```bash
python -m pytest Software/tests -q
python -m pytest dcdc-bench/tests -q -m 'not browser and not pdf and not integration'
```

Tests use fake instruments; the same commands run in
[GitHub Actions](.github/workflows/ci.yml) on Python 3.11 and 3.13. The
browser/PDF gates need Chromium and Quarto and run in a separate, non-blocking
CI job. See the [verification record](Data/Verification.md) and
[CONTRIBUTING.md](CONTRIBUTING.md). [Publishing to GitHub](Documentation/Publishing.md)
explains commit identity, ignored files, authentication and the first push.

## License

**To be chosen by the repository owner.** There is no `LICENSE` file yet, so no
reuse permission is granted beyond viewing on GitHub. Before inviting reuse,
check whether any code was adapted from the GPL-3.0 project referenced in
[the DC–DC plan](Documentation/DC-DC-Characterization-Plan.md), then add the
chosen license text as `LICENSE` and the matching `license` field to both
`pyproject.toml` files.
```

**4. Table of contents — add after `README.md:53`**

```markdown
- [License](#license)
```

**5. Other localhost links (owner decision, see #6).** If the links stay, a
one-line label immediately before each group suffices, for example in
`Data/README.md:14`:

```markdown
### Local converter measurements (development bench only — these links need the owner's SSH port forward)
```

## Owner decisions still needed

1. **License.** Choose one (and check the GPL-3.0 caveat in
   `Documentation/DC-DC-Characterization-Plan.md:376`). Then add `LICENSE`, the
   `license` field in both `pyproject.toml` files, and remove the README
   placeholder.
2. **Public status of `Data/`, `Media/`, `Electrical/`.** They are already on
   `origin/main` and GitHub Pages and contain no addresses or serials; confirm
   this stance still holds for the converter-era repository.
3. **Localhost report links.** Keep with a "local bench only" label, or replace
   with relative links to the review documents (`dcdc-bench/docs/*-results-review.md`).
   Done 2026-09-28: labeled or relinked in the three READMEs.
4. **Real serial numbers** in `cold-start-hypothesis.md` and
   `m2-qualification-plan.md` (#2): redact or accept.
5. **Owner-machine details** (`/home/jerome`, `jerome`, `rigol.local`) in the
   Pi notes (#3–#5): genericize or accept. Genericized on 2026-09-28 (forward
   edit; history unchanged).
6. **Placement of the three Pi operations notes** in `Documentation/` (#21).
