"""Reading and editing configuration over HTTP: FR-021 to FR-031."""

from __future__ import annotations

import pytest

from tests.conftest import API_TOKEN, AUTH


def _config(client) -> dict:
    response = client.get("/api/v1/config", headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _patch(client, field, value, revision=None, heater=None):
    if revision is None:
        revision = _config(client)["config_revision"]
    path = "/api/v1/config" if heater is None else f"/api/v1/config/heaters/{heater}"
    return client.patch(
        path, headers=AUTH, json={"revision": revision, "field": field, "value": value}
    )


# --------------------------------------------------------------------------- #
# Reading (FR-021, FR-022)
# --------------------------------------------------------------------------- #

def test_the_whole_configuration_is_readable(client):
    body = _config(client)
    assert body["config_revision"] == 1
    assert body["schema_revision"] == "0008_automatic_charge_planning"
    assert body["max_total_power_kw"] == 5.2
    assert body["slot_minutes"] == 30
    assert body["retention_days"] == 365
    assert body["indoor_max_age_minutes"] == 30
    assert body["indoor_min_plausible_c"] == -20
    assert body["indoor_max_plausible_c"] == 50
    assert [h["id"] for h in body["heaters"]] == [
        "salon",
        "entrada",
        "habitaciones",
        "buhardilla",
    ]
    assert body["schedule"]["start_time"] == "00:00"
    assert body["schedule"]["weekdays"] == [0, 1, 2, 3, 4, 5, 6]


def test_one_heater_is_readable(client):
    response = client.get("/api/v1/config/heaters/salon", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "salon"
    assert body["power_kw"] == 2.8
    assert body["output"] == {"kind": "gpio", "pin": 17, "active_high": False}
    assert body["thermal"]["target_temperature_c"] == 21.0
    assert body["thermal"]["thermal_loss_c_per_hour"] == 0.0


def test_an_unknown_heater_lists_the_existing_ones(client):
    response = client.get("/api/v1/config/heaters/cocina", headers=AUTH)
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert "cocina" in body["message"]
    assert "salon" in body["message"]


def test_the_weather_block_gives_the_variable_name_not_the_key(client, monkeypatch):
    """FR-022."""
    monkeypatch.setenv("AEMET_API_KEY", "the-real-secret-value")
    body = _config(client)
    assert body["weather"]["api_key_env"] == "AEMET_API_KEY"
    assert "the-real-secret-value" not in str(body)


def test_no_response_ever_carries_the_connection_string_or_the_token(client):
    """The guard that makes FR-022 more than a promise."""
    paths = [
        "/api/v1/status",
        "/api/v1/config",
        "/api/v1/config/heaters/salon",
        "/api/v1/history/plans",
        "/openapi.json",
    ]
    for path in paths:
        text = client.get(path, headers=AUTH).text
        assert "sqlite:///" not in text, f"{path} leaked the connection string"
        assert "DTC_DATABASE_URL" not in text or path == "/openapi.json"
        assert API_TOKEN not in text, f"{path} leaked the token"
        assert "dtc.db" not in text, f"{path} leaked the database path"


def test_a_new_domain_field_cannot_appear_in_the_api_unnoticed():
    """The other half of the explicit-model decision (research D7).

    An explicit model stops a new domain field leaking today. This stops it
    leaking tomorrow: adding one to the domain fails here until somebody decides
    whether it belongs in the API.
    """
    from dataclasses import fields

    from dynamic_thermal_charge.api.schemas import HeaterResponse
    from dynamic_thermal_charge.models import Heater

    domain = {field.name for field in fields(Heater)}
    exposed = set(HeaterResponse.model_fields)
    # Fields deliberately renamed or converted at the boundary.
    translated = {
        "power_w": "power_kw",
        "full_charge_minutes": "full_charge_hours",
    }
    unaccounted = {
        name
        for name in domain
        if name not in exposed and translated.get(name) not in exposed
    }
    assert not unaccounted, (
        "these Heater fields are neither exposed nor deliberately translated; "
        f"decide whether the API should show them: {sorted(unaccounted)}"
    )


# --------------------------------------------------------------------------- #
# Editing (FR-023, FR-027, FR-031)
# --------------------------------------------------------------------------- #

def test_an_installation_field_changes(client):
    response = _patch(client, "max_total_power_kw", "6.0")
    assert response.status_code == 200
    body = response.json()
    assert body["old_value"] == "5200"
    assert body["new_value"] == "6000", "the audit trail mixed kW and W"
    assert body["revision_before"] == 1 and body["revision_after"] == 2
    assert _config(client)["max_total_power_kw"] == 6.0


def test_a_weather_field_changes(client):
    response = _patch(client, "retry_minutes", "20")
    assert response.status_code == 200
    assert _config(client)["weather"]["retry_minutes"] == 20


def test_a_heater_field_changes_only_that_heater(client):
    before = {h["id"]: h for h in _config(client)["heaters"]}
    response = _patch(client, "target_charge", "0.5", heater="entrada")
    assert response.status_code == 200
    after = {h["id"]: h for h in _config(client)["heaters"]}
    assert after["entrada"]["target_charge"] == 0.5
    for heater_id, heater in before.items():
        if heater_id != "entrada":
            assert after[heater_id] == heater, "an unrelated heater changed"


def test_indoor_policy_and_topic_round_trip_with_empty_topic_as_null(client):
    for field, value, expected in (
        ("indoor_max_age_minutes", "45", 45),
        ("indoor_min_plausible_c", "-15", -15.0),
        ("indoor_max_plausible_c", "45", 45.0),
    ):
        assert _patch(client, field, value).status_code == 200
        assert _config(client)[field] == expected
    assert _patch(client, "indoor_topic", "ha/salon/temp", heater="salon").status_code == 200
    assert _config(client)["heaters"][0]["indoor_topic"] == "ha/salon/temp"
    cleared = _patch(client, "indoor_topic", "", heater="salon")
    assert cleared.status_code == 200
    assert cleared.json()["new_value"] is None
    assert _config(client)["heaters"][0]["indoor_topic"] is None


def test_a_thermal_field_changes(client):
    assert _patch(client, "target_temperature_c", "22.5", heater="salon").status_code == 200
    heaters = {h["id"]: h for h in _config(client)["heaters"]}
    assert heaters["salon"]["thermal"]["target_temperature_c"] == 22.5
    assert heaters["entrada"]["thermal"]["target_temperature_c"] == 18.0
    assert _patch(client, "thermal_loss_c_per_hour", "0.5", heater="salon").status_code == 200
    heaters = {h["id"]: h for h in _config(client)["heaters"]}
    assert heaters["salon"]["thermal"]["thermal_loss_c_per_hour"] == 0.5


def test_retention_can_be_set_to_unlimited(client):
    assert _patch(client, "retention_days", "none").status_code == 200
    assert _config(client)["retention_days"] is None


# --------------------------------------------------------------------------- #
# Adding and removing (FR-030)
# --------------------------------------------------------------------------- #

NEW_HEATER = {
    "id": "cocina",
    "power_kw": 1.2,
    "full_charge_hours": 7,
    "output": "gpio",
    "pin": 24,
    "active_high": False,
    "target_temperature_c": 20.0,
    "design_outdoor_temperature_c": -2.0,
}


def test_a_heater_can_be_added(client):
    revision = _config(client)["config_revision"]
    response = client.post(
        "/api/v1/config/heaters", headers=AUTH, json={**NEW_HEATER, "revision": revision}
    )
    assert response.status_code == 201, response.text
    assert response.json()["action"] == "add"
    added = client.get("/api/v1/config/heaters/cocina", headers=AUTH).json()
    assert added["output"]["pin"] == 24
    assert added["thermal"]["target_temperature_c"] == 20.0


def test_a_heater_can_be_removed_keeping_its_history(client, recorder, initialised_store):
    from datetime import datetime, timedelta, timezone

    from dynamic_thermal_charge.scheduler import ChargeScheduler

    config, revision = initialised_store.repository.current()
    plan = ChargeScheduler().build(
        config.site, config.heaters, datetime(2026, 1, 16, tzinfo=timezone.utc)
    )
    plan_ref = recorder.record_plan(plan, None, revision)
    recorder.record_transition(
        "buhardilla", True, datetime(2026, 1, 16, tzinfo=timezone.utc), plan_ref
    )

    revision = _config(client)["config_revision"]
    response = client.delete(
        f"/api/v1/config/heaters/buhardilla?revision={revision}", headers=AUTH
    )
    assert response.status_code == 200
    assert "buhardilla" not in [h["id"] for h in _config(client)["heaters"]]

    history = client.get(
        "/api/v1/history/transitions?heater_id=buhardilla", headers=AUTH
    ).json()
    assert history["items"], "the history of a removed heater disappeared"


def test_adding_a_duplicate_id_is_a_conflict(client):
    revision = _config(client)["config_revision"]
    response = client.post(
        "/api/v1/config/heaters",
        headers=AUTH,
        json={**NEW_HEATER, "id": "salon", "pin": 25, "revision": revision},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "already_exists"


def test_adding_on_a_used_pin_is_refused(client):
    revision = _config(client)["config_revision"]
    response = client.post(
        "/api/v1/config/heaters",
        headers=AUTH,
        json={**NEW_HEATER, "pin": 17, "revision": revision},
    )
    assert response.status_code == 422
    body = response.json()
    assert "17" in body["message"] and "salon" in body["message"]


def test_removing_an_unknown_heater_is_not_found(client):
    revision = _config(client)["config_revision"]
    response = client.delete(
        f"/api/v1/config/heaters/cocina?revision={revision}", headers=AUTH
    )
    assert response.status_code == 404
    assert "salon" in response.json()["message"]


# --------------------------------------------------------------------------- #
# Rejections. The store must be left exactly as it was.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("field", "value", "heater", "code"),
    [
        ("slot_minutes", "45", None, 422),
        ("start_time", "00:17", None, 422),
        ("max_total_power_kw", "0", None, 422),
        ("log_level", "CHATTY", None, 422),
        ("weekdays", "1,0", None, 422),
        ("retention_days", "0", None, 422),
        ("indoor_max_age_minutes", "0", None, 422),
        ("indoor_min_plausible_c", "60", None, 422),
        ("indoor_max_plausible_c", "-30", None, 422),
        ("pin", "17", "entrada", 422),
        ("target_charge", "1.5", "entrada", 422),
        ("design_outdoor_temperature_c", "30", "salon", 422),
        ("nonexistent_field", "1", None, 404),
        ("nonexistent_field", "1", "salon", 404),
        ("priority", "1", "cocina", 404),
        ("target_charge", "0.5", None, 404),
    ],
)
def test_a_rejected_edit_changes_nothing(client, field, value, heater, code):
    before = _config(client)
    response = _patch(client, field, value, heater=heater)
    assert response.status_code == code, response.text
    assert _config(client) == before, "a rejected edit left a trace"


def test_a_field_belonging_to_a_heater_says_where_to_send_it(client):
    response = _patch(client, "target_charge", "0.5")
    assert response.status_code == 404
    assert "heater" in response.json()["message"]


def test_an_unknown_field_lists_the_admissible_ones(client):
    response = _patch(client, "maximum_power", "6")
    assert response.status_code == 404
    message = response.json()["message"]
    assert "max_total_power_kw" in message and "slot_minutes" in message


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+pg8000://dtc:secret@host/dtc",
        "sqlite:////var/lib/dtc/dtc.db",
        "host=db password=hunter2",
        "https://user:token@example.com/hook",
    ],
)
def test_a_value_that_looks_like_a_credential_is_refused(client, value):
    before = _config(client)
    response = _patch(client, "state_file", value)
    assert response.status_code == 422
    assert response.json()["code"] == "secret_rejected"
    assert "environment variable" in response.json()["message"]
    assert _config(client) == before


