"""The audit trail, and the retention policy that bounds it.

**Hard rule**: no method here may propagate an exception. A write failure is
logged as an error and the call returns an empty result. Observability must never
be able to stop the control loop (FR-019, constitution principle IV).

That is the exact opposite of ``ConfigRepository``, which does raise. The
asymmetry is deliberate: without configuration there is no way to decide which
relay to close; without an audit record, there is.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.engine import Engine

from . import ForecastRef, HistoryPage, PlanRef, PruneReport
from .mapping import from_utc, to_utc
from .schema import (
    RETAINED_TABLES,
    forecast as forecast_table,
    forecast_hour,
    output_transition,
    plan as plan_table,
    plan_allocation,
    plan_slot,
    relay_test_control,
    relay_test_event,
    relay_test_output,
    relay_test_session,
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
                hourly_rows = [
                    {
                        "forecast_id": forecast_id,
                        "observed_at": to_utc(point.timestamp),
                        "temperature_c": float(point.temperature_c),
                        "interpolated": bool(getattr(point, "interpolated", False)),
                    }
                    for point in getattr(forecast, "hourly_points", ())
                ]
                if hourly_rows:
                    connection.execute(insert(forecast_hour), hourly_rows)
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
                        "temperature_c": getattr(slot, "temperature_c", None),
                        "temperature_interpolated": bool(
                            getattr(slot, "temperature_interpolated", False)
                        ),
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
                # Relay-test terminal state is retained with the audit trail.
                # Never remove a live singleton nor the terminal evidence that
                # explains an active latch.
                protected = select(relay_test_control.c.session_id).where(
                    relay_test_control.c.installation_id == self._installation_id,
                    relay_test_control.c.session_id.is_not(None),
                ).union(select(relay_test_control.c.fault_session_id).where(
                    relay_test_control.c.installation_id == self._installation_id,
                    relay_test_control.c.fault_latched.is_(True),
                    relay_test_control.c.fault_session_id.is_not(None),
                ))
                terminal = and_(
                    relay_test_session.c.installation_id == self._installation_id,
                    relay_test_session.c.ended_at.is_not(None),
                    relay_test_session.c.ended_at < cutoff,
                    ~relay_test_session.c.id.in_(protected),
                )
                terminal_ids = select(relay_test_session.c.id).where(terminal)
                count = connection.execute(delete(relay_test_event).where(and_(relay_test_event.c.installation_id == self._installation_id, or_(relay_test_event.c.occurred_at < cutoff, relay_test_event.c.session_id.in_(terminal_ids))))).rowcount
                if count:
                    deleted[relay_test_event.name] = int(count)
                count = connection.execute(delete(relay_test_session).where(terminal)).rowcount
                if count:
                    deleted[relay_test_session.name] = int(count)
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
            forecast_hour,
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


# --------------------------------------------------------------------------- #
# Paged reads. The previous phase only ever wrote history and pruned it; the API
# needs to read it back without ever returning the whole thing.
#
# The cursor encodes the (instant, id) pair of the last item returned, not an
# offset. History receives inserts while a client pages through it: with an
# offset, a plan inserted between two pages would shift everything and the client
# would see a repeated item or skip one. The id breaks ties between two records
# sharing the same instant, which happens whenever several transitions land in
# the same second.
# --------------------------------------------------------------------------- #

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class CursorError(ValueError):
    """The continuation cursor is unreadable or was tampered with."""


def encode_cursor(instant: datetime, row_id: int) -> str:
    payload = f"{to_utc(instant).isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Returns an aware UTC instant: the temporal boundary refuses naive ones."""
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        raw_instant, raw_id = payload.split("|")
        instant = datetime.fromisoformat(raw_instant)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return instant, int(raw_id)
    except Exception as exc:
        # Never silently ignored: falling back to the first page would look like
        # nothing happened while the client silently re-reads what it already had.
        raise CursorError(
            "the continuation cursor is unreadable; request the first page again "
            "without a cursor"
        ) from exc


def _page_size(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(int(limit), MAX_PAGE_SIZE))


