"""Small presentation helpers; no GUI, transport, worker or filesystem effects."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone, tzinfo
import math
import re
from pathlib import PurePosixPath
from urllib.parse import quote


def target_values(text: str, *, quantity: str, allow_zero: bool = False) -> list[float]:
    pieces = [piece for piece in re.split(r"[\s,;]+", str(text).strip()) if piece]
    if not pieces:
        raise ValueError(f"Enter at least one {quantity}.")
    if len(pieces) > 1000:
        raise ValueError(f"Use at most 1,000 {quantity} values.")
    try:
        values = [float(piece) for piece in pieces]
    except ValueError as exc:
        raise ValueError(f"Enter {quantity} as numbers separated by commas; ranges and formulas are not accepted.") from exc
    if any(not math.isfinite(value) or value < 0 or (not allow_zero and value == 0) for value in values):
        raise ValueError(f"Every {quantity} must be finite and {'nonnegative' if allow_zero else 'positive'}.")
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {quantity} values would repeat measurements; remove the duplicates.")
    return values


# --- Operator-language validation ----------------------------------------------
# The editors' visible labels, keyed by the form field (and, for pydantic errors,
# by the saved field path), so every refusal names the field the operator sees.

DUT_FIELD_LABELS = {'input_voltage_min_V': 'Minimum input (V)', 'input_voltage_max_V': 'Maximum input (V)',
                    'output_voltage_nominal_V': 'Nominal output (V)', 'output_current_rated_A': 'Rated output current (A)',
                    'output_power_rated_W': 'Rated output power (W)'}
RECIPE_FIELD_LABELS = {'minimum_dwell_s': 'Minimum settling time (s)', 'duration_s': 'Measure each load for (s)',
                       'efficiency_estimate_pct': 'Planning efficiency estimate (%)',
                       'current_budget_pct': 'Use this share of source current (%)'}
LIMIT_FIELD_LABELS = {'source_current_limit_A': 'Supply current limit (A)', 'dut_input_overvoltage_V': 'Input over-voltage (V)',
                      'dut_output_overvoltage_V': 'Output voltage guard (V)', 'output_overcurrent_A': 'Output current guard (A)'}
FIELD_LABELS = {**{'ratings.' + key: label for key, label in DUT_FIELD_LABELS.items()},
                **{'protective_controls.' + key: label for key, label in LIMIT_FIELD_LABELS.items()},
                'profile_id': 'Save converter as', 'identity.model': 'Converter / board model',
                'identity.sample_id': 'Sample ID or board revision', 'recipe_id': 'Save test as',
                'title': 'Plain name shown on the card', 'category': 'Category', 'standard_clause': 'Standard clause',
                'description': 'Description', 'settling.minimum_dwell_s': RECIPE_FIELD_LABELS['minimum_dwell_s'],
                'settling.timeout_s': 'Settling timeout (s)', 'acquisition.duration_s': RECIPE_FIELD_LABELS['duration_s'],
                'planning.efficiency_estimate_fraction': RECIPE_FIELD_LABELS['efficiency_estimate_pct'],
                'planning.source_current_budget_fraction': RECIPE_FIELD_LABELS['current_budget_pct']}


def number(values: dict, key: str, label: str, *, minimum=None, maximum=None, exclusive_minimum: bool = False) -> float:
    """A form number as a float, refused in operator language.

    A cleared ``ui.number`` field arrives as ``None``: the message says "Enter a
    number for “<label>”", never a Python ``TypeError``. A bound names the field.
    """
    raw = values.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ValueError(f'Enter a number for “{label}”.')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f'“{label}” must be a number.') from None
    if not math.isfinite(value):
        raise ValueError(f'“{label}” must be a finite number.')
    if minimum is not None and (value <= minimum if exclusive_minimum else value < minimum):
        raise ValueError(f'“{label}” must be {"greater than" if exclusive_minimum else "at least"} {minimum:g}.')
    if maximum is not None and value > maximum:
        raise ValueError(f'“{label}” must be at most {maximum:g}.')
    return value


def friendly_error(exc) -> str:
    """A validation error as one operator sentence per field.

    pydantic errors name the saved field path; the page shows the editor label
    for it when one exists and drops pydantic's "Value error, " prefix. Any
    other exception is shown as its own text.
    """
    if not hasattr(exc, 'errors'):
        return str(exc)
    parts = []
    for item in exc.errors()[:4]:
        loc = '.'.join(str(part) for part in item.get('loc', ()))
        label = FIELD_LABELS.get(loc)
        message = re.sub(r'^Value error, ', '', str(item.get('msg', '')))
        parts.append((f'“{label}”: ' if label else loc + ': ' if loc else '') + message)
    return '; '.join(parts)


def edited_dut(original: dict, values: dict) -> dict:
    result = copy.deepcopy(original)
    result['profile_id'] = str(values['profile_id'] or '').strip()
    if not result['profile_id']:
        raise ValueError('Enter a file name under “Save converter as”.')
    result['identity'].update(model=str(values['model'] or '').strip(),
                              sample_id=str(values.get('sample_id') or '').strip() or None)
    if not result['identity']['model']:
        raise ValueError('Enter the “Converter / board model”.')
    for key, label in DUT_FIELD_LABELS.items():
        result['ratings'][key] = number(values, key, label, minimum=0, exclusive_minimum=True)
    if result['ratings']['input_voltage_min_V'] > result['ratings']['input_voltage_max_V']:
        raise ValueError(f'“{DUT_FIELD_LABELS["input_voltage_min_V"]}” must not exceed “{DUT_FIELD_LABELS["input_voltage_max_V"]}”.')
    result['ratings']['verified_from_sample_label'] = bool(values.get('verified_from_sample_label', False))
    # Saved approvals gate whether a real plan can be previewed at all; each Start
    # additionally binds a fresh physical confirmation to the plan and inventory hashes.
    approval = result.setdefault('execution_approval', {})
    for key in ('real_hardware_enabled', 'wiring_and_polarity_confirmed'):
        if key in values:
            approval[key] = bool(values[key])
    return result


def edited_recipe(original: dict, values: dict, *, dut_id: str, test_id: str, mode: str | None = None) -> dict:
    """The saved recipe with the form's grid and text applied.

    ``mode`` is legacy: real vs simulated comes from the selected bench, so the
    page passes none and the saved recipe carries ``execution_mode: null``.
    Optional card text (``title``, ``category``, ``description``,
    ``standard_clause``) is applied only when the form supplies it.
    """
    result = copy.deepcopy(original)
    result.update(recipe_id=str(values['recipe_id'] or '').strip(), dut_profile_id=dut_id, execution_mode=mode)
    if not result['recipe_id']:
        raise ValueError('Enter a file name under “Save test as”.')
    for key in ('title', 'category', 'description', 'standard_clause'):
        if key in values:
            result[key] = str(values[key] or '').strip() or None
    test = next((test for test in result['tests'] if test['id'] == test_id), None)
    if test is None:
        raise ValueError('Select a test from the saved recipe before editing it.')
    test['input_voltage_targets_V'] = target_values(values['voltages'], quantity='input voltage')
    test['output_current_targets_A'] = target_values(values['currents'], quantity='load current', allow_zero=True)
    labels = RECIPE_FIELD_LABELS
    dwell = number(values, 'minimum_dwell_s', labels['minimum_dwell_s'], minimum=0)
    timeout = result['settling'].get('timeout_s', 30)
    if isinstance(timeout, (int, float)) and dwell > timeout:
        # The saved settling timeout is not a visible field; the message names the one that is.
        raise ValueError(f'“{labels["minimum_dwell_s"]}” must be at most {timeout:g} s, this test’s settling timeout.')
    result['settling']['minimum_dwell_s'] = dwell
    result['acquisition']['duration_s'] = number(values, 'duration_s', labels['duration_s'], minimum=0, exclusive_minimum=True)
    result['planning']['efficiency_estimate_fraction'] = number(values, 'efficiency_estimate_pct', labels['efficiency_estimate_pct'],
                                                                minimum=0, maximum=100, exclusive_minimum=True) / 100
    result['planning']['source_current_budget_fraction'] = number(values, 'current_budget_pct', labels['current_budget_pct'],
                                                                  minimum=0, maximum=100, exclusive_minimum=True) / 100
    return result


def quantity(value, unit: str, *, digits: int = 4) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return '—'
    return f'{value:.{digits}g} {unit}'


# One vocabulary for a requested point's fate: the planner's own status words, as the
# CLI JSON and the saved plan print them, with a legend the page shows once.
PLAN_STATUS_LEGEND = (
    ('executable', 'will run'),
    ('assumption_limited', 'kept in the plan but skipped: the planning budget (assumed efficiency × share of the supply '
                           'current) says the supply cannot feed it; the request is not reduced to fit'),
    ('approval_blocked', 'kept in the plan but skipped until the saved approvals (converter, wiring, limits) are true'),
    ('unsupported', 'kept in the plan but skipped: outside what this bench or its backend can do'),
)


def plan_rows(preview: dict) -> list[dict]:
    return [{**point, 'input_display': quantity(point.get('vin_target_V'), 'V'),
             'load_display': quantity(point.get('iout_target_A'), 'A'),
             'estimated_display': quantity(point.get('estimated_input_current_A'), 'A'),
             'status_display': str(point.get('status') or 'unknown')}
            for point in preview.get('points', [])]


def artifact_url(job_id: str, relative: str) -> str:
    path = PurePosixPath(relative)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', job_id) or not path.parts or path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('Invalid artifact location')
    return '/jobs/' + quote(job_id, safe='') + '/files/' + '/'.join(quote(part, safe='') for part in path.parts)


# Artifact statuses whose file is kept on disk and stays reachable from the UI,
# with the qualifier appended to the link label.
KEPT_ARTIFACT_STATUSES = {'success': '', 'unverified': ' (not verified: checker tool missing)',
                          'failed-validation': ' (failed the layout check; kept for inspection)'}


def report_link_rows(snapshot: dict) -> list[tuple[str, str]]:
    """(label, relative report path) for every kept artifact of a job snapshot.

    A PDF the checker could not verify, or that failed its layout check, is kept
    and linked with its status in the label; a failed or missing artifact is not.
    """
    if not snapshot.get('report_dir'):
        return []
    artifacts = snapshot.get('report_artifacts') or {}
    rows = []
    for filename, label, kind in (('report.html', 'Open HTML', 'html'), ('report.pdf', 'Open PDF', 'pdf'),
                                  ('report_model.json', 'Report data JSON', 'model')):
        status = (artifacts.get(kind) or {}).get('status')
        if status in KEPT_ARTIFACT_STATUSES:
            rows.append((label + KEPT_ARTIFACT_STATUSES[status], 'report/' + filename))
    return rows


def job_actions(snapshot: dict) -> list[str]:
    """Operator actions for a job state: 'stop' while a worker may run, 'dequeue' for a queued report."""
    state = snapshot.get('state')
    if state in ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested'):
        return ['stop']
    if state == 'report-queued':
        return ['dequeue']
    return []


DEQUEUED_ERROR_PREFIX = 'Report generation was removed from the queue'


def dequeued(snapshot: dict) -> bool:
    """The operator removed this job's report from the queue: no report was generated, none failed."""
    return bool(snapshot.get('dequeued')) or str(snapshot.get('error') or '').startswith(DEQUEUED_ERROR_PREFIX)


