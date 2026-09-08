"""UI configuration, reconfiguration and token reauthentication."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DynamicThermalChargeAuthError,
    DynamicThermalChargeClient,
    DynamicThermalChargeConnectionError,
)
from .const import CONF_HOST as DTC_CONF_HOST
from .const import CONF_PORT as DTC_CONF_PORT
from .const import CONF_TOKEN, DOMAIN


class DynamicThermalChargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one backend installation by its durable installation UUID."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry = None
        self._reconfigure_entry = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _normalized_data(user_input)
                snapshot = await self._async_validate(data)
            except ValueError:
                errors["base"] = "cannot_connect"
            except DynamicThermalChargeAuthError:
                errors["base"] = "invalid_auth"
            except DynamicThermalChargeConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(snapshot["installation"]["id"]))
                self._abort_if_unique_id_configured()
                title = str(snapshot["installation"].get("name") or data[DTC_CONF_HOST])
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(self, context: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(context["entry_id"])
        if self._reauth_entry is None:
            return self.async_abort(reason="unknown_entry")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._reauth_entry is not None:
            token = str(user_input[CONF_TOKEN]).strip()
            data = {**self._reauth_entry.data, CONF_TOKEN: token}
            try:
                await self._async_validate(data)
            except DynamicThermalChargeAuthError:
                errors["base"] = "invalid_auth"
            except (DynamicThermalChargeConnectionError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
                return self.async_abort(reason="reauth_success")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry_id = self.context.get("entry_id")
        self._reconfigure_entry = self.hass.config_entries.async_get_entry(entry_id)
        if self._reconfigure_entry is None:
            return self.async_abort(reason="unknown_entry")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _normalized_data(user_input)
                snapshot = await self._async_validate(data)
            except ValueError:
                errors["base"] = "cannot_connect"
            except DynamicThermalChargeAuthError:
                errors["base"] = "invalid_auth"
            except DynamicThermalChargeConnectionError:
                errors["base"] = "cannot_connect"
            else:
                if str(snapshot["installation"]["id"]) != str(self._reconfigure_entry.unique_id):
                    errors["base"] = "different_installation"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._reconfigure_entry,
                        data=data,
                        title=str(snapshot["installation"].get("name") or data[DTC_CONF_HOST]),
                    )
                    return self.async_abort(reason="reconfigure_success")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(
                user_input or dict(self._reconfigure_entry.data),
            ),
            errors=errors,
        )

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, Any]:
        client = DynamicThermalChargeClient.from_config(
            async_get_clientsession(self.hass), data
        )
        return await client.async_snapshot()

def _schema(data: dict[str, Any] | None = None) -> vol.Schema:
    current = data or {}
    return vol.Schema(
        {
            vol.Required(DTC_CONF_HOST, default=current.get(DTC_CONF_HOST, "")): str,
            vol.Required(
                DTC_CONF_PORT,
                default=current.get(DTC_CONF_PORT, 8080),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_TOKEN, default=current.get(CONF_TOKEN, "")): str,
        }
    )


def _normalized_data(data: dict[str, Any]) -> dict[str, Any]:
    host = str(data[DTC_CONF_HOST]).strip()
    token = str(data[CONF_TOKEN]).strip()
    port = int(data[DTC_CONF_PORT])
    if not host or not token or not 1 <= port <= 65535:
        raise ValueError("host, port and token are required")
    return {DTC_CONF_HOST: host, DTC_CONF_PORT: port, CONF_TOKEN: token}


__all__ = ["DynamicThermalChargeConfigFlow"]
