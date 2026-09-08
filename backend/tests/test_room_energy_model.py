from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest

from dynamic_thermal_charge.charge_planning import (
    DEGRADED,
    FEASIBLE,
    INVALID,
    PlanningInput,
    RoomEnergyDemandEstimator,
    RoomEnergyPlanner,
    active_temperature_target,
    room_energy_step,
)
from dynamic_thermal_charge.models import ChargeTelemetry, Heater, OutputConfig, TemperatureTarget, ThermalProfile
from dynamic_thermal_charge.weather import HourlyForecastPoint


START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _heater(
    heater_id: str = "salon",
    *,
    power_w: int = 2800,
    full_charge_minutes: int = 480,
    priority: int = 1,
    target: float = 21.0,
) -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id,
        power_w=power_w,
        full_charge_minutes=full_charge_minutes,
        priority=priority,
        output=OutputConfig(),
        thermal=ThermalProfile(
            room_thermal_capacity_kwh_per_c=2.5,
            room_heat_loss_kw_per_c=0.12,
        ),
        temperature_targets=(TemperatureTarget(target, time(0, 0)),),
    )


def _telemetry(heater_id: str, *, indoor: float = 20.0, soc: float = 50.0) -> ChargeTelemetry:
    return ChargeTelemetry(
        heater_id=heater_id,
        indoor_temperature_c=indoor,
        stored_soc_percent=soc,
        indoor_received_at=START,
        stored_soc_received_at=START,
    )


def _request(
    heaters: tuple[Heater, ...] = (_heater(),),
    *,
    telemetry: dict[str, ChargeTelemetry] | None = None,
    outdoor: float = 5.0,
    horizon_hours: int = 1,
    max_total_power_w: int = 5200,
) -> PlanningInput:
    points = tuple(
        HourlyForecastPoint(START + timedelta(hours=offset), outdoor)
        for offset in range(horizon_hours)
    )
    return PlanningInput(
        heaters=heaters,
        telemetry=telemetry or {heater.id: _telemetry(heater.id) for heater in heaters},
        constraints=(),
        forecast=points,
        horizon_start=START,
        horizon_hours=horizon_hours,
        slot_minutes=60,
        max_total_power_w=max_total_power_w,
        temperature_targets={heater.id: heater.temperature_targets for heater in heaters},
        room_energy_model=True,
    )


def test_accumulator_capacity_is_nominal_power_times_full_charge_hours():
    heater = _heater()

    assert heater.capacity_kwh == pytest.approx(22.4)
    assert heater.capacity_kwh * 0.5 == pytest.approx(11.2)


def test_room_energy_step_reproduces_signed_exchange_and_storage_balance():
    interval = room_energy_step(
        _heater(),
        start=START,
        outdoor_temperature_c=25.0,
        target_temperature_c=21.0,
        indoor_temperature_c=20.0,
        stored_energy_kwh=11.2,
        slot_minutes=60,
        charge_on=True,
        heat_delivered_kwh=1.0,
    )

    # E_loss = 0.12 * (20 - 25) * 1 = -0.6 kWh.
    assert interval.thermal_loss_kwh == pytest.approx(-0.6)
    assert interval.charge_energy_kwh == pytest.approx(2.8)
    assert interval.stored_energy_next_kwh == pytest.approx(13.0)
    assert interval.indoor_temperature_next_c == pytest.approx(20.64)


def test_active_temperature_target_respects_interval_boundaries():
    targets = (
        TemperatureTarget(18.0, time(0, 0), time(7, 0)),
        TemperatureTarget(21.0, time(7, 0), time(0, 0)),
    )

    assert active_temperature_target(targets, START + timedelta(hours=3), "UTC") == 18.0
    assert active_temperature_target(targets, START + timedelta(hours=8), "UTC") == 21.0


def test_cross_midnight_target_uses_the_start_weekday_and_exclusive_end():
    target = TemperatureTarget(19.0, time(22, 0), time(2, 0), weekdays=(4,))

    assert active_temperature_target((target,), START + timedelta(hours=22, minutes=30), "UTC") == 19.0
    assert active_temperature_target((target,), START + timedelta(days=1, hours=1), "UTC") == 19.0
    assert active_temperature_target((target,), START + timedelta(days=1, hours=2), "UTC") is None
    assert active_temperature_target((target,), START - timedelta(hours=1), "UTC") is None


