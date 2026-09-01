"""Translate weather forecasts and room profiles into charge demand."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from .models import Heater, IndoorReading
from .weather import HourlyForecastPoint, OutdoorForecast


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndoorSelection:
    temperatures: dict[str, float]
    fallback_reasons: dict[str, str]


def select_indoor_temperatures(
    heaters: tuple[Heater, ...],
    readings: Mapping[str, IndoorReading],
    *,
    at: datetime,
    max_age_minutes: int,
    min_plausible_c: float,
    max_plausible_c: float,
) -> IndoorSelection:
    """Purely select readings usable at one explicit recalculation instant."""
    if at.tzinfo is None:
        raise ValueError("indoor selection 'at' requires a timezone")
    oldest = at - timedelta(minutes=max_age_minutes)
    temperatures: dict[str, float] = {}
    fallback: dict[str, str] = {}
    for heater in heaters:
        if heater.indoor_topic is None:
            continue
        reading = readings.get(heater.id)
        if reading is None:
            fallback[heater.id] = "missing"
        elif reading.received_at < oldest or reading.received_at > at:
            fallback[heater.id] = "stale"
        elif not min_plausible_c <= reading.celsius <= max_plausible_c:
            fallback[heater.id] = "implausible"
        else:
            temperatures[heater.id] = reading.celsius
    return IndoorSelection(temperatures, fallback)


class ThermalDemandEngine:
    """Calculate a bounded linear charge demand for every enabled heater."""

    def calculate(
        self,
        heaters: tuple[Heater, ...],
        forecast: OutdoorForecast,
        indoor_temperatures: Mapping[str, float] | None = None,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> dict[str, int]:
        outdoor_temperature = _window_average(
            forecast.hourly_points, window_start, window_end
        )
        if outdoor_temperature is None:
            outdoor_temperature = forecast.average_temperature_c
        logger.info(
            "Calculating thermal demand from %s forecast: average=%.1f C, minimum=%.1f C, maximum=%.1f C",
            forecast.source,
            forecast.average_temperature_c,
            forecast.minimum_temperature_c,
            forecast.maximum_temperature_c,
        )
        demands: dict[str, int] = {}
        for heater in heaters:
            if not heater.enabled:
                continue
            if heater.thermal is None:
                demands[heater.id] = heater.requested_charge_minutes
                logger.debug(
                    "Heater %s uses configured charge target %.3f",
                    heater.id,
                    heater.target_charge,
                )
                continue

            profile = heater.thermal
            temperature_range = (
                profile.target_temperature_c
                - profile.design_outdoor_temperature_c
            )
            source_temperature = (
                outdoor_temperature
                if indoor_temperatures is None or heater.id not in indoor_temperatures
                else indoor_temperatures[heater.id]
            )
            # A room at or above target deliberately produces zero/negative raw
            # demand; the configured min_charge then preserves the thermal reserve.
            raw_charge = (
                profile.target_temperature_c - source_temperature
            ) / temperature_range
            adjusted_charge = raw_charge * profile.thermal_factor
            charge_fraction = min(
                profile.max_charge,
                max(profile.min_charge, adjusted_charge),
            )
            demands[heater.id] = round(
                heater.full_charge_minutes
                * (charge_fraction + heater.reserve_percent / 100)
            )
            logger.debug(
                "Heater %s thermal demand: raw=%.3f adjusted=%.3f bounded=%.3f minutes=%d",
                heater.id,
                raw_charge,
                adjusted_charge,
                charge_fraction,
                demands[heater.id],
            )

        logger.info("Thermal charge demand calculated (minutes): %s", demands)
        return demands


def _window_average(
    points: Sequence[HourlyForecastPoint],
    window_start: datetime | None,
    window_end: datetime | None,
) -> float | None:
    """Return the mean of detailed points intersecting a planning window."""
    if not points:
        return None
    if window_start is None or window_end is None:
        usable = points
    else:
        usable = tuple(
            point
            for point in points
            if window_start <= point.timestamp < window_end
        )
    if not usable:
        return None
    return sum(point.temperature_c for point in usable) / len(usable)
