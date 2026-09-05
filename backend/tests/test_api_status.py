"""The state endpoint: FR-013, FR-016, FR-018, FR-020, and honesty about it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.scheduler import ChargeScheduler
from dynamic_thermal_charge.weather import HourlyForecastPoint, OutdoorForecast
from tests.conftest import API_NOW, AUTH


WINDOW_START = API_NOW - timedelta(hours=1)


@pytest.fixture
def recorded_night(initialised_store, recorder):
    """A plan in progress, its forecast, and the transitions that switched it on."""
    config, revision = initialised_store.repository.current()
    requested = {heater.id: 480 for heater in config.heaters}
    plan = ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START, requested_charge_minutes=requested
    )
    forecast_ref = recorder.record_forecast(
        OutdoorForecast(
            date=WINDOW_START.date(),
            average_temperature_c=8.0,
            minimum_temperature_c=3.0,
            maximum_temperature_c=13.0,
            source="simulated",
            from_fallback=True,
        )
    )
    plan_ref = recorder.record_plan(
        plan, forecast_ref, installation_revision=revision, requested_minutes=requested
    )
    # The heaters the plan has running in the slot that contains API_NOW.
    active = next(
        slot.heater_ids for slot in plan.slots if slot.start <= API_NOW < slot.end
    )
    for heater_id in active:
        recorder.record_transition(heater_id, True, WINDOW_START, plan_ref)
    return plan, plan_ref, set(active)


def _status(client):
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# The current state (FR-013)
# --------------------------------------------------------------------------- #

def test_a_live_controller_yields_a_current_state(client, heartbeat, recorded_night):
    heartbeat.publish(API_NOW, degraded=False)
    body = _status(client)

    assert body["observed_at"].startswith("2026-01-16T01:00")
    assert body["controller"]["liveness"] == "live"
    assert body["controller"]["state_is_current"] is True
    assert body["controller"]["driver_kind"] == "gpio"
    assert body["controller"]["age_seconds"] == 0.0


def test_the_active_heaters_and_the_power_are_reported(client, heartbeat, recorded_night):
    _plan, _ref, active = recorded_night
    heartbeat.publish(API_NOW, degraded=False)
    body = _status(client)

    reported_on = {h["id"] for h in body["heaters"] if h["output_on"]}
    assert reported_on == active
    expected_w = sum(
        h["power_w"] for h in body["heaters"] if h["id"] in active
    )
    assert body["power"]["instant_w"] == expected_w
    assert body["power"]["limit_w"] == 5200
    assert body["power"]["percent_of_limit"] == pytest.approx(
        round(100.0 * expected_w / 5200, 1)
    )


def test_the_plan_in_progress_is_reported_with_its_window(client, heartbeat, recorded_night):
    heartbeat.publish(API_NOW, degraded=False)
    plan = _status(client)["plan"]
    assert plan is not None
    assert plan["window_start"].startswith("2026-01-16T00:00")
    assert plan["slot_minutes"] == 30
    assert plan["installation_revision"] == 1
    assert plan["slots"]


def test_a_fallback_forecast_is_reported_as_fallback(client, heartbeat, recorded_night):
    """FR-017: the history answers 'did the real provider work that night'."""
    heartbeat.publish(API_NOW, degraded=False)
    forecast = _status(client)["forecast"]
    assert forecast["source"] == "fallback"
    assert forecast["average_temperature_c"] == 8.0


def test_unmet_minutes_are_reported(client, heartbeat, recorded_night):
    heartbeat.publish(API_NOW, degraded=False)
    allocations = _status(client)["allocations"]
    assert allocations
    assert any(a["unmet_minutes"] > 0 for a in allocations)
    for allocation in allocations:
        assert allocation["requested_minutes"] == 480


def test_planning_endpoint_returns_hourly_series_and_all_intervals(
    client, initialised_store, recorder, api_clock
):
    config, revision = initialised_store.repository.current()
    points = tuple(
        HourlyForecastPoint(API_NOW - timedelta(hours=1) + timedelta(hours=index), 4 + index)
        for index in range(49)
    )
    recorder.record_forecast(
        OutdoorForecast(
            date=API_NOW.date(), average_temperature_c=8, minimum_temperature_c=4,
            maximum_temperature_c=12, source="aemet", hourly_points=points,
        )
    )
    for heater in config.heaters:
        for field, value in (("temperature_c", 21), ("target_temperature_c", 21), ("stored_charge_percent", 100)):
            initialised_store.planning.record_telemetry(heater.id, field, value, API_NOW)
    activated = client.post(
        "/api/v1/planning/activate",
        headers=AUTH,
        json={"token": client.post(
            "/api/v1/planning/preview",
            headers=AUTH,
            json={"constraints": [], "expected_revision": revision},
        ).json()["token"], "constraints": [], "expected_revision": revision},
    )
    assert activated.status_code == 200, activated.text
    response = client.get("/api/v1/planning", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["forecast"]["hourly_points"]
    assert len(body["plan"]["slots"]) > 0
    assert len(body["timeline"]) == 24 * 60 // config.site.slot_minutes
    assert body["horizon_end"]
    assert body["max_total_power_w"] == config.site.max_total_power_w
    salon_minutes = [slot["charge_minutes_by_heater"]["salon"] for slot in body["timeline"][:4]]
    assert salon_minutes[0] >= salon_minutes[-1]


def test_planning_endpoint_excludes_past_forecast_hours(
    client, initialised_store, recorder, api_clock
):
    now = datetime(2026, 9, 2, 22, 0, tzinfo=timezone.utc)
    api_clock.now = now
    points = (
        HourlyForecastPoint(datetime(2026, 9, 2, 20, tzinfo=timezone.utc), 10),
        HourlyForecastPoint(datetime(2026, 9, 2, 21, tzinfo=timezone.utc), 11),
        HourlyForecastPoint(datetime(2026, 9, 2, 22, tzinfo=timezone.utc), 12),
        HourlyForecastPoint(datetime(2026, 9, 3, 0, tzinfo=timezone.utc), 8),
    )
    recorder.record_forecast(
        OutdoorForecast(
            date=now.date(),
            average_temperature_c=10,
            minimum_temperature_c=8,
            maximum_temperature_c=12,
            source="aemet",
            hourly_points=points,
        )
    )
    response = client.get("/api/v1/planning", headers=AUTH)

    assert response.status_code == 200
    assert [point["temperature_c"] for point in response.json()["forecast"]["hourly_points"]] == [12, 8]


def test_planning_endpoint_prefers_automatic_plan_slot_minutes_over_legacy_plan(
    client, initialised_store, recorder
):
    from dynamic_thermal_charge.charge_planning import AutomaticPlan, AutomaticPlanSlot, FEASIBLE

    config, revision = initialised_store.repository.current()
    heater_id = config.heaters[0].id
    legacy_points = (
        HourlyForecastPoint(API_NOW, 8.0),
        HourlyForecastPoint(API_NOW + timedelta(hours=1), 8.0),
    )
    legacy_ref = recorder.record_forecast(
        OutdoorForecast(
            date=API_NOW.date(),
            average_temperature_c=8.0,
            minimum_temperature_c=8.0,
            maximum_temperature_c=8.0,
            source="simulated",
            hourly_points=legacy_points,
        )
    )
    legacy_plan = ChargeScheduler().build(
        config.site,
        config.heaters,
        WINDOW_START,
        requested_charge_minutes={heater.id: 0 for heater in config.heaters},
        hourly_points=legacy_points,
        fallback_temperature_c=8.0,
    )
    recorder.record_plan(legacy_plan, legacy_ref, revision)

    start = API_NOW
    automatic = AutomaticPlan(
        start,
        start + timedelta(minutes=15),
        15,
        (
            AutomaticPlanSlot(
                start,
                start + timedelta(minutes=15),
                (heater_id,),
                config.heaters[0].power_w,
                {heater_id: 50.0},
                {heater_id: 0.0},
                outdoor_temperature_c=4.0,
            ),
        ),
        (),
        FEASIBLE,
        (),
        "automatic-slot-test",
        start,
    )
    initialised_store.planning.save_plan(
        automatic,
        configuration_revision=revision,
        constraints_revision=initialised_store.planning.site()["revision"],
        reason="test",
        active=True,
    )

    response = client.get("/api/v1/planning", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["slot_minutes"] == 15
    first_slot = body["plan"]["slots"][0]
    slot_start = datetime.fromisoformat(first_slot["start"].replace("Z", "+00:00"))
    slot_end = datetime.fromisoformat(first_slot["end"].replace("Z", "+00:00"))
    assert (slot_end - slot_start).total_seconds() == 15 * 60


def test_planning_estimated_temperature_interpolates_between_outdoor_and_target():
    from dynamic_thermal_charge.api.routes.planning import _estimate_accumulator_temperature
    from dynamic_thermal_charge.persistence.seed import example_installation

    heater = example_installation().heaters[0]
    assert _estimate_accumulator_temperature(heater, 17.0, 0.0) == pytest.approx(17.0)
    assert _estimate_accumulator_temperature(heater, 17.0, 100.0) == pytest.approx(21.0)
    assert _estimate_accumulator_temperature(heater, 17.0, 50.0) == pytest.approx(19.0)


def test_planning_timeline_matches_plan_slots_by_index_not_exact_datetime_keys(
    client, initialised_store, recorder,
):
    from dynamic_thermal_charge.charge_planning import AutomaticPlan, AutomaticPlanSlot, FEASIBLE

    config, revision = initialised_store.repository.current()
    heater_ids = [heater.id for heater in config.heaters[:2]]
    start = API_NOW.replace(microsecond=123456)
    points = tuple(
        HourlyForecastPoint(start + timedelta(hours=index), 6.0)
        for index in range(49)
    )
    recorder.record_forecast(
        OutdoorForecast(
            date=start.date(),
            average_temperature_c=6.0,
            minimum_temperature_c=4.0,
            maximum_temperature_c=8.0,
            source="aemet",
            hourly_points=points,
        )
    )
    slots = []
    cursor = start.replace(microsecond=0)
    for index in range(4):
        end = cursor + timedelta(minutes=30)
        active = (heater_ids[0],) if index % 2 == 0 else (heater_ids[1],)
        slots.append(
            AutomaticPlanSlot(
                cursor,
                end,
                active,
                config.heaters[0].power_w,
                {heater.id: 10.0 * (index + 1) for heater in config.heaters},
                {heater.id: 0.0 for heater in config.heaters},
                outdoor_temperature_c=6.0,
            )
        )
        cursor = end
    automatic = AutomaticPlan(
        start.replace(microsecond=0),
        cursor,
        30,
        tuple(slots),
        (),
        FEASIBLE,
        (),
        "timeline-index-test",
        start,
    )
    initialised_store.planning.save_plan(
        automatic,
        configuration_revision=revision,
        constraints_revision=initialised_store.planning.site()["revision"],
        reason="test",
        active=True,
    )

    response = client.get("/api/v1/planning", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    for plan_slot, timeline_slot in zip(body["plan"]["slots"], body["timeline"]):
        assert set(plan_slot["heater_ids"]) == set(timeline_slot["heater_ids"])
        assert timeline_slot["stored_charge_percent_by_heater"]
        assert timeline_slot["estimated_temperature_c_by_heater"]
    assert body["timeline"][0]["heater_ids"]
    assert body["timeline"][1]["heater_ids"]
    assert body["timeline"][0]["heater_ids"] != body["timeline"][1]["heater_ids"]
    charging_slots = [slot for slot in body["timeline"] if slot["heater_ids"]]
    assert len(charging_slots) == 4


def test_planning_endpoint_prefers_the_newest_stored_forecast_over_plan_forecast(
    client, initialised_store, recorder
):
    from sqlalchemy import update

    from dynamic_thermal_charge.persistence.schema import forecast as forecast_table

    config, revision = initialised_store.repository.current()
    older_points = (
        HourlyForecastPoint(API_NOW, 8.0),
        HourlyForecastPoint(API_NOW + timedelta(hours=1), 8.0),
    )
    older_ref = recorder.record_forecast(
        OutdoorForecast(
            date=API_NOW.date(), average_temperature_c=8.0,
            minimum_temperature_c=8.0, maximum_temperature_c=8.0,
            source="simulated", hourly_points=older_points,
        )
    )
    assert older_ref is not None
    plan = ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START,
        requested_charge_minutes={heater.id: 0 for heater in config.heaters},
        hourly_points=older_points,
        fallback_temperature_c=8.0,
    )
    recorder.record_plan(plan, older_ref, revision)

    newer_points = (
        HourlyForecastPoint(API_NOW, 2.0),
        HourlyForecastPoint(API_NOW + timedelta(hours=1), 14.0),
    )
    newer_ref = recorder.record_forecast(
        OutdoorForecast(
            date=API_NOW.date(), average_temperature_c=7.0,
            minimum_temperature_c=2.0, maximum_temperature_c=14.0,
            source="aemet", hourly_points=newer_points,
        )
    )
    assert newer_ref is not None
    application_engine = initialised_store.application_engine or initialised_store.engine
    with application_engine.begin() as connection:
        connection.execute(
            update(forecast_table)
            .where(forecast_table.c.id == older_ref.id)
            .values(retrieved_at=API_NOW - timedelta(hours=2))
        )
        connection.execute(
            update(forecast_table)
            .where(forecast_table.c.id == newer_ref.id)
            .values(retrieved_at=API_NOW - timedelta(hours=1))
        )

    body = client.get("/api/v1/planning", headers=AUTH).json()

    assert body["forecast"]["source"] == "aemet"
    assert [point["temperature_c"] for point in body["forecast"]["hourly_points"]] == [2.0, 14.0]


def test_planning_endpoint_explicitly_reports_absence(client, heartbeat):
    heartbeat.publish(API_NOW, degraded=False)
    body = client.get("/api/v1/planning", headers=AUTH).json()
    assert body["plan"] is None
    assert body["forecast"] is None
    assert body["absence_reason"] == "no_current_or_next_plan"


# --------------------------------------------------------------------------- #
# FR-016: with the state not current, nothing is claimed
# --------------------------------------------------------------------------- #

def test_a_controller_never_seen_claims_nothing(client, recorded_night):
    body = _status(client)
    assert body["controller"]["liveness"] == "never_seen"
    assert body["controller"]["state_is_current"] is False
    assert body["controller"]["last_seen_at"] is None
    assert body["power"] is None, "power was published with no proof of it"
    # output_on is null, not false: a client reading only that field cannot
    # render a heater as charging without proof (FR-016).
    assert all(h["output_on"] is None for h in body["heaters"]), (
        "a heater state was claimed as current with no live controller"
    )


def test_a_silent_controller_reports_the_last_known_state_not_the_current_one(
    client, heartbeat, recorded_night, api_clock
):
    _plan, _ref, active = recorded_night
    heartbeat.publish(API_NOW, degraded=False)
    # Time passes and the controller stops publishing.
    api_clock.advance(hours=1)

    body = _status(client)
    assert body["controller"]["liveness"] == "stale"
    assert body["controller"]["state_is_current"] is False
    assert body["controller"]["age_seconds"] == pytest.approx(3600.0)
    assert body["power"] is None
    # No heater is claimed as current...
    assert all(h["output_on"] is None for h in body["heaters"])
    # ...but the last known value is preserved, with when it changed, so a client
    # can show it as history rather than as the present.
    still_known = {h["id"] for h in body["heaters"] if h["last_known_output_on"]}
    assert still_known == active
    for heater in body["heaters"]:
        if heater["id"] in active:
            assert heater["changed_at"] is not None


def test_a_degraded_controller_is_distinguishable_from_both(
    client, heartbeat, recorded_night
):
    heartbeat.publish(API_NOW, degraded=True)
    body = _status(client)
    assert body["controller"]["liveness"] == "live_degraded"
    assert body["controller"]["degraded"] is True
    # Degraded is still live: it has proof, so power may be published.
    assert body["controller"]["state_is_current"] is True
    assert body["power"] is not None


def test_a_recovering_controller_becomes_current_again_without_a_restart(
    client, heartbeat, recorded_night, api_clock
):
    """FR-018."""
    heartbeat.publish(API_NOW, degraded=False)
    api_clock.advance(hours=2)
    assert _status(client)["controller"]["state_is_current"] is False

    heartbeat.publish(api_clock.now, degraded=False)
    assert _status(client)["controller"]["state_is_current"] is True


def test_a_heartbeat_from_the_future_is_not_treated_as_current(
    client, heartbeat, recorded_night
):
    heartbeat.publish(API_NOW + timedelta(hours=3), degraded=False)
    body = _status(client)
    assert body["controller"]["liveness"] == "stale"
    assert body["power"] is None


# --------------------------------------------------------------------------- #
# FR-020 and edge cases
# --------------------------------------------------------------------------- #

def test_an_installation_with_no_plan_says_so(client, heartbeat):
    heartbeat.publish(API_NOW, degraded=False)
    body = _status(client)
    assert body["plan"] is None
    assert body["forecast"] is None
    assert body["allocations"] == []
    assert not any(h["output_on"] for h in body["heaters"])


def test_an_expired_plan_is_not_presented_as_running(client, heartbeat, recorder, initialised_store):
    """Never the last past plan dressed up as the present."""
    config, revision = initialised_store.repository.current()
    old_start = API_NOW - timedelta(days=2)
    plan = ChargeScheduler().build(config.site, config.heaters, old_start)
    recorder.record_plan(plan, None, revision)
    heartbeat.publish(API_NOW, degraded=False)
    assert _status(client)["plan"] is None


def test_an_installation_with_no_heaters_is_still_queryable(client, heartbeat, initialised_store):
    for heater_id in ("salon", "entrada", "habitaciones", "buhardilla"):
        _, revision = initialised_store.repository.current()
        initialised_store.repository.remove_heater(revision, heater_id)
    heartbeat.publish(API_NOW, degraded=False)
    body = _status(client)
    assert body["heaters"] == []
    assert body["power"]["instant_w"] == 0


def test_a_heater_with_no_transition_counts_as_off(client, heartbeat):
    heartbeat.publish(API_NOW, degraded=False)
    for heater in _status(client)["heaters"]:
        assert heater["output_on"] is False
        assert heater["last_known_output_on"] is False
        assert heater["changed_at"] is None


def test_output_on_is_null_not_false_when_the_state_is_not_current(client, recorded_night):
    """Null and false mean different things, and the difference matters.

    False says "it is off". Null says "I have no proof either way". Collapsing
    them would let a panel state something it cannot know.
    """
    for heater in _status(client)["heaters"]:
        assert heater["output_on"] is None


def test_two_controllers_are_flagged(client, initialised_store, api_clock):
    """FR-053. Two processes on the same relays cannot look like one."""
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    installation_id = initialised_store.repository.installation_id()

    def publisher(runner_id: str, started_hours: float) -> SqlHeartbeatPublisher:
        return SqlHeartbeatPublisher(
            initialised_store.engine,
            installation_id,
            poll_seconds=5.0,
            driver_kind="gpio",
            started_at=API_NOW + timedelta(hours=started_hours),
            runner_id=runner_id,
        )

    publisher("newer", -1).publish(api_clock.now, degraded=False)
    assert _status(client)["controller"]["multiple_controllers_suspected"] is False

    # The older process publishes after the newer one: both are alive.
    publisher("older", -5).publish(api_clock.now, degraded=False)
    body = _status(client)
    assert body["controller"]["multiple_controllers_suspected"] is True
    # And the state is still usable: the flag informs, it does not invalidate.
    assert body["controller"]["state_is_current"] is True


def test_the_api_answers_with_the_controller_absent(client):
    """FR-003: it reports the absence instead of blocking or failing."""
    response = client.get("/api/v1/status", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["controller"]["liveness"] == "never_seen"


def test_planning_config_endpoint_returns_site_parameters(client):
    response = client.get("/api/v1/planning/config", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planning_window_hours"] == 12
    assert body["forecast_horizon_hours"] == 24
    assert body["replan_minutes"] == 30
    assert body["mqtt_simulation_enabled"] is False
    assert "revision" in body


def test_planning_config_endpoint_updates_site_parameters(client):
    current = client.get("/api/v1/planning/config", headers=AUTH).json()
    response = client.patch(
        "/api/v1/planning/config",
        headers=AUTH,
        json={
            "expected_revision": current["revision"],
            "replan_minutes": current["replan_minutes"],
            "planning_window_hours": 12,
            "forecast_horizon_hours": 24,
            "aemet_query_hour": current["aemet_query_hour"],
            "contracted_power_w": current["contracted_power_w"],
            "max_heating_power_w": current["max_heating_power_w"],
            "design_indoor_temperature_c": current["design_indoor_temperature_c"],
            "design_outdoor_temperature_c": current["design_outdoor_temperature_c"],
            "feedback_horizon_hours": current["feedback_horizon_hours"],
            "mqtt_simulation_enabled": True,
            "mqtt_simulation_initial_temperature_c": 42.0,
            "mqtt_simulation_publish_seconds": 15.0,
            "mqtt_simulation_topic_prefix": "lab/sim",
            "mqtt_simulation_thermal_loss_c_per_hour": 1.5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["forecast_horizon_hours"] == 24
    assert body["mqtt_simulation_enabled"] is True
    assert body["mqtt_simulation_initial_temperature_c"] == 42.0
    assert body["mqtt_simulation_topic_prefix"] == "lab/sim"
    assert body["revision"] == current["revision"] + 1


@pytest.mark.parametrize(
    ("window_hours", "horizon_hours"),
    [(0, 24), (49, 48), (24, 12), (1.5, 24)],
)
def test_planning_config_rejects_invalid_durations(client, window_hours, horizon_hours):
    current = client.get("/api/v1/planning/config", headers=AUTH).json()
    response = client.patch(
        "/api/v1/planning/config",
        headers=AUTH,
        json={
            "expected_revision": current["revision"],
            "replan_minutes": current["replan_minutes"],
            "planning_window_hours": window_hours,
            "forecast_horizon_hours": horizon_hours,
            "aemet_query_hour": current["aemet_query_hour"],
            "contracted_power_w": current["contracted_power_w"],
            "max_heating_power_w": current["max_heating_power_w"],
            "design_indoor_temperature_c": current["design_indoor_temperature_c"],
            "design_outdoor_temperature_c": current["design_outdoor_temperature_c"],
            "feedback_horizon_hours": current["feedback_horizon_hours"],
        },
    )
    assert response.status_code == 422
