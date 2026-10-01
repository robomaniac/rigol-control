"""Presentation boundaries without importing a GUI server or opening hardware."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from dcdc_bench.cli import main
from dcdc_bench.job_service import JobService
from dcdc_bench.standard_recipes import clause_rows
from dcdc_bench.ui import GLOSSARY_PATH, RequestBodyLimit, file_headers, published_file, require_loopback, run_ui, unique_name
from dcdc_bench.ui_models import (PLAN_STATUS_LEGEND, REAL_CAN, REAL_CANNOT, SIMULATION_CAN, SIMULATION_CANNOT,
                                  SIMULATION_SEQUENCE, SIMULATION_TIME_ESTIMATE, SYNTHETIC_UNCERTAINTY_NOTE, activity_text,
                                  artifact_url, bench_equipment, bench_job, bench_title, card_meta, deferred_text, dequeued,
                                  dut_approved, dut_subtitle, duration_text, edited_dut, edited_recipe, elapsed_text,
                                  envelope_rows, event_text, friendly_error, grouped_recipes, job_actions, job_title,
                                  limits_rows, limits_summary, local_time_text, number, plan_rows, point_count, quantity,
                                  recipe_category, recipe_grid, recipe_title, report_became_ready, report_link_rows,
                                  report_rows, run_option_text, saved_runs_key, sequence_step, shutdown_label, skip_reasons,
                                  state_label, summary_text, target_values, time_legend, time_lines)

LOS_ANGELES = ZoneInfo('America/Los_Angeles')
DOCS = Path(__file__).resolve().parents[1] / 'docs'
SRC = Path(__file__).resolve().parents[1] / 'src' / 'dcdc_bench'


@pytest.mark.parametrize('text', ['nan', 'inf', '-1', '0', '1,1', '1:5', '1+2', ''])
def test_grid_rejects_invalid_or_ambiguous_values(text):
    with pytest.raises(ValueError):
        target_values(text, quantity='input voltage')


def test_grid_preserves_requested_order_and_only_explicitly_allows_no_load():
    assert target_values('24; 12, 35.8', quantity='input voltage') == [24., 12., 35.8]
    assert target_values('0, .1, .25', quantity='load current', allow_zero=True) == [0., .1, .25]
    with pytest.raises(ValueError, match='1,000'):
        target_values(','.join(str(n + 1) for n in range(1001)), quantity='input voltage')


def test_recipe_edits_keep_other_tests_and_original_evidence_metadata():
    original = {'recipe_id': 'old', 'dut_profile_id': 'dut', 'execution_mode': 'mock',
                'tests': [{'id': 'first', 'input_voltage_targets_V': [12], 'output_current_targets_A': [.1]},
                          {'id': 'second', 'input_voltage_targets_V': [24], 'output_current_targets_A': [.2]}],
                'settling': {'minimum_dwell_s': 2, 'extra': 'preserved'},
                'acquisition': {'duration_s': 3}, 'planning': {}, 'notes': ['Keep provenance']}
    before = copy.deepcopy(original)
    result = edited_recipe(original, {'recipe_id': 'new', 'voltages': '24, 35.8', 'currents': '0.1, 0.5',
        'minimum_dwell_s': 3, 'duration_s': 4, 'efficiency_estimate_pct': 80, 'current_budget_pct': 95},
        dut_id='board-2', mode='real', test_id='first')
    assert original == before
    assert result['tests'][0]['input_voltage_targets_V'] == [24, 35.8]
    assert result['tests'][1] == before['tests'][1]
    assert result['notes'] == before['notes']
    assert result['settling']['extra'] == 'preserved'
    assert result['planning'] == {'efficiency_estimate_fraction': .8, 'source_current_budget_fraction': .95}
    assert result['dut_profile_id'] == 'board-2' and result['execution_mode'] == 'real'
    # The page passes no mode (the bench decides) and may supply the card text.
    modeless = edited_recipe(original, {'recipe_id': 'new', 'voltages': '24', 'currents': '0.1', 'minimum_dwell_s': 3,
        'duration_s': 4, 'efficiency_estimate_pct': 80, 'current_budget_pct': 95, 'title': ' 24 V check ', 'category': '',
        'standard_clause': 'MIL-STD-704F §5.1', 'description': None}, dut_id='dut', test_id='first')
    assert modeless['execution_mode'] is None and modeless['title'] == '24 V check'
    assert modeless['category'] is None and modeless['standard_clause'] == 'MIL-STD-704F §5.1' and modeless['description'] is None


def test_dut_edits_preserve_identity_metadata_and_do_not_authorize_a_run():
    original = {'profile_id': 'old', 'identity': {'model': 'old', 'owner_aliases': ['one']},
                'ratings': {'origin': 'user_supplied'}, 'approval': {'approved': False}}
    values = {'profile_id': 'new', 'model': '12T12-4A', 'sample_id': '', 'input_voltage_min_V': 9,
              'input_voltage_max_V': 36, 'output_voltage_nominal_V': 12,
              'output_current_rated_A': 4, 'output_power_rated_W': 48, 'verified_from_sample_label': True}
    result = edited_dut(original, values)
    assert original['profile_id'] == 'old'
    assert result['identity']['owner_aliases'] == ['one']
    assert result['identity']['sample_id'] is None
    assert result['approval'] == {'approved': False}
    assert result['ratings']['origin'] == 'user_supplied'


@pytest.mark.parametrize('job,relative', [('..', 'report/report.html'), ('x/y', 'report/report.html'),
    ('job1', '../secret'), ('job1', '/etc/passwd'), ('job1', r'report\secret'), ('job1', '')])
def test_artifact_links_reject_path_escapes(job, relative):
    with pytest.raises(ValueError):
        artifact_url(job, relative)


def test_artifact_links_use_service_route_and_encode_names():
    assert artifact_url('job-123', 'report/report.html') == '/jobs/job-123/files/report/report.html'
    assert artifact_url('job-123', 'run/raw/test data.csv').endswith('/run/raw/test%20data.csv')


def test_published_aliases_resolve_only_inside_their_startup_allowlist(tmp_path):
    target = tmp_path / 'evidence' / 'reports' / 'r0004'
    target.mkdir(parents=True)
    report = target / 'report.html'
    report.write_text('Published report')
    published = tmp_path / 'Data' / 'Runs'
    published.mkdir(parents=True)
    (published / 'converter').symlink_to(target, target_is_directory=True)
    archive = published / 'converter-download.zip'
    archive.write_bytes(b'Published archive')
    roots = {entry.name: entry.resolve() for entry in published.iterdir() if entry.is_dir() or entry.is_file()}
    assert published_file(roots, 'converter/report.html') == report
    assert published_file(roots, 'converter-download.zip') == archive
    secret = tmp_path / 'private.yaml'
    secret.write_text('not published')
    (target / 'escape.yaml').symlink_to(secret)
    for relative in ('converter/../../private.yaml', 'unknown/report.html', 'converter/escape.yaml', 'converter/'):
        with pytest.raises(ValueError):
            published_file(roots, relative)


@pytest.mark.parametrize('host', ['0.0.0.0', '192.0.2.10', 'example.com', 'localhost.attacker.invalid'])
def test_control_ui_rejects_network_interfaces_before_loading_server(host, tmp_path):
    with pytest.raises(ValueError, match='loopback'):
        run_ui(tmp_path, host=host)
    assert list(tmp_path.iterdir()) == []


def test_loopback_and_invalid_port_boundaries(tmp_path):
    assert require_loopback('localhost') == '127.0.0.1'
    assert require_loopback('127.0.0.1') == '127.0.0.1'
    assert require_loopback('::1') == '::1'
    with pytest.raises(ValueError, match='port'):
        run_ui(tmp_path, port=65536)


def test_status_does_not_claim_outputs_off_without_both_verified():
    assert 'not been verified' in shutdown_label({})
    snapshot = {'shutdown': {'source': {'state': 'OFF', 'verified': True}, 'load': {'state': 'OFF', 'verified': False}}}
    assert 'not fully verified' in shutdown_label(snapshot)
    snapshot['shutdown']['load']['verified'] = True
    assert shutdown_label(snapshot) == 'Supply output and electronic load are verified OFF.'
    snapshot['mode'] = 'real'
    assert 'not fully verified' in shutdown_label(snapshot)
    snapshot['shutdown']['source_deadline'] = {'state': 'OFF', 'verified': False}
    assert 'not fully verified' in shutdown_label(snapshot)
    snapshot['shutdown']['source_deadline']['verified'] = True
    assert shutdown_label(snapshot) == 'Supply output and electronic load are verified OFF.'
    assert state_label({'state': 'reporting'}) == 'Preparing HTML and PDF'
    assert state_label({'state': 'cancelled'}) == 'Stopped'
    assert state_label({'state': 'acquiring', 'cancel_requested': True}) == 'Stop requested — waiting for the worker'
    # m7: a job the operator dequeued did not fail; it says so (new records carry the flag, old ones only the error text).
    assert state_label({'state': 'cancelled', 'dequeued': True}) == 'Removed from the report queue'
    assert state_label({'state': 'cancelled', 'error': 'Report generation was removed from the queue; saved measurements are preserved'}) == 'Removed from the report queue'
    assert dequeued({'state': 'cancelled', 'dequeued': True}) and not dequeued({'state': 'cancelled', 'error': 'Operator cancelled the simulation'})


def test_plan_presentation_retains_exclusions_and_missing_measurements():
    row = plan_rows({'points': [{'point_id': 'p1', 'vin_target_V': 24., 'iout_target_A': .5,
        'estimated_input_current_A': None, 'status': 'assumption_limited', 'reason': 'Above input budget'}]})[0]
    assert row['status_display'] == 'assumption_limited', "the planner's own word, as the CLI and the saved plan print it"
    assert [status for status, _ in PLAN_STATUS_LEGEND] == ['executable', 'assumption_limited', 'approval_blocked', 'unsupported']
    assert row['estimated_display'] == '—'
    assert row['reason'] == 'Above input budget'
    assert quantity(float('nan'), 'A') == '—'
    assert quantity(True, 'A') == '—'
    assert job_title({'dut_model': '12T12-4A', 'created_utc': '2026-09-27T18:30:00+00:00'}, zone=LOS_ANGELES) == '12T12-4A · 11:30:00 PDT (2026-09-27)'
    assert job_title({}) == 'Converter test'
    assert job_title({'created_utc': 'not a time'}) == 'Converter test'


def test_cli_ui_forwards_paths_and_options_without_starting_server(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr('dcdc_bench.ui.run_ui', lambda *args, **kwargs: captured.append((args, kwargs)))
    workspace, inventory = tmp_path / 'workspace', tmp_path / 'lab.yaml'
    assert main(['ui', '--root', str(workspace), '--inventory', str(inventory), '--port', '8182']) == 0
    assert captured == [((workspace.resolve(), inventory.resolve()), {'host': '127.0.0.1', 'port': 8182, 'report_root': None})]
    assert not workspace.exists()


def test_kept_report_artifacts_stay_linked_and_named_by_status():
    """M5: an unverified or failed-validation PDF is kept on disk and stays reachable, with its status in the label."""
    snapshot = {'job_id': 'job-1', 'report_dir': '/w/jobs/job-1/runs/r/reports/r0001',
                'report_artifacts': {'html': {'status': 'success'}, 'pdf': {'status': 'unverified'}, 'model': {'status': 'success'}}}
    rows = report_link_rows(snapshot)
    assert [relative for _, relative in rows] == ['report/report.html', 'report/report.pdf', 'report/report_model.json']
    assert rows[1][0] == 'Open PDF (not verified: checker tool missing)' and rows[0][0] == 'Open HTML'
    snapshot['report_artifacts']['pdf'] = {'status': 'failed-validation', 'error': 'p1: orphan-heading'}
    assert report_link_rows(snapshot)[1][0] == 'Open PDF (failed the layout check; kept for inspection)'
    for status in ('failed', 'missing', 'unavailable'):
        snapshot['report_artifacts']['pdf'] = {'status': status}
        assert [relative for _, relative in report_link_rows(snapshot)] == ['report/report.html', 'report/report_model.json']
    assert report_link_rows({'job_id': 'job-1', 'report_artifacts': {'html': {'status': 'success'}}}) == []


def test_run_panel_offers_stop_for_live_workers_and_dequeue_for_queued_reports():
    """m1: a report-queued job can be removed from the queue; live workers get Stop."""
    for state in ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested'):
        assert job_actions({'state': state}) == ['stop']
    assert job_actions({'state': 'report-queued'}) == ['dequeue']
    for state in ('completed', 'aborted', 'failed', 'cancelled', 'reporting'):
        assert job_actions({'state': state}) == []


def test_file_headers_confine_documents_and_download_uploaded_documents():
    html = file_headers(Path('report.html'), 'report/report.html')
    assert html['Content-Security-Policy'] == 'sandbox allow-scripts allow-downloads allow-popups'
    assert 'Content-Disposition' not in html
    name = 'a' * 64
    svg = file_headers(Path(f'/w/run/attachments/originals/{name}.svg'), f'run/attachments/originals/{name}.svg')
    assert svg['Content-Security-Policy'] == 'sandbox' and svg['Content-Disposition'] == f'attachment; filename="{name}.svg"'
    pdf = file_headers(Path(f'{name}.pdf'), f'run/attachments/originals/{name}.pdf')
    assert pdf['Content-Security-Policy'] == 'sandbox' and pdf['Content-Disposition'].startswith('attachment;')
    raster = file_headers(Path(f'{name}.jpg'), f'run/attachments/originals/{name}.jpg')
    assert raster['Content-Disposition'] == f'inline; filename="{name}.jpg"' and raster['Content-Security-Policy'] == 'sandbox'
    figure = file_headers(Path('fig-efficiency.svg'), 'report/figures/fig-efficiency.svg')
    assert figure['Content-Security-Policy'] == 'sandbox' and 'Content-Disposition' not in figure
    legacy = file_headers(Path('efficiency.csv'))
    assert legacy['Content-Security-Policy'] == 'sandbox' and 'Content-Disposition' not in legacy
    for headers in (html, svg, pdf, raster, figure, legacy):
        assert headers['X-Content-Type-Options'] == 'nosniff' and headers['Cache-Control'] == 'no-store'


def test_request_body_limit_refuses_declared_and_streamed_oversize_bodies():
    import asyncio
    seen, sent = [], []

    async def inner(scope, receive, send):
        seen.append(scope['path'])
        if scope['type'] != 'http':
            return
        total = 0
        while True:
            message = await receive()
            if message['type'] != 'http.request':
                seen.append(message['type'])
                return
            total += len(message.get('body', b''))
            if not message.get('more_body'):
                seen.append(total)
                return

    async def send(message):
        sent.append(message)

    async def never():
        pytest.fail('an oversized declared body must not be read')
    guard = RequestBodyLimit(inner, limit=1000)
    asyncio.run(guard({'type': 'http', 'path': '/_nicegui/client/x/upload/1', 'headers': [(b'content-length', b'5000')]}, never, send))
    assert seen == [] and sent[0]['status'] == 413
    chunks = [{'type': 'http.request', 'body': b'x' * 600, 'more_body': True} for _ in range(5)]

    async def receive():
        return chunks.pop(0)
    asyncio.run(guard({'type': 'http', 'path': '/upload', 'headers': []}, receive, send))
    assert seen == ['/upload', 'http.disconnect'] and len(chunks) == 3, 'cut off at the first chunk past the limit'
    seen.clear()
    chunks[:] = [{'type': 'http.request', 'body': b'ok', 'more_body': False}]
    asyncio.run(guard({'type': 'http', 'path': '/small', 'headers': [(b'content-length', b'2')]}, receive, send))
    assert seen == ['/small', 2]
    seen.clear()
    asyncio.run(guard({'type': 'websocket', 'path': '/socket.io'}, never, send))
    assert seen == ['/socket.io'], 'non-HTTP scopes pass straight through'


def test_annotation_editor_is_not_shadowed_by_the_published_file_catch_all(tmp_path, monkeypatch):
    """The real route table with --report-root set, without starting a server."""
    from nicegui import app, ui
    from starlette.routing import Match
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'timer', lambda *args, **kwargs: None)
    monkeypatch.setenv('DCDC_ACTIVITY_LOCK', str(tmp_path / 'activity.lock'))
    monkeypatch.setenv('DCDC_JOB_LAUNCHER', 'detached')
    reports = tmp_path / 'Data'
    (reports / 'Runs').mkdir(parents=True)
    (reports / 'legacy-report.html').write_text('published')
    run_ui(tmp_path / 'workspace', report_root=reports)

    def first_match(path):
        scope = {'type': 'http', 'method': 'GET', 'path': path, 'root_path': '', 'headers': []}
        return next((route for route in app.routes if route.matches(scope)[0] == Match.FULL), None)
    assert first_match('/annotations').path == '/annotations'
    assert first_match('/glossary').path == '/glossary', 'the footer link is not swallowed by the published-file catch-all'
    assert first_match('/').path == '/'
    assert first_match('/legacy-report.html').path == '/{filename}'
    assert first_match('/Runs/converter/report.html').path == '/Runs/{relative:path}'
    assert first_match('/jobs/j/files/report/report.html').path == '/jobs/{job_id}/files/{relative:path}'


# --- Operator-facing local time ----------------------------------------------

def test_local_time_text_shows_the_bench_computer_zone_and_never_invents_a_time():
    """Display only: evidence stays UTC. ``zone`` pins the tests to America/Los_Angeles; the page passes none."""
    assert local_time_text('2026-09-29T20:40:12+00:00', zone=LOS_ANGELES) == '13:40:12 PDT (2026-09-29)'
    assert local_time_text('2026-09-29T20:40:12', zone=LOS_ANGELES) == '13:40:12 PDT (2026-09-29)', 'naive strings are UTC'
    assert local_time_text('2026-01-15T20:40:12Z', zone=LOS_ANGELES) == '12:40:12 PST (2026-01-15)', 'standard time in winter'
    assert local_time_text('2026-09-29T22:40:12+02:00', zone=LOS_ANGELES) == '13:40:12 PDT (2026-09-29)', 'other offsets convert too'
    for garbage in (None, '', '   ', 'yesterday', 42, {'utc': '2026-09-29T20:40:12+00:00'}):
        assert local_time_text(garbage) == 'unknown'
    # Without ``zone`` the system zone is used through astimezone(); nothing is hard-coded.
    expected = datetime(2026, 9, 29, 20, 40, 12, tzinfo=timezone.utc).astimezone()
    assert local_time_text('2026-09-29T20:40:12+00:00') == expected.strftime('%H:%M:%S %Z (%Y-%m-%d)')
    assert time_legend(LOS_ANGELES).startswith('Times shown in bench-computer local time (P')
    assert time_legend(LOS_ANGELES).endswith('; evidence files record UTC.')


def test_elapsed_and_event_text_are_local_and_tolerant():
    now = datetime(2026, 9, 29, 20, 43, 24, tzinfo=timezone.utc)
    assert elapsed_text('2026-09-29T20:40:12+00:00', now) == '3:12'
    assert elapsed_text('2026-09-29T18:40:12+00:00', now) == '2:03:12'
    assert elapsed_text('2026-09-29T20:50:00+00:00', now) == '0:00', 'a start in the future (clock skew) never shows negative'
    assert elapsed_text(None, now) == '' and elapsed_text('garbage', now) == ''
    event = {'event': 'point_phase', 'timestamp_utc': '2026-09-29T20:40:12+00:00', 'run_id': 'r1', 'monotonic_s': 1.5,
             'point_id': 'p3', 'phase': 'settling'}
    assert event_text(event, zone=LOS_ANGELES) == '13:40:12 PDT (2026-09-29) · point_phase point_id=p3 phase=settling'
    assert event_text({'event': 'start'}, zone=LOS_ANGELES) == 'unknown · start'
    assert event_text('legacy string event') == 'legacy string event'


# --- Header activity indicator and Reports freshness (pure parts) -------------

def test_activity_phrase_covers_every_background_state_and_is_empty_when_idle():
    assert activity_text({'state': 'queued'}) == 'Queued — waiting for the worker to start'
    assert activity_text({'state': 'acquiring', 'progress': {'completed': 1, 'total': 4}}) == 'Acquiring… point 2 of 4'
    assert activity_text({'state': 'acquiring', 'progress': {'completed': 4, 'total': 4}}) == 'Acquiring… point 4 of 4'
    assert activity_text({'state': 'acquiring'}) == 'Acquiring… preparing the run'
    assert activity_text({'state': 'acquiring', 'cancel_requested': True}).startswith('Stopping…')
    assert activity_text({'state': 'reporting'}) == 'Generating report…'
    assert activity_text({'state': 'rendering'}) == 'Generating report…'
    assert activity_text({'state': 'report-queued', 'deferred_reason': 'MemAvailable below 150 MiB',
                          'deferred_memory': {'available_mib': 96.4}}) == 'Report queued — waiting for free memory: 96 MiB available, 150 MiB needed'
    assert activity_text({'state': 'report-queued'}) == 'Report queued — starts when the bench is idle'
    # C34: the mode word leads every phrase, so a passer-by can tell from the header alone.
    assert activity_text({'state': 'acquiring', 'mode': 'mock', 'progress': {'completed': 1, 'total': 21}}) == 'Simulation: Acquiring… point 2 of 21'
    assert activity_text({'state': 'reporting', 'mode': 'real'}) == 'Real bench: Generating report…'
    for idle in ({'state': 'completed'}, {'state': 'failed'}, {'state': 'cancelled'}, {'state': 'aborted'}, {}, None):
        assert activity_text(idle) == ''


def test_deferred_reason_is_rendered_in_operator_language():
    """C37 / QA m4: the dispatcher's /proc field names become sentences; the numbers come from the recorded snapshot."""
    assert deferred_text({'deferred_reason': 'MemAvailable below 150 MiB', 'deferred_memory': {'available_mib': 96.2}}) == \
        'Waiting for free memory: 96 MiB available, 150 MiB needed'
    assert deferred_text({'deferred_reason': 'MemAvailable below 150 MiB'}) == 'Waiting for free memory: less than that available, 150 MiB needed'
    assert deferred_text({'deferred_reason': 'MemAvailable below 150 MiB; MemAvailable+SwapFree below 600 MiB',
                          'deferred_memory': {'available_mib': 96., 'available_plus_swap_free_mib': 410.}}) == \
        'Waiting for free memory: 96 MiB available, 150 MiB needed; Waiting for free memory and swap: 410 MiB free memory and swap together, 600 MiB needed'
    assert deferred_text({'deferred_reason': 'bench lease held: Bench is busy acquiring or rendering; retry explicitly after it finishes'}) == \
        'Waiting for the bench: another acquisition or report is still running'
    assert deferred_text({'deferred_reason': 'memory gate misconfigured: DCDC_RENDER_MIN_AVAILABLE_MIB must be a number'}).startswith(
        'Waiting: the memory gate is misconfigured — DCDC_RENDER')
    assert deferred_text({'deferred_reason': None}) == '' and deferred_text(None) == ''
    assert 'MemAvailable' not in deferred_text({'deferred_reason': 'MemAvailable below 150 MiB'})


