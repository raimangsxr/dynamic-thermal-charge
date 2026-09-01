"""Weather provider boundary and deterministic simulated provider."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import json
import logging
import math
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .models import AemetConfig, SimulatedForecastConfig, WeatherConfig, WeatherWatchdogConfig
from .system_settings import WeatherSystemSettings


logger = logging.getLogger(__name__)
AEMET_BASE_URL = "https://opendata.aemet.es/opendata"
JsonObject = Any
HttpGet = Callable[[str, Mapping[str, str], float], JsonObject]


@dataclass(frozen=True)
class HourlyForecastPoint:
    """One validated outdoor temperature at an instant.

    A point may be marked as interpolated when a plan had to use the daily
    summary because the hourly provider did not cover that interval.
    """

    timestamp: datetime
    temperature_c: float
    interpolated: bool = False

    @property
    def at(self) -> datetime:
        """Compatibility alias for callers that describe points by ``at``."""
        return self.timestamp

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("hourly forecast timestamp requires a timezone")
        if not math.isfinite(self.temperature_c):
            raise ValueError("hourly forecast temperature must be finite")


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
    hourly_points: tuple[HourlyForecastPoint, ...] = ()


class WeatherProvider(Protocol):
    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        """Return the outdoor forecast used to calculate charge demand."""


class SimulatedWeatherProvider:
    def __init__(
        self, config: SimulatedForecastConfig, timezone_name: str = "UTC"
    ) -> None:
        self._config = config
        self._timezone = ZoneInfo(timezone_name)

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
            hourly_points=tuple(
                HourlyForecastPoint(
                    datetime.combine(forecast_date, datetime.min.time(), tzinfo=self._timezone)
                    + timedelta(hours=hour),
                    self._config.average_temperature_c,
                )
                for hour in range(48)
            ),
        )


class WeatherProviderError(RuntimeError):
    """A weather forecast could not be obtained or interpreted."""


@dataclass(frozen=True)
class ForecastCycleState:
    """Persistent state for one local AEMET retrieval cycle."""

    local_date: date
    scheduled_at: datetime
    attempt: int = 0
    next_retry_at: datetime | None = None
    last_error: str | None = None
    stale: bool = False
    completed: bool = False


class DailyAemetCycle:
    """Schedule one daily request and exactly five hourly retries.

    The state is deliberately serialisable and injectable; a process restart can
    restore it without resetting the retry count or fabricating a forecast.
    """

    MAX_RETRIES = 5

    def __init__(self, query_hour: int = 12, timezone_name: str = "UTC") -> None:
        if not 0 <= query_hour <= 23:
            raise ValueError("query_hour must be between 0 and 23")
        self._query_hour = query_hour
        self._zone = ZoneInfo(timezone_name)

    def initial_state(self, local_date: date) -> ForecastCycleState:
        scheduled = datetime.combine(local_date, datetime.min.time(), tzinfo=self._zone).replace(hour=self._query_hour)
        return ForecastCycleState(local_date=local_date, scheduled_at=scheduled)

    @property
    def timezone(self) -> ZoneInfo:
        return self._zone

    def due(self, state: ForecastCycleState, now: datetime) -> bool:
        moment = now.astimezone(self._zone)
        return (not state.completed) and ((state.attempt == 0 and moment >= state.scheduled_at) or state.next_retry_at is not None and moment >= state.next_retry_at)

    def success(self, state: ForecastCycleState) -> ForecastCycleState:
        return replace(state, next_retry_at=None, last_error=None, stale=False, completed=True)

    def failure(self, state: ForecastCycleState, now: datetime, error: str) -> ForecastCycleState:
        attempt = state.attempt + 1
        if attempt > self.MAX_RETRIES:
            return replace(state, attempt=attempt, next_retry_at=None, last_error=error, stale=True, completed=True)
        return replace(state, attempt=attempt, next_retry_at=now.astimezone(timezone.utc) + timedelta(hours=1), last_error=error, stale=True)


class AemetWeatherProvider:
    def __init__(
        self,
        config: AemetConfig,
        api_key: str,
        http_get: HttpGet | None = None,
        timezone_name: str = "UTC",
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._http_get = http_get or _http_get_json
        self._timezone = ZoneInfo(timezone_name)

    def forecast_for(self, forecast_date: date) -> OutdoorForecast:
        if not self._api_key:
            raise WeatherProviderError(
                f"AEMET API key is missing ({self._config.api_key_env})"
            )
        endpoint = (
            f"{AEMET_BASE_URL}/api/prediccion/especifica/municipio/horaria/"
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
        return _parse_aemet_forecast(payload, forecast_date, self._timezone)


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
    api_key: str | None = None,
    http_get: HttpGet | None = None,
    timezone_name: str = "UTC",
) -> WeatherProvider:
    if config.provider == "simulated":
        assert config.simulated is not None
        return SimulatedWeatherProvider(config.simulated, timezone_name)

    assert config.aemet is not None
    primary = AemetWeatherProvider(
        config.aemet,
        api_key=api_key or "",
        http_get=http_get,
        timezone_name=timezone_name,
    )
    if config.fallback is None:
        return primary
    return FallbackWeatherProvider(
        primary,
        SimulatedWeatherProvider(config.fallback, timezone_name),
    )


def weather_config_from_system(settings: WeatherSystemSettings) -> WeatherConfig:
    """Build the functional weather configuration from canonical system settings.

    The AEMET key is deliberately not part of this object. The system
    repository owns the secret and callers inject it only into the provider.
    """
    aemet = None
    if settings.provider == "aemet":
        aemet = AemetConfig(
            municipality_code=settings.municipality_code or "",
            api_key_env="AEMET_API_KEY",
            timeout_seconds=settings.timeout_seconds,
        )
    return WeatherConfig(
        provider=settings.provider,
        simulated=SimulatedForecastConfig(
            average_temperature_c=settings.simulated_average_temperature_c,
            minimum_temperature_c=settings.simulated_minimum_temperature_c,
        ),
        aemet=aemet,
        fallback=SimulatedForecastConfig(
            average_temperature_c=settings.fallback_average_temperature_c,
            minimum_temperature_c=settings.fallback_minimum_temperature_c,
        ),
        watchdog=WeatherWatchdogConfig(
            retry_minutes=settings.retry_minutes,
            refresh_minutes=settings.refresh_minutes,
        ),
    )


def build_weather_provider_from_system(
    settings: WeatherSystemSettings,
    *,
    api_key: str | None = None,
    http_get: HttpGet | None = None,
    timezone_name: str = "UTC",
) -> WeatherProvider:
    """Compose the provider from canonical settings and its managed secret."""
    return build_weather_provider(
        weather_config_from_system(settings),
        api_key=api_key,
        http_get=http_get,
        timezone_name=timezone_name,
    )


def _parse_aemet_forecast(
    payload: Any,
    forecast_date: date,
    local_timezone: timezone | ZoneInfo = timezone.utc,
) -> OutdoorForecast:
    try:
        municipality = payload[0]
        days = municipality["prediccion"]["dia"]
        day = next(item for item in days if item["fecha"].startswith(forecast_date.isoformat()))
    except (IndexError, KeyError, StopIteration, TypeError, ValueError) as exc:
        raise WeatherProviderError(
            f"AEMET forecast has no valid temperatures for {forecast_date.isoformat()}"
        ) from exc
    daily_temperature = day.get("temperatura")
    minimum: float | None = None
    maximum: float | None = None
    if isinstance(daily_temperature, dict):
        try:
            minimum = float(daily_temperature["minima"])
            maximum = float(daily_temperature["maxima"])
        except (KeyError, TypeError, ValueError):
            minimum = maximum = None
    municipality_name = municipality.get("nombre")
    province = municipality.get("provincia")
    location_parts = [
        str(part) for part in (municipality_name, province) if part
    ]
    hourly_points = _parse_aemet_hourly_points(
        days, forecast_date, local_timezone
    )
    if hourly_points:
        temperatures = [
            point.temperature_c
            for point in hourly_points
            if point.timestamp.astimezone(local_timezone).date() == forecast_date
        ] or [point.temperature_c for point in hourly_points]
        # Keep the daily summary as the stable public value when AEMET sent it,
        # while deriving it for payloads that only contain hourly values.
        average = sum(temperatures) / len(temperatures)
        minimum = min(temperatures) if minimum is None else minimum
        maximum = max(temperatures) if maximum is None else maximum
    else:
        if minimum is None or maximum is None:
            raise WeatherProviderError(
                f"AEMET forecast has no valid temperatures for {forecast_date.isoformat()}"
            )
        average = (minimum + maximum) / 2
    return OutdoorForecast(
        date=forecast_date,
        average_temperature_c=average,
        minimum_temperature_c=minimum,
        maximum_temperature_c=maximum,
        source="aemet",
        location=", ".join(location_parts) or None,
        hourly_points=hourly_points,
    )


def _parse_aemet_hourly_points(
    days: Any,
    forecast_date: date,
    local_timezone: timezone | ZoneInfo,
) -> tuple[HourlyForecastPoint, ...]:
    """Normalize AEMET's list-shaped hourly temperatures.

    AEMET has returned both numeric ``hora`` values and ranges such as
    ``"03-04"`` over time. Invalid entries are ignored, but a list that has no
    valid temperature is rejected by the caller rather than silently becoming
    a zero-degree forecast.
    """
    if not isinstance(days, list):
        return ()
    points: list[HourlyForecastPoint] = []
    saw_hourly_payload = False
    for day in days:
        if not isinstance(day, dict):
            continue
        raw_temperatures = day.get("temperatura")
        if isinstance(raw_temperatures, list):
            items = raw_temperatures
            saw_hourly_payload = True
        elif isinstance(raw_temperatures, dict) and not {
            "minima", "maxima"
        }.intersection(raw_temperatures):
            items = [
                {"hora": hour, "value": value}
                for hour, value in raw_temperatures.items()
            ]
            saw_hourly_payload = True
        else:
            continue
        raw_date = str(day.get("fecha", ""))[:10]
        try:
            day_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if not forecast_date <= day_date < forecast_date + timedelta(days=2):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_value = item.get("value", item.get("valor", item.get("temperature")))
            raw_hour = item.get("hora", item.get("hour"))
            try:
                temperature = float(raw_value)
                hour = int(str(raw_hour).split("-")[0].strip())
                if not 0 <= hour <= 23 or not math.isfinite(temperature):
                    raise ValueError
                timestamp = datetime.combine(
                    day_date, datetime.min.time(), tzinfo=local_timezone
                ) + timedelta(hours=hour)
                points.append(HourlyForecastPoint(timestamp, temperature))
            except (TypeError, ValueError):
                continue
    if saw_hourly_payload and not points:
        raise WeatherProviderError(
            f"AEMET forecast has no valid hourly temperatures for {forecast_date.isoformat()}"
        )
    return tuple(sorted({(point.timestamp, point.temperature_c): point for point in points}.values(), key=lambda point: point.timestamp))


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
