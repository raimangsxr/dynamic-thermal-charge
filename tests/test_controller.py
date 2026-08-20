from datetime import datetime, timedelta

from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot


class RecordingDriver:
    def __init__(self) -> None:
        self.calls = []

    def set_state(self, heater_id, enabled, at):
        self.calls.append((heater_id, enabled, at))


def plan(start: datetime) -> ScheduleResult:
    middle = start + timedelta(minutes=30)
    end = middle + timedelta(minutes=30)
    return ScheduleResult(
        slots=(
            ScheduleSlot(start, middle, ("a",), 2400),
            ScheduleSlot(middle, end, ("b",), 2400),
        ),
        allocated_minutes={"a": 30, "b": 30},
        unmet_minutes={},
    )


def test_applies_only_transitions_and_turns_off_before_turning_on() -> None:
    start = datetime(2026, 1, 1)
    driver = RecordingDriver()
    controller = ChargeController(("a", "b"), driver)
    controller.initialize(start)

    controller.apply(plan(start), start)
    controller.apply(plan(start), start + timedelta(minutes=10))
    controller.apply(plan(start), start + timedelta(minutes=30))

    assert [(heater_id, enabled) for heater_id, enabled, _ in driver.calls] == [
        ("a", False),
        ("b", False),
        ("a", True),
        ("a", False),
        ("b", True),
    ]


def test_shutdown_forces_every_output_off() -> None:
    start = datetime(2026, 1, 1)
    driver = RecordingDriver()
    controller = ChargeController(("a", "b"), driver)
    controller.initialize(start)
    controller.apply(plan(start), start)

    controller.shutdown(start + timedelta(minutes=5))

    assert [(heater_id, enabled) for heater_id, enabled, _ in driver.calls[-2:]] == [
        ("a", False),
        ("b", False),
    ]


def test_ignores_unknown_heaters_from_persisted_plan(caplog) -> None:
    start = datetime(2026, 1, 1)
    driver = RecordingDriver()
    controller = ChargeController(("known",), driver)
    persisted = ScheduleResult(
        slots=(
            ScheduleSlot(
                start,
                start + timedelta(minutes=30),
                ("known", "removed-heater"),
                4800,
            ),
        ),
        allocated_minutes={},
        unmet_minutes={},
    )
    controller.initialize(start)

    controller.apply(persisted, start)

    assert not any(call[0] == "removed-heater" for call in driver.calls)
    assert "Ignoring unknown heater ids" in caplog.text
