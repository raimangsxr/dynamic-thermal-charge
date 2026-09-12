from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest

from dynamic_thermal_charge.charge_planning import (
    CONVERGING,
    DEGRADED,
    FEASIBLE,
    INVALID,
    PlanningInput,
    PlanningViolation,
    RoomEnergyDemandEstimator,
    RoomEnergyPlanner,
    active_temperature_target,
    group_planning_violations,
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
    full_discharge_minutes: int = 600,
    priority: int = 1,
    target: float = 21.0,
) -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id,
        power_w=power_w,
        full_charge_minutes=full_charge_minutes,
        full_discharge_minutes=full_discharge_minutes,
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
    slot_minutes: int = 60,
) -> PlanningInput:
    points = tuple(
        HourlyForecastPoint(START + timedelta(hours=offset), outdoor)
        for offset in range(horizon_hours + 1)
    )
    return PlanningInput(
        heaters=heaters,
        telemetry=telemetry or {heater.id: _telemetry(heater.id) for heater in heaters},
        constraints=(),
        forecast=points,
        horizon_start=START,
        horizon_hours=horizon_hours,
        slot_minutes=slot_minutes,
        max_total_power_w=max_total_power_w,
        temperature_targets={heater.id: heater.temperature_targets for heater in heaters},
        room_energy_model=True,
    )


def test_accumulator_capacity_is_nominal_power_times_full_charge_hours():
    heater = _heater()

    assert heater.capacity_kwh == pytest.approx(22.4)
    assert heater.capacity_kwh * 0.5 == pytest.approx(11.2)


def test_room_energy_step_limits_discharge_to_emission_capability():
    heater = _heater(power_w=2400, full_charge_minutes=480)
    initial_energy = heater.capacity_kwh * 0.507

    interval = room_energy_step(
        heater,
        start=START,
        outdoor_temperature_c=20.0,
        target_temperature_c=None,
        indoor_temperature_c=20.0,
        stored_energy_kwh=initial_energy,
        slot_minutes=30,
        heat_delivered_kwh=6.7584,
    )

    # 19.2 kWh over 10 h is 1.92 kW at full charge, with a 20% residual floor:
    # 0.384 + (1.92 - 0.384) * 0.507 = 1.162752 kW, so 0.581376 kWh in 30 min.
    assert interval.heat_delivered_kwh == pytest.approx(0.581376)
    assert interval.heat_delivery_limit_kwh == pytest.approx(0.581376)
    assert interval.stored_energy_next_kwh == pytest.approx(9.153024)


def test_emission_capability_decays_with_the_state_of_charge():
    heater = _heater(power_w=2400, full_charge_minutes=480)

    assert heater.emission_power_kw == pytest.approx(1.92)
    assert heater.static_emission_power_kw == pytest.approx(0.384)

    limits = {}
    for soc in (100.0, 20.0):
        interval = room_energy_step(
            heater,
            start=START,
            outdoor_temperature_c=20.0,
            target_temperature_c=None,
            indoor_temperature_c=20.0,
            stored_energy_kwh=heater.capacity_kwh * soc / 100,
            slot_minutes=30,
            heat_delivered_kwh=heater.capacity_kwh,
        )
        limits[soc] = interval.heat_delivery_limit_kwh
        assert interval.heat_delivered_kwh == pytest.approx(limits[soc])

    assert limits[100.0] == pytest.approx(0.96)
    assert limits[20.0] == pytest.approx(0.3456)


def test_empty_accumulator_delivers_no_heat_despite_the_residual_floor():
    heater = _heater(power_w=2400, full_charge_minutes=480)

    interval = room_energy_step(
        heater,
        start=START,
        outdoor_temperature_c=5.0,
        target_temperature_c=21.0,
        indoor_temperature_c=20.0,
        stored_energy_kwh=0.0,
        slot_minutes=30,
    )

    # The floor is a capability, not a forced emission: with nothing stored the
    # accumulator delivers nothing and the deficit is preserved.
    assert interval.heat_delivery_limit_kwh == pytest.approx(0.192)
    assert interval.heat_delivered_kwh == pytest.approx(0.0)
    assert interval.stored_energy_next_kwh == pytest.approx(0.0)
    assert interval.temperature_shortfall_c > 0.0


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


