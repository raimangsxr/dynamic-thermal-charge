"""The durable operational contract used by local Home Assistant clients."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from dynamic_thermal_charge.charge_planning import (
    AutomaticPlan,
    AutomaticPlanSlot,
    FEASIBLE,
)
from dynamic_thermal_charge.persistence import ConfigConflictError, ConfigValidationError
from tests.conftest import API_NOW, AUTH


def test_installation_identity_survives_a_name_change(initialised_store):
    controls = initialised_store.home_assistant
    installation_id = controls.installation_uuid()
    UUID(installation_id)

    _config, revision = initialised_store.repository.current()
    initialised_store.repository.set_field(
        revision,
        "installation",
        None,
        "name",
        "Casa renovada",
    )

    assert controls.installation_uuid() == installation_id
    assert initialised_store.repository.installation_name() == "Casa renovada"


def test_automatic_off_invalidates_plan_and_uses_optimistic_revision(initialised_store):
    config, revision = initialised_store.repository.current()
    heater_id = config.heaters[0].id
    plan = AutomaticPlan(
        API_NOW,
        API_NOW + timedelta(minutes=30),
        30,
        (
            AutomaticPlanSlot(
                API_NOW,
                API_NOW + timedelta(minutes=30),
                (heater_id,),
                config.heaters[0].power_w,
                {heater_id: 50.0},
                {heater_id: 75.0},
                initial_soc_percent={heater_id: 50.0},
            ),
        ),
        (),
        FEASIBLE,
        (),
        "home-assistant-control-test",
        API_NOW,
    )
    initialised_store.planning.save_plan(
        plan,
        configuration_revision=revision,
        constraints_revision=initialised_store.planning.site()["revision"],
        reason="test",
        active=True,
    )
    assert initialised_store.planning.active_plan() is not None

    result = initialised_store.home_assistant.set_automatic_control(
        False,
        expected_revision=revision,
    )

    assert result.changed is True
    assert result.state.automatic_control_enabled is False
    assert result.state.recalculation_pending is True
    assert initialised_store.planning.active_plan() is None
    with pytest.raises(ConfigConflictError):
        initialised_store.home_assistant.request_recalculation(expected_revision=revision)


def test_accumulator_mode_is_durable_and_validated(initialised_store):
    controls = initialised_store.home_assistant
    state = controls.control_state()

    result = controls.set_heater_mode(
        "salon",
        "OFF",
        expected_revision=state.revision,
    )
    assert result.state.heater_modes["salon"] == "OFF"
    assert result.state.heater_enabled("salon") is False

    unchanged = controls.set_heater_mode(
        "salon",
        "OFF",
        expected_revision=result.state.revision,
    )
    assert unchanged.changed is False
    with pytest.raises(ConfigValidationError):
        controls.set_heater_mode(
            "salon",
            "HEAT",
            expected_revision=unchanged.state.revision,
        )


def test_active_target_update_changes_only_the_current_weekly_rule(initialised_store):
    controls = initialised_store.home_assistant
    state = controls.control_state()

    result = controls.set_active_temperature_target(
        "salon",
        22.5,
        at=API_NOW,
        expected_revision=state.revision,
    )

    assert result.state.revision == state.revision + 1
    config, _revision = initialised_store.repository.current()
    salon = next(item for item in config.heaters if item.id == "salon")
    assert salon.temperature_targets[0].target_temperature_c == 22.5


def test_operational_snapshot_and_commands_are_authenticated(client):
    response = client.get("/api/v1/operational/snapshot", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    UUID(body["installation"]["id"])
    assert body["health"] == "error"
    assert body["power"]["instant_w"] is None
    assert {item["id"] for item in body["accumulators"]} == {
        "salon",
        "entrada",
        "habitaciones",
        "buhardilla",
    }

    command = client.post(
        "/api/v1/operational/control/automatic",
        headers=AUTH,
        json={"enabled": False, "expected_revision": body["revision"]},
    )
    assert command.status_code == 200, command.text
    assert command.json()["automatic_control_enabled"] is False

    stale = client.post(
        "/api/v1/operational/recalculate",
        headers=AUTH,
        json={"expected_revision": body["revision"]},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "config_conflict"


def test_damper_telemetry_is_read_only_and_bounded(initialised_store):
    initialised_store.planning.record_telemetry(
        "salon",
        "damper_position_percent",
        42.5,
        API_NOW,
    )
    assert (
        initialised_store.planning.telemetry()["salon"].damper_position_percent
        == 42.5
    )
    with pytest.raises(ConfigValidationError):
        initialised_store.planning.record_telemetry(
            "salon",
            "damper_position_percent",
            101,
            API_NOW,
        )
