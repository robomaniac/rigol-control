"""RigolDL3000 driver tests against a fake transport. No hardware contact."""

import pytest

from benchctl.drivers.rigol_dl3000 import RigolDL3000
from benchctl.interfaces import ReadbackMismatchError, ScpiError

NO_ERROR = '0,"No error"'


class FakeTransport:
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
    return FakeTransport(responses={":SOUR:FUNC:MODE?": "FIX"})


@pytest.fixture
def driver(transport):
    return RigolDL3000(transport)


# -- mode selection ------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,function",
    [("cc", "CURR"), ("cv", "VOLT"), ("cr", "RES"), ("cp", "POW")],
)
def test_set_mode_scpi(driver, transport, mode, function):
    transport.responses[":SOUR:FUNC?"] = mode.upper()
    driver.set_mode(mode)
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX",
        "SYST:ERR?",
        ":SOUR:FUNC:MODE?",
        f":SOUR:FUNC {function}",
        "SYST:ERR?",
        ":SOUR:FUNC?",
    ]


def test_set_mode_accepts_uppercase(driver, transport):
    transport.responses[":SOUR:FUNC?"] = "CURRent"
    driver.set_mode("CC")
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX",
        "SYST:ERR?",
        ":SOUR:FUNC:MODE?",
        ":SOUR:FUNC CURR",
        "SYST:ERR?",
        ":SOUR:FUNC?",
    ]


@pytest.mark.parametrize("mode", ["ca", "constant_current", "", "curr", None, 3])
def test_invalid_mode_rejected(driver, transport, mode):
    with pytest.raises(ValueError):
        driver.set_mode(mode)
    assert transport.commands == []


@pytest.mark.parametrize("readback_after_write", ["FIX", "WAV"])
def test_set_mode_requests_fixed_operation_and_accepts_waveform_display(
    readback_after_write,
):
    class RetainedWaveformTransport(FakeTransport):
        def __init__(self):
            super().__init__(responses={
                ":SOUR:FUNC:MODE?": "WAV",
                ":SOUR:FUNC?": "CC",
                ":SOUR:CURR:LEV:IMM?": "0.1",
            })

        def write(self, command):
            super().write(command)
            if command == ":SOUR:FUNC:MODE FIX":
                self.responses[":SOUR:FUNC:MODE?"] = readback_after_write

    transport = RetainedWaveformTransport()
    driver = RigolDL3000(transport)
    assert transport.responses[":SOUR:FUNC:MODE?"] == "WAV"
    driver.set_mode("cc")
    driver.set_current(0.1)
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX",
        "SYST:ERR?",
        ":SOUR:FUNC:MODE?",
        ":SOUR:FUNC CURR",
        "SYST:ERR?",
        ":SOUR:FUNC?",
        ":SOUR:CURR:LEV:IMM 0.1",
        "SYST:ERR?",
        ":SOUR:CURR:LEV:IMM?",
    ]


@pytest.mark.parametrize(
    "response", ["LIST", "BATT", "OCP", "OPP", "DYN", "", "garbled"]
)
def test_set_mode_stops_before_function_when_fixed_operation_not_confirmed(
    driver, transport, response
):
    transport.responses[":SOUR:FUNC:MODE?"] = response
    with pytest.raises(ReadbackMismatchError, match="operation mode readback"):
        driver.set_mode("cc")
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX", "SYST:ERR?", ":SOUR:FUNC:MODE?",
    ]


def test_set_mode_stops_when_fixed_operation_command_reports_error(
    driver, transport
):
    transport.error_queue = ['-221,"Settings conflict"', NO_ERROR]
    with pytest.raises(ScpiError, match="Settings conflict"):
        driver.set_mode("cc")
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX", "SYST:ERR?", "SYST:ERR?",
    ]


def test_set_mode_stops_when_function_command_reports_error(driver, transport):
    transport.error_queue = [NO_ERROR, '-221,"Settings conflict"', NO_ERROR]
    with pytest.raises(ScpiError, match="Settings conflict"):
        driver.set_mode("cc")
    assert transport.commands == [
        ":SOUR:FUNC:MODE FIX", "SYST:ERR?", ":SOUR:FUNC:MODE?",
        ":SOUR:FUNC CURR", "SYST:ERR?", "SYST:ERR?",
    ]


# -- state-changing commands: exact SCPI ---------------------------------------


def test_set_current_scpi(driver, transport):
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "2.500"
    driver.set_current(2.5)
    assert transport.commands == [
        ":SOUR:CURR:LEV:IMM 2.5",
        "SYST:ERR?",
        ":SOUR:CURR:LEV:IMM?",
    ]


