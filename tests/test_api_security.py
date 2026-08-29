"""Authentication: FR-007 to FR-012, FR-052. And settings: FR-006, FR-044."""

from __future__ import annotations

import logging

import pytest

from dynamic_thermal_charge.api.settings import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MINIMUM_TOKEN_LENGTH,
    ApiSettings,
    ApiSettingsError,
    settings_from_repository,
)
from tests.conftest import API_TOKEN, AUTH


# --------------------------------------------------------------------------- #
# Settings: restrictive by default (FR-006, FR-044)
# --------------------------------------------------------------------------- #

def _configure_token(store, token="v" * 40):
    from dynamic_thermal_charge.persistence.secret_digest import digest_secret
    from dynamic_thermal_charge.persistence.system_configuration import SecretAction, SecretMutation
    repository = store.system_configuration
    revision = repository.current().revision
    repository.update_section(
        "api", {}, expected_revision=revision,
        secret_mutations={"admin_token_digest": SecretMutation(SecretAction.REPLACE, digest_secret(token))},
        actor="test",
    )


def test_settings_defaults_are_restrictive(initialised_store):
    _configure_token(initialised_store)
    settings = settings_from_repository(initialised_store.system_configuration)
    assert settings.host == DEFAULT_HOST == "127.0.0.1"
    assert settings.port == DEFAULT_PORT
    assert settings.cors_origins == (), "a cross-origin client is allowed by default"
    assert settings.exposed_beyond_localhost is False
    assert settings.stale_seconds is None


def test_exposing_the_api_takes_a_deliberate_persisted_edit(initialised_store):
    _configure_token(initialised_store)
    repository = initialised_store.system_configuration
    revision = repository.current().revision
    repository.update_section("api", {"host": "0.0.0.0"}, expected_revision=revision, actor="test")
    settings = settings_from_repository(repository)
    assert settings.exposed_beyond_localhost is True


@pytest.mark.parametrize("token", ["", "   ", "short", "x" * (MINIMUM_TOKEN_LENGTH - 1), "x" * 32])
def test_an_unusable_clear_token_refuses_to_start(token):
    """FR-011: the API must never end up listening without real protection."""
    with pytest.raises(ApiSettingsError) as error:
        ApiSettings(token=token)
    assert "token" in str(error.value)


def test_missing_persisted_digest_starts_only_the_onboarding_surface(initialised_store):
    settings = settings_from_repository(initialised_store.system_configuration)
    assert settings.configured is False
    assert settings.accepts("anything") is False


def test_a_token_of_the_minimum_length_is_accepted():
    ApiSettings(token="a1b2" * 8)


# --------------------------------------------------------------------------- #
# The credential gate (FR-007, FR-009)
# --------------------------------------------------------------------------- #

PROTECTED = [
    ("get", "/api/v1/status"),
    ("get", "/api/v1/config"),
    ("get", "/api/v1/config/heaters/salon"),
    ("get", "/api/v1/history/plans"),
    ("get", "/api/v1/history/forecasts"),
    ("get", "/api/v1/history/transitions"),
    ("post", "/api/v1/history/prune"),
    ("get", "/docs"),
    ("get", "/openapi.json"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=lambda v: str(v))
def test_no_operation_runs_without_a_credential(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=lambda v: str(v))
def test_no_operation_runs_with_a_wrong_credential(client, method, path):
    response = getattr(client, method)(
        path, headers={"Authorization": "Bearer wrong-" + "w" * 40}
    )
    assert response.status_code == 401


def test_an_absent_and_a_wrong_credential_are_indistinguishable(client):
    """FR-009: a caller must learn nothing from the difference."""
    absent = client.get("/api/v1/status")
    wrong = client.get(
        "/api/v1/status", headers={"Authorization": "Bearer " + "w" * 40}
    )
    assert absent.status_code == wrong.status_code == 401
    assert absent.json() == wrong.json()
    assert absent.headers.get("www-authenticate") == wrong.headers.get(
        "www-authenticate"
    )


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Basic abc",
        f"Token {API_TOKEN}",
        API_TOKEN,
        "Bearer",
        "Bearer ",
    ],
)
def test_a_malformed_authorization_header_is_rejected(client, header):
    assert client.get("/api/v1/status", headers={"Authorization": header}).status_code == 401


def test_the_correct_credential_works(client):
    assert client.get("/api/v1/status", headers=AUTH).status_code == 200


# --------------------------------------------------------------------------- #
# FR-010: the comparison must be constant time
# --------------------------------------------------------------------------- #

