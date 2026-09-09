"""Decide whether the active plan still serves the measured conditions.

The plan is built assuming the AEMET forecast comes true.  When the outdoor
temperature turns out lower, the room cools more than projected and the
accumulator reaches its target window without enough stored energy, but the
periodic cadence would not notice until its next turn.

The verdict is not a temperature deviation against a threshold: the remaining
intervals of the plan are reprojected with the measured indoor temperature and
state of charge, keeping the plan's own charge decisions, and what triggers a
recalculation is a comfort deficit the plan did not foresee.  A two-degree
deviation that compromises no target does not trigger; a small one that does,
triggers.  The mirror case also triggers: conditions kinder than forecast leave
surplus stored energy, which means charge the plan no longer needs.

The reprojection uses the room-energy step function, not the MILP, so the check
costs no solver budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .charge_planning import RoomEnergyDemandEstimator, RoomEnergyInterval
from .models import ChargeTelemetry, Heater, TemperatureTarget
from .scheduler import _floor_to_wall_boundary
from .weather import HourlyForecastPoint


PROJECTED_DEFICIT = "projected_deficit"
SURPLUS_STORED_ENERGY = "surplus_stored_energy"


@dataclass(frozen=True)
class DeviationVerdict:
    """Why the plan should be recalculated now, or why it should not."""

    replan: bool
    reason: str | None = None
    heater_id: str | None = None
    planned_value: float | None = None
    projected_value: float | None = None
    detail: str | None = None

    def audit_details(self) -> dict[str, Any]:
        return {
            "deviation_reason": self.reason,
            "heater_id": self.heater_id,
            "planned_value": self.planned_value,
            "projected_value": self.projected_value,
            "detail": self.detail,
        }


NO_DEVIATION = DeviationVerdict(replan=False)


class SlotBoundaryGate:
    """Let one evaluation through per slot boundary.

    The plan projects values at slot edges, so evaluating more often than that
    repeats the same verdict, and the solver budget is up to two minutes: one
    early recalculation per slot is the useful rate.
    """

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


def _remaining_slots(
    slots: Sequence[Mapping[str, Any]], at: datetime
) -> list[Mapping[str, Any]]:
    """The intervals still ahead: a slot already under way cannot be replanned."""
    moment = _instant(at)
    return [
        slot
        for slot in slots
        if isinstance(slot.get("start"), datetime)
        and _instant(slot["start"]) >= moment
    ]


def _worst_planned_shortfall(
    slots: Sequence[Mapping[str, Any]], heater_id: str
) -> float:
    worst = 0.0
    for slot in slots:
        for field in ("temperature_shortfall_c", "temperature_shortfall_start_c"):
            value = (slot.get(field) or {}).get(heater_id)
            if value is not None:
                worst = max(worst, float(value))
    return worst


def _planned_final_stored_kwh(
    slots: Sequence[Mapping[str, Any]], heater_id: str
) -> float | None:
    for slot in reversed(slots):
        value = (slot.get("stored_energy_next_kwh") or {}).get(heater_id)
        if value is not None:
            return float(value)
    return None


def _charge_decisions(
    slots: Sequence[Mapping[str, Any]], heater_id: str
) -> tuple[bool, ...]:
    return tuple(
        heater_id in tuple(slot.get("heater_ids") or ()) for slot in slots
    )


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
    """Reproject the remaining plan and say whether it still serves.

    A heater without usable telemetry is not reprojected and never triggers on
    its own; the freshness rules of the planner already cover that case.
    """
    if plan is None or plan.get("status") == "INVALID":
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
    charge_on = {heater.id: _charge_decisions(slots, heater.id) for heater in checkable}
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
    except ValueError:
        # Missing forecast coverage or telemetry is not a deviation: the normal
        # freshness and coverage rules decide what happens with those.
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
        projected_shortfall = max(
            max(item.temperature_shortfall_c, item.temperature_shortfall_start_c)
            for item in projected
        )
        planned_shortfall = _worst_planned_shortfall(slots, heater.id)
        excess = projected_shortfall - planned_shortfall
        if excess > shortfall_tolerance_c and excess > worst_excess:
            worst_excess = excess
            worst = DeviationVerdict(
                replan=True,
                reason=PROJECTED_DEFICIT,
                heater_id=heater.id,
                planned_value=round(planned_shortfall, 6),
                projected_value=round(projected_shortfall, 6),
                detail=(
                    "La reproyección con la telemetría medida revela un déficit "
                    f"de {projected_shortfall:.2f} °C donde el plan preveía "
                    f"{planned_shortfall:.2f} °C."
                ),
            )
    if worst is not None:
        return worst

    # No comfort is at risk, so surplus stored energy means the plan is charging
    # more than these conditions need.
    for heater in checkable:
        projected = by_heater.get(heater.id, [])
        planned_final = _planned_final_stored_kwh(slots, heater.id)
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
