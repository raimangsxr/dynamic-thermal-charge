"""Durable operator alerts, independent email delivery and Push attempts.

The alert row is the application inbox. Episode state, the optional email
delivery and one Push attempt per active subscription are committed together;
the transport workers only claim and finish those channel rows afterwards.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import json
import logging
from typing import Any, Callable, Sequence
from uuid import uuid4

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine

from ..alerts import (
    ALERT_TYPES_BY_NAME,
    THERMAL_CALIBRATION_TERMINAL,
    PendingAlert,
)
from .engine import store_errors, transaction
from .mapping import from_utc, to_utc
from .schema import (
    alert_delivery,
    alert_episode,
    alert_type_config,
    operator_notification,
    web_push_attempt,
    web_push_subscription,
)
from .url import StoreLocation


CLAIM_LEASE_SECONDS = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertRecord:
    id: int
    alert_type: str
    title: str
    body: str
    severity: str
    episode_id: str | None
    session_id: str | None
    opened_at: datetime
    resolved_at: datetime | None
    acknowledged_at: datetime | None

    @property
    def active(self) -> bool:
        return self.resolved_at is None and self.acknowledged_at is None


@dataclass(frozen=True)
class AlertPage:
    items: tuple[AlertRecord, ...]
    limit_applied: int
    has_more: bool
    next_cursor: str | None
    active_count: int
    maximum_severity: str | None


class SqlAlertRepository:
    """Catalogue, episodes, inbox rows and durable channel queues."""

    def __init__(
        self,
        configuration_engine: Engine,
        application_engine: Engine,
        installation_id: int,
        configuration_location: StoreLocation | None = None,
        application_location: StoreLocation | None = None,
        *,
        clock=None,
    ) -> None:
        self._configuration = configuration_engine
        self._application = application_engine
        self._installation_id = installation_id
        self._configuration_location = configuration_location
        self._application_location = application_location
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ catalog

    def type_enabled(self, alert_type: str) -> bool:
        return self.enabled_types().get(alert_type, True)

    @contextmanager
    def _locked_type_enabled(self, alert_type: str):
        """Read one catalogue row while holding its transaction lock.

        Transport handoff already owns the application delivery row.  Keeping
        this catalogue transaction open only for the final check and send
        makes a concurrent disable observe one deterministic side of the
        handoff.  ``FOR UPDATE`` is ignored by SQLite, where the transaction
        still provides the equivalent connection/commit boundary.
        """
        with transaction(self._configuration, self._configuration_location) as connection:
            try:
                row = connection.execute(
                    select(alert_type_config.c.enabled)
                    .where(alert_type_config.c.name == alert_type)
                    .with_for_update()
                ).first()
            except Exception:  # noqa: BLE001 - channel delivery remains best effort
                logger.warning(
                    "Could not read catalogue state for email alert %s",
                    alert_type,
                    exc_info=True,
                )
                row = None
            yield True if row is None else bool(row[0])

    def enabled_types(self) -> dict[str, bool]:
        with store_errors(self._configuration_location):
            with self._configuration.connect() as connection:
                rows = connection.execute(select(alert_type_config)).mappings().all()
        stored = {str(row["name"]): bool(row["enabled"]) for row in rows}
        return {name: stored.get(name, True) for name in ALERT_TYPES_BY_NAME}

    def set_type_enabled(self, alert_type: str, enabled: bool) -> None:
        if alert_type not in ALERT_TYPES_BY_NAME:
            raise ValueError(f"unknown alert type {alert_type!r}")
        with transaction(self._configuration, self._configuration_location) as connection:
            _insert_ignore(
                connection,
                alert_type_config,
                {"name": alert_type, "enabled": bool(enabled)},
                conflict_columns=("name",),
            )
            connection.execute(
                update(alert_type_config)
                .where(alert_type_config.c.name == alert_type)
                .values(enabled=bool(enabled))
            )
        if not enabled:
            # Configuration and application data may live in different
            # databases, so this cannot be one SQL transaction. Commit the
            # catalogue first; application cleanup then waits for any worker
            # that already owns a delivery row, while a later handoff sees the
            # durable disabled state and sends nothing.
            try:
                with transaction(
                    self._application, self._application_location
                ) as application_connection:
                    application_connection.execute(
                        update(alert_delivery)
                        .where(
                            and_(
                                alert_delivery.c.installation_id
                                == self._installation_id,
                                alert_delivery.c.alert_type == alert_type,
                                alert_delivery.c.status == "pending",
                            )
                        )
                        .values(
                            status="failed",
                            last_error="alert_type_disabled",
                            claimed_by=None,
                            claimed_until=None,
                        )
                    )
                    alert_ids = select(operator_notification.c.id).where(
                        and_(
                            operator_notification.c.installation_id
                            == self._installation_id,
                            operator_notification.c.alert_type == alert_type,
                        )
                    )
                    application_connection.execute(
                        update(web_push_attempt)
                        .where(
                            and_(
                                web_push_attempt.c.alert_id.in_(alert_ids),
                                web_push_attempt.c.status.in_(("pending", "error")),
                            )
                        )
                        .values(
                            status="denied",
                            error="alert_type_disabled",
                            attempted_at=to_utc(datetime.now(timezone.utc)),
                            claimed_by=None,
                            claimed_until=None,
                        )
                    )
            except Exception:
                # The setting remains durable even if the application store is
                # briefly unavailable. Delivery workers still re-check the
                # catalogue before a later send.
                logger.warning(
                    "Could not suppress queued channels for disabled alert type %s",
                    alert_type,
                    exc_info=True,
                )

    # ------------------------------------------------------------------ episodes

    def episode_active(self, alert_type: str) -> bool:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                row = connection.execute(
                    select(alert_episode.c.active).where(
                        and_(
                            alert_episode.c.installation_id == self._installation_id,
                            alert_episode.c.alert_type == alert_type,
                        )
                    )
                ).first()
        return bool(row[0]) if row is not None else False

    def open_alert(
        self,
        alert_type: str,
        *,
        severity: str,
        subject: str,
        body: str,
        at: datetime,
        title: str | None = None,
        episode_id: str | None = None,
        session_id: str | None = None,
        email_enabled: bool = True,
        push_enabled: bool = True,
        resolved: bool = False,
    ) -> bool:
        """Open one episode and its independent channel rows atomically."""
        if alert_type not in ALERT_TYPES_BY_NAME:
            raise ValueError(f"unknown alert type {alert_type!r}")
        if severity not in {"critical", "warning", "info"}:
            raise ValueError(f"unknown alert severity {severity!r}")
        # D2 is a persistence invariant, not only a service convention: an
        # informational alert can never create an email row. Calibration
        # terminal events are the explicit exception required by their
        # independent email channel contract.
        if severity == "info" and alert_type != THERMAL_CALIBRATION_TERMINAL:
            email_enabled = False
        moment = to_utc(at)
        episode_key = episode_id or str(uuid4())
        display_title = title or ALERT_TYPES_BY_NAME[alert_type].title
        with transaction(self._application, self._application_location) as connection:
            existing_notification = None
            if session_id is not None:
                existing_notification = connection.execute(
                    select(
                        operator_notification.c.id,
                        operator_notification.c.episode_id,
                    ).where(
                        and_(
                            operator_notification.c.installation_id
                            == self._installation_id,
                            operator_notification.c.session_id == session_id,
                            operator_notification.c.alert_type == alert_type,
                        )
                    )
                ).first()
            episode_row = _ensure_episode(
                connection,
                installation_id=self._installation_id,
                alert_type=alert_type,
            )

            # ``alert_episode`` is the durable claim for a condition.  The
            # old SELECT-then-INSERT sequence allowed two processes to observe
            # the same resolved row and both create a new notification.  An
            # atomic UPDATE makes reopening the episode a single-winner
            # operation on both SQLite and PostgreSQL; a rolled-back owner can
            # be reclaimed after a restart.
            claimed_episode = False
            if existing_notification is None and not resolved:
                claimed_episode = (
                    connection.execute(
                        update(alert_episode)
                        .where(
                            and_(
                                alert_episode.c.id == episode_row[0],
                                alert_episode.c.active.is_(False),
                            )
                        )
                        .values(
                            active=True,
                            since=moment,
                            last_enqueued_at=moment,
                        )
                    ).rowcount
                    == 1
                )
                if not claimed_episode:
                    return False
            elif existing_notification is None and bool(episode_row[1]):
                # Event alerts are normally passed a session id and use the
                # session unique key below.  Preserve the historical guard for
                # callers that try to create a resolved alert on an open
                # condition of the same catalogue type.
                return False

            if existing_notification is not None:
                notification_id = int(existing_notification[0])
                episode_key = str(existing_notification[1] or episode_key)
            else:
                conflict_columns = (
                    ("installation_id", "session_id")
                    if session_id is not None
                    else ("installation_id", "episode_id")
                )
                _insert_ignore(
                    connection,
                    operator_notification,
                    {
                        "installation_id": self._installation_id,
                        "session_id": session_id,
                        "kind": alert_type,
                        "alert_type": alert_type,
                        "severity": severity,
                        "episode_id": episode_key,
                        "title": display_title[:512],
                        "body": body,
                        "created_at": moment,
                        "opened_at": moment,
                        "resolved_at": moment if resolved else None,
                    },
                    conflict_columns=conflict_columns,
                )
                notification_query = [
                    operator_notification.c.installation_id == self._installation_id,
                ]
                if session_id is not None:
                    notification_query.append(
                        operator_notification.c.session_id == session_id
                    )
                else:
                    notification_query.append(
                        operator_notification.c.episode_id == episode_key
                    )
                notification = connection.execute(
                    select(
                        operator_notification.c.id,
                        operator_notification.c.episode_id,
                    ).where(and_(*notification_query))
                ).first()
                if notification is None:  # pragma: no cover - DB invariant
                    raise RuntimeError("operator notification claim was not persisted")
                notification_id = int(notification[0])
                episode_key = str(notification[1] or episode_key)

            # Channel rows are reconciled even when a legacy/event producer
            # created the inbox row first.  The alert id check makes repeated
            # enqueue/open calls idempotent without manufacturing duplicates.
            if email_enabled:
                delivery_exists = connection.execute(
                    select(alert_delivery.c.id).where(
                        and_(
                            alert_delivery.c.installation_id == self._installation_id,
                            alert_delivery.c.alert_id == notification_id,
                        )
                    )
                ).first()
                if delivery_exists is None:
                    connection.execute(
                        insert(alert_delivery).values(
                            installation_id=self._installation_id,
                            alert_type=alert_type,
                            alert_id=notification_id,
                            episode_id=episode_key,
                            subject=subject[:512],
                            body=body,
                            status="pending",
                            attempts=0,
                            next_attempt_at=moment,
                            created_at=moment,
                        )
                    )
            if push_enabled:
                subscriptions = connection.execute(
                    select(web_push_subscription).where(
                        and_(
                            web_push_subscription.c.installation_id == self._installation_id,
                            web_push_subscription.c.status == "active",
                        )
                    )
                ).mappings().all()
                for subscription in subscriptions:
                    attempt_exists = connection.execute(
                        select(web_push_attempt.c.id).where(
                            and_(
                                web_push_attempt.c.alert_id == notification_id,
                                web_push_attempt.c.subscription_id
                                == subscription["id"],
                            )
                        )
                    ).first()
                    if attempt_exists is None:
                        connection.execute(
                            insert(web_push_attempt).values(
                                subscription_id=subscription["id"],
                                # The calibration schema keeps this compatibility
                                # key non-null; episode id is the stable value for
                                # global alerts.
                                session_id=episode_key,
                                alert_id=notification_id,
                                status="pending",
                            )
                        )

            if not claimed_episode:
                values = {
                    "active": not resolved,
                    "since": moment if not resolved else None,
                    "last_enqueued_at": moment,
                }
                connection.execute(
                    update(alert_episode)
                    .where(alert_episode.c.id == episode_row[0])
                    .values(**values)
                )
        return True

    def open_episode(
        self, alert_type: str, *, subject: str, body: str, at: datetime
    ) -> bool:
        """Compatibility wrapper used by the original email-alert tests."""
        return self.open_alert(
            alert_type,
            severity="warning",
            subject=subject,
            body=body,
            at=at,
            push_enabled=False,
        )

    def set_episode(self, alert_type: str, *, active: bool, at: datetime) -> None:
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            existing = connection.execute(
                select(alert_episode.c.id).where(
                    and_(
                        alert_episode.c.installation_id == self._installation_id,
                        alert_episode.c.alert_type == alert_type,
                    )
                )
            ).first()
            values = {"active": bool(active), "since": moment if active else None}
            if active:
                values["last_enqueued_at"] = moment
            if existing is None:
                connection.execute(
                    insert(alert_episode).values(
                        installation_id=self._installation_id,
                        alert_type=alert_type,
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(alert_episode)
                    .where(alert_episode.c.id == existing[0])
                    .values(**values)
                )
            if not active:
                connection.execute(
                    update(operator_notification)
                    .where(
                        and_(
                            operator_notification.c.installation_id == self._installation_id,
                            operator_notification.c.alert_type == alert_type,
                            operator_notification.c.resolved_at.is_(None),
                        )
                    )
                    .values(resolved_at=moment)
                )

    def resolve_alert(self, alert_type: str, *, at: datetime) -> None:
        self.set_episode(alert_type, active=False, at=at)

    # ------------------------------------------------------------------ email queue

    def enqueue(
        self, alert_type: str, *, subject: str, body: str, at: datetime
    ) -> int:
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            return int(
                connection.execute(
                    insert(alert_delivery).values(
                        installation_id=self._installation_id,
                        alert_type=alert_type,
                        subject=subject[:512],
                        body=body,
                        status="pending",
                        attempts=0,
                        next_attempt_at=moment,
                        created_at=moment,
                    )
                ).inserted_primary_key[0]
            )

    def claim_pending(
        self,
        at: datetime,
        *,
        owner: str = "alert-worker",
        limit: int = 10,
        lease_seconds: int = CLAIM_LEASE_SECONDS,
    ) -> Sequence[PendingAlert]:
        """Claim due rows with a conditional update before any SMTP call."""
        moment = to_utc(at)
        lease_until = moment + timedelta(seconds=lease_seconds)
        claimed: list[PendingAlert] = []
        with transaction(self._application, self._application_location) as connection:
            rows = connection.execute(
                select(alert_delivery)
                .where(
                    and_(
                        alert_delivery.c.installation_id == self._installation_id,
                        alert_delivery.c.status == "pending",
                        alert_delivery.c.next_attempt_at <= moment,
                        or_(
                            alert_delivery.c.claimed_until.is_(None),
                            alert_delivery.c.claimed_until <= moment,
                        ),
                    )
                )
                .order_by(alert_delivery.c.next_attempt_at, alert_delivery.c.id)
                .limit(limit)
            ).mappings().all()
            for row in rows:
                updated = connection.execute(
                    update(alert_delivery)
                    .where(
                        and_(
                            alert_delivery.c.id == row["id"],
                            alert_delivery.c.status == "pending",
                            or_(
                                alert_delivery.c.claimed_until.is_(None),
                                alert_delivery.c.claimed_until <= moment,
                            ),
                        )
                    )
                    .values(claimed_by=owner, claimed_until=lease_until)
                ).rowcount
                if updated != 1:
                    continue
                claimed.append(
                    PendingAlert(
                        id=int(row["id"]),
                        alert_type=str(row["alert_type"]),
                        subject=str(row["subject"]),
                        body=str(row["body"]),
                        attempts=int(row["attempts"]),
                        alert_id=None if row.get("alert_id") is None else int(row["alert_id"]),
                        episode_id=None if row.get("episode_id") is None else str(row["episode_id"]),
                    )
                )
        return tuple(claimed)

    def due(
        self,
        at: datetime,
        limit: int = 10,
        *,
        owner: str = "alert-worker",
    ) -> Sequence[PendingAlert]:
        return self.claim_pending(at, owner=owner, limit=limit)

    def deliver_claimed(
        self,
        alert: PendingAlert,
        *,
        owner: str,
        at: datetime,
        send: Callable[[], None],
    ) -> bool:
        """Revalidate a claim while serialising catalogue cleanup and send.

        The catalogue lives in the configuration store while delivery rows
        live in the application store. Taking a write lock on the claimed row
        before re-reading the catalogue closes the cross-store race when
        catalogue cleanup is held open until its configuration commit.
        """
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            condition = and_(
                alert_delivery.c.id == alert.id,
                alert_delivery.c.installation_id == self._installation_id,
                alert_delivery.c.status == "pending",
                alert_delivery.c.claimed_by == owner,
                alert_delivery.c.claimed_until > moment,
            )
            claimed = connection.execute(
                update(alert_delivery)
                .where(condition)
                # A no-op update obtains a row lock on PostgreSQL and a write
                # transaction on SQLite while retaining the lease deadline.
                .values(claimed_until=alert_delivery.c.claimed_until)
            ).rowcount
            if claimed != 1:
                return False
            with self._locked_type_enabled(alert.alert_type) as enabled:
                if not enabled:
                    connection.execute(
                        update(alert_delivery)
                        .where(alert_delivery.c.id == alert.id)
                        .values(
                            status="failed",
                            last_error="alert_type_disabled",
                            claimed_by=None,
                            claimed_until=None,
                        )
                    )
                    return False
                send()
        return True

    def mark_sent(
        self, delivery_id: int, at: datetime, *, owner: str | None = None
    ) -> bool:
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            condition = [alert_delivery.c.id == delivery_id]
            if owner is not None:
                condition.extend(
                    (
                        alert_delivery.c.claimed_by == owner,
                        alert_delivery.c.claimed_until > moment,
                    )
                )
            return (
                connection.execute(
                    update(alert_delivery)
                    .where(and_(*condition))
                    .values(
                        status="sent",
                        sent_at=moment,
                        attempts=alert_delivery.c.attempts + 1,
                        last_error=None,
                        claimed_by=None,
                        claimed_until=None,
                    )
                ).rowcount
                == 1
            )

    def mark_attempt_failed(
        self,
        delivery_id: int,
        *,
        attempts: int,
        next_attempt_at: datetime | None,
        error: str,
        at: datetime | None = None,
        owner: str | None = None,
    ) -> bool:
        moment = to_utc(at if at is not None else self._clock())
        with transaction(self._application, self._application_location) as connection:
            condition = [alert_delivery.c.id == delivery_id]
            if owner is not None:
                condition.append(alert_delivery.c.claimed_by == owner)
                condition.append(alert_delivery.c.claimed_until > moment)
            return (
                connection.execute(
                    update(alert_delivery)
                    .where(and_(*condition))
                    .values(
                        attempts=attempts,
                        status="pending" if next_attempt_at is not None else "failed",
                        next_attempt_at=(
                            to_utc(next_attempt_at)
                            if next_attempt_at is not None
                            else alert_delivery.c.next_attempt_at
                        ),
                        last_error=error[:512],
                        claimed_by=None,
                        claimed_until=None,
                    )
                ).rowcount
                == 1
            )

    def pending_count(self) -> int:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                return len(
                    connection.execute(
                        select(alert_delivery.c.id).where(
                            and_(
                                alert_delivery.c.installation_id == self._installation_id,
                                alert_delivery.c.status == "pending",
                            )
                        )
                    ).all()
                )

    # ------------------------------------------------------------------ inbox

    def notification(self, notification_id: int) -> AlertRecord | None:
        with self._application.connect() as connection:
            row = connection.execute(
                select(operator_notification).where(
                    and_(
                        operator_notification.c.id == notification_id,
                        operator_notification.c.installation_id == self._installation_id,
                    )
                )
            ).mappings().first()
        return None if row is None else _alert_from_row(row)

    def list_alerts(
        self,
        *,
        view: str = "active",
        limit: int = 50,
        cursor: str | None = None,
    ) -> AlertPage:
        if view not in {"active", "history", "all"}:
            raise ValueError("alert view must be active, history or all")
        applied = max(1, min(int(limit), 500))
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                query = select(operator_notification).where(
                    operator_notification.c.installation_id == self._installation_id
                )
                if view == "active":
                    query = query.where(
                        operator_notification.c.acknowledged_at.is_(None),
                        operator_notification.c.resolved_at.is_(None),
                    )
                elif view == "history":
                    query = query.where(
                        or_(
                            operator_notification.c.acknowledged_at.is_not(None),
                            operator_notification.c.resolved_at.is_not(None),
                        )
                    )
                if cursor:
                    created, identifier = _decode_cursor(cursor)
                    query = query.where(
                        or_(
                            operator_notification.c.opened_at < created,
                            and_(
                                operator_notification.c.opened_at == created,
                                operator_notification.c.id < identifier,
                            ),
                        )
                    )
                rows = connection.execute(
                    query.order_by(
                        operator_notification.c.opened_at.desc(),
                        operator_notification.c.id.desc(),
                    ).limit(applied + 1)
                ).mappings().all()
                active_rows = connection.execute(
                    select(operator_notification.c.severity).where(
                        and_(
                            operator_notification.c.installation_id == self._installation_id,
                            operator_notification.c.acknowledged_at.is_(None),
                            operator_notification.c.resolved_at.is_(None),
                        )
                    )
                ).scalars().all()
        has_more = len(rows) > applied
        rows = rows[:applied]
        next_cursor = None
        if has_more and rows:
            row = rows[-1]
            next_cursor = _encode_cursor(row["opened_at"], int(row["id"]))
        return AlertPage(
            items=tuple(_alert_from_row(row) for row in rows),
            limit_applied=applied,
            has_more=has_more,
            next_cursor=next_cursor,
            active_count=len(active_rows),
            maximum_severity=_max_severity(active_rows),
        )

    def notifications(
        self, *, include_acknowledged: bool = False, limit: int = 100
    ) -> tuple[AlertRecord, ...]:
        page = self.list_alerts(
            view="all" if include_acknowledged else "active", limit=limit
        )
        return page.items

    def acknowledge(self, notification_id: int, *, at: datetime) -> bool:
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            return (
                connection.execute(
                    update(operator_notification)
                    .where(
                        and_(
                            operator_notification.c.id == notification_id,
                            operator_notification.c.installation_id == self._installation_id,
                            operator_notification.c.acknowledged_at.is_(None),
                        )
                    )
                    .values(acknowledged_at=moment)
                ).rowcount
                == 1
            )

    def acknowledge_notification(self, notification_id: int, *, at: datetime | None = None) -> bool:
        return self.acknowledge(notification_id, at=at or datetime.now(timezone.utc))

    def active_summary(self) -> dict[str, Any]:
        page = self.list_alerts(view="active", limit=1)
        return {"count": page.active_count, "maximum_severity": page.maximum_severity}

    # ------------------------------------------------------------------ Push queue

    def queue_push_attempts_for_alert(self, alert_id: int) -> tuple[int, ...]:
        with transaction(self._application, self._application_location) as connection:
            row = connection.execute(
                select(operator_notification.c.episode_id).where(
                    and_(
                        operator_notification.c.id == alert_id,
                        operator_notification.c.installation_id == self._installation_id,
                    )
                )
            ).first()
            if row is None or row[0] is None:
                return ()
            attempts: list[int] = []
            subscriptions = connection.execute(
                select(web_push_subscription).where(
                    and_(
                        web_push_subscription.c.installation_id == self._installation_id,
                        web_push_subscription.c.status == "active",
                    )
                )
            ).mappings().all()
            for subscription in subscriptions:
                existing = connection.execute(
                    select(web_push_attempt.c.id).where(
                        and_(
                            web_push_attempt.c.alert_id == alert_id,
                            web_push_attempt.c.subscription_id == subscription["id"],
                        )
                    )
                ).scalar()
                if existing is None:
                    existing = connection.execute(
                        insert(web_push_attempt).values(
                            subscription_id=subscription["id"],
                            session_id=str(row[0]),
                            alert_id=alert_id,
                            status="pending",
                        )
                    ).inserted_primary_key[0]
                attempts.append(int(existing))
        return tuple(attempts)

    def pending_push_alert_ids(self) -> tuple[int, ...]:
        with self._application.connect() as connection:
            rows = connection.execute(
                select(web_push_attempt.c.alert_id)
                .where(
                    and_(
                        web_push_attempt.c.alert_id.is_not(None),
                        web_push_attempt.c.status.in_(("pending", "error")),
                        web_push_attempt.c.subscription_id.in_(
                            select(web_push_subscription.c.id).where(
                                web_push_subscription.c.installation_id
                                == self._installation_id
                            )
                        ),
                    )
                )
                .distinct()
                .order_by(web_push_attempt.c.alert_id)
            ).scalars().all()
        return tuple(int(value) for value in rows)


def _alert_from_row(row: Any) -> AlertRecord:
    opened = from_utc(row.get("opened_at") or row["created_at"])
    return AlertRecord(
        id=int(row["id"]),
        alert_type=str(row.get("alert_type") or row["kind"]),
        title=str(row["title"]),
        body=str(row["body"]),
        severity=str(row.get("severity") or "info"),
        episode_id=None if row.get("episode_id") is None else str(row["episode_id"]),
        session_id=None if row.get("session_id") is None else str(row["session_id"]),
        opened_at=opened,
        resolved_at=from_utc(row.get("resolved_at")),
        acknowledged_at=from_utc(row.get("acknowledged_at")),
    )


def _ensure_episode(connection, *, installation_id: int, alert_type: str):
    """Return the one durable episode row, creating it without a race."""
    _insert_ignore(
        connection,
        alert_episode,
        {
            "installation_id": installation_id,
            "alert_type": alert_type,
            "active": False,
        },
        conflict_columns=("installation_id", "alert_type"),
    )
    row = connection.execute(
        select(alert_episode.c.id, alert_episode.c.active).where(
            and_(
                alert_episode.c.installation_id == installation_id,
                alert_episode.c.alert_type == alert_type,
            )
        )
    ).first()
    if row is None:  # pragma: no cover - DB invariant
        raise RuntimeError("alert episode claim was not persisted")
    return row


def _insert_ignore(
    connection,
    table,
    values: dict[str, Any],
    *,
    conflict_columns: tuple[str, ...],
) -> None:
    """Insert a row once, using native conflict handling on supported stores."""
    dialect = connection.dialect.name
    if dialect == "sqlite":
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=list(conflict_columns)
        )
        connection.execute(statement)
        return
    if dialect == "postgresql":
        statement = postgresql_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=list(conflict_columns)
        )
        connection.execute(statement)
        return
    try:  # pragma: no cover - only SQLite and PostgreSQL are supported stores
        connection.execute(insert(table).values(**values))
    except IntegrityError:
        pass


def _max_severity(values: Sequence[Any]) -> str | None:
    rank = {"info": 1, "warning": 2, "critical": 3}
    names = [str(value) for value in values if value is not None]
    return max(names, key=lambda value: rank.get(value, 0), default=None)


def _encode_cursor(value: Any, identifier: int) -> str:
    if isinstance(value, datetime):
        value = to_utc(value).isoformat()
    payload = json.dumps([str(value), identifier], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, int]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw, identifier = json.loads(base64.urlsafe_b64decode(padded.encode()))
        instant = datetime.fromisoformat(str(raw))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return to_utc(instant), int(identifier)
    except (ValueError, TypeError, json.JSONDecodeError, IndexError) as exc:
        raise ValueError("invalid alert cursor") from exc


__all__ = ["AlertPage", "AlertRecord", "CLAIM_LEASE_SECONDS", "SqlAlertRepository"]
