"""Durable alert queue, episode latch and catalogue activation."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import and_, insert, select, update
from sqlalchemy.engine import Engine

from ..alerts import ALERT_TYPES_BY_NAME, PendingAlert
from .engine import store_errors, transaction
from .mapping import to_utc
from .schema import alert_delivery, alert_episode, alert_type_config
from .url import StoreLocation


class SqlAlertRepository:
    """The alert half of the store: catalogue in configuration, queue in application.

    The catalogue only records deviations from the code registry, so a new alert
    type is enabled by default the moment it ships.
    """

    def __init__(
        self,
        configuration_engine: Engine,
        application_engine: Engine,
        installation_id: int,
        configuration_location: StoreLocation | None = None,
        application_location: StoreLocation | None = None,
    ) -> None:
        self._configuration = configuration_engine
        self._application = application_engine
        self._installation_id = installation_id
        self._configuration_location = configuration_location
        self._application_location = application_location

    # ----------------------------------------------------------------- #
    # Catalogue
    # ----------------------------------------------------------------- #

    def type_enabled(self, alert_type: str) -> bool:
        return self.enabled_types().get(alert_type, True)

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
            existing = connection.execute(
                select(alert_type_config.c.name).where(
                    alert_type_config.c.name == alert_type
                )
            ).first()
            if existing is None:
                connection.execute(
                    insert(alert_type_config).values(
                        name=alert_type, enabled=bool(enabled)
                    )
                )
            else:
                connection.execute(
                    update(alert_type_config)
                    .where(alert_type_config.c.name == alert_type)
                    .values(enabled=bool(enabled))
                )

    # ----------------------------------------------------------------- #
    # Episodes
    # ----------------------------------------------------------------- #

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

    def open_episode(
        self, alert_type: str, *, subject: str, body: str, at: datetime
    ) -> bool:
        """Atomically enqueue the first delivery and latch its episode."""
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            existing = connection.execute(
                select(alert_episode.c.id, alert_episode.c.active).where(
                    and_(
                        alert_episode.c.installation_id == self._installation_id,
                        alert_episode.c.alert_type == alert_type,
                    )
                )
            ).first()
            if existing is not None and bool(existing.active):
                return False
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
            )
            values = {
                "active": True,
                "since": moment,
                "last_enqueued_at": moment,
            }
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
                    .where(alert_episode.c.id == existing.id)
                    .values(**values)
                )
        return True

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
            values = {
                "active": bool(active),
                "since": moment if active else None,
            }
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

    # ----------------------------------------------------------------- #
    # Queue
    # ----------------------------------------------------------------- #

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

    def due(self, at: datetime, limit: int = 10) -> Sequence[PendingAlert]:
        moment = to_utc(at)
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                rows = (
                    connection.execute(
                        select(alert_delivery)
                        .where(
                            and_(
                                alert_delivery.c.installation_id == self._installation_id,
                                alert_delivery.c.status == "pending",
                                alert_delivery.c.next_attempt_at <= moment,
                            )
                        )
                        .order_by(
                            alert_delivery.c.next_attempt_at, alert_delivery.c.id
                        )
                        .limit(limit)
                    )
                    .mappings()
                    .all()
                )
        return tuple(
            PendingAlert(
                id=int(row["id"]),
                alert_type=str(row["alert_type"]),
                subject=str(row["subject"]),
                body=str(row["body"]),
                attempts=int(row["attempts"]),
            )
            for row in rows
        )

    def mark_sent(self, delivery_id: int, at: datetime) -> None:
        moment = to_utc(at)
        with transaction(self._application, self._application_location) as connection:
            connection.execute(
                update(alert_delivery)
                .where(alert_delivery.c.id == delivery_id)
                .values(
                    status="sent",
                    sent_at=moment,
                    attempts=alert_delivery.c.attempts + 1,
                    last_error=None,
                )
            )

    def mark_attempt_failed(
        self,
        delivery_id: int,
        *,
        attempts: int,
        next_attempt_at: datetime | None,
        error: str,
    ) -> None:
        """A failed attempt keeps the message pending until the attempts run out."""
        with transaction(self._application, self._application_location) as connection:
            connection.execute(
                update(alert_delivery)
                .where(alert_delivery.c.id == delivery_id)
                .values(
                    attempts=attempts,
                    status="pending" if next_attempt_at is not None else "failed",
                    next_attempt_at=(
                        to_utc(next_attempt_at)
                        if next_attempt_at is not None
                        else alert_delivery.c.next_attempt_at
                    ),
                    last_error=error[:512],
                )
            )

    def pending_count(self) -> int:
        with store_errors(self._application_location):
            with self._application.connect() as connection:
                rows = connection.execute(
                    select(alert_delivery.c.id).where(
                        and_(
                            alert_delivery.c.installation_id == self._installation_id,
                            alert_delivery.c.status == "pending",
                        )
                    )
                ).all()
        return len(rows)


__all__ = ["SqlAlertRepository"]
