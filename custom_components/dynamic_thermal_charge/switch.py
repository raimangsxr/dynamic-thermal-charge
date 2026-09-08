"""Controller automatic-control switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DynamicThermalChargeCoordinator
from .entity import DynamicThermalChargeEntity, controller_entity_unique_id


class AutomaticControlSwitch(DynamicThermalChargeEntity, SwitchEntity):
    _attr_translation_key = "automatic_control"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(coordinator, "automatic_control")
        self._attr_device_info = self.installation_device_info

    @property
    def is_on(self) -> bool | None:
        snapshot = self._snapshot
        return None if snapshot is None else bool(snapshot.get("automatic_control_enabled"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_command(
            lambda revision: self.coordinator.client.async_set_automatic_control(True, revision)
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_command(
            lambda revision: self.coordinator.client.async_set_automatic_control(False, revision)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AutomaticControlSwitch(coordinator)])
