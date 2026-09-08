"""Redacted diagnostics for the local integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT, CONF_PROTOCOL, CONF_TOKEN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    runtime_data = entry.runtime_data
    coordinator = runtime_data.coordinator
    data = _redact(coordinator.data) if coordinator.last_update_success else None
    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "host": entry.data.get(CONF_HOST),
            "port": entry.data.get(CONF_PORT),
            "protocol": entry.data.get(CONF_PROTOCOL, "http"),
            "token_configured": bool(entry.data.get(CONF_TOKEN)),
        },
        "last_update_success": coordinator.last_update_success,
        "snapshot": data if coordinator.last_update_success else None,
    }


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
}


def _redact(value: Any) -> Any:
    """Return diagnostics data without credentials, even if the API regresses."""
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in _SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
            if key.lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value
