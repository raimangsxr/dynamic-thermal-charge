"""Environment-only MQTT settings never expose credentials."""

import pytest

from dynamic_thermal_charge.mqtt import MqttConfigurationError
from dynamic_thermal_charge.mqtt.settings import load_settings


def test_host_is_required_and_defaults_are_documented():
    with pytest.raises(MqttConfigurationError, match="DTC_MQTT_HOST"):
        load_settings({})
    settings = load_settings({"DTC_MQTT_HOST": "broker.local"})
    assert settings.host == "broker.local"
    assert settings.port == 1883
    assert settings.tls is False
    assert settings.prefix == "dtc"
    assert settings.discovery_prefix == "homeassistant"
    assert settings.publish_seconds == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DTC_MQTT_PORT", "0"),
        ("DTC_MQTT_PORT", "65536"),
        ("DTC_MQTT_PORT", "abc"),
        ("DTC_MQTT_PUBLISH_SECONDS", "0"),
        ("DTC_MQTT_PUBLISH_SECONDS", "abc"),
        ("DTC_MQTT_TLS", "perhaps"),
    ],
)
def test_invalid_ranges_and_types_name_the_variable(field, value):
    with pytest.raises(MqttConfigurationError, match=field):
        load_settings({"DTC_MQTT_HOST": "broker", field: value})


def test_tls_credentials_and_custom_cadence_are_loaded_without_secret_repr():
    secret = "never-print-this"
    settings = load_settings(
        {
            "DTC_MQTT_HOST": "tunnel",
            "DTC_MQTT_PORT": "8883",
            "DTC_MQTT_TLS": "true",
            "DTC_MQTT_USERNAME": "dtc",
            "DTC_MQTT_PASSWORD": secret,
            "DTC_MQTT_PREFIX": "house/dtc",
            "DTC_MQTT_DISCOVERY_PREFIX": "ha",
            "DTC_MQTT_PUBLISH_SECONDS": "2.5",
        }
    )
    assert settings.tls is True
    assert settings.publish_seconds == 2.5
    assert settings.password == secret
    assert secret not in repr(settings)


def test_username_requires_password_and_error_never_echoes_it():
    with pytest.raises(MqttConfigurationError, match="DTC_MQTT_PASSWORD"):
        load_settings({"DTC_MQTT_HOST": "broker", "DTC_MQTT_USERNAME": "dtc"})
