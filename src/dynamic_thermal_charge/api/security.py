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


def authorize(request: Request, authorization: str | None) -> None:
    """Raise unless the request carries the configured credential."""
    settings: ApiSettings = request.app.state.settings
    offered = extract_token(authorization)
    if offered is not None and tokens_match(offered, settings.token):
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
]
