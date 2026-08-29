"""Versioned inventory of legacy runtime configuration inputs.

Runtime processes are being migrated away from these inputs.  Keeping the
inventory in code makes the migration exhaustive: a new environment lookup
cannot be added without declaring where the value belongs in the database.
The explicit legacy import command may use this inventory; normal entrypoints
must not.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


INVENTORY_VERSION = 1


class ConfigurationDisposition(Enum):
    """Where a former external value belongs after the migration."""

    PERSISTED = "persisted"
    INTERNAL_CONSTANT = "internal_constant"
    OPERATION_ARGUMENT = "operation_argument"


@dataclass(frozen=True)
class LegacyConfigurationInput:
    name: str
    section: str
    disposition: ConfigurationDisposition
    consumers: tuple[str, ...]
    secret: bool = False


def _persisted(
    name: str,
    section: str,
    *consumers: str,
    secret: bool = False,
) -> LegacyConfigurationInput:
    return LegacyConfigurationInput(
        name=name,
        section=section,
        disposition=ConfigurationDisposition.PERSISTED,
        consumers=tuple(consumers),
        secret=secret,
    )


LEGACY_ENVIRONMENT_INPUTS: dict[str, LegacyConfigurationInput] = {
    item.name: item
    for item in (
        _persisted("DTC_DATABASE_URL", "database", "persistence.url", secret=True),
        _persisted("DTC_API_TOKEN", "api_security", "api.settings", secret=True),
        _persisted("DTC_API_HOST", "api", "api.settings", "cli"),
        _persisted("DTC_API_PORT", "api", "api.settings", "cli"),
        _persisted("DTC_API_STALE_SECONDS", "operations", "api.settings"),
        _persisted("DTC_API_CORS_ORIGINS", "api", "api.settings"),
        _persisted("DTC_MQTT_HOST", "mqtt", "mqtt.settings"),
        _persisted("DTC_MQTT_PORT", "mqtt", "mqtt.settings"),
        _persisted("DTC_MQTT_TLS", "mqtt", "mqtt.settings"),
        _persisted("DTC_MQTT_USERNAME", "mqtt", "mqtt.settings", secret=True),
        _persisted("DTC_MQTT_PASSWORD", "mqtt", "mqtt.settings", secret=True),
        _persisted("DTC_MQTT_PREFIX", "mqtt", "mqtt.settings"),
        _persisted("DTC_MQTT_DISCOVERY_PREFIX", "mqtt", "mqtt.settings"),
        _persisted("DTC_MQTT_PUBLISH_SECONDS", "operations", "mqtt.settings"),
        _persisted(
            "DTC_RELAY_TEST_LEASE_SECONDS", "operations", "api.routes.relay_test"
        ),
        _persisted(
            "DTC_CONTROLLER_LOG_MAX_EVENTS", "logging", "persistence.controller_log"
        ),
        _persisted("AEMET_API_KEY", "weather", "weather", secret=True),
    )
}

# The runtime no longer reads YAML.  The one-shot legacy importer introduced by
# this change will be the only allowed configuration-file reader.
LEGACY_RUNTIME_CONFIGURATION_FILES: tuple[str, ...] = ()


__all__ = [
    "ConfigurationDisposition",
    "INVENTORY_VERSION",
    "LEGACY_ENVIRONMENT_INPUTS",
    "LEGACY_RUNTIME_CONFIGURATION_FILES",
    "LegacyConfigurationInput",
]
