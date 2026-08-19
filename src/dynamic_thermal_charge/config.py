"""YAML configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import AppConfig, Heater, OutputConfig, SiteConfig


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
    heaters_raw = root.get("heaters")
    if not isinstance(heaters_raw, list) or not heaters_raw:
        raise ValueError("heaters must be a non-empty list")

    try:
        site = SiteConfig(
            max_total_power_w=round(float(site_raw["max_total_power_kw"]) * 1000),
            slot_minutes=int(site_raw.get("slot_minutes", 30)),
            window_minutes=round(float(site_raw.get("window_hours", 8)) * 60),
        )
        heaters = tuple(_load_heater(item, index) for index, item in enumerate(heaters_raw))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid configuration: {exc}") from exc
    return AppConfig(site=site, heaters=heaters)


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
