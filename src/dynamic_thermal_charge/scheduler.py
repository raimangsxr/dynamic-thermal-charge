"""Deterministic slot-based charge scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import math
from typing import Mapping

from .models import Heater, SiteConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleSlot:
    start: datetime
    end: datetime
    heater_ids: tuple[str, ...]
    total_power_w: int


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
        slots: list[ScheduleSlot] = []

        total_slots = site.window_minutes // site.slot_minutes
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
        for slot_index in range(total_slots):
            used_power = 0
            selected: list[str] = []
            slots_left = total_slots - slot_index
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

            slot_start = aligned_start + timedelta(
                minutes=slot_index * site.slot_minutes
            )
            slots.append(
                ScheduleSlot(
                    start=slot_start,
                    end=slot_start + timedelta(minutes=site.slot_minutes),
                    heater_ids=tuple(selected),
                    total_power_w=used_power,
                )
            )
            logger.debug(
                "Slot %s: selected=%s power_w=%d",
                slot_start.isoformat(timespec="minutes"),
                selected,
                used_power,
            )

        allocated_minutes = {
            heater_id: count * site.slot_minutes for heater_id, count in allocated.items()
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
            len(slots),
            allocated_minutes,
            unmet_minutes,
        )
        return ScheduleResult(tuple(slots), allocated_minutes, unmet_minutes)


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def align_to_slot(value: datetime, slot_minutes: int) -> datetime:
    """Round a datetime up to the next wall-clock slot boundary."""
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = (value - midnight).total_seconds()
    slot_seconds = slot_minutes * 60
    elapsed_slots = math.ceil(elapsed_seconds / slot_seconds)
    return midnight + timedelta(seconds=elapsed_slots * slot_seconds)
