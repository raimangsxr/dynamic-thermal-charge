from datetime import datetime, timedelta

import pytest

from dynamic_thermal_charge.runtime import (
    _handle_termination_signal,
    _run_output_self_test,
)
from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.api.security import relay_test_credential_digest
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


def test_active_relay_test_ends_when_lease_expires_without_a_pending_command(initialised_store, clock) -> None:
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    relay_tests = initialised_store.relay_tests
    session_id = relay_tests.claim(relay_test_credential_digest("owner"), clock(), 1)["session"]["id"]
    publisher = SqlHeartbeatPublisher(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5,
        driver_kind="gpio",
        started_at=clock(),
        runner_id="runner-a",
        location=initialised_store.location,
    )
    publisher.publish(clock(), degraded=False)
    heater_ids = tuple(heater.id for heater in initialised_store.repository.current()[0].heaters)
    driver = RecordingDriver()
    controller = ChargeController(heater_ids, driver, relay_tests=relay_tests, runner_id="runner-a")

    controller.apply(None, clock())
    assert relay_tests.current()["session"]["status"] == "active"

    clock.advance(seconds=2)
    controller.apply(None, clock())

    terminal = relay_tests.get(session_id)
    assert terminal["session"]["status"] == "ended"
    assert all(output["confirmed_state"] is False for output in terminal["heaters"])


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


# --------------------------------------------------------------------------- #
# R1-R4: a driver failure in a normal transition degrades that output only.
#
# `_sweep_off` was written to tolerate one unresponsive relay; `apply` was not.
# A failure there aborted the remaining transitions of the cycle, left `_active`
# claiming a state the driver had refused, and escaped `ControllerService.run`,
# which only catches KeyboardInterrupt.
# --------------------------------------------------------------------------- #


class SelectivelyFailingDriver(RecordingDriver):
    """Refuses the scripted ``(heater_id, enabled)`` transitions.

    Tracks the state the hardware actually reached, so a test can tell what the
    relays are really doing from what the controller believes.
    """

    def __init__(self, failing=()) -> None:
        super().__init__()
        self.failing = set(failing)
        self.state: dict[str, bool] = {}

    def set_state(self, heater_id, enabled, at):
        super().set_state(heater_id, enabled, at)
        if (heater_id, enabled) in self.failing:
            raise RuntimeError(f"relay {heater_id} refused {enabled}")
        self.state[heater_id] = enabled


def test_apply_keeps_serving_the_other_outputs_when_one_relay_fails() -> None:
    start = datetime(2026, 1, 1)
    middle = start + timedelta(minutes=30)
    driver = SelectivelyFailingDriver(failing={("a", False)})
    controller = ChargeController(("a", "b"), driver)

    controller.apply(plan(start), start)
    controller.apply(plan(start), middle)

    # "b" owns the second slot and must charge even though "a" would not open.
    assert driver.state["b"] is True


def test_apply_presumes_an_output_whose_off_failed_is_still_active() -> None:
    start = datetime(2026, 1, 1)
    middle = start + timedelta(minutes=30)
    driver = SelectivelyFailingDriver(failing={("a", False)})
    controller = ChargeController(("a", "b"), driver)

    controller.apply(plan(start), start)
    controller.apply(plan(start), middle)

    # The relay is physically closed, so the controller may not report it open:
    # instantaneous power is derived from what it believes is active.
    assert controller.active_outputs == {"a", "b"}


def test_apply_does_not_claim_an_output_whose_on_failed() -> None:
    start = datetime(2026, 1, 1)
    driver = SelectivelyFailingDriver(failing={("a", True)})
    controller = ChargeController(("a", "b"), driver)

    controller.apply(plan(start), start)

    assert controller.active_outputs == set()


def test_apply_retries_a_failed_output_on_the_next_cycle() -> None:
    start = datetime(2026, 1, 1)
    middle = start + timedelta(minutes=30)
    driver = SelectivelyFailingDriver(failing={("a", False)})
    controller = ChargeController(("a", "b"), driver)

    controller.apply(plan(start), start)
    controller.apply(plan(start), middle)
    driver.failing.clear()
    controller.apply(plan(start), middle)

    assert driver.state["a"] is False
    assert controller.active_outputs == {"b"}


def test_apply_reports_degraded_outputs_only_while_a_relay_is_failing(caplog) -> None:
    start = datetime(2026, 1, 1)
    middle = start + timedelta(minutes=30)
    driver = SelectivelyFailingDriver(failing={("a", False)})
    controller = ChargeController(("a", "b"), driver)

    controller.apply(plan(start), start)
    assert controller.outputs_degraded is False

    with caplog.at_level("INFO"):
        controller.apply(plan(start), middle)
        assert controller.outputs_degraded is True
        # Once per transition, not once per cycle.
        controller.apply(plan(start), middle)
        entered = [
            record
            for record in caplog.records
            if record.levelname == "CRITICAL" and "a" in record.getMessage()
        ]
        assert len(entered) == 1

        driver.failing.clear()
        controller.apply(plan(start), middle)

    assert controller.outputs_degraded is False