def state_label(snapshot: dict) -> str:
    state = str(snapshot.get('state', 'unknown'))
    if snapshot.get('cancel_requested') and state in ('queued', 'acquiring', 'reporting'):
        return 'Stop requested — waiting for the worker'
    if state == 'cancelled' and dequeued(snapshot):
        return 'Removed from the report queue'
    labels = {'queued': 'Waiting to start', 'running': 'Acquiring measurements', 'acquiring': 'Acquiring measurements',
              'starting': 'Checking the bench', 'rendering': 'Preparing HTML and PDF',
              'reporting': 'Preparing HTML and PDF',
              'report-queued': 'Measurements saved — report queued',
              'analyzing': 'Analyzing saved measurements', 'completed': 'Complete',
              'cancel_requested': 'Stop requested — waiting for shutdown',
              'stopping': 'Stop requested — waiting for shutdown', 'cancelled': 'Stopped',
              'aborted': 'Acquisition stopped', 'failed': 'Needs attention',
              'report_failed': 'Measurements saved; report needs attention'}
    return labels.get(state, state.replace('_', ' ').capitalize())


def job_title(snapshot: dict, *, zone: tzinfo | None = None) -> str:
    """'<converter> · <local start time>'; the time is omitted when the record has none."""
    name = str(snapshot.get('dut_model') or 'Converter test')
    started = local_time_text(snapshot.get('created_utc'), zone=zone)
    return name if started == UNKNOWN_TIME else name + ' · ' + started


