from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3

import pytest
from sqlalchemy import inspect, select, update

from dynamic_thermal_charge.persistence import ConfigConflictError
from dynamic_thermal_charge.persistence.bootstrap_store import (
    BootstrapRepository,
    inspect_bootstrap,
)
from dynamic_thermal_charge.persistence.local_schema import (
    BOOTSTRAP_SCHEMA_REVISION,
    active_locator,
    bootstrap_metadata,
    bootstrap_schema_version,
    bootstrap_state,
)
from dynamic_thermal_charge.persistence.locator import DatabaseDriver, DatabaseLocator
from dynamic_thermal_charge.persistence.paths import StorePaths
from dynamic_thermal_charge.persistence.topology import (
    BootstrapCorruptError,
    BootstrapIncompatibleError,
)


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def test_initialise_creates_minimal_schema_with_protected_permissions(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = BootstrapRepository(paths, clock=lambda: NOW)
    result = repository.initialise()

    assert result.created is True
    assert result.onboarding_token
    assert result.locator == DatabaseLocator.sqlite()
    assert result.locator_revision == 1
    assert oct(tmp_path.stat().st_mode & 0o777) == "0o700"
    assert oct(paths.bootstrap.stat().st_mode & 0o777) == "0o600"
    assert set(inspect(repository.engine).get_table_names()) == set(
        bootstrap_metadata.tables
    )


def test_initialise_is_idempotent_and_never_reissues_the_token(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    first = BootstrapRepository(paths, clock=lambda: NOW).initialise()
    second = BootstrapRepository(paths, clock=lambda: NOW).initialise()
    assert first.onboarding_token
    assert second.created is False
    assert second.onboarding_token is None
    assert BootstrapRepository(paths, clock=lambda: NOW).onboarding_token_matches(
        first.onboarding_token
    )


def test_expired_onboarding_token_is_rejected(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = BootstrapRepository(
        paths, clock=lambda: NOW, onboarding_lifetime=timedelta(seconds=1)
    )
    token = repository.initialise().onboarding_token
    later = BootstrapRepository(paths, clock=lambda: NOW + timedelta(seconds=2))
    assert token is not None
    assert later.onboarding_token_matches(token) is False


def test_locator_compare_and_swap_is_atomic_and_secret_free(tmp_path):
    repository = BootstrapRepository(StorePaths.in_directory(tmp_path), clock=lambda: NOW)
    repository.initialise()
    locator = DatabaseLocator(
        driver=DatabaseDriver.POSTGRESQL,
        host="db.lan",
        port=5432,
        database="dtc",
        username="dtc-user",
        password="sentinel-password",
        tls=True,
    )
    assert repository.compare_and_swap_locator(1, locator) == 2
    loaded, revision = repository.locator()
    assert loaded == locator
    assert revision == 2
    assert "sentinel-password" not in repr(loaded)
    assert "sentinel-password" not in json.dumps(loaded.public_dict())
    with pytest.raises(ConfigConflictError):
        repository.compare_and_swap_locator(1, DatabaseLocator.sqlite())
    assert repository.locator() == (locator, 2)


def test_future_schema_is_rejected_without_modification(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = BootstrapRepository(paths, clock=lambda: NOW)
    repository.initialise()
    with repository.engine.begin() as connection:
        connection.execute(
            update(bootstrap_schema_version).values(
                revision=BOOTSTRAP_SCHEMA_REVISION + 1
            )
        )
    before = paths.bootstrap.read_bytes()
    with pytest.raises(BootstrapIncompatibleError):
        BootstrapRepository(paths, clock=lambda: NOW)
    assert paths.bootstrap.read_bytes() == before


def test_store_with_tables_but_no_revision_is_corrupt(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    connection = sqlite3.connect(paths.bootstrap)
    connection.execute("CREATE TABLE mystery (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    with pytest.raises(BootstrapCorruptError, match="no schema revision"):
        BootstrapRepository(paths, clock=lambda: NOW)


def test_doctor_is_read_only_for_missing_healthy_and_incompatible_stores(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    assert inspect_bootstrap(paths)["status"] == "missing"
    assert not paths.bootstrap.exists()

    repository = BootstrapRepository(paths, clock=lambda: NOW)
    repository.initialise()
    healthy = inspect_bootstrap(paths)
    assert healthy["status"] == "ok"
    assert healthy["locator"] == {
        "driver": "sqlite",
        "host": None,
        "port": None,
        "database": None,
        "tls": False,
    }
    with repository.engine.begin() as connection:
        connection.execute(
            update(bootstrap_schema_version).values(
                revision=BOOTSTRAP_SCHEMA_REVISION + 1
            )
        )
    incompatible = paths.bootstrap.read_bytes()
    with pytest.raises(BootstrapIncompatibleError):
        inspect_bootstrap(paths)
    assert paths.bootstrap.read_bytes() == incompatible
    with repository.engine.connect() as connection:
        assert connection.execute(select(bootstrap_schema_version.c.revision)).scalar_one() == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host": None, "database": "dtc", "username": "u", "password": "p"},
        {"host": "db", "database": None, "username": "u", "password": "p"},
        {"host": "db", "database": "dtc", "username": None, "password": "p"},
        {"host": "db", "database": "dtc", "username": "u", "password": None},
        {"host": "db", "port": 70000, "database": "dtc", "username": "u", "password": "p"},
    ],
)
def test_invalid_postgresql_locator_fields_are_rejected(kwargs):
    with pytest.raises(ValueError):
        DatabaseLocator(driver=DatabaseDriver.POSTGRESQL, tls=True, **kwargs)


def test_postgresql_without_tls_requires_explicit_trusted_network():
    values = dict(
        driver=DatabaseDriver.POSTGRESQL,
        host="db",
        database="dtc",
        username="u",
        password="p",
        tls=False,
    )
    with pytest.raises(ValueError, match="trusted-network"):
        DatabaseLocator(**values)
    assert DatabaseLocator(**values, trusted_no_tls=True).public_dict()["tls"] is False
