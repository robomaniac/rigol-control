"""Attachment import hygiene and the content-addressed asset store (brief 8.4, 16)."""
import hashlib
import io
import json
import struct
import zlib

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from dcdc_bench import attachments
from dcdc_bench.attachments import (AssetHashMismatch, AssetNotFound, AssetStore, AttachmentRejected,
                                    normalize_filename, sniff_media_type, validate_asset)
from dcdc_bench.storage import RunStore, verify_integrity

SVG_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
SVG_OK = (f'<svg {SVG_NS} width="200" height="100" viewBox="0 0 200 100"><defs><rect id="pad" width="4" height="4"/></defs>'
          '<rect width="200" height="100" fill="#cccccc"/><use href="#pad" x="2" y="2"/>'
          '<text x="10" y="50" style="fill:#183047">Case top</text></svg>').encode()


def png(width=16, height=12, color=(200, 40, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg(width=16, height=12) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def png_header(width, height) -> bytes:
    """Declared size with no pixel data: the size must be refused before any decode is attempted."""
    def chunk(kind, payload=b""):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT") + chunk(b"IEND")


def pdf(*, javascript=False, open_action=False, launch=False, encrypt=False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    root = getattr(writer, "root_object", None) or writer._root_object
    if javascript:
        action = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"),
                                   NameObject("/JS"): TextStringObject("app.alert(1);")})
        names = DictionaryObject({NameObject("/Names"): ArrayObject([TextStringObject("init"), writer._add_object(action)])})
        root[NameObject("/Names")] = DictionaryObject({NameObject("/JavaScript"): names})
    if open_action:
        root[NameObject("/OpenAction")] = ArrayObject([page.indirect_reference, NameObject("/Fit")])
    if launch:
        annotation = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(50), NumberObject(20)]),
            NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/Launch"),
                                                NameObject("/F"): TextStringObject("cmd.exe")})})
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
    if encrypt:
        writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def finalized(tmp_path):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {"execution_status": "running"})
    store.finalize({"execution_status": "completed"})
    return store.path


def _acquisition_bytes(run_dir):
    return (run_dir / "integrity.json").read_bytes(), (run_dir / "attachments/manifest.json").read_bytes()


def test_post_run_attachment_writes_documentation_revisions_and_leaves_acquisition_untouched(finalized):
    before = _acquisition_bytes(finalized)
    store = AssetStore(finalized)
    data = png()
    entry = store.add(data, "Board photo.PNG", caption="Case top, sensors under tape", owner="operator")
    digest = hashlib.sha256(data).hexdigest()
    assert entry["sha256"] == digest and entry["asset_id"] == "asset-" + digest[:16]
    assert {"asset_id", "sha256", "media_type", "byte_size", "width", "height", "caption", "owner",
            "added_utc", "added_in_revision"} <= set(entry)
    assert (entry["media_type"], entry["byte_size"], entry["width"], entry["height"]) == ("image/png", len(data), 16, 12)
    assert entry["original_name"] == "Board photo.png" and entry["added_in_revision"] == 1
    original = finalized / "attachments/originals" / (digest + ".png")
    assert original.read_bytes() == data
    revision = json.loads((finalized / "attachments/revisions/1.json").read_text())
    assert revision["assets"] == [entry] and revision["previous_revision"] is None
    assert revision["acquisition_manifest_sha256"] == hashlib.sha256(before[1]).hexdigest()
    assert revision["integrity_sha256"] == hashlib.sha256(before[0]).hexdigest()
    # The finalized acquisition manifest and hashes never change to make an
    # attachment look like acquisition-time evidence.
    assert _acquisition_bytes(finalized) == before
    verify_integrity(finalized)
    second = store.add(jpeg(), "setup.jpg")
    latest = json.loads((finalized / "attachments/revisions/2.json").read_text())
    assert latest["previous_revision"] == 1 and [a["sha256"] for a in latest["assets"]] == [digest, second["sha256"]]
    assert store.assets() == [entry, second]
    # Content-addressed: the same bytes are one asset, whatever the file name.
    assert store.add(data, "again.png")["sha256"] == digest
    assert not (finalized / "attachments/revisions/3.json").exists()
    assert len(list((finalized / "attachments/originals").iterdir())) == 2
    assert _acquisition_bytes(finalized) == before
    path, resolved = store.resolve(digest)
    assert path == original and resolved == entry


