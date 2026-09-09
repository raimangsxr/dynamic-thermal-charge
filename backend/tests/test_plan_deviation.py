"""Whether the active plan still serves the measured conditions."""

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
            room_thermal_capacity_kwh_per_c=2.5, room_heat_loss_kw_per_c=0.12
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
    status: str = "FEASIBLE",
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


# --------------------------------------------------------------------------- #
# R1, R3: a deficit the plan did not foresee
# --------------------------------------------------------------------------- #

def test_a_colder_room_than_projected_triggers_a_recalculation():
    heater = _heater()
    verdict = _evaluate(
        _plan(),
        heaters=(heater,),
        # The plan projected no deficit; the measured room is far colder and its
        # store nearly empty, so the remaining window can no longer hold 21 C.
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is True
    assert verdict.reason == PROJECTED_DEFICIT
    assert verdict.heater_id == "salon"
    assert verdict.projected_value > verdict.planned_value
    assert "déficit" in verdict.detail
    assert verdict.audit_details()["deviation_reason"] == PROJECTED_DEFICIT


def test_conditions_matching_the_plan_do_not_trigger_anything():
    heater = _heater(target=15.0)
    verdict = _evaluate(
        # The plan projected the full store the reprojection also reaches, so
        # there is neither a deficit nor a surplus.
        _plan(stored_next=heater.capacity_kwh),
        heaters=(heater,),
        outdoor=15.0,
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=100.0)},
    )

    assert verdict.replan is False
    assert verdict.reason is None


def test_a_deficit_the_plan_already_expected_does_not_trigger_again():
    """R3: only a deficit beyond what the plan foresaw is news."""
    heater = _heater()
    verdict = _evaluate(
        # The plan already recorded a large deficit for this heater.
        _plan(shortfall=10.0),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


def test_the_tolerance_decides_what_counts_as_a_deficit():
    heater = _heater()
    telemetry = {"salon": _telemetry("salon", indoor=15.0, soc=5.0)}

    tight = _evaluate(
        _plan(), heaters=(heater,), telemetry=telemetry, shortfall_tolerance_c=0.1
    )
    loose = _evaluate(
        _plan(), heaters=(heater,), telemetry=telemetry, shortfall_tolerance_c=50.0
    )

    assert tight.replan is True
    assert loose.replan is False


# --------------------------------------------------------------------------- #
# R4: the mirror case
# --------------------------------------------------------------------------- #

def test_surplus_stored_energy_triggers_a_recalculation():
    heater = _heater(target=15.0)
    verdict = _evaluate(
        # The plan expected to end the window with an almost empty store.
        _plan(stored_next=1.0),
        heaters=(heater,),
        outdoor=15.0,
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=100.0)},
    )

    assert verdict.replan is True
    assert verdict.reason == SURPLUS_STORED_ENERGY
    assert verdict.projected_value > verdict.planned_value
    assert "SOC" in verdict.detail


def test_a_surplus_below_the_tolerance_does_not_trigger():
    heater = _heater(target=15.0)
    verdict = _evaluate(
        _plan(stored_next=1.0),
        heaters=(heater,),
        outdoor=15.0,
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=100.0)},
        surplus_soc_percent=100.0,
    )

    assert verdict.replan is False


