"""Project controller evidence into retained MQTT state without inventing it."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..api.liveness import ControllerView
from ..models import AppConfig
from ..persistence import (
    ConfigStoreError,
    Heartbeat,
    Liveness,
    SchemaStatus,
    SchemaVersionError,
)
from . import MqttClient
from .discovery import DiscoveryEntity
from .discovery import discovery_entities
from .topics import TopicLayout


logger = logging.getLogger(__name__)


def _health(controller: ControllerView) -> str:
    return {
        Liveness.LIVE: "healthy",
        Liveness.LIVE_DEGRADED: "degraded",
        Liveness.STALE: "silent",
        Liveness.NEVER_SEEN: "never_seen",
    }[controller.liveness]


def project_state(
    config: AppConfig,
    controller: ControllerView,
    output_states: Mapping[str, bool],
    *,
    plan: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Pure state projection; absent evidence stays absent from the payload."""
    installation: dict[str, Any] = {
        "controller_health": _health(controller),
        "state_is_current": controller.state_is_current,
        "multiple_controllers_suspected": (
            controller.multiple_controllers_suspected
        ),
        "power_limit_w": config.site.max_total_power_w,
    }
    heaters: dict[str, dict[str, Any]] = {}
    for heater in config.heaters:
        payload: dict[str, Any] = {
            "power_w": heater.power_w,
            "enabled": heater.enabled,
            "target_charge": heater.target_charge,
        }
        if controller.state_is_current:
            payload["output_on"] = bool(output_states.get(heater.id, False))
        heaters[heater.id] = payload

    if plan is not None:
        for field in (
            "window_start",
            "window_end",
            "forecast_average_c",
            "forecast_source",
        ):
            if plan.get(field) is not None:
                installation[field] = plan[field]
        allocations = plan.get("allocations", {})
        for heater_id, allocation in allocations.items():
            if heater_id in heaters:
                for field in (
                    "requested_minutes",
                    "allocated_minutes",
                    "unmet_minutes",
                ):
                    if field in allocation:
                        heaters[heater_id][field] = allocation[field]

    if controller.state_is_current:
        instant_power = sum(
            heater.power_w
            for heater in config.heaters
            if output_states.get(heater.id, False)
        )
        installation["instant_power_w"] = instant_power
        installation["percent_of_limit"] = round(
            100.0 * instant_power / config.site.max_total_power_w, 1
        )
    return installation, heaters


