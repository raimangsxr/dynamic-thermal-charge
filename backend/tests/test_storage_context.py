import multiprocessing as mp
from datetime import datetime, timezone

import pytest

from dynamic_thermal_charge.persistence.applied_revision import (
    AppliedRevisionRepository,
)
from dynamic_thermal_charge.persistence.canonical_engines import (
    build_canonical_engines,
)
from dynamic_thermal_charge.persistence.context import StorageContext
from dynamic_thermal_charge.persistence.locator import DatabaseLocator
from dynamic_thermal_charge.persistence.paths import StorePaths


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _initialise_store_in_child(directory: str) -> bool:
    context = StorageContext.initialise(StorePaths.in_directory(directory)).context
    context.close()
    return True


def test_context_initialises_and_reopens_without_database_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DTC_DATABASE_URL", "postgresql://must-be-ignored/ignored")
    paths = StorePaths.in_directory(tmp_path)
    result = StorageContext.initialise(paths)
    context = result.context
    assert result.bootstrap.onboarding_token
    assert context.generation.configuration.current()[0].heaters
    assert context.generation.system_configuration.current().revision == 1
    assert context.topology.as_public_dict()["canonical_driver"] == "sqlite"
    context.close()

    reopened = StorageContext.open(paths)
    assert reopened.generation.configuration.current()[1] == 1
    assert reopened.generation.system_configuration.current().revision == 1
    reopened.close()


def test_concurrent_initialisation_serialises_shared_sqlite_migrations(tmp_path):
    if "fork" not in mp.get_all_start_methods():
        pytest.skip("the deployment target uses fork for process startup")
    context = mp.get_context("fork")
    with context.Pool(3) as pool:
        results = pool.map(_initialise_store_in_child, [str(tmp_path)] * 3)
    assert results == [True, True, True]


def test_generation_replacement_waits_for_inflight_lease(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    context = StorageContext.initialise(paths).context
    old = context.generation
    locator, locator_revision = context.bootstrap.locator()
    prepared_engines = build_canonical_engines(locator, paths)

    with context.lease() as leased:
        assert leased is old
        new_locator_revision = context.activate_prepared(
            locator,
            prepared_engines,
            expected_locator_revision=locator_revision,
        )
        assert new_locator_revision == locator_revision + 1
        assert context.generation is not old
        assert old.retired is True
        assert old.closed is False
        assert context.generation.configuration.current()[1] == 1
    assert old.closed is True
    context.close()


def test_failed_generation_preflight_keeps_current_generation(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    context = StorageContext.initialise(paths).context
    current = context.generation
    locator, revision = context.bootstrap.locator()
    broken_paths = StorePaths.in_directory(tmp_path / "broken")
    broken = build_canonical_engines(DatabaseLocator.sqlite(), broken_paths)

    with pytest.raises(Exception, match="schema revision is missing"):
        context.activate_prepared(
            locator, broken, expected_locator_revision=revision
        )
    assert context.generation is current
    assert context.bootstrap.locator()[1] == revision
    context.close()


def test_applied_revision_tracks_convergence_and_restart(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    repository = context.generation.applied_revisions
    repository.publish(
        "api", applied_revision=2, desired_revision=2, state="applied"
    )
    repository.publish(
        "controller",
        applied_revision=1,
        desired_revision=2,
        state="pending_apply",
    )
    repository.publish(
        "mqtt",
        applied_revision=1,
        desired_revision=2,
        state="pending_restart",
    )
    statuses = repository.statuses()
    assert statuses["api"]["state"] == "applied"
    assert statuses["controller"]["state"] == "pending_apply"
    assert statuses["mqtt"]["state"] == "pending_restart"
    assert all(status["updated_at"].tzinfo is not None for status in statuses.values())
    context.close()


@pytest.mark.parametrize(
    "args",
    [
        ("other", 1, 1, "applied"),
        ("api", 2, 1, "applied"),
        ("api", 1, 2, "applied"),
        ("api", 1, 2, "unknown"),
    ],
)
def test_invalid_applied_revision_state_is_rejected(tmp_path, args):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    process, applied, desired, state = args
    with pytest.raises(ValueError):
        context.generation.applied_revisions.publish(
            process,
            applied_revision=applied,
            desired_revision=desired,
            state=state,
        )
    context.close()


def test_initialisation_refreshes_a_minimal_secret_safe_fallback(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    snapshot = context.fallback.snapshot()
    assert snapshot is not None
    assert snapshot.configuration["functional_revision"] >= 1
    assert "secrets" not in snapshot.configuration
    assert snapshot.plan is None
    context.close()