def test_room_energy_target_end_is_enforced_but_the_gap_after_it_is_unconstrained():
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
    assert any(
        item.requirement == "temperature_comfort" and item.at == START + timedelta(hours=1)
        for item in result.violations
    )
    assert not any(
        item.requirement == "temperature_comfort" and item.at == START + timedelta(hours=2)
        for item in result.violations
    )


def test_sufficient_storage_reaches_target_without_charging():
    result = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=21.0, soc=100.0)})
    )
    interval = result.demand[0]

    assert result.status == FEASIBLE
    assert interval.indoor_temperature_next_c == pytest.approx(21.0)
    assert interval.charge_energy_kwh == pytest.approx(0.0)
    assert interval.temperature_shortfall_c == pytest.approx(0.0)


def test_warm_forecast_needs_no_residual_charge_for_a_later_target():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(22.0, time(15, 0), time(23, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=30.0,
            horizon_hours=24,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)},
        )
    )

    assert result.status == FEASIBLE
    assert all(not slot.heater_ids for slot in result.slots)
    assert all(interval.charge_energy_kwh == pytest.approx(0.0) for interval in result.demand)


def test_equal_comfort_and_energy_uses_the_latest_physically_viable_slot():
    heater = replace(
        _heater(full_charge_minutes=480, full_discharge_minutes=60),
        temperature_targets=(TemperatureTarget(20.15, time(2, 0), time(3, 0)),),
    )
    request = _request(
        heaters=(heater,),
        outdoor=20.0,
        horizon_hours=4,
        telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)},
    )

    first = RoomEnergyPlanner().build(request)
    second = RoomEnergyPlanner().build(request)

    assert first.status == FEASIBLE
    assert [index for index, slot in enumerate(first.slots) if slot.heater_ids] == [1]
    assert [slot.heater_ids for slot in first.slots] == [slot.heater_ids for slot in second.slots]
    assert first.explanations[0].charge_reasons[0]["reason"] == "preheating_for_next_target"


def test_power_contention_is_resolved_deterministically_without_exceeding_limit():
    heaters = tuple(
        replace(
            _heater(heater_id),
            full_discharge_minutes=60,
            temperature_targets=(TemperatureTarget(20.15, time(2, 0), time(3, 0)),),
        )
        for heater_id in ("a", "b")
    )
    request = _request(
        heaters=heaters,
        outdoor=20.0,
        horizon_hours=4,
        max_total_power_w=2800,
        telemetry={
            heater.id: _telemetry(heater.id, indoor=20.0, soc=0.0)
            for heater in heaters
        },
    )

    first = RoomEnergyPlanner().build(request)
    second = RoomEnergyPlanner().build(request)

    assert first.status == FEASIBLE
    assert [slot.heater_ids for slot in first.slots] == [slot.heater_ids for slot in second.slots]
    assert all(slot.power_w <= 2800 for slot in first.slots)
    assert {interval.heater_id for interval in first.demand if interval.charge_energy_kwh > 0} == {"a", "b"}


def test_terminal_objective_discharges_new_charge_when_the_dynamics_allow_it():
    heater = replace(
        _heater(full_discharge_minutes=60),
        temperature_targets=(TemperatureTarget(20.15, time(2, 0), time(3, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            horizon_hours=4,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)},
        )
    )

    explanation = result.explanations[0]
    assert explanation.total_charge_energy_kwh == pytest.approx(2.8)
    assert explanation.final_stored_energy_kwh == pytest.approx(0.0)
    assert explanation.terminal_surplus_energy_kwh == pytest.approx(0.0)


def test_preheating_satisfies_the_start_and_end_of_a_later_target():
    # An empty accumulator only has its residual emission capability, so one
    # hour of charging can nudge the room by 0.448 kWh / 2.5 kWh/C = 0.179 C.
    # The target is chosen inside that reach so the scenario stays about the
    # boundary invariant and not about an impossible lift.
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.15, time(1, 0), time(2, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            horizon_hours=3,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)},
        )
    )

    assert result.status == FEASIBLE
    assert result.demand[0].target_temperature_c is None
    assert result.demand[0].charge_energy_kwh > 0.0
    assert result.demand[0].heat_delivered_kwh > 0.0
    assert result.demand[0].indoor_temperature_next_c >= 20.15 - 1e-6
    assert result.demand[1].indoor_temperature_c >= 20.15 - 1e-6
    assert result.demand[1].indoor_temperature_next_c >= 20.15 - 1e-6
    assert not result.violations


