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
from dcdc_bench.ui import RequestBodyLimit, file_headers, published_file, require_loopback, run_ui, unique_name
from dcdc_bench.ui_models import (activity_text, artifact_url, bench_equipment, bench_title, card_meta, dut_approved,
                                  dut_subtitle, duration_text, edited_dut, edited_recipe, elapsed_text, event_text,
                                  grouped_recipes, job_actions, job_title, limits_rows, limits_summary, local_time_text,
                                  plan_rows, point_count, quantity, recipe_category, recipe_grid, recipe_title,
                                  report_became_ready, report_link_rows, report_rows, saved_runs_key, shutdown_label,
                                  skip_reasons, state_label, summary_text, target_values, time_legend)

LOS_ANGELES = ZoneInfo('America/Los_Angeles')


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


@pytest.mark.parametrize('host', ['0.0.0.0', '192.168.1.10', 'example.com', 'localhost.attacker.invalid'])
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


def test_plan_presentation_retains_exclusions_and_missing_measurements():
    row = plan_rows({'points': [{'point_id': 'p1', 'vin_target_V': 24., 'iout_target_A': .5,
        'estimated_input_current_A': None, 'status': 'assumption_limited', 'reason': 'Above input budget'}]})[0]
    assert row['status_display'] == 'Outside planning budget'
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
    assert activity_text({'state': 'report-queued', 'deferred_reason': 'MemAvailable below 150 MiB'}) == 'Report queued — waiting: MemAvailable below 150 MiB'
    assert activity_text({'state': 'report-queued'}) == 'Report queued — starts when the bench is idle'
    for idle in ({'state': 'completed'}, {'state': 'failed'}, {'state': 'cancelled'}, {'state': 'aborted'}, {}, None):
        assert activity_text(idle) == ''


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
    assert summary_text(None, 'mock', None, None) == '— no converter — · Simulated bench · — no test —'


def test_plan_panel_groups_skip_reasons_and_report_rows_use_local_time():
    preview = {'points': [{'status': 'executable', 'reason': 'ok'}, {'status': 'unsupported', 'reason': 'Above guard'},
                          {'status': 'unsupported', 'reason': 'Above guard'}, {'status': 'assumption_limited', 'reason': 'Budget'}]}
    assert skip_reasons(preview) == [(2, 'Above guard'), (1, 'Budget')]
    job = {'job_id': 'j1', 'state': 'completed', 'mode': 'real', 'dut_model': '12T12-4A', 'recipe_id': 'real-24v-small-grid',
           'recipe_title': 'old name', 'created_utc': '2026-09-29T20:37:14+00:00', 'run_dir': '/w/r',
           'progress': {'completed': 3, 'total': 3}, 'report_dir': '/w/r/reports/r0001',
           'report_artifacts': {'html': {'status': 'success'}, 'pdf': {'status': 'success'}, 'model': {'status': 'success'}}}
    [row] = report_rows([job], zone=LOS_ANGELES, recipes={'real-24v-small-grid': {'title': '24 V small grid', 'tests': []}})
    assert row['when'] == '13:37:14 PDT (2026-09-29)' and row['run'] == '12T12-4A · 24 V small grid' and row['bench'] == 'Real'
    assert row['status'] == 'Complete' and row['points'] == '3 / 3 points' and row['regenerate'] and not row['dequeue']
    assert row['links'] == [('Open HTML', 'report/report.html'), ('Open PDF', 'report/report.pdf')], 'the JSON model stays on the run panel'
    [fallback] = report_rows([{**job, 'recipe_id': 'deleted'}], zone=LOS_ANGELES)
    assert fallback['run'] == '12T12-4A · old name', 'a deleted test keeps the name recorded at Start'
    [legacy] = report_rows([{'job_id': 'j0', 'state': 'acquiring', 'mode': 'mock', 'dut_model': '12T12-4A'}], zone=LOS_ANGELES)
    assert legacy['run'] == '12T12-4A' and legacy['when'] == 'unknown' and legacy['bench'] == 'Simulated'
    assert not legacy['regenerate'] and legacy['status'] == 'Acquiring measurements'
    [queued] = report_rows([{'job_id': 'j2', 'state': 'report-queued', 'mode': 'mock', 'dut_model': 'X', 'run_dir': '/w/r'}], zone=LOS_ANGELES)
    assert queued['dequeue'] and not queued['regenerate']


# --- The rendered page, driven through its own handlers and poll --------------

