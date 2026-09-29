"""Content-addressed evidence assets with import hygiene.

Originals live at ``attachments/originals/<sha256>.<ext>`` and are never
rewritten. Before acquisition finalization an accepted asset is listed in
``attachments/manifest.json``; afterwards it is listed in a new documentation
revision ``attachments/revisions/<n>.json`` so the finalized acquisition
manifest and ``integrity.json`` stay byte-identical (brief 8.4).

Every import is validated by content, not by extension: allowlisted media
types, byte and pixel limits, normalized file names without path components,
SVG without active content or external references, and PDF without
JavaScript, open or launch actions (brief 16). Rejections are typed errors
with a stable ``reason`` code so callers can report them without guessing.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
import unicodedata
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .storage import PersistenceError, atomic_json

SCHEMA_VERSION = "1.0"
MEDIA_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "application/pdf": "pdf"}
EXTENSIONS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
              "svg": "image/svg+xml", "pdf": "application/pdf"}
IMAGE_TYPES = ("image/png", "image/jpeg", "image/svg+xml")
# Byte ceilings per media type. Photographs from a phone camera fit easily;
# nothing here needs a raw sensor dump. Tests lower these through monkeypatch.
BYTE_LIMITS = {"image/png": 25 * 1024 * 1024, "image/jpeg": 25 * 1024 * 1024,
               "image/svg+xml": 2 * 1024 * 1024, "application/pdf": 25 * 1024 * 1024}
MAX_DIMENSION = 12_000
MAX_PIXELS = 40_000_000
MAX_FILENAME = 120
MAX_CAPTION = 2000
MAX_PDF_OBJECTS = 200_000
# Wall-clock budget for one PDF inspection and the inflated size any single
# stream may reach while objects are resolved (pypdf's default is 75 MB). A
# 25 MB upload could otherwise hold hundreds of object streams that each take
# seconds to tokenize; callers must not hold a service lock meanwhile.
PDF_INSPECT_SECONDS = 10.0
MAX_PDF_STREAM_BYTES = 4 * 1024 * 1024
OWNER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.@:-]{0,99}")

_SVG_FORBIDDEN_TAGS = frozenset({"script", "foreignobject", "iframe", "object", "embed", "handler",
                                 "audio", "video", "frame", "frameset"})
_SVG_ANIMATION_TAGS = frozenset({"animate", "set", "animatetransform", "animatemotion", "discard"})
_SVG_HREF_NAMES = frozenset({"href", "xlink:href"})
# Animations may neither retarget references nor whole style declarations,
# and the values they animate towards are scanned like inline CSS.
_SVG_RETARGET_NAMES = frozenset({"href", "xlink:href", "style"})
_SVG_ANIMATION_VALUES = frozenset({"to", "from", "by", "values"})
# CSS escapes (``\75rl(`` is ``url(``, ``@\69mport`` is ``@import``) and
# comments are normalized away before the unsafe-CSS scan.
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(.))", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# A DOCTYPE (with or without an internal subset) is recognized here so the
# rejection names the entity problem instead of an unknown type.
_SVG_START = re.compile(rb"^\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*(?:<!DOCTYPE(?:[^>\[]|\[[^\]]*\])*>\s*)?"
                        rb"(?:<!--.*?-->\s*)*<svg[\s>]", re.S)
_DATA_IMAGE = re.compile(r"^data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\s]+$")
_UNSAFE_CSS = re.compile(r"@import|expression\s*\(|javascript:|-moz-binding|behavior\s*:|"
                         r"url\(\s*['\"]?(?!#|data:image/(?:png|jpeg);base64,)", re.I)
_PDF_ACTIVE_KEYS = frozenset({"/JS", "/JavaScript", "/OpenAction", "/Launch", "/AA", "/XFA",
                              "/EmbeddedFiles", "/EF", "/RichMediaContent", "/RichMediaSettings"})
_PDF_ACTIVE_SUBTYPES = frozenset({"/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/Rendition",
                                  "/Movie", "/Sound", "/GoTo3DView", "/RichMediaExecute"})
# Annotation subtypes that embed media, 3D scenes or file payloads.
_PDF_ANNOTATION_SUBTYPES = frozenset({"/RichMedia", "/3D", "/Movie", "/Sound", "/Screen", "/FileAttachment"})
# Actions that open another file or a URL. URI links are refused on purpose:
# an attachment that can phone home when clicked is not evidence; print a
# vendor datasheet to a link-free PDF before attaching it.
_PDF_EXTERNAL_SUBTYPES = frozenset({"/GoToR", "/GoToE", "/URI"})


class AttachmentRejected(ValueError):
    """An asset was refused on import; ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{detail} [{reason}]")
        self.reason = reason
        self.detail = detail


