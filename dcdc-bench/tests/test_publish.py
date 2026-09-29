"""Publication gate (PUB-01): approval record, redaction, noindex, no git/gh/network, source untouched."""
import base64
import hashlib
import io
import json
import os
import re
import socket
import subprocess
from pathlib import Path

import pytest
import yaml
from PIL import Image

from dcdc_bench import cli
from dcdc_bench.attachments import AssetStore
from dcdc_bench.publish import LOCAL_HOSTNAME, PRIVATE_IPV4, Redactor, load_approval, publish_run
from dcdc_bench.storage import RunStore, verify_integrity

RUN_ID = "20260927T120000.000000Z_real_abc123"
IP, HOST, SERIAL_S, SERIAL_L = "192.168.77.42", "load-bench.local", "DP8G0000FAKE1", "DL3A0000FAKE2"
PRIVATE_PATH = "/home/tester/rigol-control/dcdc-bench/runs/real-extended/" + RUN_ID
# A real Plotly bundle excerpt: every ``.local``/``.home`` here is JavaScript member access.
PLOTLY_EXCERPT = ('!function(){function bse(e){this.local=this.regionalOptions[e]||this.regionalOptions[""]}'
                  'var i=this._validate(e,t,r,ua.local.invalidDate||ua.regionalOptions[""].invalidDate);'
                  'Xa.zoomReset={name:"reset",attr:"zoom",val:"reset",icon:Ya.home,click:Tf};'
                  'this.removeAttributeNS(z.space,z.local);if(t.calendar()!==this)throw hc.local.invalidFormat}();')


def raster(kind="png", size=(8, 6), *, gps=False) -> bytes:
    """A small real PNG/JPEG; with ``gps`` an EXIF block carrying a GPS IFD, camera model and body serial."""
    image = Image.new("RGB", size, (200, 40, 20) if kind == "png" else (10, 120, 200))
    params = {}
    if gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (37.0, 47.0, 30.0), 3: "W", 4: (122.0, 25.0, 0.0)}
        exif[0x0110] = "Pixel 9 Pro"
        exif[0xA431] = "CAMSERIAL0042"
        params["exif"] = exif.tobytes()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG" if kind == "png" else "JPEG", **params)
    return buffer.getvalue()


BOARD_PNG = raster("png")
LAB_JPG = raster("jpg", gps=True)