def test_editor_numbers_and_validation_errors_use_operator_language():
    """QA m6: a cleared number says 'Enter a number', a limit names the field the operator sees, never a Python TypeError."""
    with pytest.raises(ValueError, match='Enter a number for “Minimum settling time \\(s\\)”'):
        number({'minimum_dwell_s': None}, 'minimum_dwell_s', 'Minimum settling time (s)')
    with pytest.raises(ValueError, match='“Planning efficiency estimate \\(%\\)” must be greater than 0'):
        number({'e': 0}, 'e', 'Planning efficiency estimate (%)', minimum=0, maximum=100, exclusive_minimum=True)
    with pytest.raises(ValueError, match='must be at most 100'):
        number({'e': 120}, 'e', 'Planning efficiency estimate (%)', minimum=0, maximum=100, exclusive_minimum=True)
    assert number({'e': '12.5'}, 'e', 'x') == 12.5
    recipe = {'recipe_id': 'r', 'dut_profile_id': 'd', 'tests': [{'id': 't', 'input_voltage_targets_V': [24], 'output_current_targets_A': [.1]}],
              'settling': {'minimum_dwell_s': 5, 'timeout_s': 30}, 'acquisition': {'duration_s': 5}, 'planning': {}}
    form = {'recipe_id': 'r', 'voltages': '24', 'currents': '0.1', 'minimum_dwell_s': 40, 'duration_s': 5,
            'efficiency_estimate_pct': 80, 'current_budget_pct': 90}
    with pytest.raises(ValueError, match='“Minimum settling time \\(s\\)” must be at most 30 s, this test’s settling timeout'):
        edited_recipe(recipe, form, dut_id='d', test_id='t')
    with pytest.raises(ValueError, match='Enter a number for “Measure each load for \\(s\\)”'):
        edited_recipe(recipe, {**form, 'minimum_dwell_s': 5, 'duration_s': None}, dut_id='d', test_id='t')
    with pytest.raises(ValueError, match='Enter a file name under “Save test as”'):
        edited_recipe(recipe, {**form, 'recipe_id': '  ', 'minimum_dwell_s': 5}, dut_id='d', test_id='t')
    dut = {'profile_id': 'x', 'identity': {'model': 'M'}, 'ratings': {'origin': 'user_supplied'}}
    values = {'profile_id': 'x', 'model': 'M', 'input_voltage_min_V': 9, 'input_voltage_max_V': 36, 'output_voltage_nominal_V': 12,
              'output_current_rated_A': 4, 'output_power_rated_W': 48}
    with pytest.raises(ValueError, match='Enter a number for “Maximum input \\(V\\)”'):
        edited_dut(dut, {**values, 'input_voltage_max_V': None})
    with pytest.raises(ValueError, match='“Minimum input \\(V\\)” must not exceed “Maximum input \\(V\\)”'):
        edited_dut(dut, {**values, 'input_voltage_min_V': 40})
    with pytest.raises(ValueError, match='“Rated output power \\(W\\)” must be greater than 0'):
        edited_dut(dut, {**values, 'output_power_rated_W': 0})
    # pydantic errors are translated to the visible label; unknown paths keep their path.
    from dcdc_bench.domain import DutProfile
    try:
        DutProfile.model_validate({**edited_dut(dut, values), 'ratings': {**edited_dut(dut, values)['ratings'], 'input_voltage_min_V': -1}})
    except ValueError as exc:
        text = friendly_error(exc)
        assert text.startswith('“Minimum input (V)”: ') and 'Value error, ' not in text
    assert friendly_error(ValueError('plain text')) == 'plain text'


def test_saved_runs_key_changes_only_when_the_list_would_and_report_ready_fires_once():
    acquiring = {'job_id': 'j', 'state': 'acquiring', 'progress': {'completed': 1, 'total': 4}, 'latest': {'Vin_V': 24.}}
    later = {**acquiring, 'progress': {'completed': 3, 'total': 4}, 'latest': {'Vin_V': 24.1}}
    assert saved_runs_key(acquiring) == saved_runs_key(later), 'live readings alone do not refresh the list'
    done = {'job_id': 'j', 'state': 'completed', 'report_dir': '/w/reports/r0001',
            'report_artifacts': {'html': {'status': 'success'}, 'pdf': {'status': 'unverified'}, 'model': {'status': 'success'}}}
    assert saved_runs_key(done) == ('completed', ('report/report.html', 'report/report.pdf', 'report/report_model.json'))
    assert report_became_ready(saved_runs_key(acquiring), saved_runs_key(done))
    assert not report_became_ready(None, saved_runs_key(done)), 'a report first seen at page load is not news'
    assert not report_became_ready(saved_runs_key(done), saved_runs_key(done)), 'no repeat on the next tick'
    assert not report_became_ready(saved_runs_key(acquiring), saved_runs_key({'job_id': 'j', 'state': 'failed'}))


