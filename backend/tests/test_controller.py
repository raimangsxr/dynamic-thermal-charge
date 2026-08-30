from datetime import datetime, timedelta

import pytest

from dynamic_thermal_charge.runtime import (
    _handle_termination_signal,
    _run_output_self_test,
)
from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot


class RecordingDriver:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    def set_state(self, heater_id, enabled, at):
        self.calls.append((heater_id, enabled, at))

    def close(self):
        self.closed = True


class PartiallyFailingDriver(RecordingDriver):
    def set_state(self, heater_id, enabled, at):
        super().set_state(heater_id, enabled, at)
        if heater_id == "a" and not enabled:
            raise RuntimeError("relay a unavailable")


class LatchRecorder:
    def __init__(self) -> None:
        self.armed: list[tuple[str | None, str]] = []

    def arm_latch(self, session_id, _at, reason) -> None:
        self.armed.append((session_id, reason))


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
    assert driver.closed is True


def test_shutdown_continues_after_one_output_fails(caplog) -> None:
    driver = PartiallyFailingDriver()
    controller = ChargeController(("a", "b"), driver)

    controller.shutdown(datetime(2026, 1, 1))

    assert [(heater_id, enabled) for heater_id, enabled, _ in driver.calls] == [
        ("a", False),
        ("b", False),
    ]
    assert driver.closed is True
    assert "Failed to force output a OFF" in caplog.text


def test_partial_shutdown_persists_a_fault_latch_after_sweeping_every_output() -> None:
    driver = PartiallyFailingDriver()
    relay_tests = LatchRecorder()
    controller = ChargeController(("a", "b"), driver, relay_tests=relay_tests)

    controller.shutdown(datetime(2026, 1, 1))

    assert [(heater_id, enabled) for heater_id, enabled, _ in driver.calls] == [
        ("a", False), ("b", False),
    ]
    assert relay_tests.armed == [(None, "off_sweep_failed")]


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


def test_sigterm_is_converted_to_controlled_shutdown() -> None:
    with pytest.raises(KeyboardInterrupt):
        _handle_termination_signal(None, None)


def test_output_self_test_activates_one_heater_at_a_time() -> None:
    from dynamic_thermal_charge.persistence.seed import example_installation

    config = example_installation()
    driver = RecordingDriver()
    waits = []

    status = _run_output_self_test(
        config,
        driver,
        duration_seconds=0.25,
        wait=waits.append,
    )

    on_calls = [(heater_id, enabled) for heater_id, enabled, _ in driver.calls if enabled]
    assert status == 0
    assert on_calls == [
        ("salon", True),
        ("entrada", True),
        ("habitaciones", True),
        ("buhardilla", True),
    ]
    assert waits == [0.25, 0.25, 0.25, 0.25]
    assert driver.closed is True
