"""Controller recalculate command."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DynamicThermalChargeCoordinator
from .entity import (
    DynamicThermalChargeEntity,
    accumulator_entity_unique_id,
    controller_entity_unique_id,
)


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


class StartCalibrationButton(DynamicThermalChargeEntity, ButtonEntity):
    _attr_translation_key = "start_calibration"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator)
        self.accumulator_id = accumulator_id
        self._attr_unique_id = accumulator_entity_unique_id(coordinator, accumulator_id, "start_calibration")
        self._attr_device_info = self.accumulator_device_info(accumulator_id)

    @property
    def available(self) -> bool:
        accumulator = self._accumulator(self.accumulator_id) or {}
        return super().available and accumulator.get("calibration_session_id") is None

    async def async_press(self) -> None:
        await self.coordinator.async_command(
            lambda _revision: self.coordinator.client.async_start_calibration(self.accumulator_id)
        )


class CancelCalibrationButton(DynamicThermalChargeEntity, ButtonEntity):
    _attr_translation_key = "cancel_calibration"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator)
        self.accumulator_id = accumulator_id
        self._attr_unique_id = accumulator_entity_unique_id(coordinator, accumulator_id, "cancel_calibration")
        self._attr_device_info = self.accumulator_device_info(accumulator_id)

    @property
    def available(self) -> bool:
        accumulator = self._accumulator(self.accumulator_id) or {}
        return super().available and accumulator.get("calibration_session_id") is not None

    async def async_press(self) -> None:
        await self.coordinator.async_command(
            lambda _revision: self.coordinator.client.async_cancel_calibration(self.accumulator_id)
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = entry.runtime_data.coordinator
    async_add_entities([RecalculateButton(coordinator)])
    await coordinator.async_register_dynamic_platform(
        "button",
        lambda accumulator_id: [
            StartCalibrationButton(coordinator, accumulator_id),
            CancelCalibrationButton(coordinator, accumulator_id),
        ],
        lambda accumulator_id: tuple(
            accumulator_entity_unique_id(coordinator, accumulator_id, key)
            for key in ("start_calibration", "cancel_calibration")
        ),
        async_add_entities,
    )
