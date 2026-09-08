"""Redacted diagnostics for the local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DOMAIN
from .coordinator import DynamicThermalChargeCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "host": entry.data.get(CONF_HOST),
            "port": entry.data.get(CONF_PORT),
            "token_configured": bool(entry.data.get(CONF_TOKEN)),
        },
        "last_update_success": coordinator.last_update_success,
        "snapshot": data if coordinator.last_update_success else None,
    }