def shutdown_label(snapshot: dict) -> str:
    shutdown = snapshot.get('shutdown') or {}
    if not shutdown:
        return 'Output state has not been verified yet.'
    required = {'source', 'load', 'source_deadline'} if snapshot.get('mode') == 'real' else {'source', 'load'}
    if isinstance(shutdown, dict) and required <= shutdown.keys() and all(
            isinstance(record, dict) and record.get('verified') is True and
            str(record.get('state', '')).upper() == 'OFF' for record in shutdown.values()):
        return 'Supply output and electronic load are verified OFF.'
    return 'Output shutdown is not fully verified. Check the instruments before touching the wiring.'


# --- Operator-facing time display -------------------------------------------
# Evidence files record UTC (spec §8.2). The page shows the bench computer's
# local wall clock instead, because that is the clock on the operator's wrist;
# nothing here is written back to disk.

UNKNOWN_TIME = 'unknown'
LOCAL_TIME_FORMAT = '%H:%M:%S %Z (%Y-%m-%d)'


def _parse_utc(iso_utc) -> datetime | None:
    if not isinstance(iso_utc, str) or not iso_utc.strip():
        return None
    try:
        parsed = datetime.fromisoformat(iso_utc.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def local_time_text(iso_utc, *, zone: tzinfo | None = None) -> str:
    """An ISO UTC instant as '13:40:12 PDT (2026-09-29)' in the bench computer's local zone.

    ``zone`` defaults to the system zone through ``datetime.astimezone()``; it is
    a parameter only so tests do not depend on the machine they run on. A naive
    string is taken as UTC (how the workers write it). ``None`` or unparsable
    input gives ``'unknown'`` rather than a misleading time.
    """
    parsed = _parse_utc(iso_utc)
    if parsed is None:
        return UNKNOWN_TIME
    return parsed.astimezone(zone).strftime(LOCAL_TIME_FORMAT)


def local_zone_name(zone: tzinfo | None = None) -> str:
    """The abbreviation the page shows for its clock, e.g. 'PDT'."""
    return datetime.now(timezone.utc).astimezone(zone).tzname() or 'local time'


def time_legend(zone: tzinfo | None = None) -> str:
    return f'Times shown in bench-computer local time ({local_zone_name(zone)}); evidence files record UTC.'


def elapsed_text(iso_utc, now: datetime | None = None) -> str:
    """Wall-clock time since ``iso_utc`` as 'm:ss' or 'h:mm:ss'; '' when the start is unknown."""
    started = _parse_utc(iso_utc)
    if started is None:
        return ''
    seconds = int(max(timedelta(0), (now or datetime.now(timezone.utc)) - started).total_seconds())
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours}:{minutes:02d}:{secs:02d}' if hours else f'{minutes}:{secs:02d}'


