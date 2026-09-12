"""Stable MQTT topics and Home Assistant identities."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


INSTALLATION_SEGMENT = "installation"
IDENTITY_NAMESPACE = "dynamic_thermal_charge"
ACCUMULATOR_NAMESPACE = "telemetria/acumuladores"


def mqtt_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")


def _slug(value: str) -> str:
    """Keep the existing private name available to local callers."""
    return mqtt_identifier(value)


@dataclass(frozen=True)
class AccumulatorTopics:
    """The effective MQTT topics for one accumulator."""

    telemetry: str
    discharge: str
    setpoint: str


def accumulator_topics(heater_id: str) -> AccumulatorTopics:
    identifier = mqtt_identifier(heater_id)
    base = f"{ACCUMULATOR_NAMESPACE}/{identifier}"
    return AccumulatorTopics(
        telemetry=f"{base}/telemetry",
        discharge=f"{base}/discharge",
        setpoint=f"{base}/setpoint",
    )


def _configured_topic(value: str | None) -> str | None:
    if value is None:
        return None
    topic = str(value).strip()
    return topic or None


def resolve_accumulator_topics(
    heater_id: str,
    *,
    telemetry_topic: str | None = None,
    damper_topic: str | None = None,
    setpoint_topic: str | None = None,
) -> AccumulatorTopics:
    """Use a persisted override when present, otherwise the standard topic."""
    standard = accumulator_topics(heater_id)
    return AccumulatorTopics(
        telemetry=_configured_topic(telemetry_topic) or standard.telemetry,
        discharge=_configured_topic(damper_topic) or standard.discharge,
        setpoint=_configured_topic(setpoint_topic) or standard.setpoint,
    )


@dataclass(frozen=True)
class TopicLayout:
    prefix: str = "dtc"
    discovery_prefix: str = "homeassistant"

    @property
    def base(self) -> str:
        return f"{self.prefix.rstrip('/')}/{INSTALLATION_SEGMENT}"

    @property
    def availability(self) -> str:
        return f"{self.base}/availability"

    @property
    def state_available(self) -> str:
        return f"{self.base}/state_available"

    @property
    def installation_state(self) -> str:
        return f"{self.base}/state"

    def heater_state(self, heater_id: str) -> str:
        return f"{self.base}/heater/{mqtt_identifier(heater_id)}/state"

    def command(self, heater_id: str, field: str) -> str:
        return f"{self.base}/heater/{mqtt_identifier(heater_id)}/set/{field}"

    @property
    def installation_device_id(self) -> str:
        return f"{IDENTITY_NAMESPACE}_{INSTALLATION_SEGMENT}"

    def heater_device_id(self, heater_id: str) -> str:
        return f"{self.installation_device_id}_{mqtt_identifier(heater_id)}"

    def unique_id(self, heater_id: str | None, entity: str) -> str:
        parts = [IDENTITY_NAMESPACE, INSTALLATION_SEGMENT]
        if heater_id is not None:
            parts.append(mqtt_identifier(heater_id))
        parts.append(mqtt_identifier(entity))
        return "_".join(parts)

    def discovery_topic(
        self, component: str, heater_id: str | None, entity: str
    ) -> str:
        return f"{self.discovery_prefix}/{component}/{self.unique_id(heater_id, entity)}/config"

    def device_discovery_topic(self, heater_id: str | None = None) -> str:
        device_id = (
            self.installation_device_id
            if heater_id is None
            else self.heater_device_id(heater_id)
        )
        return f"{self.discovery_prefix}/device/{device_id}/config"


__all__ = [
    "ACCUMULATOR_NAMESPACE",
    "AccumulatorTopics",
    "IDENTITY_NAMESPACE",
    "INSTALLATION_SEGMENT",
    "TopicLayout",
    "accumulator_topics",
    "mqtt_identifier",
    "resolve_accumulator_topics",
]
