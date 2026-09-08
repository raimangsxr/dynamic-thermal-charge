"""Native Home Assistant integration for Dynamic Thermal Charge."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DynamicThermalChargeClient
from .const import (
    CONF_PROTOCOL,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    SUPPORTED_PROTOCOLS,
    VERSION,
)
from .coordinator import DynamicThermalChargeCoordinator, installation_id


@dataclass(slots=True)
class DynamicThermalChargeRuntimeData:
    """Objects owned by one loaded config entry."""

    client: DynamicThermalChargeClient
    coordinator: DynamicThermalChargeCoordinator


type DynamicThermalChargeConfigEntry = ConfigEntry[DynamicThermalChargeRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: DynamicThermalChargeConfigEntry
) -> bool:
    """Set up the client, coordinator and all entity platforms."""
    client = DynamicThermalChargeClient.from_config(
        async_get_clientsession(hass), dict(entry.data)
    )
    coordinator = DynamicThermalChargeCoordinator(hass, client, entry)
    entry.runtime_data = DynamicThermalChargeRuntimeData(client, coordinator)
    await coordinator.async_config_entry_first_refresh()
    _ensure_controller_device(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DynamicThermalChargeConfigEntry
) -> bool:
    """Unload platforms; Home Assistant clears ``runtime_data`` afterwards."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate v1 entries that stored no protocol to explicit HTTP."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version < CONFIG_ENTRY_VERSION:
        data = dict(entry.data)
        protocol = str(data.get(CONF_PROTOCOL, data.get("scheme", "http"))).lower()
        if protocol not in SUPPORTED_PROTOCOLS:
            protocol = "http"
        data[CONF_PROTOCOL] = protocol
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            version=CONFIG_ENTRY_VERSION,
        )
    return True


def _ensure_controller_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: DynamicThermalChargeCoordinator,
) -> str:
    """Register the parent before child entities request ``via_device_id``."""
    installation = coordinator.data.get("installation", {}) if coordinator.data else {}
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, installation_id(coordinator))},
        name=str(installation.get("name") or "Dynamic Thermal Charge"),
        manufacturer=MANUFACTURER,
        model="Controller",
        sw_version=VERSION,
    )
    coordinator.controller_device_id = device.id
    return device.id


__all__ = [
    "DynamicThermalChargeConfigEntry",
    "DynamicThermalChargeRuntimeData",
    "async_migrate_entry",
    "async_setup_entry",
    "async_unload_entry",
]
