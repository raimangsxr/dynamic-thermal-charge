"""Whether the API may claim the state is current: FR-015 to FR-019, FR-053.

Pure logic, tested as a function. No FastAPI, no database, no real clock. This is
the code that decides whether the API tells the truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dynamic_thermal_charge.api.liveness import (
    CLOCK_SKEW_MARGIN_SECONDS,
    MINIMUM_TOLERANCE_SECONDS,
    POLL_MULTIPLIER,
    evaluate,
    tolerance_for,
)
from dynamic_thermal_charge.persistence import Heartbeat, Liveness


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


def _beat(
    age_seconds: float = 0.0,
    degraded: bool = False,
    poll_seconds: float = 5.0,
    started_offset_hours: float = -1.0,
    runner_id: str = "runner-a",
) -> Heartbeat:
    return Heartbeat(
        updated_at=NOW - timedelta(seconds=age_seconds),
        started_at=NOW + timedelta(hours=started_offset_hours),
        degraded=degraded,
        poll_seconds=poll_seconds,
        driver_kind="gpio",
        runner_id=runner_id,
    )


# --------------------------------------------------------------------------- #
# The tolerance (FR-015)
# --------------------------------------------------------------------------- #

def test_the_tolerance_derives_from_the_cadence_in_the_heartbeat():
    """FR-014: not from the configuration, which the process may predate."""
    assert tolerance_for(_beat(poll_seconds=30.0)) == POLL_MULTIPLIER * 30.0


def test_the_tolerance_has_a_floor():
    """A low cadence must not produce false absences from a brief pause."""
    assert tolerance_for(_beat(poll_seconds=1.0)) == MINIMUM_TOLERANCE_SECONDS


def test_an_override_wins():
    assert tolerance_for(_beat(poll_seconds=60.0), override_seconds=15.0) == 15.0


def test_without_a_heartbeat_the_tolerance_is_the_floor():
    assert tolerance_for(None) == MINIMUM_TOLERANCE_SECONDS


# --------------------------------------------------------------------------- #
# The liveness table (FR-015 to FR-019)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("beat", "expected", "label"),
    [
        (None, Liveness.NEVER_SEEN, "no heartbeat at all"),
        (_beat(0), Liveness.LIVE, "just published"),
        (_beat(29), Liveness.LIVE, "inside the tolerance"),
        (_beat(30), Liveness.LIVE, "exactly at the tolerance"),
        (_beat(31), Liveness.STALE, "past the tolerance"),
        (_beat(3600), Liveness.STALE, "long gone"),
        (_beat(0, degraded=True), Liveness.LIVE_DEGRADED, "alive but degraded"),
        (_beat(31, degraded=True), Liveness.STALE, "degraded and gone: gone wins"),
    ],
)
def test_the_liveness_table(beat, expected, label):
    assert evaluate(beat, NOW).liveness is expected, label


def test_a_longer_cadence_widens_the_window():
    beat = _beat(80, poll_seconds=30.0)  # tolerance 90 s
    assert evaluate(beat, NOW).liveness is Liveness.LIVE


def test_never_seen_is_distinguishable_from_stale():
    """FR-017: 'it never started' is not 'it stopped answering'."""
    never = evaluate(None, NOW)
    stale = evaluate(_beat(9999), NOW)
    assert never.liveness is Liveness.NEVER_SEEN
    assert stale.liveness is Liveness.STALE
    assert never.last_seen_at is None
    assert stale.last_seen_at is not None
    assert never.state_is_current is False and stale.state_is_current is False


def test_only_a_live_controller_makes_the_state_current():
    assert evaluate(_beat(0), NOW).state_is_current is True
    assert evaluate(_beat(0, degraded=True), NOW).state_is_current is True
    assert evaluate(_beat(9999), NOW).state_is_current is False
    assert evaluate(None, NOW).state_is_current is False


def test_the_age_is_reported():
    view = evaluate(_beat(12.5), NOW)
    assert view.age_seconds == pytest.approx(12.5)


# --------------------------------------------------------------------------- #
# FR-019: the clock. The dangerous failure is "current for ever".
# --------------------------------------------------------------------------- #

def test_a_slightly_future_heartbeat_is_ordinary_jitter():
    beat = _beat(-(CLOCK_SKEW_MARGIN_SECONDS - 1))
    assert evaluate(beat, NOW).liveness is Liveness.LIVE


def test_a_heartbeat_well_into_the_future_is_not_current():
    """The clock went backwards. A naive comparison would say 'current for ever'."""
    beat = _beat(-3600)
    view = evaluate(beat, NOW)
    assert view.liveness is Liveness.STALE
    assert view.state_is_current is False


def test_a_clock_jumping_backwards_never_produces_a_permanently_current_state():
    beat = _beat(0)
    # The system clock jumps a day into the past.
    jumped_back = NOW - timedelta(days=1)
    assert evaluate(beat, jumped_back).state_is_current is False


def test_a_clock_jumping_forward_recovers_by_itself():
    jumped_forward = NOW + timedelta(hours=2)
    assert evaluate(_beat(0), jumped_forward).liveness is Liveness.STALE
    # The next heartbeat, published against the new clock, restores it.
    fresh = Heartbeat(
        updated_at=jumped_forward,
        started_at=NOW,
        degraded=False,
        poll_seconds=5.0,
        driver_kind="gpio",
        runner_id="runner-a",
    )
    assert evaluate(fresh, jumped_forward).liveness is Liveness.LIVE


# --------------------------------------------------------------------------- #
# FR-053: more than one controller
# --------------------------------------------------------------------------- #

def test_a_stable_runner_means_a_single_controller():
    beat = _beat(0)
    assert evaluate(beat, NOW, previous=beat).multiple_controllers_suspected is False


def test_a_clean_restart_is_not_suspicious():
    """A new runner whose start instant is LATER is just a restart."""
    previous = _beat(0, started_offset_hours=-3, runner_id="runner-a")
    restarted = _beat(0, started_offset_hours=-1, runner_id="runner-b")
    view = evaluate(restarted, NOW, previous=previous)
    assert view.multiple_controllers_suspected is False


def test_a_start_instant_moving_backwards_is_flagged():
    """A process that started earlier cannot publish after a newer one."""
    previous = _beat(0, started_offset_hours=-1, runner_id="runner-b")
    older = _beat(0, started_offset_hours=-5, runner_id="runner-a")
    view = evaluate(older, NOW, previous=previous)
    assert view.multiple_controllers_suspected is True


def test_runners_alternating_are_flagged():
    a = _beat(0, started_offset_hours=-5, runner_id="runner-a")
    b = _beat(0, started_offset_hours=-1, runner_id="runner-b")
    # b then a: the older process publishing after the newer one.
    assert evaluate(a, NOW, previous=b).multiple_controllers_suspected is True


def test_the_flag_does_not_make_the_state_stale():
    """The information is as valid as before; the reader just needs to know."""
    previous = _beat(0, started_offset_hours=-1, runner_id="runner-b")
    older = _beat(0, started_offset_hours=-5, runner_id="runner-a")
    view = evaluate(older, NOW, previous=previous)
    assert view.multiple_controllers_suspected is True
    assert view.liveness is Liveness.LIVE
    assert view.state_is_current is True


def test_the_first_read_cannot_suspect_anything():
    assert evaluate(_beat(0), NOW, previous=None).multiple_controllers_suspected is False