# --- One-page bench: card text, bench tiles, plan panel, reports rows (pure parts) ---

def test_card_text_derives_from_the_grid_and_saved_plain_names():
    quick = {'title': None, 'tests': [{'input_voltage_targets_V': [12., 24., 30.],
                                        'output_current_targets_A': [0., .05, .1, .25, .5, .75, 1.]}]}
    assert recipe_grid(quick) == '12 / 24 / 30 V × 0–1 A'
    assert recipe_title(quick) == '12 / 24 / 30 V × 0–1 A', 'a test without a saved name is titled from its grid'
    assert point_count(quick) == 21
    assert recipe_grid({'tests': [{'input_voltage_targets_V': [24.], 'output_current_targets_A': [0., .1]}]}) == '24 V × 0 / 0.1 A'
    assert recipe_grid({'tests': [{'input_voltage_targets_V': [12.], 'output_current_targets_A': [0., .1, .25, .5]}]}) == '12 V × 0 / 0.1 / 0.25 / 0.5 A'
    assert recipe_grid({'tests': [{'input_voltage_targets_V': [15., 18., 24., 30., 35.8],
                                   'output_current_targets_A': [.1, .25, .5, .75, 1.]}]}) == '15…35.8 V × 0.1–1 A'
    assert recipe_title({'title': ' 24 V small grid ', 'tests': []}) == '24 V small grid'
    assert recipe_category({}) == 'Normal operating voltage' and recipe_category({'category': 'Bench checks'}) == 'Bench checks'
    assert card_meta(2, 'real', 62) == '2 points · ~62 s' and card_meta(2, 'real', 95) == '2 points · ~2 min'
    assert card_meta(21, 'mock', None) == '21 points · simulated', 'the simulated bench runs on a virtual clock: no invented time'
    assert card_meta(1, 'real', None) == '1 point'
    assert duration_text(45) == '~45 s' and duration_text(89.6) == '~90 s' and duration_text(150) == '~2 min'
    assert duration_text(None) == '' and duration_text(float('nan')) == '' and duration_text(-1) == ''
    grouped = grouped_recipes({'b': {'category': 'MIL-STD-704F', 'title': 'Z'}, 'a': {'title': 'Quick'},
                               'c': {'category': 'Bench checks', 'title': 'Wire'}, 'd': {'title': 'Alpha'}})
    assert [(category, [name for name, _ in items]) for category, items in grouped] == \
        [('Normal operating voltage', ['d', 'a']), ('Bench checks', ['c']), ('MIL-STD-704F', ['b'])]
    assert unique_name('quick', {'quick', 'quick-copy'}) == 'quick-copy-2' and unique_name('quick', {}) == 'quick-copy'


def test_converter_and_bench_text_never_invent_limits_or_names():
    dut = {'identity': {'model': '12T12-4A', 'sample_id': 'S1'},
           'ratings': {'input_voltage_min_V': 9., 'input_voltage_max_V': 36., 'output_voltage_nominal_V': 12., 'output_current_rated_A': 4.},
           'execution_approval': {'real_hardware_enabled': True, 'wiring_and_polarity_confirmed': False}}
    assert dut_subtitle(dut) == '9–36 V in, 12 V / 4 A out · sample S1'
    assert not dut_approved(dut) and dut_approved({**dut, 'execution_approval': {'real_hardware_enabled': True, 'wiring_and_polarity_confirmed': True}})
    bench = {'bench_id': 'rigol-local-limited', 'title': None, 'source': {'channel': 1}, 'load': {},
             'protective_controls': {'source_current_limit_A': 1., 'dut_input_overvoltage_V': 26., 'dut_output_overvoltage_V': 13.2,
                                     'output_overcurrent_A': None}}
    assert bench_title(bench) == 'rigol-local-limited', 'a plain name is not derivable; the identifier is the fallback'
    assert bench_title({**bench, 'title': '24 V converter tests'}) == '24 V converter tests'
    assert limits_rows(bench) == [('Supply current limit', '1 A'), ('Input over-voltage', '26 V'),
                                  ('Output voltage guard', '13.2 V'), ('Output current guard', '—')]
    assert limits_summary(bench) == '1 A supply · 26 V input · 13.2 V / — output'
    assert bench_equipment(bench) == 'supply CH1 + load'
    assert bench_equipment(bench, {'source': {'model': 'DP821A'}, 'load': {'model': 'DL3031A'}}) == 'DP821A CH1 + DL3031A'
    assert bench_equipment({**bench, 'source': {'channel': 1, 'physical_model': 'DP821A'}}, {'load': {'model': 'DL3031A'}}) == 'DP821A CH1 + DL3031A'
    assert summary_text(dut, 'real', {**bench, 'title': '24 V converter tests'}, {'title': '24 V small grid'}) == \
        '12T12-4A · Real bench (24 V converter tests) · 24 V small grid'
    assert summary_text(None, 'mock', None, None) == '— no converter — · Simulation · — no test —'
    mock = {'source': {'min_voltage_V': 0., 'max_voltage_V': 60., 'max_current_A': 1., 'max_power_W': 60.}, 'load': {'max_current_A': 40.}}
    assert envelope_rows(mock) == [('Synthetic source', '0–60 V · 1 A · 60 W'), ('Synthetic load', 'constant current, up to 40 A'),
                                   ('Protective limits', 'none — only the planning budget bounds the plan'),
                                   ('Readback uncertainty', 'synthetic example specification, not an instrument')]
    assert envelope_rows({**mock, 'protective_controls': {'source_current_limit_A': .5}})[2] == ('Protective limits', 'Supply current limit 0.5 A')
    assert envelope_rows({})[0] == ('Synthetic source', '— · — · —'), 'never an invented envelope'


def test_plan_panel_groups_skip_reasons_and_report_rows_use_local_time():
    preview = {'points': [{'status': 'executable', 'reason': 'ok'}, {'status': 'unsupported', 'reason': 'Above guard'},
                          {'status': 'unsupported', 'reason': 'Above guard'}, {'status': 'assumption_limited', 'reason': 'Budget'}]}
    assert skip_reasons(preview) == [(2, 'unsupported', 'Above guard'), (1, 'assumption_limited', 'Budget')], 'the planner word travels with the reason'
    job = {'job_id': 'j1', 'state': 'completed', 'mode': 'real', 'dut_model': '12T12-4A', 'recipe_id': 'real-24v-small-grid',
           'recipe_title': 'old name', 'created_utc': '2026-09-29T20:37:14+00:00', 'run_dir': '/w/r',
           'progress': {'completed': 3, 'total': 3}, 'report_dir': '/w/r/reports/r0001',
           'report_artifacts': {'html': {'status': 'success'}, 'pdf': {'status': 'success'}, 'model': {'status': 'success'}}}
    [row] = report_rows([job], zone=LOS_ANGELES, recipes={'real-24v-small-grid': {'title': '24 V small grid', 'tests': []}})
    assert row['when'] == '13:37:14 PDT (2026-09-29)' and row['run'] == '12T12-4A · 24 V small grid'
    assert row['bench'] == 'Real bench · measured' and row['real'] and row['waiting'] == ''
    assert row['status'] == 'Complete' and row['points'] == '3 / 3 points' and row['regenerate'] and not row['dequeue']
    assert row['links'] == [('Open HTML', 'report/report.html'), ('Open PDF', 'report/report.pdf')], 'the JSON model stays on the run panel'
    [fallback] = report_rows([{**job, 'recipe_id': 'deleted'}], zone=LOS_ANGELES)
    assert fallback['run'] == '12T12-4A · old name', 'a deleted test keeps the name recorded at Start'
    [legacy] = report_rows([{'job_id': 'j0', 'state': 'acquiring', 'mode': 'mock', 'dut_model': '12T12-4A'}], zone=LOS_ANGELES)
    assert legacy['run'] == '12T12-4A' and legacy['when'] == 'unknown' and legacy['bench'] == 'Simulation · synthetic data' and not legacy['real']
    assert not legacy['regenerate'] and legacy['status'] == 'Acquiring measurements'
    [queued] = report_rows([{'job_id': 'j2', 'state': 'report-queued', 'mode': 'mock', 'dut_model': 'X', 'run_dir': '/w/r',
                             'deferred_reason': 'MemAvailable below 150 MiB', 'deferred_memory': {'available_mib': 96.}}], zone=LOS_ANGELES)
    assert queued['dequeue'] and not queued['regenerate']
    assert queued['waiting'] == 'Waiting for free memory: 96 MiB available, 150 MiB needed', 'QA m4: the row shows the deferral'
    assert run_option_text({**job, 'created_utc': None}) == '12T12-4A · Real bench · measured · Complete'
    assert run_option_text(legacy | {'created_utc': None, 'dut_model': '12T12-4A', 'state': 'completed', 'mode': 'mock'}) == \
        '12T12-4A · Simulation · synthetic data · Complete'


def test_bench_job_prefers_a_working_job_then_the_oldest_queued_report():
    """QA M1: what a tab attaches to when it has no job of its own."""
    working = {'job_id': 'j3', 'state': 'acquiring'}
    older = {'job_id': 'j1', 'state': 'report-queued', 'queued_utc': '2026-09-30T10:00:00+00:00'}
    newer = {'job_id': 'j2', 'state': 'report-queued', 'queued_utc': '2026-09-30T11:00:00+00:00'}
    done = {'job_id': 'j0', 'state': 'completed'}
    assert bench_job([working, newer, older, done]) is working
    assert bench_job([newer, older, done]) is older, 'the dispatcher renders the oldest queued report first'
    assert bench_job([done]) is None and bench_job([]) is None
    assert sequence_step({'mode': 'mock', 'state': 'acquiring'}) == 0
    assert sequence_step({'mode': 'mock', 'state': 'report-queued'}) == 1
    assert sequence_step({'mode': 'mock', 'state': 'queued', 'action': 'report-only'}) == 2
    assert sequence_step({'mode': 'mock', 'state': 'reporting'}) == 2 and sequence_step({'mode': 'mock', 'state': 'completed'}) == 3
    assert sequence_step({'mode': 'real', 'state': 'acquiring'}) is None and sequence_step({'mode': 'mock', 'state': 'failed'}) is None
    assert [label for label, _ in SIMULATION_SEQUENCE] == ['Acquiring measurements', 'Measurements saved — report queued',
                                                            'Preparing HTML and PDF', 'Complete']


# --- The rendered page, driven through its own handlers and poll --------------

def snapshot(job_id, state, **extra):
    """A JobService.status()-shaped record; the fake below returns copies of these."""
    base = {'job_id': job_id, 'state': state, 'mode': 'mock', 'dut_model': '12T12-4A', 'pid': None,
            'created_utc': '2026-09-29T20:40:12+00:00', 'error': None, 'run_dir': None, 'report_dir': None,
            'progress': {'completed': 1, 'total': 4, 'current': 'p2'}, 'latest': {}, 'shutdown': {},
            'report_artifacts': {}, 'elapsed_s': 12., 'latest_age_s': 1., 'latest_kind': 'unqualified live readings',
            'deferred_reason': None, 'deferred_memory': None, 'dequeued': False, 'report_pending': False,
            'cancel_requested': False, 'events': []}
    return {**base, **extra}


REPORT_DONE = {'state': 'completed', 'run_id': 'r-0001', 'run_dir': '/w/jobs/job-1/runs/r-0001',
               'report_dir': '/w/jobs/job-1/runs/r-0001/reports/r0001',
               'report_artifacts': {'html': {'status': 'success'}, 'pdf': {'status': 'success'}, 'model': {'status': 'success'}},
               'shutdown': {role: {'state': 'OFF', 'verified': True} for role in ('source', 'load')}}

QUICK, SMALL_GRID = '12t12-4a-quick', 'real-24v-small-grid'  # the two seeded tests
QUICK_TITLE, SMALL_GRID_TITLE = 'Quick sweep — 12 / 24 / 30 V × 0–1 A', '24 V small grid — 0.1 / 0.25 / 0.5 A'


