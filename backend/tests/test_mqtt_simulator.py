from types import SimpleNamespace

from dynamic_thermal_charge.models import Heater, OutputConfig
from dynamic_thermal_charge.mqtt.simulator import (
    MqttPlanningSimulator,
    MqttSimulationConfig,
    MqttSimulationService,
    MqttSimulationSupervisor,
    advance_temperature,
    advance_stored_charge,
    heater_telemetry_topics,
    simulation_subscription_topics,
    simulation_topics,
    simulated_hours,
    stored_charge_to_temperature,
    temperature_to_stored_charge_percent,
)


class RecordingClient:
    def __init__(self) -> None:
        self.publications: list[tuple[str, str]] = []
        self.events: list[tuple[str, ...]] = []

    def publish(self, topic: str, payload: str, *, qos: int, retain: bool) -> None:
        self.publications.append((topic, payload))

    def connect_async(self, host: str, port: int) -> None:
        self.events.append(("connect", host, port))

    def loop_start(self) -> None:
        self.events.append(("loop_start",))

    def disconnect(self) -> None:
        self.events.append(("disconnect",))

    def loop_stop(self) -> None:
        self.events.append(("loop_stop",))


def _heater(heater_id: str = "salon", demand_factor: float = 1.0, **topics: str) -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id,
        model="test",
        power_w=1000,
        full_charge_minutes=480,
        target_charge=1.0,
        priority=0,
        output=OutputConfig(),
        enabled=True,
        temperature_topic=topics.get("temperature_topic"),
        target_temperature_topic=topics.get("target_temperature_topic"),
        stored_charge_topic=topics.get("stored_charge_topic"),
        demand_factor=demand_factor,
    )


def test_simulation_clock_uses_ten_seconds_per_simulated_hour_by_default():
    assert simulated_hours(10.0, 10.0) == 1.0
    assert simulated_hours(5.0, 10.0) == 0.5


def test_stored_charge_discharge_uses_demand_factor_and_charge_rate():
    idle = advance_stored_charge(
        50.0,
        charging=False,
        thermal_loss_c_per_hour=2.0,
        demand_factor=2.0,
        full_charge_minutes=480,
        elapsed_hours=1.0,
    )
    charging = advance_stored_charge(
        50.0,
        charging=True,
        thermal_loss_c_per_hour=2.0,
        demand_factor=2.0,
        full_charge_minutes=480,
        elapsed_hours=1.0,
    )
    assert idle == 42.0
    assert charging == 62.5
    assert stored_charge_to_temperature(idle) == 41.0


def test_advance_temperature_cools_when_idle_and_heats_when_charging():
    assert advance_temperature(
        50.0,
        charging=False,
        thermal_loss_c_per_hour=2.0,
        elapsed_hours=1.0,
    ) == 48.0
    assert advance_temperature(
        50.0,
        charging=True,
        thermal_loss_c_per_hour=2.0,
        elapsed_hours=1.0,
    ) == 52.0


def test_temperature_to_stored_charge_percent_maps_between_bounds():
    assert temperature_to_stored_charge_percent(20.0) == 0.0
    assert temperature_to_stored_charge_percent(70.0) == 100.0
    assert temperature_to_stored_charge_percent(45.0) == 50.0


def test_simulation_topics_use_prefix_when_heater_topics_missing():
    heater = _heater()
    assert simulation_topics(heater, topic_prefix="dtc/sim") == (
        "dtc/sim/salon/temperature",
        "dtc/sim/salon/target",
        "dtc/sim/salon/stored_charge",
    )


def test_simulation_topics_prefer_configured_heater_topics():
    heater = _heater(
        temperature_topic="custom/temp",
        target_temperature_topic="custom/target",
        stored_charge_topic="custom/soc",
    )
    assert simulation_topics(heater, topic_prefix="dtc/sim") == (
        "custom/temp",
        "custom/target",
        "custom/soc",
    )


def test_heater_telemetry_topics_use_simulation_prefix_when_enabled():
    heater = _heater()
    config = MqttSimulationConfig(
        enabled=True,
        initial_temperature_c=45.0,
        publish_seconds=30.0,
        topic_prefix="dtc/sim",
        thermal_loss_c_per_hour=2.0,
    )
    topics = heater_telemetry_topics(heater, simulation=config)
    assert topics == {
        "dtc/sim/salon/temperature": "temperature_c",
        "dtc/sim/salon/target": "target_temperature_c",
        "dtc/sim/salon/stored_charge": "stored_charge_percent",
    }


def test_simulation_subscription_topics_include_all_enabled_heaters():
    site = {
        "mqtt_simulation_enabled": True,
        "mqtt_simulation_topic_prefix": "dtc/sim",
    }
    topics = simulation_subscription_topics(
        (_heater("salon"), _heater("entrada")),
        site,
        mqtt_enabled=True,
    )
    assert "dtc/sim/salon/temperature" in topics
    assert "dtc/sim/entrada/stored_charge" in topics


