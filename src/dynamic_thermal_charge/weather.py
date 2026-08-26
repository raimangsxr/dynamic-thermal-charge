"""Weather provider boundary and deterministic simulated provider."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import json
import logging
import os
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AemetConfig, SimulatedForecastConfig, WeatherConfig


logger = logging.getLogger(__name__)
AEMET_BASE_URL = "https://opendata.aemet.es/opendata"
JsonObject = Any
HttpGet = Callable[[str, Mapping[str, str], float], JsonObject]


@dataclass(frozen=True)
class OutdoorForecast:
    date: date
    average_temperature_c: float
    minimum_temperature_c: float
    maximum_temperature_c: float
    source: str
    location: str | None = None
    #: True when this forecast came from the configured fallback rather than the
    #: primary provider. The history records it as ``fallback`` so an audit can
    #: answer "did the real provider work that night" (FR-017).
    from_fallback: bool = False


class WeatherProvider(Protocol):
    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        """Return the outdoor forecast used to calculate charge demand."""


class SimulatedWeatherProvider:
    def __init__(self, config: SimulatedForecastConfig) -> None:
        self._config = config

    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        maximum_temperature_c = (
            2 * self._config.average_temperature_c
            - self._config.minimum_temperature_c
        )
        return OutdoorForecast(
            date=forecast_date,
            average_temperature_c=self._config.average_temperature_c,
            minimum_temperature_c=self._config.minimum_temperature_c,
            maximum_temperature_c=maximum_temperature_c,
            source="simulated",
        )


class WeatherProviderError(RuntimeError):
    """A weather forecast could not be obtained or interpreted."""


class AemetWeatherProvider:
    def __init__(
        self,
        config: AemetConfig,
        api_key: str,
        http_get: HttpGet | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._http_get = http_get or _http_get_json

    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        if not self._api_key:
            raise WeatherProviderError(
                f"AEMET API key is missing ({self._config.api_key_env})"
            )
        endpoint = (
            f"{AEMET_BASE_URL}/api/prediccion/especifica/municipio/diaria/"
            f"{self._config.municipality_code}"
        )
        envelope = self._http_get(
            endpoint,
            {"api_key": self._api_key, "Accept": "application/json"},
            self._config.timeout_seconds,
        )
        if not isinstance(envelope, dict) or envelope.get("estado") != 200:
            description = (
                envelope.get("descripcion", "invalid response")
                if isinstance(envelope, dict)
                else "invalid response"
            )
            raise WeatherProviderError(f"AEMET request failed: {description}")
        data_url = envelope.get("datos")
        if not isinstance(data_url, str) or not data_url.startswith("https://"):
            raise WeatherProviderError("AEMET response does not contain a secure data URL")

        payload = self._http_get(
            data_url,
            {"Accept": "application/json"},
            self._config.timeout_seconds,
        )
        return _parse_aemet_forecast(payload, forecast_date)


class FallbackWeatherProvider:
    def __init__(
        self,
        primary: WeatherProvider,
        fallback: WeatherProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        try:
            return self._primary.forecast_for(forecast_date)
        except WeatherProviderError as exc:
            logger.warning("Weather provider failed; using configured fallback: %s", exc)
            return replace(
                self._fallback.forecast_for(forecast_date), from_fallback=True
            )


def build_weather_provider(
    config: WeatherConfig,
    environ: Mapping[str, str] | None = None,
    http_get: HttpGet | None = None,
) -> WeatherProvider:
    if config.provider == "simulated":
        assert config.simulated is not None
        return SimulatedWeatherProvider(config.simulated)

    assert config.aemet is not None
    environment = os.environ if environ is None else environ
    primary = AemetWeatherProvider(
        config.aemet,
        api_key=environment.get(config.aemet.api_key_env, ""),
        http_get=http_get,
    )
    if config.fallback is None:
        return primary
    return FallbackWeatherProvider(
        primary,
        SimulatedWeatherProvider(config.fallback),
    )


def _parse_aemet_forecast(payload: Any, forecast_date: date) -> OutdoorForecast:
    try:
        municipality = payload[0]
        days = municipality["prediccion"]["dia"]
        day = next(item for item in days if item["fecha"].startswith(forecast_date.isoformat()))
        minimum = float(day["temperatura"]["minima"])
        maximum = float(day["temperatura"]["maxima"])
    except (IndexError, KeyError, StopIteration, TypeError, ValueError) as exc:
        raise WeatherProviderError(
            f"AEMET forecast has no valid temperatures for {forecast_date.isoformat()}"
        ) from exc
    municipality_name = municipality.get("nombre")
    province = municipality.get("provincia")
    location_parts = [
        str(part) for part in (municipality_name, province) if part
    ]
    return OutdoorForecast(
        date=forecast_date,
        average_temperature_c=(minimum + maximum) / 2,
        minimum_temperature_c=minimum,
        maximum_temperature_c=maximum,
        source="aemet",
        location=", ".join(location_parts) or None,
    )


def _http_get_json(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Any:
    request = Request(
        url,
        headers={**headers, "User-Agent": "dynamic-thermal-charge/0.1"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            charset = response.headers.get_content_charset()
            return _decode_json(body, charset)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise WeatherProviderError(f"weather HTTP request failed: {exc}") from exc


def _decode_json(body: bytes, declared_charset: str | None) -> Any:
    """Decode JSON while accommodating the legacy charset returned by AEMET."""
    charsets = tuple(
        dict.fromkeys(
            charset
            # Some AEMET responses declare a legacy charset while their body is
            # actually UTF-8. UTF-8 must therefore be attempted first.
            for charset in ("utf-8", declared_charset, "iso-8859-15")
            if charset
        )
    )
    errors: list[Exception] = []
    for charset in charsets:
        try:
            return json.loads(body.decode(charset))
        except (LookupError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(exc)
    raise WeatherProviderError(
        "weather response is not valid JSON in a supported encoding"
    ) from errors[-1]
