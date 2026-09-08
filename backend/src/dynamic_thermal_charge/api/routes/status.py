"""The state of the moment, and how much of it may be claimed.

The rule that governs this whole module: when the controller has not been seen
recently, ``output_on`` is **null** and no instantaneous power is published. A
panel claiming that a 2.8 kW heater is charging when it is not leads to wrong
decisions about the electrical installation; "I do not know" does not.

No SQL here. Every read goes through the persistence boundary (principle II), and
a guard test fails if this package ever imports the driver stack.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ..dependencies import controller_view, usable_store
from ..liveness import ControllerView
from ..read_model import automatic_window, forecast_cycle_context, real_at_or_after, real_before
from ..schemas import (
    READ_RESPONSES,
    AllocationSummary,
    ControllerHealth,
    ForecastSummary,
    HeaterState,
    PlanSlotView,
    PlanSummary,
    PowerSnapshot,
    StatusResponse,
    ChargeTelemetryView,
    PlanningDeficitView,
)


router = APIRouter()


@router.get(
    "/status",
    response_model=StatusResponse,
    responses=READ_RESPONSES,
    summary="What is happening right now",
    description=(
        "The whole snapshot in one call: active heaters, instantaneous power, "
        "the plan in progress, the forecast that produced it and the per-heater "
        "allocation.\n\n"
        "**Read `controller.state_is_current` first.** When it is false the "
        "controller has not been seen recently: `power` is null, each heater's "
        "`output_on` is null rather than false, and the last known value is in "
        "`last_known_output_on` with its `changed_at`. Null and false mean "
        "different things here: false says it is off, null says there is no proof "
        "either way."
    ),
)
def get_status(
    request: Request,
    store: Store = Depends(usable_store),
    controller: ControllerView = Depends(controller_view),
) -> StatusResponse:
    observed_at: datetime = request.app.state.clock()
    config, _revision = store.repository.current()
    reader = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    planning_site = store.planning.site()
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    cycle_status = forecast_cycle_context(store.planning)
    latest_forecast = reader.latest_forecast(observed_at)

    last_states = reader.last_output_states()
    current = controller.state_is_current
    heaters = []
    for heater in config.heaters:
        known, changed_at = last_states.get(heater.id, (False, None))
        heaters.append(
            HeaterState(
                id=heater.id,
                name=heater.name,
                enabled=heater.enabled,
                power_w=heater.power_w,
                # Null unless there is proof it is current, so a client reading
                # only this field can never render a heater as charging on the
                # strength of a transition recorded before the controller died.
                output_on=known if current else None,
                last_known_output_on=known,
                changed_at=changed_at,
            )
        )

    power = None
    if current:
        instant_w = sum(h.power_w for h in heaters if h.last_known_output_on)
        # Automatic planning owns the canonical site power limit. The legacy
        # installation column remains for compatibility, but must not make the
        # status panel disagree with the plan when both values differ.
        limit_w = int(planning_site.get("contracted_power_w", config.site.max_total_power_w))
        power = PowerSnapshot(
            instant_w=instant_w,
            limit_w=limit_w,
            percent_of_limit=round(100.0 * instant_w / limit_w, 1) if limit_w else 0.0,
        )

    plan = forecast = None
    allocations: list[AllocationSummary] = []
    horizon_start = horizon_end = None
    absence_reason = None
    active_automatic = store.planning.active_plan()
    latest_automatic = (
        store.planning.latest_plan()
        if hasattr(store.planning, "latest_plan")
        else None
    )
    canonical_plan = active_automatic
    if canonical_plan is None and latest_automatic is not None and latest_automatic["status"] == "INVALID":
        # An invalid recalculation intentionally removes the previous active
        # plan.  Keep that safe outcome visible instead of reviving a legacy
        # plan which is no longer executable.
        canonical_plan = latest_automatic
        absence_reason = "invalid_automatic_plan"

    if canonical_plan is not None:
        horizon_start = canonical_plan["horizon_start"]
        horizon_end = canonical_plan["horizon_end"]
        window_start, window_end = automatic_window(
            canonical_plan,
            int(planning_site["planning_window_hours"]),
            timezone_name,
        )
        if canonical_plan["status"] == "INVALID":
            plan = None
        elif real_at_or_after(observed_at, window_start) and real_before(observed_at, window_end):
            grouped: dict[tuple[datetime, datetime], list[str]] = {}
            for slot in canonical_plan["slots"]:
                if real_before(slot["start"], window_end):
                    grouped.setdefault((slot["start"], slot["end"]), []).extend(
                        slot["heater_ids"]
                    )
            plan = PlanSummary(
                window_start=window_start,
                window_end=window_end,
                slot_minutes=canonical_plan["slot_minutes"],
                installation_revision=canonical_plan["configuration_revision"],
                created_at=canonical_plan["created_at"],
                slots=[
                    PlanSlotView(start=start, end=end, heater_ids=sorted(set(ids)))
                    for (start, end), ids in sorted(grouped.items())
                ],
            )
        else:
            absence_reason = absence_reason or "outside_visible_window"
        if latest_forecast is not None:
            forecast = ForecastSummary(**latest_forecast)
    elif latest_automatic is None:
        # Compatibility path for installations that have not produced an
        # automatic plan yet.  Once one exists, the status panel never resumes
        # reading the legacy plan as its canonical live projection.
        snapshot = reader.plan_in_progress(observed_at)
        if snapshot is not None:
            grouped = {}
            for slot in snapshot["slots"]:
                grouped.setdefault((slot["slot_start"], slot["slot_end"]), []).append(
                    slot["heater_id"]
                )
            plan = PlanSummary(
                **snapshot["plan"],
                slots=[
                    PlanSlotView(start=start, end=end, heater_ids=sorted(ids))
                    for (start, end), ids in sorted(grouped.items())
                ],
            )
            horizon_start = snapshot["plan"]["window_start"]
            horizon_end = snapshot["plan"]["window_end"]
            forecast_value = latest_forecast or snapshot["forecast"]
            if forecast_value is not None:
                forecast = ForecastSummary(**forecast_value)
            allocations = [
                AllocationSummary(**allocation)
                for allocation in snapshot["allocations"]
            ]
        elif latest_forecast is not None:
            forecast = ForecastSummary(**latest_forecast)
    elif latest_automatic is not None:
        # An automatic record exists but is not active.  Keep the absence
        # explicit instead of presenting an unrelated legacy plan as current.
        absence_reason = "no_active_automatic_plan"
        if latest_forecast is not None:
            forecast = ForecastSummary(**latest_forecast)

    telemetry_views = []
    telemetry_snapshot = store.planning.telemetry()
    for heater in config.heaters:
        value = telemetry_snapshot.get(heater.id)
        if value is None:
            telemetry_views.append(ChargeTelemetryView(heater_id=heater.id, missing_fields=["indoor_temperature_c", "stored_soc_percent"]))
            continue
        stamps = (value.indoor_received_at, value.stored_soc_received_at)
        ages = [(observed_at - item).total_seconds() for item in stamps if item is not None]
        missing = [name for name, item in (("indoor_temperature_c", value.indoor_temperature_c), ("stored_soc_percent", value.stored_soc_percent)) if item is None]
        oldest = max(ages, default=None)
        telemetry_views.append(ChargeTelemetryView(
            heater_id=heater.id,
            indoor_temperature_c=value.indoor_temperature_c,
            stored_soc_percent=value.stored_soc_percent,
            indoor_received_at=value.indoor_received_at,
            stored_soc_received_at=value.stored_soc_received_at,
            stored_energy_kwh=(
                None
                if value.stored_soc_percent is None
                else value.stored_soc_percent / 100 * heater.capacity_kwh
            ),
            state="telemetry_stale" if missing or oldest is None or oldest > config.site.indoor_max_age_minutes * 60 or any(age < 0 for age in ages) else "ready",
            missing_fields=missing,
            oldest_age_seconds=oldest,
        ))
    return StatusResponse(
        observed_at=observed_at,
        timezone=timezone_name,
        controller=ControllerHealth(
            liveness=controller.liveness.value,
            state_is_current=current,
            last_seen_at=controller.last_seen_at,
            age_seconds=(
                None
                if controller.age_seconds is None
                else round(controller.age_seconds, 1)
            ),
            started_at=controller.started_at,
            degraded=controller.degraded,
            driver_kind=controller.driver_kind,
            tolerance_seconds=controller.tolerance_seconds,
            multiple_controllers_suspected=controller.multiple_controllers_suspected,
        ),
        power=power,
        heaters=heaters,
        plan=plan,
        forecast=forecast,
        allocations=allocations,
        telemetry=telemetry_views,
        plan_status=None if canonical_plan is None else canonical_plan["status"],
        deficits=[] if canonical_plan is None else [PlanningDeficitView(**item) for item in canonical_plan["deficits"]],
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        absence_reason=absence_reason,
        forecast_status=cycle_status.get("forecast_status"),
        forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
        forecast_last_error=cycle_status.get("forecast_last_error"),
        forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
        forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
        forecast_stale=cycle_status.get("forecast_stale"),
    )


__all__ = ["router"]
