from dataclasses import replace
from datetime import date, timedelta

from dynamic_thermal_charge.persistence.system_configuration import SecretAction, SecretMutation
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
    }

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


def test_manual_aemet_refresh_returns_forecast_and_preserves_automatic_timer(
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
    assert body["forecast_next_run_at"].startswith("2026-01-16T03:00")
    assert "sentinel-aemet-key" not in response.text
    assert initialised_store.planning.forecast_cycle_status()["forecast_next_run_at"] == automatic_next

    configuration = client.get("/api/v1/system/configuration", headers=AUTH).json()
    assert configuration["sections"]["weather"]["forecast_status"] == "success"
    assert configuration["sections"]["weather"]["forecast_last_attempt_at"].startswith("2026-01-16T01:00")


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
    assert initialised_store.planning.latest_forecast()
