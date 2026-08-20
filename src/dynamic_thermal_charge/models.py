"""Domain models without hardware or infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass


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
class AppConfig:
    site: SiteConfig
    heaters: tuple[Heater, ...]
    logging: LoggingConfig = LoggingConfig()

    def __post_init__(self) -> None:
        ids = [heater.id for heater in self.heaters]
        if len(ids) != len(set(ids)):
            raise ValueError("heater ids must be unique")
