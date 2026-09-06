"""Deterministic slot-based charge scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Mapping, Sequence

from .models import Heater, SiteConfig
from .weather import HourlyForecastPoint


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleSlot:
    start: datetime
    end: datetime
    heater_ids: tuple[str, ...]
    total_power_w: int
    temperature_c: float | None = None
    temperature_interpolated: bool = False


@dataclass(frozen=True)
class ScheduleResult:
    slots: tuple[ScheduleSlot, ...]
    allocated_minutes: dict[str, int]
    unmet_minutes: dict[str, int]


class ChargeScheduler:
    """Allocate complete slots, giving constrained capacity to higher priorities."""

    def build(
        self,
        site: SiteConfig,
        heaters: tuple[Heater, ...],
        start: datetime,
        requested_charge_minutes: Mapping[str, int] | None = None,
        hourly_points: Sequence[HourlyForecastPoint] | None = None,
        fallback_temperature_c: float | None = None,
    ) -> ScheduleResult:
        aligned_start = align_to_slot(start, site.slot_minutes)
        if aligned_start != start:
            logger.info(
                "Aligned planning start from %s to %s",
                start.isoformat(timespec="seconds"),
                aligned_start.isoformat(timespec="minutes"),
            )
        enabled = tuple(heater for heater in heaters if heater.enabled)
        logger.info(
            "Building %d-minute charge plan for %d enabled heaters with %d W limit",
            site.window_minutes,
            len(enabled),
            site.max_total_power_w,
        )
        requested_slots = {
            heater.id: _ceil_div(
                (
                    requested_charge_minutes[heater.id]
                    if requested_charge_minutes is not None
                    and heater.id in requested_charge_minutes
                    else heater.requested_charge_minutes
                ),
                site.slot_minutes,
            )
            for heater in enabled
        }
        if any(count < 0 for count in requested_slots.values()):
            raise ValueError("requested charge minutes cannot be negative")
        logger.debug("Requested slots by heater: %s", requested_slots)
        remaining = requested_slots.copy()
        allocated = {heater.id: 0 for heater in enabled}
        # The window length is wall-clock; the number of slots that fits in it is
        # not fixed, because a day can be 23 or 25 hours long.
        boundaries = slot_boundaries(
            aligned_start, site.window_minutes, site.slot_minutes
        )
        total_slots = len(boundaries) - 1
        requested_power_slots = sum(
            heater.power_w * requested_slots[heater.id] for heater in enabled
        )
        capacity_constrained = (
            requested_power_slots > site.max_total_power_w * total_slots
        )
        logger.debug(
            "Scheduling mode: %s",
            "priority" if capacity_constrained else "balanced",
        )
        slot_weather = {
            slot_index: _temperature_for_slot(
                boundaries[slot_index],
                boundaries[slot_index + 1],
                hourly_points or (),
                fallback_temperature_c,
            )
            for slot_index in range(total_slots)
        }
        # Planning remains chronological when no detailed weather is available.
        # With detailed weather, cold slots are consumed first; the index is the
        # final tie-breaker and makes equal temperatures reproducible.
        slot_order = tuple(
            sorted(
                range(total_slots),
                key=lambda index: (
                    slot_weather[index][0] is None,
                    float("inf") if slot_weather[index][0] is None else slot_weather[index][0],
                    index,
                ),
            )
        )
        slots_by_index: dict[int, ScheduleSlot] = {}
        for order_index, slot_index in enumerate(slot_order):
            used_power = 0
            selected: list[str] = []
            slots_left = total_slots - order_index
            candidates = tuple(
                heater for heater in enabled if remaining[heater.id] > 0
            )
            if capacity_constrained:
                candidates = tuple(
                    sorted(
                        candidates,
                        key=lambda heater: (
                            -heater.priority,
                            -remaining[heater.id],
                            heater.id,
                        ),
                    )
                )
            else:
                candidates = tuple(
                    sorted(
                        candidates,
                        key=lambda heater: (
                            -(remaining[heater.id] / slots_left),
                            -heater.priority,
                            heater.id,
                        ),
                    )
                )
            for heater in candidates:
                if used_power + heater.power_w <= site.max_total_power_w:
                    selected.append(heater.id)
                    used_power += heater.power_w
                    remaining[heater.id] -= 1
                    allocated[heater.id] += 1

            slot_start = boundaries[slot_index]
            temperature_c, interpolated = slot_weather[slot_index]
            slots_by_index[slot_index] = ScheduleSlot(
                start=slot_start,
                # Taken from the boundary list rather than recomputed, so slots
                # stay contiguous even where a slot had to be shortened.
                end=boundaries[slot_index + 1],
                heater_ids=tuple(selected),
                total_power_w=used_power,
                temperature_c=temperature_c,
                temperature_interpolated=interpolated,
            )
            logger.debug(
                "Slot %s: selected=%s power_w=%d",
                slot_start.isoformat(timespec="minutes"),
                selected,
                used_power,
            )

        # Derived from the real duration of the slots each heater occupies, not
        # from the slot count times the nominal length. The two agree while every
        # slot is exactly `slot_minutes` long, which is the guarantee the
        # boundary generator provides; deriving it keeps the published figure
        # honest if a slot ever has to be shortened.
        allocated_minutes = {
            heater.id: sum(
                round(
                    (slot.end.astimezone(timezone.utc) - slot.start.astimezone(timezone.utc)).total_seconds() / 60
                )
                if slot.start.tzinfo is not None
                else round((slot.end - slot.start).total_seconds() / 60)
                for slot in slots_by_index.values()
                if heater.id in slot.heater_ids
            )
            for heater in enabled
        }
        unmet_minutes = {
            heater_id: count * site.slot_minutes
            for heater_id, count in remaining.items()
            if count > 0
        }
        if unmet_minutes:
            logger.warning("Unmet charge demand (minutes): %s", unmet_minutes)
        logger.info(
            "Charge plan built: %d slots, allocated_minutes=%s, unmet_minutes=%s",
            len(slots_by_index),
            allocated_minutes,
            unmet_minutes,
        )
        slots = [slots_by_index[index] for index in range(total_slots)]
        return ScheduleResult(tuple(slots), allocated_minutes, unmet_minutes)


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def advance_real(value: datetime, minutes: int) -> datetime:
    """Advance an instant by real elapsed time, not by wall-clock arithmetic.

    ``aware + timedelta`` adds to the *wall clock* and keeps the same tzinfo, so
    across a daylight-saving transition it produces an instant that is not the
    one the caller meant: 45 minutes in the past during the repeated hour, and a
    boundary that moves backwards across the spring jump. Converting to UTC first
    makes the addition mean what it says.
    """
    zone = value.tzinfo
    if zone is None:
        # Without a zone there is no daylight saving, so the wall clock *is* real
        # time. Naive input stays supported and keeps its previous behaviour.
        return value + timedelta(minutes=minutes)
    return (value.astimezone(timezone.utc) + timedelta(minutes=minutes)).astimezone(zone)


def _earlier(left: datetime, right: datetime) -> bool:
    """Whether ``left`` happens before ``right`` in real time.

    ``<`` between two aware datetimes that share a tzinfo compares their **wall
    clocks** and ignores ``fold``, so during the repeated hour it reports the
    second pass as later than an instant that actually follows it. Every
    comparison here is about real time, so every comparison converts first.
    """
    if left.tzinfo is None or right.tzinfo is None:
        return left < right
    return left.astimezone(timezone.utc) < right.astimezone(timezone.utc)


def _normalize(value: datetime) -> datetime:
    """Give an instant the wall clock it really has.

    Attaching a zone with ``.replace(tzinfo=...)`` can name a time that never
    happens: on the day the clocks go forward, 02:15 does not exist, and Python
    keeps the label while resolving the offset to the pre-jump one. Left alone,
    that label then poisons any later wall-clock arithmetic -- a 45-minute window
    from a non-existent 02:15 ended up *before* its own start, and produced an
    empty plan. A round trip through UTC replaces the label with the real one.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).astimezone(value.tzinfo)


