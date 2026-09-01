"""Reading and editing configuration.

Every write goes through the existing ``ConfigRepository``: the validation, the
atomicity and the optimistic lock are the ones already in place, not a second
implementation. Relaxing any of them here would mean the API could store what the
the configuration repository refuses (FR-025).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ...models import Heater, OutputConfig
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
    ChangesResponse,
    ConfigResponse,
    HeaterResponse,
    OutputView,
    PatchInstallationRequest,
    ScheduleView,
    SetFieldRequest,
    UpdateHeaterRequest,
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
        temperature_topic=heater.temperature_topic,
        target_temperature_topic=heater.target_temperature_topic,
        stored_charge_topic=heater.stored_charge_topic,
        reserve_percent=heater.reserve_percent,
        demand_factor=heater.demand_factor,
        output=OutputView(
            kind=heater.output.kind,
            pin=heater.output.pin,
            active_high=heater.output.active_high,
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
        poll_seconds=config.runtime.poll_seconds,
        retention_days=config.retention_days,
        schedule=schedule,
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
        "schema revision. Weather settings and its managed secret are available "
        "only through the system configuration API."
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
    """Decide whether a field belongs to the installation."""
    from ...persistence.repository import (
        HEATER_FIELDS,
        INSTALLATION_FIELDS,
    )

    if field in INSTALLATION_FIELDS:
        return "installation", True
    if field in HEATER_FIELDS:
        raise not_found(
            f"{field!r} is a heater field; use PATCH /config/heaters/{{id}}",
            field=field,
        )
    raise not_found(
        f"unknown field {field!r}. Installation fields: "
        f"{', '.join(sorted(INSTALLATION_FIELDS))}. Heater fields (via "
        f"PATCH /config/heaters/{{id}}): {', '.join(sorted(HEATER_FIELDS))}",
        field=field,
    )


@router.patch(
    "/config",
    response_model=ChangeResponse,
    responses=ERROR_RESPONSES,
    summary="Change one installation field",
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
    "/config/batch",
    response_model=ChangesResponse,
    responses=ERROR_RESPONSES,
    summary="Change several installation fields at once",
    description=(
        "`revision` is mandatory: it is the optimistic lock. Send the revision you "
        "read, and if somebody else wrote first you get 409 instead of silently "
        "overwriting them.\n\n"
        "The whole resulting configuration is validated before anything is "
        "applied. A change that would leave the installation invalid changes "
        "nothing at all."
    ),
)
def patch_config_batch(
    payload: PatchInstallationRequest, store: Store = Depends(usable_store)
) -> ChangesResponse:
    for field in payload.values:
        _route_field(field)
    changes = store.repository.set_fields(payload.revision, payload.values)
    store.context.refresh_fallback()
    return ChangesResponse(changes=[_change_view(change) for change in changes])


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


@router.put(
    "/config/heaters/{heater_id}",
    response_model=ChangeResponse,
    responses=ERROR_RESPONSES,
    summary="Replace all editable fields of a storage heater",
)
def update_heater(
    heater_id: str,
    payload: UpdateHeaterRequest,
    store: Store = Depends(usable_store),
) -> ChangeResponse:
    config, _revision = store.repository.current()
    current = next((heater for heater in config.heaters if heater.id == heater_id), None)
    if current is None:
        raise not_found(f"heater {heater_id!r} does not exist", field="heater_id")

    thermal = current.thermal

    try:
        heater = Heater(
            id=heater_id,
            name=payload.name,
            model=payload.model,
            power_w=round(payload.power_kw * 1000),
            full_charge_minutes=round(payload.full_charge_hours * 60),
            target_charge=payload.target_charge,
            priority=payload.priority,
            enabled=payload.enabled,
            indoor_topic=payload.indoor_topic,
            temperature_topic=payload.temperature_topic,
            target_temperature_topic=payload.target_temperature_topic,
            stored_charge_topic=payload.stored_charge_topic,
            reserve_percent=payload.reserve_percent,
            demand_factor=payload.demand_factor,
            output=OutputConfig(
                kind=payload.output, pin=payload.pin, active_high=payload.active_high
            ),
            thermal=thermal,
        )
        change = store.repository.update_heater(payload.revision, heater)
    except ConfigValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(str(exc), field="heater_id", heater_id=heater_id) from exc
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
        temperature_topic=payload.temperature_topic,
        target_temperature_topic=payload.target_temperature_topic,
        stored_charge_topic=payload.stored_charge_topic,
        reserve_percent=payload.reserve_percent,
        demand_factor=payload.demand_factor,
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
