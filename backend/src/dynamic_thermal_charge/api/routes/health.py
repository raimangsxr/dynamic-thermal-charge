"""The health check: the one route without a credential (FR-052).

Deliberately mute. It says the process is answering and nothing else: not whether
the database is reachable, not the schema revision, not whether an installation
exists. It exists so systemd and a reverse proxy can check the process without
being handed the token, and anything it revealed would be revealed to everyone.
"""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter()


@router.get(
    "/health",
    summary="Liveness of the API process",
    description=(
        "The only route that needs no credential. Reports that the process is "
        "answering and nothing else: it deliberately reveals nothing about the "
        "installation, the database or the schema."
    ),
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
def health() -> dict[str, str]:
    return {"status": "ok"}


__all__ = ["router"]
