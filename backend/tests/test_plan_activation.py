from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.plan_activation import (
    ACTIVATION_AUTOMATIC,
    ACTIVATION_BEST_EFFORT,
    can_activate_plan,
    candidate_activation_mode,
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
