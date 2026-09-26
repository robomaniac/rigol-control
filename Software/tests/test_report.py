"""Saved-run reports show measurements without needing instrument access."""

import json

from benchctl.cli import main
from benchctl.report import ReportError, Sample, _read_run, generate_report, render_report


def _run_dir(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps({
            "recipe": "supply_load_sweep",
            "setup": "main_bench",
            "outcome": "pass",
            "started_at": "2026-09-24T10:00:00+00:00",
            "finished_at": "2026-09-24T10:00:05+00:00",
        }),
        encoding="utf-8",
    )
    records = [
        {"save_as": "step_0p10_a", "timestamp": "2026-09-24T10:00:01+00:00", "status": "pass", "values": {
            "supply_voltage_v": 5.01, "load_voltage_v": 4.99,
            "load_current_a": 0.1, "load_power_w": 0.499,
        }},
        {"save_as": "step_0p50_a", "timestamp": "2026-09-24T10:00:02+00:00", "status": "pass", "values": {
            "supply_voltage_v": 5.00, "load_voltage_v": 4.95,
            "load_current_a": 0.5, "load_power_w": 2.475,
        }},
    ]
    (run_dir / "measurements.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    events = [
        {"phase": "steps", "action": "load.configure_cc", "status": "ok", "detail": {"current_a": 0.1}},
        {"phase": "steps", "action": "load.input_on", "status": "ok"},
        {"phase": "steps", "action": "measure", "status": "ok", "detail": {"save_as": "step_0p10_a"}},
        {"phase": "steps", "action": "load.input_off", "status": "ok"},
        {"phase": "steps", "action": "load.configure_cc", "status": "ok", "detail": {"current_a": 0.5}},
        {"phase": "steps", "action": "load.input_on", "status": "ok"},
        {"phase": "steps", "action": "measure", "status": "ok", "detail": {"save_as": "step_0p50_a"}},
    ]
    (run_dir / "execution.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    return run_dir


def test_report_plots_measured_values_and_derived_quantities(tmp_path):
    run_dir = _run_dir(tmp_path)
    path = generate_report(run_dir)
    page = path.read_text(encoding="utf-8")

    assert path == run_dir / "report.html"
    assert "Voltage reaching the device" in page
    assert "Power used by the device" in page
    assert "Voltage difference between supply and device" in page
    assert "Measured load current (mA)" in page
    assert "step_0p50_a" in page
    assert "50 mV" in page
    assert "100 mΩ" in page
    assert "2.475 W" in page
    assert "500 mA" in page
    assert page.count("<svg ") == 4
    assert "Estimated lead resistance (mΩ)" in page
    assert "Requested load current (A)" in page
    assert "Instrument offset, contacts" in page


def test_cli_report_uses_saved_data_only(tmp_path, monkeypatch, capsys):
    run_dir = _run_dir(tmp_path)

    def fail_if_hardware(*_args, **_kwargs):
        raise AssertionError("report tried to connect to hardware")

    monkeypatch.setattr("benchctl.cli.make_transport", fail_if_hardware)
    target = tmp_path / "shared" / "run-report.html"
    assert main(["report", str(run_dir), "--output", str(target)]) == 0
    assert target.exists()
    assert f"report written: {target}" in capsys.readouterr().out


def test_latest_selects_exact_recipe_by_completion_time(tmp_path, capsys):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    for directory_name, recipe, finished_at in (
        ("older", "supply_load_sweep", "2026-09-24T09:00:00+00:00"),
        ("newer", "supply_load_sweep", "2026-09-24T10:00:00+00:00"),
        ("other", "supply_load_sweep_extra", "2026-09-24T11:00:00+00:00"),
    ):
        run_dir = results_dir / directory_name
        run_dir.mkdir()
        (run_dir / "run.json").write_text(
            json.dumps({"recipe": recipe, "finished_at": finished_at, "status": "success"}),
            encoding="utf-8",
        )
    assert main(["report", "--latest", "supply_load_sweep", "--results-dir", str(results_dir)]) == 0
    assert (results_dir / "newer" / "report.html").exists()
    assert not (results_dir / "older" / "report.html").exists()
    assert not (results_dir / "other" / "report.html").exists()
    assert "newer/report.html" in capsys.readouterr().out


def test_cli_report_requires_one_run_selection(tmp_path, capsys):
    run_dir = _run_dir(tmp_path)
    assert main(["report"]) == 2
    assert main(["report", str(run_dir), "--latest", "supply_load_sweep"]) == 2
    assert "provide RUN_DIR or --latest" in capsys.readouterr().err


def test_simulated_report_cannot_present_a_passing_measured_run(tmp_path):
    run_dir = _run_dir(tmp_path)
    path = run_dir / "run.json"
    summary = json.loads(path.read_text())
    summary["data_source"] = "simulated"
    path.write_text(json.dumps(summary))
    page = generate_report(run_dir).read_text()
    assert 'class="badge neutral">SIMULATED</span>' in page
    assert "No hardware measurements were taken" in page
    assert 'class="badge pass">PASS</span>' not in page


def test_partial_run_and_missing_values_are_visible(tmp_path):
    run_dir = tmp_path / "partial"
    run_dir.mkdir()
    (run_dir / "measurements.jsonl").write_text(
        '{"save_as":"first","values":{"load_current_a":0,"load_voltage_v":4.9}}\n'
        '{"save_as":"second","values":{"load_current_a":0.2,"load_voltage_v":4.8,"supply_voltage_v":5.0}}\n'
        '{"save_as":"truncated"\n',
        encoding="utf-8",
    )
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert "Run summary is missing" in page
    assert "Measurement line 3 is invalid JSON" in page
    assert "second" in page
    assert "first" in page
    assert "200 mV" in page
    assert "1,000 mΩ" in page
    assert "INCOMPLETE" in page


def test_empty_run_still_has_readable_report(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert "No measurements file was found" in page
    assert "No matching measured values are available" in page
    assert "No measured samples are available" in page


def test_legacy_success_means_completed_without_acceptance_verdict(tmp_path):
    run_dir = _run_dir(tmp_path)
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    summary.pop("outcome")
    summary["status"] = "success"
    (run_dir / "run.json").write_text(json.dumps(summary), encoding="utf-8")
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert 'class="badge neutral">COMPLETED</span>' in page
    assert "completion does not establish that requested values were met" in page


def test_report_highlights_largest_requested_current_error(tmp_path):
    run_dir = _run_dir(tmp_path)
    path = run_dir / "measurements.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["values"]["load_current_a"] = 0.013
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert "Largest current error" in page
    assert "87 %" in page
    assert "step_0p10_a" in page


def test_report_shows_supply_and_load_current_gap(tmp_path):
    run_dir = _run_dir(tmp_path)
    path = run_dir / "measurements.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[0]["values"]["supply_current_a"] = 0.085
    records[1]["values"]["supply_current_a"] = 0.495
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert "Largest instrument current gap" in page
    assert "15 mA" in page
    assert "Supply − load current (mA)" in page
    assert "instrument offsets and timing" in page


def test_no_load_baseline_adds_supply_droop(tmp_path):
    run_dir = _run_dir(tmp_path)
    path = run_dir / "measurements.jsonl"
    initial = path.read_text(encoding="utf-8")
    baseline = {"save_as": "no_load", "values": {
        "supply_voltage_v": 5.02, "load_voltage_v": 5.01,
        "load_current_a": 0.0, "load_power_w": 0.0,
    }}
    path.write_text(json.dumps(baseline) + "\n" + initial, encoding="utf-8")
    events_path = run_dir / "execution.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    events[0:0] = [
        {"phase": "steps", "action": "load.input_off", "status": "ok"},
        {"phase": "steps", "action": "measure", "status": "ok", "detail": {"save_as": "no_load"}},
    ]
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    _, samples, _ = _read_run(run_dir)
    assert samples[0].requested_current_a is None
    assert samples[1].requested_current_a == 0.1
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert "No-load supply voltage" in page
    assert "Supply droop from no-load (%)" in page
    assert "0.4 %" in page  # (5.02 - 5.00) / 5.02 * 100
    assert "no_load" in page


def test_imported_text_is_escaped(tmp_path):
    run_dir = _run_dir(tmp_path)
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    summary["recipe"] = '<img src=x onerror="alert(1)">'
    summary["error"] = "<script>alert(2)</script>"
    (run_dir / "run.json").write_text(json.dumps(summary), encoding="utf-8")
    record = {"save_as": '<svg onload="alert(3)">', "values": {"load_current_a": 0.2}}
    with (run_dir / "measurements.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    page = generate_report(run_dir).read_text(encoding="utf-8")
    assert '<img src=x onerror="alert(1)">' not in page
    assert "<script>" not in page
    assert '<svg onload="alert(3)">' not in page
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in page


def test_report_refuses_to_overwrite_source_data(tmp_path):
    run_dir = _run_dir(tmp_path)
    before = (run_dir / "run.json").read_text(encoding="utf-8")
    try:
        generate_report(run_dir, run_dir / "run.json")
    except ReportError as exc:
        assert "overwrite run data" in str(exc)
    else:
        raise AssertionError("expected ReportError")
    assert (run_dir / "run.json").read_text(encoding="utf-8") == before


def _embedded_data(page):
    import re
    return json.loads(re.search(r'<script id="report-data" type="application/json">(.*?)</script>', page, re.S)[1])


def test_interactive_data_cannot_close_script_or_create_markup(tmp_path):
    run_dir = _run_dir(tmp_path)
    attack = '</script><script>alert("injected")</script><img src=x onerror=alert(1)>'
    record = {"save_as": attack, "status": attack, "values": {"load_current_a": 0.1}}
    with (run_dir / "measurements.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")
    page = generate_report(run_dir).read_text()
    assert attack not in page
    assert _embedded_data(page)[-1]["label"] == attack
    assert page.count("</script>") == 2
    assert 'innerHTML' not in page


def test_inline_script_matches_csp_hash(tmp_path):
    import base64
    import hashlib
    import re
    page = generate_report(_run_dir(tmp_path)).read_text()
    script = re.search(r'<script type="text/javascript">(.*?)</script>', page, re.S)[1]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in page
    assert 'script-src \'unsafe-inline\'' not in page
    assert 'script src=' not in page


def test_csv_retains_precision_and_escapes_spreadsheet_formulas(tmp_path):
    import base64
    import csv
    import io
    import re
    run_dir = _run_dir(tmp_path)
    record = {"save_as": '=HYPERLINK("evil")', "values": {"load_current_a": 0.123456789012}}
    with (run_dir / "measurements.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")
    page = generate_report(run_dir).read_text()
    data = base64.b64decode(re.search(r'href="data:text/csv;base64,([^"]+)"', page)[1]).decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(data)))
    assert len(rows) == 3
    assert rows[-1]["Step"] == '\'=HYPERLINK("evil")'
    assert rows[-1]["Load Current (A)"] == '0.123456789012'
    assert rows[0]["Requested load current (A)"] == '0.1'
    assert rows[-1]["Requested load current (A)"] == ''


