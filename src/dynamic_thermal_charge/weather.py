"""Weather provider boundary and deterministic simulated provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .models import WeatherConfig


@dataclass(frozen=True)
class OutdoorForecast:
    date: date
    average_temperature_c: float
    minimum_temperature_c: float
    source: str


class WeatherProvider(Protocol):
    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        """Return the outdoor forecast used to calculate charge demand."""


class SimulatedWeatherProvider:
    def __init__(self, config: WeatherConfig) -> None:
        self._config = config

    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        return OutdoorForecast(
            date=forecast_date,
            average_temperature_c=self._config.average_temperature_c,
            minimum_temperature_c=self._config.minimum_temperature_c,
            source="simulated",
        )
