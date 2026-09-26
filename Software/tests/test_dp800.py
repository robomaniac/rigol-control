"""RigolDP800 driver tests against a fake transport. No hardware contact."""

import pytest

from benchctl.drivers.rigol_dp800 import RigolDP800
from benchctl.interfaces import ReadbackMismatchError, ScpiError

NO_ERROR = '0,"No error"'


class FakeTransport:
    """Records every command; serves canned query responses.

    ``SYST:ERR?`` responses come from ``error_queue`` (falling back to the
    no-error response once exhausted).
    """

    def __init__(self, responses=None, error_queue=None):
        self.responses = responses or {}
        self.error_queue = list(error_queue or [])
        self.commands: list[str] = []
        self.writes: list[str] = []
        self.queries: list[str] = []

    def write(self, command: str) -> None:
        self.commands.append(command)
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.commands.append(command)
        self.queries.append(command)
        if command == "SYST:ERR?":
            return self.error_queue.pop(0) if self.error_queue else NO_ERROR
        if command.startswith(":OUTP? CH") and command not in self.responses:
            return "OFF"
        response = self.responses[command]
        if isinstance(response, list):
            if not response:
                raise AssertionError(f"no response left for {command}")
            return response.pop(0)
        return response

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def driver(transport):
    return RigolDP800(transport)


# -- state-changing commands: exact SCPI ---------------------------------------


def test_set_voltage_scpi(driver, transport):
    transport.responses[":SOUR1:VOLT?"] = "5.000"
    driver.set_voltage(1, 5.0)
    assert transport.commands == [
        ":OUTP? CH1",
        ":SOUR1:VOLT 5.0",
        "SYST:ERR?",
        ":SOUR1:VOLT?",
    ]


def test_set_voltage_channel_2(driver, transport):
    transport.responses[":SOUR2:VOLT?"] = "3.300"
    driver.set_voltage(2, 3.3)
    assert transport.commands == [
        ":OUTP? CH2",
        ":SOUR2:VOLT 3.3",
        "SYST:ERR?",
        ":SOUR2:VOLT?",
    ]


def test_set_current_limit_scpi(driver, transport):
    transport.responses[":SOUR2:CURR?"] = "1.500"
    driver.set_current_limit(2, 1.5)
    assert transport.commands == [
        ":OUTP? CH2",
        ":SOUR2:CURR 1.5",
        "SYST:ERR?",
        ":SOUR2:CURR?",
    ]


def test_output_on_scpi(driver, transport):
    transport.responses[":OUTP? CH1"] = "ON"
    driver.output_on(1)
    assert transport.commands == [
        ":OUTP CH1,ON",
        "SYST:ERR?",
        ":OUTP? CH1",
    ]


def test_output_off_scpi(driver, transport):
    transport.responses[":OUTP? CH2"] = "0"
    driver.output_off(2)
    assert transport.commands == [
        ":OUTP CH2,OFF",
        "SYST:ERR?",
        ":OUTP? CH2",
    ]


def test_all_outputs_off_scpi(driver, transport):
    transport.responses.update({":OUTP? CH1": "OFF", ":OUTP? CH2": "0"})
    driver.all_outputs_off()
    assert transport.commands == [
        ":OUTP CH1,OFF",
        "SYST:ERR?",
        ":OUTP? CH1",
        ":OUTP CH2,OFF",
        "SYST:ERR?",
        ":OUTP? CH2",
    ]


def test_no_rst_ever_sent(driver, transport):
    transport.responses.update(
        {
            ":SOUR1:VOLT?": "1.000",
            ":OUTP? CH1": ["OFF", "ON", "OFF"],
            ":OUTP? CH2": "OFF",
        }
    )
    driver.set_voltage(1, 1.0)
    driver.output_on(1)
    driver.all_outputs_off()
    assert all("*RST" not in c for c in transport.commands)


# -- setting/state readback -----------------------------------------------------


def test_get_voltage_setpoint_uses_documented_query(driver, transport):
    transport.responses[":SOUR2:VOLT?"] = "3.300"
    assert driver.get_voltage_setpoint(2) == pytest.approx(3.3)
    assert transport.queries == [":SOUR2:VOLT?"]


def test_get_current_limit_uses_documented_query(driver, transport):
    transport.responses[":SOUR1:CURR?"] = "0.500"
    assert driver.get_current_limit(1) == pytest.approx(0.5)
    assert transport.queries == [":SOUR1:CURR?"]


@pytest.mark.parametrize(
    "response, expected",
    [
        ("ON", True),
        ("off", False),
        ("1", True),
        ("0", False),
        ("+1", True),
        ("+0", False),
        ("TRUE", True),
        ("FALSE", False),
    ],
)
def test_get_output_enabled_accepts_common_boolean_responses(response, expected):
    transport = FakeTransport(responses={":OUTP? CH1": response})
    assert RigolDP800(transport).get_output_enabled(1) is expected
    assert transport.queries == [":OUTP? CH1"]


