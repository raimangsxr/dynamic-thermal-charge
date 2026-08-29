"""Stable MQTT topics and Home Assistant identities."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


INSTALLATION_SEGMENT = "installation"
IDENTITY_NAMESPACE = "dynamic_thermal_charge"


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")


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
        return f"{self.base}/heater/{_slug(heater_id)}/state"

    def command(self, heater_id: str, field: str) -> str:
        return f"{self.base}/heater/{_slug(heater_id)}/set/{field}"

    @property
    def installation_device_id(self) -> str:
        return f"{IDENTITY_NAMESPACE}_{INSTALLATION_SEGMENT}"

    def heater_device_id(self, heater_id: str) -> str:
        return f"{self.installation_device_id}_{_slug(heater_id)}"

    def unique_id(self, heater_id: str | None, entity: str) -> str:
        parts = [IDENTITY_NAMESPACE, INSTALLATION_SEGMENT]
        if heater_id is not None:
            parts.append(_slug(heater_id))
        parts.append(_slug(entity))
        return "_".join(parts)

    def discovery_topic(
        self, component: str, heater_id: str | None, entity: str
    ) -> str:
        return f"{self.discovery_prefix}/{component}/{self.unique_id(heater_id, entity)}/config"


__all__ = ["IDENTITY_NAMESPACE", "INSTALLATION_SEGMENT", "TopicLayout"]