def test_horizon_start_deficit_uses_initial_temperature_and_boundary_time():
    # A full accumulator emits 2.24 kW, which lifts this room by 0.896 C in an
    # hour, so the target stays inside that reach: the deficit under test is the
    # unavoidable one at the starting edge, not an emission limit.
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.5, time(0, 0)),),
    )
    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=100.0)},
        )
    )
    interval = result.demand[0]

    assert result.status == DEGRADED
    assert interval.temperature_shortfall_start_c == pytest.approx(0.5)
    assert interval.temperature_shortfall_c == pytest.approx(0.0)
    assert any(
        item.requirement == "temperature_comfort"
        and item.at == START
        and item.shortfall == pytest.approx(0.5)
        for item in result.violations
    )


def test_an_initial_deficit_is_converging_only_after_a_later_active_boundary():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.5, time(0, 0)),),
    )
    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=100.0)},
        )
    )

    assert result.status == CONVERGING
    assert result.convergence_by_heater["salon"] == START + timedelta(hours=1)
    assert result.convergence_at == START + timedelta(hours=1)
    assert result.guaranteed_until == START + timedelta(hours=2)


def test_a_target_window_end_cannot_be_used_as_convergence_evidence():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.5, time(0, 0), time(1, 0)),),
    )
    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=100.0)},
        )
    )

    assert result.status == DEGRADED
    assert result.convergence_by_heater == {}


def test_consecutive_deficits_are_grouped_without_losing_raw_observations():
    window_start = START + timedelta(hours=1)
    window_end = START + timedelta(hours=4)
    raw = (
        PlanningViolation(
            "salon", "temperature_comfort", 20.0, 0.4, window_start,
            "insufficient_stored_energy_or_power", window_start, window_end,
        ),
        PlanningViolation(
            "salon", "temperature_comfort", 19.7, 0.8,
            window_start + timedelta(minutes=30),
            "insufficient_stored_energy_or_power", window_start, window_end,
        ),
        PlanningViolation(
            "salon", "temperature_comfort", 19.9, 0.6,
            window_start + timedelta(hours=1),
            "insufficient_stored_energy_or_power", window_start, window_end,
        ),
    )

    grouped = group_planning_violations(raw, slot_minutes=30)

    assert len(raw) == 3
    assert len(grouped) == 1
    assert grouped[0]["observation_count"] == 3
    assert grouped[0]["affected_from"] == window_start
    assert grouped[0]["affected_until"] == window_start + timedelta(hours=1)
    assert grouped[0]["shortfall"] == pytest.approx(0.8)


def test_a_gap_splits_deficit_groups_with_the_same_cause():
    window_start = START + timedelta(hours=1)
    window_end = START + timedelta(hours=5)
    raw = (
        PlanningViolation(
            "salon", "temperature_comfort", 20.0, 0.4, window_start,
            "insufficient_stored_energy_or_power", window_start, window_end,
        ),
        PlanningViolation(
            "salon", "temperature_comfort", 19.5, 0.7,
            window_start + timedelta(hours=2),
            "insufficient_stored_energy_or_power", window_start, window_end,
        ),
    )

    grouped = group_planning_violations(raw, slot_minutes=30)

    assert len(grouped) == 2


def test_insufficient_storage_reports_shortfall_without_negative_energy():
    result = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=20.0, soc=0.0)})
    )
    interval = result.demand[0]

    assert result.status == DEGRADED
    assert interval.stored_energy_next_kwh >= 0.0
    assert interval.temperature_shortfall_c > 0.0
    assert any(item.requirement == "temperature_comfort" for item in result.violations)


def test_room_energy_solver_limits_discharge_and_preserves_comfort_deficit():
    heater = replace(
        _heater(power_w=2400, full_charge_minutes=480),
        temperature_targets=(TemperatureTarget(22.70336, time(0, 0)),),
    )
    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            slot_minutes=30,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=50.7)},
        )
    )
    interval = result.demand[0]

    assert result.status == DEGRADED
    assert interval.heat_delivered_kwh == pytest.approx(0.581376)
    assert interval.stored_energy_next_kwh >= 0.0
    assert interval.temperature_shortfall_c > 0.0
    assert any(
        item.requirement == "temperature_comfort"
        and item.reason == "insufficient_stored_energy_or_power"
        for item in result.violations
    )


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
    # At half charge the capability is 0.448 + 1.792 * 0.5 = 1.344 kW, below the
    # 1.8 kW the envelope is losing, so the room cools despite full emission.
    assert intervals[0].heat_delivery_limit_kwh == pytest.approx(1.344)
    assert intervals[0].heat_delivered_kwh == pytest.approx(1.344)
    assert intervals[0].indoor_temperature_next_c == pytest.approx(19.8176)


