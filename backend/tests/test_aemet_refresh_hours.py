from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json

from alembic import command
import pytest
from sqlalchemy import inspect, text

from dynamic_thermal_charge.models import (
    AemetConfig,
    WeatherConfig,
    WeatherWatchdogConfig,
)
from dynamic_thermal_charge.persistence.aemet_refresh_migration import (
    migrate_refresh_configuration_engine,
)
from dynamic_thermal_charge.persistence.bootstrap import open_legacy_store
from dynamic_thermal_charge.persistence.migrations import _config
from dynamic_thermal_charge.persistence.schema import weather_config
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.runtime import (
    _record_forecast_cycle,
    _refresh_daily_aemet_forecast,
    _seconds_to_forecast_refresh,
)
from dynamic_thermal_charge.api.read_model import forecast_cycle_context
from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import SimulatedOutputDriver
from dynamic_thermal_charge.scheduler import ScheduleResult
from dynamic_thermal_charge.service import ControllerService, PlanRefresh
from dynamic_thermal_charge.watchdog import DailyAemetForecastManager, ForecastWatchdog
from dynamic_thermal_charge.weather import (
    ForecastCycleState,
    HourlyForecastPoint,
    OutdoorForecast,
)


def test_refresh_hours_defaults_and_rejects_non_integer_values():
    assert WeatherWatchdogConfig().refresh_hours == 4
    for value in (True, False, 1.5, 0, -1):
        with pytest.raises(ValueError):
            WeatherWatchdogConfig(refresh_hours=value)


def test_legacy_180_minutes_migrates_to_three_hours_and_removes_minute_names(
    tmp_path,
):
    from dynamic_thermal_charge.persistence.canonical_engines import (
        build_canonical_engines,
        initialise_canonical_schemas,
    )
    from dynamic_thermal_charge.persistence.locator import DatabaseLocator
    from dynamic_thermal_charge.persistence.paths import StorePaths
    from dynamic_thermal_charge.persistence.system_configuration import (
        SystemConfigurationRepository,
    )

    engines = build_canonical_engines(
        DatabaseLocator.sqlite(), StorePaths.in_directory(tmp_path)
    )
    initialise_canonical_schemas(engines)
    repository = SystemConfigurationRepository(engines.configuration)
    assert repository.initialise()
    now = "2026-01-01 00:00:00"
    with engines.configuration.begin() as connection:
        installation_id = connection.execute(
            text(
                "INSERT INTO installation "
                "(name,max_total_power_w,slot_minutes,window_minutes,created_at,updated_at) "
                "VALUES ('test', 1, 1, 1, :now, :now)"
            ),
            {"now": now},
        ).lastrowid
        connection.execute(
            weather_config.insert().values(
                id=1,
                installation_id=installation_id,
                provider="aemet",
                watchdog_retry_minutes=15,
                watchdog_refresh_hours=4,
            )
        )
        connection.execute(
            text(
                "ALTER TABLE weather_config "
                "RENAME COLUMN watchdog_refresh_hours TO watchdog_refresh_minutes"
            )
        )
        connection.execute(
            text("UPDATE weather_config SET watchdog_refresh_minutes = 180 WHERE id = 1")
        )
        row = connection.execute(
            text("SELECT weather_json FROM system_configuration WHERE id = 1")
        ).scalar_one()
        weather = json.loads(row)
        weather["refresh_minutes"] = 180
        weather.pop("refresh_hours", None)
        connection.execute(
            text("UPDATE system_configuration SET weather_json = :weather WHERE id = 1"),
            {"weather": json.dumps(weather)},
        )

    migrate_refresh_configuration_engine(engines.configuration)
    with engines.configuration.connect() as connection:
        columns = {
            item["name"]
            for item in __import__("sqlalchemy").inspect(engines.configuration).get_columns(
                "weather_config"
            )
        }
        assert "watchdog_refresh_minutes" not in columns
        assert connection.execute(
            text("SELECT watchdog_refresh_hours FROM weather_config WHERE id = 1")
        ).scalar_one() == 3
        weather = json.loads(
            connection.execute(
                text("SELECT weather_json FROM system_configuration WHERE id = 1")
            ).scalar_one()
        )
        assert weather["refresh_hours"] == 3
        assert "refresh_minutes" not in weather


