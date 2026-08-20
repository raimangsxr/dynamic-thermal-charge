"""Command-line entry point for planning a simulated charge window."""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
from pathlib import Path
import signal
import time
from typing import Callable
from zoneinfo import ZoneInfo

from .config import load_config
from .controller import ChargeController
from .drivers import SimulatedOutputDriver
from .logging_config import configure_logging
from .models import AppConfig
from .scheduler import ChargeScheduler, ScheduleResult
from .service import ControllerService, PlanRefresh
from .state import PlanStore
from .thermal import ThermalDemandEngine
from .watchdog import ForecastWatchdog
from .weather import (
    OutdoorForecast,
    WeatherProvider,
    WeatherProviderError,
    build_weather_provider,
)


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
    persistent_mode = parser.add_mutually_exclusive_group()
    persistent_mode.add_argument(
        "--watch-weather",
        action="store_true",
        help="keep refreshing weather and retry the primary provider after failures",
    )
    persistent_mode.add_argument(
        "--run-controller",
        action="store_true",
        help="run the persistent controller with simulated outputs",
    )
    persistent_mode.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without fetching weather or building a plan",
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
        if args.check_config:
            logger.info("Configuration validation succeeded")
            return 0
        provider = (
            build_weather_provider(config.weather)
            if config.weather is not None
            else None
        )
        if args.watch_weather:
            if config.weather is None or provider is None:
                raise ValueError("--watch-weather requires weather configuration")
            if config.weather.provider == "aemet" and config.weather.fallback is None:
                raise ValueError("--watch-weather requires weather fallback values")
            return _run_watchdog(config, args.start, provider)
        if args.run_controller:
            if args.start is not None:
                raise ValueError("--run-controller does not accept --start")
            if config.weather is None or provider is None:
                raise ValueError("--run-controller requires weather configuration")
            return _run_controller(config, provider)

        start = _select_start(config, args.start)
        forecast = provider.forecast_for(start.date()) if provider is not None else None
        result = _build_plan(config, start, forecast)
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    except WeatherProviderError as exc:
        raise SystemExit(f"Weather error: {exc}") from exc

    _print_plan(config, result)
    return 2 if result.unmet_minutes else 0


def _select_start(config: AppConfig, explicit_start: datetime | None) -> datetime:
    if explicit_start is not None:
        if explicit_start.tzinfo is None and config.schedule is not None:
            return explicit_start.replace(tzinfo=ZoneInfo(config.schedule.timezone))
        return explicit_start
    if config.schedule is not None:
        start = config.schedule.next_start(datetime.now().astimezone())
        logger.info(
            "Selected next configured charge window at %s",
            start.isoformat(timespec="minutes"),
        )
        return start
    return datetime.now().replace(second=0, microsecond=0)


def _build_plan(
    config: AppConfig,
    start: datetime,
    forecast: OutdoorForecast | None,
) -> ScheduleResult:
    requested_charge_minutes = None
    if forecast is not None:
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
    return ChargeScheduler().build(
        config.site,
        config.heaters,
        start,
        requested_charge_minutes=requested_charge_minutes,
    )


def _run_watchdog(
    config: AppConfig,
    explicit_start: datetime | None,
    provider: WeatherProvider,
    wait: Callable[[float], None] = time.sleep,
) -> int:
    assert config.weather is not None
    watchdog = ForecastWatchdog(
        provider,
        expected_source=config.weather.provider,
        config=config.weather.watchdog,
    )
    try:
        while True:
            start = _select_start(config, explicit_start)
            cycle = watchdog.poll(start.date())
            result = _build_plan(config, start, cycle.forecast)
            _print_plan(config, result)
            wait(cycle.next_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Weather watchdog stopped")
        return 0


def _run_controller(config: AppConfig, provider: WeatherProvider) -> int:
    assert config.weather is not None
    logger.warning("Controller is running with simulated outputs only")
    driver = SimulatedOutputDriver()
    controller = ChargeController(
        tuple(heater.id for heater in config.heaters if heater.enabled),
        driver,
    )
    watchdog = ForecastWatchdog(
        provider,
        expected_source=config.weather.provider,
        config=config.weather.watchdog,
    )

    def refresh_plan(now: datetime) -> PlanRefresh:
        start = (
            config.schedule.active_or_next_start(now)
            if config.schedule is not None
            else now
        )
        cycle = watchdog.poll(start.date())
        plan = _build_plan(config, start, cycle.forecast)
        return PlanRefresh(plan=plan, next_refresh_seconds=cycle.next_poll_seconds)

    service = ControllerService(
        controller=controller,
        store=PlanStore(config.runtime.state_file),
        refresh_plan=refresh_plan,
        poll_seconds=config.runtime.poll_seconds,
        error_retry_seconds=config.weather.watchdog.retry_minutes * 60,
    )
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_termination_signal)
    try:
        return service.run()
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)


def _handle_termination_signal(_signum, _frame) -> None:
    logger.info("Termination signal received")
    raise KeyboardInterrupt


def _print_plan(config: AppConfig, result: ScheduleResult) -> None:
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
