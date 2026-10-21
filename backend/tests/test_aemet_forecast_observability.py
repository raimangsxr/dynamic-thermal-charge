from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from dynamic_thermal_charge.persistence.system_configuration import SecretAction, SecretMutation
from dynamic_thermal_charge.api.read_model import forecast_cycle_context
from dynamic_thermal_charge.runtime import _record_forecast_cycle
from dynamic_thermal_charge.weather import HourlyForecastPoint, OutdoorForecast, WeatherProviderError
from tests.conftest import API_NOW, AUTH


def _forecast() -> OutdoorForecast:
    return OutdoorForecast(
        date=API_NOW.date(),
        average_temperature_c=7.0,
        minimum_temperature_c=3.0,
        maximum_temperature_c=11.0,
        source="aemet",
        location="Madrid",
        hourly_points=(
            HourlyForecastPoint(API_NOW, 6.0),
            HourlyForecastPoint(API_NOW + timedelta(hours=1), 7.0),
        ),
    )


def _configure_aemet(store) -> None:
    snapshot = store.system_configuration.current()
    store.system_configuration.update_section(
        "weather",
        {"provider": "aemet", "municipality_code": "28079"},
        expected_revision=snapshot.revision,
        secret_mutations={"aemet_api_key": SecretMutation(SecretAction.REPLACE, "sentinel-aemet-key")},
        actor="test",
    )


def test_initial_cycle_projection_has_the_daily_anchor_without_a_forecast(initialised_store):
    cycle = initialised_store.planning.forecast_cycle(API_NOW.date(), API_NOW)

    context = forecast_cycle_context(initialised_store.planning)

    assert cycle.last_result is None
    assert context["forecast_next_run_at"] == cycle.scheduled_at
    assert context["forecast_next_run_kind"] == "daily"


def test_next_cycle_carries_a_successful_refresh_after_the_daily_anchor(initialised_store):
    successful_at = datetime(2026, 1, 16, 23, 30, tzinfo=timezone.utc)
    refresh_at = successful_at + timedelta(hours=14)
    _record_forecast_cycle(
        initialised_store,
        local_date=successful_at.date(),
        scheduled_at=successful_at,
        attempted_at=successful_at,
        result="success",
        error=None,
        next_run_at=refresh_at,
    )

    next_cycle = initialised_store.planning.forecast_cycle(
        refresh_at.date(),
        datetime(2026, 1, 17, 12, tzinfo=timezone.utc),
        now=datetime(2026, 1, 17, 12, 5, tzinfo=timezone.utc),
    )

    assert next_cycle.next_run_at == refresh_at
    assert next_cycle.completed is True
    assert forecast_cycle_context(initialised_store.planning)["forecast_next_run_kind"] == "refresh"


def test_persisted_failed_episode_keeps_retry_cadence_across_local_midnight(
    initialised_store,
):
    failed_at = datetime(2026, 1, 16, 23, 30, tzinfo=timezone.utc)
    retry_at = failed_at + timedelta(hours=1)
    cycle = initialised_store.planning.forecast_cycle(
        failed_at.date(), failed_at
    )
    initialised_store.planning.save_forecast_cycle(
        replace(
            cycle,
            attempt=1,
            next_retry_at=retry_at,
            last_attempt_at=failed_at,
            last_result="error",
            last_error="AEMET unavailable",
            stale=True,
            completed=False,
        )
    )

    next_cycle = initialised_store.planning.forecast_cycle(
        retry_at.date(),
        datetime(2026, 1, 17, 12, tzinfo=timezone.utc),
        now=datetime(2026, 1, 17, 0, 5, tzinfo=timezone.utc),
    )

    assert next_cycle.attempt == 1
    assert next_cycle.next_retry_at == retry_at
    assert next_cycle.last_result == "error"
    assert next_cycle.stale is True


def test_forecast_cycle_persists_success_and_failure_without_replacing_forecast(
    initialised_store, recorder
):
    reference = recorder.record_forecast(_forecast())
    next_run = API_NOW + timedelta(hours=3)
    _record_forecast_cycle(
        initialised_store,
        local_date=API_NOW.date(),
        scheduled_at=API_NOW,
        attempted_at=API_NOW,
        result="success",
        error=None,
        next_run_at=next_run,
        forecast_ref=reference,
    )
    assert initialised_store.planning.forecast_cycle_status() == {
        "forecast_status": "success",
        "forecast_last_attempt_at": API_NOW,
        "forecast_last_error": None,
        "forecast_next_run_at": next_run,
        "forecast_attempt": 0,
        "forecast_next_retry_at": None,
        "forecast_stale": False,
    }
    context = forecast_cycle_context(initialised_store.planning)
    assert context["forecast_next_run_at"] == next_run
    assert context["forecast_next_run_kind"] == "refresh"

    _record_forecast_cycle(
        initialised_store,
        local_date=API_NOW.date(),
        scheduled_at=API_NOW,
        attempted_at=API_NOW + timedelta(minutes=1),
        result="error",
        error="WeatherProviderError: no se pudo obtener el forecast meteorológico",
        next_run_at=API_NOW + timedelta(minutes=15),
    )
    status = initialised_store.planning.forecast_cycle_status()
    assert status["forecast_status"] == "error"
    assert status["forecast_last_error"].startswith("WeatherProviderError")
    assert initialised_store.planning.latest_forecast()
    context = forecast_cycle_context(initialised_store.planning)
    assert context["forecast_next_run_kind"] == "retry"
    assert context["forecast_next_run_at"] == API_NOW + timedelta(minutes=15)