def event_text(event, *, zone: tzinfo | None = None) -> str:
    """One recorded run event as '<local time> · <kind> key=value …' for the Recent events list."""
    if not isinstance(event, dict):
        return str(event)
    hidden = {'event', 'timestamp_utc', 'run_id', 'monotonic_s'}
    details = ' '.join(f'{key}={value}' for key, value in event.items() if key not in hidden)
    text = local_time_text(event.get('timestamp_utc'), zone=zone) + ' · ' + str(event.get('event', 'event'))
    return text + (' ' + details if details else '')


# --- Background-activity indicator and Reports-tab freshness -----------------

# Job states during which some process is still working for the operator: the
# acquisition worker, the report dispatcher's queue, or the report-only worker.
ACTIVITY_STATES = ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested',
                   'analyzing', 'rendering', 'reporting', 'report-queued')
# States in which a worker process owns the bench (the three questions lock, Start is refused).
WORKING_STATES = ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested',
                  'analyzing', 'rendering', 'reporting')
# The mode word every job-related phrase starts with, so a passer-by can tell from the header.
MODE_PREFIX = {'mock': 'Simulation: ', 'real': 'Real bench: '}


def deferred_text(snapshot: dict | None) -> str:
    """Why a queued report has not started, in operator language; '' when nothing is deferred.

    The dispatcher records the memory gate's stable reason (``MemAvailable below
    150 MiB``) and, in ``deferred_memory``, the numbers it saw. The page says
    "Waiting for free memory: 96 MiB available, 150 MiB needed" instead of the
    ``/proc/meminfo`` field name; the raw reason stays available as a tooltip.
    """
    reason = (snapshot or {}).get('deferred_reason')
    if not reason:
        return ''
    reason = str(reason)
    # Whole-reason cases first: the lease and gate messages carry their own "; ".
    if reason.startswith('bench lease held'):
        return 'Waiting for the bench: another acquisition or report is still running'
    if reason.startswith('memory gate misconfigured'):
        return 'Waiting: the memory gate is misconfigured — ' + reason.split(': ', 1)[-1]
    memory = (snapshot or {}).get('deferred_memory') or {}
    parts = []
    for piece in reason.split('; '):
        low = re.fullmatch(r'MemAvailable below (\S+) MiB', piece)
        if low:
            seen = memory.get('available_mib')
            have = f'{seen:.0f} MiB available' if isinstance(seen, (int, float)) else 'less than that available'
            parts.append(f'Waiting for free memory: {have}, {low.group(1)} MiB needed')
            continue
        combined = re.fullmatch(r'MemAvailable\+SwapFree below (\S+) MiB', piece)
        if combined:
            seen = memory.get('available_plus_swap_free_mib')
            have = f'{seen:.0f} MiB free memory and swap together' if isinstance(seen, (int, float)) else 'less than that free'
            parts.append(f'Waiting for free memory and swap: {have}, {combined.group(1)} MiB needed')
            continue
        parts.append('Waiting: ' + piece)
    return '; '.join(parts)


