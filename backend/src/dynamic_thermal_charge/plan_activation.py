"""Shared activation rules for automatic and best-effort plans."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping

from .charge_planning import CONVERGING, DEGRADED, VALID


ACTIVATION_AUTOMATIC = "automatic"
ACTIVATION_BEST_EFFORT = "best_effort"


def seconds_to_next_replan(
    now: datetime,
    *,
    replan_minutes: int,
    slot_minutes: int,
) -> int:
    """Use the same wall-clock cadence for runtime and API precedence."""
    cadence_minutes = max(int(replan_minutes), int(slot_minutes))
    target = now + timedelta(minutes=cadence_minutes)
    floor = target.replace(
        second=0,
        microsecond=0,
        minute=(target.minute // slot_minutes) * slot_minutes,
    )
    boundary = floor if floor == target else floor + timedelta(minutes=slot_minutes)
    return max(slot_minutes * 60, math.ceil((boundary - now).total_seconds()))


def _status(value: Any) -> str:
    return str(value or "").upper()


def _instant(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def covering_plan(
    plan: Mapping[str, Any] | None,
    *,
    now: datetime,
    next_refresh_seconds: int = 0,
) -> bool:
    """Whether a persisted VALID/CONVERGING plan covers the next refresh."""
    if plan is None or _status(plan.get("status")) not in {VALID, CONVERGING}:
        return False
    horizon_end = plan.get("horizon_end")
    if not isinstance(horizon_end, datetime):
        return False
    return _instant(horizon_end) > _instant(now) + timedelta(
        seconds=max(0, int(next_refresh_seconds))
    )


def candidate_activation_mode(
    candidate_status: str,
    active_plan: Mapping[str, Any] | None,
    *,
    now: datetime,
    next_refresh_seconds: int = 0,
    best_effort_requested: bool = False,
    require_best_effort_confirmation: bool = False,
    has_exclusions: bool = False,
) -> str | None:
    """Return the mode in which a candidate may become active.

    A degraded candidate is never allowed to displace a covering successful
    plan.  Runtime may implicitly use best-effort when no such plan exists;
    the explicit API activation path passes ``require_best_effort_confirmation``
    so a degraded preview always needs the user's confirmation.
    """
    status = _status(candidate_status)
    if status in {VALID, CONVERGING}:
        return ACTIVATION_BEST_EFFORT if has_exclusions else ACTIVATION_AUTOMATIC
    if status != DEGRADED:
        return None
    if covering_plan(
        active_plan,
        now=now,
        next_refresh_seconds=next_refresh_seconds,
    ):
        return None
    if require_best_effort_confirmation and not best_effort_requested:
        return None
    return ACTIVATION_BEST_EFFORT


def can_activate_plan(
    candidate_status: str,
    active_plan: Mapping[str, Any] | None,
    *,
    now: datetime,
    next_refresh_seconds: int = 0,
    best_effort_requested: bool = False,
    has_exclusions: bool = False,
) -> bool:
    return (
        candidate_activation_mode(
            candidate_status,
            active_plan,
            now=now,
            next_refresh_seconds=next_refresh_seconds,
            best_effort_requested=best_effort_requested,
            require_best_effort_confirmation=True,
            has_exclusions=has_exclusions,
        )
        is not None
    )


def plan_best_effort_reasons(plan: Any) -> tuple[str, ...]:
    """Return stable cause codes suitable for API and operator projections."""
    def value(item: Any, name: str, default: Any = None) -> Any:
        if isinstance(item, Mapping):
            return item.get(name, default)
        return getattr(item, name, default)

    excluded = value(plan, "excluded_heaters", ()) or ()
    reasons: set[str] = set()
    for item in excluded:
        if isinstance(item, Mapping):
            reasons.add(str(item.get("cause", "missing_required_state")))
    for item in value(plan, "violations", ()) or value(plan, "deficits", ()) or ():
        requirement = str(value(item, "requirement", ""))
        if requirement == "excluded_heater":
            reasons.add(
                str(
                    value(item, "cause")
                    or value(item, "reason", "missing_required_state")
                )
            )
        elif requirement:
            reasons.add(
                str(
                    value(item, "cause") or value(item, "reason", requirement)
                ).split(":", 1)[0]
            )
    return tuple(sorted(reasons))


__all__ = [
    "ACTIVATION_AUTOMATIC",
    "ACTIVATION_BEST_EFFORT",
    "can_activate_plan",
    "candidate_activation_mode",
    "covering_plan",
    "seconds_to_next_replan",
    "plan_best_effort_reasons",
]
