from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest

from dynamic_thermal_charge.charge_planning import (
    DEGRADED,
    FEASIBLE,
    INVALID,
    DegreeHoursDemandEstimator,
    MilpChargePlanner,
    PlanningInput,
    materialize_constraints,
)
from dynamic_thermal_charge.models import ChargeConstraint, ChargeTelemetry, Heater, OutputConfig
from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder
from dynamic_thermal_charge.weather import HourlyForecastPoint
from tests.conftest import API_NOW, AUTH


def heater(heater_id="a", *, power_w=2000, hours=4, priority=1, factor=1, reserve=0):
    return Heater(
        id=heater_id, name=heater_id, power_w=power_w,
        full_charge_minutes=hours * 60, target_charge=1, priority=priority,
        output=OutputConfig(), demand_factor=factor, reserve_percent=reserve,
    )


def state(heater_id="a", *, actual=21, target=21, soc=0, at=API_NOW):
    return ChargeTelemetry(heater_id, actual, target, soc, at, at, at)


def forecast(start=API_NOW, count=6, temperature=0):
    return tuple(HourlyForecastPoint(start + timedelta(hours=i), temperature) for i in range(count))


def request(*, heaters=None, telemetry=None, constraints=(), points=None, start=API_NOW, limit=5200, hours=4):
    heaters = tuple(heaters or (heater(),))
    return PlanningInput(
        heaters=heaters,
        telemetry=({item.id: state(item.id) for item in heaters} if telemetry is None else telemetry),
        constraints=tuple(constraints), forecast=(forecast(start) if points is None else points),
        horizon_start=start, horizon_hours=hours, slot_minutes=30,
        max_total_power_w=limit, timezone_name="Europe/Madrid",
    )


def test_capacity_and_degree_hours_v1_formula_factor_reserve_and_warm_zero():
    item = heater(power_w=3000, hours=8, factor=1.5, reserve=20)
    assert item.capacity_kwh == 24
    estimates = DegreeHoursDemandEstimator().estimate(
        (item,), {"a": state(actual=19, target=21)},
        (HourlyForecastPoint(API_NOW, 0), HourlyForecastPoint(API_NOW + timedelta(hours=6), 30)),
        (API_NOW, API_NOW + timedelta(hours=6)), 60,
        design_indoor_temperature_c=21, design_outdoor_temperature_c=0,
        feedback_horizon_hours=6,
    )
    assert estimates[0].thermal_coefficient == pytest.approx(24 / (24 * 21))
    assert estimates[0].demand_kwh == pytest.approx((23 / 21) * 1.5 * 1.2)
    assert estimates[1].feedback_temperature_c == 0
    assert estimates[1].demand_kwh == 0


def test_forecast_continuity_truncates_horizon_and_missing_or_fallback_is_invalid():
    points = (HourlyForecastPoint(API_NOW, 5), HourlyForecastPoint(API_NOW + timedelta(hours=1), 5))
    result = MilpChargePlanner().build(request(points=points, hours=8, telemetry={"a": state(soc=100)}))
    assert result.horizon_end == API_NOW + timedelta(hours=2)
    assert MilpChargePlanner().build(request(points=(), hours=2)).status == INVALID
    assert MilpChargePlanner().build(PlanningInput(**{**request(points=points).__dict__, "forecast_automatic_eligible": False})).status == INVALID


def test_planner_starts_at_first_available_forecast_hour_when_now_is_uncovered():
    from dynamic_thermal_charge.charge_planning import _continuous_forecast_slots

    start = datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)
    forecast_start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    points = tuple(
        HourlyForecastPoint(forecast_start + timedelta(hours=index), 4)
        for index in range(48)
    )
    starts = _continuous_forecast_slots(start, points, 48, 30)
    assert starts
    assert starts[0] == forecast_start
    assert starts[-1] < start + timedelta(hours=48)


def test_constraints_materialize_weekdays_at_boundaries_including_horizon_end():
    start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    rule = ChargeConstraint("a", .5, time(2, 0), weekdays=(4,))
    values = materialize_constraints((rule,), (heater(),), start, start + timedelta(hours=2), 30, "UTC")
    assert [(item.at, item.minimum_soc_percent) for item in values] == [(start + timedelta(hours=2), 50)]


def test_planner_accepts_zero_soc_respects_power_capacity_jit_and_is_deterministic():
    item = heater(power_w=2000, hours=2)
    rule = ChargeConstraint("a", 1, time(5, 0), weekdays=(4,))
    plan_input = request(heaters=(item,), telemetry={"a": state(soc=0)}, constraints=(rule,), limit=2000, hours=4)
    first = MilpChargePlanner().build(plan_input)
    second = MilpChargePlanner().build(plan_input)
    assert first.status in {FEASIBLE, DEGRADED}
    assert first.input_token == second.input_token
    assert [slot.heater_ids for slot in first.slots] == [slot.heater_ids for slot in second.slots]
    assert all(slot.power_w <= 2000 and max(slot.stored_charge_percent.values()) <= 100 for slot in first.slots)
    active_indexes = [index for index, slot in enumerate(first.slots) if slot.heater_ids]
    assert active_indexes == list(range(2, 6))


