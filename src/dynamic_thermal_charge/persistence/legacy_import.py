"""Explicit, isolated one-time importer for pre-bootstrap installations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import delete, func, inspect, insert, select

from .bootstrap import initialise_at, open_legacy_store
from .locator import DatabaseDriver, DatabaseLocator
from .migration import MigrationCoordinator
from .paths import StorePaths
from .schema import application_metadata, configuration_metadata, metadata
from .secret_digest import digest_secret
from .system_configuration import SecretAction, SecretMutation


@dataclass(frozen=True)
class LegacyImportReport:
    source_driver: str
    installation_present: bool
    table_counts: dict[str, int]
    recognized_settings: tuple[str, ...]
    missing_settings: tuple[str, ...]
    applied: bool
    already_imported: bool = False

    def public_dict(self) -> dict[str, object]:
        return {
            "source_driver": self.source_driver,
            "installation_present": self.installation_present,
            "table_counts": self.table_counts,
            "recognized_settings": list(self.recognized_settings),
            "missing_settings": list(self.missing_settings),
            "applied": self.applied,
            "already_imported": self.already_imported,
        }


def import_legacy(
    environment_file: Path, target_paths: StorePaths,
    *, apply: bool,
) -> LegacyImportReport:
    environment = _read_environment(environment_file)
    database_url = environment.get("DTC_DATABASE_URL", "").strip()
    if not database_url:
        raise ValueError("legacy environment has no DTC_DATABASE_URL")
    source = open_legacy_store({"DTC_DATABASE_URL": database_url})
    config, _revision = source.repository.current()
    source_tables = set(inspect(source.engine).get_table_names())
    table_counts = {}
    with source.engine.connect() as connection:
        for name in sorted(source_tables & set(metadata.tables)):
            table_counts[name] = int(connection.execute(
                select(func.count()).select_from(metadata.tables[name])
            ).scalar_one())
    known = tuple(sorted(set(environment) & _LEGACY_KEYS))
    missing = tuple(sorted(_LEGACY_KEYS - set(environment)))
    report = LegacyImportReport(
        source_driver=source.location.backend, installation_present=True,
        table_counts=table_counts, recognized_settings=known,
        missing_settings=missing, applied=apply,
    )
    if not apply:
        return report

    target, _init_report, _token = initialise_at(target_paths, allow_seed=False)
    if not target.repository.is_empty():
        current, _ = target.repository.current()
        if current == config:
            return LegacyImportReport(**{**report.__dict__, "already_imported": True})
        raise ValueError("target already contains a different functional configuration")
    _copy_legacy_tables(source.engine, target.configuration_engine, configuration_metadata)
    _copy_legacy_tables(source.engine, target.application_engine, application_metadata)
    _apply_system_environment(target.system_configuration, environment, config)
    target.context.refresh_fallback()

    if source.location.backend == "postgresql":
        locator = _postgres_locator(database_url)
        _current, locator_revision = target.context.bootstrap.locator()
        MigrationCoordinator(target.context).start(
            locator, expected_locator_revision=locator_revision, confirmed=True
        )
    return report


def _copy_legacy_tables(source_engine, destination_engine, destination_metadata) -> None:
    source_names = set(inspect(source_engine).get_table_names())
    targets = [table for table in destination_metadata.sorted_tables if table.name in source_names and table.name in metadata.tables]
    with source_engine.connect() as source, destination_engine.begin() as destination:
        for target in reversed(targets):
            destination.execute(delete(target))
        for target in targets:
            rows = source.execute(select(metadata.tables[target.name])).mappings().all()
            if rows:
                destination.execute(insert(target), [dict(row) for row in rows])


def _apply_system_environment(repository, environment, functional) -> None:
    parsed_database = urlsplit(environment["DTC_DATABASE_URL"])
    api_patch = {
        "host": environment.get("DTC_API_HOST", "127.0.0.1") or "127.0.0.1",
        "port": int(environment.get("DTC_API_PORT", "8080") or 8080),
        "stale_seconds": _optional_float(environment.get("DTC_API_STALE_SECONDS")),
        "cors_origins": tuple(item.strip() for item in environment.get("DTC_API_CORS_ORIGINS", "").split(",") if item.strip()),
    }
    sections = {
        "api": api_patch,
        "mqtt": {
            "enabled": bool(environment.get("DTC_MQTT_HOST", "").strip()),
            "host": environment.get("DTC_MQTT_HOST") or None,
            "port": int(environment.get("DTC_MQTT_PORT", "1883") or 1883),
            "tls": _bool(environment.get("DTC_MQTT_TLS"), False),
            "prefix": environment.get("DTC_MQTT_PREFIX", "dtc") or "dtc",
            "discovery_prefix": environment.get("DTC_MQTT_DISCOVERY_PREFIX", "homeassistant") or "homeassistant",
            "publish_seconds": float(environment.get("DTC_MQTT_PUBLISH_SECONDS", "15") or 15),
        },
        "weather": {
            "provider": "simulated" if functional.weather is None else functional.weather.provider,
            "municipality_code": (
                functional.weather.aemet.municipality_code
                if functional.weather is not None and functional.weather.aemet is not None
                else None
            ),
            "timeout_seconds": (
                functional.weather.aemet.timeout_seconds
                if functional.weather is not None and functional.weather.aemet is not None
                else 10.0
            ),
        },
        "logging": {
            "level": functional.logging.level,
            "max_events": int(environment.get("DTC_CONTROLLER_LOG_MAX_EVENTS", "1000") or 1000),
        },
        "operations": {
            "controller_poll_seconds": functional.runtime.poll_seconds,
            "relay_test_lease_seconds": int(environment.get("DTC_RELAY_TEST_LEASE_SECONDS", "30") or 30),
            "retention_days": functional.retention_days,
        },
    }
    secrets: dict[str, SecretMutation] = {}
    mappings = {
        "DTC_MQTT_USERNAME": "mqtt_username", "DTC_MQTT_PASSWORD": "mqtt_password",
        "AEMET_API_KEY": "aemet_api_key",
    }
    for legacy, current in mappings.items():
        if environment.get(legacy):
            secrets[current] = SecretMutation(SecretAction.REPLACE, environment[legacy])
    if environment.get("DTC_API_TOKEN"):
        secrets["admin_token_digest"] = SecretMutation(
            SecretAction.REPLACE, digest_secret(environment["DTC_API_TOKEN"])
        )
    if parsed_database.scheme.startswith("postgresql"):
        sections["database"] = {
            "driver": "postgresql", "host": parsed_database.hostname,
            "port": parsed_database.port, "database": unquote(parsed_database.path).lstrip("/"),
            "tls": True, "trusted_no_tls": False,
        }
        secrets["postgres_username"] = SecretMutation(
            SecretAction.REPLACE, unquote(parsed_database.username or "")
        )
        secrets["postgres_password"] = SecretMutation(
            SecretAction.REPLACE, unquote(parsed_database.password or "")
        )
    for section, patch in sections.items():
        revision = repository.current().revision
        section_secrets = {
            name: value for name, value in secrets.items()
            if section == "api" and name == "admin_token_digest"
        }
        if section == "mqtt":
            section_secrets = {name: value for name, value in secrets.items() if name.startswith("mqtt_")}
        if section == "weather":
            section_secrets = {name: value for name, value in secrets.items() if name == "aemet_api_key"}
        if section == "database":
            section_secrets = {name: value for name, value in secrets.items() if name.startswith("postgres_")}
        repository.update_section(
            section, patch, expected_revision=revision,
            secret_mutations=section_secrets, actor="legacy-import",
        )


def _read_environment(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line or line.startswith("export "):
            raise ValueError(f"unsupported legacy environment syntax at line {number}")
        name, value = line.split("=", 1)
        if name in _LEGACY_KEYS:
            result[name] = value.strip().strip('"').strip("'")
    return result


def _postgres_locator(url: str) -> DatabaseLocator:
    parsed = urlsplit(url)
    return DatabaseLocator(
        DatabaseDriver.POSTGRESQL, host=parsed.hostname, port=parsed.port,
        database=unquote(parsed.path).lstrip("/"), username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""), tls=True,
    )


def _bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip(): return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}: return True
    if normalized in {"0", "false", "no", "off"}: return False
    raise ValueError("legacy boolean value is invalid")


def _optional_float(value: str | None):
    return None if value is None or not value.strip() else float(value)


_LEGACY_KEYS = frozenset({
    "DTC_DATABASE_URL", "DTC_API_TOKEN", "DTC_API_HOST", "DTC_API_PORT",
    "DTC_API_STALE_SECONDS", "DTC_API_CORS_ORIGINS", "DTC_MQTT_HOST",
    "DTC_MQTT_PORT", "DTC_MQTT_TLS", "DTC_MQTT_USERNAME", "DTC_MQTT_PASSWORD",
    "DTC_MQTT_PREFIX", "DTC_MQTT_DISCOVERY_PREFIX", "DTC_MQTT_PUBLISH_SECONDS",
    "DTC_RELAY_TEST_LEASE_SECONDS", "DTC_CONTROLLER_LOG_MAX_EVENTS", "AEMET_API_KEY",
})


__all__ = ["LegacyImportReport", "import_legacy"]
