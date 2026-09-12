"""Read-only planning projection for the operator panel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from ...persistence.bootstrap import Store
from ...persistence.history import SqlStatusReader
from ...charge_planning import (
    AutomaticPlan,
    AutomaticPlanSlot,
    CONVERGING,
    DEGRADED,
    DemandEstimate,
    HeaterExplanation,
    INVALID,
    RoomEnergyInterval,
    VALID,
    PLANNING_HORIZON_HOURS,
    DeterministicChargeOptimizer,
    PlanningCancelled,
    PlanningInput,
    PlanningViolation,
    group_planning_violations,
    input_token,
    resolve_planning_telemetry,
)
from ...models import TemperatureTarget, validate_temperature_targets
from ...planning_explanation import operator_summary as persisted_operator_summary
from ...planning_explanation import planning_evidence
from ...persistence import ConfigValidationError
from ...scheduler import advance_real
from ...mqtt.topics import resolve_accumulator_topics
from ..dependencies import usable_store
from ..schemas import (
    ERROR_RESPONSES,
    AllocationSummary,
    HourlyForecastPointView,
    PlanningForecastView,
    PlanningHeaterView,
    PlanningPlanView,
    PlanningResponse,
    PlanningSlotView,
    PlanningTimelineSlotView,
    READ_RESPONSES,
    ChargeTelemetryView,
    PlanningActivateRequest,
    PlanningDeficitView,
    PlanningPreviewRequest,
    PlanningPreviewResponse,
    HeaterChargeConfigRequest,
    PlanningSiteConfigRequest,
    PlanningSiteConfigResponse,
    PlanningCheckView,
    PlanningPreviewJobResponse,
    TemperatureTargetRequest,
    TemperatureTargetView,
)
from ..errors import not_found
from ...persistence.mapping import (
    format_temperature_target_end_time,
    parse_temperature_target_end_time,
    parse_time,
)
from ..read_model import automatic_window, forecast_cycle_context, real_before, wall_clock_end


router = APIRouter()
logger = logging.getLogger(__name__)

PREVIEW_STEP_NAMES = (
    "input_validation", "telemetry", "aemet_coverage", "room_model",
    "resolution", "safety_validation", "operator_summary",
)


def _planning_topics(heater, charge_config):
    configured = charge_config.get(heater.id, {})
    return resolve_accumulator_topics(
        heater.id,
        damper_topic=configured.get("damper_topic"),
        setpoint_topic=configured.get("setpoint_topic"),
    )


class PreviewJobRunner:
    """One process-local worker for durable, cooperative preview jobs."""

    def __init__(self, store_factory, clock) -> None:
        self._store_factory = store_factory
        self._clock = clock
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview-job")

    def submit(self, job_id: str) -> None:
        self._executor.submit(self._run, job_id)

    def _run(self, job_id: str) -> None:
        store = self._store_factory()
        repository = store.planning
        if not repository.start_preview_job(job_id):
            return
        try:
            job = repository.preview_job(job_id)
            if job is None:
                return
            if repository.preview_job_cancel_requested(job_id):
                repository.finish_preview_job(job_id, status="cancelled", error_code="cancelled", error_detail="La cancelación se solicitó antes de iniciar el cálculo.")
                return
            site = repository.site()
            config, configuration_revision = store.repository.current()
            if configuration_revision != job["configuration_revision"] or site["revision"] != job["constraints_revision"]:
                repository.finish_preview_job(job_id, status="error", error_code="stale_input", error_detail="La configuración o los objetivos térmicos cambiaron antes de iniciar el cálculo.")
                return
            raw_targets = job["request"].get("temperature_targets")
            temperature_targets = _resolve_temperature_targets(
                store,
                None
                if raw_targets is None
                else [TemperatureTargetRequest.model_validate(item) for item in raw_targets],
            )

            def progress(step: str) -> None:
                mapped = {
                    "inputs": "input_validation", "coverage": "aemet_coverage",
                    "telemetry": "telemetry", "room_model": "room_model",
                    "safety": "safety_validation",
                    "summary": "operator_summary",
                }.get(step, "resolution" if step.startswith("solver_phase_") else None)
                if mapped is not None:
                    repository.update_preview_step(job_id, mapped, "running")

            plan = _build_automatic_plan(
                store, self._clock(), site,
                temperature_targets=temperature_targets,
                progress_callback=progress,
                cancellation_probe=lambda: repository.preview_job_cancel_requested(job_id),
            )
            forecast = SqlStatusReader(
                store.application_engine or store.engine,
                store.repository.installation_id(),
                store.location,
            ).latest_forecast(self._clock())
            payload = _preview_response(
                plan,
                temperature_targets,
                site=site,
                forecast=forecast,
                forecast_status=forecast_cycle_context(repository),
                timezone_name=(config.schedule.timezone if config.schedule is not None else "UTC"),
            ).model_dump(mode="json")
            repository.finish_preview_job(job_id, status="completed", result=payload)
            if plan.status == "INVALID" and plan.violations:
                reason = plan.violations[0].reason.split(":", 1)[0]
                failed_step = {
                    "missing_aemet_coverage": "aemet_coverage",
                    "forecast_not_eligible": "aemet_coverage",
                    "missing_required_state": "telemetry",
                    "invalid_configuration": "input_validation",
                }.get(reason, "resolution" if reason.startswith("solver") else None)
                if failed_step is not None:
                    repository.update_preview_step(job_id, failed_step, "error", detail=reason)
            logger.info("Planning preview job completed: job_id=%s status=%s", job_id, plan.status)
        except PlanningCancelled:
            repository.finish_preview_job(job_id, status="cancelled", error_code="cancelled", error_detail="La vista previa se canceló al finalizar la fase activa del solver.")
            logger.info("Planning preview job cancelled: job_id=%s", job_id)
        except Exception as exc:  # the durable job contains the operator-safe detail
            logger.exception("Planning preview job failed: job_id=%s", job_id)
            repository.finish_preview_job(job_id, status="error", error_code="preview_failed", error_detail=str(exc)[:512])


def _job_runner(request: Request) -> PreviewJobRunner:
    runner = getattr(request.app.state, "preview_job_runner", None)
    if runner is None:
        runner = PreviewJobRunner(request.app.state.store_factory, request.app.state.clock)
        request.app.state.preview_job_runner = runner
    return runner


@router.get(
    "/planning",
    response_model=PlanningResponse,
    responses=READ_RESPONSES,
    summary="Current or next accepted charge plan",
)
def get_planning(
    request: Request,
    store: Store = Depends(usable_store),
) -> PlanningResponse:
    observed_at = request.app.state.clock()
    config, _revision = store.repository.current()
    reader = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    latest_forecast = reader.latest_forecast(observed_at)
    cycle_status = forecast_cycle_context(store.planning)
    planning_site = store.planning.site()
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    charge_config = store.planning.heater_charge_config()
    heaters = [
        PlanningHeaterView(
            id=heater.id,
            name=heater.name,
            power_w=heater.power_w,
            capacity_kwh=heater.capacity_kwh,
            priority=heater.priority,
            enabled=heater.enabled,
            damper_topic=_planning_topics(heater, charge_config).discharge,
            setpoint_topic=_planning_topics(heater, charge_config).setpoint,
        )
        for heater in config.heaters
    ]
    automatic = store.planning.active_plan()
    if automatic is not None:
        response = _automatic_planning_response(
            automatic,
            observed_at=observed_at,
            config=config,
            revision=_revision,
            heaters=heaters,
            latest_forecast=latest_forecast,
            cycle_status=cycle_status,
            horizon_hours=int(planning_site["forecast_horizon_hours"]),
            planning_window_hours=int(planning_site["planning_window_hours"]),
            max_total_power_w=int(planning_site.get("contracted_power_w", config.site.max_total_power_w)),
            timezone_name=timezone_name,
        )
        return _enrich(response, store, observed_at)

    latest_automatic = (
        store.planning.latest_plan()
        if hasattr(store.planning, "latest_plan")
        else None
    )
    if latest_automatic is not None and _canonical_plan_status(latest_automatic["status"]) == INVALID:
        response = PlanningResponse(
            observed_at=observed_at,
            timezone=timezone_name,
            max_total_power_w=int(
                planning_site.get("contracted_power_w", config.site.max_total_power_w)
            ),
            heaters=heaters,
            absence_reason="invalid_automatic_plan",
            forecast=_forecast_view(latest_forecast),
            plan_status="INVALID",
            deficits=_grouped_deficit_views(
                _plan_violations(latest_automatic),
                slot_minutes=latest_automatic.get("slot_minutes"),
            ),
            convergence_by_heater=latest_automatic.get("convergence_by_heater", {}),
            convergence_at=latest_automatic.get("convergence_at"),
            guaranteed_until=latest_automatic.get("guaranteed_until"),
            horizon_start=latest_automatic["horizon_start"],
            horizon_end=latest_automatic["horizon_end"],
            forecast_status=cycle_status.get("forecast_status"),
            forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
            forecast_last_error=cycle_status.get("forecast_last_error"),
            forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
            forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
            forecast_stale=cycle_status.get("forecast_stale"),
        )
        return _enrich(response, store, observed_at)

    if latest_automatic is not None:
        response = PlanningResponse(
            observed_at=observed_at,
            timezone=timezone_name,
            max_total_power_w=int(
                planning_site.get("contracted_power_w", config.site.max_total_power_w)
            ),
            heaters=heaters,
            absence_reason="no_active_automatic_plan",
            forecast=_forecast_view(latest_forecast),
            plan_status=_canonical_plan_status(latest_automatic["status"]),
            deficits=_grouped_deficit_views(
                _plan_violations(latest_automatic),
                slot_minutes=latest_automatic.get("slot_minutes"),
            ),
            convergence_by_heater=latest_automatic.get("convergence_by_heater", {}),
            convergence_at=latest_automatic.get("convergence_at"),
            guaranteed_until=latest_automatic.get("guaranteed_until"),
            horizon_start=latest_automatic["horizon_start"],
            horizon_end=latest_automatic["horizon_end"],
            forecast_status=cycle_status.get("forecast_status"),
            forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
            forecast_last_error=cycle_status.get("forecast_last_error"),
            forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
            forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
            forecast_stale=cycle_status.get("forecast_stale"),
        )
        return _enrich(response, store, observed_at)

    snapshot = reader.planning(observed_at)
    if snapshot is None:
        response = PlanningResponse(
            observed_at=observed_at,
            timezone=timezone_name,
            max_total_power_w=int(planning_site.get("contracted_power_w", config.site.max_total_power_w)),
            heaters=heaters,
            absence_reason="no_current_or_next_plan",
            forecast=_forecast_view(latest_forecast),
            forecast_status=cycle_status.get("forecast_status"),
            forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
            forecast_last_error=cycle_status.get("forecast_last_error"),
            forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
            forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
            forecast_stale=cycle_status.get("forecast_stale"),
        )
        return _enrich(response, store, observed_at)

    # The visible forecast must reflect the newest stored retrieval, even when
    # the accepted plan was calculated with an older forecast.
    forecast = latest_forecast or snapshot["forecast"]
    forecast_view = _forecast_view(forecast)

    power_by_id = {heater.id: heater.power_w for heater in config.heaters}
    assigned: dict[tuple[datetime, datetime], list[str]] = {}
    stored_temperatures: dict[tuple[datetime, datetime], tuple[float | None, bool]] = {}
    for slot in snapshot["slots"]:
        key = (slot["slot_start"], slot["slot_end"])
        assigned.setdefault(key, []).append(slot["heater_id"])
        stored_temperatures[key] = (
            slot["temperature_c"], slot["temperature_interpolated"]
        )

    plan_data = snapshot["plan"]
    slot_delta = timedelta(minutes=plan_data["slot_minutes"])
    slots: list[PlanningSlotView] = []
    horizon_start = plan_data["window_start"]
    local_horizon_start = (
        horizon_start.astimezone(ZoneInfo(timezone_name))
        if horizon_start.tzinfo is not None
        else horizon_start
    )
    horizon_end = wall_clock_end(
        local_horizon_start, int(planning_site["forecast_horizon_hours"])
    )
    configured_window_end = wall_clock_end(
        local_horizon_start, int(planning_site["planning_window_hours"])
    )
    visible_window_end = (
        horizon_end if real_before(horizon_end, configured_window_end)
        else configured_window_end
    )
    cursor = horizon_start
    timeline_slots: list[PlanningSlotView] = []
    while real_before(cursor, visible_window_end):
        candidate_end = advance_real(cursor, plan_data["slot_minutes"])
        end = (
            visible_window_end
            if real_before(visible_window_end, candidate_end)
            else candidate_end
        )
        key = (cursor, end)
        heater_ids = sorted(assigned.get(key, []))
        temperature, interpolated = stored_temperatures.get(
            key, _temperature_for_interval(forecast, cursor, end)
        )
        slots.append(
            PlanningSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
            )
        )
        cursor = end

    cursor = horizon_start
    while real_before(cursor, horizon_end):
        candidate_end = advance_real(cursor, plan_data["slot_minutes"])
        end = horizon_end if real_before(horizon_end, candidate_end) else candidate_end
        key = (cursor, end)
        heater_ids = sorted(assigned.get(key, []))
        temperature, interpolated = stored_temperatures.get(
            key, _temperature_for_interval(forecast, cursor, end)
        )
        timeline_slots.append(
            PlanningSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
            )
        )
        cursor = end

    timeline = _build_timeline(
        config.heaters,
        power_by_id,
        _ordered_plan_slots(timeline_slots),
        forecast,
        horizon_start,
        horizon_end,
        slot_delta,
    )

    response = PlanningResponse(
        observed_at=observed_at,
        timezone=timezone_name,
        max_total_power_w=int(planning_site.get("contracted_power_w", config.site.max_total_power_w)),
        plan=PlanningPlanView(
            **{
                **plan_data,
                "source": "legacy",
                "window_start": horizon_start,
                "window_end": visible_window_end,
            },
            slots=slots,
        ),
        forecast=forecast_view,
        allocations=[AllocationSummary(**item) for item in snapshot["allocations"]],
        heaters=heaters,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        timeline=timeline,
        forecast_status=cycle_status.get("forecast_status"),
        forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
        forecast_last_error=cycle_status.get("forecast_last_error"),
        forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
        forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
        forecast_stale=cycle_status.get("forecast_stale"),
    )
    return _enrich(response, store, observed_at)


@router.post("/planning/preview", response_model=PlanningPreviewResponse, responses=ERROR_RESPONSES)
def preview_planning(
    request: PlanningPreviewRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningPreviewResponse:
    logger.info(
        "Planning preview requested: temperature_targets=%d",
        len(request.temperature_targets or []),
    )
    site = store.planning.site()
    if request.expected_revision is not None and request.expected_revision != site["revision"]:
        raise ConfigValidationError("planning configuration changed; recalculate before saving")
    temperature_targets = _resolve_temperature_targets(store, request.temperature_targets)
    config, _revision = store.repository.current()
    plan = _build_automatic_plan(
        store, app_request.app.state.clock(), site,
        temperature_targets=temperature_targets,
    )
    if plan.status in {VALID, CONVERGING}:
        preview_cache = getattr(app_request.app.state, "preview_plan_cache", None)
        if preview_cache is None:
            preview_cache = {}
            app_request.app.state.preview_plan_cache = preview_cache
        preview_cache[plan.input_token] = plan
        while len(preview_cache) > 8:
            preview_cache.pop(next(iter(preview_cache)))
    logger.info("Planning preview completed: status=%s violations=%d", plan.status, len(plan.violations))
    forecast = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    ).latest_forecast(app_request.app.state.clock())
    return _preview_response(
        plan,
        temperature_targets,
        site=site,
        forecast=forecast,
        forecast_status=forecast_cycle_context(store.planning),
        timezone_name=config.schedule.timezone if config.schedule is not None else "UTC",
    )


@router.post("/planning/preview/jobs", response_model=PlanningPreviewJobResponse, responses=ERROR_RESPONSES)
def start_preview_job(
    request: PlanningPreviewRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningPreviewJobResponse:
    site = store.planning.site()
    if request.expected_revision is not None and request.expected_revision != site["revision"]:
        raise ConfigValidationError("planning configuration changed; recalculate before saving")
    temperature_targets = _resolve_temperature_targets(store, request.temperature_targets)
    _config, configuration_revision = store.repository.current()
    job_id = store.planning.create_preview_job(
        [],
        temperature_targets=_temperature_target_payload(temperature_targets),
        configuration_revision=configuration_revision,
        constraints_revision=int(site["revision"]),
        requested_at=app_request.app.state.clock(),
        steps=PREVIEW_STEP_NAMES,
    )
    _job_runner(app_request).submit(job_id)
    return _job_response(
        store.planning.preview_job(job_id),
        site=site,
    )


@router.get("/planning/preview/jobs/{job_id}", response_model=PlanningPreviewJobResponse, responses=ERROR_RESPONSES)
def get_preview_job(job_id: str, store: Store = Depends(usable_store)) -> PlanningPreviewJobResponse:
    job = store.planning.preview_job(job_id)
    if job is None:
        raise not_found("preview job does not exist", field="job_id")
    return _job_response(
        job,
        site=store.planning.site(),
    )


@router.post("/planning/preview/jobs/{job_id}/cancel", response_model=PlanningPreviewJobResponse, responses=ERROR_RESPONSES)
def cancel_preview_job(job_id: str, store: Store = Depends(usable_store)) -> PlanningPreviewJobResponse:
    job = store.planning.request_preview_cancel(job_id)
    if job is None:
        raise not_found("preview job does not exist", field="job_id")
    return _job_response(
        job,
        site=store.planning.site(),
    )


@router.delete("/planning/preview/jobs/{job_id}", response_model=PlanningPreviewJobResponse, responses=ERROR_RESPONSES, include_in_schema=False)
def delete_preview_job(job_id: str, store: Store = Depends(usable_store)) -> PlanningPreviewJobResponse:
    return cancel_preview_job(job_id, store)


@router.post("/planning/activate", response_model=PlanningPreviewResponse, responses=ERROR_RESPONSES)
def activate_planning(
    request: PlanningActivateRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningPreviewResponse:
    site = store.planning.site()
    if request.expected_revision != site["revision"]:
        raise ConfigValidationError("temperature targets changed; recalculate before saving")
    temperature_targets = _resolve_temperature_targets(store, request.temperature_targets)
    observed_at = app_request.app.state.clock()
    planning_request = _build_automatic_request(
        store, observed_at, site, temperature_targets=temperature_targets
    )
    if input_token(planning_request) != request.token:
        raise ConfigValidationError("the preview inputs changed; recalculate before activating")
    _config, configuration_revision = store.repository.current()
    preview_cache = getattr(app_request.app.state, "preview_plan_cache", {})
    plan = preview_cache.pop(request.token, None)
    if plan is not None and plan.input_token != input_token(planning_request):
        plan = None
    if plan is None:
        plan = _cached_preview_plan(
            store,
            planning_request,
            configuration_revision=configuration_revision,
            constraints_revision=int(site["revision"]),
        )
    if plan is None:
        plan = DeterministicChargeOptimizer().build(planning_request)
    if plan.status not in {VALID, CONVERGING}:
        raise ConfigValidationError(
            "only VALID or CONVERGING plans can be activated",
            field="planning",
        )
    new_revision = (
        store.planning.replace_all_temperature_targets(
            temperature_targets,
            request.expected_revision,
        )
        if temperature_targets
        else int(site["revision"])
    )
    store.planning.save_plan(
        plan,
        configuration_revision=configuration_revision,
        constraints_revision=new_revision,
        reason="activated",
        active=True,
        evidence=planning_evidence(
            planning_request,
            planning_site=site,
            forecast_status=forecast_cycle_context(store.planning),
        ),
    )
    forecast = SqlStatusReader(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    ).latest_forecast(observed_at)
    return _preview_response(
        plan,
        temperature_targets,
        site=site,
        forecast=forecast,
        forecast_status=forecast_cycle_context(store.planning),
        timezone_name=_config.schedule.timezone if _config.schedule is not None else "UTC",
    )


@router.get(
    "/planning/config",
    response_model=PlanningSiteConfigResponse,
    responses=READ_RESPONSES,
    summary="Automatic planning site parameters",
)
def get_planning_config(
    store: Store = Depends(usable_store),
) -> PlanningSiteConfigResponse:
    return PlanningSiteConfigResponse.model_validate(store.planning.site())


@router.patch("/planning/config", response_model=PlanningSiteConfigResponse, responses=ERROR_RESPONSES)
def update_planning_config(
    payload: PlanningSiteConfigRequest,
    store: Store = Depends(usable_store),
) -> PlanningSiteConfigResponse:
    values = payload.model_dump(exclude={"expected_revision"})
    store.planning.update_site(values, payload.expected_revision)
    return PlanningSiteConfigResponse.model_validate(store.planning.site())


@router.patch("/planning/heaters/{heater_id}", response_model=PlanningResponse, responses=ERROR_RESPONSES)
def update_heater_planning(
    heater_id: str,
    payload: HeaterChargeConfigRequest,
    app_request: Request,
    store: Store = Depends(usable_store),
) -> PlanningResponse:
    config, _revision = store.repository.current()
    if heater_id not in {heater.id for heater in config.heaters}:
        raise ConfigValidationError("heater does not exist", field="heater_id", heater_id=heater_id)
    store.planning.update_heater_charge_config(
        heater_id, payload.model_dump(exclude_unset=True)
    )
    # Re-read through the public projection so the response cannot contain a
    # partially applied topic configuration.
    return get_planning(app_request, store)


def _violation_payload(item: PlanningViolation | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    return dict(item.__dict__)


def _canonical_plan_status(value: Any) -> str:
    raw = str(value)
    return {
        VALID: VALID,
        CONVERGING: CONVERGING,
        DEGRADED: DEGRADED,
        INVALID: INVALID,
        "FEASIBLE": VALID,
        "DEFICIT": DEGRADED,
        "BEST_EFFORT": DEGRADED,
        "PREVIEW": INVALID,
    }.get(raw.upper(), raw)


def _plan_violations(plan: dict[str, Any]) -> list[dict[str, Any]] | tuple:
    """Read raw observations while accepting older persistence payloads."""
    violations = plan.get("violations")
    if violations is not None:
        return violations
    return plan.get("deficits", [])


def _deficit_view(item: PlanningViolation | dict[str, Any]) -> PlanningDeficitView:
    payload = _violation_payload(item)
    if (
        payload.get("requirement") == "temperature_comfort"
        and payload.get("achievable_value") is not None
        and payload.get("shortfall") is not None
    ):
        payload.setdefault(
            "target_temperature_c",
            float(payload["achievable_value"]) + float(payload["shortfall"]),
        )
        payload.setdefault("projected_temperature_c", payload["achievable_value"])
        payload.setdefault("shortfall_c", payload["shortfall"])
    return PlanningDeficitView.model_validate(payload)


def _raw_deficit_views(
    violations: list[PlanningViolation | dict[str, Any]] | tuple[PlanningViolation | dict[str, Any], ...],
) -> list[PlanningDeficitView]:
    return [_deficit_view(item) for item in violations]


def _grouped_deficit_views(
    violations: list[PlanningViolation | dict[str, Any]] | tuple[PlanningViolation | dict[str, Any], ...],
    *,
    slot_minutes: int | None = None,
) -> list[PlanningDeficitView]:
    return [
        _deficit_view(item)
        for item in group_planning_violations(violations, slot_minutes=slot_minutes)
    ]


def _automatic_planning_response(
    automatic: dict,
    *,
    observed_at: datetime,
    config,
    revision: int,
    heaters: list[PlanningHeaterView],
    latest_forecast,
    cycle_status: dict,
    horizon_hours: int,
    planning_window_hours: int,
    max_total_power_w: int,
    timezone_name: str,
) -> PlanningResponse:
    power_by_id = {heater.id: heater.power_w for heater in config.heaters}
    slot_delta = timedelta(minutes=automatic["slot_minutes"])
    horizon_start = automatic["horizon_start"]
    horizon_end = automatic["horizon_end"]
    automatic_slots = _enrich_boundary_slots(
        list(automatic["slots"]), automatic.get("demand", [])
    )
    _window_start, window_end = automatic_window(
        automatic, planning_window_hours, timezone_name
    )
    automatic_plan = PlanningPlanView(
        id=automatic["id"],
        source="automatic",
        window_start=automatic["horizon_start"],
        window_end=window_end,
        slot_minutes=automatic["slot_minutes"],
        installation_revision=automatic["configuration_revision"],
        created_at=automatic["created_at"],
        slots=[
            PlanningSlotView(
                start=item["start"],
                end=item["end"],
                heater_ids=item["heater_ids"],
                total_power_w=item["power_w"],
                temperature_c=item["outdoor_temperature_c"],
                temperature_interpolated=False,
                stored_energy_kwh_by_heater=item.get("stored_energy_kwh", {}),
                stored_energy_next_kwh_by_heater=item.get("stored_energy_next_kwh", {}),
                indoor_temperature_c_by_heater=item.get("indoor_temperature_c", {}),
                indoor_temperature_next_c_by_heater=item.get("indoor_temperature_next_c", {}),
                target_temperature_c_by_heater=item.get("target_temperature_c", {}),
                heat_delivered_kwh_by_heater=item.get("heat_delivered_kwh", {}),
                thermal_loss_kwh_by_heater=item.get("thermal_loss_kwh", {}),
                temperature_shortfall_start_c_by_heater=item.get("temperature_shortfall_start_c", {}),
                temperature_shortfall_c_by_heater=item.get("temperature_shortfall_c", {}),
                charge_energy_kwh_by_heater=item.get("charge_energy_kwh", {}),
                heat_delivery_limit_kwh_by_heater=item.get("heat_delivery_limit_kwh", {}),
            )
            for item in automatic_slots
            if real_before(item["start"], window_end)
        ],
    )
    return PlanningResponse(
        observed_at=observed_at,
        timezone=timezone_name,
        max_total_power_w=max_total_power_w,
        heaters=heaters,
        forecast=_forecast_view(latest_forecast),
        forecast_status=cycle_status.get("forecast_status"),
        forecast_last_attempt_at=cycle_status.get("forecast_last_attempt_at"),
        forecast_last_error=cycle_status.get("forecast_last_error"),
        forecast_next_run_at=cycle_status.get("forecast_next_run_at"),
        plan=automatic_plan,
        plan_status=_canonical_plan_status(automatic["status"]),
        deficits=_grouped_deficit_views(
            _plan_violations(automatic), slot_minutes=automatic.get("slot_minutes")
        ),
        convergence_by_heater=automatic.get("convergence_by_heater", {}),
        convergence_at=automatic.get("convergence_at"),
        guaranteed_until=automatic.get("guaranteed_until"),
        absence_reason=(
            "invalid_automatic_plan"
            if _canonical_plan_status(automatic["status"]) == INVALID
            else None
        ),
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        forecast_next_run_kind=cycle_status.get("forecast_next_run_kind"),
        forecast_stale=cycle_status.get("forecast_stale"),
        timeline=_build_timeline(
            config.heaters,
            power_by_id,
            automatic_slots,
            latest_forecast,
            horizon_start,
            horizon_end,
            slot_delta,
        ),
    )


def _enrich(response: PlanningResponse, store: Store, observed_at: datetime) -> PlanningResponse:
    planning = store.planning
    config, _revision = store.repository.current()
    capacity_by_id = {heater.id: heater.capacity_kwh for heater in config.heaters}
    max_age_seconds = config.site.indoor_max_age_minutes * 60
    telemetry = planning.telemetry()
    views = []
    for heater in response.heaters:
        value = telemetry.get(heater.id)
        if value is None:
            views.append(ChargeTelemetryView(heater_id=heater.id, missing_fields=["indoor_temperature_c", "stored_soc_percent"]))
            continue
        ages = [
            (observed_at - stamp).total_seconds()
            for stamp in (value.indoor_received_at, value.stored_soc_received_at)
            if stamp is not None
        ]
        missing = [field for field, item in (("indoor_temperature_c", value.indoor_temperature_c), ("stored_soc_percent", value.stored_soc_percent)) if item is None]
        oldest = max(ages, default=None)
        stale = bool(
            missing
            or oldest is None
            or oldest > max_age_seconds
            or any(age < 0 for age in ages)
        )
        views.append(ChargeTelemetryView(
            heater_id=heater.id,
            indoor_temperature_c=value.indoor_temperature_c,
            stored_soc_percent=value.stored_soc_percent,
            indoor_received_at=value.indoor_received_at,
            stored_soc_received_at=value.stored_soc_received_at,
            state="telemetry_stale" if stale else "ready",
            missing_fields=missing,
            oldest_age_seconds=oldest,
            stored_energy_kwh=(
                None
                if value.stored_soc_percent is None
                else value.stored_soc_percent / 100 * capacity_by_id.get(heater.id, 0)
            ),
        ))
    active = planning.active_plan()
    latest = planning.latest_plan() if hasattr(planning, "latest_plan") else None
    diagnostic = (
        latest
        if latest is not None
        and _canonical_plan_status(latest["status"]) == DEGRADED
        and (
            active is None
            or latest["created_at"] > active["created_at"]
        )
        else None
    )
    response.temperature_targets = [
        TemperatureTargetView(
            id=target.id,
            heater_id=heater.id,
            target_temperature_c=target.target_temperature_c,
            start_time=target.start_time.strftime("%H:%M"),
            end_time=format_temperature_target_end_time(target.start_time, target.end_time),
            weekdays=list(target.weekdays),
            enabled=target.enabled,
        )
        for heater in store.repository.current()[0].heaters
        for target in heater.temperature_targets
    ]
    response.telemetry = views
    if active is not None or diagnostic is not None:
        projection = diagnostic or active
        assert projection is not None
        response.plan_status = _canonical_plan_status(projection["status"])
        response.deficits = _grouped_deficit_views(
            _plan_violations(projection), slot_minutes=projection.get("slot_minutes")
        )
        response.convergence_by_heater = projection.get("convergence_by_heater", {})
        response.convergence_at = projection.get("convergence_at")
        response.guaranteed_until = projection.get("guaranteed_until")
        response.preview_token = active["input_token"] if active is not None else None
    site = planning.site()
    response.temperature_targets_revision = site["revision"]
    response.base_load_w = int(site.get("base_load_w", 0))
    response.max_heating_power_w = int(site.get("max_heating_power_w", response.max_total_power_w))
    latest_job = planning.latest_preview_job()
    response.preview_job = (
        _job_response(
            latest_job,
            site=site,
        )
        if latest_job is not None
        else None
    )
    return response


def _parse_temperature_targets(
    items: list[TemperatureTargetRequest],
) -> dict[str, tuple[TemperatureTarget, ...]]:
    result: dict[str, list[TemperatureTarget]] = {}

    for item in items:
        try:
            target = TemperatureTarget(
                target_temperature_c=item.target_temperature_c,
                start_time=parse_time(item.start_time, "start_time"),
                end_time=parse_temperature_target_end_time(item.end_time, "end_time"),
                weekdays=tuple(sorted(set(item.weekdays))),
                enabled=item.enabled,
            )
        except (ValueError, TypeError) as exc:
            raise ConfigValidationError(
                str(exc), field="temperature_targets", heater_id=item.heater_id
            ) from exc
        if not item.heater_id:
            raise ConfigValidationError(
                "temperature target requires a heater id", field="heater_id"
            )
        result.setdefault(item.heater_id, []).append(target)
    normalized: dict[str, tuple[TemperatureTarget, ...]] = {}
    for heater_id, targets in result.items():
        normalized_targets = tuple(
            sorted(
                targets,
                key=lambda target: (
                    target.start_time,
                    target.end_time,
                    target.weekdays,
                ),
            )
        )
        try:
            validate_temperature_targets(normalized_targets)
        except ValueError as exc:
            raise ConfigValidationError(
                str(exc), field="temperature_targets", heater_id=heater_id
            ) from exc
        normalized[heater_id] = normalized_targets
    return normalized


def _resolve_temperature_targets(
    store: Store,
    items: list[TemperatureTargetRequest] | None,
) -> dict[str, tuple[TemperatureTarget, ...]]:
    """Resolve an omitted schedule separately from an explicitly empty one."""
    if items is None:
        return _configured_temperature_targets(store)
    parsed = _parse_temperature_targets(items)
    _validate_temperature_target_heaters(store, parsed)
    config, _revision = store.repository.current()
    return {
        heater.id: tuple(parsed.get(heater.id, ()))
        for heater in config.heaters
    }


def _build_automatic_plan(
    store: Store,
    observed_at: datetime,
    site: dict[str, int | float],
    *,
    temperature_targets: dict[str, tuple[TemperatureTarget, ...]] | None = None,
    progress_callback=None,
    cancellation_probe=None,
):
    return DeterministicChargeOptimizer().build(_build_automatic_request(
        store,
        observed_at,
        site,
        temperature_targets=temperature_targets,
        progress_callback=progress_callback,
        cancellation_probe=cancellation_probe,
    ))


def _build_automatic_request(
    store: Store,
    observed_at: datetime,
    site: dict[str, int | float],
    *,
    temperature_targets: dict[str, tuple[TemperatureTarget, ...]] | None = None,
    progress_callback=None,
    cancellation_probe=None,
) -> PlanningInput:
    config, _revision = store.repository.current()
    known_heaters = {heater.id for heater in config.heaters}
    if temperature_targets is not None:
        for heater_id in temperature_targets:
            if heater_id not in known_heaters:
                raise ConfigValidationError("heater does not exist", field="heater_id", heater_id=heater_id)
    timezone_name = config.schedule.timezone if config.schedule is not None else "UTC"
    mqtt = (
        store.system_configuration.current().configuration.mqtt
        if store.system_configuration is not None
        else None
    )
    persisted = (
        {}
        if mqtt is not None and not mqtt.enabled
        else store.planning.telemetry()
    )
    request = PlanningInput(
        heaters=config.heaters,
        telemetry=resolve_planning_telemetry(
            config.heaters,
            persisted,
            observed_at,
            mqtt=mqtt,
        ),
        constraints=(),
        temperature_targets=(
            temperature_targets
            if temperature_targets is not None
            else {
                heater.id: heater.temperature_targets for heater in config.heaters
            }
        ),
        forecast=store.planning.latest_forecast(observed_at),
        horizon_start=observed_at,
        horizon_hours=int(site["forecast_horizon_hours"]),
        slot_minutes=config.site.slot_minutes,
        max_total_power_w=int(site["contracted_power_w"]),
        base_load_w=int(site.get("base_load_w", 0)),
        max_heating_power_w=int(site["max_heating_power_w"]),
        solver_time_limit_seconds=int(site["solver_time_limit_seconds"]),
        forecast_automatic_eligible=store.planning.latest_forecast_automatic_eligible(),
        generated_at=observed_at,
        timezone_name=timezone_name,
        progress_callback=progress_callback,
        cancellation_probe=cancellation_probe,
        room_energy_model=True,
    )
    return request


def _cached_preview_plan(
    store: Store,
    request: PlanningInput,
    *,
    configuration_revision: int,
    constraints_revision: int,
) -> AutomaticPlan | None:
    finder = getattr(store.planning, "latest_completed_preview_job", None)
    if finder is None:
        return None
    job = finder(
        configuration_revision=configuration_revision,
        constraints_revision=constraints_revision,
        temperature_targets=_temperature_target_payload(request.temperature_targets),
    )
    if job is None:
        return None
    result = job.get("result")
    if not isinstance(result, dict) or result.get("token") != input_token(request):
        return None
    try:
        plan = _automatic_plan_from_preview_payload(result)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        logger.debug("Ignoring unusable cached planning preview: job_id=%s error=%s", job.get("id"), exc)
        return None
    if plan.input_token != input_token(request):
        return None
    logger.info("Reusing completed planning preview: job_id=%s token=%s", job["id"], plan.input_token)
    return plan


def _temperature_target_payload(
    targets: dict[str, tuple[TemperatureTarget, ...]],
) -> list[dict[str, Any]]:
    return [
        {
            "heater_id": heater_id,
            "target_temperature_c": target.target_temperature_c,
            "start_time": target.start_time.strftime("%H:%M"),
            "end_time": format_temperature_target_end_time(target.start_time, target.end_time),
            "weekdays": list(target.weekdays),
            "enabled": target.enabled,
        }
        for heater_id, items in sorted(targets.items())
        for target in items
    ]


def _automatic_plan_from_preview_payload(payload: dict[str, Any]) -> AutomaticPlan:
    """Convert a durable public preview result back to the domain value."""
    slots = tuple(
        AutomaticPlanSlot(
            _preview_datetime(item["start"]),
            _preview_datetime(item["end"]),
            tuple(str(value) for value in item.get("heater_ids", [])),
            int(item.get("power_w", 0)),
            _preview_float_map(item.get("stored_charge_percent")),
            _preview_float_map(item.get("required_charge_percent")),
            _preview_optional_float(item.get("outdoor_temperature_c")),
            _preview_float_map(item.get("indoor_temperature_c")),
            _preview_float_map(item.get("initial_soc_percent")),
            _preview_float_map(item.get("demand_kwh")),
            _preview_int_map(item.get("heater_power_w")),
            _preview_float_map(item.get("stored_energy_kwh")),
            _preview_float_map(item.get("target_temperature_c")),
            _preview_float_map(item.get("heat_delivered_kwh")),
            _preview_float_map(item.get("thermal_loss_kwh")),
            _preview_float_map(item.get("temperature_shortfall_c")),
            _preview_float_map(item.get("charge_energy_kwh")),
            _preview_float_map(item.get("stored_energy_next_kwh")),
            _preview_float_map(item.get("indoor_temperature_next_c")),
            _preview_float_map(item.get("temperature_shortfall_start_c")),
            _preview_float_map(item.get("heat_delivery_limit_kwh")),
        )
        for item in _preview_dict_list(payload.get("slots"))
    )
    violation_payload = payload.get("violations", payload.get("deficits", []))
    violations = tuple(
        PlanningViolation(
            item.get("heater_id"),
            str(item.get("requirement", "")),
            _preview_optional_float(item.get("achievable_value")),
            _preview_optional_float(item.get("shortfall")),
            _preview_optional_datetime(item.get("at")),
            str(item["reason"]),
            _preview_optional_datetime(item.get("target_window_start")),
            _preview_optional_datetime(item.get("target_window_end")),
        )
        for item in _preview_dict_list(violation_payload)
    )
    explanations = tuple(
        HeaterExplanation(
            str(item["heater_id"]),
            float(item.get("actual_soc_percent", 0.0)),
            float(item.get("total_demand_kwh", item.get("total_heat_delivered_kwh", 0.0))),
            float(item.get("demand_factor", 1.0)),
            float(item.get("reserve_percent", 0.0)),
            _preview_optional_datetime(item.get("next_constraint_at")),
            tuple(
                (_preview_datetime(period[0]), _preview_datetime(period[1]))
                for period in item.get("charge_periods", [])
            ),
            float(item.get("capacity_kwh", 0.0)),
            _preview_optional_float(item.get("initial_indoor_temperature_c")),
            _preview_optional_float(item.get("final_indoor_temperature_c")),
            float(item.get("total_heat_delivered_kwh", 0.0)),
            float(item.get("total_thermal_loss_kwh", 0.0)),
            float(item.get("maximum_temperature_shortfall_c", 0.0)),
            _preview_optional_float(item.get("initial_stored_energy_kwh")),
            _preview_optional_float(item.get("final_stored_energy_kwh")),
            _preview_optional_float(item.get("total_charge_energy_kwh")),
            _preview_optional_float(item.get("forecast_contribution_kwh")),
            _preview_optional_float(item.get("terminal_surplus_energy_kwh")),
            _preview_optional_float(item.get("next_target_temperature_c")),
            _preview_optional_datetime(item.get("next_target_start")),
            _preview_optional_datetime(item.get("next_target_end")),
            (
                None
                if item.get("charge_reasons") is None
                else tuple(
                    dict(reason)
                    for reason in item.get("charge_reasons", [])
                    if isinstance(reason, dict)
                )
            ),
        )
        for item in _preview_dict_list(payload.get("explanations"))
    )
    demand_items = _preview_dict_list(payload.get("demand"))
    if demand_items and "indoor_temperature_next_c" in demand_items[0]:
        demand = tuple(
            RoomEnergyInterval(
                str(item["heater_id"]),
                _preview_datetime(item["start"]),
                _preview_datetime(item["end"]),
                float(item["outdoor_temperature_c"]),
                _preview_optional_float(item.get("target_temperature_c")),
                float(item["indoor_temperature_c"]),
                float(item["indoor_temperature_next_c"]),
                float(item["stored_energy_kwh"]),
                float(item["stored_energy_next_kwh"]),
                float(item["stored_soc_percent"]),
                float(item["stored_soc_next_percent"]),
                float(item["charge_energy_kwh"]),
                float(item["heat_delivered_kwh"]),
                float(item["thermal_loss_kwh"]),
                float(item["temperature_shortfall_c"]),
                float(item.get("temperature_shortfall_start_c", 0.0)),
                float(item.get("heat_delivery_limit_kwh", 0.0)),
            )
            for item in demand_items
        )
    else:
        demand = tuple(
            DemandEstimate(
                str(item["heater_id"]),
                _preview_datetime(item["start"]),
                _preview_datetime(item["end"]),
                float(item["outdoor_temperature_c"]),
                float(item["target_temperature_c"]),
                float(item["feedback_temperature_c"]),
                float(item["degree_hours"]),
                float(item["thermal_coefficient"]),
                float(item["demand_factor"]),
                float(item["reserve_percent"]),
                float(item["demand_kwh"]),
            )
            for item in demand_items
        )
    convergence_by_heater = {
        str(heater_id): _preview_optional_datetime(value)
        for heater_id, value in (payload.get("convergence_by_heater") or {}).items()
    }
    return AutomaticPlan(
        _preview_datetime(payload["horizon_start"]),
        _preview_datetime(payload["horizon_end"]),
        int(payload["slot_minutes"]),
        slots,
        violations,
        _canonical_plan_status(payload["status"]),
        tuple(float(value) for value in payload.get("score", [])),
        str(payload["token"]),
        _preview_optional_datetime(payload.get("generated_at")),
        explanations,
        demand,
        convergence_by_heater,
        _preview_optional_datetime(payload.get("convergence_at")),
        _preview_optional_datetime(payload.get("guaranteed_until")),
    )


def _preview_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("preview payload list is invalid")
    return value


def _preview_datetime(value: Any) -> datetime:
    parsed = _preview_optional_datetime(value)
    if parsed is None:
        raise ValueError("preview datetime is missing")
    return parsed


def _preview_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _preview_optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _preview_float_map(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("preview numeric map is invalid")
    return {str(key): float(item) for key, item in value.items()}


def _preview_int_map(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("preview integer map is invalid")
    return {str(key): int(item) for key, item in value.items()}


def _projection_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _projection_key(value: Any) -> datetime | None:
    parsed = _projection_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else parsed


def _room_boundary_projection(demand: Any) -> dict[tuple[datetime, str], dict[str, float | None]]:
    """Index room-energy demand by slot start for API boundary projections."""
    result: dict[tuple[datetime, str], dict[str, float | None]] = {}
    if not isinstance(demand, (list, tuple)):
        return result
    for item in demand:
        if isinstance(item, RoomEnergyInterval):
            values = {
                "stored_energy_kwh": item.stored_energy_kwh,
                "stored_energy_next_kwh": item.stored_energy_next_kwh,
                "indoor_temperature_c": item.indoor_temperature_c,
                "indoor_temperature_next_c": item.indoor_temperature_next_c,
                "target_temperature_c": item.target_temperature_c,
                "temperature_shortfall_start_c": item.temperature_shortfall_start_c,
                "temperature_shortfall_c": item.temperature_shortfall_c,
            }
            start = item.start
            heater_id = item.heater_id
        elif isinstance(item, dict) and "indoor_temperature_next_c" in item:
            start = _projection_datetime(item.get("start"))
            heater_id = str(item.get("heater_id", ""))
            if start is None or not heater_id:
                continue
            values = {
                "stored_energy_kwh": _preview_optional_float(item.get("stored_energy_kwh")),
                "stored_energy_next_kwh": _preview_optional_float(item.get("stored_energy_next_kwh")),
                "indoor_temperature_c": _preview_optional_float(item.get("indoor_temperature_c")),
                "indoor_temperature_next_c": _preview_optional_float(item.get("indoor_temperature_next_c")),
                "target_temperature_c": _preview_optional_float(item.get("target_temperature_c")),
                "temperature_shortfall_start_c": _preview_optional_float(item.get("temperature_shortfall_start_c")),
                "temperature_shortfall_c": _preview_optional_float(item.get("temperature_shortfall_c")),
            }
        else:
            continue
        key = _projection_key(start)
        if key is not None:
            result[(key, heater_id)] = values
    return result


def _enrich_boundary_slots(slots: list[dict[str, Any]], demand: Any) -> list[dict[str, Any]]:
    """Attach start/end physical states without changing slot boundaries."""
    projections = _room_boundary_projection(demand)
    if not projections:
        return slots
    fields = (
        "stored_energy_kwh",
        "stored_energy_next_kwh",
        "indoor_temperature_c",
        "indoor_temperature_next_c",
        "target_temperature_c",
        "temperature_shortfall_start_c",
        "temperature_shortfall_c",
    )
    enriched: list[dict[str, Any]] = []
    for source in slots:
        slot = dict(source)
        start = _projection_key(slot.get("start"))
        if start is not None:
            maps = {field: dict(slot.get(field) or {}) for field in fields}
            for (projection_start, heater_id), values in projections.items():
                if projection_start != start:
                    continue
                for field in fields:
                    value = values.get(field)
                    if value is not None:
                        maps[field][heater_id] = value
            for field, values in maps.items():
                slot[field] = values
        enriched.append(slot)
    return enriched


def _preview_response(
    plan,
    temperature_targets: dict[str, tuple[TemperatureTarget, ...]] | None = None,
    *,
    site: dict[str, int | float] | None = None,
    forecast: dict[str, Any] | None = None,
    forecast_status: dict[str, Any] | None = None,
    timezone_name: str = "UTC",
) -> PlanningPreviewResponse:
    raw_violations = [_violation_payload(item) for item in plan.violations]
    violations = _raw_deficit_views(raw_violations)
    grouped_violations = [
        _deficit_view(item)
        for item in group_planning_violations(
            raw_violations, slot_minutes=plan.slot_minutes
        )
    ]
    planning_window_hours = 12 if site is None else int(site["planning_window_hours"])
    horizon_hours = PLANNING_HORIZON_HOURS if site is None else int(site["forecast_horizon_hours"])
    local_horizon_start = (
        plan.horizon_start.astimezone(ZoneInfo(timezone_name))
        if plan.horizon_start.tzinfo is not None
        else plan.horizon_start
    )
    window_end = wall_clock_end(local_horizon_start, planning_window_hours)
    forecast_points = len({item.start for item in plan.demand}) or len(plan.slots)
    forecast_summary = {
        "source": None if forecast is None else forecast.get("source"),
        "available": forecast is not None,
        "automatic_eligible": (
            forecast is not None and forecast.get("source") == "aemet"
        ),
        "points_used": forecast_points,
        "status": None if forecast_status is None else forecast_status.get("forecast_status"),
        "stale": None if forecast_status is None else forecast_status.get("forecast_stale"),
        "last_error": None if forecast_status is None else forecast_status.get("forecast_last_error"),
    }
    warnings = []
    for item in grouped_violations:
        cause = item.reason.split(":", 1)[0]
        warnings.append(
            {
                "cause": cause,
                "heater_id": item.heater_id,
                "requirement": item.requirement,
                "count": item.observation_count,
                "shortfall_c": item.shortfall_c,
                "target_window_start": item.target_window_start,
                "target_window_end": item.target_window_end,
                "affected_from": item.affected_from,
                "affected_until": item.affected_until,
                "recommended_action": _recommended_action(cause),
            }
        )
    room_energy_model = bool(
        plan.demand and isinstance(plan.demand[0], RoomEnergyInterval)
    )
    explanation_payload = [dict(item.__dict__) for item in plan.explanations]
    operator_summary = {
        "window": {"start": plan.horizon_start, "end": window_end, "hours": planning_window_hours},
        "horizon": {"start": plan.horizon_start, "end": plan.horizon_end, "hours": horizon_hours},
        "forecast": forecast_summary,
        "heat_delivered_kwh_by_heater": {
            heater_id: round(
                sum(item.heat_delivered_kwh for item in plan.demand if item.heater_id == heater_id),
                6,
            )
            for heater_id in sorted({item.heater_id for item in plan.demand})
        } if room_energy_model else {},
        "heater_summaries": persisted_operator_summary(
            {"explanations": explanation_payload}
        ),
        "room_energy_model": room_energy_model,
        "warnings": warnings,
        "deficit_groups": [item.model_dump(mode="json") for item in grouped_violations],
        "recommended_action": "Revisa los avisos agrupados y corrige la entrada indicada." if warnings else "No se requieren acciones adicionales.",
        "power_limits": {
            "contracted_w": None if site is None else int(site["contracted_power_w"]),
            "base_load_w": 0 if site is None else int(site.get("base_load_w", 0)),
            "heating_w": None if site is None else int(site["max_heating_power_w"]),
        },
    }
    preview_slots = _enrich_boundary_slots(
        [
            {
                "start": item.start,
                "end": item.end,
                "heater_ids": list(item.heater_ids),
                "power_w": item.power_w,
                "outdoor_temperature_c": item.outdoor_temperature_c,
                "stored_charge_percent": item.stored_charge_percent,
                "required_charge_percent": item.required_charge_percent,
                "initial_soc_percent": item.initial_soc_percent,
                "demand_kwh": item.demand_kwh,
                "heater_power_w": item.heater_power_w,
                "stored_energy_kwh": item.stored_energy_kwh,
                "stored_energy_next_kwh": item.stored_energy_next_kwh,
                "indoor_temperature_c": item.indoor_temperature_c,
                "indoor_temperature_next_c": item.indoor_temperature_next_c,
                "target_temperature_c": item.target_temperature_c,
                "heat_delivered_kwh": item.heat_delivered_kwh,
                "thermal_loss_kwh": item.thermal_loss_kwh,
                "temperature_shortfall_start_c": item.temperature_shortfall_start_c,
                "temperature_shortfall_c": item.temperature_shortfall_c,
                "charge_energy_kwh": item.charge_energy_kwh,
                "heat_delivery_limit_kwh": item.heat_delivery_limit_kwh,
            }
            for item in plan.slots
        ],
        plan.demand,
    )
    return PlanningPreviewResponse(
        token=plan.input_token, status=plan.status, score=list(plan.score),
        window_start=plan.horizon_start, window_end=window_end,
        horizon_start=plan.horizon_start, horizon_end=plan.horizon_end,
        slot_minutes=plan.slot_minutes,
        slots=preview_slots,
        deficits=grouped_violations,
        violations=violations,
        convergence_by_heater=dict(plan.convergence_by_heater),
        convergence_at=plan.convergence_at,
        guaranteed_until=plan.guaranteed_until,
        explanations=explanation_payload,
        demand=[item.__dict__ for item in plan.demand],
        temperature_targets=[
            TemperatureTargetView(
                id=target.id,
                heater_id=heater_id,
                target_temperature_c=target.target_temperature_c,
                start_time=target.start_time.strftime("%H:%M"),
                end_time=format_temperature_target_end_time(target.start_time, target.end_time),
                weekdays=list(target.weekdays),
                enabled=target.enabled,
            )
            for heater_id, targets in sorted((temperature_targets or {}).items())
            for target in targets
        ],
        operator_summary=operator_summary,
    )


def _recommended_action(reason: str) -> str:
    if reason == "missing_aemet_coverage":
        return "Espera una previsión AEMET horaria completa de 24 horas o revisa la conexión meteorológica."
    if reason == "missing_required_state":
        return "Comprueba que cada acumulador publica temperatura interior y SOC reciente."
    if reason in {"insufficient_capacity_or_power", "insufficient_stored_energy_or_power"}:
        return "Revisa potencia disponible, capacidad térmica y la programación de temperatura."
    if reason.startswith("solver"):
        return "Revisa la configuración del optimizador o contacta con soporte."
    return "Revisa la entrada indicada y vuelve a calcular."


def _job_response(
    job: dict[str, Any] | None,
    *,
    site: dict[str, int | float] | None = None,
) -> PlanningPreviewJobResponse:
    if job is None:
        raise not_found("preview job does not exist", field="job_id")
    result_payload = None if job["result"] is None else dict(job["result"])
    if result_payload is not None:
        # Results created before the configurable planning window was added do
        # not contain these fields. Keep durable jobs readable after upgrades.
        result_payload.setdefault("window_start", result_payload.get("horizon_start"))
        if "window_end" not in result_payload and result_payload.get("window_start") is not None:
            planning_window_hours = 12 if site is None else int(site["planning_window_hours"])
            window_start = result_payload["window_start"]
            if not isinstance(window_start, datetime):
                window_start = datetime.fromisoformat(str(window_start).replace("Z", "+00:00"))
            # Preserve the serialized shape of durable results written before
            # timezone-aware preview windows were introduced.
            result_payload["window_end"] = window_start + timedelta(hours=planning_window_hours)
    result = None if result_payload is None else PlanningPreviewResponse.model_validate(result_payload)
    return PlanningPreviewJobResponse(
        job_id=job["id"], status=job["status"], cancellation_requested=job["cancellation_requested"],
        requested_at=job["requested_at"], started_at=job["started_at"], finished_at=job["finished_at"],
        checks=[PlanningCheckView(**item) for item in job["steps"]], result=result,
        operator_summary={} if result is None else result.operator_summary,
        error_code=job["error_code"], error_detail=job["error_detail"],
    )


def _validate_temperature_target_heaters(
    store: Store,
    targets: dict[str, tuple[TemperatureTarget, ...]],
) -> None:
    known_heaters = {heater.id for heater in store.repository.current()[0].heaters}
    unknown = sorted(set(targets) - known_heaters)
    if unknown:
        raise ConfigValidationError(
            f"heater {unknown[0]!r} does not exist",
            field="heater_id",
            heater_id=unknown[0],
        )


def _configured_temperature_targets(store: Store) -> dict[str, tuple[TemperatureTarget, ...]]:
    return {
        heater.id: tuple(heater.temperature_targets)
        for heater in store.repository.current()[0].heaters
    }


def _ordered_plan_slots(slots: list[PlanningSlotView]) -> list[dict]:
    return [
        {
            "start": slot.start,
            "end": slot.end,
            "heater_ids": slot.heater_ids,
            "power_w": slot.total_power_w,
            "outdoor_temperature_c": slot.temperature_c,
            "temperature_c": slot.temperature_c,
            "temperature_interpolated": slot.temperature_interpolated,
            "stored_energy_kwh": slot.stored_energy_kwh_by_heater,
            "stored_energy_next_kwh": slot.stored_energy_next_kwh_by_heater,
            "indoor_temperature_c": slot.indoor_temperature_c_by_heater,
            "indoor_temperature_next_c": slot.indoor_temperature_next_c_by_heater,
            "target_temperature_c": slot.target_temperature_c_by_heater,
            "heat_delivered_kwh": slot.heat_delivered_kwh_by_heater,
            "thermal_loss_kwh": slot.thermal_loss_kwh_by_heater,
            "temperature_shortfall_start_c": slot.temperature_shortfall_start_c_by_heater,
            "temperature_shortfall_c": slot.temperature_shortfall_c_by_heater,
            "charge_energy_kwh": slot.charge_energy_kwh_by_heater,
            "heat_delivery_limit_kwh": slot.heat_delivery_limit_kwh_by_heater,
        }
        for slot in slots
    ]


def _plan_slot_maps(
    ordered_plan_slots: list[dict],
) -> tuple[
    dict[int, list[str]],
    dict[int, tuple[float | None, bool]],
    dict[int, int],
]:
    """Map contiguous plan slots to timeline indices by order, not datetime keys."""
    assigned_by_index: dict[int, list[str]] = {}
    temperatures_by_index: dict[int, tuple[float | None, bool]] = {}
    power_by_index: dict[int, int] = {}
    for index, item in enumerate(ordered_plan_slots):
        assigned_by_index[index] = list(item.get("heater_ids") or [])
        outdoor = item.get("outdoor_temperature_c", item.get("temperature_c"))
        temperatures_by_index[index] = (
            outdoor,
            bool(item.get("temperature_interpolated", False)),
        )
        if item.get("power_w") is not None:
            power_by_index[index] = int(item["power_w"])
    return assigned_by_index, temperatures_by_index, power_by_index


def _build_timeline(
    heaters,
    power_by_id: dict[str, int],
    ordered_plan_slots: list[dict],
    forecast,
    horizon_start: datetime,
    horizon_end: datetime,
    slot_delta: timedelta,
) -> list[PlanningTimelineSlotView]:
    """Project the accepted plan across the configured forecast horizon."""
    assigned_by_index, temperatures_by_index, power_by_index = _plan_slot_maps(
        ordered_plan_slots,
    )
    timeline: list[PlanningTimelineSlotView] = []
    cursor = horizon_start
    slot_index = 0
    while real_before(cursor, horizon_end):
        source_slot = (
            ordered_plan_slots[slot_index]
            if slot_index < len(ordered_plan_slots)
            else {}
        )
        start = source_slot.get("start", cursor)
        if not isinstance(start, datetime) or real_before(start, cursor):
            start = cursor
        candidate_end = source_slot.get("end")
        if not isinstance(candidate_end, datetime) or not real_before(start, candidate_end):
            candidate_end = advance_real(start, round(slot_delta.total_seconds() / 60))
        end = horizon_end if real_before(horizon_end, candidate_end) else candidate_end
        if not real_before(cursor, end):
            end = advance_real(cursor, round(slot_delta.total_seconds() / 60))
            if real_before(horizon_end, end):
                end = horizon_end
        heater_ids = sorted(assigned_by_index.get(slot_index, []))
        temperature, interpolated = temperatures_by_index.get(
            slot_index, _temperature_for_interval(forecast, cursor, end)
        )
        stored_energy = {str(key): float(value) for key, value in (source_slot.get("stored_energy_kwh", {}) or {}).items()}
        stored_energy_next = {
            str(key): float(value)
            for key, value in (source_slot.get("stored_energy_next_kwh", {}) or {}).items()
        }
        indoor_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("indoor_temperature_c", {}) or {}).items()
        }
        indoor_projection_next = {
            str(key): float(value)
            for key, value in (source_slot.get("indoor_temperature_next_c", {}) or {}).items()
        }
        target_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("target_temperature_c", {}) or {}).items()
        }
        heat_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("heat_delivered_kwh", {}) or {}).items()
        }
        loss_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("thermal_loss_kwh", {}) or {}).items()
        }
        shortfall_start_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("temperature_shortfall_start_c", {}) or {}).items()
        }
        shortfall_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("temperature_shortfall_c", {}) or {}).items()
        }
        charge_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("charge_energy_kwh", {}) or {}).items()
        }
        heat_limit_projection = {
            str(key): float(value)
            for key, value in (source_slot.get("heat_delivery_limit_kwh", {}) or {}).items()
        }

        timeline.append(
            PlanningTimelineSlotView(
                start=cursor,
                end=end,
                heater_ids=heater_ids,
                total_power_w=power_by_index.get(
                    slot_index,
                    sum(power_by_id.get(heater_id, 0) for heater_id in heater_ids),
                ),
                temperature_c=temperature,
                temperature_interpolated=interpolated,
                stored_energy_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in stored_energy.items()},
                stored_energy_next_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in stored_energy_next.items()},
                indoor_temperature_c_by_heater={heater_id: round(value, 6) for heater_id, value in indoor_projection.items()},
                indoor_temperature_next_c_by_heater={heater_id: round(value, 6) for heater_id, value in indoor_projection_next.items()},
                target_temperature_c_by_heater={heater_id: round(value, 6) for heater_id, value in target_projection.items()},
                heat_delivered_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in heat_projection.items()},
                thermal_loss_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in loss_projection.items()},
                temperature_shortfall_start_c_by_heater={heater_id: round(value, 6) for heater_id, value in shortfall_start_projection.items()},
                temperature_shortfall_c_by_heater={heater_id: round(value, 6) for heater_id, value in shortfall_projection.items()},
                charge_energy_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in charge_projection.items()},
                heat_delivery_limit_kwh_by_heater={heater_id: round(value, 6) for heater_id, value in heat_limit_projection.items()},
            )
        )
        cursor = end
        slot_index += 1
    return timeline


def _temperature_for_interval(forecast, start: datetime, end: datetime) -> tuple[float | None, bool]:
    if forecast is None:
        return None, False
    points = [
        point for point in forecast["hourly_points"]
        if start <= point["timestamp"] < end
    ]
    if points:
        return sum(point["temperature_c"] for point in points) / len(points), any(
            point["interpolated"] for point in points
        )
    return forecast["average_temperature_c"], True


def _forecast_view(forecast) -> PlanningForecastView | None:
    if forecast is None:
        return None
    hourly_points = [HourlyForecastPointView(**point) for point in forecast["hourly_points"]]
    summary = {
        key: value
        for key, value in forecast.items()
        if key != "hourly_points"
    }
    # The stored AEMET summary is a daily value, while the planning graph shows
    # the future hourly points. Derive all three values from that same visible
    # series so the summary cannot describe a different period than the graph.
    temperatures = [point.temperature_c for point in hourly_points]
    if temperatures:
        summary.update(
            average_temperature_c=sum(temperatures) / len(temperatures),
            minimum_temperature_c=min(temperatures),
            maximum_temperature_c=max(temperatures),
        )
    return PlanningForecastView(
        **summary,
        hourly_points=hourly_points,
    )


__all__ = ["router"]
