"""AUTO/OFF climate controls backed by the active weekly target."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DynamicThermalChargeCoordinator
from .entity import DynamicThermalChargeEntity, accumulator_entity_unique_id


class AccumulatorClimate(DynamicThermalChargeEntity, ClimateEntity):
    _attr_translation_key = "accumulator_climate"
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.OFF, HVACMode.AUTO]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = -50
    _attr_max_temp = 80

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator)
        self.accumulator_id = accumulator_id
        self._attr_unique_id = accumulator_entity_unique_id(coordinator, accumulator_id, "climate")
        self._attr_device_info = self.accumulator_device_info(accumulator_id)

    @property
    def hvac_mode(self) -> HVACMode | None:
        accumulator = self._accumulator(self.accumulator_id)
        if accumulator is None:
            return None
        return HVACMode.OFF if accumulator.get("mode") == "OFF" else HVACMode.AUTO

    @property
    def current_temperature(self) -> float | None:
        accumulator = self._accumulator(self.accumulator_id)
        return None if accumulator is None else accumulator.get("indoor_temperature_c")

    @property
    def target_temperature(self) -> float | None:
        accumulator = self._accumulator(self.accumulator_id)
        return None if accumulator is None else accumulator.get("target_temperature_c")

    @property
    def hvac_action(self) -> HVACAction | None:
        accumulator = self._accumulator(self.accumulator_id)
        if accumulator is None:
            return None
        if accumulator.get("confirmed_load") is None:
            return None
        return HVACAction.HEATING if accumulator.get("confirmed_load") else HVACAction.IDLE

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError(f"unsupported HVAC mode {hvac_mode}")
        await self.coordinator.async_command(
            lambda revision: self.coordinator.client.async_set_mode(
                self.accumulator_id,
                "OFF" if hvac_mode == HVACMode.OFF else "AUTO",
                revision,
            )
        )

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            raise ValueError("temperature is required")
        await self.coordinator.async_command(
            lambda revision: self.coordinator.client.async_set_temperature(
                self.accumulator_id,
                float(temperature),
                revision,
            )
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_register_dynamic_platform(
        "climate",
        lambda accumulator_id: [AccumulatorClimate(coordinator, accumulator_id)],
        lambda accumulator_id: (
            accumulator_entity_unique_id(coordinator, accumulator_id, "climate"),
        ),
        async_add_entities,
    )
