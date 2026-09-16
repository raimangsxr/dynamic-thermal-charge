from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from time import sleep

from dynamic_thermal_charge.charge_planning import (
    AutomaticPlan,
    PLANNING_HORIZON_HOURS,
    DeterministicChargeOptimizer,
    PlanningInput,
    VALID,
    input_token,
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


def test_preview_rejects_non_aligned_temperature_targets_without_persisting(
    client, initialised_store
):
    _configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    before = client.get("/api/v1/config/heaters/salon", headers=AUTH).json()

    response = client.post(
        "/api/v1/planning/preview",
        headers=AUTH,
        json={
            "expected_revision": constraints_revision,
            "temperature_targets": [
                {
                    "heater_id": "salon",
                    "target_temperature_c": 21.0,
                    "start_time": "10:15",
                    "end_time": "11:15",
                    "weekdays": [0],
                }
            ],
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["field"] == "temperature_targets"
    assert "non-aligned" in response.json()["message"]
    assert client.get("/api/v1/config/heaters/salon", headers=AUTH).json() == before


def test_preview_job_cancel_is_visible_and_cannot_produce_a_result(initialised_store):
    from dynamic_thermal_charge.api.routes.planning import (
        PREVIEW_STEP_NAMES,
        PreviewJobRunner,
    )

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


def _seed_valid_preview_inputs(initialised_store, *, forecast_temperature_c=4.0):
    system = initialised_store.system_configuration
    system_snapshot = system.current()
    system.update_section(
        "mqtt",
        {"enabled": True, "host": "broker.test"},
        expected_revision=system_snapshot.revision,
        actor="test",
    )
    config, configuration_revision = initialised_store.repository.current()
    points = tuple(
        HourlyForecastPoint(API_NOW + timedelta(hours=index), forecast_temperature_c)
        for index in range(25)
    )
    SqlHistoryRecorder(
        initialised_store.application_engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    ).record_forecast(SimpleNamespace(
        date=API_NOW.date(), average_temperature_c=forecast_temperature_c,
        minimum_temperature_c=forecast_temperature_c, maximum_temperature_c=forecast_temperature_c,
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
    configuration_revision, constraints_revision = _seed_valid_preview_inputs(
        initialised_store, forecast_temperature_c=20.0
    )
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
    initialised_store.planning.record_telemetry(
        "salon", "stored_soc_percent", 40.0, API_NOW
    )

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


def _wait_for_preview_job(client, job_id):
    for _ in range(1000):
        response = client.get(f"/api/v1/planning/preview/jobs/{job_id}", headers=AUTH)
        assert response.status_code == 200, response.text
        if response.json()["status"] not in {"queued", "running", "cancelling"}:
            return response.json()
        sleep(0.01)
    raise AssertionError("preview job did not finish")


def _fast_preview_plan(
    store,
    observed_at,
    site,
    *,
    temperature_targets=None,
    progress_callback=None,
    cancellation_probe=None,
):
    from dynamic_thermal_charge.api.routes.planning import _build_automatic_request

    request = _build_automatic_request(
        store,
        observed_at,
        site,
        temperature_targets=temperature_targets,
        progress_callback=progress_callback,
        cancellation_probe=cancellation_probe,
    )
    for step in (
        "inputs", "coverage", "telemetry", "room_model", "solver",
        "solver_phase_1", "solver_phase_2", "safety", "summary",
    ):
        if progress_callback is not None:
            progress_callback(step)
    phase_count = len({heater.priority for heater in request.heaters if heater.enabled}) + 7
    return AutomaticPlan(
        observed_at,
        observed_at + timedelta(hours=int(site["forecast_horizon_hours"])),
        request.slot_minutes,
        (),
        (),
        VALID,
        tuple(0.0 for _ in range(phase_count)),
        input_token(request),
        observed_at,
        diagnostics={"solver": {"time_limited": False}},
    )


def test_preview_resolution_is_persisted_once_for_all_solver_phases(
    initialised_store, monkeypatch,
):
    from dynamic_thermal_charge.api.routes.planning import (
        PREVIEW_STEP_NAMES,
        PreviewJobRunner,
        _temperature_target_payload,
    )
    from dynamic_thermal_charge.persistence.planning import SqlPlanningRepository
    import dynamic_thermal_charge.api.routes.planning as planning_route

    _configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    _config, configuration_revision = initialised_store.repository.current()
    job_id = initialised_store.planning.create_preview_job(
        [],
        temperature_targets=_temperature_target_payload({
            heater.id: heater.temperature_targets for heater in _config.heaters
        }),
        configuration_revision=configuration_revision,
        constraints_revision=constraints_revision,
        requested_at=API_NOW,
        steps=PREVIEW_STEP_NAMES,
    )
    updates = []
    original_update = SqlPlanningRepository.update_preview_step

    def record_update(self, job_id, name, status, detail=None):
        updates.append((name, status))
        return original_update(self, job_id, name, status, detail)

    monkeypatch.setattr(SqlPlanningRepository, "update_preview_step", record_update)
    monkeypatch.setattr(planning_route, "_build_automatic_plan", _fast_preview_plan)
    PreviewJobRunner(lambda: initialised_store, lambda: API_NOW)._run(job_id)

    running = [name for name, status in updates if status == "running"]
    final_job = initialised_store.planning.preview_job(job_id)
    assert final_job["status"] == "completed", final_job
    assert running == [
        "input_validation",
        "aemet_coverage",
        "telemetry",
        "room_model",
        "resolution",
        "safety_validation",
        "operator_summary",
    ], final_job


def test_exact_repeated_preview_creates_a_new_durable_cache_hit(
    client, initialised_store, monkeypatch,
):
    from dynamic_thermal_charge.api.routes.planning import PreviewJobRunner
    import dynamic_thermal_charge.api.routes.planning as planning_route

    _configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    monkeypatch.setattr(planning_route, "_build_automatic_plan", _fast_preview_plan)
    first = client.post(
        "/api/v1/planning/preview/jobs",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )
    assert first.status_code == 200, first.text
    first_final = _wait_for_preview_job(client, first.json()["job_id"])
    assert first_final["status"] == "completed"

    def unexpected_submit(self, job_id):
        raise AssertionError("an exact repeated preview must not launch the solver")

    monkeypatch.setattr(PreviewJobRunner, "submit", unexpected_submit)
    second = client.post(
        "/api/v1/planning/preview/jobs",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )

    assert second.status_code == 200, second.text
    repeated = second.json()
    assert repeated["job_id"] != first_final["job_id"]
    assert repeated["status"] == "completed"
    assert repeated["result"]["token"] == first_final["result"]["token"]
    assert repeated["result"]["diagnostics"]["preview"]["cache_hit"] is True
    assert repeated["result"]["diagnostics"]["preview"]["cache_source_job_id"] == first_final["job_id"]
    assert repeated["result"]["diagnostics"]["preview"]["reuse_seconds"] < 1.0


def test_timed_out_preview_is_never_reused_for_a_new_job(
    client, initialised_store, monkeypatch,
):
    from dynamic_thermal_charge.api.routes.planning import PreviewJobRunner
    import dynamic_thermal_charge.api.routes.planning as planning_route

    configuration_revision, constraints_revision = _seed_valid_preview_inputs(initialised_store)
    monkeypatch.setattr(planning_route, "_build_automatic_plan", _fast_preview_plan)
    first = client.post(
        "/api/v1/planning/preview/jobs",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )
    assert first.status_code == 200, first.text
    first_final = _wait_for_preview_job(client, first.json()["job_id"])
    timed_out = first_final["result"]
    timed_out["violations"].append({
        "requirement": "solver_time_limit",
        "reason": "solver_time_limit",
    })
    initialised_store.planning.finish_preview_job(
        first_final["job_id"], status="completed", result=timed_out,
    )
    submitted = []
    monkeypatch.setattr(
        PreviewJobRunner,
        "submit",
        lambda self, job_id: submitted.append(job_id),
    )

    response = client.post(
        "/api/v1/planning/preview/jobs",
        headers=AUTH,
        json={"expected_revision": constraints_revision},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert submitted == [response.json()["job_id"]]
