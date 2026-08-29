"""Token authentication.

Two properties matter here and both are cheap now and expensive later:

* The comparison runs in constant time, so the token cannot be deduced by
  measuring response times.
* A token that is absent and a token that is wrong produce the *same* answer, so
  a caller learns nothing from the difference.
"""

from __future__ import annotations

import logging
import secrets
import hashlib

from fastapi import Header, HTTPException, Request, status

from .settings import ApiSettings


logger = logging.getLogger(__name__)

SCHEME = "Bearer"
#: Deliberately identical for "no credential" and "wrong credential".
UNAUTHORIZED_DETAIL = "unauthorized"


def tokens_match(offered: str, expected: str) -> bool:
    """Constant-time comparison.

    ``==`` returns as soon as two bytes differ, which leaks the token one byte at
    a time to anyone who can measure response times. Comparing the encoded forms
    also keeps a length difference from leaking.
    """
    return secrets.compare_digest(offered.encode("utf-8"), expected.encode("utf-8"))


def extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != SCHEME.lower():
        return None
    return value.strip() or None

def new_relay_test_credential() -> str:
    """A capability delivered exactly once; 32 random bytes = 256 bits."""
    return secrets.token_urlsafe(32)

def relay_test_credential_digest(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()

def relay_test_credentials_match(offered: str | None, digest: str) -> bool:
    return offered is not None and secrets.compare_digest(relay_test_credential_digest(offered), digest)


def authorize(request: Request, authorization: str | None) -> None:
    """Raise unless the request carries the configured credential."""
    settings: ApiSettings = request.app.state.settings
    offered = extract_token(authorization)
    active_settings = settings
    # Persisted token rotation is hot: every request resolves the canonical
    # digest. Explicit clear-text settings remain an injected test boundary.
    if settings.token is None:
        try:
            from .settings import settings_from_repository
            store = request.app.state.store_factory()
            active_settings = settings_from_repository(store.system_configuration)
            request.app.state.settings = active_settings
        except Exception:
            # During a classified canonical outage, authentication remains
            # available from the local continuity snapshot.  The snapshot only
            # contains the non-reversible administrator digest.
            try:
                store = request.app.state.store_factory()
                snapshot = store.context.fallback.snapshot()
                if snapshot is not None and snapshot.admin_token_digest:
                    from ..system_settings import SystemConfiguration
                    from .settings import ApiSettings
                    docs = snapshot.configuration.get("system")
                    if isinstance(docs, dict):
                        system = SystemConfiguration.from_documents(docs)
                        active_settings = ApiSettings(
                            token_digest=snapshot.admin_token_digest,
                            host=system.api.host,
                            port=system.api.port,
                            stale_seconds=system.api.stale_seconds,
                            cors_origins=system.api.cors_origins,
                        )
            except Exception:
                active_settings = settings
    if offered is not None and active_settings.accepts(offered):
        return
    # The token itself is never logged, not even a rejected one.
    logger.warning(
        "Rejected unauthorized request to %s from %s",
        request.url.path,
        request.client.host if request.client else "unknown",
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=UNAUTHORIZED_DETAIL,
        headers={"WWW-Authenticate": SCHEME},
    )


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency. Applied to every route except the health check."""
    authorize(request, authorization)


__all__ = [
    "SCHEME",
    "UNAUTHORIZED_DETAIL",
    "authorize",
    "extract_token",
    "require_token",
    "tokens_match",
    "new_relay_test_credential", "relay_test_credential_digest", "relay_test_credentials_match",
]
