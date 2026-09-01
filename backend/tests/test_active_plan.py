"""Database continuity for the controller's accepted plan."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import SimulatedOutputDriver
from dynamic_thermal_charge.persistence import ConfigStoreUnavailableError
from dynamic_thermal_charge.persistence.active_plan import SqlActivePlanRepository
from dynamic_thermal_charge.persistence.schema import plan as plan_table
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from dynamic_thermal_charge.service import ControllerService, PlanRefresh


START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _plan() -> ScheduleResult:
    return ScheduleResult(
        slots=(
            ScheduleSlot(
                START,
                START + timedelta(minutes=30),
                ("salon",),
                2800,
                temperature_c=4.5,
                temperature_interpolated=True,
            ),
            ScheduleSlot(
                START + timedelta(minutes=30),
                START + timedelta(minutes=60),
                (),
                0,
            ),
        ),
        allocated_minutes={"salon": 30},
        unmet_minutes={"entrada": 30},
    )


def test_an_accepted_plan_survives_a_process_restart_without_a_state_file(
    initialised_store, tmp_path
):
    engine = initialised_store.application_engine or initialised_store.engine
    installation_id = initialised_store.repository.installation_id()
    plan = _plan()
    SqlActivePlanRepository(engine, installation_id, initialised_store.location).save(
        plan, installation_revision=1
    )

    recovered = SqlActivePlanRepository(
        engine, installation_id, initialised_store.location
    ).load()

    assert recovered is not None
    assert [(slot.start, slot.end, slot.heater_ids) for slot in recovered.slots] == [
        (slot.start, slot.end, slot.heater_ids) for slot in plan.slots
    ]
    assert recovered.allocated_minutes == {"salon": 30, "entrada": 0}
    assert recovered.unmet_minutes == plan.unmet_minutes
    assert not (tmp_path / "active-plan.json").exists()


def test_a_new_application_database_has_no_recoverable_plan(initialised_store):
    engine = initialised_store.application_engine or initialised_store.engine
    installation_id = initialised_store.repository.installation_id()

    assert SqlActivePlanRepository(
        engine, installation_id, initialised_store.location
    ).load() is None


def test_a_transient_database_failure_keeps_the_last_plan_in_memory(
    initialised_store, monkeypatch
):
    engine = initialised_store.application_engine or initialised_store.engine
    installation_id = initialised_store.repository.installation_id()
    store = SqlActivePlanRepository(engine, installation_id, initialised_store.location)
    old_plan = _plan()
    store.save(old_plan, installation_revision=1)
    new_plan = ScheduleResult(
        slots=(
            ScheduleSlot(
                START,
                START + timedelta(minutes=30),
                ("entrada",),
                2400,
            ),
        ),
        allocated_minutes={"entrada": 30},
        unmet_minutes={},
    )
    monkeypatch.setattr(
        store,
        "save",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ConfigStoreUnavailableError("database unreachable")
        ),
    )
    driver = SimulatedOutputDriver()
    service = ControllerService(
        controller=ChargeController(("salon", "entrada"), driver),
        store=store,
        refresh_plan=lambda _now: PlanRefresh(new_plan, 60),
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: START + timedelta(minutes=5),
        wait=lambda _seconds: None,
    )

    service.run(max_cycles=1)

    assert service.degraded is True
    assert any(
        change.heater_id == "salon" and change.enabled for change in driver.changes
    )
    assert not any(
        change.heater_id == "entrada" and change.enabled for change in driver.changes
    )


def test_an_invalid_database_plan_is_treated_as_no_plan(initialised_store):
    engine = initialised_store.application_engine or initialised_store.engine
    installation_id = initialised_store.repository.installation_id()
    store = SqlActivePlanRepository(engine, installation_id, initialised_store.location)
    plan_ref = store.save(_plan(), installation_revision=1)
    with engine.begin() as connection:
        connection.execute(
            update(plan_table)
            .where(plan_table.c.id == plan_ref.id)
            .values(slot_minutes=0)
        )

    assert store.load() is None
