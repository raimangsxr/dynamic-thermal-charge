"""Shared entity and device helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, VERSION
from .coordinator import (
    DynamicThermalChargeCoordinator,
    accumulator_from_snapshot,
    accumulator_unique_id,
    controller_device_id,
    controller_unique_id,
    installation_id,
)


class DynamicThermalChargeEntity(CoordinatorEntity[DynamicThermalChargeCoordinator]):
    """Entity that exposes only a fresh successful coordinator snapshot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return bool(self.coordinator.last_update_success and self.coordinator.data is not None)

    @property
    def installation_device_info(self) -> DeviceInfo:
        installation = self.coordinator.data.get("installation", {}) if self.coordinator.data else {}
        return DeviceInfo(
            identifiers={(DOMAIN, installation_id(self.coordinator))},
            name=str(installation.get("name", "Dynamic Thermal Charge")),
            manufacturer=MANUFACTURER,
            model="Controller",
            sw_version=VERSION,
        )

    def accumulator_device_info(self, accumulator_id: str) -> DeviceInfo:
        accumulator = accumulator_from_snapshot(self.coordinator, accumulator_id) or {}
        return DeviceInfo(
            identifiers={(DOMAIN, f"{installation_id(self.coordinator)}:{accumulator_id}")},
            name=str(accumulator.get("name", accumulator_id)),
            manufacturer=MANUFACTURER,
            model="Accumulator",
            via_device_id=controller_device_id(self.coordinator),
        )

    @property
    def _snapshot(self) -> dict[str, Any] | None:
        return self.coordinator.data if self.available else None

    def _accumulator(self, accumulator_id: str) -> dict[str, Any] | None:
        return accumulator_from_snapshot(self.coordinator, accumulator_id)


def controller_entity_unique_id(
    coordinator: DynamicThermalChargeCoordinator,
    key: str,
) -> str:
    return controller_unique_id(coordinator, key)


def accumulator_entity_unique_id(
    coordinator: DynamicThermalChargeCoordinator,
    accumulator_id: str,
    key: str,
) -> str:
    return accumulator_unique_id(coordinator, accumulator_id, key)


__all__ = [
    "DynamicThermalChargeEntity",
    "accumulator_entity_unique_id",
    "controller_entity_unique_id",
]
