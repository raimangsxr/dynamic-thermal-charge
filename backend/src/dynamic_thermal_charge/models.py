"""Domain models without hardware or infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import math
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
    thermal_loss_c_per_hour: float = 0.0
    room_inertia_hours: float = 8.0
    outdoor_loss_per_hour: float = 0.08
    emission_c_per_hour: float = 1.0

    def __post_init__(self) -> None:
        if self.design_outdoor_temperature_c >= self.target_temperature_c:
            raise ValueError("design outdoor temperature must be below target temperature")
        if self.thermal_factor <= 0:
            raise ValueError("thermal_factor must be positive")
        if not 0 <= self.min_charge <= self.max_charge <= 1:
            raise ValueError("thermal charge limits must satisfy 0 <= min <= max <= 1")
        if not math.isfinite(self.thermal_loss_c_per_hour) or self.thermal_loss_c_per_hour < 0:
            raise ValueError("thermal_loss_c_per_hour must be finite and non-negative")
        if self.room_inertia_hours <= 0:
            raise ValueError("room_inertia_hours must be positive")
        if not 0 <= self.outdoor_loss_per_hour <= 1:
            raise ValueError("outdoor_loss_per_hour must be between 0 and 1")
        if self.emission_c_per_hour < 0:
            raise ValueError("emission_c_per_hour must be non-negative")


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
    indoor_topic: str | None = None
    temperature_topic: str | None = None
    target_temperature_topic: str | None = None
    stored_charge_topic: str | None = None
    reserve_percent: float = 0.0
    demand_factor: float = 1.0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("heater id cannot be empty")
        if self.power_w <= 0:
            raise ValueError(f"heater {self.id}: power must be positive")
        if self.full_charge_minutes <= 0:
            raise ValueError(f"heater {self.id}: full charge time must be positive")
        if not 0 <= self.target_charge <= 1:
            raise ValueError(f"heater {self.id}: target_charge must be between 0 and 1")
        if self.indoor_topic is not None:
            topic = self.indoor_topic.strip()
            object.__setattr__(self, "indoor_topic", topic or None)
        for field_name in (
            "temperature_topic",
            "target_temperature_topic",
            "stored_charge_topic",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, value.strip() or None)
        if self.reserve_percent < 0:
            raise ValueError(f"heater {self.id}: reserve_percent must be non-negative")
        if not math.isfinite(self.demand_factor) or self.demand_factor <= 0:
            raise ValueError(f"heater {self.id}: demand_factor must be positive")

    @property
    def charge_power_kw(self) -> float:
        return self.power_w / 1000

    @property
    def full_charge_time_hours(self) -> float:
        return self.full_charge_minutes / 60

    @property
    def capacity_kwh(self) -> float:
        return self.charge_power_kw * self.full_charge_time_hours

    @property
    def requested_charge_minutes(self) -> int:
        return round(
            self.full_charge_minutes
            * (self.target_charge + self.reserve_percent / 100)
        )


@dataclass(frozen=True)
class SiteConfig:
    max_total_power_w: int
    slot_minutes: int
    window_minutes: int
    indoor_max_age_minutes: int = 30
    indoor_min_plausible_c: float = -20.0
    indoor_max_plausible_c: float = 50.0
    replan_minutes: int = 30
    forecast_horizon_hours: int = 48
    aemet_query_hour: int = 12
    max_heating_power_w: int | None = None
    design_indoor_temperature_c: float = 21.0
    design_outdoor_temperature_c: float = 0.0
    feedback_horizon_hours: float = 6.0

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
        if self.indoor_max_age_minutes <= 0:
            raise ValueError("indoor_max_age_minutes must be positive")
        if self.indoor_min_plausible_c >= self.indoor_max_plausible_c:
            raise ValueError(
                "indoor plausible range must satisfy minimum < maximum"
            )
        if self.replan_minutes <= 0:
            raise ValueError("replan_minutes must be positive")
        if self.forecast_horizon_hours <= 0:
            raise ValueError("forecast_horizon_hours must be positive")
        if not 0 <= self.aemet_query_hour <= 23:
            raise ValueError("aemet_query_hour must be between 0 and 23")
        if self.max_heating_power_w is not None and self.max_heating_power_w <= 0:
            raise ValueError("max_heating_power_w must be positive")
        if self.design_indoor_temperature_c <= self.design_outdoor_temperature_c:
            raise ValueError("design indoor temperature must exceed design outdoor temperature")
        if self.feedback_horizon_hours <= 0:
            raise ValueError("feedback_horizon_hours must be positive")

    @property
    def contracted_power_kw(self) -> float:
        return self.max_total_power_w / 1000

    @property
    def max_heating_power_kw(self) -> float:
        return (self.max_heating_power_w or self.max_total_power_w) / 1000


@dataclass(frozen=True)
class IndoorReading:
    heater_id: str
    celsius: float
    received_at: datetime

    def __post_init__(self) -> None:
        if not self.heater_id:
            raise ValueError("indoor reading heater id cannot be empty")
        if self.received_at.tzinfo is None:
            raise ValueError("indoor reading received_at requires a timezone")


@dataclass(frozen=True)
class ChargeConstraint:
    """A recurring desired stored-charge result for one accumulator."""

    heater_id: str
    target_charge: float
    at: time
    weekdays: tuple[int, ...] = tuple(range(7))
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.heater_id:
            raise ValueError("constraint heater_id cannot be empty")
        if not 0 <= self.target_charge <= 1:
            raise ValueError("constraint target_charge must be between 0 and 1")
        if self.at.second or self.at.microsecond or self.at.tzinfo is not None:
            raise ValueError("constraint at must be a wall-clock HH:MM time")
        if not self.weekdays or any(day not in range(7) for day in self.weekdays):
            raise ValueError("constraint weekdays must contain values from 0 to 6")
        if tuple(self.weekdays) != tuple(sorted(set(self.weekdays))):
            raise ValueError("constraint weekdays must be sorted and unique")


@dataclass(frozen=True)
class ChargeTelemetry:
    """Latest independent MQTT values for one accumulator."""

    heater_id: str
    temperature_c: float | None = None
    target_temperature_c: float | None = None
    stored_charge_percent: float | None = None
    temperature_received_at: datetime | None = None
    target_received_at: datetime | None = None
    stored_charge_received_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.heater_id:
            raise ValueError("telemetry heater_id cannot be empty")
        for value in (
            self.temperature_c,
            self.target_temperature_c,
            self.stored_charge_percent,
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError("telemetry values must be finite")
        if self.stored_charge_percent is not None and not 0 <= self.stored_charge_percent <= 100:
            raise ValueError("stored charge must be between 0 and 100")
        for received_at in (
            self.temperature_received_at,
            self.target_received_at,
            self.stored_charge_received_at,
        ):
            if received_at is not None and received_at.tzinfo is None:
                raise ValueError("telemetry timestamps require a timezone")


@dataclass(frozen=True)
class TelemetryHealth:
    heater_id: str
    state: str
    missing_fields: tuple[str, ...] = ()
    oldest_age_seconds: float | None = None


@dataclass(frozen=True)
class TelemetrySnapshot:
    values: dict[str, ChargeTelemetry]
    health: dict[str, TelemetryHealth]


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"

    def __post_init__(self) -> None:
        normalized_level = self.level.upper()
        if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unsupported log level: {self.level}")
        object.__setattr__(self, "level", normalized_level)


@dataclass(frozen=True)
class RuntimeConfig:
    poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.poll_seconds <= 0:
            raise ValueError("runtime poll_seconds must be positive")


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

    def active_or_next_start(self, reference: datetime) -> datetime:
        zone = ZoneInfo(self.timezone)
        local_reference = (
            reference.replace(tzinfo=zone)
            if reference.tzinfo is None
            else reference.astimezone(zone)
        )
        for day_offset in (0, -1):
            candidate_date = local_reference.date() + timedelta(days=day_offset)
            if candidate_date.weekday() not in self.weekdays:
                continue
            candidate = datetime.combine(candidate_date, self.start_time, tzinfo=zone)
            if candidate <= local_reference < candidate + timedelta(
                minutes=self.window_minutes
            ):
                return candidate
        return self.next_start(local_reference)


DEFAULT_RETENTION_DAYS = 365


@dataclass(frozen=True)
class AppConfig:
    site: SiteConfig
    heaters: tuple[Heater, ...]
    logging: LoggingConfig = LoggingConfig()
    schedule: ScheduleConfig | None = None
    weather: WeatherConfig | None = None
    runtime: RuntimeConfig = RuntimeConfig()
    #: Days of history kept. ``None`` means unlimited. The default is
    #: conservative for the SD card of the deployment target.
    retention_days: int | None = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days <= 0:
            raise ValueError("retention_days must be positive or None for unlimited")
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
