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


def edited_dut(original: dict, values: dict) -> dict:
    result = copy.deepcopy(original)
    result['profile_id'] = str(values['profile_id']).strip()
    result['identity'].update(model=str(values['model']).strip(),
                              sample_id=str(values.get('sample_id') or '').strip() or None)
    for key in ('input_voltage_min_V', 'input_voltage_max_V', 'output_voltage_nominal_V',
                'output_current_rated_A', 'output_power_rated_W'):
        result['ratings'][key] = float(values[key])
    result['ratings']['verified_from_sample_label'] = bool(values.get('verified_from_sample_label', False))
    # Saved approvals gate whether a real plan can be previewed at all; each Start
    # additionally binds a fresh physical confirmation to the plan and inventory hashes.
    approval = result.setdefault('execution_approval', {})
    for key in ('real_hardware_enabled', 'wiring_and_polarity_confirmed'):
        if key in values:
            approval[key] = bool(values[key])
    return result


def edited_recipe(original: dict, values: dict, *, dut_id: str, mode: str, test_id: str) -> dict:
    result = copy.deepcopy(original)
    result.update(recipe_id=str(values['recipe_id']).strip(), dut_profile_id=dut_id, execution_mode=mode)
    test = next((test for test in result['tests'] if test['id'] == test_id), None)
    if test is None:
        raise ValueError('Select a test from the saved recipe before editing it.')
    test['input_voltage_targets_V'] = target_values(values['voltages'], quantity='input voltage')
    test['output_current_targets_A'] = target_values(values['currents'], quantity='load current', allow_zero=True)
    result['settling']['minimum_dwell_s'] = float(values['minimum_dwell_s'])
    result['acquisition']['duration_s'] = float(values['duration_s'])
    result['planning']['efficiency_estimate_fraction'] = float(values['efficiency_estimate_pct']) / 100
    result['planning']['source_current_budget_fraction'] = float(values['current_budget_pct']) / 100
    return result


def quantity(value, unit: str, *, digits: int = 4) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return '—'
    return f'{value:.{digits}g} {unit}'


def plan_rows(preview: dict) -> list[dict]:
    labels = {'executable': 'Ready', 'assumption_limited': 'Outside planning budget',
              'approval_blocked': 'Needs approval', 'unsupported': 'Not supported'}
    return [{**point, 'input_display': quantity(point.get('vin_target_V'), 'V'),
             'load_display': quantity(point.get('iout_target_A'), 'A'),
             'estimated_display': quantity(point.get('estimated_input_current_A'), 'A'),
             'status_display': labels.get(point.get('status'), str(point.get('status', 'Unknown')).replace('_', ' '))}
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
    for filename, label, kind in (('report.html', 'Open interactive HTML', 'html'), ('report.pdf', 'Open PDF', 'pdf'),
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


def state_label(snapshot: dict) -> str:
    state = str(snapshot.get('state', 'unknown'))
    if snapshot.get('cancel_requested') and state in ('queued', 'acquiring', 'reporting'):
        return 'Stop requested — waiting for the worker'
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


def activity_text(snapshot: dict | None) -> str:
    """Short header phrase for work in progress; '' when the job needs no indicator."""
    if not snapshot:
        return ''
    state = str(snapshot.get('state', ''))
    if state not in ACTIVITY_STATES:
        return ''
    if snapshot.get('cancel_requested') or state in ('stopping', 'cancel_requested'):
        return 'Stopping… waiting for both outputs to be verified OFF'
    if state == 'queued':
        return 'Queued — waiting for the worker to start'
    if state == 'starting':
        return 'Starting — checking the bench'
    if state in ('running', 'acquiring'):
        progress = snapshot.get('progress') or {}
        total = progress.get('total') or 0
        if total:
            return f'Acquiring… point {min((progress.get("completed") or 0) + 1, total)} of {total}'
        return 'Acquiring… preparing the run'
    if state == 'report-queued':
        reason = snapshot.get('deferred_reason')
        return 'Report queued — waiting: ' + str(reason) if reason else 'Report queued — starts when the bench is idle'
    return 'Generating report…'


def saved_runs_key(snapshot: dict) -> tuple:
    """What the saved-runs list shows for a job: its state and the report links it offers.

    The Reports tab is refreshed when this changes between polls, so the list
    follows the job without a busy loop or a manual Refresh.
    """
    return (str(snapshot.get('state')), tuple(relative for _, relative in report_link_rows(snapshot)))


def report_became_ready(previous: tuple | None, current: tuple) -> bool:
    """A kept report appeared for a job the page had already seen without one."""
    return previous is not None and not previous[1] and bool(current[1])
