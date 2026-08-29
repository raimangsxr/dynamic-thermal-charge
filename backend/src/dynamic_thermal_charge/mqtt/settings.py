"""MQTT settings projected from canonical database configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

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


def settings_from_repository(repository) -> MqttSettings:
    snapshot = repository.current()
    configured = snapshot.configuration.mqtt
    if not configured.enabled:
        raise MqttConfigurationError("MQTT is disabled in system configuration")
    if not configured.host:
        raise MqttConfigurationError("MQTT host is missing in system configuration")
    username = snapshot.secrets.get("mqtt_username")
    password = snapshot.secrets.get("mqtt_password")
    if (username is None) != (password is None):
        raise MqttConfigurationError("MQTT username and password must be configured together")
    return MqttSettings(
        host=configured.host,
        port=configured.port,
        tls=configured.tls,
        username=None if username is None else username.value,
        password=None if password is None else password.value,
        prefix=configured.prefix.strip("/"),
        discovery_prefix=configured.discovery_prefix.strip("/"),
        publish_seconds=configured.publish_seconds,
    )


__all__ = ["MqttSettings", "settings_from_repository"]
