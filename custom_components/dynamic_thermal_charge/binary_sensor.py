"""Confirmed charging state for each accumulator."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DynamicThermalChargeCoordinator
from .entity import DynamicThermalChargeEntity, accumulator_entity_unique_id


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
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
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
