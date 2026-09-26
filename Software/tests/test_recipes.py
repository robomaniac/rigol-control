"""Recipe schema, substitution, and rejection tests. No hardware involved."""

import copy
import math
from pathlib import Path

import pytest

from benchctl.recipes import (
    LoadConfigureCC,
    LoadInputOff,
    Measure,
    Recipe,
    RecipeError,
    SupplyConfigure,
    SupplyOutputOff,
    load_recipe,
    parse_recipe,
)

RECIPES_DIR = Path(__file__).resolve().parent.parent / "recipes"

BASE_RECIPE = {
    "schema_version": 1,
    "name": "unit_test_recipe",
    "requires": {
        "supply": {"kind": "power_supply"},
        "load": {"kind": "electronic_load"},
    },
    "parameters": {
        "voltage_v": 5.0,
        "current_limit_a": 1.0,
        "load_current_a": 0.25,
        "max_voltage_v": 6.0,
        "tag": "pointA",
    },
    "steps": [
        {
            "action": "supply.configure",
            "channel": 1,
            "voltage_v": "${parameters.voltage_v}",
            "current_limit_a": "${parameters.current_limit_a}",
        },
        {
            "action": "load.configure_cc",
            "current_a": "${parameters.load_current_a}",
            "max_voltage_v": "${parameters.max_voltage_v}",
        },
        {"action": "supply.output_on", "channel": 1},
        {"action": "wait", "seconds": 0.1},
        {"action": "load.input_on"},
        {
            "action": "measure",
            "save_as": "op_${parameters.tag}",
            "values": {
                "supply_voltage_v": {"source": "supply.voltage", "channel": 1},
                "load_current_a": {"source": "load.current"},
            },
        },
    ],
    "finally": [
        {"action": "load.input_off"},
        {"action": "supply.all_outputs_off"},
    ],
}


def make_raw(**overrides) -> dict:
    raw = copy.deepcopy(BASE_RECIPE)
    raw.update(overrides)
    return raw


# -- shipped recipe files ------------------------------------------------------


def test_shipped_recipe_loads():
    recipe = load_recipe(RECIPES_DIR / "load_sweep.yaml")
    assert recipe.schema_version == 1
    assert recipe.name == "load_sweep"


def test_load_sweep_has_measurements_per_point():
    recipe = load_recipe(RECIPES_DIR / "load_sweep.yaml")
    expected_currents = [0.05 + 0.025 * i for i in range(11)]
    expected_currents += expected_currents[-2::-1]
    cc_currents = [
        step.current_a for step in recipe.steps if isinstance(step, LoadConfigureCC)
    ]
    assert cc_currents == pytest.approx(expected_currents)
    assert len(cc_currents) == 21
    assert isinstance(recipe.steps[0], LoadInputOff)
    assert isinstance(recipe.steps[1], SupplyOutputOff)
    assert isinstance(recipe.steps[2], SupplyConfigure)
    assert recipe.steps[2].channel == recipe.parameters["supply_channel"]
    assert recipe.steps[2].voltage_v == 5.0
    assert recipe.steps[2].current_limit_a == 0.5
    assert recipe.parameters["settle_s"] == 4.0
    measures = [step for step in recipe.steps if isinstance(step, Measure)]
    assert len(measures) == 22
    assert measures[0].save_as == "no_load"
    assert len({step.save_as for step in measures}) == 22
    assert all(
        {"supply_voltage_v", "supply_current_a", "load_voltage_v", "load_current_a", "load_power_w"}
        <= set(step.values)
        for step in measures[1:]
    )
    for measure, current in zip(measures[1:], expected_currents):
        for label, tolerance in (("supply_current_a", 0.03), ("load_current_a", 0.02)):
            expectation = measure.values[label].expect
            assert expectation.min == pytest.approx(current - tolerance)
            assert expectation.max == pytest.approx(current + tolerance)
        assert measure.values["supply_current_a"].expect.min > 0
    assert isinstance(recipe.finally_steps[0], LoadInputOff)
    assert isinstance(recipe.finally_steps[1], SupplyOutputOff)
    assert recipe.finally_steps[1].channel == recipe.parameters["supply_channel"]


