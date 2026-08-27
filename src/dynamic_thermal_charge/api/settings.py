"""API settings, read from the environment.

Deliberately **not** from the database. These are the values needed *before* the
database can be read, and in the token's case before the first request can be
answered at all. Storing them in the configuration store would create a circular
dependency, and for the token it would put a secret in exactly the place
principle III excludes it from.

Consistent with ``DTC_DATABASE_URL``: the location and credentials of a store
never live inside the store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


TOKEN_ENV = "DTC_API_TOKEN"
HOST_ENV = "DTC_API_HOST"
PORT_ENV = "DTC_API_PORT"
STALE_SECONDS_ENV = "DTC_API_STALE_SECONDS"
CORS_ORIGINS_ENV = "DTC_API_CORS_ORIGINS"

#: Local interface only. Exposing the API on the network must be a deliberate act.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MINIMUM_TOKEN_LENGTH = 32

#: Values that mean "nobody edited the environment file". Accepting any of them
#: would leave the API listening with no real protection.
PLACEHOLDER_TOKENS = frozenset(
    {
        "changeme",
        "change-me",
        "secret",
        "token",
        "please-change-me",
        "dtc-api-token",
        "your-token-here",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    }
)


class ApiSettingsError(ValueError):
    """The API cannot start with the environment as given."""


@dataclass(frozen=True)
class ApiSettings:
    token: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    #: Overrides the tolerance derived from the controller's own polling cadence.
    stale_seconds: float | None = None
    #: Empty means no cross-origin client is allowed. Restrictive by default.
    cors_origins: tuple[str, ...] = field(default_factory=tuple)

    @property
    def exposed_beyond_localhost(self) -> bool:
        return self.host not in ("127.0.0.1", "localhost", "::1")


def load_settings(environ: Mapping[str, str] | None = None) -> ApiSettings:
    """Read and validate the API settings, or refuse to start."""
    environment = os.environ if environ is None else environ
    token = environment.get(TOKEN_ENV, "").strip()
    _require_usable_token(token)

    host = environment.get(HOST_ENV, "").strip() or DEFAULT_HOST
    port = _positive_int(environment.get(PORT_ENV), PORT_ENV, DEFAULT_PORT)
    raw_stale = environment.get(STALE_SECONDS_ENV, "").strip()
    stale_seconds: float | None = None
    if raw_stale:
        try:
            stale_seconds = float(raw_stale)
        except ValueError as exc:
            raise ApiSettingsError(
                f"{STALE_SECONDS_ENV} must be a number of seconds; received "
                f"{raw_stale!r}"
            ) from exc
        if stale_seconds <= 0:
            raise ApiSettingsError(f"{STALE_SECONDS_ENV} must be positive")

    raw_origins = environment.get(CORS_ORIGINS_ENV, "")
    origins = tuple(
        origin.strip() for origin in raw_origins.split(",") if origin.strip()
    )
    if "*" in origins:
        # A wildcard combined with credentials is rejected by browsers anyway,
        # and it makes no sense for this surface.
        raise ApiSettingsError(
            f"{CORS_ORIGINS_ENV} does not accept '*': this API requires a "
            "credential, and a wildcard origin with credentials is refused by "
            "browsers. Name the origins explicitly"
        )

    return ApiSettings(
        token=token,
        host=host,
        port=port,
        stale_seconds=stale_seconds,
        cors_origins=origins,
    )


def _require_usable_token(token: str) -> None:
    if not token:
        raise ApiSettingsError(
            f"{TOKEN_ENV} is not set. The API will not listen without a "
            "credential. Generate one with: "
            "python3 -c 'import secrets; print(secrets.token_urlsafe(32))' "
            "and put it in /etc/dynamic-thermal-charge/environment"
        )
    if len(token) < MINIMUM_TOKEN_LENGTH:
        raise ApiSettingsError(
            f"{TOKEN_ENV} is too short: {len(token)} characters, at least "
            f"{MINIMUM_TOKEN_LENGTH} required. Anyone holding this token can "
            "change the maximum power and the pin assignments"
        )
    if token.lower() in PLACEHOLDER_TOKENS:
        raise ApiSettingsError(
            f"{TOKEN_ENV} still holds an example value. Generate a real one; the "
            "API will not listen with a placeholder credential"
        )


def _positive_int(raw: str | None, name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiSettingsError(f"{name} must be a whole number; received {raw!r}") from exc
    if not 1 <= value <= 65535:
        raise ApiSettingsError(f"{name} must be between 1 and 65535; received {value}")
    return value


__all__ = [
    "CORS_ORIGINS_ENV",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HOST_ENV",
    "MINIMUM_TOKEN_LENGTH",
    "PORT_ENV",
    "STALE_SECONDS_ENV",
    "TOKEN_ENV",
    "ApiSettings",
    "ApiSettingsError",
    "load_settings",
]
