"""Recipe execution: safety-validate everything first, then run.

Order of operations enforced here:

1. Resolve the setup's roles to configured devices and check the recipe's
   ``requires`` kinds against the device kinds.
2. Look up every device's safety profile (a missing profile is a hard error).
3. Validate EVERY setpoint in the fully-resolved recipe (steps and finally)
   against the safety profiles. Any violation aborts before a single VISA
   session is opened — nothing is ever sent to an instrument.
4. Open transports, build drivers, identify and verify any configured serials,
   then execute steps with same-run configuration guards.
5. Once connection and identity checks succeed, attempt the recipe's
   ``finally`` actions after success, step failure, and KeyboardInterrupt.
   Cleanup failures are reported on stderr and in the execution log but
   never mask the original step error.
6. Measurements are recorded before inclusive expectations are enforced.
   A run directory with logs and a pass/fail/error summary is written via
   :mod:`benchctl.results`.

The safety module is imported lazily so tests can substitute a fake via
``sys.modules``; only its documented names are used.
"""

from __future__ import annotations

import dataclasses
import importlib
import math
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from benchctl import results
from benchctl.paths import DEFAULT_RESULTS_DIR
from benchctl.config import DeviceConfig, LabConfig
from benchctl.identity import identify_and_verify
from benchctl.interfaces import Transport
from benchctl.recipes import (
    LoadConfigureCC,
    LoadInputOff,
    LoadInputOn,
    Measure,
    Recipe,
    SupplyAllOutputsOff,
    SupplyConfigure,
    SupplyOutputOff,
    SupplyOutputOn,
    Wait,
)
from benchctl.transport import VisaTransport

TransportFactory = Callable[[str, DeviceConfig], Transport]
DriverFactory = Callable[[DeviceConfig, Transport], Any]

# measure source -> (role, driver method, needs channel argument)
_MEASURE_METHODS: dict[str, tuple[str, str, bool]] = {
    "supply.voltage": ("supply", "measure_voltage", True),
    "supply.current": ("supply", "measure_current", True),
    "supply.power": ("supply", "measure_power", True),
    "load.voltage": ("load", "measure_voltage", False),
    "load.current": ("load", "measure_current", False),
    "load.power": ("load", "measure_power", False),
}


class RunnerError(Exception):
    """Raised when a recipe cannot be run against the given setup."""


class RuntimeSafetyError(RuntimeError):
    """Raised when runtime state cannot safely satisfy an action."""


class MeasurementExpectationError(RuntimeError):
    """Raised after recording a measurement that failed an expectation."""


@dataclass(frozen=True)
class ResolvedDevice:
    role: str
    name: str
    config: DeviceConfig
    profile: Any


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    status: str
    outcome: str


@dataclass
class _ExecutionState:
    """Successfully configured state established during this run only."""

    supply_channels: set[int] = field(default_factory=set)
    load_max_voltage_v: float | None = None


def make_transport(device_name: str, device: DeviceConfig) -> VisaTransport:
    return VisaTransport(device_name, device.resource)


def make_driver(device: DeviceConfig, transport: Transport) -> Any:
    # Imported lazily: the registry pulls in every driver module.
    from benchctl.registry import get_driver_class

    return get_driver_class(device.driver)(transport)


def _safety():
    return importlib.import_module("benchctl.safety")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


# -- pre-flight ---------------------------------------------------------------


def resolve_devices(
    recipe: Recipe,
    config: LabConfig,
    setup_name: str,
    safety_profiles: Mapping[str, Any],
) -> dict[str, ResolvedDevice]:
    """Map the recipe's required roles onto the setup's devices."""
    if setup_name not in config.setups:
        raise RunnerError(
            f"unknown setup {setup_name!r} (configured setups: "
            f"{sorted(config.setups)})"
        )
    setup = config.setups[setup_name]
    resolved: dict[str, ResolvedDevice] = {}
    safety = _safety()
    for role, requirement in recipe.requires.items():
        if role not in setup:
            raise RunnerError(
                f"setup {setup_name!r} does not provide role {role!r} "
                f"required by recipe {recipe.name!r}"
            )
        device_name = setup[role]
        device = config.devices[device_name]
        if device.kind != requirement.kind:
            raise RunnerError(
                f"recipe {recipe.name!r} requires role {role!r} of kind "
                f"{requirement.kind!r}, but device {device_name!r} has kind "
                f"{device.kind!r}"
            )
        try:
            profile = safety.get_device_safety_profile(
                safety_profiles, device_name, device
            )
        except safety.SafetyError as exc:
            raise RunnerError(str(exc)) from exc
        resolved[role] = ResolvedDevice(
            role=role,
            name=device_name,
            config=device,
            profile=profile,
        )
    return resolved


