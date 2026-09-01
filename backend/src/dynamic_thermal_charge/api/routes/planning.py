"""Read-only planning projection for the operator panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ...charge_planning import DeterministicChargeOptimizer, PlanningInput
from ...models import ChargeConstraint, ChargeTelemetry
from ...persistence import ConfigValidationError
from ..dependencies import usable_store
from ..schemas import (
    ERROR_RESPONSES,
    AllocationSummary,
    HourlyForecastPointView,
    PlanningForecastView,
    PlanningHeaterView,
    PlanningPlanView,
    PlanningResponse,
    PlanningSlotView,
    PlanningTimelineSlotView,
    READ_RESPONSES,
    ChargeConstraintRequest,
    ChargeConstraintView,
    ChargeTelemetryView,
    PlanningActivateRequest,
    PlanningDeficitView,
    PlanningPreviewRequest,
    PlanningPreviewResponse,
    HeaterChargeConfigRequest,
)


router = APIRouter()


@router.get(
    "/planning",
    response_model=PlanningResponse,
    responses=READ_RESPONSES,
    summary="Current or next accepted charge plan",
)
def get_planning(
    request: Request,
    store: Store = Depends(usable_store),
) -> PlanningResponse:
    observed_at = request.app.state.clock()
    config, _revision = store.repository.current()
    reader = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    snapshot = reader.planning(observed_at)
    latest_forecast = reader.latest_forecast()
    cycle_status = store.planning.forecast_cycle_status() or {}
    heaters = [
        PlanningHeaterView(
            id=heater.id,
            name=heater.name,
            power_w=heater.power_w,
            priority=heater.priority,
            enabled=heater.enabled,
        )
        for heater in config.heaters
    ]
    if snapshot is None:
        automatic = store.planning.active_plan()
        if automatic is not None:
            automatic_plan = PlanningPlanView(
                window_start=automatic["horizon_start"],
                window_end=automatic["horizon_end"],
                slot_minutes=automatic["slot_minutes"],
                installation_revision=_revision,
                created_at=automatic["created_at"],
                slots=[PlanningSlotView(start=item["start"], end=item["end"], heater_ids=item["heater_ids"], total_power_w=item["power_w"], temperature_c=item["outdoor_temperature_c"], temperature_interpolated=False) for item in automatic["slots"]],
            )
            response = PlanningResponse(
                observed_at=observed_at,
                max_total_power_w=config.site.max_total_power_w,
                heaters=heaters,
                forecast=_forecast_view(latest_forecast),
                forecast_status=cycle_status.get("forecast_status"),
                forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
                forecast_last_error=cycle_status.get("forecast_last_error"),
                forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
                plan=automatic_plan,
                horizon_start=automatic["horizon_start"],
                horizon_end=automatic["horizon_end"],
                timeline=[PlanningTimelineSlotView(start=item["start"], end=item["end"], heater_ids=item["heater_ids"], total_power_w=item["power_w"], temperature_c=item["outdoor_temperature_c"], temperature_interpolated=False, charge_minutes_by_heater={key: config.site.slot_minutes if key in item["heater_ids"] else 0 for key in (heater.id for heater in config.heaters)}) for item in automatic["slots"]],
            )
            return _enrich(response, store, observed_at)
        response = PlanningResponse(
            observed_at=observed_at,
            max_total_power_w=config.site.max_total_power_w,
            heaters=heaters,
            absence_reason="no_current_or_next_plan",
            forecast=_forecast_view(latest_forecast),
            forecast_status=cycle_status.get("forecast_status"),
            forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
            forecast_last_error=cycle_status.get("forecast_last_error"),
            forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
        )
        return _enrich(response, store, observed_at)

    # The visible forecast must reflect the newest stored retrieval, even when
    # the accepted plan was calculated with an older forecast.
    forecast = latest_forecast or snapshot["forecast"]
    forecast_view = _forecast_view(forecast)

    power_by_id = {heater.id: heater.power_w for heater in config.heaters}
    assigned: dict[tuple[datetime, datetime], list[str]] = {}
    stored_temperatures: dict[tuple[datetime, datetime], tuple[float | None, bool]] = {}
    for slot in snapshot["slots"]:
        key = (slot["slot_start"], slot["slot_end"])
        assigned.setdefault(key, []).append(slot["heater_id"])
        stored_temperatures[key] = (
            slot["temperature_c"], slot["temperature_interpolated"]
        )

    plan_data = snapshot["plan"]
    slot_delta = timedelta(minutes=plan_data["slot_minutes"])
    slots: list[PlanningSlotView] = []
    cursor = plan_data["window_start"]
    while cursor < plan_data["window_end"]:
        end = min(cursor + slot_delta, plan_data["window_end"])
        key = (cursor, end)
        heater_ids = sorted(assigned.get(key, []))
        temperature, interpolated = stored_temperatures.get(
            key, _temperature_for_interval(forecast, cursor, end)
        )
        slots.append(
            PlanningSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
            )
        )
        cursor = end

    horizon_start = plan_data["window_start"]
    horizon_end = horizon_start + timedelta(hours=48)
    timeline = _build_timeline(
        config.heaters,
        power_by_id,
        assigned,
        stored_temperatures,
        forecast,
        horizon_start,
        horizon_end,
        slot_delta,
    )

    response = PlanningResponse(
        observed_at=observed_at,
        max_total_power_w=config.site.max_total_power_w,
        plan=PlanningPlanView(**plan_data, slots=slots),
        forecast=forecast_view,
        allocations=[AllocationSummary(**item) for item in snapshot["allocations"]],
        heaters=heaters,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        timeline=timeline,
        forecast_status=cycle_status.get("forecast_status"),
        forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
        forecast_last_error=cycle_status.get("forecast_last_error"),
        forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
    )
    return _enrich(response, store, observed_at)


@router.post("/planning/preview", response_model=PlanningPreviewResponse, responses=ERROR_RESPONSES)
def preview_planning(
    request: PlanningPreviewRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningPreviewResponse:
    site = store.planning.site()
    if request.expected_revision is not None and request.expected_revision != site["revision"]:
        raise ConfigValidationError("planning configuration changed; recalculate before saving")
    constraints = _parse_constraints(request.constraints)
    plan = _build_automatic_plan(store, app_request.app.state.clock(), constraints, site)
    return _preview_response(plan, constraints)


@router.post("/planning/activate", response_model=PlanningPreviewResponse, responses=ERROR_RESPONSES)
def activate_planning(
    request: PlanningActivateRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningPreviewResponse:
    site = store.planning.site()
    if request.expected_revision != site["revision"]:
        raise ConfigValidationError("constraints changed; recalculate before saving")
    constraints = _parse_constraints(request.constraints)
    plan = _build_automatic_plan(store, app_request.app.state.clock(), constraints, site)
    if plan.input_token != request.token:
        raise ConfigValidationError("the preview inputs changed; recalculate before activating")
    blocking = [item for item in plan.deficits if item.reason == "power_limit_or_capacity" and item.deficit_percent > 0]
    if blocking:
        raise ConfigValidationError("the constraints cannot be satisfied within the configured power/capacity; resolve the conflict before activating", field="constraints")
    new_revision = store.planning.replace_constraints(constraints, request.expected_revision)
    store.planning.save_plan(plan, configuration_revision=store.repository.current()[1], constraints_revision=new_revision, reason="activated", active=True)
    return _preview_response(plan, constraints)


@router.patch("/planning/heaters/{heater_id}", response_model=PlanningResponse, responses=ERROR_RESPONSES)
def update_heater_planning(
    heater_id: str,
    payload: HeaterChargeConfigRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningResponse:
    config, _revision = store.repository.current()
    if heater_id not in {heater.id for heater in config.heaters}:
        raise ConfigValidationError("heater does not exist", field="heater_id", heater_id=heater_id)
    store.planning.update_heater_charge_config(heater_id, payload.model_dump())
    # Re-read through the public projection so the response cannot contain a
    # partially applied topic configuration.
    return get_planning(app_request, store)


def _enrich(response: PlanningResponse, store: Store, observed_at: datetime) -> PlanningResponse:
    planning = store.planning
    telemetry = planning.telemetry()
    views = []
    for heater in response.heaters:
        value = telemetry.get(heater.id)
        if value is None:
            views.append(ChargeTelemetryView(heater_id=heater.id, missing_fields=["temperature_c", "target_temperature_c", "stored_charge_percent"]))
            continue
        ages = [
            (observed_at - stamp).total_seconds()
            for stamp in (value.temperature_received_at, value.target_received_at, value.stored_charge_received_at)
            if stamp is not None
        ]
        missing = [field for field, item in (("temperature_c", value.temperature_c), ("target_temperature_c", value.target_temperature_c), ("stored_charge_percent", value.stored_charge_percent)) if item is None]
        oldest = max(ages, default=None)
        stale = bool(missing or oldest is None or oldest > 900)
        views.append(ChargeTelemetryView(
            heater_id=heater.id,
            temperature_c=value.temperature_c,
            target_temperature_c=value.target_temperature_c,
            stored_charge_percent=value.stored_charge_percent,
            temperature_received_at=value.temperature_received_at,
            target_received_at=value.target_received_at,
            stored_charge_received_at=value.stored_charge_received_at,
            state="telemetry_stale" if stale else "ready",
            missing_fields=missing,
            oldest_age_seconds=oldest,
        ))
    constraints = [ChargeConstraintView(id=item.id, heater_id=item.heater_id, target_charge=item.target_charge, at_time=item.at.strftime("%H:%M"), weekdays=list(item.weekdays)) for item in planning.constraints()]
    active = planning.active_plan()
    response.constraints = constraints
    response.telemetry = views
    response.plan_status = None if active is None else active["status"]
    response.deficits = [] if active is None else [PlanningDeficitView(**item) for item in active["deficits"]]
    response.preview_token = None if active is None else active["input_token"]
    response.constraints_revision = planning.site()["revision"]
    return response


def _parse_constraints(items: list[ChargeConstraintRequest]) -> tuple[ChargeConstraint, ...]:
    result = []
    from ...persistence.mapping import parse_time
    for item in items:
        try:
            parsed_time = parse_time(item.at_time, "at_time")
            weekdays = tuple(item.weekdays)
            result.append(ChargeConstraint(heater_id=item.heater_id, target_charge=item.target_charge, at=parsed_time, weekdays=weekdays))
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError(str(exc), field="constraints", heater_id=item.heater_id) from exc
    return tuple(result)


def _build_automatic_plan(store: Store, observed_at: datetime, constraints: tuple[ChargeConstraint, ...], site: dict[str, int]):
    config, _revision = store.repository.current()
    known_heaters = {heater.id for heater in config.heaters}
    for constraint in constraints:
        if constraint.heater_id not in known_heaters:
            raise ConfigValidationError("heater does not exist", field="heater_id", heater_id=constraint.heater_id)
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    request = PlanningInput(
        heaters=config.heaters,
        telemetry=store.planning.telemetry(),
        constraints=constraints,
        forecast=store.planning.latest_forecast(),
        horizon_start=observed_at,
        horizon_hours=site["forecast_horizon_hours"],
        slot_minutes=config.site.slot_minutes,
        max_total_power_w=config.site.max_total_power_w,
        timezone_name=timezone_name,
    )
    return DeterministicChargeOptimizer().build(request)


def _preview_response(plan, constraints) -> PlanningPreviewResponse:
    return PlanningPreviewResponse(
        token=plan.input_token, status=plan.status, score=list(plan.score),
        horizon_start=plan.horizon_start, horizon_end=plan.horizon_end,
        slot_minutes=plan.slot_minutes,
        slots=[{"start": item.start, "end": item.end, "heater_ids": list(item.heater_ids), "power_w": item.power_w, "stored_charge_percent": item.stored_charge_percent, "required_charge_percent": item.required_charge_percent, "outdoor_temperature_c": item.outdoor_temperature_c} for item in plan.slots],
        deficits=[PlanningDeficitView(**item.__dict__) for item in plan.deficits],
        constraints=[ChargeConstraintView(id=item.id, heater_id=item.heater_id, target_charge=item.target_charge, at_time=item.at.strftime("%H:%M"), weekdays=list(item.weekdays)) for item in constraints],
    )


def _build_timeline(
    heaters,
    power_by_id: dict[str, int],
    assigned: dict[tuple[datetime, datetime], list[str]],
    stored_temperatures: dict[tuple[datetime, datetime], tuple[float | None, bool]],
    forecast,
    horizon_start: datetime,
    horizon_end: datetime,
    slot_delta: timedelta,
) -> list[PlanningTimelineSlotView]:
    """Project the accepted plan and thermal reserve across exactly 48 hours.

    The reserve is represented as equivalent minutes of full charge. It starts
    at zero at the horizon boundary, gains charge while a stored plan assigns a
    heater, and loses reserve outside charge windows according to its configured
    thermal loss and the forecast delta from the target temperature.
    """
    heater_by_id = {heater.id: heater for heater in heaters}
    reserve_minutes = {heater.id: 0.0 for heater in heaters}
    timeline: list[PlanningTimelineSlotView] = []
    cursor = horizon_start
    while cursor < horizon_end:
        end = min(cursor + slot_delta, horizon_end)
        key = (cursor, end)
        heater_ids = sorted(assigned.get(key, []))
        temperature, interpolated = stored_temperatures.get(
            key, _temperature_for_interval(forecast, cursor, end)
        )
        duration_hours = (end - cursor).total_seconds() / 3600
        for heater in heaters:
            profile = heater.thermal
            if profile is not None and temperature is not None:
                delta_c = max(profile.target_temperature_c - temperature, 0.0)
                design_delta_c = max(
                    profile.target_temperature_c - profile.design_outdoor_temperature_c,
                    0.0001,
                )
                loss_fraction = (
                    profile.thermal_loss_c_per_hour
                    * duration_hours
                    * delta_c
                    / design_delta_c
                )
                reserve_minutes[heater.id] *= max(0.0, 1.0 - loss_fraction)
            if heater.id in heater_ids:
                reserve_minutes[heater.id] += (end - cursor).total_seconds() / 60
            reserve_minutes[heater.id] = max(0.0, reserve_minutes[heater.id])

        timeline.append(
            PlanningTimelineSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
                charge_minutes_by_heater={
                    heater_id: round(reserve_minutes[heater_id], 2)
                    for heater_id in heater_by_id
                },
            )
        )
        cursor = end
    return timeline


def _temperature_for_interval(forecast, start: datetime, end: datetime) -> tuple[float | None, bool]:
    if forecast is None:
        return None, False
    points = [
        point for point in forecast["hourly_points"]
        if start <= point["timestamp"] < end
    ]
    if points:
        return sum(point["temperature_c"] for point in points) / len(points), any(
            point["interpolated"] for point in points
        )
    return forecast["average_temperature_c"], True


def _forecast_view(forecast) -> PlanningForecastView | None:
    if forecast is None:
        return None
    return PlanningForecastView(
        **{key: value for key, value in forecast.items() if key != "hourly_points"},
        hourly_points=[HourlyForecastPointView(**point) for point in forecast["hourly_points"]],
    )


__all__ = ["router"]
