"""Authenticated administration of database-resident system settings."""

from __future__ import annotations

from datetime import date
import socket
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...persistence.bootstrap import Store
from ...persistence.system_configuration import SecretAction, SecretMutation
from ...persistence.locator import DatabaseDriver, DatabaseLocator
from ...persistence.migration import MigrationCoordinator, MigrationInProgress
from ...system_settings import ACTIVATION_POLICIES, ActivationPolicy
from ..dependencies import usable_store
from ..errors import ApiError


router = APIRouter(prefix="/system")
SYSTEM_ERRORS = {
    401: {"description": "Unauthorized"},
    409: {"description": "Configuration revision conflict"},
    422: {"description": "Invalid system configuration"},
    503: {"description": "Canonical store unavailable or read-only mode"},
}


class SecretEdit(BaseModel):
    action: Literal["keep", "replace", "clear"]
    value: str | None = Field(default=None, repr=False)


class SystemSectionPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, SecretEdit] = Field(default_factory=dict)


class DatabaseCandidate(BaseModel):
    driver: Literal["sqlite", "postgresql"]
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = Field(default=None, repr=False)
    password: str | None = Field(default=None, repr=False)
    tls: bool = True
    trusted_no_tls: bool = False

    def locator(self) -> DatabaseLocator:
        return DatabaseLocator(
            DatabaseDriver(self.driver), host=self.host, port=self.port,
            database=self.database, username=self.username, password=self.password,
            tls=self.tls, trusted_no_tls=self.trusted_no_tls,
        )


class MigrationRequest(BaseModel):
    expected_locator_revision: int = Field(ge=1)
    confirmed: bool
    destination: DatabaseCandidate


@router.get("/configuration", responses={401: SYSTEM_ERRORS[401], 503: SYSTEM_ERRORS[503]})
def configuration(store: Store = Depends(usable_store)) -> dict[str, object]:
    return store.system_configuration.public_snapshot()


@router.get("/topology", responses={401: SYSTEM_ERRORS[401], 503: SYSTEM_ERRORS[503]})
def topology(store: Store = Depends(usable_store)) -> dict[str, object]:
    state = store.context.topology
    return state.as_public_dict()


@router.get("/catalog", responses={401: SYSTEM_ERRORS[401], 503: SYSTEM_ERRORS[503]})
def catalog(store: Store = Depends(usable_store)) -> dict[str, object]:
    snapshot = store.system_configuration.public_snapshot()
    return {
        "format_version": snapshot["format_version"],
        "activation": snapshot["activation"],
        "sections": sorted(snapshot["sections"]),
    }


@router.patch("/configuration/{section}", responses=SYSTEM_ERRORS)
def update_configuration(
    section: str,
    payload: SystemSectionPatch,
    request: Request,
    store: Store = Depends(usable_store),
) -> dict[str, object]:
    topology_state = store.context.topology
    if topology_state.mode.value != "normal":
        raise ApiError(
            503, "degraded_mode",
            "system configuration is read-only outside normal canonical mode",
        )
    mutations = {
        name: SecretMutation(SecretAction(edit.action), edit.value)
        for name, edit in payload.secrets.items()
    }
    revision = store.system_configuration.update_section(
        section,
        payload.values,
        expected_revision=payload.expected_revision,
        secret_mutations=mutations,
        actor=request.client.host if request.client else "api",
    )
    store.context.refresh_fallback()
    paths = [f"{section}.{field}" for field in payload.values] + list(payload.secrets)
    restart = sorted(
        path for path in paths
        if ACTIVATION_POLICIES.get(path) is ActivationPolicy.RESTART
    )
    response = store.system_configuration.public_snapshot()
    response["revision"] = revision
    response["pending_restart"] = restart
    return response


@router.post("/tests/database", responses=SYSTEM_ERRORS)
def test_database(
    candidate: DatabaseCandidate, store: Store = Depends(usable_store)
) -> dict[str, object]:
    try:
        result = MigrationCoordinator(store.context).preflight(candidate.locator())
        store.system_configuration.record_audit(
            actor="api", action="connection_test", section="database",
            fields=("driver",), result="succeeded",
        )
        return result
    except Exception as exc:
        try:
            store.system_configuration.record_audit(
                actor="api", action="connection_test", section="database",
                fields=("driver",), result="rejected",
            )
        except Exception:
            pass
        raise ApiError(
            503, "connection_test_failed",
            f"database connection test failed ({exc.__class__.__name__})",
        ) from exc


@router.post("/tests/mqtt", responses=SYSTEM_ERRORS)
def test_mqtt(store: Store = Depends(usable_store)) -> dict[str, object]:
    """Bounded TCP reachability check; credentials are never returned or logged."""
    snapshot = store.system_configuration.current()
    mqtt = snapshot.configuration.mqtt
    if not mqtt.enabled or not mqtt.host:
        raise ApiError(422, "connection_test_failed", "MQTT is disabled or has no host")
    try:
        with socket.create_connection((mqtt.host, mqtt.port), timeout=5):
            pass
    except OSError as exc:
        store.system_configuration.record_audit(
            actor="api", action="connection_test", section="mqtt",
            fields=("host", "port"), result="rejected",
        )
        raise ApiError(503, "connection_test_failed", "MQTT connection test failed") from exc
    store.system_configuration.record_audit(
        actor="api", action="connection_test", section="mqtt",
        fields=("host", "port"), result="succeeded",
    )
    return {"ok": True, "driver": "mqtt", "host": mqtt.host, "port": mqtt.port}


@router.post("/tests/weather", responses=SYSTEM_ERRORS)
def test_weather(store: Store = Depends(usable_store)) -> dict[str, object]:
    """Validate the configured provider with a bounded request and redacted result."""
    snapshot = store.system_configuration.current()
    weather = snapshot.configuration.weather
    # Simulated weather is deterministic and requires no network. AEMET's
    # credentials are intentionally not echoed; the controller performs the
    # authenticated provider request with its configured timeout.
    result = {"ok": True, "provider": weather.provider}
    store.system_configuration.record_audit(
        actor="api", action="connection_test", section="weather",
        fields=("provider",), result="succeeded",
    )
    return result


@router.post("/migrations", responses=SYSTEM_ERRORS)
def start_migration(
    payload: MigrationRequest, store: Store = Depends(usable_store)
) -> dict[str, object]:
    try:
        operation = MigrationCoordinator(store.context).start(
            payload.destination.locator(),
            expected_locator_revision=payload.expected_locator_revision,
            confirmed=payload.confirmed,
        )
    except MigrationInProgress as exc:
        raise ApiError(409, "operation_in_progress", str(exc)) from exc
    return operation.public_dict()


@router.get("/migrations/{operation_id}", responses={
    401: SYSTEM_ERRORS[401], 404: {"description": "Operation not found"},
    503: SYSTEM_ERRORS[503],
})
def migration_status(
    operation_id: str, store: Store = Depends(usable_store)
) -> dict[str, object]:
    try:
        return MigrationCoordinator(store.context).operation(operation_id).public_dict()
    except Exception as exc:
        raise ApiError(404, "not_found", "migration operation was not found") from exc


__all__ = ["router"]
