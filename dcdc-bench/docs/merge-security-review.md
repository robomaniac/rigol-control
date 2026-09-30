# Merge security review: attachments, annotation editor, publication, doctor, PDF check, dispatcher

Independent defensive review of the surfaces merged into `dcdc-bench-hardening` at
`0ec41fd` ("Integrate the nine parallel increments and settle their seams").
Method: read and trace every listed module and its tests, then confirm suspected
weaknesses with small standalone Python probes against the real validators and
the real `publish_run`/NiceGUI route table (no pytest, no renders, no UI server,
no instruments). Probe inputs are quoted inline so each finding can be re-run.

## Threat model as understood

Owner-operated bench software on a Raspberry Pi (≈900 MiB RAM). Attackers are
not remote: the UI binds to loopback and is Host-checked. What is untrusted:

1. **Files imported into reports** (PNG/JPEG/SVG/PDF photographs, schematics,
   datasheets from vendors, phones, colleagues) — may carry active content,
   external references, decompression bombs, hostile metadata.
2. **Free text reaching HTML/PDF/CSV** — captions, marker labels, sensor IDs,
   run notes, file names, instrument `*IDN?` replies.
3. **Path handling on a shared filesystem** — job IDs, relative artifact paths,
   manifest paths, symlinks planted in run folders, lock files.
4. **Local network requests to the UI** — anything that can reach
   `127.0.0.1:8082` (other local users/processes, a browser tab that is
   attempting DNS rebinding, SSH-forwarded clients).
5. **Accidental disclosure in published copies** — instrument endpoints,
   serials, home paths, hostnames, private photographs, EXIF, embedded JSON.
6. **Read-only instrument diagnosis** — must never write to an instrument.

Assumption inherited from the existing design and *not* changed by this merge:
every client that can reach loopback is a trusted operator (there is no
authentication; see Info I1).

## Findings

Severity reflects impact under the model above. Line numbers refer to
`dcdc-bench/src/dcdc_bench/...` at `0ec41fd`.

### Critical

None found.

### High

#### H1. Publication allowlist bypass: the sensor-placement print figure embeds the whole photograph

* `reporting/sensor_placement.py:65-91` (`static_overlay_svg`) writes the
  original image as a `data:<media_type>;base64,…` URI into
  `reports/<rev>/figures/sensor-placement.svg` (called from
  `with_sensor_placement`, lines 136-138).
* `publish.py:39` lists `.svg` in `TEXT_SUFFIXES`; `publish.py:295-312` copies
  every `figures/*.svg` as "text with redaction", irrespective of
  `approval.attachments`.
* `publish.py:251-262` builds the allowlist universe from
  `attachments/manifest.json` only, so an asset added after finalisation
  (documentation revision, i.e. every editor upload) cannot be allowlisted at
  all.
* `publish.py:40-41` publishes `annotations.json` (fine) but never `assets/`,
  so the published `report.html` `<img src="assets/<sha>.png">` is broken.

Scenario: the operator uploads a private lab photograph through the editor,
places markers, renders r0002, then publishes with `attachments: []` to withhold
the photo. The photo ships anyway inside `figures/sensor-placement.svg`, the
publication manifest records the SVG as an ordinary redacted text file, lists
nothing about the photograph under `excluded`, and the HTML shows a broken
image. JPEG originals carry EXIF (GPS, device serial) verbatim inside the
base64 payload.

Evidence (probe: finalized `RunStore`, `AssetStore.add(png, "private-lab-photo.png")`,
`with_sensor_placement`, minimal `report.html`, approval with `attachments: []`):

```
documentation-revision asset id: asset-211723ff87adf8d5 | listed in acquisition manifest: False
published files with an EMPTY attachment allowlist: ['annotations.json', 'figures/sensor-placement.svg', 'publication_manifest.json', 'report.html']
figures/sensor-placement.svg embeds the photograph bytes verbatim: True
manifest records the SVG as an ordinary redacted text file: reports/r0001/figures/sensor-placement.svg
manifest 'excluded' entries mentioning attachments: []
published HTML points at assets/<sha>.png: True | any assets/ file published: False
allowlisting the documentation-revision asset: Approval allowlists attachment IDs that are not in the run: asset-211723ff87adf8d5
```

Fix:
1. In `publish_run`, treat any SVG (or any text file) containing
   `data:image/` as binary-bearing: exclude it unless the referenced asset hash
   (`annotations.json` → `image_asset_sha256`) is allowlisted, and record the
   decision in `excluded`/`files`.
