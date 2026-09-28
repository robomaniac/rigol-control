"""Versioned contracts. Importing this module never opens an instrument."""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, validate_assignment=True)


class DutIdentity(Contract):
    model: str
    brand_aliases: list[str] = Field(default_factory=list)
    actual_brand_on_label: str | None = None
    sample_id: str | None = None
    revision: str | None = None
    label_photo_asset_id: str | None = None


class DutRatings(Contract):
    origin: str
    verified_from_sample_label: bool = False
    input_voltage_min_V: float = Field(gt=0)
    input_voltage_max_V: float = Field(gt=0)
    output_voltage_nominal_V: float = Field(gt=0)
    output_current_rated_A: float = Field(gt=0)
    output_power_rated_W: float = Field(gt=0)
    derating_conditions: str | None = None

    @model_validator(mode="after")
    def ordered(self) -> DutRatings:
        if self.input_voltage_min_V > self.input_voltage_max_V:
            raise ValueError("DUT input minimum exceeds maximum")
        return self


class Construction(Contract):
    topology: str = "unknown"
    isolation: str = "unknown"
    controller_part_number: str | None = None
    switching_frequency_Hz: float | None = Field(default=None, gt=0)
    enable_interface: str = "unknown"
    enclosure: str = "unknown"


class Acceptance(Contract):
    output_voltage_tolerance_pct: float | None = Field(default=None, gt=0)
    minimum_efficiency_pct: float | None = Field(default=None, ge=0, le=100)
    maximum_surface_temperature_C: float | None = None


class ExecutionApproval(Contract):
    real_hardware_enabled: bool = False
    wiring_and_polarity_confirmed: bool = False
    protective_policy_id: str | None = None


class DutProfile(Contract):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    identity: DutIdentity
    ratings: DutRatings
    construction: Construction = Field(default_factory=Construction)
    acceptance: Acceptance = Field(default_factory=Acceptance)
    execution_approval: ExecutionApproval = Field(default_factory=ExecutionApproval)


class AccuracySpec(Contract):
    """Readback specifications must explicitly establish their applicability."""
    applies_to: Literal["readback", "programming"]
    reading_fraction: float = Field(ge=0)
    full_scale_fraction: float = Field(default=0, ge=0)
    offset: float = Field(default=0, ge=0)
    full_scale: float | None = Field(default=None, gt=0)
    unit: str
    source: str
    conditions: str
    distribution: Literal["unspecified_bound", "rectangular", "standard_uncertainty"] = "unspecified_bound"
    distribution_justification: str | None = None

    @model_validator(mode="after")
    def full_scale_required(self) -> AccuracySpec:
        if self.full_scale_fraction and self.full_scale is None:
            raise ValueError("Full-scale accuracy requires its documented full scale")
        if self.distribution == "rectangular" and not self.distribution_justification:
            raise ValueError("A rectangular distribution requires an explicit justification")
        return self


class MeasurementBinding(Contract):
    instrument_id: str
    quantity: str
    unit: str
    location: str
    measurement_range: float | None = Field(default=None, gt=0)
    resolution: float | None = Field(default=None, gt=0)
    accuracy: AccuracySpec | None = None
    programming_accuracy: AccuracySpec | None = None

    @model_validator(mode="after")
    def correct_accuracy_role(self) -> MeasurementBinding:
        if self.accuracy and self.accuracy.applies_to != "readback":
            raise ValueError("Programming accuracy is not a readback uncertainty specification")
        if self.programming_accuracy and self.programming_accuracy.applies_to != "programming":
            raise ValueError("programming_accuracy requires a programming specification")
        return self


