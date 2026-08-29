"""Pure Home Assistant MQTT discovery definitions.

The definitions carry availability explicitly.  An entity either depends only
on this publisher or also on recent proof from the controller; there is no
implicit default that could accidentally turn an unknown relay state into OFF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import AppConfig
from .topics import TopicLayout


MANUFACTURER = "Dynamic Thermal Charge"
CONTROLLER_HEALTH_VALUES = ["healthy", "degraded", "silent", "never_seen"]


@dataclass(frozen=True)
class DiscoveryEntity:
    key: str
    component: str
    heater_id: str | None
    entity: str
    payload: dict[str, Any]

    def topic(self, topics: TopicLayout) -> str:
        return topics.discovery_topic(self.component, self.heater_id, self.entity)


def _availability(topics: TopicLayout, controller_dependent: bool) -> dict[str, Any]:
    entries = [
        {
            "topic": topics.availability,
            "payload_available": "online",
            "payload_not_available": "offline",
        }
    ]
    result: dict[str, Any] = {"availability": entries}
    if controller_dependent:
        entries.append(
            {
                "topic": topics.state_available,
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        )
        result["availability_mode"] = "all"
    return result


def _device(
    topics: TopicLayout,
    name: str,
    heater_id: str | None = None,
) -> dict[str, Any]:
    identifier = (
        topics.installation_device_id
        if heater_id is None
        else topics.heater_device_id(heater_id)
    )
    device: dict[str, Any] = {
        "identifiers": [identifier],
        "name": name,
        "manufacturer": MANUFACTURER,
    }
    if heater_id is not None:
        device["via_device"] = topics.installation_device_id
    return device


def _entity(
    *,
    topics: TopicLayout,
    key: str,
    component: str,
    entity: str,
    name: str,
    device_name: str,
    state_topic: str,
    value: str,
    controller_dependent: bool = False,
    heater_id: str | None = None,
    **extra: Any,
) -> DiscoveryEntity:
    payload = {
        "name": name,
        "unique_id": topics.unique_id(heater_id, entity),
        "device": _device(topics, device_name, heater_id),
        "state_topic": state_topic,
        "value_template": f"{{{{ value_json.{value} }}}}",
        **_availability(topics, controller_dependent),
        **extra,
    }
    return DiscoveryEntity(key, component, heater_id, entity, payload)


def discovery_entities(
    config: AppConfig,
    installation_name: str,
    topics: TopicLayout,
) -> list[DiscoveryEntity]:
    """Return deterministic discovery definitions for the current inventory."""
    state = topics.installation_state
    entities = [
        _entity(
            topics=topics,
            key="installation_instant_power",
            component="sensor",
            entity="instant_power",
            name="Potencia instantánea",
            device_name=installation_name,
            state_topic=state,
            value="instant_power_w",
            controller_dependent=True,
            device_class="power",
            unit_of_measurement="W",
        ),
        _entity(
            topics=topics,
            key="installation_window_start",
            component="sensor",
            entity="window_start",
            name="Inicio de ventana",
            device_name=installation_name,
            state_topic=state,
            value="window_start",
            device_class="timestamp",
        ),
        _entity(
            topics=topics,
            key="installation_window_end",
            component="sensor",
            entity="window_end",
            name="Fin de ventana",
            device_name=installation_name,
            state_topic=state,
            value="window_end",
            device_class="timestamp",
        ),
        _entity(
            topics=topics,
            key="installation_forecast_average",
            component="sensor",
            entity="forecast_average",
            name="Temperatura media prevista",
            device_name=installation_name,
            state_topic=state,
            value="forecast_average_c",
            device_class="temperature",
            unit_of_measurement="°C",
        ),
        _entity(
            topics=topics,
            key="installation_forecast_source",
            component="sensor",
            entity="forecast_source",
            name="Origen de previsión",
            device_name=installation_name,
            state_topic=state,
            value="forecast_source",
        ),
        _entity(
            topics=topics,
            key="installation_percent_of_limit",
            component="sensor",
            entity="percent_of_limit",
            name="Porcentaje del límite",
            device_name=installation_name,
            state_topic=state,
            value="percent_of_limit",
            controller_dependent=True,
            unit_of_measurement="%",
        ),
        _entity(
            topics=topics,
            key="installation_power_limit",
            component="sensor",
            entity="power_limit",
            name="Límite de potencia",
            device_name=installation_name,
            state_topic=state,
            value="power_limit_w",
            device_class="power",
            unit_of_measurement="W",
        ),
        _entity(
            topics=topics,
            key="installation_controller_health",
            component="sensor",
            entity="controller_health",
            name="Salud del controlador",
            device_name=installation_name,
            state_topic=state,
            value="controller_health",
            options=CONTROLLER_HEALTH_VALUES,
        ),
        _entity(
            topics=topics,
            key="installation_multiple_controllers",
            component="binary_sensor",
            entity="multiple_controllers",
            name="Más de un controlador",
            device_name=installation_name,
            state_topic=state,
            value="multiple_controllers_suspected",
            payload_on=True,
            payload_off=False,
        ),
    ]
    for heater in config.heaters:
        heater_state = topics.heater_state(heater.id)
        common = {
            "topics": topics,
            "heater_id": heater.id,
            "device_name": heater.name,
            "state_topic": heater_state,
        }
        entities.extend(
            [
                _entity(
                    **common,
                    key=f"heater_{heater.id}_output",
                    component="binary_sensor",
                    entity="output",
                    name="Salida",
                    value="output_on",
                    controller_dependent=True,
                    payload_on=True,
                    payload_off=False,
                ),
                _entity(
                    **common,
                    key=f"heater_{heater.id}_power",
                    component="sensor",
                    entity="power",
                    name="Potencia nominal",
                    value="power_w",
                    device_class="power",
                    unit_of_measurement="W",
                ),
                _entity(
                    **common,
                    key=f"heater_{heater.id}_enabled",
                    component="switch",
                    entity="enabled",
                    name="Habilitado",
                    value="enabled",
                    command_topic=topics.command(heater.id, "enabled"),
                    payload_on="ON",
                    payload_off="OFF",
                ),
                _entity(
                    **common,
                    key=f"heater_{heater.id}_target_charge",
                    component="number",
                    entity="target_charge",
                    name="Carga objetivo",
                    value="target_charge",
                    command_topic=topics.command(heater.id, "target_charge"),
                    min=0,
                    max=1,
                    step=0.01,
                ),
            ]
        )
        for field, label in (
            ("requested_minutes", "Minutos solicitados"),
            ("allocated_minutes", "Minutos asignados"),
            ("unmet_minutes", "Minutos no atendidos"),
        ):
            entities.append(
                _entity(
                    **common,
                    key=f"heater_{heater.id}_{field}",
                    component="sensor",
                    entity=field,
                    name=label,
                    value=field,
                    unit_of_measurement="min",
                )
            )
    return entities


__all__ = [
    "CONTROLLER_HEALTH_VALUES",
    "DiscoveryEntity",
    "discovery_entities",
]
