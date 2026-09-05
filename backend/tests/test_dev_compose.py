"""Deterministic checks for the local Compose environments."""

from pathlib import Path

from dynamic_thermal_charge.entrypoints import _dev_postgres_locator, initialise_dev_storage
from dynamic_thermal_charge.persistence.bootstrap_store import inspect_bootstrap
from dynamic_thermal_charge.persistence.bootstrap import open_store
from dynamic_thermal_charge.persistence.locator import DatabaseDriver
from dynamic_thermal_charge.persistence.paths import StorePaths


ROOT = Path(__file__).resolve().parents[2]


def test_dev_compose_matrix_has_isolated_state_and_one_shot_postgres_override():
    sqlite = (ROOT / "deploy/compose.dev.yaml").read_text()
    postgres = (ROOT / "deploy/compose.dev-postgres.yaml").read_text()

    assert all(f"  {service}:" in sqlite for service in ("frontend", "backend", "backend-api", "backend-mqtt", "mosquitto"))
    assert "postgres:" not in sqlite
    assert "dev-sqlite-state" in sqlite
    assert 'entrypoint: ["python"]' in sqlite
    assert "service_completed_successfully" in sqlite
    assert "connection_messages false" in (ROOT / "deploy/mosquitto.dev.conf").read_text()
    assert "postgres:" in postgres
    assert "dev-postgres-state" in postgres
    assert "dev-postgres-data" in postgres
    assert "healthcheck" in postgres


def test_dev_postgres_locator_uses_all_configurable_connection_fields(monkeypatch):
    values = {
        "DEV_POSTGRES_HOST": "db",
        "DEV_POSTGRES_PORT": "5544",
        "DEV_POSTGRES_DB": "thermal",
        "DEV_POSTGRES_USER": "operator",
        "DEV_POSTGRES_PASSWORD": "secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    locator = _dev_postgres_locator()

    assert locator.driver is DatabaseDriver.POSTGRESQL
    assert (locator.host, locator.port, locator.database) == ("db", 5544, "thermal")
    assert (locator.username, locator.password) == ("operator", "secret")
    assert locator.tls is False and locator.trusted_no_tls is True


def test_dev_sqlite_initialisation_is_simulated_and_idempotent(tmp_path, monkeypatch):
    paths = StorePaths.in_directory(tmp_path / "state")
    monkeypatch.setattr(StorePaths, "production", classmethod(lambda cls: paths))
    monkeypatch.setenv("DEV_DATABASE", "sqlite")
    monkeypatch.setenv("DTC_API_TOKEN", "dev-token-please-use-a-longer-value")

    initialise_dev_storage()
    first = open_store(paths)
    config, _ = first.repository.current()
    system = first.system_configuration.current()
    initialise_dev_storage()
    second = open_store(paths)

    assert inspect_bootstrap(paths)["locator"]["driver"] == "sqlite"
    assert config.weather is not None and config.weather.provider == "simulated"
    assert all(heater.output.kind == "gpio" for heater in config.heaters)
    assert system.configuration.weather.provider == "simulated"
    assert system.configuration.output.driver == "simulated"
    assert system.configuration.mqtt.enabled is True
    assert system.secrets["admin_token_digest"].value
    assert second.repository.current()[1] == first.repository.current()[1]
