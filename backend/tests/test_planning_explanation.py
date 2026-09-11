from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.charge_planning import (
    AutomaticPlan,
    AutomaticPlanSlot,
    HeaterExplanation,
    PlanningInput,
    VALID,
)
from dynamic_thermal_charge.models import ChargeTelemetry, TemperatureTarget
from dynamic_thermal_charge.planning_explanation import planning_evidence
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.scheduler import ChargeScheduler
from dynamic_thermal_charge.weather import HourlyForecastPoint
from tests.conftest import AUTH


NOW = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _plan(*, start: datetime = NOW, charging: bool = True) -> AutomaticPlan:
    end = start + timedelta(minutes=30)
    return AutomaticPlan(
        horizon_start=start,
        horizon_end=end,
        slot_minutes=30,
        slots=(
            AutomaticPlanSlot(
                start=start,
                end=end,
                heater_ids=("salon",) if charging else (),
                power_w=2000 if charging else 0,
                stored_charge_percent={"salon": 50.0},
                required_charge_percent={"salon": 60.0},
                outdoor_temperature_c=4.0,
                indoor_temperature_c={"salon": 18.0},
                initial_soc_percent={"salon": 50.0},
                demand_kwh={"salon": 1.0},
                heater_power_w={"salon": 2000 if charging else 0},
                stored_energy_kwh={"salon": 4.0},
                target_temperature_c={"salon": 21.0},
                heat_delivered_kwh={"salon": 0.4},
                thermal_loss_kwh={"salon": 0.2},
                temperature_shortfall_c={"salon": 1.0},
                charge_energy_kwh={"salon": 1.0 if charging else 0.0},
                stored_energy_next_kwh={"salon": 4.4},
                indoor_temperature_next_c={"salon": 18.5},
                temperature_shortfall_start_c={"salon": 0.5},
                heat_delivery_limit_kwh={"salon": 0.8},
            ),
        ),
        deficits=(),
        status=VALID,
        score=(0.0,),
        input_token=f"token-{start.isoformat()}-{charging}",
        generated_at=start,
        explanations=(
            HeaterExplanation(
                heater_id="salon",
                actual_soc_percent=50.0,
                total_demand_kwh=1.0,
                demand_factor=1.0,
                reserve_percent=0.0,
                next_constraint_at=None,
                charge_periods=((start, end),) if charging else (),
                capacity_kwh=8.0,
                initial_indoor_temperature_c=18.0,
                final_indoor_temperature_c=18.5,
                total_heat_delivered_kwh=0.4,
                total_thermal_loss_kwh=0.2,
                maximum_temperature_shortfall_c=1.0,
            ),
        ),
    )


def _evidence() -> dict:
    return {
        "captured_at": NOW.isoformat(),
        "limits": {
            "contracted_power_w": 5200,
            "max_heating_power_w": 4000,
            "base_load_w": 500,
        },
        "heaters": [{"id": "salon", "name": "Salón"}],
        "telemetry": {
            "salon": {
                "indoor_temperature_c": 18.0,
                "stored_soc_percent": 50.0,
                "indoor_received_at": NOW.isoformat(),
                "stored_soc_received_at": NOW.isoformat(),
            }
        },
        "temperature_targets": [{"heater_id": "salon", "target_temperature_c": 21.0}],
        "forecast": [{"timestamp": NOW.isoformat(), "temperature_c": 4.0}],
        "forecast_automatic_eligible": True,
    }


def test_planning_evidence_allow_lists_the_real_solver_inputs():
    config = example_installation()
    heater = config.heaters[0]
    request = PlanningInput(
        heaters=(heater,),
        telemetry={
            heater.id: ChargeTelemetry(
                heater.id,
                indoor_temperature_c=18.0,
                stored_soc_percent=50.0,
                indoor_received_at=NOW,
                stored_soc_received_at=NOW,
            )
        },
        constraints=(),
        forecast=(HourlyForecastPoint(NOW, 4.0),),
        horizon_start=NOW,
        horizon_hours=1,
        slot_minutes=30,
        max_total_power_w=5200,
        max_heating_power_w=4000,
        base_load_w=500,
        temperature_targets={
            heater.id: (TemperatureTarget(21.0, NOW.time()),)
        },
        generated_at=NOW,
    )
    evidence = planning_evidence(
        request,
        planning_site={"revision": 3, "replan_minutes": 30},
        forecast_status={"forecast_status": "success"},
    )
    encoded = str(evidence).lower()
    assert evidence["telemetry"][heater.id]["indoor_temperature_c"] == 18.0
    assert evidence["limits"]["base_load_w"] == 500
    assert evidence["forecast_status"]["forecast_status"] == "success"
    assert "password" not in encoded
    assert "token" not in encoded