def test_forecast_cycle_does_not_resume_stale_episode_after_success(initialised_store):
    first_day = datetime(2026, 1, 16, 1, tzinfo=timezone.utc)
    second_day = first_day + timedelta(days=1)
    third_day = second_day + timedelta(days=1)

    _record_forecast_cycle(
        initialised_store,
        local_date=first_day.date(),
        scheduled_at=first_day,
        attempted_at=first_day,
        result="error",
        error="AEMET unavailable",
        next_run_at=first_day + timedelta(hours=1),
    )
    _record_forecast_cycle(
        initialised_store,
        local_date=second_day.date(),
        scheduled_at=second_day,
        attempted_at=second_day,
        result="success",
        error=None,
        next_run_at=second_day + timedelta(days=1),
    )

    next_cycle = initialised_store.planning.forecast_cycle(
        third_day.date(), third_day, now=third_day
    )

    assert next_cycle.attempt == 0
    assert next_cycle.next_retry_at is None
    assert next_cycle.stale is False
    assert next_cycle.completed is True
    assert next_cycle.next_run_at == third_day


def test_manual_aemet_refresh_returns_forecast_and_restarts_automatic_timer(
    client, initialised_store, monkeypatch
):
    _configure_aemet(initialised_store)
    automatic_next = API_NOW + timedelta(hours=2)
    cycle = initialised_store.planning.forecast_cycle(API_NOW.date(), API_NOW)
    initialised_store.planning.save_forecast_cycle(
        replace(cycle, next_run_at=automatic_next)
    )

    class Provider:
        def __init__(self, *_args, **_kwargs):
            pass

        def forecast_for(self, forecast_date):
            assert forecast_date == date(2026, 1, 16)
            return _forecast()

    monkeypatch.setattr(
        "dynamic_thermal_charge.api.routes.system.AemetWeatherProvider", Provider
    )
    response = client.post("/api/v1/system/weather/refresh", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["forecast_status"] == "success"
    assert body["forecast"]["hourly_points"]
    expected_next = API_NOW + timedelta(hours=4)
    assert body["forecast_next_run_at"].startswith("2026-01-16T05:00")
    assert "sentinel-aemet-key" not in response.text
    assert initialised_store.planning.forecast_cycle_status()["forecast_next_run_at"] == expected_next

    configuration = client.get("/api/v1/system/configuration", headers=AUTH).json()
    assert configuration["sections"]["weather"]["forecast_status"] == "success"
    assert configuration["sections"]["weather"]["forecast_last_attempt_at"].startswith("2026-01-16T01:00")


def test_manual_aemet_refresh_schedules_from_actual_completion(
    client, initialised_store, api_clock, monkeypatch
):
    _configure_aemet(initialised_store)

    class Provider:
        def __init__(self, *_args, **_kwargs):
            pass

        def forecast_for(self, _forecast_date):
            api_clock.advance(minutes=30)
            return _forecast()

    monkeypatch.setattr(
        "dynamic_thermal_charge.api.routes.system.AemetWeatherProvider", Provider
    )
    response = client.post("/api/v1/system/weather/refresh", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    expected_completed = API_NOW + timedelta(minutes=30)
    expected_next = expected_completed + timedelta(hours=4)
    assert body["forecast_last_attempt_at"].startswith("2026-01-16T01:30")
    assert body["forecast_next_run_at"].startswith("2026-01-16T05:30")
    assert initialised_store.planning.forecast_cycle_status()["forecast_next_run_at"] == expected_next


def test_manual_aemet_refresh_exposes_safe_error_and_keeps_last_forecast(
    client, initialised_store, recorder, monkeypatch
):
    _configure_aemet(initialised_store)
    recorder.record_forecast(_forecast())

    class Provider:
        def __init__(self, *_args, **_kwargs):
            pass

        def forecast_for(self, _forecast_date):
            raise WeatherProviderError("request included sentinel-aemet-key")

    monkeypatch.setattr(
        "dynamic_thermal_charge.api.routes.system.AemetWeatherProvider", Provider
    )
    response = client.post("/api/v1/system/weather/refresh", headers=AUTH)
    assert response.status_code == 503
    assert "sentinel-aemet-key" not in response.text
    configuration = client.get("/api/v1/system/configuration", headers=AUTH).json()
    weather = configuration["sections"]["weather"]
    assert weather["forecast_status"] == "error"
    assert weather["forecast_last_error"].startswith("WeatherProviderError")
    assert weather["forecast_next_run_kind"] == "retry"
    assert initialised_store.planning.latest_forecast()
