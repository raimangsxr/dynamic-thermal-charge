"""Indoor MQTT inputs use the local receive clock and invalidate bad data."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.mqtt import IncomingMessage
from dynamic_thermal_charge.mqtt.indoor import IndoorMessageProcessor
from dynamic_thermal_charge.mqtt.publisher import MqttPublisher, project_state
from dynamic_thermal_charge.mqtt.service import MqttService
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.api.liveness import evaluate
from tests.test_mqtt_publisher import _heartbeat


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def _configured(initialised_store):
    config, revision = initialised_store.repository.current()
    initialised_store.repository.set_field(
        revision, "heater", "salon", "indoor_topic", "ha/salon/temp"
    )
    return IndoorMessageProcessor(
        initialised_store.repository,
        initialised_store.indoor_readings,
        clock=lambda: NOW,
    )


def test_valid_payload_replaces_previous_reading_with_local_receive_time(initialised_store):
    processor = _configured(initialised_store)
    assert processor.handle(IncomingMessage("ha/salon/temp", b"19.5"))
    first = initialised_store.indoor_readings.read_all()["salon"]
    assert first.celsius == 19.5 and first.received_at == NOW

    assert processor.handle(IncomingMessage("ha/salon/temp", b"20.25"))
    assert initialised_store.indoor_readings.read_all()["salon"].celsius == 20.25


@pytest.mark.parametrize("payload", [b"", b"not-a-number", b"85", b"-127"])
def test_invalid_or_implausible_payload_immediately_invalidates_previous(
    initialised_store, payload, caplog
):
    processor = _configured(initialised_store)
    processor.handle(IncomingMessage("ha/salon/temp", b"20"))
    assert not processor.handle(IncomingMessage("ha/salon/temp", payload))
    assert "salon" not in initialised_store.indoor_readings.read_all()
    assert "invalid indoor temperature" in caplog.text.lower()


def test_topic_add_change_and_removal_reconcile_subscriptions(mqtt_client):
    base = example_installation()
    current = [replace(base, heaters=(replace(base.heaters[0], indoor_topic="ha/old"),))]
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(current[0], evaluate(_heartbeat(), NOW), {}),
        subscriptions=lambda: tuple(
            topic for heater in current[0].heaters
            for topic in (
                topics.command(heater.id, "enabled"),
                topics.command(heater.id, "target_charge"),
                *((heater.indoor_topic,) if heater.indoor_topic else ()),
            )
        ),
    )
    service = MqttService(
        mqtt_client, topics, host="broker", port=1883, publisher=publisher,
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()
    assert "ha/old" in mqtt_client.subscriptions

    current[0] = replace(current[0], heaters=(replace(current[0].heaters[0], indoor_topic="ha/new"),))
    service.run(max_cycles=1)
    assert "ha/old" not in mqtt_client.subscriptions
    assert "ha/new" in mqtt_client.subscriptions

    current[0] = replace(current[0], heaters=(replace(current[0].heaters[0], indoor_topic=None),))
    service.run(max_cycles=1)
    assert "ha/new" not in mqtt_client.subscriptions
