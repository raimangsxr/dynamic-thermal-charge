"""PostgreSQL compatibility: SC-002, end-to-end half.

Skipped unless ``DTC_TEST_POSTGRES_URL`` names a real server. Never runs in the
default suite and never on the deployment target (constitution principle V). The
half of SC-002 that does run everywhere lives in
``test_persistence_schema.py::test_both_dialects_compile_the_same_statements``.

To run it:

    DTC_TEST_POSTGRES_URL='postgresql+pg8000://dtc:pw@host:5432/dtc_test' pytest -m postgres
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from dynamic_thermal_charge.persistence.bootstrap import initialise, open_store
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV
from dynamic_thermal_charge.scheduler import ChargeScheduler


pytestmark = pytest.mark.postgres

WINDOW_START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def postgres_store():
    url = os.environ["DTC_TEST_POSTGRES_URL"]
    store = open_store({DATABASE_URL_ENV: url})
    # Start from a clean slate: this suite owns the test database.
    from dynamic_thermal_charge.persistence.schema import metadata

    metadata.drop_all(store.engine)
    with store.engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    initialise(store)
    return store


def test_the_schema_is_created_on_postgresql(postgres_store):
    from dynamic_thermal_charge.persistence import SchemaStatus

    assert postgres_store.gate.check() is SchemaStatus.OK


def test_the_seeded_configuration_is_identical_to_the_local_one(postgres_store):
    config, revision = postgres_store.repository.current()
    assert revision == 1
    assert config == example_installation()


def test_the_plan_is_identical_to_the_one_from_a_local_database(postgres_store):
    """SC-002: same installation, same plan, whichever engine holds it."""
    stored, _ = postgres_store.repository.current()
    reference = example_installation()
    scheduler = ChargeScheduler()
    assert scheduler.build(
        stored.site, stored.heaters, WINDOW_START
    ) == scheduler.build(reference.site, reference.heaters, WINDOW_START)


def test_editing_works_the_same_way(postgres_store):
    repository = postgres_store.repository
    _, revision = repository.current()
    change = repository.set_field(
        revision, "installation", None, "max_total_power_kw", "6.0"
    )
    assert change.old_value == "5200"
    assert change.new_value == "6000"
    config, new_revision = repository.current()
    assert config.site.max_total_power_w == 6000
    assert new_revision == revision + 1


def test_an_invalid_edit_is_refused_the_same_way(postgres_store):
    from dynamic_thermal_charge.persistence import ConfigValidationError

    repository = postgres_store.repository
    before, revision = repository.current()
    with pytest.raises(ConfigValidationError):
        repository.set_field(revision, "installation", None, "slot_minutes", "45")
    after, after_revision = repository.current()
    assert after == before
    assert after_revision == revision


def test_instants_survive_the_round_trip_on_postgresql(postgres_store):
    from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder
    from dynamic_thermal_charge.persistence.mapping import from_utc
    from dynamic_thermal_charge.persistence.schema import plan as plan_table
    from sqlalchemy import select

    config, revision = postgres_store.repository.current()
    recorder = SqlHistoryRecorder(
        postgres_store.engine, postgres_store.repository.installation_id()
    )
    plan = ChargeScheduler().build(config.site, config.heaters, WINDOW_START)
    recorder.record_plan(plan, None, revision)
    with postgres_store.engine.connect() as connection:
        stored = connection.execute(select(plan_table.c.window_start)).scalar()
    assert from_utc(stored) == WINDOW_START


def test_foreign_keys_are_enforced_on_postgresql(postgres_store):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from dynamic_thermal_charge.persistence.schema import output_config

    with pytest.raises(IntegrityError):
        with postgres_store.engine.begin() as connection:
            connection.execute(
                insert(output_config).values(
                    heater_id=999999, kind="simulated", active_high=True
                )
            )