def test_get_output_enabled_rejects_unknown_response(driver, transport):
    transport.responses[":OUTP? CH1"] = "maybe"
    with pytest.raises(ValueError, match=r"malformed :OUTP\? CH1 response"):
        driver.get_output_enabled(1)


@pytest.mark.parametrize("response", ["not-a-number", "nan", "inf"])
def test_numeric_readback_rejects_malformed_or_nonfinite_response(response):
    transport = FakeTransport(responses={":SOUR1:VOLT?": response})
    with pytest.raises(ValueError, match=r"malformed :SOUR1:VOLT\? response"):
        RigolDP800(transport).get_voltage_setpoint(1)


# -- measurements ---------------------------------------------------------------


def test_measure_voltage(driver, transport):
    transport.responses[":MEAS:VOLT? CH1"] = "5.001"
    assert driver.measure_voltage(1) == pytest.approx(5.001)
    assert transport.queries == [":MEAS:VOLT? CH1"]


def test_measure_current(driver, transport):
    transport.responses[":MEAS:CURR? CH2"] = "0.2503"
    assert driver.measure_current(2) == pytest.approx(0.2503)
    assert transport.queries == [":MEAS:CURR? CH2"]


def test_measure_power(driver, transport):
    transport.responses[":MEAS:POWE? CH1"] = "1.2515"
    assert driver.measure_power(1) == pytest.approx(1.2515)
    assert transport.queries == [":MEAS:POWE? CH1"]


def test_measurements_do_not_write(driver, transport):
    transport.responses[":MEAS:VOLT? CH1"] = "0.0"
    driver.measure_voltage(1)
    assert transport.writes == []


@pytest.mark.parametrize("response", ["nan", "inf", "-inf", "invalid"])
@pytest.mark.parametrize(
    "method_name, command",
    [
        ("measure_voltage", ":MEAS:VOLT? CH1"),
        ("measure_current", ":MEAS:CURR? CH1"),
        ("measure_power", ":MEAS:POWE? CH1"),
    ],
)
def test_measurements_reject_malformed_or_nonfinite_response(
    driver, transport, method_name, command, response
):
    transport.responses[command] = response
    with pytest.raises(ValueError, match="malformed"):
        getattr(driver, method_name)(1)
    assert transport.queries == [command]
    assert transport.writes == []


# -- channel validation ----------------------------------------------------------


@pytest.mark.parametrize("channel", [0, 3, -1, 99])
def test_invalid_channel_rejected(driver, transport, channel):
    with pytest.raises(ValueError):
        driver.set_voltage(channel, 1.0)
    with pytest.raises(ValueError):
        driver.set_current_limit(channel, 1.0)
    with pytest.raises(ValueError):
        driver.output_on(channel)
    with pytest.raises(ValueError):
        driver.output_off(channel)
    with pytest.raises(ValueError):
        driver.get_voltage_setpoint(channel)
    with pytest.raises(ValueError):
        driver.get_current_limit(channel)
    with pytest.raises(ValueError):
        driver.get_output_enabled(channel)
    with pytest.raises(ValueError):
        driver.measure_voltage(channel)
    with pytest.raises(ValueError):
        driver.measure_current(channel)
    with pytest.raises(ValueError):
        driver.measure_power(channel)
    # Nothing must reach the instrument on validation failure.
    assert transport.commands == []


# -- post-write verification ----------------------------------------------------


def test_set_voltage_accepts_one_programming_increment_difference(
    driver, transport
):
    # The largest documented standard DP800 voltage increment is 10 mV.
    transport.responses[":SOUR1:VOLT?"] = "5.009"
    driver.set_voltage(1, 5.0)


def test_set_current_accepts_one_programming_increment_difference(
    driver, transport
):
    # The largest documented standard two-channel DP800 current increment is 10 mA.
    transport.responses[":SOUR2:CURR?"] = "1.509"
    driver.set_current_limit(2, 1.5)


@pytest.mark.parametrize("method_name", ["set_voltage", "set_current_limit"])
def test_setpoints_refuse_enabled_output_before_any_write(
    driver, transport, method_name
):
    transport.responses[":OUTP? CH1"] = "ON"
    with pytest.raises(RuntimeError, match="CH1 output is ON"):
        getattr(driver, method_name)(1, 0.5)
    assert transport.queries == [":OUTP? CH1"]
    assert transport.writes == []


def test_set_voltage_readback_mismatch_does_not_retry_write(driver, transport):
    transport.responses[":SOUR1:VOLT?"] = "4.98"
    with pytest.raises(ReadbackMismatchError, match="voltage setpoint"):
        driver.set_voltage(1, 5.0)
    assert transport.writes == [":SOUR1:VOLT 5.0"]