def activity_text(snapshot: dict | None) -> str:
    """Short header phrase for work in progress, prefixed with the mode; '' when the job needs no indicator."""
    if not snapshot:
        return ''
    state = str(snapshot.get('state', ''))
    if state not in ACTIVITY_STATES:
        return ''
    prefix = MODE_PREFIX.get(snapshot.get('mode'), '')
    if snapshot.get('cancel_requested') or state in ('stopping', 'cancel_requested'):
        return prefix + 'Stopping… waiting for both outputs to be verified OFF'
    if state == 'queued':
        return prefix + 'Queued — waiting for the worker to start'
    if state == 'starting':
        return prefix + 'Starting — checking the bench'
    if state in ('running', 'acquiring'):
        progress = snapshot.get('progress') or {}
        total = progress.get('total') or 0
        if total:
            return prefix + f'Acquiring… point {min((progress.get("completed") or 0) + 1, total)} of {total}'
        return prefix + 'Acquiring… preparing the run'
    if state == 'report-queued':
        waiting = deferred_text(snapshot)
        return prefix + ('Report queued — ' + waiting[0].lower() + waiting[1:] if waiting
                         else 'Report queued — starts when the bench is idle')
    return prefix + 'Generating report…'


def bench_job(jobs: list[dict]) -> dict | None:
    """The job the page follows when it has none of its own: the newest working job, else the oldest queued report.

    Page load, F5 and a second tab all attach through this, so the header, the
    lock and Start describe the bench rather than the job one tab happened to start.
    """
    working = [job for job in jobs if str(job.get('state')) in WORKING_STATES]
    if working:
        return working[0]  # list_jobs() is newest first
    queued = [job for job in jobs if job.get('state') == 'report-queued']
    return min(queued, key=lambda job: str(job.get('queued_utc') or '')) if queued else None


def saved_runs_key(snapshot: dict) -> tuple:
    """What the saved-runs list shows for a job: its state and the report links it offers.

    The Reports tab is refreshed when this changes between polls, so the list
    follows the job without a busy loop or a manual Refresh.
    """
    return (str(snapshot.get('state')), tuple(relative for _, relative in report_link_rows(snapshot)))


def report_became_ready(previous: tuple | None, current: tuple) -> bool:
    """A kept report appeared for a job the page had already seen without one."""
    return previous is not None and not previous[1] and bool(current[1])


# --- One-page bench: card text, bench tiles, plan panel, reports table --------
# Everything here reads saved-profile dicts (JobService.load_profile output) and
# preview/status dicts; nothing is written back.

DEFAULT_CATEGORY = 'Normal operating voltage'
# The mode is named "Simulation" everywhere it is named: tile, header pill, Start, Reports rows.
START_LABELS = {'mock': 'Start simulation', 'real': 'Start test on the real bench'}
BENCH_NAMES = {'mock': 'Simulation', 'real': 'Real bench'}
REPORT_BENCH_LABELS = {'mock': 'Simulation · synthetic data', 'real': 'Real bench · measured'}
DELETE_PROMPTS = {'dut': 'Delete this saved converter? Past runs keep their own copy.',
                  'recipe': 'Delete this saved test? Past runs keep their own copy.',
                  'bench': 'Delete this saved bench preset? Past runs keep their own copy.'}

