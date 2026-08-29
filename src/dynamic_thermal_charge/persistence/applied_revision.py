"""Observable per-process adoption of system configuration revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from .engine import transaction
from .mapping import from_utc, to_utc
from .schema import process_applied_revision
from .url import StoreLocation


ALLOWED_PROCESSES = frozenset({"api", "controller", "mqtt"})
ALLOWED_STATES = frozenset({"applied", "pending_apply", "pending_restart"})


class AppliedRevisionRepository:
    def __init__(
        self,
        engine: Engine,
        location: StoreLocation | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._location = location
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(
        self,
        process: str,
        *,
        applied_revision: int,
        desired_revision: int,
        state: str,
    ) -> None:
        if process not in ALLOWED_PROCESSES:
            raise ValueError(f"unknown process {process!r}")
        if state not in ALLOWED_STATES:
            raise ValueError(f"unknown applied-revision state {state!r}")
        if min(applied_revision, desired_revision) < 0:
            raise ValueError("configuration revisions cannot be negative")
        if applied_revision > desired_revision:
            raise ValueError("applied revision cannot exceed desired revision")
        if state == "applied" and applied_revision != desired_revision:
            raise ValueError("an applied process must match the desired revision")
        with transaction(self._engine, self._location) as connection:
            connection.execute(
                delete(process_applied_revision).where(
                    process_applied_revision.c.process == process
                )
            )
            connection.execute(
                insert(process_applied_revision).values(
                    process=process,
                    applied_revision=applied_revision,
                    desired_revision=desired_revision,
                    state=state,
                    updated_at=to_utc(self._clock()),
                )
            )

    def statuses(self) -> dict[str, dict[str, object]]:
        with self._engine.connect() as connection:
            rows = connection.execute(select(process_applied_revision)).mappings().all()
        return {
            str(row["process"]): {
                "applied_revision": int(row["applied_revision"]),
                "desired_revision": int(row["desired_revision"]),
                "state": str(row["state"]),
                "updated_at": from_utc(row["updated_at"]),
            }
            for row in rows
        }


__all__ = ["ALLOWED_PROCESSES", "ALLOWED_STATES", "AppliedRevisionRepository"]