def test_return_sweep_preserves_point_identity_order_and_recorded_direction(tmp_path):
    import re
    run_dir = _run_dir(tmp_path)
    targets = [0.05 + n * 0.025 for n in range(11)] + [0.05 + n * 0.025 for n in range(9, -1, -1)]
    records, events = [], []
    for index, target in enumerate(targets):
        # Repeated labels intentionally exercise queue matching, not label parsing.
        records.append({"save_as": "same_label", "status": "pass", "values": {
            "load_current_a": target - 0.001, "supply_voltage_v": 5.0,
            "load_voltage_v": 5.0 - target * 0.1 - index * 0.00001,
            "load_power_w": target * 4.99,
        }})
        events.extend([
            {"phase": "steps", "action": "load.configure_cc", "status": "ok", "detail": {"current_a": target}},
            {"phase": "steps", "action": "load.input_on", "status": "ok"},
            {"phase": "steps", "action": "measure", "status": "ok", "detail": {"save_as": "same_label"}},
        ])
    (run_dir / "measurements.jsonl").write_text(''.join(json.dumps(item) + '\n' for item in records))
    (run_dir / "execution.jsonl").write_text(''.join(json.dumps(item) + '\n' for item in events))
    page = generate_report(run_dir).read_text()
    samples = _embedded_data(page)
    assert len(samples) == 21
    assert [sample["requested_current_a"] for sample in samples] == targets
    assert samples[0]["values"]["load_current_a"] == 0.049
    assert all(sample["direction"] == "Increasing demand" for sample in samples[:11])
    assert all(sample["direction"] == "Reducing demand" for sample in samples[11:])
    chart = re.search(r'<section class="chart-card featured" id="drop-chart"(.*?)</section>', page, re.S)[1]
    indices = [int(index) for index in re.findall(r'data-sample="(\d+)"', chart)]
    assert indices == list(range(11)) + list(range(10, 21))  # Shared measured turning point.
    assert 'data-series="Increasing demand"' in chart
    assert 'data-series="Reducing demand"' in chart
    assert 'id="point-range"' in page
    assert 'aria-live="polite"' in page


