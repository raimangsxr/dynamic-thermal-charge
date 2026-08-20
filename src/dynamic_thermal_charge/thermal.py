"""Translate weather forecasts and room profiles into charge demand."""

from __future__ import annotations

import logging

from .models import Heater
from .weather import OutdoorForecast


logger = logging.getLogger(__name__)


class ThermalDemandEngine:
    """Calculate a bounded linear charge demand for every enabled heater."""

    def calculate(
        self,
        heaters: tuple[Heater, ...],
        forecast: OutdoorForecast,
    ) -> dict[str, int]:
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
            raw_charge = (
                profile.target_temperature_c - forecast.average_temperature_c
            ) / temperature_range
            adjusted_charge = raw_charge * profile.thermal_factor
            charge_fraction = min(
                profile.max_charge,
                max(profile.min_charge, adjusted_charge),
            )
            demands[heater.id] = round(
                heater.full_charge_minutes * charge_fraction
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
