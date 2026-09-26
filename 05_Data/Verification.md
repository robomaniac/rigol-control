# Verification — updated 26 September 2026

- The automated regression suite passed with fake instruments, including bounded sweep
  expansion, setpoint validation before connection, cleanup, report generation,
  load configuration guards, and rejection of nonfinite instrument readings.
- A clean copy containing only publishable files installed successfully into
  a fresh virtual environment as a wheel. Dependency validation, offline sweep
  validation and preview generation passed without the editable source install.
- The current recipe expands to **21 loaded points plus baseline**, 132 actions
  and two cleanup actions, with 98.5 seconds of configured waits plus instrument
  communication.
- Chromium checks covered desktop 1440px and touch 390px layouts for the measured
  report, the public preview and a fixture with duplicate current coordinates.
  Hover/tap tooltips, crosshairs, keyboard controls, every slider point, filtering,
  CSV download and outside-tap dismissal passed. No page overflow, JavaScript
  console errors or network requests were observed.
- The rewritten reports explain the 5 V test, identify readings by current and
  direction, and compare voltage with each run's saved limits. Checks cover
  missing limits, incomplete runs, simulated results and below-minimum wording.
  A final desktop/mobile browser pass verified friendly labels, hover/tap,
  keyboard navigation and CSV export. Searching for `250 mA` returns exactly
  its two readings without accidentally matching neighbouring table cells.
- The current overview follows reading order and distinguishes requested from
  measured current. Tests verify its peak at reading 12, return at reading 22,
  and baseline provenance. Comparison axes use round mA tick positions while
  retaining the original numeric data. The report and runner checks passed
  together (67 tests); all 22 slider selections stay linked across four charts.
  Mobile checks also verified that tapping another chart keeps its tooltip
  visible and tapping outside dismisses it.
- The publishable files were scanned against the local instrument addresses and
  serial numbers. Test fixtures use reserved documentation addresses; private
  inventory, raw runs and traffic logs are ignored by Git.

## Live test — 26 September 2026

- The final automated regression suite passed **435 tests**. The served real
  report returned HTTP 200 with PASS status, 22 readings and four interactive
  charts. Its embedded CSV matches `power-test-results.csv`; both shareable
  files were checked for configured instrument addresses and serial numbers.
- Instrument identities were verified before control. Hardware protections were
  restored and read back: CH1 OVP enabled at 6 V, OCP enabled at 1 A; load CC range
  6 A, voltage limit 6 V, current limit 0.50 A. The recipe used a 5 V supply
  setpoint and 0.50 A supply current limit.
- The first attempt, `20260926T071044Z_load_sweep`, stopped at the 100 mA request
  after the load reported only 13.852 mA. The acceptance check failed and shutdown
  was verified. Its failed raw run was retained locally.
- Before retrying, the load's fixed-function configuration was normalized and a
  0.5-second pause was added between setting each current and enabling the load.
  The voltage, current and power acceptance criteria were unchanged. The precise
  cause of the earlier low reading has not been established.
- Run `20260926T072124Z_load_sweep` passed all acceptance checks: **21 loaded
  readings plus the starting reference**, completed in **104.85 seconds**.
  The load-end voltage ranged from **4.978736 to 4.989864 V**, within the chosen
  **4.75–5.25 V** window. The largest voltage difference was **26.264 mV**;
  peak measured current and power were **299.28 mA** and **1.490034 W**.
- Independent fresh identity checks and state readbacks after the run confirmed
  the load input **off**, CH1 output **off**, and load terminal voltage **0.0 V**.
  The postflight record is saved with the ignored local run data.

The [real 21-point report](power-test-report.html) and [CSV](power-test-results.csv)
contain this successful run. The [original measured report](demo-report.html)
retains the three-point run used for the unchanged README SVG. The
[21-point preview](sweep-preview.html) remains explicitly simulated.