def test_attachment_before_finalization_is_covered_by_the_acquisition_manifest(tmp_path):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {"execution_status": "running"})
    entry = AssetStore(store.path).add(png(), "wiring.png", caption="Wiring before energizing")
    manifest = json.loads((store.path / "attachments/manifest.json").read_text())
    assert manifest["assets"] == [entry] and entry["added_in_revision"] is None
    assert not (store.path / "attachments/revisions").exists()
    store.finalize({"execution_status": "completed"})
    verify_integrity(store.path)
    manifest["assets"][0]["caption"] = "edited later"
    (store.path / "attachments/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="attachments/manifest.json"):
        verify_integrity(store.path)


def test_changed_original_or_unknown_hash_is_detected(finalized):
    store = AssetStore(finalized)
    entry = store.add(png(), "photo.png")
    with pytest.raises(AssetNotFound):
        store.resolve("0" * 64)
    with pytest.raises(AssetNotFound):
        store.resolve("not-a-hash")
    original = store.path_for(entry)
    original.write_bytes(png(color=(0, 0, 0)))
    with pytest.raises(AssetHashMismatch):
        store.resolve(entry["sha256"])
    with pytest.raises(AssetHashMismatch):
        store.read(entry["sha256"])
    with pytest.raises(AssetHashMismatch):
        store.add(png(), "photo-again.png")


@pytest.mark.parametrize("name", ["../escape.png", "/etc/passwd.png", "a/b.png", "a\\b.png", "a\x00.png", "..",
                                  ".hidden.png", "~home.png", "C:photo.png", "noextension", "", None, 12])
def test_unsafe_or_relative_file_names_are_rejected(name):
    with pytest.raises(AttachmentRejected) as info:
        normalize_filename(name)
    assert info.value.reason == "unsafe_filename"
    with pytest.raises(AttachmentRejected):
        validate_asset(png(), name)


def test_file_names_are_normalized_and_only_allowlisted_extensions_pass():
    assert normalize_filename("  Board Photo (top).JPEG ") == "Board Photo _top.jpg"
    assert normalize_filename("schematic.PDF") == "schematic.pdf"
    with pytest.raises(AttachmentRejected) as info:
        normalize_filename("macro.exe")
    assert info.value.reason == "unsupported_type"
    with pytest.raises(AttachmentRejected) as info:
        normalize_filename("page.html")
    assert info.value.reason == "unsupported_type"


def test_content_sniffing_decides_the_type_not_the_extension():
    assert sniff_media_type(png()) == "image/png"
    assert sniff_media_type(jpeg()) == "image/jpeg"
    assert sniff_media_type(SVG_OK) == "image/svg+xml"
    assert sniff_media_type(b"\xef\xbb\xbf<?xml version='1.0'?>\n<!-- c -->" + SVG_OK) == "image/svg+xml"
    assert sniff_media_type(pdf()) == "application/pdf"
    assert sniff_media_type(b"<html><script>alert(1)</script></html>") is None
    for data, name in [(jpeg(), "photo.png"), (SVG_OK, "drawing.png"), (pdf(), "page.svg"), (png(), "photo.jpg")]:
        with pytest.raises(AttachmentRejected) as info:
            validate_asset(data, name)
        assert info.value.reason == "type_mismatch"
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(b"<html><script>alert(1)</script></html>", "page.png")
    assert info.value.reason == "unknown_type"
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(b"", "empty.png")
    assert info.value.reason == "empty"


def test_byte_limits_apply_per_media_type(monkeypatch):
    data = png()
    monkeypatch.setitem(attachments.BYTE_LIMITS, "image/png", len(data) - 1)
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(data, "photo.png")
    assert info.value.reason == "too_large"
    monkeypatch.setitem(attachments.BYTE_LIMITS, "image/png", len(data))
    assert validate_asset(data, "photo.png")["byte_size"] == len(data)
    for key in attachments.BYTE_LIMITS:
        monkeypatch.setitem(attachments.BYTE_LIMITS, key, 8)
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(SVG_OK, "drawing.svg")
    assert info.value.reason == "too_large"


@pytest.mark.parametrize("data,name", [(png_header(attachments.MAX_DIMENSION + 1, 10), "wide.png"),
                                       (png_header(7000, 7000), "many-pixels.png"),
                                       (f'<svg {SVG_NS} width="20000" height="10"></svg>'.encode(), "wide.svg"),
                                       (f'<svg {SVG_NS} viewBox="0 0 7000 7000"></svg>'.encode(), "pixels.svg")])
def test_dimension_limits_are_enforced_from_headers(data, name):
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(data, name)
    assert info.value.reason == "dimensions"


def test_damaged_raster_is_rejected():
    data = bytearray(png())
    data[-20] ^= 0xFF  # inside the IDAT chunk or its CRC; ahead of IEND
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(bytes(data), "photo.png")
    assert info.value.reason == "image_malformed"


@pytest.mark.parametrize("body,reason", [
    ('<script>alert(1)</script>', "svg_active_content"),
    ('<rect width="1" height="1" onload="alert(1)"/>', "svg_active_content"),
    ('<rect width="1" height="1" onclick="alert(1)"/>', "svg_active_content"),
    ('<foreignObject><body xmlns="http://www.w3.org/1999/xhtml"><p>x</p></body></foreignObject>', "svg_active_content"),
    ('<iframe src="https://example.invalid"/>', "svg_active_content"),
    ('<object data="x"/>', "svg_active_content"),
    ('<embed src="x"/>', "svg_active_content"),
    ('<image href="https://example.invalid/photo.png" width="1" height="1"/>', "svg_external_reference"),
    ('<image xlink:href="file:///etc/passwd" width="1" height="1"/>', "svg_external_reference"),
    ('<image href="data:image/svg+xml;base64,PHN2Zz4=" width="1" height="1"/>', "svg_external_reference"),
    ('<use href="https://example.invalid/sprite.svg#a"/>', "svg_external_reference"),
    ('<use xlink:href="other.svg#a"/>', "svg_external_reference"),
    ('<a href="javascript:alert(1)"><text>x</text></a>', "svg_external_reference"),
    ('<style>@import url("https://example.invalid/x.css");</style>', "svg_external_reference"),
    ('<rect style="fill:url(https://example.invalid/p.png)" width="1" height="1"/>', "svg_external_reference"),
    ('<set attributeName="href" to="https://example.invalid/x" xlink:href="#pad"/>', "svg_active_content"),
])
def test_svg_active_content_and_external_references_are_rejected(body, reason):
    data = f'<svg {SVG_NS} width="20" height="10"><defs><rect id="pad" width="1" height="1"/></defs>{body}</svg>'.encode()
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(data, "drawing.svg")
    assert info.value.reason == reason


@pytest.mark.parametrize("prefix,reason", [
    ('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">', "svg_entities"),
    ('<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>', "svg_entities"),
    ('<?xml-stylesheet href="https://example.invalid/x.css" type="text/css"?>', "svg_external_reference"),
])
def test_svg_doctype_entities_and_stylesheet_instructions_are_rejected(prefix, reason):
    data = (prefix + f'<svg {SVG_NS} width="20" height="10"><rect width="1" height="1"/></svg>').encode()
    with pytest.raises(AttachmentRejected) as info:
        validate_asset(data, "drawing.svg")
    assert info.value.reason == reason


def test_plain_svg_with_internal_and_embedded_references_is_accepted():
    embedded = ('<image href="data:image/png;base64,iVBORw0KGgo=" width="4" height="4"/>')
    data = SVG_OK.replace(b"</svg>", embedded.encode() + b"</svg>")
    info = validate_asset(data, "board.svg")
    assert (info["media_type"], info["width"], info["height"]) == ("image/svg+xml", 200, 100)
    with pytest.raises(AttachmentRejected) as rejected:
        validate_asset(f'<svg {SVG_NS}><rect width="1" height="1" /></svg'.encode(), "broken.svg")
    assert rejected.value.reason == "svg_malformed"


def test_pdf_without_actions_is_accepted_and_active_pdfs_are_rejected():
    info = validate_asset(pdf(), "schematic.pdf")
    assert info["media_type"] == "application/pdf" and info["width"] is None and info["height"] is None
    for variant in ({"javascript": True}, {"open_action": True}, {"launch": True}):
        with pytest.raises(AttachmentRejected) as rejected:
            validate_asset(pdf(**variant), "schematic.pdf")
        assert rejected.value.reason == "pdf_active_content", variant
    with pytest.raises(AttachmentRejected) as rejected:
        validate_asset(pdf(encrypt=True), "locked.pdf")
    assert rejected.value.reason == "pdf_encrypted"
    with pytest.raises(AttachmentRejected) as rejected:
        validate_asset(b"%PDF-1.4 not really a document", "garbage.pdf")
    assert rejected.value.reason == "pdf_malformed"


def test_caption_and_owner_text_is_bounded(finalized):
    store = AssetStore(finalized)
    with pytest.raises(AttachmentRejected) as info:
        store.add(png(), "photo.png", caption="bad\x00caption")
    assert info.value.reason == "invalid_text"
    with pytest.raises(AttachmentRejected):
        store.add(png(), "photo.png", caption="x" * (attachments.MAX_CAPTION + 1))
    with pytest.raises(AttachmentRejected):
        store.add(png(), "photo.png", owner="operator!!")
    assert not (finalized / "attachments/revisions").exists(), "rejected imports leave no revision"
    entry = store.add(png(), "photo.png", caption="Line one\nLine two", owner="jerome@bench")
    assert entry["caption"] == "Line one\nLine two"