# What each bench can and cannot do, shown on its tile at all times. The real
# bench's lines follow the supported envelope in docs/configured-runs.md.
SIMULATION_CAN = (
    'Runs a deterministic synthetic converter, source and load: a software model on a virtual clock.',
    'Reproduces realistic supply current limiting and start-up behaviour.',
    'Labels every output SYNTHETIC: this page, the HTML, the PDF and the CSV export.',
    'Touches no instrument: no driver is loaded and nothing is switched on.',
    'Uses the same report layout and the same workflow as the real bench.',
)
SIMULATION_CANNOT = (
    'Measure your converter: the numbers describe the model, not the sample on the bench.',
    'Prove anything about safety, protective limits or a real start-up.',
    'Show ripple, transients or thermal behaviour.',
    'Give an instrument uncertainty: any ± in its report comes from the synthetic specification, not from an instrument.',
)
REAL_CAN = (
    'Measure steady DC efficiency, output regulation and power loss at loaded points of 0.05–2.5 A and at most 34 W.',
    'Program 1–35.8 V input inside the converter rating, cold-starting the converter once per input voltage.',
    'Stop the run on the input over-voltage guard, the output guards and the supply current limit (polled DC criteria).',
)
REAL_CANNOT = (
    'Reach the 48 W rating: the 1 A source cannot feed it; over-budget points stay in the plan and are skipped.',
    'Run unsupervised: an operator stays at the bench, and Start needs the saved approvals plus a fresh wiring, CH1, limits and serial confirmation.',
    'Measure temperature, ripple, transients or dynamic response; the guards are not transient protection.',
    'Certify accuracy: uncertainty is unquantified until the readback specifications are transcribed.',
)
SYNTHETIC_UNCERTAINTY_NOTE = ('Any ± in this report is uncertainty from the synthetic specification, not an instrument: '
                              'the mock bench profile carries example readback specifications so the budget can be demonstrated.')

# What follows Start in the simulation, in the order the page will show it, with the time each step takes.
SIMULATION_SEQUENCE = (
    ('Acquiring measurements', 'seconds — the model runs on a virtual clock'),
    ('Measurements saved — report queued', 'waits until no test is running and enough memory is free'),
    ('Preparing HTML and PDF', 'typically one to four minutes on a Raspberry Pi, longer while memory is short'),
    ('Complete', 'the links appear under Run and in Reports'),
)
SIMULATION_TIME_ESTIMATE = 'Measurements: seconds (virtual clock) · Report: typically 1–4 min on a Raspberry Pi'


def simulation_time_text(seconds) -> str:
    """Plan-panel estimate for a simulated run: the planner's wall-time estimate when it exists, else the generic text."""
    shown = duration_text(seconds)
    if not shown:
        return SIMULATION_TIME_ESTIMATE
    approx = shown if shown.startswith('~') else f'about {shown}'   # never "about ~42 s"
    return f'Measurements: {approx} (simulated) · Report: typically 1–4 min on a Raspberry Pi'


def sequence_step(snapshot: dict | None) -> int | None:
    """Index into SIMULATION_SEQUENCE for a simulation job's current step; None when it does not apply."""
    if not snapshot or snapshot.get('mode') != 'mock':
        return None
    state = str(snapshot.get('state', ''))
    if state in ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested'):
        return 2 if snapshot.get('action') == 'report-only' else 0
    if state == 'report-queued':
        return 1
    if state in ('analyzing', 'rendering', 'reporting'):
        return 2
    if state == 'completed':
        return 3
    return None


def envelope_rows(bench: dict) -> list[tuple[str, str]]:
    """The simulated bench's envelope as (label, value) rows, so a skipped simulated point is predictable from the tile."""
    source, load = bench.get('source') or {}, bench.get('load') or {}

    def span(low, high, unit):
        if not all(isinstance(v, (int, float)) for v in (low, high)):
            return '—'
        return f'{low:g}–{high:g} {unit}'

    def value(item, unit):
        return f'{item:g} {unit}' if isinstance(item, (int, float)) and not isinstance(item, bool) else '—'
    rows = [('Synthetic source', span(source.get('min_voltage_V'), source.get('max_voltage_V'), 'V') + ' · ' +
             value(source.get('max_current_A'), 'A') + ' · ' + value(source.get('max_power_W'), 'W')),
            ('Synthetic load', f"constant current, up to {value(load.get('max_current_A'), 'A')}")]
    limits = [(label, shown) for label, shown in limits_rows(bench) if shown != '—']
    rows.append(('Protective limits', '; '.join(f'{label} {shown}' for label, shown in limits) if limits
                 else 'none — only the planning budget bounds the plan'))
    rows.append(('Readback uncertainty', 'synthetic example specification, not an instrument'))
    return rows


