"""Whether the API may present the output state as current.

Kept **pure**: no FastAPI, no data access, no clock of its own. This is the logic
that decides whether the API tells the truth, so it deserves to be tested as a
function rather than through an HTTP request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..persistence import Heartbeat, Liveness


#: The controller may simply be busy; three polling cycles is generous.
POLL_MULTIPLIER = 3
#: Floor, so a very low polling cadence does not produce false absences from a
#: garbage-collection pause or a slow write.
MINIMUM_TOLERANCE_SECONDS = 30.0
#: A heartbeat dated slightly ahead is ordinary clock jitter between two hosts.
CLOCK_SKEW_MARGIN_SECONDS = 5.0


@dataclass(frozen=True)
class ControllerView:
    """What the API knows about the controller, and how much it may claim."""

    liveness: Liveness
    last_seen_at: datetime | None
    age_seconds: float | None
    started_at: datetime | None
    degraded: bool
    driver_kind: str | None
    tolerance_seconds: float | None
    multiple_controllers_suspected: bool = False

    @property
    def state_is_current(self) -> bool:
        return self.liveness.state_is_current


def tolerance_for(
    heartbeat: Heartbeat | None, override_seconds: float | None = None
) -> float:
    """How old a heartbeat may be before the state stops being current.

    Derived from the cadence carried **in the heartbeat**, not from the stored
    configuration: the controller may have started before the last edit, and the
    tolerance has to match the process that is actually running.
    """
    if override_seconds is not None:
        return float(override_seconds)
    if heartbeat is None:
        return MINIMUM_TOLERANCE_SECONDS
    return max(
        POLL_MULTIPLIER * float(heartbeat.poll_seconds), MINIMUM_TOLERANCE_SECONDS
    )


def evaluate(
    heartbeat: Heartbeat | None,
    now: datetime,
    override_seconds: float | None = None,
    previous: Heartbeat | None = None,
) -> ControllerView:
    """Decide what may be claimed about the controller right now."""
    tolerance = tolerance_for(heartbeat, override_seconds)
    if heartbeat is None:
        return ControllerView(
            liveness=Liveness.NEVER_SEEN,
            last_seen_at=None,
            age_seconds=None,
            started_at=None,
            degraded=False,
            driver_kind=None,
            tolerance_seconds=tolerance,
        )

    age = (now - heartbeat.updated_at).total_seconds()
    suspected = _suspects_two_controllers(heartbeat, previous)

    if age < -CLOCK_SKEW_MARGIN_SECONDS:
        # A heartbeat from the future. If the clock went backwards -- and the
        # Raspberry Pi has no battery-backed clock, so this happens on every boot
        # before time sync -- a naive comparison would report "current" for ever,
        # and the API would claim its information is fresh with no proof at all.
        # Resolve towards the honest answer.
        liveness = Liveness.STALE
    elif age > tolerance:
        liveness = Liveness.STALE
    elif heartbeat.degraded:
        liveness = Liveness.LIVE_DEGRADED
    else:
        liveness = Liveness.LIVE

    return ControllerView(
        liveness=liveness,
        last_seen_at=heartbeat.updated_at,
        age_seconds=age,
        started_at=heartbeat.started_at,
        degraded=heartbeat.degraded,
        driver_kind=heartbeat.driver_kind,
        tolerance_seconds=tolerance,
        multiple_controllers_suspected=suspected,
    )


def _suspects_two_controllers(
    heartbeat: Heartbeat, previous: Heartbeat | None
) -> bool:
    """Detect more than one controller sharing the single heartbeat row (FR-053).

    Two processes conmuting the same relays is an electrical hazard, and the worst
    possible outcome is a panel showing normality. The signals:

    * ``started_at`` moving **backwards**: a process that started earlier cannot
      begin publishing after a newer one unless both are alive.
    * ``runner_id`` alternating between two values across consecutive reads.

    The API only flags it. It does not arbitrate, does not stop anyone, and does
    not mark the state stale: the information is as valid as before, but whoever
    reads it needs to know there are two hands on the same relays.
    """
    if previous is None:
        return False
    if heartbeat.runner_id == previous.runner_id:
        return False
    return heartbeat.started_at < previous.started_at


__all__ = [
    "CLOCK_SKEW_MARGIN_SECONDS",
    "MINIMUM_TOLERANCE_SECONDS",
    "POLL_MULTIPLIER",
    "ControllerView",
    "evaluate",
    "tolerance_for",
]