2. Build `by_id` from `AssetStore(run_dir).assets()` (acquisition manifest plus
   latest documentation revision) so editor uploads can be allowlisted; record
   which revision listed each asset.
3. When the sensor-placement image is allowlisted, publish `assets/<sha>.<ext>`
   (hash re-verified) so the HTML is not broken; when it is not, strip the
   `<img>`/figure or replace it with an explicit "withheld" placeholder.
4. Strip EXIF/APP segments from published photographs (or at minimum record
   `metadata_retained: true` in the manifest) — see M7.

### Medium

#### M1. Text redaction corrupts the embedded Plotly runtime in the published HTML

* `publish.py:34` `LOCAL_HOSTNAME` matches `\b<label>\.(local|lan|home|internal|localdomain)\b`.
* `publish.py:288` runs `_publish_text` over the whole `report.html`, which
  embeds `plotly.min.js` inline (`reporting/renderer.py:1438-1441`).

Evidence (grep over the shipped `plotly/package_data/plotly.min.js`, and the
publish probe over `plotly.offline.get_plotlyjs()`):

```
plotly.min.js: LOCAL_HOSTNAME matches 156x, e.g. ['z.local', 'z.local', ...]
     43 this.local      21 ua.local      10 lp.local      10 z.local      5 Ya.home ...
){var i=this._validate(e,t,r,ua.local.invalidDate||ua.regionalOptio
```

Every `this.local`, `ua.local`, `Ya.home` becomes `[REDACTED:hostname]`: the
published interactive report's JavaScript breaks at runtime, and the manifest
inflates `totals.hostname` by ≥156 fake hits, masking real ones. The unit test
uses a 400-byte synthetic HTML, so this is invisible to the suite.

