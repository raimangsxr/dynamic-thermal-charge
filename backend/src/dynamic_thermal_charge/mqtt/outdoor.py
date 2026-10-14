"""Strict, non-retained outdoor-temperature MQTT acquisition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging

from ..thermal_calibration import CalibrationError, parse_outdoor_payload
from . import IncomingMessage


logger = logging.getLogger(__name__)


class OutdoorTemperatureMessageProcessor:
    def __init__(self, repository, *, topic: str | None, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._topic = None if topic is None else topic.strip()
        self._clock = clock
        self._started_at = clock()

    @property
    def topic(self) -> str | None:
        return self._topic

    def handle(self, message: IncomingMessage) -> bool:
        if not self._topic or message.topic != self._topic:
            return False
        if message.retain:
            logger.warning("Ignoring retained outdoor temperature on %s", message.topic)
            return False
        try:
            value = parse_outdoor_payload(message.payload)
        except (CalibrationError, UnicodeDecodeError) as exc:
            logger.error("Invalid outdoor temperature payload: %s", exc)
            return False
        now = self._clock()
        received_at = getattr(message, "received_at", None) or now
        if received_at.tzinfo is None or received_at > now:
            logger.error("Ignoring future outdoor temperature sample")
            return False
        if received_at < self._started_at:
            logger.warning("Ignoring outdoor temperature received before MQTT startup")
            return False
        try:
            self._repository.record(value, received_at)
        except Exception:
            logger.exception("Could not persist outdoor temperature")
            return False
        return True


__all__ = ["OutdoorTemperatureMessageProcessor"]
