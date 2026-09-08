"""Small shared projections used by the operator-facing read endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def real_before(left: datetime, right: datetime) -> bool:
    """Compare instants rather than ambiguous wall-clock labels."""
    if left.tzinfo is None or right.tzinfo is None:
        return left < right
    return left.astimezone(timezone.utc) < right.astimezone(timezone.utc)


def real_at_or_after(left: datetime, right: datetime) -> bool:
    return not real_before(left, right)


def wall_clock_end(start: datetime, hours: int) -> datetime:
    """End a wall-clock window while preserving the installation timezone."""
    if start.tzinfo is None:
        return start + timedelta(hours=hours)
    naive_end = start.replace(tzinfo=None) + timedelta(hours=hours)
    candidate = naive_end.replace(tzinfo=start.tzinfo, fold=start.fold)
    # The round trip resolves a non-existent DST label to the instant that
    # actually exists in the configured zone.
    return candidate.astimezone(timezone.utc).astimezone(start.tzinfo)


def automatic_window(
    automatic: dict[str, Any],
    planning_window_hours: int,
    timezone_name: str = "UTC",
) -> tuple[datetime, datetime]:
    start = automatic["horizon_start"]
    if start.tzinfo is None:
        local_start = start
    else:
        local_start = start.astimezone(ZoneInfo(timezone_name))
    configured_end = wall_clock_end(local_start, planning_window_hours)
    horizon_end = automatic["horizon_end"]
    return start, horizon_end if real_before(horizon_end, configured_end) else configured_end


def forecast_cycle_context(planning) -> dict[str, Any]:
    """Combine stable cycle metadata with retry/staleness context."""
    context = dict(planning.forecast_cycle_status() or {})
    latest_cycle = getattr(planning, "latest_forecast_cycle", None)
    cycle = latest_cycle() if callable(latest_cycle) else None
    if cycle is None:
        context.setdefault("forecast_next_run_kind", None)
        context.setdefault("forecast_stale", None)
        return context
    context["forecast_next_run_kind"] = (
        "retry"
        if cycle.get("next_retry_at") is not None
        else "daily"
        if cycle.get("next_run_at") is not None
        else None
    )
    if cycle.get("next_retry_at") is not None:
        context["forecast_next_run_at"] = cycle["next_retry_at"]
    context["forecast_stale"] = bool(cycle.get("stale", False))
    return context


__all__ = [
    "automatic_window",
    "forecast_cycle_context",
    "real_at_or_after",
    "real_before",
    "wall_clock_end",
]