def tree_hash(folder):
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(folder)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def synthetic_run(tmp_path, *, revision="r0001", with_pdf=True, build_status="success"):
    run_dir = tmp_path / "runs" / RUN_ID
    store = RunStore(run_dir)
    run = {"schema_version": "1.0", "run_id": RUN_ID, "data_source": "measured", "execution_status": "completed",
           "instrument_identities": {"source": {"manufacturer": "RIGOL TECHNOLOGIES", "model": "DP821A", "serial": SERIAL_S, "firmware": "00.01.16"},
                                     "load": {"manufacturer": "RIGOL TECHNOLOGIES", "model": "DL3031A", "serial": SERIAL_L, "firmware": "00.01.04"}},
           "software": {"git": {"commit": "abc", "dirty": True}}}
    store.initialize({"bench": {"source": {"endpoint": f"TCPIP0::{IP}::INSTR"}, "load": {"endpoint": None}}},
                     {"bench": {"source": {"endpoint": None}, "load": {"endpoint": f"TCPIP0::{HOST}::INSTR"}}}, run)
    store.append("samples", {"sample_id": "s1", "value": 12.1})
    originals = run_dir / "attachments" / "originals"
    (originals / "board.png").write_bytes(BOARD_PNG)
    (originals / "private-lab.jpg").write_bytes(LAB_JPG)
    manifest = {"assets": [
        {"asset_id": "board-photo", "path": "originals/board.png", "sha256": hashlib.sha256(BOARD_PNG).hexdigest(),
         "caption": f"Board photo taken at {PRIVATE_PATH}/attachments", "role": "board_photo"},
        {"asset_id": "lab-photo", "path": "originals/private-lab.jpg", "sha256": hashlib.sha256(LAB_JPG).hexdigest(),
         "caption": "Private lab photo", "role": "setup_photo"}]}
    (run_dir / "attachments" / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "scpi.jsonl").write_text(
        json.dumps({"device": "source", "resource": f"TCPIP0::{IP}::INSTR", "command": "*IDN?",
                    "response": f"RIGOL TECHNOLOGIES,DP821A,{SERIAL_S},00.01.16"}) + "\n" +
        json.dumps({"device": "load", "resource": f"TCPIP0::{HOST}::INSTR", "command": "*IDN?",
                    "response": f"RIGOL TECHNOLOGIES,DL3031A,{SERIAL_L},00.01.04"}) + "\n")
    store.finalize(run)
    report = run_dir / "reports" / revision
    (report / "exports").mkdir(parents=True)
    (report / "figures").mkdir()
    (report / "report.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
        f'<title>Run {RUN_ID}</title></head><body><h1>Characterization</h1>'
        f'<p>Source {SERIAL_S} at TCPIP0::{IP}::INSTR, load {SERIAL_L} at {HOST}; record {PRIVATE_PATH}/run.json</p>'
        '<table><tr><td>003.371.214.673</td><td>12.1352</td><td>0.0993278</td></tr></table>'
        '<script type="application/json" id="dcdc-report-data">{"v":[24.005,12.1,"1.2.3.4"]}</script></body></html>')
    (report / "report_model.json").write_text(json.dumps({
        "run_id": RUN_ID, "provenance": {"software": {"platform": "Linux-6.18-aarch64"}, "source_path": PRIVATE_PATH},
        "bench": {"source": {"serial": SERIAL_S}}, "points": [{"Vin_V": 24.005, "Iin_A": 0.0687}]}))
    build_manifest = {"artifacts": {"html": {"path": PRIVATE_PATH + f"/reports/{revision}/report.html", "sha256": "x"}},
                      "versions": {"plotly_js": "4.1.1"}}
    if build_status is not None:
        build_manifest["status"] = build_status  # the renderer's verdict; None leaves it undeclared
    (report / "build_manifest.json").write_text(json.dumps(build_manifest))
    (report / "exports" / "points.csv").write_text(f"point_id,Vin_V\np0001,24.005\n# source {PRIVATE_PATH}\n")
    (report / "figures" / "fig-efficiency.svg").write_text(f'<svg><title>{RUN_ID} {IP}</title></svg>')
    (report / "figures" / "fig-efficiency.pdf").write_bytes(b"%PDF-1.4 fake")
    if with_pdf:
        (report / "report.pdf").write_bytes(b"%PDF-1.4 fake report " + SERIAL_S.encode())
    return run_dir


def approval_file(tmp_path, **overrides):
    record = {"schema_version": "1.0", "run_id": RUN_ID, "report_revision": "r0001", "approver": "J. Reviewer",
              "date": "2026-09-27", "public": False, "attachments": ["board-photo"]}
    record.update(overrides)
    path = tmp_path / "approval.yaml"
    path.write_text(yaml.safe_dump(record))
    return path


@pytest.fixture
def no_git_no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"forbidden call: {args[:1]} {kwargs.keys()}")
    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def test_refused_without_approval_record_and_source_untouched(tmp_path):
    run_dir = synthetic_run(tmp_path)
    before = tree_hash(run_dir)
    with pytest.raises(ValueError, match="approval record"):
        publish_run(run_dir, "r0001", tmp_path / "public", tmp_path / "missing-approval.yaml")
    assert not (tmp_path / "public").exists()
    assert tree_hash(run_dir) == before
    assert cli.main(["publish", str(run_dir), "--revision", "r0001", "--out", str(tmp_path / "public"),
                     "--approval", str(tmp_path / "missing-approval.yaml")]) == 2
    assert not (tmp_path / "public").exists() and tree_hash(run_dir) == before


