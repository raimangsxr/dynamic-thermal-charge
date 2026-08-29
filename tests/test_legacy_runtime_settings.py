"""Former operational environment knobs now come from the system database."""

from dynamic_thermal_charge.api.routes.relay_test import _lease
from dynamic_thermal_charge.persistence.controller_log import ControllerLogHandler, DEFAULT_MAX_EVENTS


def test_relay_test_lease_default_and_persisted_override(initialised_store, monkeypatch):
    monkeypatch.setenv("DTC_RELAY_TEST_LEASE_SECONDS", "99")
    assert _lease(initialised_store) == 30
    repository = initialised_store.system_configuration
    revision = repository.current().revision
    repository.update_section(
        "operations", {"relay_test_lease_seconds": 45},
        expected_revision=revision, actor="test",
    )
    assert _lease(initialised_store) == 45


def test_controller_log_retention_is_an_injected_persisted_value(initialised_store, monkeypatch):
    monkeypatch.setenv("DTC_CONTROLLER_LOG_MAX_EVENTS", "99999")
    engine = initialised_store.application_engine or initialised_store.engine
    default = ControllerLogHandler(engine, 1)
    low = ControllerLogHandler(engine, 1, max_events=1)
    high = ControllerLogHandler(engine, 1, max_events=100001)
    assert default._max_events == DEFAULT_MAX_EVENTS
    assert low._max_events == 10
    assert high._max_events == 100_000
