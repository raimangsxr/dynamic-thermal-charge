"""Independent active-schema version gate."""

import sys

import pytest

from dynamic_thermal_charge.persistence import SchemaStatus, SchemaVersionError
from dynamic_thermal_charge.persistence.schema import configuration_schema_version


def _force_revision(store, revision: int) -> None:
    with store.engine.begin() as connection:
        connection.execute(configuration_schema_version.update().values(revision=revision))


def test_a_missing_active_schema_reports_missing(store):
    configuration_schema_version.drop(store.engine)
    assert store.gate.check() is SchemaStatus.MISSING
    with pytest.raises(SchemaVersionError, match="db init"):
        store.gate.require_ready()


def test_the_expected_revision_reports_ok(initialised_store):
    assert initialised_store.gate.check() is SchemaStatus.OK
    initialised_store.gate.require_ready()


def test_an_older_revision_reports_behind(initialised_store):
    _force_revision(initialised_store, 0)
    assert initialised_store.gate.check() is SchemaStatus.BEHIND
    with pytest.raises(SchemaVersionError, match="db upgrade"):
        initialised_store.gate.require_ready()


def test_a_future_revision_rejects_start_up(initialised_store):
    _force_revision(initialised_store, 9999)
    assert initialised_store.gate.check() is SchemaStatus.UNKNOWN
    with pytest.raises(SchemaVersionError, match="update the service"):
        initialised_store.gate.require_ready()


def test_the_gate_does_not_import_alembic(initialised_store):
    for module in [name for name in sys.modules if name.startswith("alembic")]:
        del sys.modules[module]
    initialised_store.gate.check()
    assert not any(name.startswith("alembic") for name in sys.modules)
