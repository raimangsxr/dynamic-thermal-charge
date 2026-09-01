from datetime import date, datetime, timedelta, timezone
import logging

import pytest

from dynamic_thermal_charge.models import (
    AemetConfig,
    SimulatedForecastConfig,
    WeatherConfig,
)
from dynamic_thermal_charge.weather import (
    AemetWeatherProvider,
    HourlyForecastPoint,
    WeatherProviderError,
    _decode_json,
    build_weather_provider,
    future_forecast_points,
)


def aemet_payload():
    return [
        {
            "nombre": "Madrid",
            "provincia": "Madrid",
            "prediccion": {
                "dia": [
                    {
                        "fecha": "2026-01-15T00:00:00",
                        "temperatura": {"minima": 2, "maxima": 12},
                    }
                ]
            }
        }
    ]


def hourly_aemet_payload():
    return [{
        "nombre": "Madrid",
        "provincia": "Madrid",
        "prediccion": {"dia": [
            {"fecha": "2026-01-15T00:00:00", "temperatura": [
                {"hora": 0, "value": "2"}, {"hora": 1, "value": "4"},
                {"hora": 2, "value": "bad"}, {"hora": 3},
            ]},
            {"fecha": "2026-01-16T00:00:00", "temperatura": [
                {"hora": "00-01", "value": "8"},
            ]},
        ]},
    }]


def test_aemet_fetches_envelope_and_daily_data() -> None:
    calls = []

    def http_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        if len(calls) == 1:
            return {
                "estado": 200,
                "descripcion": "Éxito",
                "datos": "https://opendata.aemet.es/data/forecast.json",
            }
        return aemet_payload()

    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079", timeout_seconds=7),
        api_key="secret-key",
        http_get=http_get,
    )

    result = provider.forecast_for(date(2026, 1, 15))

    assert result.average_temperature_c == 7
    assert result.minimum_temperature_c == 2
    assert result.maximum_temperature_c == 12
    assert result.source == "aemet"
    assert result.location == "Madrid, Madrid"
    assert calls[0][0].endswith("/28079")
    assert calls[0][1]["api_key"] == "secret-key"
    assert "api_key" not in calls[1][1]
    assert calls[0][2] == 7


def test_aemet_fetches_hourly_endpoint_and_normalizes_valid_points() -> None:
    calls = []

    def http_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {"estado": 200, "datos": "https://data.example/hourly.json"} if len(calls) == 1 else hourly_aemet_payload()

    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=http_get,
    )
    result = provider.forecast_for(date(2026, 1, 15))

    assert calls[0][0].endswith("/prediccion/especifica/municipio/horaria/28079")
    assert calls[0][1]["api_key"] == "secret-key"
    assert "api_key" not in calls[1][1]
    assert [point.temperature_c for point in result.hourly_points] == [2, 4, 8]
    assert result.average_temperature_c == pytest.approx(3)
    assert result.minimum_temperature_c == 2
    assert result.maximum_temperature_c == 4


def test_aemet_accepts_period_and_nested_dato_hourly_shape() -> None:
    payload = [{
        "nombre": "Madrid",
        "provincia": "Madrid",
        "prediccion": {"dia": [{
            "fecha": "2026-01-15T00:00:00",
            "temperatura": {
                "minima": 2,
                "maxima": 12,
                "dato": [
                    {"periodo": "00", "value": "2"},
                    {"periodo": "01-02", "value": "4"},
                ],
            },
        }]},
    }]
    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=lambda url, headers, timeout: {"estado": 200, "datos": "https://data.example/hourly.json"} if headers.get("api_key") else payload,
    )

    result = provider.forecast_for(date(2026, 1, 15))

    assert [point.temperature_c for point in result.hourly_points] == [2, 4]


def test_aemet_rejects_an_hourly_payload_without_usable_temperature() -> None:
    payload = [{"prediccion": {"dia": [{
        "fecha": "2026-01-15T00:00:00",
        "temperatura": [{"hora": 1, "value": "not-a-number"}, {"hora": 2}],
    }]}}]
    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=lambda url, headers, timeout: {"estado": 200, "datos": "https://data.example/hourly.json"} if headers.get("api_key") else payload,
    )
    with pytest.raises(WeatherProviderError, match="hourly"):
        provider.forecast_for(date(2026, 1, 15))


def test_simulated_forecast_has_a_deterministic_48_hour_series() -> None:
    config = WeatherConfig(
        provider="simulated",
        simulated=SimulatedForecastConfig(average_temperature_c=8, minimum_temperature_c=3),
    )
    first = build_weather_provider(config).forecast_for(date(2026, 1, 15))
    second = build_weather_provider(config).forecast_for(date(2026, 1, 15))
    assert first.hourly_points == second.hourly_points
    assert len(first.hourly_points) == 48
    assert first.hourly_points[0].timestamp == datetime(2026, 1, 15, tzinfo=first.hourly_points[0].timestamp.tzinfo)