class AssetNotFound(LookupError):
    """No stored original matches the requested hash."""


class AssetHashMismatch(ValueError):
    """A stored original no longer hashes to the identity it is filed under."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_filename(name: Any) -> str:
    """Return a safe display name ``stem.ext``; reject path components and control bytes."""
    if not isinstance(name, str) or not name.strip():
        raise AttachmentRejected("unsafe_filename", "Attachment needs a file name")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise AttachmentRejected("unsafe_filename", "File name contains control characters")
    text = unicodedata.normalize("NFC", name).strip()
    if "/" in text or "\\" in text:
        raise AttachmentRejected("unsafe_filename", "File name must not contain path separators")
    if ".." in text or text.startswith(".") or text.startswith("~"):
        raise AttachmentRejected("unsafe_filename", "Relative, hidden or home-directory names are not accepted")
    if re.match(r"^[A-Za-z]:", text):
        raise AttachmentRejected("unsafe_filename", "Drive-qualified names are not accepted")
    stem, dot, extension = text.rpartition(".")
    if not dot or not stem.strip():
        raise AttachmentRejected("unsafe_filename", "File name needs a media extension")
    extension = extension.lower()
    if extension not in EXTENSIONS:
        raise AttachmentRejected("unsupported_type", f"Extension .{extension} is not an accepted attachment type")
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" _")[:MAX_FILENAME - 5] or "asset"
    return f"{stem}.{MEDIA_TYPES[EXTENSIONS[extension]]}"


def sniff_media_type(data: bytes) -> str | None:
    """Identify an allowlisted media type from content alone."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    head = data[:8192]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    if _SVG_START.match(head):
        return "image/svg+xml"
    return None


def _check_dimensions(width: Any, height: Any) -> None:
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise AttachmentRejected("dimensions", "Image dimensions are missing or not positive")
    if width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise AttachmentRejected("dimensions", f"Image {width}×{height} exceeds {MAX_DIMENSION} px per side "
                                 f"or {MAX_PIXELS} pixels")


def _inspect_raster(data: bytes, media_type: str) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise AttachmentRejected("validator_unavailable", "Pillow is required to verify raster images") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                declared = image.format
                _check_dimensions(width, height)
                image.verify()
    except AttachmentRejected:
        raise
    except Image.DecompressionBombError as exc:
        raise AttachmentRejected("dimensions", f"Image is too large to decode safely: {exc}") from exc
    except Exception as exc:  # Pillow raises several unrelated types for damaged files.
        raise AttachmentRejected("image_malformed", f"Image data could not be verified: {exc}") from exc
    expected = {"image/png": "PNG", "image/jpeg": "JPEG"}[media_type]
    if declared != expected:
        raise AttachmentRejected("type_mismatch", f"Content decodes as {declared}, not {expected}")
    return width, height


def _finite_pixels(text: str) -> int | None:
    """A length as whole pixels; non-finite or absurd values are a typed rejection, never a crash."""
    try:
        number = float(text)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(number) or abs(number) > 1e9:
        raise AttachmentRejected("dimensions", f"SVG dimension {text.strip()[:32]!r} is not a finite pixel count")
    return int(round(number))