def _wall_minutes(value: datetime) -> int:
    return value.hour * 60 + value.minute


def _on_boundary(value: datetime, slot_minutes: int) -> bool:
    return (
        value.second == 0
        and value.microsecond == 0
        and _wall_minutes(value) % slot_minutes == 0
    )


def _floor_to_wall_boundary(value: datetime, slot_minutes: int) -> datetime:
    """The wall-clock boundary at or before ``value``, resolved to an instant."""
    floored = (_wall_minutes(value) // slot_minutes) * slot_minutes
    naive_midnight = value.replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return _normalize(
        (naive_midnight + timedelta(minutes=floored)).replace(tzinfo=value.tzinfo)
    )


def next_slot_boundary(current: datetime, slot_minutes: int) -> datetime:
    """The next wall-clock slot boundary strictly after ``current``.

    Advancing in real time keeps boundaries strictly increasing without any
    special case for the hour that happens twice or the hour that never happens.
    The wall clock stays aligned because a zone's offset shift is a whole hour in
    every supported installation, a multiple of any configurable slot length. A
    zone that shifts by less than one slot (Lord Howe shifts 30 minutes) is
    re-aligned forward instead, which shortens that one slot.
    """
    candidate = advance_real(current, slot_minutes)
    if _on_boundary(candidate, slot_minutes):
        return candidate
    snapped = advance_real(
        _floor_to_wall_boundary(candidate, slot_minutes), slot_minutes
    )
    while not _earlier(current, snapped) or not _on_boundary(snapped, slot_minutes):
        snapped = advance_real(snapped, slot_minutes)
    return snapped


def slot_boundaries(
    aligned_start: datetime, window_minutes: int, slot_minutes: int
) -> tuple[datetime, ...]:
    """Every boundary of the window, including its end.

    The window length is counted on the **wall clock**, so a 24-hour window
    covers 25 real hours on the day the clocks go back and 23 on the day they go
    forward, with one slot more or two fewer respectively.
    """
    naive_end = aligned_start.replace(tzinfo=None) + timedelta(minutes=window_minutes)
    window_end = _normalize(naive_end.replace(tzinfo=aligned_start.tzinfo))
    boundaries = [aligned_start]
    while _earlier(boundaries[-1], window_end):
        boundaries.append(next_slot_boundary(boundaries[-1], slot_minutes))
    return tuple(boundaries)


def align_to_slot(value: datetime, slot_minutes: int) -> datetime:
    """The first wall-clock slot boundary that has not passed.

    "Has not passed" is decided in real time. During the repeated hour the wall
    clock alone is ambiguous, and the previous implementation resolved it to the
    first pass, answering with an instant already in the past.
    """
    candidate = _floor_to_wall_boundary(value, slot_minutes)
    while _earlier(candidate, value):
        candidate = next_slot_boundary(candidate, slot_minutes)
    return candidate


def _temperature_for_slot(
    start: datetime,
    end: datetime,
    points: Sequence[HourlyForecastPoint],
    fallback_temperature_c: float | None,
) -> tuple[float | None, bool]:
    usable = tuple(
        point for point in points if start <= point.timestamp < end
    )
    if usable:
        return sum(point.temperature_c for point in usable) / len(usable), any(
            point.interpolated for point in usable
        )
    if fallback_temperature_c is not None:
        return fallback_temperature_c, True
    return None, False
