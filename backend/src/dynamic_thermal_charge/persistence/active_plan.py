"""Durable storage for the plan currently executed by the controller."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Mapping

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine

from ..scheduler import ScheduleResult, ScheduleSlot
from . import ConfigStoreError, ForecastRef, PlanRef
from .engine import store_errors, transaction
from .mapping import from_utc, to_utc
from .schema import plan as plan_table, plan_allocation, plan_slot
from .url import StoreLocation


logger = logging.getLogger(__name__)


class SqlActivePlanRepository:
    """Persist and recover accepted controller plans from application storage.

    The existing plan tables already contain the interval assignments and the
    allocation totals. Empty intervals are reconstructed from the plan window,
    so a missing assignment is never mistaken for a missing plan.
    """

    def __init__(
        self,
        engine: Engine,
        installation_id: int,
        location: StoreLocation | None = None,
    ) -> None:
        self._engine = engine
        self._installation_id = installation_id
        self._location = location

    def save(
        self,
        plan: ScheduleResult,
        *,
        installation_revision: int = 0,
        forecast_ref: ForecastRef | None = None,
    ) -> PlanRef:
        if not plan.slots:
            raise ConfigStoreError("an accepted plan must contain at least one slot")
        window_start = plan.slots[0].start
        window_end = plan.slots[-1].end
        slot_minutes = round(
            (plan.slots[0].end - plan.slots[0].start).total_seconds() / 60
        )
        if slot_minutes <= 0:
            raise ConfigStoreError("an accepted plan must contain positive intervals")
        now = datetime.now(timezone.utc)
        with transaction(self._engine, self._location) as connection:
            plan_id = connection.execute(
                insert(plan_table).values(
                    installation_id=self._installation_id,
                    installation_revision=installation_revision,
                    forecast_id=None if forecast_ref is None else forecast_ref.id,
                    window_start=to_utc(window_start),
                    window_end=to_utc(window_end),
                    slot_minutes=slot_minutes,
                    created_at=to_utc(now),
                )
            ).inserted_primary_key[0]

            slot_rows = [
                {
                    "plan_id": plan_id,
                    "heater_id": heater_id,
                    "slot_start": to_utc(slot.start),
                    "slot_end": to_utc(slot.end),
                    "temperature_c": slot.temperature_c,
                    "temperature_interpolated": slot.temperature_interpolated,
                }
                for slot in plan.slots
                for heater_id in slot.heater_ids
            ]
            if slot_rows:
                connection.execute(insert(plan_slot), slot_rows)

            heater_ids = set(plan.allocated_minutes) | set(plan.unmet_minutes)
            allocation_rows = [
                {
                    "plan_id": plan_id,
                    "heater_id": heater_id,
                    "requested_minutes": int(
                        plan.allocated_minutes.get(heater_id, 0)
                        + plan.unmet_minutes.get(heater_id, 0)
                    ),
                    "allocated_minutes": int(plan.allocated_minutes.get(heater_id, 0)),
                    "unmet_minutes": int(plan.unmet_minutes.get(heater_id, 0)),
                }
                for heater_id in sorted(heater_ids)
            ]
            if allocation_rows:
                connection.execute(insert(plan_allocation), allocation_rows)
        return PlanRef(id=int(plan_id))

    def load(self) -> ScheduleResult | None:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                row = (
                    connection.execute(
                        select(plan_table)
                        .where(plan_table.c.installation_id == self._installation_id)
                        .order_by(plan_table.c.created_at.desc(), plan_table.c.id.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    return None
                slot_rows = (
                    connection.execute(
                        select(plan_slot)
                        .where(plan_slot.c.plan_id == row["id"])
                        .order_by(plan_slot.c.slot_start, plan_slot.c.heater_id)
                    )
                    .mappings()
                    .all()
                )
                allocation_rows = (
                    connection.execute(
                        select(plan_allocation)
                        .where(plan_allocation.c.plan_id == row["id"])
                        .order_by(plan_allocation.c.heater_id)
                    )
                    .mappings()
                    .all()
                )

        try:
            return _schedule_from_rows(row, slot_rows, allocation_rows)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.error("Ignoring invalid active charge plan in the database: %s", exc)
            return None


def _schedule_from_rows(
    plan_row: Mapping[str, Any],
    slot_rows: list[Mapping[str, Any]],
    allocation_rows: list[Mapping[str, Any]],
) -> ScheduleResult:
    start = from_utc(plan_row["window_start"])
    end = from_utc(plan_row["window_end"])
    assert start is not None and end is not None
    slot_minutes = int(plan_row["slot_minutes"])
    slot_seconds = slot_minutes * 60
    total_seconds = (end - start).total_seconds()
    if slot_minutes <= 0 or total_seconds <= 0 or total_seconds % slot_seconds:
        raise ValueError("the persisted plan window is not aligned to its slot size")

    by_start: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for row in slot_rows:
        row_start = from_utc(row["slot_start"])
        if row_start is None:
            raise ValueError("a persisted plan slot has no start")
        by_start[row_start].append(row)

    slots: list[ScheduleSlot] = []
    for index in range(int(total_seconds // slot_seconds)):
        slot_start = start + timedelta(seconds=index * slot_seconds)
        slot_end = slot_start + timedelta(seconds=slot_seconds)
        rows = by_start.pop(slot_start, [])
        heater_ids = tuple(str(row["heater_id"]) for row in rows)
        for row in rows:
            if from_utc(row["slot_end"]) != slot_end:
                raise ValueError("a persisted plan slot has an invalid end")
        slots.append(
            ScheduleSlot(
                start=slot_start,
                end=slot_end,
                heater_ids=heater_ids,
                total_power_w=0,
                temperature_c=(
                    None if not rows else rows[0].get("temperature_c")
                ),
                temperature_interpolated=bool(
                    rows and any(row.get("temperature_interpolated", False) for row in rows)
                ),
            )
        )
    if by_start:
        raise ValueError("a persisted plan slot falls outside its plan window")

    return ScheduleResult(
        slots=tuple(slots),
        allocated_minutes={
            str(row["heater_id"]): int(row["allocated_minutes"])
            for row in allocation_rows
        },
        unmet_minutes={
            str(row["heater_id"]): int(row["unmet_minutes"])
            for row in allocation_rows
            if int(row["unmet_minutes"])
        },
    )


__all__ = ["SqlActivePlanRepository"]
