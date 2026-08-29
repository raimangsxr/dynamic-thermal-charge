"""The example installation used to seed an empty database.

The seeded installation is strictly idempotent: if any configuration already
exists, nothing is touched (FR-012).

Every value that has physical consequences -- pins, active level, maximum power,
charge window -- is declared explicitly here rather than defaulted, so
``config show`` displays it and the operator can compare it against the
installation (principle III).
"""

from __future__ import annotations

import logging
from datetime import time

from ..models import (
    AemetConfig,
    AppConfig,
    Heater,
    LoggingConfig,
    OutputConfig,
    RuntimeConfig,
    ScheduleConfig,
    SimulatedForecastConfig,
    SiteConfig,
    ThermalProfile,
    WeatherConfig,
    WeatherWatchdogConfig,
)


logger = logging.getLogger(__name__)

SEED_INSTALLATION_NAME = "Instalación de ejemplo"
DEFAULT_STATE_FILE = "/var/lib/dynamic-thermal-charge/active-plan.json"


def example_installation(state_file: str = DEFAULT_STATE_FILE) -> AppConfig:
    """A complete, valid installation to start from."""
    return AppConfig(
        site=SiteConfig(
            max_total_power_w=5200,
            slot_minutes=30,
            window_minutes=480,
        ),
        heaters=(
            Heater(
                id="salon",
                name="Salón",
                model="ADS-2812",
                power_w=2800,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=90,
                thermal=ThermalProfile(
                    target_temperature_c=21.0,
                    design_outdoor_temperature_c=-2.0,
                    thermal_factor=1.0,
                    min_charge=0.10,
                    max_charge=1.0,
                ),
                output=OutputConfig(kind="gpio", pin=17, active_high=False),
            ),
            Heater(
                id="entrada",
                name="Entrada",
                model="ADS-2412",
                power_w=2400,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=50,
                thermal=ThermalProfile(
                    target_temperature_c=18.0,
                    design_outdoor_temperature_c=0.0,
                    thermal_factor=0.70,
                    min_charge=0.0,
                    max_charge=0.80,
                ),
                output=OutputConfig(kind="gpio", pin=18, active_high=False),
            ),
            Heater(
                id="habitaciones",
                name="Habitaciones",
                model="ADS-2412",
                power_w=2400,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=100,
                thermal=ThermalProfile(
                    target_temperature_c=20.5,
                    design_outdoor_temperature_c=-2.0,
                    thermal_factor=1.05,
                    min_charge=0.10,
                    max_charge=1.0,
                ),
                output=OutputConfig(kind="gpio", pin=22, active_high=False),
            ),
            Heater(
                id="buhardilla",
                name="Buhardilla",
                model="ADS-2412",
                power_w=2400,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=40,
                thermal=ThermalProfile(
                    target_temperature_c=17.0,
                    design_outdoor_temperature_c=-2.0,
                    thermal_factor=0.65,
                    min_charge=0.0,
                    max_charge=0.75,
                ),
                output=OutputConfig(kind="gpio", pin=23, active_high=False),
            ),
        ),
        logging=LoggingConfig(level="INFO"),
        schedule=ScheduleConfig(
            timezone="Europe/Madrid",
            start_time=time(0, 0),
            end_time=time(8, 0),
            weekdays=(0, 1, 2, 3, 4, 5, 6),
        ),
        weather=WeatherConfig(
            provider="aemet",
            aemet=AemetConfig(
                # Five-digit INE code. Must be replaced with the real one.
                municipality_code="15057",
                api_key_env="AEMET_API_KEY",
                timeout_seconds=10.0,
            ),
            fallback=SimulatedForecastConfig(
                average_temperature_c=8.0,
                minimum_temperature_c=3.0,
            ),
            watchdog=WeatherWatchdogConfig(retry_minutes=15, refresh_minutes=180),
        ),
        runtime=RuntimeConfig(state_file=state_file, poll_seconds=5.0),
    )


__all__ = ["DEFAULT_STATE_FILE", "SEED_INSTALLATION_NAME", "example_installation"]