def snapshot(job_id, state, **extra):
    """A JobService.status()-shaped record; the fake below returns copies of these."""
    base = {'job_id': job_id, 'state': state, 'mode': 'mock', 'dut_model': '12T12-4A', 'pid': None,
            'created_utc': '2026-09-29T20:40:12+00:00', 'error': None, 'run_dir': None, 'report_dir': None,
            'progress': {'completed': 1, 'total': 4, 'current': 'p2'}, 'latest': {}, 'shutdown': {},
            'report_artifacts': {}, 'elapsed_s': 12., 'latest_age_s': 1., 'latest_kind': 'unqualified live readings',
            'deferred_reason': None, 'report_pending': False, 'cancel_requested': False, 'events': []}
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
        """Real seeded mock profiles; job status comes from the test's dictionaries."""

        def __init__(self, root, inventory_path=None, gate=None):
            super().__init__(root, inventory_path=inventory_path)
            self.list_jobs_calls = 0
            self.cancelled = []
            created.append(self)

        def status(self, job_id):
            return copy.deepcopy(snapshots[job_id])

        def list_jobs(self):
            self.list_jobs_calls += 1
            return [self.status(job_id) for job_id in sorted(snapshots, reverse=True)]

        def dispatch_reports(self):
            return None

        def cancel(self, job_id):
            self.cancelled.append(job_id)
            snapshots[job_id]['cancel_requested'] = True
            return self.status(job_id)

    async def inline(callback, *args, **kwargs):
        return callback(*args, **kwargs)
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'timer', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'handle_exception', lambda exc: errors.append(exc))
    monkeypatch.setattr(ui, 'timer', lambda interval, callback, **kwargs: timers.append(callback))
    monkeypatch.setattr(ui, 'notify', lambda message, **kwargs: notices.append(str(message)))
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
    return SimpleNamespace(client=client, poll=timers[-1], notices=notices, service=created[-1], errors=errors)


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