def test_missing_state_invalidates_all_outputs_and_replanning_uses_new_real_soc():
    missing = MilpChargePlanner().build(request(telemetry={}))
    assert missing.status == INVALID
    assert all(not slot.heater_ids and slot.power_w == 0 for slot in missing.slots)
    low = MilpChargePlanner().build(request(telemetry={"a": state(soc=0)}))
    high = MilpChargePlanner().build(request(telemetry={"a": state(soc=100)}))
    assert low.slots[0].initial_soc_percent["a"] == 0
    assert high.slots[0].initial_soc_percent["a"] == 100


def test_oversized_heater_is_reported_without_breaking_global_limit():
    result = MilpChargePlanner().build(request(heaters=(heater(power_w=6000),), limit=5000))
    assert result.status == DEGRADED
    assert any(item.requirement == "individual_power_limit" for item in result.violations)
    assert all(slot.power_w == 0 for slot in result.slots)


def test_planner_completes_within_solver_time_limit_with_full_seed_horizon():
    import shutil
    import time

    if shutil.which("cbc") is None:
        pytest.skip("system CBC is required for the full-horizon planner benchmark")

    from dynamic_thermal_charge.persistence.seed import example_installation

    config = example_installation()
    start = API_NOW
    points = tuple(
        HourlyForecastPoint(start + timedelta(hours=index), 5.0)
        for index in range(48)
    )
    telemetry = {
        item.id: state(item.id, actual=45, target=55, soc=50, at=start)
        for item in config.heaters
        if item.enabled
    }
    plan_input = PlanningInput(
        heaters=config.heaters,
        telemetry=telemetry,
        constraints=(),
        forecast=points,
        horizon_start=start,
        horizon_hours=48,
        slot_minutes=30,
        max_total_power_w=5200,
        max_heating_power_w=5200,
        timezone_name="Europe/Madrid",
    )
    started = time.monotonic()
    result = MilpChargePlanner().build(plan_input)
    elapsed = time.monotonic() - started
    assert result.status in {FEASIBLE, DEGRADED}
    assert elapsed < 60


def test_preview_uses_mqtt_fixed_telemetry_when_broker_disabled(client, initialised_store):
    system = client.get("/api/v1/system/configuration", headers=AUTH).json()
    client.patch(
        "/api/v1/system/configuration/mqtt",
        headers=AUTH,
        json={
            "expected_revision": system["revision"],
            "values": {
                "enabled": False,
                "fixed_temperature_c": 18,
                "fixed_target_temperature_c": 22,
                "fixed_stored_charge_percent": 80,
            },
        },
    )
    config, revision = initialised_store.repository.current()
    points = forecast(API_NOW, 6, 4)
    record = SimpleNamespace(
        date=API_NOW.date(), average_temperature_c=4, minimum_temperature_c=4,
        maximum_temperature_c=4, source="aemet", location="test",
        retrieved_at=API_NOW, hourly_points=points,
    )
    SqlHistoryRecorder(
        initialised_store.application_engine, initialised_store.repository.installation_id(),
        initialised_store.location,
    ).record_forecast(record)
    preview = client.post(
        "/api/v1/planning/preview", headers=AUTH,
        json={"constraints": [], "expected_revision": revision},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] != INVALID


def test_preview_activation_persists_v1_snapshot(client, initialised_store):
    config, revision = initialised_store.repository.current()
    points = forecast(API_NOW, 3, 4)
    record = SimpleNamespace(
        date=API_NOW.date(), average_temperature_c=4, minimum_temperature_c=4,
        maximum_temperature_c=4, source="aemet", location="test",
        retrieved_at=API_NOW, hourly_points=points,
    )
    SqlHistoryRecorder(
        initialised_store.application_engine, initialised_store.repository.installation_id(),
        initialised_store.location,
    ).record_forecast(record)
    for item in config.heaters:
        for field, value in (("temperature_c", 21), ("target_temperature_c", 21), ("stored_charge_percent", 100)):
            initialised_store.planning.record_telemetry(item.id, field, value, API_NOW)
    preview = client.post(
        "/api/v1/planning/preview", headers=AUTH,
        json={"constraints": [], "expected_revision": 1},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["status"] in {FEASIBLE, DEGRADED}
    activated = client.post(
        "/api/v1/planning/activate", headers=AUTH,
        json={"token": body["token"], "constraints": [], "expected_revision": 1},
    )
    assert activated.status_code == 200, activated.text
    stored = initialised_store.planning.active_plan()
    assert stored is not None
    assert stored["slots"][0]["initial_soc_percent"]
    assert stored["explanations"] and stored["demand"]
