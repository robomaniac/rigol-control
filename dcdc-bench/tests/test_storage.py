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