async def open_bench_page(monkeypatch, tmp_path, snapshots):
    """Render the real '/' page against a fake JobService without a server, socket or browser.

    Returns the NiceGUI client (its element tree is the page), the poll callback the page
    registered with ``ui.timer`` (a test calls it to simulate a tick), the notifications the
    page issued, the fake service (real seeded profiles on disk; job status from the test's
    dictionaries) and the exceptions NiceGUI's handler dispatch swallowed (must stay empty).
    """
    from nicegui import app, core, run, ui
    from nicegui.client import Client
    from nicegui.page import page
    created, timers, notices, errors = [], [], [], []

    class FakeService(JobService):
        """Real seeded mock profiles; job status comes from the test's dictionaries (plus any job a test really starts)."""

        def __init__(self, root, inventory_path=None, gate=None):
            super().__init__(root, inventory_path=inventory_path)
            self.list_jobs_calls = 0
            self.cancelled = []
            self.retried = []
            created.append(self)

        def status(self, job_id):
            if job_id in snapshots:
                return copy.deepcopy(snapshots[job_id])
            return super().status(job_id)

        def _all_jobs(self):
            return [self.status(job_id) for job_id in sorted(snapshots, reverse=True)] + super().list_jobs()

        def list_jobs(self):
            self.list_jobs_calls += 1
            return self._all_jobs()

        def active_job(self):
            # The cheap per-tick probe, from the same dictionaries; never counted as a list_jobs call.
            job = bench_job(self._all_jobs())
            return {'job_id': job['job_id'], 'state': job['state'], 'mode': job.get('mode')} if job else None

        def dispatch_reports(self):
            return None

        def cancel(self, job_id):
            self.cancelled.append(job_id)
            snapshots[job_id]['cancel_requested'] = True
            return self.status(job_id)

        def retry_report(self, job_id, annotations=None):
            self.retried.append(job_id)
            snapshots[job_id].update(state='report-queued', report_dir=None, report_artifacts={})
            return {'job_id': job_id, 'state': 'report-queued'}

    async def inline(callback, *args, **kwargs):
        return callback(*args, **kwargs)
    kinds = []
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'timer', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'handle_exception', lambda exc: errors.append(exc))
    monkeypatch.setattr(ui, 'timer', lambda interval, callback, **kwargs: timers.append(callback))
    monkeypatch.setattr(ui, 'notify', lambda message, **kwargs: (notices.append(str(message)), kinds.append(kwargs.get('type'))))
    monkeypatch.setattr(run, 'io_bound', inline)
    # Async click/change handlers become background tasks on the NiceGUI loop; point it at ours.
    monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
    monkeypatch.setattr('dcdc_bench.job_service.JobService', FakeService)
    monkeypatch.setenv('DCDC_ACTIVITY_LOCK', str(tmp_path / 'activity.lock'))
    monkeypatch.setenv('DCDC_JOB_LAUNCHER', 'detached')
    run_ui(tmp_path / 'workspace')
    bench_page = [func for func, path in Client.page_routes.items() if path == '/'][-1]
    client = Client(page('/'))
    client.tab_id = 'test-tab'  # counts as connected, so ``await client.connected()`` returns at once
    with client:
        await bench_page()
    # No browser is attached: the client's outbox loop would try to deliver updates with
    # run-time settings that only ``ui.run`` (stubbed above) configures. The element tree
    # is what the tests read, so the delivery loop is stopped.
    client.outbox.stop()
    return SimpleNamespace(client=client, poll=timers[-1], notices=notices, notice_kinds=kinds, service=created[-1], errors=errors)


async def open_page(monkeypatch, tmp_path, path):
    """Render another registered page ('/glossary') the same way; run_ui must already have been called."""
    from nicegui.client import Client
    from nicegui.page import page
    func = [func for func, route in Client.page_routes.items() if route == path][-1]
    client = Client(page(path))
    client.tab_id = 'test-tab'
    with client:
        await func()
    client.outbox.stop()
    return client


async def click_twice(element):
    """Two clicks that both reach the handler before either finishes: a double click."""
    from nicegui.events import GenericEventArguments, handle_event
    listeners = [listener for listener in element._event_listeners.values() if listener.type.startswith('click')]
    assert listeners, f'{element} has no click handler'
    for _ in range(2):
        for listener in listeners:
            handle_event(listener.handler, GenericEventArguments(sender=element, client=element.client, args={}))
    await settle()


async def settle():
    """Let every background task NiceGUI scheduled for an async handler run to completion."""
    from nicegui import background_tasks
    for _ in range(50):
        await asyncio.sleep(0)
        # Every client owns an endless 'outbox loop' task; only handler tasks are awaited.
        pending = [task for task in background_tasks.running_tasks
                   if not task.done() and not task.get_name().startswith('outbox loop')]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    raise AssertionError('background handlers did not settle')


def click_target(element):
    """The element whose click listener a browser click on ``element`` reaches: itself, or (for a card) its face button,
    the first descendant that listens (the "⋯" menu comes after it in document order)."""
    if any(listener.type.startswith('click') for listener in element._event_listeners.values()):
        return element
    return next((child for child in descendants(element)
                 if any(listener.type.startswith('click') for listener in child._event_listeners.values())), element)


async def click(element):
    """Fire the element's click listener the way the browser would, then let async handlers finish."""
    from nicegui.events import GenericEventArguments, handle_event
    element = click_target(element)
    listeners = [listener for listener in element._event_listeners.values() if listener.type.startswith('click')]
    assert listeners, f'{element} has no click handler'
    for listener in listeners:
        handle_event(listener.handler, GenericEventArguments(sender=element, client=element.client, args={}))
    await settle()


def descendants(element):
    for slot in element.slots.values():
        for child in slot.children:
            yield child
            yield from descendants(child)


def texts(element):
    from nicegui import ui
    return [child.text for child in descendants(element) if isinstance(child, ui.label)]


def find(client, **props):
    matches = find_all(client, **props)
    if not matches:
        raise AssertionError(f'no element {props}')
    return matches[-1]  # the newest, so a fresh dialog wins over an older one


def find_all(client, **props):
    tag = props.pop('tag', None)
    css = props.pop('css', None)
    text = props.pop('text', None)
    return [element for element in client.elements.values()
            if (tag is None or element.tag == tag) and (css is None or css in element.classes)
            and (text is None or getattr(element, 'text', None) == text)
            and all(element._props.get(key) == value for key, value in props.items())]


def button(client, label):
    return find(client, tag='q-btn', label=label)


def checkbox(client, text):
    return find(client, tag='q-checkbox', text=text)


def field(client, label):
    """A text (nicegui-input) or number (q-input) field by its label."""
    matches = [element for element in find_all(client, label=label) if element.tag in ('nicegui-input', 'q-input')]
    assert matches, f'no field {label!r}'
    return matches[-1]


def links(element):
    return [child.text for child in descendants(element) if child.tag == 'nicegui-link']


def visible_editor(client):
    """The one inline editor (converter, test or limits) that is open; the others stay hidden."""
    open_editors = [editor for editor in find_all(client, css='bench-editor') if editor.visible]
    assert len(open_editors) == 1, f'{len(open_editors)} editors open'
    return open_editors[0]


def cards(client):
    """(title, card element) for every selectable card on the page, in document order."""
    return [(texts(card)[0], card) for card in find_all(client, css='bench-card-item')]


def card_named(client, title):
    return next(card for name, card in cards(client) if name == title)


def link_in(card, label):
    """A card action: an item of the card's "⋯" menu (Rename, Duplicate, Edit, Delete); the item carries the click listener."""
    return next(child for child in descendants(card) if child.tag == 'q-item'
                and any(grandchild.tag == 'q-item-section' and grandchild.text == label for grandchild in descendants(child)))


def menu_items(card):
    return [child.text for child in descendants(card) if child.tag == 'q-item-section']


def iso_rows(service, system='12V'):
    """The catalog's own rows for the seeded converter on the simulated bench: the tests derive their expectations
    from them so they hold for the catalog version in this checkout and for the mock-only / after-approval one."""
    return clause_rows(service.load_profile('bench', 'mock-dp821-envelope'), service.load_profile('dut', '12t12-4a'), system)


def default_ticked(row):
    return bool(row.get('ticked_by_default', row['badge'] == 'runs_here')) and row['tickable']


def ancestors(element):
    while element.parent_slot is not None:
        element = element.parent_slot.parent
        yield element