def _svg_length(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(?:px)?\s*", value)
    return _finite_pixels(match.group(1)) if match else None


def _css_normalize(text: str) -> str:
    def unescape(match: re.Match) -> str:
        if match.group(1) is not None:
            code = int(match.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF else "�"
        return match.group(2)
    return _CSS_ESCAPE.sub(unescape, _CSS_COMMENT.sub("", text))


def _unsafe_css(text: str) -> bool:
    return bool(_UNSAFE_CSS.search(_css_normalize(text)))


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _inspect_svg(data: bytes) -> tuple[int | None, int | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AttachmentRejected("svg_malformed", "SVG must be UTF-8 text") from exc
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise AttachmentRejected("svg_entities", "SVG with a DOCTYPE or XML entities is not accepted")
    if "<?xml-stylesheet" in lowered:
        raise AttachmentRejected("svg_external_reference", "SVG stylesheet processing instructions are not accepted")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise AttachmentRejected("svg_malformed", f"SVG is not well-formed XML: {exc}") from exc
    if _local(root.tag).lower() != "svg":
        raise AttachmentRejected("type_mismatch", "Root element is not <svg>")
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue  # comments and processing instructions carry no behavior once parsed
        tag = _local(element.tag).lower()
        if tag in _SVG_FORBIDDEN_TAGS:
            raise AttachmentRejected("svg_active_content", f"SVG element <{tag}> is not accepted")
        if tag == "style" and element.text and _unsafe_css(element.text):
            raise AttachmentRejected("svg_external_reference", "SVG style loads external or executable content")
        animation = tag in _SVG_ANIMATION_TAGS
        for raw_name, value in element.attrib.items():
            name = _local(raw_name).lower()
            if name.startswith("on"):
                raise AttachmentRejected("svg_active_content", f"SVG event handler attribute {name} is not accepted")
            if name == "style" and _unsafe_css(value):
                raise AttachmentRejected("svg_external_reference", "SVG inline style loads external content")
            if name == "href":
                candidate = value.strip()
                internal = candidate.startswith("#")
                embedded = tag == "image" and bool(_DATA_IMAGE.match(candidate))
                if not (internal or embedded):
                    raise AttachmentRejected("svg_external_reference",
                                             f"SVG <{tag}> references content outside the file")
            if animation and name == "attributename" and value.strip().lower() in _SVG_RETARGET_NAMES:
                raise AttachmentRejected("svg_active_content", "SVG animations may not retarget references or styles")
            if animation and name in _SVG_ANIMATION_VALUES and _unsafe_css(value):
                raise AttachmentRejected("svg_external_reference", f"SVG <{tag}> animates towards external content")
            if name not in ("style", "href") and "url(" in _css_normalize(value).lower() and _unsafe_css(value):
                raise AttachmentRejected("svg_external_reference",
                                         f"SVG attribute {name} references content outside the file")
    width, height = _svg_length(root.get("width")), _svg_length(root.get("height"))
    view_box = root.get("viewBox")
    if (width is None or height is None) and view_box:
        parts = re.split(r"[\s,]+", view_box.strip())
        if len(parts) == 4:
            width = width if width is not None else _finite_pixels(parts[2])
            height = height if height is not None else _finite_pixels(parts[3])
    if width is not None and height is not None:
        _check_dimensions(width, height)
    elif len(data) > BYTE_LIMITS["image/svg+xml"] // 4:
        raise AttachmentRejected("dimensions", "Large SVG without intrinsic dimensions is not accepted")
    return width, height


def _inspect_pdf(data: bytes) -> None:
    try:
        import pypdf
        from pypdf import generic
        from pypdf.errors import LimitReachedError
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise AttachmentRejected("validator_unavailable", "pypdf is required to verify PDF attachments") from exc
    deadline = time.monotonic() + PDF_INSPECT_SECONDS
    try:
        with pypdf.apply_configuration(zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
                                       lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
                                       run_length_maximum_output_length=MAX_PDF_STREAM_BYTES):
            reader = pypdf.PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise AttachmentRejected("pdf_encrypted", "Encrypted PDF cannot be inspected")
            stack: list[Any] = [reader.trailer]
            visited: set[tuple[int, int]] = set()
            budget = MAX_PDF_OBJECTS
            while stack:
                if time.monotonic() > deadline:
                    raise AttachmentRejected("pdf_too_complex",
                                             f"PDF inspection exceeded its {PDF_INSPECT_SECONDS:g} s budget")
                item = stack.pop()
                budget -= 1
                if budget < 0:
                    raise AttachmentRejected("pdf_malformed", "PDF object graph is too large to inspect")
                if isinstance(item, generic.IndirectObject):
                    key = (item.idnum, item.generation)
                    if key in visited:
                        continue
                    visited.add(key)
                    item = item.get_object()
                if isinstance(item, dict):
                    for key, value in item.items():
                        name = str(key)
                        if name in _PDF_ACTIVE_KEYS:
                            raise AttachmentRejected("pdf_active_content", f"PDF contains {name}")
                        if name in ("/S", "/Subtype"):
                            target = str(value.get_object() if hasattr(value, "get_object") else value)
                            if name == "/S" and target in _PDF_EXTERNAL_SUBTYPES:
                                raise AttachmentRejected("pdf_external_reference",
                                                         f"PDF action {target} opens another file or a URL")
                            if (name == "/S" and target in _PDF_ACTIVE_SUBTYPES) or \
                                    (name == "/Subtype" and target in _PDF_ANNOTATION_SUBTYPES):
                                raise AttachmentRejected("pdf_active_content", f"PDF {name} {target} is not accepted")
                        stack.append(value)
                elif isinstance(item, list):
                    stack.extend(item)
    except AttachmentRejected:
        raise
    except LimitReachedError as exc:
        raise AttachmentRejected("pdf_too_complex",
                                 f"PDF stream inflates beyond {MAX_PDF_STREAM_BYTES} bytes: {exc}") from exc
    except Exception as exc:
        raise AttachmentRejected("pdf_malformed", f"PDF could not be parsed: {type(exc).__name__}: {exc}") from exc


def validate_asset(data: bytes, filename: Any) -> dict:
    """Validate bytes by content and return the identity fields for a manifest entry."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise AttachmentRejected("empty", "Attachment has no content")
    data = bytes(data)
    name = normalize_filename(filename)
    if len(data) > max(BYTE_LIMITS.values()):
        raise AttachmentRejected("too_large", f"Attachment exceeds {max(BYTE_LIMITS.values())} bytes")
    media_type = sniff_media_type(data)
    if media_type is None:
        raise AttachmentRejected("unknown_type", "Content is not a recognized PNG, JPEG, SVG or PDF")
    declared = EXTENSIONS[name.rsplit(".", 1)[1]]
    if declared != media_type:
        raise AttachmentRejected("type_mismatch", f"File name says {declared} but the content is {media_type}")
    if len(data) > BYTE_LIMITS[media_type]:
        raise AttachmentRejected("too_large", f"{media_type} attachments are limited to {BYTE_LIMITS[media_type]} bytes")
    width = height = None
    if media_type in ("image/png", "image/jpeg"):
        width, height = _inspect_raster(data, media_type)
    elif media_type == "image/svg+xml":
        width, height = _inspect_svg(data)
    else:
        _inspect_pdf(data)
    digest = hashlib.sha256(data).hexdigest()
    return {"sha256": digest, "media_type": media_type, "byte_size": len(data), "width": width,
            "height": height, "original_name": name, "extension": MEDIA_TYPES[media_type]}


def _check_text(value: Any, *, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AttachmentRejected("invalid_text", f"{field} must be text")
    if len(value) > limit:
        raise AttachmentRejected("invalid_text", f"{field} exceeds {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value) or "\x7f" in value:
        raise AttachmentRejected("invalid_text", f"{field} contains control characters")
    return value


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise PersistenceError(f"cannot store {path.name}: {exc}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


class AssetStore:
    """Read and extend one run's attachment store without touching acquisition truth."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.root = self.run_dir / "attachments"
        self.originals = self.root / "originals"
        self.revisions = self.root / "revisions"

    @property
    def finalized(self) -> bool:
        return (self.run_dir / "integrity.json").is_file()

    def acquisition_assets(self) -> list[dict]:
        manifest = self.root / "manifest.json"
        if not manifest.is_file():
            return []
        value = json.loads(manifest.read_text(encoding="utf-8"))
        return list(value.get("assets", []))

    def revision_paths(self) -> list[Path]:
        if not self.revisions.is_dir():
            return []
        numbered = [(int(path.stem), path) for path in self.revisions.glob("*.json") if path.stem.isdigit()]
        return [path for _, path in sorted(numbered)]

    def latest_revision(self) -> dict | None:
        paths = self.revision_paths()
        return json.loads(paths[-1].read_text(encoding="utf-8")) if paths else None

    def assets(self) -> list[dict]:
        """Acquisition-time assets followed by the current documentation revision."""
        latest = self.latest_revision()
        return self.acquisition_assets() + (list(latest.get("assets", [])) if latest else [])

    def find(self, sha256: str) -> dict | None:
        return next((asset for asset in self.assets() if asset.get("sha256") == sha256), None)

    def path_for(self, asset: dict) -> Path:
        return self.originals / f"{asset['sha256']}.{MEDIA_TYPES[asset['media_type']]}"

    def resolve(self, sha256: str) -> tuple[Path, dict]:
        """Locate an original by hash and prove the stored bytes still match it."""
        if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise AssetNotFound("Asset hash must be 64 lowercase hex characters")
        asset = self.find(sha256)
        if asset is None:
            raise AssetNotFound(f"No attachment with hash {sha256} is recorded for this run")
        path = self.path_for(asset)
        if not path.is_file():
            raise AssetNotFound(f"Original {path.name} is missing from the attachment store")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != sha256:
            raise AssetHashMismatch(f"Original {path.name} hashes to {actual}; the recorded asset hash differs")
        return path, asset

    def read(self, sha256: str) -> tuple[bytes, dict]:
        path, asset = self.resolve(sha256)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise AssetHashMismatch(f"Original {path.name} changed while being read")
        return data, asset

    def add(self, data: bytes, filename: Any, *, caption: str = "", owner: str = "operator",
            validated: dict | None = None) -> dict:
        """Validate and store one asset; return its manifest entry.

        The same content is stored once. After finalization the entry is
        appended to a new documentation revision manifest; the acquisition
        manifest and integrity file are never rewritten. ``validated`` may
        carry the fields ``validate_asset`` already returned for these exact
        bytes (so a caller can validate before taking a lock); it is re-bound
        to the bytes by hash, size and name before use, else ignored.
        """
        info = None
        if isinstance(validated, dict) and isinstance(data, (bytes, bytearray)) and data:
            if (validated.get("sha256") == hashlib.sha256(data).hexdigest() and validated.get("byte_size") == len(data)
                    and validated.get("original_name") == normalize_filename(filename)):
                info = dict(validated)
        if info is None:
            info = validate_asset(data, filename)
        caption = _check_text(caption, field="Caption", limit=MAX_CAPTION)
        if not isinstance(owner, str) or not OWNER_PATTERN.fullmatch(owner):
            raise AttachmentRejected("invalid_text", "Owner must be a short printable identifier")
        existing = self.find(info["sha256"])
        if existing is not None:
            self.resolve(info["sha256"])
            return dict(existing)
        path = self.originals / f"{info['sha256']}.{info['extension']}"
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
                raise AssetHashMismatch(f"Original {path.name} exists with different content; originals are immutable")
        else:
            _write_bytes(path, data)
        entry = {"asset_id": "asset-" + info["sha256"][:16], "sha256": info["sha256"],
                 "media_type": info["media_type"], "byte_size": info["byte_size"],
                 "width": info["width"], "height": info["height"], "caption": caption, "owner": owner,
                 "added_utc": utc_now(), "added_in_revision": None, "original_name": info["original_name"]}
        if not self.finalized:
            manifest_path = self.root / "manifest.json"
            manifest = (json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file()
                        else {"assets": []})
            manifest.setdefault("assets", []).append(entry)
            atomic_json(manifest_path, manifest)
            return entry
        latest = self.latest_revision()
        number = int(latest["revision"]) + 1 if latest else 1
        entry["added_in_revision"] = number
        revision = {"schema_version": SCHEMA_VERSION, "kind": "documentation-assets", "revision": number,
                    "created_utc": utc_now(), "previous_revision": latest["revision"] if latest else None,
                    "acquisition_manifest_sha256": hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest(),
                    "integrity_sha256": hashlib.sha256((self.run_dir / "integrity.json").read_bytes()).hexdigest(),
                    "assets": (list(latest.get("assets", [])) if latest else []) + [entry]}
        target = self.revisions / f"{number}.json"
        if target.exists():
            raise PersistenceError(f"documentation revision {number} already exists")
        atomic_json(target, revision)
        return entry
