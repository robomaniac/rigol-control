"""Local NiceGUI bench workflow. Hardware ownership stays in JobService workers.

One page, three questions (converter, simulated or real bench, test), then
Preview and Start. Importing this module does not import NiceGUI, start a
server or open equipment.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import sys
from pathlib import Path

from .standard_recipes import STANDARDS_GROUP, build_recipe, clause_rows, default_system, standard_cards
from .ui_models import (BENCH_NAMES, DEFAULT_CATEGORY, DELETE_PROMPTS, PLAN_STATUS_LEGEND, REAL_CAN, REAL_CANNOT,
                        SIMULATION_CAN, SIMULATION_CANNOT, SIMULATION_SEQUENCE, SIMULATION_TIME_ESTIMATE, START_LABELS, simulation_time_text,
                        SYNTHETIC_UNCERTAINTY_NOTE, WORKING_STATES, activity_text, artifact_url, bench_equipment, bench_job,
                        bench_title, card_meta, deferred_text, dequeued, dut_approved, dut_subtitle, duration_text,
                        edited_dut, edited_recipe, elapsed_text, envelope_rows, event_text, friendly_error, grouped_recipes,
                        job_actions, limits_rows, limits_summary, local_time_text, plan_rows, quantity, recipe_grid,
                        recipe_title, report_became_ready, report_link_rows, report_rows, saved_runs_key, sequence_step,
                        shutdown_label, skip_reasons, state_label, summary_text, time_legend)


STYLE = '''
body{background:#fff;color:#183047;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.bench-shell{max-width:1000px;margin:0 auto;width:100%;padding:0 16px 140px}
.bench-header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.97);border-bottom:1px solid #dce4e9;padding:10px 16px;width:100%}
.bench-header-inner{max-width:1000px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}
.bench-title{font-size:23px;font-weight:700;line-height:1.2;letter-spacing:-.03em}
.bench-subtitle{color:#516677;font-size:13.5px}
.bench-status-area{display:flex;align-items:center;gap:12px;margin-left:auto;flex-wrap:wrap}
.bench-idle{border:1px solid #dce4e9;border-radius:999px;padding:5px 13px;font-size:13.5px;font-weight:600;color:#516677;background:#f3f7fa}
.bench-activity{background:#e6f1fb;border:1px solid #b7d3ea;border-radius:999px;padding:5px 13px;cursor:pointer;max-width:100%}
.bench-activity-text{font-weight:650;color:#174c6e;font-size:13.5px}
.bench-stop{display:flex;gap:6px;align-items:center;margin-left:auto}
.bench-summary{background:#f3f7fa;border:1px solid #dce4e9;border-radius:6px;padding:9px 13px;margin:16px 0 0;font-size:14.5px;width:100%;overflow-wrap:anywhere}
.bench-summary-key{color:#516677;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em;margin-right:6px}
.bench-h2{font-size:19px;font-weight:650;letter-spacing:-.02em;border-bottom:1px solid #dce4e9;padding-bottom:6px;margin:28px 0 13px;display:flex;align-items:center;gap:9px;width:100%}
.bench-num{display:inline-flex;width:26px;height:26px;border-radius:50%;background:#15608f;color:#fff;font-size:14px;align-items:center;justify-content:center;font-weight:700;flex-shrink:0}
.bench-group{font-size:13px;color:#516677;text-transform:uppercase;letter-spacing:.04em;font-weight:600;margin:10px 0 4px;width:100%}
.bench-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:11px;width:100%}
.bench-card-item{position:relative;border:2px solid #dce4e9;border-radius:8px;background:#fff;min-height:104px;display:flex;flex-direction:column}
.bench-card-item:hover{border-color:#abc0cf}
.bench-card-item.selected{border-color:#168477;background:#edf7f4;box-shadow:0 0 0 1px #168477 inset}
.bench-card-item.greyed{background:#f6f8fa;border-color:#e6edf1}
/* The whole card is one real <button>: Enter and Space select it, nothing interactive is nested inside it. */
.bench-card-select{all:unset;box-sizing:border-box;display:flex;flex-direction:column;gap:3px;width:100%;flex:1;padding:13px 40px 14px 14px;cursor:pointer;text-align:left;color:inherit;font:inherit;border-radius:6px}
.bench-card-select:focus-visible{outline:3px solid #15608f;outline-offset:-3px}
.bench-card-title{font-weight:650;font-size:16px;line-height:1.3;display:flex;align-items:center;gap:7px}
.bench-card-grid{font-size:14px}.bench-card-meta{color:#516677;font-size:13px}
.bench-card-reason{color:#8a2727;font-size:13px}.bench-card-note{color:#5a6f7e;font-size:13px}
.bench-card-check{display:inline-flex;width:20px;height:20px;border-radius:50%;background:#168477;color:#fff;align-items:center;justify-content:center;flex-shrink:0}
/* One "⋯" menu per card replaces four nested 10 px buttons: 32 px target, outside the select button. */
.bench-card-menu{position:absolute;top:6px;right:6px;min-width:32px;min-height:32px;color:#15608f}
.bench-link{font-size:12.5px;color:#15608f}.bench-link-danger{color:#8a2727}
.bench-menu-danger{color:#8a2727}
.bench-badge{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12.5px;font-weight:600;white-space:nowrap;background:#eef2f5;color:#516677}
.bench-badge-standard{background:#e6f1fb;color:#174c6e}.bench-badge-ok{background:#edf7f4;color:#174b42}
.bench-badge-partial{background:#fff7e9;color:#785018}.bench-badge-real{background:#fff1dc;color:#785018}
.bench-badge-grey{background:#eef2f5;color:#516677}
.bench-checklist{border:1px solid #dce4e9;border-radius:8px;padding:12px 14px;background:#f8fafb;width:100%}
.bench-clause-row{display:grid;grid-template-columns:minmax(0,1.4fr) auto minmax(0,1fr);gap:4px 12px;align-items:center;padding:6px 0;border-bottom:1px solid #e6edf1;width:100%}
.bench-clause-row.untickable .q-checkbox__inner{opacity:.45}
.bench-clause-note{color:#5a6f7e;font-size:12.5px;grid-column:1 / -1;margin-top:-2px}
.bench-checklist-footer{font-weight:600;color:#183047}
.bench-add{all:unset;box-sizing:border-box;border:2px dashed #dce4e9;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#15608f;font-weight:600;font:inherit;font-weight:600;padding:13px;text-align:center;cursor:pointer;min-height:104px;width:100%}
.bench-add:hover{background:#f3f7fa}.bench-add:focus-visible{outline:3px solid #15608f;outline-offset:2px}
.bench-tiles{display:grid;grid-template-columns:1fr 1fr;gap:13px;align-items:stretch;width:100%}
.bench-tile{border:2px solid #dce4e9;border-radius:8px;background:#fff;cursor:pointer;padding:14px;display:flex;flex-direction:column;gap:6px}
.bench-tile:hover{border-color:#abc0cf}.bench-tile.selected{border-color:#168477;background:#edf7f4}
.bench-tile:focus-visible{outline:3px solid #15608f;outline-offset:2px}
.bench-tile.real.selected{border-color:#ac7427;background:#fff7e9}
.bench-tile-title{font-weight:650;font-size:16.5px;line-height:1.3}.bench-tile-sub{color:#516677;font-size:13.5px}
.bench-real-details{border-top:1px dashed #d9c39a;padding-top:11px;margin-top:6px;font-size:13.5px;width:100%}
.bench-sim-details{border-top:1px dashed #b7d3ea;padding-top:11px;margin-top:6px;font-size:13.5px;width:100%}
/* "What this bench can and cannot do": always visible, plain text at AA contrast, no dimming. */
.bench-cando{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 14px;width:100%;font-size:13px;line-height:1.35}
.bench-cando-col{display:flex;flex-direction:column;gap:4px;min-width:0}
.bench-cando-head{font-weight:650;color:#183047;font-size:12.5px;text-transform:uppercase;letter-spacing:.04em}
.bench-cando-can{color:#174b42}.bench-cando-cannot{color:#5a2e2e}
.bench-lbl{color:#516677;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.bench-pills{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.bench-pill{border:1px solid #abc0cf;background:#fff;border-radius:999px;padding:3px 11px;font-size:13px;color:#174c6e;cursor:pointer}
.bench-pill:hover{background:#e8f0f6}.bench-pill.on{background:#15608f;border-color:#15608f;font-weight:600}
.bench-pill.on,.bench-pill.on .q-btn__content{color:#fff}
.bench-limits{display:grid;grid-template-columns:56% 44%;border:1px solid #dce4e9;background:#fff;font-size:13.5px;width:100%}
.bench-limits>*{padding:5px 10px;border-bottom:1px solid #dce4e9}.bench-limits>*:nth-last-child(-n+2){border-bottom:0}
.bench-limit-key{color:#516677}.bench-limit-value{font-weight:600;font-variant-numeric:tabular-nums}
.bench-approve-ok{color:#174b42;font-weight:600}.bench-approve-missing{color:#8a2727;font-weight:600}
.bench-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;width:100%}
.bench-fields>*{min-width:0}
.bench-editor{border:1px solid #dce4e9;border-radius:8px;padding:14px;background:#f8fafb;width:100%}
.bench-message{padding:10px 14px;border-radius:7px;background:#edf5f7;width:100%;overflow-wrap:anywhere}
.bench-warning{background:#fff3df;color:#77511d}.bench-muted{color:#5a6f7e;font-size:13px}
.bench-danger{color:#8a2727}
.bench-panel{border:1px solid #dce4e9;border-radius:8px;padding:16px;background:#fff;width:100%}
.bench-panel.stale .bench-stat,.bench-panel.stale .bench-reasons{color:#5a6f7e}
.bench-plan,.bench-confirm,.bench-run-section{scroll-margin-top:84px}
.bench-stale{background:#fff7e9;color:#785018;border:1px solid #e3cfa9;border-radius:6px;padding:7px 11px;font-weight:600;font-size:14px;width:100%}
.bench-sequence{display:flex;flex-direction:column;gap:3px;width:100%;font-size:13.5px}
.bench-sequence-step{display:flex;gap:8px;align-items:baseline;color:#5a6f7e}
.bench-sequence-step.current{color:#183047;font-weight:650}.bench-sequence-step.done{color:#174b42}
.bench-sequence-num{display:inline-flex;width:20px;height:20px;border-radius:50%;border:1px solid #abc0cf;font-size:12px;align-items:center;justify-content:center;flex-shrink:0}
.bench-sequence-step.current .bench-sequence-num{background:#15608f;border-color:#15608f;color:#fff}
.bench-legend{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:2px 10px;font-size:13px;color:#5a6f7e;width:100%}
.bench-legend code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:#183047}
.bench-bar-hint{font-size:12.5px;color:#5a6f7e;flex-basis:100%}
.bench-stats{display:flex;flex-wrap:wrap;gap:12px 28px;width:100%}
.bench-stat{display:flex;flex-direction:column;gap:2px;min-width:120px}
.bench-stat-key{color:#516677;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.bench-stat-value{font-size:21px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.3}
.bench-stat-value.small{font-size:16px}
.bench-k-label{font-weight:650;font-size:14.5px;margin-top:6px}
.bench-reasons{font-size:14px;margin-left:8px}
.bench-confirm{border:2px solid #ac7427;background:#fff7e9;border-radius:8px;padding:16px;width:100%}
.bench-run{border:1px solid #dce4e9;border-radius:8px;padding:16px;width:100%}
.bench-stat-tile{background:#f3f7f9;border-radius:8px;padding:12px;min-width:140px;flex:1}
.bench-reports{width:100%}
/* The time column sizes to its content so a local time with its zone never overprints the run name. */
.bench-report-row{display:grid;grid-template-columns:max-content minmax(0,1.4fr) max-content max-content minmax(220px,1fr);gap:8px 12px;align-items:start;padding:8px 6px;border-bottom:1px solid #dce4e9;font-size:13.5px;width:100%}
.bench-report-head{color:#29495d;font-weight:600;background:#f3f7fa}
.bench-report-when{white-space:nowrap;font-variant-numeric:tabular-nums}
.bench-report-row .bench-badge{justify-self:start}
.bench-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.bench-artifact{font-weight:600;color:#15608f}
.bench-bar{position:fixed;left:0;right:0;bottom:0;z-index:30;background:#fff;border-top:1px solid #dce4e9;box-shadow:0 -4px 16px rgba(24,48,71,.08);padding:10px 16px}
.bench-bar-inner{max-width:1000px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}
.bench-bar-summary{font-size:13.5px;color:#516677;flex:1 1 240px;min-width:0;overflow-wrap:anywhere}
.bench-bar-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bench-locked{pointer-events:none;opacity:.55}
.bench-dialog{min-width:min(92vw,420px)}
.bench-shell .q-field{width:100%}.bench-shell .q-checkbox__label{overflow-wrap:anywhere}
.bench-shell .q-table td{white-space:normal;overflow-wrap:anywhere}
.bench-shell .q-table td.nowrap,.bench-shell .q-table th.nowrap{white-space:nowrap}
/* Shared with the /annotations editor page (annotation_editor.py builds its own layout on this sheet). */
.bench-card{background:#fff;border:1px solid #dce5eb;border-radius:8px;box-shadow:none;padding:22px;width:100%}
.bench-section-title{font-size:20px;font-weight:650;margin-bottom:6px}
.bench-glossary{max-width:1000px;margin:0 auto;padding:16px}
.bench-glossary table{border-collapse:collapse;width:100%;font-size:14px}.bench-glossary th,.bench-glossary td{border-bottom:1px solid #dce4e9;padding:6px 8px;text-align:left;vertical-align:top}
@media(max-width:650px){.bench-shell{padding:0 12px 170px}.bench-tiles{grid-template-columns:1fr}.bench-cards{grid-template-columns:1fr}
.bench-fields{grid-template-columns:1fr}.bench-cando{grid-template-columns:1fr}
.bench-header-inner{flex-wrap:nowrap;gap:8px}.bench-subtitle{display:none}.bench-status-area{width:auto;margin-left:auto;justify-content:flex-end}
.bench-summary-key{white-space:nowrap}
.bench-clause-row{grid-template-columns:minmax(0,1fr)}.bench-clause-row>*{min-width:0}
.bench-plan,.bench-confirm,.bench-run-section{scroll-margin-top:72px}
.bench-report-row{grid-template-columns:minmax(0,1fr);gap:4px}.bench-report-head{display:none}.bench-bar-actions{width:100%}
.bench-bar-actions .q-btn{flex:1}.bench-stat-value{font-size:17px}.bench-title{font-size:18px}}
'''


RASTER_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
_TOO_LARGE = b'Request body exceeds the upload limit\n'
# The glossary the page footer links: one document, kept with the source (an editable install has it).
GLOSSARY_PATH = Path(__file__).resolve().parents[2] / 'docs' / 'glossary.md'


def file_headers(path: Path, relative: str | None = None) -> dict[str, str]:
    """Response headers for a served artifact.

    Sniffing is off and nothing is cached. The report HTML keeps its scripted
    sandbox; every other document is confined to an opaque origin with a
    script-less ``sandbox``, so an SVG or PDF opened directly can never act in
    the instrument-control origin. Uploaded attachments are downloads unless
    they are raster images (``inline``); ``<img>`` loads ignore both headers,
    so the editor keeps working.
    """
    headers = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'}
    suffix = Path(path).suffix.lower()
    if suffix == '.html':
        # Report scripts can draw/export plots, but have an opaque origin
        # and cannot access the local instrument-control UI.
        # Printing is a sandboxed modal action: the report's Print current
        # view button needs allow-modals. Keep allow-same-origin absent so
        # reports still cannot act in the instrument-control origin.
        headers['Content-Security-Policy'] = 'sandbox allow-scripts allow-downloads allow-popups allow-modals'
        return headers
    headers['Content-Security-Policy'] = 'sandbox'
    if relative is not None and '/attachments/' in '/' + relative.replace('\\', '/'):
        disposition = 'inline' if suffix in RASTER_SUFFIXES else 'attachment'
        headers['Content-Disposition'] = f'{disposition}; filename="{Path(path).name}"'
    return headers


class RequestBodyLimit:
    """Pure-ASGI guard: refuse or cut off HTTP request bodies above ``limit`` bytes.

    Runs before anything downstream (NiceGUI's upload spool included) can
    buffer a body: a declared Content-Length above the limit is answered with
    413 without reading it, and a chunked body is disconnected once it has
    delivered more than the limit.
    """

    def __init__(self, app, limit: int):
        self.app, self.limit = app, int(limit)

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)
        declared = next((value for name, value in scope.get('headers') or () if name == b'content-length'), None)
        if declared is not None:
            try:
                too_large = int(declared) > self.limit
            except ValueError:
                too_large = True
            if too_large:
                await send({'type': 'http.response.start', 'status': 413,
                            'headers': [(b'content-type', b'text/plain; charset=utf-8'),
                                        (b'content-length', str(len(_TOO_LARGE)).encode())]})
                await send({'type': 'http.response.body', 'body': _TOO_LARGE})
                return
        received = {'bytes': 0}

        async def limited_receive():
            message = await receive()
            if message.get('type') == 'http.request':
                received['bytes'] += len(message.get('body', b''))
                if received['bytes'] > self.limit:
                    return {'type': 'http.disconnect'}
            return message
        await self.app(scope, limited_receive, send)


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


def unique_name(base: str, taken) -> str:
    """'<base>-copy', then '<base>-copy-2', … not in ``taken``."""
    candidate, index = base + '-copy', 2
    while candidate in taken:
        candidate, index = f'{base}-copy-{index}', index + 1
    return candidate


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
    # Server-side upload ceiling: the largest attachment plus multipart framing.
    from .attachments import BYTE_LIMITS
    app.add_middleware(RequestBodyLimit, limit=max(BYTE_LIMITS.values()) + 1024 * 1024)
    # NiceGUI's generic default permits every WebSocket origin. Bench control
    # uses Engine.IO's same-origin policy; SSH forwards retain their Host port.
    core.sio.eio.cors_allowed_origins = None

    dispatcher = {'busy': False}

    async def dispatch_reports():
        """One app-level dispatcher, not per client or per request: a queued report
        starts only when no job is active and the memory gate passes."""
        if dispatcher['busy']:
            return
        dispatcher['busy'] = True
        try:
            await run.io_bound(service.dispatch_reports)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f'Report dispatcher: {exc}', file=sys.stderr, flush=True)
        finally:
            dispatcher['busy'] = False

    app.on_startup(dispatch_reports)
    app.timer(2.0, dispatch_reports)

    def file_response(path, relative=None):
        return FileResponse(path, headers=file_headers(path, relative))

    @app.get('/jobs/{job_id}/files/{relative:path}')
    async def job_file(job_id: str, relative: str):
        try:
            artifact_url(job_id, relative)
            path = await run.io_bound(service.resolve_file, job_id, relative)
        except (ValueError, OSError, KeyError):
            raise HTTPException(status_code=404, detail='Artifact not available') from None
        return file_response(path, relative)

    # Photo/sensor-marker documentation editor: report-only revisions, no acquisition path.
    # Registered before the published-file routes: FastAPI matches in registration
    # order and the legacy ``/{filename}`` catch-all below would otherwise shadow
    # every single-segment page such as ``/annotations``.
    from .annotation_editor import register_annotation_editor
    register_annotation_editor(ui, run, service, STYLE)

    @ui.page('/glossary', response_timeout=30.0)
    async def glossary_page():
        """docs/glossary.md rendered from the checkout; the page footer links it, so the page and the document share one source.
        Registered before the published-file routes for the same reason as /annotations."""
        ui.add_css(STYLE)
        with ui.column().classes('bench-glossary gap-3'):
            ui.link('← Back to the bench', '/').classes('bench-artifact')
            if GLOSSARY_PATH.is_file():
                ui.markdown(GLOSSARY_PATH.read_text(encoding='utf-8'))
            else:
                ui.label('Glossary').classes('bench-title')
                ui.label('The glossary file dcdc-bench/docs/glossary.md is not part of this installation. '
                         'It is kept with the source at docs/glossary.md.').classes('bench-message bench-warning')

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
        ui.colors(primary='#15608f', secondary='#168477', accent='#7753a2', positive='#168477', negative='#8a2727')
        client = ui.context.client
        with ui.column().classes('bench-shell gap-4') as loading_frame:
            ui.label('DC–DC Bench').classes('bench-title')
            with ui.row().classes('items-center gap-3'):
                ui.spinner(size='md')
                ui.label('Loading your saved converters, benches and tests…').classes('bench-muted')
        # Send a usable loading page before filesystem/thread-pool work. The
        # default three-second NiceGUI response budget is too short on a busy Pi.
        await client.connected()
        if client.is_deleted:
            return

        state = {'catalog': {'dut': {}, 'bench': {}, 'recipe': {}}, 'inventory': {},
                 'dut': None, 'mode': 'mock', 'bench': {'mock': None, 'real': None}, 'recipe': None,
                 'feasibility': {}, 'preview': None, 'stale_note': None, 'preview_busy': False, 'generation': 0,
                 'job_id': None, 'polling': False, 'active': False, 'active_job_id': None, 'jobs': [],
                 # Single-shot actions: Start while the service answers, the jobs whose stop this tab
                 # already confirmed, and the jobs whose report rebuild this tab already asked for.
                 'start_busy': False, 'stop_requested': set(), 'regenerate_busy': set(),
                 # job_id -> saved_runs_key of the last snapshot this page showed; drives the
                 # Reports auto-refresh and the "Report ready" notice from the same poll.
                 'seen': {},
                 'events_open': {},
                 # Real-start confirmation widgets; emptied whenever the panel is cleared so a
                 # later invalidation never touches deleted inputs.
                 'confirm': {}, 'stop_armed': False, 'stop_key': None, 'editor': None,
                 # The automotive-standards checklist: expanded or not, the 12 V / 24 V system class chosen
                 # for the current converter (None: the converter's remembered class, else 12 V) and the
                 # ticked ISO 16750-2 clause numbers.
                 'standards': {'open': False, 'system': None, 'ticked': set()}}
        panels = {}
        widgets = {}

        def load_everything():
            catalog = service.catalog()
            return catalog, service.inventory_models(), service.list_jobs()

        try:
            loaded = await run.io_bound(load_everything)
            if client.is_deleted or loaded is None:
                return
            state['catalog'], state['inventory'], jobs = loaded
        except (ValueError, OSError, RuntimeError) as exc:
            loading_frame.clear()
            with loading_frame:
                ui.label('Could not load the saved bench profiles').classes('bench-h2')
                ui.label(str(exc)).classes('bench-message bench-warning')
            return
        loading_frame.delete()

        # --- selection helpers ------------------------------------------------------------------

        def notify(message, **kwargs):
            # A save/delete handler can outlive its editor or dialog slot after
            # refresh. Notifications belong to the stable page client, never
            # to the now-deleted event sender's parent.
            if not client.is_deleted:
                with client:
                    ui.notify(message, **kwargs)

        def notify_error(exc):
            notify(friendly_error(exc), type='negative', timeout=12000, multi_line=True)

        def benches_of(mode):
            return {name: bench for name, bench in state['catalog']['bench'].items() if bench.get('mode') == mode}

        def fix_selection():
            """Keep every selection pointing at a saved profile; prefer the seeded names on first load."""
            catalog = state['catalog']
            if state['dut'] not in catalog['dut']:
                state['dut'] = next(iter(catalog['dut']), None)
            for mode, preferred in (('mock', 'mock-dp821-envelope'), ('real', 'rigol-local-limited')):
                names = list(benches_of(mode))
                if state['bench'][mode] not in names:
                    state['bench'][mode] = preferred if preferred in names else (names[0] if names else None)
            if state['mode'] == 'real' and state['bench']['real'] is None:
                state['mode'] = 'mock'
            if state['recipe'] not in catalog['recipe']:
                state['recipe'] = next(iter(catalog['recipe']), None)

        def bench_name():
            return state['bench'][state['mode']]

        def current(kind):
            name = {'dut': state['dut'], 'bench': bench_name(), 'recipe': state['recipe']}[kind]
            return state['catalog'][kind].get(name) if name else None

        def compute_feasibility(dut, bench, recipes):
            result = {}
            for name in recipes:
                try:
                    result[name] = service.feasibility(dut, bench, name)
                except (ValueError, OSError, RuntimeError) as exc:
                    result[name] = {'runnable': False, 'reason': str(exc).split('; ')[0], 'executable': 0,
                                    'estimated_seconds': None, 'mode': None}
            return result

        async def reload(*, recompute=True):
            """Re-read the saved profiles (after a save/rename/delete) and re-plan every test card."""
            generation = state['generation']
            catalog = await run.io_bound(service.catalog)
            if client.is_deleted or catalog is None or generation != state['generation']:
                return False
            state['catalog'] = catalog
            fix_selection()
            if recompute:
                await refresh_feasibility()
            return generation == state['generation']

        async def refresh_feasibility():
            dut, bench, recipes = state['dut'], bench_name(), list(state['catalog']['recipe'])
            generation = state['generation']
            if not dut or not bench:
                state['feasibility'] = {}
                return
            result = await run.io_bound(compute_feasibility, dut, bench, recipes)
            if (client.is_deleted or result is None or generation != state['generation']
                    or (dut, bench, recipes) != (state['dut'], bench_name(), list(state['catalog']['recipe']))):
                return
            state['feasibility'] = result

        def changed(note='Settings changed — Preview again before starting.'):
            """Any change to the three selections or a saved profile makes the plan stale and disables Start."""
            state['generation'] += 1
            state['preview'] = None
            state['stale_note'] = note if panels.get('plan') is not None and panels['plan'].visible else None
            state['confirm'] = {}
            if 'confirm' in panels:
                panels['confirm'].clear()
                panels['confirm'].set_visibility(False)
            render_plan()
            render_summary()
            render_bar()

        async def select(kind, name):
            if state['active'] or state['start_busy']:
                return
            if kind == 'dut':
                if state['dut'] == name:
                    return
                state['dut'] = name
                state['standards'].update(system=None, ticked=set())  # the checklist follows the converter's ratings and class
                changed()  # Invalidate the old plan before the first asynchronous operation.
                generation = state['generation']
                await refresh_feasibility()  # the cards' runnability depends on the converter's ratings
                if client.is_deleted or generation != state['generation']:
                    return
                render_converters()
            else:
                if state['recipe'] == name:
                    return
                state['recipe'] = name
                changed()
            render_tests()

        async def select_mode(mode):
            if state['active'] or state['start_busy']:
                return
            if mode == 'real' and state['bench']['real'] is None:
                notify('Save a real bench preset first (the seeded "24 V converter tests" preset was removed).', type='warning')
                return
            if state['mode'] == mode:
                return
            state['mode'] = mode
            changed()
            generation = state['generation']
            await refresh_feasibility()
            if client.is_deleted or generation != state['generation']:
                return
            render_bench()
            render_tests()

        async def select_bench(mode, name):
            if state['active'] or state['start_busy']:
                return
            if state['bench'][mode] == name and state['mode'] == mode:
                return
            state['bench'][mode] = name
            state['mode'] = mode
            changed()
            generation = state['generation']
            await refresh_feasibility()
            if client.is_deleted or generation != state['generation']:
                return
            render_bench()
            render_tests()

        # --- dialogs ------------------------------------------------------------------------------

        def dismiss(box):
            box.close()
            box.delete()

        def dialog(title, build):
            """A modal at the page root (not inside a card, which re-renders); removed when dismissed."""
            with panels['dialogs']:
                with ui.dialog().props('persistent') as box, ui.card().classes('bench-dialog gap-3'):
                    ui.label(title).classes('bench-h2').style('margin:0 0 4px;border:0;padding:0')
                    build(box)
            box.open()
            return box

        def confirm_dialog(title, body, ok_label, on_ok):
            def build(box):
                ui.label(body).classes('bench-muted').style('font-size:14.5px;color:#183047')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Cancel', on_click=lambda: dismiss(box)).props('outline no-caps')

                    async def confirmed():
                        dismiss(box)
                        await on_ok()
                    ui.button(ok_label, on_click=confirmed, color='negative').props('unelevated no-caps')
            dialog(title, build)

        def prompt_dialog(title, value, on_ok, *, label='New name'):
            def build(box):
                field = ui.input(label, value=value).props('outlined dense autofocus')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Cancel', on_click=lambda: dismiss(box)).props('outline no-caps')

                    async def saved():
                        text = str(field.value or '').strip()
                        if not text:
                            notify('Enter a name.', type='warning')
                            return
                        dismiss(box)
                        await on_ok(text)
                    ui.button('Save', on_click=saved).props('unelevated no-caps')
            dialog(title, build)

        # --- profile actions ----------------------------------------------------------------------

        async def save_and_select(kind, data, *, note=None, overwrite=True, replaces=None, select_saved=True):
            """Validate + save a profile, re-read the catalog and select the saved name.

            ``overwrite=False`` for a new profile: the service refuses an existing file
            name instead of replacing it. ``replaces`` for Edit with a changed file
            name: the old file goes away with the save (no second card).
            """
            if state['active'] or state['start_busy']:
                raise ValueError('Wait for the current job to finish before changing saved profiles.')
            changed()
            generation = state['generation']
            name = await run.io_bound(lambda: service.save_profile(kind, data, overwrite=overwrite, replaces=replaces))
            if client.is_deleted or name is None:
                return None
            if not await reload(recompute=False) or generation != state['generation']:
                return name
            if kind == 'dut':
                state['dut'] = name
            elif kind == 'recipe':
                state['recipe'] = name
            elif kind == 'bench' and select_saved:
                state['bench'][data['mode']] = name
                state['mode'] = data['mode']
            await refresh_feasibility()
            if client.is_deleted or generation != state['generation']:
                return name
            render_converters()
            render_bench()
            render_tests()
            changed()
            if note:
                notify(note, type='positive')
            return name

        async def delete_profile(kind, name):
            async def do_delete():
                if state['active'] or state['start_busy']:
                    notify('Wait for the current job to finish before changing saved profiles.', type='warning')
                    return
                changed()
                generation = state['generation']
                try:
                    await run.io_bound(service.delete_profile, kind, name)
                except (ValueError, OSError) as exc:
                    notify_error(exc)
                    return
                if state['editor'] and state['editor'][0] in (kind, 'limits' if kind == 'bench' else kind) and state['editor'][1] == name:
                    close_editor()  # Save in a still-open editor would recreate the deleted file
                if not await reload() or generation != state['generation']:
                    return
                render_converters()
                render_bench()
                render_tests()
                changed()
                notify(f'Deleted “{name}”. Past runs keep their own copy.', type='info')
            confirm_dialog(DELETE_PROMPTS[kind], f'“{display_name(kind, name)}” will disappear from this list.', 'Delete', do_delete)

        def display_name(kind, name):
            data = state['catalog'][kind].get(name) or {}
            if kind == 'dut':
                return (data.get('identity') or {}).get('model') or name
            return recipe_title(data) if kind == 'recipe' else bench_title(data)

        async def rename_profile(kind, name):
            """The plain name shown on the card (converter model, test or preset title); the saved identifier is unchanged."""
            async def do_rename(text):
                data = copy.deepcopy(state['catalog'][kind][name])
                if kind == 'dut':
                    data['identity']['model'] = text
                else:
                    data['title'] = text
                try:
                    await save_and_select(kind, data, note='Renamed.')
                except (ValueError, OSError) as exc:
                    notify_error(exc)
            prompt_dialog({'dut': 'Rename converter', 'recipe': 'Rename test', 'bench': 'Rename bench preset'}[kind],
                          display_name(kind, name), do_rename)

        async def duplicate_recipe(name):
            data = copy.deepcopy(state['catalog']['recipe'][name])
            data['recipe_id'] = unique_name(name, state['catalog']['recipe'])
            data['title'] = recipe_title(data) + ' (copy)'
            data['execution_mode'] = None
            try:
                await save_and_select('recipe', data, note='Duplicated — rename it, then edit the grid.')
            except (ValueError, OSError) as exc:
                notify_error(exc)

        # --- inline editors (the existing form fields) --------------------------------------------

        def input_field(key, label, value, fields, *, number=False, hint=None):
            widget = ui.number(label, value=value).props('outlined dense') if number else ui.input(label, value=value or '').props('outlined dense')
            if hint:
                widget.props('hint=' + json.dumps(hint))
            fields[key] = widget
            return widget

        def values(fields):
            return {key: widget.value for key, widget in fields.items()}

        def close_editor():
            state['editor'] = None
            for key in ('editor_dut', 'editor_recipe', 'editor_limits'):
                if key in panels:
                    panels[key].clear()
                    panels[key].set_visibility(False)

        def offer_free_name(container, kind, field, taken, open_existing):
            """Inside an editor, after the service refused to overwrite ``taken``: the two ways out.

            Rename (a free file name is filled in for the operator to accept or change)
            or open the existing profile with Edit. Nothing is written until Save.
            """
            word = {'dut': 'converter', 'recipe': 'test'}[kind]
            container.clear()
            container.set_visibility(True)
            with container:
                ui.label(f'A {word} file named “{taken}” already exists. Nothing was overwritten.').classes('bench-message bench-warning')
                with ui.row().classes('gap-2 items-center'):
                    def suggest():
                        field.set_value(unique_name(taken, state['catalog'][kind]))
                        container.set_visibility(False)
                    ui.button('Use a free file name', on_click=suggest, icon='drive_file_rename_outline').props('outline no-caps')
                    ui.button(f'Open the existing {word}', on_click=lambda: open_existing(taken), icon='edit').props('outline no-caps')

        def open_dut_editor(name=None):
            """Add (name None) or edit a converter with the existing DUT form; saved approvals live here too."""
            if state['active'] or state['start_busy']:
                return
            close_editor()
            state['editor'] = ('dut', name)
            template = state['catalog']['dut'].get(name) if name else None
            if template is None:
                template = copy.deepcopy(next(iter(state['catalog']['dut'].values()), None)) or {
                    'profile_id': '', 'identity': {'model': ''}, 'ratings': {'origin': 'user_supplied', 'input_voltage_min_V': 9.,
                    'input_voltage_max_V': 36., 'output_voltage_nominal_V': 12., 'output_current_rated_A': 1., 'output_power_rated_W': 12.},
                    'execution_approval': {}}
                template['profile_id'], template['identity']['model'] = '', ''
                template['identity']['sample_id'] = None
                template['ratings']['verified_from_sample_label'] = False
                template['execution_approval'] = {'real_hardware_enabled': False, 'wiring_and_polarity_confirmed': False, 'protective_policy_id': None}
            data = copy.deepcopy(template)
            fields = {}
            panel = panels['editor_dut']
            panel.set_visibility(True)
            with panel:
                ui.label('Edit converter' if name else 'Add a converter').classes('bench-k-label')
                with ui.element('div').classes('bench-fields'):
                    input_field('profile_id', 'Save converter as (file name, letters/digits/-_.)', data['profile_id'], fields)
                    input_field('model', 'Converter / board model', data['identity']['model'], fields)
                    input_field('sample_id', 'Sample ID or board revision', data['identity'].get('sample_id'), fields)
                    input_field('input_voltage_min_V', 'Minimum input (V)', data['ratings']['input_voltage_min_V'], fields, number=True)
                    input_field('input_voltage_max_V', 'Maximum input (V)', data['ratings']['input_voltage_max_V'], fields, number=True)
                    input_field('output_voltage_nominal_V', 'Nominal output (V)', data['ratings']['output_voltage_nominal_V'], fields, number=True)
                    input_field('output_current_rated_A', 'Rated output current (A)', data['ratings']['output_current_rated_A'], fields, number=True)
                    input_field('output_power_rated_W', 'Rated output power (W)', data['ratings']['output_power_rated_W'], fields, number=True)
                fields['verified_from_sample_label'] = ui.checkbox('I checked these ratings against the sample label',
                    value=bool(data['ratings'].get('verified_from_sample_label', False)))
                ui.label('Ratings describe the converter. The bench may reach a smaller load range.').classes('bench-muted')
                approval = data.get('execution_approval', {})
                with ui.expansion('Real-bench approval for this converter', icon='verified_user').classes('w-full'):
                    fields['real_hardware_enabled'] = ui.checkbox('This converter is approved for the real bench',
                        value=bool(approval.get('real_hardware_enabled', False)))
                    fields['wiring_and_polarity_confirmed'] = ui.checkbox('The wiring plan and polarity for this converter were reviewed',
                        value=bool(approval.get('wiring_and_polarity_confirmed', False)))
                    ui.label('Saved approvals are required before a real preview is supported. Each Start still needs a fresh wiring, CH1, limits and serial confirmation.').classes('bench-muted')
                conflict = ui.column().classes('w-full gap-2')
                conflict.set_visibility(False)
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Cancel', on_click=close_editor).props('outline no-caps')

                    async def save():
                        try:
                            edited = edited_dut(data, values(fields))
                            # A new converter never overwrites a saved one; an edited converter whose
                            # file name changed replaces its old file instead of leaving two cards.
                            await save_and_select('dut', edited, note='Converter saved.', overwrite=name is not None,
                                                  replaces=name if name and edited['profile_id'] != name else None)
                            close_editor()
                        except (ValueError, TypeError, OSError) as exc:
                            if 'already exists' in str(exc):
                                offer_free_name(conflict, 'dut', fields['profile_id'], str(fields['profile_id'].value or '').strip(),
                                                open_dut_editor)
                            notify_error(exc)
                    ui.button('Save converter', on_click=save, icon='save').props('unelevated no-caps')

        def open_recipe_editor(name=None):
            """New test (name None) or edit a test with the existing recipe fields plus its card text."""
            if state['active'] or state['start_busy']:
                return
            close_editor()
            state['editor'] = ('recipe', name)
            template = state['catalog']['recipe'].get(name) if name else None
            new = template is None
            if new:
                source = state['catalog']['recipe'].get(state['recipe']) or next(iter(state['catalog']['recipe'].values()), None)
                if source is None:
                    notify('No saved test to start from; the seeded quick sweep is restored when the page restarts.', type='warning')
                    return
                template = copy.deepcopy(source)
                template.update(recipe_id='', title='', description=None, standard_clause=None, execution_mode=None)
                template['category'] = template.get('category') or DEFAULT_CATEGORY
            data = copy.deepcopy(template)
            tests = [test['id'] for test in data['tests']]
            chosen = {'test_id': tests[0]}
            fields = {}
            panel = panels['editor_recipe']
            panel.set_visibility(True)

            def grid_fields(container):
                container.clear()
                test = next(item for item in data['tests'] if item['id'] == chosen['test_id'])
                with container:
                    with ui.element('div').classes('bench-fields'):
                        input_field('voltages', 'Input voltages (V)', ', '.join(f'{v:g}' for v in test['input_voltage_targets_V']), fields,
                                    hint='For example: 24, 35.8')
                        input_field('currents', 'Output loads (A)', ', '.join(f'{v:g}' for v in test['output_current_targets_A']), fields,
                                    hint='For example: 0, 0.1, 0.25, 0.5')
                        input_field('duration_s', 'Measure each load for (s)', data['acquisition']['duration_s'], fields, number=True)
                        input_field('minimum_dwell_s', 'Minimum settling time (s)', data['settling']['minimum_dwell_s'], fields, number=True)
            with panel:
                ui.label('Edit test' if name else 'New test').classes('bench-k-label')
                with ui.element('div').classes('bench-fields'):
                    input_field('recipe_id', 'Save test as (file name, letters/digits/-_.)', data['recipe_id'], fields)
                    input_field('title', 'Plain name shown on the card', data.get('title') or '', fields,
                                hint='Blank: the grid is used, e.g. "24 V × 0 / 0.1 A"')
                    input_field('category', 'Category', data.get('category') or DEFAULT_CATEGORY, fields,
                                hint='Cards are grouped by category; a standard\'s name groups its tests')
                    input_field('standard_clause', 'Standard clause (optional badge)', data.get('standard_clause') or '', fields,
                                hint='For example: MIL-STD-704F §5.1.2')
                fields['description'] = ui.textarea('Description (optional)', value=data.get('description') or '').props('outlined autogrow dense')
                if len(tests) > 1:
                    def change_test(event):
                        if event.value == chosen['test_id']:
                            return
                        try:
                            data.update(edited_recipe(data, values(fields), dut_id=data['dut_profile_id'], test_id=chosen['test_id']))
                        except (ValueError, TypeError) as exc:
                            notify_error(exc)
                            event.sender.set_value(chosen['test_id'])
                            return
                        chosen['test_id'] = event.value
                        grid_fields(grid)
                    ui.select({test: test for test in tests}, value=tests[0], label='Edit test within this recipe',
                              on_change=change_test).props('outlined dense')
                grid = ui.column().classes('w-full gap-3')
                grid_fields(grid)
                ui.label('Each input voltage is tested at each requested load. Simulated vs real is not part of a test; question 2 decides.').classes('bench-muted')
                with ui.expansion('Planning assumptions', icon='tune').classes('w-full'):
                    with ui.element('div').classes('bench-fields'):
                        input_field('efficiency_estimate_pct', 'Planning efficiency estimate (%)', data['planning']['efficiency_estimate_fraction'] * 100, fields, number=True)
                        input_field('current_budget_pct', 'Use this share of source current (%)', data['planning']['source_current_budget_fraction'] * 100, fields, number=True)
                    ui.label('Planning assumptions, not measured efficiency or an authorization to exceed instrument limits.').classes('bench-muted')
                conflict = ui.column().classes('w-full gap-2')
                conflict.set_visibility(False)
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Cancel', on_click=close_editor).props('outline no-caps')

                    async def save():
                        try:
                            dut_id = state['dut'] or data['dut_profile_id']
                            edited = edited_recipe(data, values(fields), dut_id=dut_id, test_id=chosen['test_id'])
                            await save_and_select('recipe', edited, note='Test saved.', overwrite=name is not None,
                                                  replaces=name if name and edited['recipe_id'] != name else None)
                            close_editor()
                        except (ValueError, TypeError, OSError) as exc:
                            if 'already exists' in str(exc):
                                offer_free_name(conflict, 'recipe', fields['recipe_id'], str(fields['recipe_id'].value or '').strip(),
                                                open_recipe_editor)
                            notify_error(exc)
                    ui.button('Save test', on_click=save, icon='save').props('unelevated no-caps')

        def open_limits_editor(name):
            """Change the four protective limits of a real bench preset; saving clears its approval."""
            if state['active'] or state['start_busy']:
                return
            close_editor()
            state['editor'] = ('limits', name)
            data = copy.deepcopy(state['catalog']['bench'][name])
            fields = {}
            panel = panels['editor_limits']
            panel.set_visibility(True)
            with panel:
                ui.label('Change limits — ' + bench_title(data)).classes('bench-k-label')
                ui.label('Changing a limit clears its approval; tick "I reviewed these limits" again afterwards.').classes('bench-muted')
                controls = data.get('protective_controls') or {}
                with ui.element('div').classes('bench-fields'):
                    for key, label in [('source_current_limit_A', 'Supply current limit (A)'), ('dut_input_overvoltage_V', 'Input over-voltage (V)'),
                                       ('dut_output_overvoltage_V', 'Output voltage guard (V)'), ('output_overcurrent_A', 'Output current guard (A)')]:
                        input_field(key, label, controls.get(key), fields, number=True)
                ui.label('Instrument addresses and expected serials come from the private inventory file supplied when starting this page.').classes('bench-muted')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Cancel', on_click=close_editor).props('outline no-caps')

                    async def save():
                        try:
                            data.setdefault('protective_controls', {})
                            for key, value in values(fields).items():
                                data['protective_controls'][key] = None if value is None or value == '' else float(value)
                            data['protective_controls']['approved'] = False
                            await save_and_select('bench', data, note='Limits saved — approval cleared; review and tick the box again.', select_saved=False)
                            close_editor()
                        except (ValueError, TypeError, OSError) as exc:
                            notify_error(exc)
                    ui.button('Save limits', on_click=save, icon='save').props('unelevated no-caps')

        async def approve_changed(event, name):
            data = copy.deepcopy(state['catalog']['bench'][name])
            data.setdefault('protective_controls', {})['approved'] = bool(event.value)
            try:
                await save_and_select('bench', data, select_saved=False)
            except (ValueError, OSError) as exc:
                notify_error(exc)

        # --- rendering: the three questions ------------------------------------------------------

        def link_button(text, handler, *, danger=False):
            button = ui.button(text).props('flat dense no-caps size=sm').classes('bench-link' + (' bench-link-danger' if danger else ''))
            button.on('click.stop', handler)
            return button

        def card(*, selected, title, on_select, subtitle=None, meta=None, reason=None, badge=None, links=(), reason_style='danger'):
            """A selectable card: one real <button> for the whole face (Enter and Space work, nothing interactive
            nested inside it) plus one "⋯" actions menu beside it. ``reason`` greys the card; ``reason_style``
            'danger' is for a test the operator chose that cannot run now, 'muted' for a plain fact."""
            item = ui.element('div').classes('bench-card-item' + (' selected' if selected else '') + (' greyed' if reason else ''))
            with item:
                face = ui.element('button').classes('bench-card-select')
                face.props(f'type=button aria-pressed={"true" if selected else "false"}')
                face.on('click.stop', on_select)
                with face:
                    with ui.element('div').classes('bench-card-title'):
                        if selected:
                            with ui.element('span').classes('bench-card-check'):
                                ui.icon('check', size='15px')
                        ui.label(title)
                    if subtitle:
                        ui.label(subtitle).classes('bench-card-grid')
                    if badge:
                        ui.label(badge).classes('bench-badge bench-badge-standard')
                    if meta:
                        ui.label(meta).classes('bench-card-meta')
                    if reason:
                        ui.label(('Cannot run on this bench: ' if reason_style == 'danger' else 'Not on this bench: ') + reason).classes(
                            'bench-card-reason' if reason_style == 'danger' else 'bench-card-note')
                if links:
                    more = ui.button(icon='more_horiz').props(f'flat dense round aria-label={json.dumps("Actions for " + title)} aria-haspopup=menu')
                    more.classes('bench-card-menu')
                    more.on('click.stop', lambda: None)  # opening the menu never selects the card
                    with more, ui.menu().props('auto-close'):
                        for text, handler in links:
                            ui.menu_item(text, on_click=handler).classes('bench-menu-danger' if text == 'Delete' else '')
            return item

        def add_card(text, handler):
            item = ui.element('button').classes('bench-add').props('type=button')
            item.on('click', handler)
            with item:
                ui.label(text)
            return item

        def render_summary():
            panels['summary'].clear()
            with panels['summary']:
                with ui.row().classes('items-baseline gap-1 flex-nowrap'):
                    ui.label('Selected').classes('bench-summary-key')
                    ui.label(summary_text(current('dut'), state['mode'], current('bench'), current('recipe'))).classes('bench-summary-text')

        def render_converters():
            panels['converters'].clear()
            with panels['converters']:
                for name, dut in state['catalog']['dut'].items():
                    card(selected=state['dut'] == name, title=dut['identity']['model'], subtitle=dut_subtitle(dut),
                         meta='Approved for the real bench' if dut_approved(dut) else 'Not yet approved for the real bench',
                         on_select=lambda _=None, name=name: select('dut', name),
                         links=[('Rename', lambda _=None, name=name: rename_profile('dut', name)),
                                ('Edit', lambda _=None, name=name: open_dut_editor(name)),
                                ('Delete', lambda _=None, name=name: delete_profile('dut', name))])
                add_card('+ Add a converter', lambda _=None: open_dut_editor(None))

        def render_bench():
            panels['bench'].clear()
            panels.pop('editor_limits', None)  # lived inside the real tile; re-created below when a preset exists
            real_benches, mock_benches = benches_of('real'), benches_of('mock')
            real = state['catalog']['bench'].get(state['bench']['real']) if state['bench']['real'] else None
            def preset_pill(mode, name, bench):
                on = state['bench'][mode] == name
                # A selected pill is a filled primary button: Quasar's flat text colour would otherwise
                # paint the label in the same blue as the fill.
                pill = ui.button(bench_title(bench)).props('dense no-caps size=sm ' + ('unelevated color=primary text-color=white' if on else 'flat'))
                pill.classes('bench-pill' + (' on' if on else ''))
                pill.props(f'aria-pressed={"true" if on else "false"}')
                pill.on('click.stop', lambda _=None, name=name: select_bench(mode, name))
                return pill

            def can_cannot(title, can, cannot, can_head, cannot_head):
                ui.label(title).classes('bench-lbl')
                with ui.element('div').classes('bench-cando'):
                    with ui.element('div').classes('bench-cando-col'):
                        ui.label(can_head).classes('bench-cando-head')
                        for line in can:
                            ui.label('✓ ' + line).classes('bench-cando-can')
                    with ui.element('div').classes('bench-cando-col'):
                        ui.label(cannot_head).classes('bench-cando-head')
                        for line in cannot:
                            ui.label('✗ ' + line).classes('bench-cando-cannot')

            def tile_keys(tile):
                # The two tiles form one radio group: arrow keys move between them, Enter and Space choose.
                tile.on('keydown.enter.prevent', lambda _=None, mode=tile_mode[tile.id]: select_mode(mode))
                tile.on('keydown.space.prevent', lambda _=None, mode=tile_mode[tile.id]: select_mode(mode))
                tile.on('keydown.right.prevent', lambda _=None: select_mode('real'))
                tile.on('keydown.down.prevent', lambda _=None: select_mode('real'))
                tile.on('keydown.left.prevent', lambda _=None: select_mode('mock'))
                tile.on('keydown.up.prevent', lambda _=None: select_mode('mock'))
            tile_mode = {}
            with panels['bench']:
                with ui.element('div').classes('bench-tiles').props('role=radiogroup aria-label="Simulation or real bench"'):
                    tile = ui.element('div').classes('bench-tile sim' + (' selected' if state['mode'] == 'mock' else ''))
                    tile.props(f'role=radio tabindex=0 aria-checked={"true" if state["mode"] == "mock" else "false"}')
                    tile.on('click', lambda _=None: select_mode('mock'))
                    tile_mode[tile.id] = 'mock'
                    tile_keys(tile)
                    mock = state['catalog']['bench'].get(state['bench']['mock']) if state['bench']['mock'] else None
                    with tile:
                        ui.label(BENCH_NAMES['mock']).classes('bench-tile-title')
                        ui.label('Nothing is switched on. Synthetic readings, real report layout; every output is labelled SYNTHETIC.').classes('bench-tile-sub')
                        with ui.column().classes('bench-sim-details gap-2'):
                            if len(mock_benches) > 1:
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label('Synthetic bench').classes('bench-lbl')
                                    with ui.element('div').classes('bench-pills'):
                                        for name, bench in mock_benches.items():
                                            preset_pill('mock', name, bench)
                            if mock is not None:
                                # The same anatomy as the real tile: the envelope that decides which points the plan skips.
                                with ui.element('div').classes('bench-limits').props('role=table aria-label="Synthetic envelope"'):
                                    for label, value in envelope_rows(mock):
                                        ui.label(label).classes('bench-limit-key')
                                        ui.label(value).classes('bench-limit-value')
                            can_cannot('What the simulation can and cannot do', SIMULATION_CAN, SIMULATION_CANNOT,
                                       'The simulation can', 'It cannot')
                    tile = ui.element('div').classes('bench-tile real' + (' selected' if state['mode'] == 'real' else ''))
                    tile.props(f'role=radio tabindex=0 aria-checked={"true" if state["mode"] == "real" else "false"}')
                    tile.on('click', lambda _=None: select_mode('real'))
                    tile_mode[tile.id] = 'real'
                    tile_keys(tile)
                    with tile:
                        ui.label(BENCH_NAMES['real']).classes('bench-tile-title')
                        if real is None:
                            ui.label('No real bench preset is saved. The seeded preset is restored when the page restarts.').classes('bench-tile-sub')
                        else:
                            ui.label(bench_equipment(real, state['inventory']) + '. Start can switch outputs on.').classes('bench-tile-sub')
                            with ui.column().classes('bench-real-details gap-2') as details:
                                # Editing a field or approving a preset is not a
                                # selection of the surrounding real-bench tile.
                                # Keyboard events must stay with the input too.
                                details.on('click.stop', lambda: None)
                                details.on('keydown.stop', lambda: None)
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label('Limit preset').classes('bench-lbl')
                                    with ui.element('div').classes('bench-pills'):
                                        for name, bench in real_benches.items():
                                            preset_pill('real', name, bench)
                                with ui.element('div').classes('bench-limits').props('role=table aria-label="Protective limits"'):
                                    for label, value in limits_rows(real):
                                        ui.label(label).classes('bench-limit-key')
                                        ui.label(value).classes('bench-limit-value')
                                with ui.row().classes('w-full items-center justify-between gap-2 flex-wrap'):
                                    link_button('Change limits…', lambda _=None: open_limits_editor(state['bench']['real']))
                                    ui.label('Instrument addresses and serials come from the inventory file').classes('bench-lbl')
                                panels['editor_limits'] = ui.column().classes('bench-editor gap-3')
                                panels['editor_limits'].set_visibility(False)
                                approved = bool((real.get('protective_controls') or {}).get('approved'))
                                box = ui.checkbox('Limits approved for this preset' if approved else 'I reviewed these limits — required once',
                                                  value=approved, on_change=lambda e, name=state['bench']['real']: approve_changed(e, name))
                                box.classes('bench-approve-ok' if approved else 'bench-approve-missing' if state['mode'] == 'real' else '')
                                box.props('aria-label="I reviewed these limits"')
                                box.on('click.stop', lambda: None)  # ticking the approval never also switches the bench
                                widgets['approve'] = box
                                can_cannot('What the real bench can and cannot do', REAL_CAN, REAL_CANNOT,
                                           'The real bench can', 'It cannot')
            if state.get('editor') and state['editor'][0] == 'limits':
                state['editor'] = None

        def render_tests():
            panels['tests'].clear()
            feasibility = state['feasibility']
            with panels['tests']:
                for category, items in grouped_recipes(state['catalog']['recipe']):
                    ui.label(category).classes('bench-group')
                    with ui.element('div').classes('bench-cards'):
                        for name, recipe in items:
                            feasible = feasibility.get(name) or {}
                            runnable = feasible.get('runnable', True)
                            count = feasible.get('points') if feasible.get('points') is not None else sum(
                                len(t['input_voltage_targets_V']) * len(t['output_current_targets_A']) for t in recipe['tests'])
                            card(selected=state['recipe'] == name, title=recipe_title(recipe), subtitle=recipe_grid(recipe),
                                 meta=card_meta(count, state['mode'], feasible.get('estimated_seconds')),
                                 reason=None if runnable else feasible.get('reason') or 'no executable point',
                                 badge=recipe.get('standard_clause'),
                                 on_select=lambda _=None, name=name: select('recipe', name),
                                 links=[('Rename', lambda _=None, name=name: rename_profile('recipe', name)),
                                        ('Duplicate', lambda _=None, name=name: duplicate_recipe(name)),
                                        ('Edit', lambda _=None, name=name: open_recipe_editor(name)),
                                        ('Delete', lambda _=None, name=name: delete_profile('recipe', name))])
                if not state['catalog']['recipe']:
                    ui.label('No saved tests yet.').classes('bench-muted')
                with ui.element('div').classes('bench-cards'):
                    add_card('+ New test', lambda _=None: open_recipe_editor(None))
                ui.label('Whether a test runs in the simulation or on the real bench is decided by question 2. Each input voltage is tested at each requested load.').classes('bench-muted')
                render_standards()

        # --- automotive standards: one card per standard, the ISO 16750-2 card expands into a clause checklist ---

        def standards_system():
            return state['standards']['system'] or default_system(current('dut') or {})

        def render_standards():
            """Cards for the automotive standards catalog; non-runnable standards are greyed with their one-sentence reason."""
            dut, bench = current('dut'), current('bench')
            ui.label(STANDARDS_GROUP).classes('bench-group')
            if not dut or not bench:
                ui.label('Select a converter and a bench to see which clauses can run here.').classes('bench-muted')
                return
            system = standards_system()
            try:
                infos = standard_cards(bench, dut, system)
                rows = clause_rows(bench, dut, system) if state['standards']['open'] else []
            except (ValueError, KeyError) as exc:
                ui.label('Standards catalog unavailable: ' + str(exc)).classes('bench-card-reason')
                return
            with ui.element('div').classes('bench-cards'):
                for info in infos:
                    if info['expandable']:
                        item = card(selected=state['standards']['open'], title=info['title'], subtitle=info['subtitle'],
                                    meta=(f"{info['clause_count']} clauses: " + info['summary']) if info.get('summary')
                                    else f"{info['runnable_count']} test subsets available · {info['clause_count']} clauses reviewed",
                                    reason=None if info['runnable'] else info['reason'], badge=f'{system[:-1]} V system',
                                    on_select=lambda _=None: toggle_standard())
                        item.classes(add='bench-standard-card')
                        item.props(f'aria-expanded={"true" if state["standards"]["open"] else "false"}')
                    else:
                        # A laboratory this bench will never be is a plain fact, not an operator error: grey, not red.
                        card(selected=False, title=info['title'], subtitle=info['subtitle'], reason=info['reason'], reason_style='muted',
                             on_select=lambda _=None: None).classes(add='bench-standard-card')
            if state['standards']['open']:
                render_checklist(rows, system)

        def ticked_by_default(row):
            """The catalog's own default (``ticked_by_default``); older catalogs without it tick what runs here now."""
            return bool(row.get('ticked_by_default', row['badge'] == 'runs_here')) and row['tickable']

        def preticked(rows):
            """Only clauses that run here now are ticked by default; a clause that needs an approval first is left for the operator."""
            return {row['number'] for row in rows if ticked_by_default(row)}

        def toggle_standard():
            """Selecting the standard opens its checklist with every clause that runs now ticked; selecting again folds it."""
            standards = state['standards']
            standards['open'] = not standards['open']
            if standards['open']:
                standards['ticked'] = preticked(clause_rows(current('bench'), current('dut'), standards_system()))
            render_tests()

        def render_checklist(rows, system):
            ticked = state['standards']['ticked']
            runnable = sum(1 for row in rows if row['tickable'] and row['badge'] == 'runs_here')
            later = sum(1 for row in rows if row['tickable'] and row['badge'] != 'runs_here')
            with ui.column().classes('bench-checklist gap-1'):
                with ui.row().classes('items-center gap-3 flex-wrap w-full'):
                    ui.label('System voltage class').classes('bench-lbl')
                    toggle = ui.toggle({'12V': '12 V', '24V': '24 V'}, value=system, on_change=lambda e: system_changed(e.value))
                    toggle.props('no-caps dense unelevated toggle-color=primary aria-label="System voltage class"')
                    widgets['system_toggle'] = toggle
                    ui.label('Remembered on the converter profile. Levels follow ISO 16750-2 Tables 3/4 for the chosen class.').classes('bench-muted')
                for row in rows:
                    with ui.element('div').classes('bench-clause-row' + ('' if row['tickable'] else ' untickable')):
                        box = ui.checkbox(f"§{row['number']} {row['title']}", value=row['tickable'] and row['number'] in ticked,
                                          on_change=lambda e, number=row['number']: tick_clause(number, e.value))
                        box.props(f'aria-label="clause {row["number"]}"')
                        if not row['tickable']:
                            box.disable()
                        # The catalog's status word is shown as it comes; "runs here" is the only green badge.
                        # An approval-first or mock-only clause is amber, never green.
                        style = ('bench-badge-ok' if row['badge'] == 'runs_here' else
                                 'bench-badge-partial' if row['badge'] in ('procedure_pending', 'runs_after_approval', 'mock_only', 'needs_split')
                                 or row['tickable'] else 'bench-badge-grey')
                        badge = ui.label(row['badge_label']).classes('bench-badge ' + style)
                        ui.label(row['levels']).classes('bench-muted')
                        note = row['text'] if not row['tickable'] else '; '.join(row['conditions'])
                        if row.get('needs_approval') and row.get('approval') and row['approval'] not in (note or ''):
                            note = (note + ' ' if note else '') + str(row['approval'])
                        if note:
                            ui.label(note).classes('bench-clause-note')
                        else:
                            badge.tooltip(row['text'] or row['reason'])
                with ui.row().classes('items-center justify-between w-full flex-wrap gap-2'):
                    ui.label(f'{runnable} test subset{"s" if runnable != 1 else ""} available now · {len(rows)} clauses reviewed'
                             + (f' · {later} after approval' if later else '')).classes(
                        'bench-card-meta bench-checklist-footer')
                    widgets['add_tests'] = ui.button('Add as tests', on_click=add_as_tests, icon='playlist_add').props('unelevated no-caps')
                    widgets['add_tests'].set_enabled(bool(ticked))
                ui.label('Each ticked clause becomes a saved test under “ISO 16750-2 supply profiles”. A clause marked “runs here after '
                         'approval” is saved unapproved and its card stays greyed until the saved recipe is approved under the bench’s '
                         'protective policy (brief §7.5); the row says where that approval is recorded.').classes('bench-muted')

        def tick_clause(number, value):
            ticked = state['standards']['ticked']
            (ticked.add if value else ticked.discard)(number)
            if 'add_tests' in widgets:
                widgets['add_tests'].set_enabled(bool(ticked))

        async def system_changed(value):
            """Switch the clause parameters to the other system class and remember it on the converter profile."""
            if state['active'] or state['start_busy']:
                return
            if value not in ('12V', '24V') or value == standards_system():
                return
            name = state['dut']
            data = copy.deepcopy(state['catalog']['dut'][name])
            data['system_voltage_class'] = value
            changed()
            generation = state['generation']
            try:
                await run.io_bound(service.save_profile, 'dut', data)
            except (ValueError, OSError) as exc:
                notify_error(exc)
                return
            if client.is_deleted or generation != state['generation']:
                return
            state['catalog']['dut'][name] = data
            state['standards']['system'] = value
            state['standards']['ticked'] = preticked(clause_rows(current('bench'), data, value))
            render_tests()
            changed()

        async def add_as_tests():
            """Save one recipe per ticked runnable clause and select the last one; every field comes from the catalog and the ratings."""
            if state['active'] or state['start_busy']:
                return
            standards = state['standards']
            dut, bench = current('dut'), current('bench')
            numbers = sorted(standards['ticked'], key=lambda number: [int(part) for part in number.split('.')])
            if not (dut and bench and numbers):
                notify('Tick at least one runnable clause first.', type='warning')
                return
            system, saved = standards_system(), []
            changed()
            generation = state['generation']
            try:
                for number in numbers:
                    data = build_recipe(number, system, dut, bench)
                    taken = set(state['catalog']['recipe']) | set(saved)
                    if data['recipe_id'] in taken:
                        data['recipe_id'] = unique_name(data['recipe_id'], taken)
                    name = await run.io_bound(service.save_profile, 'recipe', data)
                    if client.is_deleted:
                        return
                    saved.append(name)
            except (ValueError, TypeError, OSError) as exc:
                notify_error(exc)
                if not saved:
                    return
            if not await reload(recompute=False) or generation != state['generation']:
                return
            state['recipe'] = saved[-1]
            await refresh_feasibility()
            if client.is_deleted or generation != state['generation']:
                return
            standards['ticked'] = set()
            render_tests()
            changed()
            notify(f'Added {len(saved)} test{"" if len(saved) == 1 else "s"} under “ISO 16750-2 supply profiles”.', type='positive')

        # --- plan, confirmation, start -----------------------------------------------------------

        def can_start():
            preview = state['preview']
            return bool(preview and preview.get('supported') and not preview.get('errors')
                        and not state['active'] and not state['preview_busy'] and not state['start_busy'])

        def start_hint():
            """Why Start is disabled, spelled out under the bar; '' when it is enabled."""
            if can_start():
                return ''
            if state['active']:
                return 'Locked while a test runs on the bench. Start returns when it has finished.'
            if state['start_busy']:
                return 'Starting…'
            preview = state['preview']
            if preview is None:
                return 'Preview first — Start unlocks after a fresh plan.'
            if preview.get('errors') or not preview.get('supported'):
                return 'The plan cannot start: see the Before Start list in the Plan panel.'
            return ''

        def render_bar():
            widgets['bar_summary'].set_text(summary_text(current('dut'), state['mode'], current('bench'), current('recipe')))
            start = widgets['start']
            start.set_text(START_LABELS[state['mode']])
            start.props('aria-label=' + json.dumps(START_LABELS[state['mode']]))
            start.classes(remove='bench-start-real bench-start-mock', add='bench-start-real' if state['mode'] == 'real' else 'bench-start-mock')
            start.set_enabled(can_start())
            hint = start_hint()
            widgets['start_hint'].set_text(hint)
            widgets['start_hint'].set_visibility(bool(hint))
            widgets['preview'].set_enabled(not state['preview_busy'] and not state['active'] and not state['start_busy']
                                           and bool(state['dut'] and bench_name() and state['recipe']))
            for key in ('converters_section', 'bench_section', 'tests_section'):
                locked = state['active'] or state['start_busy']
                panels[key].classes(add='bench-locked' if locked else '', remove='' if locked else 'bench-locked')
                # pointer-events alone still admits keyboard activation. Native
                # inert locks the whole editor group, with run status outside it.
                panels[key].props(add='inert' if locked else '', remove='' if locked else 'inert')

        def render_plan():
            panel = panels['plan']
            preview, note = state['preview'], state['stale_note']
            if preview is None and note is None:
                panel.clear()
                panel.set_visibility(False)
                return
            panel.clear()
            panel.set_visibility(True)
            panel.classes(add='stale' if preview is None else '', remove='' if preview is None else 'stale')
            with panel:
                ui.label('Plan').classes('bench-h2')
                if preview is None:
                    ui.label(note).classes('bench-stale')
                    return
                counts = preview.get('counts', {})
                ready, total = counts.get('executable', 0), len(preview.get('points', []))
                mode = preview.get('mode')
                with ui.element('div').classes('bench-stats'):
                    for key, value, small in (('Points that will run', f'{ready} / {total}', False), ('Skipped', str(total - ready), False),
                                              ('Estimated time', simulation_time_text(preview.get('estimated_seconds')) if mode == 'mock' else (duration_text(preview.get('estimated_seconds')) or '—'),
                                               mode == 'mock'),
                                              ('Bench', ('Real bench — ' + bench_equipment(preview.get('plan', {}).get('bench', {}), state['inventory']))
                                               if mode == 'real' else 'Simulation — nothing switched on', True)):
                        with ui.element('div').classes('bench-stat'):
                            ui.label(key).classes('bench-stat-key')
                            ui.label(value).classes('bench-stat-value' + (' small' if small else ''))
                if mode == 'real':
                    ui.label('Limits: ' + limits_summary(preview.get('plan', {}).get('bench', {}))).classes('bench-muted')
                reasons = skip_reasons(preview)
                if reasons:
                    ui.label('Why points are skipped').classes('bench-k-label')
                    with ui.column().classes('bench-reasons gap-1'):
                        for count, status, reason in reasons:
                            ui.label(f'{count} point{"s" if count > 1 else ""} {status}: {reason}')
                    ui.label('Skipped points stay in the saved plan and are listed in the report with the same reason; a request is never reduced to fit.').classes('bench-muted')
                errors = preview.get('errors', [])
                if errors:
                    ui.label('Before Start').classes('bench-k-label bench-danger')
                    with ui.column().classes('bench-reasons gap-1'):
                        for error in errors:
                            ui.label(str(error)).classes('bench-danger')
                elif mode == 'mock':
                    ui.label('Ready. After Start you will see:').classes('bench-muted')
                    render_sequence(None)
                else:
                    ui.label('Ready. HTML and PDF reports are queued after acquisition (minutes on a Raspberry Pi) and appear as links under Run and in Reports.').classes('bench-muted')
                widgets['notes'] = ui.textarea('Notes for the report (optional)', placeholder='Sample revision, wiring, mounting or observations').props('outlined autogrow dense')
                with ui.expansion('All requested points and planning notes', icon='list').classes('w-full'):
                    for warning in preview.get('warnings', []):
                        ui.label(str(warning)).classes('bench-muted')
                    ui.table(columns=[{'name': key, 'label': label, 'field': key, 'align': 'left', 'classes': '' if key == 'reason' else 'nowrap',
                                       'headerClasses': '' if key == 'reason' else 'nowrap'} for key, label in
                        [('input_display', 'Input'), ('load_display', 'Requested output load'), ('estimated_display', 'Estimated supply current'),
                         ('status_display', 'Plan'), ('reason', 'Reason')]], rows=plan_rows(preview), row_key='point_id',
                         pagination=15).props('flat dense').classes('w-full')
                    ui.label('Plan words, the same as the CLI and the saved plan').classes('bench-lbl')
                    with ui.element('div').classes('bench-legend'):
                        for status, meaning in PLAN_STATUS_LEGEND:
                            ui.html(f'<code>{status}</code>')
                            ui.label(meaning)

        def render_sequence(snapshot):
            """The four steps a simulation goes through, with the current one marked and its time."""
            step = sequence_step(snapshot)
            with ui.element('div').classes('bench-sequence').props('role=list aria-label="What happens next"'):
                for index, (label, timing) in enumerate(SIMULATION_SEQUENCE):
                    status = 'current' if step == index else 'done' if step is not None and index < step else ''
                    with ui.element('div').classes('bench-sequence-step ' + status).props('role=listitem'):
                        ui.label(str(index + 1)).classes('bench-sequence-num')
                        ui.label(label + ' — ' + timing)

        async def preview_test():
            if state['preview_busy'] or state['active'] or state['start_busy']:
                return
            dut, bench, recipe = state['dut'], bench_name(), state['recipe']
            if not (dut and bench and recipe):
                notify('Choose a converter, a bench and a test first.', type='warning')
                return
            state['preview_busy'] = True
            widgets['preview'].disable()
            state['preview'] = None
            generation = state['generation']
            try:
                saved = state['catalog']['recipe'][recipe]
                if saved.get('dut_profile_id') != dut:
                    # A test belongs to whichever converter is selected; the saved copy follows (as before).
                    await run.io_bound(service.save_profile, 'recipe', {**saved, 'dut_profile_id': dut})
                    state['catalog']['recipe'][recipe] = {**saved, 'dut_profile_id': dut}
                preview = await run.io_bound(service.preview, dut, bench, recipe)
                jobs = await run.io_bound(service.list_jobs)
                if client.is_deleted or preview is None:
                    return
                remember_jobs(jobs)
                if state['generation'] != generation:
                    notify('Settings changed while the preview was being prepared. Preview again to use your latest settings.', type='warning')
                    return
                state['preview'], state['stale_note'] = preview, None
                render_plan()
                scroll_to('.bench-plan')
            except (ValueError, TypeError, OSError, RuntimeError) as exc:
                notify_error(exc)
            finally:
                state['preview_busy'] = False
                render_bar()

        def scroll_to(selector):
            if getattr(client, 'has_socket_connection', False):
                with client:
                    ui.run_javascript(f"document.querySelector({json.dumps(selector)})?.scrollIntoView({{behavior:'smooth',block:'start'}})")

        def can_arm():
            preview = state['preview']
            confirm = state['confirm']
            if not preview or not confirm or not all(widget.value for widget in confirm.values()):
                return False
            return all(str(confirm[role + '_serial'].value or '').strip() == preview.get('inventory', {}).get(role, {}).get('serial')
                       for role in ('source', 'load'))

        def arm_changed(_event=None):
            if 'confirm_start' in widgets:
                widgets['confirm_start'].set_enabled(can_arm())

        def open_confirm():
            """Fresh physical confirmation for every real Start: three statements and both serials."""
            preview = state['preview']
            panel = panels['confirm']
            panel.clear()
            state['confirm'] = {}
            panel.set_visibility(True)
            bench = preview.get('plan', {}).get('bench', {})
            with panel:
                ui.label('Confirm the physical setup').classes('bench-h2')
                with ui.column().classes('bench-confirm gap-2'):
                    ui.label('Required before every real start. The worker re-checks instrument identity and that both outputs are OFF before switching anything on.').classes('bench-muted')
                    for key, label in [('wiring_and_polarity', 'Converter input/output wiring and polarity are correct'),
                                       ('channel1', f'The converter is on {bench_equipment(bench, state["inventory"]).split(" + ")[0]} (not CH2) and the load input'),
                                       ('protections_reviewed', 'I reviewed the protective limits: ' + limits_summary(bench))]:
                        state['confirm'][key] = ui.checkbox(label, on_change=arm_changed)
                    with ui.element('div').classes('bench-fields'):
                        for role, label in [('source', 'Power-supply serial'), ('load', 'Electronic-load serial')]:
                            identity = preview.get('inventory', {}).get(role, {})
                            state['confirm'][role + '_serial'] = ui.input(
                                label + ' (configured: ' + str(identity.get('serial') or 'not configured') + ')',
                                on_change=arm_changed).props('outlined dense autocomplete=off')
                    with ui.row().classes('w-full justify-end gap-2'):
                        def cancel():
                            state['confirm'] = {}
                            panel.clear()
                            panel.set_visibility(False)
                        ui.button('Cancel', on_click=cancel).props('outline no-caps')
                        widgets['confirm_start'] = ui.button('Switch on and start', on_click=lambda: start_job(confirmed=True),
                                                             icon='power_settings_new', color='negative').props('unelevated no-caps aria-label="Switch on and start"')
                        widgets['confirm_start'].disable()
            scroll_to('.bench-confirm')

        async def start_pressed():
            if not can_start():
                return
            if state['preview'].get('mode') == 'real':
                open_confirm()
            else:
                await start_job()

        async def start_job(confirmed=False):
            preview = state['preview']
            if not can_start() or (confirmed and not can_arm()):
                return
            # Single-shot: a second click before the service answers finds can_start() false and does nothing.
            state['start_busy'] = True
            render_bar()
            if 'confirm_start' in widgets:
                widgets['confirm_start'].disable()
            try:
                confirmation = None
                if preview.get('mode') == 'real':
                    confirmation = {key: widget.value for key, widget in state['confirm'].items()}
                    confirmation['plan_hash'] = preview['plan_hash']
                notes = widgets['notes'].value if 'notes' in widgets else ''
                job = await run.io_bound(service.start, preview['plan_hash'], confirmation=confirmation, notes=notes or '')
                if client.is_deleted or job is None:
                    return
                state['job_id'] = job['job_id']
                state['preview'] = None
                # The confirmation inputs are gone with the panel; forget them so a later
                # invalidation never calls set_value on deleted elements.
                state['confirm'] = {}
                panels['confirm'].clear()
                panels['confirm'].set_visibility(False)
                widgets.pop('confirm_start', None)
                widgets.pop('notes', None)
                state['stale_note'] = 'Test started — the header shows its progress. Preview again to plan another test.'
                render_plan()
                await poll()
                scroll_to('.bench-run')
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)
                # A refused Start (a profile changed, another job holds the bench) never leaves a
                # stale plan armed: Start stays disabled until the operator previews again.
                changed('Start was refused — Preview again before starting.')
            finally:
                state['start_busy'] = False
                render_bar()
                arm_changed()

        # --- running: header pill, two-step Stop, run panel ---------------------------------------

        async def stop_confirmed(job_id):
            """Single-shot: the first click asks the service once; later clicks for the same job do nothing
            (the service's cancel() is idempotent as well, for a second tab)."""
            if job_id in state['stop_requested']:
                return
            state['stop_requested'].add(job_id)
            state['stop_armed'] = False
            if 'confirm_stop' in widgets:
                widgets['confirm_stop'].disable()
            try:
                await run.io_bound(service.cancel, job_id)
                notify('Stop requested. Wait for the worker to verify both outputs OFF.', type='warning')
                await poll()
            except (ValueError, OSError, RuntimeError) as exc:
                state['stop_requested'].discard(job_id)
                notify_error(exc)

        def render_stop(snapshot):
            """Far right of the header: 'Stop…' arms; 'Confirm stop' / 'Keep running' decide. Never where Start was."""
            visible = bool(snapshot) and 'stop' in job_actions(snapshot)
            requested = bool(snapshot and snapshot.get('cancel_requested'))
            key = (visible, state['stop_armed'], requested, snapshot.get('job_id') if snapshot else None)
            if key == state['stop_key']:
                return
            state['stop_key'] = key
            area = panels['stop']
            area.clear()
            area.set_visibility(visible)
            if not visible:
                return
            job_id = snapshot['job_id']
            with area:
                if requested:
                    ui.label('Stop requested — waiting for the worker').classes('bench-muted')
                elif not state['stop_armed']:
                    def arm():
                        state['stop_armed'] = True
                        render_stop(snapshot)
                    ui.button('Stop…', on_click=arm, icon='stop', color='negative').props('outline no-caps aria-label="Stop…"')
                else:
                    def keep():
                        state['stop_armed'] = False
                        render_stop(snapshot)
                    widgets['confirm_stop'] = ui.button('Confirm stop', on_click=lambda: stop_confirmed(job_id), color='negative').props(
                        'unelevated no-caps aria-label="Confirm stop"')
                    ui.button('Keep running', on_click=keep).props('outline no-caps aria-label="Keep running"')

        async def dequeue_report(job_id):
            try:
                await run.io_bound(service.cancel, job_id)
                notify('Removed from the report queue. The saved measurements are preserved; Regenerate report can build one later.', type='info')
                await poll()
                await refresh_reports()
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)

        async def regenerate_report(job_id):
            """Single-shot: a second click while the first is in flight, or once the job is already queued, does nothing."""
            known = next((job for job in state['jobs'] if job.get('job_id') == job_id), None)
            if job_id in state['regenerate_busy'] or (known and known.get('state') in WORKING_STATES + ('report-queued',)):
                return
            state['regenerate_busy'].add(job_id)
            render_reports(state['jobs'])
            try:
                await run.io_bound(service.retry_report, job_id)
                state['job_id'] = job_id
                notify('Rebuilding the report from the saved measurements. No acquisition will run.', type='info')
                await poll()
                await refresh_reports()
            except (ValueError, OSError, RuntimeError) as exc:
                notify_error(exc)
            finally:
                state['regenerate_busy'].discard(job_id)

        def report_links(snapshot):
            # Kept artifacts only: a PDF that is unverified (checker tool missing) or
            # failed its layout check stays reachable, named as such in the label.
            rows = report_link_rows(snapshot)
            if not rows:
                return
            with ui.row().classes('gap-5'):
                for label, relative in rows:
                    ui.link(label, artifact_url(snapshot['job_id'], relative), new_tab=True).classes('bench-artifact')

        def show_status(snapshot):
            panel = panels['run']
            panel.clear()
            panel.set_visibility(True)
            with panel:
                ui.label('Run').classes('bench-h2')
                with ui.column().classes('bench-run gap-3'):
                    ui.label(state_label(snapshot)).classes('bench-k-label').style('font-size:17px')
                    ui.label('Simulation · synthetic data · no instrument is touched' if snapshot.get('mode') == 'mock'
                             else 'Real bench · measured data').classes('bench-message')
                    if sequence_step(snapshot) is not None:
                        render_sequence(snapshot)
                    if snapshot.get('state') == 'reporting':
                        ui.label('The measurements are saved. Preparing the interactive plots and PDF can take several minutes on a Raspberry Pi. You can reconnect later; this job continues independently.').classes('bench-message')
                    if snapshot.get('state') == 'report-queued':
                        waiting = deferred_text(snapshot)
                        note = ui.label('The measurements are saved and both outputs are verified OFF. Report generation is queued and starts automatically when no test is running and enough memory is free.'
                                        + (' ' + waiting + '.' if waiting else '')).classes('bench-message')
                        if snapshot.get('deferred_reason'):
                            note.tooltip('Dispatcher reason: ' + str(snapshot['deferred_reason'])
                                         + (' · checked ' + local_time_text(snapshot['deferred_utc']) if snapshot.get('deferred_utc') else ''))
                    ui.label('Run ' + str(snapshot.get('run_id') or snapshot['job_id'])).classes('bench-muted')
                    # Local wall-clock display only; job.json and the run evidence keep UTC.
                    for key, label in [('created_utc', 'Started'), ('acquisition_cancelled_utc', 'Stop requested'),
                                       ('queued_utc', 'Report queued'), ('dispatched_utc', 'Report started')]:
                        if snapshot.get(key):
                            ui.label(f'{label}: {local_time_text(snapshot[key])}').classes('bench-muted')
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
                    reading_kind = 'Simulated' if snapshot.get('mode') == 'mock' else 'Measured'
                    with ui.row().classes('w-full gap-3'):
                        for key, label, unit in [('Vin_V', reading_kind + ' input', 'V'), ('Iin_A', 'Supply current', 'A'),
                                                  ('Vout_V', reading_kind + ' output', 'V'), ('Iout_A', 'Load current', 'A')]:
                            with ui.column().classes('bench-stat-tile gap-1'):
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
                    if snapshot.get('report_note'):
                        ui.label(str(snapshot['report_note'])).classes('bench-message bench-warning')
                    ui.label(shutdown_label(snapshot)).classes('bench-message')
                    if 'dequeue' in job_actions(snapshot):
                        ui.button('Remove from report queue', on_click=lambda: dequeue_report(snapshot['job_id']),
                                  icon='playlist_remove').props('outline no-caps aria-label="Remove from report queue"')
                    report_links(snapshot)
                    if snapshot.get('mode') == 'mock' and report_link_rows(snapshot):
                        ui.label(SYNTHETIC_UNCERTAINTY_NOTE).classes('bench-muted')
                    artifacts = snapshot.get('report_artifacts') or {}
                    terminal = snapshot.get('state') in ('completed', 'aborted', 'failed', 'cancelled')
                    removed = dequeued(snapshot)
                    failed_formats = [name.upper() for name in ('html', 'pdf')
                                      if terminal and not removed and snapshot.get('run_dir') and artifacts.get(name, {}).get('status') not in ('success', 'unverified')]
                    if terminal and not snapshot.get('run_dir'):
                        ui.label('No measurements were acquired for this job.').classes('bench-muted')
                    if removed:
                        ui.label('Removed from the report queue: no report was generated and none failed. The saved measurements are preserved; '
                                 '"Regenerate report" in Reports builds one from them.').classes('bench-message')
                    if failed_formats:
                        ui.label('Report generation needs attention: ' + ', '.join(failed_formats) + '. Saved measurements are preserved. Use "Regenerate report" in Reports.').classes('bench-message bench-warning')
                    events = snapshot.get('events') or []
                    if events:
                        job_id = snapshot['job_id']
                        with ui.expansion('Recent events', icon='list', value=state['events_open'].get(job_id, False),
                                          on_value_change=lambda e, job_id=job_id: state['events_open'].__setitem__(job_id, e.value)).classes('w-full'):
                            for event in events[-12:]:
                                ui.label(event_text(event)).classes('bench-muted')

        async def select_job(job_id):
            state['job_id'] = job_id
            await poll()
            scroll_to('.bench-run')

        def remember_jobs(jobs):
            state['jobs'] = jobs
            active = next((job for job in jobs if job.get('state') in WORKING_STATES), None)
            state['active'] = bool(active)
            state['active_job_id'] = active['job_id'] if active else None

        def render_reports(jobs):
            panels['reports'].clear()
            with panels['reports']:
                if not jobs:
                    ui.label('Your completed and interrupted runs will appear here.').classes('bench-muted')
                    return
                with ui.element('div').classes('bench-report-row bench-report-head'):
                    for head in ('When', 'Run', 'Bench', 'Status', 'Report'):
                        ui.label(head)
                rows = report_rows(jobs[:30], recipes=state['catalog']['recipe'])
                for row in rows:
                    with ui.element('div').classes('bench-report-row'):
                        ui.label(row['when']).classes('bench-report-when')
                        ui.label(row['run'])
                        ui.label(row['bench']).classes('bench-badge' + (' bench-badge-real' if row['real'] else ''))
                        with ui.column().classes('gap-0'):
                            ui.label(row['status']).classes('bench-badge' + (' bench-badge-ok' if row['status'] == 'Complete' else ' bench-badge-partial'))
                            if row['points']:
                                ui.label(row['points']).classes('bench-muted')
                            if row['waiting']:
                                ui.label(row['waiting']).classes('bench-muted')
                        with ui.element('div').classes('bench-actions'):
                            for label, relative in row['links']:
                                ui.link(label, artifact_url(row['job_id'], relative), new_tab=True).classes('bench-artifact')
                            ui.button('View run', on_click=lambda _=None, job_id=row['job_id']: select_job(job_id)).props('flat dense no-caps size=sm')
                            if row['regenerate']:
                                again = ui.button('Regenerate report', on_click=lambda _=None, job_id=row['job_id']: regenerate_report(job_id),
                                                  icon='refresh').props('flat dense no-caps size=sm aria-label="Regenerate report"')
                                again.tooltip('Makes a new report revision from the saved measurements; nothing is re-measured.')
                                if row['job_id'] in state['regenerate_busy']:
                                    again.disable()
                            if row['dequeue']:
                                ui.button('Remove from report queue', on_click=lambda _=None, job_id=row['job_id']: dequeue_report(job_id),
                                          icon='playlist_remove').props('flat dense no-caps size=sm')
                if len(jobs) > 30:
                    ui.label(f'Newest 30 of {len(jobs)} saved runs shown.').classes('bench-muted')

        async def refresh_reports():
            jobs = await run.io_bound(service.list_jobs)
            if client.is_deleted or jobs is None:
                return
            remember_jobs(jobs)
            state['seen'].update({job['job_id']: saved_runs_key(job) for job in jobs})
            render_reports(jobs)
            render_bar()

        def show_activity(snapshot):
            """Header spinner and phrase; hidden (idle text shown) when nothing works in the background."""
            phrase = activity_text(snapshot)
            if not phrase:
                widgets['activity'].set_visibility(False)
                widgets['idle'].set_visibility(True)
                return
            widgets['activity_text'].set_text(phrase)
            started = snapshot.get('created_utc')
            detail = str(snapshot.get('dut_model') or 'Converter test')
            if elapsed_text(started):
                detail += ' · started ' + local_time_text(started) + ' · elapsed ' + elapsed_text(started)
            widgets['activity_detail'].set_text(detail)
            widgets['idle'].set_visibility(False)
            widgets['activity'].set_visibility(True)

        async def note_transitions(snapshots):
            """Reports bookkeeping from the poll: refresh the saved-runs list when a polled job's
            state or report links changed since the page last showed it; announce a report that
            became available. Nothing happens on ticks without a change."""
            stale = False
            for snapshot in snapshots:
                key = saved_runs_key(snapshot)
                previous = state['seen'].get(snapshot['job_id'])
                state['seen'][snapshot['job_id']] = key
                stale = stale or previous != key
                if report_became_ready(previous, key):
                    notify('Report ready: ' + str(snapshot.get('run_id') or snapshot['job_id']), type='positive', timeout=10000)
            if stale:
                await refresh_reports()

        async def poll():
            """Every tick follows the bench, not a job id this tab happens to hold.

            A cheap service.active_job() (job.json records only) says which job is
            working or waiting for its report; a tab with no job attaches to it (F5,
            a second tab, a job started from the CLI), the header, the lock and
            Start follow it even while an older run is displayed, and the lock
            releases when it ends.
            """
            if state['polling']:
                return
            state['polling'] = True
            try:
                bench = await run.io_bound(service.active_job)
                if client.is_deleted:
                    return
                if state['job_id'] is None and bench:
                    state['job_id'] = bench['job_id']
                job_id = state['job_id']
                if job_id is None:
                    if state['active']:
                        state['active'], state['active_job_id'] = False, None
                        render_bar()
                    show_activity(None)
                    render_stop(None)
                    return
                snapshot = await run.io_bound(service.status, job_id)
                if client.is_deleted or snapshot is None or state['job_id'] != job_id:
                    return
                busy = None
                if bench and bench['job_id'] != job_id and bench['state'] in ('queued', 'acquiring', 'reporting'):
                    busy = await run.io_bound(service.status, bench['job_id'])
                    if client.is_deleted or busy is None or state['job_id'] != job_id:
                        return
                working = busy if busy and busy.get('state') in WORKING_STATES else snapshot
                state['active'] = working.get('state') in WORKING_STATES
                state['active_job_id'] = working['job_id'] if state['active'] else None
                render_bar()
                show_status(snapshot)
                # The indicator and Stop follow whichever job is working (or waiting for its report), even
                # while an older run is displayed.
                show_activity(working if activity_text(working) else snapshot)
                render_stop(working if 'stop' in job_actions(working) else snapshot)
                await note_transitions([snapshot] + ([busy] if busy else []))
            except (ValueError, OSError, RuntimeError) as exc:
                if state['job_id'] is None:
                    return
                panels['run'].clear()
                panels['run'].set_visibility(True)
                with panels['run']:
                    ui.label('Could not refresh run status: ' + str(exc)).classes('bench-message bench-warning')
                    ui.label('The worker owns the instruments independently. Refreshing this page does not restart it.').classes('bench-muted')
            finally:
                state['polling'] = False

        # --- layout -------------------------------------------------------------------------------

        fix_selection()
        await refresh_feasibility()
        with ui.element('header').classes('bench-header'):
            with ui.element('div').classes('bench-header-inner'):
                with ui.column().classes('gap-0'):
                    ui.label('DC–DC Bench').classes('bench-title')
                    ui.label('One page: converter → bench → test → Preview → Start.').classes('bench-subtitle')
                with ui.element('div').classes('bench-status-area'):
                    widgets['idle'] = ui.label('Idle — no job running').classes('bench-idle').props('role=status')
                    with ui.row().classes('bench-activity items-center gap-3').props('role=status aria-live=polite') as activity:
                        ui.spinner(size='sm', color='primary')
                        widgets['activity_text'] = ui.label('').classes('bench-activity-text')
                        widgets['activity_detail'] = ui.label('').classes('bench-muted')
                    activity.tooltip('Work in progress on the bench computer. Click to show the run.')
                    activity.on('click', lambda: scroll_to('.bench-run'))
                    activity.set_visibility(False)
                    widgets['activity'] = activity
                    panels['stop'] = ui.element('div').classes('bench-stop')
                    panels['stop'].set_visibility(False)
        with ui.column().classes('bench-shell gap-0'):
            panels['summary'] = ui.element('div').classes('bench-summary')
            with ui.column().classes('bench-question w-full gap-0') as section:
                panels['converters_section'] = section
                with ui.element('div').classes('bench-h2'):
                    ui.label('1').classes('bench-num')
                    ui.label('Which converter?')
                panels['converters'] = ui.element('div').classes('bench-cards')
                panels['editor_dut'] = ui.column().classes('bench-editor gap-3 mt-3')
                panels['editor_dut'].set_visibility(False)
            with ui.column().classes('bench-question w-full gap-0') as section:
                panels['bench_section'] = section
                with ui.element('div').classes('bench-h2'):
                    ui.label('2').classes('bench-num')
                    ui.label('Simulated or real bench?')
                panels['bench'] = ui.element('div').classes('w-full')
            with ui.column().classes('bench-question w-full gap-0') as section:
                panels['tests_section'] = section
                with ui.element('div').classes('bench-h2'):
                    ui.label('3').classes('bench-num')
                    ui.label('Which test?')
                panels['tests'] = ui.column().classes('w-full gap-2')
                panels['editor_recipe'] = ui.column().classes('bench-editor gap-3 mt-3')
                panels['editor_recipe'].set_visibility(False)
            panels['plan'] = ui.column().classes('bench-panel bench-plan gap-3 mt-6')
            panels['plan'].set_visibility(False)
            panels['confirm'] = ui.column().classes('w-full gap-0 mt-4')
            panels['confirm'].set_visibility(False)
            panels['run'] = ui.column().classes('w-full gap-0 bench-run-section')
            with panels['run']:
                ui.label('Run').classes('bench-h2')
                ui.label('Start a previewed test or open a saved run from Reports.').classes('bench-muted')
            with ui.column().classes('w-full gap-0'):
                with ui.element('div').classes('bench-h2'):
                    ui.label('Reports')
                    with ui.row().classes('items-center gap-2').style('margin-left:auto'):
                        ui.label('Times are local').classes('bench-lbl')
                        ui.button('Refresh saved runs', on_click=refresh_reports, icon='refresh').props('flat dense no-caps size=sm aria-label="Refresh saved runs"')
                panels['reports'] = ui.column().classes('bench-reports gap-0')
            ui.label('Local bench control · Data stays in your workspace · Closing this tab does not restart or cancel acquisition.').classes('bench-muted mt-6')
            ui.label(time_legend()).classes('bench-muted')
            with ui.row().classes('gap-5 flex-wrap'):
                ui.link('Sensor placement editor — add photographs and sensor markers to a finished run', '/annotations').classes('bench-artifact')
                ui.link('Glossary — path efficiency, qualified, revision, lease, SYNTHETIC and the other words on this page', '/glossary').classes('bench-artifact')
        panels['dialogs'] = ui.element('div')
        with ui.element('div').classes('bench-bar'):
            with ui.element('div').classes('bench-bar-inner'):
                widgets['bar_summary'] = ui.label('').classes('bench-bar-summary')
                with ui.element('div').classes('bench-bar-actions'):
                    widgets['preview'] = ui.button('Preview', on_click=preview_test, icon='fact_check').props('outline no-caps aria-label="Preview"')
                    widgets['start'] = ui.button(START_LABELS['mock'], on_click=start_pressed, icon='play_arrow').props('unelevated no-caps')
                    widgets['start'].disable()
                widgets['start_hint'] = ui.label('').classes('bench-bar-hint').props('role=status')
        render_summary()
        render_converters()
        render_bench()
        render_tests()
        render_bar()
        remember_jobs(jobs)
        state['seen'].update({job['job_id']: saved_runs_key(job) for job in jobs})
        render_reports(jobs)
        render_bar()
        # Attach to whatever the bench is doing, including a job whose report is still queued.
        active = bench_job(jobs)
        if active:
            state['job_id'] = active['job_id']
            await poll()
        ui.timer(2.0, poll)

    ui.run(host=host, port=port, reload=False, show=False, title='DC–DC Bench',
           reconnect_timeout=30.0, fastapi_docs=False)
