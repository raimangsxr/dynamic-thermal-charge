"""Home Assistant discovery is explicit about what can still be trusted."""

from dataclasses import replace

from dynamic_thermal_charge.mqtt.discovery import discovery_entities
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence.seed import example_installation


def _entities():
    return {
        entity.key: entity
        for entity in discovery_entities(
            example_installation(), "Instalación", TopicLayout()
        )
    }


def test_only_live_controller_values_require_both_availability_levels():
    entities = _entities()
    controller_dependent = {
        "installation_instant_power",
        "installation_percent_of_limit",
        *(f"heater_{heater_id}_output" for heater_id in (
            "salon", "entrada", "habitaciones", "buhardilla"
        )),
    }

    for key, entity in entities.items():
        if entity.component == "device":
            availability = entity.payload["availability"]
            assert "availability_mode" not in entity.payload
            assert [entry["topic"] for entry in availability] == [
                "dtc/installation/availability"
            ]
            continue
        availability = entity.payload["availability"]
        if key in controller_dependent:
            assert entity.payload["availability_mode"] == "all"
            assert [entry["topic"] for entry in availability] == [
                "dtc/installation/availability",
                "dtc/installation/state_available",
            ]
        else:
            assert "availability_mode" not in entity.payload
            assert [entry["topic"] for entry in availability] == [
                "dtc/installation/availability"
            ]


def test_grouped_devices_keep_shared_entities_and_separate_live_values():
    entities = _entities()
    installation = entities["installation_device"]
    assert installation.component == "device"
    assert installation.topic(TopicLayout()) == (
        "homeassistant/device/dynamic_thermal_charge_installation/config"
    )
    assert set(installation.payload["cmps"]) == {
        "window_start",
        "window_end",
        "forecast_average",
        "forecast_source",
        "power_limit",
        "controller_health",
        "multiple_controllers",
    }
    assert installation.payload["cmps"]["controller_health"]["options"] == [
        "healthy", "degraded", "silent", "never_seen"
    ]
    assert "availability" not in installation.payload["cmps"]["power_limit"]
    assert entities["installation_instant_power"].component == "sensor"

    heater = entities["heater_salon_device"]
    assert heater.payload["dev"]["via_device"] == (
        "dynamic_thermal_charge_installation"
    )
    assert set(heater.payload["cmps"]) == {
        "power", "enabled", "requested_minutes", "allocated_minutes", "unmet_minutes"
    }
    assert heater.payload["cmps"]["enabled"]["command_topic"] == (
        "dtc/installation/heater/salon/set/enabled"
    )
    assert entities["heater_salon_output"].payload["value_template"] == (
        "{{ value_json.output_on }}"
    )


def test_catalog_contains_one_group_per_device_and_live_entities():
    entities = _entities()
    assert set(entities) == {
        "installation_device",
        "installation_instant_power",
        "installation_percent_of_limit",
        *(f"heater_{heater_id}_device" for heater_id in (
            "salon", "entrada", "habitaciones", "buhardilla"
        )),
        *(f"heater_{heater_id}_output" for heater_id in (
            "salon", "entrada", "habitaciones", "buhardilla"
        )),
    }


def test_health_and_multiple_controller_entities_are_grouped():
    entities = _entities()
    health = entities["installation_device"].payload["cmps"]["controller_health"]
    suspected = entities["installation_device"].payload["cmps"]["multiple_controllers"]

    assert health["p"] == "sensor"
    assert health["options"] == [
        "healthy", "degraded", "silent", "never_seen"
    ]
    assert suspected["p"] == "binary_sensor"
    assert suspected["payload_on"] is True
    assert suspected["payload_off"] is False


def test_discovery_ids_survive_renames_and_prefix_changes():
    config = example_installation()
    renamed = replace(
        config,
        heaters=(replace(config.heaters[0], name="Otro salón"), *config.heaters[1:]),
    )
    first = discovery_entities(config, "Casa", TopicLayout())
    second = discovery_entities(
        renamed, "Casa renombrada", TopicLayout(prefix="other", discovery_prefix="ha")
    )

    def identities(entities):
        result = set()
        for entity in entities:
            if entity.component == "device":
                result.add(entity.payload["dev"]["identifiers"][0])
            else:
                result.add(entity.payload["unique_id"])
        return result

    assert identities(first) == identities(second)
