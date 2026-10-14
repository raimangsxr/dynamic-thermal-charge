"""Authenticated room, calibration, notification and Web Push API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

from fastapi import APIRouter, Depends, Request, status

from ...persistence import ConfigConflictError, ConfigValidationError
from ...persistence.bootstrap import Store
from ...persistence.mapping import from_utc
from ...calibration_runtime import finish_calibration
from ...thermal_calibration import CalibrationError, RoomEstimateInput, estimate_room
from ..dependencies import usable_store
from ..errors import not_found
from ..schemas import (
    CalibrationActionResponse,
    CalibrationQualityView,
    CalibrationSessionView,
    ERROR_RESPONSES,
    OperatorNotificationPage,
    OperatorNotificationView,
    PushRegistrationRequest,
    PushRegistrationResponse,
    PushRevocationRequest,
    READ_RESPONSES,
    RoomEstimateRequest,
    RoomEstimateResponse,
    RoomPatchRequest,
    RoomResponse,
)


router = APIRouter()


def _quality(value: object) -> CalibrationQualityView | None:
    if not isinstance(value, dict):
        return None
    allowed = {name: value.get(name) for name in CalibrationQualityView.model_fields if name in value}
    try:
        return CalibrationQualityView(**allowed)
    except Exception:
        return None


def _room_response(
    store: Store,
    heater_id: str,
    *,
    now: datetime | None = None,
) -> RoomResponse:
    row = store.repository.room(heater_id)
    if row is None:
        raise not_found(f"heater {heater_id!r} does not have a room", field="heater_id")
    result = row.get("terminal_result_json")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = None
    session = store.calibration.active(heater_id)
    session_view = None
    if session is not None:
        session_view = CalibrationSessionView(
            id=session.id,
            status=session.status,
            phase=session.phase,
            started_at=session.started_at,
            updated_at=session.updated_at,
            phase_deadline_at=session.phase_deadline_at,
            missing_since=session.missing_since,
            commands=session.commands,
            metrics=session.metrics,
            terminal_cause=session.terminal_cause,
        )
    active_quality = None if session is None else session.metrics.get("quality")
    quality = _quality(
        result.get("quality") if isinstance(result, dict) else active_quality
    )
    moment = now or datetime.now(timezone.utc)
    telemetry = store.planning.telemetry().get(heater_id)
    outdoor = store.outdoor_temperature.latest()

    def age(timestamp: datetime | None) -> float | None:
        if timestamp is None:
            return None
        delta = moment - timestamp
        if delta.total_seconds() < 0:
            return None
        return delta.total_seconds() / 60

    return RoomResponse(
        heater_id=heater_id,
        capacity_kwh_per_c=float(row["room_thermal_capacity_kwh_per_c"]),
        loss_kw_per_c=float(row["room_heat_loss_kw_per_c"]),
        status=str(row["status"]),
        terminal_result=result if isinstance(result, dict) else None,
        terminal_cause=None if row["terminal_cause"] is None else str(row["terminal_cause"]),
        terminal_at=from_utc(row.get("terminal_at")),
        applied_session_id=(
            None if row.get("applied_session_id") is None else str(row["applied_session_id"])
        ),
        session=session_view,
        quality=quality,
        input_ages_minutes={
            "indoor_temperature": age(
                None if telemetry is None else telemetry.indoor_received_at
            ),
            "soc": age(None if telemetry is None else telemetry.stored_soc_received_at),
            "outdoor_temperature": age(None if outdoor is None else outdoor.received_at),
        },
    )


def _heater_or_404(store: Store, heater_id: str):
    config, revision = store.repository.current()
    heater = next((item for item in config.heaters if item.id == heater_id), None)
    if heater is None:
        raise not_found(f"heater {heater_id!r} does not exist", field="heater_id")
    return config, revision, heater


@router.get(
    "/rooms/{heater_id}",
    response_model=RoomResponse,
    responses=READ_RESPONSES,
)
def get_room(
    heater_id: str,
    request: Request,
    store: Store = Depends(usable_store),
) -> RoomResponse:
    _heater_or_404(store, heater_id)
    return _room_response(store, heater_id, now=request.app.state.clock())


@router.patch(
    "/rooms/{heater_id}",
    response_model=RoomResponse,
    responses=ERROR_RESPONSES,
)
def patch_room(
    heater_id: str,
    payload: RoomPatchRequest,
    request: Request,
    store: Store = Depends(usable_store),
) -> RoomResponse:
    _heater_or_404(store, heater_id)
    if store.calibration.active(heater_id) is not None:
        raise ConfigConflictError("room coefficients cannot be edited during calibration")
    store.repository.update_room(
        heater_id,
        capacity_kwh_per_c=payload.capacity_kwh_per_c,
        loss_kw_per_c=payload.loss_kw_per_c,
        expected_revision=payload.expected_revision,
    )
    if store.context is not None:
        store.context.refresh_fallback()
    return _room_response(store, heater_id, now=request.app.state.clock())


@router.post(
    "/rooms/{heater_id}/calibration",
    response_model=CalibrationActionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def start_calibration(
    heater_id: str,
    request: Request,
    store: Store = Depends(usable_store),
) -> CalibrationActionResponse:
    config, revision, heater = _heater_or_404(store, heater_id)
    if not heater.enabled:
        raise ConfigValidationError("the accumulator is disabled", field="enabled", heater_id=heater_id)
    control = store.home_assistant.control_state()
    if control.heater_modes.get(heater_id, "AUTO") != "AUTO":
        raise ConfigValidationError("the accumulator must be in AUTO mode", field="mode", heater_id=heater_id)
    relay = store.relay_tests.current()
    if relay is not None and (
        relay.get("session") is not None
        or bool((relay.get("safety") or {}).get("fault_latched"))
        or bool((relay.get("audit") or {}).get("degraded"))
    ):
        raise ConfigConflictError("a relay test is active")
    if store.calibration.active(heater_id) is not None:
        raise ConfigConflictError("a calibration session is already active")
    now = request.app.state.clock()
    telemetry = store.planning.telemetry().get(heater_id)
    for field, timestamp in (
        ("indoor temperature", None if telemetry is None else telemetry.indoor_received_at),
        ("SOC", None if telemetry is None else telemetry.stored_soc_received_at),
    ):
        if timestamp is None or now - timestamp > timedelta(minutes=15) or timestamp > now:
            raise ConfigValidationError(f"fresh {field} telemetry is required", heater_id=heater_id)
    outdoor = store.outdoor_temperature.latest()
    if outdoor is None or not outdoor.received_at <= now <= outdoor.received_at + timedelta(minutes=15):
        raise ConfigValidationError("fresh outdoor temperature is required", field="outdoor_temperature_c")
    # Insert the application session first, then apply the optimistic
    # configuration transition.  If the revision loses a race, compensate by
    # deleting the just-created session so the request has no partial write in
    # either store.
    session = store.calibration.start(heater_id, now=now)
    try:
        store.repository.update_room(
            heater_id,
            capacity_kwh_per_c=heater.room_thermal_capacity_kwh_per_c,
            loss_kw_per_c=heater.room_heat_loss_kw_per_c,
            expected_revision=revision,
            status="calibrating",
        )
    except Exception:
        store.calibration.abort_start(session.id)
        raise
    if store.context is not None:
        store.context.refresh_fallback()
    return CalibrationActionResponse(
        revision=store.repository.current()[1],
        room=_room_response(store, heater_id, now=now),
    )


@router.delete(
    "/rooms/{heater_id}/calibration",
    response_model=CalibrationActionResponse,
    responses=ERROR_RESPONSES,
)
def cancel_calibration(
    heater_id: str,
    request: Request,
    store: Store = Depends(usable_store),
) -> CalibrationActionResponse:
    _config, revision, _heater = _heater_or_404(store, heater_id)
    session = store.calibration.active(heater_id)
    if session is None:
        raise ConfigConflictError("no calibration session is active")
    finish_calibration(
        store,
        session.id,
        result=None,
        status="cancelled",
        cause="cancelled_by_operator",
        now=request.app.state.clock(),
        heater_id=heater_id,
    )
    if store.context is not None:
        store.context.refresh_fallback()
    return CalibrationActionResponse(
        revision=store.repository.current()[1],
        room=_room_response(store, heater_id, now=request.app.state.clock()),
    )


@router.post(
    "/rooms/{heater_id}/estimate",
    response_model=RoomEstimateResponse,
    responses=ERROR_RESPONSES,
)
def estimate_room_endpoint(
    heater_id: str,
    payload: RoomEstimateRequest,
    request: Request,
    store: Store = Depends(usable_store),
) -> RoomEstimateResponse:
    _config, revision, _heater = _heater_or_404(store, heater_id)
    if store.calibration.active(heater_id) is not None:
        raise ConfigConflictError("cannot estimate during calibration")
    try:
        estimate = estimate_room(
            RoomEstimateInput(
                surface_m2=payload.surface_m2,
                walls_exterior=payload.walls_exterior,
                windows_m2=payload.windows_m2,
                insulation=payload.insulation,
                height_m=payload.height_m,
                other_heat_sources_kw=payload.other_heat_sources_kw,
            )
        )
    except CalibrationError as exc:
        raise ConfigValidationError(str(exc), field="estimate", heater_id=heater_id) from exc
    store.repository.update_room(
        heater_id,
        capacity_kwh_per_c=estimate.capacity_kwh_per_c,
        loss_kw_per_c=estimate.loss_kw_per_c,
        expected_revision=payload.expected_revision,
        status="estimated",
    )
    if store.context is not None:
        store.context.refresh_fallback()
    return RoomEstimateResponse(
        room=_room_response(store, heater_id, now=request.app.state.clock()),
        revision=store.repository.current()[1],
    )


@router.get(
    "/notifications",
    response_model=OperatorNotificationPage,
    responses=READ_RESPONSES,
)
def get_notifications(store: Store = Depends(usable_store)) -> OperatorNotificationPage:
    return OperatorNotificationPage(
        items=[
            OperatorNotificationView(
                id=item.id,
                session_id=item.session_id,
                kind=item.kind,
                title=item.title,
                body=item.body,
                created_at=item.created_at,
                acknowledged_at=item.acknowledged_at,
            )
            for item in store.calibration.notifications()
        ]
    )


@router.post(
    "/notifications/{notification_id}/ack",
    response_model=OperatorNotificationPage,
    responses=ERROR_RESPONSES,
)
def acknowledge_notification(notification_id: int, store: Store = Depends(usable_store)) -> OperatorNotificationPage:
    store.calibration.acknowledge_notification(notification_id)
    return get_notifications(store)


@router.get("/push/public-key", responses=READ_RESPONSES)
def push_public_key() -> dict[str, str | None]:
    return {"public_key": os.environ.get("DTC_VAPID_PUBLIC_KEY")}


@router.post(
    "/push/subscriptions",
    response_model=PushRegistrationResponse,
    responses=ERROR_RESPONSES,
)
def register_push(
    payload: PushRegistrationRequest,
    store: Store = Depends(usable_store),
) -> PushRegistrationResponse:
    if not os.environ.get("DTC_VAPID_PUBLIC_KEY"):
        return PushRegistrationResponse(browser_id=payload.browser_id, status="unsupported")
    keys = payload.keys
    if set(keys) != {"p256dh", "auth"}:
        raise ConfigValidationError("push keys must contain p256dh and auth")
    subscription = store.calibration.register_subscription(
        user_id="operator",
        browser_id=payload.browser_id,
        endpoint=payload.endpoint,
        p256dh=keys["p256dh"],
        auth=keys["auth"],
    )
    return PushRegistrationResponse(browser_id=payload.browser_id, status=subscription.status)


@router.delete(
    "/push/subscriptions",
    response_model=PushRegistrationResponse,
    responses=ERROR_RESPONSES,
)
def revoke_push(
    payload: PushRevocationRequest,
    store: Store = Depends(usable_store),
) -> PushRegistrationResponse:
    store.calibration.revoke_subscription(user_id="operator", browser_id=payload.browser_id)
    return PushRegistrationResponse(browser_id=payload.browser_id, status="revoked")


__all__ = ["router"]
