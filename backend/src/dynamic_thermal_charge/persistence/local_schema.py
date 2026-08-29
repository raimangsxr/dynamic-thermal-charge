"""Independent schemas and migrations for mandatory local SQLite stores."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    select,
)
from sqlalchemy.engine import Engine

from .topology import BootstrapCorruptError, BootstrapIncompatibleError


BOOTSTRAP_SCHEMA_REVISION = 1
FALLBACK_SCHEMA_REVISION = 1

bootstrap_metadata = MetaData()
bootstrap_schema_version = Table(
    "bootstrap_schema_version",
    bootstrap_metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", Integer, nullable=False),
)
bootstrap_state = Table(
    "bootstrap_state",
    bootstrap_metadata,
    Column("id", Integer, primary_key=True),
    Column("installation_state", String(32), nullable=False),
    Column("locator_revision", Integer, nullable=False),
    Column("onboarding_digest", Text, nullable=True),
    Column("onboarding_expires_at", String(40), nullable=True),
    Column("onboarding_attempts", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
active_locator = Table(
    "active_locator",
    bootstrap_metadata,
    Column("id", Integer, primary_key=True),
    Column("driver", String(16), nullable=False),
    Column("host", String(255), nullable=True),
    Column("port", Integer, nullable=True),
    Column("database_name", String(255), nullable=True),
    Column("username", String(255), nullable=True),
    Column("password", Text, nullable=True),
    Column("tls", Boolean, nullable=False),
    Column("trusted_no_tls", Boolean, nullable=False),
)
migration_operation = Table(
    "migration_operation",
    bootstrap_metadata,
    Column("id", String(36), primary_key=True),
    Column("phase", String(32), nullable=False),
    Column("status", String(24), nullable=False),
    Column("lease_owner", String(64), nullable=True),
    Column("lease_expires_at", String(40), nullable=True),
    Column("source_revision", Integer, nullable=False),
    Column("detail", Text, nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)

fallback_metadata = MetaData()
fallback_schema_version = Table(
    "fallback_schema_version",
    fallback_metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", Integer, nullable=False),
)
continuity_snapshot = Table(
    "continuity_snapshot",
    fallback_metadata,
    Column("id", Integer, primary_key=True),
    Column("configuration_revision", Integer, nullable=False),
    Column("captured_at", String(40), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column("configuration_json", Text, nullable=False),
    Column("plan_json", Text, nullable=True),
    Column("admin_token_digest", Text, nullable=True),
)
fallback_outbox = Table(
    "fallback_outbox",
    fallback_metadata,
    Column("event_id", String(36), primary_key=True),
    Column("event_type", String(64), nullable=False),
    Column("payload_version", Integer, nullable=False),
    Column("aggregate_id", String(128), nullable=False),
    Column("aggregate_order", Integer, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("occurred_at", String(40), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("delivered_at", String(40), nullable=True),
)
reconciliation_state = Table(
    "reconciliation_state",
    fallback_metadata,
    Column("id", Integer, primary_key=True),
    Column("last_attempt_at", String(40), nullable=True),
    Column("last_success_at", String(40), nullable=True),
    Column("last_error_code", String(64), nullable=True),
)


def upgrade_bootstrap_schema(engine: Engine) -> None:
    _upgrade(
        engine,
        metadata=bootstrap_metadata,
        version_table=bootstrap_schema_version,
        expected=BOOTSTRAP_SCHEMA_REVISION,
        label="bootstrap",
    )


def upgrade_fallback_schema(engine: Engine) -> None:
    _upgrade(
        engine,
        metadata=fallback_metadata,
        version_table=fallback_schema_version,
        expected=FALLBACK_SCHEMA_REVISION,
        label="fallback",
    )


def _upgrade(
    engine: Engine,
    *,
    metadata: MetaData,
    version_table: Table,
    expected: int,
    label: str,
) -> None:
    tables_before = set(inspect(engine).get_table_names())
    if version_table.name in tables_before:
        with engine.connect() as connection:
            rows = connection.execute(select(version_table.c.revision)).scalars().all()
        if len(rows) != 1:
            raise BootstrapCorruptError(
                f"{label} schema has an ambiguous revision record"
            )
        revision = int(rows[0])
        if revision > expected:
            raise BootstrapIncompatibleError(
                f"{label} schema revision {revision} is newer than supported {expected}"
            )
        if revision < expected:
            raise BootstrapIncompatibleError(
                f"{label} schema revision {revision} has no registered upgrade path"
            )
        metadata.create_all(engine)
        return
    if tables_before:
        raise BootstrapCorruptError(
            f"{label} store has tables but no schema revision"
        )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version_table.insert().values(id=1, revision=expected))


__all__ = [
    "BOOTSTRAP_SCHEMA_REVISION",
    "FALLBACK_SCHEMA_REVISION",
    "active_locator",
    "bootstrap_metadata",
    "bootstrap_schema_version",
    "bootstrap_state",
    "continuity_snapshot",
    "fallback_metadata",
    "fallback_outbox",
    "fallback_schema_version",
    "migration_operation",
    "reconciliation_state",
    "upgrade_bootstrap_schema",
    "upgrade_fallback_schema",
]
