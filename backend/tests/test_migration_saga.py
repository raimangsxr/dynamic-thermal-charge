from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from dynamic_thermal_charge.persistence.context import StorageContext
from dynamic_thermal_charge.persistence.local_schema import migration_operation
from dynamic_thermal_charge.persistence.locator import DatabaseLocator
from dynamic_thermal_charge.persistence.migration import MigrationCoordinator, MigrationInProgress
from dynamic_thermal_charge.persistence.paths import StorePaths
from tests.conftest import AUTH


def test_preflight_is_ephemeral_and_never_changes_locator(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    locator, revision = context.bootstrap.locator()
    result = MigrationCoordinator(context).preflight(DatabaseLocator.sqlite())
    assert result == {"ok": True, "driver": "sqlite", "tls": None}
    assert context.bootstrap.locator() == (locator, revision)
    with context.bootstrap.engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(migration_operation)).scalar_one() == 0


def test_migration_requires_confirmation_and_exclusive_unexpired_lease(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    coordinator = MigrationCoordinator(context, owner="one")
    with pytest.raises(ValueError, match="confirmation"):
        coordinator.start(DatabaseLocator.sqlite(), expected_locator_revision=1, confirmed=False)
    coordinator._acquire(1)
    with pytest.raises(MigrationInProgress):
        MigrationCoordinator(context, owner="two")._acquire(1)


def test_database_preflight_api_does_not_persist_candidate(client, initialised_store):
    before = initialised_store.context.bootstrap.locator()
    response = client.post(
        "/api/v1/system/tests/database", headers=AUTH,
        json={"driver": "sqlite"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert initialised_store.context.bootstrap.locator() == before
