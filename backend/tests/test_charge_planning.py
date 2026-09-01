from datetime import datetime, time, timedelta, timezone

from dynamic_thermal_charge.charge_planning import DeterministicChargeOptimizer, PlanningInput
from dynamic_thermal_charge.models import ChargeConstraint, ChargeTelemetry, Heater, OutputConfig, ThermalProfile
from dynamic_thermal_charge import runtime
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.system_settings import MqttSystemSettings
from dynamic_thermal_charge.weather import DailyAemetCycle, HourlyForecastPoint


def _heater(heater_id: str, power: int = 2400, reserve: float = 10) -> Heater:
    return Heater(
        id=heater_id, name=heater_id, power_w=power, full_charge_minutes=120,
        target_charge=1, priority=1, output=OutputConfig(),
        thermal=ThermalProfile(21, -2), reserve_percent=reserve,
    )


def _telemetry(heater_id: str, charge: float) -> ChargeTelemetry:
    stamp = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    return ChargeTelemetry(heater_id, 20, 21, charge, stamp, stamp, stamp)


def test_optimizer_keeps_each_accumulator_independent_and_never_exceeds_limit():
    start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    result = DeterministicChargeOptimizer().build(PlanningInput(
        heaters=(_heater("a"), _heater("b", reserve=0)),
        telemetry={"a": _telemetry("a", 0), "b": _telemetry("b", 100)},
        constraints=(ChargeConstraint("a", .5, time(1, 0)),),
        forecast=(HourlyForecastPoint(start, 5),), horizon_start=start,
        horizon_hours=2, slot_minutes=30, max_total_power_w=2400,
    ))
    assert all(slot.power_w <= 2400 for slot in result.slots)
    assert any("a" in slot.heater_ids for slot in result.slots)
    assert all("b" not in slot.heater_ids for slot in result.slots)


def test_optimizer_plans_reserve_as_equivalent_time_beyond_full_charge():
    start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    heater = Heater(
        **{**_heater("a", reserve=25).__dict__, "full_charge_minutes": 480}
    )
    result = DeterministicChargeOptimizer().build(PlanningInput(
        heaters=(heater,), telemetry={"a": _telemetry("a", 0)}, constraints=(),
        forecast=(HourlyForecastPoint(start, 5),), horizon_start=start,
        horizon_hours=10, slot_minutes=30, max_total_power_w=2400,
    ))

    assert sum("a" in slot.heater_ids for slot in result.slots) == 20
    assert result.deficits == ()
    assert result.slots[-1].required_charge_percent["a"] == 125.0


def test_aemet_cycle_has_initial_attempt_and_exactly_five_hourly_retries():
    cycle = DailyAemetCycle(query_hour=12, timezone_name="Europe/Madrid")
    state = cycle.initial_state(datetime(2026, 1, 16).date())
    now = state.scheduled_at
    for attempt in range(1, 6):
        state = cycle.failure(state, now, "offline")
        assert state.attempt == attempt
        if attempt < 5:
            assert state.next_retry_at == now.astimezone(timezone.utc) + timedelta(hours=1)
            now = state.next_retry_at
    assert state.stale is True
    assert state.next_retry_at is not None
    state = cycle.failure(state, now, "offline")
    assert state.attempt == 6
    assert state.next_retry_at is None


def test_thermal_projection_uses_target_delta_and_emission():
    start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    heater = _heater("room")
    heater = Heater(
        **{**heater.__dict__, "thermal": ThermalProfile(21, -2, thermal_loss_c_per_hour=0.5, emission_c_per_hour=2.0)}
    )
    result = DeterministicChargeOptimizer().build(PlanningInput(
        heaters=(heater,), telemetry={"room": _telemetry("room", 50)}, constraints=(),
        forecast=(HourlyForecastPoint(start, -2),), horizon_start=start,
        horizon_hours=1, slot_minutes=30, max_total_power_w=2400,
    ))
    assert result.slots[0].indoor_temperature_c is not None
    assert result.slots[0].indoor_temperature_c["room"] > 20
    assert result.slots[0].stored_charge_percent["room"] > 50


def test_disabled_mqtt_supplies_valid_global_telemetry_to_automatic_planning(monkeypatch):
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    config = example_installation()

    class Planning:
        def __init__(self):
            self.telemetry_called = False

        def telemetry(self):
            self.telemetry_called = True
            return {}

        def latest_forecast(self):
            return ()

    planning = Planning()
    store = type("Store", (), {"planning": planning})()
    original = DeterministicChargeOptimizer
    requests = []

    class RecordingOptimizer:
        def build(self, request):
            requests.append(request)
            return original().build(request)

    monkeypatch.setattr(runtime, "DeterministicChargeOptimizer", RecordingOptimizer)
    runtime._build_automatic_runtime_plan(
        store,
        config,
        now,
        (),
        {"forecast_horizon_hours": 2},
        mqtt=MqttSystemSettings(
            fixed_temperature_c=18,
            fixed_target_temperature_c=22,
            fixed_stored_charge_percent=40,
            fixed_indoor_temperature_c=19,
        ),
    )

    assert planning.telemetry_called is False
    assert set(requests[0].telemetry) == {heater.id for heater in config.heaters}
    assert {
        (value.temperature_c, value.target_temperature_c, value.stored_charge_percent)
        for value in requests[0].telemetry.values()
    } == {(18, 22, 40)}


def test_enabled_mqtt_automatic_planning_uses_only_persisted_telemetry(monkeypatch):
    now = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    config = example_installation()
    source = ChargeTelemetry("salon", 7, 8, 9, now, now, now)

    class Planning:
        def telemetry(self):
            return {"salon": source}

        def latest_forecast(self):
            return ()

    planning = Planning()
    store = type("Store", (), {"planning": planning})()
    original = DeterministicChargeOptimizer
    requests = []

    class RecordingOptimizer:
        def build(self, request):
            requests.append(request)
            return original().build(request)

    monkeypatch.setattr(runtime, "DeterministicChargeOptimizer", RecordingOptimizer)
    runtime._build_automatic_runtime_plan(
        store,
        config,
        now,
        (),
        {"forecast_horizon_hours": 2},
        mqtt=MqttSystemSettings(enabled=True, host="broker"),
    )

    assert requests[0].telemetry == {"salon": source}
