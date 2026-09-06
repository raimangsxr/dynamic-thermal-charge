from datetime import timedelta

from tests.conftest import API_NOW, API_TOKEN, AUTH


def test_current_reports_controller_readiness_without_a_session(client):
    response = client.get("/api/v1/relay-test", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["session"] is None
    assert body["controller"]["state_is_current"] is False
    assert body["heaters"] == []


def test_start_delivers_credential_once_and_mutations_require_it(client, heartbeat):
    heartbeat.publish(API_NOW, degraded=False)
    response = client.post("/api/v1/relay-test", headers=AUTH)
    assert response.status_code == 202
    started = response.json()
    assert started["client_credential"]
    assert started["state_poll_seconds"] == 1
    assert started["lease_renew_seconds"] == 10
    current = client.get("/api/v1/relay-test", headers=AUTH).json()
    heater = current["heaters"][0]["id"]
    assert current["state_poll_seconds"] == 1
    assert current["lease_renew_seconds"] == 10
    denied = client.put(f"/api/v1/relay-test/{started['session_id']}/heaters/{heater}", headers=AUTH, json={"state": True})
    assert denied.status_code == 403
    accepted = client.put(f"/api/v1/relay-test/{started['session_id']}/heaters/{heater}", headers={**AUTH, "X-Relay-Test-Credential": started["client_credential"]}, json={"state": True})
    assert accepted.status_code == 409  # Controller has not made starting active yet.


def test_start_requires_a_recent_controller(client):
    response = client.post("/api/v1/relay-test", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["code"] == "controller_unavailable"


def test_start_rejects_a_stale_controller(client, heartbeat, api_clock):
    heartbeat.publish(API_NOW, degraded=False)
    api_clock.advance(seconds=31)

    response = client.post("/api/v1/relay-test", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["code"] == "controller_unavailable"


def test_command_is_rejected_when_the_controller_becomes_stale(client, heartbeat, initialised_store, api_clock):
    heartbeat.publish(API_NOW, degraded=False)
    started = client.post("/api/v1/relay-test", headers=AUTH).json()
    initialised_store.relay_tests.activate(started["session_id"], heartbeat.runner_id, API_NOW)
    heater_id = client.get(
        f"/api/v1/relay-test/{started['session_id']}",
        headers={**AUTH, "X-Relay-Test-Credential": started["client_credential"]},
    ).json()["heaters"][0]["id"]
    api_clock.advance(seconds=31)

    response = client.put(
        f"/api/v1/relay-test/{started['session_id']}/heaters/{heater_id}",
        headers={**AUTH, "X-Relay-Test-Credential": started["client_credential"]},
        json={"state": True},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "controller_unavailable"


def test_start_rejects_two_controllers(client, heartbeat, initialised_store, api_clock):
    heartbeat.publish(API_NOW, degraded=False)
    client.get("/api/v1/status", headers=AUTH)

    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    other = SqlHeartbeatPublisher(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5,
        driver_kind="gpio",
        started_at=API_NOW - timedelta(hours=5),
        runner_id="older-runner",
        location=initialised_store.location,
    )
    other.publish(api_clock.now, degraded=False)

    response = client.post("/api/v1/relay-test", headers=AUTH)

    assert response.status_code == 503
    assert response.json()["code"] == "controller_unavailable"


def test_start_returns_persisted_operation_timing(client, heartbeat, initialised_store):
    heartbeat.publish(API_NOW, degraded=False)
    repository = initialised_store.system_configuration
    revision = repository.current().revision
    repository.update_section(
        "operations",
        {
            "relay_test_lease_seconds": 45,
            "relay_test_state_poll_seconds": 2.5,
            "relay_test_lease_renew_seconds": 10,
        },
        expected_revision=revision,
        actor="test",
    )

    response = client.post("/api/v1/relay-test", headers=AUTH)

    assert response.status_code == 202
    assert response.json()["state_poll_seconds"] == 2.5
    assert response.json()["lease_renew_seconds"] == 10


def test_cors_allows_the_relay_test_credential_header(initialised_store, api_clock):
    from starlette.testclient import TestClient

    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.api.settings import ApiSettings

    app = create_app(
        settings=ApiSettings(token=API_TOKEN, cors_origins=("http://panel.test",)),
        store_factory=lambda: initialised_store,
        clock=api_clock,
    )
    response = TestClient(app).options(
        "/api/v1/relay-test",
        headers={
            "Origin": "http://panel.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Relay-Test-Credential",
        },
    )

    assert response.status_code == 200
    assert "x-relay-test-credential" in response.headers["access-control-allow-headers"].lower()