def validate_setpoints(recipe: Recipe, devices: Mapping[str, ResolvedDevice]) -> None:
    """Check every setpoint in steps and finally against safety profiles."""
    safety = _safety()
    for phase, actions in (("steps", recipe.steps), ("finally", recipe.finally_steps)):
        for index, action in enumerate(actions):
            where = f"{phase}[{index}] ({action.action})"
            try:
                if isinstance(action, SupplyConfigure):
                    safety.validate_supply_setpoint(
                        devices["supply"].profile,
                        action.channel,
                        voltage_v=action.voltage_v,
                        current_a=action.current_limit_a,
                    )
                elif isinstance(action, LoadConfigureCC):
                    safety.validate_load_setpoint(
                        devices["load"].profile,
                        mode="cc",
                        current_a=action.current_a,
                        max_voltage_v=action.max_voltage_v,
                    )
            except safety.SafetyError as exc:
                raise RunnerError(f"unsafe setpoint at {where}: {exc}") from exc


# -- execution ------------------------------------------------------------------


def _best_effort_input_off(load: Any, original: BaseException) -> None:
    """Try to make a failed enable safe without replacing its root cause."""
    try:
        load.input_off()
    except BaseException as shutdown_error:
        original.add_note(
            "load input-off after enable failure also failed: "
            f"{_describe(shutdown_error)}"
        )
        print(
            "warning: load input-off after enable failure also failed: "
            f"{shutdown_error}",
            file=sys.stderr,
        )


def _best_effort_output_off(
    supply: Any, channel: int, original: BaseException
) -> None:
    """Try to disable a supply channel after an uncertain enable."""
    try:
        supply.output_off(channel)
    except BaseException as shutdown_error:
        original.add_note(
            f"supply CH{channel} output-off after enable failure also failed: "
            f"{_describe(shutdown_error)}"
        )
        print(
            f"warning: supply CH{channel} output-off after enable failure "
            f"also failed: {shutdown_error}",
            file=sys.stderr,
        )


def _enable_and_verify_load(
    load: Any,
    profile: Any,
    max_voltage_v: float,
) -> None:
    """Enable the load and immediately enforce its live safety envelope."""
    try:
        load.input_on()
        voltage_v = float(load.measure_voltage())
        current_a = float(load.measure_current())
        power_w = float(load.measure_power())
        _safety().validate_load_measurements(
            profile,
            max_voltage_v=max_voltage_v,
            voltage_v=voltage_v,
            current_a=current_a,
            power_w=power_w,
        )
    except BaseException as exc:
        _best_effort_input_off(load, exc)
        raise


def _measurement_verdicts(
    action: Measure,
    values: Mapping[str, float],
) -> tuple[dict[str, dict[str, Any]], str, list[str]]:
    """Build inclusive per-value verdicts without raising."""
    verdicts: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    checked = 0
    for label, spec in action.values.items():
        value = values[label]
        expectation = spec.expect
        if expectation is None:
            verdicts[label] = {"status": "not_checked"}
            continue

        checked += 1
        verdict: dict[str, Any] = {"status": "pass"}
        if expectation.min is not None:
            verdict["min"] = expectation.min
        if expectation.max is not None:
            verdict["max"] = expectation.max

        reasons: list[str] = []
        if not math.isfinite(value):
            reasons.append("value is not finite")
        else:
            if expectation.min is not None and value < expectation.min:
                reasons.append(f"below minimum {expectation.min}")
            if expectation.max is not None and value > expectation.max:
                reasons.append(f"above maximum {expectation.max}")
        if reasons:
            verdict["status"] = "fail"
            verdict["reason"] = "; ".join(reasons)
            failures.append(f"{label}={value!r} ({verdict['reason']})")
        verdicts[label] = verdict

    status = "fail" if failures else ("pass" if checked else "not_checked")
    return verdicts, status, failures


