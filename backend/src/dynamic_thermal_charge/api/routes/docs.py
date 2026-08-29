"""The self-describing documentation, behind the credential.

FastAPI's built-in docs routes are disabled in ``create_app`` and re-served here
so the router-level dependency applies to them. The description enumerates the
whole surface of the API; nobody needs that unauthenticated (FR-007, FR-042).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse


router = APIRouter()


@router.get("/openapi.json", include_in_schema=False)
def openapi(request: Request) -> JSONResponse:
    app = request.app
    return JSONResponse(
        get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
    )


@router.get("/docs", include_in_schema=False)
def docs(request: Request) -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url="/openapi.json", title=f"{request.app.title} — API"
    )


__all__ = ["router"]
