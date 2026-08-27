"""MQTT deployment settings loaded exclusively from the environment."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Mapping

from . import MqttConfigurationError


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int = 1883
    tls: bool = False
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    prefix: str = "dtc"
    discovery_prefix: str = "homeassistant"
    publish_seconds: float = 15.0


def _boolean(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise MqttConfigurationError(
        f"{name} must be true or false; received an invalid value"
    )


def _integer(environ: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(environ.get(name, str(default)))
    except ValueError as exc:
        raise MqttConfigurationError(f"{name} must be a whole number") from exc


def _number(environ: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(environ.get(name, str(default)))
    except ValueError as exc:
        raise MqttConfigurationError(f"{name} must be a number") from exc


def load_settings(environ: Mapping[str, str] | None = None) -> MqttSettings:
    source = os.environ if environ is None else environ
    host = source.get("DTC_MQTT_HOST", "").strip()
    if not host:
        raise MqttConfigurationError("DTC_MQTT_HOST is required")
    port = _integer(source, "DTC_MQTT_PORT", 1883)
    if not 1 <= port <= 65535:
        raise MqttConfigurationError("DTC_MQTT_PORT must be between 1 and 65535")
    cadence = _number(source, "DTC_MQTT_PUBLISH_SECONDS", 15.0)
    if cadence <= 0:
        raise MqttConfigurationError("DTC_MQTT_PUBLISH_SECONDS must be positive")
    username = source.get("DTC_MQTT_USERNAME") or None
    password = source.get("DTC_MQTT_PASSWORD") or None
    if username is not None and password is None:
        raise MqttConfigurationError(
            "DTC_MQTT_PASSWORD is required when DTC_MQTT_USERNAME is set"
        )
    if password is not None and username is None:
        raise MqttConfigurationError(
            "DTC_MQTT_USERNAME is required when DTC_MQTT_PASSWORD is set"
        )
    prefix = source.get("DTC_MQTT_PREFIX", "dtc").strip().strip("/")
    discovery_prefix = source.get(
        "DTC_MQTT_DISCOVERY_PREFIX", "homeassistant"
    ).strip().strip("/")
    if not prefix:
        raise MqttConfigurationError("DTC_MQTT_PREFIX cannot be empty")
    if not discovery_prefix:
        raise MqttConfigurationError("DTC_MQTT_DISCOVERY_PREFIX cannot be empty")
    return MqttSettings(
        host=host,
        port=port,
        tls=_boolean(source, "DTC_MQTT_TLS", False),
        username=username,
        password=password,
        prefix=prefix,
        discovery_prefix=discovery_prefix,
        publish_seconds=cadence,
    )


__all__ = ["MqttSettings", "load_settings"]
