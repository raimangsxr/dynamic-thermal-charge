"""Schema version gate.

Deliberately does **not** import Alembic (research.md D4): it reads the
``alembic_version`` table with Core and compares it against the revisions this
build ships. ``KNOWN_REVISIONS`` is a constant rather than a directory scan so
that start-up costs nothing; a test keeps it from drifting from the files on
disk.

A revision this service does not know can only come from a newer binary that
already migrated the database. Interpreting it would mean guessing at columns we
do not understand in order to decide which relay to close, so the gate rejects
start-up instead: principle I resolves ambiguity towards the safe state.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from . import SchemaStatus, SchemaVersionError
from .engine import store_errors
from .url import StoreLocation


logger = logging.getLogger(__name__)

# Oldest first. Must stay in step with persistence/migrations/versions/; a test
# fails if it drifts.
#
# Adding a revision here is not optional bookkeeping: without it, a database that
# this very build just migrated would be read as UNKNOWN and the service would
# refuse to start. That is the failure mode the previous phase armed on purpose,
# and its first possible victim is this one.
KNOWN_REVISIONS: tuple[str, ...] = (
    "0001_initial_schema",
    "0002_controller_heartbeat",
    "0003_indoor_temperature",
    "0004_relay_test_mode",
    "0005_controller_log_events",
)
EXPECTED_REVISION = KNOWN_REVISIONS[-1]

VERSION_TABLE = "alembic_version"


class SchemaVersionGate:
    def __init__(self, engine: Engine, location: StoreLocation | None = None) -> None:
        self._engine = engine
        self._location = location

    def stored_revision(self) -> str | None:
        """The revision recorded in the database, or None if not initialised."""
        with store_errors(self._location):
            inspector = inspect(self._engine)
            if not inspector.has_table(VERSION_TABLE):
                return None
            with self._engine.connect() as connection:
                revision = connection.execute(
                    text(f"SELECT version_num FROM {VERSION_TABLE}")
                ).scalar()
        return None if revision is None else str(revision)

    def check(self) -> SchemaStatus:
        revision = self.stored_revision()
        if revision is None:
            return SchemaStatus.MISSING
        if revision == EXPECTED_REVISION:
            return SchemaStatus.OK
        if revision in KNOWN_REVISIONS:
            return SchemaStatus.BEHIND
        return SchemaStatus.UNKNOWN

    def require_ready(self) -> None:
        """Raise unless the schema is exactly the one this service understands."""
        status = self.check()
        if status is SchemaStatus.OK:
            return
        if status is SchemaStatus.MISSING:
            raise SchemaVersionError(
                "the configuration database is not initialised; ask the administrator to "
                "initialise it before starting the service"
            )
        if status is SchemaStatus.BEHIND:
            raise SchemaVersionError(
                f"the configuration database is at schema revision "
                f"{self.stored_revision()} and this service expects "
                f"{EXPECTED_REVISION}; ask the administrator to migrate it before starting the service"
            )
        raise SchemaVersionError(
            f"the configuration database is at schema revision "
            f"{self.stored_revision()}, which this service does not understand "
            f"(it knows up to {EXPECTED_REVISION}). The database was migrated by a "
            "newer build. Update the service; it will not run against a schema it "
            "cannot interpret"
        )


__all__ = [
    "EXPECTED_REVISION",
    "KNOWN_REVISIONS",
    "SchemaVersionGate",
    "VERSION_TABLE",
]
