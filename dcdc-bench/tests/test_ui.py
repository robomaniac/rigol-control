"""Presentation boundaries without importing a GUI server or opening hardware."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from dcdc_bench.cli import main
from dcdc_bench.ui import published_file, require_loopback, run_ui
from dcdc_bench.ui_models import artifact_url, edited_dut, edited_recipe, job_title, plan_rows, quantity, shutdown_label, state_label, target_values


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