def test_alembic_upgrade_from_0029_rewrites_default_for_fresh_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy-0029.db'}"
    store = open_legacy_store({"DTC_DATABASE_URL": url})
    try:
        command.upgrade(_config(store.engine), "0029_measured_history_and_chart_cues")
        assert store.repository.seed(example_installation(), "old-0029")
        with store.engine.begin() as connection:
            connection.execute(
                text("UPDATE weather_config SET watchdog_refresh_minutes = 180")
            )

        command.upgrade(_config(store.engine), "head")
        with store.engine.connect() as connection:
            columns = {
                item["name"]: item
                for item in inspect(store.engine).get_columns("weather_config")
            }
            assert columns["watchdog_refresh_hours"]["default"] == "4"
            assert connection.execute(
                text("SELECT watchdog_refresh_hours FROM weather_config")
            ).scalar_one() == 3

        with store.engine.begin() as connection:
            connection.execute(text("DELETE FROM weather_config"))
            connection.execute(
                text(
                    "INSERT INTO weather_config (installation_id, provider) "
                    "VALUES (1, 'aemet')"
                )
            )
        with store.engine.connect() as connection:
            assert connection.execute(
                text("SELECT watchdog_refresh_hours FROM weather_config")
            ).scalar_one() == 4
    finally:
        store.close()


def test_invalid_or_conflicting_legacy_values_abort_without_mutation(tmp_path):
    from dynamic_thermal_charge.persistence.canonical_engines import (
        build_canonical_engines,
        initialise_canonical_schemas,
    )
    from dynamic_thermal_charge.persistence.locator import DatabaseLocator
    from dynamic_thermal_charge.persistence.paths import StorePaths
    from dynamic_thermal_charge.persistence.system_configuration import (
        SystemConfigurationRepository,
    )

    engines = build_canonical_engines(
        DatabaseLocator.sqlite(), StorePaths.in_directory(tmp_path)
    )
    initialise_canonical_schemas(engines)
    repository = SystemConfigurationRepository(engines.configuration)
    assert repository.initialise()
    with engines.configuration.begin() as connection:
        now = "2026-01-01 00:00:00"
        installation_id = connection.execute(
            text(
                "INSERT INTO installation "
                "(name,max_total_power_w,slot_minutes,window_minutes,created_at,updated_at) "
                "VALUES ('test', 1, 1, 1, :now, :now)"
            ),
            {"now": now},
        ).lastrowid
        connection.execute(
            weather_config.insert().values(
                id=1,
                installation_id=installation_id,
                provider="aemet",
                watchdog_retry_minutes=15,
                watchdog_refresh_hours=4,
            )
        )
        connection.execute(
            text(
                "ALTER TABLE weather_config "
                "RENAME COLUMN watchdog_refresh_hours TO watchdog_refresh_minutes"
            )
        )
        connection.execute(
            text("UPDATE weather_config SET watchdog_refresh_minutes = 181 WHERE id = 1")
        )
        row = connection.execute(
            text("SELECT weather_json FROM system_configuration WHERE id = 1")
        ).scalar_one()
        weather = json.loads(row)
        weather["refresh_minutes"] = 180
        weather.pop("refresh_hours", None)
        connection.execute(
            text("UPDATE system_configuration SET weather_json = :weather WHERE id = 1"),
            {"weather": json.dumps(weather)},
        )

    with pytest.raises(ValueError, match="divisible by 60"):
        migrate_refresh_configuration_engine(engines.configuration)
    with engines.configuration.connect() as connection:
        assert connection.execute(
            text("SELECT watchdog_refresh_minutes FROM weather_config WHERE id = 1")
        ).scalar_one() == 181
        assert "refresh_minutes" in json.loads(
            connection.execute(
                text("SELECT weather_json FROM system_configuration WHERE id = 1")
            ).scalar_one()
        )

    with engines.configuration.begin() as connection:
        connection.execute(
            text("UPDATE weather_config SET watchdog_refresh_minutes = 180 WHERE id = 1")
        )
        weather = json.loads(
            connection.execute(
                text("SELECT weather_json FROM system_configuration WHERE id = 1")
            ).scalar_one()
        )
        weather.pop("refresh_minutes", None)
        weather["refresh_hours"] = 4
        connection.execute(
            text("UPDATE system_configuration SET weather_json = :weather WHERE id = 1"),
            {"weather": json.dumps(weather)},
        )

    with pytest.raises(ValueError, match="conflicting"):
        migrate_refresh_configuration_engine(engines.configuration)
    with engines.configuration.connect() as connection:
        assert connection.execute(
            text("SELECT watchdog_refresh_minutes FROM weather_config WHERE id = 1")
        ).scalar_one() == 180
        assert json.loads(
            connection.execute(
                text("SELECT weather_json FROM system_configuration WHERE id = 1")
            ).scalar_one()
        )["refresh_hours"] == 4


