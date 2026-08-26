"""Shared fixtures.

No test may sleep in real time, reach the network, need PostgreSQL, or need a
Raspberry Pi (constitution principle V). Clocks and waits are injected; the
integration tests use a SQLite file under ``tmp_path`` rather than an in-memory
database, so WAL, foreign keys and migrations are actually exercised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.models import AppConfig
from dynamic_thermal_charge.persistence import (
    ConfigChange,
    ConfigStoreEmptyError,
    ConfigStoreUnavailableError,
    ForecastRef,
    PlanRef,
    PruneReport,
    SchemaStatus,
)
from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV


# --------------------------------------------------------------------------- #
# Store fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'dtc.db'}"


@pytest.fixture
def store_env(sqlite_url) -> dict[str, str]:
    return {DATABASE_URL_ENV: sqlite_url}


@pytest.fixture
def store(store_env):
    from dynamic_thermal_charge.persistence.bootstrap import open_store

    return open_store(store_env, clock=lambda: FIXED_NOW)


@pytest.fixture
def initialised_store(store):
    from dynamic_thermal_charge.persistence.bootstrap import initialise

    initialise(store)
    return store


@pytest.fixture
def recorder(initialised_store):
    from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder

    return SqlHistoryRecorder(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    )


# --------------------------------------------------------------------------- #
# API fixtures. The client runs the app in process over the ASGI transport: no
# port is ever opened (FR-048).
# --------------------------------------------------------------------------- #

API_TOKEN = "test-token-" + "z" * 32
AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def api_clock() -> "ControlledClock":
    return ControlledClock(API_NOW)


@pytest.fixture
def api_settings():
    from dynamic_thermal_charge.api.settings import ApiSettings

    return ApiSettings(token=API_TOKEN)


@pytest.fixture
def api_app(initialised_store, api_settings, api_clock, store_env):
    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.persistence.bootstrap import open_store

    return create_app(
        settings=api_settings,
        store_factory=lambda: open_store(store_env),
        clock=api_clock,
    )


@pytest.fixture
def client(api_app):
    from starlette.testclient import TestClient

    return TestClient(api_app)


@pytest.fixture
def heartbeat(initialised_store):
    """A publisher whose runner and start instant the test controls."""
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    return SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="gpio",
        started_at=API_NOW - timedelta(hours=3),
        runner_id="runner-a",
        location=initialised_store.location,
    )


def iter_routes(app) -> list[tuple[str, str, bool]]:
    """Every served route as (full path, method, in_schema), flattened.

    FastAPI 0.141 wraps an included router in ``_IncludedRouter``, so
    ``app.routes`` is not a flat list of routes carrying ``.path``. A test that
    assumed it was would find nothing and pass vacuously, which is worse than
    failing: it looks like a guard while guarding nothing.
    """
    found: list[tuple[str, str, bool]] = []
    visited: set[int] = set()

    def _walk(container, prefix: str) -> None:
        if id(container) in visited:
            return
        visited.add(id(container))
        for route in getattr(container, "routes", []):
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path and methods:
                in_schema = getattr(route, "include_in_schema", True)
                for method in methods:
                    if method not in ("HEAD", "OPTIONS"):
                        found.append((prefix + path, method.lower(), in_schema))
                continue
            context = getattr(route, "include_context", None)
            nested = getattr(context, "included_router", None) or getattr(
                route, "original_router", None
            )
            if nested is not None:
                _walk(nested, prefix + getattr(context, "prefix", ""))

    _walk(app, "")
    _walk(getattr(app, "router", None) or app, "")
    assert found, "no route was found: the walker is broken, not the app"
    return found


API_NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)
FIXED_NOW = datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Controlled clock and wait
# --------------------------------------------------------------------------- #

class ControlledClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, start: datetime = FIXED_NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


class ControlledWait:
    """Records requested delays instead of sleeping, and can advance a clock."""

    def __init__(self, clock: ControlledClock | None = None) -> None:
        self.delays: list[float] = []
        self._clock = clock

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if self._clock is not None:
            self._clock.advance(seconds=seconds)


@pytest.fixture
def clock() -> ControlledClock:
    return ControlledClock()


@pytest.fixture
def wait(clock) -> ControlledWait:
    return ControlledWait(clock)


# --------------------------------------------------------------------------- #
# Protocol doubles. Deliberately free of SQLAlchemy so core tests never load it.
# --------------------------------------------------------------------------- #

@dataclass
class FakeConfigRepository:
    """A configuration repository that can be made to fail deterministically."""

    config: AppConfig | None = None
    revision: int = 1
    fail_with: Exception | None = None
    #: number of remaining calls that should fail before recovering
    fail_times: int | None = None
    calls: int = 0

    def current(self) -> tuple[AppConfig, int]:
        self.calls += 1
        if self.fail_with is not None and (
            self.fail_times is None or self.calls <= self.fail_times
        ):
            raise self.fail_with
        if self.config is None:
            raise ConfigStoreEmptyError("no installation")
        return self.config, self.revision

    def set_field(self, revision, entity, entity_key, field, value) -> ConfigChange:
        raise NotImplementedError

    def add_heater(self, revision, heater) -> ConfigChange:
        raise NotImplementedError

    def remove_heater(self, revision, heater_id) -> ConfigChange:
        raise NotImplementedError

    def start_failing(self, error: Exception | None = None) -> None:
        self.fail_with = error or ConfigStoreUnavailableError("database unreachable")
        self.fail_times = None
        self.calls = 0

    def stop_failing(self) -> None:
        self.fail_with = None


@dataclass
class FakeHistoryRecorder:
    """Records what it was asked to store; can be made to fail on every write.

    Mirrors the contract's hard rule: no method ever propagates an exception.
    """

    forecasts: list[object] = field(default_factory=list)
    plans: list[tuple] = field(default_factory=list)
    transitions: list[tuple] = field(default_factory=list)
    prunes: list[tuple] = field(default_factory=list)
    failing: bool = False
    errors: int = 0

    def record_forecast(self, forecast) -> ForecastRef | None:
        if self.failing:
            self.errors += 1
            return None
        self.forecasts.append(forecast)
        return ForecastRef(id=len(self.forecasts))

    def record_plan(
        self, plan, forecast_ref, installation_revision, requested_minutes=None
    ) -> PlanRef | None:
        if self.failing:
            self.errors += 1
            return None
        self.plans.append((plan, forecast_ref, installation_revision, requested_minutes))
        return PlanRef(id=len(self.plans))

    def record_transition(self, heater_id, state, occurred_at, plan_ref=None) -> None:
        if self.failing:
            self.errors += 1
            return
        self.transitions.append((heater_id, state, occurred_at, plan_ref))

    def prune(self, now, retention_days) -> PruneReport:
        if self.failing:
            self.errors += 1
            return PruneReport(deleted={})
        self.prunes.append((now, retention_days))
        return PruneReport(deleted={})


@dataclass
class FakeSchemaGate:
    status: SchemaStatus = SchemaStatus.OK

    def check(self) -> SchemaStatus:
        return self.status


@pytest.fixture
def fake_repository() -> FakeConfigRepository:
    return FakeConfigRepository()


@pytest.fixture
def fake_history() -> FakeHistoryRecorder:
    return FakeHistoryRecorder()


# --------------------------------------------------------------------------- #
# PostgreSQL compatibility suite: skipped unless a server is offered
# --------------------------------------------------------------------------- #

POSTGRES_URL_ENV = "DTC_TEST_POSTGRES_URL"


def pytest_collection_modifyitems(config, items) -> None:
    if os.environ.get(POSTGRES_URL_ENV):
        return
    skip = pytest.mark.skip(
        reason=f"{POSTGRES_URL_ENV} is not set; PostgreSQL compatibility suite skipped"
    )
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)