@pytest.mark.parametrize("overrides,match", [
    ({"run_id": "other-run"}, "names run"),
    ({"report_revision": "r0002"}, "covers revision"),
    ({"public": "yes"}, "invalid"),
    ({"approver": "   "}, "invalid"),
    ({"date": "2026-13-40"}, "invalid"),
    ({"attachments": ["board-photo", "not-in-run"]}, "not in the run"),
    ({"unexpected": True}, "invalid"),
])
def test_incomplete_or_mismatched_approval_is_refused(tmp_path, overrides, match):
    run_dir = synthetic_run(tmp_path)
    before = tree_hash(run_dir)
    with pytest.raises(ValueError, match=match):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path, **overrides))
    assert not (tmp_path / "public" / RUN_ID / "r0001").exists() and tree_hash(run_dir) == before


def test_redacted_copy_strips_endpoints_paths_serials_and_keeps_numbers(tmp_path, no_git_no_network):
    run_dir = synthetic_run(tmp_path)
    before = tree_hash(run_dir)
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    assert target == tmp_path / "public" / RUN_ID / "r0001"
    assert tree_hash(run_dir) == before
    verify_integrity(run_dir)
    published = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
    assert set(published) == {"report.html", "report_model.json", "build_manifest.json", "exports/points.csv",
                              "figures/fig-efficiency.svg", "attachments/board.png", "attachments/manifest.json",
                              "publication_manifest.json"}
    for name, path in published.items():
        if name.endswith(".png"):
            continue
        text = path.read_text()
        for secret in (IP, HOST, SERIAL_S, SERIAL_L, PRIVATE_PATH, "/home/tester", "TCPIP0::"):
            assert secret not in text, (name, secret)
    html = published["report.html"].read_text()
    assert "003.371.214.673" in html and "12.1352" in html and "0.0993278" in html and '"1.2.3.4"' in html
    assert "[REDACTED:endpoint]" in html and "[REDACTED:serial]" in html and "[REDACTED:path]" in html
    assert "Redacted publication copy" in html and "not complete raw evidence" in html
    assert '<meta name="dcdc-publication"' in html
    model = json.loads(published["report_model.json"].read_text())
    assert model["points"] == [{"Vin_V": 24.005, "Iin_A": 0.0687}]
    assert model["provenance"]["source_path"] == "[REDACTED:path]"
    assert model["bench"]["source"]["serial"] == "[REDACTED:serial]"
    manifest = json.loads(published["publication_manifest.json"].read_text())
    assert manifest["noindex"] is True and manifest["approval"]["public"] is False
    assert manifest["files"]["build_manifest.json"]["redacted_fields"] == ["artifacts.html.path"]
    assert manifest["files"]["build_manifest.json"]["redactions"] == {"path": 1}
    assert set(manifest["files"]["report_model.json"]["redacted_fields"]) == {"bench.source.serial", "provenance.source_path"}
    assert manifest["redaction"]["totals"]["endpoint"] >= 3 and manifest["redaction"]["totals"]["serial"] >= 3
    assert manifest["redaction"]["totals"]["path"] >= 4
    manifest_text = published["publication_manifest.json"].read_text()
    for secret in (IP, HOST, SERIAL_S, SERIAL_L, PRIVATE_PATH):
        assert secret not in manifest_text
    assert manifest["source_hashes"]["integrity.json"] == hashlib.sha256((run_dir / "integrity.json").read_bytes()).hexdigest()
    assert manifest["source_hashes"]["reports/r0001/report.html"] == hashlib.sha256((run_dir / "reports/r0001/report.html").read_bytes()).hexdigest()
    assert manifest["files"]["report.html"]["sha256_published"] == hashlib.sha256(published["report.html"].read_bytes()).hexdigest()
    assert manifest["source_integrity"] == json.loads((run_dir / "integrity.json").read_text())
    assert "not complete raw evidence" in manifest["completeness"]
    assert "raw/" in manifest["never_published"] and "scpi.jsonl" in manifest["never_published"]
    assert {e.get("attachment_id") for e in manifest["excluded"] if "attachment_id" in e} == {"lab-photo"}
    assert any(e["file"] == "reports/r0001/report.pdf" for e in manifest["excluded"])
    assert any(e["file"] == "reports/r0001/figures/fig-efficiency.pdf" for e in manifest["excluded"])
    assets = json.loads(published["attachments/manifest.json"].read_text())["assets"]
    assert [a["asset_id"] for a in assets] == ["board-photo"] and assets[0]["path"] == "attachments/board.png"
    assert PRIVATE_PATH not in assets[0]["caption"]
    copy = Image.open(io.BytesIO(published["attachments/board.png"].read_bytes()))
    assert list(copy.getdata()) == list(Image.open(io.BytesIO(BOARD_PNG)).getdata()) and dict(copy.getexif()) == {}
    assert manifest["files"]["attachments/board.png"]["metadata_stripped"] is True
    assert manifest["files"]["attachments/board.png"]["listed_in"] == "attachments/manifest.json"
    assert assets[0]["listed_in"] == "attachments/manifest.json" and assets[0]["metadata_stripped"] is True


