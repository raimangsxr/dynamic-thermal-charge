"""The diagnostic log is bounded, controller-only and protected like the API."""
from __future__ import annotations

import logging

from dynamic_thermal_charge.persistence.controller_log import ControllerLogHandler
from tests.conftest import AUTH


def _write(initialised_store, count: int = 2) -> None:
    handler = ControllerLogHandler(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(), initialised_store.location
    )
    logger = logging.getLogger("dynamic_thermal_charge.controller-test")
    logger.addHandler(handler)
    try:
        for number in range(count):
            logger.warning("controller event %d", number)
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_controller_log_is_protected_and_paged(client, initialised_store):
    assert client.get("/api/v1/controller-log").status_code == 401
    _write(initialised_store)
    response = client.get("/api/v1/controller-log?limit=1", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit_applied"] == 1
    assert body["has_more"] is True
    assert body["items"][0]["level"] == "WARNING"
    assert body["next_before_id"] is not None


def test_controller_log_filters_and_rejects_invalid_levels(client, initialised_store):
    _write(initialised_store)
    body = client.get("/api/v1/controller-log?level=warning&q=event+1", headers=AUTH).json()
    assert [row["message"] for row in body["items"]] == ["controller event 1"]
    assert client.get("/api/v1/controller-log?level=journal", headers=AUTH).status_code == 400