def test_comfort_takes_precedence_over_a_surplus():
    heater = _heater()
    verdict = _evaluate(
        _plan(stored_next=0.0),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.reason == PROJECTED_DEFICIT


# --------------------------------------------------------------------------- #
# R6 and the guards
# --------------------------------------------------------------------------- #

def test_a_heater_without_usable_telemetry_does_not_trigger_but_another_does():
    salon, cocina = _heater("salon"), _heater("cocina")
    verdict = _evaluate(
        _plan(heaters=("salon", "cocina")),
        heaters=(salon, cocina),
        # Only one accumulator reported.
        telemetry={"cocina": _telemetry("cocina", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is True
    assert verdict.heater_id == "cocina"


def test_no_telemetry_at_all_is_not_a_deviation():
    verdict = _evaluate(_plan(), heaters=(_heater(),), telemetry={})

    assert verdict.replan is False


@pytest.mark.parametrize(
    ("label", "plan"),
    [
        ("no active plan", None),
        ("invalid plan", _plan(status="INVALID")),
        ("no slots", {"status": "FEASIBLE", "slots": []}),
    ],
)
def test_nothing_to_reproject_is_not_a_deviation(label, plan):
    verdict = _evaluate(
        plan,
        heaters=(_heater(),),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False, label


def test_a_slot_already_under_way_is_not_reprojected():
    heater = _heater()
    plan = _plan(slots=1)
    # The only slot started before now, so there is nothing ahead to replan.
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


def test_a_disabled_heater_is_not_reprojected():
    heater = replace(_heater(), enabled=False)

    verdict = _evaluate(
        _plan(),
        heaters=(heater,),
        telemetry={"salon": _telemetry("salon", indoor=15.0, soc=5.0)},
    )

    assert verdict.replan is False


# --------------------------------------------------------------------------- #
# R5: one evaluation per slot boundary
# --------------------------------------------------------------------------- #

def test_the_gate_allows_one_evaluation_per_slot_boundary():
    gate = SlotBoundaryGate()

    assert gate.enter(NOW, 30) is True
    assert gate.enter(NOW + timedelta(minutes=5), 30) is False
    assert gate.enter(NOW + timedelta(minutes=29), 30) is False
    assert gate.enter(NOW + timedelta(minutes=30), 30) is True
    assert gate.enter(NOW + timedelta(minutes=31), 30) is False


# --------------------------------------------------------------------------- #
# R9, R10: what a deviation-triggered recalculation does to the active plan
# --------------------------------------------------------------------------- #

def _automatic_plan(status: str):
    from dynamic_thermal_charge.charge_planning import AutomaticPlan

    return AutomaticPlan(NOW, NOW + SLOT, 60, (), (), status, (), f"token-{status}", NOW)


def test_a_deviation_recalculation_that_fails_keeps_the_previous_plan(initialised_store):
    planning = initialised_store.planning
    revision = planning.site()["revision"]
    planning.save_plan(
        _automatic_plan("FEASIBLE"),
        configuration_revision=1,
        constraints_revision=revision,
        reason="periodic",
        active=True,
    )

    planning.save_plan(
        _automatic_plan("INVALID"),
        configuration_revision=1,
        constraints_revision=revision,
        reason="deviation",
        active=False,
        preserve_active=True,
        audit_details={"deviation_reason": PROJECTED_DEFICIT, "heater_id": "salon"},
    )

    active = planning.active_plan()
    assert active is not None
    assert active["status"] == "FEASIBLE"
    assert active["reason"] == "periodic"
    # The invalid attempt is still recorded, just not activated.
    assert planning.latest_plan()["status"] == "INVALID"


def test_a_periodic_recalculation_that_fails_still_clears_the_plan(initialised_store):
    planning = initialised_store.planning
    revision = planning.site()["revision"]
    planning.save_plan(
        _automatic_plan("FEASIBLE"),
        configuration_revision=1,
        constraints_revision=revision,
        reason="periodic",
        active=True,
    )

    planning.save_plan(
        _automatic_plan("INVALID"),
        configuration_revision=1,
        constraints_revision=revision,
        reason="periodic",
        active=False,
    )

    assert planning.active_plan() is None


def test_the_audit_distinguishes_a_deviation_from_the_periodic_cadence(initialised_store):
    planning = initialised_store.planning
    revision = planning.site()["revision"]
    planning.save_plan(
        _automatic_plan("FEASIBLE"),
        configuration_revision=1,
        constraints_revision=revision,
        reason="deviation",
        active=True,
        audit_details={
            "deviation_reason": PROJECTED_DEFICIT,
            "heater_id": "salon",
            "planned_value": 0.0,
            "projected_value": 1.5,
        },
    )

    entries = planning.audit()
    deviation = [item for item in entries if item["reason"] == "deviation"]
    assert deviation, "the deviation-triggered recalculation is not auditable"
    details = deviation[0]["details"]
    assert details["deviation_reason"] == PROJECTED_DEFICIT
    assert details["heater_id"] == "salon"
    assert details["projected_value"] == 1.5


def test_the_control_cycle_recalculates_early_when_the_check_says_so():
    """R5: the check pulls the recalculation forward instead of waiting."""
    from dynamic_thermal_charge.controller import ChargeController
    from dynamic_thermal_charge.drivers import SimulatedOutputDriver
    from dynamic_thermal_charge.service import ControllerService, PlanRefresh

    class _Store:
        def load(self):
            return None

        def save(self, *args, **kwargs):
            return None

    refreshes: list[datetime] = []
    detections = iter([True, False])

    def refresh(now: datetime) -> PlanRefresh:
        refreshes.append(now)
        # A long cadence: without the deviation check the second cycle waits.
        return PlanRefresh(None, 3600)

    service = ControllerService(
        controller=ChargeController(("salon",), SimulatedOutputDriver()),
        store=_Store(),
        refresh_plan=refresh,
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: NOW,
        wait=lambda _seconds: None,
        deviation_check=lambda _now: next(detections, False),
    )

    service.run(max_cycles=3)

    # The first cycle refreshes on schedule, the second because of the
    # deviation, and the third waits for the cadence again.
    assert len(refreshes) == 2


def test_a_failing_deviation_check_never_breaks_the_cycle(caplog):
    from dynamic_thermal_charge.controller import ChargeController
    from dynamic_thermal_charge.drivers import SimulatedOutputDriver
    from dynamic_thermal_charge.service import ControllerService, PlanRefresh

    caplog.set_level("INFO")

    class _Store:
        def load(self):
            return None

        def save(self, *args, **kwargs):
            return None

    def exploding(_now: datetime) -> bool:
        raise RuntimeError("the plan store is unreachable")

    service = ControllerService(
        controller=ChargeController(("salon",), SimulatedOutputDriver()),
        store=_Store(),
        refresh_plan=lambda _now: PlanRefresh(None, 3600),
        poll_seconds=1,
        error_retry_seconds=60,
        clock=lambda: NOW,
        wait=lambda _seconds: None,
        deviation_check=exploding,
    )

    assert service.run(max_cycles=3) == 0
    assert caplog.text.count("Could not evaluate the plan deviation") == 1


def test_the_alert_of_a_deviation_recalculation_says_the_plan_is_preserved():
    """R10: the operator learns the plan could not be replaced."""
    from dynamic_thermal_charge.runtime import _notify_recalculation_result

    queued: list[str] = []

    class _Alerts:
        def raise_alert(self, alert_type, *, subject, body):
            queued.append(body)
            return True

        def clear_alert(self, alert_type):
            return None

    _notify_recalculation_result(
        _Alerts(),
        _automatic_plan("INVALID"),
        installation="Casa",
        at=NOW,
        previous_plan_preserved=True,
    )

    assert queued and "conserva el plan anterior" in queued[0]
