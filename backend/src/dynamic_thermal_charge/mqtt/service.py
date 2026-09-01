"""Independent MQTT process lifecycle."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

from . import MqttClient, MqttError
from . import IncomingMessage
from .topics import TopicLayout


logger = logging.getLogger(__name__)


class MqttService:
    def __init__(
        self,
        client: MqttClient,
        topics: TopicLayout,
        *,
        host: str,
        port: int,
        publisher=None,
        publish_seconds: float = 15,
        wait: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        command_handler: Callable[[IncomingMessage], object] | None = None,
        indoor_handler: Callable[[IncomingMessage], object] | None = None,
    ) -> None:
        self._client = client
        self._topics = topics
        self._host = host
        self._port = port
        self._publisher = publisher
        self._publish_seconds = publish_seconds
        self._wait = wait
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._subscribed: set[str] = set()
        self._command_handler = command_handler
        self._indoor_handler = indoor_handler
        self._messages: deque[IncomingMessage] = deque()
        self._connections: deque[tuple[bool, str | None]] = deque()
        self._connected = False

    def start(self) -> None:
        # MQTT records the will as part of CONNECT; ordering is semantic.
        self._client.will_set(
            self._topics.availability, "offline", qos=1, retain=True
        )
        self._client.set_connection_handler(self._on_connection)
        self._client.set_message_handler(self._on_message)
        self._client.connect_async(self._host, self._port)
        self._client.loop_start()

    def stop(self) -> None:
        for topic in (self._topics.state_available, self._topics.availability):
            try:
                self._client.publish(topic, "offline", qos=1, retain=True)
            except MqttError:
                logger.warning("Could not publish clean MQTT shutdown on %s", topic)
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def run(self, *, max_cycles: int | None = None) -> None:
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            self._clock()
            connection_refreshed = self.process_events()
            if self._publisher is not None and self._connected:
                if not connection_refreshed:
                    self._publisher.refresh(force_discovery=False)
                    self._sync_subscriptions()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            self._wait(self._publish_seconds)

    def _on_connection(self, accepted: bool, reason: str | None) -> None:
        # Paho invokes callbacks on its network thread. QoS 1 publishing waits
        # for that same thread to receive PUBACK, so callbacks must only queue.
        self._connections.append((accepted, reason))

    def process_events(self) -> bool:
        """Process queued network events on the service's owning thread."""
        connection_refreshed = False
        while self._connections:
            accepted, reason = self._connections.popleft()
            if self._process_connection(accepted, reason):
                connection_refreshed = True
        while self._messages:
            message = self._messages.popleft()
            try:
                if "/set/" in message.topic and self._command_handler is not None:
                    self._command_handler(message)
                elif self._indoor_handler is not None:
                    self._indoor_handler(message)
            except Exception:
                logger.exception(
                    "Unexpected MQTT command handler failure; message rejected"
                )
        return connection_refreshed

    def _process_connection(self, accepted: bool, reason: str | None) -> bool:
        if accepted:
            self._connected = True
            # A new network session has no subscriptions even if the previous
            # connection did; renew every declared topic after discovery.
            self._subscribed.clear()
            self._client.publish(
                self._topics.availability, "online", qos=1, retain=True
            )
            if self._publisher is not None:
                self._publisher.refresh(force_discovery=True)
                self._sync_subscriptions()
            return True
        self._connected = False
        logger.warning("MQTT connection unavailable: %s", reason or "unknown reason")
        return False

    def _sync_subscriptions(self) -> None:
        desired = set(
            getattr(self._publisher, "subscription_topics", lambda: ())()
        )
        for topic in sorted(self._subscribed - desired):
            self._client.unsubscribe(topic)
        for topic in sorted(desired - self._subscribed):
            self._client.subscribe(topic, qos=1)
        self._subscribed = desired

    def _on_message(self, message: IncomingMessage) -> None:
        if self._command_handler is None and self._indoor_handler is None:
            return
        self._messages.append(message)


__all__ = ["MqttService"]
