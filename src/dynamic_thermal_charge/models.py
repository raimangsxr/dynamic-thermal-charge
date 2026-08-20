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
class Heater:
    id: str
    name: str
    power_w: int
    full_charge_minutes: int
    target_charge: float
    priority: int
    output: OutputConfig
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
