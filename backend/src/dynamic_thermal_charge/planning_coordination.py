"""Cross-process coordination for deterministic planning calculations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Callable

from .charge_planning import (
    AutomaticPlan,
    PlanningCancelled,
    deserialize_automatic_plan,
    input_token,
    serialize_automatic_plan,
)


def coordinated_plan(
    repository,
    request,
    *,
    kind: str,
    builder: Callable[[], AutomaticPlan],
    cancellation_probe: Callable[[], bool] | None = None,
    poll_seconds: float = 0.1,
    lease_seconds: int = 180,
) -> AutomaticPlan:
    """Build or join exactly one calculation for an immutable input token.

    The durable row deduplicates work across API and runtime processes.  The
    installation lease prevents two different tokens from running CBC at the
    same time on the small controller.  Waiting is cooperative so a preview
    can still be cancelled while it is queued behind automatic planning.
    """
    if not all(
        hasattr(repository, method)
        for method in (
            "claim_planning_calculation",
            "planning_calculation",
            "finish_planning_calculation",
            "acquire_planning_lease",
            "release_planning_lease",
        )
    ):
        # Lightweight integrations and old embedding applications can still
        # provide a planning facade without the durable coordinator.  The
        # production Store always exposes it after schema revision 11.
        return builder()

    token = input_token(request)
    requested_at = request.generated_at
    coordination_started = monotonic()
    claim = repository.claim_planning_calculation(
        token,
        kind=kind,
        requested_at=requested_at,
        lease_seconds=lease_seconds,
    )
    claim, plan = _usable_claim(
        repository,
        claim,
        token=token,
        kind=kind,
        requested_at=requested_at,
        lease_seconds=lease_seconds,
    )
    if plan is not None:
        return plan

    owner = claim.get("owner")
    if claim.get("state") == "waiting":
        owner = _wait_for_calculation(
            repository,
            token,
            cancellation_probe=cancellation_probe,
            poll_seconds=poll_seconds,
        )
        if isinstance(owner, AutomaticPlan):
            return owner
        # The previous owner failed or its lease expired.  Re-enter the claim
        # path; only one caller can become the new owner because the token is
        # unique and the repository locks its row transactionally.
        claim = repository.claim_planning_calculation(
            token,
            kind=kind,
            requested_at=requested_at,
            lease_seconds=lease_seconds,
        )
        claim, plan = _usable_claim(
            repository,
            claim,
            token=token,
            kind=kind,
            requested_at=requested_at,
            lease_seconds=lease_seconds,
        )
        if plan is not None:
            return plan
        owner = claim.get("owner")

    if not owner:
        raise RuntimeError("planning calculation claim returned no owner")

    queue_started = monotonic()
    _acquire_global_lease(
        repository,
        owner,
        token,
        kind=kind,
        cancellation_probe=cancellation_probe,
        poll_seconds=poll_seconds,
        lease_seconds=lease_seconds,
    )
    queue_seconds = monotonic() - queue_started
    try:
        plan = builder()
        if not isinstance(plan, AutomaticPlan):
            # Test doubles and legacy embedders occasionally return a sentinel
            # from the optimizer.  Do not try to persist an object that cannot
            # be losslessly serialized.
            repository.finish_planning_calculation(
                token,
                owner,
                error_detail="planning builder returned an invalid result",
            )
            return plan
        diagnostics = dict(plan.diagnostics)
        diagnostics["coordination"] = {
            "queue_seconds": queue_seconds,
            "total_seconds_before_persistence": monotonic() - coordination_started,
            "joined": False,
        }
        plan = replace(plan, diagnostics=diagnostics)
        finished = repository.finish_planning_calculation(
            token,
            owner,
            result=serialize_automatic_plan(plan),
        )
        if not finished:
            raise RuntimeError("planning calculation ownership was lost before persistence")
        return plan
    except PlanningCancelled:
        repository.finish_planning_calculation(
            token,
            owner,
            error_detail="planning calculation cancelled",
        )
        raise
    except Exception as exc:
        repository.finish_planning_calculation(
            token,
            owner,
            error_detail=str(exc)[:512],
        )
        raise
    finally:
        repository.release_planning_lease(owner)


def _completed_plan(result) -> AutomaticPlan | None:
    if not isinstance(result, dict):
        return None
    try:
        return deserialize_automatic_plan(result)
    except (KeyError, TypeError, ValueError, IndexError):
        # A malformed/stale row must never be activated.  The durable result
        # remains observable for diagnosis, while activation fails closed.
        return None


def _usable_claim(
    repository,
    claim: dict,
    *,
    token: str,
    kind: str,
    requested_at,
    lease_seconds: int,
) -> tuple[dict, AutomaticPlan | None]:
    plan = _completed_plan(claim.get("result"))
    if claim.get("state") != "completed" or plan is not None:
        return claim, plan
    invalidate = getattr(repository, "invalidate_planning_calculation", None)
    if invalidate is None or not invalidate(
        token,
        error_detail="durable planning result failed domain deserialization",
    ):
        raise RuntimeError("durable planning result is malformed")
    replacement = repository.claim_planning_calculation(
        token,
        kind=kind,
        requested_at=requested_at,
        lease_seconds=lease_seconds,
    )
    return replacement, _completed_plan(replacement.get("result"))


def _wait_for_calculation(
    repository,
    token: str,
    *,
    cancellation_probe: Callable[[], bool] | None,
    poll_seconds: float,
):
    while True:
        if cancellation_probe is not None and cancellation_probe():
            raise PlanningCancelled()
        state = repository.planning_calculation(token)
        if state is None:
            return None
        plan = _completed_plan(state.get("result"))
        if state.get("status") == "completed":
            return plan
        if state.get("status") == "error":
            return None
        lease_until = state.get("lease_until")
        if (
            lease_until is not None
            and lease_until <= datetime.now(timezone.utc)
        ):
            return None
        sleep(max(0.01, poll_seconds))


def _acquire_global_lease(
    repository,
    owner: str,
    token: str,
    *,
    kind: str,
    cancellation_probe: Callable[[], bool] | None,
    poll_seconds: float,
    lease_seconds: int,
) -> None:
    renew = getattr(repository, "renew_planning_calculation", None)
    while True:
        if cancellation_probe is not None and cancellation_probe():
            repository.finish_planning_calculation(
                token,
                owner,
                error_detail="planning calculation cancelled while queued",
            )
            raise PlanningCancelled()
        if renew is not None and not renew(
            token,
            owner,
            lease_seconds=lease_seconds,
        ):
            raise RuntimeError("planning calculation ownership expired while queued")
        if repository.acquire_planning_lease(
            owner,
            input_token=token,
            kind=kind,
            lease_seconds=lease_seconds,
        ):
            return
        sleep(max(0.01, poll_seconds))


__all__ = ["coordinated_plan"]
