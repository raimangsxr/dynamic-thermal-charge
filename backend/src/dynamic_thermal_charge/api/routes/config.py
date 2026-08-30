"""Reading and editing configuration.

Every write goes through the existing ``ConfigRepository``: the validation, the
atomicity and the optimistic lock are the ones already in place, not a second
implementation. Relaxing any of them here would mean the API could store what the
the configuration repository refuses (FR-025).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ...models import Heater, OutputConfig, ThermalProfile
from ...persistence import ConfigChange, ConfigValidationError
from ...persistence.bootstrap import Store
from ...persistence.gate import EXPECTED_REVISION
from ..dependencies import usable_store
from ..errors import ApiError, CODE_ALREADY_EXISTS, not_found
from ..schemas import (
    ERROR_RESPONSES,
    READ_RESPONSES,
    AddHeaterRequest,
    ChangeResponse,
    ConfigResponse,
    HeaterResponse,
    OutputView,
    ScheduleView,
    SetFieldRequest,
    ThermalProfileView,
    WeatherView,
)


router = APIRouter()


def _heater_view(heater: Heater) -> HeaterResponse:
    return HeaterResponse(
        id=heater.id,
        name=heater.name,
        model=heater.model,
        power_kw=heater.power_w / 1000,
        full_charge_hours=heater.full_charge_minutes / 60,
        target_charge=heater.target_charge,
        priority=heater.priority,
        enabled=heater.enabled,
        indoor_topic=heater.indoor_topic,
        output=OutputView(
            kind=heater.output.kind,
            pin=heater.output.pin,
            active_high=heater.output.active_high,
        ),
        thermal=(
            None
            if heater.thermal is None
            else ThermalProfileView(
                target_temperature_c=heater.thermal.target_temperature_c,
                design_outdoor_temperature_c=heater.thermal.design_outdoor_temperature_c,
                thermal_factor=heater.thermal.thermal_factor,
                min_charge=heater.thermal.min_charge,
                max_charge=heater.thermal.max_charge,
            )
        ),
    )


def _config_view(config, revision: int) -> ConfigResponse:
    schedule = None
    if config.schedule is not None:
        schedule = ScheduleView(
            timezone=config.schedule.timezone,
            start_time=f"{config.schedule.start_time:%H:%M}",
            end_time=f"{config.schedule.end_time:%H:%M}",
            weekdays=list(config.schedule.weekdays),
        )
    weather = None
    if config.weather is not None:
        aemet = config.weather.aemet
        weather = WeatherView(
            provider=config.weather.provider,
            municipality_code=None if aemet is None else aemet.municipality_code,
            # The NAME of the variable. Never its value (FR-022).
            api_key_env=None if aemet is None else aemet.api_key_env,
            timeout_seconds=None if aemet is None else aemet.timeout_seconds,
            simulated_average_temperature_c=(
                None
                if config.weather.simulated is None
                else config.weather.simulated.average_temperature_c
            ),
            simulated_minimum_temperature_c=(
                None
                if config.weather.simulated is None
                else config.weather.simulated.minimum_temperature_c
            ),
            fallback_average_temperature_c=(
                None
                if config.weather.fallback is None
                else config.weather.fallback.average_temperature_c
            ),
            fallback_minimum_temperature_c=(
                None
                if config.weather.fallback is None
                else config.weather.fallback.minimum_temperature_c
            ),
            retry_minutes=config.weather.watchdog.retry_minutes,
            refresh_minutes=config.weather.watchdog.refresh_minutes,
        )
    return ConfigResponse(
        config_revision=revision,
        schema_revision=EXPECTED_REVISION,
        max_total_power_kw=config.site.max_total_power_w / 1000,
        slot_minutes=config.site.slot_minutes,
        window_minutes=config.site.window_minutes,
        indoor_max_age_minutes=config.site.indoor_max_age_minutes,
        indoor_min_plausible_c=config.site.indoor_min_plausible_c,
        indoor_max_plausible_c=config.site.indoor_max_plausible_c,
        log_level=config.logging.level,
        state_file=config.runtime.state_file,
        poll_seconds=config.runtime.poll_seconds,
        retention_days=config.retention_days,
        schedule=schedule,
        weather=weather,
        heaters=[_heater_view(heater) for heater in config.heaters],
    )


def _change_view(change: ConfigChange) -> ChangeResponse:
    return ChangeResponse(
        entity=change.entity,
        entity_key=change.entity_key,
        field=change.field,
        old_value=change.old_value,
        new_value=change.new_value,
        action=change.action,
        revision_before=change.revision_before,
        revision_after=change.revision_after,
    )


@router.get(
    "/config",
    response_model=ConfigResponse,
    responses=READ_RESPONSES,
    summary="The whole installation configuration",
    description=(
        "Includes the configuration revision, needed for any write, and the "
        "schema revision. Never returns the database location or the value of the "
        "weather provider's key: only whether a key is configured."
    ),
)
def get_config(store: Store = Depends(usable_store)) -> ConfigResponse:
    config, revision = store.repository.current()
    return _config_view(config, revision)


@router.get(
    "/config/heaters/{heater_id}",
    response_model=HeaterResponse,
    responses={**READ_RESPONSES, 404: ERROR_RESPONSES[404]},
    summary="One storage heater",
)
def get_heater(heater_id: str, store: Store = Depends(usable_store)) -> HeaterResponse:
    config, _ = store.repository.current()
    for heater in config.heaters:
        if heater.id == heater_id:
            return _heater_view(heater)
    raise not_found(
        f"heater {heater_id!r} does not exist; existing heaters: "
        f"{', '.join(h.id for h in config.heaters) or 'none'}",
        field="heater_id",
    )


def _route_field(field: str) -> tuple[str, bool]:
    """Decide whether a field belongs to the installation or to the weather block."""
    from ...persistence.repository import (
        HEATER_FIELDS,
        INSTALLATION_FIELDS,
        WEATHER_FIELDS,
    )

    if field in INSTALLATION_FIELDS:
        return "installation", True
    if field in WEATHER_FIELDS:
        return "weather", True
    if field in HEATER_FIELDS:
        raise not_found(
            f"{field!r} is a heater field; use PATCH /config/heaters/{{id}}",
            field=field,
        )
    raise not_found(
        f"unknown field {field!r}. Installation fields: "
        f"{', '.join(sorted(INSTALLATION_FIELDS))}. Weather fields: "
        f"{', '.join(sorted(WEATHER_FIELDS))}. Heater fields (via "
        f"PATCH /config/heaters/{{id}}): {', '.join(sorted(HEATER_FIELDS))}",
        field=field,
    )


@router.patch(
    "/config",
    response_model=ChangeResponse,
    responses=ERROR_RESPONSES,
    summary="Change one installation or weather field",
    description=(
        "`revision` is mandatory: it is the optimistic lock. Send the revision you "
        "read, and if somebody else wrote first you get 409 instead of silently "
        "overwriting them.\n\n"
        "The whole resulting configuration is validated before anything is "
        "applied. A change that would leave the installation invalid changes "
        "nothing at all."
    ),
)
def patch_config(
    payload: SetFieldRequest, store: Store = Depends(usable_store)
) -> ChangeResponse:
    entity, _ = _route_field(payload.field)
    change = store.repository.set_field(
        payload.revision, entity, None, payload.field, payload.value
    )
    store.context.refresh_fallback()
    return _change_view(change)


@router.patch(
    "/config/heaters/{heater_id}",
    response_model=ChangeResponse,
    responses=ERROR_RESPONSES,
    summary="Change one field of a storage heater",
)
def patch_heater(
    heater_id: str, payload: SetFieldRequest, store: Store = Depends(usable_store)
) -> ChangeResponse:
    from ...persistence.repository import HEATER_FIELDS

    if payload.field not in HEATER_FIELDS:
        raise not_found(
            f"unknown heater field {payload.field!r}; admissible fields: "
            f"{', '.join(sorted(HEATER_FIELDS))}",
            field=payload.field,
        )
    try:
        change = store.repository.set_field(
            payload.revision, "heater", heater_id, payload.field, payload.value
        )
    except ConfigValidationError as exc:
        if "does not exist" in str(exc):
            raise not_found(str(exc), field="heater_id") from exc
        raise
    store.context.refresh_fallback()
    return _change_view(change)


@router.post(
    "/config/heaters",
    response_model=ChangeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
    summary="Add a storage heater",
)
def post_heater(
    payload: AddHeaterRequest, store: Store = Depends(usable_store)
) -> ChangeResponse:
    thermal = None
    if (
        payload.target_temperature_c is not None
        or payload.design_outdoor_temperature_c is not None
    ):
        if (
            payload.target_temperature_c is None
            or payload.design_outdoor_temperature_c is None
        ):
            raise ConfigValidationError(
                "a thermal profile needs both target_temperature_c and "
                "design_outdoor_temperature_c",
                field="target_temperature_c",
                heater_id=payload.id,
            )
        thermal = ThermalProfile(
            target_temperature_c=payload.target_temperature_c,
            design_outdoor_temperature_c=payload.design_outdoor_temperature_c,
            thermal_factor=payload.thermal_factor,
            min_charge=payload.min_charge,
            max_charge=payload.max_charge,
        )
    heater = Heater(
        id=payload.id,
        name=payload.name or payload.id,
        model=payload.model,
        power_w=round(payload.power_kw * 1000),
        full_charge_minutes=round(payload.full_charge_hours * 60),
        target_charge=payload.target_charge,
        priority=payload.priority,
        enabled=payload.enabled,
        indoor_topic=payload.indoor_topic,
        thermal=thermal,
        output=OutputConfig(
            kind=payload.output, pin=payload.pin, active_high=payload.active_high
        ),
    )
    try:
        change = store.repository.add_heater(payload.revision, heater)
    except ConfigValidationError as exc:
        if "already exists" in str(exc):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_ALREADY_EXISTS,
                str(exc),
                field="heater_id",
                heater_id=payload.id,
            ) from exc
        raise
    store.context.refresh_fallback()
    return _change_view(change)


@router.delete(
    "/config/heaters/{heater_id}",
    response_model=ChangeResponse,
    responses=ERROR_RESPONSES,
    summary="Remove a storage heater, keeping its history",
    description=(
        "Removes the heater with its output and thermal profile. Its history is "
        "kept: a plan from six months ago stays readable."
    ),
)
def delete_heater(
    heater_id: str,
    revision: int = Query(description="The configuration revision you read"),
    store: Store = Depends(usable_store),
) -> ChangeResponse:
    try:
        change = store.repository.remove_heater(revision, heater_id)
    except ConfigValidationError as exc:
        if "does not exist" in str(exc):
            raise not_found(str(exc), field="heater_id") from exc
        raise
    store.context.refresh_fallback()
    return _change_view(change)


__all__ = ["router"]
