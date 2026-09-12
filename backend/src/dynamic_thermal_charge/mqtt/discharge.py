"""Resolve the discharge command of each accumulator from the active plan.

The command enables or disables the discharge; it is not an order to open the
damper.  The accumulator's own thermostat modulates its damper against the
published setpoint, closing it when the room reaches the target and opening it
again as the room cools, until the command disables the discharge at the end of
the window.  A closed damper reported by telemetry while the discharge is
enabled is therefore normal and never a discrepancy.

Nothing here touches MQTT or the database: the caller supplies the durable
active plan and the control evidence, and this module decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .topics import resolve_accumulator_topics


# Below this the projected heat is solver noise, not an intention to emit.
HEAT_EPSILON_KWH = 1e-6

ON = "ON"
OFF = "OFF"
NO_SETPOINT = "NULL"


@dataclass(frozen=True)
class DischargeCommand:
    """What to publish for one accumulator in this cycle."""

    heater_id: str
    enabled: bool
    setpoint_c: float | None
    damper_topic: str | None
    setpoint_topic: str | None

    @property
    def payload(self) -> str:
        return ON if self.enabled else OFF

    @property
    def setpoint_payload(self) -> str | None:
        """A decimal target, or the explicit no-target sentinel when off."""
        if self.setpoint_topic is None:
            return None
        if not self.enabled or self.setpoint_c is None:
            return NO_SETPOINT
        return f"{self.setpoint_c:.1f}"


def _instant(value: datetime) -> datetime:
    return value if value.tzinfo is None else value.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _slot_index_at(slots: Sequence[Mapping[str, Any]], at: datetime) -> int | None:
    moment = _instant(at)
    for index, slot in enumerate(slots):
        start, end = slot.get("start"), slot.get("end")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        if _instant(start) <= moment < _instant(end):
            return index
    return None


def _upcoming_setpoint(
    slots: Sequence[Mapping[str, Any]], index: int, heater_id: str
) -> float | None:
    """The target that motivates emission in an anticipation interval."""
    for slot in slots[index + 1 :]:
        target = _float_or_none(
            (slot.get("target_temperature_c") or {}).get(heater_id)
        )
        if target is not None:
            return target
    return None


def resolve_discharge_commands(
    heater_ids: Sequence[str],
    *,
    plan: Mapping[str, Any] | None,
    at: datetime,
    charge_config: Mapping[str, Mapping[str, Any]] | None = None,
    automatic_control_enabled: bool = True,
    heater_modes: Mapping[str, str] | None = None,
    controller_state_is_current: bool = True,
    relay_test_in_progress: bool = False,
) -> tuple[DischargeCommand, ...]:
    """Decide the discharge command of every accumulator for one instant.

    Every degraded condition resolves to a disabled discharge, so stored energy
    is never spent on a plan nobody is governing.
    """
    config = charge_config or {}
    modes = heater_modes or {}

    def command(
        heater_id: str, enabled: bool, setpoint: float | None
    ) -> DischargeCommand:
        topics = config.get(heater_id, {})
        effective_topics = resolve_accumulator_topics(
            heater_id,
            damper_topic=topics.get("damper_topic"),
            setpoint_topic=topics.get("setpoint_topic"),
        )
        return DischargeCommand(
            heater_id=heater_id,
            enabled=enabled,
            setpoint_c=setpoint if enabled else None,
            damper_topic=effective_topics.discharge,
            setpoint_topic=effective_topics.setpoint,
        )

    governed = (
        plan is not None
        and plan.get("status") != "INVALID"
        and automatic_control_enabled
        and controller_state_is_current
        and not relay_test_in_progress
    )
    if not governed:
        return tuple(command(heater_id, False, None) for heater_id in heater_ids)

    assert plan is not None
    slots = [
        item for item in (plan.get("slots") or ()) if isinstance(item, Mapping)
    ]
    index = _slot_index_at(slots, at)
    if index is None:
        return tuple(command(heater_id, False, None) for heater_id in heater_ids)

    slot = slots[index]
    targets = slot.get("target_temperature_c") or {}
    heat = slot.get("heat_delivered_kwh") or {}
    result: list[DischargeCommand] = []
    for heater_id in heater_ids:
        if modes.get(heater_id, "AUTO") != "AUTO":
            result.append(command(heater_id, False, None))
            continue
        target = _float_or_none(targets.get(heater_id))
        if target is not None:
            # Inside the window the window rules, not the projected heat: the
            # thermostat needs the discharge enabled even in an interval where
            # the plan projects no heat at all.
            result.append(command(heater_id, True, target))
            continue
        projected = _float_or_none(heat.get(heater_id)) or 0.0
        if projected > HEAT_EPSILON_KWH:
            upcoming = _upcoming_setpoint(slots, index, heater_id)
            result.append(command(heater_id, upcoming is not None, upcoming))
            continue
        result.append(command(heater_id, False, None))
    return tuple(result)


__all__ = [
    "HEAT_EPSILON_KWH",
    "DischargeCommand",
    "NO_SETPOINT",
    "resolve_discharge_commands",
]
