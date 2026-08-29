"""Paho adapter behavior through a complete in-memory module double."""

from types import SimpleNamespace

import pytest

from dynamic_thermal_charge.mqtt import MqttPublishError
from dynamic_thermal_charge.mqtt.client import PahoMqttClient
from dynamic_thermal_charge.mqtt.settings import MqttSettings


class Reason:
    def __init__(self, value=0, text="Success"):
        self.value = value
        self.is_failure = value != 0
        self.text = text

    def __str__(self):
        return self.text


class Info:
    def __init__(self, mid, rc=0):
        self.mid = mid
        self.rc = rc

    def wait_for_publish(self):
        return None


class FakePahoClient:
    def __init__(self, **kwargs):
        self.constructor = kwargs
        self.calls = []
        self.next_publish_reason = Reason()
        self.on_connect = self.on_disconnect = self.on_message = self.on_publish = None

    def username_pw_set(self, username, password):
        self.calls.append(("auth", username, password))

    def tls_set(self): self.calls.append(("tls",))
    def reconnect_delay_set(self, minimum, maximum): self.calls.append(("delay", minimum, maximum))
    def will_set(self, *args, **kwargs): self.calls.append(("will", args, kwargs))
    def connect_async(self, host, port): self.calls.append(("connect_async", host, port))
    def loop_start(self): self.calls.append(("loop_start",))
    def loop_stop(self): self.calls.append(("loop_stop",))
    def disconnect(self): self.calls.append(("disconnect",))
    def subscribe(self, topic, qos): self.calls.append(("subscribe", topic, qos))
    def unsubscribe(self, topic): self.calls.append(("unsubscribe", topic))
    def reconnect(self):
        self.calls.append(("reconnect",))
        return 0

    def publish(self, topic, payload, qos, retain):
        mid = len([call for call in self.calls if call[0] == "publish"]) + 1
        self.calls.append(("publish", topic, payload, qos, retain))
        self.on_publish(self, None, mid, self.next_publish_reason, None)
        return Info(mid)


class FakePaho:
    CallbackAPIVersion = SimpleNamespace(VERSION2="v2")
    MQTTv5 = "mqtt-v5"
    MQTT_ERR_SUCCESS = 0

    def __init__(self):
        self.instance = None

    def Client(self, **kwargs):
        self.instance = FakePahoClient(**kwargs)
        return self.instance


def _adapter(*, tls=True, wait=lambda _seconds: None):
    module = FakePaho()
    settings = MqttSettings(
        host="broker", port=8883 if tls else 1883, tls=tls,
        username="dtc", password="secret",
    )
    adapter = PahoMqttClient(
        settings, mqtt_module=module, wait=wait, dispatch=lambda action: action()
    )
    return adapter, module.instance


def test_adapter_uses_mqtt_v5_async_loop_tls_auth_and_backoff():
    adapter, client = _adapter()
    assert client.constructor == {"callback_api_version": "v2", "protocol": "mqtt-v5"}
    assert ("auth", "dtc", "secret") in client.calls
    assert ("tls",) in client.calls
    assert ("delay", 1, 120) in client.calls
    adapter.connect_async("broker", 8883)
    adapter.loop_start()
    assert ("connect_async", "broker", 8883) in client.calls
    assert ("loop_start",) in client.calls


def test_qos_one_publish_requires_an_accepted_puback():
    adapter, client = _adapter()
    adapter.publish("topic", "safe", qos=1, retain=True)
    assert client.calls[-1] == ("publish", "topic", "safe", 1, True)

    client.next_publish_reason = Reason(135, "Not authorized")
    with pytest.raises(MqttPublishError, match="topic.*Not authorized") as error:
        adapter.publish("topic", "secret-payload", qos=1, retain=True)
    assert "secret-payload" not in str(error.value)


def test_bad_credentials_wait_exactly_five_minutes_and_log_transitions_once(caplog):
    waits = []
    adapter, client = _adapter(wait=waits.append)
    accepted = []
    adapter.set_connection_handler(lambda ok, reason: accepted.append((ok, reason)))
    caplog.set_level("INFO")

    client.on_connect(client, None, None, Reason(134, "Bad user name or password"), None)
    client.on_connect(client, None, None, Reason(134, "Bad user name or password"), None)
    client.on_connect(client, None, None, Reason(), None)

    assert waits == [300, 300]
    assert [call for call in client.calls if call[0] == "reconnect"] == [
        ("reconnect",), ("reconnect",)
    ]
    assert caplog.text.count("credentials rejected") == 1
    assert caplog.text.count("credentials accepted again") == 1
    assert accepted[-1] == (True, None)
