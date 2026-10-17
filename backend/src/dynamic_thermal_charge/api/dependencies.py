"""Injectable edges: store, schema gate, clock and settings.

Every handler is a **synchronous** function. Starlette runs those in a thread
pool. An ``async def`` handler calling the synchronous repository would block the
event loop while waiting on a remote database, and the alternative -- SQLAlchemy's
asyncio API -- reintroduces greenlet, the one dependency with no armv7l wheel
(research D6).
"""

from __future__ import annotations

import logging
from threading import Event, Thread, current_thread
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
LIVENESS_CHECK_INTERVAL_SECONDS = 5.0


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
            "the configuration database is not initialised. Ask the administrator to initialise it "
            "on the host; the API never creates or migrates the schema",
        )
    if status is SchemaStatus.BEHIND:
        raise ApiError(
            503,
            CODE_SCHEMA_UNUSABLE,
            "the configuration database needs migrating. Ask the administrator to migrate it on "
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
    settings: ApiSettings = request.app.state.settings
    at = request.app.state.clock()
    lock = getattr(request.app.state, "liveness_lock", _NOOP_LOCK)
    with lock:
        view = _read_controller_view(request.app.state, store, settings, at)
        _detect_controller_alert(store, view, at)
    return view


class ControllerLivenessSupervisor:
    """Evaluate controller liveness without waiting for an HTTP request."""

    def __init__(
        self,
        store_factory: Callable[[], Store],
        *,
        settings: ApiSettings,
        clock: Callable[[], datetime],
        state,
        interval_seconds: float = LIVENESS_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._store_factory = store_factory
        self._settings = settings
        self._clock = clock
        self._state = state
        self._interval_seconds = max(0.1, float(interval_seconds))
        self._stop = Event()
        self._thread: Thread | None = None

    def run_cycle(self) -> None:
        """Run one bounded liveness/alert evaluation for deterministic tests."""
        store = self._store_factory()
        at = self._clock()
        lock = getattr(self._state, "liveness_lock", _NOOP_LOCK)
        with lock:
            view = _read_controller_view(self._state, store, self._settings, at)
            _detect_controller_alert(store, view, at)

    # ``cycle`` is a compact alias for embedders that already drive other
    # supervisors one tick at a time.
    cycle = run_cycle

    def run(self, max_cycles: int | None = None) -> None:
        cycles = 0
        while not self._stop.is_set() and (
            max_cycles is None or cycles < max_cycles
        ):
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Could not run controller liveness cycle")
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                self._stop.wait(self._interval_seconds)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self.run,
            name="dtc-api-liveness",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)
        self._thread = None


class _NoopLock:
    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False


_NOOP_LOCK = _NoopLock()


def _read_controller_view(state, store: Store, settings: ApiSettings, at: datetime):
    from .liveness import evaluate

    heartbeat = read_heartbeat(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    previous = getattr(state, "last_heartbeat", None)
    view = evaluate(
        heartbeat,
        at,
        override_seconds=settings.stale_seconds,
        previous=previous,
    )
    if heartbeat is not None:
        # Remembered so the next read can spot a second controller.
        state.last_heartbeat = heartbeat
        if view.multiple_controllers_suspected:
            logger.warning(
                "More than one controller appears to be running against this "
                "database. Two processes switching the same relays is an "
                "electrical hazard; check the deployment"
            )
    return view


def _detect_controller_alert(store: Store, view, at: datetime) -> None:
    """Open/resolve the liveness alert from the API process itself.

    The detector is deliberately attached to the read edge: even when the
    controller is stopped, the next API poll can persist the episode and drain
    both independent channels. Failures are isolated from the state endpoint.
    """
    try:
        from ..alerts import CONTROLLER_UNRESPONSIVE, build_alert_service

        alerts = build_alert_service(store)
        if alerts is None:
            return
        if not view.state_is_current or view.multiple_controllers_suspected:
            reason = (
                "latido obsoleto"
                if not view.state_is_current
                else "varios controladores sospechados"
            )
            alerts.raise_alert(
                CONTROLLER_UNRESPONSIVE,
                subject=f"[{store.repository.installation_name()}] Controlador sin respuesta",
                body=(
                    f"Instalación: {store.repository.installation_name()}\n"
                    f"Momento: {at.isoformat()}\n"
                    f"Causa: {reason}\n"
                    f"Último latido: {view.last_seen_at.isoformat() if view.last_seen_at else 'nunca'}\n"
                    f"Edad: {view.age_seconds if view.age_seconds is not None else 'sin dato'}"
                ),
            )
        else:
            alerts.clear_alert(CONTROLLER_UNRESPONSIVE)
        alerts.deliver_pending()
        from ..push import WebPushDelivery

        delivery = WebPushDelivery(store.calibration, clock=lambda: at)
        alert_repository = getattr(store, "alerts", None)
        for alert_id in getattr(
            alert_repository, "pending_push_alert_ids", lambda: ()
        )():
            delivery.deliver_pending(alert_id=alert_id)
    except Exception:
        logger.exception("Could not evaluate controller_unresponsive alert")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "ControllerLivenessSupervisor",
    "LIVENESS_CHECK_INTERVAL_SECONDS",
    "POOL_TIMEOUT_SECONDS",
    "controller_view",
    "get_clock",
    "get_settings",
    "get_store",
    "now",
    "usable_store",
    "utc_now",
]
