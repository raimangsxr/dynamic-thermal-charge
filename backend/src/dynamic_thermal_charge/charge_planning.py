"""Pure deterministic automatic charge planning.

The planner deliberately knows nothing about SQLAlchemy, MQTT, HTTP or output
drivers.  A plan is a value object and can therefore be previewed, persisted and
replayed with exactly the same inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from .models import ChargeConstraint, ChargeTelemetry, Heater
from .weather import HourlyForecastPoint


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


@dataclass(frozen=True)
class PlanningDeficit:
    heater_id: str
    target_charge_percent: float
    projected_charge_percent: float
    deficit_percent: float
    reason: str


@dataclass(frozen=True)
class AutomaticPlan:
    horizon_start: datetime
    horizon_end: datetime
    slot_minutes: int
    slots: tuple[AutomaticPlanSlot, ...]
    deficits: tuple[PlanningDeficit, ...]
    status: str
    score: tuple[float, ...]
    input_token: str


@dataclass(frozen=True)
class PlanningInput:
    heaters: tuple[Heater, ...]
    telemetry: Mapping[str, ChargeTelemetry]
    constraints: tuple[ChargeConstraint, ...]
    forecast: Sequence[HourlyForecastPoint]
    horizon_start: datetime
    horizon_hours: int = 48
    slot_minutes: int = 30
    max_total_power_w: int = 5200
    timezone_name: str = "UTC"
    exploration_limit: int = 100_000


class DeterministicChargeOptimizer:
    """Schedule latest possible compatible slots, with deterministic fallback."""

    def build(self, request: PlanningInput) -> AutomaticPlan:
        _validate_input(request)
        horizon_start = _align(request.horizon_start, request.slot_minutes)
        horizon_end = horizon_start + timedelta(hours=request.horizon_hours)
        count = math.ceil((horizon_end - horizon_start).total_seconds() / 60 / request.slot_minutes)
        slots = [
            horizon_start + timedelta(minutes=index * request.slot_minutes)
            for index in range(count)
        ]
        enabled = tuple(
            heater for heater in request.heaters
            if heater.enabled and _telemetry_usable(request.telemetry.get(heater.id))
        )
        telemetry_health = {
            heater.id: request.telemetry.get(heater.id) for heater in request.heaters
        }
        required = {heater.id: _required_percent(heater, request, slots, horizon_end) for heater in enabled}
        current = {
            heater.id: float(request.telemetry[heater.id].stored_charge_percent or 0.0)
            for heater in enabled
        }
        selected: dict[int, list[str]] = {index: [] for index in range(count)}
        explored = 0
        # Work backwards: later charging loses less stored heat and is the final
        # tie-breaker required by the design.  The capacity check is per slot.
        for heater in sorted(enabled, key=lambda item: (-item.priority, item.id)):
            target = required[heater.id]
            charge_needed = max(0.0, target - current[heater.id])
            rate = 100.0 * request.slot_minutes / heater.full_charge_minutes
            for index in reversed(range(count)):
                if charge_needed <= 1e-9:
                    break
                if not _constraint_allows(heater.id, slots[index], request.constraints, request.timezone_name):
                    continue
                if sum(next(h.power_w for h in enabled if h.id == hid) for hid in selected[index]) + heater.power_w > request.max_total_power_w:
                    continue
                selected[index].append(heater.id)
                charge_needed -= rate
                explored += 1
                if explored > request.exploration_limit:
                    break
            if explored > request.exploration_limit:
                break

        plan_slots: list[AutomaticPlanSlot] = []
        projected = {heater.id: current[heater.id] for heater in enabled}
        projected_indoor = {
            heater.id: float(request.telemetry[heater.id].temperature_c or 0.0)
            for heater in enabled
        }
        deficits: list[PlanningDeficit] = []
        for index, start in enumerate(slots):
            end = start + timedelta(minutes=request.slot_minutes)
            outdoor = _weather_at(start, request.forecast)
            for heater in enabled:
                projected[heater.id], projected_indoor[heater.id] = _project_state(
                    heater,
                    projected[heater.id],
                    projected_indoor[heater.id],
                    float(request.telemetry[heater.id].target_temperature_c or 0.0),
                    start,
                    end,
                    outdoor,
                    heater.id in selected[index],
                )
            plan_slots.append(AutomaticPlanSlot(
                start=start, end=end, heater_ids=tuple(sorted(selected[index])),
                power_w=sum(next(h.power_w for h in enabled if h.id == hid) for hid in selected[index]),
                stored_charge_percent={key: round(value, 3) for key, value in projected.items()},
                required_charge_percent={key: round(value, 3) for key, value in required.items()},
                outdoor_temperature_c=outdoor,
                indoor_temperature_c={key: round(value, 3) for key, value in projected_indoor.items()},
            ))

        for heater in request.heaters:
            telemetry = telemetry_health.get(heater.id)
            if not _telemetry_usable(telemetry):
                deficits.append(PlanningDeficit(heater.id, 0.0, 0.0, 0.0, "telemetry_stale"))
                continue
            target = required.get(heater.id, 0.0)
            final = projected.get(heater.id, float(telemetry.stored_charge_percent or 0.0))
            if final + 1e-6 < target:
                deficits.append(PlanningDeficit(heater.id, target, final, round(target - final, 3), "power_limit_or_capacity"))
        status = "best_effort" if explored > request.exploration_limit else ("deficit" if deficits else "feasible")
        score = (float(sum(item.deficit_percent for item in deficits)), float(sum(len(slot.heater_ids) for slot in plan_slots)), float(sum(slot.power_w for slot in plan_slots)), float(sum(len(slot.heater_ids) * (count - index) for index, slot in enumerate(plan_slots))))
        return AutomaticPlan(
            horizon_start=horizon_start, horizon_end=horizon_end,
            slot_minutes=request.slot_minutes, slots=tuple(plan_slots),
            deficits=tuple(deficits), status=status, score=score,
            input_token=input_token(request),
        )


def input_token(request: PlanningInput) -> str:
    payload = {
        "heaters": [(h.id, h.power_w, h.full_charge_minutes, h.enabled, h.reserve_percent) for h in request.heaters],
        "telemetry": {key: _json_telemetry(value) for key, value in sorted(request.telemetry.items())},
        "constraints": [(c.id, c.heater_id, c.target_charge, c.at.isoformat(), c.weekdays) for c in request.constraints],
        "forecast": [(point.timestamp.isoformat(), point.temperature_c, point.interpolated) for point in request.forecast],
        "horizon_start": request.horizon_start.astimezone(timezone.utc).isoformat(),
        "horizon_hours": request.horizon_hours, "slot_minutes": request.slot_minutes,
        "max_total_power_w": request.max_total_power_w, "timezone_name": request.timezone_name,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _json_telemetry(value: ChargeTelemetry) -> dict[str, object]:
    return {key: (item.isoformat() if isinstance(item, datetime) else item) for key, item in value.__dict__.items()}


def _validate_input(request: PlanningInput) -> None:
    if request.horizon_start.tzinfo is None:
        raise ValueError("horizon_start requires a timezone")
    if request.slot_minutes not in (5, 10, 15, 20, 30, 60):
        raise ValueError("slot_minutes must be one of 5, 10, 15, 20, 30 or 60")
    if request.horizon_hours <= 0 or request.max_total_power_w <= 0:
        raise ValueError("horizon_hours and max_total_power_w must be positive")
    ZoneInfo(request.timezone_name)


def _align(value: datetime, minutes: int) -> datetime:
    return value.replace(second=0, microsecond=0, minute=(value.minute // minutes) * minutes)


def _telemetry_usable(value: ChargeTelemetry | None) -> bool:
    return value is not None and all(
        item is not None
        for item in (
            value.temperature_c,
            value.target_temperature_c,
            value.stored_charge_percent,
        )
    )


def _required_percent(heater: Heater, request: PlanningInput, slots: Sequence[datetime], horizon_end: datetime) -> float:
    relevant = [constraint.target_charge * 100.0 for constraint in request.constraints if constraint.heater_id == heater.id and _constraint_in_horizon(constraint, slots, request.timezone_name)]
    target = max(relevant, default=float(heater.target_charge) * 100.0)
    return min(100.0, target + heater.reserve_percent)


def _constraint_in_horizon(constraint: ChargeConstraint, slots: Sequence[datetime], timezone_name: str) -> bool:
    zone = ZoneInfo(timezone_name)
    return any(slot.astimezone(zone).weekday() in constraint.weekdays and slot.astimezone(zone).time().replace(second=0, microsecond=0) >= constraint.at for slot in slots)


def _constraint_allows(heater_id: str, slot: datetime, constraints: Sequence[ChargeConstraint], timezone_name: str) -> bool:
    # Constraints are result deadlines, not operating windows. Charging is valid
    # at every slot; deadlines are represented by the required result, not by a
    # forbidden operating window.
    return True


def _weather_at(at: datetime, points: Sequence[HourlyForecastPoint]) -> float | None:
    matching = [point.temperature_c for point in points if point.timestamp <= at < point.timestamp + timedelta(hours=1)]
    return sum(matching) / len(matching) if matching else None


def _project_state(
    heater: Heater,
    value: float,
    indoor: float,
    target: float,
    start: datetime,
    end: datetime,
    outdoor: float | None,
    charging: bool,
) -> tuple[float, float]:
    profile = heater.thermal
    hours = (end - start).total_seconds() / 3600
    if profile is not None and outdoor is not None:
        # First project the room towards the forecast exterior temperature.
        indoor += (outdoor - indoor) * profile.outdoor_loss_per_hour * hours
        delta = max(target - indoor, 0.0)
        design_delta = max(target - profile.design_outdoor_temperature_c, 0.1)
        value *= max(0.0, 1.0 - profile.thermal_loss_c_per_hour * hours * delta / design_delta)
    if charging:
        value += 100.0 * hours * 60 / heater.full_charge_minutes
        if profile is not None:
            indoor += profile.emission_c_per_hour * hours
    return min(100.0, max(0.0, value)), indoor


__all__ = ["AutomaticPlan", "AutomaticPlanSlot", "DeterministicChargeOptimizer", "PlanningDeficit", "PlanningInput", "input_token"]
