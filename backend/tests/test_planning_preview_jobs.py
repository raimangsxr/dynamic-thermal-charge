from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from dynamic_thermal_charge.charge_planning import (
    PLANNING_HORIZON_HOURS,
    DeterministicChargeOptimizer,
    PlanningInput,
)
from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder
from dynamic_thermal_charge.weather import HourlyForecastPoint
from tests.conftest import API_NOW, AUTH


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
        json={},
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
        "input_validation", "telemetry", "aemet_coverage", "room_model",
        "resolution", "safety_validation", "operator_summary",
    }
    assert final["operator_summary"]["window"]["hours"] == 12
    assert final["operator_summary"]["horizon"]["hours"] == 24


def test_explicitly_empty_temperature_targets_are_not_replaced_by_saved_defaults(
    client, initialised_store
):
    _configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)

    response = client.post(
        "/api/v1/planning/preview",
        headers=AUTH,
        json={"temperature_targets": [], "expected_revision": constraints_revision},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "INVALID"
    assert result["violations"][0]["reason"] == "missing_temperature_schedule"


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
        json={},
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


def _seed_valid_preview_inputs(initialised_store):
    config, configuration_revision = initialised_store.repository.current()
    points = tuple(
        HourlyForecastPoint(API_NOW + timedelta(hours=index), 4.0)
        for index in range(25)
    )
    SqlHistoryRecorder(
        initialised_store.application_engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    ).record_forecast(SimpleNamespace(
        date=API_NOW.date(), average_temperature_c=4.0,
        minimum_temperature_c=4.0, maximum_temperature_c=4.0,
        source="aemet", location="test", retrieved_at=API_NOW,
        hourly_points=points,
    ))
    for heater in config.heaters:
        for field, value in (
            ("indoor_temperature_c", 21.0),
            ("stored_soc_percent", 100.0),
        ):
            initialised_store.planning.record_telemetry(heater.id, field, value, API_NOW)
    return configuration_revision, initialised_store.planning.site()["revision"]


def _persist_preview_job(initialised_store, result, configuration_revision, constraints_revision):
    from dynamic_thermal_charge.api.routes.planning import PREVIEW_STEP_NAMES

    job_id = initialised_store.planning.create_preview_job(
        [],
        temperature_targets=[
            {
                key: value
                for key, value in item.items()
                if key != "id"
            }
            for item in result.get("temperature_targets", [])
        ],
        configuration_revision=configuration_revision,
        constraints_revision=constraints_revision,
        requested_at=API_NOW,
        steps=PREVIEW_STEP_NAMES,
    )
    initialised_store.planning.finish_preview_job(
        job_id,
        status="completed",
        result=result,
    )
    return job_id


def test_activation_reuses_completed_preview_without_second_solver_call(
    client, initialised_store, monkeypatch,
):
    configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    preview = client.post(
        "/api/v1/planning/preview",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()
    _persist_preview_job(
        initialised_store, result, configuration_revision, constraints_revision,
    )

    import dynamic_thermal_charge.api.routes.planning as planning_route

    calls = []

    class FailingOptimizer:
        def build(self, request):
            calls.append(request)
            raise AssertionError("activation should reuse the completed preview")

    monkeypatch.setattr(planning_route, "DeterministicChargeOptimizer", FailingOptimizer)
    activated = client.post(
        "/api/v1/planning/activate",
        headers=AUTH,
        json={
            "token": result["token"],
            "expected_revision": constraints_revision,
        },
    )

    assert activated.status_code == 200, activated.text
    assert calls == []
    assert activated.json()["token"] == result["token"]


def test_changed_telemetry_cannot_activate_cached_preview(
    client, initialised_store, monkeypatch,
):
    configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    preview = client.post(
        "/api/v1/planning/preview",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )
    assert preview.status_code == 200, preview.text
    result = preview.json()
    _persist_preview_job(
        initialised_store, result, configuration_revision, constraints_revision,
    )
    system = client.get("/api/v1/system/configuration", headers=AUTH).json()
    changed = client.patch(
        "/api/v1/system/configuration/mqtt",
        headers=AUTH,
        json={
            "expected_revision": system["revision"],
            "values": {"fixed_stored_soc_percent": 40.0},
        },
    )
    assert changed.status_code == 200, changed.text

    import dynamic_thermal_charge.api.routes.planning as planning_route

    calls = []

    class FailingOptimizer:
        def build(self, request):
            calls.append(request)
            raise AssertionError("stale activation must be rejected before solving")

    monkeypatch.setattr(planning_route, "DeterministicChargeOptimizer", FailingOptimizer)
    activated = client.post(
        "/api/v1/planning/activate",
        headers=AUTH,
        json={
            "token": result["token"],
            "expected_revision": constraints_revision,
        },
    )

    assert activated.status_code >= 400
    assert calls == []
