"""Schema version gate: FR-010, research.md D5."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import text

from dynamic_thermal_charge.persistence import SchemaStatus, SchemaVersionError
from dynamic_thermal_charge.persistence.bootstrap import initialise
from dynamic_thermal_charge.persistence.gate import EXPECTED_REVISION, VERSION_TABLE


def _force_revision(store, revision: str) -> None:
    with store.engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {VERSION_TABLE}"))
        connection.execute(
            text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES (:v)"),
            {"v": revision},
        )


def test_an_uninitialised_database_reports_missing(store):
    assert store.gate.check() is SchemaStatus.MISSING
    with pytest.raises(SchemaVersionError, match="db init"):
        store.gate.require_ready()


def test_the_expected_revision_reports_ok(initialised_store):
    assert initialised_store.gate.check() is SchemaStatus.OK
    initialised_store.gate.require_ready()  # must not raise


def test_a_known_older_revision_reports_behind(initialised_store, monkeypatch):
    import dynamic_thermal_charge.persistence.gate as gate_module

    monkeypatch.setattr(
        gate_module, "KNOWN_REVISIONS", ("0000_older", EXPECTED_REVISION)
    )
    _force_revision(initialised_store, "0000_older")
    assert initialised_store.gate.check() is SchemaStatus.BEHIND
    with pytest.raises(SchemaVersionError, match="db upgrade"):
        initialised_store.gate.require_ready()


def test_an_unknown_revision_rejects_start_up(initialised_store):
    """A newer binary migrated the database. Never operate on what we cannot read."""
    _force_revision(initialised_store, "9999_from_the_future")
    assert initialised_store.gate.check() is SchemaStatus.UNKNOWN
    with pytest.raises(SchemaVersionError) as error:
        initialised_store.gate.require_ready()
    message = str(error.value)
    assert "9999_from_the_future" in message
    assert EXPECTED_REVISION in message
    assert "does not understand" in message
    # There is no degraded mode over an unreadable schema.
    assert "upgrade" not in message.lower().replace("update the service", "")


def test_the_gate_does_not_import_alembic(initialised_store):
    """Alembic costs seconds on the deployment target; keep it off the hot path."""
    for module in [name for name in sys.modules if name.startswith("alembic")]:
        del sys.modules[module]
    initialised_store.gate.check()
    assert not any(name.startswith("alembic") for name in sys.modules)