def test_set_current_readback_mismatch_does_not_retry_write(driver, transport):
    transport.responses[":SOUR2:CURR?"] = "1.48"
    with pytest.raises(ReadbackMismatchError, match="current limit"):
        driver.set_current_limit(2, 1.5)
    assert transport.writes == [":SOUR2:CURR 1.5"]


@pytest.mark.parametrize(
    "method_name, expected, response",
    [("output_on", "ON", "OFF"), ("output_off", "OFF", "ON")],
)
def test_output_state_mismatch_does_not_retry_write(
    driver, transport, method_name, expected, response
):
    transport.responses[":OUTP? CH1"] = response
    with pytest.raises(ReadbackMismatchError, match=f"expected {expected}"):
        getattr(driver, method_name)(1)
    assert len(transport.writes) == 1


def test_all_outputs_off_queries_both_channels_before_reporting_mismatch(
    driver, transport
):
    transport.responses.update({":OUTP? CH1": "ON", ":OUTP? CH2": "OFF"})
    with pytest.raises(ReadbackMismatchError, match="CH1"):
        driver.all_outputs_off()
    assert [q for q in transport.queries if q.startswith(":OUTP?")] == [
        ":OUTP? CH1", ":OUTP? CH2"
    ]
    assert transport.writes == [":OUTP CH1,OFF", ":OUTP CH2,OFF"]


def test_all_outputs_off_attempts_second_channel_after_first_write_fails(
    driver, transport
):
    write = transport.write

    def fail_first_write(command):
        if command == ":OUTP CH1,OFF":
            transport.commands.append(command)
            transport.writes.append(command)
            raise OSError("CH1 link lost")
        write(command)

    transport.write = fail_first_write
    with pytest.raises(OSError, match="CH1 link lost"):
        driver.all_outputs_off()
    assert transport.writes == [":OUTP CH1,OFF", ":OUTP CH2,OFF"]
    assert ":OUTP? CH2" in transport.queries


def test_malformed_post_write_readback_does_not_retry_write(driver, transport):
    transport.responses[":SOUR1:VOLT?"] = "garbled"
    with pytest.raises(ValueError, match="malformed"):
        driver.set_voltage(1, 5.0)
    assert transport.writes == [":SOUR1:VOLT 5.0"]


# -- error-queue behavior ----------------------------------------------------------


def test_check_errors_passes_when_clean(driver, transport):
    driver.check_errors()
    assert transport.queries == ["SYST:ERR?"]


@pytest.mark.parametrize("clean", ['0,"No error"', '+0,"No error"', "0,No error"])
def test_check_errors_accepts_no_error_variants(clean):
    transport = FakeTransport(error_queue=[clean])
    RigolDP800(transport).check_errors()


def test_check_errors_raises_on_error(driver, transport):
    transport.error_queue = ['-113,"Undefined header"', NO_ERROR]
    with pytest.raises(ScpiError, match="Undefined header"):
        driver.check_errors()


def test_check_errors_collects_multiple_errors(driver, transport):
    transport.error_queue = [
        '-113,"Undefined header"',
        '-222,"Data out of range"',
        NO_ERROR,
    ]
    with pytest.raises(ScpiError) as excinfo:
        driver.check_errors()
    assert "Undefined header" in str(excinfo.value)
    assert "Data out of range" in str(excinfo.value)


def test_check_errors_is_bounded(driver, transport):
    transport.error_queue = ['-350,"Queue overflow"'] * 50
    with pytest.raises(ScpiError):
        driver.check_errors()
    assert transport.queries.count("SYST:ERR?") == 10


def test_state_change_triggers_error_check(driver, transport):
    transport.responses[":SOUR1:VOLT?"] = "5.0"
    driver.set_voltage(1, 5.0)
    assert transport.commands == [
        ":OUTP? CH1",
        ":SOUR1:VOLT 5.0",
        "SYST:ERR?",
        ":SOUR1:VOLT?",
    ]


def test_all_state_changing_methods_check_errors(driver, transport):
    transport.responses.update(
        {
            ":SOUR1:VOLT?": "1.0",
            ":SOUR1:CURR?": "0.5",
            ":OUTP? CH1": ["OFF", "OFF", "ON", "OFF", "OFF"],
            ":OUTP? CH2": "OFF",
        }
    )
    driver.set_voltage(1, 1.0)
    driver.set_current_limit(1, 0.5)
    driver.output_on(1)
    driver.output_off(1)
    driver.all_outputs_off()
    # all_outputs_off checks each channel separately.
    assert transport.queries.count("SYST:ERR?") == 6


def test_state_change_raises_when_instrument_reports_error(driver, transport):
    transport.error_queue = ['-222,"Data out of range"', NO_ERROR]
    with pytest.raises(ScpiError, match="Data out of range"):
        driver.set_voltage(1, 99.0)
    assert transport.writes == [":SOUR1:VOLT 99.0"]
    assert transport.queries == [":OUTP? CH1", "SYST:ERR?", "SYST:ERR?"]
