from dataclasses import replace
from types import SimpleNamespace

from dynamic_thermal_charge.mqtt.service import MqttService, MqttSupervisor
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.system_settings import MqttSystemSettings


class ConfigurationRepository:
    def __init__(self, mqtt):
        self.mqtt = mqtt

    def current(self):
        return SimpleNamespace(configuration=SimpleNamespace(mqtt=self.mqtt))


def test_disabled_startup_does_not_create_transport_or_touch_mqtt(mqtt_client):
    repository = ConfigurationRepository(MqttSystemSettings())
    created = []

    def build_service():
        created.append(True)
        return MqttService(mqtt_client, TopicLayout(), host="broker", port=1883)

    MqttSupervisor(repository, build_service, wait=lambda _seconds: None).run(
        max_cycles=2
    )

    assert created == []
    assert mqtt_client.events == []
    assert mqtt_client.publications == []
    assert mqtt_client.subscriptions == []


def test_enable_and_disable_reconciles_connection_without_restarting_supervisor(
    mqtt_client, clock
):
    repository = ConfigurationRepository(MqttSystemSettings())
    created = []
    waits = 0

    def build_service():
        service = MqttService(
            mqtt_client,
            TopicLayout(),
            host="broker",
            port=1883,
            clock=clock,
        )
        created.append(service)
        return service

    def wait(_seconds):
        nonlocal waits
        waits += 1
        if waits == 1:
            repository.mqtt = replace(repository.mqtt, enabled=True, host="broker")
        elif waits == 2:
            mqtt_client.connect_result()
        elif waits == 3:
            repository.mqtt = replace(repository.mqtt, enabled=False)
        clock.advance(seconds=1)

    supervisor = MqttSupervisor(repository, build_service, wait=wait, clock=clock)
    supervisor.run(max_cycles=4)

    assert len(created) == 1
    assert ("connect", "broker", 1883) in mqtt_client.events
    assert ("loop_start",) in mqtt_client.events
    assert ("disconnect",) in mqtt_client.events
    assert ("loop_stop",) in mqtt_client.events
    assert supervisor.service is None
