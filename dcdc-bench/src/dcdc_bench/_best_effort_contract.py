"""TEMPORARY local copy of the best-effort ISO 16750-2 contract (delete at merge).

``best_effort_procedures`` imports these names from ``domain`` first and falls
back to this module only while the checkout lacks them (the shared contract is
added to ``domain.py`` by another worktree). Importing this module installs the
same optional fields on the existing contracts in place, so the procedures and
their tests are written exactly against the final shape:

- ``TestDefinition.best_effort: BestEffortPolicy | None``
- ``AuthorizationPolicy.best_effort_approved``, ``accepted_deviations_sha256``,
  ``instrument_timed_bound_s``, ``program_clause_level_exactly``
- ``planning.IMPLEMENTED_TEST_TYPES`` gains the four best-effort test types so
  the planner expands their points (the procedure enforces its own approval
  gate; the planner-side verdicts belong to the standards work).

Nothing here touches hardware or changes any saved profile.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic.fields import FieldInfo

from . import domain, planning
from .domain import Contract

TRANSIENT_HOLD_TEST_TYPE = "transient_hold"
MOMENTARY_DROP_TEST_TYPE = "momentary_drop"
MICRO_INTERRUPTION_TEST_TYPE = "micro_interruption"
LINE_INTERRUPTION_TEST_TYPE = "line_interruption"
BEST_EFFORT_TEST_TYPES = (TRANSIENT_HOLD_TEST_TYPE, MOMENTARY_DROP_TEST_TYPE, MICRO_INTERRUPTION_TEST_TYPE,
                          LINE_INTERRUPTION_TEST_TYPE)
Mechanism = Literal["lan_voltage_step", "lan_output_off", "supply_timer", "supply_delayer", "switch_box", "none"]
MeasuredBy = Literal["host_clock", "supply_readback", "none", "scope"]
Classification = Literal["met", "approximated", "not_met_but_documented", "unknown_until_measured"]


class DeviationRequirement(Contract):
    """What the clause asks: the recorded value, the tolerance that applies and the basis tag."""
    value: float | str | None = None
    tolerance: float | str | None = None
    basis: str


class DeviationAchievable(Contract):
    """What this bench commands or is bounded to, with its basis tag."""
    value: float | str | None = None
    bound: str | None = None
    basis: str


class DeviationEntry(Contract):
    parameter: str
    unit: str
    required: DeviationRequirement
    achievable: DeviationAchievable
    mechanism: Mechanism
    measured_by: MeasuredBy
    classification: Classification
    note: str | None = None


class DeviationSheet(Contract):
    schema_version: Literal["1.0"] = "1.0"
    standard: str
    clause: str
    variant: str | None = None
    entries: list[DeviationEntry] = Field(min_length=1)
    statement: str


class BestEffortPolicy(Contract):
    """Declared best-effort stimulus for one ISO 16750-2 clause (mock-only procedures)."""
    clause: str
    variant: str | None = None
    level_V: float | None = Field(default=None, gt=0)
    hold_s: float | None = Field(default=None, gt=0)
    repeats: int = Field(default=1, ge=1, le=1000)
    interruption_s: float | None = Field(default=None, gt=0)
    recovery_s: float = Field(default=0.0, ge=0)
    drop_level_V: float | None = Field(default=None, ge=0)
    drop_s: float | None = Field(default=None, gt=0)
    mechanism: Mechanism
    deviation_sheet: DeviationSheet

    @model_validator(mode="after")
    def finite_declarations(self) -> BestEffortPolicy:
        if self.mechanism == "none":
            raise ValueError("A best-effort stimulus needs a mechanism; 'none' is the sheet's marker for an unmeasured row")
        return self


def _install() -> None:
    changed = False
    if "best_effort" not in domain.TestDefinition.model_fields:
        domain.TestDefinition.model_fields["best_effort"] = FieldInfo(annotation=BestEffortPolicy | None, default=None)
        domain.TestDefinition.model_rebuild(force=True)
        changed = True
    additions = {"best_effort_approved": FieldInfo(annotation=bool, default=False),
                 "accepted_deviations_sha256": FieldInfo(annotation=str | None, default=None),
                 "instrument_timed_bound_s": FieldInfo(annotation=float | None, default=None),
                 "program_clause_level_exactly": FieldInfo(annotation=bool, default=False)}
    for name, info in additions.items():
        if name not in domain.AuthorizationPolicy.model_fields:
            domain.AuthorizationPolicy.model_fields[name] = info
            changed = True
    if changed:
        domain.AuthorizationPolicy.model_rebuild(force=True)
        domain.TestRecipe.model_rebuild(force=True)
        domain.Plan.model_rebuild(force=True)
    missing = tuple(kind for kind in BEST_EFFORT_TEST_TYPES if kind not in planning.IMPLEMENTED_TEST_TYPES)
    if missing:
        planning.IMPLEMENTED_TEST_TYPES = (*planning.IMPLEMENTED_TEST_TYPES, *missing)


_install()

__all__ = ["BEST_EFFORT_TEST_TYPES", "BestEffortPolicy", "DeviationAchievable", "DeviationEntry", "DeviationRequirement",
           "DeviationSheet", "LINE_INTERRUPTION_TEST_TYPE", "MICRO_INTERRUPTION_TEST_TYPE", "MOMENTARY_DROP_TEST_TYPE",
           "TRANSIENT_HOLD_TEST_TYPE"]
