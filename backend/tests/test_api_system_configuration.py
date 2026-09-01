from __future__ import annotations

from fastapi.testclient import TestClient

from dynamic_thermal_charge.api import create_app
from dynamic_thermal_charge.persistence.bootstrap import initialise_at, open_store
from dynamic_thermal_charge.persistence.paths import StorePaths
from tests.conftest import AUTH


def test_deployment_token_skips_onboarding(tmp_path):
    paths = StorePaths.in_directory(tmp_path / "deployment-token")
    token = "deployment-token-" + "a" * 32
    store, _report, onboarding_token = initialise_at(paths, admin_token=token)
    assert onboarding_token is None
    store.context.close()

    app = create_app(store_factory=lambda: open_store(paths))
    client = TestClient(app)
    assert client.get("/api/v1/onboarding/status").json()["required"] is False
    assert client.get(
        "/api/v1/config", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200


def test_onboarding_is_one_use_and_enables_persisted_authentication(tmp_path):
    paths = StorePaths.in_directory(tmp_path / "onboarding")
    _store, _report, onboarding_token = initialise_at(paths, allow_seed=True)
    assert onboarding_token
    app = create_app(store_factory=lambda: open_store(paths))
    client = TestClient(app)

    assert client.get("/api/v1/onboarding/status").json()["required"] is True
    assert client.get("/api/v1/config").status_code == 401
    assert client.post(
        "/api/v1/onboarding/complete",
        json={"onboarding_credential": "wrong", "administrator_token": "a" * 40},
    ).status_code == 401

    response = client.post(
        "/api/v1/onboarding/complete",
        json={"onboarding_credential": onboarding_token, "administrator_token": "a" * 40},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/onboarding/status").json()["required"] is False
    assert client.get(
        "/api/v1/config", headers={"Authorization": f"Bearer {'a' * 40}"}
    ).status_code == 200
    assert client.post(
        "/api/v1/onboarding/complete",
        json={"onboarding_credential": onboarding_token, "administrator_token": "b" * 40},
    ).status_code == 401


def test_system_sections_are_allow_listed_revisioned_and_secret_free(client):
    snapshot = client.get("/api/v1/system/configuration", headers=AUTH)
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert "value" not in str(body["secrets"])
    revision = body["revision"]

    changed = client.patch(
        "/api/v1/system/configuration/mqtt",
        headers=AUTH,
        json={
            "expected_revision": revision,
            "values": {"enabled": True, "host": "broker.local"},
            "secrets": {},
        },
    )
    assert changed.status_code == 200
    assert changed.json()["revision"] == revision + 1
    assert changed.json()["sections"]["mqtt"]["host"] == "broker.local"

    conflict = client.patch(
        "/api/v1/system/configuration/mqtt",
        headers=AUTH,
        json={"expected_revision": revision, "values": {"port": 1884}},
    )
    assert conflict.status_code == 409


def test_weather_system_section_round_trips_all_fields_and_secret(client):
    snapshot = client.get("/api/v1/system/configuration", headers=AUTH).json()
    response = client.patch(
        "/api/v1/system/configuration/weather",
        headers=AUTH,
        json={
            "expected_revision": snapshot["revision"],
            "values": {
                "provider": "aemet",
                "municipality_code": "28079",
                "timeout_seconds": 12.5,
                "simulated_average_temperature_c": 9,
                "simulated_minimum_temperature_c": 4,
                "fallback_average_temperature_c": 7,
                "fallback_minimum_temperature_c": 1,
                "retry_minutes": 20,
                "refresh_minutes": 240,
            },
            "secrets": {"aemet_api_key": {"action": "replace", "value": "secret-key"}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sections"]["weather"]["refresh_minutes"] == 240
    assert body["secrets"]["aemet_api_key"]["configured"] is True
    assert "secret-key" not in response.text


def test_aemet_system_update_without_municipality_or_secret_is_atomic(client):
    snapshot = client.get("/api/v1/system/configuration", headers=AUTH).json()
    response = client.patch(
        "/api/v1/system/configuration/weather",
        headers=AUTH,
        json={
            "expected_revision": snapshot["revision"],
            "values": {"provider": "aemet", "municipality_code": ""},
            "secrets": {"aemet_api_key": {"action": "clear"}},
        },
    )
    assert response.status_code == 422
    current = client.get("/api/v1/system/configuration", headers=AUTH).json()
    assert current["revision"] == snapshot["revision"]
    assert current["sections"]["weather"]["provider"] == "simulated"


def test_topology_and_catalog_never_expose_locator_credentials(client):
    topology = client.get("/api/v1/system/topology", headers=AUTH)
    catalog = client.get("/api/v1/system/catalog", headers=AUTH)
    assert topology.status_code == catalog.status_code == 200
    assert topology.json()["mode"] == "normal"
    assert "password" not in topology.text.lower()
    assert catalog.json()["activation"]["database.driver"] == "restart"