def test_no_heat_is_delivered_when_no_target_remains_in_the_horizon():
    # The discharge system only emits on demand: a target that ends before the
    # horizon does leaves the trailing slots with nothing to reach.
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.5, time(0, 0), time(1, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=20.0,
            horizon_hours=3,
            telemetry={"salon": _telemetry("salon", indoor=20.5, soc=100.0)},
        )
    )

    assert result.demand[0].target_temperature_c == pytest.approx(20.5)
    assert result.demand[1].target_temperature_c is None
    assert result.demand[2].target_temperature_c is None
    assert result.demand[1].heat_delivered_kwh == pytest.approx(0.0)
    assert result.demand[2].heat_delivered_kwh == pytest.approx(0.0)


def test_emission_capability_bounds_the_plan_at_every_state_of_charge():
    # A target this room cannot reach even at full charge stays DEGRADED, with
    # the stored energy inside its physical bounds at both boundaries.
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(24.0, time(0, 0)),),
    )

    result = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=5.0,
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.0, soc=100.0)},
        )
    )

    assert result.status == DEGRADED
    for interval in result.demand:
        assert interval.heat_delivered_kwh <= interval.heat_delivery_limit_kwh + 1e-9
        assert 0.0 <= interval.stored_energy_kwh <= heater.capacity_kwh + 1e-9
        assert 0.0 <= interval.stored_energy_next_kwh <= heater.capacity_kwh + 1e-9
    assert any(item.requirement == "temperature_comfort" for item in result.violations)


def test_terminal_guard_keeps_only_energy_needed_by_a_continuing_target():
    heater = replace(
        _heater(power_w=1000, full_charge_minutes=60, full_discharge_minutes=60),
        temperature_targets=(TemperatureTarget(20.5, time(1, 0), time(4, 0)),),
    )
    crossing = RoomEnergyPlanner().build(
        _request(
            heaters=(heater,),
            outdoor=13.9,
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.75, soc=0.0)},
        )
    )

    assert crossing.status == FEASIBLE
    assert len(crossing.slots) == 2
    assert len(crossing.demand) == 2
    assert crossing.explanations[0].final_stored_energy_kwh > 0.0
    guard = room_energy_step(
        heater,
        start=START + timedelta(hours=2),
        outdoor_temperature_c=13.9,
        target_temperature_c=20.5,
        indoor_temperature_c=crossing.demand[-1].indoor_temperature_next_c,
        stored_energy_kwh=crossing.explanations[0].final_stored_energy_kwh,
        slot_minutes=60,
        charge_on=False,
    )
    assert guard.temperature_shortfall_start_c == pytest.approx(0.0)
    assert guard.temperature_shortfall_c == pytest.approx(0.0)


def test_target_ending_at_the_horizon_does_not_add_a_terminal_guard():
    heater = replace(
        _heater(power_w=1000, full_charge_minutes=60, full_discharge_minutes=60),
        temperature_targets=(TemperatureTarget(20.5, time(1, 0), time(2, 0)),),
    )
    request = replace(
        _request(
            heaters=(heater,),
            outdoor=13.9,
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.75, soc=0.0)},
        ),
        forecast=tuple(
            HourlyForecastPoint(START + timedelta(hours=offset), 13.9)
            for offset in range(2)
        ),
    )
    result = RoomEnergyPlanner().build(request)

    assert result.status == FEASIBLE
    assert len(result.slots) == 2
    assert result.explanations[0].final_stored_energy_kwh == pytest.approx(0.0)