def test_noindex_retained_by_default_and_injected_if_missing(tmp_path):
    run_dir = synthetic_run(tmp_path)
    html = run_dir / "reports/r0001/report.html"
    html.write_text(html.read_text().replace('<meta name="robots" content="noindex,nofollow">', ""))
    # The synthetic fixture edits its own report before publishing; re-finalize is not needed since reports are not in integrity.
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    published = (target / "report.html").read_text()
    assert published.count('<meta name="robots" content="noindex,nofollow">') == 1
    assert json.loads((target / "publication_manifest.json").read_text())["noindex"] is True


def test_public_true_removes_noindex_only_when_approved(tmp_path):
    run_dir = synthetic_run(tmp_path)
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path, public=True))
    published = (target / "report.html").read_text()
    assert "noindex" not in published and "robots" not in published
    manifest = json.loads((target / "publication_manifest.json").read_text())
    assert manifest["noindex"] is False and manifest["approval"]["public"] is True
    assert "not access control" in manifest["noindex_is_not_access_control"]


def test_serials_kept_and_pdf_included_only_by_explicit_approval(tmp_path):
    run_dir = synthetic_run(tmp_path)
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path, keep_serials=True, include_pdf=True))
    html = (target / "report.html").read_text()
    assert SERIAL_S in html and IP not in html and PRIVATE_PATH not in html
    assert (target / "report.pdf").read_bytes() == (run_dir / "reports/r0001/report.pdf").read_bytes()
    manifest = json.loads((target / "publication_manifest.json").read_text())
    assert "not text-redacted" in manifest["files"]["report.pdf"]["warning"]
    assert manifest["approval"]["keep_serials"] is True


def test_publication_never_writes_into_the_run_folder_or_over_an_existing_copy(tmp_path):
    run_dir = synthetic_run(tmp_path)
    before = tree_hash(run_dir)
    with pytest.raises(ValueError, match="inside the run folder"):
        publish_run(run_dir, "r0001", run_dir / "public", approval_file(tmp_path))
    with pytest.raises(ValueError, match="inside the run folder"):
        publish_run(run_dir, "r0001", run_dir.parent, approval_file(tmp_path))
    assert tree_hash(run_dir) == before
    publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    with pytest.raises(ValueError, match="already exists"):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    assert tree_hash(run_dir) == before