def test_simulator_logs_and_publishes_three_topics_per_heater(caplog):
    import logging

    caplog.set_level(logging.INFO)
    client = RecordingClient()
    config = MqttSimulationConfig(
        enabled=True,
        initial_temperature_c=45.0,
        publish_seconds=30.0,
        topic_prefix="dtc/sim",
        thermal_loss_c_per_hour=2.0,
    )
    simulator = MqttPlanningSimulator(
        client,
        config_provider=lambda: config,
        heaters_provider=lambda: (_heater(),),
        charging_state_provider=lambda: {"salon": False},
        clock=lambda: __import__("datetime").datetime(
            2026, 1, 1, 12, 0, tzinfo=__import__("datetime").timezone.utc
        ),
    )
    simulator.publish_cycle()
    topics = {topic for topic, _payload in client.publications}
    assert topics == {
        "dtc/sim/salon/temperature",
        "dtc/sim/salon/target",
        "dtc/sim/salon/stored_charge",
    }
    assert "Published simulated telemetry for 1 heater(s)" in caplog.text
    assert "dtc/sim/salon/temperature=45.00" in caplog.text
    assert "dtc/sim/salon/target=55.00" in caplog.text
    assert "dtc/sim/salon/stored_charge=50.0" in caplog.text


def test_simulator_advances_one_simulated_hour_and_records_coherent_sample():
    from datetime import datetime, timedelta, timezone

    client = RecordingClient()
    config = MqttSimulationConfig(
        enabled=True,
        initial_temperature_c=45.0,
        publish_seconds=10.0,
        topic_prefix="dtc/sim",
        thermal_loss_c_per_hour=2.0,
        seconds_per_hour=10.0,
    )
    now = [datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)]
    charging = [False]
    simulator = MqttPlanningSimulator(
        client,
        config_provider=lambda: config,
        heaters_provider=lambda: (_heater(demand_factor=2.0),),
        charging_state_provider=lambda: {"salon": charging[0]},
        clock=lambda: now[0],
    )
    simulator.publish_cycle()
    now[0] += timedelta(seconds=10)
    simulator.publish_cycle()

    sample = simulator.samples()[-1]
    assert sample.heater_id == "salon"
    assert sample.temperature_c == 41.0
    assert sample.stored_charge_percent == 42.0
    assert sample.target_temperature_c == 55.0
    assert sample.power_w == 0

    charging[0] = True
    now[0] += timedelta(seconds=10)
    simulator.publish_cycle()
    sample = simulator.samples()[-1]
    assert sample.charging is True
    assert sample.stored_charge_percent == 54.5
    assert sample.power_w == 1000


def test_simulator_applies_a_changed_clock_ratio_without_restart():
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone

    client = RecordingClient()
    config = [
        MqttSimulationConfig(
            enabled=True,
            initial_temperature_c=45.0,
            publish_seconds=10.0,
            topic_prefix="dtc/sim",
            thermal_loss_c_per_hour=2.0,
            seconds_per_hour=10.0,
        )
    ]
    now = [datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)]
    simulator = MqttPlanningSimulator(
        client,
        config_provider=lambda: config[0],
        heaters_provider=lambda: (_heater(),),
        charging_state_provider=lambda: {"salon": False},
        clock=lambda: now[0],
    )
    simulator.publish_cycle()
    now[0] += timedelta(seconds=10)
    simulator.publish_cycle()
    config[0] = replace(config[0], seconds_per_hour=20.0)
    now[0] += timedelta(seconds=20)
    simulator.publish_cycle()

    assert [sample.stored_charge_percent for sample in simulator.samples()] == [50.0, 46.0, 42.0]


def test_simulator_supervisor_starts_only_when_enabled_and_mqtt_is_on():
    client = RecordingClient()
    site = {
        "mqtt_simulation_enabled": False,
        "mqtt_simulation_publish_seconds": 30.0,
    }
    system = SimpleNamespace(configuration=SimpleNamespace(mqtt=SimpleNamespace(enabled=True, host="broker", port=1883)))
    repository = SimpleNamespace(current=lambda: system)
    planning = SimpleNamespace(site=lambda: site)
    simulator = MqttPlanningSimulator(
        client,
        config_provider=lambda: MqttSimulationConfig(
            enabled=False,
            initial_temperature_c=45.0,
            publish_seconds=30.0,
            topic_prefix="dtc/sim",
            thermal_loss_c_per_hour=2.0,
        ),
        heaters_provider=lambda: (),
        charging_state_provider=lambda: {},
    )
    supervisor = MqttSimulationSupervisor(
        repository,
        planning,
        lambda: MqttSimulationService(client=client, simulator=simulator),
        wait=lambda _seconds: None,
    )
    supervisor.run(max_cycles=2)
    assert client.events == []


def test_simulator_supervisor_connects_when_enabled():
    client = RecordingClient()
    site = {
        "mqtt_simulation_enabled": True,
        "mqtt_simulation_publish_seconds": 30.0,
    }
    system = SimpleNamespace(configuration=SimpleNamespace(mqtt=SimpleNamespace(enabled=True, host="broker", port=1883)))
    repository = SimpleNamespace(current=lambda: system)
    planning = SimpleNamespace(site=lambda: site)
    simulator = MqttPlanningSimulator(
        client,
        config_provider=lambda: MqttSimulationConfig(
            enabled=True,
            initial_temperature_c=45.0,
            publish_seconds=30.0,
            topic_prefix="dtc/sim",
            thermal_loss_c_per_hour=2.0,
        ),
        heaters_provider=lambda: (_heater(),),
        charging_state_provider=lambda: {"salon": True},
    )
    supervisor = MqttSimulationSupervisor(
        repository,
        planning,
        lambda: MqttSimulationService(client=client, simulator=simulator),
        wait=lambda _seconds: None,
    )
    supervisor.run(max_cycles=1)
    assert ("connect", "broker", 1883) in client.events
    assert ("loop_start",) in client.events
    assert client.publications
    supervisor.stop()
    assert ("disconnect",) in client.events
    assert ("loop_stop",) in client.events
