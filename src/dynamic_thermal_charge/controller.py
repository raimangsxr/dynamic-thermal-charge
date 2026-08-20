"""Fail-safe execution of a charge plan through an output driver."""

from __future__ import annotations

from datetime import datetime
import logging

from .drivers import OutputDriver
from .scheduler import ScheduleResult


logger = logging.getLogger(__name__)


class ChargeController:
    def __init__(self, heater_ids: tuple[str, ...], driver: OutputDriver) -> None:
        self._heater_ids = heater_ids
        self._heater_id_set = set(heater_ids)
        self._driver = driver
        self._active: set[str] = set()

    def initialize(self, at: datetime) -> None:
        logger.info("Initializing controller with all outputs off")
        for heater_id in self._heater_ids:
            self._driver.set_state(heater_id, False, at)
        self._active.clear()

    def apply(self, plan: ScheduleResult | None, at: datetime) -> None:
        desired = self._desired_outputs(plan, at)
        for heater_id in sorted(self._active - desired):
            self._driver.set_state(heater_id, False, at)
        for heater_id in sorted(desired - self._active):
            self._driver.set_state(heater_id, True, at)
        if desired != self._active:
            logger.info("Controller outputs at %s: %s", at.isoformat(), sorted(desired))
        self._active = desired

    def shutdown(self, at: datetime) -> None:
        logger.info("Shutting down controller outputs")
        for heater_id in self._heater_ids:
            try:
                self._driver.set_state(heater_id, False, at)
            except Exception:
                logger.exception("Failed to force output %s OFF", heater_id)
        try:
            self._driver.close()
        except Exception:
            logger.exception("Failed to close output driver")
        self._active.clear()

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
