"""Output driver boundary and an in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .persistence import HistoryRecorder


logger = logging.getLogger(__name__)


class OutputDriver(Protocol):
    def set_state(self, heater_id: str, enabled: bool, at: datetime) -> None:
        """Apply an output state at a particular instant."""

    def close(self) -> None:
        """Release driver resources after leaving every output off."""


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

    def close(self) -> None:
        logger.debug("Closed simulated output driver")


class RecordingOutputDriver:
    """Wraps a driver and records every state change in the audit trail.

    A decorator rather than a change to ``ChargeController`` so the fail-safe
    controller stays untouched, and so the recording sits exactly at the boundary
    where a transition physically happens.

    Only *changes* are recorded (FR-018). The tracked state starts at OFF for
    every output, which is also the state every driver is initialised to
    (principle I), so the initial forcing of all outputs to OFF produces no
    record: nothing changed.
    """

    def __init__(
        self,
        driver: OutputDriver,
        history: "HistoryRecorder",
        plan_ref: Callable[[], object] | None = None,
    ) -> None:
        self._driver = driver
        self._history = history
        self._plan_ref = plan_ref
        self._state: dict[str, bool] = {}

    def set_state(self, heater_id: str, enabled: bool, at: datetime) -> None:
        # The driver acts first: an audit record for a switch that never happened
        # would be worse than a missing one.
        self._driver.set_state(heater_id, enabled, at)
        if self._state.get(heater_id, False) == enabled:
            return
        self._state[heater_id] = enabled
        self._history.record_transition(
            heater_id,
            enabled,
            at,
            None if self._plan_ref is None else self._plan_ref(),
        )

    def close(self) -> None:
        self._driver.close()