# --------------------------------------------------------------------------- #
# R5: the relay-test paths that discard the result of their OFF sweep.
#
# The living relay-test spec requires that any partial OFF arms a *persistent*
# safety lock. Four paths in `_apply_relay_test` swept, threw the result away
# and armed only the in-memory latch, so a possibly-closed relay left no durable
# trace for the next process.
# --------------------------------------------------------------------------- #


class DeadRelayDriver(RecordingDriver):
    """Relay "a" accepts nothing at all; "b" works."""

    def set_state(self, heater_id, enabled, at):
        super().set_state(heater_id, enabled, at)
        if heater_id == "a":
            raise RuntimeError("relay a unavailable")


class CoordinationStub:
    """Relay-test coordination whose failures are scripted per call."""

    def __init__(self, view=None, raise_on=()) -> None:
        self.view = view
        self.raise_on = set(raise_on)
        self.armed: list[tuple[str | None, str]] = []
        self.ended: list[tuple[str, bool, str | None]] = []
        self.can_switch_calls = 0

    def _maybe_raise(self, key: str) -> None:
        if key in self.raise_on:
            raise RuntimeError(f"coordination unavailable at {key}")

    def current(self, credential_digest=None):
        self._maybe_raise("current")
        return self.view

    def controller_can_switch(self, session_id, runner_id, now) -> bool:
        self.can_switch_calls += 1
        self._maybe_raise(f"can_switch:{self.can_switch_calls}")
        return True

    def activate(self, session_id, runner_id, now) -> bool:
        self._maybe_raise("activate")
        return True

    def confirm(self, session_id, heater_id, sequence, state, now) -> None:
        self._maybe_raise("confirm")

    def unknown(self, session_id, heater_id, sequence, now, code="driver_failed") -> None:
        self._maybe_raise("unknown")

    def request_controller_end(self, session_id, now, reason) -> None:
        self._maybe_raise("request_controller_end")

    def recover_latch(self, generation, now) -> bool:
        self._maybe_raise("recover_latch")
        return True

    def arm_latch(self, session_id, now, reason) -> None:
        self._maybe_raise("arm_latch")
        self.armed.append((session_id, reason))

    def end(self, session_id, now, failed=False, reason=None, off_results=None) -> None:
        self._maybe_raise("end")
        self.ended.append((session_id, failed, reason))

    def durable_latches(self) -> list[str]:
        """Every reason for which a partial OFF was made durable."""
        return [reason for _, reason in self.armed] + [
            reason for _, failed, reason in self.ended if failed
        ]


def _active_view(status: str = "active", pending: bool = False) -> dict:
    return {
        "session": {"id": "session-1", "status": status},
        "safety": {},
        "heaters": [
            {
                "heater_id": "a",
                "command_seq": 2 if pending else 1,
                "confirmed_seq": 1,
                "desired_state": True,
            }
        ],
    }


def test_partial_off_is_durable_when_coordination_cannot_be_read() -> None:
    relay_tests = CoordinationStub(raise_on={"current"})
    controller = ChargeController(("a", "b"), DeadRelayDriver(), relay_tests=relay_tests)

    controller.apply(None, datetime(2026, 1, 1))

    assert relay_tests.durable_latches() == ["off_sweep_failed"]


def test_partial_off_is_durable_when_the_lease_check_fails_before_any_command() -> None:
    relay_tests = CoordinationStub(_active_view(), raise_on={"can_switch:1"})
    controller = ChargeController(("a", "b"), DeadRelayDriver(), relay_tests=relay_tests)

    controller.apply(None, datetime(2026, 1, 1))

    assert relay_tests.durable_latches() == ["off_sweep_failed"]


def test_partial_off_is_durable_when_the_lease_check_fails_for_a_pending_command() -> None:
    relay_tests = CoordinationStub(
        _active_view(pending=True), raise_on={"can_switch:2"}
    )
    controller = ChargeController(("a", "b"), DeadRelayDriver(), relay_tests=relay_tests)

    controller.apply(None, datetime(2026, 1, 1))

    assert relay_tests.durable_latches() == ["off_sweep_failed"]


def test_partial_off_is_durable_when_a_driver_failure_cannot_be_recorded() -> None:
    relay_tests = CoordinationStub(_active_view(pending=True), raise_on={"unknown"})
    controller = ChargeController(("a", "b"), DeadRelayDriver(), relay_tests=relay_tests)

    controller.apply(None, datetime(2026, 1, 1))

    assert relay_tests.durable_latches() == ["off_sweep_failed"]