# -- valid parsing and substitution ---------------------------------------------


def test_valid_recipe_parses():
    recipe = parse_recipe(make_raw())
    assert isinstance(recipe, Recipe)
    assert len(recipe.steps) == 6
    assert len(recipe.finally_steps) == 2


def test_parameter_substitution_preserves_numeric_type():
    recipe = parse_recipe(make_raw())
    configure = recipe.steps[0]
    assert configure.voltage_v == 5.0
    assert configure.current_limit_a == 1.0
    assert recipe.steps[1].current_a == 0.25
    assert recipe.steps[1].max_voltage_v == 6.0


def test_embedded_substitution_builds_strings():
    recipe = parse_recipe(make_raw())
    measure = recipe.steps[5]
    assert measure.save_as == "op_pointA"


def test_unresolved_placeholder_rejected():
    raw = make_raw()
    raw["steps"][0]["voltage_v"] = "${parameters.missing}"
    with pytest.raises(RecipeError, match="unknown parameter 'missing'"):
        parse_recipe(raw)


def test_malformed_placeholder_rejected():
    raw = make_raw()
    raw["steps"][0]["voltage_v"] = "${params.voltage_v}"
    with pytest.raises(RecipeError, match="unsupported placeholder"):
        parse_recipe(raw)


# -- strict rejection -----------------------------------------------------------


def test_unknown_top_level_field_rejected():
    with pytest.raises(RecipeError):
        parse_recipe(make_raw(surprise=True))


def test_unknown_action_rejected():
    raw = make_raw()
    raw["steps"].append({"action": "supply.explode"})
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_raw_scpi_action_rejected():
    raw = make_raw()
    raw["steps"].append({"action": "scpi", "command": ":OUTP CH1,ON"})
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_scpi_field_inside_known_action_rejected():
    raw = make_raw()
    raw["steps"][0]["scpi"] = "*RST"
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_wrong_schema_version_rejected():
    with pytest.raises(RecipeError):
        parse_recipe(make_raw(schema_version=2))


def test_negative_wait_rejected():
    raw = make_raw()
    raw["steps"][3]["seconds"] = -1
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_supply_measure_source_requires_channel():
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"] = {"source": "supply.voltage"}
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_load_measure_source_rejects_channel():
    raw = make_raw()
    raw["steps"][5]["values"]["load_current_a"] = {
        "source": "load.current",
        "channel": 1,
    }
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_action_role_must_be_declared_in_requires():
    raw = make_raw()
    del raw["requires"]["load"]
    with pytest.raises(RecipeError, match="not declared in 'requires'"):
        parse_recipe(raw)


def test_requires_kind_must_match_action_role():
    raw = make_raw()
    raw["requires"]["supply"] = {"kind": "electronic_load"}
    with pytest.raises(RecipeError, match="kind must be 'power_supply'"):
        parse_recipe(raw)


# -- enable ordering and measurement expectations ------------------------------


def test_supply_output_on_requires_prior_same_channel_configuration():
    raw = make_raw()
    raw["steps"][2]["channel"] = 2
    with pytest.raises(RecipeError, match="prior same-run supply.configure"):
        parse_recipe(raw)


def test_supply_configuration_persists_across_off_on_cycle():
    raw = make_raw()
    raw["steps"].insert(3, {"action": "supply.output_off", "channel": 1})
    raw["steps"].insert(4, {"action": "supply.output_on", "channel": 1})
    assert isinstance(parse_recipe(raw), Recipe)


def test_load_input_on_requires_prior_same_run_configuration():
    raw = make_raw()
    raw["steps"] = [
        step for step in raw["steps"] if step["action"] != "load.configure_cc"
    ]
    with pytest.raises(RecipeError, match="prior same-run load.configure_cc"):
        parse_recipe(raw)


