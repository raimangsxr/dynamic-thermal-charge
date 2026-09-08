"""Global calendar projection of contiguous charge intervals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import DynamicThermalChargeCoordinator
from .entity import DynamicThermalChargeEntity, controller_entity_unique_id


class GlobalChargeCalendar(DynamicThermalChargeEntity, CalendarEntity):
    _attr_translation_key = "global_calendar"

    def __init__(self, coordinator: DynamicThermalChargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = controller_entity_unique_id(coordinator, "calendar")
        self._attr_device_info = self.installation_device_info

    @property
    def event(self) -> CalendarEvent | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        now = dt_util.utcnow()
        events = _events(snapshot, now, now.replace(year=now.year + 1))
        return next((item for item in events if item.start <= now < item.end), None)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        snapshot = self._snapshot
        if snapshot is None:
            return []
        return _events(snapshot, start_date, end_date)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities) -> None:
    coordinator: DynamicThermalChargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GlobalChargeCalendar(coordinator)])


def _events(
    snapshot: dict[str, Any],
    start_date: datetime,
    end_date: datetime,
) -> list[CalendarEvent]:
    plan = snapshot.get("plan")
    if not plan:
        return []
    names = {
        str(item["id"]): str(item.get("name", item["id"]))
        for item in snapshot.get("accumulators", ())
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for interval in plan.get("intervals", ()):
        start = _parse(interval.get("start"))
        end = _parse(interval.get("end"))
        if start is None or end is None or end <= start:
            continue
        if end <= start_date or start >= end_date:
            continue
        grouped.setdefault(str(interval["accumulator_id"]), []).append(
            {**interval, "start": start, "end": end}
        )
    events: list[CalendarEvent] = []
    for accumulator_id, intervals in grouped.items():
        intervals.sort(key=lambda item: item["start"])
        merged: list[dict[str, Any]] = []
        for interval in intervals:
            if merged and merged[-1]["end"] == interval["start"]:
                merged[-1]["end"] = interval["end"]
                merged[-1]["planned_energy_kwh"] = _sum(
                    merged[-1].get("planned_energy_kwh"),
                    interval.get("planned_energy_kwh"),
                )
                merged[-1]["target_soc_percent"] = interval.get(
                    "target_soc_percent", merged[-1].get("target_soc_percent")
                )
            else:
                merged.append(dict(interval))
        for position, interval in enumerate(merged):
            initial = interval.get("initial_soc_percent")
            target = interval.get("target_soc_percent")
            energy = interval.get("planned_energy_kwh")
            description = _description(initial, target, energy)
            events.append(
                CalendarEvent(
                    start=interval["start"],
                    end=interval["end"],
                    summary=names.get(accumulator_id, accumulator_id),
                    description=description,
                    uid=f"{snapshot['installation']['id']}:{accumulator_id}:{position}:{interval['start'].isoformat()}",
                )
            )
    return sorted(events, key=lambda event: (event.start, event.end, event.summary))


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None if value is None else dt_util.parse_datetime(str(value))


def _sum(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(left) + float(right)


def _description(initial: Any, target: Any, energy: Any) -> str:
    parts: list[str] = []
    if initial is not None or target is not None:
        parts.append(f"SOC {initial if initial is not None else '?'}% → {target if target is not None else '?'}%")
    if energy is not None:
        parts.append(f"{float(energy):.2f} kWh")
    return "; ".join(parts)
