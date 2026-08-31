"""Read-only planning projection for the operator panel."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ..dependencies import usable_store
from ..schemas import (
    AllocationSummary,
    HourlyForecastPointView,
    PlanningForecastView,
    PlanningHeaterView,
    PlanningPlanView,
    PlanningResponse,
    PlanningSlotView,
    PlanningTimelineSlotView,
    READ_RESPONSES,
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
        return PlanningResponse(
            observed_at=observed_at,
            max_total_power_w=config.site.max_total_power_w,
            heaters=heaters,
            absence_reason="no_current_or_next_plan",
        )

    forecast = snapshot["forecast"]
    forecast_view = None
    if forecast is not None:
        forecast_view = PlanningForecastView(
            **{key: value for key, value in forecast.items() if key != "hourly_points"},
            hourly_points=[HourlyForecastPointView(**point) for point in forecast["hourly_points"]],
        )

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

    return PlanningResponse(
        observed_at=observed_at,
        max_total_power_w=config.site.max_total_power_w,
        plan=PlanningPlanView(**plan_data, slots=slots),
        forecast=forecast_view,
        allocations=[AllocationSummary(**item) for item in snapshot["allocations"]],
        heaters=heaters,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        timeline=timeline,
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
            reserve_minutes[heater.id] = min(
                heater.full_charge_minutes,
                max(0.0, reserve_minutes[heater.id]),
            )

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


__all__ = ["router"]
