"""The scheduler across the two daylight-saving transitions.

The installation is configured in a real timezone and the planning horizon is 24
to 48 hours, so twice a year the window contains a day of 23 or 25 hours. The
scheduler builds slots with wall-clock arithmetic (`aligned_start + timedelta`),
which keeps the wall clock tidy and makes the *real* duration of one slot per
transition wrong.

The tests that pass state what the scheduler does hold. The `xfail(strict=True)`
tests record defects that are demonstrated, not hypothetical: remove the marker
when the behaviour is fixed and the suite will tell you it no longer fails.

Spain, both transitions in 2026:

* Sunday 29 March: 02:00 CET -> 03:00 CEST, a 23-hour day.
* Sunday 25 October: 03:00 CEST -> 02:00 CET, a 25-hour day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from dynamic_thermal_charge.models import Heater, OutputConfig, SiteConfig
from dynamic_thermal_charge.scheduler import ChargeScheduler, align_to_slot


MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

SLOT_MINUTES = 30
#: The evening before each transition, so the 24-hour window contains it.
BEFORE_SPRING_FORWARD = datetime(2026, 3, 28, 22, 0, tzinfo=MADRID)
BEFORE_FALL_BACK = datetime(2026, 10, 24, 22, 0, tzinfo=MADRID)


def _site() -> SiteConfig:
    return SiteConfig(
        max_total_power_w=3000,
        slot_minutes=SLOT_MINUTES,
        window_minutes=24 * 60,
    )


def _heaters() -> tuple[Heater, ...]:
    return (
        Heater(
            id="a",
            name="heater a",
            power_w=1000,
            full_charge_minutes=120,
            target_charge=1.0,
            priority=1,
            output=OutputConfig(kind="gpio", pin=1),
        ),
    )


def _plan(start: datetime):
    return ChargeScheduler().build(_site(), _heaters(), start).slots


def _real(value: datetime) -> datetime:
    """The same instant, so two wall clocks can be compared as real time."""
    return value.astimezone(UTC)


# --------------------------------------------------------------------------- #
# What holds across both transitions.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("start", [BEFORE_SPRING_FORWARD, BEFORE_FALL_BACK])
def test_the_window_always_produces_the_configured_number_of_slots(start) -> None:
    assert len(_plan(start)) == 24 * 60 // SLOT_MINUTES


@pytest.mark.parametrize("start", [BEFORE_SPRING_FORWARD, BEFORE_FALL_BACK])
def test_slots_stay_contiguous_on_the_wall_clock(start) -> None:
    slots = _plan(start)

    for previous, following in zip(slots, slots[1:]):
        assert previous.end == following.start


@pytest.mark.parametrize("start", [BEFORE_SPRING_FORWARD, BEFORE_FALL_BACK])
def test_the_first_slot_is_the_aligned_start(start) -> None:
    assert _plan(start)[0].start == align_to_slot(start, SLOT_MINUTES)


# --------------------------------------------------------------------------- #
# Demonstrated defects.
# --------------------------------------------------------------------------- #


@pytest.mark.xfail(
    strict=True,
    reason=(
        "align_to_slot rounds up on the wall clock and returns fold=0, so during "
        "the repeated hour it answers with an instant 45 minutes in the past. The "
        "horizon is then anchored before the current instant, which contradicts "
        "'the window starts at the first slot boundary that has not passed'."
    ),
)
def test_alignment_never_looks_back_during_the_repeated_hour() -> None:
    # 02:15 exists twice on 25 October; fold=1 is the second, CET pass.
    second_pass = datetime(2026, 10, 25, 2, 15, fold=1, tzinfo=MADRID)

    aligned = align_to_slot(second_pass, SLOT_MINUTES)

    assert _real(aligned) >= _real(second_pass)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Slots are built with wall-clock arithmetic, so the slot containing the "
        "fall-back lasts 90 real minutes while allocated_minutes accounts 30. A "
        "heater scheduled there charges for an hour longer than the plan claims."
    ),
)
def test_every_slot_lasts_one_slot_of_real_time_across_the_fall_back() -> None:
    for slot in _plan(BEFORE_FALL_BACK):
        assert _real(slot.end) - _real(slot.start) == timedelta(minutes=SLOT_MINUTES)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Across the spring forward jump the slot containing the transition ends "
        "before it starts in real time, so it can never be active, and it "
        "overlaps the following slot for half an hour. `_desired_outputs` returns "
        "the first matching slot, so which heaters run during that half hour "
        "depends on tuple order rather than on the plan."
    ),
)
def test_every_slot_lasts_one_slot_of_real_time_across_the_spring_forward() -> None:
    for slot in _plan(BEFORE_SPRING_FORWARD):
        assert _real(slot.end) - _real(slot.start) == timedelta(minutes=SLOT_MINUTES)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Two slots overlap in real time across the spring forward jump; see the "
        "test above. The controller resolves the overlap by tuple order."
    ),
)
def test_no_two_slots_cover_the_same_real_instant() -> None:
    slots = _plan(BEFORE_SPRING_FORWARD)
    cursor = _real(slots[0].start)
    finish = _real(slots[-1].end)

    while cursor < finish:
        covering = [
            slot
            for slot in slots
            if _real(slot.start) <= cursor < _real(slot.end)
        ]
        assert len(covering) == 1, f"{cursor} is covered by {len(covering)} slots"
        cursor += timedelta(minutes=10)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A 24-hour window spans 25 real hours across the fall-back and 23 across "
        "the spring forward jump, so the horizon the operator configured is not "
        "the horizon that is planned."
    ),
)
@pytest.mark.parametrize("start", [BEFORE_SPRING_FORWARD, BEFORE_FALL_BACK])
def test_a_24_hour_window_spans_24_real_hours(start) -> None:
    slots = _plan(start)

    assert _real(slots[-1].end) - _real(slots[0].start) == timedelta(hours=24)
