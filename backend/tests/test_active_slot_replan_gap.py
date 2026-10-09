from datetime import datetime, timedelta

from dynamic_thermal_charge.charge_planning import (
    AutomaticPlan,
    AutomaticPlanSlot,
    RoomEnergyInterval,
    VALID,
)
from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import SimulatedOutputDriver
from dynamic_thermal_charge.persistence.active_plan import SqlActivePlanRepository
from dynamic_thermal_charge.runtime import (
    _preserve_active_automatic_slot,
    _preserve_active_controller_slot,
)
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from tests.conftest import API_NOW, AUTH


SLOT = timedelta(minutes=30)


def _automatic_slot(start: datetime, heater_id: str) -> AutomaticPlanSlot:
    end = start + SLOT
    return AutomaticPlanSlot(
        start,
        end,
        (heater_id,),
        2800,
        {heater_id: 50.0},
        {heater_id: 60.0},
        outdoor_temperature_c=5.0,
        indoor_temperature_c={heater_id: 20.0},
        initial_soc_percent={heater_id: 50.0},
        demand_kwh={heater_id: 1.0},
        heater_power_w={heater_id: 2800},
        stored_energy_kwh={heater_id: 4.0},
        target_temperature_c={heater_id: 21.0},
        heat_delivered_kwh={heater_id: 0.5},
        thermal_loss_kwh={heater_id: 0.2},
        temperature_shortfall_c={heater_id: 0.0},
        charge_energy_kwh={heater_id: 1.0},
        stored_energy_next_kwh={heater_id: 4.5},
        indoor_temperature_next_c={heater_id: 20.1},
        temperature_shortfall_start_c={heater_id: 0.0},
        heat_delivery_limit_kwh={heater_id: 0.8},
    )


def _automatic_plan(start: datetime, heater_id: str) -> AutomaticPlan:
    slot = _automatic_slot(start, heater_id)
    interval = RoomEnergyInterval(
        heater_id,
        start,
        slot.end,
        5.0,
        21.0,
        20.0,
        20.1,
        4.0,
        4.5,
        50.0,
        56.25,
        1.0,
        0.5,
        0.2,
        0.0,
        0.0,
        0.8,
    )
    return AutomaticPlan(
        horizon_start=start,
        horizon_end=slot.end,
        slot_minutes=30,
        slots=(slot,),
        deficits=(),
        status=VALID,
        score=(),
        input_token=f"plan-{start.isoformat()}-{heater_id}",
        generated_at=start,
        demand=(interval,),
    )


def _controller_plan(start: datetime, heater_id: str) -> ScheduleResult:
    slot = ScheduleSlot(start, start + SLOT, (heater_id,), 2800)
    return ScheduleResult(
        slots=(slot,),
        allocated_minutes={heater_id: 30},
        unmet_minutes={},
    )


def test_deviation_at_one_microsecond_keeps_the_active_slot_and_joins_the_future():
    boundary = API_NOW
    now = boundary + timedelta(microseconds=1)
    previous = _controller_plan(boundary, "salon")
    candidate = _controller_plan(boundary + SLOT, "entrada")

    merged = _preserve_active_controller_slot(candidate, previous, now)

    assert [(slot.start, slot.end, slot.heater_ids) for slot in merged.slots] == [
        (boundary, boundary + SLOT, ("salon",)),
        (boundary + SLOT, boundary + 2 * SLOT, ("entrada",)),
    ]
    assert merged.slots[0].heater_ids == previous.slots[0].heater_ids
    assert merged.slots[1].start == boundary + SLOT


def test_replan_without_an_active_slot_keeps_the_candidate_unchanged():
    boundary = API_NOW
    candidate = _controller_plan(boundary + SLOT, "entrada")
    previous = _controller_plan(boundary - SLOT, "salon")

    assert _preserve_active_controller_slot(
        candidate, previous, boundary + timedelta(microseconds=1)
    ) == candidate


