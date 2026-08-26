"""The audit trail, and the retention policy that bounds it.

**Hard rule**: no method here may propagate an exception. A write failure is
logged as an error and the call returns an empty result. Observability must never
be able to stop the control loop (FR-019, constitution principle IV).

That is the exact opposite of ``ConfigRepository``, which does raise. The
asymmetry is deliberate: without configuration there is no way to decide which
relay to close; without an audit record, there is.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from . import ForecastRef, PlanRef, PruneReport
from .mapping import to_utc
from .schema import (
    RETAINED_TABLES,
    forecast as forecast_table,
    output_transition,
    plan as plan_table,
    plan_allocation,
    plan_slot,
)
from .url import StoreLocation


logger = logging.getLogger(__name__)


class SqlHistoryRecorder:
    def __init__(
        self,
        engine: Engine,
        installation_id: int,
        location: StoreLocation | None = None,
    ) -> None:
        self._engine = engine
        self._installation_id = installation_id
        self._location = location

    # ------------------------------------------------------------- recording

    def record_forecast(self, forecast: Any) -> ForecastRef | None:
        try:
            with self._engine.begin() as connection:
                forecast_id = connection.execute(
                    insert(forecast_table).values(
                        installation_id=self._installation_id,
                        forecast_date=forecast.date,
                        average_temperature_c=forecast.average_temperature_c,
                        minimum_temperature_c=forecast.minimum_temperature_c,
                        maximum_temperature_c=forecast.maximum_temperature_c,
                        source=_forecast_source(forecast),
                        municipality=getattr(forecast, "location", None),
                        retrieved_at=to_utc(_now_of(forecast)),
                    )
                ).inserted_primary_key[0]
            return ForecastRef(id=int(forecast_id))
        except Exception:
            logger.error(
                "Could not record the forecast used for planning; scheduling continues",
                exc_info=True,
            )
            return None

    def record_plan(
        self,
        plan: Any,
        forecast_ref: ForecastRef | None,
        installation_revision: int,
        requested_minutes: Mapping[str, int] | None = None,
    ) -> PlanRef | None:
        try:
            slots: Sequence[Any] = plan.slots
            if not slots:
                logger.debug("Empty plan; nothing to record")
                return None
            window_start = slots[0].start
            window_end = slots[-1].end
            slot_minutes = round((slots[0].end - slots[0].start).total_seconds() / 60)
            with self._engine.begin() as connection:
                plan_id = connection.execute(
                    insert(plan_table).values(
                        installation_id=self._installation_id,
                        installation_revision=installation_revision,
                        forecast_id=None if forecast_ref is None else forecast_ref.id,
                        window_start=to_utc(window_start),
                        window_end=to_utc(window_end),
                        slot_minutes=slot_minutes,
                        created_at=to_utc(window_start),
                    )
                ).inserted_primary_key[0]

                slot_rows = [
                    {
                        "plan_id": plan_id,
                        "heater_id": heater_id,
                        "slot_start": to_utc(slot.start),
                        "slot_end": to_utc(slot.end),
                    }
                    for slot in slots
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
                            (requested_minutes or {}).get(
                                heater_id,
                                plan.allocated_minutes.get(heater_id, 0)
                                + plan.unmet_minutes.get(heater_id, 0),
                            )
                        ),
                        "allocated_minutes": int(
                            plan.allocated_minutes.get(heater_id, 0)
                        ),
                        "unmet_minutes": int(plan.unmet_minutes.get(heater_id, 0)),
                    }
                    for heater_id in sorted(heater_ids)
                ]
                if allocation_rows:
                    connection.execute(insert(plan_allocation), allocation_rows)
            return PlanRef(id=int(plan_id))
        except Exception:
            logger.error(
                "Could not record the generated plan; scheduling continues",
                exc_info=True,
            )
            return None

    def record_transition(
        self,
        heater_id: str,
        state: bool,
        occurred_at: datetime,
        plan_ref: PlanRef | None = None,
    ) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(output_transition).values(
                        installation_id=self._installation_id,
                        heater_id=heater_id,
                        state=state,
                        occurred_at=to_utc(occurred_at),
                        plan_id=None if plan_ref is None else plan_ref.id,
                    )
                )
        except Exception:
            logger.error(
                "Could not record the output transition %s=%s; switching continues",
                heater_id,
                state,
                exc_info=True,
            )

    # ------------------------------------------------------------- retention

    def prune(self, now: datetime, retention_days: int | None) -> PruneReport:
        """Delete history older than the retention limit.

        Never touches the installation configuration, and never touches a plan
        that is still live: any plan whose ``window_end`` is in the future is
        protected, including plans calculated for a window that has not started
        yet (FR-023, data-model.md "Identificación del plan activo").

        ``config_change`` is deliberately excluded from retention: it is the only
        trace of who changed the configuration, and it is tens of rows a year.
        """
        if retention_days is None:
            logger.debug("Retention is unlimited; nothing pruned")
            return PruneReport(deleted={})
        try:
            cutoff = to_utc(now) - timedelta(days=retention_days)
            now_utc = to_utc(now)
            deleted: dict[str, int] = {}
            with self._engine.begin() as connection:
                for table, timestamp_column in RETAINED_TABLES:
                    condition = table.c[timestamp_column] < cutoff
                    if table is plan_table:
                        # Live and future plans survive regardless of age.
                        condition = condition & (plan_table.c.window_end <= now_utc)
                    if table is forecast_table:
                        # Do not orphan a forecast a surviving plan still cites.
                        condition = condition & ~forecast_table.c.id.in_(
                            select(plan_table.c.forecast_id).where(
                                plan_table.c.forecast_id.is_not(None)
                            )
                        )
                    count = connection.execute(delete(table).where(condition)).rowcount
                    if count:
                        deleted[table.name] = int(count)
            report = PruneReport(deleted=deleted)
            if report.total:
                logger.info(
                    "Pruned %d history rows older than %d days: %s",
                    report.total,
                    retention_days,
                    deleted,
                )
            else:
                logger.debug("Nothing older than %d days to prune", retention_days)
            return report
        except Exception:
            logger.error(
                "Could not prune history; scheduling continues", exc_info=True
            )
            return PruneReport(deleted={})

    # ------------------------------------------------------------------ query

    def row_counts(self) -> dict[str, int]:
        """Row counts per history table. Used by the tests and by diagnostics."""
        tables = (
            forecast_table,
            plan_table,
            plan_slot,
            plan_allocation,
            output_transition,
        )
        with self._engine.connect() as connection:
            return {
                table.name: int(
                    connection.execute(select(func.count()).select_from(table)).scalar()
                    or 0
                )
                for table in tables
            }


def _forecast_source(forecast: Any) -> str:
    """Map the provider's source onto the audited one.

    A simulated forecast reached through the fallback provider is recorded as
    ``fallback``, so the history answers "did the real provider work that night"
    (FR-017).
    """
    source = getattr(forecast, "source", "simulated")
    if getattr(forecast, "from_fallback", False):
        return "fallback"
    return source


def _now_of(forecast: Any) -> datetime:
    retrieved = getattr(forecast, "retrieved_at", None)
    if retrieved is not None:
        return retrieved
    from datetime import timezone

    return datetime.now(timezone.utc)


__all__ = ["SqlHistoryRecorder"]
