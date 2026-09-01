"""Persistent controller runtime with plan refresh, recovery and audit.

Failure policy, straight from constitution principle IV and
``contracts/repository.md``:

* ``ConfigStoreUnavailableError`` is the **only** error treated as transient. The
  running plan is retained and the refresh is retried on the configured cadence.
  The process never ends.
* Every other configuration error is terminal for the refresh: it is logged once
  as critical, refreshing stops, and the already-persisted plan keeps running
  until its window closes, after which every output is off. A human has to fix
  the configuration; the service will not guess.
* Entering and leaving the degraded state is logged **once per transition**,
  never once per loop iteration.
* History writes can never break any of this: the recorder swallows its own
  failures by contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import time
from typing import Callable

from .controller import ChargeController
from .persistence import (
    ActivePlanRepository,
    ConfigStoreError,
    ConfigStoreUnavailableError,
    ForecastRef,
    HeartbeatPublisher,
    HistoryRecorder,
    PlanRef,
)
from .scheduler import ScheduleResult


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanRefresh:
    plan: ScheduleResult
    next_refresh_seconds: int
    plan_ref: PlanRef | None = None
    installation_revision: int = 0
    forecast_ref: ForecastRef | None = None


class ControllerService:
    def __init__(
        self,
        controller: ChargeController,
        store: ActivePlanRepository,
        refresh_plan: Callable[[datetime], PlanRefresh],
        poll_seconds: float,
        error_retry_seconds: int,
        clock: Callable[[], datetime] | None = None,
        wait: Callable[[float], None] = time.sleep,
        history: HistoryRecorder | None = None,
        retention_days: int | None = None,
        heartbeat: HeartbeatPublisher | None = None,
    ) -> None:
        self._controller = controller
        self._store = store
        self._refresh_plan = refresh_plan
        self._poll_seconds = poll_seconds
        self._error_retry_seconds = error_retry_seconds
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._wait = wait
        self._history = history
        self._retention_days = retention_days
        self._heartbeat = heartbeat
        self._current_plan_ref: PlanRef | None = None
        self._degraded = False
        self._refresh_abandoned = False
        self._warned_planless = False

    def run(self, max_cycles: int | None = None) -> int:
        now = self._clock()
        try:
            self._controller.initialize(now)
            try:
                plan = self._store.load()
            except ConfigStoreUnavailableError as exc:
                self._enter_degraded(exc)
                plan = None
            next_refresh = now
            cycles = 0
            while max_cycles is None or cycles < max_cycles:
                now = self._clock()
                if now >= next_refresh and not self._refresh_abandoned:
                    plan, next_refresh = self._try_refresh(now, plan)
                self._controller.apply(plan, now)
                # Published every iteration, not only on refresh: refreshing can
                # be hours apart, and a dead controller would look alive for all
                # of it. Never raises, by contract.
                self._publish_heartbeat(now)
                cycles += 1
                if max_cycles is None or cycles < max_cycles:
                    self._wait(self._poll_seconds)
        except KeyboardInterrupt:
            logger.info("Controller service interrupted")
        finally:
            self._controller.shutdown(self._clock())
        return 0

    def _try_refresh(
        self, now: datetime, plan: ScheduleResult | None
    ) -> tuple[ScheduleResult | None, datetime]:
        try:
            refreshed = self._refresh_plan(now)
            persisted_ref = self._store.save(
                refreshed.plan,
                installation_revision=refreshed.installation_revision,
                forecast_ref=refreshed.forecast_ref,
            )
        except ConfigStoreUnavailableError as exc:
            self._enter_degraded(exc)
            self._warn_if_planless(plan)
            return plan, now + timedelta(seconds=self._error_retry_seconds)
        except ConfigStoreError as exc:
            # Empty, invalid or unreadable-schema configuration. Not transient:
            # retrying cannot fix it, so stop trying and say so once.
            self._refresh_abandoned = True
            logger.critical(
                "The stored configuration cannot be used, so plan refresh is "
                "abandoned until it is fixed: %s. The persisted plan keeps running "
                "until its window closes, after which every output stays off",
                exc,
            )
            self._warn_if_planless(plan)
            return plan, now + timedelta(seconds=self._error_retry_seconds)
        except Exception:
            logger.exception(
                "Plan refresh failed; retaining persisted plan and retrying in %d "
                "seconds",
                self._error_retry_seconds,
            )
            self._warn_if_planless(plan)
            return plan, now + timedelta(seconds=self._error_retry_seconds)

        self._leave_degraded()
        self._current_plan_ref = persisted_ref or refreshed.plan_ref
        self._prune_history(now)
        return (
            refreshed.plan,
            now + timedelta(seconds=refreshed.next_refresh_seconds),
        )

    def _enter_degraded(self, exc: BaseException) -> None:
        if not self._degraded:
            self._degraded = True
            logger.warning(
                "The configuration database became unreachable; retaining the running "
                "plan and retrying every %d seconds: %s",
                self._error_retry_seconds,
                exc,
            )
        else:
            logger.debug("Configuration database still unreachable: %s", exc)

    def _leave_degraded(self) -> None:
        if self._degraded:
            self._degraded = False
            logger.info(
                "The configuration database is reachable again; recalculating the "
                "plan with the current configuration"
            )

    def _warn_if_planless(self, plan: ScheduleResult | None) -> None:
        if plan is not None:
            self._warned_planless = False
            return
        if not self._warned_planless:
            self._warned_planless = True
            logger.critical("No valid plan is available; all outputs remain off")

    def _publish_heartbeat(self, now: datetime) -> None:
        if self._heartbeat is None:
            return
        self._heartbeat.publish(
            now,
            degraded=self._degraded or self._refresh_abandoned,
            plan_ref=self._current_plan_ref,
        )

    def _prune_history(self, now: datetime) -> None:
        if self._history is None:
            return
        report = self._history.prune(now, self._retention_days)
        if report.total:
            logger.info("Pruned %d history rows", report.total)

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def refresh_abandoned(self) -> bool:
        return self._refresh_abandoned

    @property
    def current_plan_ref(self) -> PlanRef | None:
        return self._current_plan_ref