def test_controller_transitions_directly_at_the_next_boundary_without_an_off_pulse():
    boundary = API_NOW
    now = boundary + timedelta(microseconds=1)
    merged = _preserve_active_controller_slot(
        _controller_plan(boundary + SLOT, "entrada"),
        _controller_plan(boundary, "salon"),
        now,
    )
    driver = SimulatedOutputDriver()
    controller = ChargeController(("salon", "entrada"), driver)

    controller.initialize(now)
    controller.apply(merged, now)
    controller.apply(merged, boundary + SLOT)

    assert [(change.heater_id, change.enabled) for change in driver.changes] == [
        ("salon", True),
        ("salon", False),
        ("entrada", True),
    ]
    assert driver.changes[-2].at == driver.changes[-1].at == boundary + SLOT


def test_persisted_replan_keeps_the_active_automatic_slot(initialised_store):
    boundary = API_NOW
    now = boundary + timedelta(microseconds=1)
    _config, revision = initialised_store.repository.current()
    planning = initialised_store.planning
    previous = _automatic_plan(boundary, "salon")
    candidate = _automatic_plan(boundary + SLOT, "entrada")
    planning.save_plan(
        previous,
        configuration_revision=revision,
        constraints_revision=planning.site()["revision"],
        reason="periodic",
        active=True,
    )

    merged = _preserve_active_automatic_slot(
        candidate, planning.active_plan(), now
    )
    planning.save_plan(
        merged,
        configuration_revision=revision,
        constraints_revision=planning.site()["revision"],
        reason="deviation",
        active=True,
        preserve_active=True,
    )

    reloaded = planning.active_plan()
    assert reloaded is not None
    assert [
        (slot["start"], slot["end"], slot["heater_ids"])
        for slot in reloaded["slots"]
    ] == [
        (boundary, boundary + SLOT, ["salon"]),
        (boundary + SLOT, boundary + 2 * SLOT, ["entrada"]),
    ]
    assert reloaded["slots"][0]["required_charge_percent"] == {"salon": 60.0}
    assert reloaded["slots"][0]["target_temperature_c"] == {"salon": 21.0}
    assert reloaded["slots"][0]["stored_energy_next_kwh"] == {"salon": 4.5}
    assert reloaded["slots"][0]["temperature_shortfall_start_c"] == {"salon": 0.0}

    active_store = SqlActivePlanRepository(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    )
    active_store.save(
        _preserve_active_controller_slot(
            _controller_plan(boundary + SLOT, "entrada"),
            _controller_plan(boundary, "salon"),
            now,
        ),
        installation_revision=revision,
    )
    recovered = active_store.load()
    assert recovered is not None
    assert [slot.heater_ids for slot in recovered.slots] == [
        ("salon",),
        ("entrada",),
    ]


def test_status_projects_the_retained_slot_during_the_transition(
    client, initialised_store, heartbeat, api_clock
):
    boundary = API_NOW
    now = boundary + timedelta(microseconds=1)
    api_clock.now = now
    _config, revision = initialised_store.repository.current()
    planning = initialised_store.planning
    planning.save_plan(
        _automatic_plan(boundary, "salon"),
        configuration_revision=revision,
        constraints_revision=planning.site()["revision"],
        reason="periodic",
        active=True,
    )
    merged = _preserve_active_automatic_slot(
        _automatic_plan(boundary + SLOT, "entrada"),
        planning.active_plan(),
        now,
    )
    planning.save_plan(
        merged,
        configuration_revision=revision,
        constraints_revision=planning.site()["revision"],
        reason="deviation",
        active=True,
    )
    heartbeat.publish(now, degraded=False)

    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"] is not None
    assert [
        (item["start"], item["end"], item["heater_ids"])
        for item in body["plan"]["slots"][:2]
    ] == [
        (boundary.isoformat().replace("+00:00", "Z"), (boundary + SLOT).isoformat().replace("+00:00", "Z"), ["salon"]),
        ((boundary + SLOT).isoformat().replace("+00:00", "Z"), (boundary + 2 * SLOT).isoformat().replace("+00:00", "Z"), ["entrada"]),
    ]
