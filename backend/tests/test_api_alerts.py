"""The email section, its secrets, the catalogue and the test send."""

from __future__ import annotations

import pytest

from dynamic_thermal_charge.alerts import (
    PLAN_RECALCULATION_INVALID,
    AlertDeliveryError,
)

from .conftest import AUTH

EMAIL = {
    "enabled": True,
    "host": "smtp.example.org",
    "port": 587,
    "security": "starttls",
    "sender": "dtc@example.org",
    "recipients": ["operador@example.org"],
    "timeout_seconds": 10.0,
}


def _revision(client) -> int:
    return client.get("/api/v1/system/configuration", headers=AUTH).json()["revision"]


def _configure_email(client, values=None) -> dict:
    response = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={"expected_revision": _revision(client), "values": values or EMAIL},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# R1, R2: configuration and secrets
# --------------------------------------------------------------------------- #

def test_the_email_section_is_persisted_and_returned(client):
    body = _configure_email(client)

    assert body["sections"]["email"] == EMAIL
    reread = client.get("/api/v1/system/configuration", headers=AUTH).json()
    assert reread["sections"]["email"]["recipients"] == ["operador@example.org"]


def test_email_alerts_start_disabled(client):
    body = client.get("/api/v1/system/configuration", headers=AUTH).json()

    assert body["sections"]["email"]["enabled"] is False
    assert body["sections"]["email"]["recipients"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("port", 0),
        ("port", 70000),
        ("security", "ssl-maybe"),
        ("timeout_seconds", 0),
        ("recipients", ["not-an-address"]),
        ("sender", "not-an-address"),
    ],
)
def test_an_invalid_email_setting_is_rejected_and_changes_nothing(client, field, value):
    before = client.get("/api/v1/system/configuration", headers=AUTH).json()

    response = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={"expected_revision": before["revision"], "values": {**EMAIL, field: value}},
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/v1/system/configuration", headers=AUTH).json() == before


def test_enabling_without_a_host_is_rejected(client):
    response = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={
            "expected_revision": _revision(client),
            "values": {**EMAIL, "host": None},
        },
    )

    assert response.status_code == 422, response.text


def test_a_stale_revision_cannot_change_the_email_section(client):
    _configure_email(client)

    response = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={"expected_revision": 1, "values": {**EMAIL, "port": 2525}},
    )

    assert response.status_code == 409, response.text
    reread = client.get("/api/v1/system/configuration", headers=AUTH).json()
    assert reread["sections"]["email"]["port"] == 587


def test_the_smtp_credentials_are_reported_without_their_values(client):
    body = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={
            "expected_revision": _revision(client),
            "values": EMAIL,
            "secrets": {
                "smtp_username": {"action": "replace", "value": "buzon"},
                "smtp_password": {"action": "replace", "value": "clave-secreta"},
            },
        },
    ).json()

    assert body["secrets"]["smtp_username"]["configured"] is True
    assert body["secrets"]["smtp_password"]["configured"] is True
    assert "clave-secreta" not in str(body)

    cleared = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={
            "expected_revision": body["revision"],
            "values": {},
            "secrets": {
                "smtp_username": {"action": "clear"},
                "smtp_password": {"action": "clear"},
            },
        },
    ).json()
    assert cleared["secrets"]["smtp_password"]["configured"] is False


def test_half_a_credential_pair_is_rejected(client):
    response = client.patch(
        "/api/v1/system/configuration/email",
        headers=AUTH,
        json={
            "expected_revision": _revision(client),
            "values": EMAIL,
            "secrets": {"smtp_password": {"action": "replace", "value": "clave"}},
        },
    )

    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# R3: the catalogue
# --------------------------------------------------------------------------- #

def test_the_catalogue_lists_every_alert_enabled_by_default(client):
    body = client.get("/api/v1/system/alerts", headers=AUTH).json()

    names = [item["name"] for item in body["alerts"]]
    assert PLAN_RECALCULATION_INVALID in names
    assert all(item["enabled"] for item in body["alerts"])
    assert all({"name", "title", "description", "enabled"} == set(item) for item in body["alerts"])


def test_one_alert_type_can_be_silenced_and_restored(client):
    silenced = client.patch(
        f"/api/v1/system/alerts/{PLAN_RECALCULATION_INVALID}",
        headers=AUTH,
        json={"enabled": False},
    )
    assert silenced.status_code == 200, silenced.text
    assert silenced.json()["alerts"][0]["enabled"] is False

    reread = client.get("/api/v1/system/alerts", headers=AUTH).json()
    assert reread["alerts"][0]["enabled"] is False

    restored = client.patch(
        f"/api/v1/system/alerts/{PLAN_RECALCULATION_INVALID}",
        headers=AUTH,
        json={"enabled": True},
    )
    assert restored.json()["alerts"][0]["enabled"] is True


def test_an_unknown_alert_type_is_rejected(client):
    response = client.patch(
        "/api/v1/system/alerts/not_in_the_catalogue", headers=AUTH, json={"enabled": False}
    )

    assert response.status_code == 422, response.text


# --------------------------------------------------------------------------- #
# R9: the test send
# --------------------------------------------------------------------------- #

def test_the_test_send_is_refused_while_email_is_disabled(client):
    response = client.post("/api/v1/system/tests/email", headers=AUTH)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "connection_test_failed"


def test_the_test_send_reports_success_and_leaves_no_alert(client, monkeypatch, initialised_store):
    _configure_email(client)
    sent: list[tuple[str, str]] = []

    def fake_send(self, settings, alert):
        sent.append((alert.alert_type, alert.subject))

    monkeypatch.setattr(
        "dynamic_thermal_charge.alerts.SmtpAlertSender.send", fake_send
    )

    response = client.post("/api/v1/system/tests/email", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True, "driver": "email", "host": "smtp.example.org", "port": 587
    }
    assert [item[0] for item in sent] == ["test"]
    assert initialised_store.alerts.pending_count() == 0


def test_the_test_send_explains_a_failure(client, monkeypatch):
    _configure_email(client)

    def failing_send(self, settings, alert):
        raise AlertDeliveryError("connection refused")

    monkeypatch.setattr(
        "dynamic_thermal_charge.alerts.SmtpAlertSender.send", failing_send
    )

    response = client.post("/api/v1/system/tests/email", headers=AUTH)

    assert response.status_code == 503, response.text
    assert "connection refused" in response.json()["message"]