def test_nonfinite_and_missing_measurements_do_not_leak_into_chart_data(tmp_path):
    run_dir = _run_dir(tmp_path)
    records = [
        {"save_as": "invalid", "values": {"load_current_a": float("nan"), "load_voltage_v": float("inf"), "load_power_w": True}},
        {"save_as": "partial", "values": {"load_current_a": 0.2, "load_voltage_v": None}},
    ]
    (run_dir / "measurements.jsonl").write_text(''.join(json.dumps(item) + '\n' for item in records))
    page = generate_report(run_dir).read_text()
    data = _embedded_data(page)
    assert data[0]["values"] == {}
    assert data[1]["values"] == {"load_current_a": 0.2}
    assert data[0]["voltage_drop_mv"] is None
    assert 'data-value="nan"' not in page
    assert 'data-value="inf"' not in page
    assert 'No matching measured values are available.' in page


def test_plain_labels_use_recorded_demand_and_preserve_raw_ids_only_for_export(tmp_path):
    import re
    run_dir = _run_dir(tmp_path)
    page = generate_report(run_dir).read_text()
    data = _embedded_data(page)
    assert data[0]["display_label"] == "100 mA · Increasing demand"
    assert data[1]["display_label"] == "500 mA · Increasing demand"
    assert data[0]["label"] == "step_0p10_a"
    visible = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    assert "step_0p10_a" not in visible
    assert "step_0p50_a" not in visible
    assert "sample.display_label" in page
    assert "sample.label" not in page