def test_explanation_keeps_immutable_evidence_and_predecessor(initialised_store):
    repository = initialised_store.planning
    first_id = repository.save_plan(
        _plan(), configuration_revision=1, constraints_revision=1,
        reason="periodic", active=True, evidence=_evidence(),
    )
    evidence = _evidence()
    second_id = repository.save_plan(
        _plan(start=NOW + timedelta(minutes=30), charging=False),
        configuration_revision=1, constraints_revision=1,
        reason="deviation", active=True, evidence=evidence,
        audit_details={
            "deviation_reason": "projected_deficit", "heater_id": "salon",
            "planned_value": 0.0, "projected_value": 1.0,
        },
    )
    evidence["telemetry"]["salon"]["indoor_temperature_c"] = -40

    detail = repository.plan_explanation(second_id)
    assert detail is not None
    assert detail["plan"]["predecessor_plan_id"] == first_id
    assert detail["plan"]["evidence"]["telemetry"]["salon"]["indoor_temperature_c"] == 18.0
    assert detail["comparison"]["predecessor_plan_id"] == first_id
    assert detail["comparison"]["removed_charge_intervals"]
    assert detail["operator_summary"][0]["heater_name"] == "Salón"
    assert detail["audit"][0]["details"]["deviation_reason"] == "projected_deficit"


def test_explanation_api_marks_old_automatic_plan_evidence_unavailable(
    client, initialised_store
):
    plan_id = initialised_store.planning.save_plan(
        _plan(), configuration_revision=1, constraints_revision=1,
        reason="periodic", active=True,
    )
    response = client.get(
        f"/api/v1/history/plans/automatic/{plan_id}/explanation", headers=AUTH
    )
    assert response.status_code == 200, response.text
    assert response.json()["evidence_available"] is False
    assert response.json()["plan"]["evidence"] is None


def test_non_activated_candidate_records_whether_governing_plan_was_preserved(
    initialised_store,
):
    repository = initialised_store.planning
    active_id = repository.save_plan(
        _plan(), configuration_revision=1, constraints_revision=1,
        reason="periodic", active=True, evidence=_evidence(),
    )
    candidate_id = repository.save_plan(
        _plan(start=NOW + timedelta(minutes=30), charging=False),
        configuration_revision=1, constraints_revision=1,
        reason="deviation", active=False, preserve_active=True, evidence=_evidence(),
    )
    detail = repository.plan_explanation(candidate_id)
    assert detail is not None
    assert detail["comparison"]["predecessor_plan_id"] == active_id
    assert detail["comparison"]["replaced"] is False
    assert detail["comparison"]["predecessor_preserved"] is True
    assert repository.active_plan()["id"] == active_id


def test_diagnostic_download_is_json_and_contains_no_credentials(
    client, initialised_store
):
    plan_id = initialised_store.planning.save_plan(
        _plan(), configuration_revision=1, constraints_revision=1,
        reason="periodic", active=True, evidence=_evidence(),
    )
    response = client.get(
        f"/api/v1/history/plans/automatic/{plan_id}/diagnostic", headers=AUTH
    )
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    encoded = response.text.lower()
    assert "api_token" not in encoded
    assert "password" not in encoded
    assert response.json()["plan"]["id"] == plan_id


def test_unknown_plan_and_source_are_explicit(client):
    missing = client.get(
        "/api/v1/history/plans/automatic/999999/explanation", headers=AUTH
    )
    assert missing.status_code == 404
    invalid = client.get(
        "/api/v1/history/plans/other/1/explanation", headers=AUTH
    )
    assert invalid.status_code == 400


def test_legacy_plan_is_explainable_without_inventing_missing_evidence(
    client, initialised_store, recorder
):
    config, revision = initialised_store.repository.current()
    plan = ChargeScheduler().build(config.site, config.heaters, NOW)
    reference = recorder.record_plan(plan, None, revision)
    assert reference is not None
    response = client.get(
        f"/api/v1/history/plans/legacy/{reference.id}/explanation", headers=AUTH
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "legacy"
    assert body["evidence_available"] is False
    assert body["operator_summary"] == []
    assert body["plan"]["slots"]
