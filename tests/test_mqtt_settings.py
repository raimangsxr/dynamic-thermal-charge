"""Database-resident MQTT settings never expose credentials."""

import pytest

from dynamic_thermal_charge.mqtt import MqttConfigurationError
from dynamic_thermal_charge.mqtt.settings import settings_from_repository
from dynamic_thermal_charge.persistence import ConfigValidationError
from dynamic_thermal_charge.persistence.system_configuration import SecretAction, SecretMutation


def _update(store, patch, secrets=None):
    repository = store.system_configuration
    revision = repository.current().revision
    repository.update_section(
        "mqtt", patch, expected_revision=revision,
        secret_mutations=secrets, actor="test",
    )


def test_disabled_mqtt_is_explicit(initialised_store):
    with pytest.raises(MqttConfigurationError, match="disabled"):
        settings_from_repository(initialised_store.system_configuration)


def test_host_and_defaults_are_loaded_from_database(initialised_store, monkeypatch):
    monkeypatch.setenv("DTC_MQTT_HOST", "must-be-ignored")
    _update(initialised_store, {"enabled": True, "host": "broker.local"})
    settings = settings_from_repository(initialised_store.system_configuration)
    assert settings.host == "broker.local"
    assert settings.port == 1883
    assert settings.tls is False
    assert settings.prefix == "dtc"
    assert settings.discovery_prefix == "homeassistant"
    assert settings.publish_seconds == 15


def test_tls_credentials_and_custom_cadence_are_loaded_without_secret_repr(initialised_store):
    secret = "never-print-this"
    _update(
        initialised_store,
        {"enabled": True, "host": "tunnel", "port": 8883, "tls": True,
         "prefix": "house/dtc", "discovery_prefix": "ha", "publish_seconds": 2.5},
        {"mqtt_username": SecretMutation(SecretAction.REPLACE, "dtc"),
         "mqtt_password": SecretMutation(SecretAction.REPLACE, secret)},
    )
    settings = settings_from_repository(initialised_store.system_configuration)
    assert settings.tls is True
    assert settings.publish_seconds == 2.5
    assert settings.password == secret
    assert secret not in repr(settings)


def test_username_requires_password_atomically(initialised_store):
    with pytest.raises(ConfigValidationError, match="pair"):
        _update(
            initialised_store,
            {"enabled": True, "host": "broker"},
            {"mqtt_username": SecretMutation(SecretAction.REPLACE, "dtc")},
        )