def test_missing_execution_log_cannot_turn_step_name_into_requested_current(tmp_path):
    run_dir = _run_dir(tmp_path)
    (run_dir / "execution.jsonl").unlink()
    page = generate_report(run_dir).read_text()
    sample = _embedded_data(page)[0]
    assert sample["requested_current_a"] is None
    assert sample["display_label"] == "100 mA measured · reading 1"
    assert "Before drawing current" not in page


def test_recorded_off_state_gets_plain_baseline_name(tmp_path):
    run_dir = _run_dir(tmp_path)
    measurements = run_dir / "measurements.jsonl"
    measurements.write_text(json.dumps({"save_as": "arbitrary_baseline_id", "values": {"supply_voltage_v": 5.0}}) + "\n" + measurements.read_text())
    execution = run_dir / "execution.jsonl"
    events = [
        {"phase": "steps", "action": "load.input_off", "status": "ok"},
        {"phase": "steps", "action": "measure", "status": "ok", "detail": {"save_as": "arbitrary_baseline_id"}},
    ]
    execution.write_text("".join(json.dumps(event) + "\n" for event in events) + execution.read_text())
    page = generate_report(run_dir).read_text()
    assert _embedded_data(page)[0]["display_label"] == "Before drawing current"


def test_voltage_verdict_uses_only_the_saved_window_and_readings(tmp_path):
    run_dir = _run_dir(tmp_path)
    summary_path = run_dir / "run.json"
    summary = json.loads(summary_path.read_text())
    summary["parameters"] = {"voltage_v": 5.0, "min_acceptable_voltage_v": 4.5, "max_expected_voltage_v": 5.5}
    summary_path.write_text(json.dumps(summary))
    page = generate_report(run_dir).read_text()
    assert "5 V power delivery test" in page
    assert "Device voltage stayed in the chosen range" in page
    assert "All 2 saved device-voltage readings are within 4.5–5.5 V" in page
    assert "4.75" not in page
    assert "450 mV above the saved minimum of 4.5 V" in page
    summary["parameters"]["min_acceptable_voltage_v"] = 4.98
    summary_path.write_text(json.dumps(summary))
    page = generate_report(run_dir).read_text()
    assert "Device voltage went outside the chosen range" in page
    assert "1 of 2 saved device-voltage readings are outside 4.98–5.5 V" in page
    assert "30 mV below the saved minimum of 4.98 V" in page
    assert "-30 mV above" not in page
    assert "The recorded run passed its checks." not in page


