"""Property-based invariants of the slot scheduler.

The scheduler is deterministic and pure, which makes it the one part of the
planner where a property is cheaper and stronger than an example. These are the
promises the rest of the system relies on: never exceed the contracted power,
tile the window exactly once, and never allocate more charge than was asked for.

Examples answer "does it work for this installation". These answer "can it be
made to break at all".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings, strategies as st

from dynamic_thermal_charge.models import Heater, OutputConfig, SiteConfig
from dynamic_thermal_charge.scheduler import ChargeScheduler, align_to_slot


MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")


def _wall_plus(value: datetime, minutes: int) -> datetime:
    """Advance a wall clock by `minutes`, then resolve back to an instant."""
    naive = value.replace(tzinfo=None) + timedelta(minutes=minutes)
    return naive.replace(tzinfo=value.tzinfo)

#: Divisors of 60 keep slots aligned to the wall clock, which is what the
#: installation actually configures.
SLOT_MINUTES = st.sampled_from([15, 20, 30, 60])

#: Spain 2026: clocks go forward on 29 March and back on 25 October. The day
#: before each is included so a 24-hour window contains the transition.
TRANSITION_DAYS = [
    datetime(2026, 3, 28).date(),
    datetime(2026, 3, 29).date(),
    datetime(2026, 10, 24).date(),
    datetime(2026, 10, 25).date(),
]


def _heater(index: int, power_w: int, minutes: int, priority: int) -> Heater:
    return Heater(
        id=f"h{index}",
        name=f"heater {index}",
        power_w=power_w,
        full_charge_minutes=minutes,
        target_charge=1.0,
        priority=priority,
        output=OutputConfig(kind="gpio", pin=index + 1),
    )


@st.composite
def installations(draw):
    """A plausible installation and planning window."""
    slot_minutes = draw(SLOT_MINUTES)
    slots_in_window = draw(st.integers(min_value=1, max_value=48))
    heater_count = draw(st.integers(min_value=1, max_value=5))
    heaters = tuple(
        _heater(
            index,
            power_w=draw(st.integers(min_value=100, max_value=4000)),
            minutes=draw(st.integers(min_value=1, max_value=600)),
            priority=draw(st.integers(min_value=0, max_value=5)),
        )
        for index in range(heater_count)
    )
    site = SiteConfig(
        max_total_power_w=draw(st.integers(min_value=100, max_value=12000)),
        slot_minutes=slot_minutes,
        window_minutes=slot_minutes * slots_in_window,
    )
    # Two days out of 365 are the interesting ones, and uniform sampling finds
    # them only by luck. The transition days are drawn explicitly so every
    # property actually exercises them, alongside ordinary dates.
    day = draw(
        st.one_of(
            st.sampled_from(TRANSITION_DAYS),
            st.dates(
                min_value=datetime(2026, 1, 1).date(),
                max_value=datetime(2026, 12, 31).date(),
            ),
        )
    )
    start = datetime.combine(
        day, draw(st.times()).replace(microsecond=0), tzinfo=MADRID
    )
    return site, heaters, start


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


@given(installations())
@settings(max_examples=200, deadline=None)
def test_no_slot_ever_exceeds_the_contracted_power(installation) -> None:
    site, heaters, start = installation

    result = ChargeScheduler().build(site, heaters, start)

    powers = {heater.id: heater.power_w for heater in heaters}
    for slot in result.slots:
        assert slot.total_power_w <= site.max_total_power_w
        # The published figure must match what the slot actually switches on.
        assert slot.total_power_w == sum(powers[hid] for hid in slot.heater_ids)


@given(installations())
@settings(max_examples=200, deadline=None)
def test_the_window_is_tiled_exactly_once_in_chronological_order(installation) -> None:
    site, heaters, start = installation

    result = ChargeScheduler().build(site, heaters, start)

    aligned = align_to_slot(start, site.slot_minutes)
    assert result.slots[0].start == aligned
    for slot in result.slots:
        # Real duration, not wall-clock: across a transition the two differ.
        assert slot.end.astimezone(UTC) - slot.start.astimezone(UTC) == timedelta(
            minutes=site.slot_minutes
        )
        minutes_since_midnight = slot.start.hour * 60 + slot.start.minute
        assert minutes_since_midnight % site.slot_minutes == 0
    # Contiguous, non-overlapping and strictly increasing in real time.
    for previous, following in zip(result.slots, result.slots[1:]):
        assert previous.end == following.start
        assert following.start.astimezone(UTC) > previous.start.astimezone(UTC)
    # The horizon is counted on the wall clock, so it ends where wall-clock
    # arithmetic says it does even when that spans 23 or 25 real hours. The
    # comparison is by instant: when wall-clock arithmetic lands on a time that
    # never existed, the scheduler labels the same moment with the wall clock
    # that does exist (02:00 CET becomes 03:00 CEST).
    expected_end = _wall_plus(aligned, site.window_minutes)
    assert result.slots[-1].end.astimezone(UTC) == expected_end.astimezone(UTC)


@given(installations())
@settings(max_examples=200, deadline=None)
def test_only_enabled_heaters_are_scheduled_and_never_twice_in_one_slot(
    installation,
) -> None:
    site, heaters, start = installation

    result = ChargeScheduler().build(site, heaters, start)

    allowed = {heater.id for heater in heaters if heater.enabled}
    for slot in result.slots:
        assert set(slot.heater_ids) <= allowed
        assert len(slot.heater_ids) == len(set(slot.heater_ids))


@given(installations())
@settings(max_examples=200, deadline=None)
def test_allocated_and_unmet_account_for_exactly_what_was_requested(
    installation,
) -> None:
    site, heaters, start = installation

    result = ChargeScheduler().build(site, heaters, start)

    for heater in heaters:
        requested = (
            _ceil_div(heater.requested_charge_minutes, site.slot_minutes)
            * site.slot_minutes
        )
        allocated = result.allocated_minutes[heater.id]
        unmet = result.unmet_minutes.get(heater.id, 0)
        assert allocated + unmet == requested
        assert allocated <= requested
        assert unmet >= 0


@given(installations())
@settings(max_examples=200, deadline=None)
def test_allocated_minutes_match_the_published_slots(installation) -> None:
    site, heaters, start = installation

    result = ChargeScheduler().build(site, heaters, start)

    for heater in heaters:
        occupied = sum(1 for slot in result.slots if heater.id in slot.heater_ids)
        assert result.allocated_minutes[heater.id] == occupied * site.slot_minutes


@given(installations())
@settings(max_examples=100, deadline=None)
def test_the_same_inputs_always_produce_the_same_plan(installation) -> None:
    site, heaters, start = installation

    first = ChargeScheduler().build(site, heaters, start)
    second = ChargeScheduler().build(site, heaters, start)

    assert first == second


# --------------------------------------------------------------------------- #
# `align_to_slot` on its own.
# --------------------------------------------------------------------------- #


@given(
    st.datetimes(
        min_value=datetime(2026, 6, 1), max_value=datetime(2026, 8, 31)
    ),
    SLOT_MINUTES,
)
def test_alignment_is_idempotent_and_never_looks_back(value, slot_minutes) -> None:
    at = value.replace(tzinfo=MADRID)

    aligned = align_to_slot(at, slot_minutes)

    assert aligned >= at
    assert align_to_slot(aligned, slot_minutes) == aligned
    # It never skips a whole slot, so no usable capacity is thrown away.
    assert aligned - at < timedelta(minutes=slot_minutes)


@given(
    st.datetimes(
        min_value=datetime(2026, 6, 1), max_value=datetime(2026, 8, 31)
    ),
    SLOT_MINUTES,
)
def test_alignment_lands_on_a_wall_clock_slot_boundary(value, slot_minutes) -> None:
    at = value.replace(tzinfo=MADRID)

    aligned = align_to_slot(at, slot_minutes)

    minutes_since_midnight = aligned.hour * 60 + aligned.minute
    assert minutes_since_midnight % slot_minutes == 0
    assert aligned.second == 0 and aligned.microsecond == 0
