from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest
import pulp

from dynamic_thermal_charge.charge_planning import (
    AutomaticPlan,
    AutomaticPlanSlot,
    DEGRADED,
    INVALID,
    MilpChargePlanner,
    PlanningInput,
    PlanningViolation,
)
from dynamic_thermal_charge.models import ChargeTelemetry, Heater, OutputConfig
from dynamic_thermal_charge.runtime import (
    _aggregate_unmet_minutes,
    _refresh_daily_aemet_forecast,
    _require_real_telemetry_for_gpio,
    _seconds_to_next_replan,
)
from dynamic_thermal_charge.persistence.mapping import to_utc
from dynamic_thermal_charge.persistence.schema import (
    automatic_plan,
    automatic_plan_slot,
    forecast,
    forecast_cycle,
    forecast_hour,
)
from dynamic_thermal_charge.system_settings import MqttSystemSettings
from dynamic_thermal_charge.watchdog import DailyAemetForecastManager
from dynamic_thermal_charge.weather import HourlyForecastPoint, OutdoorForecast
from tests.conftest import API_NOW


def _forecast(at=API_NOW):
    return OutdoorForecast(
        date=at.date(),
        average_temperature_c=5,
        minimum_temperature_c=2,
        maximum_temperature_c=8,
        source="aemet",
        hourly_points=tuple(
            HourlyForecastPoint(at + timedelta(hours=index), 5)
            for index in range(4)
        ),
    )


def test_daily_aemet_refresh_persists_before_automatic_planning(initialised_store, recorder):
    class Provider:
        def forecast_for(self, requested_date):
            assert requested_date == API_NOW.date()
            return _forecast()

    _refresh_daily_aemet_forecast(
        initialised_store,
        recorder,
        Provider(),
        API_NOW,
        query_hour=1,
        timezone_name="UTC",
    )

    assert initialised_store.planning.latest_forecast(API_NOW)
    assert initialised_store.planning.latest_forecast_automatic_eligible() is True
    assert initialised_store.planning.forecast_cycle_status()["forecast_status"] == "success"


def test_daily_aemet_cycle_keeps_six_failures_across_persisted_state(initialised_store):
    class OfflineProvider:
        def forecast_for(self, _requested_date):
            raise RuntimeError("offline")

    manager = DailyAemetForecastManager(OfflineProvider(), query_hour=12, timezone_name="UTC")
    scheduled_at = datetime(2026, 1, 16, 12, tzinfo=timezone.utc)
    state = initialised_store.planning.forecast_cycle(scheduled_at.date(), scheduled_at)
    now = scheduled_at
    for attempt in range(1, 7):
        result = manager.poll(now, state)
        initialised_store.planning.save_forecast_cycle(result.state)
        state = initialised_store.planning.forecast_cycle(scheduled_at.date(), scheduled_at)
        assert state.attempt == attempt
        now = state.next_retry_at or now

    assert state.completed is True
    assert state.stale is True
    assert state.next_retry_at is None


def test_replan_cadence_waits_for_a_slot_boundary_and_never_underflows():
    now = datetime(2026, 1, 16, 1, 5, tzinfo=timezone.utc)
    assert _seconds_to_next_replan(now, replan_minutes=10, slot_minutes=30) == 55 * 60
    assert _seconds_to_next_replan(now, replan_minutes=45, slot_minutes=30) == 55 * 60


def test_gpio_startup_rejects_fixed_or_simulated_telemetry(caplog):
    with pytest.raises(RuntimeError, match="MQTT is disabled"):
        _require_real_telemetry_for_gpio(
            "gpio", MqttSystemSettings(enabled=False), {"mqtt_simulation_enabled": False}
        )
    with pytest.raises(RuntimeError, match="accumulator simulation"):
        _require_real_telemetry_for_gpio(
            "gpio", MqttSystemSettings(), {"mqtt_simulation_enabled": True}
        )
    assert "GPIO controller startup rejected" in caplog.text


def test_base_load_and_heating_limit_both_restrict_the_automatic_plan():
    start = API_NOW
    heater = Heater("a", "a", 2000, 120, 1, 1, OutputConfig())
    telemetry = ChargeTelemetry("a", 21, 21, 0, start, start, start)
    points = tuple(HourlyForecastPoint(start + timedelta(hours=index), 0) for index in range(4))
    result = MilpChargePlanner().build(
        PlanningInput(
            heaters=(heater,), telemetry={"a": telemetry}, constraints=(), forecast=points,
            horizon_start=start, horizon_hours=2, slot_minutes=30,
            max_total_power_w=3000, base_load_w=1500, max_heating_power_w=2500,
        )
    )
    assert result.status == DEGRADED
    assert all(slot.power_w == 0 for slot in result.slots)


