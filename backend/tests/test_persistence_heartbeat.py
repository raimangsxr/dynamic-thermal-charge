"""The controller's heartbeat: FR-014, FR-048b, FR-053."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from dynamic_thermal_charge.persistence.heartbeat import (
    SqlHeartbeatPublisher,
    read_heartbeat,
)
from dynamic_thermal_charge.persistence.schema import controller_heartbeat


NOW = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def publisher(initialised_store):
    return SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="simulated",
        started_at=NOW - timedelta(hours=3),
        runner_id="runner-a",
        location=initialised_store.location,
    )


def _rows(store) -> int:
    with store.engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(controller_heartbeat)
            ).scalar()
            or 0
        )


# --------------------------------------------------------------------------- #
# Publishing and reading
# --------------------------------------------------------------------------- #

def test_reading_before_any_heartbeat_returns_none(initialised_store):
    assert (
        read_heartbeat(
            initialised_store.engine, initialised_store.repository.installation_id()
        )
        is None
    )


def test_the_first_publication_creates_the_row(initialised_store, publisher):
    publisher.publish(NOW, degraded=False)
    assert _rows(initialised_store) == 1
    heartbeat = publisher.read()
    assert heartbeat is not None
    assert heartbeat.updated_at == NOW
    assert heartbeat.started_at == NOW - timedelta(hours=3)
    assert heartbeat.degraded is False
    assert heartbeat.poll_seconds == 5.0
    assert heartbeat.driver_kind == "simulated"
    assert heartbeat.runner_id == "runner-a"
    assert heartbeat.plan_id is None


def test_successive_publications_update_without_growing(initialised_store, publisher):
    """The row is updated in place: this is why it stays out of retention."""
    for minute in range(20):
        publisher.publish(NOW + timedelta(minutes=minute), degraded=False)
    assert _rows(initialised_store) == 1, "the heartbeat grew instead of updating"
    assert publisher.read().updated_at == NOW + timedelta(minutes=19)


def test_the_heartbeat_carries_the_plan_it_is_executing(initialised_store, publisher, recorder):
    from dynamic_thermal_charge.scheduler import ChargeScheduler

    config, revision = initialised_store.repository.current()
    plan = ChargeScheduler().build(config.site, config.heaters, NOW)
    plan_ref = recorder.record_plan(plan, None, revision)
    publisher.publish(NOW, degraded=False, plan_ref=plan_ref)
    assert publisher.read().plan_id == plan_ref.id


def test_degradation_is_reflected_both_ways(initialised_store, publisher):
    publisher.publish(NOW, degraded=True)
    assert publisher.read().degraded is True
    publisher.publish(NOW + timedelta(seconds=5), degraded=False)
    assert publisher.read().degraded is False


def test_instants_survive_the_round_trip_as_utc(initialised_store):
    """The temporal boundary rule applies here too."""
    local = datetime(2026, 1, 16, 2, 0, tzinfo=timezone(timedelta(hours=1)))
    publisher = SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="gpio",
        started_at=local,
        runner_id="runner-b",
    )
    publisher.publish(local, degraded=False)
    heartbeat = publisher.read()
    assert heartbeat.updated_at == local
    assert heartbeat.updated_at.tzinfo is not None
    assert heartbeat.updated_at.utcoffset() == timedelta(0)


def test_a_runner_generates_its_own_identifier_when_not_given(initialised_store):
    first = SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="simulated",
    )
    second = SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,
        driver_kind="simulated",
    )
    assert first.runner_id != second.runner_id, (
        "two controller processes must be distinguishable"
    )


def test_the_cadence_published_is_the_one_the_process_runs_with(initialised_store):
    """Not the stored configuration: the process may predate the last edit."""
    _, revision = initialised_store.repository.current()
    initialised_store.repository.set_field(
        revision, "installation", None, "poll_seconds", "30"
    )
    publisher = SqlHeartbeatPublisher(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5.0,  # what this process actually started with
        driver_kind="simulated",
    )
    publisher.publish(NOW, degraded=False)
    assert publisher.read().poll_seconds == 5.0


# --------------------------------------------------------------------------- #
# The hard rule: publishing can never stop the control loop
# --------------------------------------------------------------------------- #

def test_a_write_failure_does_not_propagate(initialised_store, publisher, caplog):
    import logging

    with initialised_store.engine.begin() as connection:
        connection.execute(text("DROP TABLE controller_heartbeat"))

    with caplog.at_level(logging.ERROR):
        publisher.publish(NOW, degraded=False)  # must not raise

    assert "heartbeat" in caplog.text.lower()
    assert "control continues" in caplog.text


def test_a_read_failure_is_not_silently_swallowed(initialised_store, publisher):
    """Reading is the API's side, and there a failure must be visible."""
    from dynamic_thermal_charge.persistence import ConfigStoreError

    with initialised_store.engine.begin() as connection:
        connection.execute(text("DROP TABLE controller_heartbeat"))
    with pytest.raises(ConfigStoreError):
        publisher.read()


# --------------------------------------------------------------------------- #
# FR-048b: the first migration over a real installation's data
# --------------------------------------------------------------------------- #

def test_migrating_from_phase_one_preserves_data(sqlite_url):
    """Seed on 0001, migrate to 0002, and lose nothing."""
    from alembic import command

    from dynamic_thermal_charge.persistence import SchemaStatus
    from dynamic_thermal_charge.persistence.bootstrap import initialise, open_legacy_store
    from dynamic_thermal_charge.persistence.migrations import _config

    store = open_legacy_store({"DTC_DATABASE_URL": sqlite_url})

    # Stop at the previous phase's revision, as a real installation would be.
    command.upgrade(_config(store.engine), "0001_initial_schema")
    assert store.gate.check() is SchemaStatus.BEHIND, (
        "a phase-1 database must read as pending migration, never as unknown"
    )
    store.repository.seed(
        __import__(
            "dynamic_thermal_charge.persistence.seed", fromlist=["example_installation"]
        ).example_installation(),
        "Instalación de ejemplo",
    )
    before, revision_before = store.repository.current()
    _, revision = store.repository.current()
    store.repository.set_field(revision, "installation", None, "poll_seconds", "7")
    edited, edited_revision = store.repository.current()

    # Now upgrade, as `dtc db upgrade` would.
    initialise(store, allow_seed=False)

    assert store.gate.check() is SchemaStatus.OK
    after, revision_after = store.repository.current()
    assert after == edited, "the migration altered the stored configuration"
    assert revision_after == edited_revision
    assert after.runtime.poll_seconds == 7.0


def test_a_phase_one_database_is_behind_not_unknown(sqlite_url):
    """The failure mode phase 1 armed on purpose; we are its first candidate."""
    from alembic import command

    from dynamic_thermal_charge.persistence import SchemaStatus, SchemaVersionError
    from dynamic_thermal_charge.persistence.migrations import _config
    from dynamic_thermal_charge.persistence.bootstrap import open_legacy_store

    store = open_legacy_store({"DTC_DATABASE_URL": sqlite_url})

    command.upgrade(_config(store.engine), "0001_initial_schema")
    assert store.gate.check() is SchemaStatus.BEHIND
    with pytest.raises(SchemaVersionError, match="db upgrade"):
        store.gate.require_ready()
