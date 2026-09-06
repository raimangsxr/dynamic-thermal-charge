"""The scheduler across the two daylight-saving transitions.

The installation is configured in a real timezone and the planning horizon is 24
to 48 hours, so twice a year the window contains a day of 23 or 25 hours. The
scheduler builds slots with wall-clock arithmetic (`aligned_start + timedelta`),
which keeps the wall clock tidy and makes the *real* duration of one slot per
transition wrong.

Boundaries advance in absolute time, so they stay strictly increasing and every
slot lasts exactly `slot_minutes` of real time. The wall clock stays tidy because
the offset shift is a whole hour, a multiple of every configurable slot length.
The consequence, accepted deliberately: a 24-hour window covers 25 real hours on
the day the clocks go back and 23 on the day they go forward.

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


def test_alignment_never_looks_back_during_the_repeated_hour() -> None:
    # 02:15 exists twice on 25 October; fold=1 is the second, CET pass.
    second_pass = datetime(2026, 10, 25, 2, 15, fold=1, tzinfo=MADRID)

    aligned = align_to_slot(second_pass, SLOT_MINUTES)

    assert _real(aligned) >= _real(second_pass)


@pytest.mark.parametrize("start", [BEFORE_SPRING_FORWARD, BEFORE_FALL_BACK])
def test_every_slot_lasts_one_slot_of_real_time(start) -> None:
    for slot in _plan(start):
        assert _real(slot.end) - _real(slot.start) == timedelta(minutes=SLOT_MINUTES)


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


@pytest.mark.parametrize(
    "start,expected_slots,real_hours",
    [(BEFORE_SPRING_FORWARD, 46, 23), (BEFORE_FALL_BACK, 50, 25)],
)
def test_a_24_wall_clock_hour_window_covers_the_real_length_of_the_day(
    start, expected_slots, real_hours
) -> None:
    slots = _plan(start)

    assert len(slots) == expected_slots
    assert _real(slots[-1].end) - _real(slots[0].start) == timedelta(hours=real_hours)


# --------------------------------------------------------------------------- #
# The MILP planner, which is the one that plans in production.
# --------------------------------------------------------------------------- #


def _hourly_wall_clock_forecast(
    first_wall: datetime, hours: int, temperature: float = 4.0
) -> tuple:
    """One point per wall-clock hour, the way an hourly provider publishes.

    On the day the clocks go back the repeated hour therefore has a single
    point, which both of its passes have to share.
    """
    from dynamic_thermal_charge.weather import HourlyForecastPoint

    points = []
    seen = set()
    wall = first_wall.replace(tzinfo=None)
    for _ in range(hours + 4):
        marker = (wall.date(), wall.hour)
        if marker not in seen:
            seen.add(marker)
            points.append(
                HourlyForecastPoint(
                    timestamp=wall.replace(tzinfo=MADRID), temperature_c=temperature
                )
            )
        wall += timedelta(hours=1)
    return tuple(points)


def _planning_request(start: datetime, horizon_hours: int = 24):
    from dynamic_thermal_charge.charge_planning import PlanningInput
    from dynamic_thermal_charge.models import ChargeTelemetry, Heater, OutputConfig

    item = Heater(
        id="a",
        name="a",
        power_w=2000,
        full_charge_minutes=4 * 60,
        target_charge=1,
        priority=1,
        output=OutputConfig(),
    )
    telemetry = ChargeTelemetry("a", 19.0, 21.0, 0.0, start, start, start)
    return PlanningInput(
        heaters=(item,),
        telemetry={"a": telemetry},
        constraints=(),
        forecast=_hourly_wall_clock_forecast(start, horizon_hours),
        horizon_start=start,
        horizon_hours=horizon_hours,
        slot_minutes=SLOT_MINUTES,
        max_total_power_w=5200,
        timezone_name="Europe/Madrid",
    )


@pytest.mark.parametrize(
    "start,expected_slots",
    [(BEFORE_SPRING_FORWARD, 46), (BEFORE_FALL_BACK, 50)],
)
def test_the_optimizer_plans_the_real_length_of_a_transition_day(
    start, expected_slots
) -> None:
    from dynamic_thermal_charge.charge_planning import INVALID, MilpChargePlanner

    plan = MilpChargePlanner().build(_planning_request(start))

    # A fixed slot-count guard used to reject exactly these two days, which left
    # the installation with no plan at all once a year.
    assert plan.status != INVALID
    assert len(plan.slots) == expected_slots
    for slot in plan.slots:
        assert _real(slot.end) - _real(slot.start) == timedelta(minutes=SLOT_MINUTES)
    for previous, following in zip(plan.slots, plan.slots[1:]):
        assert previous.end == following.start


def test_both_passes_of_the_repeated_hour_get_that_hours_forecast() -> None:
    from dynamic_thermal_charge.charge_planning import MilpChargePlanner

    plan = MilpChargePlanner().build(_planning_request(BEFORE_FALL_BACK))

    repeated = [
        slot
        for slot in plan.slots
        if slot.start.hour == 2 and slot.start.date() == datetime(2026, 10, 25).date()
    ]
    # 02:00 and 02:30 each happen twice, so four slots share two forecast hours.
    assert len(repeated) == 4
    assert all(slot.outdoor_temperature_c is not None for slot in repeated)
