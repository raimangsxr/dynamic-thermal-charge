"""Failure paths: FR-038 to FR-041, FR-039, SC-009.

Nothing here may produce a traceback, a hang, or an invented figure.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from starlette.testclient import TestClient

from dynamic_thermal_charge.persistence import ConfigStoreUnavailableError
from tests.conftest import API_TOKEN, AUTH


ALL_PATHS = [
    ("get", "/api/v1/status"),
    ("get", "/api/v1/config"),
    ("get", "/api/v1/config/heaters/salon"),
    ("get", "/api/v1/history/plans"),
    ("get", "/api/v1/history/forecasts"),
    ("get", "/api/v1/history/transitions"),
    ("post", "/api/v1/history/prune"),
]
WRITE_PATHS = [
    ("patch", "/api/v1/config", {"revision": 1, "field": "poll_seconds", "value": "6"}),
    ("patch", "/api/v1/config/heaters/salon", {"revision": 1, "field": "priority", "value": "5"}),
    ("post", "/api/v1/config/heaters", {"revision": 1, "id": "x", "power_kw": 1.0, "full_charge_hours": 7}),
]


def _broken_app(api_app, error: Exception):
    def _factory():
        raise error

    api_app.state.store_factory = _factory
    return TestClient(api_app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# FR-038: the database is unreachable
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("method", "path"), ALL_PATHS, ids=lambda v: str(v))
def test_an_unreachable_database_is_reported_cleanly(api_app, method, path):
    client = _broken_app(
        api_app,
        ConfigStoreUnavailableError(
            "the configuration database is unavailable (postgresql (remote) at "
            "server:5432, database dtc): connection refused"
        ),
    )
    response = getattr(client, method)(path, headers=AUTH)
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "store_unavailable"
    assert "Traceback" not in response.text
    assert "/private/var" not in response.text
    assert "sqlite:///" not in response.text


def test_an_invalid_store_url_is_reported_cleanly(api_app):
    from dynamic_thermal_charge.persistence.url import DatabaseUrlError

    client = _broken_app(api_app, DatabaseUrlError("DTC_DATABASE_URL is not set"))
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["code"] == "store_unavailable"


def test_no_state_is_invented_when_the_database_is_gone(api_app):
    client = _broken_app(api_app, ConfigStoreUnavailableError("gone"))
    body = client.get("/api/v1/status", headers=AUTH).json()
    assert "heaters" not in body, "a status payload was fabricated"
    assert body["code"] == "store_unavailable"


# --------------------------------------------------------------------------- #
# FR-039: the schema. Nothing is served, not even a read.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("method", "path"), ALL_PATHS, ids=lambda v: str(v))
def test_a_missing_schema_serves_nothing(client, initialised_store, method, path):
    """Not initialised: no read either, and it says what to run."""
    from dynamic_thermal_charge.persistence.schema import configuration_schema_version
    configuration_schema_version.drop(initialised_store.engine)
    response = getattr(client, method)(path, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["code"] == "schema_unusable"
    assert "db init" in response.json()["message"]


@pytest.mark.parametrize(("method", "path"), ALL_PATHS, ids=lambda v: str(v))
def test_a_schema_pending_migration_serves_nothing(client, initialised_store, method, path):
    from dynamic_thermal_charge.persistence.schema import configuration_schema_version
    with initialised_store.engine.begin() as connection:
        connection.execute(configuration_schema_version.update().values(revision=0))
    response = getattr(client, method)(path, headers=AUTH)
    assert response.status_code == 503
    assert response.json()["code"] == "schema_unusable"
    assert "db upgrade" in response.json()["message"]


def test_an_unknown_schema_serves_nothing(client, initialised_store):
    from dynamic_thermal_charge.persistence.schema import configuration_schema_version
    with initialised_store.engine.begin() as connection:
        connection.execute(configuration_schema_version.update().values(revision=9999))
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "schema_unusable"
    assert "does not understand" in body["message"]
    assert "update the service" in body["message"].lower()


@pytest.mark.parametrize(("method", "path", "payload"), WRITE_PATHS, ids=lambda v: str(v))
def test_no_write_is_offered_over_an_unusable_schema(
    client, initialised_store, method, path, payload
):
    from dynamic_thermal_charge.persistence.schema import configuration_schema_version
    with initialised_store.engine.begin() as connection:
        connection.execute(configuration_schema_version.update().values(revision=0))
    response = getattr(client, method)(path, headers=AUTH, json=payload)
    assert response.status_code == 503
    assert response.json()["code"] == "schema_unusable"


def test_the_api_never_migrates_the_schema(client, initialised_store):
    """Migrating from an HTTP request would let a client alter the structure."""
    from dynamic_thermal_charge.persistence import SchemaStatus
    from dynamic_thermal_charge.persistence.schema import configuration_schema_version
    with initialised_store.engine.begin() as connection:
        connection.execute(configuration_schema_version.update().values(revision=0))
    for method, path in ALL_PATHS:
        getattr(client, method)(path, headers=AUTH)
    assert initialised_store.gate.check() is SchemaStatus.BEHIND, (
        "the API migrated the schema by itself"
    )


# --------------------------------------------------------------------------- #
# Stored configuration that is invalid
# --------------------------------------------------------------------------- #

def test_invalid_stored_configuration_is_reported_with_the_field(client, initialised_store):
    with initialised_store.engine.begin() as connection:
        # Straight SQL, bypassing every validator, as external tampering would.
        connection.execute(text("UPDATE installation SET slot_minutes = 45"))
    response = client.get("/api/v1/config", headers=AUTH)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert "divisor of 60" in body["message"]


def test_no_configuration_at_all_is_distinguishable(store_env, api_settings, api_clock):
    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.persistence.bootstrap import initialise_at, open_store

    store = initialise_at(store_env, allow_seed=False)[0]
    app = create_app(
        settings=api_settings,
        store_factory=lambda: open_store(store_env),
        clock=api_clock,
    )
    response = TestClient(app).get("/api/v1/config", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["code"] == "no_configuration"
    assert "db init" in response.json()["message"]


# --------------------------------------------------------------------------- #
# FR-040: no error leaks anything
# --------------------------------------------------------------------------- #

def test_no_error_body_leaks_internals(client, initialised_store):
    """Walks every error code in the contract."""
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    responses = [
        client.get("/api/v1/status"),  # 401
        client.get("/api/v1/config/heaters/nope", headers=AUTH),  # 404
        client.patch(
            "/api/v1/config",
            headers=AUTH,
            json={"revision": 1, "field": "slot_minutes", "value": "45"},
        ),  # 422
        client.patch(
            "/api/v1/config",
            headers=AUTH,
            json={"revision": 99, "field": "poll_seconds", "value": "6"},
        ),  # 409
        client.get("/api/v1/history/plans?cursor=garbage", headers=AUTH),  # 400
    ]
    for response in responses:
        text_body = response.text
        assert "Traceback" not in text_body
        assert "sqlite:///" not in text_body
        assert "dtc.db" not in text_body
        assert "/private/var" not in text_body
        assert "site-packages" not in text_body
        assert API_TOKEN not in text_body
        # The uniform shape holds everywhere.
        body = response.json()
        assert set(body) == {"code", "message", "field", "heater_id"}


def test_an_unexpected_failure_becomes_a_clean_500(api_app):
    client = _broken_app(api_app, RuntimeError("something nobody predicted"))
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "something nobody predicted" not in body["message"], (
        "the internal message reached the client"
    )
    assert "Traceback" not in response.text


# --------------------------------------------------------------------------- #
# FR-041: bounded waits
# --------------------------------------------------------------------------- #

def test_the_engine_bounds_how_long_a_request_waits():
    """At the engine, not with a timer: a timer would not interrupt a blocked thread."""
    from dynamic_thermal_charge.api.dependencies import (
        CONNECT_TIMEOUT_SECONDS,
        POOL_TIMEOUT_SECONDS,
    )
    from dynamic_thermal_charge.persistence.engine import build_engine
    from dynamic_thermal_charge.persistence.url import parse_location

    assert CONNECT_TIMEOUT_SECONDS > 0 and POOL_TIMEOUT_SECONDS > 0
    engine = build_engine(
        parse_location("sqlite:///var/timeout-probe.db"),
        timeouts=(CONNECT_TIMEOUT_SECONDS, POOL_TIMEOUT_SECONDS),
    )
    assert engine.pool._timeout == POOL_TIMEOUT_SECONDS


def test_the_default_store_factory_applies_the_timeouts(monkeypatch, tmp_path):
    from dynamic_thermal_charge.api import _default_store_factory
    from dynamic_thermal_charge.api.dependencies import POOL_TIMEOUT_SECONDS
    from dynamic_thermal_charge.persistence.bootstrap import initialise_at
    from dynamic_thermal_charge.persistence.paths import StorePaths

    paths = StorePaths.in_directory(tmp_path / "default-store")
    initialise_at(paths, allow_seed=False)
    monkeypatch.setattr(StorePaths, "production", classmethod(lambda cls: paths))
    store = _default_store_factory()
    assert store.engine.pool._timeout == POOL_TIMEOUT_SECONDS
