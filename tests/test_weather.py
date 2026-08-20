from datetime import date
import logging

import pytest

from dynamic_thermal_charge.models import (
    AemetConfig,
    SimulatedForecastConfig,
    WeatherConfig,
)
from dynamic_thermal_charge.weather import (
    AemetWeatherProvider,
    WeatherProviderError,
    _decode_json,
    build_weather_provider,
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
    provider = build_weather_provider(config, environ={})

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
    provider = build_weather_provider(config, environ={})

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
