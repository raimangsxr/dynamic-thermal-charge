"""Publish simulated accumulator telemetry for planning integration tests."""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..models import Heater, SimulationSample
from . import MqttClient


logger = logging.getLogger(__name__)

MIN_TEMPERATURE_C = -50.0
MAX_TEMPERATURE_C = 80.0
STORED_CHARGE_MIN_C = 20.0
STORED_CHARGE_MAX_C = 70.0


@dataclass(frozen=True)
class MqttSimulationConfig:
    enabled: bool
    initial_temperature_c: float
    publish_seconds: float
    topic_prefix: str
    thermal_loss_c_per_hour: float
    seconds_per_hour: float = 10.0


@dataclass
class MqttSimulationService:
    client: MqttClient
    simulator: "MqttPlanningSimulator"


def advance_temperature(
    current_c: float,
    *,
    charging: bool,
    thermal_loss_c_per_hour: float,
    elapsed_hours: float,
) -> float:
    """Move temperature according to the configured thermal loss factor."""
    delta = thermal_loss_c_per_hour * elapsed_hours
    next_c = current_c + delta if charging else current_c - delta
    return max(MIN_TEMPERATURE_C, min(MAX_TEMPERATURE_C, next_c))


def simulated_hours(elapsed_seconds: float, seconds_per_hour: float) -> float:
    """Convert wall-clock seconds to the configured accelerated time base."""
    if elapsed_seconds <= 0:
        return 0.0
    if not math.isfinite(seconds_per_hour) or seconds_per_hour <= 0:
        raise ValueError("seconds_per_hour must be positive")
    return elapsed_seconds / seconds_per_hour


def advance_stored_charge(
    current_percent: float,
    *,
    charging: bool,
    thermal_loss_c_per_hour: float,
    demand_factor: float,
    full_charge_minutes: int,
    elapsed_hours: float,
) -> float:
    """Advance SOC using the heater's charge rate or thermal demand."""
    if full_charge_minutes <= 0:
        raise ValueError("full_charge_minutes must be positive")
    if demand_factor <= 0:
        raise ValueError("demand_factor must be positive")
    if thermal_loss_c_per_hour < 0:
        raise ValueError("thermal_loss_c_per_hour must be non-negative")
    if elapsed_hours <= 0:
        return max(0.0, min(100.0, current_percent))
    if charging:
        delta_percent = elapsed_hours * 60.0 / full_charge_minutes * 100.0
    else:
        temperature_range = STORED_CHARGE_MAX_C - STORED_CHARGE_MIN_C
        delta_percent = (
            elapsed_hours
            * thermal_loss_c_per_hour
            * demand_factor
            / temperature_range
            * 100.0
        )
    return max(0.0, min(100.0, current_percent + (delta_percent if charging else -delta_percent)))


def stored_charge_to_temperature(
    stored_charge_percent: float,
    *,
    min_c: float = STORED_CHARGE_MIN_C,
    max_c: float = STORED_CHARGE_MAX_C,
) -> float:
    bounded = max(0.0, min(100.0, stored_charge_percent))
    return min_c + (max_c - min_c) * bounded / 100.0


def temperature_to_stored_charge_percent(
    temperature_c: float,
    *,
    min_c: float = STORED_CHARGE_MIN_C,
    max_c: float = STORED_CHARGE_MAX_C,
) -> float:
    if max_c <= min_c:
        return 50.0
    fraction = (temperature_c - min_c) / (max_c - min_c)
    return max(0.0, min(100.0, fraction * 100.0))


def simulation_topics(
    heater: Heater,
    *,
    topic_prefix: str,
) -> tuple[str, str, str]:
    """Resolve the three MQTT topics used by automatic planning."""
    prefix = topic_prefix.strip("/")
    temperature = heater.temperature_topic or f"{prefix}/{heater.id}/temperature"
    target = heater.target_temperature_topic or f"{prefix}/{heater.id}/target"
    stored_charge = heater.stored_charge_topic or f"{prefix}/{heater.id}/stored_charge"
    return temperature, target, stored_charge


