"""The controller's proof of life.

The only thing that lets the API tell "this is happening now" from "this is the
last thing anyone knew". Without it, two separate processes communicating only
through a database mean the API would read the last recorded transition and
present it as current even with the controller dead -- showing heaters as
charging when they are not.

**Hard rule**: ``publish`` never propagates an exception. A write failure is
logged and the control loop carries on. The API will then mark the state as not
current, which is the honest outcome.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from . import Heartbeat, PlanRef
from .mapping import from_utc, to_utc
from .schema import controller_heartbeat
from .url import StoreLocation


logger = logging.getLogger(__name__)


class SqlHeartbeatPublisher:
    """Publishes into the single heartbeat row of an installation.

    ``runner_id`` and ``started_at`` are fixed when this object is built, i.e.
    once per controller process. That is what makes a second controller
    detectable: both share the row, so without a per-process marker they would
    look like one healthy controller (FR-053).
    """

    def __init__(
        self,
        engine: Engine,
        installation_id: int,
        poll_seconds: float,
        driver_kind: str,
        started_at: datetime | None = None,
        runner_id: str | None = None,
        location: StoreLocation | None = None,
    ) -> None:
        self._engine = engine
        self._installation_id = installation_id
        self._poll_seconds = poll_seconds
        self._driver_kind = driver_kind
        self._started_at = started_at or datetime.now(timezone.utc)
        self._runner_id = runner_id or secrets.token_hex(16)
        self._location = location

    @property
    def runner_id(self) -> str:
        return self._runner_id

    def publish(
        self,
        now: datetime,
        degraded: bool,
        plan_ref: PlanRef | None = None,
    ) -> None:
        try:
            values = {
                "updated_at": to_utc(now),
                "started_at": to_utc(self._started_at),
                "degraded": degraded,
                "plan_id": None if plan_ref is None else plan_ref.id,
                # The cadence this process is really running with, not the one
                # currently stored: the configuration may have changed since it
                # started, and the API derives the tolerance from this value.
                "poll_seconds": self._poll_seconds,
                "driver_kind": self._driver_kind,
                "runner_id": self._runner_id,
            }
            with self._engine.begin() as connection:
                updated = connection.execute(
                    update(controller_heartbeat)
                    .where(
                        controller_heartbeat.c.installation_id == self._installation_id
                    )
                    .values(**values)
                ).rowcount
                if not updated:
                    connection.execute(
                        insert(controller_heartbeat).values(
                            installation_id=self._installation_id, **values
                        )
                    )
        except Exception:
            logger.error(
                "Could not publish the controller heartbeat; control continues. The "
                "API will report the output state as not current until this "
                "recovers",
                exc_info=True,
            )

    def read(self) -> Heartbeat | None:
        return read_heartbeat(self._engine, self._installation_id, self._location)


def read_heartbeat(
    engine: Engine,
    installation_id: int,
    location: StoreLocation | None = None,
) -> Heartbeat | None:
    """Read the stored heartbeat. Used by the API, not by the controller."""
    from .engine import store_errors

    with store_errors(location):
        with engine.connect() as connection:
            row = (
                connection.execute(
                    select(controller_heartbeat).where(
                        controller_heartbeat.c.installation_id == installation_id
                    )
                )
                .mappings()
                .first()
            )
    if row is None:
        return None
    return Heartbeat(
        updated_at=from_utc(row["updated_at"]),
        started_at=from_utc(row["started_at"]),
        degraded=bool(row["degraded"]),
        poll_seconds=float(row["poll_seconds"]),
        driver_kind=str(row["driver_kind"]),
        runner_id=str(row["runner_id"]),
        plan_id=None if row["plan_id"] is None else int(row["plan_id"]),
    )


__all__ = ["SqlHeartbeatPublisher", "read_heartbeat"]
