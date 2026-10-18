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
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.engine import Engine

from . import ForecastRef, HistoryPage, PlanRef, PruneReport
from ..planning_explanation import diagnostic_report
from ..thermal_calibration import OUTDOOR_MAX_AGE
from ..weather import HourlyForecastPoint, future_forecast_points, normalize_municipality
from .mapping import from_utc, to_utc
from .forecast_context import persisted_forecast_context
from .schema import (
    RETAINED_TABLES,
    alert_delivery,
    alert_episode,
    automatic_plan,
    automatic_plan_slot,
    forecast as forecast_table,
    forecast_hour,
    measured_heater_sample,
    measured_installation_sample,
    output_transition,
    operator_notification,
    plan as plan_table,
    plan_allocation,
    plan_audit,
    plan_slot,
    relay_test_control,
    relay_test_event,
    relay_test_session,
    web_push_attempt,
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
                        municipality=normalize_municipality(
                            getattr(forecast, "location", None)
                        ),
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

    def record_measured(
        self,
        observed_at: datetime,
        *,
        heaters: Sequence[Any],
        telemetry: Mapping[str, Any],
        outdoor: Any | None,
        active_outputs: Sequence[str] | set[str] | None,
        discharge_commands: Mapping[str, Any] | Sequence[Any] | None,
        indoor_max_age: timedelta = timedelta(minutes=15),
    ) -> None:
        """Record one idempotent five-minute measurement bucket.

        The sampler receives the values that the controller has just applied,
        rather than re-deriving a plan or reading a forecast.  Every value is
        checked at capture time; a stale or missing input is deliberately
        stored as NULL so the historical chart never presents an old reading as
        current.  Audit/storage failures remain failure-open like the other
        history writes.
        """
        try:
            bucket = _measurement_bucket(observed_at)
            active = None if active_outputs is None else {str(item) for item in active_outputs}
            discharge = _discharge_values(discharge_commands)
            now = _aware_utc(observed_at)
            outdoor_value = None
            if outdoor is not None:
                received_at = getattr(outdoor, "received_at", None)
                if _fresh_measurement(received_at, now, OUTDOOR_MAX_AGE):
                    outdoor_value = _number_or_none(getattr(outdoor, "temperature_c", None))
            with self._engine.begin() as connection:
                existing = connection.execute(
                    select(measured_installation_sample.c.id).where(
                        measured_installation_sample.c.installation_id == self._installation_id,
                        measured_installation_sample.c.observed_at == to_utc(bucket),
                    )
                ).scalar_one_or_none()
                if existing is None:
                    connection.execute(
                        insert(measured_installation_sample).values(
                            installation_id=self._installation_id,
                            observed_at=to_utc(bucket),
                            outdoor_temperature_c=outdoor_value,
                        )
                    )

                for heater in heaters:
                    heater_id = str(getattr(heater, "id", ""))
                    if not heater_id:
                        continue
                    exists = connection.execute(
                        select(measured_heater_sample.c.id).where(
                            measured_heater_sample.c.installation_id == self._installation_id,
                            measured_heater_sample.c.heater_id == heater_id,
                            measured_heater_sample.c.observed_at == to_utc(bucket),
                        )
                    ).scalar_one_or_none()
                    if exists is not None:
                        continue
                    value = telemetry.get(heater_id)
                    indoor = _fresh_value(
                        value,
                        ("indoor_temperature_c", "temperature_c"),
                        ("indoor_received_at", "temperature_received_at"),
                        now,
                        indoor_max_age,
                    )
                    soc = _fresh_value(
                        value,
                        ("stored_soc_percent", "stored_charge_percent"),
                        ("stored_soc_received_at", "stored_charge_received_at"),
                        now,
                        indoor_max_age,
                    )
                    damper = _fresh_value(
                        value,
                        ("damper_position_percent",),
                        ("damper_received_at",),
                        now,
                        indoor_max_age,
                    )
                    capacity = _number_or_none(getattr(heater, "capacity_kwh", None))
                    energy = None if soc is None or capacity is None else capacity * soc / 100
                    charge_power = (
                        None
                        if active is None
                        else int(getattr(heater, "power_w", 0))
                        if heater_id in active
                        else 0
                    )
                    commanded = None if discharge is None else discharge.get(heater_id)
                    connection.execute(
                        insert(measured_heater_sample).values(
                            installation_id=self._installation_id,
                            heater_id=heater_id,
                            observed_at=to_utc(bucket),
                            indoor_temperature_c=indoor,
                            stored_soc_percent=soc,
                            stored_energy_kwh=energy,
                            confirmed_charge_power_w=charge_power,
                            discharge_commanded=commanded,
                            damper_position_percent=damper,
                        )
                    )
        except Exception:
            logger.error(
                "Could not record measured history; scheduling continues",
                exc_info=True,
            )

    # Both spellings are useful at integration boundaries; retain one body so
    # the controller cannot accidentally grow a second recording policy.
    record_measurements = record_measured
    record_measurement = record_measured

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
                # Forecasts are checked after both plan tables.  A plan that
                # survives its own age policy must be able to keep its linked
                # snapshot alive during this same pruning pass.
                retained_tables = tuple(
                    (table, timestamp_column)
                    for table, timestamp_column in RETAINED_TABLES
                    if table is not forecast_table
                ) + ((forecast_table, "retrieved_at"),)
                for table, timestamp_column in retained_tables:
                    condition = table.c[timestamp_column] < cutoff
                    if table is plan_table:
                        # Live and future plans survive regardless of age.
                        condition = condition & (plan_table.c.window_end <= now_utc)
                    if table is forecast_table:
                        # Do not remove a snapshot still cited by either
                        # historical plan representation.
                        for plan_table_ref in (plan_table, automatic_plan):
                            condition = condition & ~forecast_table.c.id.in_(
                                select(plan_table_ref.c.forecast_id).where(
                                    plan_table_ref.c.forecast_id.is_not(None)
                                )
                            )
                    if table is operator_notification:
                        # Active alerts are operational state, not disposable
                        # history; acknowledged or resolved rows remain subject
                        # to the configured retention window.
                        condition = condition & or_(
                            operator_notification.c.acknowledged_at.is_not(None),
                            operator_notification.c.resolved_at.is_not(None),
                        )
                        # Keep the inbox row alongside a channel row that is
                        # still waiting for a worker; otherwise a delayed
                        # delivery could outlive the operator-visible alert.
                        condition = condition & ~operator_notification.c.id.in_(
                            select(alert_delivery.c.alert_id).where(
                                and_(
                                    alert_delivery.c.alert_id.is_not(None),
                                    alert_delivery.c.installation_id
                                    == self._installation_id,
                                    alert_delivery.c.status.in_(
                                        ("pending", "failed")
                                    ),
                                )
                            )
                        )
                        condition = condition & ~operator_notification.c.id.in_(
                            select(web_push_attempt.c.alert_id).where(
                                and_(
                                    web_push_attempt.c.alert_id.is_not(None),
                                    web_push_attempt.c.status.in_(
                                        ("pending", "error")
                                    ),
                                )
                            )
                        )
                    if table is alert_episode:
                        condition = condition & alert_episode.c.active.is_(False)
                    if table is alert_delivery:
                        # A pending delivery must survive until the channel
                        # worker can claim it, even if its alert is old.
                        condition = condition & alert_delivery.c.status.in_(("sent", "failed"))
                    if table is web_push_attempt:
                        # Pending/error attempts have no attempted_at and must
                        # not disappear before a process can deliver them.
                        condition = condition & web_push_attempt.c.status.not_in(("pending", "error"))
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
            measured_installation_sample,
            measured_heater_sample,
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
    """Accept only a forecast returned by the real AEMET provider."""
    source = getattr(forecast, "source", None)
    if source != "aemet":
        raise ValueError("only AEMET forecasts can be recorded")
    return "aemet"


def _now_of(forecast: Any) -> datetime:
    retrieved = getattr(forecast, "retrieved_at", None)
    if retrieved is not None:
        return retrieved
    from datetime import timezone

    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("measurement timestamps require a timezone")
    return value.astimezone(timezone.utc)


def _measurement_bucket(value: datetime) -> datetime:
    """Floor an aware instant to the five-minute UTC wall-clock bucket."""
    instant = _aware_utc(value)
    return instant.replace(
        minute=instant.minute - instant.minute % 5,
        second=0,
        microsecond=0,
    )


def _fresh_measurement(
    received_at: datetime | None,
    now: datetime,
    max_age: timedelta,
) -> bool:
    if received_at is None or received_at.tzinfo is None:
        return False
    age = now - received_at.astimezone(timezone.utc)
    return timedelta(0) <= age <= max_age


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _fresh_value(
    telemetry: Any | None,
    value_names: Sequence[str],
    timestamp_names: Sequence[str],
    now: datetime,
    max_age: timedelta,
) -> float | None:
    if telemetry is None:
        return None
    value = next(
        (getattr(telemetry, name, None) for name in value_names if getattr(telemetry, name, None) is not None),
        None,
    )
    received_at = next(
        (
            getattr(telemetry, name, None)
            for name in timestamp_names
            if getattr(telemetry, name, None) is not None
        ),
        None,
    )
    if not _fresh_measurement(received_at, now, max_age):
        return None
    return _number_or_none(value)


def _discharge_values(value: Mapping[str, Any] | Sequence[Any] | None) -> dict[str, bool] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        items = value.items()
    else:
        items = (
            (getattr(item, "heater_id", None), getattr(item, "enabled", None))
            for item in value
        )
    result: dict[str, bool] = {}
    for heater_id, enabled in items:
        if heater_id is None or enabled is None:
            continue
        result[str(heater_id)] = bool(enabled)
    return result


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


def encode_plan_cursor(instant: datetime, source: str, row_id: int) -> str:
    """Encode the source-aware cursor used by the combined plans stream."""
    if source not in {"automatic", "legacy"}:
        raise CursorError("the continuation cursor has an unknown plan source")
    payload = {
        "v": 1,
        "instant": to_utc(instant).isoformat(),
        "source": source,
        "id": int(row_id),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def decode_plan_cursor(cursor: str) -> tuple[datetime, str, int]:
    """Decode a source-aware plans cursor, accepting the old legacy cursor."""
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            # Cursors issued before automatic plans were exposed only contained
            # (instant, id); interpret those as the legacy stream.
            instant, row_id = decode_cursor(cursor)
            return instant, "legacy", row_id
        if not isinstance(value, dict) or value.get("v") != 1:
            raise ValueError("unsupported cursor version")
        source = value.get("source")
        if source not in {"automatic", "legacy"}:
            raise ValueError("unknown plan source")
        instant = datetime.fromisoformat(str(value["instant"]))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        row_id = int(value["id"])
        if row_id < 1:
            raise ValueError("invalid row id")
        return instant, source, row_id
    except CursorError:
        raise
    except Exception as exc:
        raise CursorError(
            "the continuation cursor is unreadable; request the first page again "
            "without a cursor"
        ) from exc


def _plan_source_rank(source: str) -> int:
    if source == "automatic":
        return 1
    if source == "legacy":
        return 0
    raise CursorError("the continuation cursor has an unknown plan source")


def _plan_history_item(row: dict[str, Any], source: str) -> dict[str, Any]:
    """Project either plan table into the stable history API shape."""
    if source == "automatic":
        status = {
            "VALID": "VALID",
            "CONVERGING": "CONVERGING",
            "DEGRADED": "DEGRADED",
            "INVALID": "INVALID",
            "FEASIBLE": "VALID",
            "feasible": "VALID",
            "deficit": "DEGRADED",
            "best_effort": "DEGRADED",
            "preview": "INVALID",
        }.get(row["status"], str(row["status"]))
        return {
            "id": int(row["id"]),
            "source": source,
            "created_at": from_utc(row["created_at"]),
            "window_start": from_utc(row["horizon_start"]),
            "window_end": from_utc(row["horizon_end"]),
            "slot_minutes": int(row["slot_minutes"]),
            "installation_revision": int(row["configuration_revision"]),
            "forecast_id": None if row["forecast_id"] is None else int(row["forecast_id"]),
            "status": status,
            "reason": str(row["reason"]),
            "active": bool(row["active"]),
        }
    return {
        "id": int(row["id"]),
        "source": source,
        "created_at": from_utc(row["created_at"]),
        "window_start": from_utc(row["window_start"]),
        "window_end": from_utc(row["window_end"]),
        "slot_minutes": int(row["slot_minutes"]),
        "installation_revision": int(row["installation_revision"]),
        "forecast_id": None if row["forecast_id"] is None else int(row["forecast_id"]),
        "status": None,
        "reason": None,
        "active": None,
    }


def _page_size(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(int(limit), MAX_PAGE_SIZE))


def encode_series_cursor(instant: datetime, row_id: int) -> str:
    payload = {
        "v": 1,
        "instant": to_utc(instant).isoformat(),
        "id": int(row_id),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def decode_series_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        value = json.loads(payload)
        if not isinstance(value, dict) or value.get("v") != 1:
            raise ValueError("unsupported cursor version")
        instant = datetime.fromisoformat(str(value["instant"]))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        row_id = int(value["id"])
        if row_id < 1:
            raise ValueError("invalid row id")
        return instant, row_id
    except Exception as exc:
        raise CursorError(
            "the continuation cursor is unreadable; request the first page again "
            "without a cursor"
        ) from exc


def _json_mapping(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    return list(parsed) if isinstance(parsed, list) else None


def _canonical_automatic_status(value: Any) -> str:
    return {
        "VALID": "VALID",
        "CONVERGING": "CONVERGING",
        "DEGRADED": "DEGRADED",
        "INVALID": "INVALID",
        "FEASIBLE": "VALID",
        "feasible": "VALID",
        "deficit": "DEGRADED",
        "best_effort": "DEGRADED",
        "preview": "INVALID",
    }.get(str(value), str(value))


def _forecast_interpolated(evidence: Mapping[str, Any], at: datetime) -> bool | None:
    points = evidence.get("forecast")
    if not isinstance(points, list):
        return None
    target = _aware_utc(at)
    for point in points:
        if not isinstance(point, Mapping):
            continue
        raw_at = point.get("timestamp")
        if not isinstance(raw_at, str):
            continue
        try:
            timestamp = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp.astimezone(timezone.utc) == target:
            return bool(point.get("interpolated", False))
    return None


def _interval_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _reason_overlaps_bucket(
    reason: Mapping[str, Any], slot: Mapping[str, Any]
) -> bool:
    """Keep a reason only when its persisted interval touches this slot."""
    reason_start = _interval_instant(reason.get("start"))
    reason_end = _interval_instant(reason.get("end"))
    slot_start = _interval_instant(slot.get("slot_start"))
    slot_end = _interval_instant(slot.get("slot_end"))
    if None in (reason_start, reason_end, slot_start, slot_end):
        return False
    assert reason_start is not None
    assert reason_end is not None
    assert slot_start is not None
    assert slot_end is not None
    return reason_start < slot_end and reason_end > slot_start


def _plan_cues(
    inputs: Mapping[str, Any],
    slot: Mapping[str, Any],
    *,
    at: datetime,
    heater_id: str | None,
) -> dict[str, Any]:
    evidence = inputs.get("evidence")
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    cues: dict[str, Any] = {
        "forecast_interpolated": _forecast_interpolated(
            evidence_map, from_utc(slot["slot_start"])
        ),
        "forecast_stale": (
            None if "stale_forecast" not in inputs else bool(inputs.get("stale_forecast"))
        ),
        "guaranteed": None,
        "charge_reasons": None,
        "aggregate_limit_reached": None,
    }
    guaranteed_until = inputs.get("guaranteed_until")
    if guaranteed_until is not None:
        try:
            guaranteed = datetime.fromisoformat(str(guaranteed_until).replace("Z", "+00:00"))
            if guaranteed.tzinfo is None:
                guaranteed = guaranteed.replace(tzinfo=timezone.utc)
            cues["guaranteed"] = _aware_utc(at) < guaranteed.astimezone(timezone.utc)
        except ValueError:
            cues["guaranteed"] = None

    explanations = inputs.get("explanations")
    if isinstance(explanations, list):
        reasons: list[Any] = []
        has_charge_reasons_list = False
        for item in explanations:
            if not isinstance(item, Mapping):
                continue
            if heater_id is not None and str(item.get("heater_id")) != heater_id:
                continue
            if "charge_reasons" not in item:
                continue
            value = item["charge_reasons"]
            if isinstance(value, list):
                has_charge_reasons_list = True
                reasons.extend(
                    reason
                    for reason in value
                    if isinstance(reason, Mapping)
                    and _reason_overlaps_bucket(reason, slot)
                )
        # A persisted explanation with an explicit list is evidence, including
        # an empty list after interval filtering; absent/null remains unknown.
        if has_charge_reasons_list:
            cues["charge_reasons"] = reasons

    limits = evidence_map.get("limits")
    if isinstance(limits, Mapping) and limits.get("contracted_power_w") is not None:
        try:
            contracted = float(limits["contracted_power_w"])
            max_heating = limits.get("max_heating_power_w")
            base_load = float(limits.get("base_load_w") or 0)
            limit = contracted - base_load
            if max_heating is not None:
                limit = min(limit, float(max_heating))
            cues["aggregate_limit_reached"] = float(slot.get("power_w") or 0) >= limit
        except (TypeError, ValueError):
            cues["aggregate_limit_reached"] = None
    return cues


def _series_projected(
    plan: Mapping[str, Any], slot: Mapping[str, Any], heater_id: str | None
) -> dict[str, Any]:
    if heater_id is None:
        return {
            "outdoor_temperature_c": slot.get("outdoor_temperature_c"),
            "aggregate_charge_power_w": slot.get("power_w"),
        }
    field_by_name = {
        "stored_soc_percent": "stored_charge_json",
        "stored_energy_kwh": "stored_energy_json",
        "indoor_temperature_c": "indoor_temperature_json",
        "target_temperature_c": "target_temperature_json",
        "heat_delivered_kwh": "heat_delivered_json",
        "charge_energy_kwh": "charge_energy_json",
        "heater_power_w": "heater_power_json",
    }
    projected: dict[str, Any] = {
        "outdoor_temperature_c": slot.get("outdoor_temperature_c"),
        "charge_power_w": None,
        "indoor_temperature_c": None,
        "stored_soc_percent": None,
        "stored_energy_kwh": None,
    }
    for output_name, column_name in field_by_name.items():
        values = _json_mapping(slot.get(column_name))
        if heater_id in values:
            projected[output_name] = values[heater_id]
    if projected["charge_power_w"] is None:
        projected["charge_power_w"] = projected.get("heater_power_w")
    return projected


def _series_candidate(
    audit: Mapping[str, Any],
    plan: Mapping[str, Any],
    slots: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    inputs = _json_mapping(plan.get("inputs_json"))
    normalized_slots = [dict(slot) for slot in slots]
    return {
        "plan_id": int(plan["id"]),
        "activated_at": from_utc(audit["occurred_at"]),
        "status": _canonical_automatic_status(plan["status"]),
        "activation_mode": str(inputs.get("activation_mode", "automatic")),
        "inputs": inputs,
        "slots": normalized_slots,
    }


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
        return self._plan_page(since, until, limit, cursor)

    def legacy_plan_explanation(self, plan_id: int) -> dict[str, Any] | None:
        """Expose honest minimal evidence for plans predating explainability."""
        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                row = connection.execute(
                    select(plan_table).where(
                        (plan_table.c.installation_id == self._installation_id)
                        & (plan_table.c.id == plan_id)
                    )
                ).mappings().first()
                if row is None:
                    return None
                slots = connection.execute(
                    select(plan_slot)
                    .where(plan_slot.c.plan_id == plan_id)
                    .order_by(plan_slot.c.slot_start, plan_slot.c.heater_id)
                ).mappings().all()
                transitions = connection.execute(
                    select(output_transition)
                    .where(
                        (output_transition.c.installation_id == self._installation_id)
                        & (output_transition.c.plan_id == plan_id)
                    )
                    .order_by(output_transition.c.occurred_at, output_transition.c.id)
                ).mappings().all()
        plan = _plan_history_item(dict(row), "legacy")
        plan["slots"] = [
            {
                "start": from_utc(item["slot_start"]),
                "end": from_utc(item["slot_end"]),
                "heater_ids": [str(item["heater_id"])],
                "outdoor_temperature_c": item["temperature_c"],
            }
            for item in slots
        ]
        return {
            "source": "legacy",
            "evidence_available": False,
            "plan": plan,
            "predecessor": None,
            "operator_summary": [],
            "comparison": None,
            "audit": [],
            "transitions": [
                {
                    "id": int(item["id"]),
                    "heater_id": str(item["heater_id"]),
                    "state": bool(item["state"]),
                    "occurred_at": from_utc(item["occurred_at"]),
                }
                for item in transitions
            ],
        }

    def legacy_plan_diagnostic(self, plan_id: int) -> dict[str, Any] | None:
        """Return a secret-free legacy diagnostic with its linked forecast."""
        detail = self.legacy_plan_explanation(plan_id)
        if detail is None:
            return None
        plan = detail["plan"]
        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                forecast_context = persisted_forecast_context(
                    connection,
                    installation_id=self._installation_id,
                    forecast_id=plan.get("forecast_id"),
                    plan_start=plan["window_start"],
                    plan_end=plan["window_end"],
                )
        return diagnostic_report(detail, forecast=forecast_context)

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

    def series(
        self,
        since: datetime,
        until: datetime,
        *,
        scope: str,
        heater_id: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> HistoryPage:
        """Read ascending measured samples and attach their governing plan.

        Governing-plan selection is intentionally based on persisted activation
        audit rows and persisted slots.  A plan activated in the middle of a
        slot only becomes eligible at the next slot boundary, so no measured
        bucket is split or assigned a preview/current-plan projection after the
        fact.
        """
        if scope not in {"installation", "heater"}:
            raise ValueError("history series scope is invalid")
        if scope == "heater" and not heater_id:
            raise ValueError("heater_id is required for heater series")
        if scope == "installation" and heater_id is not None:
            raise ValueError("heater_id is only valid for heater series")
        size = _page_size(limit)
        table = measured_heater_sample if scope == "heater" else measured_installation_sample
        timestamp = table.c.observed_at
        condition = table.c.installation_id == self._installation_id
        if scope == "heater":
            condition = condition & (table.c.heater_id == heater_id)
        condition = condition & (timestamp >= to_utc(since)) & (timestamp <= to_utc(until))
        if cursor is not None:
            cursor_instant, cursor_id = decode_series_cursor(cursor)
            cursor_utc = to_utc(cursor_instant)
            condition = condition & (
                (timestamp > cursor_utc)
                | ((timestamp == cursor_utc) & (table.c.id > cursor_id))
            )

        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                rows = (
                    connection.execute(
                        select(table)
                        .where(condition)
                        .order_by(timestamp.asc(), table.c.id.asc())
                        .limit(size + 1)
                    )
                    .mappings()
                    .all()
                )
                aggregate: dict[datetime, int] = {}
                sample_times = [row["observed_at"] for row in rows]
                if scope == "installation" and sample_times:
                    heater_rows = connection.execute(
                        select(measured_heater_sample).where(
                            (measured_heater_sample.c.installation_id == self._installation_id)
                            & measured_heater_sample.c.observed_at.in_(sample_times)
                        )
                    ).mappings().all()
                    for heater_row in heater_rows:
                        value = heater_row["confirmed_charge_power_w"]
                        if value is not None:
                            observed = heater_row["observed_at"]
                            aggregate[observed] = aggregate.get(observed, 0) + int(value)

                until_utc = to_utc(until)
                audit_condition = (
                    (plan_audit.c.installation_id == self._installation_id)
                    & (plan_audit.c.event == "activated")
                    & plan_audit.c.plan_id.is_not(None)
                    & (plan_audit.c.occurred_at <= until_utc)
                )
                audits = connection.execute(
                    select(plan_audit)
                    .where(audit_condition)
                    .order_by(plan_audit.c.occurred_at.asc(), plan_audit.c.id.asc())
                ).mappings().all()
                plan_ids = [int(item["plan_id"]) for item in audits]
                plans = (
                    connection.execute(
                        select(automatic_plan).where(automatic_plan.c.id.in_(plan_ids))
                    ).mappings().all()
                    if plan_ids
                    else []
                )
                plan_by_id = {int(item["id"]): item for item in plans}
                slots_by_plan: dict[int, list[dict[str, Any]]] = {}
                if plan_ids:
                    slot_rows = connection.execute(
                        select(automatic_plan_slot)
                        .where(automatic_plan_slot.c.plan_id.in_(plan_ids))
                        .order_by(automatic_plan_slot.c.slot_start.asc())
                    ).mappings().all()
                    for item in slot_rows:
                        slots_by_plan.setdefault(int(item["plan_id"]), []).append(dict(item))
                candidates = [
                    _series_candidate(
                        audit,
                        plan_by_id[int(audit["plan_id"])],
                        slots_by_plan.get(int(audit["plan_id"]), ()),
                    )
                    for audit in audits
                    if int(audit["plan_id"]) in plan_by_id
                    and _canonical_automatic_status(
                        plan_by_id[int(audit["plan_id"])]["status"]
                    )
                    not in {"INVALID", "preview"}
                ]

        def empty_cues() -> dict[str, Any]:
            return {
                "forecast_interpolated": None,
                "forecast_stale": None,
                "guaranteed": None,
                "charge_reasons": None,
                "aggregate_limit_reached": None,
            }

        def governing(at: datetime) -> tuple[dict[str, Any], Mapping[str, Any]] | None:
            moment = _aware_utc(at)
            selected = None
            for candidate in candidates:
                activated = _aware_utc(candidate["activated_at"])
                for slot in candidate["slots"]:
                    start = _aware_utc(from_utc(slot["slot_start"]))
                    end = _aware_utc(from_utc(slot["slot_end"]))
                    if start <= moment < end and activated <= start:
                        selected = (candidate, slot)
                        break
            return selected

        has_more = len(rows) > size
        items: list[dict[str, Any]] = []
        for row in rows[:size]:
            observed_at = from_utc(row["observed_at"])
            assert observed_at is not None
            if scope == "installation":
                measured = {
                    "outdoor_temperature_c": row["outdoor_temperature_c"],
                    "aggregate_charge_power_w": aggregate.get(row["observed_at"]),
                }
            else:
                measured = {
                    "indoor_temperature_c": row["indoor_temperature_c"],
                    "stored_soc_percent": row["stored_soc_percent"],
                    "stored_energy_kwh": row["stored_energy_kwh"],
                    "confirmed_charge_power_w": row["confirmed_charge_power_w"],
                    "discharge_commanded": row["discharge_commanded"],
                    "damper_position_percent": row["damper_position_percent"],
                }
            selected = governing(observed_at)
            if selected is None:
                projected = None
                governing_plan = None
                cues = empty_cues()
            else:
                candidate, slot = selected
                projected = _series_projected(candidate, slot, heater_id)
                governing_plan = {
                    "plan_id": candidate["plan_id"],
                    "activated_at": candidate["activated_at"],
                    "slot_start": from_utc(slot["slot_start"]),
                    "slot_end": from_utc(slot["slot_end"]),
                    "status": candidate["status"],
                    "activation_mode": candidate["activation_mode"],
                }
                cues = _plan_cues(
                    candidate["inputs"], slot, at=observed_at, heater_id=heater_id
                )
            items.append(
                {
                    "at": observed_at,
                    "measured": measured,
                    "projected": projected,
                    "governing_plan": governing_plan,
                    "cues": cues,
                }
            )
        next_cursor = None
        if has_more and rows[:size]:
            last = rows[size - 1]
            next_cursor = encode_series_cursor(
                from_utc(last["observed_at"]), int(last["id"])
            )
        return HistoryPage(
            items=items,
            limit_applied=size,
            has_more=has_more,
            next_cursor=next_cursor,
        )

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

    def _plan_page(self, since, until, limit, cursor) -> HistoryPage:
        """Read the canonical automatic and legacy plan streams together.

        The two tables intentionally keep their own identities.  The composite
        cursor carries the source as well as the instant and id, so equal
        timestamps and colliding integer ids cannot make a page repeat or skip
        a plan.  Each source is bounded to ``size + 1`` rows before merging;
        this remains a paged read even when the installation has a long audit
        trail.
        """
        size = _page_size(limit)
        cursor_value = None if cursor is None else decode_plan_cursor(cursor)
        rows: list[dict[str, Any]] = []

        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                for table, timestamp, source, source_rank in (
                    (plan_table, plan_table.c.created_at, "legacy", 0),
                    (automatic_plan, automatic_plan.c.created_at, "automatic", 1),
                ):
                    condition = table.c.installation_id == self._installation_id
                    if since is not None:
                        condition = condition & (timestamp >= to_utc(since))
                    if until is not None:
                        condition = condition & (timestamp <= to_utc(until))
                    if cursor_value is not None:
                        cursor_instant, cursor_source, cursor_id = cursor_value
                        cursor_rank = _plan_source_rank(cursor_source)
                        cursor_utc = to_utc(cursor_instant)
                        if source_rank < cursor_rank:
                            cursor_condition = timestamp <= cursor_utc
                        elif source_rank == cursor_rank:
                            cursor_condition = (timestamp < cursor_utc) | (
                                (timestamp == cursor_utc) & (table.c.id < cursor_id)
                            )
                        else:
                            cursor_condition = timestamp < cursor_utc
                        condition = condition & cursor_condition
                    source_rows = (
                        connection.execute(
                            select(table)
                            .where(condition)
                            .order_by(timestamp.desc(), table.c.id.desc())
                            .limit(size + 1)
                        )
                        .mappings()
                        .all()
                    )
                    rows.extend(
                        _plan_history_item(dict(row), source)
                        for row in source_rows
                    )

        rows.sort(
            key=lambda item: (
                to_utc(item["created_at"]),
                _plan_source_rank(str(item["source"])),
                int(item["id"]),
            ),
            reverse=True,
        )
        items = rows[:size]
        has_more = len(rows) > size
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_plan_cursor(
                last["created_at"], str(last["source"]), int(last["id"])
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
                "id": int(plan_row["id"]),
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
                            "timestamp": point.timestamp,
                            "temperature_c": point.temperature_c,
                            "interpolated": point.interpolated,
                        }
                        for point in future_forecast_points(
                            tuple(
                                HourlyForecastPoint(
                                    from_utc(row["observed_at"]),
                                    float(row["temperature_c"]),
                                    bool(row["interpolated"]),
                                )
                                for row in forecast_hours
                            ),
                            at,
                        )
                    ],
                }
            ),
        }

    def latest_forecast(self, at: datetime | None = None) -> dict | None:
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
        points = tuple(
            HourlyForecastPoint(
                from_utc(row["observed_at"]),
                float(row["temperature_c"]),
                bool(row["interpolated"]),
            )
            for row in forecast_hours
        )
        filtered = future_forecast_points(points, at) if at is not None else points
        return {
            "date": forecast_row["forecast_date"],
            "source": str(forecast_row["source"]),
            "average_temperature_c": float(forecast_row["average_temperature_c"]),
            "minimum_temperature_c": forecast_row["minimum_temperature_c"],
            "maximum_temperature_c": forecast_row["maximum_temperature_c"],
            "municipality": normalize_municipality(
                forecast_row["municipality"]
            ),
            "retrieved_at": from_utc(forecast_row["retrieved_at"]),
            "hourly_points": [
                {
                    "timestamp": point.timestamp,
                    "temperature_c": point.temperature_c,
                    "interpolated": point.interpolated,
                }
                for point in filtered
            ],
        }

    def latest_forecast_success_at(self) -> datetime | None:
        """Return when the latest accepted AEMET forecast was stored."""
        from .engine import store_errors

        with store_errors(self._location):
            with self._engine.connect() as connection:
                retrieved_at = connection.execute(
                    select(forecast_table.c.retrieved_at)
                    .where(
                        (forecast_table.c.installation_id == self._installation_id)
                        & (forecast_table.c.source == "aemet")
                    )
                    .order_by(
                        forecast_table.c.retrieved_at.desc(),
                        forecast_table.c.id.desc(),
                    )
                    .limit(1)
                ).scalar()
        return from_utc(retrieved_at)

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
    "decode_plan_cursor",
    "encode_cursor",
    "encode_plan_cursor",
]
