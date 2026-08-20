"""YAML configuration loading and validation."""

from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import (
    AppConfig,
    Heater,
    LoggingConfig,
    OutputConfig,
    ScheduleConfig,
    SiteConfig,
)


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read configuration {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {config_path}: {exc}") from exc

    root = _mapping(raw, "configuration")
    site_raw = _mapping(root.get("site"), "site")
    logging_raw = _mapping(root.get("logging", {}), "logging")
    schedule_raw = root.get("schedule")
    heaters_raw = root.get("heaters")
    if not isinstance(heaters_raw, list) or not heaters_raw:
        raise ValueError("heaters must be a non-empty list")

    try:
        schedule = (
            _load_schedule(_mapping(schedule_raw, "schedule"))
            if schedule_raw is not None
            else None
        )
        window_minutes = (
            schedule.window_minutes
            if schedule is not None
            else round(float(site_raw.get("window_hours", 8)) * 60)
        )
        site = SiteConfig(
            max_total_power_w=round(float(site_raw["max_total_power_kw"]) * 1000),
            slot_minutes=int(site_raw.get("slot_minutes", 30)),
            window_minutes=window_minutes,
        )
        if schedule is not None:
            _validate_schedule_alignment(schedule, site.slot_minutes)
        heaters = tuple(_load_heater(item, index) for index, item in enumerate(heaters_raw))
        logging_config = LoggingConfig(level=str(logging_raw.get("level", "INFO")))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid configuration: {exc}") from exc
    return AppConfig(
        site=site,
        heaters=heaters,
        logging=logging_config,
        schedule=schedule,
    )


def _load_schedule(raw: Mapping[str, Any]) -> ScheduleConfig:
    weekday_names = raw.get("weekdays")
    if not isinstance(weekday_names, list):
        raise ValueError("schedule weekdays must be a list")
    try:
        weekdays = tuple(WEEKDAYS[str(name).lower()] for name in weekday_names)
        start_time = _parse_time(raw["start_time"], "schedule start_time")
        end_time = _parse_time(raw["end_time"], "schedule end_time")
    except KeyError as exc:
        raise ValueError(f"invalid schedule value: {exc}") from exc
    return ScheduleConfig(
        timezone=str(raw.get("timezone", "Europe/Madrid")),
        start_time=start_time,
        end_time=end_time,
        weekdays=weekdays,
    )


def _parse_time(value: Any, label: str) -> time:
    try:
        parsed = time.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} must use HH:MM format") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ValueError(f"{label} must use HH:MM format")
    return parsed


def _validate_schedule_alignment(schedule: ScheduleConfig, slot_minutes: int) -> None:
    for label, configured_time in (
        ("start_time", schedule.start_time),
        ("end_time", schedule.end_time),
    ):
        minutes = configured_time.hour * 60 + configured_time.minute
        if minutes % slot_minutes:
            raise ValueError(f"schedule {label} must align with slot_minutes")


def _load_heater(raw: Any, index: int) -> Heater:
    item = _mapping(raw, f"heaters[{index}]")
    output_raw = _mapping(item.get("output", {"type": "simulated"}), "output")
    heater_id = str(item["id"])
    return Heater(
        id=heater_id,
        name=str(item.get("name", heater_id)),
        model=str(item["model"]) if item.get("model") is not None else None,
        power_w=round(float(item["power_kw"]) * 1000),
        full_charge_minutes=round(float(item["full_charge_hours"]) * 60),
        target_charge=float(item.get("target_charge", 1.0)),
        priority=int(item.get("priority", 0)),
        enabled=bool(item.get("enabled", True)),
        output=OutputConfig(
            kind=str(output_raw.get("type", "simulated")),
            pin=int(output_raw["pin"]) if output_raw.get("pin") is not None else None,
            active_high=bool(output_raw.get("active_high", True)),
        ),
    )
