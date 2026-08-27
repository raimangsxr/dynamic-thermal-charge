"""Lazy, synchronous Paho MQTT v5 adapter."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from threading import Thread
from typing import Any

from . import (
    ConnectionHandler,
    IncomingMessage,
    MessageHandler,
    MqttAuthenticationError,
    MqttConfigurationError,
    MqttPublishError,
)
from .settings import MqttSettings


logger = logging.getLogger(__name__)
AUTH_RETRY_SECONDS = 300
RECONNECT_MIN_SECONDS = 1
RECONNECT_MAX_SECONDS = 120


class PahoMqttClient:
    def __init__(
        self,
        settings: MqttSettings,
        *,
        mqtt_module=None,
        wait: Callable[[float], None] = time.sleep,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        if mqtt_module is None:
            try:
                import paho.mqtt.client as mqtt_module
            except ImportError as exc:  # pragma: no cover - deployment edge
                raise MqttConfigurationError(
                    "MQTT support is not installed; install "
                    "dynamic-thermal-charge[mqtt]"
                ) from exc
        self._mqtt = mqtt_module
        self._settings = settings
        self._wait = wait
        self._dispatch = dispatch or self._dispatch_thread
        self._connection_handler: ConnectionHandler = lambda _ok, _reason: None
        self._message_handler: MessageHandler = lambda _message: None
        self._publish_reasons: dict[int, Any] = {}
        self._auth_failed = False

        self._client = mqtt_module.Client(
            callback_api_version=mqtt_module.CallbackAPIVersion.VERSION2,
            protocol=mqtt_module.MQTTv5,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_publish = self._on_publish
        if settings.username is not None:
            self._client.username_pw_set(settings.username, settings.password)
        if settings.tls:
            self._client.tls_set()
        self._client.reconnect_delay_set(
            RECONNECT_MIN_SECONDS, RECONNECT_MAX_SECONDS
        )

    def set_connection_handler(self, handler: ConnectionHandler) -> None:
        self._connection_handler = handler

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    def will_set(self, topic: str, payload: str, *, qos: int, retain: bool) -> None:
        self._client.will_set(topic, payload, qos=qos, retain=retain)

    def connect_async(self, host: str, port: int) -> None:
        try:
            self._client.connect_async(host, port)
        except Exception as exc:
            raise MqttPublishError(
                f"cannot start MQTT connection to {host}:{port}: {exc}"
            ) from exc

    def loop_start(self) -> None:
        self._client.loop_start()

    def loop_stop(self) -> None:
        self._client.loop_stop()

    def disconnect(self) -> None:
        self._client.disconnect()

    def publish(self, topic: str, payload: str, *, qos: int, retain: bool) -> None:
        try:
            info = self._client.publish(topic, payload, qos=qos, retain=retain)
            info.wait_for_publish()
        except Exception as exc:
            raise MqttPublishError(
                f"MQTT publication to {topic!r} failed: {exc}"
            ) from exc
        if info.rc != self._mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(
                f"MQTT publication to {topic!r} failed with transport code {info.rc}"
            )
        reason = self._publish_reasons.pop(info.mid, None)
        if reason is None:
            raise MqttPublishError(
                f"MQTT publication to {topic!r} received no PUBACK"
            )
        if getattr(reason, "is_failure", False):
            raise MqttPublishError(
                f"MQTT publication to {topic!r} was rejected: {reason}"
            )

    def subscribe(self, topic: str, *, qos: int = 1) -> None:
        self._client.subscribe(topic, qos=qos)

    def unsubscribe(self, topic: str) -> None:
        self._client.unsubscribe(topic)

    def _on_publish(self, _client, _userdata, mid, reason_code, _properties) -> None:
        self._publish_reasons[int(mid)] = reason_code

    def _on_message(self, _client, _userdata, message) -> None:
        self._message_handler(
            IncomingMessage(
                topic=str(message.topic),
                payload=bytes(message.payload),
                retain=bool(message.retain),
            )
        )

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if not getattr(reason_code, "is_failure", False):
            if self._auth_failed:
                logger.info("MQTT credentials accepted again")
                self._auth_failed = False
            self._connection_handler(True, None)
            return
        reason = str(reason_code)
        if self._is_authentication_reason(reason_code):
            if not self._auth_failed:
                logger.error("MQTT credentials rejected by broker")
                self._auth_failed = True
            self._connection_handler(False, reason)
            self._dispatch(self._retry_authentication)
            return
        self._connection_handler(False, reason)

    def _on_disconnect(
        self, _client, _userdata, _flags, reason_code, _properties
    ) -> None:
        self._connection_handler(False, str(reason_code))

    @staticmethod
    def _is_authentication_reason(reason_code) -> bool:  # noqa: ANN001
        return getattr(reason_code, "value", None) in {134, 135}

    def _retry_authentication(self) -> None:
        self._wait(AUTH_RETRY_SECONDS)
        try:
            self._client.reconnect()
        except Exception:
            logger.warning("MQTT credential retry could not connect")

    @staticmethod
    def _dispatch_thread(action: Callable[[], None]) -> None:
        Thread(target=action, name="dtc-mqtt-auth-retry", daemon=True).start()


__all__ = [
    "AUTH_RETRY_SECONDS",
    "PahoMqttClient",
    "RECONNECT_MAX_SECONDS",
    "RECONNECT_MIN_SECONDS",
]
