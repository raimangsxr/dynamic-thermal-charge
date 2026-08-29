"""Strict, ordered and configuration-only MQTT commands."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from dynamic_thermal_charge.mqtt import IncomingMessage
from dynamic_thermal_charge.mqtt.commands import CommandProcessor
from dynamic_thermal_charge.mqtt.publisher import MqttPublisher, project_state
from dynamic_thermal_charge.mqtt.service import MqttService
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence import ConfigChange, ConfigConflictError
from dynamic_thermal_charge.persistence.seed import example_installation

from tests.test_mqtt_publisher import NOW, _heartbeat
from dynamic_thermal_charge.api.liveness import evaluate


class CommandRepository:
    def __init__(self, *, conflicts=0):
        self.config = example_installation()
        self.revision = 1
        self.conflicts = conflicts
        self.set_calls = []

    def current(self):
        return self.config, self.revision

    def set_field(self, revision, entity, heater_id, field, value):
        self.set_calls.append((revision, entity, heater_id, field, value))
        if self.conflicts:
            self.conflicts -= 1
            self.revision += 1
            raise ConfigConflictError("changed concurrently")
        heaters = []
        for heater in self.config.heaters:
            if heater.id != heater_id:
                heaters.append(heater)
            elif field == "enabled":
                heaters.append(replace(heater, enabled=value == "true"))
            elif field == "target_charge":
                heaters.append(replace(heater, target_charge=float(value)))
        self.config = replace(self.config, heaters=tuple(heaters))
        before = self.revision
        self.revision += 1
        return ConfigChange(
            entity="heater", entity_key=heater_id, field=field,
            old_value=None, new_value=value, action="set",
            revision_before=before, revision_after=self.revision,
        )


def _processor(repository=None, republished=None):
    repository = repository or CommandRepository()
    republished = republished if republished is not None else []
    processor = CommandProcessor(
        repository, TopicLayout(), republish=republished.append
    )
    return processor, repository, republished


@pytest.mark.parametrize(
    ("field", "payload", "expected"),
    [
        ("enabled", "ON", True),
        ("enabled", "OFF", False),
        ("target_charge", "0", 0.0),
        ("target_charge", "0.45", 0.45),
        ("target_charge", "1", 1.0),
    ],
)
def test_valid_commands_update_only_the_requested_configuration(field, payload, expected):
    processor, repository, _ = _processor()
    assert processor.handle(
        IncomingMessage(f"dtc/installation/heater/salon/set/{field}", payload.encode())
    )
    heater = next(h for h in repository.config.heaters if h.id == "salon")
    assert getattr(heater, field) == expected


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("enabled", ""), ("enabled", "true"),
        ("target_charge", ""), ("target_charge", "abc"),
        ("target_charge", "-0.1"), ("target_charge", "1.1"),
    ],
)
def test_invalid_payload_or_unknown_heater_is_rejected_and_republished(field, payload):
    processor, repository, republished = _processor()
    assert not processor.handle(
        IncomingMessage(f"dtc/installation/heater/salon/set/{field}", payload.encode())
    )
    assert repository.set_calls == []
    assert republished == ["salon"]

    assert not processor.handle(
        IncomingMessage(f"dtc/installation/heater/no-existe/set/{field}", b"ON")
    )
    assert repository.set_calls == []
    assert republished[-1] == "no-existe"


@pytest.mark.parametrize("field", ["power", "pin", "active_high", "future_field"])
def test_structural_allowlist_rejects_every_other_field(field):
    processor, repository, _ = _processor()
    assert not processor.handle(
        IncomingMessage(f"dtc/installation/heater/salon/set/{field}", b"1")
    )
    assert repository.set_calls == []


def test_one_conflict_is_retried_once_and_a_second_conflict_stops():
    processor, repository, _ = _processor(CommandRepository(conflicts=1))
    assert processor.handle(
        IncomingMessage("dtc/installation/heater/salon/set/enabled", b"OFF")
    )
    assert len(repository.set_calls) == 2

    processor, repository, _ = _processor(CommandRepository(conflicts=2))
    assert not processor.handle(
        IncomingMessage("dtc/installation/heater/salon/set/enabled", b"OFF")
    )
    assert len(repository.set_calls) == 2


def test_retained_command_is_rejected_before_payload_parsing():
    processor, repository, republished = _processor()
    assert not processor.handle(
        IncomingMessage(
            "dtc/installation/heater/salon/set/enabled", b"\xff", retain=True
        )
    )
    assert repository.set_calls == []
    assert republished == ["salon"]


def test_contradictory_commands_are_applied_in_arrival_order_through_service(mqtt_client):
    processor, repository, _ = _processor()
    service = MqttService(
        mqtt_client, TopicLayout(), host="broker", port=1883,
        command_handler=processor.handle,
    )
    service.start()
    mqtt_client.inject("dtc/installation/heater/salon/set/enabled", "OFF")
    mqtt_client.inject("dtc/installation/heater/salon/set/enabled", "ON")
    service.process_events()
    assert [call[-1] for call in repository.set_calls] == ["false", "true"]


def test_every_result_republishes_qos_one_retained_stored_state(mqtt_client):
    repository = CommandRepository()
    topics = TopicLayout()
    publisher = MqttPublisher(
        mqtt_client,
        topics,
        lambda: project_state(
            repository.config, evaluate(_heartbeat(), NOW), {}
        ),
    )
    processor = CommandProcessor(
        repository, topics, republish=publisher.republish_heater
    )
    assert not processor.handle(
        IncomingMessage(topics.command("salon", "target_charge"), b"9")
    )
    topic, payload, qos, retained = mqtt_client.publications[-1]
    assert topic == topics.heater_state("salon")
    assert json.loads(payload)["target_charge"] == 1.0
    assert (qos, retained) == (1, True)


def test_accepted_target_is_visible_to_the_next_plan_input():
    processor, repository, _ = _processor()
    assert processor.handle(
        IncomingMessage(
            "dtc/installation/heater/salon/set/target_charge", b"0.5"
        )
    )
    heater = next(h for h in repository.current()[0].heaters if h.id == "salon")
    assert heater.requested_charge_minutes == heater.full_charge_minutes // 2
