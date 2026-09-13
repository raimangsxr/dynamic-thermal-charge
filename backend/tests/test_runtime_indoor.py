"""Automatic planning never fabricates missing MQTT telemetry."""

from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge import runtime
from dynamic_thermal_charge.models import ChargeTelemetry
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.system_settings import MqttSystemSettings
from dynamic_thermal_charge.weather import HourlyForecastPoint


NOW = datetime(2026, 1, 16, 1, tzinfo=timezone.utc)


class Planning:
    def __init__(self, values=None):
        self.values = values or {}

    def telemetry(self):
        return self.values

    def latest_forecast(self, at=None):
        del at
        return tuple(
            HourlyForecastPoint(NOW + timedelta(hours=index), 5.0)
            for index in range(8)
        )

    def latest_forecast_automatic_eligible(self):
        return True


def _store(values=None):
    return type(
        "Store",
        (),
        {"planning": Planning(values), "home_assistant": None},
    )()


def _planning_site():
    return {
        "forecast_horizon_hours": 2,
        "contracted_power_w": 5200,
        "base_load_w": 0,
        "max_heating_power_w": 5200,
        "solver_time_limit_seconds": 10,
    }


def test_disabled_mqtt_produces_an_invalid_plan_without_reading_or_fabricating_data():
    planning = Planning()
    store = type("Store", (), {"planning": planning, "home_assistant": None})()

    plan, schedule, _evidence = runtime._build_automatic_runtime_plan(
        store,
        example_installation(),
        NOW,
        (),
        _planning_site(),
        mqtt=MqttSystemSettings(enabled=False),
    )

    assert plan.status == "INVALID"
    assert schedule.slots == ()
    assert planning.values == {}
    assert all(not slot.heater_ids for slot in plan.slots)
    assert all(not slot.indoor_temperature_c for slot in plan.slots)
    assert all(not slot.stored_energy_kwh for slot in plan.slots)


def test_missing_or_stale_mqtt_telemetry_produces_an_invalid_plan():
    stale = ChargeTelemetry(
        heater_id="salon",
        indoor_temperature_c=19.0,
        stored_soc_percent=50.0,
        indoor_received_at=NOW - timedelta(minutes=31),
        stored_soc_received_at=NOW - timedelta(minutes=31),
    )
    plan, schedule, _evidence = runtime._build_automatic_runtime_plan(
        _store({"salon": stale}),
        example_installation(),
        NOW,
        (),
        _planning_site(),
        mqtt=MqttSystemSettings(enabled=True, host="broker"),
    )

    assert plan.status == "INVALID"
    assert schedule.slots == ()
    assert all(not slot.heater_ids for slot in plan.slots)
    assert all(not slot.indoor_temperature_c for slot in plan.slots)
    assert all(not slot.stored_energy_kwh for slot in plan.slots)
