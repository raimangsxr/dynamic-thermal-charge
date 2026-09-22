"""Stable operator recovery information for unusable planning results.

The planner deliberately keeps its detailed violation reasons technical.  This
module adds a small, shared projection for operator-facing clients without
changing the planner's safety decision or the persisted reasons.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_CAUSES: dict[str, tuple[str, str | None, str | None]] = {
    "missing_aemet_coverage": (
        "missing_aemet_coverage",
        "check_weather",
        "/configuracion",
    ),
    "missing_forecast_coverage": (
        "missing_aemet_coverage",
        "check_weather",
        "/configuracion",
    ),
    "missing_guard_forecast_coverage": (
        "missing_aemet_coverage",
        "check_weather",
        "/configuracion",
    ),
    "forecast_not_eligible": (
        "missing_aemet_coverage",
        "check_weather",
        "/configuracion",
    ),
    "missing_required_state": (
        "missing_required_state",
        "check_telemetry",
        "/estado#telemetry-title",
    ),
    "missing_temperature_schedule": (
        "invalid_configuration",
        "review_configuration",
        "/configuracion",
    ),
    "invalid_temperature_schedule": (
        "invalid_configuration",
        "review_configuration",
        "/configuracion",
    ),
    "invalid_configuration": (
        "invalid_configuration",
        "review_configuration",
        "/configuracion",
    ),
    "insufficient_capacity_or_power": (
        "insufficient_capacity_or_power",
        "review_power",
        "/configuracion",
    ),
    "insufficient_stored_energy_or_power": (
        "insufficient_capacity_or_power",
        "review_power",
        "/configuracion",
    ),
    "heater_power_exceeds_global_limit": (
        "insufficient_capacity_or_power",
        "review_power",
        "/configuracion",
    ),
    "projected_deficit": (
        "insufficient_capacity_or_power",
        "review_power",
        "/configuracion",
    ),
    "solver_time_limit": (
        "solver_failure",
        "contact_support",
        "/diagnostico",
    ),
    "solver_status": (
        "solver_failure",
        "contact_support",
        "/diagnostico",
    ),
    "solver_failure": (
        "solver_failure",
        "contact_support",
        "/diagnostico",
    ),
    "solver_unavailable": (
        "solver_failure",
        "contact_support",
        "/diagnostico",
    ),
    "no_active_automatic_plan": (
        "no_plan_available",
        "review_configuration",
        "/planificacion",
    ),
    "no_current_or_next_plan": (
        "no_plan_available",
        "review_configuration",
        "/planificacion",
    ),
}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _reason_key(reason: Any) -> str:
    return str(reason or "").strip().split(":", 1)[0].lower()


def _cause_for_reason(reason: Any, heater_ids: Sequence[str] = ()) -> dict[str, Any]:
    raw = str(reason or "").strip()
    key = _reason_key(raw)
    mapped = _CAUSES.get(key)
    if mapped is None and key.startswith("solver"):
        mapped = _CAUSES["solver_failure"]
    if mapped is None:
        mapped = ("unknown", None, None)
    code, action_code, destination = mapped
    return {
        "code": code,
        "action_code": action_code,
        "destination": destination,
        "detail": raw or None,
        "heater_ids": sorted({str(item) for item in heater_ids if item}),
    }


def _merge_cause(causes: list[dict[str, Any]], cause: dict[str, Any]) -> None:
    for existing in causes:
        if existing["code"] != cause["code"]:
            continue
        existing["heater_ids"] = sorted(
            set(existing["heater_ids"]) | set(cause["heater_ids"])
        )
        if existing.get("detail") is None:
            existing["detail"] = cause.get("detail")
        return
    causes.append(cause)


def _safe_state(plan_status: str | None, absence_reason: str | None) -> str:
    status = str(plan_status or "").upper()
    if status in {"INVALID", ""} and (status == "INVALID" or absence_reason):
        return "outputs_off"
    if status == "DEGRADED":
        return "last_valid_plan"
    return "active_plan"


def build_planning_recovery(
    *,
    plan_status: str | None,
    absence_reason: str | None,
    deficits: Sequence[Any] = (),
    telemetry: Sequence[Any] = (),
    forecast_automatic_eligible: bool | None = None,
) -> dict[str, Any] | None:
    """Return a deterministic recovery projection, or ``None`` when healthy.

    ``deficits`` is the same grouped list exposed by both read endpoints.  The
    function accepts mappings and Pydantic/domain objects so the API routes can
    call it without introducing a dependency from the projection into schemas.
    """

    status = str(plan_status or "").upper()
    causes: list[dict[str, Any]] = []

    for deficit in deficits:
        reason = _value(deficit, "reason", "")
        heater_id = _value(deficit, "heater_id")
        _merge_cause(
            causes,
            _cause_for_reason(reason, () if heater_id is None else (str(heater_id),)),
        )

    if not causes and absence_reason:
        _merge_cause(causes, _cause_for_reason(absence_reason))

    if not causes and forecast_automatic_eligible is False:
        _merge_cause(causes, _cause_for_reason("forecast_not_eligible"))

    needs_telemetry_context = status in {"INVALID", "DEGRADED"} or bool(
        absence_reason
    )
    if needs_telemetry_context and any(
        bool(_value(item, "missing_fields", ()))
        or _value(item, "state") not in (None, "ready")
        for item in telemetry
    ):
        _merge_cause(causes, _cause_for_reason("missing_required_state"))

    if not causes:
        return None

    return {
        "primary": causes[0],
        "secondary": causes[1:],
        "safe_state": _safe_state(plan_status, absence_reason),
    }


def forecast_coverage(
    forecast: Any,
    *,
    required_hours: int | None,
    automatic_eligible: bool | None,
    stale: bool | None,
) -> dict[str, Any]:
    """Project received points and their available time range for the API."""

    points = _value(forecast, "hourly_points", ()) if forecast is not None else ()
    points = tuple(points or ())
    timestamps = [
        _value(point, "timestamp") for point in points if _value(point, "timestamp")
    ]
    return {
        "points_received": len(points),
        "coverage_start": min(timestamps) if timestamps else None,
        "coverage_end": max(timestamps) if timestamps else None,
        "required_hours": required_hours,
        "automatic_eligible": automatic_eligible,
        "stale": stale,
    }


__all__ = ["build_planning_recovery", "forecast_coverage"]