def test_altered_attachment_is_refused(tmp_path):
    run_dir = synthetic_run(tmp_path)
    (run_dir / "attachments/originals/board.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="manifest hash"):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))


def test_missing_revision_or_unfinalized_run_is_refused(tmp_path):
    run_dir = synthetic_run(tmp_path)
    with pytest.raises(ValueError, match="no issued report.html"):
        publish_run(run_dir, "r0002", tmp_path / "public", approval_file(tmp_path, report_revision="r0002"))
    with pytest.raises(ValueError, match="look like r0001"):
        publish_run(run_dir, "latest", tmp_path / "public", approval_file(tmp_path))
    (run_dir / "integrity.json").unlink()
    with pytest.raises(ValueError, match="finalized run folder"):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))


def test_cli_publish_prints_target_and_uses_no_subprocess(tmp_path, no_git_no_network, capsys):
    run_dir = synthetic_run(tmp_path)
    code = cli.main(["publish", str(run_dir), "--revision", "r0001", "--out", str(tmp_path / "public"),
                     "--approval", str(approval_file(tmp_path))])
    assert code == 0
    assert capsys.readouterr().out.strip() == str(tmp_path / "public" / RUN_ID / "r0001")


def test_private_ipv4_pattern_does_not_touch_numeric_evidence_or_versions():
    for text in ("003.371.214.673", "053.177.1.224", "105.323.2.39", "00.01.04.00", "4.1.1", "1.2.3.4",
                 "192.168.77.42.5", "24.005 12.1352", "8.8.8.8"):
        assert PRIVATE_IPV4.search(text) is None, text
    for text in ("192.168.77.42", "10.0.0.7", "172.16.4.200", "169.254.1.1", "127.0.0.1", "at 192.168.77.42."):
        assert PRIVATE_IPV4.search(text) is not None, text
    redactor = Redactor(endpoints={"192.168.77.42"}, serials={"DP8G0000FAKE1"}, paths=set())
    cleaned, counts = redactor.text("Vin 24.005 V; TCPIP0::192.168.77.42::INSTR; serial DP8G0000FAKE1; /home/x/y.json; C:\\Users\\x\\run")
    assert cleaned == "Vin 24.005 V; [REDACTED:endpoint]; serial [REDACTED:serial]; [REDACTED:path]; [REDACTED:path]"
    assert counts == {"endpoint": 1, "serial": 1, "path": 2}


def test_load_approval_requires_explicit_fields(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("run_id: x\nreport_revision: r0001\napprover: A\ndate: 2026-09-27\n")
    with pytest.raises(ValueError, match="public"):
        load_approval(path)
    path.write_text("- not a mapping\n")
    with pytest.raises(ValueError, match="mapping"):
        load_approval(path)


@pytest.mark.parametrize("build_status", ["failed-validation", "unverified", "failed", None])
def test_revision_without_a_successful_build_is_refused_unless_explicitly_allowed(tmp_path, build_status):
    """M6 / brief 12.1: a report validation error blocks an ordinary issued publication."""
    run_dir = synthetic_run(tmp_path, build_status=build_status)
    before = tree_hash(run_dir)
    with pytest.raises(ValueError, match="not 'success'"):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    assert not (tmp_path / "public").exists() and tree_hash(run_dir) == before
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path, allow_unverified=True))
    manifest = json.loads((target / "publication_manifest.json").read_text())
    assert manifest["approval"]["allow_unverified"] is True and manifest["build_status"] == build_status
    assert tree_hash(run_dir) == before


def test_successful_build_publishes_without_the_override_and_records_it(tmp_path):
    target = publish_run(synthetic_run(tmp_path), "r0001", tmp_path / "public", approval_file(tmp_path))
    manifest = json.loads((target / "publication_manifest.json").read_text())
    assert manifest["approval"]["allow_unverified"] is False and manifest["build_status"] == "success"


