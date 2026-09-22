"""Pure planning domain values and deterministic input materialisation.

This module is deliberately independent from FastAPI, persistence and the
HTTP response models.  The solver and the coordination layer consume these
values, while the existing ``charge_planning`` module re-exports them for
internal compatibility during the incremental migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .models import ChargeConstraint, ChargeTelemetry, Heater, TemperatureTarget
from .scheduler import next_slot_boundary
from .system_settings import MqttSystemSettings
from .weather import HourlyForecastPoint

# ``VALID`` is the only successful public status.  Keep ``FEASIBLE`` as an
# import-level compatibility alias for integrations that still import the old
# symbol; it deliberately has the new persisted value.
VALID = "VALID"
FEASIBLE = VALID
CONVERGING = "CONVERGING"
DEGRADED = "DEGRADED"
INVALID = "INVALID"
OPTIMAL = "OPTIMAL"
FEASIBLE_LIMIT = "FEASIBLE_LIMIT"
NO_SOLUTION = "NO_SOLUTION"
SOLVER_TIME_LIMIT_SECONDS = 30
PLANNING_HORIZON_HOURS = 24
SOLVER_NUMERICAL_TOLERANCE = 1e-5
REPLAY_NUMERICAL_TOLERANCE = 1e-4
QUALITY_PHASE_BUDGET_SECONDS = 2.0


def _key(at: datetime) -> datetime:
    """Return a unique instant key across repeated local DST hours."""
    return at.astimezone(timezone.utc)


def resolve_planning_telemetry(
    heaters: Sequence[Heater],
    persisted: Mapping[str, ChargeTelemetry],
    observed_at: datetime,
    *,
    mqtt: MqttSystemSettings | None = None,
    max_age_seconds: float = 900,
) -> dict[str, ChargeTelemetry]:
    """Return the telemetry snapshot automatic planning should use."""
    if mqtt is not None and not mqtt.enabled:
        return {}
    valid: dict[str, ChargeTelemetry] = {}
    for heater in heaters:
        if not heater.enabled:
            continue
        value = persisted.get(heater.id)
        if value is None:
            continue
        stamps = (value.indoor_received_at, value.stored_soc_received_at)
        if all(
            item is not None
            and 0 <= (observed_at - item).total_seconds() <= max_age_seconds
            for item in stamps
        ):
            valid[heater.id] = value
    return valid


@dataclass(frozen=True)
class DemandEstimate:
    heater_id: str
    start: datetime
    end: datetime
    outdoor_temperature_c: float
    target_temperature_c: float
    feedback_temperature_c: float
    degree_hours: float
    thermal_coefficient: float
    demand_factor: float
    reserve_percent: float
    demand_kwh: float


@dataclass(frozen=True)
class MaterializedConstraint:
    requirement_id: int | None
    heater_id: str
    at: datetime
    minimum_soc_percent: float
    priority: int


@dataclass(frozen=True)
class PlanningViolation:
    heater_id: str | None
    requirement: str
    achievable_value: float | None
    shortfall: float | None
    at: datetime | None
    reason: str
    target_window_start: datetime | None = None
    target_window_end: datetime | None = None
    stored_energy_kwh: float | None = None

    @property
    def target_charge_percent(self) -> float:
        return float((self.achievable_value or 0) + (self.shortfall or 0))

    @property
    def projected_charge_percent(self) -> float:
        return float(self.achievable_value or 0)

    @property
    def deficit_percent(self) -> float:
        return float(self.shortfall or 0)


PlanningDeficit = PlanningViolation


class PlanningCancelled(Exception):
    """Raised when cooperative preview cancellation reaches a safe boundary."""


@dataclass(frozen=True)
class AutomaticPlanSlot:
    start: datetime
    end: datetime
    heater_ids: tuple[str, ...]
    power_w: int
    stored_charge_percent: dict[str, float]
    required_charge_percent: dict[str, float]
    outdoor_temperature_c: float | None = None
    indoor_temperature_c: dict[str, float] | None = None
    initial_soc_percent: dict[str, float] | None = None
    demand_kwh: dict[str, float] | None = None
    heater_power_w: dict[str, int] | None = None
    stored_energy_kwh: dict[str, float] | None = None
    target_temperature_c: dict[str, float] | None = None
    heat_delivered_kwh: dict[str, float] | None = None
    thermal_loss_kwh: dict[str, float] | None = None
    temperature_shortfall_c: dict[str, float] | None = None
    charge_energy_kwh: dict[str, float] | None = None
    stored_energy_next_kwh: dict[str, float] | None = None
    indoor_temperature_next_c: dict[str, float] | None = None
    temperature_shortfall_start_c: dict[str, float] | None = None
    heat_delivery_limit_kwh: dict[str, float] | None = None


@dataclass(frozen=True)
class HeaterExplanation:
    heater_id: str
    actual_soc_percent: float
    total_demand_kwh: float
    demand_factor: float
    reserve_percent: float
    next_constraint_at: datetime | None
    charge_periods: tuple[tuple[datetime, datetime], ...]
    capacity_kwh: float = 0.0
    initial_indoor_temperature_c: float | None = None
    final_indoor_temperature_c: float | None = None
    total_heat_delivered_kwh: float = 0.0
    total_thermal_loss_kwh: float = 0.0
    maximum_temperature_shortfall_c: float = 0.0
    initial_stored_energy_kwh: float | None = None
    final_stored_energy_kwh: float | None = None
    total_charge_energy_kwh: float | None = None
    forecast_contribution_kwh: float | None = None
    terminal_surplus_energy_kwh: float | None = None
    next_target_temperature_c: float | None = None
    next_target_start: datetime | None = None
    next_target_end: datetime | None = None
    charge_reasons: tuple[dict[str, Any], ...] | None = None


@dataclass(frozen=True)
class AutomaticPlan:
    horizon_start: datetime
    horizon_end: datetime
    slot_minutes: int
    slots: tuple[AutomaticPlanSlot, ...]
    deficits: tuple[PlanningViolation, ...]
    status: str
    score: tuple[float, ...]
    input_token: str
    generated_at: datetime | None = None
    explanations: tuple[HeaterExplanation, ...] = ()
    demand: tuple[DemandEstimate, ...] = ()
    convergence_by_heater: Mapping[str, datetime | None] = field(default_factory=dict)
    convergence_at: datetime | None = None
    guaranteed_until: datetime | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    optimization_quality: str = OPTIMAL

    @property
    def violations(self) -> tuple[PlanningViolation, ...]:
        return self.deficits


@dataclass(frozen=True)
class PlanningInput:
    heaters: tuple[Heater, ...]
    telemetry: Mapping[str, ChargeTelemetry]
    constraints: tuple[ChargeConstraint, ...]
    forecast: Sequence[HourlyForecastPoint]
    horizon_start: datetime
    horizon_hours: int = PLANNING_HORIZON_HOURS
    slot_minutes: int = 30
    max_total_power_w: int = 5200
    base_load_w: int = 0
    timezone_name: str = "UTC"
    design_indoor_temperature_c: float = 21.0
    design_outdoor_temperature_c: float = 0.0
    feedback_horizon_hours: float = 6.0
    max_heating_power_w: int | None = None
    forecast_automatic_eligible: bool = True
    solver_time_limit_seconds: int | None = None
    generated_at: datetime | None = None
    exploration_limit: int = 100_000
    progress_callback: Callable[[str], None] | None = None
    cancellation_probe: Callable[[], bool] | None = None
    temperature_targets: Mapping[str, Sequence[TemperatureTarget]] = field(
        default_factory=dict
    )
    room_energy_model: bool = False
    telemetry_max_age_seconds: float = 900.0


def materialize_constraints(
    constraints: Sequence[ChargeConstraint],
    heaters: Sequence[Heater],
    horizon_start: datetime,
    horizon_end: datetime,
    slot_minutes: int,
    timezone_name: str,
) -> tuple[MaterializedConstraint, ...]:
    """Expand recurring percentage constraints into deterministic boundaries."""
    zone = ZoneInfo(timezone_name)
    priorities = {item.id: item.priority for item in heaters}
    boundaries: list[datetime] = []
    cursor = horizon_start
    while not _key(horizon_end) < _key(cursor):
        boundaries.append(cursor)
        cursor = next_slot_boundary(cursor, slot_minutes)
    result: list[MaterializedConstraint] = []
    for rule in constraints:
        if rule.heater_id not in priorities:
            raise ValueError(f"unknown heater in constraint: {rule.heater_id}")
        if rule.at.minute % slot_minutes:
            raise ValueError("constraint time must align with the configured slot")
        for boundary in boundaries:
            local = boundary.astimezone(zone)
            if local.weekday() in rule.weekdays and local.time().replace(tzinfo=None) == rule.at:
                result.append(
                    MaterializedConstraint(
                        rule.id,
                        rule.heater_id,
                        boundary,
                        rule.target_charge * 100,
                        priorities[rule.heater_id],
                    )
                )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.at,
                -item.priority,
                item.heater_id,
                item.requirement_id or 0,
            ),
        )
    )


__all__ = [
    "AutomaticPlan",
    "AutomaticPlanSlot",
    "CONVERGING",
    "DEGRADED",
    "DemandEstimate",
    "FEASIBLE",
    "FEASIBLE_LIMIT",
    "HeaterExplanation",
    "INVALID",
    "MaterializedConstraint",
    "NO_SOLUTION",
    "OPTIMAL",
    "PLANNING_HORIZON_HOURS",
    "PlanningCancelled",
    "PlanningInput",
    "PlanningViolation",
    "PlanningDeficit",
    "QUALITY_PHASE_BUDGET_SECONDS",
    "REPLAY_NUMERICAL_TOLERANCE",
    "SOLVER_NUMERICAL_TOLERANCE",
    "SOLVER_TIME_LIMIT_SECONDS",
    "VALID",
    "materialize_constraints",
    "resolve_planning_telemetry",
]
