"""Presentation boundaries without importing a GUI server or opening hardware."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from dcdc_bench.cli import main
from dcdc_bench.job_service import JobService
from dcdc_bench.ui import RequestBodyLimit, file_headers, published_file, require_loopback, run_ui
from dcdc_bench.ui_models import (activity_text, artifact_url, edited_dut, edited_recipe, elapsed_text, event_text,
                                  job_actions, job_title, local_time_text, plan_rows, quantity, report_became_ready,
                                  report_link_rows, saved_runs_key, shutdown_label, state_label, target_values,
                                  time_legend)

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
    assert rows[1][0] == 'Open PDF (not verified: checker tool missing)' and rows[0][0] == 'Open interactive HTML'
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


# --- The rendered page, driven through its own poll --------------------------

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


async def open_bench_page(monkeypatch, tmp_path, snapshots):
    """Render the real '/' page against a fake JobService without a server, socket or browser.

    Returns the NiceGUI client (its element tree is the page), the poll callback the page
    registered with ``ui.timer`` (a test calls it to simulate a tick), the notifications the
    page issued, and the fake service (which counts ``list_jobs`` calls).
    """
    from nicegui import app, run, ui
    from nicegui.client import Client
    from nicegui.page import page
    created, timers, notices = [], [], []

    class FakeService(JobService):
        """Real seeded mock profiles; job status comes from the test's dictionaries."""

        def __init__(self, root, inventory_path=None, gate=None):
            super().__init__(root, inventory_path=inventory_path)
            self.list_jobs_calls = 0
            created.append(self)

        def status(self, job_id):
            return copy.deepcopy(snapshots[job_id])

        def list_jobs(self):
            self.list_jobs_calls += 1
            return [self.status(job_id) for job_id in sorted(snapshots, reverse=True)]

        def dispatch_reports(self):
            return None

    async def inline(callback, *args, **kwargs):
        return callback(*args, **kwargs)
    monkeypatch.setattr(ui, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(app, 'timer', lambda *args, **kwargs: None)
    monkeypatch.setattr(ui, 'timer', lambda interval, callback, **kwargs: timers.append(callback))
    monkeypatch.setattr(ui, 'notify', lambda message, **kwargs: notices.append(str(message)))
    monkeypatch.setattr(run, 'io_bound', inline)
    monkeypatch.setattr('dcdc_bench.job_service.JobService', FakeService)
    monkeypatch.setenv('DCDC_ACTIVITY_LOCK', str(tmp_path / 'activity.lock'))
    monkeypatch.setenv('DCDC_JOB_LAUNCHER', 'detached')
    run_ui(tmp_path / 'workspace')
    bench_page = [func for func, path in Client.page_routes.items() if path == '/'][-1]
    client = Client(page('/'))
    client.tab_id = 'test-tab'  # counts as connected, so ``await client.connected()`` returns at once
    with client:
        await bench_page()
    return client, timers[-1], notices, created[-1]


def descendants(element):
    for slot in element.slots.values():
        for child in slot.children:
            yield child
            yield from descendants(child)


def texts(element):
    from nicegui import ui
    return [child.text for child in descendants(element) if isinstance(child, ui.label)]


def find(client, **props):
    from nicegui import ui
    tag = props.pop('tag', None)
    css = props.pop('css', None)
    for element in client.elements.values():
        if (tag is None or element.tag == tag) and (css is None or css in element.classes) and \
                all(element._props.get(key) == value for key, value in props.items()):
            return element
    raise AssertionError(f'no element {tag} {css} {props}')


def ancestors(element):
    while element.parent_slot is not None:
        element = element.parent_slot.parent
        yield element


def test_header_shows_background_activity_from_every_tab_until_the_job_settles(tmp_path, monkeypatch):
    """Owner: 'I wish it had a loading-type icon to let me know it's working in the background.'"""
    from nicegui import ui
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        client, poll, notices, service = await open_bench_page(monkeypatch, tmp_path, snapshots)
        try:
            with client:
                pill = find(client, css='bench-activity')
                assert not any(ancestor.tag == 'q-tab-panel' for ancestor in ancestors(pill)), 'header, not inside a tab'
                assert any(isinstance(child, ui.spinner) for child in descendants(pill))
                assert pill.visible, 'the page attached to the active job on load and polled it'
                phrase, detail = texts(pill)
                assert phrase == 'Acquiring… point 2 of 4'
                assert detail.startswith('12T12-4A · started ' + local_time_text('2026-09-29T20:40:12+00:00') + ' · elapsed ')
                for state_name, expected in (('queued', 'Queued — waiting for the worker to start'),
                                             ('reporting', 'Generating report…'),
                                             ('report-queued', 'Report queued — starts when the bench is idle')):
                    snapshots['job-1']['state'] = state_name
                    await poll()
                    assert pill.visible and texts(pill)[0] == expected, state_name
                snapshots['job-1'].update(REPORT_DONE)
                await poll()
                assert not pill.visible, 'nothing runs in the background any more'
                assert 'Started: ' + local_time_text('2026-09-29T20:40:12+00:00') in texts(find(client, tag='q-tab-panel', name='Run'))
                assert time_legend() in texts(client.layout)
        finally:
            client.delete()
    asyncio.run(scenario())


def test_reports_tab_follows_the_job_without_pressing_refresh(tmp_path, monkeypatch):
    """Owner: 'I am in Reports and the new test does not show automatically — I have to press Refresh.'"""
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        client, poll, notices, service = await open_bench_page(monkeypatch, tmp_path, snapshots)
        try:
            with client:
                reports = find(client, tag='q-tab-panel', name='Reports')
                assert 'Acquiring measurements' in texts(reports)
                assert job_title(snapshots['job-1']) in texts(reports), 'saved runs are titled with the local start time'
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
                assert any(link.text == 'Open interactive HTML' for link in descendants(reports) if hasattr(link, 'text'))
                assert notices == ['Report ready: r-0001']
                await poll()
                assert service.list_jobs_calls == listed + 1 and notices == ['Report ready: r-0001'], 'settled: no busy loop, no repeat'
                assert any(button._props.get('label') == 'Refresh saved runs' for button in descendants(reports)), 'manual button kept'
        finally:
            client.delete()
    asyncio.run(scenario())


def test_idle_page_shows_no_activity_indicator(tmp_path, monkeypatch):
    snapshots = {'job-1': snapshot('job-1', **REPORT_DONE)}

    async def scenario():
        client, poll, notices, service = await open_bench_page(monkeypatch, tmp_path, snapshots)
        try:
            with client:
                pill = find(client, css='bench-activity')
                assert not pill.visible
                await poll()
                assert not pill.visible and notices == []
        finally:
            client.delete()
    asyncio.run(scenario())


def test_stopped_run_shows_when_the_operator_requested_the_stop(tmp_path, monkeypatch):
    """Job 20260929T213318Z_6290205b showed only 'Stopped' (error None, no time). The recorded request
    time now appears with the other local times so an operator can match it to what they did."""
    snapshots = {'job-1': snapshot('job-1', 'acquiring')}

    async def scenario():
        client, poll, notices, service = await open_bench_page(monkeypatch, tmp_path, snapshots)
        try:
            with client:
                run_tab = find(client, tag='q-tab-panel', name='Run')
                assert not any(text.startswith('Stop requested') for text in texts(run_tab))
                snapshots['job-1'].update(state='cancelled', run_dir='/w/jobs/job-1/runs/r-0001', acquisition_cancelled=True,
                                          acquisition_cancelled_utc='2026-09-29T20:40:15+00:00')
                await poll()
                shown = texts(run_tab)
                assert 'Stopped' in shown
                assert 'Stop requested: ' + local_time_text('2026-09-29T20:40:15+00:00') in shown
        finally:
            client.delete()
    asyncio.run(scenario())
