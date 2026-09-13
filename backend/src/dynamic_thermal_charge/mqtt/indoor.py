"""Validate indoor temperature inputs and persist only the latest usable value."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from datetime import datetime

from ..models import IndoorReading
from ..persistence import (
    ConfigStoreError,
)
from . import IncomingMessage
from .topics import TopicLayout


logger = logging.getLogger(__name__)


class ChargeTelemetryMessageProcessor:
    """Validate and persist grouped JSON telemetry for one heater."""

    _FIELDS = (
        "indoor_temperature_c",
        "stored_soc_percent",
        "damper_position_percent",
    )

    def __init__(
        self,
        config_repository,
        planning_repository,
        *,
        topics: TopicLayout | None = None,
        readings=None,
        clock: Callable[[], datetime],
    ):
        self._config_repository = config_repository
        self._planning = planning_repository
        self._topics = topics or TopicLayout()
        self._readings = readings
        self._clock = clock

    def handle(self, message: IncomingMessage) -> bool:
        try:
            config, _revision = self._config_repository.current()
        except ConfigStoreError as exc:
            logger.error("Cannot resolve charge telemetry topic: %s", exc)
            return False
        match = None
        for heater in config.heaters:
            topic = self._topics.accumulator_topics(heater.id).telemetry
            if message.topic == topic:
                match = heater.id
                break
        if match is None:
            return False
        heater_id = match
        try:
            raw = message.payload.decode("utf-8", errors="strict").strip()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "Invalid grouped telemetry for heater %s on topic %s: %s",
                heater_id,
                message.topic,
                exc,
            )
            return False

        present = [field for field in self._FIELDS if field in payload]
        if not present:
            return False
        received_at = self._clock()
        all_valid = True
        for field in present:
            value = payload[field]
            error = self._validate(field, value, config)
            if error is not None:
                all_valid = False
                logger.error(
                    "Invalid %s for heater %s on topic %s: %s",
                    field,
                    heater_id,
                    message.topic,
                    error,
                )
                self._invalidate(heater_id, field, received_at)
                continue
            try:
                self._planning.record_telemetry(
                    heater_id, field, float(value), received_at
                )
                if field == "indoor_temperature_c" and self._readings is not None:
                    self._readings.upsert(
                        IndoorReading(heater_id, float(value), received_at)
                    )
            except ConfigStoreError as exc:
                all_valid = False
                logger.error(
                    "Could not store %s telemetry for %s: %s", field, heater_id, exc
                )
        return all_valid

    @staticmethod
    def _validate(field: str, value: object, config) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "value must be a finite JSON number"
        try:
            numeric = float(value)
        except (OverflowError, ValueError):
            return "value must be a finite JSON number"
        if not math.isfinite(numeric):
            return "value must be finite"
        if field == "stored_soc_percent" and not 0 <= numeric <= 100:
            return "stored SOC must be between 0 and 100"
        if field == "damper_position_percent" and not 0 <= numeric <= 100:
            return "damper position must be between 0 and 100"
        if field == "indoor_temperature_c" and not (
            config.site.indoor_min_plausible_c
            <= numeric
            <= config.site.indoor_max_plausible_c
        ):
            return "temperature is outside the configured plausible range"
        return None

    def _invalidate(self, heater_id: str, field: str, at: datetime) -> None:
        try:
            self._planning.invalidate_telemetry(heater_id, field, at)
            if field == "indoor_temperature_c" and self._readings is not None:
                self._readings.invalidate(heater_id)
        except ConfigStoreError as exc:
            logger.error("Could not invalidate charge telemetry: %s", exc)


__all__ = ["ChargeTelemetryMessageProcessor"]
