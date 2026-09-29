"""Presentation boundaries without importing a GUI server or opening hardware."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dcdc_bench.cli import main
from dcdc_bench.ui import RequestBodyLimit, file_headers, published_file, require_loopback, run_ui
from dcdc_bench.ui_models import (artifact_url, edited_dut, edited_recipe, job_actions, job_title, plan_rows, quantity,
                                  report_link_rows, shutdown_label, state_label, target_values)


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
    assert job_title({'dut_model': '12T12-4A', 'created_utc': '2026-09-27T18:30:00+00:00'}) == '12T12-4A · 27 Sep 2026, 18:30 UTC'
    assert job_title({}) == 'Converter test'


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
