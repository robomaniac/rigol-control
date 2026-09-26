"""Results layout, JSONL, and CSV export tests."""

import csv
import json
import re

import pytest

from benchctl import results

RUN_DIR_RE = re.compile(r"^\d{8}T\d{6}Z_[A-Za-z0-9_.\-]+$")


# -- run directory -----------------------------------------------------------------


def test_create_run_dir_naming(tmp_path):
    run_dir = results.create_run_dir("basic_load_test", base=tmp_path / "results")
    assert run_dir.is_dir()
    assert run_dir.parent == tmp_path / "results"
    assert RUN_DIR_RE.match(run_dir.name)
    assert run_dir.name.endswith("_basic_load_test")


def test_create_run_dir_collision_gets_suffix(tmp_path):
    first = results.create_run_dir("recipe", base=tmp_path / "results")
    second = results.create_run_dir("recipe", base=tmp_path / "results")
    assert first != second
    assert first.is_dir() and second.is_dir()


def test_create_run_dir_sanitizes_name(tmp_path):
    run_dir = results.create_run_dir("weird name/../x", base=tmp_path / "results")
    assert "/" not in run_dir.name
    assert " " not in run_dir.name
    assert run_dir.parent == tmp_path / "results"


# -- measurements JSONL --------------------------------------------------------------


def test_append_measurement_jsonl_contents(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_measurement(
        run_dir,
        save_as="point_1",
        values={"v": 5.0, "i": 0.25},
        setup="main_bench",
        recipe_name="basic_load_test",
    )
    results.append_measurement(
        run_dir,
        save_as="point_2",
        values={"v": 4.9, "i": 0.30},
        setup="main_bench",
        recipe_name="basic_load_test",
    )

    lines = (run_dir / "measurements.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["save_as"] == "point_1"
    assert first["values"] == {"v": 5.0, "i": 0.25}
    assert first["setup"] == "main_bench"
    assert first["recipe"] == "basic_load_test"
    assert first["timestamp"].endswith("+00:00")
    assert json.loads(lines[1])["save_as"] == "point_2"


def test_append_measurement_records_per_value_verdicts(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_measurement(
        run_dir,
        save_as="point",
        values={"v": 5.0, "i": 0.25},
        setup="main_bench",
        recipe_name="r",
        status="pass",
        verdicts={
            "v": {"status": "pass", "min": 0.0, "max": 6.0},
            "i": {"status": "not_checked"},
        },
    )
    record = json.loads(
        (run_dir / "measurements.jsonl").read_text(encoding="utf-8")
    )
    assert record["status"] == "pass"
    assert record["values"] == {"v": 5.0, "i": 0.25}
    assert record["verdicts"]["v"]["max"] == 6.0
    assert record["verdicts"]["i"]["status"] == "not_checked"


def test_append_measurement_legacy_shape_remains_supported(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    record = results.append_measurement(
        run_dir,
        save_as="legacy",
        values={"v": 5.0},
        setup="main_bench",
        recipe_name="r",
    )
    assert "status" not in record
    assert "verdicts" not in record


def test_append_event_execution_log(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_event(
        run_dir, phase="steps", index=0, action="supply.configure",
        detail={"channel": 1, "voltage_v": 5.0},
    )
    results.append_event(
        run_dir, phase="finally", index=0, action="load.input_off", error="boom"
    )

    lines = (run_dir / "execution.jsonl").read_text(encoding="utf-8").splitlines()
    ok, failed = (json.loads(line) for line in lines)
    assert ok["status"] == "ok"
    assert ok["detail"] == {"channel": 1, "voltage_v": 5.0}
    assert failed["status"] == "error"
    assert failed["error"] == "boom"


# -- run summary ---------------------------------------------------------------------


def test_write_run_summary(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.write_run_summary(
        run_dir,
        recipe_name="basic_load_test",
        setup="main_bench",
        parameters={"voltage_v": 5.0},
        started_at="2026-08-15T00:00:00+00:00",
        finished_at="2026-08-15T00:00:05+00:00",
        status="failed",
        error="RuntimeError: boom",
        identities={"supply": {"model": "DP821A"}},
    )
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert summary["recipe"] == "basic_load_test"
    assert summary["setup"] == "main_bench"
    assert summary["parameters"] == {"voltage_v": 5.0}
    assert summary["status"] == "failed"
    assert summary["outcome"] == "error"
    assert summary["error"] == "RuntimeError: boom"
    assert summary["identities"]["supply"]["model"] == "DP821A"


def test_write_run_summary_accepts_explicit_failed_expectation_outcome(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.write_run_summary(
        run_dir,
        recipe_name="r",
        setup="s",
        parameters={},
        started_at="2026-08-15T00:00:00+00:00",
        finished_at="2026-08-15T00:00:01+00:00",
        status="failed",
        outcome="fail",
        error="expectation failed",
    )
    summary = json.loads((run_dir / "run.json").read_text())
    assert summary["status"] == "failed"
    assert summary["outcome"] == "fail"


# -- CSV export ----------------------------------------------------------------------


def test_export_csv_roundtrip(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_measurement(
        run_dir, save_as="a", values={"v": 5.0, "i": 0.25},
        setup="main_bench", recipe_name="r",
    )
    # Second record has a different label set; missing columns stay blank.
    results.append_measurement(
        run_dir, save_as="b", values={"v": 4.9, "p": 1.2},
        setup="main_bench", recipe_name="r",
    )

    csv_path = results.export_csv(run_dir)
    assert csv_path == run_dir / "measurements.csv"
    with open(csv_path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 2
    assert rows[0]["save_as"] == "a"
    assert float(rows[0]["v"]) == 5.0
    assert float(rows[0]["i"]) == 0.25
    assert rows[0]["p"] == ""
    assert rows[1]["save_as"] == "b"
    assert float(rows[1]["v"]) == 4.9
    assert float(rows[1]["p"]) == 1.2
    assert rows[1]["i"] == ""
    assert all(row["recipe"] == "r" and row["setup"] == "main_bench" for row in rows)


def test_export_csv_explicit_path(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_measurement(
        run_dir, save_as="a", values={"v": 1.0}, setup="s", recipe_name="r"
    )
    target = tmp_path / "out.csv"
    assert results.export_csv(run_dir, target) == target
    assert target.exists()


def test_export_csv_includes_measurement_and_verdict_columns(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    results.append_measurement(
        run_dir,
        save_as="checked",
        values={"v": 6.1},
        setup="s",
        recipe_name="r",
        status="fail",
        verdicts={
            "v": {
                "status": "fail",
                "max": 6.0,
                "reason": "above maximum 6.0",
            }
        },
    )
    csv_path = results.export_csv(run_dir)
    with open(csv_path, encoding="utf-8", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["measurement_status"] == "fail"
    assert row["v__verdict"] == "fail"
    assert float(row["v__max"]) == 6.0
    assert row["v__reason"] == "above maximum 6.0"


def test_export_csv_without_measurements_fails(tmp_path):
    run_dir = results.create_run_dir("r", base=tmp_path)
    with pytest.raises(FileNotFoundError):
        results.export_csv(run_dir)