def test_non_optimal_solver_result_is_never_reported_as_feasible(monkeypatch):
    monkeypatch.setattr(pulp.LpProblem, "solve", lambda _self, _solver: pulp.LpStatusInfeasible)
    heater = Heater("a", "a", 2000, 120, 1, 1, OutputConfig())
    telemetry = ChargeTelemetry("a", 21, 21, 0, API_NOW, API_NOW, API_NOW)
    result = MilpChargePlanner().build(
        PlanningInput(
            heaters=(heater,), telemetry={"a": telemetry}, constraints=(),
            forecast=tuple(HourlyForecastPoint(API_NOW + timedelta(hours=index), 0) for index in range(4)),
            horizon_start=API_NOW, horizon_hours=2, slot_minutes=30,
        )
    )
    assert result.status == INVALID


def test_automatic_planner_emits_debug_progress(caplog):
    caplog.set_level("DEBUG", logger="dynamic_thermal_charge.charge_planning")
    heater = Heater("a", "a", 2000, 120, 1, 1, OutputConfig())
    telemetry = ChargeTelemetry("a", 21, 21, 100, API_NOW, API_NOW, API_NOW)
    MilpChargePlanner().build(
        PlanningInput(
            heaters=(heater,), telemetry={"a": telemetry}, constraints=(),
            forecast=tuple(HourlyForecastPoint(API_NOW + timedelta(hours=index), 5) for index in range(4)),
            horizon_start=API_NOW, horizon_hours=2, slot_minutes=30,
        )
    )
    assert "Automatic planning started" in caplog.text
    assert "Automatic planning solver phase=" in caplog.text
    assert "Automatic planning completed" in caplog.text


def test_verified_time_limited_solver_candidate_is_degraded(monkeypatch):
    original_solve = pulp.LpProblem.solve
    calls = 0

    def solve_with_timeout(model, solver):
        nonlocal calls
        calls += 1
        status = original_solve(model, solver)
        return pulp.LpStatusNotSolved if calls == 4 else status

    monkeypatch.setattr(pulp.LpProblem, "solve", solve_with_timeout)
    heater = Heater("a", "a", 2000, 120, 1, 1, OutputConfig())
    telemetry = ChargeTelemetry("a", 21, 21, 100, API_NOW, API_NOW, API_NOW)
    result = MilpChargePlanner().build(
        PlanningInput(
            heaters=(heater,), telemetry={"a": telemetry}, constraints=(),
            forecast=tuple(HourlyForecastPoint(API_NOW + timedelta(hours=index), 5) for index in range(4)),
            horizon_start=API_NOW, horizon_hours=2, slot_minutes=30,
        )
    )
    assert result.status == DEGRADED
    assert any(item.requirement == "solver_time_limit" for item in result.violations)


def test_invalid_automatic_plan_clears_the_previously_active_plan(initialised_store):
    start = API_NOW
    valid = AutomaticPlan(
        start, start + timedelta(minutes=30), 30,
        (AutomaticPlanSlot(start, start + timedelta(minutes=30), (), 0, {}, {}),),
        (), "FEASIBLE", (), "valid", start,
    )
    invalid = replace(valid, status=INVALID, input_token="invalid")
    site = initialised_store.planning.site()
    initialised_store.planning.save_plan(
        valid, configuration_revision=1, constraints_revision=site["revision"],
        reason="test", active=True,
    )
    initialised_store.planning.save_plan(
        invalid, configuration_revision=1, constraints_revision=site["revision"],
        reason="test", active=False,
    )
    assert initialised_store.planning.active_plan() is None


def test_multiple_deficits_for_one_accumulator_are_aggregated():
    heater = Heater("a", "a", 2000, 120, 1, 1, OutputConfig())
    config = type("Config", (), {"heaters": (heater,)})()
    violations = (
        PlanningViolation("a", "minimum_soc", 0, 10, API_NOW, "short"),
        PlanningViolation("a", "minimum_soc", 0, 15, API_NOW, "short"),
    )
    assert _aggregate_unmet_minutes(config, violations) == {"a": 30}


def test_retention_prunes_automatic_plans_and_hourly_forecasts(
    initialised_store, recorder
):
    _refresh_daily_aemet_forecast(
        initialised_store, recorder, type("Provider", (), {"forecast_for": lambda _self, _date: _forecast()})(),
        API_NOW, query_hour=1, timezone_name="UTC",
    )
    plan = AutomaticPlan(
        API_NOW, API_NOW + timedelta(minutes=30), 30,
        (AutomaticPlanSlot(API_NOW, API_NOW + timedelta(minutes=30), (), 0, {}, {}),),
        (), "FEASIBLE", (), "retention", API_NOW,
    )
    initialised_store.planning.save_plan(
        plan, configuration_revision=1,
        constraints_revision=initialised_store.planning.site()["revision"],
        reason="test", active=False,
    )
    engine = initialised_store.application_engine or initialised_store.engine
    old = to_utc(API_NOW - timedelta(days=2))
    with engine.begin() as connection:
        connection.execute(forecast.update().values(retrieved_at=old))
        connection.execute(forecast_cycle.update().values(updated_at=old))
        connection.execute(automatic_plan.update().values(created_at=old))

    report = recorder.prune(API_NOW, retention_days=1)

    assert {"forecast", "forecast_cycle", "automatic_plan"} <= set(report.deleted)
    with engine.connect() as connection:
        assert connection.execute(forecast_hour.select()).first() is None
        assert connection.execute(automatic_plan_slot.select()).first() is None
