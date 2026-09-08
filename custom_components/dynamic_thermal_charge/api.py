"""Small asynchronous client for the generic backend operational API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_TOKEN,
    REQUEST_TIMEOUT_SECONDS,
    SUPPORTED_PROTOCOLS,
)


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


class DynamicThermalChargeResponseError(DynamicThermalChargeConnectionError):
    """The backend returned a response that is not the operational contract."""


class DynamicThermalChargeInstallationError(DynamicThermalChargeResponseError):
    """The endpoint belongs to a different backend installation."""


@dataclass(frozen=True)
class DynamicThermalChargeClient:
    """Bearer-authenticated client using Home Assistant's shared aiohttp session."""

    session: ClientSession
    host: str
    port: int
    token: str
    protocol: str = "http"

    @classmethod
    def from_config(
        cls, session: ClientSession, data: dict[str, Any]
    ) -> DynamicThermalChargeClient:
        raw_host = data.get(CONF_HOST)
        raw_port = data.get(CONF_PORT)
        raw_token = data.get(CONF_TOKEN)
        if raw_host is None or raw_port is None or raw_token is None:
            raise ValueError("host, port and token are required")
        host = str(raw_host).strip()
        if not host:
            raise ValueError("host cannot be empty")
        if "://" in host or "/" in host:
            raise ValueError("host must not include a protocol or path")
        protocol = str(
            data.get(CONF_PROTOCOL, data.get("scheme", "http"))
        ).strip().lower()
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("unsupported protocol")
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("port out of range")
        token = str(raw_token).strip()
        if not token:
            raise ValueError("token cannot be empty")
        return cls(session, host, port, token, protocol)

    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{self.protocol}://{host}:{self.port}/api/v1"

    async def async_snapshot(self) -> dict[str, Any]:
        return validate_snapshot(await self._request("GET", "/operational/snapshot"))

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
        request_kwargs: dict[str, Any] = {
            "headers": headers,
            "json": payload,
            "timeout": timeout,
        }
        # aiohttp verifies the CA chain and hostname by default.  Passing
        # ``ssl=True`` explicitly for HTTPS makes that security property
        # intentional and leaves no opt-out in the integration configuration.
        if self.protocol == "https":
            request_kwargs["ssl"] = True
        try:
            async with self.session.request(
                method,
                url,
                **request_kwargs,
            ) as response:
                raw = await response.text()
        except (ClientError, OSError, TimeoutError, ValueError) as exc:
            raise DynamicThermalChargeConnectionError("backend connection failed") from exc
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            if response.status == 401:
                raise DynamicThermalChargeAuthError("backend rejected the token") from exc
            if response.status >= 400:
                body = {}
            else:
                raise DynamicThermalChargeConnectionError(
                    "backend returned invalid JSON"
                ) from exc
        if response.status == 401:
            raise DynamicThermalChargeAuthError("backend rejected the token")
        if response.status == 409:
            raise DynamicThermalChargeConflictError(
                _message(body, secrets=(self.token,))
            )
        if response.status >= 400:
            if response.status == 422:
                raise DynamicThermalChargeValidationError(
                    _message(body, secrets=(self.token,))
                )
            raise DynamicThermalChargeConnectionError(
                _message(body, secrets=(self.token,))
            )
        if not isinstance(body, dict):
            raise DynamicThermalChargeConnectionError("backend returned an unexpected response")
        return body


def validate_snapshot(
    body: Any,
    *,
    expected_installation_id: str | None = None,
) -> dict[str, Any]:
    """Validate the small, authoritative shape used by every HA entity."""
    if not isinstance(body, dict):
        raise DynamicThermalChargeResponseError("backend returned an unexpected response")

    installation = body.get("installation")
    if not isinstance(installation, dict):
        raise DynamicThermalChargeResponseError("backend snapshot has no installation")
    installation_id = installation.get("id")
    if installation_id is None or not str(installation_id).strip():
        raise DynamicThermalChargeResponseError("backend snapshot has no installation id")
    if expected_installation_id is not None and str(installation_id) != str(
        expected_installation_id
    ):
        raise DynamicThermalChargeInstallationError("backend installation id changed")

    revision = body.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise DynamicThermalChargeResponseError("backend snapshot has no valid revision")

    accumulators = body.get("accumulators")
    if not isinstance(accumulators, list):
        raise DynamicThermalChargeResponseError("backend snapshot has no accumulator inventory")
    seen_ids: set[str] = set()
    for accumulator in accumulators:
        if not isinstance(accumulator, dict):
            raise DynamicThermalChargeResponseError("backend snapshot has an invalid accumulator")
        accumulator_id = accumulator.get("id")
        if accumulator_id is None or not str(accumulator_id).strip():
            raise DynamicThermalChargeResponseError("backend snapshot has an invalid accumulator id")
        normalized_id = str(accumulator_id)
        if normalized_id in seen_ids:
            raise DynamicThermalChargeResponseError("backend snapshot has duplicate accumulators")
        seen_ids.add(normalized_id)

    health = body.get("health")
    if health not in {"running", "idle", "degraded", "error"}:
        raise DynamicThermalChargeResponseError("backend snapshot has an invalid health")
    return body


def _message(body: Any, *, secrets: tuple[str, ...] = ()) -> str:
    if isinstance(body, dict):
        message = body.get("message") or body.get("detail")
        if isinstance(message, str):
            normalized = message.strip()
            lowered = normalized.lower()
            if normalized and not any(
                marker in lowered
                for marker in ("token", "bearer", "password", "secret", "api_key", "authorization")
            ) and not any(
                secret and secret.lower() in lowered for secret in secrets
            ):
                return normalized[:200]
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
    "DynamicThermalChargeInstallationError",
    "DynamicThermalChargeResponseError",
    "DynamicThermalChargeValidationError",
    "validate_snapshot",
]