def test_success_timer_uses_provider_completion_clock_across_dst():
    class Clock:
        def __init__(self, value):
            self.value = value

        def __call__(self):
            return self.value

    class Provider:
        def __init__(self, clock):
            self.clock = clock

        def forecast_for(self, requested_date: date):
            assert requested_date == date(2026, 3, 29)
            self.clock.value += timedelta(minutes=30)
            return OutdoorForecast(
                date=requested_date,
                average_temperature_c=7,
                minimum_temperature_c=3,
                maximum_temperature_c=11,
                source="aemet",
            )

    started = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    clock = Clock(started)
    manager = DailyAemetForecastManager(
        Provider(clock),
        query_hour=0,
        timezone_name="Europe/Madrid",
        refresh_hours=4,
        clock=clock,
    )
    result = manager.poll(started)
    completed = started + timedelta(minutes=30)
    assert result.state.last_attempt_at == completed
    assert result.state.next_run_at == completed + timedelta(hours=4)
    assert result.state.next_run_at != started + timedelta(hours=4)


def test_automatic_refresh_uses_injected_clock_for_completion_and_next_run():
    class Clock:
        def __init__(self, value):
            self.value = value

        def __call__(self):
            return self.value

    class Provider:
        def __init__(self, clock):
            self.clock = clock

        def forecast_for(self, requested_date: date):
            self.clock.value += timedelta(minutes=30)
            return OutdoorForecast(
                date=requested_date,
                average_temperature_c=7,
                minimum_temperature_c=3,
                maximum_temperature_c=11,
                source="aemet",
            )

    class Planning:
        def __init__(self):
            self.state = None

        def forecast_cycle(self, local_date, scheduled_at, now=None):
            if self.state is None:
                self.state = ForecastCycleState(local_date, scheduled_at)
            return self.state

        def save_forecast_cycle(self, state, _forecast_ref=None):
            self.state = state

    class Store:
        def __init__(self):
            self.planning = Planning()
            self.system_configuration = None

    class History:
        def record_forecast(self, _forecast):
            return None

    started = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    clock = Clock(started)
    store = Store()
    weather = WeatherConfig(
        provider="aemet",
        aemet=AemetConfig(municipality_code="00001"),
        watchdog=WeatherWatchdogConfig(refresh_hours=4),
    )

    delay = _refresh_daily_aemet_forecast(
        store,
        History(),
        Provider(clock),
        started,
        query_hour=0,
        timezone_name="Europe/Madrid",
        weather_fallback=weather,
        clock=clock,
    )

    completed = started + timedelta(minutes=30)
    assert store.planning.state.last_attempt_at == completed
    assert store.planning.state.next_run_at == completed + timedelta(hours=4)
    assert delay == 4 * 60 * 60 + 30 * 60