class MqttPublisher:
    """Publish snapshots and collapse repeated infrastructure failures."""

    def __init__(
        self,
        client: MqttClient,
        topics: TopicLayout,
        snapshot: Callable[
            [], tuple[dict[str, Any], dict[str, dict[str, Any]]]
        ],
        *,
        discovery: Callable[[], Iterable[DiscoveryEntity]] | None = None,
        subscriptions: Callable[[], Iterable[str]] | None = None,
    ) -> None:
        self._client = client
        self._topics = topics
        self._snapshot = snapshot
        self._discovery = discovery or (lambda: ())
        self._subscriptions = subscriptions or (lambda: ())
        self._inventory: set[str] = set()
        self._failure: str | None = None

    def refresh(self, *, force_discovery: bool = False) -> bool:
        try:
            installation, heaters = self._snapshot()
        except (ConfigStoreError, SchemaVersionError) as exc:
            self._enter_failure(exc)
            return False

        if self._failure is not None:
            logger.info("MQTT publication recovered after %s", self._failure)
            self._failure = None
            self._publish(self._topics.availability, "online")

        self._publish_discovery(force=force_discovery)

        state_available = (
            "online" if installation.get("state_is_current") is True else "offline"
        )
        self._publish(self._topics.state_available, state_available)
        self._publish_json(self._topics.installation_state, installation)
        for heater_id, payload in heaters.items():
            self._publish_json(self._topics.heater_state(heater_id), payload)
        return True

    def subscription_topics(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self._subscriptions()))

    def republish_heater(self, heater_id: str) -> None:
        """Publish the stored truth after any accepted or rejected command."""
        try:
            _installation, heaters = self._snapshot()
        except (ConfigStoreError, SchemaVersionError) as exc:
            self._enter_failure(exc)
            return
        payload = heaters.get(heater_id)
        if payload is not None:
            self._publish_json(self._topics.heater_state(heater_id), payload)

    def _publish_discovery(self, *, force: bool) -> None:
        current: set[str] = set()
        for entity in self._discovery():
            topic = entity.topic(self._topics)
            current.add(topic)
            if force or topic not in self._inventory:
                self._publish_json(topic, entity.payload)
        for removed in sorted(self._inventory - current):
            self._publish(removed, "")
        self._inventory = current

    def _enter_failure(self, exc: Exception) -> None:
        if self._failure is not None:
            return
        self._failure = str(exc)
        logger.error("MQTT publication unavailable: %s", exc)
        self._publish(self._topics.state_available, "offline")
        self._publish(self._topics.availability, "offline")

    def _publish_json(self, topic: str, payload: Mapping[str, Any]) -> None:
        self._publish(topic, json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def _publish(self, topic: str, payload: str) -> None:
        self._client.publish(topic, payload, qos=1, retain=True)


class StoreSnapshotReader:
    """Compose existing persistence readers with the shared liveness rule."""

    def __init__(
        self,
        *,
        config_repository,
        schema_gate,
        heartbeat_reader: Callable[[], Heartbeat | None],
        status_reader,
        clock: Callable[[], Any],
    ) -> None:
        self._config_repository = config_repository
        self._schema_gate = schema_gate
        self._heartbeat_reader = heartbeat_reader
        self._status_reader = status_reader
        self._clock = clock
        self._previous_heartbeat: Heartbeat | None = None
        self._config: AppConfig | None = None

    def __call__(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        status = self._schema_gate.check()
        if status is not SchemaStatus.OK:
            raise SchemaVersionError(
                f"configuration schema is {status.value}; run the appropriate "
                "database migration or update this service"
            )
        now = self._clock()
        config, _revision = self._config_repository.current()
        self._config = config
        heartbeat = self._heartbeat_reader()
        # This imports no FastAPI objects; liveness.py is the already-tested,
        # shared pure rule used by the HTTP projection too.
        from ..api.liveness import evaluate

        controller = evaluate(
            heartbeat, now, previous=self._previous_heartbeat
        )
        if heartbeat is not None:
            self._previous_heartbeat = heartbeat
        last_states = {
            heater_id: state
            for heater_id, (state, _changed_at) in (
                self._status_reader.last_output_states().items()
            )
        }
        raw_plan = self._status_reader.plan_in_progress(now)
        plan = self._plan(raw_plan)
        return project_state(config, controller, last_states, plan=plan)

    def discovery(
        self, topics: TopicLayout, installation_name: str
    ) -> list[DiscoveryEntity]:
        if self._config is None:
            self()
        assert self._config is not None
        return discovery_entities(self._config, installation_name, topics)

    def subscriptions(self, topics: TopicLayout) -> tuple[str, ...]:
        if self._config is None:
            self()
        assert self._config is not None
        result: list[str] = []
        for heater in self._config.heaters:
            result.extend(
                (
                    topics.command(heater.id, "enabled"),
                    topics.command(heater.id, "target_charge"),
                )
            )
            if heater.indoor_topic is not None:
                result.append(heater.indoor_topic)
        return tuple(result)

    @staticmethod
    def _plan(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if raw is None:
            return None
        forecast = raw.get("forecast")
        return {
            "window_start": raw["plan"]["window_start"].isoformat(),
            "window_end": raw["plan"]["window_end"].isoformat(),
            "forecast_average_c": (
                None if forecast is None else forecast["average_temperature_c"]
            ),
            "forecast_source": None if forecast is None else forecast["source"],
            "allocations": {
                allocation["heater_id"]: allocation
                for allocation in raw.get("allocations", ())
            },
        }


__all__ = ["MqttPublisher", "StoreSnapshotReader", "project_state"]