def test_input_on_scpi(driver, transport):
    transport.responses[":SOUR:INP:STAT?"] = "1"
    driver.input_on()
    assert transport.commands == [
        ":SOUR:INP:STAT ON",
        "SYST:ERR?",
        ":SOUR:INP:STAT?",
    ]


def test_input_off_scpi(driver, transport):
    transport.responses[":SOUR:INP:STAT?"] = "OFF"
    driver.input_off()
    assert transport.commands == [
        ":SOUR:INP:STAT OFF",
        "SYST:ERR?",
        ":SOUR:INP:STAT?",
    ]


def test_no_rst_ever_sent(driver, transport):
    transport.responses.update(
        {
            ":SOUR:FUNC?": "CC",
            ":SOUR:CURR:LEV:IMM?": "1.0",
            ":SOUR:INP:STAT?": ["1", "0"],
        }
    )
    driver.set_mode("cc")
    driver.set_current(1.0)
    driver.input_on()
    driver.input_off()
    assert all("*RST" not in c for c in transport.commands)


# -- setting/state readback -----------------------------------------------------


@pytest.mark.parametrize(
    "response, expected",
    [
        ("CC", "cc"),
        ("curr", "cc"),
        ("CURRENT", "cc"),
        ("CV", "cv"),
        ("VOLT", "cv"),
        ("voltage", "cv"),
        ("CR", "cr"),
        ("RES", "cr"),
        ("resistance", "cr"),
        ("CP", "cp"),
        ("POW", "cp"),
        ("power", "cp"),
    ],
)
def test_get_mode_normalizes_common_rigol_responses(response, expected):
    transport = FakeTransport(responses={":SOUR:FUNC?": response})
    assert RigolDL3000(transport).get_mode() == expected
    assert transport.queries == [":SOUR:FUNC?"]


def test_get_mode_rejects_unknown_response(driver, transport):
    transport.responses[":SOUR:FUNC?"] = "LIST"
    with pytest.raises(ValueError, match=r"malformed :SOUR:FUNC\? response"):
        driver.get_mode()


def test_get_current_setpoint_uses_documented_query(driver, transport):
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "2.500"
    assert driver.get_current_setpoint() == pytest.approx(2.5)
    assert transport.queries == [":SOUR:CURR:LEV:IMM?"]


@pytest.mark.parametrize(
    "response, expected",
    [
        ("1", True),
        ("0", False),
        ("+1", True),
        ("+0", False),
        ("ON", True),
        ("off", False),
        ("TRUE", True),
        ("FALSE", False),
    ],
)
def test_get_input_enabled_accepts_common_boolean_responses(response, expected):
    transport = FakeTransport(responses={":SOUR:INP:STAT?": response})
    assert RigolDL3000(transport).get_input_enabled() is expected
    assert transport.queries == [":SOUR:INP:STAT?"]


def test_get_input_enabled_rejects_unknown_response(driver, transport):
    transport.responses[":SOUR:INP:STAT?"] = "enabled"
    with pytest.raises(ValueError, match=r"malformed :SOUR:INP:STAT\? response"):
        driver.get_input_enabled()


@pytest.mark.parametrize("response", ["not-a-number", "nan", "-inf"])
def test_current_setpoint_rejects_malformed_or_nonfinite_response(response):
    transport = FakeTransport(responses={":SOUR:CURR:LEV:IMM?": response})
    with pytest.raises(
        ValueError, match=r"malformed :SOUR:CURR:LEV:IMM\? response"
    ):
        RigolDL3000(transport).get_current_setpoint()


# -- measurements ---------------------------------------------------------------


def test_measure_voltage(driver, transport):
    transport.responses[":MEAS:VOLT?"] = "12.002"
    assert driver.measure_voltage() == pytest.approx(12.002)
    assert transport.queries == [":MEAS:VOLT?"]


def test_measure_current(driver, transport):
    transport.responses[":MEAS:CURR?"] = "2.4998"
    assert driver.measure_current() == pytest.approx(2.4998)
    assert transport.queries == [":MEAS:CURR?"]


def test_measure_power(driver, transport):
    transport.responses[":MEAS:POW?"] = "30.001"
    assert driver.measure_power() == pytest.approx(30.001)
    assert transport.queries == [":MEAS:POW?"]


def test_measurements_do_not_write(driver, transport):
    transport.responses[":MEAS:VOLT?"] = "0.0"
    driver.measure_voltage()
    assert transport.writes == []


