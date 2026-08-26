"""The state endpoint: FR-013, FR-016, FR-018, FR-020, and honesty about it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.scheduler import ChargeScheduler
from dynamic_thermal_charge.weather import OutdoorForecast
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
