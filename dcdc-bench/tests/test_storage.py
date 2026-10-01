"""Acquisition manifest coverage for optional real-instrument transcripts."""
import hashlib
import json
import os

import pytest

from dcdc_bench.storage import PersistenceError, RunStore, verify_integrity


@pytest.mark.parametrize("has_transcript", [False, True])
def test_finalization_covers_optional_scpi_transcript_and_detects_later_changes(tmp_path, has_transcript):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {"execution_status": "running"})
    transcript = store.path / "scpi.jsonl"
    original = b'{"command":":OUTP? CH1","response":"OFF"}\n'
    if has_transcript:
        transcript.write_bytes(original)
    store.finalize({"execution_status": "completed"})
    manifest = json.loads((store.path / "integrity.json").read_text())
    assert ("scpi.jsonl" in manifest["files"]) is has_transcript
    verify_integrity(store.path)
    if has_transcript:
        assert manifest["files"]["scpi.jsonl"] == hashlib.sha256(original).hexdigest()
        transcript.write_bytes(original.replace(b"OFF", b"ON"))
        with pytest.raises(ValueError, match="scpi.jsonl"):
            verify_integrity(store.path)


def test_failed_transcript_fsync_cannot_issue_an_integrity_manifest(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "run")
    store.initialize({}, {}, {})
    transcript = store.path / "scpi.jsonl"
    transcript.write_text('{"command":":OUTP CH1,OFF"}\n')
    transcript_inode = transcript.stat().st_ino
    original_fsync = os.fsync

    def fail_transcript_fsync(fd):
        if os.fstat(fd).st_ino == transcript_inode:
            raise OSError("Simulated transcript storage failure")
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_transcript_fsync)
    with pytest.raises(PersistenceError, match="cannot persist scpi.jsonl"):
        store.finalize({"execution_status": "completed"})
    assert not (store.path / "integrity.json").exists()


@pytest.mark.parametrize('missing', [None, 'run.json', 'plan.json', 'request.json', 'raw/samples.jsonl'])
def test_integrity_rejects_empty_or_incomplete_coverage(tmp_path, missing):
    store = RunStore(tmp_path / 'run')
    store.initialize({}, {}, {})
    store.finalize({})
    path = store.path / 'integrity.json'
    manifest = json.loads(path.read_text())
    if missing is None:
        manifest['files'] = {}
    else:
        del manifest['files'][missing]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='required report evidence'):
        verify_integrity(store.path)


def test_integrity_rejects_symlink_outside_run_even_with_matching_bytes(tmp_path):
    store = RunStore(tmp_path / 'run')
    store.initialize({}, {}, {})
    store.finalize({})
    original = store.path / 'raw/samples.jsonl'
    outside = tmp_path / 'outside.jsonl'
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)
    with pytest.raises(ValueError, match='invalid integrity path'):
        verify_integrity(store.path)


def test_legacy_manifest_without_optional_transcript_remains_verifiable(tmp_path):
    store = RunStore(tmp_path / 'run')
    store.initialize({}, {}, {})
    store.finalize({})
    path = store.path / 'integrity.json'
    manifest = json.loads(path.read_text())
    manifest['files'] = {name: manifest['files'][name] for name in
                         ('run.json', 'plan.json', 'request.json', 'raw/samples.jsonl')}
    path.write_text(json.dumps(manifest))
    verify_integrity(store.path)