async def click(element):
    """Fire the element's click listener the way the browser would, then let async handlers finish."""
    from nicegui.events import GenericEventArguments, handle_event
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
    return next(child for child in descendants(card) if child.tag == 'q-btn' and child._props.get('label') == label)


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
                assert phrase == 'Acquiring… point 2 of 4'
                assert detail.startswith('12T12-4A · started ' + local_time_text('2026-09-29T20:40:12+00:00') + ' · elapsed ')
                questions = find_all(client, css='bench-question')
                assert len(questions) == 3 and all('bench-locked' in q.classes for q in questions), 'the three questions are locked while a job runs'
                for state_name, expected in (('queued', 'Queued — waiting for the worker to start'),
                                             ('reporting', 'Generating report…'),
                                             ('report-queued', 'Report queued — starts when the bench is idle')):
                    snapshots['job-1']['state'] = state_name
                    await poll()
                    assert pill.visible and texts(pill)[0] == expected, state_name
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
                assert local_time_text('2026-09-29T20:40:12+00:00') in texts(reports), 'rows show the local start time'
                assert '12T12-4A' in texts(reports) and 'Simulated' in texts(reports)
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
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulated bench · {QUICK_TITLE}'
                titles = [name for name, _ in cards(client)]
                assert titles[:3] == ['12T12-4A', SMALL_GRID_TITLE, QUICK_TITLE], 'converter first, then tests by title'
                assert titles[3:] == ['ISO 16750-2:2023 — electrical loads', 'ISO 7637-2:2011 — conducted transients', 'CISPR 25:2021 — emissions',
                                      'ISO 11452 — radiated immunity', 'ISO 10605:2023 — electrostatic discharge',
                                      'ISO 16750-3:2023 — mechanical loads', 'ISO 16750-4:2023 — climatic loads'], 'then the standards catalog'
                converter = card_named(client, '12T12-4A')
                assert 'selected' in converter.classes and '9–36 V in, 12 V / 4 A out' in texts(converter)
                assert 'Not yet approved for the real bench' in texts(converter)
                quick = card_named(client, QUICK_TITLE)
                assert 'selected' in quick.classes and '12 / 24 / 30 V × 0–1 A' in texts(quick) and '21 points · simulated' in texts(quick)
                small = card_named(client, SMALL_GRID_TITLE)
                assert 'selected' not in small.classes and '24 V × 0.1 / 0.25 / 0.5 A' in texts(small) and '3 points · simulated' in texts(small)
                assert [link._props['label'] for link in descendants(quick) if link.tag == 'q-btn'] == ['Rename', 'Duplicate', 'Edit', 'Delete']
                assert [link._props['label'] for link in descendants(converter) if link.tag == 'q-btn'] == ['Rename', 'Edit', 'Delete']
                assert 'Normal operating voltage' in shown, 'tests are grouped by category'
                assert [texts(add)[0] for add in find_all(client, css='bench-add')] == ['+ Add a converter', '+ New test']
                sim, real = find_all(client, css='bench-tile')
                assert 'selected' in sim.classes and 'selected' not in real.classes
                assert texts(real)[0] == 'Real bench' and texts(real)[1].startswith('supply CH1 + load.')
                pill = find(client, css='bench-pill')
                assert pill._props['label'] == '24 V converter tests' and 'on' in pill.classes, 'the seeded preset by its plain name'
                limits = texts(find(client, css='bench-limits'))
                assert limits == ['Supply current limit', '1 A', 'Input over-voltage', '26 V', 'Output voltage guard', '13.2 V',
                                  'Output current guard', '2.55 A'], 'protective limits are always visible'
                approve = checkbox(client, 'I reviewed these limits — required once')
                assert approve.value is False
                start, preview = button(client, 'Start simulated test'), button(client, 'Preview')
                assert not start.enabled and preview.enabled
                assert find(client, css='bench-bar-summary').text == f'12T12-4A · Simulated bench · {QUICK_TITLE}'
                assert not find(client, css='bench-plan').visible
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
                assert find(client, css='bench-summary-text').text == f'12T12-4A · Simulated bench · {SMALL_GRID_TITLE}'
                assert 'selected' in card_named(client, SMALL_GRID_TITLE).classes and 'selected' not in card_named(client, QUICK_TITLE).classes
                await click(button(client, 'Preview'))
                plan = find(client, css='bench-plan')
                assert plan.visible and 'stale' not in plan.classes
                shown = texts(plan)
                assert 'Points that will run' in shown and '3 / 3' in shown and 'Skipped' in shown and '0' in shown
                assert 'Simulated — nothing switched on' in shown and 'simulated · seconds' in shown
                assert 'Ready. HTML and PDF reports are generated automatically after acquisition.' in shown
                assert 'Before Start' not in shown
                assert button(client, 'Start simulated test').enabled
                assert (tmp_path / 'workspace' / 'previews').is_dir() and list((tmp_path / 'workspace' / 'previews').iterdir())
                await click(card_named(client, QUICK_TITLE))
                assert 'Settings changed — Preview again before starting.' in texts(plan) and 'stale' in plan.classes
                assert not button(client, 'Start simulated test').enabled
                await click(button(client, 'Preview'))
                shown = texts(plan)
                assert '19 / 21' in shown and '2' in shown and 'Why points are skipped' in shown
                assert any(text.startswith('2 points skipped: Requested load exceeds the planning budget') for text in shown)
            assert page.errors == [] and not any('negative' in n for n in page.notices)
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
                assert not start.enabled and not find_all(client, tag='q-btn', label='Start simulated test')
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
                assert any(text.startswith('Real — ') for text in shown) and 'Limits: 1 A supply · 26 V input · 13.2 V / 2.55 A output' in shown
                assert not button(client, 'Start test on the real bench').enabled
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
                assert not button(client, 'Start simulated test').enabled
                assert not any(b._props.get('label', '').startswith('Stop') for b in descendants(bar)), 'Stop never sits where Start was'
                await click(button(client, 'Stop…'))
                assert service.cancelled == [], 'the first step only arms'
                assert button(client, 'Confirm stop') and button(client, 'Keep running') and not find_all(client, tag='q-btn', label='Stop…')
                await click(button(client, 'Keep running'))
                assert service.cancelled == [] and button(client, 'Stop…') and not find_all(client, tag='q-btn', label='Confirm stop')
                await click(button(client, 'Stop…'))
                await click(button(client, 'Confirm stop'))
                assert service.cancelled == ['job-1']
                assert 'Stop requested — waiting for the worker' in texts(stop_area)
                assert texts(find(client, css='bench-activity'))[0].startswith('Stopping…')
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
                assert not button(client, 'Start simulated test').enabled
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