def sensor_placement_revision(tmp_path, photo, name="private-lab-photo.png"):
    """A finalized run whose r0001 carries sensor markers on a photograph uploaded after finalization,
    with the real assets/ copy, print SVG and HTML section the renderer produces."""
    from dcdc_bench.annotations import annotation_document, annotations_file
    from dcdc_bench.reporting.sensor_placement import with_sensor_placement
    run_dir = synthetic_run(tmp_path)
    entry = AssetStore(run_dir).add(photo, name, caption="Case top, sensors under tape; bench at rigol.local")
    report = run_dir / "reports" / "r0001"
    document = annotation_document(entry["sha256"], [{"sensor_id": "TC1", "x_norm": 0.25, "y_norm": 0.5, "label": "Case top"}])
    (report / "annotations.json").write_text(json.dumps(annotations_file(run_dir, document)))
    body = with_sensor_placement("## Summary\n\ntext\n\n**Run:** x\n", report, str)
    section = body.split("```{=html}", 1)[1].split("```", 1)[0]
    html = report / "report.html"
    html.write_text(html.read_text().replace("</body>", section + "</body>"))
    return run_dir, entry


def test_sensor_placement_photograph_follows_the_attachment_allowlist(tmp_path):
    photo = raster("png", gps=True)
    run_dir, entry = sensor_placement_revision(tmp_path, photo)
    sha, prefix = entry["sha256"], base64.b64encode(photo)[:96]
    before = tree_hash(run_dir)
    # Empty allowlist: the photograph is in no published file; the section keeps its markers and table.
    target = publish_run(run_dir, "r0001", tmp_path / "withheld", approval_file(tmp_path, attachments=[]))
    assert tree_hash(run_dir) == before
    published = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
    assert not any(sha in name for name in published) and "figures/sensor-placement.svg" not in published
    assert not (target / "assets").exists()
    for name, path in published.items():
        data = path.read_bytes()
        assert prefix not in data and photo not in data and b"CAMSERIAL0042" not in data, name
    html = published["report.html"].read_text()
    block = html.split('class="sensor-placement-block"', 1)[1].split("</figure>", 1)[0]
    assert f"assets/{sha}" not in html and "<img" not in block
    assert "Photograph withheld from publication" in block and 'data-withheld="attachment"' in block
    assert 'class="sensor-marker-table"' in html and 'data-sensor-id="TC1"' in html and 'class="sensor-marker"' in html
    assert "rigol.local" not in html and "[REDACTED:hostname]" in html
    manifest = json.loads(published["publication_manifest.json"].read_text())
    excluded_files = {e.get("file") for e in manifest["excluded"]}
    assert {"reports/r0001/figures/sensor-placement.svg", f"reports/r0001/assets/{sha}.png"} <= excluded_files
    assert manifest["attachments"]["withheld_images"] == sorted([f"assets/{sha}.png", "figures/sensor-placement.svg"])
    assert manifest["files"]["report.html"]["images_withheld"] == 1
    assert "figures/sensor-placement.svg" not in manifest["files"]
    assert any(e.get("attachment_id") == entry["asset_id"] and e["listed_in"] == "attachments/revisions/1.json"
               for e in manifest["excluded"])
    # Allowlisting the documentation-revision asset publishes it everywhere, without its metadata.
    target = publish_run(run_dir, "r0001", tmp_path / "allowed", approval_file(tmp_path, attachments=[entry["asset_id"]]))
    assert tree_hash(run_dir) == before
    published = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}
    assert {f"assets/{sha}.png", "figures/sensor-placement.svg", f"attachments/{sha}.png"} <= set(published)
    source_pixels = list(Image.open(io.BytesIO(photo)).getdata())
    for name in (f"assets/{sha}.png", f"attachments/{sha}.png"):
        copy = Image.open(io.BytesIO(published[name].read_bytes()))
        assert dict(copy.getexif()) == {} and list(copy.getdata()) == source_pixels, name
    svg = published["figures/sensor-placement.svg"].read_text()
    payload = re.search(r"base64,([A-Za-z0-9+/=]+)", svg).group(1)
    inner = Image.open(io.BytesIO(base64.b64decode(payload)))
    assert dict(inner.getexif()) == {} and list(inner.getdata()) == source_pixels and prefix.decode() not in svg
    html = published["report.html"].read_text()
    assert f'src="assets/{sha}.png"' in html and "withheld" not in html
    manifest = json.loads(published["publication_manifest.json"].read_text())
    assert manifest["attachments"]["withheld_images"] == [] and "images_withheld" not in manifest["files"]["report.html"]
    for name in (f"assets/{sha}.png", f"attachments/{sha}.png", "figures/sensor-placement.svg"):
        assert manifest["files"][name]["metadata_stripped"] is True, name
    assert manifest["files"][f"attachments/{sha}.png"]["listed_in"] == "attachments/revisions/1.json"
    assert manifest["files"]["figures/sensor-placement.svg"]["embedded_attachments"] == [sha]
    revision_file = run_dir / "attachments/revisions/1.json"
    assert manifest["source_hashes"]["attachments/revisions/1.json"] == hashlib.sha256(revision_file.read_bytes()).hexdigest()