def _unique(values) -> list[float]:
    seen: list[float] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def values_text(values, unit: str, *, range_join: str) -> str:
    """'12 / 24 / 30 V' for up to four values; '15…35.8 V' or '0–1 A' (min to max) beyond that."""
    unique = _unique(float(v) for v in values)
    if not unique:
        return '— ' + unit
    if len(unique) <= 4:
        return ' / '.join(f'{v:g}' for v in unique) + ' ' + unit
    return f'{min(unique):g}{range_join}{max(unique):g} {unit}'


def recipe_grid(recipe: dict) -> str:
    """'24 V × 0 / 0.1 A': every requested input voltage against every requested load, over all tests."""
    volts = [v for test in recipe.get('tests', []) for v in test.get('input_voltage_targets_V', [])]
    amps = [a for test in recipe.get('tests', []) for a in test.get('output_current_targets_A', [])]
    return values_text(volts, 'V', range_join='…') + ' × ' + values_text(amps, 'A', range_join='–')


def recipe_title(recipe: dict) -> str:
    """The saved plain name, else the grid ('12 / 24 / 30 V × 0–1 A') so every card has a title."""
    return str(recipe.get('title') or '').strip() or recipe_grid(recipe)


def recipe_category(recipe: dict) -> str:
    return str(recipe.get('category') or '').strip() or DEFAULT_CATEGORY


def point_count(recipe: dict) -> int:
    return sum(len(test.get('input_voltage_targets_V', [])) * len(test.get('output_current_targets_A', []))
               for test in recipe.get('tests', []))


def duration_text(seconds) -> str:
    """'~45 s' below a minute and a half, else '~N min'; '' when there is no estimate."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
        return ''
    return f'~{round(seconds)} s' if seconds < 90 else f'~{round(seconds / 60)} min'


def card_meta(count: int, mode: str, seconds=None) -> str:
    """'2 points · ~1 min' on the real bench; the simulated bench runs on a virtual clock and gets no time."""
    text = f'{count} point' + ('' if count == 1 else 's')
    estimate = duration_text(seconds) if mode == 'real' else ''
    return text + (' · ' + estimate if estimate else ' · simulated' if mode == 'mock' else '')


def grouped_recipes(recipes: dict[str, dict]) -> list[tuple[str, list[tuple[str, dict]]]]:
    """[(category, [(name, recipe), …])]: the default category first, the rest alphabetically; cards by title."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for name, recipe in recipes.items():
        groups.setdefault(recipe_category(recipe), []).append((name, recipe))
    order = sorted(groups, key=lambda category: (category != DEFAULT_CATEGORY, category.lower()))
    return [(category, sorted(groups[category], key=lambda item: recipe_title(item[1]).lower())) for category in order]


def dut_subtitle(dut: dict) -> str:
    """'9–36 V in, 12 V / 4 A out · sample S1'."""
    ratings = dut.get('ratings', {})
    low, high = ratings.get('input_voltage_min_V'), ratings.get('input_voltage_max_V')
    span = f'{low:g} V in' if low == high else f'{low:g}–{high:g} V in'
    text = span + f", {ratings.get('output_voltage_nominal_V'):g} V / {ratings.get('output_current_rated_A'):g} A out"
    sample = (dut.get('identity') or {}).get('sample_id')
    return text + (f' · sample {sample}' if sample else '')


def dut_approved(dut: dict) -> bool:
    approval = dut.get('execution_approval') or {}
    return bool(approval.get('real_hardware_enabled')) and bool(approval.get('wiring_and_polarity_confirmed'))


def bench_title(bench: dict) -> str:
    """The saved plain name; a bench without one shows its identifier (a name like '24 V converter tests' is not derivable)."""
    return str(bench.get('title') or '').strip() or str(bench.get('bench_id'))


def bench_equipment(bench: dict, inventory: dict | None = None) -> str:
    """'DP821A CH1 + DL3031A' from the bench profile, else the inventory models, else generic words."""
    inventory = inventory or {}
    source, load = bench.get('source') or {}, bench.get('load') or {}
    supply = source.get('physical_model') or (inventory.get('source') or {}).get('model') or 'supply'
    sink = load.get('physical_model') or (inventory.get('load') or {}).get('model') or 'load'
    return f"{supply} CH{source.get('channel', 1)} + {sink}"


