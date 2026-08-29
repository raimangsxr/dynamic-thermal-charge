"""Fail-safe execution of a charge plan through an output driver."""

from __future__ import annotations

from datetime import datetime
import logging

from .drivers import OutputDriver
from .scheduler import ScheduleResult


logger = logging.getLogger(__name__)


class ChargeController:
    def __init__(self, heater_ids: tuple[str, ...], driver: OutputDriver, relay_tests=None, runner_id: str = "controller") -> None:
        self._heater_ids = heater_ids
        self._heater_id_set = set(heater_ids)
        self._driver = driver
        self._active: set[str] = set()
        self._relay_tests = relay_tests
        self._runner_id = runner_id
        self._relay_test_latch_local = False
        self._relay_test_session_id: str | None = None

    def initialize(self, at: datetime) -> None:
        logger.info("Initializing controller with all outputs off")
        # Startup is a safety sweep too.  Do not allow one bad relay to abort
        # the remaining OFF requests, and preserve the failure for the next
        # process instead of forgetting it when this controller exits.
        results = self._sweep_off(at)
        if not all(results.values()):
            self._latch_partial_off(at, "off_sweep_failed")

    def apply(self, plan: ScheduleResult | None, at: datetime) -> None:
        if self._relay_tests is not None and self._apply_relay_test(at):
            return
        desired = self._desired_outputs(plan, at)
        for heater_id in sorted(self._active - desired):
            self._driver.set_state(heater_id, False, at)
        for heater_id in sorted(desired - self._active):
            self._driver.set_state(heater_id, True, at)
        if desired != self._active:
            logger.info("Controller outputs at %s: %s", at.isoformat(), sorted(desired))
        self._active = desired

    def _apply_relay_test(self, at: datetime) -> bool:
        """Apply DB intentions only while test coordination owns the controller."""
        try:
            view = self._relay_tests.current()
        except Exception:
            # Loss of coordination is ambiguous: immediately go safe and never
            # fall through to automatic output in this cycle.
            self._sweep_off(at)
            self._relay_test_latch_local = True
            return True
        # A local latch is authoritative until it has been durably reconciled;
        # do not let a temporarily readable store re-enable automatic control.
        if self._relay_test_latch_local:
            results = self._sweep_off(at)
            if all(results.values()):
                try:
                    self._relay_tests.arm_latch(None, at, "store_unavailable")
                    self._relay_test_latch_local = False
                except Exception:
                    return True
            return True
        if not view:
            return False
        session = view.get("session")
        safety = view.get("safety", {})
        if safety.get("fault_latched"):
            generation = int(safety.get("fault_generation", 0))
            results = self._sweep_off(at)
            try:
                if all(results.values()):
                    # This cycle is recovery only.  Automatic control can resume
                    # on the following cycle after a fresh read.
                    self._relay_tests.recover_latch(generation, at)
                else:
                    self._relay_tests.arm_latch(safety.get("fault_session_id"), at, "off_sweep_failed")
            except Exception:
                self._relay_test_latch_local = True
            return True
        if session is None:
            return False
        self._relay_test_session_id = session["id"]
        status = session["status"]
        if status == "starting":
            results = self._sweep_off(at)
            try:
                if all(results.values()): self._relay_tests.activate(session["id"], self._runner_id, at)
                else: self._relay_tests.end(session["id"], at, failed=True, reason="off_sweep_failed")
            except Exception:
                self._relay_test_latch_local = True
            return True
        if status == "active":
            for output in view["heaters"]:
                if output["confirmed_seq"] == output["command_seq"]:
                    continue
                try:
                    if not self._relay_tests.controller_can_switch(session["id"], self._runner_id, at):
                        self._relay_tests.unknown(session["id"], output["heater_id"], output["command_seq"], at, "session_invalid")
                        self._relay_tests.request_controller_end(session["id"], at, "configuration_changed")
                        return True
                except Exception:
                    self._sweep_off(at)
                    self._relay_test_latch_local = True
                    return True
                try:
                    self._driver.set_state(output["heater_id"], bool(output["desired_state"]), at)
                    if output["desired_state"]: self._active.add(output["heater_id"])
                    else: self._active.discard(output["heater_id"])
                    self._relay_tests.confirm(session["id"], output["heater_id"], output["command_seq"], bool(output["desired_state"]), at)
                except Exception:
                    logger.exception("Relay-test output %s could not be confirmed", output["heater_id"])
                    try:
                        self._relay_tests.unknown(session["id"], output["heater_id"], output["command_seq"], at)
                        if not bool(output["desired_state"]):
                            self._relay_tests.arm_latch(session["id"], at, "driver_failed")
                    except Exception:
                        self._relay_test_latch_local = True
            return True
        if status == "ending":
            results = self._sweep_off(at)
            try:
                self._relay_tests.end(session["id"], at, failed=not all(results.values()), reason="owner_finished" if all(results.values()) else "off_sweep_failed")
            except Exception:
                self._relay_test_latch_local = True
            return True
        return status in ("ended", "failed")

    def _sweep_off(self, at: datetime) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for heater_id in self._heater_ids:
            try:
                self._driver.set_state(heater_id, False, at)
                results[heater_id] = True
            except Exception:
                logger.exception("Failed to force output %s OFF", heater_id)
                results[heater_id] = False
        self._active.clear()
        return results

    def shutdown(self, at: datetime) -> None:
        logger.info("Shutting down controller outputs")
        results = self._sweep_off(at)
        if not all(results.values()):
            self._latch_partial_off(at, "off_sweep_failed")
        try:
            self._driver.close()
        except Exception:
            logger.exception("Failed to close output driver")
        self._active.clear()

    def _latch_partial_off(self, at: datetime, reason: str) -> None:
        """Make an incomplete safety sweep durable, while retaining a local guard.

        The store may be unavailable precisely when shutdown happens.  The
        in-memory latch covers that process; a successful write makes recovery
        mandatory after its restart.  This helper intentionally does no GPIO.
        """
        self._relay_test_latch_local = True
        if self._relay_tests is None:
            return
        try:
            self._relay_tests.arm_latch(self._relay_test_session_id, at, reason)
        except Exception:
            logger.exception("Could not persist relay-test safety latch after partial OFF")
            return
        self._relay_test_latch_local = False

    def _desired_outputs(self, plan: ScheduleResult | None, at: datetime) -> set[str]:
        if plan is None:
            return set()
        for slot in plan.slots:
            if slot.start <= at < slot.end:
                requested = set(slot.heater_ids)
                unknown = requested - self._heater_id_set
                if unknown:
                    logger.error("Ignoring unknown heater ids in active plan: %s", sorted(unknown))
                return requested & self._heater_id_set
        return set()
