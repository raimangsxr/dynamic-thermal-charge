"""Regression tests for the Home Assistant native integration contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")


def _snapshot(*, installation_id: str = "installation-uuid") -> dict:
    return {
        "revision": 1,
        "health": "idle",
        "installation": {"id": installation_id, "name": "Test"},
        "accumulators": [],
    }


class _Response:
    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def text(self) -> str:
        import json

        return json.dumps(self._body)


class _Session:
    def __init__(self, body: object) -> None:
        self.body = body
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def request(self, *args: object, **kwargs: object) -> _Response:
        self.calls.append((args, kwargs))
        return _Response(200, self.body)


def test_client_keeps_protocol_host_and_port_separate() -> None:
    from custom_components.dynamic_thermal_charge.api import DynamicThermalChargeClient

    session = _Session(_snapshot())
    client = DynamicThermalChargeClient.from_config(
        session,
        {"protocol": "https", "host": "backend.example", "port": 8443, "token": "secret"},
    )

    asyncio.run(client.async_snapshot())

    assert client.base_url == "https://backend.example:8443/api/v1"
    assert session.calls[0][1]["ssl"] is True
    assert session.calls[0][1]["headers"] == {"Authorization": "Bearer secret"}


def test_snapshot_validation_rejects_incompatible_installation() -> None:
    from custom_components.dynamic_thermal_charge.api import (
        DynamicThermalChargeInstallationError,
        validate_snapshot,
    )

    with pytest.raises(DynamicThermalChargeInstallationError):
        validate_snapshot(_snapshot(installation_id="other"), expected_installation_id="one")


def test_v1_entry_migrates_to_explicit_http() -> None:
    from custom_components.dynamic_thermal_charge import async_migrate_entry

    entry = SimpleNamespace(
        version=1,
        data={"host": "backend", "port": 8080, "token": "secret"},
    )

    class _ConfigEntries:
        def async_update_entry(self, current, **kwargs):
            current.data = kwargs["data"]
            current.version = kwargs["version"]

    hass = SimpleNamespace(config_entries=_ConfigEntries())
    assert asyncio.run(async_migrate_entry(hass, entry)) is True
    assert entry.version == 2
    assert entry.data["protocol"] == "http"


def test_controller_state_is_an_enum_with_only_contract_states() -> None:
    from custom_components.dynamic_thermal_charge.sensor import ControllerStateSensor
    from homeassistant.components.sensor import SensorDeviceClass

    sensor = object.__new__(ControllerStateSensor)
    sensor.coordinator = SimpleNamespace(
        data={"health": "degraded"},
        last_update_success=True,
    )

    assert sensor.device_class is SensorDeviceClass.ENUM
    assert sensor.options == ["running", "idle", "degraded", "error"]
    assert sensor.native_value == "degraded"


def test_calendar_returns_next_event_and_handles_february_29(monkeypatch) -> None:
    from custom_components.dynamic_thermal_charge.calendar import GlobalChargeCalendar

    now = datetime(2028, 2, 29, 12, tzinfo=timezone.utc)
    future = now + timedelta(hours=1)
    snapshot = {
        **_snapshot(),
        "plan": {
            "intervals": [
                {
                    "accumulator_id": "salon",
                    "start": future.isoformat(),
                    "end": (future + timedelta(minutes=30)).isoformat(),
                }
            ]
        },
    }
    calendar = object.__new__(GlobalChargeCalendar)
    calendar.coordinator = SimpleNamespace(data=snapshot, last_update_success=True)
    monkeypatch.setattr(
        "custom_components.dynamic_thermal_charge.calendar.dt_util.utcnow",
        lambda: now,
    )

    assert calendar.event is not None
    assert calendar.event.start == future


def test_diagnostics_redact_nested_credentials() -> None:
    from custom_components.dynamic_thermal_charge.diagnostics import _redact

    value = _redact({"token": "secret", "nested": {"password": "pw", "ok": 1}})
    assert value == {"nested": {"ok": 1}}


def test_reconcile_removes_child_device_with_removed_accumulator(monkeypatch) -> None:
    import custom_components.dynamic_thermal_charge.coordinator as coordinator_module
    from custom_components.dynamic_thermal_charge.coordinator import (
        DynamicThermalChargeCoordinator,
    )

    entity_entries = [SimpleNamespace(entity_id="sensor.b", device_id="child-b")]
    removed_devices: list[str] = []

    class _EntityRegistry:
        def async_remove(self, entity_id: str) -> None:
            entity_entries[:] = [
                item for item in entity_entries if item.entity_id != entity_id
            ]

    class _DeviceRegistry:
        def async_get_devices(self, **_kwargs):
            return []

        def async_get_child_device_by_identifier(self, _identifier, _entry_id):
            return SimpleNamespace(id="child-b")

        def async_remove_device(self, device_id: str) -> None:
            removed_devices.append(device_id)

    entity_registry = _EntityRegistry()
    device_registry = _DeviceRegistry()
    monkeypatch.setattr(coordinator_module.er, "async_get", lambda _hass: entity_registry)
    monkeypatch.setattr(
        coordinator_module.er,
        "async_entries_for_config_entry",
        lambda _registry, _entry_id: list(entity_entries),
    )
    monkeypatch.setattr(coordinator_module.dr, "async_get", lambda _hass: device_registry)

    coordinator = object.__new__(DynamicThermalChargeCoordinator)
    coordinator.hass = SimpleNamespace()
    coordinator.entry = SimpleNamespace(
        entry_id="entry",
        unique_id="installation-uuid",
    )
    coordinator.data = {"installation": {"id": "installation-uuid"}}
    coordinator._pending_snapshot = None

    coordinator._remove_accumulator_devices({"b"})

    assert entity_entries == []
    assert removed_devices == ["child-b"]
