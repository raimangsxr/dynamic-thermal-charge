"""A safe, bounded projection of controller logging for the web panel."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine

from .mapping import from_utc, to_utc
from .schema import controller_log_event
from .url import StoreLocation

DEFAULT_MAX_EVENTS = 1000
MAX_PAGE_SIZE = 200
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ControllerLogHandler(logging.Handler):
    """Logging handler which never lets database trouble affect control."""
    def __init__(self, engine: Engine, installation_id: int, location: StoreLocation | None = None,
                 max_events: int = DEFAULT_MAX_EVENTS) -> None:
        super().__init__()
        self._engine, self._installation_id, self._location = engine, installation_id, location
        self._max_events = min(max(10, max_events), 100_000)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()[:2048]
            with self._engine.begin() as connection:
                connection.execute(insert(controller_log_event).values(
                    installation_id=self._installation_id,
                    occurred_at=to_utc(datetime.fromtimestamp(record.created, timezone.utc)),
                    level=record.levelname[:16], logger=record.name[:160], message=message,
                ))
                cutoff = connection.execute(select(controller_log_event.c.id).where(
                    controller_log_event.c.installation_id == self._installation_id
                ).order_by(controller_log_event.c.id.desc()).offset(self._max_events).limit(1)).scalar()
                if cutoff is not None:
                    connection.execute(delete(controller_log_event).where(
                        (controller_log_event.c.installation_id == self._installation_id)
                        & (controller_log_event.c.id <= cutoff)
                    ))
        except Exception:
            self.handleError(record)


class SqlControllerLogReader:
    def __init__(self, engine: Engine, installation_id: int, location: StoreLocation | None = None) -> None:
        self._engine, self._installation_id, self._location = engine, installation_id, location

    def events(self, *, limit: int = 100, before_id: int | None = None, after_id: int | None = None,
               level: str | None = None, query: str | None = None) -> dict:
        from .engine import store_errors
        size = min(max(1, limit), MAX_PAGE_SIZE)
        stmt = select(controller_log_event).where(controller_log_event.c.installation_id == self._installation_id)
        if before_id is not None: stmt = stmt.where(controller_log_event.c.id < before_id)
        if after_id is not None: stmt = stmt.where(controller_log_event.c.id > after_id)
        if level is not None: stmt = stmt.where(controller_log_event.c.level == level)
        if query: stmt = stmt.where(controller_log_event.c.message.ilike(f"%{query}%"))
        with store_errors(self._location):
            with self._engine.connect() as connection:
                rows = connection.execute(stmt.order_by(controller_log_event.c.id.desc()).limit(size + 1)).mappings().all()
        has_more = len(rows) > size
        rows = rows[:size]
        return {"items": [{"id": int(row["id"]), "occurred_at": from_utc(row["occurred_at"]), "level": row["level"], "logger": row["logger"], "message": row["message"]} for row in rows],
                "limit_applied": size, "has_more": has_more, "next_before_id": int(rows[-1]["id"]) if has_more and rows else None}
