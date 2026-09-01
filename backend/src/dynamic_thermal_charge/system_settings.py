"""Typed system configuration, independent of its persistence representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
import math
from typing import Any, Mapping, TypeVar


SYSTEM_CONFIGURATION_FORMAT_VERSION = 1


class ActivationPolicy(Enum):
    HOT = "hot"
    NEXT_CYCLE = "next_cycle"
    RESTART = "restart"


@dataclass(frozen=True)
class DatabaseSettings:
    driver: str = "sqlite"
    host: str | None = None
    port: int | None = None
    database: str | None = None
    tls: bool = True
    trusted_no_tls: bool = False

    def __post_init__(self) -> None:
        if self.driver not in {"sqlite", "postgresql"}:
            raise ValueError("database.driver must be sqlite or postgresql")
        if self.driver == "sqlite":
            if any((self.host, self.port, self.database)):
                raise ValueError("SQLite cannot contain remote connection fields")
            return
        if not self.host or not self.database:
            raise ValueError("PostgreSQL requires host and database")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("database.port must be between 1 and 65535")
        if not self.tls and not self.trusted_no_tls:
            raise ValueError("PostgreSQL without TLS requires trusted-network confirmation")


@dataclass(frozen=True)
class ApiSystemSettings:
    host: str = "127.0.0.1"
    port: int = 8080
    cors_origins: tuple[str, ...] = ()
    stale_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("api.host cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("api.port must be between 1 and 65535")
        if self.stale_seconds is not None and self.stale_seconds <= 0:
            raise ValueError("api.stale_seconds must be positive")
        if "*" in self.cors_origins:
            raise ValueError("api.cors_origins cannot contain '*'")


@dataclass(frozen=True)
class MqttSystemSettings:
    enabled: bool = False
    host: str | None = None
    port: int = 1883
    tls: bool = False
    prefix: str = "dtc"
    discovery_prefix: str = "homeassistant"
    publish_seconds: float = 15.0
    fixed_temperature_c: float = 20.0
    fixed_target_temperature_c: float = 21.0
    fixed_stored_charge_percent: float = 50.0
    fixed_indoor_temperature_c: float = 20.0

    def __post_init__(self) -> None:
        if self.enabled and not self.host:
            raise ValueError("mqtt.host is required when MQTT is enabled")
        if not 1 <= self.port <= 65535:
            raise ValueError("mqtt.port must be between 1 and 65535")
        if not self.prefix.strip("/") or not self.discovery_prefix.strip("/"):
            raise ValueError("MQTT prefixes cannot be empty")
        if self.publish_seconds <= 0:
            raise ValueError("mqtt.publish_seconds must be positive")
        for name, value in (
            ("fixed_temperature_c", self.fixed_temperature_c),
            ("fixed_target_temperature_c", self.fixed_target_temperature_c),
            ("fixed_indoor_temperature_c", self.fixed_indoor_temperature_c),
        ):
            if not math.isfinite(value) or not -50 <= value <= 80:
                raise ValueError(f"mqtt.{name} must be between -50 and 80")
        if (
            not math.isfinite(self.fixed_stored_charge_percent)
            or not 0 <= self.fixed_stored_charge_percent <= 100
        ):
            raise ValueError(
                "mqtt.fixed_stored_charge_percent must be between 0 and 100"
            )


@dataclass(frozen=True)
class WeatherSystemSettings:
    provider: str = "simulated"
    municipality_code: str | None = None
    timeout_seconds: float = 10.0
    simulated_average_temperature_c: float = 8.0
    simulated_minimum_temperature_c: float = 3.0
    fallback_average_temperature_c: float = 8.0
    fallback_minimum_temperature_c: float = 3.0
    retry_minutes: int = 15
    refresh_minutes: int = 180

    def __post_init__(self) -> None:
        if self.provider not in {"simulated", "aemet"}:
            raise ValueError("weather.provider must be simulated or aemet")
        if self.municipality_code is not None and (
            len(self.municipality_code) != 5 or not self.municipality_code.isdigit()
        ):
            raise ValueError("weather.municipality_code must contain 5 digits")
        if self.provider == "aemet" and not self.municipality_code:
            raise ValueError("weather.municipality_code is required for AEMET")
        if self.timeout_seconds <= 0:
            raise ValueError("weather.timeout_seconds must be positive")
        if self.simulated_minimum_temperature_c > self.simulated_average_temperature_c:
            raise ValueError(
                "weather simulated minimum temperature cannot exceed average temperature"
            )
        if self.fallback_minimum_temperature_c > self.fallback_average_temperature_c:
            raise ValueError(
                "weather fallback minimum temperature cannot exceed average temperature"
            )
        if self.retry_minutes <= 0:
            raise ValueError("weather.retry_minutes must be positive")
        if self.refresh_minutes <= 0:
            raise ValueError("weather.refresh_minutes must be positive")


@dataclass(frozen=True)
class OutputSystemSettings:
    driver: str = "simulated"

    def __post_init__(self) -> None:
        if self.driver not in {"simulated", "gpio"}:
            raise ValueError("output.driver must be simulated or gpio")


@dataclass(frozen=True)
class LoggingSystemSettings:
    level: str = "INFO"
    max_events: int = 1000

    def __post_init__(self) -> None:
        if self.level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("logging.level is invalid")
        if not 10 <= self.max_events <= 100_000:
            raise ValueError("logging.max_events must be between 10 and 100000")


@dataclass(frozen=True)
class OperationsSystemSettings:
    controller_poll_seconds: float = 5.0
    heartbeat_stale_multiplier: float = 3.0
    relay_test_lease_seconds: int = 30
    relay_test_state_poll_seconds: float = 1.0
    relay_test_lease_renew_seconds: float = 10.0
    retention_days: int | None = 365
    fallback_max_age_minutes: int = 1440

    def __post_init__(self) -> None:
        positive = {
            "controller_poll_seconds": self.controller_poll_seconds,
            "heartbeat_stale_multiplier": self.heartbeat_stale_multiplier,
            "relay_test_lease_seconds": self.relay_test_lease_seconds,
            "relay_test_state_poll_seconds": self.relay_test_state_poll_seconds,
            "relay_test_lease_renew_seconds": self.relay_test_lease_renew_seconds,
            "fallback_max_age_minutes": self.fallback_max_age_minutes,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"operations.{name} must be positive")
        if self.retention_days is not None and self.retention_days <= 0:
            raise ValueError("operations.retention_days must be positive or null")
        if self.relay_test_lease_renew_seconds >= self.relay_test_lease_seconds:
            raise ValueError("relay-test renewal must be shorter than its lease")


@dataclass(frozen=True)
class SystemConfiguration:
    database: DatabaseSettings = DatabaseSettings()
    api: ApiSystemSettings = ApiSystemSettings()
    mqtt: MqttSystemSettings = MqttSystemSettings()
    weather: WeatherSystemSettings = WeatherSystemSettings()
    output: OutputSystemSettings = OutputSystemSettings()
    logging: LoggingSystemSettings = LoggingSystemSettings()
    operations: OperationsSystemSettings = OperationsSystemSettings()

    def documents(self) -> dict[str, dict[str, Any]]:
        documents = asdict(self)
        documents["api"]["cors_origins"] = list(self.api.cors_origins)
        return documents

    @classmethod
    def from_documents(cls, documents: Mapping[str, Mapping[str, Any]]) -> "SystemConfiguration":
        api = dict(documents["api"])
        api["cors_origins"] = tuple(api.get("cors_origins", ()))
        return cls(
            database=_strict_build(DatabaseSettings, documents["database"]),
            api=_strict_build(ApiSystemSettings, api),
            mqtt=_strict_build(MqttSystemSettings, documents["mqtt"]),
            weather=_strict_build(WeatherSystemSettings, documents["weather"]),
            output=_strict_build(OutputSystemSettings, documents["output"]),
            logging=_strict_build(LoggingSystemSettings, documents["logging"]),
            operations=_strict_build(OperationsSystemSettings, documents["operations"]),
        )


SECTION_TYPES = {
    "database": DatabaseSettings,
    "api": ApiSystemSettings,
    "mqtt": MqttSystemSettings,
    "weather": WeatherSystemSettings,
    "output": OutputSystemSettings,
    "logging": LoggingSystemSettings,
    "operations": OperationsSystemSettings,
}

PUBLIC_SECTION_FIELDS = {
    name: frozenset(field.name for field in fields(section_type))
    for name, section_type in SECTION_TYPES.items()
}

ACTIVATION_POLICIES: dict[str, ActivationPolicy] = {
    "database.driver": ActivationPolicy.RESTART,
    "database.host": ActivationPolicy.RESTART,
    "database.port": ActivationPolicy.RESTART,
    "database.database": ActivationPolicy.RESTART,
    "database.tls": ActivationPolicy.RESTART,
    "database.trusted_no_tls": ActivationPolicy.RESTART,
    "api.host": ActivationPolicy.RESTART,
    "api.port": ActivationPolicy.RESTART,
    "api.cors_origins": ActivationPolicy.HOT,
    "api.stale_seconds": ActivationPolicy.HOT,
    "mqtt.enabled": ActivationPolicy.HOT,
    "mqtt.host": ActivationPolicy.HOT,
    "mqtt.port": ActivationPolicy.HOT,
    "mqtt.tls": ActivationPolicy.HOT,
    "mqtt.prefix": ActivationPolicy.HOT,
    "mqtt.discovery_prefix": ActivationPolicy.HOT,
    "mqtt.publish_seconds": ActivationPolicy.HOT,
    "mqtt.fixed_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "mqtt.fixed_target_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "mqtt.fixed_stored_charge_percent": ActivationPolicy.NEXT_CYCLE,
    "mqtt.fixed_indoor_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "weather.provider": ActivationPolicy.NEXT_CYCLE,
    "weather.municipality_code": ActivationPolicy.NEXT_CYCLE,
    "weather.timeout_seconds": ActivationPolicy.NEXT_CYCLE,
    "weather.simulated_average_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "weather.simulated_minimum_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "weather.fallback_average_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "weather.fallback_minimum_temperature_c": ActivationPolicy.NEXT_CYCLE,
    "weather.retry_minutes": ActivationPolicy.NEXT_CYCLE,
    "weather.refresh_minutes": ActivationPolicy.NEXT_CYCLE,
    "output.driver": ActivationPolicy.RESTART,
    "logging.level": ActivationPolicy.HOT,
    "logging.max_events": ActivationPolicy.HOT,
    "operations.controller_poll_seconds": ActivationPolicy.NEXT_CYCLE,
    "operations.heartbeat_stale_multiplier": ActivationPolicy.HOT,
    "operations.relay_test_lease_seconds": ActivationPolicy.HOT,
    "operations.relay_test_state_poll_seconds": ActivationPolicy.HOT,
    "operations.relay_test_lease_renew_seconds": ActivationPolicy.HOT,
    "operations.retention_days": ActivationPolicy.NEXT_CYCLE,
    "operations.fallback_max_age_minutes": ActivationPolicy.HOT,
}


_T = TypeVar("_T")


def _strict_build(model: type[_T], values: Mapping[str, Any]) -> _T:
    allowed = {field.name for field in fields(model)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(
            f"unknown {model.__name__} fields: {', '.join(sorted(unknown))}"
        )
    return model(**dict(values))


__all__ = [
    "ACTIVATION_POLICIES",
    "PUBLIC_SECTION_FIELDS",
    "SECTION_TYPES",
    "SYSTEM_CONFIGURATION_FORMAT_VERSION",
    "ActivationPolicy",
    "ApiSystemSettings",
    "DatabaseSettings",
    "LoggingSystemSettings",
    "MqttSystemSettings",
    "OperationsSystemSettings",
    "OutputSystemSettings",
    "SystemConfiguration",
    "WeatherSystemSettings",
]
