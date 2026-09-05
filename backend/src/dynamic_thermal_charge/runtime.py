"""Runtime composition for the controller and forecast services.

This module contains process behavior, not a user-facing command interface.
Each public entrypoint is called by the deployment directly.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, time as clock_time, timedelta
import logging
import math
import signal
import time
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from .controller import ChargeController
from .drivers import OutputDriver, RecordingOutputDriver, SimulatedOutputDriver
from .gpio_driver import GpioOutputDriver
from .charge_planning import PLANNING_HORIZON_HOURS, DeterministicChargeOptimizer, PlanningInput, resolve_planning_telemetry
from .models import AppConfig, ChargeTelemetry
from .persistence import ConfigStoreError
from .persistence.active_plan import SqlActivePlanRepository
from .scheduler import ChargeScheduler, ScheduleResult, ScheduleSlot
from .service import ControllerService, PlanRefresh
from .system_settings import MqttSystemSettings
from .thermal import ThermalDemandEngine, select_indoor_temperatures
from .watchdog import DailyAemetForecastManager, ForecastWatchdog
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
    active_plan = SqlActivePlanRepository(
        application_engine, installation_id, store.location
    )
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
    indoor_fallback = _IndoorFallbackTracker()
    driver: OutputDriver | None = None
    service: ControllerService | None = None
    with _controlled_termination():
        try:
            _require_real_telemetry_for_gpio(
                driver_name,
                _live_mqtt_settings(
                    store, None if system is None else system.mqtt
                ),
                store.planning.site(),
            )
            driver = RecordingOutputDriver(
                _build_output_driver(config, driver_name),
                history,
                plan_ref=lambda: None if service is None else service.current_plan_ref,
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
                live_mqtt = _live_mqtt_settings(store, None if system is None else system.mqtt)
                planning_site = store.planning.site()
                automatic_constraints = store.planning.constraints()
                logger.debug(
                    "Plan refresh started: at=%s constraints=%d active_automatic=%s "
                    "replan_minutes=%s",
                    now.isoformat(),
                    len(automatic_constraints),
                    store.planning.active_plan() is not None,
                    planning_site["replan_minutes"],
                )
                timezone_name = (
                    live_config.schedule.timezone
                    if live_config.schedule is not None
                    else "UTC"
                )
                _refresh_daily_aemet_forecast(
                    store,
                    history,
                    provider,
                    now,
                    query_hour=int(planning_site["aemet_query_hour"]),
                    timezone_name=timezone_name,
                )
                if automatic_constraints or store.planning.active_plan() is not None:
                    automatic = _build_automatic_runtime_plan(
                        store,
                        live_config,
                        now,
                        automatic_constraints,
                        planning_site,
                        mqtt=live_mqtt,
                    )
                    if automatic is not None:
                        store.planning.save_plan(
                            automatic[0],
                            configuration_revision=live_revision,
                            constraints_revision=planning_site["revision"],
                            reason="periodic",
                            active=automatic[0].status != "INVALID",
                        )
                        logger.debug(
                            "Automatic plan persisted: status=%s slots=%d violations=%d",
                            automatic[0].status,
                            len(automatic[0].slots),
                            len(automatic[0].violations),
                        )
                        return PlanRefresh(
                            plan=automatic[1],
                            next_refresh_seconds=_seconds_to_next_replan(
                                now,
                                replan_minutes=int(planning_site["replan_minutes"]),
                                slot_minutes=live_config.site.slot_minutes,
                            ),
                            plan_ref=None,
                            installation_revision=live_revision,
                        )
                start = (
                    live_config.schedule.active_or_next_start(now)
                    if live_config.schedule is not None
                    else now
                )
                try:
                    cycle = watchdog.poll(start.date())
                except Exception as exc:
                    _record_forecast_cycle(
                        store,
                        local_date=start.date(),
                        scheduled_at=now,
                        attempted_at=now,
                        result="error",
                        error=_safe_forecast_error(exc),
                        next_run_at=now + timedelta(minutes=config.weather.watchdog.retry_minutes),
                    )
                    raise
                forecast_ref = history.record_forecast(cycle.forecast)
                _record_forecast_cycle(
                    store,
                    local_date=start.date(),
                    scheduled_at=now,
                    attempted_at=now,
                    result="success",
                    error=None,
                    next_run_at=now + timedelta(seconds=cycle.next_poll_seconds),
                    forecast_ref=forecast_ref,
                )
                indoor_temperatures = indoor_fallback.select(
                    live_config,
                    store.indoor_readings,
                    now,
                    fixed_temperature_c=(
                        None
                        if live_mqtt is None or live_mqtt.enabled
                        else live_mqtt.fixed_indoor_temperature_c
                    ),
                )
                plan = _build_plan(
                    live_config,
                    start,
                    cycle.forecast,
                    indoor_temperatures=indoor_temperatures,
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
                    plan_ref=None,
                    installation_revision=live_revision,
                    forecast_ref=forecast_ref,
                )

            service = ControllerService(
                controller=controller,
                store=active_plan,
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
    store,
    config: AppConfig,
    now: datetime,
    constraints,
    planning_site: dict[str, int],
    *,
    mqtt: MqttSystemSettings | None = None,
):
    """Build the controller-facing schedule from the automatic plan value."""
    mqtt_settings = mqtt if mqtt is not None else _live_mqtt_settings(store, None)
    persisted = (
        {}
        if mqtt_settings is not None and not mqtt_settings.enabled
        else store.planning.telemetry()
    )
    valid = resolve_planning_telemetry(
        config.heaters,
        persisted,
        now,
        mqtt=mqtt_settings,
    )
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    request = PlanningInput(
        heaters=config.heaters,
        telemetry=valid,
        constraints=constraints,
        forecast=store.planning.latest_forecast(now),
        horizon_start=now,
        horizon_hours=int(planning_site.get("forecast_horizon_hours", PLANNING_HORIZON_HOURS)),
        slot_minutes=config.site.slot_minutes,
        max_total_power_w=int(planning_site.get("contracted_power_w", config.site.max_total_power_w)),
        base_load_w=int(planning_site.get("base_load_w", 0)),
        max_heating_power_w=int(planning_site.get("max_heating_power_w", config.site.max_heating_power_w or config.site.max_total_power_w)),
        design_indoor_temperature_c=float(planning_site.get("design_indoor_temperature_c", config.site.design_indoor_temperature_c)),
        design_outdoor_temperature_c=float(planning_site.get("design_outdoor_temperature_c", config.site.design_outdoor_temperature_c)),
        feedback_horizon_hours=float(planning_site.get("feedback_horizon_hours", config.site.feedback_horizon_hours)),
        forecast_automatic_eligible=(store.planning.latest_forecast_automatic_eligible() if hasattr(store.planning, "latest_forecast_automatic_eligible") else True),
        generated_at=now,
        timezone_name=timezone_name,
    )
    plan = DeterministicChargeOptimizer().build(request)
    legacy_slots = tuple(
        ScheduleSlot(slot.start, slot.end, slot.heater_ids, slot.power_w, slot.outdoor_temperature_c, False)
        for slot in plan.slots
    )
    allocated = {heater.id: sum(config.site.slot_minutes for slot in plan.slots if heater.id in slot.heater_ids) for heater in config.heaters}
    return plan, ScheduleResult(
        legacy_slots,
        allocated,
        _aggregate_unmet_minutes(config, plan.deficits),
    )


def _aggregate_unmet_minutes(config: AppConfig, violations) -> dict[str, int]:
    heaters_by_id = {heater.id: heater for heater in config.heaters}
    unmet: dict[str, int] = {}
    for item in violations:
        if item.heater_id is None or item.deficit_percent <= 0:
            continue
        heater = heaters_by_id.get(item.heater_id)
        if heater is None:
            continue
        minutes = round(item.deficit_percent * heater.full_charge_minutes / 100)
        unmet[item.heater_id] = unmet.get(item.heater_id, 0) + minutes
    return unmet


def _seconds_to_next_slot(now: datetime, slot_minutes: int) -> int:
    floor = now.replace(second=0, microsecond=0, minute=(now.minute // slot_minutes) * slot_minutes)
    boundary = floor + timedelta(minutes=slot_minutes)
    return max(1, math.ceil((boundary - now).total_seconds()))


def _seconds_to_next_replan(
    now: datetime, *, replan_minutes: int, slot_minutes: int
) -> int:
    """Schedule no sooner than the configured cadence on a slot boundary."""
    cadence_minutes = max(replan_minutes, slot_minutes)
    target = now + timedelta(minutes=cadence_minutes)
    floor = target.replace(
        second=0,
        microsecond=0,
        minute=(target.minute // slot_minutes) * slot_minutes,
    )
    boundary = floor if floor == target else floor + timedelta(minutes=slot_minutes)
    return max(slot_minutes * 60, math.ceil((boundary - now).total_seconds()))


def _refresh_daily_aemet_forecast(
    store,
    history,
    provider: WeatherProvider,
    now: datetime,
    *,
    query_hour: int,
    timezone_name: str,
) -> None:
    """Run and durably record the AEMET cycle without stopping planning."""
    manager = DailyAemetForecastManager(
        provider, query_hour=query_hour, timezone_name=timezone_name
    )
    zone = ZoneInfo(timezone_name)
    local_date = now.astimezone(zone).date()
    scheduled_at = datetime.combine(
        local_date, clock_time(hour=query_hour), tzinfo=zone
    )
    try:
        current = store.planning.forecast_cycle(local_date, scheduled_at)
        result = manager.poll(now, current)
        forecast_ref = (
            history.record_forecast(result.forecast)
            if result.forecast is not None and result.state.last_result == "success"
            else None
        )
        store.planning.save_forecast_cycle(result.state, forecast_ref)
        logger.debug(
            "AEMET cycle refreshed: local_date=%s result=%s attempt=%d completed=%s "
            "forecast_persisted=%s next_retry_at=%s",
            local_date.isoformat(),
            result.state.last_result,
            result.state.attempt,
            result.state.completed,
            forecast_ref is not None,
            result.state.next_retry_at.isoformat() if result.state.next_retry_at else None,
        )
    except Exception:
        logger.error("Could not refresh the daily AEMET forecast", exc_info=True)


def _record_forecast_cycle(
    store,
    *,
    local_date,
    scheduled_at: datetime,
    attempted_at: datetime,
    result: str,
    error: str | None,
    next_run_at: datetime,
    forecast_ref=None,
) -> None:
    """Best-effort durable observability for an automatic provider attempt."""
    try:
        planning = store.planning
        current = planning.forecast_cycle(local_date, scheduled_at)
        state = replace(
            current,
            last_attempt_at=attempted_at,
            last_result=result,
            last_error=error,
            stale=result == "error",
            next_retry_at=(next_run_at if result == "error" else None),
            next_run_at=next_run_at,
            attempt=(current.attempt + 1 if result == "error" else 0),
        )
        planning.save_forecast_cycle(state, forecast_ref)
    except Exception:
        # Forecast observability is subordinate to keeping the controller alive.
        logger.error("Could not persist forecast cycle state", exc_info=True)


def _safe_forecast_error(error: BaseException) -> str:
    return f"{error.__class__.__name__}: no se pudo obtener el forecast meteorológico"


class _IndoorFallbackTracker:
    """Read once per plan and log only fallback state transitions."""

    def __init__(self) -> None:
        self._fallback: set[str] = set()
        self._store_unavailable = False

    def select(
        self,
        config: AppConfig,
        repository,
        at: datetime,
        *,
        fixed_temperature_c: float | None = None,
    ) -> dict[str, float]:
        if fixed_temperature_c is not None:
            self._fallback = set()
            self._store_unavailable = False
            return {
                heater.id: fixed_temperature_c
                for heater in config.heaters
                if heater.enabled
            }
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


def _live_mqtt_settings(
    store,
    fallback: MqttSystemSettings | None,
) -> MqttSystemSettings | None:
    if store.system_configuration is None:
        return fallback
    return store.system_configuration.current().configuration.mqtt


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


def _require_real_telemetry_for_gpio(
    driver_name: str,
    mqtt: MqttSystemSettings | None,
    planning_site: dict[str, object],
) -> None:
    """Never allow physical relays to run from invented accumulator state."""
    if driver_name != "gpio":
        return
    causes: list[str] = []
    if mqtt is not None and not mqtt.enabled:
        causes.append("MQTT is disabled")
    if bool(planning_site.get("mqtt_simulation_enabled", False)):
        causes.append("accumulator simulation is enabled")
    if not causes:
        return
    message = "GPIO controller startup rejected: " + "; ".join(causes)
    logger.critical(message)
    raise RuntimeError(message)


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
