"""Persistent weather refresh and retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging

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
        delay_minutes = (
            self._config.retry_minutes if degraded else self._config.refresh_minutes
        )
        logger.info(
            "Weather watchdog next poll in %d minutes (degraded=%s)",
            delay_minutes,
            degraded,
        )
        return WatchdogCycle(
            forecast=forecast,
            degraded=degraded,
            next_poll_seconds=delay_minutes * 60,
        )


@dataclass(frozen=True)
class DailyForecastResult:
    forecast: OutdoorForecast | None
    state: ForecastCycleState
    next_poll_seconds: int


class DailyAemetForecastManager:
    """AEMET-specific daily retrieval with durable five-retry semantics.

    A failed cycle returns the last real forecast marked stale by the caller;
    it never asks a simulated provider to replace it.
    """

    def __init__(self, provider: WeatherProvider, *, query_hour: int = 12, timezone_name: str = "UTC") -> None:
        self._provider = provider
        self._cycle = DailyAemetCycle(query_hour, timezone_name)
        self._last_valid: OutdoorForecast | None = None

    def poll(self, now: datetime, state: ForecastCycleState | None = None) -> DailyForecastResult:
        local_date = now.astimezone(self._cycle.timezone).date()
        current = state or self._cycle.initial_state(local_date)
        if not self._cycle.due(current, now):
            return DailyForecastResult(self._last_valid, current, _seconds_until(current, now))
        try:
            forecast = self._provider.forecast_for(local_date)
        except WeatherProviderError as exc:
            updated = self._cycle.failure(current, now, str(exc))
            return DailyForecastResult(self._last_valid, updated, _seconds_until(updated, now))
        self._last_valid = forecast
        updated = self._cycle.success(current)
        return DailyForecastResult(forecast, updated, 24 * 60 * 60)


def _seconds_until(state: ForecastCycleState, now: datetime) -> int:
    if state.next_retry_at is None:
        return 24 * 60 * 60
    return max(1, round((state.next_retry_at - now.astimezone(timezone.utc)).total_seconds()))
