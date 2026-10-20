"""Persistent weather refresh and retry policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
import logging
from typing import Callable

from .models import WeatherWatchdogConfig
from .weather import DailyAemetCycle, ForecastCycleState, OutdoorForecast, WeatherProvider, WeatherProviderError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchdogCycle:
    forecast: OutdoorForecast
    degraded: bool
    next_poll_seconds: int


class ForecastWatchdog:
    def __init__(
        self,
        provider: WeatherProvider,
        expected_source: str,
        config: WeatherWatchdogConfig,
    ) -> None:
        self._provider = provider
        self._expected_source = expected_source
        self._config = config
        self._was_degraded = False

    def poll(self, forecast_date: date) -> WatchdogCycle:
        forecast = self._provider.forecast_for(forecast_date)
        degraded = forecast.source != self._expected_source
        if degraded and not self._was_degraded:
            logger.warning(
                "Weather watchdog entered degraded mode; retrying in %d minutes",
                self._config.retry_minutes,
            )
        elif not degraded and self._was_degraded:
            logger.info("Weather watchdog recovered primary forecast provider")

        self._was_degraded = degraded
        delay_seconds = (
            self._config.retry_minutes * 60
            if degraded
            else self._config.refresh_hours * 60 * 60
        )
        logger.info(
            "Weather watchdog next poll in %d seconds (degraded=%s)",
            delay_seconds,
            degraded,
        )
        return WatchdogCycle(
            forecast=forecast,
            degraded=degraded,
            next_poll_seconds=delay_seconds,
        )


@dataclass(frozen=True)
class DailyForecastResult:
    forecast: OutdoorForecast | None
    state: ForecastCycleState
    next_poll_seconds: int


class DailyAemetForecastManager:
    """AEMET-specific retrieval with durable refresh and retry semantics.

    A failed cycle returns the last real forecast marked stale by the caller;
    it never asks a simulated provider to replace it.
    """

    def __init__(
        self,
        provider: WeatherProvider,
        *,
        query_hour: int = 12,
        timezone_name: str = "UTC",
        retry_minutes: int = 60,
        refresh_hours: int = 4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        if (
            isinstance(refresh_hours, bool)
            or not isinstance(refresh_hours, int)
            or refresh_hours <= 0
        ):
            raise ValueError("refresh_hours must be a positive integer")
        self._cycle = DailyAemetCycle(
            query_hour,
            timezone_name,
            retry_minutes=retry_minutes,
            refresh_hours=refresh_hours,
        )
        self._clock = clock
        self._last_valid: OutdoorForecast | None = None

    def poll(self, now: datetime, state: ForecastCycleState | None = None) -> DailyForecastResult:
        local_date = now.astimezone(self._cycle.timezone).date()
        current = state or self._cycle.initial_state(local_date)
        if current.local_date != local_date:
            # A failed cycle must not wait for the next configured query hour
            # after midnight.  Start the new local-day record immediately,
            # carrying the retry episode forward until the provider succeeds.
            previous_failed = current.stale and current.last_result == "error"
            previous_success = current.last_result == "success"
            initial = self._cycle.initial_state(local_date)
            carry_refresh = (
                previous_success
                and current.next_run_at is not None
            )
            inherited_success = previous_success and carry_refresh
            current = replace(
                initial,
                attempt=current.attempt if previous_failed else 0,
                next_retry_at=(
                    current.next_retry_at if previous_failed else None
                ),
                last_error=current.last_error if previous_failed else None,
                stale=previous_failed,
                completed=inherited_success,
                last_attempt_at=(
                    current.last_attempt_at
                    if previous_failed or inherited_success
                    else None
                ),
                last_result=(
                    current.last_result
                    if previous_failed or inherited_success
                    else None
                ),
                last_forecast_id=(
                    current.last_forecast_id
                    if previous_failed or inherited_success
                    else None
                ),
                next_run_at=current.next_run_at if carry_refresh else None,
            )
        logger.debug(
            "Daily AEMET forecast poll: local_date=%s attempt=%d due=%s",
            local_date.isoformat(),
            current.attempt,
            self._cycle.due(current, now),
        )
        if not self._cycle.due(current, now):
            return DailyForecastResult(self._last_valid, current, _seconds_until(current, now))
        try:
            forecast = self._provider.forecast_for(local_date)
            if forecast.source != "aemet":
                raise WeatherProviderError(
                    f"unexpected forecast source: {forecast.source}"
                )
        except Exception as exc:
            completed_at = now if self._clock is None else self._clock()
            updated = replace(
                self._cycle.failure(current, completed_at, str(exc)),
                last_attempt_at=completed_at.astimezone(timezone.utc),
                last_result="error",
                next_run_at=None,
            )
            return DailyForecastResult(self._last_valid, updated, _seconds_until(updated, now))
        self._last_valid = forecast
        completed_at = now if self._clock is None else self._clock()
        updated = replace(
            self._cycle.success(current, completed_at),
            last_attempt_at=completed_at.astimezone(timezone.utc),
            last_result="success",
        )
        return DailyForecastResult(forecast, updated, _seconds_until(updated, now))


def _seconds_until(state: ForecastCycleState, now: datetime) -> int:
    target = state.next_retry_at or state.next_run_at
    if target is None and not state.completed:
        target = state.scheduled_at
    if target is None:
        return 24 * 60 * 60
    return max(1, round((target - now.astimezone(timezone.utc)).total_seconds()))
