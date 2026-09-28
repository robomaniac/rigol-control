"""Local NiceGUI bench workflow. Hardware ownership stays in JobService workers.

Importing this module does not import NiceGUI, start a server or open equipment.
"""
from __future__ import annotations

import copy
import ipaddress
import json
from pathlib import Path

from .ui_models import artifact_url, edited_dut, edited_recipe, job_title, plan_rows, quantity, shutdown_label, state_label


STYLE = '''
body{background:#f3f6f8;color:#183047;font-family:system-ui,sans-serif}
.bench-shell{max-width:1180px;margin:0 auto;width:100%;padding:24px}
.bench-card{background:white;border:1px solid #dce5eb;border-radius:12px;box-shadow:none;padding:22px;width:100%}
.bench-title{font-size:30px;font-weight:700;line-height:1.2;letter-spacing:-.035em}
.bench-subtitle{color:#526879;max-width:850px;font-size:15px}
.bench-section-title{font-size:20px;font-weight:650;margin-bottom:6px}
.bench-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;width:100%}
.bench-fields>*{min-width:0}.bench-message{padding:12px 16px;border-radius:7px;background:#edf5f7;width:100%;overflow-wrap:anywhere}
.bench-warning{background:#fff3df;color:#77511d}.bench-muted{color:#5a6f7e;font-size:13px}
.bench-stat{background:#f3f7f9;border-radius:8px;padding:14px;min-width:150px;flex:1}
.bench-stat-value{font-size:24px;font-weight:650}.bench-tabs{background:white;border:1px solid #dce5eb;border-radius:10px}
.bench-shell .q-table__container{max-width:100%}.bench-shell .q-table td{white-space:normal;overflow-wrap:anywhere}
.bench-shell .q-tab-panels{background:transparent;width:100%}.bench-shell .q-tab-panel{padding:20px 0}
.bench-shell .q-field{width:100%}.bench-shell .q-checkbox__label{overflow-wrap:anywhere}
.bench-shell pre{white-space:pre-wrap;overflow-wrap:anywhere}.bench-artifact{font-weight:600;color:#15608f}
@media(max-width:680px){.bench-shell{padding:14px}.bench-card{padding:16px}.bench-fields{grid-template-columns:1fr}.bench-title{font-size:25px}.bench-stat{min-width:125px}}
'''


def require_loopback(host: str) -> str:
    if host == 'localhost':
        return '127.0.0.1'
    try:
        okay = ipaddress.ip_address(host).is_loopback
    except ValueError:
        okay = False
    if not okay:
        raise ValueError('The instrument-control UI binds to loopback only. Use an SSH tunnel for remote access.')
    return host


def published_file(roots: dict[str, Path], relative: str) -> Path:
    """Resolve a file inside an explicitly published run root, including aliases."""
    artifact_url('published', relative)
    parts = relative.split('/')
    if parts[0] not in roots:
        raise ValueError('Unknown published run')
    root = roots[parts[0]]
    if len(parts) == 1 and root.is_file():
        return root
    if len(parts) < 2:
        raise ValueError('Choose a file within the published run')
    path = root.joinpath(*parts[1:]).resolve()
    path.relative_to(root)
    if not path.is_file():
        raise ValueError('Not a published file')
    return path


