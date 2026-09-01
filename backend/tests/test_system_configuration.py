from datetime import datetime, timezone
import json

import pytest
from sqlalchemy import select, text

from dynamic_thermal_charge.persistence import ConfigConflictError, ConfigValidationError
from dynamic_thermal_charge.persistence.canonical_engines import (
    build_canonical_engines,
    initialise_canonical_schemas,
)
from dynamic_thermal_charge.persistence.locator import DatabaseLocator
from dynamic_thermal_charge.persistence.paths import StorePaths
from dynamic_thermal_charge.persistence.schema import system_secret
from dynamic_thermal_charge.persistence.system_configuration import (
    SECRET_KINDS,
    SecretAction,
    SecretMutation,
    SystemConfigurationRepository,
)
from dynamic_thermal_charge.system_settings import (
    ACTIVATION_POLICIES,
    PUBLIC_SECTION_FIELDS,
    SECTION_TYPES,
    ApiSystemSettings,
    DatabaseSettings,
    MqttSystemSettings,
    OperationsSystemSettings,
    SystemConfiguration,
    WeatherSystemSettings,
)
from dynamic_thermal_charge.weather import weather_config_from_system


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
SENTINELS = {
    "admin_token_digest": "scrypt:admin-salt:admin-digest",
    "postgres_username": "secret-pg-user",
    "postgres_password": "secret-pg-password",
    "mqtt_username": "secret-mqtt-user",
    "mqtt_password": "secret-mqtt-password",
    "aemet_api_key": "secret-aemet-key",
}


@pytest.fixture
def system_repository(tmp_path):
    engines = build_canonical_engines(
        DatabaseLocator.sqlite(), StorePaths.in_directory(tmp_path)
    )
    initialise_canonical_schemas(engines)
    repository = SystemConfigurationRepository(
        engines.configuration, engines.configuration_location, clock=lambda: NOW
    )
    assert repository.initialise(secrets=SENTINELS, actor="installer")
    return repository, engines


def test_typed_defaults_and_cross_field_validation():
    config = SystemConfiguration()
    assert config.api == ApiSystemSettings()
    assert config.mqtt == MqttSystemSettings()
    assert config.operations == OperationsSystemSettings()
    assert config.mqtt.fixed_temperature_c == 20.0
    assert config.mqtt.fixed_target_temperature_c == 21.0
    assert config.mqtt.fixed_stored_charge_percent == 50.0
    assert config.mqtt.fixed_indoor_temperature_c == 20.0
    with pytest.raises(ValueError, match="host and database"):
        DatabaseSettings(driver="postgresql")
    with pytest.raises(ValueError, match="trusted-network"):
        DatabaseSettings(
            driver="postgresql", host="db", database="dtc", tls=False
        )
    with pytest.raises(ValueError, match="required"):
        WeatherSystemSettings(provider="aemet")
    with pytest.raises(ValueError, match="5 digits"):
        WeatherSystemSettings(provider="aemet", municipality_code="123")
    with pytest.raises(ValueError, match="renewal"):
        OperationsSystemSettings(
            relay_test_lease_seconds=10, relay_test_lease_renew_seconds=10
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("fixed_temperature_c", -50.1),
        ("fixed_target_temperature_c", 80.1),
        ("fixed_indoor_temperature_c", float("nan")),
        ("fixed_stored_charge_percent", -0.1),
        ("fixed_stored_charge_percent", 100.1),
    ],
)
def test_mqtt_fixed_values_use_telemetry_safety_bounds(field, value):
    with pytest.raises(ValueError):
        MqttSystemSettings(**{field: value})


def test_mqtt_fixed_values_round_trip_in_the_mqtt_section(system_repository):
    repository, _engines = system_repository
    revision = repository.update_section(
        "mqtt",
        {
            "fixed_temperature_c": 19.5,
            "fixed_target_temperature_c": 22.0,
            "fixed_stored_charge_percent": 65.0,
            "fixed_indoor_temperature_c": 18.0,
        },
        expected_revision=1,
        actor="admin",
    )
    snapshot = repository.current()
    assert revision == 2
    assert snapshot.configuration.mqtt.fixed_temperature_c == 19.5
    assert snapshot.configuration.mqtt.fixed_target_temperature_c == 22.0
    assert snapshot.configuration.mqtt.fixed_stored_charge_percent == 65.0
    assert snapshot.configuration.mqtt.fixed_indoor_temperature_c == 18.0
    assert set(snapshot.configuration.documents()["mqtt"]) >= {
        "fixed_temperature_c",
        "fixed_target_temperature_c",
        "fixed_stored_charge_percent",
        "fixed_indoor_temperature_c",
    }


def test_initialise_is_idempotent_and_round_trips_typed_documents(system_repository):
    repository, _engines = system_repository
    assert repository.initialise() is False
    snapshot = repository.current()
    assert snapshot.revision == 1
    assert snapshot.configuration == SystemConfiguration()
    assert {name: value.value for name, value in snapshot.secrets.items()} == SENTINELS


def test_valid_update_is_atomic_and_increments_revision(system_repository):
    repository, _engines = system_repository
    revision = repository.update_section(
        "api",
        {"port": 9090, "cors_origins": ["https://panel.lan"]},
        expected_revision=1,
        actor="admin@panel",
    )
    snapshot = repository.current()
    assert revision == snapshot.revision == 2
    assert snapshot.configuration.api.port == 9090
    assert snapshot.configuration.api.cors_origins == ("https://panel.lan",)