class SqlHistoryReader:
    """Paged, filtered reads over the audit trail."""

    def __init__(
        self,
        engine: Engine,
        installation_id: int,
        location: StoreLocation | None = None,
    ) -> None:
        self._engine = engine
        self._installation_id = installation_id
        self._location = location

    def plans(self, since=None, until=None, limit=None, cursor=None) -> HistoryPage:
        return self._page(
            plan_table, plan_table.c.created_at, since, until, limit, cursor
        )

    def forecasts(self, since=None, until=None, limit=None, cursor=None) -> HistoryPage:
        return self._page(
            forecast_table,
            forecast_table.c.retrieved_at,
            since,
            until,
            limit,
            cursor,
        )

    def transitions(
        self, since=None, until=None, limit=None, cursor=None, heater_id=None
    ) -> HistoryPage:
        extra = None
        if heater_id is not None:
            # Resolved against the text column, so transitions of a heater that
            # has since been removed keep showing up.
            extra = output_transition.c.heater_id == heater_id
        return self._page(
            output_transition,
            output_transition.c.occurred_at,
            since,
            until,
            limit,
            cursor,
            extra=extra,
        )

    def relay_tests(
        self, since=None, until=None, limit=None, cursor=None, session_id=None, heater_id=None
    ) -> HistoryPage:
        extra = None
        if session_id is not None:
            extra = relay_test_event.c.session_id == session_id
        if heater_id is not None:
            condition = relay_test_event.c.heater_id == heater_id
            extra = condition if extra is None else extra & condition
        return self._page(relay_test_event, relay_test_event.c.occurred_at, since, until, limit, cursor, extra=extra)

    def _page(
        self, table, timestamp, since, until, limit, cursor, extra=None
    ) -> HistoryPage:
        size = _page_size(limit)
        condition = table.c.installation_id == self._installation_id
        if since is not None:
            condition = condition & (timestamp >= to_utc(since))
        if until is not None:
            condition = condition & (timestamp <= to_utc(until))
        if extra is not None:
            condition = condition & extra
        if cursor is not None:
            cursor_instant, cursor_id = decode_cursor(cursor)
            cursor_utc = to_utc(cursor_instant)
            condition = condition & (
                (timestamp < cursor_utc)
                | ((timestamp == cursor_utc) & (table.c.id < cursor_id))
            )

        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(table)
                        .where(condition)
                        # One extra row is fetched to learn whether there is more,
                        # without a second COUNT query.
                        .order_by(timestamp.desc(), table.c.id.desc())
                        .limit(size + 1)
                    )
                    .mappings()
                    .all()
                )

        has_more = len(rows) > size
        items = [dict(row) for row in rows[:size]]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                from_utc(last[timestamp.name]), int(last["id"])
            )
        for item in items:
            for key, value in list(item.items()):
                if isinstance(value, datetime):
                    item[key] = from_utc(value)
        return HistoryPage(
            items=items,
            limit_applied=size,
            has_more=has_more,
            next_cursor=next_cursor,
        )


