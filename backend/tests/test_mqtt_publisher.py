"""Honest MQTT projection and failure transitions, without a broker."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from dynamic_thermal_charge.api.liveness import evaluate
from dynamic_thermal_charge.models import AppConfig
from dynamic_thermal_charge.mqtt.discovery import discovery_entities
from dynamic_thermal_charge.mqtt.publisher import MqttPublisher, project_state
from dynamic_thermal_charge.mqtt.service import MqttService
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence import (
    ConfigStoreUnavailableError,
    Heartbeat,
    SchemaVersionError,
)
from dynamic_thermal_charge.persistence.seed import example_installation


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def _heartbeat(*, age=0, degraded=False) -> Heartbeat:
    return Heartbeat(
        updated_at=NOW - timedelta(seconds=age),
        started_at=NOW - timedelta(hours=3),
        degraded=degraded,
        poll_seconds=5,
        driver_kind="gpio",
        runner_id="runner-a",
    )


@pytest.mark.parametrize(
    ("heartbeat", "health", "current"),
    [
        (_heartbeat(), "healthy", True),
        (_heartbeat(degraded=True), "degraded", True),
        (_heartbeat(age=31), "silent", False),
        (None, "never_seen", False),
    ],
)
def test_projection_distinguishes_all_controller_states(heartbeat, health, current):
    controller = evaluate(heartbeat, NOW)
    installation, heaters = project_state(
        example_installation(), controller, {"salon": True}
    )
    assert installation["controller_health"] == health
    if current:
        assert installation["instant_power_w"] == 2800
        assert heaters["salon"]["output_on"] is True
    else:
        assert "instant_power_w" not in installation
        assert "percent_of_limit" not in installation
        assert "output_on" not in heaters["salon"]


@pytest.mark.parametrize(
    "failure",
    [
        ConfigStoreUnavailableError("database unreachable"),
        SchemaVersionError("schema pending"),
        SchemaVersionError("schema is from the future"),
        SchemaVersionError("schema revision invalid"),
    ],
)
def test_database_or_schema_failure_makes_everything_unavailable_once_per_transition(
    mqtt_client, caplog, failure
):
    caplog.set_level("INFO")
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise failure
        return project_state(
            example_installation(), evaluate(_heartbeat(), NOW), {"salon": False}
        )

    publisher = MqttPublisher(mqtt_client, TopicLayout(), snapshot)
    publisher.refresh()
    publisher.refresh()
    publisher.refresh()

    assert mqtt_client.publications[:2] == [
        ("dtc/installation/state_available", "offline", 1, True),
        ("dtc/installation/availability", "offline", 1, True),
    ]
    assert caplog.text.count("MQTT publication unavailable:") == 1
    assert caplog.text.count("MQTT publication recovered") == 1
    # No false output or zero power was emitted during either failed refresh.
    failed_payloads = [payload for _, payload, _, _ in mqtt_client.publications[:2]]
    assert failed_payloads == ["offline", "offline"]


def test_last_will_is_qos_one_retained_and_declared_before_connect(mqtt_client):
    service = MqttService(
        mqtt_client,
        TopicLayout(),
        host="broker.local",
        port=1883,
    )
    service.start()

    assert mqtt_client.events[:3] == [
        ("will", "dtc/installation/availability", "offline", 1, True),
        ("connect", "broker.local", 1883),
        ("loop_start",),
    ]


def test_connect_and_clean_stop_publish_retained_availability_transitions(mqtt_client):
    service = MqttService(
        mqtt_client,
        TopicLayout(),
        host="broker.local",
        port=1883,
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()
    service.stop()

    assert mqtt_client.publications == [
        ("dtc/installation/availability", "online", 1, True),
        ("dtc/installation/state_available", "offline", 1, True),
        ("dtc/installation/availability", "offline", 1, True),
    ]


def test_complete_state_is_deterministic_and_retained(mqtt_client):
    plan = {
        "window_start": "2026-01-16T00:00:00+00:00",
        "window_end": "2026-01-16T08:00:00+00:00",
        "forecast_average_c": 7.5,
        "forecast_source": "aemet",
        "allocations": {
            "salon": {
                "requested_minutes": 300,
                "allocated_minutes": 270,
                "unmet_minutes": 30,
            }
        },
    }
    snapshot = lambda: project_state(
        example_installation(),
        evaluate(_heartbeat(), NOW),
        {"salon": True},
        plan=plan,
    )
    publisher = MqttPublisher(mqtt_client, TopicLayout(), snapshot)
    publisher.refresh()

    publications = {topic: (json.loads(payload), qos, retain) for topic, payload, qos, retain in mqtt_client.publications if payload.startswith("{")}
    installation, qos, retained = publications["dtc/installation/state"]
    assert (qos, retained) == (1, True)
    assert installation == {
        "controller_health": "healthy",
        "forecast_average_c": 7.5,
        "forecast_source": "aemet",
        "instant_power_w": 2800,
        "multiple_controllers_suspected": False,
        "percent_of_limit": 53.8,
        "power_limit_w": 5200,
        "state_is_current": True,
        "window_end": "2026-01-16T08:00:00+00:00",
        "window_start": "2026-01-16T00:00:00+00:00",
    }
    salon, qos, retained = publications["dtc/installation/heater/salon/state"]
    assert (qos, retained) == (1, True)
    assert salon["output_on"] is True
    assert salon["power_w"] == 2800
    assert salon["requested_minutes"] == 300
    assert salon["allocated_minutes"] == 270
    assert salon["unmet_minutes"] == 30


def test_dynamic_inventory_adds_discovery_and_tombstones_every_removed_entity(
    mqtt_client,
):
    config = example_installation()
    current = [config]
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(current[0], evaluate(_heartbeat(), NOW), {}),
        discovery=lambda: discovery_entities(current[0], "Casa", topics),
    )
    publisher.refresh()
    initial_topics = {
        entity.topic(topics)
        for entity in discovery_entities(config, "Casa", topics)
        if entity.heater_id == "buhardilla"
    }
    mqtt_client.publications.clear()

    new_heater = replace(config.heaters[-1], id="cocina", name="Cocina")
    current[0] = replace(
        config,
        heaters=tuple(h for h in config.heaters if h.id != "buhardilla")
        + (new_heater,),
    )
    publisher.refresh()

    tombstones = {
        topic for topic, payload, qos, retain in mqtt_client.publications
        if payload == "" and qos == 1 and retain
    }
    assert tombstones == initial_topics
    assert any("_cocina_" in topic and payload for topic, payload, _, _ in mqtt_client.publications)


def test_reconnect_republishes_availability_discovery_then_last_state(mqtt_client):
    config = example_installation()
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(config, evaluate(_heartbeat(), NOW), {}),
        discovery=lambda: discovery_entities(config, "Casa", topics),
    )
    service = MqttService(
        mqtt_client, topics, host="broker", port=1883, publisher=publisher
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()

    topics_in_order = [event[1] for event in mqtt_client.events if event[0] == "publish"]
    assert topics_in_order[0] == topics.availability
    first_state = topics_in_order.index(topics.installation_state)
    discovery_positions = [
        index for index, topic in enumerate(topics_in_order) if "/config" in topic
    ]
    assert discovery_positions
    assert min(discovery_positions) > 0
    assert max(discovery_positions) < first_state
    assert all(qos == 1 and retain for _, _, qos, retain in mqtt_client.publications)


def test_periodic_cycle_uses_default_fifteen_seconds_without_real_sleep(mqtt_client):
    refreshes = []
    waits = []

    class Publisher:
        def refresh(self, *, force_discovery=False):
            refreshes.append(force_discovery)

    service = MqttService(
        mqtt_client,
        TopicLayout(),
        host="broker",
        port=1883,
        publisher=Publisher(),
        wait=waits.append,
    )
    service.start()
    mqtt_client.connect_result()
    service.run(max_cycles=3)
    assert refreshes == [True, False, False]
    assert waits == [15, 15]


def test_periodic_cycles_skip_publication_until_connection_is_accepted(mqtt_client):
    refreshes = []

    class Publisher:
        def refresh(self, *, force_discovery=False):
            refreshes.append(force_discovery)

    service = MqttService(
        mqtt_client,
        TopicLayout(),
        host="broker",
        port=1883,
        publisher=Publisher(),
        wait=lambda _seconds: None,
    )
    service.start()

    service.run(max_cycles=2)
    assert refreshes == []

    mqtt_client.connect_result()
    service.run(max_cycles=1)
    assert refreshes == [True]

    mqtt_client.connect_result(accepted=False, reason="broker unavailable")
    service.run(max_cycles=2)
    assert refreshes == [True]


def test_declared_command_and_indoor_topics_are_subscribed_after_discovery(mqtt_client):
    config = replace(
        example_installation(),
        heaters=(
            replace(example_installation().heaters[0], indoor_topic="ha/salon/temp"),
        ),
    )
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(config, evaluate(_heartbeat(), NOW), {}),
        discovery=lambda: discovery_entities(config, "Casa", topics),
        subscriptions=lambda: (
            topics.command("salon", "enabled"),
            topics.command("salon", "target_charge"),
            "ha/salon/temp",
        ),
    )
    service = MqttService(
        mqtt_client, topics, host="broker", port=1883, publisher=publisher
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()

    first_subscribe = next(
        index for index, event in enumerate(mqtt_client.events)
        if event[0] == "subscribe"
    )
    last_discovery = max(
        index for index, event in enumerate(mqtt_client.events)
        if event[0] == "publish" and "/config" in event[1]
    )
    assert first_subscribe > last_discovery
    assert set(mqtt_client.subscriptions) == {
        topics.command("salon", "enabled"),
        topics.command("salon", "target_charge"),
        "ha/salon/temp",
    }

    subscribe_count = len(
        [event for event in mqtt_client.events if event[0] == "subscribe"]
    )
    mqtt_client.connect_result()
    service.process_events()
    assert len([event for event in mqtt_client.events if event[0] == "subscribe"]) == (
        subscribe_count * 2
    )
