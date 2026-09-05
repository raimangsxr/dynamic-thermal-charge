"""Schema, PRAGMAs, referential integrity and the temporal boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from dynamic_thermal_charge.persistence.engine import (
    SQLITE_PRAGMAS,
    build_engine,
    read_sqlite_pragmas,
)
from dynamic_thermal_charge.persistence.mapping import from_utc, to_utc
from dynamic_thermal_charge.persistence.schema import (
    heater as heater_table,
    indoor_reading,
    installation as installation_table,
    output_config as output_table,
    plan,
    metadata,
)
from dynamic_thermal_charge.persistence.url import parse_location


# --------------------------------------------------------------------------- #
# T012: SQLite ships foreign_keys OFF. Without the connect listener, half the
# integrity guarantees of the model would be decorative.
# --------------------------------------------------------------------------- #

def test_sqlite_pragmas(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    applied = read_sqlite_pragmas(engine)
    assert applied["foreign_keys"] == 1, "foreign keys would not be enforced"
    assert applied["journal_mode"] == "wal"
    assert applied["synchronous"] == 2  # FULL
    assert applied["busy_timeout"] == 5000


def test_every_declared_pragma_is_actually_read_back(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    applied = read_sqlite_pragmas(engine)
    assert set(applied) == {pragma for pragma, _ in SQLITE_PRAGMAS}


def test_pragmas_are_applied_to_every_new_connection(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_a_missing_directory_is_created(tmp_path):
    location = parse_location(f"sqlite:///{tmp_path / 'nested' / 'deep' / 'dtc.db'}")
    build_engine(location)
    assert (tmp_path / "nested" / "deep").is_dir()


# --------------------------------------------------------------------------- #
# T018: foreign keys are really enforced
# --------------------------------------------------------------------------- #

def _installation_row(now: datetime) -> dict:
    return {
        "name": "test",
        "revision": 1,
        "max_total_power_w": 6000,
        "slot_minutes": 30,
        "window_minutes": 480,
        "log_level": "INFO",
        "poll_seconds": 5.0,
        "retention_days": 365,
        "created_at": now,
        "updated_at": now,
    }


def test_deleting_an_installation_cascades_to_its_heaters(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    metadata.create_all(engine)
    now = datetime(2026, 1, 1, 12, 0)
    with engine.begin() as connection:
        installation_id = connection.execute(
            insert(installation_table).values(**_installation_row(now))
        ).inserted_primary_key[0]
        heater_key = connection.execute(
            insert(heater_table).values(
                installation_id=installation_id,
                heater_id="salon",
                name="Salon",
                power_w=1500,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=0,
                enabled=True,
                position=0,
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(output_table).values(
                heater_id=heater_key, kind="simulated", active_high=True
            )
        )
    with engine.begin() as connection:
        connection.execute(installation_table.delete())
    with engine.connect() as connection:
        assert connection.execute(select(heater_table)).first() is None
        assert connection.execute(select(output_table)).first() is None


def test_an_orphan_output_is_rejected(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    metadata.create_all(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(output_table).values(
                    heater_id=9999, kind="simulated", active_high=True
                )
            )


def test_a_gpio_output_without_a_pin_is_rejected(sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    metadata.create_all(engine)
    now = datetime(2026, 1, 1, 12, 0)
    with engine.begin() as connection:
        installation_id = connection.execute(
            insert(installation_table).values(**_installation_row(now))
        ).inserted_primary_key[0]
        heater_key = connection.execute(
            insert(heater_table).values(
                installation_id=installation_id,
                heater_id="salon",
                name="Salon",
                power_w=1500,
                full_charge_minutes=480,
                target_charge=1.0,
                priority=0,
                enabled=True,
                position=0,
            )
        ).inserted_primary_key[0]
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(output_table).values(
                    heater_id=heater_key, kind="gpio", pin=None, active_high=False
                )
            )


def test_the_schema_declares_every_expected_table():
    assert set(metadata.tables) == {
        "installation",
        "weather_config",
        "heater",
        "output_config",
        "thermal_profile",
            "forecast",
            "forecast_hour",
        "plan",
        "plan_slot",
        "plan_allocation",
        "output_transition",
        "config_change",
        # Added in 002-config-api: the controller's proof of life.
        "controller_heartbeat",
            "indoor_reading",
            "relay_test_control",
            "relay_test_session",
            "relay_test_output",
            "relay_test_event",
            "controller_log_event",
            "preview_job",
            "preview_job_step",
    }


def test_indoor_reading_uses_the_integer_heater_identity_without_cross_store_fk():
    assert indoor_reading.c.heater_pk.primary_key
    assert indoor_reading.c.heater_pk.type.python_type is int
    assert not indoor_reading.c.heater_pk.foreign_keys


def test_indoor_configuration_columns_have_compatible_defaults():
    assert heater_table.c.indoor_topic.nullable
    assert installation_table.c.indoor_max_age_minutes.server_default.arg == "30"
    assert installation_table.c.indoor_min_plausible_c.server_default.arg == "-20"
    assert installation_table.c.indoor_max_plausible_c.server_default.arg == "50"


def test_migrating_from_0002_preserves_existing_configuration(sqlite_url):
    from alembic import command

    from dynamic_thermal_charge.persistence.bootstrap import initialise, open_legacy_store
    from dynamic_thermal_charge.persistence.migrations import _config

    store = open_legacy_store({"DTC_DATABASE_URL": sqlite_url})
    initialise(store)
    config_before, revision_before = store.repository.current()

    command.downgrade(_config(store.engine), "0002_controller_heartbeat")
    command.upgrade(_config(store.engine), "head")

    config_after, revision_after = store.repository.current()
    assert config_after == config_before
    assert revision_after == revision_before


# --------------------------------------------------------------------------- #
# T024: instants survive the round trip; naive datetimes never escape
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "offset_hours",
    [0, 1, 2, -5, 5.5],
)
def test_an_instant_survives_the_round_trip_whatever_its_offset(offset_hours, sqlite_url):
    engine = build_engine(parse_location(sqlite_url))
    metadata.create_all(engine)
    zone = timezone(timedelta(hours=offset_hours))
    original = datetime(2026, 1, 15, 23, 30, tzinfo=zone)
    now = datetime(2026, 1, 1, 12, 0)
    with engine.begin() as connection:
        installation_id = connection.execute(
            insert(installation_table).values(**_installation_row(now))
        ).inserted_primary_key[0]
        connection.execute(
            insert(plan).values(
                installation_id=installation_id,
                installation_revision=1,
                window_start=to_utc(original),
                window_end=to_utc(original + timedelta(hours=8)),
                slot_minutes=30,
                created_at=to_utc(original),
            )
        )
    with engine.connect() as connection:
        stored = connection.execute(select(plan.c.window_start)).scalar()
    recovered = from_utc(stored)
    assert recovered == original, "the instant changed on the round trip"
    assert recovered.tzinfo is not None, "a naive datetime escaped the boundary"
    assert recovered.utcoffset() == timedelta(0), "reads must come back as UTC"


def test_a_naive_datetime_cannot_be_stored():
    with pytest.raises(ValueError, match="naive datetime"):
        to_utc(datetime(2026, 1, 15, 23, 30))


def test_from_utc_attaches_utc_to_a_stored_naive_value():
    recovered = from_utc(datetime(2026, 1, 15, 22, 30))
    assert recovered.tzinfo is timezone.utc


def test_from_utc_passes_none_through():
    assert from_utc(None) is None


# --------------------------------------------------------------------------- #
# T106 (SC-002): the half of "identical behaviour on both engines" that does not
# need a server, so it runs on every single test run rather than only when
# someone remembers to point DTC_TEST_POSTGRES_URL at a database.
# --------------------------------------------------------------------------- #

def test_both_dialects_compile_the_whole_schema():
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateIndex, CreateTable

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        for table in metadata.tables.values():
            statement = str(CreateTable(table).compile(dialect=dialect))
            assert table.name in statement
            for index in table.indexes:
                assert index.name in str(CreateIndex(index).compile(dialect=dialect))


def test_both_dialects_compile_the_same_statements():
    """The queries the repository issues must be portable, not just the DDL."""
    from sqlalchemy import delete, insert, select, update
    from sqlalchemy.dialects import postgresql, sqlite

    from dynamic_thermal_charge.persistence.schema import (
        config_change,
        forecast as forecast_table,
        heater as heater_table,
        output_transition,
    )

    statements = [
        select(installation_table).order_by(installation_table.c.id).limit(1),
        select(heater_table)
        .where(heater_table.c.installation_id == 1)
        .order_by(heater_table.c.position),
        update(installation_table)
        .where(
            (installation_table.c.id == 1) & (installation_table.c.revision == 1)
        )
        .values(revision=2),
        insert(config_change).values(
            installation_id=1,
            revision_before=1,
            revision_after=2,
            entity="installation",
            action="set",
            occurred_at=datetime(2026, 1, 1),
        ),
        delete(output_transition).where(
            output_transition.c.occurred_at < datetime(2026, 1, 1)
        ),
        delete(plan).where(
            (plan.c.created_at < datetime(2026, 1, 1))
            & (plan.c.window_end <= datetime(2026, 1, 2))
        ),
        delete(forecast_table).where(
            ~forecast_table.c.id.in_(
                select(plan.c.forecast_id).where(plan.c.forecast_id.is_not(None))
            )
        ),
    ]
    known_objects = {
        f"{table.name}.{column.name}"
        for table in metadata.tables.values()
        for column in table.columns
    } | set(metadata.tables)

    for statement in statements:
        # Comparing rendered SQL text across dialects is the wrong instrument.
        # "LIMIT ? OFFSET ?" versus "LIMIT %(param_1)s", or PostgreSQL adding a
        # RETURNING clause, are dialect capabilities, not portability problems.
        #
        # What the real risk looks like is an engine-specific construct that one
        # dialect cannot compile at all, or a reference to something outside the
        # schema. Both of those are what this checks.
        for name, dialect in (
            ("sqlite", sqlite.dialect()),
            ("postgresql", postgresql.dialect()),
        ):
            compiled = str(statement.compile(dialect=dialect))
            assert compiled.strip(), f"the statement compiled to nothing on {name}"
            referenced = set(re.findall(r"[a-z_]+\.[a-z_]+", compiled))
            unknown = referenced - known_objects
            assert not unknown, (
                f"on {name} the statement references objects outside the schema: "
                f"{sorted(unknown)}"
            )


def test_no_column_uses_an_engine_specific_type():
    """An engine-specific type would let the two backends drift apart."""
    from sqlalchemy.dialects import postgresql, sqlite

    for table in metadata.tables.values():
        for column in table.columns:
            for dialect in (sqlite.dialect(), postgresql.dialect()):
                # Compiling the type on both dialects is the check: a
                # PostgreSQL-only type such as JSONB raises on SQLite.
                column.type.compile(dialect=dialect)


# --------------------------------------------------------------------------- #
# The migrations must build exactly the schema that schema.py describes.
#
# This exists because of a real defect: 0001 originally called
# metadata.create_all(), which is not pinned in time. It created whatever
# schema.py described at the moment it ran, so as soon as 0002 added a table,
# 0001 created it too and 0002 failed with "already exists". The DDL is now
# explicit, which trades that failure for a different risk -- the hand-written
# DDL drifting from schema.py. This closes that risk.
# --------------------------------------------------------------------------- #

def test_the_migrations_build_exactly_the_declared_schema(sqlite_url):
    from sqlalchemy import inspect

    from dynamic_thermal_charge.persistence.bootstrap import initialise, open_legacy_store
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    store = open_legacy_store({DATABASE_URL_ENV: sqlite_url})
    initialise(store, allow_seed=False)
    inspector = inspect(store.engine)

    migrated = {
        name for name in inspector.get_table_names() if name != "alembic_version"
    }
    declared = set(metadata.tables)
    assert migrated == declared, (
        "the migrations and schema.py disagree on which tables exist; "
        f"only migrated: {sorted(migrated - declared)}; "
        f"only declared: {sorted(declared - migrated)}"
    )

    for table_name in sorted(declared):
        table = metadata.tables[table_name]
        migrated_columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        declared_columns = {column.name: column for column in table.columns}
        assert set(migrated_columns) == set(declared_columns), (
            f"table {table_name}: columns disagree; "
            f"only migrated: {sorted(set(migrated_columns) - set(declared_columns))}; "
            f"only declared: {sorted(set(declared_columns) - set(migrated_columns))}"
        )
        for name, declared_column in declared_columns.items():
            assert migrated_columns[name]["nullable"] == declared_column.nullable, (
                f"{table_name}.{name}: nullability disagrees between the migration "
                "and schema.py"
            )


def test_no_migration_imports_the_live_schema_module():
    """A migration built from live metadata is not pinned in time."""
    import ast
    from pathlib import Path

    versions = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "dynamic_thermal_charge"
        / "persistence"
        / "migrations"
        / "versions"
    )
    offenders = {}
    for path in versions.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        leaked = {name for name in imported if name.endswith("persistence.schema")}
        if leaked:
            offenders[path.name] = sorted(leaked)
    assert not offenders, (
        "these migrations import the live schema module, so they are not pinned "
        f"to their own revision: {offenders}"
    )
