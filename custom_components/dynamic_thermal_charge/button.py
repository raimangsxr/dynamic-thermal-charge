"""Controller recalculate command."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DynamicThermalChargeCoordinator
from .entity import DynamicThermalChargeEntity, controller_entity_unique_id


class RecalculateButton(DynamicThermalChargeEntity, ButtonEntity):
    _attr_translation_key = "recalculate"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(coordinator, "recalculate")
        self._attr_device_info = self.installation_device_info

    async def async_press(self) -> None:
        await self.coordinator.async_command(
            lambda revision: self.coordinator.client.async_recalculate(revision)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = entry.runtime_data.coordinator
    async_add_entities([RecalculateButton(coordinator)])
