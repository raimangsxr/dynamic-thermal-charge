"""Living examples for the automatic thermal-calibration contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dynamic_thermal_charge.mqtt import IncomingMessage
from dynamic_thermal_charge.mqtt.outdoor import OutdoorTemperatureMessageProcessor
from dynamic_thermal_charge.push import PushUnsupported, WebPushDelivery
from dynamic_thermal_charge.calibration_runtime import CalibrationCoordinator
from dynamic_thermal_charge.thermal_calibration import (
    CalibrationInput,
    CalibrationFit,
    CalibrationProtocol,
    CalibrationQuality,
    CalibrationSample,
    RoomEstimateInput,
    arbitrate_calibration_plan,
    estimate_room,
    fit_calibration,
    parse_outdoor_payload,
)
from tests.conftest import API_NOW, AUTH

import pytest


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def test_outdoor_payload_is_strict_and_estimation_is_deterministic():
    assert parse_outdoor_payload('{"outdoor_temperature_c": 12.5}') == 12.5
    with pytest.raises(ValueError):
        parse_outdoor_payload('{"outdoor_temperature_c": 12.5, "unit": "C"}')
    with pytest.raises(ValueError):
        parse_outdoor_payload('{"outdoor_temperature_c": true}')

    values = RoomEstimateInput(
        surface_m2=20,
        walls_exterior=2,
        windows_m2=3,
        insulation="medium",
        height_m=2.5,
        other_heat_sources_kw=0.2,
    )
    first = estimate_room(values)
    second = estimate_room(values)
    assert first == second
    assert first.capacity_kwh_per_c == pytest.approx(0.7165)
    assert first.loss_kw_per_c == pytest.approx(0.01973854382)


def test_protocol_enforces_safe_phases_limits_and_restarts():
    protocol = CalibrationProtocol(started_at=NOW)
    baseline = protocol.step(
        CalibrationInput(NOW, 19.0, 5.0, 50.0, 21.0)
    )
    assert baseline.phase == "baseline"
    assert baseline.command == baseline.command.__class__(False, False)

    charge = protocol.step(
        CalibrationInput(NOW + timedelta(minutes=60), 19.0, 5.0, 50.0, 21.0)
    )
    assert charge.phase == "charge"
    assert charge.command.charge is True

    deferred = protocol.step(
        CalibrationInput(
            NOW + timedelta(minutes=61), 19.0, 5.0, 50.0, 21.0,
            global_power_available=False,
            confirmations={"charge": True},
        )
    )
    assert deferred.command.charge is False
    assert deferred.command.deferred is True

    release = protocol.step(
        CalibrationInput(
            NOW + timedelta(minutes=181), 19.0, 5.0, 60.0, 21.0,
            confirmations={"charge": True},
        )
    )
    assert release.phase == "release"
    assert release.command.discharge is True
    assert release.command.setpoint_temperature_c == 23.0

    cool = protocol.step(
        CalibrationInput(
            NOW + timedelta(minutes=182), 25.0, 5.0, 60.0, 21.0,
            confirmations={"discharge": True},
        )
    )
    assert cool.phase == "cool"
    assert cool.command.discharge is False

    snapshot = protocol.snapshot(now=NOW + timedelta(minutes=182))
    restored = CalibrationProtocol.restore(
        {
            "started_at": NOW,
            "phase": protocol.phase,
            "updated_at": NOW + timedelta(minutes=182),
            "metrics": snapshot,
        }
    )
    assert restored.phase == "cool"
    assert restored.reference_soc == protocol.reference_soc


def test_plan_arbitration_excludes_only_selected_heater():
    assert arbitrate_calibration_plan(
        ("salon", "entrada", "cocina"),
        selected_heater_id="entrada",
        plan_heater_ids=("salon", "entrada"),
        calibration_charge=True,
    ) == ("entrada", "salon")
    assert arbitrate_calibration_plan(
        ("salon", "entrada"),
        selected_heater_id="entrada",
        plan_heater_ids=("salon", "entrada"),
        calibration_charge=True,
        relay_test_active=True,
    ) == ()


def test_fit_rejects_insufficient_excitation_deterministically():
    samples = tuple(
        CalibrationSample(
            NOW + timedelta(minutes=5 * index),
            19.0,
            5.0,
            50.0,
            False,
            phase="baseline",
        )
        for index in range(60)
    )
    fit = fit_calibration(samples, capacity_kwh=2.5)
    assert fit.status == "failed"
    assert fit.quality.reason in {"excitation_criteria_not_met", "quality_criteria_not_met"}
    assert fit.capacity_kwh_per_c is None


def test_fit_counts_only_synchronized_samples_for_the_early_success_gate():
    samples = tuple(
        CalibrationSample(
            NOW + timedelta(minutes=5 * index),
            19.0,
            5.0,
            50.0,
            False,
            synchronized=index != 59,
            phase="baseline",
        )
        for index in range(60)
    )
    fit = fit_calibration(samples, capacity_kwh=2.5)
    assert fit.status == "failed"
    assert fit.quality.sample_count == 59
    assert fit.quality.reason == "not_enough_samples"


def test_deadline_attempts_fit_and_applies_a_sufficient_result(initialised_store, monkeypatch):
    planning = initialised_store.planning
    deadline = NOW
    planning.record_telemetry("salon", "indoor_temperature_c", 19.0, deadline)
    planning.record_telemetry("salon", "stored_soc_percent", 50.0, deadline)
    initialised_store.outdoor_temperature.record(5.0, deadline)
    session = initialised_store.calibration.start(
        "salon", now=deadline - timedelta(hours=24)
    )
    fit = CalibrationFit(
        capacity_kwh_per_c=3.1,
        loss_kw_per_c=0.2,
        quality=CalibrationQuality(
            sample_count=60,
            elapsed_hours=6.0,
            heating_windows=2,
            cooling_windows=2,
            indoor_range_c=1.0,
            differential_range_c=3.0,
            heat_delivered_kwh=0.5,
            rmse_c=0.1,
            bias_c=0.01,
            capacity_confidence_relative=0.1,
            loss_confidence_relative=0.1,
            condition_number=10.0,
            sufficient=True,
        ),
        status="calibrated",
    )
    calls = []

    def fake_fit(samples, *, capacity_kwh):
        calls.append((samples, capacity_kwh))
        return fit

    monkeypatch.setattr("dynamic_thermal_charge.calibration_runtime.fit_calibration", fake_fit)
    before_revision = initialised_store.repository.current()[1]

    coordinator = CalibrationCoordinator(initialised_store, clock=lambda: deadline)
    assert coordinator.outputs(deadline) == set()

    assert len(calls) == 1
    assert calls[0][1] == 2.5
    assert initialised_store.calibration.active("salon") is None
    config, revision = initialised_store.repository.current()
    room = next(item.room for item in config.heaters if item.id == "salon")
    assert room.status == "calibrated"
    assert room.room_thermal_capacity_kwh_per_c == pytest.approx(3.1)
    assert room.room_heat_loss_kw_per_c == pytest.approx(0.2)
    assert room.terminal_cause == "quality_criteria_met"
    assert revision == before_revision + 1
    assert session.id in {
        item.session_id for item in initialised_store.calibration.notifications()
    }


def test_applying_session_resumes_terminal_saga_after_coordinator_restart(
    initialised_store, monkeypatch
):
    calibration = initialised_store.calibration
    session = calibration.start("salon", now=NOW - timedelta(hours=6))
    calibration.add_sample(
        session.id,
        CalibrationSample(NOW - timedelta(minutes=5), 19.0, 5.0, 50.0, False),
    )
    calibration.save_state(
        session.id,
        phase="applying",
        commands={"authorized_at": None, "charge": False, "discharge": False},
        now=NOW,
    )
    fit = CalibrationFit(
        capacity_kwh_per_c=3.1,
        loss_kw_per_c=0.2,
        quality=CalibrationQuality(
            sample_count=60,
            elapsed_hours=6.0,
            heating_windows=2,
            cooling_windows=2,
            indoor_range_c=1.0,
            differential_range_c=3.0,
            heat_delivered_kwh=0.5,
            rmse_c=0.1,
            bias_c=0.01,
            capacity_confidence_relative=0.1,
            loss_confidence_relative=0.1,
            condition_number=10.0,
            sufficient=True,
        ),
        status="calibrated",
    )
    calls = []

    def fake_fit(samples, *, capacity_kwh):
        calls.append((samples, capacity_kwh))
        return fit

    monkeypatch.setattr("dynamic_thermal_charge.calibration_runtime.fit_calibration", fake_fit)

    # A new coordinator stands in for the process that restarted after the
    # phase marker was persisted and before terminal cleanup completed.
    restarted = CalibrationCoordinator(initialised_store, clock=lambda: NOW)
    before_revision = initialised_store.repository.current()[1]
    assert restarted.outputs(NOW) == set()

    assert len(calls) == 1
    assert calls[0][1] == 2.5
    assert initialised_store.calibration.active("salon") is None
    config, revision = initialised_store.repository.current()
    room = next(item.room for item in config.heaters if item.id == "salon")
    assert room.status == "calibrated"
    assert room.room_thermal_capacity_kwh_per_c == pytest.approx(3.1)
    assert room.room_heat_loss_kw_per_c == pytest.approx(0.2)
    assert revision == before_revision + 1


def test_deadline_fails_with_fit_quality_when_result_is_insufficient(initialised_store, monkeypatch):
    planning = initialised_store.planning
    deadline = NOW
    planning.record_telemetry("salon", "indoor_temperature_c", 19.0, deadline)
    planning.record_telemetry("salon", "stored_soc_percent", 50.0, deadline)
    initialised_store.outdoor_temperature.record(5.0, deadline)
    session = initialised_store.calibration.start(
        "salon", now=deadline - timedelta(hours=24)
    )
    fit = CalibrationFit(
        capacity_kwh_per_c=None,
        loss_kw_per_c=None,
        quality=CalibrationQuality(
            sample_count=12,
            elapsed_hours=1.0,
            heating_windows=0,
            cooling_windows=0,
            indoor_range_c=0.1,
            differential_range_c=0.1,
            heat_delivered_kwh=0.0,
            reason="quality_criteria_not_met",
        ),
        status="failed",
    )
    monkeypatch.setattr(
        "dynamic_thermal_charge.calibration_runtime.fit_calibration",
        lambda _samples, *, capacity_kwh: fit,
    )

    coordinator = CalibrationCoordinator(initialised_store, clock=lambda: deadline)
    assert coordinator.outputs(deadline) == set()

    assert initialised_store.calibration.active("salon") is None
    config, _revision = initialised_store.repository.current()
    room = next(item.room for item in config.heaters if item.id == "salon")
    assert room.status == "failed"
    assert room.terminal_cause == "quality_criteria_not_met"
    assert room.room_thermal_capacity_kwh_per_c == pytest.approx(2.5)
    assert room.room_heat_loss_kw_per_c == pytest.approx(0.12)
    assert session.id in {item.session_id for item in initialised_store.calibration.notifications()}


def test_relay_failure_callback_finishes_active_calibration_durably(initialised_store):
    initialised_store.calibration.start("salon", now=NOW)
    coordinator = CalibrationCoordinator(initialised_store, clock=lambda: NOW)

    assert coordinator.fail_active_relay("salon", at=NOW) is True
    assert initialised_store.calibration.active("salon") is None
    config, _revision = initialised_store.repository.current()
    room = next(item.room for item in config.heaters if item.id == "salon")
    assert room.status == "failed"
    assert room.terminal_cause == "relay_off_failed"


def test_outdoor_mqtt_ignores_retained_and_persists_fresh_sample(initialised_store):
    def clock():
        return NOW

    processor = OutdoorTemperatureMessageProcessor(
        initialised_store.outdoor_temperature,
        topic="weather/outdoor",
        clock=clock,
    )
    assert not processor.handle(
        IncomingMessage("weather/outdoor", b'{"outdoor_temperature_c": 5}', retain=True)
    )
    message = SimpleNamespace(
        topic="weather/outdoor",
        payload=b'{"outdoor_temperature_c": 5}',
        retain=False,
        received_at=NOW,
    )
    assert processor.handle(message)
    assert initialised_store.outdoor_temperature.latest().temperature_c == 5


def test_terminal_persistence_cleans_samples_and_deduplicates_push(initialised_store):
    calibration = initialised_store.calibration
    session = calibration.start("salon", now=NOW)
    calibration.add_sample(
        session.id,
        CalibrationSample(NOW, 19.0, 5.0, 50.0, False),
    )
    subscription = calibration.register_subscription(
        user_id="operator",
        browser_id="browser-a",
        endpoint="https://push.example/a",
        p256dh="p256dh",
        auth="auth",
        at=NOW,
    )
    before_revision = initialised_store.repository.current()[1]
    assert calibration.finish(
        session.id,
        result=None,
        status="failed",
        cause="inputs_missing_over_one_hour",
        now=NOW,
    )
    assert calibration.active("salon") is None
    assert calibration.samples(session.id) == ()
    assert calibration.push_attempts(session.id)[0].subscription_id == subscription.id
    assert calibration.notifications()[0].session_id == session.id
    assert initialised_store.repository.current()[1] == before_revision + 1
    assert calibration.finish(
        session.id, result=None, status="failed", cause="retry", now=NOW
    ) is False

    sent: list[str] = []
    delivery = WebPushDelivery(
        calibration,
        sender=lambda _subscription, payload: sent.append(payload),
        clock=lambda: NOW,
    )
    assert delivery.deliver_pending(session_id=session.id) == 1
    assert delivery.deliver_pending(session_id=session.id) == 0
    assert calibration.push_attempts(session.id)[0].status == "sent"
    assert sent


def test_unsupported_push_is_a_channel_state_not_a_control_failure(initialised_store):
    calibration = initialised_store.calibration
    session = calibration.start("salon", now=NOW)
    calibration.register_subscription(
        user_id="operator",
        browser_id="browser-a",
        endpoint="https://push.example/a",
        p256dh="p256dh",
        auth="auth",
        at=NOW,
    )
    calibration.finish(session.id, result=None, status="cancelled", cause="cancelled_by_operator", now=NOW)
    delivery = WebPushDelivery(
        calibration,
        sender=lambda _subscription, _payload: (_ for _ in ()).throw(
            PushUnsupported("vapid_private_key_unconfigured")
        ),
        clock=lambda: NOW,
    )
    delivery.deliver_pending(session_id=session.id)
    assert calibration.push_attempts(session.id)[0].status == "unsupported"


def test_api_start_cancel_and_acknowledge_are_atomic(client, initialised_store):
    planning = initialised_store.planning
    planning.record_telemetry("salon", "indoor_temperature_c", 19.0, API_NOW)
    planning.record_telemetry("salon", "stored_soc_percent", 50.0, API_NOW)
    initialised_store.outdoor_temperature.record(5.0, API_NOW)

    started = client.post("/api/v1/rooms/salon/calibration", headers=AUTH)
    assert started.status_code == 201, started.text
    assert started.json()["room"]["status"] == "calibrating"

    cancelled = client.delete("/api/v1/rooms/salon/calibration", headers=AUTH)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["room"]["status"] == "cancelled"
    notices = client.get("/api/v1/notifications", headers=AUTH).json()["items"]
    assert len(notices) == 1
    acknowledged = client.post(
        f"/api/v1/notifications/{notices[0]['id']}/ack", headers=AUTH
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["items"] == []