def test_load_configuration_persists_across_off_on_cycle():
    raw = make_raw()
    raw["steps"].insert(5, {"action": "load.input_off"})
    raw["steps"].insert(6, {"action": "load.input_on"})
    assert isinstance(parse_recipe(raw), Recipe)


def test_load_configure_cc_requires_maximum_voltage():
    raw = make_raw()
    del raw["steps"][1]["max_voltage_v"]
    with pytest.raises(RecipeError, match="max_voltage_v"):
        parse_recipe(raw)


@pytest.mark.parametrize("expect", [{"min": 0.0}, {"max": 6.0}, {"min": 0.0, "max": 6.0}])
def test_measure_expectation_valid_forms(expect):
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"]["expect"] = expect
    parsed = parse_recipe(raw)
    assert parsed.steps[5].values["supply_voltage_v"].expect is not None


def test_measure_expectation_requires_a_bound():
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"]["expect"] = {}
    with pytest.raises(RecipeError, match="at least one"):
        parse_recipe(raw)


def test_measure_expectation_rejects_reversed_bounds():
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"]["expect"] = {
        "min": 6.0,
        "max": 5.0,
    }
    with pytest.raises(RecipeError, match="less than or equal"):
        parse_recipe(raw)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_measure_expectation_rejects_nonfinite_bounds(value):
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"]["expect"] = {"max": value}
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_measure_expectation_rejects_unknown_fields():
    raw = make_raw()
    raw["steps"][5]["values"]["supply_voltage_v"]["expect"] = {
        "min": 0.0,
        "tolerance": 0.1,
    }
    with pytest.raises(RecipeError):
        parse_recipe(raw)


def test_recipe_without_expectations_remains_valid():
    recipe = parse_recipe(make_raw())
    measure = recipe.steps[5]
    assert all(spec.expect is None for spec in measure.values.values())


# -- file loading -----------------------------------------------------------------


def test_missing_recipe_file_rejected(tmp_path):
    with pytest.raises(RecipeError, match="cannot read recipe file"):
        load_recipe(tmp_path / "nope.yaml")


def test_invalid_yaml_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("steps: [unbalanced", encoding="utf-8")
    with pytest.raises(RecipeError, match="invalid YAML"):
        load_recipe(path)


def test_non_mapping_yaml_rejected(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RecipeError, match="must be a mapping"):
        load_recipe(path)


# -- finite sweep expansion -------------------------------------------------------


def sweep_recipe(**overrides):
    block = {
        "action": "sweep",
        "start": 0.05,
        "stop": 0.10,
        "step": 0.025,
        "return_to_start": True,
        "steps": [
            {
                "action": "load.configure_cc",
                "current_a": "${sweep.value}",
                "max_voltage_v": "${parameters.max_voltage_v}",
            },
            {
                "action": "measure",
                "save_as": "point_${sweep.index}_${sweep.value}",
                "values": {
                    "current_a": {
                        "source": "load.current",
                        "expect": {"target": "${sweep.value}", "tolerance": 0.02},
                    }
                },
            },
        ],
    }
    block.update(overrides)
    return make_raw(steps=[block])


def test_sweep_expands_both_directions_without_repeating_peak():
    recipe = parse_recipe(sweep_recipe())
    configure = recipe.steps[::2]
    measures = recipe.steps[1::2]
    assert [step.current_a for step in configure] == [0.05, 0.075, 0.1, 0.075, 0.05]
    assert [step.save_as for step in measures] == [
        "point_1_0.05", "point_2_0.075", "point_3_0.1", "point_4_0.075", "point_5_0.05"
    ]
    assert measures[1].values["current_a"].expect.min == pytest.approx(0.055)
    assert measures[1].values["current_a"].expect.max == pytest.approx(0.095)