def test_overlapping_temperature_targets_are_rejected_even_across_midnight():
    with pytest.raises(ValueError, match="overlap"):
        replace(
            _heater(),
            temperature_targets=(
                TemperatureTarget(19.0, time(22, 0), time(2, 0), weekdays=(4,)),
                TemperatureTarget(20.0, time(1, 0), time(3, 0), weekdays=(5,)),
            ),
        )


def test_room_energy_gaps_have_no_temperature_target_or_comfort_deficit():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(21.0, time(0, 0), time(1, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)},
        )
    )
    assert result.demand[1].target_temperature_c is None
    assert result.demand[1].temperature_shortfall_c == pytest.approx(0.0)
    assert not any(
        item.requirement == "temperature_comfort" and item.at == START + timedelta(hours=1)
        for item in result.violations
    )


def test_sufficient_storage_reaches_target_without_charging():
    result = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=20.0, soc=100.0)})
    )
    interval = result.demand[0]

    assert result.status == FEASIBLE
    assert interval.indoor_temperature_next_c == pytest.approx(21.0)
    assert interval.charge_energy_kwh == pytest.approx(0.0)
    assert interval.temperature_shortfall_c == pytest.approx(0.0)


def test_insufficient_storage_reports_shortfall_without_negative_energy():
    result = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)})
    )
    interval = result.demand[0]

    assert result.status == DEGRADED
    assert interval.stored_energy_next_kwh >= 0.0
    assert interval.temperature_shortfall_c > 0.0
    assert any(item.requirement == "temperature_comfort" for item in result.violations)


def test_forecast_changes_exchange_but_soc_does_not_become_temperature():
    cold = RoomEnergyPlanner().build(_request(outdoor=0.0))
    warm = RoomEnergyPlanner().build(_request(outdoor=20.0))
    low_soc = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)})
    )

    assert cold.demand[0].thermal_loss_kwh > warm.demand[0].thermal_loss_kwh
    assert cold.demand[0].indoor_temperature_c == pytest.approx(
        warm.demand[0].indoor_temperature_c
    )
    assert low_soc.demand[0].indoor_temperature_c == pytest.approx(20.0)
    assert low_soc.demand[0].stored_energy_kwh == pytest.approx(0.0)


def test_priority_is_used_when_contract_power_cannot_charge_all_rooms():
    heaters = (_heater("high", priority=100), _heater("low", priority=1))
    result = RoomEnergyPlanner().build(
        _request(
            heaters,
            telemetry={heater.id: _telemetry(heater.id, indoor=20.0, soc=0.0) for heater in heaters},
            max_total_power_w=2800,
        )
    )

    assert result.slots[0].heater_ids == ("high",)
    assert result.slots[0].power_w <= 2800


def test_missing_or_stale_room_telemetry_is_explicitly_invalid():
    missing = RoomEnergyPlanner().build(
        _request(telemetry={"salon": ChargeTelemetry("salon", indoor_temperature_c=20.0)})
    )
    stale = RoomEnergyPlanner().build(
        _request(
            telemetry={
                "salon": ChargeTelemetry(
                    "salon",
                    indoor_temperature_c=20.0,
                    stored_soc_percent=50.0,
                    indoor_received_at=START - timedelta(hours=1),
                    stored_soc_received_at=START,
                )
            }
        )
    )

    assert missing.status == INVALID
    assert stale.status == INVALID
    assert all(item.requirement == "safe_planning_input" for item in missing.violations)


def test_disabled_temperature_targets_are_explicitly_missing_schedule():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(21.0, time(0, 0), enabled=False),),
    )

    result = RoomEnergyPlanner().build(_request(heaters=(heater,)))

    assert result.status == INVALID
    assert result.violations[0].reason == "missing_temperature_schedule"


def test_estimator_projects_each_interval_from_indoor_temperature_and_soc():
    intervals = RoomEnergyDemandEstimator().estimate(
        (_heater(),),
        {"salon": _telemetry("salon", indoor=20.0, soc=50.0)},
        (HourlyForecastPoint(START, 5.0),),
        (START,),
        60,
        targets={"salon": (_heater().temperature_targets[0],)},
    )

    assert intervals[0].stored_energy_kwh == pytest.approx(11.2)
    assert intervals[0].indoor_temperature_next_c == pytest.approx(21.0)
