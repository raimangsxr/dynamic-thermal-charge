from datetime import datetime, timedelta

from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import SimulatedOutputDriver
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from dynamic_thermal_charge.service import ControllerService, PlanRefresh


class MemoryActivePlanStore:
    def __init__(self, plan=None):
        self.plan = plan

    def save(self, plan, *, installation_revision=0, forecast_ref=None):
        self.plan = plan
        return None

    def load(self):
        return self.plan


def service_plan(start):
    return ScheduleResult(
        slots=(
            ScheduleSlot(start, start + timedelta(minutes=30), ("a",), 2400),
            ScheduleSlot(
                start + timedelta(minutes=30),
                start + timedelta(minutes=60),
                ("b",),
                2400,
            ),
        ),
        allocated_minutes={"a": 30, "b": 30},
        unmet_minutes={},
    )


def test_service_persists_plan_and_executes_slots(tmp_path) -> None:
    start = datetime(2026, 1, 1)
    times = iter((start, start, start + timedelta(minutes=30), start + timedelta(minutes=30)))
    driver = SimulatedOutputDriver()
    store = MemoryActivePlanStore()
    service = ControllerService(
        controller=ChargeController(("a", "b"), driver),
        store=store,
        refresh_plan=lambda now: PlanRefresh(service_plan(start), 3600),
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: next(times),
        wait=lambda _: None,
    )

    assert service.run(max_cycles=2) == 0
    assert store.load() == service_plan(start)
    assert any(change.heater_id == "a" and change.enabled for change in driver.changes)
    assert any(change.heater_id == "b" and change.enabled for change in driver.changes)
    assert driver.changes[-1].enabled is False


def test_service_keeps_outputs_off_without_any_valid_plan(tmp_path, caplog) -> None:
    now = datetime(2026, 1, 1)
    times = iter((now, now, now))
    driver = SimulatedOutputDriver()

    def fail(_now):
        raise RuntimeError("forecast unavailable")

    service = ControllerService(
        controller=ChargeController(("a",), driver),
        store=MemoryActivePlanStore(),
        refresh_plan=fail,
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: next(times),
        wait=lambda _: None,
    )

    assert service.run(max_cycles=1) == 0
    assert not any(change.enabled for change in driver.changes)
    assert "Plan refresh failed; retaining persisted plan and retrying in 60 seconds: forecast unavailable" in caplog.text
    assert "Traceback" not in caplog.text
    assert "all outputs remain off" in caplog.text