LIMIT_FIELDS = (('source_current_limit_A', 'Supply current limit', 'A'),
                ('dut_input_overvoltage_V', 'Input over-voltage', 'V'),
                ('dut_output_overvoltage_V', 'Output voltage guard', 'V'),
                ('output_overcurrent_A', 'Output current guard', 'A'))


def limits_rows(bench: dict) -> list[tuple[str, str]]:
    """The four protective limits as (label, value) rows; a missing limit shows '—', never a default."""
    controls = bench.get('protective_controls') or {}
    return [(label, quantity(controls.get(key), unit)) for key, label, unit in LIMIT_FIELDS]


def limits_summary(bench: dict) -> str:
    """'1 A supply · 26 V input · 13.2 V / 2.55 A output' for the Start confirmation."""
    controls = bench.get('protective_controls') or {}
    return (quantity(controls.get('source_current_limit_A'), 'A') + ' supply · ' +
            quantity(controls.get('dut_input_overvoltage_V'), 'V') + ' input · ' +
            quantity(controls.get('dut_output_overvoltage_V'), 'V') + ' / ' +
            quantity(controls.get('output_overcurrent_A'), 'A') + ' output')


def skip_reasons(preview: dict) -> list[tuple[int, str, str]]:
    """(count, planner status, reason) for every point that will not run, most frequent first; identical reasons are merged."""
    counts: dict[tuple[str, str], int] = {}
    for point in preview.get('points', []):
        if point.get('status') != 'executable':
            key = (str(point.get('status') or 'unknown'), str(point.get('reason') or 'no reason recorded'))
            counts[key] = counts.get(key, 0) + 1
    return sorted(((count, status, reason) for (status, reason), count in counts.items()),
                  key=lambda item: (-item[0], item[1], item[2]))


def summary_text(dut: dict | None, mode: str, bench: dict | None, recipe: dict | None) -> str:
    """'12T12-4A · Real bench (24 V converter tests) · 24 V small grid' for the header and the bottom bar."""
    converter = (dut or {}).get('identity', {}).get('model') if dut else None
    bench_text = BENCH_NAMES.get(mode, mode)
    if mode == 'real' and bench:
        bench_text += f' ({bench_title(bench)})'
    return ' · '.join([converter or '— no converter —', bench_text, recipe_title(recipe) if recipe else '— no test —'])


def report_rows(jobs: list[dict], *, zone: tzinfo | None = None, recipes: dict[str, dict] | None = None) -> list[dict]:
    """One row per saved run for the Reports table: local start time, run, bench, status, kept report links.

    ``recipes`` (name -> saved recipe) supplies the current plain title when the
    job's recipe still exists; the job's own recorded title, then its recipe id,
    are the fallbacks so renamed or deleted tests never blank a row.
    """
    rows = []
    for job in jobs:
        recipe_name = job.get('recipe_id')
        saved = (recipes or {}).get(recipe_name) if recipe_name else None
        test = recipe_title(saved) if saved else job.get('recipe_title') or recipe_name
        progress = job.get('progress') or {}
        total = progress.get('total') or 0
        terminal = job.get('state') in ('completed', 'aborted', 'failed', 'cancelled', 'report_failed')
        real = job.get('mode') == 'real'
        rows.append({'job_id': job['job_id'], 'when': local_time_text(job.get('created_utc'), zone=zone),
                     'run': ' · '.join(part for part in (str(job.get('dut_model') or 'Converter test'), test) if part),
                     'bench': REPORT_BENCH_LABELS['real' if real else 'mock'], 'real': real,
                     'status': state_label(job),
                     'waiting': deferred_text(job) if job.get('state') == 'report-queued' else '',
                     'points': f"{progress.get('completed', 0)} / {total} points" if total else '',
                     'links': [(label, relative) for label, relative in report_link_rows(job) if not relative.endswith('.json')],
                     'regenerate': bool(terminal and job.get('run_dir')),
                     'dequeue': 'dequeue' in job_actions(job)})
    return rows


def run_option_text(job: dict, *, zone: tzinfo | None = None) -> str:
    """'<converter> · <local start> · Simulation · synthetic data · Complete' for a run chooser such as /annotations."""
    return ' · '.join((job_title(job, zone=zone), REPORT_BENCH_LABELS['real' if job.get('mode') == 'real' else 'mock'],
                       state_label(job)))