def run_ui(root: Path, inventory_path: Path | None = None, *, host: str = '127.0.0.1', port: int = 8082,
           report_root: Path | None = None) -> None:
    host = require_loopback(host)
    if not 1 <= port <= 65535:
        raise ValueError('Choose a TCP port between 1 and 65535.')
    from nicegui import app, core, run, ui
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from .job_service import JobService

    service = JobService(Path(root), inventory_path=inventory_path)
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=list({'localhost', '127.0.0.1', '[::1]', '::1', host}))
    # NiceGUI's generic default permits every WebSocket origin. Bench control
    # uses Engine.IO's same-origin policy; SSH forwards retain their Host port.
    core.sio.eio.cors_allowed_origins = None

    def file_response(path):
        headers = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}
        if path.suffix.lower() == '.html':
            # Report scripts can draw/export plots, but have an opaque origin
            # and cannot access the local instrument-control UI.
            headers['Content-Security-Policy'] = 'sandbox allow-scripts allow-downloads allow-popups'
        return FileResponse(path, headers=headers)

    @app.get('/jobs/{job_id}/files/{relative:path}')
    async def job_file(job_id: str, relative: str):
        try:
            artifact_url(job_id, relative)
            path = await run.io_bound(service.resolve_file, job_id, relative)
        except (ValueError, OSError, KeyError):
            raise HTTPException(status_code=404, detail='Artifact not available') from None
        return file_response(path)

    if report_root is not None:
        published_directory = Path(report_root).resolve()
        published_runs = (published_directory / 'Runs').resolve()
        # Snapshot only the run aliases explicitly published at server startup.
        # Their targets may be immutable report revisions outside Data/Runs.
        published = {entry.name: entry.resolve() for entry in published_runs.iterdir() if entry.is_dir() or entry.is_file()}

        @app.get('/Runs/{relative:path}')
        async def published_run_file(relative: str):
            try:
                path = published_file(published, relative)
            except (ValueError, OSError):
                raise HTTPException(status_code=404, detail='Published report not available') from None
            return file_response(path)

        published_files = {entry.name: entry.resolve() for entry in published_directory.iterdir()
                           if entry.is_file() and entry.suffix.lower() in {'.html', '.csv', '.json', '.svg'}}

        @app.get('/{filename}')
        async def published_legacy_file(filename: str):
            path = published_files.get(filename)
            if path is None or not path.is_file():
                raise HTTPException(status_code=404, detail='Published file not available') from None
            return file_response(path)

    @ui.page('/', response_timeout=30.0)
    async def bench_page():
        ui.add_css(STYLE)
        ui.colors(primary='#15608f', secondary='#168477', accent='#7753a2', positive='#168477')
        client = ui.context.client
        with ui.column().classes('bench-shell gap-4') as loading_frame:
            ui.label('DC–DC Bench').classes('bench-title')
            with ui.row().classes('items-center gap-3'):
                ui.spinner(size='md')
                ui.label('Loading your saved converters and test recipes…').classes('bench-muted')
        # Send a usable loading page before filesystem/thread-pool work. The
        # default three-second NiceGUI response budget is too short on a busy Pi.
        await client.connected()
        if client.is_deleted:
            return
        state = {'preview': None, 'job_id': None, 'loading': False, 'polling': False,
                 'profiles': {}, 'selected': {}, 'fields': {}, 'confirm': {}, 'jobs': [],
                 'generation': 0, 'loads': {}, 'pending_loads': set(), 'preview_busy': False,
                 'active': False, 'active_job_id': None}
        selectors = {}
        status_widgets = {}
        panels = {}
        def initial_profiles():
            catalog = service.list_profiles()
            selected, profiles = {}, {}
            for kind in ('dut', 'bench', 'recipe'):
                options = catalog.get(kind, [])
                if not options:
                    raise ValueError(f'No saved {kind} profiles are available. Check the local workspace.')
                preferred = next((name for name in options if 'mock' in name), options[0]) if kind == 'bench' else options[0]
                selected[kind], profiles[kind] = preferred, service.load_profile(kind, preferred)
            return catalog, selected, profiles

        try:
            initial = await run.io_bound(initial_profiles)
            if client.is_deleted or initial is None:
                return
            catalog, state['selected'], state['profiles'] = initial
        except (ValueError, OSError, RuntimeError) as exc:
            loading_frame.clear()
            with loading_frame:
                ui.label('Could not load the saved bench profiles').classes('bench-section-title')
                ui.label(str(exc)).classes('bench-message bench-warning')
            return
        loading_frame.delete()

        def notify_error(exc):
            if hasattr(exc, 'errors'):
                text = '; '.join('.'.join(map(str, item['loc'])) + ': ' + item['msg'] for item in exc.errors()[:4])
            else:
                text = str(exc)
            ui.notify(text, type='negative', timeout=12000, multi_line=True)

        def invalidate(_event=None):
            if state['loading']:
                return
            state['generation'] += 1
            state['preview'] = None
            for checkbox in state['confirm'].values():
                if hasattr(checkbox, 'set_value'):
                    checkbox.set_value(False if isinstance(checkbox.value, bool) else '')
            if 'start' in status_widgets:
                status_widgets['start'].disable()
            if 'preview_note' in status_widgets:
                status_widgets['preview_note'].set_text('Settings changed. Preview this test again before starting.')

        def input_field(key, label, value, fields, *, number=False, hint=None):
            widget = (ui.number(label, value=value, on_change=invalidate) if number else
                      ui.input(label, value=value or '', on_change=invalidate))
            widget.props('outlined dense')
            if hint:
                widget.props('hint=' + json.dumps(hint))
            fields[key] = widget
            return widget

        def values(kind):
            return {key: widget.value for key, widget in state['fields'][kind].items()}

        async def load_selected(kind, name, token):
            try:
                data = await run.io_bound(service.load_profile, kind, name)
                if client.is_deleted or data is None:
                    return
                if state['loads'].get(kind) != token:
                    return
                invalidate()
                state['selected'][kind] = name
                state['profiles'][kind] = data
                state['loading'] = True
                render_form(kind)
                state['loading'] = False
            except (ValueError, OSError, RuntimeError) as exc:
                if state['loads'].get(kind) == token:
                    state['loading'] = True
                    selectors[kind].set_value(state['selected'][kind])
                    state['loading'] = False
                    notify_error(exc)
            finally:
                if state['loads'].get(kind) == token:
                    state['pending_loads'].discard(kind)
                if not client.is_deleted and 'preview_button' in status_widgets:
                    status_widgets['preview_button'].set_enabled(not state['pending_loads'] and not state['preview_busy'])

        def selected_changed(event, kind):
            if not state['loading']:
                invalidate()
                token = state['generation']
                state['loads'][kind] = token
                state['pending_loads'].add(kind)
                if 'preview_button' in status_widgets:
                    status_widgets['preview_button'].disable()
                return load_selected(kind, event.value, token)

        def render_dut():
            data = state['profiles']['dut']
            fields = state['fields']['dut'] = {}
            with ui.element('div').classes('bench-fields'):
                input_field('profile_id', 'Save converter as', data['profile_id'], fields)
                input_field('model', 'Converter / board model', data['identity']['model'], fields)
                input_field('sample_id', 'Sample ID or board revision', data['identity'].get('sample_id'), fields)
                input_field('input_voltage_min_V', 'Minimum input (V)', data['ratings']['input_voltage_min_V'], fields, number=True)
                input_field('input_voltage_max_V', 'Maximum input (V)', data['ratings']['input_voltage_max_V'], fields, number=True)
                input_field('output_voltage_nominal_V', 'Nominal output (V)', data['ratings']['output_voltage_nominal_V'], fields, number=True)
                input_field('output_current_rated_A', 'Rated output current (A)', data['ratings']['output_current_rated_A'], fields, number=True)
                input_field('output_power_rated_W', 'Rated output power (W)', data['ratings']['output_power_rated_W'], fields, number=True)
            fields['verified_from_sample_label'] = ui.checkbox('I checked these ratings against the sample label',
                value=data['ratings'].get('verified_from_sample_label', False), on_change=invalidate)
            ui.label('Ratings describe the converter. The bench may reach a smaller load range.').classes('bench-muted')

        def render_bench():
            data = state['profiles']['bench']
            fields = state['fields']['bench'] = {}
            label = 'SIMULATED BENCH — no instruments will be opened' if data['mode'] == 'mock' else 'REAL BENCH — Start can enable the connected instruments'
            ui.label(label).classes('bench-message' + (' bench-warning' if data['mode'] == 'real' else ''))
            rows = []
            for role in ('source', 'load'):
                item = data[role]
                rows.append({'role': 'Power supply' if role == 'source' else 'Electronic load',
                    'model': item.get('physical_model') or 'Not configured',
                    'voltage': quantity(item.get('max_voltage_V'), 'V'),
                    'current': quantity(item.get('max_current_A'), 'A'),
                    'power': quantity(item.get('max_power_W'), 'W')})
            ui.table(columns=[{'name': key, 'label': label, 'field': key, 'align': 'left'} for key, label in
                [('role', 'Role'), ('model', 'Configured equipment'), ('voltage', 'Voltage limit'), ('current', 'Current limit'), ('power', 'Power limit')]],
                rows=rows, row_key='role').props('flat dense hide-bottom').classes('w-full')
            ui.label('Identity and output states are checked again by the worker before a real run.').classes('bench-muted')
            ui.label('Measurement boundary: ' + data.get('measurement_boundary', 'Not supplied')).classes('bench-muted')
            with ui.expansion('Bench limits', icon='tune').classes('w-full'):
                with ui.element('div').classes('bench-fields'):
                    input_field('bench_id', 'Save bench as', data['bench_id'], fields)
                    for key, label in [('source_current_limit_A', 'Supply current limit (A)'),
                                       ('dut_input_overvoltage_V', 'Input overvoltage guard (V)'),
                                       ('dut_output_overvoltage_V', 'Output overvoltage guard (V)'),
                                       ('output_overcurrent_A', 'Output current guard (A)')]:
                        input_field(key, label, data.get('protective_controls', {}).get(key), fields, number=True)
                ui.label('Instrument addresses and expected serials come from the local inventory file supplied when starting this UI.').classes('bench-muted')
            for note in data.get('notes', []):
                ui.label(note).classes('bench-muted')

        def render_recipe():
            data = state['profiles']['recipe']
            fields = state['fields']['recipe'] = {}
            tests = {test['id']: test['id'] for test in data['tests']}
            chosen = state.get('test_id') if state.get('test_id') in tests else next(iter(tests))
            state['test_id'] = chosen
            if len(tests) > 1:
                def change_test(event):
                    if event.value == state['test_id']:
                        return
                    invalidate()
                    try:
                        state['profiles']['recipe'] = edited_recipe(data, values('recipe'),
                            dut_id=data['dut_profile_id'], mode=data['execution_mode'], test_id=state['test_id'])
                    except (ValueError, TypeError) as exc:
                        notify_error(exc)
                        event.sender.set_value(state['test_id'])
                        return
                    state['test_id'] = event.value
                    render_form('recipe')
                ui.select(tests, value=chosen, label='Edit test within recipe', on_change=change_test).props('outlined dense')
            test = next(item for item in data['tests'] if item['id'] == chosen)
            with ui.element('div').classes('bench-fields'):
                input_field('recipe_id', 'Save recipe as', data['recipe_id'], fields)
                input_field('voltages', 'Input voltages (V)', ', '.join(f'{v:g}' for v in test['input_voltage_targets_V']), fields,
                            hint='For example: 24, 35.8')
                input_field('currents', 'Output loads (A)', ', '.join(f'{v:g}' for v in test['output_current_targets_A']), fields,
                            hint='For example: 0.1, 0.25, 0.5, 0.75')
                input_field('duration_s', 'Measure each load for (s)', data['acquisition']['duration_s'], fields, number=True)
            ui.label('Each input voltage is tested at each requested load. Efficiency, output voltage and path loss come from the same readings.').classes('bench-muted')
            ui.label('For a real run, the converter starts separately at each input voltage. Outputs are turned OFF between input conditions. A converter that needs a higher startup voltage may stop at a lower input; this procedure does not warm-start it.').classes('bench-muted')
            with ui.expansion('Settling and planning assumptions', icon='tune').classes('w-full'):
                with ui.element('div').classes('bench-fields'):
                    input_field('minimum_dwell_s', 'Minimum settling time (s)', data['settling']['minimum_dwell_s'], fields, number=True)
                    input_field('efficiency_estimate_pct', 'Planning efficiency estimate (%)', data['planning']['efficiency_estimate_fraction'] * 100, fields, number=True)
                    input_field('current_budget_pct', 'Use this share of source current (%)', data['planning']['source_current_budget_fraction'] * 100, fields, number=True)
                ui.label('These are planning assumptions, not measured efficiency or an authorization to exceed instrument limits.').classes('bench-muted')

        def render_form(kind):
            panels[kind].clear()
            with panels[kind]:
                {'dut': render_dut, 'bench': render_bench, 'recipe': render_recipe}[kind]()

        async def save_forms(generation):
            dut = edited_dut(state['profiles']['dut'], values('dut'))
            bench = copy.deepcopy(state['profiles']['bench'])
            bench_fields = values('bench')
            bench['bench_id'] = str(bench_fields.pop('bench_id')).strip()
            bench.setdefault('protective_controls', {})
            for key, value in bench_fields.items():
                bench['protective_controls'][key] = None if value is None else float(value)
            recipe = edited_recipe(state['profiles']['recipe'], values('recipe'), dut_id=dut['profile_id'],
                                   mode=bench['mode'], test_id=state['test_id'])
            saved = {}
            for kind, data in [('dut', dut), ('bench', bench), ('recipe', recipe)]:
                saved[kind] = await run.io_bound(service.save_profile, kind, data)
                if state['generation'] != generation or state['pending_loads']:
                    raise ValueError('Settings changed while saving. Preview again to use your latest settings.')
                state['profiles'][kind] = data
            new_catalog = await run.io_bound(service.list_profiles)
            if state['generation'] != generation or state['pending_loads']:
                raise ValueError('Settings changed while saving. Preview again to use your latest settings.')
            state['loading'] = True
            try:
                for kind, name in saved.items():
                    state['selected'][kind] = name
                    selectors[kind].set_options(new_catalog[kind], value=name)
            finally:
                state['loading'] = False

        async def preview_test():
            if state['pending_loads'] or state['preview_busy']:
                ui.notify('Wait for the selected profiles to finish loading before previewing.', type='info')
                return
            state['preview_busy'] = True
            status_widgets['preview_button'].disable()
            invalidate()
            generation = state['generation']
            try:
                await save_forms(generation)
                selected = state['selected']
                preview = await run.io_bound(service.preview, selected['dut'], selected['bench'], selected['recipe'])
                remember_jobs(await run.io_bound(service.list_jobs))
                if state['generation'] != generation:
                    ui.notify('Settings changed while the preview was being prepared. Preview again to use your latest settings.', type='warning')
                    return
                state['preview'] = preview
                show_preview()
                tabs.set_value('Run')
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                notify_error(exc)
            finally:
                state['preview_busy'] = False
                status_widgets['preview_button'].set_enabled(not state['pending_loads'])
                if 'start' in status_widgets:
                    status_widgets['start'].set_enabled(can_start())

        def can_start():
            preview = state['preview']
            if state['active'] or state['pending_loads'] or state['preview_busy'] or not preview or not preview.get('supported') or preview.get('errors'):
                return False
            if preview.get('mode') == 'mock':
                return True
            if not all(widget.value for widget in state['confirm'].values()):
                return False
            return all(state['confirm'][role + '_serial'].value ==
                       preview.get('inventory', {}).get(role, {}).get('serial') for role in ('source', 'load'))

        def arm_changed(_event=None):
            if 'start' in status_widgets:
                status_widgets['start'].set_enabled(can_start())

        def show_preview():
            panels['preview'].clear()
            status_widgets.pop('start', None)
            status_widgets.pop('preview_note', None)
            state['confirm'] = {}
            preview = state['preview']
            with panels['preview']:
                ui.label('Review this test').classes('bench-section-title')
                if preview is None:
                    status_widgets['preview_note'] = ui.label('Choose your converter and recipe, then preview the limits.').classes('bench-muted')
                    return
                counts = preview.get('counts', {})
                ready = counts.get('executable', 0)
                total = len(preview.get('points', []))
                seconds = preview.get('estimated_seconds')
                duration_label = f'{seconds / 60:.1f} min' if isinstance(seconds, (int, float)) else 'Estimate unavailable'
                with ui.row().classes('w-full gap-3'):
                    for label, value in [('Ready points', f'{ready} / {total}'),
                                         ('Planned acquisition', duration_label),
                                         ('Bench', 'Simulated' if preview['mode'] == 'mock' else 'Real equipment')]:
                        with ui.column().classes('bench-stat gap-1'):
                            ui.label(label).classes('bench-muted')
                            ui.label(value).classes('bench-stat-value')
                plan = preview.get('plan', {})
                controls = plan.get('bench', {}).get('protective_controls', {})
                ui.label('Supply current limit: ' + quantity(controls.get('source_current_limit_A'), 'A') +
                         ' · Output guard: ' + quantity(controls.get('dut_output_overvoltage_V'), 'V') + ' / ' +
                         quantity(controls.get('output_overcurrent_A'), 'A')).classes('bench-message')
                for error in preview.get('errors', []):
                    ui.label(str(error)).classes('bench-message bench-warning')
                for warning in preview.get('warnings', []):
                    ui.label(str(warning)).classes('bench-muted')
                ui.table(columns=[{'name': key, 'label': label, 'field': key, 'align': 'left'} for key, label in
                    [('input_display', 'Input'), ('load_display', 'Requested output load'), ('estimated_display', 'Estimated supply current'),
                     ('status_display', 'Plan'), ('reason', 'Reason')]], rows=plan_rows(preview), row_key='point_id',
                     pagination=15).props('flat dense').classes('w-full')
                ui.label('Excluded points remain in the saved plan. Start runs the supported points; changing any setting requires a fresh preview.').classes('bench-muted')
                if preview['mode'] == 'real':
                    ui.label('Confirm the physical setup').classes('bench-section-title')
                    for key, label in [('wiring_and_polarity', 'Converter input/output wiring and polarity are correct'),
                                       ('channel1', 'The converter input is connected to power-supply channel 1'),
                                       ('protections_reviewed', 'I reviewed these limits and will supervise the run')]:
                        state['confirm'][key] = ui.checkbox(label, on_change=arm_changed)
                    with ui.element('div').classes('bench-fields'):
                        for role, label in [('source', 'Power-supply serial number'), ('load', 'Electronic-load serial number')]:
                            identity = preview.get('inventory', {}).get(role, {})
                            ui.label(label + ' configured: ' + str(identity.get('serial') or 'not configured')).classes('bench-muted')
                            state['confirm'][role + '_serial'] = ui.input('Confirm ' + label.lower(), on_change=arm_changed).props('outlined dense')
                status_widgets['preview_note'] = ui.label('Preview ready. HTML and PDF are generated automatically after acquisition.').classes('bench-muted')
                if state['active']:
                    ui.label('A job is still acquiring or preparing reports. Wait for it to finish before starting another test.').classes('bench-message')
                start_label = 'Start test' if preview['mode'] == 'real' else 'Start simulated test'
                status_widgets['start'] = ui.button(start_label,
                    on_click=start_test, icon='play_arrow').props('unelevated no-caps aria-label=' + json.dumps(start_label))
                status_widgets['start'].set_enabled(can_start())

        async def start_test():
            preview = state['preview']
            if not can_start():
                return
            status_widgets['start'].disable()
            try:
                confirmation = {key: widget.value for key, widget in state['confirm'].items()}
                confirmation['plan_hash'] = preview['plan_hash']
                job = await run.io_bound(service.start, preview['plan_hash'], confirmation=confirmation,
                                         notes=status_widgets['notes'].value or '')
                if client.is_deleted or job is None:
                    return
                state['job_id'] = job['job_id']
                state['preview'] = None
                panels['preview'].clear()
                status_widgets.pop('start', None)
                status_widgets.pop('preview_note', None)
                await poll()
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)
                status_widgets['start'].set_enabled(can_start())

        async def stop_test(job_id):
            try:
                await run.io_bound(service.cancel, job_id)
                ui.notify('Stop requested. Wait for the worker to verify both outputs OFF.', type='warning')
                await poll()
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)

        def report_links(snapshot):
            if not snapshot.get('report_dir'):
                return
            artifacts = snapshot.get('report_artifacts') or {}
            with ui.row().classes('gap-5'):
                for filename, label in [('report.html', 'Open interactive HTML'), ('report.pdf', 'Open PDF'),
                                        ('report_model.json', 'Report data JSON')]:
                    artifact_kind = 'model' if filename == 'report_model.json' else filename.rsplit('.', 1)[1]
                    if artifacts.get(artifact_kind, {}).get('status') != 'success':
                        continue
                    ui.link(label, artifact_url(snapshot['job_id'], 'report/' + filename), new_tab=True).classes('bench-artifact')

        async def retry_report(job_id):
            try:
                await run.io_bound(service.retry_report, job_id)
                state['job_id'] = job_id
                tabs.set_value('Run')
                ui.notify('Rebuilding reports from the saved measurements. No acquisition will run.', type='info')
                await poll()
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)

        def show_status(snapshot):
            panels['status'].clear()
            with panels['status']:
                ui.label(state_label(snapshot)).classes('bench-section-title')
                ui.label('Simulated test · no real instruments' if snapshot.get('mode') == 'mock'
                         else 'Real equipment test').classes('bench-message')
                if snapshot.get('state') == 'reporting':
                    ui.label('The measurements are saved. Preparing the interactive plots and PDF can take several minutes on a Raspberry Pi. You can reconnect later; this job continues independently.').classes('bench-message')
                ui.label('Run ' + str(snapshot.get('run_id') or snapshot['job_id'])).classes('bench-muted')
                progress = snapshot.get('progress') or {}
                complete, total = progress.get('completed', 0), progress.get('total', 0)
                ui.linear_progress(value=complete / total if total else 0, show_value=False).props('rounded size=10px').classes('w-full')
                ui.label(f'{complete} / {total} load points accepted').classes('bench-muted')
                if progress.get('current') and snapshot.get('state') == 'acquiring':
                    ui.label('Measuring this condition').classes('bench-muted')
                if progress.get('requested_input_V') is not None:
                    ui.label('Requested input: ' + quantity(progress['requested_input_V'], 'V') +
                             ' · Requested load: ' + quantity(progress.get('requested_output_A'), 'A')).classes('bench-muted')
                latest = snapshot.get('latest') or {}
                with ui.row().classes('w-full gap-3'):
                    for key, label, unit in [('Vin_V', 'Measured input', 'V'), ('Iin_A', 'Supply current', 'A'),
                                              ('Vout_V', 'Measured output', 'V'), ('Iout_A', 'Load current', 'A')]:
                        with ui.column().classes('bench-stat gap-1'):
                            ui.label(label).classes('bench-muted')
                            ui.label(quantity(latest.get(key), unit)).classes('bench-stat-value')
                for key, label in [('phase', 'Stage'), ('elapsed_s', 'Elapsed seconds'), ('latest_age_s', 'Last measurement age (s)'),
                                   ('source_mode', 'Supply mode')]:
                    value = snapshot.get(key, latest.get(key))
                    if value is not None:
                        if key.endswith('_s') and isinstance(value, (int, float)):
                            value = f'{value:.0f}'
                        ui.label(f'{label}: {value}').classes('bench-muted')
                if snapshot.get('latest_kind') == 'startup':
                    ui.label('Latest readings are from startup; they are not a qualified efficiency result.').classes('bench-muted')
                elif latest:
                    ui.label('Latest raw readings. Qualified averages and efficiency are available in the final report.').classes('bench-muted')
                if snapshot.get('error'):
                    ui.label(str(snapshot['error'])).classes('bench-message bench-warning')
                ui.label(shutdown_label(snapshot)).classes('bench-message')
                active = snapshot.get('state') in ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested')
                if active:
                    stop = ui.button('Stop test safely', on_click=lambda: stop_test(snapshot['job_id']),
                                     icon='stop', color='negative').props('outline no-caps aria-label="Stop test safely"')
                    if snapshot.get('cancel_requested'):
                        stop.disable()
                report_links(snapshot)
                artifacts = snapshot.get('report_artifacts') or {}
                terminal = snapshot.get('state') in ('completed', 'aborted', 'failed', 'cancelled')
                failed_formats = [name.upper() for name in ('html', 'pdf')
                                  if terminal and snapshot.get('run_dir') and artifacts.get(name, {}).get('status') != 'success']
                if terminal and not snapshot.get('run_dir'):
                    ui.label('No measurements were acquired for this job.').classes('bench-muted')
                if failed_formats:
                    ui.label('Report generation needs attention: ' + ', '.join(failed_formats) + '. Saved measurements are preserved.').classes('bench-message bench-warning')
                if snapshot.get('run_dir') and terminal and (
                        failed_formats or not snapshot.get('report_dir')):
                    ui.button('Retry report generation', on_click=lambda: retry_report(snapshot['job_id']),
                              icon='refresh').props('outline no-caps aria-label="Retry report generation"')
                events = snapshot.get('events') or []
                if events:
                    with ui.expansion('Recent events', icon='list').classes('w-full'):
                        for event in events[-12:]:
                            ui.label(str(event)).classes('bench-muted')

        async def select_job(job_id):
            state['job_id'] = job_id
            panels['status'].clear()
            with panels['status']:
                ui.label('Loading the selected run…').classes('bench-muted')
            tabs.set_value('Run')
            await poll()

        def remember_jobs(jobs):
            state['jobs'] = jobs
            active = next((job for job in jobs if job.get('state') in ('queued', 'acquiring', 'reporting')), None)
            state['active'] = bool(active)
            state['active_job_id'] = active['job_id'] if active else None

        async def refresh_reports():
            jobs = await run.io_bound(service.list_jobs)
            if client.is_deleted or jobs is None:
                return
            remember_jobs(jobs)
            panels['reports'].clear()
            with panels['reports']:
                if not jobs:
                    ui.label('Your completed and interrupted runs will appear here.').classes('bench-muted')
                for job in jobs[:30]:
                    with ui.card().classes('bench-card gap-3'):
                        ui.label(job_title(job)).classes('bench-section-title')
                        ui.label('Simulated data' if job.get('mode') == 'mock' else 'Real bench').classes('bench-muted')
                        ui.label(state_label(job)).classes('bench-muted')
                        ui.button('View run', on_click=lambda _, job_id=job['job_id']: select_job(job_id)).props('flat no-caps')
                        report_links(job)

        async def poll():
            if state['polling'] or not state['job_id']:
                return
            state['polling'] = True
            job_id = state['job_id']
            try:
                snapshot = await run.io_bound(service.status, job_id)
                if client.is_deleted or snapshot is None or state['job_id'] != job_id:
                    return
                if snapshot.get('state') in ('queued', 'acquiring', 'reporting'):
                    state['active'], state['active_job_id'] = True, job_id
                elif state['active_job_id'] and state['active_job_id'] != job_id:
                    busy = await run.io_bound(service.status, state['active_job_id'])
                    if state['job_id'] != job_id:
                        return
                    state['active'] = busy.get('state') in ('queued', 'acquiring', 'reporting')
                    if not state['active']:
                        state['active_job_id'] = None
                else:
                    state['active'], state['active_job_id'] = False, None
                if 'start' in status_widgets:
                    status_widgets['start'].set_enabled(can_start())
                show_status(snapshot)
            except (ValueError, OSError, RuntimeError) as exc:
                if state['job_id'] != job_id:
                    return
                panels['status'].clear()
                with panels['status']:
                    ui.label('Could not refresh run status: ' + str(exc)).classes('bench-message bench-warning')
                    ui.label('The worker owns the instruments independently. Refreshing this page does not restart it.').classes('bench-muted')
            finally:
                state['polling'] = False

        with ui.column().classes('bench-shell gap-5'):
            ui.label('DC–DC Bench').classes('bench-title')
            ui.label('Choose a converter, preview the limits, then measure efficiency and generate an interactive report.').classes('bench-subtitle')
            with ui.tabs().classes('bench-tabs w-full') as tabs:
                for name, icon in [('Bench', 'electrical_services'), ('DUT and recipe', 'tune'), ('Run', 'play_circle'), ('Reports', 'description')]:
                    ui.tab(name, icon=icon).props('aria-label=' + json.dumps(name))
            with ui.tab_panels(tabs, value='DUT and recipe').classes('w-full'):
                with ui.tab_panel('Bench'):
                    with ui.card().classes('bench-card gap-4'):
                        ui.label('Bench configuration').classes('bench-section-title')
                        selectors['bench'] = ui.select(catalog['bench'], value=state['selected']['bench'], label='Saved bench',
                            on_change=lambda e: selected_changed(e, 'bench')).props('outlined dense')
                        panels['bench'] = ui.column().classes('w-full gap-4')
                        render_form('bench')
                with ui.tab_panel('DUT and recipe'):
                    for kind, heading in [('dut', '1. Choose the converter'), ('recipe', '2. Choose input voltages and loads')]:
                        with ui.card().classes('bench-card gap-4 mb-5'):
                            ui.label(heading).classes('bench-section-title')
                            selectors[kind] = ui.select(catalog[kind], value=state['selected'][kind], label='Saved ' + ('converter' if kind == 'dut' else 'recipe'),
                                on_change=lambda e, kind=kind: selected_changed(e, kind)).props('outlined dense')
                            panels[kind] = ui.column().classes('w-full gap-4')
                            render_form(kind)
                    with ui.card().classes('bench-card gap-4'):
                        status_widgets['notes'] = ui.textarea('Test notes / setup description', placeholder='Sample revision, wiring, mounting or observations',
                                                             on_change=invalidate).props('outlined autogrow')
                        ui.label('Your profiles are saved locally when you preview. No output is enabled by a preview.').classes('bench-muted')
                        status_widgets['preview_button'] = ui.button('Preview test and limits', on_click=preview_test,
                                                                      icon='fact_check').props('unelevated no-caps aria-label="Preview test and limits"')
                with ui.tab_panel('Run'):
                    with ui.card().classes('bench-card gap-4 mb-5'):
                        panels['preview'] = ui.column().classes('w-full gap-4')
                        show_preview()
                    with ui.card().classes('bench-card gap-4'):
                        panels['status'] = ui.column().classes('w-full gap-4')
                        with panels['status']:
                            ui.label('No run selected').classes('bench-section-title')
                            ui.label('Start a previewed test or reopen a saved run from Reports.').classes('bench-muted')
                with ui.tab_panel('Reports'):
                    ui.button('Refresh saved runs', on_click=refresh_reports, icon='refresh').props('flat no-caps aria-label="Refresh saved runs"')
                    panels['reports'] = ui.column().classes('w-full gap-4')
            ui.label('Local bench control · Data stays in your workspace · Closing this tab does not restart or cancel acquisition.').classes('bench-muted')
        await refresh_reports()
        active = next((job for job in state['jobs'] if job.get('state') in
                       ('queued', 'starting', 'running', 'acquiring', 'stopping', 'cancel_requested', 'analyzing', 'rendering', 'reporting')), None)
        if active:
            state['job_id'] = active['job_id']
            tabs.set_value('Run')
            await poll()
        ui.timer(2.0, poll)

    ui.run(host=host, port=port, reload=False, show=False, title='DC–DC Bench',
           reconnect_timeout=30.0, fastapi_docs=False)
