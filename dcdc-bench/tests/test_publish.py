"""Publication gate (PUB-01): approval record, redaction, noindex, no git/gh/network, source untouched."""
import hashlib
import json
import os
import socket
import subprocess

import pytest
import yaml

from dcdc_bench import cli
from dcdc_bench.publish import PRIVATE_IPV4, Redactor, load_approval, publish_run
from dcdc_bench.storage import RunStore, verify_integrity

RUN_ID = "20260927T120000.000000Z_real_abc123"
IP, HOST, SERIAL_S, SERIAL_L = "192.168.1.100", "load-bench.local", "DP8G0000FAKE1", "DL3A0000FAKE2"
PRIVATE_PATH = "/home/tester/rigol-control/dcdc-bench/runs/real-extended/" + RUN_ID


def tree_hash(folder):
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(folder)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def synthetic_run(tmp_path, *, revision="r0001", with_pdf=True):
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
    (originals / "board.png").write_bytes(b"\x89PNG fake board photo")
    (originals / "private-lab.jpg").write_bytes(b"\xff\xd8 fake private photo")
    manifest = {"assets": [
        {"asset_id": "board-photo", "path": "originals/board.png", "sha256": hashlib.sha256(b"\x89PNG fake board photo").hexdigest(),
         "caption": f"Board photo taken at {PRIVATE_PATH}/attachments", "role": "board_photo"},
        {"asset_id": "lab-photo", "path": "originals/private-lab.jpg", "sha256": hashlib.sha256(b"\xff\xd8 fake private photo").hexdigest(),
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
    (report / "build_manifest.json").write_text(json.dumps({
        "artifacts": {"html": {"path": PRIVATE_PATH + f"/reports/{revision}/report.html", "sha256": "x"}},
        "versions": {"plotly_js": "4.1.1"}}))
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
    assert published["attachments/board.png"].read_bytes() == b"\x89PNG fake board photo"


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
                 "192.168.1.100.5", "24.005 12.1352", "8.8.8.8"):
        assert PRIVATE_IPV4.search(text) is None, text
    for text in ("192.168.1.100", "10.0.0.7", "172.16.4.200", "169.254.1.1", "127.0.0.1", "at 192.168.1.100."):
        assert PRIVATE_IPV4.search(text) is not None, text
    redactor = Redactor(endpoints={"192.168.1.100"}, serials={"DP8G0000FAKE1"}, paths=set())
    cleaned, counts = redactor.text("Vin 24.005 V; TCPIP0::192.168.1.100::INSTR; serial DP8G0000FAKE1; /home/x/y.json; C:\\Users\\x\\run")
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
