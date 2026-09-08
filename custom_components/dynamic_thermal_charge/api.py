"""Small asynchronous client for the generic backend operational API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, REQUEST_TIMEOUT_SECONDS


class DynamicThermalChargeError(Exception):
    """Base error raised by the local REST client."""


class DynamicThermalChargeConnectionError(DynamicThermalChargeError):
    """The backend could not be reached or returned invalid JSON."""


class DynamicThermalChargeAuthError(DynamicThermalChargeError):
    """The backend rejected the token."""


class DynamicThermalChargeConflictError(DynamicThermalChargeError):
    """The optimistic revision no longer matches the backend."""


class DynamicThermalChargeValidationError(DynamicThermalChargeError):
    """The backend rejected a command without changing state."""


@dataclass(frozen=True)
class DynamicThermalChargeClient:
    """Bearer-authenticated client using Home Assistant's shared aiohttp session."""

    session: ClientSession
    host: str
    port: int
    token: str

    @classmethod
    def from_config(
        cls, session: ClientSession, data: dict[str, Any]
    ) -> DynamicThermalChargeClient:
        host = str(data[CONF_HOST]).strip()
        if not host:
            raise ValueError("host cannot be empty")
        return cls(session, host, int(data[CONF_PORT]), str(data[CONF_TOKEN]))

    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.port}/api/v1"

    async def async_snapshot(self) -> dict[str, Any]:
        return await self._request("GET", "/operational/snapshot")

    async def async_forecast(self) -> dict[str, Any]:
        return await self._request("GET", "/operational/forecast")

    async def async_set_automatic_control(self, enabled: bool, revision: int) -> dict[str, Any]:
        return await self._command(
            "/operational/control/automatic",
            {"enabled": enabled, "expected_revision": revision},
        )

    async def async_recalculate(self, revision: int) -> dict[str, Any]:
        return await self._command(
            "/operational/recalculate",
            {"expected_revision": revision},
        )

    async def async_set_mode(self, accumulator_id: str, mode: str, revision: int) -> dict[str, Any]:
        return await self._command(
            f"/operational/accumulators/{_path_segment(accumulator_id)}/mode",
            {"mode": mode, "expected_revision": revision},
        )

    async def async_set_temperature(
        self, accumulator_id: str, temperature_c: float, revision: int
    ) -> dict[str, Any]:
        return await self._command(
            f"/operational/accumulators/{_path_segment(accumulator_id)}/target",
            {
                "target_temperature_c": temperature_c,
                "expected_revision": revision,
            },
        )

    async def _command(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, payload)

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        timeout = ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        try:
            async with self.session.request(
                method,
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            ) as response:
                raw = await response.text()
        except (ClientError, TimeoutError) as exc:
            raise DynamicThermalChargeConnectionError("backend connection failed") from exc
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise DynamicThermalChargeConnectionError("backend returned invalid JSON") from exc
        if response.status == 401:
            raise DynamicThermalChargeAuthError("backend rejected the token")
        if response.status == 409:
            raise DynamicThermalChargeConflictError(_message(body))
        if response.status >= 400:
            if response.status == 422:
                raise DynamicThermalChargeValidationError(_message(body))
            raise DynamicThermalChargeConnectionError(_message(body))
        if not isinstance(body, dict):
            raise DynamicThermalChargeConnectionError("backend returned an unexpected response")
        return body


def _message(body: Any) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("detail") or "backend rejected the request")
    return "backend rejected the request"


def _path_segment(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = [
    "DynamicThermalChargeAuthError",
    "DynamicThermalChargeClient",
    "DynamicThermalChargeConflictError",
    "DynamicThermalChargeConnectionError",
    "DynamicThermalChargeError",
    "DynamicThermalChargeValidationError",
]
