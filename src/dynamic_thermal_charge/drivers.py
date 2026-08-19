"""Output driver boundary and an in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Protocol


logger = logging.getLogger(__name__)


class OutputDriver(Protocol):
    def set_state(self, heater_id: str, enabled: bool, at: datetime) -> None:
        """Apply an output state at a particular instant."""


@dataclass(frozen=True)
class StateChange:
    at: datetime
    heater_id: str
    enabled: bool


class SimulatedOutputDriver:
    def __init__(self) -> None:
        self.changes: list[StateChange] = []
        self._state: dict[str, bool] = {}

    def set_state(self, heater_id: str, enabled: bool, at: datetime) -> None:
        if self._state.get(heater_id, False) == enabled:
            logger.debug("Ignoring unchanged simulated output %s=%s", heater_id, enabled)
            return
        self._state[heater_id] = enabled
        self.changes.append(StateChange(at=at, heater_id=heater_id, enabled=enabled))
        logger.info("Simulated output changed: %s=%s at %s", heater_id, enabled, at)
