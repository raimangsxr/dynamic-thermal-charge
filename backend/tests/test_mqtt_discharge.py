"""The discharge command: what enables it, what disables it, what is published."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.api.liveness import evaluate
from dynamic_thermal_charge.mqtt import MqttError
from dynamic_thermal_charge.mqtt.discharge import resolve_discharge_commands
from dynamic_thermal_charge.mqtt.publisher import MqttPublisher, project_state
from dynamic_thermal_charge.mqtt.service import MqttService
from dynamic_thermal_charge.mqtt.topics import TopicLayout
from dynamic_thermal_charge.persistence import Heartbeat
from dynamic_thermal_charge.persistence.seed import example_installation


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)
SLOT = timedelta(minutes=30)
HEATERS = ("salon", "entrada")
TOPICS = {
    "salon": {"damper_topic": "ha/salon/discharge", "setpoint_topic": "ha/salon/setpoint"},
    "entrada": {"damper_topic": "ha/entrada/discharge", "setpoint_topic": "ha/entrada/setpoint"},
}


def _heartbeat(*, age: int = 0) -> Heartbeat:
    return Heartbeat(
        updated_at=NOW - timedelta(seconds=age),
        started_at=NOW - timedelta(hours=3),
        degraded=False,
        poll_seconds=5,
        driver_kind="gpio",
        runner_id="runner-a",
    )


def _slot(offset: int, *, targets=None, heat=None) -> dict:
    return {
        "start": NOW + offset * SLOT,
        "end": NOW + (offset + 1) * SLOT,
        "target_temperature_c": dict(targets or {}),
        "heat_delivered_kwh": dict(heat or {}),
    }


def _plan(slots, *, status: str = "FEASIBLE") -> dict:
    return {"status": status, "slots": list(slots)}


def _commands(plan, **kwargs) -> dict[str, tuple[bool, float | None]]:
    resolved = resolve_discharge_commands(
        HEATERS, plan=plan, at=NOW, charge_config=TOPICS, **kwargs
    )
    return {item.heater_id: (item.enabled, item.setpoint_c) for item in resolved}


# --------------------------------------------------------------------------- #
# R1, R2, R3: what the plan asks for
# --------------------------------------------------------------------------- #

def test_an_active_target_enables_the_discharge_with_its_setpoint():
    plan = _plan([_slot(0, targets={"salon": 21.0})])

    assert _commands(plan) == {"salon": (True, 21.0), "entrada": (False, None)}


def test_the_window_rules_inside_the_window_even_with_no_projected_heat():
    """D2: the thermostat must stay able to react in a mild interval."""
    plan = _plan([_slot(0, targets={"salon": 21.0}, heat={"salon": 0.0})])

    assert _commands(plan)["salon"] == (True, 21.0)


def test_the_end_of_the_window_disables_the_discharge():
    plan = _plan(
        [
            _slot(-1, targets={"salon": 21.0}),
            _slot(0, heat={"salon": 0.0}),
        ]
    )

    assert _commands(plan)["salon"] == (False, None)


def test_projected_heat_before_a_target_enables_it_with_the_upcoming_setpoint():
    plan = _plan(
        [
            _slot(0, heat={"salon": 0.4}),
            _slot(1, targets={"salon": 20.5}),
        ]
    )

    assert _commands(plan)["salon"] == (True, 20.5)


def test_solver_noise_outside_a_window_does_not_enable_the_discharge():
    plan = _plan([_slot(0, heat={"salon": 1e-9}), _slot(1, targets={"salon": 20.5})])

    assert _commands(plan)["salon"] == (False, None)


def test_blank_command_topics_use_the_standard_topics():
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config={"salon": {"damper_topic": "  ", "setpoint_topic": " "}},
    )

    assert commands[0].damper_topic == "telemetria/acumuladores/salon/discharge"
    assert commands[0].setpoint_topic == "telemetria/acumuladores/salon/setpoint"


# --------------------------------------------------------------------------- #
# R5: every degraded condition disables the discharge
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("label", "kwargs", "plan"),
    [
        ("no active plan", {}, None),
        (
            "invalid plan",
            {},
            _plan([_slot(0, targets={"salon": 21.0})], status="INVALID"),
        ),
        (
            "automatic control off",
            {"automatic_control_enabled": False},
            _plan([_slot(0, targets={"salon": 21.0})]),
        ),
        (
            "heater in OFF",
            {"heater_modes": {"salon": "OFF"}},
            _plan([_slot(0, targets={"salon": 21.0})]),
        ),
        (
            "relay test in progress",
            {"relay_test_in_progress": True},
            _plan([_slot(0, targets={"salon": 21.0})]),
        ),
        (
            "controller state not current",
            {"controller_state_is_current": False},
            _plan([_slot(0, targets={"salon": 21.0})]),
        ),
        (
            "no slot covers now",
            {},
            _plan([_slot(3, targets={"salon": 21.0})]),
        ),
    ],
)
def test_a_degraded_condition_disables_the_discharge(label, kwargs, plan):
    assert _commands(plan, **kwargs)["salon"] == (False, None), label


# --------------------------------------------------------------------------- #
# R4, R6, R7, R10: what reaches the broker
# --------------------------------------------------------------------------- #

def _publisher(mqtt_client, commands):
    def snapshot():
        return project_state(
            example_installation(), evaluate(_heartbeat(), NOW), {"salon": False}
        )

    return MqttPublisher(mqtt_client, TopicLayout(), snapshot, discharge=lambda: commands)


def _published(mqtt_client, topic):
    return [item for item in mqtt_client.publications if item[0] == topic]


def test_the_command_and_its_setpoint_are_published_without_retention(mqtt_client):
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config=TOPICS,
    )
    _publisher(mqtt_client, commands).refresh()

    assert _published(mqtt_client, "ha/salon/discharge") == [
        ("ha/salon/discharge", "ON", 1, False)
    ]
    assert _published(mqtt_client, "ha/salon/setpoint") == [
        ("ha/salon/setpoint", "21.0", 1, False)
    ]
    assert _published(
        mqtt_client, "telemetria/acumuladores/salon/discharge"
    ) == []
    assert _published(mqtt_client, "telemetria/acumuladores/salon/setpoint") == []


def test_a_disabled_discharge_publishes_off_and_clears_the_setpoint(mqtt_client):
    commands = resolve_discharge_commands(
        ("salon",), plan=None, at=NOW, charge_config=TOPICS
    )
    _publisher(mqtt_client, commands).refresh()

    assert _published(mqtt_client, "ha/salon/discharge") == [
        ("ha/salon/discharge", "OFF", 1, False)
    ]
    assert _published(mqtt_client, "ha/salon/setpoint") == [
        ("ha/salon/setpoint", "NULL", 1, False)
    ]


def test_every_cycle_reasserts_the_command(mqtt_client):
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config=TOPICS,
    )
    publisher = _publisher(mqtt_client, commands)
    publisher.refresh()
    publisher.refresh()

    assert len(_published(mqtt_client, "ha/salon/discharge")) == 2


def test_the_published_heater_state_carries_the_commanded_discharge(mqtt_client):
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config=TOPICS,
    )
    _publisher(mqtt_client, commands).refresh()

    state = _published(mqtt_client, "dtc/installation/heater/salon/state")[-1]
    assert '"discharge_enabled":true' in state[1]


def test_a_heater_without_a_damper_topic_uses_the_standard_topic(
    mqtt_client, caplog
):
    caplog.set_level("WARNING")
    commands = resolve_discharge_commands(
        HEATERS,
        plan=_plan([_slot(0, targets={"salon": 21.0, "entrada": 18.0})]),
        at=NOW,
        charge_config={"entrada": TOPICS["entrada"]},
    )
    _publisher(mqtt_client, commands).refresh()

    assert _published(mqtt_client, "ha/entrada/discharge") == [
        ("ha/entrada/discharge", "ON", 1, False)
    ]
    assert _published(
        mqtt_client, "telemetria/acumuladores/salon/discharge"
    ) == [
        (
            "telemetria/acumuladores/salon/discharge",
            "ON",
            1,
            False,
        )
    ]
    assert "No damper topic is configured" not in caplog.text


def test_a_publication_failure_keeps_the_cycle_and_logs_once_per_transition(
    mqtt_client, caplog
):
    caplog.set_level("INFO")
    commands = resolve_discharge_commands(
        HEATERS,
        plan=_plan([_slot(0, targets={"salon": 21.0, "entrada": 18.0})]),
        at=NOW,
        charge_config=TOPICS,
    )
    original = mqtt_client.publish

    def failing(topic, payload, *, qos, retain):
        if topic == "ha/salon/discharge":
            raise MqttError("broker refused the command")
        original(topic, payload, qos=qos, retain=retain)

    mqtt_client.publish = failing
    publisher = _publisher(mqtt_client, commands)

    assert publisher.refresh() is True
    assert publisher.refresh() is True
    # The healthy accumulator still got both cycles.
    assert len(_published(mqtt_client, "ha/entrada/discharge")) == 2
    assert caplog.text.count("Could not publish the discharge command") == 1

    mqtt_client.publish = original
    publisher.refresh()
    assert "Every discharge command was published again" in caplog.text


def test_a_closed_damper_while_enabled_is_not_a_discrepancy(mqtt_client):
    """R8: the thermostat closing its damper on reaching the target is normal."""
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config=TOPICS,
    )

    def snapshot():
        installation, heaters = project_state(
            example_installation(), evaluate(_heartbeat(), NOW), {"salon": False}
        )
        heaters["salon"]["damper_position_percent"] = 0.0
        return installation, heaters

    publisher = MqttPublisher(
        mqtt_client, TopicLayout(), snapshot, discharge=lambda: commands
    )
    publisher.refresh()

    state = _published(mqtt_client, "dtc/installation/heater/salon/state")[-1]
    assert '"discharge_enabled":true' in state[1]
    assert '"damper_position_percent":0.0' in state[1]
    assert _published(mqtt_client, "ha/salon/discharge") == [
        ("ha/salon/discharge", "ON", 1, False)
    ]


def test_orderly_service_stop_publishes_off_without_retention(mqtt_client):
    commands = resolve_discharge_commands(
        ("salon",),
        plan=_plan([_slot(0, targets={"salon": 21.0})]),
        at=NOW,
        charge_config=TOPICS,
    )
    publisher = _publisher(mqtt_client, commands)
    service = MqttService(
        mqtt_client, TopicLayout(), host="broker", port=1883, publisher=publisher
    )
    service.start()
    mqtt_client.connect_result()
    service.process_events()
    mqtt_client.publications.clear()

    service.stop()

    assert _published(mqtt_client, "ha/salon/discharge") == [
        ("ha/salon/discharge", "OFF", 1, False)
    ]
    assert _published(mqtt_client, "ha/salon/setpoint") == [
        ("ha/salon/setpoint", "NULL", 1, False)
    ]
