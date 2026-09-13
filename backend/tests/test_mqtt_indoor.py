"""Grouped MQTT telemetry validates and persists each JSON field independently."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dynamic_thermal_charge.api.liveness import evaluate
from dynamic_thermal_charge.mqtt import IncomingMessage
from dynamic_thermal_charge.mqtt.indoor import ChargeTelemetryMessageProcessor
from dynamic_thermal_charge.mqtt.publisher import MqttPublisher, project_state
from dynamic_thermal_charge.mqtt.service import MqttService
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence.seed import example_installation
from tests.test_mqtt_publisher import _heartbeat


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def _configured(initialised_store):
    return ChargeTelemetryMessageProcessor(
        initialised_store.repository,
        initialised_store.planning,
        readings=initialised_store.indoor_readings,
        clock=lambda: NOW,
    )


def test_standard_topic_accepts_grouped_payload_without_persisted_topic(initialised_store):
    processor = ChargeTelemetryMessageProcessor(
        initialised_store.repository,
        initialised_store.planning,
        readings=initialised_store.indoor_readings,
        clock=lambda: NOW,
    )

    assert processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"indoor_temperature_c":19.5,"stored_soc_percent":60}',
        )
    )
    telemetry = initialised_store.planning.telemetry()["salon"]
    assert telemetry.indoor_temperature_c == 19.5
    assert telemetry.stored_soc_percent == 60


def test_valid_grouped_payload_updates_temperature_and_soc(initialised_store):
    processor = _configured(initialised_store)
    message = IncomingMessage(
        "telemetria/acumuladores/salon/telemetry",
        b'{"indoor_temperature_c":19.5,"stored_soc_percent":60}',
    )

    assert processor.handle(message)
    telemetry = initialised_store.planning.telemetry()["salon"]
    assert telemetry.indoor_temperature_c == 19.5
    assert telemetry.stored_soc_percent == 60
    assert telemetry.indoor_received_at == NOW
    assert telemetry.stored_soc_received_at == NOW
    reading = initialised_store.indoor_readings.read_all()["salon"]
    assert reading.celsius == 19.5
    assert reading.received_at == NOW


def test_legacy_topic_is_not_accepted(initialised_store):
    processor = _configured(initialised_store)

    assert not processor.handle(
        IncomingMessage(
            "ha/salon/telemetry",
            b'{"indoor_temperature_c":19.5,"stored_soc_percent":60}',
        )
    )
    assert initialised_store.planning.telemetry() == {}


def test_absent_field_preserves_last_valid_value_and_timestamp(initialised_store):
    processor = _configured(initialised_store)
    assert processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"indoor_temperature_c":19.5,"stored_soc_percent":60}',
        )
    )
    before = initialised_store.planning.telemetry()["salon"]

    assert processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"indoor_temperature_c":20.25}',
        )
    )
    after = initialised_store.planning.telemetry()["salon"]
    assert after.indoor_temperature_c == 20.25
    assert after.stored_soc_percent == before.stored_soc_percent
    assert after.stored_soc_received_at == before.stored_soc_received_at


@pytest.mark.parametrize(
    "payload",
    [
        b'{"indoor_temperature_c":85}',
        b'{"indoor_temperature_c":"not-a-number"}',
        b'{"indoor_temperature_c":null}',
    ],
)
def test_invalid_field_invalidates_only_that_field(initialised_store, payload, caplog):
    processor = _configured(initialised_store)
    assert processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"indoor_temperature_c":20,"stored_soc_percent":60}',
        )
    )

    assert not processor.handle(
        IncomingMessage("telemetria/acumuladores/salon/telemetry", payload)
    )
    telemetry = initialised_store.planning.telemetry()["salon"]
    assert telemetry.indoor_temperature_c is None
    assert telemetry.indoor_received_at is None
    assert telemetry.stored_soc_percent == 60
    assert telemetry.stored_soc_received_at == NOW
    assert "invalid indoor_temperature_c" in caplog.text.lower()
    assert "salon" not in initialised_store.indoor_readings.read_all()


def test_invalid_soc_does_not_erase_temperature(initialised_store):
    processor = _configured(initialised_store)
    assert processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"indoor_temperature_c":20,"stored_soc_percent":60}',
        )
    )

    assert not processor.handle(
        IncomingMessage(
            "telemetria/acumuladores/salon/telemetry",
            b'{"stored_soc_percent":101}',
        )
    )
    telemetry = initialised_store.planning.telemetry()["salon"]
    assert telemetry.indoor_temperature_c == 20
    assert telemetry.stored_soc_percent is None


def test_malformed_or_unknown_grouped_payload_is_ignored(initialised_store):
    processor = _configured(initialised_store)
    topic = "telemetria/acumuladores/salon/telemetry"
    assert not processor.handle(IncomingMessage(topic, b"not-json"))
    assert not processor.handle(
        IncomingMessage(topic, b'{"unrelated": 1}')
    )
    assert initialised_store.planning.telemetry() == {}


def test_topic_add_change_and_removal_reconcile_one_telemetry_subscription(mqtt_client):
    base = example_installation()
    current = [replace(base, heaters=(base.heaters[0],))]
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(current[0], evaluate(_heartbeat(), NOW), {}),
        subscriptions=lambda: tuple(
            topic
            for heater in current[0].heaters
            for topic in (
                topics.command(heater.id, "enabled"),
                topics.accumulator_topics(heater.id).telemetry,
            )
        ),
    )
    service = MqttService(
        mqtt_client, topics, host="broker", port=1883, publisher=publisher,
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()
    standard_salon = topics.accumulator_topics("salon").telemetry
    standard_entrada = topics.accumulator_topics("entrada").telemetry
    assert standard_salon in mqtt_client.subscriptions

    current[0] = replace(
        current[0],
        heaters=(base.heaters[1],),
    )
    service.run(max_cycles=1)
    assert standard_salon not in mqtt_client.subscriptions
    assert standard_entrada in mqtt_client.subscriptions