def _execute_action(
    action: Any,
    drivers: Mapping[str, Any],
    devices: Mapping[str, ResolvedDevice],
    state: _ExecutionState,
    sleep: Callable[[float], None],
    record_measurement: Callable[
        [str, dict[str, float], dict[str, dict[str, Any]], str], None
    ],
) -> None:
    if isinstance(action, SupplyConfigure):
        supply = drivers["supply"]
        if supply.get_output_enabled(action.channel):
            raise RuntimeSafetyError(
                f"supply channel {action.channel} output is ON; turn it OFF "
                "before changing voltage or current limit"
            )
        supply.set_voltage(action.channel, action.voltage_v)
        supply.set_current_limit(action.channel, action.current_limit_a)
        state.supply_channels.add(action.channel)
    elif isinstance(action, SupplyOutputOn):
        if action.channel not in state.supply_channels:
            raise RuntimeSafetyError(
                f"supply.output_on for channel {action.channel} requires a "
                "successful prior same-run supply.configure"
            )
        supply = drivers["supply"]
        try:
            supply.output_on(action.channel)
        except BaseException as exc:
            _best_effort_output_off(supply, action.channel, exc)
            raise
    elif isinstance(action, SupplyOutputOff):
        drivers["supply"].output_off(action.channel)
    elif isinstance(action, SupplyAllOutputsOff):
        drivers["supply"].all_outputs_off()
    elif isinstance(action, LoadConfigureCC):
        load = drivers["load"]
        if load.get_input_enabled():
            raise RuntimeSafetyError(
                "load input is ON; turn it OFF before changing mode or current"
            )
        load.set_mode("cc")
        load.set_current(action.current_a)
        state.load_max_voltage_v = action.max_voltage_v
    elif isinstance(action, LoadInputOn):
        if state.load_max_voltage_v is None:
            raise RuntimeSafetyError(
                "load.input_on requires a successful prior same-run "
                "load.configure_cc"
            )
        _enable_and_verify_load(
            drivers["load"],
            devices["load"].profile,
            state.load_max_voltage_v,
        )
    elif isinstance(action, LoadInputOff):
        drivers["load"].input_off()
    elif isinstance(action, Wait):
        sleep(action.seconds)
    elif isinstance(action, Measure):
        values: dict[str, float] = {}
        for label, spec in action.values.items():
            role, method, needs_channel = _MEASURE_METHODS[spec.source]
            fn = getattr(drivers[role], method)
            values[label] = float(fn(spec.channel) if needs_channel else fn())
        verdicts, status, failures = _measurement_verdicts(action, values)
        record_measurement(action.save_as, values, verdicts, status)
        if failures:
            raise MeasurementExpectationError(
                f"measurement {action.save_as!r} failed expectations: "
                + ", ".join(failures)
            )
    else:  # pragma: no cover - the recipe schema makes this unreachable
        raise RunnerError(f"unsupported action {action.action!r}")


def _log_event(
    run_dir: Path, phase: str, index: int, action: Any, error: str | None = None
) -> None:
    results.append_event(
        run_dir,
        phase=phase,
        index=index,
        action=action.action,
        detail=action.model_dump(exclude={"action"}),
        error=error,
    )


def _export_csv_if_measured(run_dir: Path) -> None:
    """Write measurements.csv if any measurements were recorded.

    A CSV failure must never change the run's real outcome, so problems
    are reported as warnings instead of raised.
    """
    source = run_dir / results.MEASUREMENTS_FILENAME
    try:
        if not source.exists() or not source.read_text(encoding="utf-8").strip():
            return
        results.export_csv(run_dir)
    except Exception as exc:
        print(
            f"warning: could not write {results.CSV_FILENAME}: {exc}",
            file=sys.stderr,
        )


def _run_finally_actions(
    recipe: Recipe,
    drivers: Mapping[str, Any],
    devices: Mapping[str, ResolvedDevice],
    state: _ExecutionState,
    run_dir: Path,
    sleep: Callable[[float], None],
    record_measurement: Callable[
        [str, dict[str, float], dict[str, dict[str, Any]], str], None
    ],
) -> BaseException | None:
    """Run every cleanup action; report failures, return the first one."""
    first_error: BaseException | None = None
    for index, action in enumerate(recipe.finally_steps):
        action_error: BaseException | None = None
        try:
            _execute_action(
                action,
                drivers,
                devices,
                state,
                sleep,
                record_measurement,
            )
        except BaseException as exc:
            action_error = exc
            print(
                f"warning: cleanup action {action.action!r} failed: {exc}",
                file=sys.stderr,
            )
            if first_error is None:
                first_error = exc
        try:
            _log_event(
                run_dir,
                "finally",
                index,
                action,
                error=_describe(action_error) if action_error is not None else None,
            )
        except BaseException as log_error:
            print(
                f"warning: could not log cleanup action {action.action!r}: "
                f"{log_error}",
                file=sys.stderr,
            )
            if first_error is None:
                first_error = log_error
    return first_error


