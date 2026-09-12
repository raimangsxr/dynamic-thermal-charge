from dataclasses import replace
from types import SimpleNamespace

from dynamic_thermal_charge.mqtt.service import MqttService, MqttSupervisor
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.system_settings import MqttSystemSettings


class ConfigurationRepository:
    def __init__(self, mqtt):
        self.mqtt = mqtt
        self.secrets = {}

    def current(self):
        return SimpleNamespace(
            configuration=SimpleNamespace(mqtt=self.mqtt), secrets=self.secrets
        )


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


def test_mqtt_settings_change_recreates_service_once_with_current_configuration(
    mqtt_client, clock
):
    repository = ConfigurationRepository(
        MqttSystemSettings(enabled=True, host="broker", publish_seconds=15)
    )
    created = []
    waits = 0

    def build_service():
        service = MqttService(
            mqtt_client,
            TopicLayout(),
            host=repository.mqtt.host or "",
            port=repository.mqtt.port,
            clock=clock,
        )
        created.append(service)
        return service

    def wait(_seconds):
        nonlocal waits
        waits += 1
        if waits == 1:
            repository.mqtt = replace(repository.mqtt, host="new-broker")
        clock.advance(seconds=1)

    supervisor = MqttSupervisor(repository, build_service, wait=wait, clock=clock)
    supervisor.run(max_cycles=2)

    assert len(created) == 2
    assert ("connect", "broker", 1883) in mqtt_client.events
    assert ("connect", "new-broker", 1883) in mqtt_client.events
    assert mqtt_client.events.count(("disconnect",)) == 1


def test_mqtt_credentials_change_recreates_service_but_other_sections_do_not(
    mqtt_client, clock
):
    repository = ConfigurationRepository(
        MqttSystemSettings(enabled=True, host="broker")
    )
    created = []
    waits = 0

    def build_service():
        created.append(True)
        return MqttService(
            mqtt_client, TopicLayout(), host="broker", port=1883, clock=clock
        )

    def wait(_seconds):
        nonlocal waits
        waits += 1
        if waits == 1:
            repository.secrets["mqtt_username"] = SimpleNamespace(value="user")
            repository.secrets["mqtt_password"] = SimpleNamespace(value="first")
        elif waits == 2:
            repository.secrets["mqtt_password"] = SimpleNamespace(value="second")
        clock.advance(seconds=1)

    supervisor = MqttSupervisor(repository, build_service, wait=wait, clock=clock)
    supervisor.run(max_cycles=3)
    assert len(created) == 3

    # Mutating an unrelated field in the same snapshot is not part of the
    # runtime signature and does not create another client.
    repository.other_section = "changed"
    supervisor.run(max_cycles=1)
    assert len(created) == 3
