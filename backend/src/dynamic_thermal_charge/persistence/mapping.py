"""Row <-> dataclass conversion, and the temporal boundary.

The frozen dataclasses in ``models.py`` are built unchanged, so their
``__post_init__`` validations remain the last line of defence: configuration
loaded from the database cannot be something the scheduler considers invalid
(constitution principle III).

Temporal rule (research.md D8): instants are stored as naive UTC and read back
as timezone-aware UTC. ``start_time`` and ``end_time`` are local rules, not
instants, and travel as ``HH:MM`` text.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Mapping, Sequence

from ..models import (
    AemetConfig,
    AppConfig,
    Heater,
    IndoorReading,
    LoggingConfig,
    OutputConfig,
    RuntimeConfig,
    ScheduleConfig,
    SimulatedForecastConfig,
    SiteConfig,
    ThermalProfile,
    WeatherConfig,
    WeatherWatchdogConfig,
)
from . import ConfigValidationError


# --------------------------------------------------------------------------- #
# Temporal boundary
# --------------------------------------------------------------------------- #

def to_utc(value: datetime) -> datetime:
    """Convert an instant to the naive-UTC form the schema stores."""
    if value.tzinfo is None:
        raise ValueError(
            "a naive datetime cannot be stored: attach a timezone before writing"
        )
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def from_utc(value: datetime | None) -> datetime | None:
    """Rebuild a timezone-aware UTC instant from a stored value."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=timezone.utc)


def format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_time(raw: str, field: str) -> time:
    try:
        parsed = time.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(
            f"{field} must use HH:MM format; stored value is {raw!r}", field=field
        ) from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ConfigValidationError(
            f"{field} must use HH:MM format; stored value is {raw!r}", field=field
        )
    return parsed


def format_weekdays(weekdays: Sequence[int]) -> str:
    """Normative format: ascending, comma-separated, no repeats."""
    return ",".join(str(day) for day in sorted(set(weekdays)))


def parse_weekdays(raw: str, field: str = "weekdays") -> tuple[int, ...]:
    parts = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not parts:
        raise ConfigValidationError("weekdays cannot be empty", field=field)
    try:
        days = tuple(int(part) for part in parts)
    except ValueError as exc:
        raise ConfigValidationError(
            f"weekdays must be integers 0-6 separated by commas; stored value is {raw!r}",
            field=field,
        ) from exc
    if any(day not in range(7) for day in days):
        raise ConfigValidationError(
            f"weekdays must be between 0 and 6; stored value is {raw!r}", field=field
        )
    if list(days) != sorted(set(days)):
        raise ConfigValidationError(
            "weekdays must be ascending and free of repeats, for example 0,1,2,3,4; "
            f"stored value is {raw!r}",
            field=field,
        )
    return days


# --------------------------------------------------------------------------- #
# Row -> dataclass
# --------------------------------------------------------------------------- #

def _domain_error(field: str, heater_id: str | None = None):
    """Turn a dataclass ValueError into an actionable domain error."""

    class _Wrapper:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type, exc, _tb) -> bool:
            if exc_type is ConfigValidationError:
                return False
            if exc_type in (ValueError, TypeError, KeyError):
                raise ConfigValidationError(
                    str(exc) or f"invalid value for {field}",
                    field=field,
                    heater_id=heater_id,
                ) from exc
            return False

    return _Wrapper()


def site_from_row(row: Mapping[str, Any]) -> SiteConfig:
    with _domain_error("site"):
        return SiteConfig(
            max_total_power_w=int(row["max_total_power_w"]),
            slot_minutes=int(row["slot_minutes"]),
            window_minutes=int(row["window_minutes"]),
            indoor_max_age_minutes=int(row.get("indoor_max_age_minutes", 30)),
            indoor_min_plausible_c=float(row.get("indoor_min_plausible_c", -20)),
            indoor_max_plausible_c=float(row.get("indoor_max_plausible_c", 50)),
        )


def schedule_from_row(row: Mapping[str, Any]) -> ScheduleConfig | None:
    present = [
        row.get("timezone"),
        row.get("start_time"),
        row.get("end_time"),
        row.get("weekdays"),
    ]
    if all(value is None for value in present):
        return None
    if any(value is None for value in present):
        raise ConfigValidationError(
            "timezone, start_time, end_time and weekdays must all be set or all be "
            "empty: a partial schedule cannot define a charge window",
            field="schedule",
        )
    with _domain_error("schedule"):
        return ScheduleConfig(
            timezone=str(row["timezone"]),
            start_time=parse_time(str(row["start_time"]), "start_time"),
            end_time=parse_time(str(row["end_time"]), "end_time"),
            weekdays=parse_weekdays(str(row["weekdays"])),
        )