def test_invalid_and_stale_updates_leave_snapshot_unchanged(system_repository):
    repository, _engines = system_repository
    before = repository.current()
    with pytest.raises(ConfigValidationError, match="between 1 and 65535"):
        repository.update_section(
            "api", {"port": 70000}, expected_revision=1, actor="admin"
        )
    assert repository.current() == before
    repository.update_section(
        "logging", {"level": "DEBUG"}, expected_revision=1, actor="admin"
    )
    with pytest.raises(ConfigConflictError, match="revision 2"):
        repository.update_section(
            "logging", {"level": "ERROR"}, expected_revision=1, actor="stale"
        )
    assert repository.current().configuration.logging.level == "DEBUG"


def test_secret_keep_replace_and_clear_never_enter_public_snapshot(system_repository):
    repository, engines = system_repository
    repository.update_section(
        "mqtt",
        {"enabled": True, "host": "broker.lan"},
        expected_revision=1,
        secret_mutations={
            "mqtt_password": SecretMutation(
                SecretAction.REPLACE, "rotated-mqtt-password"
            ),
            "aemet_api_key": SecretMutation(SecretAction.KEEP),
        },
        actor="admin",
    )
    public = repository.public_snapshot()
    rendered = json.dumps(public)
    assert "rotated-mqtt-password" not in rendered
    assert all(value not in rendered for value in SENTINELS.values())
    assert public["secrets"]["mqtt_password"]["configured"] is True

    with pytest.raises(ConfigValidationError, match="mqtt_username/mqtt_password"):
        repository.update_section(
            "mqtt",
            {},
            expected_revision=2,
            secret_mutations={"mqtt_username": SecretMutation(SecretAction.CLEAR)},
            actor="admin",
        )
    assert "mqtt_username" in repository.current().secrets


def test_required_postgres_and_aemet_secrets_are_validated(system_repository):
    repository, _engines = system_repository
    repository.update_section(
        "database",
        {
            "driver": "postgresql",
            "host": "db.lan",
            "database": "dtc",
            "tls": True,
        },
        expected_revision=1,
        actor="admin",
    )
    with pytest.raises(ConfigValidationError, match="aemet_api_key"):
        repository.update_section(
            "weather",
            {"provider": "aemet", "municipality_code": "28079"},
            expected_revision=2,
            secret_mutations={"aemet_api_key": SecretMutation(SecretAction.CLEAR)},
            actor="admin",
        )


def test_weather_settings_round_trip_and_runtime_projection(system_repository):
    repository, _engines = system_repository
    revision = repository.update_section(
        "weather",
        {
            "provider": "aemet",
            "municipality_code": "28079",
            "timeout_seconds": 12.5,
            "simulated_average_temperature_c": 9.0,
            "simulated_minimum_temperature_c": 4.0,
            "fallback_average_temperature_c": 7.0,
            "fallback_minimum_temperature_c": 1.0,
            "retry_minutes": 20,
            "refresh_minutes": 240,
        },
        expected_revision=1,
        secret_mutations={
            "aemet_api_key": SecretMutation(SecretAction.REPLACE, "runtime-key")
        },
        actor="admin",
    )
    snapshot = repository.current()
    assert revision == snapshot.revision == 2
    assert snapshot.configuration.weather == WeatherSystemSettings(
        provider="aemet",
        municipality_code="28079",
        timeout_seconds=12.5,
        simulated_average_temperature_c=9.0,
        simulated_minimum_temperature_c=4.0,
        fallback_average_temperature_c=7.0,
        fallback_minimum_temperature_c=1.0,
        retry_minutes=20,
        refresh_minutes=240,
    )
    runtime = weather_config_from_system(snapshot.configuration.weather)
    assert runtime.provider == "aemet"
    assert runtime.aemet is not None
    assert runtime.aemet.municipality_code == "28079"
    assert runtime.aemet.timeout_seconds == 12.5
    assert runtime.fallback is not None
    assert runtime.fallback.average_temperature_c == 7.0
    assert runtime.watchdog.retry_minutes == 20
    public = repository.public_snapshot()
    assert public["sections"]["weather"]["municipality_code"] == "28079"
    assert "aemet_api_key" not in str(public["sections"]["weather"])
    assert public["secrets"]["aemet_api_key"]["configured"] is True


def test_public_catalog_is_allow_list_complete():
    expected_paths = {
        f"{section}.{field}"
        for section, fields in PUBLIC_SECTION_FIELDS.items()
        for field in fields
    }
    assert set(ACTIVATION_POLICIES) == expected_paths
    assert set(PUBLIC_SECTION_FIELDS) == set(SECTION_TYPES)


def test_audit_records_fields_and_result_but_never_values(system_repository):
    repository, _engines = system_repository
    repository.update_section(
        "mqtt",
        {"host": "broker.lan"},
        expected_revision=1,
        secret_mutations={
            "mqtt_password": SecretMutation(SecretAction.REPLACE, "new-secret")
        },
        actor="admin@panel",
    )
    with pytest.raises(ConfigValidationError):
        repository.update_section(
            "api", {"port": 0}, expected_revision=2, actor="bad-client"
        )
    events = repository.audit_events()
    assert [event["result"] for event in events] == [
        "succeeded",
        "succeeded",
        "rejected",
    ]
    rendered = json.dumps(events, default=str)
    assert "new-secret" not in rendered
    assert "mqtt_password" in rendered
    assert events[1]["revision_before"] == 1
    assert events[1]["revision_after"] == 2


def test_secret_table_kinds_are_explicit_and_no_public_dto_reads_values(system_repository):
    repository, engines = system_repository
    with engines.configuration.connect() as connection:
        rows = connection.execute(
            select(system_secret.c.name, system_secret.c.kind)
        ).all()
    assert dict(rows) == SECRET_KINDS
    public = repository.public_snapshot()
    assert all(set(item) == {"configured", "rotated_at"} for item in public["secrets"].values())
