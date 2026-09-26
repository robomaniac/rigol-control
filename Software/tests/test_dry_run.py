"""Plan validation must never open hardware or create a run directory."""

from pathlib import Path

import yaml

from benchctl.cli import main


def _args(tmp_path, voltage=5):
    software = Path(__file__).resolve().parents[1]
    recipe = tmp_path / "plan.yaml"
    recipe.write_text(yaml.safe_dump({
        "schema_version": 1, "name": "offline_check",
        "requires": {"supply": {"kind": "power_supply"}},
        "steps": [
            {"action": "supply.configure", "channel": 1, "voltage_v": voltage, "current_limit_a": .5},
            {"action": "supply.output_on", "channel": 1},
            {"action": "wait", "seconds": 4},
            {"action": "measure", "save_as": "voltage", "values": {
                "voltage_v": {"source": "supply.voltage", "channel": 1},
            }},
        ],
        "finally": [{"action": "supply.output_off", "channel": 1}],
    }))
    return ["run", str(recipe), "--setup", "main_bench", "--dry-run",
            "--config", str(software / "config/lab.example.yaml"),
            "--safety-profiles", str(software / "config/safety_profiles.yaml"),
            "--results-dir", str(tmp_path / "results")]


def test_dry_run_checks_plan_without_hardware_or_results(tmp_path, monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("dry-run must not execute a recipe")
    monkeypatch.setattr("benchctl.runner.run_recipe", unexpected)
    assert main(_args(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "plan valid: offline_check" in output
    assert "1 measurements" in output
    assert "4 seconds" in output
    assert not (tmp_path / "results").exists()


def test_dry_run_rejects_unsafe_setpoint_without_hardware(tmp_path, monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid plan must not execute")
    monkeypatch.setattr("benchctl.runner.run_recipe", unexpected)
    assert main(_args(tmp_path, voltage=1000)) == 2
    assert "unsafe setpoint" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()