def weather_from_row(row: Mapping[str, Any] | None) -> WeatherConfig | None:
    if row is None:
        return None
    provider = str(row["provider"])
    with _domain_error("weather"):
        simulated = _forecast_values(row, "simulated")
        fallback = _forecast_values(row, "fallback")
        aemet = None
        if row.get("aemet_municipality_code") is not None:
            aemet = AemetConfig(
                municipality_code=str(row["aemet_municipality_code"]),
                api_key_env=str(row.get("aemet_api_key_env") or "AEMET_API_KEY"),
                timeout_seconds=float(row.get("aemet_timeout_seconds") or 10.0),
            )
        return WeatherConfig(
            provider=provider,
            simulated=simulated,
            aemet=aemet,
            fallback=fallback,
            watchdog=WeatherWatchdogConfig(
                retry_minutes=int(row["watchdog_retry_minutes"]),
                refresh_minutes=int(row["watchdog_refresh_minutes"]),
            ),
        )


def _forecast_values(
    row: Mapping[str, Any], prefix: str
) -> SimulatedForecastConfig | None:
    average = row.get(f"{prefix}_average_temperature_c")
    minimum = row.get(f"{prefix}_minimum_temperature_c")
    if average is None and minimum is None:
        return None
    if average is None or minimum is None:
        raise ConfigValidationError(
            f"{prefix} forecast needs both an average and a minimum temperature",
            field=f"{prefix}_average_temperature_c",
        )
    return SimulatedForecastConfig(
        average_temperature_c=float(average),
        minimum_temperature_c=float(minimum),
    )


def heater_from_rows(
    heater_row: Mapping[str, Any],
    output_row: Mapping[str, Any] | None,
    thermal_row: Mapping[str, Any] | None,
) -> Heater:
    heater_id = str(heater_row["heater_id"])
    if output_row is None:
        raise ConfigValidationError(
            "every heater needs an output", field="output", heater_id=heater_id
        )
    with _domain_error("heater", heater_id):
        output = OutputConfig(
            kind=str(output_row["kind"]),
            pin=None if output_row.get("pin") is None else int(output_row["pin"]),
            active_high=bool(output_row["active_high"]),
        )
        thermal = None
        if thermal_row is not None:
                thermal = ThermalProfile(
                target_temperature_c=float(thermal_row["target_temperature_c"]),
                design_outdoor_temperature_c=float(
                    thermal_row["design_outdoor_temperature_c"]
                ),
                thermal_factor=float(thermal_row["thermal_factor"]),
                    min_charge=float(thermal_row["min_charge"]),
                    max_charge=float(thermal_row["max_charge"]),
                    thermal_loss_c_per_hour=float(
                        thermal_row.get("thermal_loss_c_per_hour", 0.0)
                    ),
            )
        return Heater(
            id=heater_id,
            name=str(heater_row["name"]),
            model=None if heater_row.get("model") is None else str(heater_row["model"]),
            power_w=int(heater_row["power_w"]),
            full_charge_minutes=int(heater_row["full_charge_minutes"]),
            target_charge=float(heater_row["target_charge"]),
            priority=int(heater_row["priority"]),
            enabled=bool(heater_row["enabled"]),
            thermal=thermal,
            output=output,
            indoor_topic=(
                None
                if heater_row.get("indoor_topic") is None
                else str(heater_row["indoor_topic"])
            ),
        )