def test_header_shows_background_activity_until_the_job_settles(tmp_path, monkeypatch):
    """Owner: 'I wish it had a loading-type icon to let me know it's working in the background.'"""
    from nicegui import ui
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll = page.client, page.poll
        try:
            with client:
                pill = find(client, css='bench-activity')
                assert any('bench-header' in ancestor.classes for ancestor in ancestors(pill)), 'in the sticky header'
                assert any(isinstance(child, ui.spinner) for child in descendants(pill))
                assert pill.visible, 'the page attached to the active job on load and polled it'
                assert not find(client, css='bench-idle').visible
                phrase, detail = texts(pill)
                assert phrase == 'Simulation: Acquiring… point 2 of 4', 'the mode word leads (C34)'
                assert detail.startswith('12T12-4A · started ' + local_time_text('2026-09-29T20:40:12+00:00') + ' · elapsed ')
                questions = find_all(client, css='bench-question')
                assert len(questions) == 3 and all('bench-locked' in q.classes for q in questions), 'the three questions are locked while a job runs'
                assert find(client, css='bench-bar-hint').text == 'Locked while a test runs on the bench. Start returns when it has finished.'
                for state_name, expected in (('queued', 'Simulation: Queued — waiting for the worker to start'),
                                             ('reporting', 'Simulation: Generating report…'),
                                             ('report-queued', 'Simulation: Report queued — starts when the bench is idle')):
                    snapshots['job-1']['state'] = state_name
                    await poll()
                    assert pill.visible and texts(pill)[0] == expected, state_name
                assert not any('bench-locked' in q.classes for q in find_all(client, css='bench-question')), \
                    'a queued report does not hold the bench: a new test may start meanwhile'
                snapshots['job-1'].update(REPORT_DONE)
                await poll()
                assert not pill.visible, 'nothing runs in the background any more'
                assert find(client, css='bench-idle').visible and find(client, css='bench-idle').text == 'Idle — nothing switched on'
                assert 'Started: ' + local_time_text('2026-09-29T20:40:12+00:00') in texts(find(client, css='bench-run-section'))
                assert time_legend() in texts(client.layout)
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_reports_follow_the_job_without_pressing_refresh(tmp_path, monkeypatch):
    """Owner: 'I am in Reports and the new test does not show automatically — I have to press Refresh.'"""
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll, notices, service = page.client, page.poll, page.notices, page.service
        try:
            with client:
                reports = find(client, css='bench-reports')
                assert 'Acquiring measurements' in texts(reports)
                clock, date = time_lines(local_time_text('2026-09-29T20:40:12+00:00'))
                assert clock in texts(reports) and date in texts(reports), 'rows show the local start time, clock above date'
                assert '12T12-4A' in texts(reports) and 'Simulation · synthetic data' in texts(reports)
                listed = service.list_jobs_calls
                snapshots['job-1']['progress'] = {'completed': 3, 'total': 4, 'current': 'p4'}
                await poll()
                await poll()
                assert service.list_jobs_calls == listed, 'progress ticks alone do not re-list the saved runs'
                assert notices == []
                snapshots['job-1'].update(REPORT_DONE)
                await poll()
                assert service.list_jobs_calls == listed + 1, 'the terminal transition refreshed the list from the poll'
                assert 'Complete' in texts(reports) and 'Acquiring measurements' not in texts(reports)
                assert links(reports) == ['Open HTML', 'Open PDF']
                assert any(child._props.get('label') == 'Regenerate report' for child in descendants(reports))
                assert notices == ['Report ready: r-0001']
                await poll()
                assert service.list_jobs_calls == listed + 1 and notices == ['Report ready: r-0001'], 'settled: no busy loop, no repeat'
                button(client, 'Refresh saved runs')
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_idle_page_shows_no_activity_indicator(tmp_path, monkeypatch):
    snapshots = {'job-1': snapshot('job-1', **REPORT_DONE)}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll, notices = page.client, page.poll, page.notices
        try:
            with client:
                pill = find(client, css='bench-activity')
                assert not pill.visible
                await poll()
                assert not pill.visible and notices == []
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_page_asks_three_questions_then_preview_and_start(tmp_path, monkeypatch):
    """The approved one-page layout: converter cards, two bench tiles with the limit presets, test cards, sticky bar."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                shown = texts(client.layout)
                for heading in ('Which converter?', 'Simulated or real bench?', 'Which test?', 'Reports'):
                    assert heading in shown
                assert not find_all(client, tag='q-tab'), 'no tabs any more'
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulation · {QUICK_TITLE}'
                titles = [name for name, _ in cards(client)]
                assert titles[:3] == ['12T12-4A', SMALL_GRID_TITLE, QUICK_TITLE], 'converter first, then tests by title'
                assert titles[3:] == ['ISO 16750-2:2023 — electrical loads'], 'then the one standard this bench can test'
                converter = card_named(client, '12T12-4A')
                assert 'selected' in converter.classes and '9–36 V in, 12 V / 4 A out' in texts(converter)
                assert 'Not yet approved for the real bench' in texts(converter)
                quick = card_named(client, QUICK_TITLE)
                assert 'selected' in quick.classes and '12 / 24 / 30 V × 0–1 A' in texts(quick) and '21 points · simulated' in texts(quick)
                small = card_named(client, SMALL_GRID_TITLE)
                assert 'selected' not in small.classes and '24 V × 0.1 / 0.25 / 0.5 A' in texts(small) and '3 points · simulated' in texts(small)
                assert menu_items(quick) == ['Rename', 'Duplicate', 'Edit', 'Delete'], 'one ⋯ menu per card, not nested buttons'
                assert menu_items(converter) == ['Rename', 'Edit', 'Delete']
                face = next(child for child in descendants(quick) if 'bench-card-select' in child.classes)
                assert face.tag == 'button' and face._props.get('aria-pressed') == 'true', 'the card face is a real button (Enter and Space work)'
                assert not any(child.tag == 'q-btn' for child in descendants(face)), 'nothing interactive inside the button'
                assert 'Normal operating voltage' in shown, 'tests are grouped by category'
                assert [texts(add)[0] for add in find_all(client, css='bench-add')] == ['+ Add a converter', '+ New test']
                assert all(add.tag == 'button' for add in find_all(client, css='bench-add'))
                assert titles.index(ISO_TITLE) > titles.index(QUICK_TITLE) and \
                    texts(client.layout).index('+ New test') < texts(client.layout).index('Automotive supply standards'), '+ New test sits with the saved tests'
                sim, real = find_all(client, css='bench-tile')
                assert 'selected' in sim.classes and 'selected' not in real.classes
                group = sim.parent_slot.parent
                assert group._props.get('role') == 'radiogroup' and sim._props.get('role') == 'radio' and real._props.get('role') == 'radio'
                assert texts(sim)[0] == 'Simulation' and texts(real)[0] == 'Real bench' and texts(real)[1].startswith('supply CH1 + load.')
                pill = find(client, css='bench-pill')
                assert pill._props['label'] == '24 V converter tests' and 'on' in pill.classes, 'the seeded preset by its plain name'
                assert pill._props.get('text-color') == 'white' and 'flat' not in pill._props, 'B1: the selected pill label is readable'
                limits = texts(find(client, css='bench-limits'))
                assert limits == ['Supply current limit', '1 A', 'Input over-voltage', '26 V', 'Output voltage guard', '13.2 V',
                                  'Output current guard', '2.55 A'], 'protective limits are always visible'
                approve = checkbox(client, 'I reviewed these limits — required once')
                assert approve.value is False
                assert any(listener.type == 'click.stop' for listener in approve._event_listeners.values()), \
                    'M7: ticking the approval never also switches the bench tile'
                start, preview = button(client, 'Start simulation'), button(client, 'Preview')
                assert not start.enabled and preview.enabled
                assert find(client, css='bench-bar-hint').text == 'Preview first — Start unlocks after a fresh plan.', 'M8: a disabled Start says why'
                assert find(client, css='bench-bar-summary').text == f'12T12-4A · Simulation · {QUICK_TITLE}'
                assert not find(client, css='bench-plan').visible
                footer_links = [child for child in descendants(client.layout) if child.tag == 'nicegui-link']
                assert any(link._props.get('href') == '/glossary' for link in footer_links), 'the footer links the glossary'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_card_selection_updates_the_summary_and_any_change_makes_the_plan_stale(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                await click(card_named(client, SMALL_GRID_TITLE))
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulation · {SMALL_GRID_TITLE}'
                assert 'selected' in card_named(client, SMALL_GRID_TITLE).classes and 'selected' not in card_named(client, QUICK_TITLE).classes
                await click(button(client, 'Preview'))
                plan = find(client, css='bench-plan')
                assert plan.visible and 'stale' not in plan.classes
                shown = texts(plan)
                assert 'Points that will run' in shown and '3 / 3' in shown and 'Skipped' in shown and '0' in shown
                assert 'Simulation — nothing switched on' in shown, 'the bench line names the simulation'
                estimate = next(text for text in shown if 'Report: typically' in text)
                assert estimate.startswith('Measurements: ') and '(simulated)' in estimate and 'about ~' not in estimate, 'a real estimate, not the placeholder'
                assert 'Ready. After Start you will see:' in shown, 'C26/C36: what follows Start is spelled out'
                for index, (label, timing) in enumerate(SIMULATION_SEQUENCE):
                    assert f'{label} — {timing}' in shown and str(index + 1) in shown
                assert 'Before Start' not in shown
                assert button(client, 'Start simulation').enabled and not find(client, css='bench-bar-hint').visible
                assert (tmp_path / 'workspace' / 'previews').is_dir() and list((tmp_path / 'workspace' / 'previews').iterdir())
                await click(card_named(client, QUICK_TITLE))
                assert 'Settings changed — Preview again before starting.' in texts(plan) and 'stale' in plan.classes
                assert not button(client, 'Start simulation').enabled
                await click(button(client, 'Preview'))
                shown = texts(plan)
                assert '19 / 21' in shown and '2' in shown and 'Why points are skipped' in shown
                assert any(text.startswith('2 points assumption_limited: Requested load exceeds the planning budget') for text in shown), \
                    "C24: the planner's word, the same as the CLI"
                legend = [child.content for child in descendants(plan) if child.tag == 'div' and 'bench-legend' in child.classes for child in descendants(child) if hasattr(child, 'content')]
                assert legend == [f'<code>{status}</code>' for status, _ in PLAN_STATUS_LEGEND], 'the legend explains every planner word once'
                assert all(meaning in shown for _, meaning in PLAN_STATUS_LEGEND)
                from nicegui import ui
                table = next(child for child in descendants(plan) if isinstance(child, ui.table))
                assert [column['classes'] for column in table._props['columns']] == ['nowrap', 'nowrap', 'nowrap', 'nowrap', ''], 'only Reason wraps'
            assert page.errors == [] and 'negative' not in page.notice_kinds
        finally:
            client.delete()
    asyncio.run(scenario())


def test_real_bench_changes_the_start_label_and_lists_what_blocks_a_real_start(tmp_path, monkeypatch):
    """Question 2 decides real vs simulated; approvals, limits and the inventory are the 'Before Start' list."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                sim, real = find_all(client, css='bench-tile')
                await click(real)
                sim, real = find_all(client, css='bench-tile')
                assert 'selected' in real.classes and 'selected' not in sim.classes
                start = button(client, 'Start test on the real bench')
                assert not start.enabled and not find_all(client, tag='q-btn', label='Start simulation')
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Real bench (24 V converter tests) · {QUICK_TITLE}'
                approve = checkbox(client, 'I reviewed these limits — required once')
                assert 'bench-approve-missing' in approve.classes
                small = card_named(client, SMALL_GRID_TITLE)
                assert '3 points · ~62 s' in texts(small), 'the real backend\'s own time arithmetic (3 × 16 s + 14 s startup), not a guess'
                await click(small)
                await click(button(client, 'Preview'))
                shown = texts(find(client, css='bench-plan'))
                assert 'Before Start' in shown
                assert any('real_hardware_enabled is false' in text for text in shown)
                assert any('protective_controls.approved is false' in text for text in shown)
                assert any('Configure the private bench inventory before a real run' in text for text in shown)
                assert any(text.startswith('Real bench — ') for text in shown) and 'Limits: 1 A supply · 26 V input · 13.2 V / 2.55 A output' in shown
                assert not button(client, 'Start test on the real bench').enabled
                assert find(client, css='bench-bar-hint').text == 'The plan cannot start: see the Before Start list in the Plan panel.'
                approve.set_value(True)
                await settle()
                assert service.load_profile('bench', 'rigol-local-limited')['protective_controls']['approved'] is True
                assert checkbox(client, 'Limits approved for this preset').value is True
                assert 'Settings changed — Preview again before starting.' in texts(find(client, css='bench-plan'))
                await click(button(client, 'Change limits…'))
                assert 'Change limits — 24 V converter tests' in texts(visible_editor(client))
                field(client, 'Supply current limit (A)').set_value(0.5)
                await click(button(client, 'Save limits'))
                saved = service.load_profile('bench', 'rigol-local-limited')['protective_controls']
                assert saved['source_current_limit_A'] == .5 and saved['approved'] is False, 'changing a limit clears the approval'
                assert '0.5 A' in texts(find(client, css='bench-limits'))
                assert checkbox(client, 'I reviewed these limits — required once').value is False
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_stop_is_a_two_step_control_at_the_far_right_of_the_header(tmp_path, monkeypatch):
    """Stop… → Confirm stop / Keep running, never where Start was; the request time is shown afterwards."""
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll, service = page.client, page.poll, page.service
        try:
            with client:
                stop_area = find(client, css='bench-stop')
                assert stop_area.visible and any('bench-header' in a.classes for a in ancestors(stop_area))
                assert not find_all(client, tag='q-btn', label='Stop test safely')
                bar = find(client, css='bench-bar')
                assert not button(client, 'Start simulation').enabled
                assert not any(b._props.get('label', '').startswith('Stop') for b in descendants(bar)), 'Stop never sits where Start was'
                await click(button(client, 'Stop…'))
                assert service.cancelled == [], 'the first step only arms'
                assert button(client, 'Confirm stop') and button(client, 'Keep running') and not find_all(client, tag='q-btn', label='Stop…')
                await click(button(client, 'Keep running'))
                assert service.cancelled == [] and button(client, 'Stop…') and not find_all(client, tag='q-btn', label='Confirm stop')
                await click(button(client, 'Stop…'))
                await click_twice(button(client, 'Confirm stop'))
                assert service.cancelled == ['job-1'], 'QA M3: Confirm stop is single-shot; a double click asks the service once'
                assert 'Stop requested — waiting for the worker' in texts(stop_area)
                assert texts(find(client, css='bench-activity'))[0] == 'Simulation: Stopping… waiting for both outputs to be verified OFF'
                snapshots['job-1'].update(state='cancelled', cancel_requested=False, run_dir='/w/jobs/job-1/runs/r-0001',
                                          acquisition_cancelled=True, acquisition_cancelled_utc='2026-09-29T20:40:15+00:00')
                await poll()
                shown = texts(find(client, css='bench-run-section'))
                assert 'Stopped' in shown and 'Stop requested: ' + local_time_text('2026-09-29T20:40:15+00:00') in shown
                assert not stop_area.visible
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_rename_duplicate_and_delete_go_through_dialogs_and_persist(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(link_in(card_named(client, '12T12-4A'), 'Rename'))
                name_field = field(client, 'New name')
                assert name_field.value == '12T12-4A'
                name_field.set_value('Board A')
                await click(button(client, 'Save'))
                assert service.load_profile('dut', '12t12-4a')['identity']['model'] == 'Board A', 'the saved identifier is unchanged'
                assert card_named(client, 'Board A') is not None
                assert find(client, css='bench-summary-text').text.startswith('Board A · ')
                await click(link_in(card_named(client, QUICK_TITLE), 'Rename'))
                field(client, 'New name').set_value('Quick sweep')
                await click(button(client, 'Save'))
                assert service.load_profile('recipe', QUICK)['title'] == 'Quick sweep'
                assert 'selected' in card_named(client, 'Quick sweep').classes
                await click(link_in(card_named(client, SMALL_GRID_TITLE), 'Duplicate'))
                copied = service.load_profile('recipe', SMALL_GRID + '-copy')
                assert copied['title'] == SMALL_GRID_TITLE + ' (copy)' and copied['execution_mode'] is None
                assert 'selected' in card_named(client, SMALL_GRID_TITLE + ' (copy)').classes
                await click(link_in(card_named(client, 'Quick sweep'), 'Delete'))
                assert 'Delete this saved test? Past runs keep their own copy.' in texts(client.layout)
                await click(button(client, 'Cancel'))
                assert QUICK in service.list_profiles()['recipe'], 'Cancel keeps it'
                await click(link_in(card_named(client, 'Quick sweep'), 'Delete'))
                await click(button(client, 'Delete'))
                assert QUICK not in service.list_profiles()['recipe']
                assert 'Quick sweep' not in [name for name, _ in cards(client)]
                assert any(n.startswith('Deleted “' + QUICK + '”') for n in page.notices)
                await click(link_in(card_named(client, 'Board A'), 'Delete'))
                assert 'Delete this saved converter? Past runs keep their own copy.' in texts(client.layout)
                await click(button(client, 'Delete'))
                assert service.list_profiles()['dut'] == []
                assert find(client, css='bench-summary-text').text.startswith('— no converter —')
                assert not button(client, 'Preview').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_a_test_the_planner_cannot_run_on_the_selected_bench_is_greyed_with_the_reason(tmp_path, monkeypatch):
    seeded = JobService(tmp_path / 'workspace')
    recipe = seeded.load_profile('recipe', QUICK)
    recipe.update(recipe_id='hundred-volt', title='100 V check', execution_mode=None, standard_clause='MIL-STD-704F §5.1.2',
                  category='MIL-STD-704F')
    recipe['tests'][0]['input_voltage_targets_V'] = [100.]
    seeded.save_profile('recipe', recipe)

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                greyed = card_named(client, '100 V check')
                assert 'greyed' in greyed.classes
                assert 'Cannot run on this bench: Requested input voltage is outside the DUT operating rating' in texts(greyed)
                assert 'MIL-STD-704F §5.1.2' in texts(greyed), 'a standard clause shows as a badge'
                assert 'MIL-STD-704F' in texts(client.layout), 'grouped under its standard'
                assert 'greyed' not in card_named(client, QUICK_TITLE).classes
                await click(greyed)
                await click(button(client, 'Preview'))
                shown = texts(find(client, css='bench-plan'))
                assert '0 / 7' in shown and 'No feasible point is available' in shown
                assert not button(client, 'Start simulation').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_new_test_editor_saves_a_modeless_recipe_bound_to_the_selected_converter(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(next(add for add in find_all(client, css='bench-add') if texts(add)[0] == '+ New test'))
                assert 'New test' in texts(visible_editor(client))
                field(client, 'Save test as (file name, letters/digits/-_.)').set_value('noload-then-0p1')
                field(client, 'Plain name shown on the card').set_value('24 V — no-load window, then 0.1 A')
                field(client, 'Input voltages (V)').set_value('24')
                field(client, 'Output loads (A)').set_value('0, 0.1')
                await click(button(client, 'Save test'))
                saved = service.load_profile('recipe', 'noload-then-0p1')
                assert saved['execution_mode'] is None and saved['dut_profile_id'] == '12t12-4a'
                assert saved['tests'][0]['output_current_targets_A'] == [0., .1] and saved['category'] == 'Normal operating voltage'
                card = card_named(client, '24 V — no-load window, then 0.1 A')
                assert 'selected' in card.classes and '24 V × 0 / 0.1 A' in texts(card) and '2 points · simulated' in texts(card)
                assert not any(editor.visible for editor in find_all(client, css='bench-editor')), 'saving closes the editor'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


# --- Automotive standards in "Which test?" ---------------------------------------------------------

ISO_TITLE = 'ISO 16750-2:2023 — electrical loads'


def clause_box(client, number):
    return next(element for element in find_all(client, tag='q-checkbox') if str(element.text).startswith(f'§{number} '))


def clause_row(client, number):
    box = clause_box(client, number)
    return next(ancestor for ancestor in ancestors(box) if 'bench-clause-row' in ancestor.classes)


def badge_of(client, number):
    return next(child for child in descendants(clause_row(client, number)) if 'bench-badge' in child.classes)


def test_standards_group_shows_only_iso16750_2_and_names_the_other_laboratories_in_a_footnote(tmp_path, monkeypatch):
    """Owner: conducted transients, CISPR emissions, radiated immunity, ESD, mechanical and climatic loads 'can't
    possibly be tested on this setup', so they are no longer cards; one footnote names them and links the catalog."""
    from dcdc_bench.standard_recipes import OTHER_LABORATORIES_NOTE

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                assert 'Automotive supply standards' in texts(client.layout)
                titles = [name for name, _ in cards(client)]
                assert titles.index(ISO_TITLE) > titles.index(QUICK_TITLE), 'the standards group follows the saved tests'
                assert [title for title in titles if title.startswith(('ISO ', 'CISPR '))] == [ISO_TITLE], 'the only standards card'
                for title in ('ISO 7637-2:2011 — conducted transients', 'CISPR 25:2021 — emissions', 'ISO 11452 — radiated immunity',
                              'ISO 10605:2023 — electrostatic discharge', 'ISO 16750-3:2023 — mechanical loads', 'ISO 16750-4:2023 — climatic loads'):
                    assert title not in titles and title not in texts(client.layout), title
                assert not any(text.startswith('Not on this bench: ') for text in texts(client.layout)), 'no greyed laboratory cards'
                note = find(client, css='bench-standards-note')
                head, catalog, tail = OTHER_LABORATORIES_NOTE.partition('the standards catalog')
                assert note.content == f'{head}[{catalog}](/standards){tail}', 'the footnote links the catalog page'
                assert OTHER_LABORATORIES_NOTE.startswith('Other automotive standards (ISO 7637-2, CISPR 25, ISO 11452, ISO 10605, ISO 16750-3/-4) '
                                                          'need other laboratories; see the standards catalog.')
                shown = texts(client.layout)
                assert shown.index('+ New test') < shown.index('Automotive supply standards'), 'the footnote closes the group'
                iso = card_named(client, ISO_TITLE)
                rows = iso_rows(page.service)
                now = sum(1 for row in rows if row['badge'] == 'runs_here')
                assert 'greyed' not in iso.classes and 'selected' not in iso.classes and 'editor' in iso.classes and '12 V system' in texts(iso)
                assert any(str(now) in text and 'runnable now' in text for text in texts(iso)), texts(iso)
                assert not find_all(client, tag='q-checkbox', text='§4.2 Direct current (DC) supply voltage'), 'folded until opened'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_iso_card_expands_into_a_clause_checklist_with_one_badge_per_status(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                await click(card_named(client, ISO_TITLE))
                assert 'open' in card_named(client, ISO_TITLE).classes and 'selected' not in card_named(client, ISO_TITLE).classes
                shown = texts(client.layout)
                rows = {row['number']: row for row in iso_rows(page.service)}
                now = sum(1 for row in rows.values() if row['badge'] == 'runs_here')
                later = sum(1 for row in rows.values() if row['tickable'] and row['badge'] != 'runs_here')
                assert f'{now} of 19 clauses runnable now on this bench' + (f' · {later} after approval' if later else '') in shown
                assert rows['4.2']['badge'] == 'runs_here' and clause_box(client, '4.2').value is True
                for number, row in rows.items():
                    box, badge = clause_box(client, number), badge_of(client, number)
                    assert badge.text == row['badge_label'], f'§{number} shows the catalog status word as it comes'
                    assert box.enabled is row['tickable']
                    # B3: only a clause that runs here now is ticked by selecting the standard and badged green;
                    # a clause that needs an approval first is amber and left unticked for the operator.
                    assert box.value is default_ticked(row), f'§{number} default tick'
                    if row['badge'] == 'runs_here':
                        assert 'bench-badge-ok' in badge.classes
                    elif row['tickable'] or row['badge'] == 'procedure_pending':
                        assert 'bench-badge-partial' in badge.classes, f'§{number} is never green'
                    else:
                        assert 'bench-badge-grey' in badge.classes and box._props.get('disable') is True
                        assert any(text.endswith('.') and len(text) > 40 for text in texts(clause_row(client, number))), 'the reason sentence is shown'
                    if row.get('needs_approval') and row.get('approval'):
                        assert any(row['approval'] in text for text in texts(clause_row(client, number))), 'where approval is recorded is said on the row'
                assert badge_of(client, '4.3.1.1').text == 'procedure not yet implemented' and not clause_box(client, '4.3.1.1').enabled
                assert rows['4.3.1.1']['text'] in texts(clause_row(client, '4.3.1.1'))
                assert badge_of(client, '4.6.4').text == 'excluded by policy' and rows['4.6.4']['text'] in texts(clause_row(client, '4.6.4'))
                assert any('code C: UA 14 V, Usmin 9 V, Usmax 16 V' in text for text in texts(clause_row(client, '4.2')))
                assert rows['4.5']['levels'] in texts(clause_row(client, '4.5'))
                assert len(find_all(client, css='bench-clause-row')) == 19
                assert button(client, 'Add as tests').enabled
                await click(card_named(client, ISO_TITLE))
                assert not find_all(client, css='bench-clause-row'), 'selecting the standard again folds the checklist'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_system_toggle_switches_to_24_v_levels_and_is_remembered_on_the_converter(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(card_named(client, ISO_TITLE))
                toggle = find(client, tag='q-btn-toggle')
                assert toggle.value == '12V'
                toggle.set_value('24V')
                await settle()
                assert service.load_profile('dut', '12t12-4a')['system_voltage_class'] == '24V', 'remembered on the converter profile'
                assert '24 V system' in texts(card_named(client, ISO_TITLE))
                rows = {row['number']: row for row in iso_rows(service, '24V')}
                assert any('code E: UA 28 V, Usmin 10 V, Usmax 32 V' in text for text in texts(clause_row(client, '4.2')))
                assert rows['4.5']['levels'].startswith('28 V → 1 V → 28 V') and rows['4.5']['levels'] in texts(clause_row(client, '4.5'))
                assert badge_of(client, '4.3.1.1').text == rows['4.3.1.1']['badge_label'] == 'outside DUT rating' and not clause_box(client, '4.3.1.1').enabled
                assert any('36 V level' in text and 'equals the DUT ceiling' in text for text in texts(clause_row(client, '4.3.1.1')))
                assert badge_of(client, '4.3.1.2').text == 'not applicable'
                assert all(clause_box(client, n).value is default_ticked(rows[n]) for n in ('4.2', '4.5', '4.6.2'))
                now = sum(1 for row in rows.values() if row['badge'] == 'runs_here')
                assert any(text.startswith(f'{now} of 19 clauses runnable now on this bench') for text in texts(client.layout))
            assert page.errors == []
            # A fresh page for the same converter opens on the remembered class.
            again = await open_bench_page(monkeypatch, tmp_path, {})
            try:
                with again.client:
                    assert '24 V system' in texts(card_named(again.client, ISO_TITLE))
            finally:
                again.client.delete()
        finally:
            client.delete()
    asyncio.run(scenario())


def test_add_as_tests_saves_one_recipe_per_ticked_runnable_clause_with_the_catalog_fields(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(card_named(client, ISO_TITLE))
                # §4.5 is ticked explicitly (it is not pre-ticked once the catalog marks it approval-first); §4.6.2 is left out.
                clause_box(client, '4.5').set_value(True)
                clause_box(client, '4.6.2').set_value(False)
                await settle()
                await click(button(client, 'Add as tests'))
                saved = service.list_profiles()['recipe']
                assert 'iso16750-2-4-2-12v' in saved and 'iso16750-2-4-5-12v' in saved and 'iso16750-2-4-6-2-12v' not in saved
                assert not any(name.startswith('iso16750-2-4-3') for name in saved), 'a clause without a procedure never becomes a test'
                sweep = service.load_profile('recipe', 'iso16750-2-4-2-12v')
                assert sweep['title'] == 'ISO 16750-2 §4.2 — supply voltage range (12 V system)'
                assert sweep['category'] == 'ISO 16750-2 supply profiles' and sweep['standard_clause'] == 'ISO 16750-2:2023 §4.2'
                assert sweep['dut_profile_id'] == '12t12-4a' and sweep['execution_mode'] is None
                assert sweep['tests'][0]['type'] == 'steady_state_load_sweep' and sweep['tests'][0]['input_voltage_targets_V'] == [14., 9., 16.]
                assert sweep['tests'][0]['output_current_targets_A'] == [.1, .25, .5]
                ramp = service.load_profile('recipe', 'iso16750-2-4-5-12v')
                assert ramp['title'] == 'ISO 16750-2 §4.5 — slow decrease and increase (12 V system)'
                assert ramp['tests'][0]['type'] == 'slow_supply_ramp' and ramp['tests'][0]['input_voltage_targets_V'][:3] == [14., 13., 12.]
                assert min(ramp['tests'][0]['input_voltage_targets_V']) == 1. and ramp['tests'][0]['output_current_targets_A'] == [.1]
                policy = ramp['tests'][0]['supply_profile']
                assert (policy['step_V'], policy['step_interval_s'], policy['expected_off_below_V'], policy['output_on_minimum_V']) == (.02, 2.4, 9., 10.8)
                assert ramp['authorization']['uvlo_approved'] is False
                assert 'ISO 16750-2 supply profiles' in texts(client.layout), 'the new cards are grouped under the standard'
                sweep_card = card_named(client, 'ISO 16750-2 §4.2 — supply voltage range (12 V system)')
                assert 'greyed' not in sweep_card.classes and 'ISO 16750-2:2023 §4.2' in texts(sweep_card) and '9 points · simulated' in texts(sweep_card)
                ramp_card = card_named(client, 'ISO 16750-2 §4.5 — slow decrease and increase (12 V system)')
                assert 'selected' in ramp_card.classes, 'the last added test is selected'
                assert 'greyed' in ramp_card.classes and any('approved UVLO-style path' in text for text in texts(ramp_card)), \
                    'below the stated minimum the profile waits for the recipe approval, as the UVLO example does'
                assert '27 points · simulated' in texts(ramp_card)
                assert any(n.startswith('Added 2 tests') for n in page.notices)
                assert not find_all(client, css='bench-clause-row') and 'open' not in card_named(client, ISO_TITLE).classes, \
                    'the editor folds once its tests exist; the selection is the last test it made'
                await click(card_named(client, ISO_TITLE))
                assert clause_box(client, '4.2').value is True and clause_box(client, '4.5').value is False, 'reopened: default ticks only'
                sweep_card = card_named(client, 'ISO 16750-2 §4.2 — supply voltage range (12 V system)')  # re-rendered with the checklist
                await click(sweep_card)
                assert not find_all(client, css='bench-clause-row'), 'choosing a test folds the editor'
                await click(button(client, 'Preview'))
                shown = texts(find(client, css='bench-plan'))
                assert '9 / 9' in shown and button(client, 'Start simulation').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_an_approval_first_clause_is_amber_unticked_and_names_where_approval_happens(tmp_path, monkeypatch):
    """B3 at the page: whatever the catalog version, a tickable clause that is not "runs here" is never pre-ticked
    or green, and the row says where its approval is recorded."""
    import dcdc_bench.ui as ui_module
    real_rows = ui_module.clause_rows
    how = 'Approval happens in the saved recipe, not on the bench page: set authorization.uvlo_approved to true.'

    def rows_with_approval_first(bench, dut, system):
        rows = real_rows(bench, dut, system)
        for row in rows:
            if row['number'] == '4.5':
                row.update(badge='runs_after_approval', badge_label='runs here after approval', tickable=True,
                           ticked_by_default=False, needs_approval=True, approval=how, text=how)
        return rows
    monkeypatch.setattr(ui_module, 'clause_rows', rows_with_approval_first)

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                await click(card_named(client, ISO_TITLE))
                box, badge = clause_box(client, '4.5'), badge_of(client, '4.5')
                assert box.enabled and box.value is False, 'tickable but not ticked by selecting the standard'
                assert badge.text == 'runs here after approval' and 'bench-badge-partial' in badge.classes and 'bench-badge-ok' not in badge.classes
                assert any(how in text for text in texts(clause_row(client, '4.5'))), 'where approval is recorded is said on the row'
                assert clause_box(client, '4.2').value is True and 'bench-badge-ok' in badge_of(client, '4.2').classes
                footer = find(client, css='bench-checklist-footer').text
                # The footer counts follow the catalog: 4.2 runs now, 4.5 and 4.6.2 need approval, whatever the
                # catalog version says about the exact split.
                assert ' of 19 clauses runnable now on this bench · ' in footer and footer.endswith(' after approval'), footer
                runnable_now = int(footer.split(' of ')[0]); after = int(footer.split('· ')[1].split(' after')[0])
                assert runnable_now + after == 3 and after >= 1, footer
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


# --- Concurrency at the page: a second tab that never saw the running job -------------------------

def test_start_from_a_tab_that_missed_another_tabs_job_is_refused_and_marks_the_plan_stale(tmp_path, monkeypatch):
    """Tab B previewed while idle; Tab A then started a job. Tab B's Start must be refused by the
    service, must not create a job directory or launch a worker, and (QA m1) must leave the plan
    stale so the same refused plan cannot be re-armed without a new Preview."""
    snapshots = {}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client = page.client
        try:
            with client:
                await click(button(client, 'Preview'))
                assert button(client, 'Start simulation').enabled
                # Another tab (or the CLI) started a job after this tab's preview.
                snapshots['job-2'] = snapshot('job-2', 'acquiring')
                monkeypatch.setattr('dcdc_bench.job_service.subprocess.Popen',
                                    lambda *a, **k: pytest.fail('a refused start must not launch a worker'))
                await click(button(client, 'Start simulation'))
                assert any('already acquiring or reporting' in notice for notice in page.notices), page.notices
                assert list((tmp_path / 'workspace' / 'jobs').iterdir()) == [], 'no job directory was created'
                plan = find(client, css='bench-plan')
                assert 'stale' in plan.classes and 'Start was refused — Preview again before starting.' in texts(plan)
                assert not button(client, 'Start simulation').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_an_idle_tab_discovers_a_job_started_elsewhere_within_one_poll(tmp_path, monkeypatch):
    """QA M1 (b, c): a tab with no job of its own follows the bench on the next tick — header, lock, Stop — and unlocks when it ends."""
    snapshots = {}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll = page.client, page.poll
        try:
            with client:
                await click(button(client, 'Preview'))
                assert button(client, 'Start simulation').enabled and find(client, css='bench-idle').visible
                snapshots['job-9'] = snapshot('job-9', 'acquiring')
                await poll()
                pill = find(client, css='bench-activity')
                assert pill.visible and texts(pill)[0] == 'Simulation: Acquiring… point 2 of 4'
                assert all('bench-locked' in q.classes for q in find_all(client, css='bench-question'))
                assert not button(client, 'Start simulation').enabled and not button(client, 'Preview').enabled
                assert find(client, css='bench-stop').visible and button(client, 'Stop…')
                assert 'Acquiring measurements' in texts(find(client, css='bench-run-section')), 'the Run section shows the discovered job'
                snapshots['job-9'].update(REPORT_DONE)
                await poll()
                assert not pill.visible and find(client, css='bench-idle').visible
                assert not any('bench-locked' in q.classes for q in find_all(client, css='bench-question')), 'unlocked without Refresh saved runs'
                assert button(client, 'Preview').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_page_load_attaches_to_a_report_queued_job_and_shows_its_deferral_reason(tmp_path, monkeypatch):
    """QA M1 (a) and m4: F5 while the report is queued (and held back by the memory gate) lands on the truth, in operator words."""
    queued = snapshot('job-1', 'report-queued', run_dir='/w/jobs/job-1/runs/r-0001', queued_utc='2026-09-30T10:00:00+00:00',
                      deferred_reason='MemAvailable below 150 MiB', deferred_utc='2026-09-30T10:00:30+00:00',
                      deferred_memory={'available_mib': 96.4, 'available_plus_swap_free_mib': 900.})
    snapshots = {'job-1': queued}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll = page.client, page.poll
        try:
            with client:
                pill = find(client, css='bench-activity')
                assert pill.visible and texts(pill)[0] == 'Simulation: Report queued — waiting for free memory: 96 MiB available, 150 MiB needed'
                run = texts(find(client, css='bench-run-section'))
                assert 'Measurements saved — report queued' in run
                assert any(text.endswith('Waiting for free memory: 96 MiB available, 150 MiB needed.') for text in run)
                assert not any('MemAvailable' in text for text in run), 'no /proc field name on the page (the raw reason is a tooltip)'
                assert 'Report queued: ' + local_time_text('2026-09-30T10:00:00+00:00') in run
                assert 'Waiting for free memory: 96 MiB available, 150 MiB needed' in texts(find(client, css='bench-reports')), 'the Reports row says so too'
                assert not any('bench-locked' in q.classes for q in find_all(client, css='bench-question')), 'a queued report does not lock the bench'
                assert button(client, 'Remove from report queue')
                # The current step of the simulation sequence is marked.
                steps = find_all(client, css='bench-sequence-step')
                assert [('current' in step.classes, 'done' in step.classes) for step in steps[-4:]] == [(False, True), (True, False), (False, False), (False, False)]
                snapshots['job-1'].update(state='reporting', deferred_reason=None, deferred_memory=None, action='report-only')
                await poll()
                assert texts(pill)[0] == 'Simulation: Generating report…'
                assert all('bench-locked' in q.classes for q in find_all(client, css='bench-question')), 'rendering holds the bench'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_an_older_report_rendering_after_a_new_start_drives_the_header_and_the_lock(tmp_path, monkeypatch):
    """QA M1 family: the tab shows its own queued job while the dispatcher renders an older one; header, lock and Start follow the bench."""
    snapshots = {'job-2': snapshot('job-2', 'report-queued', run_dir='/w/jobs/job-2/runs/r', queued_utc='2026-09-30T11:00:00+00:00'),
                 'job-1': snapshot('job-1', 'reporting', run_dir='/w/jobs/job-1/runs/r', queued_utc='2026-09-30T10:00:00+00:00')}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, poll = page.client, page.poll
        try:
            with client:
                # The page attached to the working job (job-1); the operator views the newer queued run.
                assert texts(find(client, css='bench-activity'))[0] == 'Simulation: Generating report…'
                view = [b for b in find_all(client, tag='q-btn', label='View run')]
                await click(view[0])  # rows are newest first: job-2
                assert 'Measurements saved — report queued' in texts(find(client, css='bench-run-section'))
                assert texts(find(client, css='bench-activity'))[0] == 'Simulation: Generating report…', 'the header follows the bench, not the displayed run'
                assert all('bench-locked' in q.classes for q in find_all(client, css='bench-question')) and not button(client, 'Start simulation').enabled
                snapshots['job-1'].update(REPORT_DONE)
                await poll()
                assert texts(find(client, css='bench-activity'))[0] == 'Simulation: Report queued — starts when the bench is idle'
                assert not any('bench-locked' in q.classes for q in find_all(client, css='bench-question'))
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_double_click_start_creates_one_job_and_no_error_toast(tmp_path, monkeypatch):
    """QA m2: two Start clicks in one tick create one job and no red notice."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                await click(button(client, 'Preview'))
                monkeypatch.setattr('dcdc_bench.job_service.subprocess.Popen', lambda *a, **k: SimpleNamespace(pid=None))
                await click_twice(button(client, 'Start simulation'))
                jobs = list((tmp_path / 'workspace' / 'jobs').iterdir())
                assert len(jobs) == 1, 'one job'
                assert 'negative' not in page.notice_kinds, page.notices
                assert texts(find(client, css='bench-activity'))[0] == 'Simulation: Queued — waiting for the worker to start'
                assert 'Test started — the header shows its progress. Preview again to plan another test.' in texts(find(client, css='bench-plan'))
                run = texts(find(client, css='bench-run-section'))
                assert 'Simulation · synthetic data · no instrument is touched' in run
                assert SIMULATION_SEQUENCE[0][0] + ' — ' + SIMULATION_SEQUENCE[0][1] in run, 'what happens next, with the current step marked'
                assert 'current' in find_all(client, css='bench-sequence-step')[-4].classes
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_regenerate_report_is_single_shot(tmp_path, monkeypatch):
    """QA m2: a double click on Regenerate report queues one rebuild."""
    snapshots = {'job-1': snapshot('job-1', **REPORT_DONE)}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client, service = page.client, page.service
        try:
            with client:
                again = button(client, 'Regenerate report')
                assert again._props.get('aria-label') == 'Regenerate report'
                await click_twice(again)
                assert service.retried == ['job-1']
                assert 'Measurements saved — report queued' in texts(find(client, css='bench-reports'))
                assert not find_all(client, tag='q-btn', label='Regenerate report'), 'a queued job offers no second rebuild'
                await click(button(client, 'Remove from report queue'))
                assert service.cancelled == ['job-1']
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_dequeued_job_does_not_claim_a_failed_report(tmp_path, monkeypatch):
    """QA m7: a job the operator removed from the queue says so; nothing 'needs attention'."""
    snapshots = {'job-1': snapshot('job-1', 'cancelled', run_dir='/w/jobs/job-1/runs/r-0001', dequeued=True,
                                   error='Report generation was removed from the queue; saved measurements are preserved',
                                   shutdown={role: {'state': 'OFF', 'verified': True} for role in ('source', 'load')})}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client = page.client
        try:
            with client:
                await click(button(client, 'View run'))
                run = texts(find(client, css='bench-run-section'))
                assert 'Removed from the report queue' in run
                assert any(text.startswith('Removed from the report queue: no report was generated and none failed.') for text in run)
                assert not any('needs attention' in text for text in run)
                assert 'Removed from the report queue' in texts(find(client, css='bench-reports'))
                assert button(client, 'Regenerate report'), 'the saved measurements can still be rendered'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_completed_simulation_notes_that_its_uncertainty_is_synthetic(tmp_path, monkeypatch):
    """C31: the ± in a simulated report comes from example specifications, and the page says so next to the links."""
    snapshots = {'job-1': snapshot('job-1', **REPORT_DONE)}

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client = page.client
        try:
            with client:
                await click(button(client, 'View run'))
                run = texts(find(client, css='bench-run-section'))
                assert SYNTHETIC_UNCERTAINTY_NOTE in run and 'Complete' in run
                assert 'not an instrument' in SYNTHETIC_UNCERTAINTY_NOTE
                snapshots['job-1']['mode'] = 'real'
                await click(button(client, 'View run'))
                assert SYNTHETIC_UNCERTAINTY_NOTE not in texts(find(client, css='bench-run-section'))
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


# --- Simulation identity: the tiles say what each bench can and cannot do -----------------------

def test_simulation_and_real_tiles_state_what_they_can_and_cannot_do(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                sim, real = find_all(client, css='bench-tile')
                shown_sim, shown_real = texts(sim), texts(real)
                assert shown_sim[0] == 'Simulation'
                assert 'What the simulation can and cannot do' in shown_sim
                for line in SIMULATION_CAN:
                    assert '✓ ' + line in shown_sim
                for line in SIMULATION_CANNOT:
                    assert '✗ ' + line in shown_sim
                assert any('SYNTHETIC' in line for line in SIMULATION_CAN) and any('no instrument' in line.lower() for line in SIMULATION_CAN)
                assert any('cannot' in line.lower() or 'Measure your converter' in line for line in SIMULATION_CANNOT)
                assert any('ripple' in line for line in SIMULATION_CANNOT) and any('± ' in line for line in SIMULATION_CANNOT)
                # UX M1: the synthetic envelope that decides the plan is on the tile, in the real tile's anatomy.
                envelope = texts(find_all(client, css='bench-limits')[0])
                assert envelope[:2] == ['Synthetic source', '0–60 V · 1 A · 60 W'] and 'Protective limits' in envelope
                assert 'What the real bench can and cannot do' in shown_real
                for line in REAL_CAN:
                    assert '✓ ' + line in shown_real
                for line in REAL_CANNOT:
                    assert '✗ ' + line in shown_real
                assert any('48 W' in line for line in REAL_CANNOT) and any('unsupervised' in line for line in REAL_CANNOT)
                assert any('approvals' in line for line in REAL_CANNOT) and any('over-voltage guard' in line for line in REAL_CAN)
                # Both panels stay visible whichever tile is selected.
                await click(real)
                sim, real = find_all(client, css='bench-tile')
                assert 'What the simulation can and cannot do' in texts(sim) and 'What the real bench can and cannot do' in texts(real)
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


# --- No silent overwrite; editors follow deletes; operator-language errors ------------------------

def test_add_converter_or_new_test_refuses_an_existing_file_name(tmp_path, monkeypatch):
    """QA M4: '+ Add a converter' with a saved file name changes nothing and offers a free name or Edit; Edit with a new
    file name replaces the old file instead of leaving two cards."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        before = (tmp_path / 'workspace' / 'profiles' / 'dut' / '12t12-4a.json').read_bytes()
        try:
            with client:
                await click(next(add for add in find_all(client, css='bench-add') if texts(add)[0] == '+ Add a converter'))
                assert 'Add a converter' in texts(visible_editor(client))
                field(client, 'Save converter as (file name, letters/digits/-_.)').set_value('12t12-4a')
                field(client, 'Converter / board model').set_value('Impostor')
                field(client, 'Minimum input (V)').set_value(20)
                await click(button(client, 'Save converter'))
                assert (tmp_path / 'workspace' / 'profiles' / 'dut' / '12t12-4a.json').read_bytes() == before, 'nothing was overwritten'
                assert any("A converter with the file name '12t12-4a' already exists" in n for n in page.notices), page.notices
                editor = visible_editor(client)
                assert 'A converter file named “12t12-4a” already exists. Nothing was overwritten.' in texts(editor)
                assert button(client, 'Open the existing converter')
                await click(button(client, 'Use a free file name'))
                assert field(client, 'Save converter as (file name, letters/digits/-_.)').value == '12t12-4a-copy'
                await click(button(client, 'Save converter'))
                assert set(service.list_profiles()['dut']) == {'12t12-4a', '12t12-4a-copy'}
                assert card_named(client, 'Impostor') is not None and card_named(client, '12T12-4A') is not None
                # The same for a new test with a saved test's file name.
                await click(next(add for add in find_all(client, css='bench-add') if texts(add)[0] == '+ New test'))
                field(client, 'Save test as (file name, letters/digits/-_.)').set_value(QUICK)
                await click(button(client, 'Save test'))
                assert any(f"A test with the file name '{QUICK}' already exists" in n for n in page.notices)
                assert service.load_profile('recipe', QUICK)['title'] == QUICK_TITLE, 'the seeded test is untouched'
                assert button(client, 'Open the existing test')
                await click(button(client, 'Cancel'))
                # Edit with a changed file name moves the profile; recipes that referenced the converter follow it.
                await click(link_in(card_named(client, '12T12-4A'), 'Edit'))
                field(client, 'Save converter as (file name, letters/digits/-_.)').set_value('board-a')
                await click(button(client, 'Save converter'))
                assert set(service.list_profiles()['dut']) == {'board-a', '12t12-4a-copy'}, 'no second card, no orphaned file'
                assert all(service.load_profile('recipe', name)['dut_profile_id'] in ('board-a', '12t12-4a-copy')
                           for name in service.list_profiles()['recipe'])
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_delete_closes_an_open_editor_for_the_same_profile(tmp_path, monkeypatch):
    """QA m9: Delete while the same test is open in the editor closes it, so Save cannot recreate the file."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(link_in(card_named(client, QUICK_TITLE), 'Edit'))
                assert 'Edit test' in texts(visible_editor(client))
                await click(link_in(card_named(client, QUICK_TITLE), 'Delete'))
                await click(button(client, 'Delete'))
                assert QUICK not in service.list_profiles()['recipe']
                assert not any(editor.visible for editor in find_all(client, css='bench-editor')), 'the editor closed with its profile'
                assert not find_all(client, tag='q-btn', label='Save test')
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_editor_errors_use_operator_language(tmp_path, monkeypatch):
    """QA m6 at the page: a cleared number and a hidden-limit violation are refused in sentences naming the visible field."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client, service = page.client, page.service
        try:
            with client:
                await click(next(add for add in find_all(client, css='bench-add') if texts(add)[0] == '+ New test'))
                field(client, 'Save test as (file name, letters/digits/-_.)').set_value('my-grid')
                field(client, 'Minimum settling time (s)').set_value(None)
                await click(button(client, 'Save test'))
                assert page.notices[-1] == 'Enter a number for “Minimum settling time (s)”.'
                field(client, 'Minimum settling time (s)').set_value(45)
                await click(button(client, 'Save test'))
                assert page.notices[-1] == '“Minimum settling time (s)” must be at most 30 s, this test’s settling timeout.'
                field(client, 'Minimum settling time (s)').set_value(5)
                field(client, 'Planning efficiency estimate (%)').set_value(0)
                await click(button(client, 'Save test'))
                assert page.notices[-1] == '“Planning efficiency estimate (%)” must be greater than 0.'
                assert 'my-grid' not in service.list_profiles()['recipe']
                assert not any('TypeError' in n or 'NoneType' in n or 'timeout_s' in n for n in page.notices)
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


# --- Glossary page and the guide's labels ----------------------------------------------------------

def guide_section(text, heading):
    start = text.index('\n' + heading)
    following = text.find('\n## ', start + 1)
    return text[start:following if following != -1 else None]


# Bold phrases of the guide's page walkthroughs and safety checklist that are prose, not labels on the page.
NOT_UI_LABELS = {'8082', '8081', 'Ports → Forward a Port → 8082', 'no job is active', 'and',
                 # §5 emphasis: wiring, sensing, exit codes and the measurement boundary
                 'channel 1', 'local load sensing', 'path efficiency includes input and output wiring losses',
                 'REAL HARDWARE, read-only `*IDN?`', 'both with `expected_serial` set', '26 V input OVP',
                 'Exit 0', 'Exit 4', 'Exit 2'}
# Labels the guide quotes with a placeholder or a runtime value: the literal fragments the page source must contain.
COMPOSED_LABELS = {'Acquiring… point n of m': ('Acquiring… point ', ' of '),
                   'Simulation: Acquiring… point 2 of 21': ('Simulation: ', 'Acquiring… point ', ' of '),
                   'Waiting for free memory: 96 MiB available, 150 MiB needed': ('Waiting for free memory: ', ' MiB available', ' MiB needed'),
                   'Report generation needs attention: PDF. Saved measurements are preserved.':
                       ('Report generation needs attention: ', '. Saved measurements are preserved.'),
                   'The converter is on DP821A CH1 (not CH2) and the load input': ('The converter is on ', ' (not CH2) and the load input'),
                   'I reviewed the protective limits: 1 A supply · 26 V input · 13.2 V / 2.55 A output':
                       ('I reviewed the protective limits: ', ' supply · ', ' input · ', ' / ', ' output')}
# Bold UI labels in the guide that do not occur on the page today; each names its owner. Remove the entry when the guide is fixed.
KNOWN_GUIDE_MISMATCHES = {}


def test_every_bold_ui_label_quoted_in_the_guide_exists_in_the_page_source():
    """New-user C27 and its re-check: the guide's bold labels are the page's labels, byte for byte, in the simulated
    walkthrough (§4.6), the safety checklist (§5) and the real-test walkthrough (§6). A numbered item's bold opening
    sentence is the guide's own heading, not a label. A label composed at run time is checked by its literal fragments."""
    import re
    guide = (DOCS / 'getting-started.md').read_text(encoding='utf-8')
    source = '\n'.join((SRC / name).read_text(encoding='utf-8') for name in ('ui.py', 'ui_models.py', 'job_service.py'))
    sections = ''.join(guide_section(guide, heading) for heading in (
        '6. Optional: open the bench page', '## 5. Critical before any real test', '## 6. Run a real test through the UI'))
    normalise = lambda phrase: re.sub(r'\s+', ' ', phrase)
    titles = {normalise(title) for title in re.findall(r'^\s*\d+\.\s+\*\*(.+?)\*\*', sections, flags=re.M | re.S)}
    phrases = [normalise(phrase) for phrase in re.findall(r'\*\*(.+?)\*\*', sections, flags=re.S)]
    assert len(phrases) > 80 and 'I checked these ratings against the sample label' in phrases, 'all three sections were found'

    def present(phrase):
        phrase = re.sub(r'^\d+ ', '', phrase)  # '1 Which converter?': the number is its own label
        if phrase in COMPOSED_LABELS:
            return all(fragment in source for fragment in COMPOSED_LABELS[phrase])
        if phrase in source:
            return True
        parts = [part for separator in (' → ', ' / ') for part in phrase.split(separator) if separator in phrase]
        return bool(parts) and all(part in source for part in parts)
    missing = sorted({phrase for phrase in phrases if phrase not in titles and phrase not in NOT_UI_LABELS and not present(phrase)})
    assert missing == sorted(KNOWN_GUIDE_MISMATCHES), missing
    assert all(mismatch in guide for mismatch in KNOWN_GUIDE_MISMATCHES), 'a fixed mismatch must be removed from the list'


def test_glossary_page_renders_the_docs_glossary(tmp_path, monkeypatch):
    """The footer's Glossary link opens docs/glossary.md, rendered from the same file the documentation links."""
    assert GLOSSARY_PATH == DOCS / 'glossary.md' and GLOSSARY_PATH.is_file()
    text = GLOSSARY_PATH.read_text(encoding='utf-8')
    for term in ('Path efficiency', 'Qualified', 'Revision', 'Lease', '`approval_blocked`', '`assumption_limited`', '`unsupported`',
                 'SYNTHETIC', '`report-queued`', 'Memory gate', 'M0', 'M5'):
        assert term in text, term

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        glossary = await open_page(monkeypatch, tmp_path, '/glossary')
        try:
            with glossary:
                from nicegui import ui
                rendered = [child for child in glossary.elements.values() if isinstance(child, ui.markdown)]
                assert rendered and 'Path efficiency' in rendered[0].content and 'assumption_limited' in rendered[0].content
                assert any(link._props.get('href') == '/' for link in glossary.elements.values() if link.tag == 'nicegui-link')
            assert page.errors == []
        finally:
            glossary.delete()
            page.client.delete()
    asyncio.run(scenario())


def test_standards_catalog_page_renders_docs_standards_readme_with_its_sibling_links(tmp_path, monkeypatch):
    """The footnote under the ISO 16750-2 card links /standards: docs/standards/README.md read-only, its sibling
    documents under /standards/<file>, and links into the wider docs tree reduced to text (nothing links a file
    the page does not serve)."""
    from dcdc_bench.ui import standards_document
    readme = DOCS / 'standards' / 'README.md'
    assert readme.is_file()
    for name in ('ISO 7637-2', 'CISPR 25', 'ISO 11452', 'ISO 10605', 'ISO 16750-3', 'ISO 16750-4'):
        assert name in readme.read_text(encoding='utf-8'), f'{name} stays in the catalog document'

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        catalog = await open_page(monkeypatch, tmp_path, '/standards')
        try:
            with catalog:
                from nicegui import ui
                rendered = [child for child in catalog.elements.values() if isinstance(child, ui.markdown)]
                assert rendered and 'ISO 7637-2' in rendered[0].content and 'CISPR 25' in rendered[0].content
                assert '](/standards/iso16750-2.md)' in rendered[0].content and '](iso16750-2.md)' not in rendered[0].content
                assert '](../' not in rendered[0].content, 'links into the wider docs tree are plain text here'
                assert any(link._props.get('href') == '/' for link in catalog.elements.values() if link.tag == 'nicegui-link')
            sibling = standards_document('iso16750-2.md')
            assert sibling and 'ISO 16750-2' in sibling and '](../' not in sibling
            assert standards_document('../glossary.md') is None and standards_document('missing.md') is None
            assert page.errors == []
        finally:
            catalog.delete()
            page.client.delete()
    asyncio.run(scenario())


def test_time_lines_split_the_local_time_for_a_narrow_column():
    assert time_lines('13:37:14 PDT (2026-09-29)') == ('13:37:14 PDT', '2026-09-29')
    assert time_lines('unknown') == ('unknown', '')
    assert time_lines(local_time_text('2026-09-29T20:37:14+00:00', zone=LOS_ANGELES)) == ('13:37:14 PDT', '2026-09-29')


def test_exactly_one_test_is_selected_and_the_iso_card_is_an_editor_not_a_second_selection(tmp_path, monkeypatch):
    """Owner: 'Is it normal I can select Normal operating voltage and Automotive supply standards at the same time?!'
    What they saw: a selected test card in one group while the open ISO 16750-2 card in the standards group was drawn
    exactly like a second selected card (green, solid, check mark), because selecting a test never folded it. Now the
    ISO card is an editor (blue, dashed, expand arrow) that leaves the selection alone, and choosing any test folds it."""
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client

        def selected_tests():
            return [name for name, card in cards(client) if 'selected' in card.classes and name != '12T12-4A']

        try:
            with client:
                assert selected_tests() == [QUICK_TITLE]
                await click(card_named(client, ISO_TITLE))
                iso = card_named(client, ISO_TITLE)
                assert find_all(client, css='bench-clause-row'), 'the checklist is open'
                assert 'open' in iso.classes and 'editor' in iso.classes and 'selected' not in iso.classes
                assert not any('bench-card-check' in child.classes for child in descendants(iso)), 'no check mark: it is not a selection'
                assert any('bench-card-expand' in child.classes for child in descendants(iso)), 'an expand arrow instead'
                face = next(child for child in descendants(iso) if 'bench-card-select' in child.classes)
                assert face._props.get('aria-expanded') == 'true' and 'aria-pressed' not in face._props
                assert selected_tests() == [QUICK_TITLE], 'opening the editor changes no selection'
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulation · {QUICK_TITLE}'
                assert find(client, css='bench-bar-summary').text == f'12T12-4A · Simulation · {QUICK_TITLE}'
                await click(card_named(client, SMALL_GRID_TITLE))
                assert selected_tests() == [SMALL_GRID_TITLE], 'exactly one test is selected'
                assert not find_all(client, css='bench-clause-row'), 'choosing a test folds the editor'
                iso = card_named(client, ISO_TITLE)
                assert 'open' not in iso.classes and 'selected' not in iso.classes
                face = next(child for child in descendants(iso) if 'bench-card-select' in child.classes)
                assert face._props.get('aria-expanded') == 'false'
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulation · {SMALL_GRID_TITLE}'
                assert find(client, css='bench-bar-summary').text == f'12T12-4A · Simulation · {SMALL_GRID_TITLE}'
                assert len([card for _, card in cards(client) if 'selected' in card.classes]) == 2, 'one converter and one test, nothing else'
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_reports_list_is_one_grid_whose_header_and_rows_share_the_columns(tmp_path, monkeypatch):
    """Owner: 'The Reports section table is not well aligned.' Each row used to be its own grid, so its max-content
    columns resolved differently from the header's and from its neighbours'. Now the header and every row are
    subgrids of one grid: five shared tracks, Run the only flexible one, the shell widened to 1280 px."""
    from dcdc_bench.ui import STYLE
    snapshots = {'job-2': snapshot('job-2', **REPORT_DONE),
                 'job-1': snapshot('job-1', 'report-queued', run_dir='/w/r', deferred_reason='MemAvailable below 150 MiB',
                                   deferred_memory={'available_mib': 96.})}

    def labels(cell):
        """Visible texts of a cell's direct children (labels, links, buttons); a button's tooltip is not a column entry."""
        return [getattr(child, 'text', None) or child._props.get('label') for child in cell.default_slot.children if child.tag != 'q-tooltip']

    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, snapshots)
        client = page.client
        try:
            with client:
                reports = find(client, css='bench-reports')
                grids = [child for child in descendants(reports) if 'bench-report-grid' in child.classes]
                assert len(grids) == 1, 'one grid for the whole list'
                rows = [child for child in grids[0].default_slot.children if 'bench-report-row' in child.classes]
                assert len(rows) == 3 and 'bench-report-head' in rows[0].classes, 'the header is a row of the same grid'
                assert labels(rows[0]) == ['When', 'Run', 'Bench', 'Status', 'Report']
                assert all(len(row.default_slot.children) == 5 for row in rows), 'every row fills the same five columns'
                when, run, bench, status, actions = rows[1].default_slot.children
                assert 'bench-report-when' in when.classes and labels(when) == list(time_lines(local_time_text('2026-09-29T20:40:12+00:00')))
                assert 'bench-report-run' in run.classes and run.text == '12T12-4A'
                assert 'bench-badge' in bench.classes and bench.text == 'Simulation · synthetic data'
                assert 'bench-report-status' in status.classes and labels(status) == ['Complete', '1 / 4 points'], 'badge above the points line'
                assert 'bench-report-actions' in actions.classes and labels(actions) == ['Open HTML', 'Open PDF', 'View run', 'Regenerate report']
                queued = rows[2]
                assert 'Waiting for free memory: 96 MiB available, 150 MiB needed' in labels(queued.default_slot.children[3])
                assert 'Remove from report queue' in labels(queued.default_slot.children[4])
                # The sheet: the header and the rows share one template through subgrid; the phone layout stacks the cells.
                assert '.bench-report-grid{display:grid;grid-template-columns:max-content minmax(0,2fr) max-content max-content max-content' in STYLE
                assert '.bench-report-row{display:grid;grid-template-columns:subgrid;grid-column:1 / -1' in STYLE
                assert '.bench-shell{max-width:1280px' in STYLE and '.bench-header-inner{max-width:1280px' in STYLE and '.bench-bar-inner{max-width:1280px' in STYLE
                assert '.bench-report-grid,.bench-report-row{grid-template-columns:minmax(0,1fr)}' in STYLE.split('@media(max-width:650px)')[1]
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())