def test_missing_limits_and_incomplete_runs_do_not_claim_voltage_pass(tmp_path):
    run_dir = _run_dir(tmp_path)
    page = generate_report(run_dir).read_text()
    assert "Voltage recorded; no acceptable range was saved" in page
    assert "Device voltage stayed in the chosen range" not in page
    path = run_dir / "run.json"
    summary = json.loads(path.read_text())
    summary.update(outcome="incomplete", parameters={"min_acceptable_voltage_v": 4.75, "max_expected_voltage_v": 5.25})
    path.write_text(json.dumps(summary))
    page = generate_report(run_dir).read_text()
    assert "Available device-voltage readings are within range" in page
    assert "These voltage readings alone do not establish an overall pass" in page


def test_simulation_explains_purpose_without_a_real_bench_verdict(tmp_path):
    import re
    run_dir = _run_dir(tmp_path)
    path = run_dir / "run.json"
    summary = json.loads(path.read_text())
    summary.update(data_source="simulated", parameters={"voltage_v": 5.0, "min_acceptable_voltage_v": 4.75, "max_expected_voltage_v": 5.25})
    path.write_text(json.dumps(summary))
    page = generate_report(run_dir).read_text()
    assert "The electronic load stands in for a device plugged into the power supply" in page
    assert "</p><p>This run requests" in page
    assert "</p><p>The saved test settings choose" in page
    assert "Illustration only — your bench has not been tested" in page
    assert "Device voltage stayed in the chosen range" not in page
    assert "The recorded run passed its checks." not in page
    visible = re.sub(r"<script.*?</script>", "", page, flags=re.S)
    assert "Offline · generated example readings" in visible
    assert "Illustrated with generated data" in visible
    assert "<h2>Example readings</h2>" in visible
    assert 'download="example-readings.csv"' in visible
    assert "saved measurements" not in visible
    assert "Measured points" not in visible
    assert "Measured load current" not in visible


def _chart_svg(page, chart_id):
    import re
    from xml.etree import ElementTree
    section = re.search(rf'<section[^>]+id="{chart_id}"[^>]*>(.*?)</section>', page, re.S)[1]
    return ElementTree.fromstring(re.search(r'<svg .*?</svg>', section, re.S)[0])


