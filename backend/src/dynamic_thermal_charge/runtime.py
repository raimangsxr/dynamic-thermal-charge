"""Runtime composition for the controller and forecast services.

This module contains process behavior, not a user-facing command interface.
Each public entrypoint is called by the deployment directly.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import logging
import signal
import time
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from .controller import ChargeController
from .drivers import OutputDriver, RecordingOutputDriver, SimulatedOutputDriver
from .gpio_driver import GpioOutputDriver
from .charge_planning import DeterministicChargeOptimizer, PlanningInput
from .models import AppConfig, ChargeTelemetry
from .persistence import ConfigStoreError, PlanRef
from .scheduler import ChargeScheduler, ScheduleResult, ScheduleSlot
from .service import ControllerService, PlanRefresh
from .state import PlanStore
from .thermal import ThermalDemandEngine, select_indoor_temperatures
from .watchdog import ForecastWatchdog
from .weather import OutdoorForecast, WeatherProvider

logger = logging.getLogger(__name__)

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
    indoor_temperatures: dict[str, float] | None = None,
) -> ScheduleResult:
    requested_charge_minutes = None
    if forecast is not None:
        logger.info(
            "Weather forecast: date=%s source=%s location=%s min=%.1f C avg=%.1f C "
            "max=%.1f C",
            forecast.date.isoformat(),
            "fallback" if forecast.from_fallback else forecast.source,
            forecast.location or "n/a",
            forecast.minimum_temperature_c,
            forecast.average_temperature_c,
            forecast.maximum_temperature_c,
        )
        requested_charge_minutes = ThermalDemandEngine().calculate(
            config.heaters,
            forecast,
            indoor_temperatures=indoor_temperatures,
            window_start=start,
            window_end=start + timedelta(minutes=config.site.window_minutes),
        )
    return ChargeScheduler().build(
        config.site,
        config.heaters,
        start,
        requested_charge_minutes=requested_charge_minutes,
        hourly_points=None if forecast is None else forecast.hourly_points,
        fallback_temperature_c=(
            None if forecast is None else forecast.average_temperature_c
        ),
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


def _run_controller(
    store,
    config: AppConfig,
    revision: int,
    provider: WeatherProvider,
    driver_name: str = "simulated",
    system=None,
) -> int:
    from .persistence.heartbeat import SqlHeartbeatPublisher
    from .persistence.history import SqlHistoryRecorder
    from .persistence.controller_log import ControllerLogHandler

    assert config.weather is not None
    if store.context is not None:
        store.context.publish_process_revision("controller")
    installation_id = store.repository.installation_id()
    application_engine = store.application_engine or store.engine
    history = SqlHistoryRecorder(application_engine, installation_id, store.location)
    max_events = 1000 if system is None else system.logging.max_events
    web_log_handler = ControllerLogHandler(
        application_engine, installation_id, store.location, max_events=max_events
    )
    logging.getLogger().addHandler(web_log_handler)
    # The controller's proof of life, so a separate API can tell "now" from
    # "the last thing anyone knew". Publishing it can never stop the loop.
    heartbeat = SqlHeartbeatPublisher(
        application_engine,
        installation_id,
        poll_seconds=(config.runtime.poll_seconds if system is None else system.operations.controller_poll_seconds),
        driver_kind=driver_name,
        location=store.location,
    )
    current_plan_ref: list[PlanRef | None] = [None]
    indoor_fallback = _IndoorFallbackTracker()
    driver: OutputDriver | None = None
    with _controlled_termination():
        try:
            driver = RecordingOutputDriver(
                _build_output_driver(config, driver_name),
                history,
                plan_ref=lambda: current_plan_ref[0],
            )
            controller = ChargeController(
                tuple(heater.id for heater in config.heaters if heater.enabled),
                driver,
                relay_tests=store.relay_tests,
                runner_id=heartbeat.runner_id,
            )
            watchdog = ForecastWatchdog(
                provider,
                expected_source=config.weather.provider,
                config=config.weather.watchdog,
            )

            def refresh_plan(now: datetime) -> PlanRefresh:
                # Re-read the configuration each refresh so an edit takes effect
                # on the next recalculation, never mid-plan (FR-039).
                live_config, live_revision = store.repository.current()
                planning_site = store.planning.site()
                automatic_constraints = store.planning.constraints()
                if automatic_constraints or store.planning.active_plan() is not None:
                    automatic = _build_automatic_runtime_plan(
                        store, live_config, now, automatic_constraints, planning_site
                    )
                    if automatic is not None:
                        store.planning.save_plan(
                            automatic[0],
                            configuration_revision=live_revision,
                            constraints_revision=planning_site["revision"],
                            reason="periodic",
                            active=True,
                        )
                        return PlanRefresh(
                            plan=automatic[1],
                            next_refresh_seconds=planning_site["replan_minutes"] * 60,
                            plan_ref=None,
                        )
                start = (
                    live_config.schedule.active_or_next_start(now)
                    if live_config.schedule is not None
                    else now
                )
                cycle = watchdog.poll(start.date())
                indoor_temperatures = indoor_fallback.select(
                    live_config, store.indoor_readings, now
                )
                plan = _build_plan(
                    live_config,
                    start,
                    cycle.forecast,
                    indoor_temperatures=indoor_temperatures,
                )
                forecast_ref = history.record_forecast(cycle.forecast)
                current_plan_ref[0] = history.record_plan(
                    plan, forecast_ref, live_revision
                )
                if store.context is not None:
                    # The fallback snapshot is refreshed only after the plan
                    # and its source forecast have been accepted by canonical
                    # storage.
                    from .persistence.context import _json_ready
                    store.context.refresh_fallback(plan=_json_ready(plan))
                return PlanRefresh(
                    plan=plan,
                    next_refresh_seconds=cycle.next_poll_seconds,
                    plan_ref=current_plan_ref[0],
                )

            service = ControllerService(
                controller=controller,
                store=PlanStore(config.runtime.state_file),
                refresh_plan=refresh_plan,
                poll_seconds=(config.runtime.poll_seconds if system is None else system.operations.controller_poll_seconds),
                error_retry_seconds=config.weather.watchdog.retry_minutes * 60,
                history=history,
                retention_days=(config.retention_days if system is None else system.operations.retention_days),
                heartbeat=heartbeat,
            )
            return service.run()
        finally:
            logging.getLogger().removeHandler(web_log_handler)
            web_log_handler.close()
            if driver is not None:
                driver.close()


def _build_automatic_runtime_plan(
    store, config: AppConfig, now: datetime, constraints, planning_site: dict[str, int]
):
    """Build the controller-facing schedule from the automatic plan value."""
    telemetry = store.planning.telemetry()
    valid: dict[str, ChargeTelemetry] = {}
    for heater_id, value in telemetry.items():
        stamps = (value.temperature_received_at, value.target_received_at, value.stored_charge_received_at)
        if all(item is not None and (now - item).total_seconds() <= 900 for item in stamps):
            valid[heater_id] = value
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    request = PlanningInput(
        heaters=config.heaters,
        telemetry=valid,
        constraints=constraints,
        forecast=store.planning.latest_forecast(),
        horizon_start=now,
        horizon_hours=planning_site["forecast_horizon_hours"],
        slot_minutes=config.site.slot_minutes,
        max_total_power_w=config.site.max_total_power_w,
        timezone_name=timezone_name,
    )
    plan = DeterministicChargeOptimizer().build(request)
    legacy_slots = tuple(
        ScheduleSlot(slot.start, slot.end, slot.heater_ids, slot.power_w, slot.outdoor_temperature_c, False)
        for slot in plan.slots
    )
    allocated = {heater.id: sum(config.site.slot_minutes for slot in plan.slots if heater.id in slot.heater_ids) for heater in config.heaters}
    unmet = {item.heater_id: round(item.deficit_percent * config.heaters[[h.id for h in config.heaters].index(item.heater_id)].full_charge_minutes / 100) for item in plan.deficits if item.deficit_percent > 0}
    return plan, ScheduleResult(legacy_slots, allocated, unmet)


class _IndoorFallbackTracker:
    """Read once per plan and log only fallback state transitions."""

    def __init__(self) -> None:
        self._fallback: set[str] = set()
        self._store_unavailable = False

    def select(self, config: AppConfig, repository, at: datetime) -> dict[str, float]:
        try:
            readings = repository.read_all()
        except ConfigStoreError as exc:
            readings = {}
            if not self._store_unavailable:
                logger.error(
                    "Indoor reading store unavailable; using thermal fallback: %s",
                    exc,
                )
            self._store_unavailable = True
        else:
            if self._store_unavailable:
                logger.info("Indoor reading store recovered")
            self._store_unavailable = False

        selection = select_indoor_temperatures(
            config.heaters,
            readings,
            at=at,
            max_age_minutes=config.site.indoor_max_age_minutes,
            min_plausible_c=config.site.indoor_min_plausible_c,
            max_plausible_c=config.site.indoor_max_plausible_c,
        )
        current = set(selection.fallback_reasons)
        for heater_id in sorted(current - self._fallback):
            logger.warning(
                "Heater %s is using thermal fallback: %s",
                heater_id,
                selection.fallback_reasons[heater_id],
            )
        for heater_id in sorted(self._fallback - current):
            logger.info("Heater %s recovered indoor temperature", heater_id)
        self._fallback = current
        return selection.temperatures


def _build_output_driver(config: AppConfig, driver_name: str) -> OutputDriver:
    if driver_name == "simulated":
        logger.warning("Controller is running with simulated outputs only")
        return SimulatedOutputDriver()
    if driver_name == "gpio":
        logger.warning("Controller is running with REAL GPIO outputs")
        return GpioOutputDriver(
            {heater.id: heater.output for heater in config.heaters if heater.enabled}
        )
    raise ValueError(f"unsupported output driver: {driver_name}")


# ------------------------------------------------------------------------ api

def _run_output_self_test(
    config: AppConfig,
    driver: OutputDriver,
    duration_seconds: float,
    wait: Callable[[float], None] = time.sleep,
) -> int:
    enabled_heaters = tuple(heater for heater in config.heaters if heater.enabled)
    now = datetime.now().astimezone()
    try:
        for heater in enabled_heaters:
            driver.set_state(heater.id, False, now)
        for heater in enabled_heaters:
            logger.warning(
                "GPIO self-test activating %s for %.2f seconds",
                heater.id,
                duration_seconds,
            )
            driver.set_state(heater.id, True, datetime.now().astimezone())
            try:
                wait(duration_seconds)
            finally:
                driver.set_state(heater.id, False, datetime.now().astimezone())
    finally:
        for heater in enabled_heaters:
            try:
                driver.set_state(heater.id, False, datetime.now().astimezone())
            except Exception:
                logger.exception("Failed to force self-test output %s OFF", heater.id)
        driver.close()
    logger.info("GPIO self-test completed with every output off")
    return 0


# ------------------------------------------------------------------ utilities

def _handle_termination_signal(_signum, _frame) -> None:
    logger.info("Termination signal received")
    raise KeyboardInterrupt


@contextmanager
def _controlled_termination() -> Iterator[None]:
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_termination_signal)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)


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
