"""Check whether the active room-energy plan still serves live conditions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .charge_planning import (
    CONVERGING,
    DEGRADED,
    INVALID,
    VALID,
    RoomEnergyDemandEstimator,
    RoomEnergyInterval,
)
from .models import ChargeTelemetry, Heater, TemperatureTarget
from .scheduler import _floor_to_wall_boundary
from .weather import HourlyForecastPoint


PROJECTED_DEFICIT = "projected_deficit"
SURPLUS_STORED_ENERGY = "surplus_stored_energy"


@dataclass(frozen=True)
class DeviationVerdict:
    """Why the active plan should be recalculated, or why it should not."""

    replan: bool
    reason: str | None = None
    heater_id: str | None = None
    planned_value: float | None = None
    projected_value: float | None = None
    at: datetime | None = None
    detail: str | None = None

    def audit_details(self) -> dict[str, Any]:
        return {
            "deviation_reason": self.reason,
            "heater_id": self.heater_id,
            "planned_value": self.planned_value,
            "projected_value": self.projected_value,
            "deviation_at": self.at,
            "detail": self.detail,
        }


NO_DEVIATION = DeviationVerdict(replan=False)


class SlotBoundaryGate:
    """Allow one deviation evaluation per wall-clock slot boundary."""

    def __init__(self) -> None:
        self._boundary: datetime | None = None

    def enter(self, at: datetime, slot_minutes: int) -> bool:
        boundary = _floor_to_wall_boundary(at, slot_minutes)
        if self._boundary == boundary:
            return False
        self._boundary = boundary
        return True


def _instant(value: datetime) -> datetime:
    return value if value.tzinfo is None else value.astimezone(timezone.utc)


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _time_key(value: object) -> datetime | None:
    parsed = _datetime(value)
    return None if parsed is None else _instant(parsed)


def _remaining_slots(
    slots: Sequence[Mapping[str, Any]], at: datetime
) -> list[Mapping[str, Any]]:
    """Return intervals whose start has not passed yet."""
    moment = _instant(at)
    return [
        slot
        for slot in slots
        if isinstance(slot.get("start"), datetime)
        and _instant(slot["start"]) >= moment
    ]


def _planned_shortfall_by_boundary(
    plan: Mapping[str, Any],
    slots: Sequence[Mapping[str, Any]],
    heater_id: str,
) -> dict[datetime, float]:
    """Read planned border values, including the persisted physical series."""
    remaining_starts = {
        key for slot in slots if (key := _time_key(slot.get("start"))) is not None
    }
    observations: dict[datetime, float] = {}

    def record(at: object, value: object) -> None:
        key = _time_key(at)
        if key is not None and value is not None:
            observations[key] = max(observations.get(key, 0.0), float(value))

    for slot in slots:
        record(
            slot.get("start"),
            (slot.get("temperature_shortfall_start_c") or {}).get(heater_id),
        )
        record(
            slot.get("end"),
            (slot.get("temperature_shortfall_c") or {}).get(heater_id),
        )

    # ``automatic_plan_slot`` predates explicit boundary fields. The complete
    # physical intervals are nevertheless durable in ``inputs_json.demand``;
    # use them so a plan read after commit/restart compares the same evidence
    # that the optimiser produced.
    for interval in plan.get("demand") or ():
        if not isinstance(interval, Mapping) or interval.get("heater_id") != heater_id:
            continue
        if _time_key(interval.get("start")) not in remaining_starts:
            continue
        record(interval.get("start"), interval.get("temperature_shortfall_start_c"))
        record(interval.get("end"), interval.get("temperature_shortfall_c"))
    return observations


def _planned_final_stored_kwh(
    plan: Mapping[str, Any],
    slots: Sequence[Mapping[str, Any]],
    heater_id: str,
) -> float | None:
    remaining_starts = {
        key for slot in slots if (key := _time_key(slot.get("start"))) is not None
    }
    physical = [
        interval
        for interval in (plan.get("demand") or ())
        if isinstance(interval, Mapping)
        and interval.get("heater_id") == heater_id
        and _time_key(interval.get("start")) in remaining_starts
        and interval.get("stored_energy_next_kwh") is not None
    ]
    if physical:
        last = max(physical, key=lambda item: _time_key(item.get("start")) or datetime.min)
        return float(last["stored_energy_next_kwh"])
    for slot in reversed(slots):
        value = (slot.get("stored_energy_next_kwh") or {}).get(heater_id)
        if value is not None:
            return float(value)
    return None


def _charge_decisions(
    slots: Sequence[Mapping[str, Any]], heater_id: str
) -> tuple[bool, ...]:
    return tuple(heater_id in tuple(slot.get("heater_ids") or ()) for slot in slots)


def evaluate_plan_deviation(
    plan: Mapping[str, Any] | None,
    *,
    heaters: Sequence[Heater],
    telemetry: Mapping[str, ChargeTelemetry],
    forecast: Sequence[HourlyForecastPoint],
    targets: Mapping[str, Sequence[TemperatureTarget]],
    at: datetime,
    slot_minutes: int,
    timezone_name: str = "UTC",
    shortfall_tolerance_c: float = 0.1,
    surplus_soc_percent: float = 5.0,
) -> DeviationVerdict:
    """Reproject the remaining active plan with the measured state.

    Missing inputs belong to the normal planner validation path, not this
    early-replan signal. The check therefore remains conservative and returns
    no deviation when it cannot make a complete comparison.
    """
    status = str(plan.get("status", "")).upper() if plan is not None else ""
    if plan is None or status == INVALID:
        return NO_DEVIATION
    if status not in {
        VALID,
        CONVERGING,
        "FEASIBLE",
        DEGRADED,
    }:
        return NO_DEVIATION
    slots = _remaining_slots(
        [item for item in (plan.get("slots") or ()) if isinstance(item, Mapping)], at
    )
    if not slots:
        return NO_DEVIATION
    checkable = tuple(
        heater
        for heater in heaters
        if heater.enabled and heater.id in telemetry and heater.id in targets
    )
    if not checkable:
        return NO_DEVIATION

    starts = tuple(slot["start"] for slot in slots)
    charge_on = {
        heater.id: _charge_decisions(slots, heater.id) for heater in checkable
    }
    try:
        intervals = RoomEnergyDemandEstimator().estimate(
            checkable,
            telemetry,
            forecast,
            starts,
            slot_minutes,
            timezone_name=timezone_name,
            targets={heater.id: tuple(targets[heater.id]) for heater in checkable},
            charge_on=charge_on,
        )
    except (TypeError, ValueError):
        return NO_DEVIATION

    by_heater: dict[str, list[RoomEnergyInterval]] = {}
    for interval in intervals:
        by_heater.setdefault(interval.heater_id, []).append(interval)

    worst: DeviationVerdict | None = None
    worst_excess = 0.0
    for heater in checkable:
        projected = by_heater.get(heater.id, [])
        if not projected:
            continue
        planned = _planned_shortfall_by_boundary(plan, slots, heater.id)
        projected_by_boundary: dict[datetime, tuple[datetime, float]] = {}
        for interval in projected:
            for boundary, shortfall in (
                (interval.start, interval.temperature_shortfall_start_c),
                (interval.end, interval.temperature_shortfall_c),
            ):
                key = _instant(boundary)
                previous = projected_by_boundary.get(key)
                if previous is None or shortfall > previous[1]:
                    projected_by_boundary[key] = (boundary, shortfall)
        for key, (boundary, projected_shortfall) in projected_by_boundary.items():
            planned_shortfall = planned.get(key, 0.0)
            excess = projected_shortfall - planned_shortfall
            if excess > shortfall_tolerance_c and excess > worst_excess:
                worst_excess = excess
                worst = DeviationVerdict(
                    replan=True,
                    reason=PROJECTED_DEFICIT,
                    heater_id=heater.id,
                    planned_value=round(planned_shortfall, 6),
                    projected_value=round(projected_shortfall, 6),
                    at=boundary,
                    detail=(
                        "La reproyección con la telemetría medida revela en "
                        f"{boundary.isoformat()} un déficit de "
                        f"{projected_shortfall:.2f} °C donde el plan preveía "
                        f"{planned_shortfall:.2f} °C."
                    ),
                )
    if worst is not None:
        return worst

    # If comfort remains safe, a materially larger remaining store means the
    # original plan is charging more than the measured conditions require.
    for heater in checkable:
        projected = by_heater.get(heater.id, [])
        planned_final = _planned_final_stored_kwh(plan, slots, heater.id)
        if not projected or planned_final is None or heater.capacity_kwh <= 0:
            continue
        projected_final = projected[-1].stored_energy_next_kwh
        surplus = (projected_final - planned_final) / heater.capacity_kwh * 100
        if surplus > surplus_soc_percent:
            return DeviationVerdict(
                replan=True,
                reason=SURPLUS_STORED_ENERGY,
                heater_id=heater.id,
                planned_value=round(planned_final, 6),
                projected_value=round(projected_final, 6),
                detail=(
                    f"La reproyección deja {surplus:.1f} puntos de SOC por encima "
                    "de lo previsto, así que parte de la carga ya no es necesaria."
                ),
            )
    return NO_DEVIATION


__all__ = [
    "NO_DEVIATION",
    "SlotBoundaryGate",
    "PROJECTED_DEFICIT",
    "SURPLUS_STORED_ENERGY",
    "DeviationVerdict",
    "evaluate_plan_deviation",
]