class SqlStatusReader:
    """Reads what the status endpoint needs, so the API never issues SQL itself.

    Keeping these queries here rather than in the route is principle II: the API
    is an edge that depends on this boundary, not on SQLAlchemy. A guard test
    fails if any module outside this package imports the driver stack.
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

    def last_output_states(self) -> dict[str, tuple[bool, datetime]]:
        """The last recorded transition per heater.

        A heater with no transition at all is absent from the result and counts as
        off, which is the state every driver initialises to (principle I).
        """
        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(
                            output_transition.c.heater_id,
                            output_transition.c.state,
                            output_transition.c.occurred_at,
                        )
                        .where(
                            output_transition.c.installation_id == self._installation_id
                        )
                        .order_by(
                            output_transition.c.occurred_at.desc(),
                            output_transition.c.id.desc(),
                        )
                    )
                    .mappings()
                    .all()
                )
        latest: dict[str, tuple[bool, datetime]] = {}
        for row in rows:
            heater_id = str(row["heater_id"])
            if heater_id not in latest:
                latest[heater_id] = (bool(row["state"]), from_utc(row["occurred_at"]))
        return latest

    def plan_in_progress(self, at: datetime, *, include_next: bool = False) -> dict | None:
        """Read the current plan, or the next future plan when requested.

        Never the last past plan: presenting an expired window as if it were
        running is the same kind of lie as presenting a stale output state as
        current.
        """
        from .engine import store_errors

        moment = to_utc(at)
        with store_errors(self._location):
            with self._engine.connect() as connection:
                current_condition = (
                    (plan_table.c.window_start <= moment)
                    & (plan_table.c.window_end > moment)
                )
                plan_condition = current_condition
                if include_next:
                    plan_condition = current_condition | (plan_table.c.window_start >= moment)
                plan_row = (
                    connection.execute(
                        select(plan_table)
                        .where(
                            (plan_table.c.installation_id == self._installation_id)
                            & plan_condition
                        )
                        .order_by(
                            plan_table.c.window_start,
                            plan_table.c.created_at.desc(),
                        )
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if plan_row is None:
                    return None
                slots = (
                    connection.execute(
                        select(plan_slot)
                        .where(plan_slot.c.plan_id == plan_row["id"])
                        .order_by(plan_slot.c.slot_start, plan_slot.c.heater_id)
                    )
                    .mappings()
                    .all()
                )
                allocations = (
                    connection.execute(
                        select(plan_allocation)
                        .where(plan_allocation.c.plan_id == plan_row["id"])
                        .order_by(plan_allocation.c.heater_id)
                    )
                    .mappings()
                    .all()
                )
                forecast_row = None
                if plan_row["forecast_id"] is not None:
                    forecast_row = (
                        connection.execute(
                            select(forecast_table).where(
                                forecast_table.c.id == plan_row["forecast_id"]
                            )
                        )
                        .mappings()
                        .first()
                    )
                forecast_hours = []
                if forecast_row is not None:
                    forecast_hours = (
                        connection.execute(
                            select(forecast_hour)
                            .where(forecast_hour.c.forecast_id == forecast_row["id"])
                            .order_by(forecast_hour.c.observed_at)
                        )
                        .mappings()
                        .all()
                    )

        return {
            "plan": {
                "window_start": from_utc(plan_row["window_start"]),
                "window_end": from_utc(plan_row["window_end"]),
                "slot_minutes": int(plan_row["slot_minutes"]),
                "installation_revision": int(plan_row["installation_revision"]),
                "created_at": from_utc(plan_row["created_at"]),
            },
            "slots": [
                {
                    "heater_id": str(row["heater_id"]),
                    "slot_start": from_utc(row["slot_start"]),
                    "slot_end": from_utc(row["slot_end"]),
                    "temperature_c": row["temperature_c"],
                    "temperature_interpolated": bool(row["temperature_interpolated"]),
                }
                for row in slots
            ],
            "allocations": [
                {
                    "heater_id": str(row["heater_id"]),
                    "requested_minutes": int(row["requested_minutes"]),
                    "allocated_minutes": int(row["allocated_minutes"]),
                    "unmet_minutes": int(row["unmet_minutes"]),
                }
                for row in allocations
            ],
            "forecast": (
                None
                if forecast_row is None
                else {
                    "date": forecast_row["forecast_date"],
                    "source": str(forecast_row["source"]),
                    "average_temperature_c": float(
                        forecast_row["average_temperature_c"]
                    ),
                    "minimum_temperature_c": forecast_row["minimum_temperature_c"],
                    "maximum_temperature_c": forecast_row["maximum_temperature_c"],
                    "municipality": forecast_row["municipality"],
                    "hourly_points": [
                        {
                            "timestamp": from_utc(row["observed_at"]),
                            "temperature_c": float(row["temperature_c"]),
                            "interpolated": bool(row["interpolated"]),
                        }
                        for row in forecast_hours
                    ],
                }
            ),
        }

    def latest_forecast(self) -> dict | None:
        """Return the newest stored forecast, including its hourly points."""
        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                forecast_row = (
                    connection.execute(
                        select(forecast_table)
                        .where(forecast_table.c.installation_id == self._installation_id)
                        .order_by(forecast_table.c.retrieved_at.desc(), forecast_table.c.id.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                if forecast_row is None:
                    return None
                forecast_hours = (
                    connection.execute(
                        select(forecast_hour)
                        .where(forecast_hour.c.forecast_id == forecast_row["id"])
                        .order_by(forecast_hour.c.observed_at)
                    )
                    .mappings()
                    .all()
                )
        return {
            "date": forecast_row["forecast_date"],
            "source": str(forecast_row["source"]),
            "average_temperature_c": float(forecast_row["average_temperature_c"]),
            "minimum_temperature_c": forecast_row["minimum_temperature_c"],
            "maximum_temperature_c": forecast_row["maximum_temperature_c"],
            "municipality": forecast_row["municipality"],
            "hourly_points": [
                {
                    "timestamp": from_utc(row["observed_at"]),
                    "temperature_c": float(row["temperature_c"]),
                    "interpolated": bool(row["interpolated"]),
                }
                for row in forecast_hours
            ],
        }

    def planning(self, at: datetime) -> dict | None:
        """Return the active plan or, outside a window, the next future plan."""
        return self.plan_in_progress(at, include_next=True)


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CursorError",
    "SqlHistoryReader",
    "SqlHistoryRecorder",
    "SqlStatusReader",
    "decode_cursor",
    "encode_cursor",
]