def test_current_timeline_preserves_test_order_and_known_off_baseline():
    targets = [round(0.05 + n * 0.025, 3) for n in range(11)]
    targets += targets[-2::-1]
    samples = [Sample("baseline", "", "pass", {"load_current_a": 0.0003}, load_enabled=False)]
    samples += [Sample(f"point_{index}", "", "pass", {"load_current_a": target - 0.001},
                       requested_current_a=target, load_enabled=True)
                for index, target in enumerate(targets)]
    page = render_report({}, samples, [])
    svg = _chart_svg(page, "demand-chart")
    commanded = [point for point in svg.findall("circle") if point.get("data-series") == "Requested current"]
    measured = [point for point in svg.findall("circle") if point.get("data-series") == "Measured current"]
    assert [int(point.get("data-sample")) for point in commanded] == list(range(22))
    assert [float(point.get("data-x")) for point in commanded] == list(range(1, 23))
    assert [float(point.get("data-value")) for point in commanded] == [0] + [target * 1000 for target in targets]
    assert max(commanded, key=lambda point: float(point.get("data-value"))) is commanded[11]
    assert float(commanded[11].get("cy")) < float(commanded[-1].get("cy"))
    assert float(commanded[11].get("cx")) < float(commanded[-1].get("cx"))
    assert float(commanded[-1].get("data-value")) == 50
    assert "Load switched off; 0 mA commanded, not an assumed measurement" in commanded[0].find("title").text
    assert float(measured[0].get("data-value")) == 0.3  # Never replace a reading with commanded zero.
    assert _embedded_data(page)[0]["requested_current_a"] is None
    assert _embedded_data(page)[0]["load_enabled"] is False
    assert "X: Reading number (test order)" in page
    assert "Returning to the same current moves left" in page


def test_comparison_ticks_are_round_milliamps_at_true_coordinates_without_rounding_data():
    currents = [0.0, 0.123456789012, 0.298840]
    page = render_report({}, [Sample(str(index), "", "pass", {"load_current_a": current,
        "load_voltage_v": 4.99, "supply_voltage_v": 5.0}) for index, current in enumerate(currents)], [])
    svg = _chart_svg(page, "voltage-chart")
    ticks = [element for element in svg.findall("text") if "x-tick" in element.get("class", "").split()]
    assert [float(tick.get("data-tick")) for tick in ticks] == [0, 50, 100, 150, 200, 250, 300]
    assert [tick.text for tick in ticks] == ["0", "50", "100", "150", "200", "250", "300"]
    low, high = -298.84 * 0.06, 298.84 * 1.06
    for tick in ticks:
        true_position = 76 + (float(tick.get("data-tick")) - low) / (high - low) * 760
        assert abs(float(tick.get("x")) - true_position) < 0.006
    points = svg.findall("circle")
    assert float(points[1].get("data-x")) == currents[1] * 1000
    assert "123.456789012 mA" in points[1].find("title").text
    assert _embedded_data(page)[1]["values"]["load_current_a"] == currents[1]
    assert "X: Measured load current (mA)" in page


def test_timeline_never_infers_requested_current_from_measurement_or_label():
    page = render_report({}, [Sample("no_load", "", "ungraded", {"load_current_a": 0.2})], [])
    points = _chart_svg(page, "demand-chart").findall("circle")
    assert len(points) == 1
    assert points[0].get("data-series") == "Measured current"
    assert float(points[0].get("data-value")) == 200
    assert "Load switched off;" not in page


def test_chart_ticks_handle_single_tiny_and_negative_current_ranges():
    import math
    for currents in ([0.1], [0.0], [0.000001, 0.000004], [-2.0, 1.0]):
        samples = [Sample(str(index), "", "ungraded", {"load_current_a": current,
                   "load_power_w": current * 5}) for index, current in enumerate(currents)]
        page = render_report({}, samples, [])
        for chart_id in ("demand-chart", "power-chart"):
            svg = _chart_svg(page, chart_id)
            ticks = [element for element in svg.findall("text") if "x-tick" in element.get("class", "").split()]
            assert 1 <= len(ticks) <= 9
            values = [float(tick.get("data-tick")) for tick in ticks]
            assert values == sorted(set(values))
            assert all(math.isfinite(float(point.get("cx"))) and math.isfinite(float(point.get("cy")))
                       for point in svg.findall("circle"))
            if chart_id == "demand-chart":
                assert all(value >= 1 and value.is_integer() for value in values)