def heater_telemetry_topics(
    heater: Heater,
    *,
    simulation: MqttSimulationConfig | None,
) -> dict[str, str]:
    """Map MQTT topics to telemetry fields for one heater."""
    if simulation is not None and simulation.enabled:
        temperature, target, stored_charge = simulation_topics(
            heater,
            topic_prefix=simulation.topic_prefix,
        )
        candidates = {
            heater.temperature_topic or heater.indoor_topic or temperature: "temperature_c",
            heater.target_temperature_topic or target: "target_temperature_c",
            heater.stored_charge_topic or stored_charge: "stored_charge_percent",
        }
    else:
        candidates = {
            (heater.temperature_topic or heater.indoor_topic): "temperature_c",
            heater.target_temperature_topic: "target_temperature_c",
            heater.stored_charge_topic: "stored_charge_percent",
        }
    return {
        topic: field for topic, field in candidates.items() if topic is not None
    }


def simulation_subscription_topics(
    heaters: Sequence[Heater],
    site: Mapping[str, object],
    *,
    mqtt_enabled: bool,
) -> tuple[str, ...]:
    config = simulation_config_from_site(site)
    if not config.enabled or not mqtt_enabled:
        return ()
    topics: list[str] = []
    for heater in heaters:
        if not heater.enabled:
            continue
        topics.extend(heater_telemetry_topics(heater, simulation=config))
    return tuple(dict.fromkeys(topics))


