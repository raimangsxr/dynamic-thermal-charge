"""Stable MQTT transport topics and Home Assistant identities."""

from dynamic_thermal_charge.mqtt.topics import (
    TopicLayout,
    accumulator_topics,
    resolve_accumulator_topics,
)


def test_accumulator_topics_use_the_fixed_namespace_and_existing_slug_rule():
    topics = accumulator_topics("Salón principal")

    assert topics.telemetry == "telemetria/acumuladores/salon_principal/telemetry"
    assert topics.discharge == "telemetria/acumuladores/salon_principal/discharge"
    assert topics.setpoint == "telemetria/acumuladores/salon_principal/setpoint"


def test_accumulator_topic_overrides_are_used_independently():
    topics = resolve_accumulator_topics(
        "salon",
        telemetry_topic=" custom/telemetry ",
        setpoint_topic="custom/setpoint",
    )

    assert topics.telemetry == "custom/telemetry"
    assert topics.discharge == "telemetria/acumuladores/salon/discharge"
    assert topics.setpoint == "custom/setpoint"


def test_transport_topics_use_the_fixed_installation_segment():
    topics = TopicLayout(prefix="custom", discovery_prefix="ha")
    assert topics.availability == "custom/installation/availability"
    assert topics.heater_state("salon") == "custom/installation/heater/salon/state"


def test_home_assistant_ids_ignore_visible_name_prefix_pk_and_order():
    first = TopicLayout(prefix="dtc", discovery_prefix="homeassistant")
    moved = TopicLayout(prefix="other", discovery_prefix="ha")
    assert first.installation_device_id == moved.installation_device_id
    assert first.heater_device_id("salon") == moved.heater_device_id("salon")
    assert first.unique_id("salon", "output") == moved.unique_id("salon", "output")
    assert first.unique_id("salon", "output") == (
        "dynamic_thermal_charge_installation_salon_output"
    )
    assert first.device_discovery_topic() == (
        "homeassistant/device/dynamic_thermal_charge_installation/config"
    )
    assert first.device_discovery_topic("salon") == (
        "homeassistant/device/dynamic_thermal_charge_installation_salon/config"
    )


def test_domain_ids_are_sanitized_deterministically():
    topics = TopicLayout()
    assert topics.unique_id("Salón principal", "Output State") == (
        "dynamic_thermal_charge_installation_salon_principal_output_state"
    )
