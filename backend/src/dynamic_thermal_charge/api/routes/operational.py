"""Generic local operational contract for dashboards and automations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ...persistence.home_assistant import ControlCommandResult
from ..dependencies import controller_view, usable_store
from ..liveness import ControllerView
from ..schemas import ERROR_RESPONSES, READ_RESPONSES


router = APIRouter()


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class AutomaticControlRequest(RevisionRequest):
    enabled: bool


class HeaterModeRequest(RevisionRequest):
    mode: Literal["AUTO", "OFF"]


class TemperatureTargetRequest(RevisionRequest):
    target_temperature_c: float = Field(ge=-50, le=80)


class OperationalHeater(BaseModel):
    id: str
    name: str
    mode: Literal["AUTO", "OFF"]
    configured_enabled: bool
    indoor_temperature_c: float | None = None
    indoor_observed_at: datetime | None = None
    soc_percent: float | None = None
    soc_observed_at: datetime | None = None
    confirmed_load: bool | None = None
    instant_power_w: int | None = None
    damper_position_percent: float | None = None
    damper_observed_at: datetime | None = None
    target_temperature_c: float | None = None
    next_charge_at: datetime | None = None
    next_soc_target_percent: float | None = None


class OperationalPower(BaseModel):
    instant_w: int | None = None
    confirmed_load_w: int | None = None
    limit_w: int


class PlanInterval(BaseModel):
    accumulator_id: str
    start: datetime
    end: datetime
    initial_soc_percent: float | None = None
    target_soc_percent: float | None = None
    planned_energy_kwh: float | None = None
    power_w: int | None = None


class OperationalPlan(BaseModel):
    status: str | None = None
    observed_at: datetime
    intervals: list[PlanInterval] = Field(default_factory=list)


class OperationalInstallation(BaseModel):
    id: str
    name: str
    timezone: str | None = None
    revision: int


class OperationalSnapshot(BaseModel):
    observed_at: datetime
    revision: int
    health: Literal["running", "idle", "degraded", "error"]
    controller_current: bool
    automatic_control_enabled: bool
    recalculation_pending: bool
    recalculation_requested_generation: int
    installation: OperationalInstallation
    power: OperationalPower
    accumulators: list[OperationalHeater]
    plan: OperationalPlan | None = None


class ForecastPoint(BaseModel):
    timestamp: datetime
    temperature_c: float
    interpolated: bool = False


class ForecastResponse(BaseModel):
    observed_at: datetime
    retrieved_at: datetime | None = None
    source: str | None = None
    forecast_date: str | None = None
    points: list[ForecastPoint] = Field(default_factory=list)


class CommandResponse(BaseModel):
    accepted: bool
    changed: bool
    revision: int
    automatic_control_enabled: bool
    recalculation_requested_generation: int
    recalculation_processed_generation: int
    recalculation_pending: bool
    heater_modes: dict[str, Literal["AUTO", "OFF"]]


def _command_response(result: ControlCommandResult) -> CommandResponse:
    state = result.state
    return CommandResponse(
        accepted=True,
        changed=result.changed,
        revision=state.revision,
        automatic_control_enabled=state.automatic_control_enabled,
        recalculation_requested_generation=state.recalculation_requested_generation,
        recalculation_processed_generation=state.recalculation_processed_generation,
        recalculation_pending=state.recalculation_pending,
        heater_modes=state.heater_modes,
    )


@router.get("/operational", response_model=OperationalSnapshot, responses=READ_RESPONSES)
@router.get(
    "/operational/snapshot",
    response_model=OperationalSnapshot,
    responses=READ_RESPONSES,
)
@router.get(
    "/integration/snapshot",
    response_model=OperationalSnapshot,
    responses=READ_RESPONSES,
    include_in_schema=False,
)
def get_operational_snapshot(
    request: Request,
    store: Store = Depends(usable_store),
    controller: ControllerView = Depends(controller_view),
) -> OperationalSnapshot:
    observed_at = request.app.state.clock()
    config, _configuration_revision = store.repository.current()
    control = store.home_assistant.control_state()
    planning_site = store.planning.site()
    telemetry = store.planning.telemetry()
    reader = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    last_states = reader.last_output_states()
    current = controller.state_is_current
    plan = _operational_plan(store, observed_at)
    active_targets = _active_targets(config, store.planning.temperature_targets(enabled_only=True), observed_at)
    future_by_heater: dict[str, list[PlanInterval]] = {}
    if plan is not None:
        for interval in plan.intervals:
            future_by_heater.setdefault(interval.accumulator_id, []).append(interval)

    power_w: int | None = None
    limit_w = int(planning_site.get("contracted_power_w", config.site.max_total_power_w))
    if current:
        power_w = sum(
            heater.power_w
            for heater in config.heaters
            if last_states.get(heater.id, (False, None))[0]
        )
    accumulators: list[OperationalHeater] = []
    for heater in config.heaters:
        value = telemetry.get(heater.id)
        known_state, _changed_at = last_states.get(heater.id, (False, None))
        intervals = [
            item
            for item in future_by_heater.get(heater.id, ())
            if item.end > observed_at
        ]
        next_interval = next((item for item in intervals if item.start >= observed_at), None)
        accumulators.append(
            OperationalHeater(
                id=heater.id,
                name=heater.name,
                mode=control.heater_modes.get(heater.id, "AUTO"),
                configured_enabled=heater.enabled,
                indoor_temperature_c=None if value is None else value.indoor_temperature_c,
                indoor_observed_at=None if value is None else value.indoor_received_at,
                soc_percent=None if value is None else value.stored_soc_percent,
                soc_observed_at=None if value is None else value.stored_soc_received_at,
                confirmed_load=known_state if current else None,
                instant_power_w=(heater.power_w if current and known_state else 0) if current else None,
                damper_position_percent=None if value is None else value.damper_position_percent,
                damper_observed_at=None if value is None else value.damper_received_at,
                target_temperature_c=active_targets.get(heater.id),
                next_charge_at=None if next_interval is None else next_interval.start,
                next_soc_target_percent=None if next_interval is None else next_interval.target_soc_percent,
            )
        )

    if not controller.state_is_current:
        health = "error"
    elif controller.liveness.value == "live_degraded":
        health = "degraded"
    elif power_w:
        health = "running"
    else:
        health = "idle"
    return OperationalSnapshot(
        observed_at=observed_at,
        revision=control.revision,
        health=health,
        controller_current=current,
        automatic_control_enabled=control.automatic_control_enabled,
        recalculation_pending=control.recalculation_pending,
        recalculation_requested_generation=control.recalculation_requested_generation,
        installation=OperationalInstallation(
            id=control.installation_uuid,
            name=store.repository.installation_name(),
            timezone=None if config.schedule is None else config.schedule.timezone,
            revision=control.revision,
        ),
        power=OperationalPower(instant_w=power_w, confirmed_load_w=power_w, limit_w=limit_w),
        accumulators=accumulators,
        plan=plan,
    )


@router.get("/operational/plan", response_model=OperationalPlan | None, responses=READ_RESPONSES)
def get_operational_plan(
    request: Request,
    store: Store = Depends(usable_store),
) -> OperationalPlan | None:
    return _operational_plan(store, request.app.state.clock())


@router.get("/operational/forecast", response_model=ForecastResponse, responses=READ_RESPONSES)
def get_operational_forecast(
    request: Request,
    store: Store = Depends(usable_store),
) -> ForecastResponse:
    observed_at = request.app.state.clock()
    snapshot = store.planning.latest_forecast_snapshot()
    if snapshot is None:
        return ForecastResponse(observed_at=observed_at)
    return ForecastResponse(observed_at=observed_at, **snapshot)


@router.post(
    "/operational/control/automatic",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
)
@router.post(
    "/operational/automatic-control",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
    include_in_schema=False,
)
def set_automatic_control(
    payload: AutomaticControlRequest,
    store: Store = Depends(usable_store),
) -> CommandResponse:
    return _command_response(
        store.home_assistant.set_automatic_control(
            payload.enabled, expected_revision=payload.expected_revision
        )
    )


@router.post("/operational/recalculate", response_model=CommandResponse, responses=ERROR_RESPONSES)
@router.post(
    "/operational/plan/recalculate",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
    include_in_schema=False,
)
def request_recalculation(
    payload: RevisionRequest,
    store: Store = Depends(usable_store),
) -> CommandResponse:
    return _command_response(
        store.home_assistant.request_recalculation(
            expected_revision=payload.expected_revision
        )
    )


@router.post(
    "/operational/accumulators/{heater_id}/mode",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
)
@router.post(
    "/operational/heaters/{heater_id}/mode",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
    include_in_schema=False,
)
def set_heater_mode(
    heater_id: str,
    payload: HeaterModeRequest,
    store: Store = Depends(usable_store),
) -> CommandResponse:
    return _command_response(
        store.home_assistant.set_heater_mode(
            heater_id, payload.mode, expected_revision=payload.expected_revision
        )
    )


@router.post(
    "/operational/accumulators/{heater_id}/target",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
)
@router.post(
    "/operational/heaters/{heater_id}/target",
    response_model=CommandResponse,
    responses=ERROR_RESPONSES,
    include_in_schema=False,
)
def set_active_temperature_target(
    heater_id: str,
    payload: TemperatureTargetRequest,
    request: Request,
    store: Store = Depends(usable_store),
) -> CommandResponse:
    return _command_response(
        store.home_assistant.set_active_temperature_target(
            heater_id,
            payload.target_temperature_c,
            at=request.app.state.clock(),
            expected_revision=payload.expected_revision,
        )
    )


def _operational_plan(store: Store, observed_at: datetime) -> OperationalPlan | None:
    automatic = store.planning.active_plan()
    if automatic is None:
        return None
    intervals: list[PlanInterval] = []
    for slot in automatic.get("slots", ()):
        initial = slot.get("initial_soc_percent", {})
        target = slot.get("required_charge_percent", {})
        energy = slot.get("charge_energy_kwh", {})
        for heater_id in slot.get("heater_ids", ()):
            initial_soc = _number(initial.get(heater_id))
            target_soc = _number(target.get(heater_id))
            if target_soc is None:
                target_soc = initial_soc
            intervals.append(
                PlanInterval(
                    accumulator_id=str(heater_id),
                    start=slot["start"],
                    end=slot["end"],
                    initial_soc_percent=initial_soc,
                    target_soc_percent=target_soc,
                    planned_energy_kwh=_number(energy.get(heater_id)),
                    power_w=int(slot.get("heater_power_w", {}).get(heater_id, slot.get("power_w", 0))) or None,
                )
            )
    if not intervals:
        return OperationalPlan(status=automatic.get("status"), observed_at=observed_at)
    return OperationalPlan(
        status=automatic.get("status"),
        observed_at=observed_at,
        intervals=sorted(intervals, key=lambda item: (item.start, item.accumulator_id)),
    )


def _active_targets(config, targets_by_heater, at: datetime) -> dict[str, float]:
    timezone_name = "UTC" if config.schedule is None else config.schedule.timezone
    zone = ZoneInfo(timezone_name)
    local = at.astimezone(zone) if at.tzinfo is not None else at.replace(tzinfo=zone)
    result: dict[str, float] = {}
    for heater_id, targets in targets_by_heater.items():
        active = [target for target in targets if _model_target_is_active(target, local)]
        if len(active) == 1:
            result[heater_id] = active[0].target_temperature_c
    return result


def _model_target_is_active(target, local: datetime) -> bool:
    start = target.start_time.hour * 60 + target.start_time.minute
    end = target.end_time.hour * 60 + target.end_time.minute
    if target.start_time == target.end_time:
        return local.weekday() in target.weekdays
    if start == 0 and end == 0:
        return local.weekday() in target.weekdays
    now = local.hour * 60 + local.minute
    if end > start:
        return local.weekday() in target.weekdays and start <= now < end
    if local.weekday() in target.weekdays and now >= start:
        return True
    return (local.weekday() - 1) % 7 in target.weekdays and now < end


def _number(value):
    return None if value is None else float(value)


__all__ = ["router"]