def config_from_rows(
    installation_row: Mapping[str, Any],
    weather_row: Mapping[str, Any] | None,
    heater_rows: Sequence[
        tuple[Mapping[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None]
    ],
) -> AppConfig:
    """Build the whole configuration, or raise with the offending field."""
    site = site_from_row(installation_row)
    schedule = schedule_from_row(installation_row)
    weather = weather_from_row(weather_row)
    heaters = tuple(
        heater_from_rows(heater_row, output_row, thermal_row)
        for heater_row, output_row, thermal_row in heater_rows
    )
    # Runs before AppConfig is built so the detailed message ("pin 17 is already
    # assigned to heater 'salon'") wins over the generic dataclass ValueError.
    from ..config import validate_heaters

    validate_heaters(heaters)
    with _domain_error("logging"):
        logging_config = LoggingConfig(level=str(installation_row["log_level"]))
    with _domain_error("runtime"):
        runtime = RuntimeConfig(
            poll_seconds=float(installation_row["poll_seconds"]),
        )
    retention = installation_row.get("retention_days")
    with _domain_error("retention_days"):
        config = AppConfig(
            site=site,
            heaters=heaters,
            logging=logging_config,
            schedule=schedule,
            weather=weather,
            runtime=runtime,
            retention_days=None if retention is None else int(retention),
        )
    from ..config import validate_config

    validate_config(config)
    return config


# --------------------------------------------------------------------------- #
# Dataclass -> write parameters
# --------------------------------------------------------------------------- #

def installation_params(config: AppConfig, name: str, now: datetime) -> dict[str, Any]:
    schedule = config.schedule
    return {
        "name": name,
        "revision": 1,
        "max_total_power_w": config.site.max_total_power_w,
        "slot_minutes": config.site.slot_minutes,
        "window_minutes": config.site.window_minutes,
        "timezone": None if schedule is None else schedule.timezone,
        "start_time": None if schedule is None else format_time(schedule.start_time),
        "end_time": None if schedule is None else format_time(schedule.end_time),
        "weekdays": None if schedule is None else format_weekdays(schedule.weekdays),
        "log_level": config.logging.level,
        "poll_seconds": config.runtime.poll_seconds,
        "retention_days": config.retention_days,
        "indoor_max_age_minutes": config.site.indoor_max_age_minutes,
        "indoor_min_plausible_c": config.site.indoor_min_plausible_c,
        "indoor_max_plausible_c": config.site.indoor_max_plausible_c,
        "created_at": to_utc(now),
        "updated_at": to_utc(now),
    }


def weather_params(config: WeatherConfig, installation_id: int) -> dict[str, Any]:
    return {
        "installation_id": installation_id,
        "provider": config.provider,
        "aemet_municipality_code": (
            None if config.aemet is None else config.aemet.municipality_code
        ),
        "aemet_api_key_env": None if config.aemet is None else config.aemet.api_key_env,
        "aemet_timeout_seconds": (
            None if config.aemet is None else config.aemet.timeout_seconds
        ),
        "simulated_average_temperature_c": (
            None if config.simulated is None else config.simulated.average_temperature_c
        ),
        "simulated_minimum_temperature_c": (
            None if config.simulated is None else config.simulated.minimum_temperature_c
        ),
        "fallback_average_temperature_c": (
            None if config.fallback is None else config.fallback.average_temperature_c
        ),
        "fallback_minimum_temperature_c": (
            None if config.fallback is None else config.fallback.minimum_temperature_c
        ),
        "watchdog_retry_minutes": config.watchdog.retry_minutes,
        "watchdog_refresh_minutes": config.watchdog.refresh_minutes,
    }


def heater_params(heater: Heater, installation_id: int, position: int) -> dict[str, Any]:
    return {
        "installation_id": installation_id,
        "heater_id": heater.id,
        "name": heater.name,
        "model": heater.model,
        "power_w": heater.power_w,
        "full_charge_minutes": heater.full_charge_minutes,
        "target_charge": heater.target_charge,
        "priority": heater.priority,
        "enabled": heater.enabled,
        "indoor_topic": heater.indoor_topic,
        "position": position,
    }


def output_params(heater: Heater, heater_key: int) -> dict[str, Any]:
    return {
        "heater_id": heater_key,
        "kind": heater.output.kind,
        "pin": heater.output.pin,
        "active_high": heater.output.active_high,
    }


def thermal_params(profile: ThermalProfile, heater_key: int) -> dict[str, Any]:
    return {
        "heater_id": heater_key,
        "target_temperature_c": profile.target_temperature_c,
        "design_outdoor_temperature_c": profile.design_outdoor_temperature_c,
        "thermal_factor": profile.thermal_factor,
        "min_charge": profile.min_charge,
        "max_charge": profile.max_charge,
        "thermal_loss_c_per_hour": profile.thermal_loss_c_per_hour,
    }


__all__ = [
    "config_from_rows",
    "format_time",
    "format_weekdays",
    "from_utc",
    "heater_from_rows",
    "heater_params",
    "installation_params",
    "output_params",
    "parse_time",
    "parse_weekdays",
    "site_from_row",
    "thermal_params",
    "to_utc",
    "weather_params",
]