def test_the_comparison_goes_through_compare_digest(monkeypatch):
    """Verified by inspection, NOT by timing.

    A timing test would be non-deterministic, and principle V forbids that. The
    property is guaranteed by construction, so construction is what gets checked.
    """
    import secrets as secrets_module

    from dynamic_thermal_charge.api import security

    calls: list[tuple] = []
    real = secrets_module.compare_digest

    def _recording(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(security.secrets, "compare_digest", _recording)
    assert security.tokens_match("abc", "abc") is True
    assert security.tokens_match("abc", "abd") is False
    assert len(calls) == 2, "the token comparison bypassed compare_digest"
    # Encoded, so a length difference cannot leak either.
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls)


def test_a_length_difference_does_not_short_circuit():
    from dynamic_thermal_charge.api.security import tokens_match

    assert tokens_match("a" * 40, "a" * 39) is False
    assert tokens_match("", "a") is False


# --------------------------------------------------------------------------- #
# FR-008, FR-012: the token never leaks
# --------------------------------------------------------------------------- #

def test_a_rejected_attempt_is_logged_without_the_token(client, caplog):
    offered = "leaked-token-" + "q" * 30
    with caplog.at_level(logging.WARNING):
        client.get("/api/v1/status", headers={"Authorization": f"Bearer {offered}"})
    assert "Rejected unauthorized request" in caplog.text
    assert offered not in caplog.text, "the offered token was written to the log"
    assert "/api/v1/status" in caplog.text


def test_the_configured_token_never_appears_in_a_response(client):
    for method, path in PROTECTED:
        for headers in ({}, AUTH):
            response = getattr(client, method)(path, headers=headers)
            assert API_TOKEN not in response.text, f"{path} leaked the token"


def test_the_configured_token_never_appears_in_the_description(client):
    response = client.get("/openapi.json", headers=AUTH)
    assert response.status_code == 200
    assert API_TOKEN not in response.text


# --------------------------------------------------------------------------- #
# FR-052: the health check, the one exception, deliberately mute
# --------------------------------------------------------------------------- #

def test_health_answers_without_a_credential(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reveals_nothing_about_the_installation(client):
    body = client.get("/health").text.lower()
    for leak in ("salon", "sqlite", "revision", "schema", "installation", "heater"):
        assert leak not in body, f"the health check revealed {leak!r}"


def test_health_answers_even_with_the_database_gone(api_app, initialised_store):
    """It reports the process, not the installation."""
    from starlette.testclient import TestClient

    from dynamic_thermal_charge.persistence import ConfigStoreUnavailableError

    def _broken():
        raise ConfigStoreUnavailableError("gone")

    api_app.state.store_factory = _broken
    assert TestClient(api_app).get("/health").status_code == 200


def test_the_documentation_requires_a_credential(client):
    """It enumerates the whole surface of the API; nobody needs that unauthed."""
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/docs", headers=AUTH).status_code == 200
    assert client.get("/openapi.json", headers=AUTH).status_code == 200


# --------------------------------------------------------------------------- #
# FR-044: the positive cross-origin case. The frontend of phase 3 depends on it.
# --------------------------------------------------------------------------- #

def test_a_declared_origin_gets_the_headers_a_browser_needs(
    initialised_store, store_env, api_clock
):
    from starlette.testclient import TestClient

    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.api.settings import ApiSettings
    from dynamic_thermal_charge.persistence.bootstrap import open_store

    origin = "http://localhost:4200"
    app = create_app(
        settings=ApiSettings(token=API_TOKEN, cors_origins=(origin,)),
        store_factory=lambda: open_store(store_env),
        clock=api_clock,
    )
    client = TestClient(app)
    response = client.get("/api/v1/status", headers={**AUTH, "Origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_an_undeclared_origin_gets_nothing(initialised_store, store_env, api_clock):
    from starlette.testclient import TestClient

    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.api.settings import ApiSettings
    from dynamic_thermal_charge.persistence.bootstrap import open_store

    app = create_app(
        settings=ApiSettings(token=API_TOKEN, cors_origins=("http://allowed.lan",)),
        store_factory=lambda: open_store(store_env),
        clock=api_clock,
    )
    response = TestClient(app).get(
        "/api/v1/status", headers={**AUTH, "Origin": "http://evil.example"}
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_with_no_origin_declared_no_cross_origin_headers_appear(client):
    response = client.get(
        "/api/v1/status", headers={**AUTH, "Origin": "http://localhost:4200"}
    )
    assert response.headers.get("access-control-allow-origin") is None
