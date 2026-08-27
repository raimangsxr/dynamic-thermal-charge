"""Strict MQTT command boundary: two configuration fields and nothing else."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

from ..persistence import (
    ConfigConflictError,
    ConfigRepository,
    ConfigStoreError,
    ConfigValidationError,
)
from . import IncomingMessage
from .topics import TopicLayout


logger = logging.getLogger(__name__)

ALLOWED_COMMAND_FIELDS = frozenset({"enabled", "target_charge"})


class CommandProcessor:
    def __init__(
        self,
        repository: ConfigRepository,
        topics: TopicLayout,
        *,
        republish: Callable[[str], None],
    ) -> None:
        self._repository = repository
        self._topics = topics
        self._republish = republish

    def handle(self, message: IncomingMessage) -> bool:
        candidate, field = self._topic_parts(message.topic)
        # Retention is rejected before decoding or otherwise interpreting the
        # payload. An old command delivered after reconnect must never run.
        if message.retain:
            logger.warning("Rejected retained MQTT command on %s", message.topic)
            if candidate is not None:
                self._republish(candidate)
            return False

        if candidate is None or field not in ALLOWED_COMMAND_FIELDS:
            logger.warning("Rejected MQTT command topic %s: field is not allowed", message.topic)
            if candidate is not None:
                self._republish(candidate)
            return False

        try:
            config, revision = self._repository.current()
        except ConfigStoreError as exc:
            logger.error("Cannot apply MQTT command: %s", exc)
            self._republish(candidate)
            return False

        heater = next(
            (
                item
                for item in config.heaters
                if self._topics.command(item.id, field) == message.topic
            ),
            None,
        )
        if heater is None:
            logger.warning("Rejected MQTT command for unknown heater %s", candidate)
            self._republish(candidate)
            return False

        try:
            value = self._parse(field, message.payload)
        except ValueError as exc:
            logger.warning(
                "Rejected MQTT command for heater %s field %s: %s",
                heater.id,
                field,
                exc,
            )
            self._republish(heater.id)
            return False

        accepted = False
        for attempt in range(2):
            try:
                self._repository.set_field(
                    revision, "heater", heater.id, field, value
                )
                accepted = True
                break
            except ConfigConflictError:
                if attempt:
                    logger.warning(
                        "Rejected MQTT command for heater %s after a second "
                        "configuration conflict",
                        heater.id,
                    )
                    break
                try:
                    _config, revision = self._repository.current()
                except ConfigStoreError as exc:
                    logger.error("Cannot retry MQTT command: %s", exc)
                    break
            except (ConfigValidationError, ConfigStoreError) as exc:
                logger.warning(
                    "Rejected MQTT command for heater %s field %s: %s",
                    heater.id,
                    field,
                    exc,
                )
                break
        self._republish(heater.id)
        return accepted

    def _topic_parts(self, topic: str) -> tuple[str | None, str | None]:
        marker = f"{self._topics.base}/heater/"
        if not topic.startswith(marker):
            return None, None
        remainder = topic[len(marker) :]
        parts = remainder.split("/")
        if len(parts) != 3 or parts[1] != "set" or not parts[0]:
            return None, None
        return parts[0], parts[2]

    @staticmethod
    def _parse(field: str, payload: bytes) -> str:
        try:
            raw = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("payload is not UTF-8") from exc
        if field == "enabled":
            if raw == "ON":
                return "true"
            if raw == "OFF":
                return "false"
            raise ValueError("enabled accepts exactly ON or OFF")
        if not raw:
            raise ValueError("target_charge cannot be empty")
        try:
            number = float(raw)
        except ValueError as exc:
            raise ValueError("target_charge must be a number between 0 and 1") from exc
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError("target_charge must be between 0 and 1")
        return format(number, "g")


__all__ = ["ALLOWED_COMMAND_FIELDS", "CommandProcessor"]
