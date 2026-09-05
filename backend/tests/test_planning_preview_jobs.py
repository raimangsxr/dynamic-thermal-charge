from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.charge_planning import (
    PLANNING_HORIZON_HOURS,
    DeterministicChargeOptimizer,
    PlanningInput,
)
from dynamic_thermal_charge.models import ChargeTelemetry
from dynamic_thermal_charge.weather import HourlyForecastPoint


def test_planner_rejects_incomplete_24_hour_coverage_without_partial_slots():
    start = datetime(2026, 1, 16, 1, tzinfo=timezone.utc)
    forecast = tuple(
        HourlyForecastPoint(start + timedelta(hours=index), 5)
        for index in range(PLANNING_HORIZON_HOURS - 1)
    )
    result = DeterministicChargeOptimizer().build(PlanningInput(
        heaters=(), telemetry={}, constraints=(), forecast=forecast,
        horizon_start=start,
    ))
    assert result.status == "INVALID"
    assert result.horizon_end == start + timedelta(hours=PLANNING_HORIZON_HOURS)
    assert result.slots == ()
    assert result.violations[0].reason.startswith("missing_aemet_coverage")


def test_preview_job_is_durable_and_returns_all_final_checks(client):
    token = "test-token-" + "z" * 32
    headers = {"Authorization": f"Bearer {token}"}
    started = client.post(
        "/api/v1/planning/preview/jobs",
        headers=headers,
        json={"constraints": []},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]

    final = None
    for _ in range(100):
        response = client.get(f"/api/v1/planning/preview/jobs/{job_id}", headers=headers)
        assert response.status_code == 200
        body = response.json()
        if body["status"] not in {"queued", "running", "cancelling"}:
            final = body
            break
    assert final is not None
    assert final["status"] == "completed"
    assert final["result"]["status"] == "INVALID"
    assert len(final["result"]["slots"]) == 0
    assert {item["name"] for item in final["checks"]} == {
        "input_validation", "telemetry", "aemet_coverage", "demand_estimation",
        "constraints", "resolution", "safety_validation", "operator_summary",
    }
    assert final["operator_summary"]["window"]["hours"] == 12
    assert final["operator_summary"]["horizon"]["hours"] == 24


def test_preview_job_cancel_is_visible_and_cannot_produce_a_result(initialised_store):
    from dynamic_thermal_charge.api.routes.planning import PREVIEW_STEP_NAMES, PreviewJobRunner

    site = initialised_store.planning.site()
    _config, configuration_revision = initialised_store.repository.current()
    job_id = initialised_store.planning.create_preview_job(
        [], configuration_revision=configuration_revision,
        constraints_revision=site["revision"], requested_at=datetime.now(timezone.utc),
        steps=PREVIEW_STEP_NAMES,
    )
    cancelling = initialised_store.planning.request_preview_cancel(job_id)
    assert cancelling is not None
    assert cancelling["status"] == "cancelling"

    PreviewJobRunner(lambda: initialised_store, lambda: datetime.now(timezone.utc))._run(job_id)
    final = initialised_store.planning.preview_job(job_id)
    assert final is not None
    assert final["status"] == "cancelled"
    assert final["result"] is None


def test_preview_job_with_legacy_result_remains_readable(client, initialised_store):
    token = "test-token-" + "z" * 32
    headers = {"Authorization": f"Bearer {token}"}
    started = client.post(
        "/api/v1/planning/preview/jobs",
        headers=headers,
        json={"constraints": []},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]

    final = None
    for _ in range(100):
        response = client.get(f"/api/v1/planning/preview/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        if response.json()["status"] not in {"queued", "running", "cancelling"}:
            final = initialised_store.planning.preview_job(job_id)
            break
    assert final is not None
    assert final["result"] is not None

    legacy_result = dict(final["result"])
    legacy_result.pop("window_start")
    legacy_result.pop("window_end")
    initialised_store.planning.finish_preview_job(job_id, status="completed", result=legacy_result)

    response = client.get(f"/api/v1/planning/preview/jobs/{job_id}", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["window_start"] == body["result"]["horizon_start"]
    assert body["result"]["window_end"] == "2026-01-16T13:00:00Z"
