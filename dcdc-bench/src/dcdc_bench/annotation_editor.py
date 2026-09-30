"""Local sensor-placement editor page for finished runs.

Importing this module does not import NiceGUI. ``register_annotation_editor``
adds the ``/annotations`` page to the already loopback-bound, Host-checked
local server. Uploads pass the attachment validator, markers are normalized
image coordinates bound to the original image hash, and Save asks JobService
for a report-only revision. Nothing on this page can start acquisition,
open an instrument, or rewrite finalized evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from .annotations import (AnnotationError, annotation_document, load_annotations, marker_overlay_svg,
                          nearest_marker, new_sensor_id, normalized_point, nudge_marker)
from .attachments import (BYTE_LIMITS, IMAGE_TYPES, MEDIA_TYPES, AssetHashMismatch, AssetNotFound, AssetStore,
                          AttachmentRejected)
from .ui_models import artifact_url, job_title, state_label

ACTIVE = ("queued", "acquiring", "reporting")
UPLOAD_LIMIT = max(BYTE_LIMITS.values())
UPLOAD_CHUNK = 256 * 1024
EDITOR_STYLE = '''
.bench-editor-image{width:100%;max-width:900px;border:1px solid #dce5eb;border-radius:8px;overflow:hidden}
.bench-editor-image img{max-width:100%;height:auto;display:block}
.bench-marker-row{display:grid;grid-template-columns:2.2rem minmax(0,1fr) minmax(0,2fr) 9rem auto auto;gap:8px;align-items:center;width:100%}
.bench-marker-row .q-field{min-width:0}
@media(max-width:760px){.bench-marker-row{grid-template-columns:2rem minmax(0,1fr) minmax(0,1fr)}}
'''
HELP = ('Click the photograph where a sensor is attached to add a marker; drag a marker to move it. '
        'Keyboard: Tab to a marker\'s Select button and press Enter, then use the arrow keys to nudge it '
        '(Shift for larger steps) and Delete to remove it. Positions are stored as normalized image '
        'coordinates bound to this exact photograph\'s hash, so any later resize keeps them on the same spot.')


def eligible_jobs(jobs: list[dict]) -> list[dict]:
    """Finished jobs with preserved acquisition; active or evidence-less jobs are excluded."""
    return [job for job in jobs if job.get('run_dir') and job.get('state') not in ACTIVE]


def image_assets(store: AssetStore) -> list[dict]:
    """Stored photographs that can carry markers: image types with known pixel dimensions."""
    return [asset for asset in store.assets() if asset.get('media_type') in IMAGE_TYPES
            and isinstance(asset.get('width'), int) and isinstance(asset.get('height'), int)]


def asset_url(job_id: str, asset: dict) -> str:
    return artifact_url(job_id, f"run/attachments/originals/{asset['sha256']}.{MEDIA_TYPES[asset['media_type']]}")


def existing_annotations(run_dir: Path) -> tuple[dict, dict] | None:
    """Markers from the newest report revision that has any; None when no revision does."""
    reports = Path(run_dir) / 'reports'
    if not reports.is_dir():
        return None
    for report_dir in sorted(reports.glob('r*'), reverse=True):
        loaded = load_annotations(report_dir, run_dir)
        if loaded is not None:
            return loaded
    return None


def asset_summary(asset: dict) -> str:
    revision = asset.get('added_in_revision')
    origin = f'documentation revision {revision}' if revision is not None else 'the acquisition manifest'
    return (f"{asset.get('original_name', 'original')} · {asset['width']}×{asset['height']} px · "
            f"SHA-256 {asset['sha256'][:16]}… · listed in {origin}")


async def read_upload(file, limit: int | None = None) -> bytes:
    """Read an upload without ever holding more than ``limit`` bytes.

    The browser-side ``max-file-size`` is advisory only. The reported size is
    checked first when the upload object offers one; then the body is read in
    chunks and the read aborts as soon as the limit is passed, so an oversized
    body is refused before it is ever assembled in memory.
    """
    limit = UPLOAD_LIMIT if limit is None else int(limit)
    size = getattr(file, 'size', None)
    if callable(size):
        try:
            size = size()
        except (OSError, ValueError, TypeError):
            size = None
    if isinstance(size, int) and not isinstance(size, bool) and size > limit:
        raise AttachmentRejected('too_large', f'Upload of {size} bytes exceeds the {limit} byte attachment limit')
    iterate = getattr(file, 'iterate', None)
    if callable(iterate):
        chunks, total = [], 0
        async for chunk in iterate(chunk_size=UPLOAD_CHUNK):
            total += len(chunk)
            if total > limit:
                raise AttachmentRejected('too_large', f'Upload exceeds the {limit} byte attachment limit')
            chunks.append(chunk)
        return b''.join(chunks)
    data = await file.read()
    if len(data) > limit:
        raise AttachmentRejected('too_large', f'Upload of {len(data)} bytes exceeds the {limit} byte attachment limit')
    return data


def register_annotation_editor(ui, run, service, style: str) -> None:
    @ui.page('/annotations', response_timeout=30.0)
    async def annotation_page():
        ui.add_css(style)
        ui.add_css(EDITOR_STYLE)
        ui.colors(primary='#15608f', secondary='#168477', accent='#7753a2', positive='#168477')
        client = ui.context.client
        with ui.column().classes('bench-shell gap-4') as loading:
            ui.label('Sensor placement editor').classes('bench-title')
            with ui.row().classes('items-center gap-3'):
                ui.spinner(size='md')
                ui.label('Loading finished runs…').classes('bench-muted')
        await client.connected()
        if client.is_deleted:
            return
        try:
            jobs = await run.io_bound(lambda: eligible_jobs(service.list_jobs()))
        except (ValueError, OSError, RuntimeError) as exc:
            loading.clear()
            with loading:
                ui.label('Could not list finished runs: ' + str(exc)).classes('bench-message bench-warning')
            return
        if client.is_deleted or jobs is None:
            return
        loading.delete()
        state = {'job_id': None, 'run_dir': None, 'assets': [], 'asset': None, 'markers': [],
                 'selected': None, 'dragging': False, 'busy': False}
        widgets: dict = {}
        coordinate_labels: list = []

        def notify_error(exc):
            ui.notify(str(exc), type='negative', timeout=12000, multi_line=True)

        def overlay():
            asset = state['asset']
            if asset is None:
                return ''
            return marker_overlay_svg(state['markers'], asset['width'], asset['height'], state['selected'])

        def refresh_image():
            if 'image' in widgets:
                widgets['image'].set_content(overlay())

        def refresh_coordinates():
            for index, label in enumerate(coordinate_labels):
                if index < len(state['markers']):
                    marker = state['markers'][index]
                    label.set_text(f"x {marker['x_norm']:.4f} · y {marker['y_norm']:.4f}")

        def set_field(index, key, value):
            if 0 <= index < len(state['markers']):
                state['markers'][index][key] = str(value)
                if key == 'sensor_id':
                    refresh_image()

        def refresh_markers():
            panel = widgets['markers']
            panel.clear()
            coordinate_labels.clear()
            with panel:
                if state['asset'] is None:
                    ui.label('Choose a photograph to start placing markers.').classes('bench-muted')
                    return
                if not state['markers']:
                    ui.label('No markers yet. Click the photograph where a sensor is attached.').classes('bench-muted')
                    return
                for index, marker in enumerate(state['markers']):
                    with ui.element('div').classes('bench-marker-row'):
                        ui.label(str(index + 1)).classes('bench-stat-value')
                        ui.input('Sensor ID', value=marker['sensor_id'],
                                 on_change=lambda e, i=index: set_field(i, 'sensor_id', e.value)).props('outlined dense')
                        ui.input('Location note', value=marker['label'],
                                 on_change=lambda e, i=index: set_field(i, 'label', e.value)).props('outlined dense')
                        coordinate_labels.append(ui.label(f"x {marker['x_norm']:.4f} · y {marker['y_norm']:.4f}").classes('bench-muted'))
                        select = ui.button('Select', on_click=lambda _, i=index: select_marker(i)).props(
                            'flat no-caps aria-label=' + json.dumps(f'Select marker {index + 1}'))
                        if index == state['selected']:
                            select.props('color=primary')
                        ui.button('Delete', icon='delete', on_click=lambda _, i=index: delete_marker(i)).props(
                            'flat no-caps aria-label=' + json.dumps(f'Delete marker {index + 1}'))

        def select_marker(index):
            state['selected'] = index if index is not None and 0 <= index < len(state['markers']) else None
            refresh_image()
            refresh_markers()

        def delete_marker(index):
            if 0 <= index < len(state['markers']):
                del state['markers'][index]
                state['selected'] = None
                refresh_image()
                refresh_markers()

        def handle_mouse(e):
            asset = state['asset']
            if asset is None:
                return
            try:
                x, y = normalized_point(e.image_x, e.image_y, asset['width'], asset['height'])
            except AnnotationError as exc:
                notify_error(exc)
                return
            if e.type == 'mousedown':
                hit = nearest_marker(state['markers'], x, y)
                if hit is None:
                    state['markers'].append({'sensor_id': new_sensor_id(state['markers']), 'x_norm': round(x, 6),
                                             'y_norm': round(y, 6), 'label': ''})
                    hit = len(state['markers']) - 1
                state['selected'], state['dragging'] = hit, True
                refresh_image()
                refresh_markers()
            elif e.type == 'mousemove' and state['dragging'] and state['selected'] is not None and e.buttons & 1:
                marker = state['markers'][state['selected']]
                marker['x_norm'], marker['y_norm'] = round(x, 6), round(y, 6)
                refresh_image()
                refresh_coordinates()
            elif e.type == 'mouseup' and state['dragging']:
                state['dragging'] = False
                refresh_coordinates()

        def handle_key(e):
            if not e.action.keydown or state['selected'] is None or state['asset'] is None:
                return
            index = state['selected']
            if e.key.name in ('Delete', 'Backspace'):
                delete_marker(index)
                return
            moved = nudge_marker(state['markers'][index], e.key.name, large=e.modifiers.shift)
            if moved != state['markers'][index]:
                state['markers'][index] = moved
                refresh_image()
                refresh_coordinates()

        def show_asset():
            panel = widgets['image_panel']
            panel.clear()
            widgets.pop('image', None)
            asset = state['asset']
            with panel:
                if asset is None:
                    ui.label('Upload or choose a photograph to place markers.').classes('bench-muted')
                else:
                    ui.label(asset_summary(asset)).classes('bench-muted')
                    widgets['image'] = ui.interactive_image(asset_url(state['job_id'], asset), content=overlay(),
                        events=['mousedown', 'mousemove', 'mouseup'], on_mouse=handle_mouse, cross=True).classes('bench-editor-image')
            refresh_markers()
            widgets['save'].set_enabled(asset is not None and not state['busy'])

        def choose_asset(e):
            asset = next((item for item in state['assets'] if item['sha256'] == e.value), None)
            previous = state['asset']
            if previous is not None and asset is not None and asset['sha256'] != previous['sha256'] and state['markers']:
                # Markers belong to one exact image; another photograph starts its own set.
                state['markers'], state['selected'] = [], None
                ui.notify('Markers are bound to one photograph. Starting a new set for the selected image.', type='info')
            state['asset'] = asset
            show_asset()

        def set_asset_options(select_sha=None):
            options = {asset['sha256']: f"{asset.get('original_name', 'original')} · {asset['width']}×{asset['height']} px"
                       for asset in state['assets']}
            widgets['asset_select'].set_options(options, value=select_sha if select_sha in options else None)

        async def reload_assets(select_sha=None):
            run_dir = state['run_dir']
            assets = await run.io_bound(lambda: image_assets(AssetStore(Path(run_dir))))
            if client.is_deleted or assets is None or state['run_dir'] != run_dir:
                return
            state['assets'] = assets
            set_asset_options(select_sha)

        async def load_job(job_id):
            state.update(job_id=job_id, run_dir=None, assets=[], asset=None, markers=[], selected=None, dragging=False)
            widgets['notice'].set_text('')
            widgets['notice'].classes(remove='bench-warning')
            try:
                snapshot = await run.io_bound(service.status, job_id)
                run_dir = snapshot.get('run_dir') if snapshot else None
                if not run_dir:
                    raise ValueError('This job has no preserved acquisition.')

                def read():
                    store = AssetStore(Path(run_dir))
                    try:
                        existing = existing_annotations(Path(run_dir))
                    except (AssetHashMismatch, AssetNotFound, AnnotationError, ValueError) as exc:
                        existing = exc
                    return image_assets(store), existing
                assets, existing = await run.io_bound(read)
            except (ValueError, OSError, RuntimeError, KeyError) as exc:
                notify_error(exc)
                return
            if client.is_deleted or state['job_id'] != job_id:
                return
            state['run_dir'], state['assets'] = run_dir, assets
            widgets['job_label'].set_text(job_title(snapshot) + ' · ' + state_label(snapshot))
            if isinstance(existing, Exception):
                widgets['notice'].set_text('Saved markers were not loaded because their photograph could not be verified: ' + str(existing))
                widgets['notice'].classes(add='bench-warning')
                set_asset_options()
            elif existing is not None:
                annotations, asset = existing
                state['markers'] = [dict(marker) for marker in annotations['markers']]
                widgets['notice'].set_text(f"Loaded {len(state['markers'])} saved marker(s) from the latest report revision; "
                                           'saving creates a further revision.')
                set_asset_options(asset['sha256'])
            else:
                widgets['notice'].set_text('No saved sensor markers for this run yet.')
                set_asset_options()
            if state['asset'] is None:
                show_asset()

        async def handle_upload(e):
            if state['job_id'] is None or state['run_dir'] is None:
                ui.notify('Choose a finished run before uploading.', type='warning')
                return
            try:
                data = await read_upload(e.file)
                entry = await run.io_bound(service.add_attachment, state['job_id'], e.file.name, data,
                                           caption=widgets['caption'].value or '')
                if client.is_deleted or entry is None:
                    return
                # Keep the photograph being annotated; a new upload is offered, not forced.
                current = state['asset']['sha256'] if state['asset'] is not None else entry['sha256']
                await reload_assets(select_sha=current)
                if entry.get('media_type') not in IMAGE_TYPES or not isinstance(entry.get('width'), int):
                    ui.notify(f"Stored {entry['original_name']} as a document; only PNG, JPEG or sized SVG images carry markers.",
                              type='warning', timeout=10000)
                else:
                    ui.notify(f"Stored {entry['original_name']} ({entry['byte_size']} bytes) in documentation revision "
                              f"{entry.get('added_in_revision')}. Acquisition files are unchanged.", type='positive', timeout=8000)
            except AttachmentRejected as exc:
                ui.notify(f'Rejected: {exc.detail} ({exc.reason})', type='negative', timeout=12000, multi_line=True)
            except (ValueError, OSError, RuntimeError, LookupError) as exc:
                notify_error(exc)

        async def save():
            if state['asset'] is None or state['busy']:
                return
            state['busy'] = True
            widgets['save'].disable()
            try:
                document = annotation_document(state['asset']['sha256'], state['markers'])
                result = await run.io_bound(service.retry_report, state['job_id'], document)
                if client.is_deleted or result is None:
                    return
                widgets['notice'].classes(remove='bench-warning')
                widgets['notice'].set_text(f"Saved {len(document['markers'])} marker(s) bound to image "
                                           f"{document['image_asset_sha256'][:16]}…; job {result['job_id']} is rebuilding "
                                           'its report as a new revision.')
                ui.notify('New report revision queued. The report worker renders HTML and PDF from the saved '
                          'measurements; no acquisition runs.', type='positive', timeout=10000)
            except (AnnotationError, ValueError, OSError, RuntimeError, LookupError) as exc:
                notify_error(exc)
            finally:
                state['busy'] = False
                if not client.is_deleted:
                    widgets['save'].set_enabled(state['asset'] is not None)

        with ui.column().classes('bench-shell gap-5'):
            ui.label('Sensor placement editor').classes('bench-title')
            ui.label('Attach photographs to a finished run and mark where each sensor sits. Edits are saved as a new '
                     'report revision; the recorded measurements and their integrity hashes stay untouched.').classes('bench-subtitle')
            with ui.card().classes('bench-card gap-4'):
                ui.label('1. Choose a finished run').classes('bench-section-title')
                if not jobs:
                    ui.label('No finished runs with preserved measurements are available yet.').classes('bench-muted')
                ui.select({job['job_id']: job_title(job) + ' · ' + state_label(job) for job in jobs},
                          label='Finished run', on_change=lambda e: load_job(e.value)).props('outlined dense')
                widgets['job_label'] = ui.label('').classes('bench-muted')
                widgets['notice'] = ui.label('').classes('bench-message')
            with ui.card().classes('bench-card gap-4'):
                ui.label('2. Photograph').classes('bench-section-title')
                widgets['caption'] = ui.input('Caption for the next upload', placeholder='Case top view, sensors attached with thermal tape').props('outlined dense')
                ui.upload(label='Add a photograph (PNG, JPEG or SVG; PDF pages are stored as documents)', auto_upload=True,
                          max_file_size=max(BYTE_LIMITS.values()), on_upload=handle_upload).props(
                    'accept=".png,.jpg,.jpeg,.svg,.pdf" flat bordered').classes('w-full')
                ui.label('Every file is checked by content: type, size, dimensions and SVG/PDF active content. '
                         'Originals are stored by hash and never modified.').classes('bench-muted')
                widgets['asset_select'] = ui.select({}, label='Photograph for markers', on_change=choose_asset).props('outlined dense')
                widgets['image_panel'] = ui.column().classes('w-full gap-2')
            with ui.card().classes('bench-card gap-4'):
                ui.label('3. Sensor markers').classes('bench-section-title')
                ui.label(HELP).classes('bench-muted')
                widgets['markers'] = ui.column().classes('w-full gap-2')
                widgets['save'] = ui.button('Save as new report revision', icon='save', on_click=save).props(
                    'unelevated no-caps aria-label="Save as new report revision"')
                widgets['save'].disable()
                ui.label('Saving queues a report-only rebuild; no output is enabled and no instrument is opened.').classes('bench-muted')
            ui.link('Back to the bench', '/').classes('bench-artifact')
        ui.keyboard(on_key=handle_key, ignore=['input', 'select', 'textarea'])
        with widgets['image_panel']:
            ui.label('Upload or choose a photograph to place markers.').classes('bench-muted')
        with widgets['markers']:
            ui.label('Choose a photograph to start placing markers.').classes('bench-muted')