class MqttPlanningSimulator:
    """Maintain per-heater temperatures and publish them to MQTT."""

    def __init__(
        self,
        client: MqttClient,
        *,
        config_provider: Callable[[], MqttSimulationConfig],
        heaters_provider: Callable[[], Sequence[Heater]],
        charging_state_provider: Callable[[], Mapping[str, bool]],
        sample_observer: Callable[[SimulationSample], None] | None = None,
        history_limit: int = 240,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._config_provider = config_provider
        self._heaters_provider = heaters_provider
        self._charging_state_provider = charging_state_provider
        self._sample_observer = sample_observer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._temperatures: dict[str, float] = {}
        self._stored_charge: dict[str, float] = {}
        self._samples: deque[SimulationSample] = deque(maxlen=max(1, history_limit))
        self._last_advanced_at: datetime | None = None

    def reset(self) -> None:
        self._temperatures.clear()
        self._stored_charge.clear()
        self._samples.clear()
        self._last_advanced_at = None

    def samples(self) -> tuple[SimulationSample, ...]:
        return tuple(self._samples)

    def publish_cycle(self) -> None:
        config = self._config_provider()
        if not config.enabled:
            return
        now = self._clock()
        if self._last_advanced_at is None:
            self._last_advanced_at = now
        elapsed_seconds = max(0.0, (now - self._last_advanced_at).total_seconds())
        elapsed_hours = simulated_hours(elapsed_seconds, config.seconds_per_hour)
        charging = self._charging_state_provider()
        published_heaters = 0
        published_messages: list[str] = []
        for heater in self._heaters_provider():
            if not heater.enabled:
                continue
            current = self._temperatures.get(heater.id, config.initial_temperature_c)
            stored_charge = self._stored_charge.get(
                heater.id,
                temperature_to_stored_charge_percent(current),
            )
            is_charging = charging.get(heater.id, False)
            stored_charge = advance_stored_charge(
                stored_charge,
                charging=is_charging,
                thermal_loss_c_per_hour=config.thermal_loss_c_per_hour,
                demand_factor=heater.demand_factor,
                full_charge_minutes=heater.full_charge_minutes,
                elapsed_hours=elapsed_hours,
            )
            current = stored_charge_to_temperature(stored_charge)
            target_temperature_c = (
                heater.thermal.target_temperature_c
                if heater.thermal is not None
                else min(MAX_TEMPERATURE_C, config.initial_temperature_c + 10.0)
            )
            self._temperatures[heater.id] = current
            self._stored_charge[heater.id] = stored_charge
            temperature_topic, target_topic, stored_charge_topic = simulation_topics(
                heater,
                topic_prefix=config.topic_prefix,
            )
            messages = (
                (temperature_topic, f"{current:.2f}"),
                (target_topic, f"{target_temperature_c:.2f}"),
                (stored_charge_topic, f"{stored_charge:.1f}"),
            )
            for topic, payload in messages:
                self._publish(topic, payload)
                published_messages.append(f"{topic}={payload}")
            sample = SimulationSample(
                at=now,
                heater_id=heater.id,
                temperature_c=current,
                target_temperature_c=target_temperature_c,
                stored_charge_percent=stored_charge,
                charging=is_charging,
                power_w=heater.power_w if is_charging else 0,
            )
            self._samples.append(sample)
            if self._sample_observer is not None:
                try:
                    self._sample_observer(sample)
                except Exception:
                    logger.exception("Could not persist simulated sample for %s", heater.id)
            published_heaters += 1
        self._last_advanced_at = now
        if published_heaters:
            logger.info(
                "Published simulated telemetry for %d heater(s) on prefix %s: %s",
                published_heaters,
                config.topic_prefix,
                ", ".join(published_messages),
            )

    def _publish(self, topic: str, payload: str) -> None:
        try:
            self._client.publish(topic, payload, qos=0, retain=False)
        except Exception:
            logger.exception("Could not publish simulated telemetry on %s", topic)


class MqttSimulationSupervisor:
    """Keep the planning simulator aligned with persisted settings."""

    def __init__(
        self,
        system_configuration_repository,
        planning_repository,
        service_factory: Callable[[], MqttSimulationService],
        *,
        poll_seconds: float = 1.0,
        wait: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._system_configuration_repository = system_configuration_repository
        self._planning_repository = planning_repository
        self._service_factory = service_factory
        self._poll_seconds = poll_seconds
        self._wait = wait
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._service: MqttSimulationService | None = None
        self._next_publish_at: datetime | None = None

    def run(self, *, max_cycles: int | None = None) -> None:
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            now = self._clock()
            self._reconcile(now)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            self._wait(self._poll_seconds)

    def stop(self) -> None:
        if self._service is not None:
            try:
                self._service.client.disconnect()
            finally:
                self._service.client.loop_stop()
        self._service = None
        self._next_publish_at = None

    def _reconcile(self, now: datetime) -> None:
        site = self._planning_repository.site()
        mqtt = self._system_configuration_repository.current().configuration.mqtt
        should_run = bool(site.get("mqtt_simulation_enabled")) and mqtt.enabled
        if not should_run:
            if self._service is not None:
                self.stop()
            return

        publish_seconds = float(site["mqtt_simulation_publish_seconds"])
        if self._service is None:
            self._service = self._service_factory()
            self._service.simulator.reset()
            clear_samples = getattr(self._planning_repository, "clear_simulation_samples", None)
            if callable(clear_samples):
                try:
                    clear_samples()
                except Exception:
                    logger.exception("Could not clear the previous simulated sample history")
            self._service.client.connect_async(mqtt.host, mqtt.port)
            self._service.client.loop_start()
            self._next_publish_at = now

        due = self._next_publish_at is None or now >= self._next_publish_at
        if due:
            self._service.simulator.publish_cycle()
            self._next_publish_at = now + timedelta(seconds=publish_seconds)


def simulation_config_from_site(site: Mapping[str, object]) -> MqttSimulationConfig:
    return MqttSimulationConfig(
        enabled=bool(site.get("mqtt_simulation_enabled")),
        initial_temperature_c=float(site.get("mqtt_simulation_initial_temperature_c", 45.0)),
        publish_seconds=float(site.get("mqtt_simulation_publish_seconds", 30.0)),
        topic_prefix=str(site.get("mqtt_simulation_topic_prefix", "dtc/sim")),
        thermal_loss_c_per_hour=float(
            site.get("mqtt_simulation_thermal_loss_c_per_hour", 2.0)
        ),
        seconds_per_hour=float(site.get("mqtt_simulation_seconds_per_hour", 10.0)),
    )


def validate_simulation_config(config: MqttSimulationConfig) -> None:
    if not math.isfinite(config.initial_temperature_c) or not (
        MIN_TEMPERATURE_C <= config.initial_temperature_c <= MAX_TEMPERATURE_C
    ):
        raise ValueError("initial temperature must be between -50 and 80")
    if config.publish_seconds <= 0:
        raise ValueError("publish_seconds must be positive")
    if not config.topic_prefix.strip():
        raise ValueError("topic_prefix cannot be empty")
    if config.thermal_loss_c_per_hour < 0:
        raise ValueError("thermal_loss_c_per_hour must be non-negative")
    if not math.isfinite(config.seconds_per_hour) or config.seconds_per_hour <= 0:
        raise ValueError("seconds_per_hour must be positive")


__all__ = [
    "MqttPlanningSimulator",
    "MqttSimulationConfig",
    "MqttSimulationService",
    "MqttSimulationSupervisor",
    "advance_temperature",
    "advance_stored_charge",
    "heater_telemetry_topics",
    "simulation_config_from_site",
    "simulation_subscription_topics",
    "simulation_topics",
    "simulated_hours",
    "stored_charge_to_temperature",
    "temperature_to_stored_charge_percent",
    "validate_simulation_config",
]
