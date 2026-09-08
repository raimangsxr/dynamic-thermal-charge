"""UI configuration, reconfiguration and token reauthentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigFlowResult,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DynamicThermalChargeAuthError,
    DynamicThermalChargeClient,
    DynamicThermalChargeConnectionError,
    DynamicThermalChargeResponseError,
)
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_TOKEN,
    CONFIG_ENTRY_VERSION,
    DOMAIN,
    SUPPORTED_PROTOCOLS,
)


class DynamicThermalChargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one backend installation by its durable installation UUID."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial setup and the shared reauth/reconfigure submission."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                data = _normalized_data(user_input)
                snapshot = await self._async_validate(data)
            except ValueError:
                errors["base"] = "cannot_connect"
            except DynamicThermalChargeAuthError:
                errors["base"] = "invalid_auth"
            except (DynamicThermalChargeConnectionError, DynamicThermalChargeResponseError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(snapshot["installation"]["id"]))
                title = str(snapshot["installation"].get("name") or data[CONF_HOST])
                if self.source == SOURCE_REAUTH:
                    self._abort_if_unique_id_mismatch(reason="different_installation")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data=data
                    )
                if self.source == SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_mismatch(reason="different_installation")
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data=data, title=title
                    )

                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication for an existing entry."""
        # ``entry_data`` is supplied by Home Assistant; the entry itself is
        # resolved from the flow context by ``_get_reauth_entry``.
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a replacement token and validate its installation identity."""
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            data = {
                **dict(reauth_entry.data),
                CONF_TOKEN: str(user_input[CONF_TOKEN]).strip(),
            }
            return await self.async_step_user(data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change endpoint details without changing installation identity."""
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input is not None:
            return await self.async_step_user(user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(dict(reconfigure_entry.data)),
        )

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, Any]:
        client = DynamicThermalChargeClient.from_config(
            async_get_clientsession(self.hass), data
        )
        return await client.async_snapshot()


def _schema(data: Mapping[str, Any] | None = None) -> vol.Schema:
    current = data or {}
    protocol = str(
        current.get(CONF_PROTOCOL, current.get("scheme", SUPPORTED_PROTOCOLS[0]))
    ).lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        protocol = SUPPORTED_PROTOCOLS[0]
    return vol.Schema(
        {
            vol.Required(
                CONF_PROTOCOL,
                default=protocol,
            ): vol.In(SUPPORTED_PROTOCOLS),
            vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_PORT,
                default=current.get(CONF_PORT, 8080),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required(CONF_TOKEN, default=current.get(CONF_TOKEN, "")): str,
        }
    )


def _normalized_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize form data while keeping host and port as separate fields."""
    raw_host = data.get(CONF_HOST)
    raw_port = data.get(CONF_PORT)
    raw_token = data.get(CONF_TOKEN)
    if raw_host is None or raw_port is None or raw_token is None:
        raise ValueError("protocol, host, port and token are required")
    host = str(raw_host).strip()
    token = str(raw_token).strip()
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    protocol = str(
        data.get(CONF_PROTOCOL, data.get("scheme", SUPPORTED_PROTOCOLS[0]))
    ).strip().lower()
    if (
        not host
        or not token
        or not 1 <= port <= 65535
        or protocol not in SUPPORTED_PROTOCOLS
        or "://" in host
        or "/" in host
    ):
        raise ValueError("protocol, host, port and token are required")
    return {
        CONF_PROTOCOL: protocol,
        CONF_HOST: host,
        CONF_PORT: port,
        CONF_TOKEN: token,
    }


__all__ = ["DynamicThermalChargeConfigFlow"]
