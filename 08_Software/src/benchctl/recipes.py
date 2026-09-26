"""Recipe loading and strict validation.

Recipes are YAML documents parsed with ``yaml.safe_load`` and validated
with strict Pydantic v2 models before any instrument is contacted.
Unknown fields and unknown actions are rejected, so a recipe can never
smuggle raw SCPI to an instrument: the only way to touch hardware is
through the fixed, whitelisted action vocabulary below.

``"${parameters.<name>}"`` placeholders and finite ``sweep`` blocks are
expanded *before* validation, so every generated action and setpoint is
checked before an instrument can be contacted. Sweep bodies can use
``${sweep.value}`` and ``${sweep.index}`` (one-based); nesting is rejected.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ParameterValue = bool | int | float | str

# Device kind each implicit action role maps to (mirrors config.ROLE_KINDS).
ROLE_KIND_FOR_PREFIX: dict[str, str] = {
    "supply": "power_supply",
    "load": "electronic_load",
}

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]*)\}")
_PARAM_REF_RE = re.compile(r"^parameters\.([A-Za-z_][A-Za-z0-9_]*)$")
MAX_SWEEP_POINTS = 1000
MAX_EXPANDED_ACTIONS = 10000


class RecipeError(Exception):
    """Raised when a recipe cannot be loaded, resolved, or validated."""


# -- actions -------------------------------------------------------------------


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SupplyConfigure(_ActionBase):
    action: Literal["supply.configure"]
    channel: int = Field(ge=1)
    voltage_v: float = Field(ge=0)
    current_limit_a: float = Field(gt=0)


class SupplyOutputOn(_ActionBase):
    action: Literal["supply.output_on"]
    channel: int = Field(ge=1)


class SupplyOutputOff(_ActionBase):
    action: Literal["supply.output_off"]
    channel: int = Field(ge=1)


class SupplyAllOutputsOff(_ActionBase):
    action: Literal["supply.all_outputs_off"]


class LoadConfigureCC(_ActionBase):
    action: Literal["load.configure_cc"]
    current_a: float = Field(ge=0)
    max_voltage_v: float = Field(gt=0, allow_inf_nan=False)


class LoadInputOn(_ActionBase):
    action: Literal["load.input_on"]


class LoadInputOff(_ActionBase):
    action: Literal["load.input_off"]


MeasureSourceName = Literal[
    "supply.voltage",
    "supply.current",
    "supply.power",
    "load.voltage",
    "load.current",
    "load.power",
]


class _TargetExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: float = Field(allow_inf_nan=False)
    tolerance: float = Field(ge=0, allow_inf_nan=False)


class MeasurementExpectation(BaseModel):
    """Inclusive acceptance bounds for one measured value."""

    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def _target_to_bounds(cls, value: Any) -> Any:
        """Keep execution/reporting on one inclusive min/max representation."""
        if isinstance(value, dict) and {"target", "tolerance"} & value.keys():
            expectation = _TargetExpectation.model_validate(value)
            target = Decimal(str(expectation.target))
            tolerance = Decimal(str(expectation.tolerance))
            return {
                "min": float(target - tolerance),
                "max": float(target + tolerance),
            }
        return value

    @model_validator(mode="after")
    def _check_bounds(self) -> "MeasurementExpectation":
        if self.min is None and self.max is None:
            raise ValueError("expect requires at least one of 'min' or 'max'")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("expect.min must be less than or equal to expect.max")
        return self


class MeasureSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: MeasureSourceName
    channel: int | None = Field(default=None, ge=1)
    expect: MeasurementExpectation | None = None

    @model_validator(mode="after")
    def _check_channel(self) -> "MeasureSource":
        if self.source.startswith("supply.") and self.channel is None:
            raise ValueError(f"source {self.source!r} requires a channel")
        if self.source.startswith("load.") and self.channel is not None:
            raise ValueError(f"source {self.source!r} does not take a channel")
        return self


class Measure(_ActionBase):
    action: Literal["measure"]
    save_as: str = Field(min_length=1)
    values: dict[str, MeasureSource]

    @field_validator("values")
    @classmethod
    def _non_empty(cls, value: dict[str, MeasureSource]) -> dict[str, MeasureSource]:
        if not value:
            raise ValueError("measure action needs at least one value to record")
        return value


class Wait(_ActionBase):
    action: Literal["wait"]
    seconds: float = Field(ge=0)


Action = Annotated[
    Union[
        SupplyConfigure,
        SupplyOutputOn,
        SupplyOutputOff,
        SupplyAllOutputsOff,
        LoadConfigureCC,
        LoadInputOn,
        LoadInputOff,
        Measure,
        Wait,
    ],
    Field(discriminator="action"),
]


# -- recipe --------------------------------------------------------------------


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["power_supply", "electronic_load"]


def _action_roles(action: Any) -> set[str]:
    """Roles ('supply' / 'load') an action implicitly uses."""
    roles: set[str] = set()
    prefix = action.action.split(".", 1)[0]
    if prefix in ROLE_KIND_FOR_PREFIX:
        roles.add(prefix)
    if isinstance(action, Measure):
        for spec in action.values.values():
            roles.add(spec.source.split(".", 1)[0])
    return roles


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1]
    name: str = Field(min_length=1)
    requires: dict[str, Requirement] = {}
    parameters: dict[str, ParameterValue] = {}
    steps: list[Action] = Field(max_length=MAX_EXPANDED_ACTIONS)
    finally_steps: list[Action] = Field(
        default_factory=list, alias="finally", max_length=MAX_EXPANDED_ACTIONS
    )

    @model_validator(mode="after")
    def _check_action_count(self) -> "Recipe":
        if len(self.steps) + len(self.finally_steps) > MAX_EXPANDED_ACTIONS:
            raise ValueError(f"recipe exceeds {MAX_EXPANDED_ACTIONS} expanded actions")
        return self

    @model_validator(mode="after")
    def _check_required_roles(self) -> "Recipe":
        for phase, actions in (("steps", self.steps), ("finally", self.finally_steps)):
            for index, action in enumerate(actions):
                for role in sorted(_action_roles(action)):
                    requirement = self.requires.get(role)
                    if requirement is None:
                        raise ValueError(
                            f"{phase}[{index}]: action {action.action!r} uses role "
                            f"{role!r}, which is not declared in 'requires'"
                        )
                    expected_kind = ROLE_KIND_FOR_PREFIX[role]
                    if requirement.kind != expected_kind:
                        raise ValueError(
                            f"requires.{role}: kind must be {expected_kind!r} "
                            f"because {phase}[{index}] uses action {action.action!r}"
                        )
        return self

    @model_validator(mode="after")
    def _check_enable_order(self) -> "Recipe":
        """Reject nominal paths that enable unconfigured same-run state."""
        configured_supply_channels: set[int] = set()
        load_configured = False
        for phase, actions in (("steps", self.steps), ("finally", self.finally_steps)):
            for index, action in enumerate(actions):
                where = f"{phase}[{index}]"
                if isinstance(action, SupplyConfigure):
                    configured_supply_channels.add(action.channel)
                elif (
                    isinstance(action, SupplyOutputOn)
                    and action.channel not in configured_supply_channels
                ):
                    raise ValueError(
                        f"{where}: supply.output_on for channel {action.channel} "
                        "requires a prior same-run supply.configure for that channel"
                    )
                elif isinstance(action, LoadConfigureCC):
                    load_configured = True
                elif isinstance(action, LoadInputOn) and not load_configured:
                    raise ValueError(
                        f"{where}: load.input_on requires a prior same-run "
                        "load.configure_cc"
                    )
        return self


# -- parameter substitution ------------------------------------------------------


def _resolve_placeholder(
    reference: str, parameters: dict[str, Any], location: str,
    sweep: dict[str, Any] | None = None,
) -> Any:
    if reference in ("sweep.value", "sweep.index"):
        if sweep is None:
            raise RecipeError(f"{location}: '${{{reference}}}' requires a sweep body")
        return sweep[reference.split(".", 1)[1]]
    match = _PARAM_REF_RE.match(reference)
    if not match:
        raise RecipeError(
            f"{location}: unsupported placeholder '${{{reference}}}' "
            "(use '${parameters.<name>}' or a sweep body's value/index)"
        )
    name = match.group(1)
    if name not in parameters:
        raise RecipeError(
            f"{location}: placeholder references unknown parameter {name!r} "
            f"(declared parameters: {sorted(parameters)})"
        )
    return parameters[name]


def _substitute(
    node: Any, parameters: dict[str, Any], location: str,
    sweep: dict[str, Any] | None = None,
) -> Any:
    if isinstance(node, str):
        matches = list(_PLACEHOLDER_RE.finditer(node))
        if not matches:
            return node
        # A string that is exactly one placeholder keeps the parameter's
        # native type (e.g. float); embedded placeholders stringify.
        if len(matches) == 1 and matches[0].span() == (0, len(node)):
            return _resolve_placeholder(matches[0].group(1), parameters, location, sweep)
        return _PLACEHOLDER_RE.sub(
            lambda m: str(_resolve_placeholder(m.group(1), parameters, location, sweep)),
            node,
        )
    if isinstance(node, dict):
        return {
            key: _substitute(value, parameters, f"{location}.{key}", sweep)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [
            _substitute(item, parameters, f"{location}[{index}]", sweep)
            for index, item in enumerate(node)
        ]
    return node


# -- finite sweep expansion -------------------------------------------------------


class _Sweep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["sweep"]
    start: float = Field(allow_inf_nan=False)
    stop: float = Field(allow_inf_nan=False)
    step: float = Field(gt=0, allow_inf_nan=False)
    return_to_start: bool = Field(default=False, strict=True)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_EXPANDED_ACTIONS)

    def points(self) -> list[float]:
        # Decimal avoids binary accumulation such as 0.05 + 0.025 + ... .
        start, stop, step = (Decimal(str(v)) for v in (self.start, self.stop, self.step))
        if stop < start:
            raise RecipeError("sweep.stop must be greater than or equal to sweep.start")
        segments = (stop - start) / step
        if segments != segments.to_integral_value():
            raise RecipeError("sweep range must be an exact multiple of sweep.step")
        count = segments * (2 if self.return_to_start else 1) + 1
        if count > MAX_SWEEP_POINTS:
            raise RecipeError(f"sweep exceeds {MAX_SWEEP_POINTS} points")
        points = [float(start + step * index) for index in range(int(segments) + 1)]
        if any(left >= right for left, right in zip(points, points[1:])):
            raise RecipeError("sweep.step is too small to produce distinct numeric setpoints")
        if self.return_to_start:
            points.extend(points[-2::-1])
        return points


def _expand_steps(node: Any, parameters: dict[str, Any]) -> Any:
    """Expand bounded, unnested sweeps to the ordinary action vocabulary."""
    if not isinstance(node, list):
        return node  # Let Recipe validation describe the invalid type.
    expanded: list[Any] = []
    for index, item in enumerate(node):
        location = f"steps[{index}]"
        action = _substitute(item.get("action"), parameters, location) if isinstance(item, dict) else None
        if action != "sweep":
            expanded.append(_substitute(item, parameters, location))
        else:
            raw_sweep = {
                key: value if key == "steps" else _substitute(value, parameters, f"{location}.{key}")
                for key, value in item.items()
            }
            block = _Sweep.model_validate(raw_sweep)
            points = block.points()
            if len(expanded) + len(points) * len(block.steps) > MAX_EXPANDED_ACTIONS:
                raise RecipeError(f"recipe exceeds {MAX_EXPANDED_ACTIONS} expanded actions")
            for point_index, value in enumerate(points, start=1):
                body = _substitute(block.steps, parameters, location, {"value": value, "index": point_index})
                if any(step.get("action") == "sweep" for step in body):
                    raise RecipeError(f"{location}: nested sweeps are not supported")
                expanded.extend(body)
        if len(expanded) > MAX_EXPANDED_ACTIONS:
            raise RecipeError(f"recipe exceeds {MAX_EXPANDED_ACTIONS} expanded actions")
    return expanded


# -- loading ---------------------------------------------------------------------


def parse_recipe(raw: dict, *, source: str = "<recipe>") -> Recipe:
    """Substitute parameters into a raw recipe mapping and validate it."""
    if not isinstance(raw, dict):
        raise RecipeError(f"{source}: recipe must be a mapping")
    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise RecipeError(f"{source}: 'parameters' must be a flat mapping of scalars")
    resolved = dict(raw)
    try:
        if "steps" in resolved:
            resolved["steps"] = _expand_steps(resolved["steps"], parameters)
        if "finally" in resolved:
            resolved["finally"] = _substitute(resolved["finally"], parameters, "finally")
        return Recipe.model_validate(resolved)
    except ValidationError as exc:
        raise RecipeError(f"invalid recipe in {source}:\n{exc}") from exc


def load_recipe(path: str | Path) -> Recipe:
    """Load, parameter-substitute, and strictly validate a recipe file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecipeError(f"cannot read recipe file {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RecipeError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecipeError(f"{path}: top-level YAML content must be a mapping")
    return parse_recipe(raw, source=str(path))