def test_sweep_endpoints_can_use_parameters_and_peak_can_stand_alone():
    raw = sweep_recipe(start="${parameters.load_current_a}", stop=0.25)
    recipe = parse_recipe(raw)
    assert len(recipe.steps) == 2
    assert recipe.steps[0].current_a == 0.25


def test_sweep_can_stop_without_returning():
    recipe = parse_recipe(sweep_recipe(return_to_start=False))
    assert [step.current_a for step in recipe.steps[::2]] == [0.05, 0.075, 0.1]


def test_target_bounds_preserve_inclusive_decimal_limits():
    recipe = parse_recipe(sweep_recipe())
    expectation = recipe.steps[1].values["current_a"].expect
    assert expectation.min == 0.03
    assert expectation.max == 0.07


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"step": 0}, "step"),
        ({"step": -0.025}, "step"),
        ({"stop": 0.01}, "greater than or equal"),
        ({"step": 0.03}, "exact multiple"),
        ({"stop": 100.0}, "exceeds 1000 points"),
        ({"start": math.nan}, "finite"),
        ({"stop": math.inf}, "finite"),
        ({"step": math.inf}, "finite"),
        ({"return_to_start": "yes"}, "valid boolean"),
        ({"surprise": True}, "Extra inputs"),
        ({"steps": []}, "at least 1 item"),
    ],
)
def test_sweep_rejects_invalid_or_unbounded_ranges(overrides, match):
    with pytest.raises(RecipeError, match=match):
        parse_recipe(sweep_recipe(**overrides))


def test_sweep_rejects_nested_sweeps():
    nested = sweep_recipe()["steps"]
    with pytest.raises(RecipeError, match="nested sweeps"):
        parse_recipe(sweep_recipe(steps=nested))


def test_sweep_rejects_unsupported_actions_and_out_of_context_values():
    with pytest.raises(RecipeError):
        parse_recipe(sweep_recipe(steps=[{"action": "scpi", "command": "*RST"}]))
    raw = make_raw()
    raw["steps"][1]["current_a"] = "${sweep.value}"
    with pytest.raises(RecipeError, match="requires a sweep body"):
        parse_recipe(raw)


def test_sweep_checks_every_expanded_value():
    with pytest.raises(RecipeError, match="greater than or equal to 0"):
        parse_recipe(sweep_recipe(start=-0.025, stop=0.025))


def test_sweep_counts_actions_across_multiple_blocks():
    raw = sweep_recipe(start=0, stop=99, step=1, return_to_start=False,
                       steps=[{"action": "wait", "seconds": 0}] * 51)
    raw["steps"] *= 2
    with pytest.raises(RecipeError, match="exceeds 10000 expanded actions"):
        parse_recipe(raw)


def test_sweep_rejects_steps_that_cannot_make_distinct_float_values():
    with pytest.raises(RecipeError, match="distinct numeric setpoints"):
        parse_recipe(sweep_recipe(start=1.0, stop=1.0000000000000002, step=1e-18))


@pytest.mark.parametrize(
    "expect",
    [
        {"target": 0.1},
        {"target": 0.1, "tolerance": -0.01},
        {"target": math.inf, "tolerance": 0.01},
        {"target": 0.1, "tolerance": math.inf},
        {"target": 0.1, "tolerance": 0.01, "min": 0},
        {"target": 1e308, "tolerance": 1e308},
    ],
)
def test_target_expectations_reject_invalid_or_ambiguous_limits(expect):
    raw = make_raw()
    raw["steps"][5]["values"]["load_current_a"]["expect"] = expect
    with pytest.raises(RecipeError):
        parse_recipe(raw)


@pytest.mark.parametrize(
    "step_index, field", [(0, "voltage_v"), (0, "current_limit_a"), (1, "current_a"), (3, "seconds")]
)
def test_actions_reject_infinite_setpoints_and_waits(step_index, field):
    raw = make_raw()
    raw["steps"][step_index][field] = math.inf
    with pytest.raises(RecipeError, match="finite"):
        parse_recipe(raw)
