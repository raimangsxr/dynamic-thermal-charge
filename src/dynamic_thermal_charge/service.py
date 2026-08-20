"""Persistent controller runtime with plan refresh and recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import Callable

from .controller import ChargeController
from .scheduler import ScheduleResult
from .state import PlanStore


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanRefresh:
    plan: ScheduleResult
    next_refresh_seconds: int


class ControllerService:
    def __init__(
        self,
        controller: ChargeController,
        store: PlanStore,
        refresh_plan: Callable[[datetime], PlanRefresh],
        poll_seconds: float,
        error_retry_seconds: int,
        clock: Callable[[], datetime] | None = None,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        self._controller = controller
        self._store = store
        self._refresh_plan = refresh_plan
        self._poll_seconds = poll_seconds
        self._error_retry_seconds = error_retry_seconds
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._wait = wait

    def run(self, max_cycles: int | None = None) -> int:
        now = self._clock()
        try:
            self._controller.initialize(now)
            plan = self._store.load()
            next_refresh = now
            cycles = 0
            while max_cycles is None or cycles < max_cycles:
                now = self._clock()
                if now >= next_refresh:
                    try:
                        refreshed = self._refresh_plan(now)
                        self._store.save(refreshed.plan)
                        plan = refreshed.plan
                        next_refresh = now + timedelta(
                            seconds=refreshed.next_refresh_seconds
                        )
                    except Exception:
                        logger.exception(
                            "Plan refresh failed; retaining persisted plan and retrying in %d seconds",
                            self._error_retry_seconds,
                        )
                        next_refresh = now + timedelta(seconds=self._error_retry_seconds)
                        if plan is None:
                            logger.critical(
                                "No valid plan is available; all outputs remain off"
                            )
                self._controller.apply(plan, now)
                cycles += 1
                if max_cycles is None or cycles < max_cycles:
                    self._wait(self._poll_seconds)
        except KeyboardInterrupt:
            logger.info("Controller service interrupted")
        finally:
            self._controller.shutdown(self._clock())
        return 0
