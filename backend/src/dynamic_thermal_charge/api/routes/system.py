"""Authenticated administration of database-resident system settings."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import logging
import socket
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...persistence.bootstrap import Store
from ...persistence.system_configuration import SecretAction, SecretMutation
from ...persistence.locator import DatabaseDriver, DatabaseLocator
from ...persistence.migration import MigrationCoordinator, MigrationInProgress
from ...system_settings import ACTIVATION_POLICIES, ActivationPolicy
from ...weather import AemetWeatherProvider, future_forecast_points, weather_config_from_system
from ...persistence.history import SqlHistoryRecorder
from ..dependencies import usable_store
from ..errors import ApiError
from ..schemas import WeatherRefreshResponse


router = APIRouter(prefix="/system")
logger = logging.getLogger(__name__)
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
    return _public_snapshot(store)


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
    response = _public_snapshot(store)
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


@router.post(
    "/weather/refresh",
    response_model=WeatherRefreshResponse,
    responses=SYSTEM_ERRORS,
    summary="Refresh the AEMET forecast now",
)
def refresh_weather(request: Request, store: Store = Depends(usable_store)) -> WeatherRefreshResponse:
    """Run one additional AEMET request without changing the automatic timer."""
    lock = getattr(request.app.state, "weather_refresh_lock", None)
    if lock is None or not lock.acquire(blocking=False):
        raise ApiError(409, "weather_refresh_in_progress", "ya hay una consulta meteorológica en curso")
    try:
        snapshot = store.system_configuration.current()
        settings = snapshot.configuration.weather
        if settings.provider != "aemet":
            raise ApiError(422, "weather_not_configured", "AEMET no está configurado como proveedor meteorológico")
        secret = snapshot.secrets.get("aemet_api_key")
        if secret is None:
            raise ApiError(422, "weather_not_configured", "la clave de AEMET no está configurada")
        config, _revision = store.repository.current()
        timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
        weather_config = weather_config_from_system(settings)
        assert weather_config.aemet is not None
        provider = AemetWeatherProvider(
            weather_config.aemet,
            api_key=secret.value,
            timezone_name=timezone_name,
        )
        now = request.app.state.clock()
        local_date = now.astimezone(ZoneInfo(timezone_name)).date()
        planning = store.planning
        cycle = planning.forecast_cycle(local_date, now)
        next_run_at = cycle.next_run_at or now + timedelta(minutes=settings.refresh_minutes)
        try:
            forecast = provider.forecast_for(local_date)
        except Exception as exc:
            safe_error = _safe_weather_error(exc, secret.value)
            logger.warning(
                "Manual AEMET refresh failed (%s): %s",
                exc.__class__.__name__,
                safe_error,
            )
            failed = replace(
                cycle,
                last_attempt_at=now,
                last_result="error",
                last_error=safe_error,
                stale=True,
                next_run_at=next_run_at,
            )
            _save_forecast_cycle(planning, failed)
            raise ApiError(503, "weather_refresh_failed", safe_error) from exc

        history = SqlHistoryRecorder(
            store.application_engine or store.engine,
            store.repository.installation_id(),
            store.location,
        )
        forecast_ref = history.record_forecast(forecast)
        completed = replace(
            cycle,
            last_attempt_at=now,
            last_result="success",
            last_error=None,
            stale=False,
            next_run_at=next_run_at,
        )
        _save_forecast_cycle(planning, completed, forecast_ref)
        return WeatherRefreshResponse(
            status="success",
            forecast_status="success",
            forecast_last_attempt_at=now,
            forecast_last_error=None,
            forecast_next_run_at=next_run_at,
            forecast=_forecast_response(forecast, now),
        )
    finally:
        lock.release()


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


def _public_snapshot(store: Store) -> dict[str, object]:
    response = store.system_configuration.public_snapshot()
    status = store.planning.forecast_cycle_status() or {
        "forecast_status": None,
        "forecast_last_attempt_at": None,
        "forecast_last_error": None,
        "forecast_next_run_at": None,
    }
    sections = response["sections"]
    assert isinstance(sections, dict)
    weather = sections["weather"]
    assert isinstance(weather, dict)
    weather.update(status)
    return response


def _save_forecast_cycle(planning, state, forecast_ref=None) -> None:
    try:
        planning.save_forecast_cycle(state, forecast_ref)
    except Exception:
        # A status write must never turn a valid manual weather request into a
        # second failure, nor interfere with the controller's next refresh.
        pass


def _safe_weather_error(error: BaseException, secret: str | None = None) -> str:
    detail = str(error).strip() or "no se pudo obtener el forecast de AEMET"
    if secret:
        detail = detail.replace(secret, "[redacted]")
    return f"{error.__class__.__name__}: {detail[:480]}"


def _forecast_response(forecast, at) -> dict[str, object]:
    hourly_points = future_forecast_points(forecast.hourly_points, at)
    return {
        "date": forecast.date,
        "source": forecast.source,
        "average_temperature_c": forecast.average_temperature_c,
        "minimum_temperature_c": forecast.minimum_temperature_c,
        "maximum_temperature_c": forecast.maximum_temperature_c,
        "municipality": forecast.location,
        "hourly_points": [
            {
                "timestamp": point.timestamp,
                "temperature_c": point.temperature_c,
                "interpolated": point.interpolated,
            }
            for point in hourly_points
        ],
    }


__all__ = ["router"]
