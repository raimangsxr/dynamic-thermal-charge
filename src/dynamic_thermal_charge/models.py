"""Domain models without hardware or infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class OutputConfig:
    kind: str = "simulated"
    pin: int | None = None
    active_high: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {"simulated", "gpio"}:
            raise ValueError(f"unsupported output type: {self.kind}")
        if self.kind == "gpio" and self.pin is None:
            raise ValueError("a GPIO output requires a BCM pin")
        if self.pin is not None and not 0 <= self.pin <= 27:
            raise ValueError("GPIO BCM pin must be between 0 and 27")


@dataclass(frozen=True)
class ThermalProfile:
    target_temperature_c: float
    design_outdoor_temperature_c: float
    thermal_factor: float = 1.0
    min_charge: float = 0.0
    max_charge: float = 1.0

    def __post_init__(self) -> None:
        if self.design_outdoor_temperature_c >= self.target_temperature_c:
            raise ValueError("design outdoor temperature must be below target temperature")
        if self.thermal_factor <= 0:
            raise ValueError("thermal_factor must be positive")
        if not 0 <= self.min_charge <= self.max_charge <= 1:
            raise ValueError("thermal charge limits must satisfy 0 <= min <= max <= 1")


@dataclass(frozen=True)
class Heater:
    id: str
    name: str
    power_w: int
    full_charge_minutes: int
    target_charge: float
    priority: int
    output: OutputConfig
    thermal: ThermalProfile | None = None
    model: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("heater id cannot be empty")
        if self.power_w <= 0:
            raise ValueError(f"heater {self.id}: power must be positive")
        if self.full_charge_minutes <= 0:
            raise ValueError(f"heater {self.id}: full charge time must be positive")
        if not 0 <= self.target_charge <= 1:
            raise ValueError(f"heater {self.id}: target_charge must be between 0 and 1")

    @property
    def requested_charge_minutes(self) -> int:
        return round(self.full_charge_minutes * self.target_charge)


@dataclass(frozen=True)
class SiteConfig:
    max_total_power_w: int
    slot_minutes: int
    window_minutes: int

    def __post_init__(self) -> None:
        if self.max_total_power_w <= 0:
            raise ValueError("max_total_power must be positive")
        if self.slot_minutes <= 0:
            raise ValueError("slot_minutes must be positive")
        if self.slot_minutes > 60 or 60 % self.slot_minutes:
            raise ValueError("slot_minutes must be a divisor of 60")
        if self.window_minutes <= 0:
            raise ValueError("window_hours must be positive")
        if self.window_minutes % self.slot_minutes:
            raise ValueError("the charge window must contain a whole number of slots")


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"

    def __post_init__(self) -> None:
        normalized_level = self.level.upper()
        if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unsupported log level: {self.level}")
        object.__setattr__(self, "level", normalized_level)


@dataclass(frozen=True)
class SimulatedForecastConfig:
    average_temperature_c: float
    minimum_temperature_c: float

    def __post_init__(self) -> None:
        if self.minimum_temperature_c > self.average_temperature_c:
            raise ValueError("minimum temperature cannot exceed average temperature")


@dataclass(frozen=True)
class AemetConfig:
    municipality_code: str
    api_key_env: str = "AEMET_API_KEY"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if len(self.municipality_code) != 5 or not self.municipality_code.isdigit():
            raise ValueError("AEMET municipality_code must contain 5 digits")
        if not self.api_key_env:
            raise ValueError("AEMET api_key_env cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("AEMET timeout_seconds must be positive")


@dataclass(frozen=True)
class WeatherWatchdogConfig:
    retry_minutes: int = 15
    refresh_minutes: int = 180

    def __post_init__(self) -> None:
        if self.retry_minutes <= 0:
            raise ValueError("weather watchdog retry_minutes must be positive")
        if self.refresh_minutes <= 0:
            raise ValueError("weather watchdog refresh_minutes must be positive")


@dataclass(frozen=True)
class WeatherConfig:
    provider: str
    simulated: SimulatedForecastConfig | None = None
    aemet: AemetConfig | None = None
    fallback: SimulatedForecastConfig | None = None
    watchdog: WeatherWatchdogConfig = WeatherWatchdogConfig()

    def __post_init__(self) -> None:
        if self.provider not in {"simulated", "aemet"}:
            raise ValueError(f"unsupported weather provider: {self.provider}")
        if self.provider == "simulated" and self.simulated is None:
            raise ValueError("simulated weather provider requires simulated values")
        if self.provider == "aemet" and self.aemet is None:
            raise ValueError("AEMET weather provider requires AEMET configuration")


@dataclass(frozen=True)
class ScheduleConfig:
    timezone: str
    start_time: time
    end_time: time
    weekdays: tuple[int, ...]

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        if not self.weekdays:
            raise ValueError("schedule weekdays cannot be empty")
        if any(day not in range(7) for day in self.weekdays):
            raise ValueError("schedule weekdays must be between 0 and 6")
        if self.start_time == self.end_time:
            raise ValueError("schedule start_time and end_time cannot be equal")

    @property
    def window_minutes(self) -> int:
        anchor = date(2000, 1, 1)
        start = datetime.combine(anchor, self.start_time)
        end = datetime.combine(anchor, self.end_time)
        if end <= start:
            end += timedelta(days=1)
        return round((end - start).total_seconds() / 60)

    def next_start(self, reference: datetime) -> datetime:
        zone = ZoneInfo(self.timezone)
        if reference.tzinfo is None:
            local_reference = reference.replace(tzinfo=zone)
        else:
            local_reference = reference.astimezone(zone)

        for day_offset in range(8):
            candidate_date = local_reference.date() + timedelta(days=day_offset)
            if candidate_date.weekday() not in self.weekdays:
                continue
            candidate = datetime.combine(candidate_date, self.start_time, tzinfo=zone)
            if candidate >= local_reference:
                return candidate
        raise ValueError("schedule has no next start in the configured week")


@dataclass(frozen=True)
class AppConfig:
    site: SiteConfig
    heaters: tuple[Heater, ...]
    logging: LoggingConfig = LoggingConfig()
    schedule: ScheduleConfig | None = None
    weather: WeatherConfig | None = None

    def __post_init__(self) -> None:
        ids = [heater.id for heater in self.heaters]
        if len(ids) != len(set(ids)):
            raise ValueError("heater ids must be unique")
        gpio_pins = [
            heater.output.pin
            for heater in self.heaters
            if heater.output.kind == "gpio" and heater.output.pin is not None
        ]
        if len(gpio_pins) != len(set(gpio_pins)):
            raise ValueError("GPIO BCM pins must be unique")
        if any(heater.thermal is not None for heater in self.heaters):
            if self.weather is None:
                raise ValueError("thermal profiles require a weather provider")