def test_published_photographs_carry_no_exif_gps_and_originals_stay_untouched(tmp_path):
    run_dir = synthetic_run(tmp_path)
    original_path = run_dir / "attachments/originals/private-lab.jpg"
    original = original_path.read_bytes()
    assert 0x8825 in Image.open(io.BytesIO(original)).getexif() and b"CAMSERIAL0042" in original
    target = publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path, attachments=["board-photo", "lab-photo"]))
    copy = (target / "attachments/private-lab.jpg").read_bytes()
    image = Image.open(io.BytesIO(copy))
    assert dict(image.getexif()) == {} and b"CAMSERIAL0042" not in copy and image.size == (8, 6)
    assert original_path.read_bytes() == original
    manifest = json.loads((target / "publication_manifest.json").read_text())
    record = manifest["files"]["attachments/private-lab.jpg"]
    assert record["metadata_stripped"] is True and "EXIF" in record["warning"]
    assert record["sha256_published"] == hashlib.sha256(copy).hexdigest() != record["sha256_source"]
    assert "EXIF" in manifest["attachments"]["metadata_policy"]


def test_plotly_runtime_is_left_intact_while_prose_hostnames_are_redacted(tmp_path):
    run_dir = synthetic_run(tmp_path)
    report = run_dir / "reports/r0001"
    html = report / "report.html"
    html.write_text(html.read_text().replace(
        "</body>", '<figcaption>Load at rigol.local, source at bench.rigol.local; docs at sub.example.com</figcaption>'
        f'<script id="dcdc-plotly-runtime">{PLOTLY_EXCERPT}</script></body>'))
    built = json.loads((report / "build_manifest.json").read_text())
    built["plotly_js_sha256"] = hashlib.sha256(PLOTLY_EXCERPT.encode()).hexdigest()
    (report / "build_manifest.json").write_text(json.dumps(built))
    target = publish_run(run_dir, "r0001", tmp_path / "verified", approval_file(tmp_path))
    published = (target / "report.html").read_text()
    assert PLOTLY_EXCERPT in published, "the vendor runtime is byte-identical"
    assert "rigol.local" not in published and "sub.example.com" in published
    assert published.count("[REDACTED:hostname]") == 2
    manifest = json.loads((target / "publication_manifest.json").read_text())
    record = manifest["files"]["report.html"]
    assert record["plotly_runtime"] == {"sha256": built["plotly_js_sha256"], "verified": True, "redacted": False}
    assert record["redactions"]["hostname"] == 2 and manifest["redaction"]["totals"]["hostname"] == 2
    # Without a matching recorded hash the block is not trusted: redacted like any text, and flagged.
    del built["plotly_js_sha256"]
    (report / "build_manifest.json").write_text(json.dumps(built))
    target = publish_run(run_dir, "r0001", tmp_path / "unverified", approval_file(tmp_path))
    manifest = json.loads((target / "publication_manifest.json").read_text())
    assert manifest["files"]["report.html"]["plotly_runtime"]["verified"] is False
    assert PLOTLY_EXCERPT not in (target / "report.html").read_text()


