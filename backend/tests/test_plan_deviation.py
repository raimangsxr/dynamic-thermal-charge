"""Early replanning when the active room-energy plan stops serving conditions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest

from dynamic_thermal_charge.models import (
    ChargeTelemetry,
    Heater,
    OutputConfig,
    TemperatureTarget,
    ThermalProfile,
)
from dynamic_thermal_charge.plan_deviation import (
    PROJECTED_DEFICIT,
    SURPLUS_STORED_ENERGY,
    SlotBoundaryGate,
    evaluate_plan_deviation,
)
from dynamic_thermal_charge.weather import HourlyForecastPoint


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)
SLOT = timedelta(minutes=60)


def _heater(heater_id: str = "salon", *, target: float = 21.0) -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id,
        power_w=2800,
        full_charge_minutes=480,
        priority=1,
        output=OutputConfig(),
        thermal=ThermalProfile(
            room_thermal_capacity_kwh_per_c=2.5,
            room_heat_loss_kw_per_c=0.12,
        ),
        temperature_targets=(TemperatureTarget(target, time(0, 0)),),
    )


def _telemetry(heater_id: str, *, indoor: float, soc: float) -> ChargeTelemetry:
    return ChargeTelemetry(
        heater_id=heater_id,
        indoor_temperature_c=indoor,
        stored_soc_percent=soc,
        indoor_received_at=NOW,
        stored_soc_received_at=NOW,
    )


def _plan(
    *,
    heaters=("salon",),
    shortfall: float = 0.0,
    stored_next: float = 11.2,
    charge: bool = True,
    slots: int = 2,
    status: str = "VALID",
) -> dict:
    return {
        "status": status,
        "slots": [
            {
                "start": NOW + index * SLOT,
                "end": NOW + (index + 1) * SLOT,
                "heater_ids": list(heaters) if charge else [],
                "temperature_shortfall_c": {item: shortfall for item in heaters},
                "temperature_shortfall_start_c": {item: 0.0 for item in heaters},
                "stored_energy_next_kwh": {item: stored_next for item in heaters},
            }
            for index in range(slots)
        ],
    }


def _evaluate(plan, *, heaters, telemetry, outdoor=5.0, **kwargs):
    forecast = tuple(
        HourlyForecastPoint(NOW + timedelta(hours=offset), outdoor)
        for offset in range(4)
    )
    return evaluate_plan_deviation(
        plan,
        heaters=heaters,
        telemetry=telemetry,
        forecast=forecast,
        targets={heater.id: heater.temperature_targets for heater in heaters},
        at=NOW,
        slot_minutes=60,
        **kwargs,
    )


def test_colder_measured_room_triggers_replanning():
    heater = _heater()
    verdict = _evaluate(
        _plan(),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is True
    assert verdict.reason == PROJECTED_DEFICIT
    assert verdict.heater_id == "salon"
    assert verdict.projected_value > verdict.planned_value
    assert verdict.audit_details()["deviation_reason"] == PROJECTED_DEFICIT


def test_a_deficit_already_foreseen_by_the_plan_is_not_new():
    heater = _heater()
    verdict = _evaluate(
        _plan(shortfall=10.0),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


def test_surplus_stored_energy_triggers_replanning_after_comfort_check():
    heater = _heater(target=15.0)
    verdict = _evaluate(
        _plan(stored_next=1.0),
        heaters=(heater,),
        outdoor=15.0,
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=100.0)},
    )

    assert verdict.replan is True
    assert verdict.reason == SURPLUS_STORED_ENERGY
    assert verdict.projected_value > verdict.planned_value


def test_comfort_deviation_takes_precedence_over_surplus_energy():
    heater = _heater()
    verdict = _evaluate(
        _plan(stored_next=0.0),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.reason == PROJECTED_DEFICIT


def test_tolerance_controls_projected_deficit_detection():
    heater = _heater()
    telemetry = {"salon": _telemetry("salon", indoor=15.0, soc=5.0)}

    tight = _evaluate(_plan(), heaters=(heater,), telemetry=telemetry)
    loose = _evaluate(
        _plan(),
        heaters=(heater,),
        telemetry=telemetry,
        shortfall_tolerance_c=50.0,
    )

    assert tight.replan is True
    assert loose.replan is False


@pytest.mark.parametrize(
    "plan",
    [None, {"status": "INVALID", "slots": _plan()["slots"]}, {"status": "VALID", "slots": []}],
)
def test_missing_or_non_actionable_plan_has_no_deviation(plan):
    heater = _heater()
    verdict = _evaluate(
        plan,
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


def test_a_slot_already_under_way_is_not_reprojected():
    heater = _heater()
    plan = _plan(slots=1)
    plan["slots"][0]["start"] = NOW - SLOT
    plan["slots"][0]["end"] = NOW

    verdict = _evaluate(
        plan,
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


def test_missing_forecast_coverage_is_not_a_deviation():
    heater = _heater()
    verdict = evaluate_plan_deviation(
        _plan(),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
        forecast=(),
        targets={"salon": heater.temperature_targets},
        at=NOW,
        slot_minutes=60,
    )

    assert verdict.replan is False


def test_one_usable_heater_can_trigger_when_another_has_no_telemetry():
    salon, cocina = _heater("salon"), _heater("cocina")
    verdict = _evaluate(
        _plan(heaters=("salon", "cocina")),
        heaters=(salon, cocina),
        telemetry={"cocina": _telemetry("cocina", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is True
    assert verdict.heater_id == "cocina"


def test_disabled_heater_is_not_reprojected():
    heater = replace(_heater(), enabled=False)
    verdict = _evaluate(
        _plan(),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


def test_slot_boundary_gate_allows_one_check_per_boundary():
    gate = SlotBoundaryGate()

    assert gate.enter(NOW, 30) is True
    assert gate.enter(NOW + timedelta(minutes=5), 30) is False
    assert gate.enter(NOW + timedelta(minutes=29), 30) is False
    assert gate.enter(NOW + timedelta(minutes=30), 30) is True
    assert gate.enter(NOW + timedelta(minutes=31), 30) is False