class InstrumentCapabilities(Contract):
    instrument_id: str
    adapter: str
    physical_model: str | None = None
    reported_identity: str | None = None
    firmware: str | None = None
    modification: str | None = None
    endpoint: str | None = None
    capabilities_confirmed: bool = False
    min_voltage_V: float = Field(default=0, ge=0)
    max_voltage_V: float | None = Field(default=None, gt=0)
    max_current_A: float | None = Field(default=None, gt=0)
    max_power_W: float | None = Field(default=None, gt=0)
    remote_sense_supported: bool = False
    remote_sense_required: bool = False
    programming_accuracy: dict[str, AccuracySpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def programming_specs_only(self) -> InstrumentCapabilities:
        if any(item.applies_to != "programming" for item in self.programming_accuracy.values()):
            raise ValueError("Instrument programming_accuracy accepts programming specifications only")
        if self.max_voltage_V is not None and self.min_voltage_V > self.max_voltage_V:
            raise ValueError("Instrument voltage minimum exceeds maximum")
        return self


class SourceCapabilities(InstrumentCapabilities):
    channel: int = Field(default=1, ge=1)


class LoadCapabilities(InstrumentCapabilities):
    mode: Literal["CC"] = "CC"
    min_current_A: float = Field(default=0, ge=0)


class ProtectiveControls(Contract):
    policy_id: str | None = None
    source_current_limit_A: float | None = Field(default=None, gt=0)
    dut_input_overvoltage_V: float | None = Field(default=None, gt=0)
    dut_output_overvoltage_V: float | None = Field(default=None, gt=0)
    output_overcurrent_A: float | None = Field(default=None, gt=0)
    maximum_temperature_C: float | None = None
    approved: bool = False


class BenchProfile(Contract):
    schema_version: Literal["1.0"] = "1.0"
    bench_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    mode: Literal["mock", "real"]
    source: SourceCapabilities
    load: LoadCapabilities
    measurements: dict[str, MeasurementBinding]
    protective_controls: ProtectiveControls = Field(default_factory=ProtectiveControls)
    measurement_boundary: str = "source-to-DUT-output path"
    notes: list[str] = Field(default_factory=list)


class TestDefinition(Contract):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    type: str = "steady_state_load_sweep"
    input_voltage_targets_V: list[float] = Field(min_length=1, max_length=1000)
    output_current_targets_A: list[float] = Field(min_length=1, max_length=1000)
    derived_results: list[str] = Field(default_factory=list)
    required_quantities: list[str] = Field(default_factory=lambda: ["Vin_V", "Iin_A", "Vout_V", "Iout_A"])
    optional_quantities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def finite_nonnegative_targets(self) -> TestDefinition:
        if any(v <= 0 for v in self.input_voltage_targets_V):
            raise ValueError("Requested input voltages must be positive")
        if any(i < 0 for i in self.output_current_targets_A):
            raise ValueError("Requested output current cannot be negative")
        return self


class PlanningPolicy(Contract):
    efficiency_estimate_fraction: float = Field(default=.8, gt=0, le=1)
    source_current_budget_fraction: float = Field(default=.9, gt=0, le=1)
    infeasible_point_policy: Literal["record_and_skip"] = "record_and_skip"
    assumption_status: Literal["planning_only_not_measured"] = "planning_only_not_measured"
    auxiliary_input_power_estimate_W: float = Field(default=0, ge=0)
    input_wiring_drop_allowance_V: float = Field(default=0, ge=0)


class SettlingPolicy(Contract):
    policy: Literal["electrical"] = "electrical"
    settings_origin: str = "draft_requires_bench_validation"
    minimum_dwell_s: float = Field(default=5, ge=0)
    window_s: float = Field(default=5, gt=0)
    minimum_fresh_samples: int = Field(default=5, ge=2)
    maximum_vout_span_V: float = Field(default=.05, gt=0)
    timeout_s: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def timeout_after_dwell(self) -> SettlingPolicy:
        if self.timeout_s < self.minimum_dwell_s:
            raise ValueError("Settling timeout must allow the minimum dwell")
        return self


class AcquisitionPolicy(Contract):
    duration_s: float = Field(default=5, gt=0)
    target_poll_interval_s: float = Field(default=.5, gt=0)
    minimum_complete_cycles: int = Field(default=5, ge=1)
    maximum_interchannel_skew_s: float = Field(default=.5, gt=0)
    settings_origin: str = "draft_requires_driver_timing_validation"


class AuthorizationPolicy(Contract):
    require_operator_arming: bool = True
    allow_unattended: bool = False
    protective_policy_id: str | None = None


class TestRecipe(Contract):
    __test__ = False
    schema_version: Literal["1.0"] = "1.0"
    recipe_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    dut_profile_id: str
    execution_mode: Literal["mock", "real"] = "mock"
    tests: list[TestDefinition] = Field(min_length=1, max_length=100)
    planning: PlanningPolicy = Field(default_factory=PlanningPolicy)
    settling: SettlingPolicy = Field(default_factory=SettlingPolicy)
    acquisition: AcquisitionPolicy = Field(default_factory=AcquisitionPolicy)
    authorization: AuthorizationPolicy = Field(default_factory=AuthorizationPolicy)

    @model_validator(mode="after")
    def unique_tests(self) -> TestRecipe:
        if len({t.id for t in self.tests}) != len(self.tests):
            raise ValueError("Test identifiers must be unique")
        if sum(len(t.input_voltage_targets_V) * len(t.output_current_targets_A) for t in self.tests) > 10000:
            raise ValueError("A plan may contain at most 10,000 requested points")
        return self


class ReportProfile(Contract):
    schema_version: Literal["1.0"] = "1.0"
    profile_id: str = "engineering"
    title: str = "DC–DC converter characterization"
    theme: Literal["engineering"] = "engineering"
    language: Literal["en"] = "en"
    units: Literal["SI"] = "SI"
    formats: list[Literal["html", "pdf"]] = Field(default_factory=lambda: ["html", "pdf"])
    selected_sections: list[str] = Field(default_factory=lambda: ["summary", "dut", "setup", "results", "interpretation", "appendix"])
    default_metric: str = "efficiency_pct"
    publication_enabled: Literal[False] = False
    embed_assets: Literal[True] = True
    noindex: Literal[True] = True


class PlannedPoint(Contract):
    point_id: str
    test_id: str
    vin_target_V: float
    iout_target_A: float
    status: Literal["executable", "assumption_limited", "unsupported", "approval_blocked"]
    reason: str
    estimated_input_current_A: float | None = None
    physical_input_power_limit_W: float | None = None
    planning_output_current_limit_A: float | None = None

    @property
    def feasible(self) -> bool:
        return self.status == "executable"

    @property
    def vin_v(self) -> float:
        return self.vin_target_V

    @property
    def iout_a(self) -> float:
        return self.iout_target_A


class Plan(Contract):
    schema_version: Literal["1.0"] = "1.0"
    planner_version: str = "1.0"
    dut: DutProfile
    bench: BenchProfile
    recipe: TestRecipe
    points: list[PlannedPoint]
    plan_hash: str
    warnings: list[str] = Field(default_factory=list)


class RawSample(Contract):
    """One actual query result; null values carry a quality reason, never NaN."""
    schema_version: Literal["1.0"] = "1.0"
    sample_id: str
    run_id: str
    test_id: str
    point_id: str
    channel_id: str
    instrument_id: str
    quantity: str
    value: float | None
    unit: str
    location: str
    query_start_utc: str
    query_end_utc: str
    query_start_monotonic_s: float
    query_end_monotonic_s: float
    device_timestamp: str | None = None
    measurement_range: float | None = None
    resolution: float | None = None
    acquisition_settings: dict[str, Any] = Field(default_factory=dict)
    raw_response: str | None = None
    status: str = "ok"
    quality_flags: list[str] = Field(default_factory=list)
    acquisition_cycle_id: str
    phase: str = "acquisition"

    @model_validator(mode="after")
    def valid_reading(self) -> RawSample:
        if self.value is None and not self.quality_flags:
            raise ValueError("A missing reading requires a quality reason")
        if self.query_end_monotonic_s < self.query_start_monotonic_s:
            raise ValueError("Query end precedes query start")
        return self


class SourceAdapter(Protocol):
    def identify(self) -> str: ...
    def capabilities(self) -> SourceCapabilities: ...
    def configure(self, voltage_V: float, current_limit_A: float) -> None: ...
    def output(self, enabled: bool) -> None: ...
    def status(self) -> dict[str, Any]: ...
    def close(self, timeout_s: float) -> None: ...


class LoadAdapter(Protocol):
    def identify(self) -> str: ...
    def capabilities(self) -> LoadCapabilities: ...
    def configure(self, mode: str, current_A: float, remote_sense: bool) -> None: ...
    def input(self, enabled: bool) -> None: ...
    def status(self) -> dict[str, Any]: ...
    def close(self, timeout_s: float) -> None: ...


class MeasurementProvider(Protocol):
    def read(self, quantity: str, timeout_s: float) -> RawSample: ...


class TestProcedure(Protocol):
    def required_quantities(self) -> list[str]: ...
    def expected_states(self) -> list[str]: ...
    def result_type(self) -> str: ...


class RunStore(Protocol):
    def append(self, stream: str, record: dict[str, Any]) -> None: ...
    def finalize(self, manifest: dict[str, Any]) -> None: ...


class Analyzer(Protocol):
    def analyze(self, evidence: dict[str, Any]) -> dict[str, Any]: ...


class ReportRenderer(Protocol):
    def render(self, report_model: dict[str, Any], output_directory: str) -> dict[str, Any]: ...
