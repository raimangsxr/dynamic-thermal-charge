"""The current energy-model solver boundary.

The MILP implementation remains in ``charge_planning`` while the extraction
is staged.  New runtime and API code imports this boundary instead of reaching
into the compatibility module.  Keeping the implementation class unchanged is
intentional: it preserves variable creation order and therefore deterministic
plans during the refactor.
"""

from __future__ import annotations

from .charge_planning import (
    DegreeHoursDemandEstimator,
    DeterministicChargeOptimizer,
    MilpChargePlanner,
)
from .planning_domain import AutomaticPlan, PlanningInput


class CurrentEnergyPlanner(DeterministicChargeOptimizer):
    """Build plans with the active room-energy model."""

    def build(self, request: PlanningInput) -> AutomaticPlan:
        if not request.room_energy_model:
            raise ValueError(
                "the current planning solver requires the room-energy model"
            )
        return super().build(request)


__all__ = [
    "CurrentEnergyPlanner",
    "DegreeHoursDemandEstimator",
    "DeterministicChargeOptimizer",
    "MilpChargePlanner",
]