def test_standards_group_lists_every_standard_and_greys_those_not_on_this_bench(tmp_path, monkeypatch):
    async def scenario():
        page = await open_bench_page(monkeypatch, tmp_path, {})
        client = page.client
        try:
            with client:
                assert 'Automotive supply standards' in texts(client.layout)
                titles = [name for name, _ in cards(client)]
                assert titles.index(ISO_TITLE) > titles.index(QUICK_TITLE), 'the standards group follows the saved tests'
                for title in ('ISO 7637-2:2011 — conducted transients', 'CISPR 25:2021 — emissions', 'ISO 11452 — radiated immunity',
                              'ISO 10605:2023 — electrostatic discharge', 'ISO 16750-3:2023 — mechanical loads', 'ISO 16750-4:2023 — climatic loads'):
                    other = card_named(client, title)
                    assert 'greyed' in other.classes and 'selected' not in other.classes
                    assert any(text.startswith('Cannot run on this bench: ') for text in texts(other))
                transients = card_named(client, 'ISO 7637-2:2011 — conducted transients')
                assert any('transient pulse generator' in text and 'different laboratory' in text for text in texts(transients))
                iso = card_named(client, ISO_TITLE)
                assert 'greyed' not in iso.classes and '3 of 19 clauses runnable on this bench' in texts(iso) and '12 V system' in texts(iso)
                assert not find_all(client, tag='q-checkbox', text='§4.2 Direct current (DC) supply voltage'), 'folded until selected'
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
                assert 'selected' in card_named(client, ISO_TITLE).classes
                shown = texts(client.layout)
                assert '3 of 19 clauses runnable on this bench' in shown
                for number in ('4.2', '4.5', '4.6.2'):
                    box = clause_box(client, number)
                    assert box.value is True and box.enabled, f'§{number} is ticked by selecting the standard'
                    assert badge_of(client, number).text == 'runs here' and 'bench-badge-ok' in badge_of(client, number).classes
                for number, label, note in (('4.3.1.1', 'procedure not yet implemented', '60-min hold exceeds the 540 s run budget; needs a long-hold procedure'),
                                            ('4.6.1.2', 'procedure not yet implemented', '>=1 s interruptions only (source output switched off at the command cadence); needs an interruption procedure')):
                    box, badge = clause_box(client, number), badge_of(client, number)
                    assert box.value is False and not box.enabled and box._props.get('disable') is True
                    assert badge.text == label and 'bench-badge-partial' in badge.classes
                    assert note in texts(clause_row(client, number))
                for number, label in (('4.3.2', 'needs ms pulse generator'), ('4.6.4', 'excluded by policy'), ('4.7', 'excluded by policy'),
                                      ('4.11', 'not on this bench'), ('4.6.1.1', 'needs 10 ms edges, ms pulse generator')):
                    box, badge = clause_box(client, number), badge_of(client, number)
                    assert not box.enabled and box.value is False, f'§{number} cannot be ticked'
                    assert badge.text == label and 'bench-badge-grey' in badge.classes
                    assert any(text.endswith('.') and len(text) > 40 for text in texts(clause_row(client, number))), 'the reason sentence is shown'
                assert 'Load dump is a fault-injection overvoltage transient that this release does not perform (implementation brief §2 and §7.5).' in texts(clause_row(client, '4.6.4'))
                assert any('code C: UA 14 V, Usmin 9 V, Usmax 16 V' in text for text in texts(clause_row(client, '4.2')))
                assert any(text.startswith('14 V → 1 V → 14 V at 0.5 V/min (20 mV every 2.4 s)') for text in texts(clause_row(client, '4.5')))
                assert any("Levels below the DUT's stated 9 V minimum need the approved UVLO-style recipe" in text for text in texts(clause_row(client, '4.6.2')))
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
                assert any('code E: UA 28 V, Usmin 10 V, Usmax 32 V' in text for text in texts(clause_row(client, '4.2')))
                assert any(text.startswith('28 V → 1 V → 28 V at 0.5 V/min') for text in texts(clause_row(client, '4.5')))
                assert badge_of(client, '4.3.1.1').text == 'outside DUT rating' and not clause_box(client, '4.3.1.1').enabled
                assert any('36 V level' in text and 'equals the DUT ceiling' in text for text in texts(clause_row(client, '4.3.1.1')))
                assert badge_of(client, '4.3.1.2').text == 'not applicable'
                assert all(clause_box(client, n).value is True for n in ('4.2', '4.5', '4.6.2'))
                assert '3 of 19 clauses runnable on this bench' in texts(client.layout)
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
                assert not button(client, 'Add as tests').enabled, 'ticks are consumed'
                await click(sweep_card)
                await click(button(client, 'Preview'))
                shown = texts(find(client, css='bench-plan'))
                assert '9 / 9' in shown and button(client, 'Start simulated test').enabled
            assert page.errors == []
        finally:
            client.delete()
    asyncio.run(scenario())
