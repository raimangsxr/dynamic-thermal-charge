"""Command-line entry point for planning a simulated charge window."""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .logging_config import configure_logging
from .scheduler import ChargeScheduler
from .thermal import ThermalDemandEngine
from .weather import WeatherProviderError, build_weather_provider


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan storage-heater charging")
    parser.add_argument("config", type=Path, help="YAML installation configuration")
    parser.add_argument(
        "--start",
        type=datetime.fromisoformat,
        default=None,
        help="override the configured window start using ISO format",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="override the YAML log level",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
        configure_logging(args.log_level or config.logging.level)
        logger.info(
            "Loaded configuration %s with %d heaters",
            args.config,
            len(config.heaters),
        )
        if args.start is not None:
            start = args.start
            if start.tzinfo is None and config.schedule is not None:
                start = start.replace(tzinfo=ZoneInfo(config.schedule.timezone))
        elif config.schedule is not None:
            start = config.schedule.next_start(datetime.now().astimezone())
            logger.info(
                "Selected next configured charge window at %s",
                start.isoformat(timespec="minutes"),
            )
        else:
            start = datetime.now().replace(second=0, microsecond=0)
        requested_charge_minutes = None
        if config.weather is not None:
            forecast = build_weather_provider(config.weather).forecast_for(start.date())
            logger.info(
                "Weather forecast: date=%s source=%s location=%s min=%.1f C avg=%.1f C max=%.1f C",
                forecast.date.isoformat(),
                forecast.source,
                forecast.location or "n/a",
                forecast.minimum_temperature_c,
                forecast.average_temperature_c,
                forecast.maximum_temperature_c,
            )
            requested_charge_minutes = ThermalDemandEngine().calculate(
                config.heaters,
                forecast,
            )
        result = ChargeScheduler().build(
            config.site,
            config.heaters,
            start,
            requested_charge_minutes=requested_charge_minutes,
        )
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except WeatherProviderError as exc:
        raise SystemExit(f"Weather error: {exc}") from exc

    print("Charge plan")
    for slot in result.slots:
        active = ", ".join(slot.heater_ids) or "—"
        print(
            f"{slot.start:%Y-%m-%d %H:%M}–{slot.end:%H:%M}  "
            f"{slot.total_power_w / 1000:.1f} kW  {active}"
        )
    print("\nAllocated:")
    for heater in config.heaters:
        if heater.enabled:
            minutes = result.allocated_minutes[heater.id]
            print(f"- {heater.name}: {minutes / 60:g} h")
    if result.unmet_minutes:
        print("\nUnmet demand:")
        for heater_id, minutes in result.unmet_minutes.items():
            print(f"- {heater_id}: {minutes / 60:g} h")
        return 2
    return 0
