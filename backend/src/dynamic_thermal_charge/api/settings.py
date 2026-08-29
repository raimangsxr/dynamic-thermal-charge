"""HTTP settings projected from the canonical system configuration store."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..persistence.secret_digest import secret_matches


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
MINIMUM_TOKEN_LENGTH = 32
PLACEHOLDER_TOKENS = frozenset(
    {"changeme", "change-me", "secret", "token", "please-change-me",
     "dtc-api-token", "your-token-here", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}
)


class ApiSettingsError(ValueError):
    """The API cannot start with the persisted configuration as stored."""


@dataclass(frozen=True)
class ApiSettings:
    # Clear text is accepted only as an injected testing/embedding boundary.
    token: str | None = field(default=None, repr=False)
    token_digest: str | None = field(default=None, repr=False)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    stale_seconds: float | None = None
    cors_origins: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.token is not None:
            _require_usable_token(self.token)
        if self.token is not None and self.token_digest is not None:
            raise ApiSettingsError("configure either a token or its digest, never both")

    @property
    def exposed_beyond_localhost(self) -> bool:
        return self.host not in ("127.0.0.1", "localhost", "::1")

    def accepts(self, offered: str) -> bool:
        if self.token_digest is not None:
            return secret_matches(offered, self.token_digest)
        from .security import tokens_match
        return self.token is not None and tokens_match(offered, self.token)

    @property
    def configured(self) -> bool:
        return self.token is not None or self.token_digest is not None


def settings_from_repository(repository) -> ApiSettings:
    """Build the HTTP edge configuration without consulting process state."""
    snapshot = repository.current()
    configured = snapshot.configuration.api
    secret = snapshot.secrets.get("admin_token_digest")
    return ApiSettings(
        token_digest=None if secret is None else secret.value,
        host=configured.host,
        port=configured.port,
        stale_seconds=configured.stale_seconds,
        cors_origins=configured.cors_origins,
    )


def _require_usable_token(token: str) -> None:
    if len(token) < MINIMUM_TOKEN_LENGTH:
        raise ApiSettingsError(
            f"administrator token is too short: at least {MINIMUM_TOKEN_LENGTH} characters required"
        )
    if token.lower() in PLACEHOLDER_TOKENS:
        raise ApiSettingsError("administrator token cannot be an example value")


__all__ = [
    "DEFAULT_HOST", "DEFAULT_PORT", "MINIMUM_TOKEN_LENGTH", "ApiSettings",
    "ApiSettingsError", "settings_from_repository",
]