Fix: do not redact inside `<script id="dcdc-plotly-runtime">…</script>` (split
the document on that element and verify the runtime's SHA-256 is unchanged);
alternatively require the hostname label to contain a hyphen or digit or be
preceded by whitespace/`:`/`/`/quote rather than `.`-chained identifiers.
Add a regression test that publishes a real rendered `report.html` and asserts
`window.dcdcReport` still initialises (or that the runtime bytes are byte-identical).

#### M2. Upload size is enforced only in the browser; the server reads the whole body into memory before validation

* `annotation_editor.py:343-345` passes `max_file_size=max(BYTE_LIMITS.values())`
  to `ui.upload` — this is the Quasar `max-file-size` prop, evaluated client-side.
* `annotation_editor.py:286` `data = await e.file.read()` runs before
  `validate_asset` checks `len(data)` (`attachments.py:269`).
* NiceGUI 3.17.1 `elements/upload_files.py:create_file_upload` spools anything
  over 1 MiB to a temp file with no ceiling; `LargeFileUpload.read()` returns
  the entire file as one `bytes`. Starlette's `max_part_size` applies to
  non-file fields only.

Scenario: any loopback client that has loaded `/annotations` (the upload URL
`/_nicegui/client/<uuid>/upload/<id>` is in the page) posts a multi-GB body with
curl; the UI process fills `/tmp`, then attempts to hold it in RAM on a host
with ~150 MiB available and is OOM-killed while it may be supervising a
report worker. The operator can also trigger it by accident from a non-browser
client. The brief (§16) requires size validation; the test suite only checks
`BYTE_LIMITS` against bytes already in memory.

Fix: call `e.file.size()` (available on both `SmallFileUpload` and
`LargeFileUpload`) and refuse before `read()`; better, stream with
`e.file.iterate()` into a bounded buffer that aborts past `max(BYTE_LIMITS)`.
Add an ASGI request-body limit for the upload route.

#### M3. PDF validator: allowlist gaps and CPU amplification under the service lock

* `attachments.py:59-60` forbids `/JS /JavaScript /OpenAction /Launch /AA` and
  `/S` ∈ `{JavaScript, Launch, SubmitForm, ImportData, Rendition}`.
* Not covered: `/XFA` (XFA forms carry JavaScript inside an XML stream that the
  key scan cannot see), `/GoToR`/`/GoToE` (remote/embedded go-to; opens other
  files, UNC paths on Windows viewers), `/URI` actions (tracking beacons when
  the operator clicks), `/RichMedia`/`/3D`/`/Movie`/`/Sound` annotations,
  `/EmbeddedFiles` (arbitrary attached payloads).
* `job_service.py:411-419` runs the whole validation inside `self.lock`, so a
  slow PDF blocks `start`, `preview`, `save_profile`, `retry_report` and the
  2-second `dispatch_reports` timer.

Evidence (probes with hand-built PDFs):

```
ACCEPTED   XFA form with embedded JavaScript
ACCEPTED   /GoToR remote file action
ACCEPTED   /URI link (tracking beacon)
ACCEPTED   /RichMedia annotation
ACCEPTED   /EmbeddedFiles attachment
ACCEPTED   ObjStm pad=8,000,000 compressed size=8,216 bytes
           peak RSS delta ~0 MiB, 6.42s; ratio 974:1
```

pypdf's per-stream ceiling (`zlib_maximum_output_length = 75_000_000`) bounds
memory, but parsing 8 MiB of inflated whitespace took 6.4 s; a 25 MiB upload
can hold hundreds of such object streams that the traversal must resolve, i.e.
tens of minutes to hours of CPU while the lock is held.

Fix: add `/XFA`, `/RichMedia`, `/EmbeddedFiles`, `/EF`, `/GoToR`, `/GoToE`,
`/Movie`, `/Sound`, `/3D` to the rejected keys/subtypes (decide `/URI` policy
explicitly and document it); validate before taking `self.lock` (store under
the lock); enforce a wall-clock budget (e.g. 10 s) around `_inspect_pdf` via a
worker thread with timeout, and count resolved object streams.

#### M4. The `/{filename}` catch-all shadows the new `/annotations` page when `--report-root` is given

* `ui.py:137-142` registers `GET /{filename}` (published legacy files) before
  `ui.py:145-146` registers the editor page; FastAPI matches in registration
  order. `docs/bench-ui.md:29` documents launching with `--report-root Data`.

Evidence (route probe: `run_ui(tmp, report_root=tmp/"reports")` with `ui.run`
suppressed, then `route.matches()`):

```
   /jobs/{job_id}/files/{relative:path} ['GET']
   /Runs/{relative:path} ['GET']
   /{filename} ['GET']
   /annotations ['GET']
   / ['GET']
FIRST FULL MATCH for GET /annotations -> route /{filename} endpoint published_legacy_file
```

Result: `GET /annotations` returns 404 "Published file not available" in the
documented configuration; the Host check still applies (middleware), but the
editor is unreachable and any future single-segment page will be shadowed too.

Fix: register `register_annotation_editor` and `bench_page` before the
`report_root` routes, or serve legacy files from an explicit prefix.
Add a route-order test (the probe above is ~20 lines and needs no server).

#### M5. SVG validator misses CSS escape sequences and animated style values

* `attachments.py:57-58` `_UNSAFE_CSS` matches the literal tokens `@import`,
  `url(`, `expression(`, `javascript:`; CSS decodes `\75rl(` as `url(` and
  `@\69mport` as `@import`.
* `attachments.py:204-205` checks animation elements only for
  `attributeName` targeting `href`; `to`/`values`/`from`/`by` on
  `<animate attributeName="style">` are not scanned.

Evidence:

```
ACCEPTED   CSS escape \75rl in <style>: width=10 height=10
ACCEPTED   CSS escape \75rl inline style: width=10 height=10
ACCEPTED   CSS @\69mport: width=10 height=10
ACCEPTED   animate attributeName=style to url(): width=10 height=10
```

Impact: external fetches (IP/tracking leak) when the SVG is opened as a
document from the local UI or processed by a CSS-aware renderer; no script
execution (CSS cannot run script in current browsers) and no effect in
`<img>` mode. Combined with M6 the document-mode case is same-origin with the
instrument UI.

Fix: reject any backslash inside `<style>` text or `style=` attributes (no
legitimate SVG stylesheet needs one), or decode CSS escapes before matching;
apply `_UNSAFE_CSS` and the href policy to `to`, `from`, `by`, `values` of
`animate`/`set`; consider dropping `<style>` support entirely for uploads.

#### M6. Uploaded SVG/PDF originals are served same-origin with no sandbox

* `ui.py:102-108` sets `X-Content-Type-Options: nosniff` and `Cache-Control`
  for every job file, but `Content-Security-Policy: sandbox …` only for `.html`.
  `/jobs/<id>/files/run/attachments/originals/<sha>.svg` is therefore a
  same-origin SVG document when opened directly; any validator bypass (M5 or a
  future one) becomes script running in the instrument-control origin, which
  can drive the NiceGUI socket (the preview exposes the serials that `start()`
  requires, `ui.py:478` / `job_service.py:302`). PDFs render in the browser's
  viewer with the same origin.

Fix: for non-HTML files under `attachments/`, add
`Content-Security-Policy: sandbox` (no `allow-scripts`) and
`Content-Disposition: inline; filename="<sha>.<ext>"`; these headers are
ignored for `<img>` loads so the editor keeps working.

#### M7. Allowlisted photographs and the print SVG are published with all metadata

* `publish.py:337` copies the original bytes verbatim (`shutil.copyfile`); the
  manifest warns "not text-redacted" but says nothing about EXIF. Phone JPEGs
  routinely carry GPS position, capture time, device model/serial and
  thumbnail; H1 ships the same bytes inside `figures/sensor-placement.svg`.

Fix: re-encode published raster images without metadata (Pillow `getdata()`
round-trip or drop APP1/APPn segments), record `sha256_published` of the
stripped copy and `metadata_stripped: true`; or refuse publication of JPEGs
with an EXIF/GPS IFD unless the approval sets `keep_image_metadata: true`.

### Low

#### L1. `OverflowError` escapes the attachment validator's exception contract

* `attachments.py:160` `int(round(float(...)))` on a 400-digit width and
  `attachments.py:212-214` (`except ValueError` only) for `viewBox` values like
  `9e999`/`inf` raise `OverflowError`, not `AttachmentRejected`.
* `annotation_editor.py:300-303` catches `AttachmentRejected, ValueError,
  OSError, RuntimeError, LookupError` — an `OverflowError` propagates into
  NiceGUI's `handle_event`, is logged server-side and the operator gets no
  notification. `job_service.add_attachment` releases its lock via the context
  manager, so no lock leak.

Evidence:

```
!!EXCEPTION width 400-digit integer: OverflowError: cannot convert float infinity to integer
!!EXCEPTION viewBox 9e999: OverflowError: cannot convert float infinity to integer
!!EXCEPTION viewBox inf: OverflowError: cannot convert float infinity to integer
ACCEPTED   viewBox nan: width=None height=None
```

Fix: in `_svg_length` and the viewBox branch, check `math.isfinite` and catch
`(ValueError, OverflowError)`; reject `nan`/`inf` explicitly with reason
`dimensions`. Optionally catch `Exception` in `handle_upload` and notify.

#### L2. `include_pdf: true` publishes an unredacted PDF under a flag that does not say so

* `publish.py:313-320` copies `report.pdf` verbatim; the PDF contains the same
  serials, endpoints and paths as the HTML (the fixture even puts a serial in
  it), plus producer metadata. The manifest warning is correct but the approval
  field name invites misuse.

Fix: rename to `include_unredacted_pdf` (or require both `include_pdf` and
`acknowledge_pdf_unredacted: true`), and refuse when the HTML redaction totals
are non-zero unless acknowledged.

#### L3. Publication follows symlinks for report files

* `publish.py:282-292, 299-311`: `source.is_file()` and `read_text()` follow
  symlinks; only attachments get `_inside` (line 330). A symlink planted at
  `reports/r0001/figures/x.svg -> ~/.ssh/id_ed25519` (shared filesystem,
  another account with write access to the run tree) is published as text with
  path redaction.

Fix: refuse `source.is_symlink()` and require `_inside(source, report_dir)`
for every published file.

#### L4. Approval YAML: recursion and alias expansion are not bounded by the 200 kB size limit

* `publish.py:82-90`: `yaml.safe_load` is correct (no code execution), but a
  3000-deep nested list raises `RecursionError` (not caught; traceback instead
  of the "invalid approval" message). A 9-level alias amplification
  (`&a [x×9]`, `&b [*a×9]`, …, `attachments: *i`) did not complete in 120 s and
  had to be terminated — most likely pydantic formatting the expanded input in
  its error message. Owner-supplied file, so availability only.

Evidence: `!!EXCEPTION nesting 3000: RecursionError: maximum recursion depth exceeded`;
alias-amplification probe terminated after 120 s without output.

Fix: refuse `&`/`*` anchors and aliases in the approval text (a flat record
never needs them), catch `RecursionError`/`yaml.YAMLError` into `ValueError`,
and pre-check `attachments` is a list of ≤ 100 short strings before pydantic.

#### L5. `doctor --out` can overwrite any file outside run folders

* `doctor.py:390-395, 467`: `diagnostics_dir(out.parent)` only refuses run
  folders; `atomic_json(target, …)` then replaces whatever `--out` names
  (a saved profile, `jobs/<id>/job.json`, `approval.yaml`). Operator CLI, so
  mistake-level risk; the diagnosis also contains endpoints and serials, so an
  `--out` under a published or synced folder leaks them.

Fix: require `.json` suffix, refuse existing targets unless `--force`, and
refuse targets inside `workspace/`, `profiles/` or any `publication_manifest.json`
folder.

#### L6. Captions and labels accept Unicode bidi and zero-width controls

* `attachments.py:298` and `annotations.py:60` reject only C0 controls and DEL.
  U+202E (RLO), U+2066 (isolate) and U+200B pass and visually reorder the
  caption/table cell in HTML and PDF ("Trojan source" style); no injection.

Evidence: `'Case top ‮RLO reversed' -> accepted`, `'zero​width' -> accepted`.

Fix: reject `unicodedata.category(ch) in {"Cc", "Cf"}` except `\n`, `\t`.

#### L8. The documented approval example is rejected: unquoted `date` becomes a YAML date object

* `docs/doctor-and-publication.md:141` shows `date: 2026-09-27   # calendar date`.
  PyYAML resolves an unquoted ISO date to `datetime.date`; `publish.py:56`
  declares `date: str` under `strict=True`, so `PublicationApproval` rejects it
  with "Input should be a valid string". `tests/test_publish.py` never hits
  this because `yaml.safe_dump` quotes the string it is given.

Evidence: every probe file written with `date: 2026-09-28` failed with
`Approval record … is invalid: … date  Input should be a valid string`.

Impact: fail-closed (nothing is published), but an operator following the
documentation gets a confusing validation error and may "fix" it by loosening
the record. Fix: accept `date | str` and normalise to ISO text in the
validator, or quote the value in the example and say why.

#### L7. Post-exit sweep of the report process group has a PID-reuse window

* `job_service.py:610` calls `_sweep_report_group(child.pid, …)` after
  `child.wait()` has reaped the child; `resources.py:167-182` matches any live
  process whose `pgrp` or `session` equals that number. A new session leader
  that reuses the PID in that window would be SIGTERM/SIGKILLed
  (`resources.py:194-205`). Guards present: `pgid <= 1` refused, own PID
  skipped, only same-session processes otherwise. Window is milliseconds and
  sequential PID allocation makes reuse very unlikely; `cancel()` itself is
  race-free (pidfd + cmdline match, `job_service.py:513-521`).

Fix: enumerate survivors *before* reaping (poll `/proc` while `child.poll()`
is None on timeout) or compare `/proc/<pid>/stat` start time with the child's.

### Info

* **I1. Loopback = trusted.** `TrustedHostMiddleware` (`ui.py:78-79`) blocks
  DNS-rebinding Host headers and Engine.IO is same-origin (`ui.py:82`), but any
  local user/process can open the UI, read the configured serials from the
  preview (`ui.py:478`) and arm a real run. Unchanged by this merge; document
  it in `bench-ui.md`.
* **I2. pdf_check XML parsing.** `reporting/pdf_check.py:490` uses stdlib
  `ElementTree.parse` on pdftohtml output. The XML is tool-generated (text is
  escaped, no attacker-controlled markup), external DTD/entities are not
  fetched by expat, and expat 2.7.1 has amplification limits. Acceptable;
  `defusedxml` would be belt-and-braces. pdftohtml runs with `-i` and a 120 s
  timeout in a temp dir (`pdf_check.py:476-482`) — resource use is bounded;
  poppler parser bugs are contained to the report worker process.
* **I3. pypdf defences verified.** `#xx` name escapes are decoded
  (`/A#41` → rejected as `/AA`; `/J#53` → rejected), per-stream inflate cap
  75 MB, `flate_maximum_row_length` 4 MB.
* **I4. CLI argv.** `pdf-check`/`pdftohtml` receive `str(path)` after options;
  a path starting with `-` would be parsed as an option (owner CLI).
* **I5. Provenance content.** `runner._provenance()` records
  `platform.platform()` and package versions, no hostname/user; the run path is
  redacted by exact value. Bare hostnames (e.g. `raspberrypi`), public IPs,
  `/opt` `/var` `/tmp` `/data` paths, UNC `\\server\share`, MAC addresses and
  SSIDs in notes stay unredacted — matches the documented policy; consider
  adding `/tmp|/var|/opt|/srv|/data` roots and `\\\\[A-Za-z0-9._-]+\\` UNC.
* **I6. Lock files.** `activity.py:14` defaults to `<repo>/runs/.bench-activity.lock`
  (not world-writable). benchctl's `VisaTransport` lock lives in `/tmp`
  (`Software/src/benchctl/transport.py:18`, opened `a+`, no truncation) —
  pre-existing, symlink-following but not exploitable for content damage.
* **I7. MPO JPEGs.** Pillow reports multi-picture phone JPEGs as `MPO`;
  `attachments.py:150-152` then rejects them as `type_mismatch`. Functional
  false negative, not a security issue.
* **I8.** (promoted to L8: the documented example itself is rejected.)
* **I9. Redaction over base64.** Patterns need `.` or `\`, which base64 lacks;
  the print SVG payload is not corrupted (only its presence is the problem, H1).
* **I10. Validation under lock.** `job_service.add_attachment` (`:411`) holds
  the service `FileLock` for the full validation — see M3.

## Verified defenses

Confirmed by reading and, where marked (probe), by executing against the code:

* **Origin/Host.** `require_loopback` refuses non-loopback binds;
  `TrustedHostMiddleware` allowlist is app-wide, so `/annotations` and the
  NiceGUI upload route inherit it; Engine.IO `cors_allowed_origins=None`
  (same-origin); the upload URL embeds the unguessable client UUID (CSRF-safe);
  `fastapi_docs=False`.
* **Path containment.** `artifact_url` rejects `..`, absolute, backslash;
  `resolve_file` applies `_inside` twice (base and job), resolving symlinks and
  neutralising an absolute `tail` (`Path(base) / "/etc/passwd"` → outside →
  refused); `_name` regex for job IDs; `annotations.request.json` and
  `inventory.yaml` live outside the servable `run/` and `report/` roots;
  `published_file` resolves and re-checks `relative_to(root)`.
* **Content sniffing and limits.** Type decided by magic bytes, extension must
  agree; per-type byte ceilings; PNG/JPEG dimensions checked from the header
  before any decode, `verify()` without pixel decode, `DecompressionBombError`
  mapped; Pillow's own text-chunk limits apply.
* **SVG (probe).** DOCTYPE/ENTITY rejected textually before parsing (no entity
  expansion path), forbidden tags including uppercase and XHTML-namespaced
  `script`, `on*` attributes, `href` policy including `xlink:href`,
  entity-encoded `javascript:`, XInclude, nested `data:image/svg+xml`,
  `<set attributeName="href">`, `@import` without `url()`, CDATA `<style>`.
* **PDF (probe).** `/JS /JavaScript /OpenAction /Launch /AA` and `/S`
  subtypes rejected including `#`-escaped names; encrypted PDFs refused;
  object budget and visited set; pypdf 75 MB per-stream inflate cap.
* **File names (probe).** Separators, `..`, hidden/`~`, drive letters and
  control characters rejected; Unicode look-alike separators (`∕`, `／`) and
  zero-width characters collapse to `_`/removed; stored name is the SHA-256.
* **Storage integrity.** Content-addressed immutable originals; hash
  re-verified on `resolve`, `read`, `add` (existing path), and after copying
  into `reports/<rev>/assets/`; documentation revisions never rewrite
  `attachments/manifest.json` or `integrity.json`; `verify_integrity` before
  and after every `add_attachment`; atomic writes via `NamedTemporaryFile` in
  the target directory; `verify_integrity` rejects absolute/`..` manifest paths.
* **Annotations.** Exact key set, finite bounded coordinates, `sensor_id`
  regex, label length/control checks, unique IDs, hash-bound to an image-type
  original; re-validated by `services.report_run` → `annotations_file` (not
  only in the editor); a refused set creates no revision; saving always
  creates a new revision and never touches acquisition files.
* **Output escaping.** `sensor_placement_html` escapes every caption, name,
  ID and label with `html.escape(quote=True)`; numeric attributes are
  formatted; `report.js` reads `dataset` values through `Number()` and writes
  only `textContent` — no `innerHTML`; `_embedded_json` escapes `< > &` and
  U+2028/9; `_md` escapes Markdown/Typst specials; CSV `_safe_cell` prefixes
  `= + - @ \t \r`.
* **Served HTML.** `report.html` gets `Content-Security-Policy: sandbox
  allow-scripts allow-downloads allow-popups`, `nosniff`, `no-store`.
* **Publication gate.** Missing approval → refuse; strict pydantic model
  (`extra="forbid"`, `strict=True`); run ID and revision must match; unknown
  allowlist IDs refused; attachment hash re-verified and `_inside(originals)`;
  output cannot be inside the run folder; target immutable; never writes to
  the run; no subprocess/network (test-enforced); `noindex` retained unless
  `public: true`; manifest records counts and field names, never values;
  `NEVER_PUBLISHED` list is accurate for raw/, scpi.jsonl, request/plan/run.
* **Doctor.** `ReadOnlyTransport.write` always refuses; `query` requires exact
  membership in the allowlist (no prefix matching); `SYST:ERR?`, `*CLS`,
  `*RST`, `*ESR?` absent; benchctl `VisaTransport.open()` only opens the VISA
  resource and sets the timeout (no `clear()`/write), `close()` only closes;
  per-instrument `flock` fails closed if an acquisition owns the instrument;
  drivers' `check_errors` proven unused by the tests; cadence bounded
  1–120 s / 0.01–5 s and refused unless all outputs read OFF; diagnostics
  refuse run folders; `dcdc-bench/diagnostics/` is git-ignored.
* **Dispatcher.** One app-level timer under the service lock; memory gate and
  bench lease checked before launch; `cancel()` verifies `/proc/<pid>/cmdline`
  contains the module and job path and signals through a pidfd (no PID reuse);
  `killpg` only targets a child started with `start_new_session=True`;
  `terminate_group` refuses pgid ≤ 1 and skips its own PID.
* **pdf_check.** Structure-tree recursion capped at depth 96; every extraction
  failure becomes a finding rather than a pass; subprocess timeout and scratch
  dir cleanup.

## Gaps in test coverage

* `tests/test_publish.py` uses a synthetic run without sensor placement, a
  400-byte HTML and no documentation revision: it cannot see H1, M1 or M7.
  Needed: publish a run whose revision has `annotations.json` markers and a
  real rendered `report.html`; assert the photo is absent unless allowlisted,
  the plotly runtime bytes are unchanged, and documentation-revision IDs can
  be allowlisted.
* No server-side upload-size test; `test_byte_limits_apply_per_media_type`
  only exercises bytes already in memory (M2).
* No route-order test; `tests/test_ui.py` covers `published_file` and CLI
  forwarding but never builds the app (M4). The probe used here needs no
  server and would fit in `test_ui.py`.
* SVG tests lack CSS escapes, animation `to/values`, and huge/`inf`/`nan`
  numeric attributes (M5, L1).
* PDF tests cover JS/OpenAction/Launch/encrypted only; none for `#`-escaped
  names (a verified defense that should stay pinned), XFA, GoToR, URI,
  EmbeddedFiles, RichMedia, or object-stream inflation/timing (M3).
* `file_response` headers are untested for any suffix (M6).
* No approval-YAML tests for anchors/aliases, merge keys, unquoted dates,
  deep nesting (L4, L8); a test that loads the exact example block from
  `docs/doctor-and-publication.md` would have caught L8.
* No symlink tests for `publish_run` or `resolve_file` (L3).
* No `doctor --out` overwrite test (L5).
* No bidi/zero-width text test (L6).
* `attachments.py:409-427` (add after finalisation) is well covered; the
  pre-finalisation branch and duplicate-content branch are covered; the
  `existing path with different content` branch is covered.
* No test asserts that `_provenance()`/`build_manifest.json` contain no
  hostname or user name (currently true by construction).

## Reproduction notes

All probes were plain Python run with
`PYTHONPATH=dcdc-bench/src:Software/src .venv/bin/python <probe>` from the
worktree; none imported the UI server or touched instruments or `runs/`:

* SVG/filename/caption probe: `validate_asset()` / `normalize_filename()` /
  `_check_text()` with the inputs quoted under M5, L1, L6 and the verified list.
* PDF probe: hand-written PDFs (`/A#41`, `/J#53`, `/S /Java#53cript`), pypdf
  `PdfWriter` documents with `/AcroForm /XFA`, `/GoToR`, `/URI`, `/RichMedia`,
  `/EmbeddedFiles`, and a PDF 1.5 object stream holding the catalog padded with
  8 MB of spaces before FlateDecode (8,216 bytes compressed).
* Publication probe: `RunStore` finalize → `AssetStore.add(png)` →
  `with_sensor_placement` → `publish_run` with `attachments: []`, then with the
  revision asset ID; regex sweep of `plotly.offline.get_plotlyjs()`.
* Route probe: `nicegui.ui.run` and `app.timer` replaced with no-ops,
  `run_ui(tmp_workspace, report_root=tmp_reports)`, then `route.matches()` for
  `GET /annotations`.
* YAML probe: six small approval files through `load_approval()`; the
  alias-amplification case was terminated after 120 s.

## Resolution

Written 2026-09-30 by an agent role from `git show 2582508` and the current
tree, not by the reviewer above. The fixes landed in commit `2582508`
("Salvage the security-review fixes left uncommitted in worktree abeda9ea",
2026-09-28), merged into `dcdc-bench-hardening` as `bcdc58f`; ten files, 938
insertions, with new cases in `tests/test_attachments.py`,
`tests/test_annotation_editor.py`, `tests/test_doctor.py`,
`tests/test_publish.py` and `tests/test_ui.py`. Per finding:

| Finding | Addressed in `2582508`? | What the commit did |
| --- | --- | --- |
| H1 publication allowlist bypass (print figure embeds the photograph) | Yes | `publish.py`: the sensor-placement print SVG and the `reports/<rev>/assets` copies follow the attachment allowlist; a withheld image is replaced by a placeholder; the allowlist universe includes documentation-revision assets. |
| M1 text redaction corrupts the Plotly runtime | Yes | `publish.py`: the inline Plotly runtime is left byte-identical only when its SHA-256 matches `build_manifest.plotly_js_sha256`; the `LOCAL_HOSTNAME` pattern skips JavaScript member access. |
| M2 upload size enforced only in the browser | Yes | `annotation_editor.py`: `read_upload()` checks the byte limit server-side before assembling the body; `ui.py`: `RequestBodyLimit` ASGI middleware answers 413 or disconnects above the attachment ceiling. |
| M3 PDF validator allowlist gaps and CPU amplification under the lock | Yes | `attachments.py`: a 10 s wall-clock budget and a 4 MiB per-stream inflate cap (`pdf_too_complex`); allowlist extended to `/XFA`, `/EmbeddedFiles`, RichMedia, 3D, Movie, Sound, FileAttachment; external actions (`/GoToR`, `/GoToE`, `/URI`) refused; `job_service.py` validates before taking the service lock (also I10). |
| M4 `/{filename}` catch-all shadows `/annotations` | Yes | `ui.py`: the `/annotations` page is registered before the catch-all. |
| M5 SVG validator misses CSS escapes and animated style values | Yes | `attachments.py`: CSS escape and comment normalisation before the unsafe-CSS scan; animations may not retarget `style` or animate towards `url()`. |
| M6 uploaded SVG/PDF served same-origin without a sandbox | Yes | `ui.py`: `file_headers()` gives non-HTML documents a script-less sandbox and uploaded documents `Content-Disposition: attachment`. |
| M7 photographs published with all metadata | Yes | `publish.py`: published PNG/JPEG are re-encoded without EXIF, GPS, ICC or text chunks. |
| L1 `OverflowError` escapes the validator | Yes | `attachments.py`: SVG dimensions must be finite. |
| L2 `include_pdf: true` publishes an unredacted PDF under a flag that does not say so | **No** | The approval field is still `include_pdf`; the manifest warning "binary copied verbatim under include_pdf approval; not text-redacted" is the only guard. Rename or acknowledgement flag still open. |
| L3 publication follows symlinks | Yes | `publish.py`: symlinked report files are refused. |
| L4 approval YAML recursion and alias expansion unbounded | Yes | `publish.py`: the loader refuses anchors, aliases and deep nesting and caps attachments at 100. |
| L5 `doctor --out` can overwrite any file | Yes | `doctor.py`: `--out` must name a new `.json` file, never overwrites, and is refused inside a publication copy. |
| L6 captions and labels accept bidi and zero-width controls | **No** | `attachments.py` and `annotations.py` still reject only C0 controls and DEL; U+202E, U+2066 and U+200B pass. Still open. |
| L7 PID-reuse window in the post-exit sweep | **No** | `job_service.py` still calls `_sweep_report_group(child.pid, …)` after `child.wait()`. Judged very unlikely (sequential PID allocation, same-session guard); still open. |
| L8 documented approval example rejected (unquoted `date`) | Yes | `publish.py`: the loader accepts the documented unquoted date. |
| I1–I10 | Informational | I10 is covered by the M3 change (validation before the lock). I1 (every client on loopback is a trusted operator; no authentication) is **not yet** stated in `bench-ui.md`, which says only that the server listens on loopback; the others recorded no change. |

Focused runs recorded in the commit message: `test_attachments` 46 passed,
`test_annotation_editor` 8, `test_doctor` 16, `test_publish` 34, `test_ui` 32.
The three open Lows (L2, L6, L7) are policy or hardening items with no
exploit on the loopback-only bench; they stay listed here until fixed.
