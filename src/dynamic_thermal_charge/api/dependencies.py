"""Injectable edges: store, schema gate, clock and settings.

Every handler is a **synchronous** function. Starlette runs those in a thread
pool. An ``async def`` handler calling the synchronous repository would block the
event loop while waiting on a remote database, and the alternative -- SQLAlchemy's
asyncio API -- reintroduces greenlet, the one dependency with no armv7l wheel
(research D6).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, Request

from ..persistence import SchemaStatus
from ..persistence.bootstrap import Store
from ..persistence.heartbeat import read_heartbeat
from .errors import ApiError, CODE_SCHEMA_UNUSABLE
from .settings import ApiSettings


logger = logging.getLogger(__name__)

#: Bounded so a request never hangs waiting on the database (FR-041). Applied at
#: the engine, not with a timer: a timer would not interrupt a blocked thread.
CONNECT_TIMEOUT_SECONDS = 5
POOL_TIMEOUT_SECONDS = 5


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def get_clock(request: Request) -> Callable[[], datetime]:
    return request.app.state.clock


def now(request: Request) -> datetime:
    return request.app.state.clock()


def get_store(request: Request) -> Store:
    return request.app.state.store_factory()


def usable_store(store: Store = Depends(get_store)) -> Store:
    """The store, or refuse to serve.

    With a schema the API does not understand, **nothing** is served, not even a
    read: a column reinterpreted would produce a panel showing the wrong maximum
    power. With a schema pending migration, nothing either -- migrating is
    maintenance, and the API never does it: doing so from an HTTP request would
    let a client alter the structure of the database.
    """
    status = store.gate.check()
    if status is SchemaStatus.OK:
        return store
    if status is SchemaStatus.MISSING:
        raise ApiError(
            503,
            CODE_SCHEMA_UNUSABLE,
            "the configuration database is not initialised. Run 'dtc db init' on "
            "the host; the API never creates or migrates the schema",
        )
    if status is SchemaStatus.BEHIND:
        raise ApiError(
            503,
            CODE_SCHEMA_UNUSABLE,
            "the configuration database needs migrating. Run 'dtc db upgrade' on "
            "the host; the API never migrates the schema itself",
        )
    raise ApiError(
        503,
        CODE_SCHEMA_UNUSABLE,
        "the configuration database is at a schema revision this service does not "
        "understand. It was migrated by a newer build; update the service. Nothing "
        "is served over a schema that cannot be interpreted",
    )


def controller_view(request: Request, store: Store = Depends(usable_store)):
    """Evaluate what may be claimed about the controller right now."""
    from .liveness import evaluate

    settings: ApiSettings = request.app.state.settings
    heartbeat = read_heartbeat(
        store.engine, store.repository.installation_id(), store.location
    )
    previous = getattr(request.app.state, "last_heartbeat", None)
    view = evaluate(
        heartbeat,
        request.app.state.clock(),
        override_seconds=settings.stale_seconds,
        previous=previous,
    )
    if heartbeat is not None:
        # Remembered so the next read can spot a second controller.
        request.app.state.last_heartbeat = heartbeat
        if view.multiple_controllers_suspected:
            logger.warning(
                "More than one controller appears to be running against this "
                "database. Two processes switching the same relays is an "
                "electrical hazard; check the deployment"
            )
    return view


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "POOL_TIMEOUT_SECONDS",
    "controller_view",
    "get_clock",
    "get_settings",
    "get_store",
    "now",
    "usable_store",
    "utc_now",
]