def test_local_hostname_pattern_skips_javascript_member_access():
    for text in ("ua.local.invalidDate", "this.local=this.regionalOptions", "$m.local.invalidYear", "z.local?ne:Z",
                 "hc.local.unexpectedText||x", "this.local(1)", "a.home[0]", "x-.local", "foo.local-bar"):
        assert LOCAL_HOSTNAME.search(text) is None, text
    for text in ("at rigol.local,", "rigol.local", "TCPIP0::rigol.local::INSTR", '"bench.rigol.local"', ">dp832.lan<",
                 "load-bench.home.", "host=rigol.internal;", "(rigol.localdomain)"):
        assert LOCAL_HOSTNAME.search(text) is not None, text
    cleaned, counts = Redactor(endpoints=set(), serials=set(), paths=set()).text("at bench.rigol.local, not sub.example.com")
    assert cleaned == "at [REDACTED:hostname], not sub.example.com" and counts == {"hostname": 1}


def test_symlinked_report_files_are_refused_not_followed(tmp_path):
    run_dir = synthetic_run(tmp_path)
    secret = tmp_path / "id_ed25519"
    secret.write_text("PRIVATE KEY MATERIAL")
    planted = run_dir / "reports/r0001/figures/planted.svg"
    planted.symlink_to(secret)
    with pytest.raises(ValueError, match="symbolic link"):
        publish_run(run_dir, "r0001", tmp_path / "public", approval_file(tmp_path))
    assert not [p for p in (tmp_path / "public").rglob("*") if p.is_file() and b"PRIVATE KEY" in p.read_bytes()]
    planted.unlink()
    (run_dir / "reports/r0001/report_profile.json").symlink_to(secret)
    with pytest.raises(ValueError, match="symbolic link"):
        publish_run(run_dir, "r0001", tmp_path / "public2", approval_file(tmp_path))


@pytest.mark.parametrize("text,match", [
    ("run_id: &a x\nreport_revision: r0001\napprover: *a\ndate: '2026-09-27'\npublic: false\n", "anchors"),
    ("attachments: [*a]\nrun_id: x\n", "aliases"),
    ("a: &a [x, x, x, x, x, x, x, x, x]\nb: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\nattachments: *b\n", "anchors"),
    ("x: " + "[" * 40 + "]" * 40 + "\n", "deeper"),
    ("run_id: x\nreport_revision: r0001\napprover: A\ndate: 2026-09-27T10:00:00\npublic: false\n", "invalid"),
])
def test_approval_yaml_anchors_aliases_deep_nesting_and_datetimes_are_refused(tmp_path, text, match):
    path = tmp_path / "approval.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match=match):
        load_approval(path)


def test_documented_approval_example_loads_with_its_unquoted_date(tmp_path):
    doc = (Path(__file__).resolve().parents[1] / "docs" / "doctor-and-publication.md").read_text()
    block = doc.split("```yaml", 1)[1].split("```", 1)[0]
    assert "date: 2026-09-27" in block, "the documented example keeps an unquoted calendar date"
    path = tmp_path / "approval.yaml"
    path.write_text(block)
    approval = load_approval(path)
    assert approval.date == "2026-09-27" and approval.report_revision == "r0002"
    assert approval.attachments == ["board-photo"] and approval.public is False
    path.write_text("run_id: x\nreport_revision: r0001\napprover: A\ndate: 2026-09-27\npublic: false\nattachments: "
                    + json.dumps([f"a{i}" for i in range(101)]) + "\n")
    with pytest.raises(ValueError, match="at most 100"):
        load_approval(path)
