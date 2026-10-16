from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.api.routes.planning import _deficit_view
from dynamic_thermal_charge.charge_planning import PlanningViolation, group_planning_violations
from dynamic_thermal_charge.plan_activation import (
    ACTIVATION_AUTOMATIC,
    ACTIVATION_BEST_EFFORT,
    can_activate_plan,
    candidate_activation_mode,
    plan_best_effort_reasons,
    plan_has_degrading_exclusions,
)


NOW = datetime(2026, 1, 16, 12, 0, tzinfo=timezone.utc)


def _active(status: str, horizon_end: datetime) -> dict:
    return {"status": status, "horizon_end": horizon_end}


def test_degraded_candidate_never_replaces_a_covering_plan():
    active = _active("VALID", NOW + timedelta(minutes=31))

    assert candidate_activation_mode(
        "DEGRADED",
        active,
        now=NOW,
        next_refresh_seconds=30 * 60,
        best_effort_requested=True,
        require_best_effort_confirmation=True,
    ) is None


def test_degraded_candidate_needs_confirmation_without_a_covering_plan():
    assert candidate_activation_mode(
        "DEGRADED",
        None,
        now=NOW,
        best_effort_requested=False,
        require_best_effort_confirmation=True,
    ) is None
    assert can_activate_plan(
        "DEGRADED",
        None,
        now=NOW,
        best_effort_requested=True,
    ) is True
    assert candidate_activation_mode(
        "DEGRADED",
        None,
        now=NOW,
        best_effort_requested=True,
        require_best_effort_confirmation=True,
    ) == ACTIVATION_BEST_EFFORT


def test_successful_candidate_replaces_best_effort_and_partial_success_is_flagged():
    active = _active("DEGRADED", NOW + timedelta(hours=1))

    assert candidate_activation_mode(
        "VALID",
        active,
        now=NOW,
        has_exclusions=False,
    ) == ACTIVATION_AUTOMATIC
    assert candidate_activation_mode(
        "CONVERGING",
        active,
        now=NOW,
        has_exclusions=True,
    ) == ACTIVATION_BEST_EFFORT


def test_successful_stale_forecast_is_activated_as_best_effort():
    active = _active("VALID", NOW + timedelta(hours=1))

    assert candidate_activation_mode(
        "VALID",
        active,
        now=NOW,
        has_stale_forecast=True,
    ) == ACTIVATION_BEST_EFFORT
    assert can_activate_plan(
        "CONVERGING",
        active,
        now=NOW,
        has_stale_forecast=True,
    ) is True
def test_calibration_exclusion_keeps_normal_activation_and_no_best_effort_reason():
    plan = {
        "status": "VALID",
        "excluded_heaters": [
            {"heater_id": "salon", "cause": "calibration_active"},
        ],
        "violations": [
            {
                "heater_id": "salon",
                "requirement": "excluded_heater",
                "reason": "calibration_active",
                "cause": "calibration_active",
            },
        ],
    }

    assert plan_has_degrading_exclusions(plan) is False
    assert plan_best_effort_reasons(plan) == ()
    assert candidate_activation_mode(
        "VALID",
        None,
        now=NOW,
        has_exclusions=plan_has_degrading_exclusions(plan),
    ) == ACTIVATION_AUTOMATIC


def test_missing_telemetry_still_degrades_alongside_calibration_exclusion():
    plan = {
        "excluded_heaters": [
            {"heater_id": "salon", "cause": "calibration_active"},
            {"heater_id": "cocina", "cause": "missing_required_state"},
        ],
    }

    assert plan_has_degrading_exclusions(plan) is True
    assert plan_best_effort_reasons(plan) == ("missing_required_state",)


def test_grouped_calibration_exclusion_preserves_cause_over_legacy_reason():
    violation = PlanningViolation(
        "salon",
        "excluded_heater",
        None,
        None,
        NOW,
        "missing_required_state",
        cause="calibration_active",
    )

    grouped = group_planning_violations((violation,), slot_minutes=30)
    assert grouped[0]["reason"] == "missing_required_state"
    assert grouped[0]["cause"] == "calibration_active"

    view = _deficit_view(grouped[0])

    assert view.cause == "calibration_active"
    assert view.recommended_action is None

    legacy = group_planning_violations(
        (
            {
                "heater_id": "salon",
                "requirement": "excluded_heater",
                "at": NOW,
                "reason": "calibration_active",
            },
        ),
        slot_minutes=30,
    )
    legacy_view = _deficit_view(legacy[0])
    assert legacy_view.cause == "calibration_active"
    assert legacy_view.recommended_action is None


def test_a_successful_candidate_can_activate_when_the_old_plan_expires_before_refresh():
    active = _active("VALID", NOW + timedelta(minutes=29))

    assert candidate_activation_mode(
        "DEGRADED",
        active,
        now=NOW,
        next_refresh_seconds=30 * 60,
        best_effort_requested=True,
        require_best_effort_confirmation=True,
    ) == ACTIVATION_BEST_EFFORT
