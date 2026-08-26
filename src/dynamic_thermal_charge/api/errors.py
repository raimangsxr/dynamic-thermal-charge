"""Domain errors to a uniform HTTP body.

No traceback, no filesystem path, no fragment of the connection string ever
reaches a client. The mapping reuses the domain taxonomy from the previous phase
rather than inventing a second one.

503 for "database unavailable" and "schema unusable" is deliberate: from the
client's point of view those are transient or maintenance conditions, not faults
in its request.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..persistence import (
    ConfigConflictError,
    ConfigStoreEmptyError,
    ConfigStoreError,
    ConfigStoreUnavailableError,
    ConfigValidationError,
    SchemaVersionError,
    SecretRejectedError,
)
from ..persistence.url import DatabaseUrlError


logger = logging.getLogger(__name__)

CODE_UNAUTHORIZED = "unauthorized"
CODE_NOT_FOUND = "not_found"
CODE_ALREADY_EXISTS = "already_exists"
CODE_CONFLICT = "config_conflict"
CODE_VALIDATION = "validation_failed"
CODE_SECRET_REJECTED = "secret_rejected"
CODE_BAD_REQUEST = "bad_request"
CODE_NO_CONFIGURATION = "no_configuration"
CODE_SCHEMA_UNUSABLE = "schema_unusable"
CODE_STORE_UNAVAILABLE = "store_unavailable"
CODE_INTERNAL = "internal_error"


class ApiError(HTTPException):
    """An error with a stable machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field: str | None = None,
        heater_id: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.field = field
        self.heater_id = heater_id
        super().__init__(status_code=status_code, detail=message)


def not_found(message: str, field: str | None = None) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, message, field=field)


def bad_request(message: str, field: str | None = None) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, CODE_BAD_REQUEST, message, field=field)


def _body(code: str, message: str, field=None, heater_id=None) -> dict:
    return {"code": code, "message": message, "field": field, "heater_id": heater_id}


def register_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(exc.code, exc.message, exc.field, exc.heater_id),
            headers=exc.headers,
        )

    @app.exception_handler(HTTPException)
    def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = (
            CODE_UNAUTHORIZED
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else CODE_BAD_REQUEST
            if exc.status_code < 500
            else CODE_INTERNAL
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(SecretRejectedError)
    def _secret(_request: Request, exc: SecretRejectedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_body(CODE_SECRET_REJECTED, str(exc), exc.field, exc.heater_id),
        )

    @app.exception_handler(ConfigConflictError)
    def _conflict(_request: Request, exc: ConfigConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_body(CODE_CONFLICT, str(exc)),
        )

    @app.exception_handler(ConfigValidationError)
    def _validation(_request: Request, exc: ConfigValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_body(CODE_VALIDATION, str(exc), exc.field, exc.heater_id),
        )

    @app.exception_handler(ConfigStoreEmptyError)
    def _empty(_request: Request, exc: ConfigStoreEmptyError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body(CODE_NO_CONFIGURATION, str(exc)),
        )

    @app.exception_handler(SchemaVersionError)
    def _schema(_request: Request, exc: SchemaVersionError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body(CODE_SCHEMA_UNUSABLE, str(exc)),
        )

    @app.exception_handler(ConfigStoreUnavailableError)
    def _unavailable(_request: Request, exc: ConfigStoreUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body(CODE_STORE_UNAVAILABLE, str(exc)),
        )

    @app.exception_handler(DatabaseUrlError)
    def _url(_request: Request, exc: DatabaseUrlError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body(CODE_STORE_UNAVAILABLE, str(exc)),
        )

    @app.exception_handler(ConfigStoreError)
    def _store(_request: Request, exc: ConfigStoreError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_body(CODE_STORE_UNAVAILABLE, str(exc)),
        )

    @app.exception_handler(Exception)
    def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # The traceback goes to the log, never to the client.
        logger.exception("Unhandled error serving a request")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(
                CODE_INTERNAL,
                "the request could not be completed; see the service logs",
            ),
        )


__all__ = [
    "ApiError",
    "CODE_ALREADY_EXISTS",
    "CODE_BAD_REQUEST",
    "CODE_CONFLICT",
    "CODE_INTERNAL",
    "CODE_NOT_FOUND",
    "CODE_NO_CONFIGURATION",
    "CODE_SCHEMA_UNUSABLE",
    "CODE_SECRET_REJECTED",
    "CODE_STORE_UNAVAILABLE",
    "CODE_UNAUTHORIZED",
    "CODE_VALIDATION",
    "bad_request",
    "not_found",
    "register_error_handlers",
]
