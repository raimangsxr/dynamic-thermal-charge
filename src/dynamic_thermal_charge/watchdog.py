"""Persistent weather refresh and retry policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

from .models import WeatherWatchdogConfig
from .weather import OutdoorForecast, WeatherProvider


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
