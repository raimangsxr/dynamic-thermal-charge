"""Explicit compatibility boundary for legacy planning payloads.

Runtime and HTTP preview paths use :mod:`planning_solver`.  This module keeps
the old percentage planner and persisted plan representation available to
callers that explicitly need them, without making them an implicit fallback
for the current energy model.
"""

from __future__ import annotations

from typing import Any, Mapping

from .charge_planning import (
    MilpChargePlanner,
    deserialize_automatic_plan,
    independently_validate_plan,
    input_token,
    serialize_automatic_plan,
)
from .planning_domain import PlanningInput


class LegacyPercentagePlanner:
    """Opt into the historical percentage-constraint planning model."""

    def build(self, request: PlanningInput):
        if request.room_energy_model:
            raise ValueError(
                "legacy percentage planning cannot build a room-energy request"
            )
        return MilpChargePlanner().build(request)


def deserialize_legacy_plan(payload: Mapping[str, Any]):
    """Read the persisted plan shape used by older integrations."""
    return deserialize_automatic_plan(payload)


__all__ = [
    "LegacyPercentagePlanner",
    "deserialize_automatic_plan",
    "deserialize_legacy_plan",
    "independently_validate_plan",
    "input_token",
    "serialize_automatic_plan",
]
