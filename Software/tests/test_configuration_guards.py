"""Recipe reconfiguration guards use readback before changing a load."""

from unittest.mock import Mock

import pytest

from benchctl.recipes import LoadConfigureCC
from benchctl.runner import RuntimeSafetyError, _execute_action, _ExecutionState


def configure_load(load, state):
    _execute_action(
        LoadConfigureCC(
            action="load.configure_cc", current_a=0.2, max_voltage_v=5.5
        ),
        {"load": load},
        {},
        state,
        lambda seconds: None,
        lambda *args: None,
    )


def test_recipe_refuses_reconfiguring_enabled_load_without_writes():
    load = Mock()
    load.get_input_enabled.return_value = True
    state = _ExecutionState()

    with pytest.raises(RuntimeSafetyError, match="input is ON"):
        configure_load(load, state)

    load.set_mode.assert_not_called()
    load.set_current.assert_not_called()
    load.input_on.assert_not_called()
    assert state.load_max_voltage_v is None


def test_recipe_refuses_reconfiguring_load_when_state_readback_fails():
    load = Mock()
    load.get_input_enabled.side_effect = OSError("state read timed out")
    state = _ExecutionState()

    with pytest.raises(OSError, match="state read timed out"):
        configure_load(load, state)

    load.set_mode.assert_not_called()
    load.set_current.assert_not_called()
    assert state.load_max_voltage_v is None


def test_recipe_configures_disabled_load_and_records_enable_bound():
    load = Mock()
    load.get_input_enabled.return_value = False
    state = _ExecutionState()

    configure_load(load, state)

    load.set_mode.assert_called_once_with("cc")
    load.set_current.assert_called_once_with(0.2)
    assert state.load_max_voltage_v == 5.5
