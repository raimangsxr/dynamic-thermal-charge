from datetime import datetime, timezone

from dynamic_thermal_charge.planning_recovery import (
    build_planning_recovery,
    forecast_coverage,
)


def test_recovery_normalizes_known_causes_and_keeps_technical_detail():
    recovery = build_planning_recovery(
        plan_status="INVALID",
        absence_reason="invalid_automatic_plan",
        deficits=[
            {
                "heater_id": "salon",
                "reason": "missing_aemet_coverage: horizon starts at 2026-01-16T00:00:00Z",
            },
            {"heater_id": "salon", "reason": "missing_required_state: stored_soc_percent"},
        ],
    )

    assert recovery is not None
    assert recovery["primary"] == {
        "code": "missing_aemet_coverage",
        "action_code": "check_weather",
        "destination": "/configuracion",
        "detail": "missing_aemet_coverage: horizon starts at 2026-01-16T00:00:00Z",
        "heater_ids": ["salon"],
    }
    assert recovery["secondary"][0]["code"] == "missing_required_state"
    assert recovery["safe_state"] == "outputs_off"


def test_recovery_has_neutral_fallback_for_unknown_reason():
    recovery = build_planning_recovery(
        plan_status="DEGRADED",
        absence_reason=None,
        deficits=[{"heater_id": None, "reason": "new_planner_reason"}],
    )

    assert recovery == {
        "primary": {
            "code": "unknown",
            "action_code": None,
            "destination": None,
            "detail": "new_planner_reason",
            "heater_ids": [],
        },
        "secondary": [],
        "safe_state": "last_valid_plan",
    }


def test_forecast_coverage_describes_received_range_and_requirements():
    start = datetime(2026, 1, 16, 1, tzinfo=timezone.utc)
    coverage = forecast_coverage(
        {"hourly_points": [{"timestamp": start}, {"timestamp": start.replace(hour=5)}]},
        required_hours=24,
        automatic_eligible=True,
        stale=False,
    )

    assert coverage == {
        "points_received": 2,
        "coverage_start": start,
        "coverage_end": start.replace(hour=5),
        "required_hours": 24,
        "automatic_eligible": True,
        "stale": False,
    }