def test_aemet_persists_all_hourly_days_in_payload() -> None:
    payload = [{
        "nombre": "Madrid",
        "provincia": "Madrid",
        "prediccion": {"dia": [
            {"fecha": "2026-01-15T00:00:00", "temperatura": [{"hora": 22, "value": "6"}]},
            {"fecha": "2026-01-16T00:00:00", "temperatura": [{"hora": 0, "value": "4"}]},
            {"fecha": "2026-01-17T00:00:00", "temperatura": [{"hora": 0, "value": "2"}]},
        ]},
    }]
    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=lambda url, headers, timeout: {"estado": 200, "datos": "https://data.example/hourly.json"} if headers.get("api_key") else payload,
    )

    result = provider.forecast_for(date(2026, 1, 15))

    assert [point.temperature_c for point in result.hourly_points] == [6, 4, 2]


def test_aemet_accepts_hourly_payload_starting_on_next_day() -> None:
    payload = [{
        "nombre": "Madrid",
        "provincia": "Madrid",
        "prediccion": {"dia": [
            {
                "fecha": "2026-01-16T00:00:00",
                "temperatura": [
                    {"hora": 0, "value": "3"},
                    {"hora": 1, "value": "5"},
                ],
            },
            {"fecha": "2026-01-17T00:00:00", "temperatura": [{"hora": 0, "value": "1"}]},
        ]},
    }]
    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=lambda url, headers, timeout: {"estado": 200, "datos": "https://data.example/hourly.json"} if headers.get("api_key") else payload,
    )

    result = provider.forecast_for(date(2026, 1, 15))

    assert [point.temperature_c for point in result.hourly_points] == [3, 5, 1]
    assert result.average_temperature_c == pytest.approx(3)
    assert result.minimum_temperature_c == 1
    assert result.maximum_temperature_c == 5


def test_future_forecast_points_drop_hours_before_current_hour() -> None:
    now = datetime(2026, 9, 2, 22, 30, tzinfo=timezone.utc)
    points = (
        HourlyForecastPoint(datetime(2026, 9, 2, 20, tzinfo=timezone.utc), 10),
        HourlyForecastPoint(datetime(2026, 9, 2, 21, tzinfo=timezone.utc), 11),
        HourlyForecastPoint(datetime(2026, 9, 2, 22, tzinfo=timezone.utc), 12),
        HourlyForecastPoint(datetime(2026, 9, 3, 0, tzinfo=timezone.utc), 8),
    )

    filtered = future_forecast_points(points, now)

    assert [point.temperature_c for point in filtered] == [12, 8]


def test_aemet_rejects_missing_forecast_day() -> None:
    responses = iter(
        [
            {"estado": 200, "datos": "https://opendata.aemet.es/data.json"},
            aemet_payload(),
        ]
    )
    provider = AemetWeatherProvider(
        AemetConfig(municipality_code="28079"),
        api_key="secret-key",
        http_get=lambda *_: next(responses),
    )

    with pytest.raises(WeatherProviderError, match="2026-01-16"):
        provider.forecast_for(date(2026, 1, 16))


def test_uses_fallback_when_aemet_key_is_missing(caplog) -> None:
    config = WeatherConfig(
        provider="aemet",
        aemet=AemetConfig(municipality_code="28079"),
        fallback=SimulatedForecastConfig(
            average_temperature_c=8,
            minimum_temperature_c=3,
        ),
    )
    provider = build_weather_provider(config, api_key=None)

    with caplog.at_level(logging.WARNING):
        result = provider.forecast_for(date(2026, 1, 15))

    assert result.source == "simulated"
    assert result.average_temperature_c == 8
    assert result.minimum_temperature_c == 3
    assert result.maximum_temperature_c == 13
    assert "using configured fallback" in caplog.text


def test_fails_without_key_or_fallback() -> None:
    config = WeatherConfig(
        provider="aemet",
        aemet=AemetConfig(municipality_code="28079"),
    )
    provider = build_weather_provider(config, api_key=None)

    with pytest.raises(WeatherProviderError, match="AEMET_API_KEY"):
        provider.forecast_for(date(2026, 1, 15))


def test_decodes_aemet_legacy_iso_8859_15_json() -> None:
    body = '{"descripcion": "Predicción válida", "estado": 200}'.encode(
        "iso-8859-15"
    )

    result = _decode_json(body, None)

    assert result == {"descripcion": "Predicción válida", "estado": 200}


def test_prefers_utf_8_when_aemet_declares_legacy_charset() -> None:
    body = '{"provincia": "A Coruña"}'.encode("utf-8")

    result = _decode_json(body, "iso-8859-15")

    assert result == {"provincia": "A Coruña"}


def test_rejects_payload_that_is_not_json() -> None:
    with pytest.raises(WeatherProviderError, match="supported encoding"):
        _decode_json(b"\xff\x00not-json", "utf-8")