@pytest.mark.parametrize("response", ["nan", "inf", "-inf", "invalid"])
@pytest.mark.parametrize(
    "method_name, command",
    [
        ("measure_voltage", ":MEAS:VOLT?"),
        ("measure_current", ":MEAS:CURR?"),
        ("measure_power", ":MEAS:POW?"),
    ],
)
def test_measurements_reject_malformed_or_nonfinite_response(
    driver, transport, method_name, command, response
):
    transport.responses[command] = response
    with pytest.raises(ValueError, match="malformed"):
        getattr(driver, method_name)()
    assert transport.queries == [command]
    assert transport.writes == []


# -- post-write verification ----------------------------------------------------


def test_set_current_accepts_one_programming_increment_difference(
    driver, transport
):
    # Every DL3000 model has documented 1 mA CC programming resolution.
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "2.5009"
    driver.set_current(2.5)


@pytest.mark.parametrize("operation_mode", ["FIX", "WAV"])
def test_set_mode_readback_mismatch_does_not_retry_write(
    driver, transport, operation_mode
):
    transport.responses[":SOUR:FUNC:MODE?"] = operation_mode
    transport.responses[":SOUR:FUNC?"] = "CV"
    with pytest.raises(ReadbackMismatchError, match="mode readback"):
        driver.set_mode("cc")
    assert transport.writes == [":SOUR:FUNC:MODE FIX", ":SOUR:FUNC CURR"]


def test_set_current_readback_mismatch_does_not_retry_write(driver, transport):
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "2.502"
    with pytest.raises(ReadbackMismatchError, match="current setpoint"):
        driver.set_current(2.5)
    assert transport.writes == [":SOUR:CURR:LEV:IMM 2.5"]


@pytest.mark.parametrize(
    "method_name, expected, response",
    [("input_on", "ON", "0"), ("input_off", "OFF", "1")],
)
def test_input_state_mismatch_does_not_retry_write(
    driver, transport, method_name, expected, response
):
    transport.responses[":SOUR:INP:STAT?"] = response
    with pytest.raises(ReadbackMismatchError, match=f"expected {expected}"):
        getattr(driver, method_name)()
    assert len(transport.writes) == 1


def test_malformed_post_write_readback_does_not_retry_write(driver, transport):
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "garbled"
    with pytest.raises(ValueError, match="malformed"):
        driver.set_current(2.5)
    assert transport.writes == [":SOUR:CURR:LEV:IMM 2.5"]


# -- error-queue behavior ----------------------------------------------------------


def test_check_errors_passes_when_clean(driver, transport):
    driver.check_errors()
    assert transport.queries == ["SYST:ERR?"]


@pytest.mark.parametrize("clean", ['0,"No error"', '+0,"No error"', "0,No error"])
def test_check_errors_accepts_no_error_variants(clean):
    transport = FakeTransport(error_queue=[clean])
    RigolDL3000(transport).check_errors()


def test_check_errors_raises_on_error(driver, transport):
    transport.error_queue = ['-113,"Undefined header"', NO_ERROR]
    with pytest.raises(ScpiError, match="Undefined header"):
        driver.check_errors()


def test_check_errors_is_bounded(driver, transport):
    transport.error_queue = ['-350,"Queue overflow"'] * 50
    with pytest.raises(ScpiError):
        driver.check_errors()
    assert transport.queries.count("SYST:ERR?") == 10


def test_state_change_triggers_error_check(driver, transport):
    transport.responses[":SOUR:CURR:LEV:IMM?"] = "1.0"
    driver.set_current(1.0)
    assert transport.commands == [
        ":SOUR:CURR:LEV:IMM 1.0",
        "SYST:ERR?",
        ":SOUR:CURR:LEV:IMM?",
    ]


def test_all_state_changing_methods_check_errors(driver, transport):
    transport.responses.update(
        {
            ":SOUR:FUNC?": "CC",
            ":SOUR:CURR:LEV:IMM?": "1.0",
            ":SOUR:INP:STAT?": ["1", "0"],
        }
    )
    driver.set_mode("cc")
    driver.set_current(1.0)
    driver.input_on()
    driver.input_off()
    assert transport.queries.count("SYST:ERR?") == 5


def test_state_change_raises_when_instrument_reports_error(driver, transport):
    transport.error_queue = ['-222,"Data out of range"', NO_ERROR]
    with pytest.raises(ScpiError, match="Data out of range"):
        driver.set_current(999.0)
    assert transport.writes == [":SOUR:CURR:LEV:IMM 999.0"]
    assert transport.queries == ["SYST:ERR?", "SYST:ERR?"]