def test_an_ordinary_path_is_not_mistaken_for_a_secret(client):
    assert _patch(client, "state_file", "/var/lib/dtc/plan.json").status_code == 200


# --------------------------------------------------------------------------- #
# FR-026: the revision is the optimistic lock
# --------------------------------------------------------------------------- #

def test_a_stale_revision_is_a_conflict(client):
    revision = _config(client)["config_revision"]
    assert _patch(client, "poll_seconds", "6", revision=revision).status_code == 200
    # A second client still holding the old revision.
    response = _patch(client, "poll_seconds", "7", revision=revision)
    assert response.status_code == 409
    assert response.json()["code"] == "config_conflict"
    assert "revision" in response.json()["message"]
    assert _config(client)["poll_seconds"] == 6.0, "the first edit was lost"


def test_the_revision_is_mandatory(client):
    response = client.patch(
        "/api/v1/config", headers=AUTH, json={"field": "poll_seconds", "value": "6"}
    )
    assert response.status_code == 422


def test_two_clients_on_the_same_revision_do_not_both_win(client):
    revision = _config(client)["config_revision"]
    first = _patch(client, "poll_seconds", "11", revision=revision)
    second = _patch(client, "poll_seconds", "12", revision=revision)
    assert {first.status_code, second.status_code} == {200, 409}
    assert _config(client)["config_revision"] == revision + 1


# --------------------------------------------------------------------------- #
# FR-031: an edit does not disturb the running plan
# --------------------------------------------------------------------------- #

def test_an_edit_does_not_alter_the_plan_in_progress(client, heartbeat, recorder, initialised_store):
    from datetime import datetime, timedelta, timezone

    from dynamic_thermal_charge.scheduler import ChargeScheduler
    from tests.conftest import API_NOW

    config, revision = initialised_store.repository.current()
    plan = ChargeScheduler().build(
        config.site, config.heaters, API_NOW - timedelta(hours=1)
    )
    recorder.record_plan(plan, None, revision)
    heartbeat.publish(API_NOW, degraded=False)

    before = client.get("/api/v1/status", headers=AUTH).json()["plan"]
    assert _patch(client, "max_total_power_kw", "2.4").status_code == 200
    after = client.get("/api/v1/status", headers=AUTH).json()["plan"]
    assert after == before, "editing the configuration changed the running plan"
