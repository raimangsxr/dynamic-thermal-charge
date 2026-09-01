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
        limit_w = config.site.max_total_power_w
        power = PowerSnapshot(
            instant_w=instant_w,
            limit_w=limit_w,
            percent_of_limit=round(100.0 * instant_w / limit_w, 1) if limit_w else 0.0,
        )

    plan = forecast = None
    allocations: list[AllocationSummary] = []
    snapshot = reader.plan_in_progress(observed_at)
    if snapshot is not None:
        grouped: dict[tuple[datetime, datetime], list[str]] = {}
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
        if snapshot["forecast"] is not None:
            forecast = ForecastSummary(**snapshot["forecast"])
        allocations = [
            AllocationSummary(**allocation) for allocation in snapshot["allocations"]
        ]

    telemetry_views = []
    telemetry_snapshot = store.planning.telemetry()
    for heater in config.heaters:
        value = telemetry_snapshot.get(heater.id)
        if value is None:
            telemetry_views.append(ChargeTelemetryView(heater_id=heater.id, missing_fields=["temperature_c", "target_temperature_c", "stored_charge_percent"]))
            continue
        stamps = (value.temperature_received_at, value.target_received_at, value.stored_charge_received_at)
        ages = [(observed_at - item).total_seconds() for item in stamps if item is not None]
        missing = [name for name, item in (("temperature_c", value.temperature_c), ("target_temperature_c", value.target_temperature_c), ("stored_charge_percent", value.stored_charge_percent)) if item is None]
        oldest = max(ages, default=None)
        telemetry_views.append(ChargeTelemetryView(heater_id=heater.id, temperature_c=value.temperature_c, target_temperature_c=value.target_temperature_c, stored_charge_percent=value.stored_charge_percent, temperature_received_at=value.temperature_received_at, target_received_at=value.target_received_at, stored_charge_received_at=value.stored_charge_received_at, state="telemetry_stale" if missing or oldest is None or oldest > 900 else "ready", missing_fields=missing, oldest_age_seconds=oldest))
    active_automatic = store.planning.active_plan()
    return StatusResponse(
        observed_at=observed_at,
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
        plan_status=None if active_automatic is None else active_automatic["status"],
        deficits=[] if active_automatic is None else [PlanningDeficitView(**item) for item in active_automatic["deficits"]],
    )


__all__ = ["router"]
