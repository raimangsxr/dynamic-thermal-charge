"""Characterisation tests for the incremental planning module boundaries."""

import ast
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from dynamic_thermal_charge import charge_planning as legacy_module
from dynamic_thermal_charge.models import (
    ChargeTelemetry,
    Heater,
    OutputConfig,
    TemperatureTarget,
)
from dynamic_thermal_charge.planning_compatibility import LegacyPercentagePlanner
from dynamic_thermal_charge.planning_domain import (
    AutomaticPlan,
    AutomaticPlanSlot,
    PlanningInput,
    PlanningViolation,
)
from dynamic_thermal_charge.planning_solver import CurrentEnergyPlanner
from dynamic_thermal_charge.weather import HourlyForecastPoint


def _room_request() -> PlanningInput:
    start = datetime(2026, 1, 19, 0, 0, tzinfo=timezone.utc)
    heater = Heater(
        id="room",
        name="room",
        power_w=1200,
        full_charge_minutes=120,
        output=OutputConfig(),
    )
    stamp = start
    telemetry = ChargeTelemetry(
        "room",
        indoor_temperature_c=20.0,
        stored_soc_percent=50.0,
        indoor_received_at=stamp,
        stored_soc_received_at=stamp,
    )
    target = TemperatureTarget(
        21.0,
        time(0, 0),
        time(0, 0),
        weekdays=(0,),
    )
    forecast = tuple(
        HourlyForecastPoint(start + timedelta(hours=index), 5.0)
        for index in range(3)
    )
    return PlanningInput(
        heaters=(heater,),
        telemetry={"room": telemetry},
        constraints=(),
        forecast=forecast,
        horizon_start=start,
        horizon_hours=2,
        slot_minutes=30,
        max_total_power_w=1200,
        max_heating_power_w=1200,
        generated_at=start,
        temperature_targets={"room": (target,)},
        room_energy_model=True,
    )


def _canonical_plan(plan: AutomaticPlan) -> dict:
    value = {
        "horizon_start": plan.horizon_start,
        "horizon_end": plan.horizon_end,
        "slot_minutes": plan.slot_minutes,
        "slots": plan.slots,
        "deficits": plan.deficits,
        "status": plan.status,
        "score": plan.score,
        "input_token": plan.input_token,
        "generated_at": plan.generated_at,
        "explanations": plan.explanations,
        "demand": plan.demand,
        "convergence_by_heater": dict(plan.convergence_by_heater),
        "convergence_at": plan.convergence_at,
        "guaranteed_until": plan.guaranteed_until,
        "diagnostics": dict(plan.diagnostics),
        "optimization_quality": plan.optimization_quality,
    }
    def without_runtime_measurements(item):
        if isinstance(item, dict):
            return {
                key: without_runtime_measurements(child)
                for key, child in item.items()
                if not str(key).endswith("_seconds")
            }
        if isinstance(item, tuple):
            return tuple(without_runtime_measurements(child) for child in item)
        if isinstance(item, list):
            return [without_runtime_measurements(child) for child in item]
        return item

    return without_runtime_measurements(value)


def test_domain_values_are_reexported_for_legacy_consumers():
    assert legacy_module.AutomaticPlan is AutomaticPlan
    assert legacy_module.AutomaticPlanSlot is AutomaticPlanSlot
    assert legacy_module.PlanningInput is PlanningInput
    assert legacy_module.PlanningViolation is PlanningViolation


def test_current_solver_preserves_the_existing_room_energy_result():
    request = _room_request()
    before = legacy_module.DeterministicChargeOptimizer().build(request)
    after = CurrentEnergyPlanner().build(request)

    assert _canonical_plan(before) == _canonical_plan(after)


def test_legacy_compatibility_is_explicit_and_never_a_solver_fallback():
    request = _room_request()

    with pytest.raises(ValueError, match="current planning solver"):
        CurrentEnergyPlanner().build(replace(request, room_energy_model=False))
    with pytest.raises(ValueError, match="legacy percentage planning"):
        LegacyPercentagePlanner().build(request)


@pytest.mark.parametrize("module_name", ("planning_domain.py", "planning_solver.py"))
def test_domain_and_solver_modules_have_no_infrastructure_imports(module_name):
    source = Path(legacy_module.__file__).parent / module_name
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("fastapi", "persistence", "angular")
    assert not any(
        any(item in name.lower() for item in forbidden) for name in imported
    )
