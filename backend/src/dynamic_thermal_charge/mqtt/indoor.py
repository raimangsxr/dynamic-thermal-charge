"""Validate indoor temperature inputs and persist only the latest usable value."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import datetime

from ..models import IndoorReading
from ..persistence import (
    ConfigRepository,
    ConfigStoreError,
    IndoorReadingRepository,
)
from . import IncomingMessage
from .simulator import heater_telemetry_topics, simulation_config_from_site


logger = logging.getLogger(__name__)


class IndoorMessageProcessor:
    def __init__(
        self,
        config_repository: ConfigRepository,
        readings: IndoorReadingRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._config_repository = config_repository
        self._readings = readings
        self._clock = clock

    def handle(self, message: IncomingMessage) -> bool:
        try:
            config, _revision = self._config_repository.current()
        except ConfigStoreError as exc:
            logger.error("Cannot resolve indoor MQTT topic: %s", exc)
            return False
        heater = next(
            (item for item in config.heaters if item.indoor_topic == message.topic),
            None,
        )
        if heater is None:
            return False
        try:
            raw = message.payload.decode("utf-8", errors="strict")
            if not raw.strip():
                raise ValueError("empty payload")
            celsius = float(raw)
            if not math.isfinite(celsius):
                raise ValueError("non-finite value")
            if not (
                config.site.indoor_min_plausible_c
                <= celsius
                <= config.site.indoor_max_plausible_c
            ):
                raise ValueError("outside the configured plausible range")
        except (UnicodeDecodeError, ValueError) as exc:
            logger.error(
                "Invalid indoor temperature for heater %s on topic %s: %s",
                heater.id,
                message.topic,
                exc,
            )
            try:
                self._readings.invalidate(heater.id)
            except ConfigStoreError as store_exc:
                logger.error("Could not invalidate indoor reading: %s", store_exc)
            return False
        try:
            self._readings.upsert(
                IndoorReading(heater.id, celsius, self._clock())
            )
        except ConfigStoreError as exc:
            logger.error("Could not store indoor temperature for %s: %s", heater.id, exc)
            return False
        return True


class ChargeTelemetryMessageProcessor:
    """Validate and persist the three independent accumulator MQTT values."""

    def __init__(self, config_repository, planning_repository, *, clock: Callable[[], datetime]):
        self._config_repository = config_repository
        self._planning = planning_repository
        self._clock = clock

    def handle(self, message: IncomingMessage) -> bool:
        try:
            config, _revision = self._config_repository.current()
        except ConfigStoreError as exc:
            logger.error("Cannot resolve charge telemetry topic: %s", exc)
            return False
        match = None
        simulation = simulation_config_from_site(self._planning.site())
        for heater in config.heaters:
            topics = heater_telemetry_topics(heater, simulation=simulation)
            field = topics.get(message.topic)
            if field is not None:
                match = (heater.id, field)
                break
        if match is None:
            return False
        heater_id, field = match
        try:
            raw = message.payload.decode("utf-8", errors="strict").strip()
            value = float(raw)
            if not raw or not math.isfinite(value):
                raise ValueError("empty or non-finite value")
            if field == "stored_charge_percent" and not 0 <= value <= 100:
                raise ValueError("stored charge must be between 0 and 100")
            if field != "stored_charge_percent" and not -50 <= value <= 80:
                raise ValueError("temperature is outside the safe range")
        except (UnicodeDecodeError, ValueError) as exc:
            logger.error("Invalid %s for heater %s on topic %s: %s", field, heater_id, message.topic, exc)
            try:
                self._planning.invalidate_telemetry(heater_id, field, self._clock())
            except Exception as store_exc:
                logger.error("Could not invalidate charge telemetry: %s", store_exc)
            return False
        try:
            self._planning.record_telemetry(heater_id, field, value, self._clock())
        except ConfigStoreError as exc:
            logger.error("Could not store charge telemetry for %s: %s", heater_id, exc)
            return False
        return True


__all__ = ["ChargeTelemetryMessageProcessor", "IndoorMessageProcessor"]
