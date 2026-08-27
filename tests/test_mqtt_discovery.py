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


def test_health_and_multiple_controller_entities_are_automation_friendly():
    entities = _entities()
    health = entities["installation_controller_health"]
    suspected = entities["installation_multiple_controllers"]

    assert health.component == "sensor"
    assert health.payload["options"] == [
        "healthy", "degraded", "silent", "never_seen"
    ]
    assert suspected.component == "binary_sensor"
    assert suspected.payload["payload_on"] is True
    assert suspected.payload["payload_off"] is False


def test_catalog_contains_every_installation_and_heater_entity_with_grouping():
    entities = _entities()
    assert set(entities) == {
        "installation_instant_power",
        "installation_percent_of_limit",
        "installation_power_limit",
        "installation_window_start",
        "installation_window_end",
        "installation_forecast_average",
        "installation_forecast_source",
        "installation_controller_health",
        "installation_multiple_controllers",
        *(
            f"heater_{heater_id}_{entity}"
            for heater_id in ("salon", "entrada", "habitaciones", "buhardilla")
            for entity in (
                "output", "power", "enabled", "target_charge",
                "requested_minutes", "allocated_minutes", "unmet_minutes",
            )
        ),
    }
    output = entities["heater_salon_output"].payload
    assert output["device"]["via_device"] == (
        "dynamic_thermal_charge_installation"
    )
    assert output["value_template"] == "{{ value_json.output_on }}"
    assert entities["heater_salon_power"].payload["unit_of_measurement"] == "W"
    assert entities["installation_forecast_average"].payload[
        "unit_of_measurement"
    ] == "°C"


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
    assert {entity.payload["unique_id"] for entity in first} == {
        entity.payload["unique_id"] for entity in second
    }
