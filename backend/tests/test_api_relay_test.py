from tests.conftest import AUTH

def test_start_delivers_credential_once_and_mutations_require_it(client):
    response = client.post("/api/v1/relay-test", headers=AUTH)
    assert response.status_code == 202
    started = response.json()
    assert started["client_credential"]
    current = client.get("/api/v1/relay-test", headers=AUTH).json()
    heater = current["heaters"][0]["id"]
    denied = client.put(f"/api/v1/relay-test/{started['session_id']}/heaters/{heater}", headers=AUTH, json={"state": True})
    assert denied.status_code == 403
    accepted = client.put(f"/api/v1/relay-test/{started['session_id']}/heaters/{heater}", headers={**AUTH, "X-Relay-Test-Credential": started["client_credential"]}, json={"state": True})
    assert accepted.status_code == 409  # Controller has not made starting active yet.