def test_missing_terminal_guard_forecast_is_explicitly_invalid():
    heater = replace(
        _heater(),
        temperature_targets=(TemperatureTarget(20.5, time(1, 0), time(4, 0)),),
    )
    request = replace(
        _request(
            heaters=(heater,),
            horizon_hours=2,
            telemetry={"salon": _telemetry("salon", indoor=20.5, soc=100.0)},
        ),
        forecast=(HourlyForecastPoint(START, 20.0), HourlyForecastPoint(START + timedelta(hours=1), 20.0)),
    )

    result = RoomEnergyPlanner().build(request)

    assert result.status == INVALID
    assert result.violations[0].reason.startswith("missing_guard_forecast_coverage")
    assert len(result.slots) == 2


def test_room_time_limited_candidate_is_degraded_until_all_phases_are_optimal(monkeypatch):
    import pulp

    original_solve = pulp.LpProblem.solve
    calls = 0

    def solve_with_timeout(model, solver):
        nonlocal calls
        calls += 1
        status = original_solve(model, solver)
        if calls == 2:
            for variable in model.variables():
                variable.varValue = None
            return pulp.LpStatusNotSolved
        return status

    monkeypatch.setattr(pulp.LpProblem, "solve", solve_with_timeout)
    result = RoomEnergyPlanner().build(
        _request(telemetry={"salon": _telemetry("salon", indoor=21.0, soc=100.0)})
    )

    assert result.status == DEGRADED
    assert len(result.score) < 8
    assert any(item.requirement == "solver_time_limit" for item in result.violations)


def test_large_room_model_keeps_priority_lexicographic():
    heaters = tuple(
        replace(
            _heater(
                heater_id,
                power_w=1000,
                full_charge_minutes=60,
                full_discharge_minutes=60,
                priority=100 if heater_id == "high" else 1,
                target=20.15,
            ),
            temperature_targets=(TemperatureTarget(20.15, time(1, 0), time(2, 0)),),
            static_emission_percent=100.0,
        )
        for heater_id in ("high", "low", "spare", "fourth")
    )
    telemetry = {
        heater.id: _telemetry(
            heater.id, indoor=20.0, soc=0.0
        )
        for heater in heaters
    }
    request = _request(
        heaters=heaters,
        outdoor=20.0,
        horizon_hours=13,
        telemetry=telemetry,
        max_total_power_w=1000,
        slot_minutes=30,
    )

    first = RoomEnergyPlanner().build(request)
    second = RoomEnergyPlanner().build(request)

    assert len(first.slots) * len(heaters) > 96
    assert first.status in {FEASIBLE, DEGRADED}
    assert len(first.score) == 9
    assert not any(item.requirement == "solver_time_limit" for item in first.violations)
    high_shortfall = sum(
        item.shortfall or 0.0 for item in first.violations if item.heater_id == "high"
    )
    low_shortfall = sum(
        item.shortfall or 0.0 for item in first.violations if item.heater_id == "low"
    )
    assert high_shortfall < low_shortfall
    assert [slot.heater_ids for slot in first.slots] == [slot.heater_ids for slot in second.slots]


def test_large_room_model_places_charge_in_the_latest_viable_slot():
    heaters = tuple(
        replace(
            _heater(
                heater_id,
                power_w=1000,
                full_charge_minutes=60,
                full_discharge_minutes=60,
                target=20.0,
            ),
            temperature_targets=(
                (
                    TemperatureTarget(20.15, time(10, 0), time(12, 0))
                    if heater_id == "late"
                    else TemperatureTarget(20.0, time(1, 0), time(2, 0))
                ),
            ),
        )
        for heater_id in ("late", "idle", "spare", "fourth")
    )
    request = _request(
        heaters=heaters,
        outdoor=20.0,
        horizon_hours=26,
        telemetry={heater.id: _telemetry(heater.id, indoor=20.0, soc=0.0) for heater in heaters},
        max_total_power_w=1000,
        slot_minutes=60,
    )

    first = RoomEnergyPlanner().build(request)
    second = RoomEnergyPlanner().build(request)

    assert len(first.slots) * len(heaters) > 96
    assert first.status == FEASIBLE
    assert len(first.score) == 8
    assert not any(item.requirement == "solver_time_limit" for item in first.violations)
    assert [slot.heater_ids for slot in first.slots] == [slot.heater_ids for slot in second.slots]
    late_charge_starts = [
        round((interval.start - START).total_seconds() / 3600)
        for interval in first.demand
        if interval.heater_id == "late" and interval.charge_energy_kwh > 1e-6
    ]
    assert late_charge_starts == [8]
