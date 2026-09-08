"""Controller and accumulator sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import DynamicThermalChargeCoordinator
from .entity import (
    DynamicThermalChargeEntity,
    accumulator_entity_unique_id,
    controller_entity_unique_id,
)


class ControllerStateSensor(DynamicThermalChargeEntity, SensorEntity):
    _attr_options: ClassVar[list[str]] = ["running", "idle", "degraded", "error"]
    _attr_translation_key = "controller_state"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(coordinator, "state")
        self._attr_device_info = self.installation_device_info

    @property
    def native_value(self) -> str | None:
        snapshot = self._snapshot
        return None if snapshot is None else snapshot.get("health")


class TotalPowerSensor(DynamicThermalChargeEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "total_power"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(coordinator, "total_power")
        self._attr_device_info = self.installation_device_info

    @property
    def native_value(self) -> int | None:
        snapshot = self._snapshot
        return None if snapshot is None else snapshot.get("power", {}).get("instant_w")


class AccumulatorSensor(DynamicThermalChargeEntity, SensorEntity):
    def __init__(
        self,
        coordinator: DynamicThermalChargeCoordinator,
        accumulator_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self.accumulator_id = accumulator_id
        self.key = key
        self._attr_unique_id = accumulator_entity_unique_id(coordinator, accumulator_id, key)
        self._attr_device_info = self.accumulator_device_info(accumulator_id)
        self._attr_translation_key = key

    @property
    def _value(self) -> Any:
        accumulator = self._accumulator(self.accumulator_id)
        return None if accumulator is None else accumulator.get(self.key)

    @property
    def native_value(self) -> Any:
        return self._value


class AccumulatorTemperatureSensor(AccumulatorSensor):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "indoor_temperature_c")


class AccumulatorSocSensor(AccumulatorSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "soc_percent")


class AccumulatorPowerSensor(AccumulatorSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "instant_power_w")


class AccumulatorDamperSensor(AccumulatorSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "damper_position_percent")


class AccumulatorNextChargeSensor(AccumulatorSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "next_charge_at")

    @property
    def native_value(self) -> datetime | None:
        value = self._value
        return None if value is None else dt_util.parse_datetime(str(value))


class AccumulatorNextSocTargetSensor(AccumulatorSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DynamicThermalChargeCoordinator, accumulator_id: str) -> None:
        super().__init__(coordinator, accumulator_id, "next_soc_target_percent")


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ControllerStateSensor(coordinator),
        TotalPowerSensor(coordinator),
    ])
    await coordinator.async_register_dynamic_platform(
        "sensor",
        lambda accumulator_id: [
            AccumulatorTemperatureSensor(coordinator, accumulator_id),
            AccumulatorSocSensor(coordinator, accumulator_id),
            AccumulatorPowerSensor(coordinator, accumulator_id),
            AccumulatorDamperSensor(coordinator, accumulator_id),
            AccumulatorNextChargeSensor(coordinator, accumulator_id),
            AccumulatorNextSocTargetSensor(coordinator, accumulator_id),
        ],
        lambda accumulator_id: tuple(
            accumulator_entity_unique_id(coordinator, accumulator_id, key)
            for key in (
                "indoor_temperature_c",
                "soc_percent",
                "instant_power_w",
                "damper_position_percent",
                "next_charge_at",
                "next_soc_target_percent",
            )
        ),
        async_add_entities,
    )


__all__ = ["async_setup_entry"]
