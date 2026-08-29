"""Resumable local saga for switching the canonical database driver."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import shutil
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update

from .canonical_engines import build_canonical_engines, initialise_canonical_schemas
from .local_schema import migration_operation
from .locator import DatabaseDriver, DatabaseLocator
from .schema import (
    application_metadata, application_schema_version,
    configuration_metadata, configuration_schema_version,
)


PHASES = (
    "preflight", "prepare", "copy_configuration", "copy_application",
    "verify", "prepared", "commit_locator", "open_destination", "complete",
)


@dataclass(frozen=True)
class MigrationOperation:
    id: str
    phase: str
    status: str
    source_revision: int
    detail: str | None
    created_at: datetime
    updated_at: datetime

    def public_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.id, "phase": self.phase, "status": self.status,
            "source_revision": self.source_revision, "detail": self.detail,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class MigrationInProgress(RuntimeError):
    pass


class MigrationCoordinator:
    def __init__(self, context, *, clock=None, owner: str | None = None) -> None:
        self.context = context
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.owner = owner or str(uuid4())

    def preflight(self, locator: DatabaseLocator) -> dict[str, object]:
        """Test a candidate without changing bootstrap or creating schemas."""
        if locator.driver is DatabaseDriver.SQLITE:
            usage = shutil.disk_usage(self.context.paths.state_directory)
            if usage.free < 10 * 1024 * 1024:
                raise RuntimeError("insufficient free space for SQLite migration")
            return {"ok": True, "driver": "sqlite", "tls": None}
        from .engine import build_engine
        from .url import parse_location
        engine = build_engine(
            parse_location(locator.configuration_url(self.context.paths)),
            timeouts=(5, 5),
        )
        try:
            with engine.connect() as connection:
                connection.execute(select(1)).scalar_one()
        finally:
            engine.dispose()
        return {"ok": True, "driver": "postgresql", "tls": locator.tls}

    def start(
        self, locator: DatabaseLocator, *, expected_locator_revision: int,
        confirmed: bool,
    ) -> MigrationOperation:
        if not confirmed:
            raise ValueError("driver migration requires explicit confirmation")
        current, actual_revision = self.context.bootstrap.locator()
        if actual_revision != expected_locator_revision:
            raise MigrationInProgress("bootstrap locator revision changed")
        if current == locator:
            raise ValueError("destination is already canonical")
        operation_id = self._acquire(actual_revision)
        destination = None
        succeeded = False
        self.context.begin_migration()
        try:
            self._phase(operation_id, "preflight")
            self.preflight(locator)
            self._phase(operation_id, "prepare")
            destination = build_canonical_engines(locator, self.context.paths, timeouts=(5, 5))
            initialise_canonical_schemas(destination)
            self._phase(operation_id, "copy_configuration")
            _copy_metadata(
                self.context.generation.engines.configuration,
                destination.configuration,
                configuration_metadata,
                excluded={configuration_schema_version.name},
            )
            self._phase(operation_id, "copy_application")
            _copy_metadata(
                self.context.generation.engines.application,
                destination.application,
                application_metadata,
                excluded={application_schema_version.name},
            )
            self._phase(operation_id, "verify")
            _verify_metadata(
                self.context.generation.engines.configuration,
                destination.configuration,
                configuration_metadata,
                excluded={configuration_schema_version.name},
            )
            _verify_metadata(
                self.context.generation.engines.application,
                destination.application,
                application_metadata,
                excluded={application_schema_version.name},
            )
            self._phase(operation_id, "prepared")
            self._phase(operation_id, "commit_locator")
            self.context.activate_prepared(
                locator, destination,
                expected_locator_revision=expected_locator_revision,
            )
            destination = None  # now owned by StorageContext
            self._phase(operation_id, "open_destination")
            self.context.refresh_fallback()
            self._phase(operation_id, "complete", status="succeeded")
            succeeded = True
            return self.operation(operation_id)
        except Exception as exc:
            self._phase(
                operation_id, self.operation(operation_id).phase,
                status="failed", detail=exc.__class__.__name__,
            )
            raise
        finally:
            if destination is not None:
                destination.configuration.dispose()
                if destination.application is not destination.configuration:
                    destination.application.dispose()
            self.context.end_migration(succeeded=succeeded)
            try:
                snapshot = self.context.generation.system_configuration.current()
                self.context.generation.system_configuration.record_audit(
                    actor=self.owner,
                    action="migration",
                    section="database",
                    fields=("driver",),
                    revision_before=snapshot.revision,
                    revision_after=snapshot.revision,
                    result="succeeded" if succeeded else "rejected",
                )
            except Exception:
                # Audit must never turn a completed/failed storage operation
                # into a second failure when the canonical store is unavailable.
                pass

    def operation(self, operation_id: str) -> MigrationOperation:
        with self.context.bootstrap.engine.connect() as connection:
            row = connection.execute(
                select(migration_operation).where(migration_operation.c.id == operation_id)
            ).mappings().one()
        return _map_operation(row)

    def active(self) -> MigrationOperation | None:
        with self.context.bootstrap.engine.connect() as connection:
            row = connection.execute(
                select(migration_operation)
                .where(migration_operation.c.status == "running")
                .order_by(migration_operation.c.created_at.desc()).limit(1)
            ).mappings().first()
        return None if row is None else _map_operation(row)

    def _acquire(self, source_revision: int) -> str:
        now = self.clock().astimezone(timezone.utc)
        expires = now + timedelta(minutes=10)
        operation_id = str(uuid4())
        with self.context.bootstrap.engine.begin() as connection:
            active = connection.execute(
                select(migration_operation).where(
                    (migration_operation.c.status == "running")
                    & (migration_operation.c.lease_expires_at > now.isoformat())
                )
            ).first()
            if active:
                raise MigrationInProgress("another driver migration is in progress")
            connection.execute(insert(migration_operation).values(
                id=operation_id, phase="preflight", status="running",
                lease_owner=self.owner, lease_expires_at=expires.isoformat(),
                source_revision=source_revision, detail=None,
                created_at=now.isoformat(), updated_at=now.isoformat(),
            ))
        return operation_id

    def _phase(self, operation_id: str, phase: str, *, status="running", detail=None) -> None:
        if phase not in PHASES:
            raise ValueError(f"unknown migration phase {phase}")
        now = self.clock().astimezone(timezone.utc)
        with self.context.bootstrap.engine.begin() as connection:
            changed = connection.execute(
                update(migration_operation)
                .where((migration_operation.c.id == operation_id)
                       & (migration_operation.c.lease_owner == self.owner))
                .values(phase=phase, status=status, detail=detail,
                        lease_expires_at=(now + timedelta(minutes=10)).isoformat(),
                        updated_at=now.isoformat())
            )
        if changed.rowcount != 1:
            raise MigrationInProgress("migration lease was lost")


def _tables(metadata, excluded):
    return [table for table in metadata.sorted_tables if table.name not in excluded]


def _copy_metadata(source, destination, metadata, *, excluded) -> None:
    tables = _tables(metadata, excluded)
    with source.connect() as source_connection, destination.begin() as destination_connection:
        for table in reversed(tables):
            destination_connection.execute(delete(table))
        for table in tables:
            rows = source_connection.execute(select(table)).mappings().all()
            for offset in range(0, len(rows), 250):
                destination_connection.execute(insert(table), [dict(row) for row in rows[offset:offset + 250]])


def _verify_metadata(source, destination, metadata, *, excluded) -> None:
    with source.connect() as left, destination.connect() as right:
        for table in _tables(metadata, excluded):
            left_count = left.execute(select(func.count()).select_from(table)).scalar_one()
            right_count = right.execute(select(func.count()).select_from(table)).scalar_one()
            if left_count != right_count:
                raise RuntimeError(f"verification count mismatch for {table.name}")
            if _table_checksum(left, table) != _table_checksum(right, table):
                raise RuntimeError(f"verification checksum mismatch for {table.name}")


def _table_checksum(connection, table) -> str:
    """Stable row checksum catches same-count but different-content copies."""
    rows = connection.execute(select(table)).mappings().all()
    values = [dict(row) for row in rows]
    values.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
    payload = json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _map_operation(row) -> MigrationOperation:
    return MigrationOperation(
        id=str(row["id"]), phase=str(row["phase"]), status=str(row["status"]),
        source_revision=int(row["source_revision"]), detail=row["detail"],
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


__all__ = ["MigrationCoordinator", "MigrationInProgress", "MigrationOperation", "PHASES"]
