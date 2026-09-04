"""Read-only planning projection for the operator panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ...charge_planning import DeterministicChargeOptimizer, PlanningInput, resolve_planning_telemetry
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
    PlanningSiteConfigRequest,
    PlanningSiteConfigResponse,
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
    latest_forecast = reader.latest_forecast(observed_at)
    cycle_status = store.planning.forecast_cycle_status() or {}
    planning_site = store.planning.site()
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
    automatic = store.planning.active_plan()
    if automatic is not None:
        response = _automatic_planning_response(
            automatic,
            observed_at=observed_at,
            config=config,
            revision=_revision,
            heaters=heaters,
            latest_forecast=latest_forecast,
            cycle_status=cycle_status,
            horizon_hours=int(planning_site["forecast_horizon_hours"]),
        )
        return _enrich(response, store, observed_at)

    snapshot = reader.planning(observed_at)
    if snapshot is None:
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
    horizon_end = horizon_start + timedelta(hours=int(planning_site["forecast_horizon_hours"]))
    timeline = _build_timeline(
        config.heaters,
        power_by_id,
        _ordered_plan_slots(slots),
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
    if plan.status == "INVALID":
        raise ConfigValidationError("the plan is invalid and cannot be activated", field="planning")
    new_revision = store.planning.replace_constraints(constraints, request.expected_revision)
    store.planning.save_plan(plan, configuration_revision=store.repository.current()[1], constraints_revision=new_revision, reason="activated", active=True)
    return _preview_response(plan, constraints)


@router.get(
    "/planning/config",
    response_model=PlanningSiteConfigResponse,
    responses=READ_RESPONSES,
    summary="Automatic planning site parameters",
)
def get_planning_config(
    store: Store = Depends(usable_store),
) -> PlanningSiteConfigResponse:
    return PlanningSiteConfigResponse.model_validate(store.planning.site())


@router.patch("/planning/config", response_model=PlanningSiteConfigResponse, responses=ERROR_RESPONSES)
def update_planning_config(
    payload: PlanningSiteConfigRequest,
    store: Store = Depends(usable_store),
) -> PlanningSiteConfigResponse:
    values = payload.model_dump(exclude={"expected_revision"})
    store.planning.update_site(values, payload.expected_revision)
    return PlanningSiteConfigResponse.model_validate(store.planning.site())


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


def _automatic_planning_response(
    automatic: dict,
    *,
    observed_at: datetime,
    config,
    revision: int,
    heaters: list[PlanningHeaterView],
    latest_forecast,
    cycle_status: dict,
    horizon_hours: int,
) -> PlanningResponse:
    power_by_id = {heater.id: heater.power_w for heater in config.heaters}
    slot_delta = timedelta(minutes=automatic["slot_minutes"])
    horizon_start = automatic["horizon_start"]
    horizon_end = horizon_start + timedelta(hours=horizon_hours)
    automatic_plan = PlanningPlanView(
        window_start=automatic["horizon_start"],
        window_end=automatic["horizon_end"],
        slot_minutes=automatic["slot_minutes"],
        installation_revision=revision,
        created_at=automatic["created_at"],
        slots=[
            PlanningSlotView(
                start=item["start"],
                end=item["end"],
                heater_ids=item["heater_ids"],
                total_power_w=item["power_w"],
                temperature_c=item["outdoor_temperature_c"],
                temperature_interpolated=False,
                stored_charge_percent_by_heater=item["stored_charge_percent"],
            )
            for item in automatic["slots"]
        ],
    )
    return PlanningResponse(
        observed_at=observed_at,
        max_total_power_w=config.site.max_total_power_w,
        heaters=heaters,
        forecast=_forecast_view(latest_forecast),
        forecast_status=cycle_status.get("forecast_status"),
        forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
        forecast_last_error=cycle_status.get("forecast_last_error"),
        forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
        plan=automatic_plan,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        timeline=_build_timeline(
            config.heaters,
            power_by_id,
            automatic["slots"],
            latest_forecast,
            horizon_start,
            horizon_end,
            slot_delta,
        ),
    )


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


def _build_automatic_plan(store: Store, observed_at: datetime, constraints: tuple[ChargeConstraint, ...], site: dict[str, int | float]):
    config, _revision = store.repository.current()
    known_heaters = {heater.id for heater in config.heaters}
    for constraint in constraints:
        if constraint.heater_id not in known_heaters:
            raise ConfigValidationError("heater does not exist", field="heater_id", heater_id=constraint.heater_id)
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    mqtt = (
        store.system_configuration.current().configuration.mqtt
        if store.system_configuration is not None
        else None
    )
    persisted = (
        {}
        if mqtt is not None and not mqtt.enabled
        else store.planning.telemetry()
    )
    request = PlanningInput(
        heaters=config.heaters,
        telemetry=resolve_planning_telemetry(
            config.heaters,
            persisted,
            observed_at,
            mqtt=mqtt,
        ),
        constraints=constraints,
        forecast=store.planning.latest_forecast(observed_at),
        horizon_start=observed_at,
        horizon_hours=int(site["forecast_horizon_hours"]),
        slot_minutes=config.site.slot_minutes,
        max_total_power_w=int(site["contracted_power_w"]),
        base_load_w=int(site.get("base_load_w", 0)),
        max_heating_power_w=int(site["max_heating_power_w"]),
        design_indoor_temperature_c=float(site["design_indoor_temperature_c"]),
        design_outdoor_temperature_c=float(site["design_outdoor_temperature_c"]),
        feedback_horizon_hours=float(site["feedback_horizon_hours"]),
        forecast_automatic_eligible=(store.planning.latest_forecast_automatic_eligible() if hasattr(store.planning, "latest_forecast_automatic_eligible") else True),
        generated_at=observed_at,
        timezone_name=timezone_name,
    )
    return DeterministicChargeOptimizer().build(request)


def _preview_response(plan, constraints) -> PlanningPreviewResponse:
    violations = [PlanningDeficitView(**item.__dict__, target_charge_percent=item.target_charge_percent, projected_charge_percent=item.projected_charge_percent, deficit_percent=item.deficit_percent) for item in plan.violations]
    return PlanningPreviewResponse(
        token=plan.input_token, status=plan.status, score=list(plan.score),
        horizon_start=plan.horizon_start, horizon_end=plan.horizon_end,
        slot_minutes=plan.slot_minutes,
        slots=[{"start": item.start, "end": item.end, "heater_ids": list(item.heater_ids), "power_w": item.power_w, "stored_charge_percent": item.stored_charge_percent, "initial_soc_percent": item.initial_soc_percent, "demand_kwh": item.demand_kwh, "heater_power_w": item.heater_power_w, "required_charge_percent": item.required_charge_percent, "outdoor_temperature_c": item.outdoor_temperature_c} for item in plan.slots],
        deficits=violations,
        violations=violations,
        explanations=[item.__dict__ for item in plan.explanations],
        demand=[item.__dict__ for item in plan.demand],
        constraints=[ChargeConstraintView(id=item.id, heater_id=item.heater_id, target_charge=item.target_charge, at_time=item.at.strftime("%H:%M"), weekdays=list(item.weekdays)) for item in constraints],
    )


def _ordered_plan_slots(slots: list[PlanningSlotView]) -> list[dict]:
    return [
        {
            "start": slot.start,
            "end": slot.end,
            "heater_ids": slot.heater_ids,
            "power_w": slot.total_power_w,
            "outdoor_temperature_c": slot.temperature_c,
            "temperature_c": slot.temperature_c,
            "temperature_interpolated": slot.temperature_interpolated,
            "stored_charge_percent": slot.stored_charge_percent_by_heater or None,
        }
        for slot in slots
    ]


def _plan_slot_maps(
    ordered_plan_slots: list[dict],
) -> tuple[
    dict[int, list[str]],
    dict[int, tuple[float | None, bool]],
    dict[int, dict[str, float]],
    dict[int, int],
]:
    """Map contiguous plan slots to timeline indices by order, not datetime keys."""
    assigned_by_index: dict[int, list[str]] = {}
    temperatures_by_index: dict[int, tuple[float | None, bool]] = {}
    soc_by_index: dict[int, dict[str, float]] = {}
    power_by_index: dict[int, int] = {}
    for index, item in enumerate(ordered_plan_slots):
        assigned_by_index[index] = list(item.get("heater_ids") or [])
        outdoor = item.get("outdoor_temperature_c", item.get("temperature_c"))
        temperatures_by_index[index] = (
            outdoor,
            bool(item.get("temperature_interpolated", False)),
        )
        projected = item.get("stored_charge_percent")
        if projected:
            soc_by_index[index] = projected
        if item.get("power_w") is not None:
            power_by_index[index] = int(item["power_w"])
    return assigned_by_index, temperatures_by_index, soc_by_index, power_by_index


def _estimate_accumulator_temperature(heater, outdoor_c: float | None, soc_percent: float) -> float | None:
    """Estimate room temperature from outdoor forecast and planned stored charge."""
    if outdoor_c is None:
        return None
    profile = heater.thermal
    target = profile.target_temperature_c if profile is not None else outdoor_c
    bounded_soc = max(0.0, min(100.0, soc_percent))
    return outdoor_c + (target - outdoor_c) * (bounded_soc / 100)


def _build_timeline(
    heaters,
    power_by_id: dict[str, int],
    ordered_plan_slots: list[dict],
    forecast,
    horizon_start: datetime,
    horizon_end: datetime,
    slot_delta: timedelta,
) -> list[PlanningTimelineSlotView]:
    """Project the accepted plan across the configured forecast horizon."""
    heater_by_id = {heater.id: heater for heater in heaters}
    charge_minutes = {heater.id: 0.0 for heater in heaters}
    stored_charge_percent = {heater.id: 0.0 for heater in heaters}
    assigned_by_index, temperatures_by_index, soc_by_index, power_by_index = _plan_slot_maps(
        ordered_plan_slots,
    )
    has_projected_soc = bool(soc_by_index)
    timeline: list[PlanningTimelineSlotView] = []
    cursor = horizon_start
    slot_index = 0
    while cursor < horizon_end:
        end = min(cursor + slot_delta, horizon_end)
        heater_ids = sorted(assigned_by_index.get(slot_index, []))
        temperature, interpolated = temperatures_by_index.get(
            slot_index, _temperature_for_interval(forecast, cursor, end)
        )
        slot_minutes = (end - cursor).total_seconds() / 60
        projected = soc_by_index.get(slot_index)
        if projected is not None:
            for heater in heaters:
                soc = projected.get(heater.id, 0.0)
                stored_charge_percent[heater.id] = soc
                charge_minutes[heater.id] = soc / 100 * heater.full_charge_minutes
        elif not has_projected_soc:
            for heater in heaters:
                if heater.id in heater_ids:
                    charge_minutes[heater.id] += slot_minutes
                stored_charge_percent[heater.id] = (
                    charge_minutes[heater.id] / heater.full_charge_minutes * 100
                    if heater.full_charge_minutes
                    else 0.0
                )

        timeline.append(
            PlanningTimelineSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=power_by_index.get(
                    slot_index,
                    sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                ),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
                charge_minutes_by_heater={
                    heater_id: round(charge_minutes[heater_id], 2)
                    for heater_id in heater_by_id
                },
                stored_charge_percent_by_heater={
                    heater_id: round(stored_charge_percent[heater_id], 2)
                    for heater_id in heater_by_id
                },
                estimated_temperature_c_by_heater={
                    heater_id: round(estimated, 2)
                    for heater_id in heater_by_id
                    if (estimated := _estimate_accumulator_temperature(
                        heater_by_id[heater_id],
                        temperature,
                        stored_charge_percent[heater_id],
                    )) is not None
                },
            )
        )
        cursor = end
        slot_index += 1
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