def run_recipe(
    recipe: Recipe,
    config: LabConfig,
    setup_name: str,
    safety_profiles: Mapping[str, Any],
    *,
    transport_factory: TransportFactory | None = None,
    driver_factory: DriverFactory | None = None,
    results_base: str | Path = DEFAULT_RESULTS_DIR,
    sleep: Callable[[float], None] | None = None,
) -> RunResult:
    """Validate then execute a recipe; attempt cleanup after verified setup.

    On failure the original exception propagates after cleanup and after
    the run summary has been written. Connection and identity failures do
    not send recipe cleanup commands to unverified instruments.
    """
    # Factories resolved at call time so tests can monkeypatch the
    # module-level defaults.
    if transport_factory is None:
        transport_factory = make_transport
    if driver_factory is None:
        driver_factory = make_driver
    if sleep is None:
        sleep = time.sleep

    devices = resolve_devices(recipe, config, setup_name, safety_profiles)
    validate_setpoints(recipe, devices)

    run_dir = results.create_run_dir(recipe.name, base=results_base)
    started_at = _utc_now_iso()
    error: BaseException | None = None
    identities: dict[str, Any] = {}
    state = _ExecutionState()

    def record_measurement(
        save_as: str,
        values: dict[str, float],
        verdicts: dict[str, dict[str, Any]],
        status: str,
    ) -> None:
        results.append_measurement(
            run_dir,
            save_as=save_as,
            values=values,
            setup=setup_name,
            recipe_name=recipe.name,
            verdicts=verdicts,
            status=status,
        )
        rendered = ", ".join(f"{label}={value:.6g}" for label, value in values.items())
        print(f"measured {save_as}: {rendered}")

    try:
        with ExitStack() as stack:
            drivers: dict[str, Any] = {}
            for role, device in devices.items():
                transport = stack.enter_context(
                    transport_factory(device.name, device.config)
                )
                drivers[role] = driver_factory(device.config, transport)
            for role, driver in drivers.items():
                device = devices[role]
                ident = identify_and_verify(
                    device.name,
                    device.config,
                    driver,
                )
                identities[role] = (
                    dataclasses.asdict(ident)
                    if dataclasses.is_dataclass(ident)
                    else str(ident)
                )
            try:
                for index, action in enumerate(recipe.steps):
                    try:
                        _execute_action(
                            action,
                            drivers,
                            devices,
                            state,
                            sleep,
                            record_measurement,
                        )
                    except BaseException as exc:
                        _log_event(
                            run_dir, "steps", index, action, error=_describe(exc)
                        )
                        raise
                    _log_event(run_dir, "steps", index, action)
            except BaseException as exc:
                error = exc
            finally:
                cleanup_error = _run_finally_actions(
                    recipe,
                    drivers,
                    devices,
                    state,
                    run_dir,
                    sleep,
                    record_measurement,
                )
                if error is None and cleanup_error is not None:
                    error = cleanup_error
    except BaseException as exc:
        # Connection/identification/transport-close failures. Never mask an
        # error already captured from the steps.
        if error is None:
            error = exc
        else:
            print(f"warning: teardown failed: {exc}", file=sys.stderr)

    status = "success" if error is None else "failed"
    if error is None:
        outcome = "pass"
    elif isinstance(error, MeasurementExpectationError):
        outcome = "fail"
    else:
        outcome = "error"
    results.write_run_summary(
        run_dir,
        recipe_name=recipe.name,
        setup=setup_name,
        parameters=recipe.parameters,
        started_at=started_at,
        finished_at=_utc_now_iso(),
        status=status,
        outcome=outcome,
        error=_describe(error) if error is not None else None,
        identities=identities,
    )
    _export_csv_if_measured(run_dir)
    if error is not None:
        raise error
    return RunResult(run_dir=run_dir, status=status, outcome=outcome)
