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


CONFIGURATION_SCHEMA_REVISION = 1
APPLICATION_SCHEMA_REVISION = 2
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
            if label != "application":
                raise BootstrapIncompatibleError(
                    f"{label} schema revision {revision} has no registered upgrade path"
                )
            _upgrade_application_schema(engine, revision, expected)
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
    if revision != expected:
        raise BootstrapIncompatibleError(
            f"application schema revision {revision} has no registered upgrade path to {expected}"
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
