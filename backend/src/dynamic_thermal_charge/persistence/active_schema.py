"""Independent lifecycle for canonical configuration and application schemas."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import MetaData, Table, inspect, select, text, update
from sqlalchemy.engine import Engine

from .schema import (
    application_metadata,
    application_schema_version,
    configuration_metadata,
    configuration_schema_version,
)
from .topology import BootstrapCorruptError, BootstrapIncompatibleError
from . import SchemaStatus, SchemaVersionError


CONFIGURATION_SCHEMA_REVISION = 5
APPLICATION_SCHEMA_REVISION = 4
POSTGRES_CONFIGURATION_SCHEMA = "dtc_config"
POSTGRES_APPLICATION_SCHEMA = "dtc_app"


@dataclass(frozen=True)
class ActiveSchemaStatus:
    configuration_revision: int
    application_revision: int


class ActiveSchemaGate:
    def __init__(self, configuration_engine: Engine, application_engine: Engine) -> None:
        self._configuration_engine = configuration_engine
        self._application_engine = application_engine

    def check(self) -> SchemaStatus:
        statuses = (
            _status(self._configuration_engine, configuration_schema_version,
                    CONFIGURATION_SCHEMA_REVISION),
            _status(self._application_engine, application_schema_version,
                    APPLICATION_SCHEMA_REVISION),
        )
        if SchemaStatus.UNKNOWN in statuses:
            return SchemaStatus.UNKNOWN
        if SchemaStatus.MISSING in statuses:
            return SchemaStatus.MISSING
        if SchemaStatus.BEHIND in statuses:
            return SchemaStatus.BEHIND
        return SchemaStatus.OK

    def require_ready(self) -> None:
        status = self.check()
        if status is SchemaStatus.OK:
            return
        if status is SchemaStatus.MISSING:
            raise SchemaVersionError("an active schema is missing; ask the administrator to initialise it")
        if status is SchemaStatus.BEHIND:
            raise SchemaVersionError("an active schema needs migration; ask the administrator to migrate it")
        raise SchemaVersionError(
            "an active schema revision is newer or invalid; update the service"
        )


def _status(engine: Engine, table: Table, expected: int) -> SchemaStatus:
    if table.name not in inspect(engine).get_table_names():
        return SchemaStatus.MISSING
    with engine.connect() as connection:
        revisions = connection.execute(select(table.c.revision)).scalars().all()
    if len(revisions) != 1:
        return SchemaStatus.UNKNOWN
    revision = int(revisions[0])
    if revision == expected:
        return SchemaStatus.OK
    if revision < expected:
        return SchemaStatus.BEHIND
    return SchemaStatus.UNKNOWN


def upgrade_active_schemas(
    configuration_engine: Engine, application_engine: Engine
) -> ActiveSchemaStatus:
    config_revision = _upgrade(
        configuration_engine,
        configuration_metadata,
        configuration_schema_version,
        CONFIGURATION_SCHEMA_REVISION,
        "configuration",
    )
    application_revision = _upgrade(
        application_engine,
        application_metadata,
        application_schema_version,
        APPLICATION_SCHEMA_REVISION,
        "application",
    )
    return ActiveSchemaStatus(config_revision, application_revision)


def require_active_schemas(
    configuration_engine: Engine, application_engine: Engine
) -> ActiveSchemaStatus:
    return ActiveSchemaStatus(
        _require(
            configuration_engine,
            configuration_schema_version,
            CONFIGURATION_SCHEMA_REVISION,
            "configuration",
        ),
        _require(
            application_engine,
            application_schema_version,
            APPLICATION_SCHEMA_REVISION,
            "application",
        ),
    )


def _upgrade(
    engine: Engine,
    metadata: MetaData,
    version_table: Table,
    expected: int,
    label: str,
) -> int:
    existing = set(inspect(engine).get_table_names())
    if version_table.name in existing:
        revision = _stored_revision(engine, version_table, label)
        if revision > expected:
            raise BootstrapIncompatibleError(
                f"{label} schema revision {revision} is newer than supported {expected}"
            )
        if revision < expected:
            if label == "application":
                _upgrade_application_schema(engine, revision, expected)
            else:
                _upgrade_configuration_schema(engine, revision, expected)
            with engine.begin() as connection:
                connection.execute(
                    update(version_table).where(version_table.c.id == 1).values(revision=expected)
                )
            revision = expected
        metadata.create_all(engine)
        return revision
    if existing:
        raise BootstrapCorruptError(
            f"{label} store has tables but no independent schema revision"
        )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version_table.insert().values(id=1, revision=expected))
    return expected


def _require(engine: Engine, table: Table, expected: int, label: str) -> int:
    if table.name not in inspect(engine).get_table_names():
        raise BootstrapCorruptError(f"{label} schema revision is missing")
    revision = _stored_revision(engine, table, label)
    if revision != expected:
        direction = "newer" if revision > expected else "older"
        raise BootstrapIncompatibleError(
            f"{label} schema revision {revision} is {direction} than supported {expected}"
        )
    return revision


def _stored_revision(engine: Engine, table: Table, label: str) -> int:
    with engine.connect() as connection:
        revisions = connection.execute(select(table.c.revision)).scalars().all()
    if len(revisions) != 1:
        raise BootstrapCorruptError(f"{label} schema revision is ambiguous")
    return int(revisions[0])


def _upgrade_application_schema(engine: Engine, revision: int, expected: int) -> None:
    """Apply the small, portable application-schema upgrades in order."""
    if revision == 1 and expected >= 2:
        columns = {
            column["name"] for column in inspect(engine).get_columns("forecast_cycle")
        }
        additions = (
            ("last_attempt_at", "DATETIME"),
            ("last_result", "VARCHAR(16)"),
            ("next_run_at", "DATETIME"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE forecast_cycle ADD COLUMN {name} {definition}"))
        revision = 2
    if revision == 2 and expected >= 3:
        columns = {column["name"] for column in inspect(engine).get_columns("automatic_plan_slot")}
        with engine.begin() as connection:
            for name in ("initial_soc_json", "demand_json", "heater_power_json"):
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE automatic_plan_slot ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'"))
        revision = 3
    if revision == 3 and expected >= 4:
        from .schema import preview_job, preview_job_step
        application_metadata.create_all(engine, tables=[preview_job, preview_job_step])
        revision = 4
    if revision != expected:
        raise BootstrapIncompatibleError(
            f"application schema revision {revision} has no registered upgrade path to {expected}"
        )


def _upgrade_configuration_schema(engine: Engine, revision: int, expected: int) -> None:
    if revision == 1 and expected >= 2:
        site_columns = {column["name"] for column in inspect(engine).get_columns("charge_planning_site")}
        heater_columns = {column["name"] for column in inspect(engine).get_columns("heater_charge_config")}
        additions = (
            ("contracted_power_w", "INTEGER NOT NULL DEFAULT 5200"),
            ("max_heating_power_w", "INTEGER NOT NULL DEFAULT 5200"),
            ("design_indoor_temperature_c", "FLOAT NOT NULL DEFAULT 21"),
            ("design_outdoor_temperature_c", "FLOAT NOT NULL DEFAULT 0"),
            ("feedback_horizon_hours", "FLOAT NOT NULL DEFAULT 6"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in site_columns:
                    connection.execute(text(f"ALTER TABLE charge_planning_site ADD COLUMN {name} {definition}"))
            if "demand_factor" not in heater_columns:
                connection.execute(text("ALTER TABLE heater_charge_config ADD COLUMN demand_factor FLOAT NOT NULL DEFAULT 1"))
            connection.execute(text(
                "UPDATE charge_planning_site SET "
                "contracted_power_w = (SELECT max_total_power_w FROM installation WHERE installation.id = charge_planning_site.installation_id), "
                "max_heating_power_w = (SELECT max_total_power_w FROM installation WHERE installation.id = charge_planning_site.installation_id)"
            ))
            connection.execute(text(
                "UPDATE heater_charge_config SET demand_factor = COALESCE(("
                "SELECT thermal_profile.thermal_factor FROM thermal_profile "
                "JOIN heater ON heater.id = thermal_profile.heater_id "
                "WHERE heater.heater_id = heater_charge_config.heater_id "
                "AND heater.installation_id = heater_charge_config.installation_id"
                "), 1)"
            ))
        revision = 2
    if revision == 2 and expected >= 3:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        additions = (
            ("mqtt_simulation_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("mqtt_simulation_initial_temperature_c", "FLOAT NOT NULL DEFAULT 45"),
            ("mqtt_simulation_publish_seconds", "FLOAT NOT NULL DEFAULT 30"),
            ("mqtt_simulation_topic_prefix", "VARCHAR(256) NOT NULL DEFAULT 'dtc/sim'"),
            ("mqtt_simulation_thermal_loss_c_per_hour", "FLOAT NOT NULL DEFAULT 2"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in site_columns:
                    connection.execute(
                        text(f"ALTER TABLE charge_planning_site ADD COLUMN {name} {definition}")
                    )
        revision = 3
    if revision == 3 and expected >= 4:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        if "base_load_w" not in site_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE charge_planning_site ADD COLUMN base_load_w INTEGER NOT NULL DEFAULT 0")
                )
        revision = 4
    if revision == 4 and expected >= 5:
        with engine.begin() as connection:
            connection.execute(text("UPDATE charge_planning_site SET forecast_horizon_hours = 24"))
        revision = 5
    if revision != expected:
        raise BootstrapIncompatibleError(
            f"configuration schema revision {revision} has no registered upgrade path to {expected}"
        )


__all__ = [
    "APPLICATION_SCHEMA_REVISION",
    "CONFIGURATION_SCHEMA_REVISION",
    "POSTGRES_APPLICATION_SCHEMA",
    "POSTGRES_CONFIGURATION_SCHEMA",
    "ActiveSchemaStatus",
    "ActiveSchemaGate",
    "require_active_schemas",
    "upgrade_active_schemas",
]
