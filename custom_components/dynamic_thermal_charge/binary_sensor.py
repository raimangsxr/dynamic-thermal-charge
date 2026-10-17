"""Confirmed charging state for each accumulator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DynamicThermalChargeCoordinator
from .entity import (
    DynamicThermalChargeEntity,
    accumulator_entity_unique_id,
    controller_entity_unique_id,
)


class ActiveAlertsBinarySensor(DynamicThermalChargeEntity, BinarySensorEntity):
    """Global operator alert state projected by the operational snapshot."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Alertas activas"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(
            coordinator, "alerts_active"
        )
        self._attr_device_info = self.installation_device_info

    @property
    def is_on(self) -> bool | None:
        alerts = (self._snapshot or {}).get("alerts")
        return None if not isinstance(alerts, dict) else bool(alerts.get("active", False))

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        alerts = (self._snapshot or {}).get("alerts")
        if not isinstance(alerts, dict):
            return {}
        return {
            "count": int(alerts.get("count", 0)),
            "types": list(alerts.get("types", ())),
            "maximum_severity": alerts.get("maximum_severity"),
            "messages": list(alerts.get("messages", ())),
        }


class AccumulatorChargingBinarySensor(DynamicThermalChargeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_translation_key = "charging"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator)
        self.accumulator_id = accumulator_id
        self._attr_unique_id = accumulator_entity_unique_id(coordinator, accumulator_id, "charging")
        self._attr_device_info = self.accumulator_device_info(accumulator_id)

    @property
    def is_on(self) -> bool | None:
        accumulator = self._accumulator(self.accumulator_id)
        return None if accumulator is None else accumulator.get("confirmed_load")


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = entry.runtime_data.coordinator
    async_add_entities([ActiveAlertsBinarySensor(coordinator)])
    await coordinator.async_register_dynamic_platform(
        "binary_sensor",
        lambda accumulator_id: [
            AccumulatorChargingBinarySensor(coordinator, accumulator_id)
        ],
        lambda accumulator_id: (
            accumulator_entity_unique_id(coordinator, accumulator_id, "charging"),
        ),
        async_add_entities,
    )