@pytest.mark.parametrize(
    ("source", "interval_seconds"),
    (("aemet", 4 * 60 * 60), ("unsupported", 10 * 60)),
)
def test_controller_service_fallback_refresh_starts_after_provider_completion(
    source, interval_seconds
):
    class Clock:
        def __init__(self, value):
            self.value = value

        def __call__(self):
            return self.value

    class Provider:
        def __init__(self, clock):
            self.clock = clock

        def forecast_for(self, requested_date):
            self.clock.value += timedelta(minutes=30)
            return OutdoorForecast(
                date=requested_date,
                average_temperature_c=7,
                minimum_temperature_c=3,
                maximum_temperature_c=11,
                source=source,
            )

    started = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    clock = Clock(started)
    watchdog = ForecastWatchdog(
        Provider(clock),
        expected_source="aemet",
        config=WeatherWatchdogConfig(retry_minutes=10, refresh_hours=4),
    )
    plan = ScheduleResult(slots=(), allocated_minutes={}, unmet_minutes={})

    def refresh_plan(now):
        cycle = watchdog.poll(now.date())
        completed_at = clock()
        return PlanRefresh(
            plan=plan,
            next_refresh_seconds=_seconds_to_forecast_refresh(
                now, completed_at, cycle.next_poll_seconds
            ),
            persist_plan=False,
        )

    service = ControllerService(
        controller=ChargeController((), SimulatedOutputDriver()),
        store=object(),
        refresh_plan=refresh_plan,
        poll_seconds=1,
        error_retry_seconds=60,
        clock=clock,
        wait=lambda _seconds: None,
    )

    _plan, next_refresh = service._try_refresh(started, None)

    completed = started + timedelta(minutes=30)
    assert next_refresh == completed + timedelta(seconds=interval_seconds)


def test_degraded_fallback_persists_retry_state_and_keeps_forecast(
    initialised_store, recorder
):
    class Clock:
        def __init__(self, value):
            self.value = value

        def __call__(self):
            return self.value

    class Provider:
        def __init__(self, clock):
            self.clock = clock

        def forecast_for(self, requested_date):
            self.clock.value += timedelta(minutes=30)
            return OutdoorForecast(
                date=requested_date,
                average_temperature_c=7,
                minimum_temperature_c=3,
                maximum_temperature_c=11,
                source="unsupported",
            )

    started = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    clock = Clock(started)
    recorder.record_forecast(
        OutdoorForecast(
            date=started.date(),
            average_temperature_c=6,
            minimum_temperature_c=2,
            maximum_temperature_c=10,
            source="aemet",
            hourly_points=(HourlyForecastPoint(started, 6),),
        )
    )
    cycle = ForecastWatchdog(
        Provider(clock),
        expected_source="aemet",
        config=WeatherWatchdogConfig(retry_minutes=10, refresh_hours=4),
    ).poll(started.date())
    completed = clock()
    forecast_ref = recorder.record_forecast(cycle.forecast)
    retry_at = completed + timedelta(seconds=cycle.next_poll_seconds)
    _record_forecast_cycle(
        initialised_store,
        local_date=started.date(),
        scheduled_at=started,
        attempted_at=completed,
        result="error",
        error="WeatherProviderError: no se pudo obtener el forecast meteorológico",
        next_run_at=retry_at,
        forecast_ref=forecast_ref,
    )

    status = initialised_store.planning.forecast_cycle_status()
    assert status["forecast_status"] == "error"
    assert status["forecast_next_run_at"] is None
    assert status["forecast_next_retry_at"] == retry_at
    context = forecast_cycle_context(initialised_store.planning)
    assert context["forecast_next_run_kind"] == "retry"
    assert context["forecast_next_run_at"] == retry_at
    assert initialised_store.planning.latest_forecast()


def test_controller_service_exception_retry_starts_after_provider_completion():
    class Clock:
        def __init__(self, value):
            self.value = value

        def __call__(self):
            return self.value

    class Provider:
        def __init__(self, clock):
            self.clock = clock

        def forecast_for(self, requested_date):
            self.clock.value += timedelta(minutes=30)
            raise RuntimeError(f"provider unavailable for {requested_date}")

    started = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)
    clock = Clock(started)
    watchdog = ForecastWatchdog(
        Provider(clock),
        expected_source="aemet",
        config=WeatherWatchdogConfig(retry_minutes=10, refresh_hours=4),
    )
    plan = ScheduleResult(slots=(), allocated_minutes={}, unmet_minutes={})

    def refresh_plan(now):
        watchdog.poll(now.date())
        return PlanRefresh(plan=plan, next_refresh_seconds=1, persist_plan=False)

    service = ControllerService(
        controller=ChargeController((), SimulatedOutputDriver()),
        store=object(),
        refresh_plan=refresh_plan,
        poll_seconds=1,
        error_retry_seconds=10 * 60,
        clock=clock,
        wait=lambda _seconds: None,
    )

    _plan, next_retry = service._try_refresh(started, None)

    completed = started + timedelta(minutes=30)
    assert next_retry == completed + timedelta(minutes=10)
