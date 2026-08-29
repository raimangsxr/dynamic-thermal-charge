"""MQTT boundary contracts without importing the optional Paho adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class MqttError(RuntimeError):
    """Base error for messaging failures."""


class MqttConfigurationError(MqttError):
    """The deployment settings are missing or invalid."""


class MqttAuthenticationError(MqttError):
    """The broker rejected the configured credentials."""


class MqttPublishError(MqttError):
    """The broker rejected or could not confirm a publication."""


@dataclass(frozen=True)
class IncomingMessage:
    topic: str
    payload: bytes
    retain: bool = False


MessageHandler = Callable[[IncomingMessage], None]
ConnectionHandler = Callable[[bool, str | None], None]


class MqttClient(Protocol):
    """Transport operations used by the publisher and exposed by test doubles."""

    def set_connection_handler(self, handler: ConnectionHandler) -> None: ...

    def set_message_handler(self, handler: MessageHandler) -> None: ...

    def will_set(
        self, topic: str, payload: str, *, qos: int, retain: bool
    ) -> None: ...

    def connect_async(self, host: str, port: int) -> None: ...

    def loop_start(self) -> None: ...

    def loop_stop(self) -> None: ...

    def disconnect(self) -> None: ...

    def publish(
        self, topic: str, payload: str, *, qos: int, retain: bool
    ) -> None: ...

    def subscribe(self, topic: str, *, qos: int = 1) -> None: ...

    def unsubscribe(self, topic: str) -> None: ...


__all__ = [
    "ConnectionHandler",
    "IncomingMessage",
    "MessageHandler",
    "MqttAuthenticationError",
    "MqttClient",
    "MqttConfigurationError",
    "MqttError",
    "MqttPublishError",
]
