"""Small presentation helpers; no GUI, transport, worker or filesystem effects."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
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
    # Profile statements are not a run authorization. The backend binds the
    # fresh physical confirmation to its validated plan and inventory hashes.
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


def state_label(snapshot: dict) -> str:
    state = str(snapshot.get('state', 'unknown'))
    if snapshot.get('cancel_requested') and state in ('queued', 'acquiring', 'reporting'):
        return 'Stop requested — waiting for the worker'
    labels = {'queued': 'Waiting to start', 'running': 'Acquiring measurements', 'acquiring': 'Acquiring measurements',
              'starting': 'Checking the bench', 'rendering': 'Preparing HTML and PDF',
              'reporting': 'Preparing HTML and PDF',
              'analyzing': 'Analyzing saved measurements', 'completed': 'Complete',
              'cancel_requested': 'Stop requested — waiting for shutdown',
              'stopping': 'Stop requested — waiting for shutdown', 'cancelled': 'Stopped',
              'aborted': 'Acquisition stopped', 'failed': 'Needs attention',
              'report_failed': 'Measurements saved; report needs attention'}
    return labels.get(state, state.replace('_', ' ').capitalize())


def job_title(snapshot: dict) -> str:
    name = str(snapshot.get('dut_model') or 'Converter test')
    try:
        timestamp = datetime.fromisoformat(snapshot.get('created_utc', '')).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return name
    return name + ' · ' + timestamp.strftime('%d %b %Y, %H:%M UTC')


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
