from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, inspect, select, text, update

from dynamic_thermal_charge.models import IndoorReading
from dynamic_thermal_charge.persistence import ConfigConflictError
from dynamic_thermal_charge.persistence.active_schema import (
    APPLICATION_SCHEMA_REVISION,
    CONFIGURATION_SCHEMA_REVISION,
    POSTGRES_APPLICATION_SCHEMA,
    POSTGRES_CONFIGURATION_SCHEMA,
    require_active_schemas,
    upgrade_active_schemas,
)
from dynamic_thermal_charge.persistence.canonical_engines import (
    build_canonical_engines,
    initialise_canonical_schemas,
)
from dynamic_thermal_charge.persistence.history import SqlHistoryRecorder
from dynamic_thermal_charge.persistence.locator import DatabaseLocator
from dynamic_thermal_charge.persistence.paths import StorePaths
from dynamic_thermal_charge.persistence.relay_test import SqlRelayTestRepository
from dynamic_thermal_charge.persistence.repository import (
    SqlConfigRepository,
    SqlIndoorReadingRepository,
)
from dynamic_thermal_charge.persistence.schema import (
    APPLICATION_TABLES,
    CONFIG_TABLES,
    application_metadata,
    application_schema_version,
    automatic_plan,
    automatic_plan_slot,
    configuration_metadata,
    configuration_schema_version,
)
from dynamic_thermal_charge.persistence.seed import example_installation
from dynamic_thermal_charge.persistence.topology import BootstrapIncompatibleError


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def split_store(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    engines = build_canonical_engines(DatabaseLocator.sqlite(), paths)
    initialise_canonical_schemas(engines)
    repository = SqlConfigRepository(
        engines.configuration,
        engines.configuration_location,
        clock=lambda: NOW,
        relay_test_engine=engines.application,
    )
    repository.seed(example_installation(), "split-test")
    return paths, engines, repository


def test_sqlite_materialises_configuration_and_application_separately(split_store):
    paths, engines, _repository = split_store
    assert paths.configuration.exists() and paths.application.exists()
    assert paths.configuration != paths.application
    assert set(inspect(engines.configuration).get_table_names()) == set(
        configuration_metadata.tables
    )
    assert set(inspect(engines.application).get_table_names()) == set(
        application_metadata.tables
    )
    assert not (set(CONFIG_TABLES) & set(APPLICATION_TABLES))
    assert set(configuration_metadata.tables).isdisjoint(application_metadata.tables)
    status = require_active_schemas(engines.configuration, engines.application)
    assert status.configuration_revision == CONFIGURATION_SCHEMA_REVISION
    assert status.application_revision == APPLICATION_SCHEMA_REVISION


def test_configuration_repository_never_writes_application_store(split_store):
    _paths, engines, repository = split_store
    app_before = engines.application.connect().execute(
        select(application_schema_version.c.revision)
    ).scalar_one()
    config, revision = repository.current()
    repository.set_field(revision, "installation", None, "poll_seconds", "8")
    assert repository.current()[0].runtime.poll_seconds == 8
    with engines.application.connect() as connection:
        assert connection.execute(
            select(application_schema_version.c.revision)
        ).scalar_one() == app_before


def test_application_status_upgrade_preserves_plan_slots_and_allows_converging(
    split_store,
):
    _paths, engines, _repository = split_store
    end = NOW + timedelta(hours=1)
    with engines.application.begin() as connection:
        plan_id = connection.execute(
            insert(automatic_plan).values(
                installation_id=1,
                configuration_revision=1,
                constraints_revision=1,
                forecast_id=None,
                horizon_start=NOW,
                horizon_end=end,
                slot_minutes=30,
                status="FEASIBLE",
                reason="periodic",
                input_token="migration-status-test",
                score_json="[]",
                deficits_json="[]",
                inputs_json="{}",
                active=True,
                created_at=NOW,
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(automatic_plan_slot).values(
                plan_id=plan_id,
                slot_start=NOW,
                slot_end=NOW + timedelta(minutes=30),
                heater_ids_json="[\"salon\"]",
                power_w=2800,
                stored_charge_json="{}",
                required_charge_json="{}",
                outdoor_temperature_c=5.0,
            )
        )
        connection.execute(
            update(application_schema_version).values(revision=8)
        )

    upgrade_active_schemas(engines.configuration, engines.application)

    with engines.application.connect() as connection:
        assert connection.execute(
            select(automatic_plan_slot.c.plan_id).where(
                automatic_plan_slot.c.plan_id == plan_id
            )
        ).scalar_one() == plan_id
        connection.execute(
            insert(automatic_plan).values(
                installation_id=1,
                configuration_revision=1,
                constraints_revision=1,
                forecast_id=None,
                horizon_start=NOW,
                horizon_end=end,
                slot_minutes=30,
                status="CONVERGING",
                reason="periodic",
                input_token="converging-status-test",
                score_json="[]",
                deficits_json="[]",
                inputs_json="{}",
                active=False,
                created_at=NOW + timedelta(minutes=1),
            )
        )
    status_sql = " ".join(
        str(item.get("sqltext", ""))
        for item in inspect(engines.application).get_check_constraints("automatic_plan")
    )
    assert "CONVERGING" in status_sql


def test_history_and_indoor_readings_use_application_engine(split_store):
    _paths, engines, repository = split_store
    installation_id = repository.installation_id()
    history = SqlHistoryRecorder(
        engines.application, installation_id, engines.application_location
    )
    forecast = SimpleNamespace(
        date=NOW.date(),
        average_temperature_c=7.0,
        minimum_temperature_c=2.0,
        maximum_temperature_c=12.0,
        source="simulated",
        location=None,
        retrieved_at=NOW,
    )
    assert history.record_forecast(forecast) is not None
    assert history.row_counts()["forecast"] == 1

    indoor = SqlIndoorReadingRepository(
        engines.application,
        engines.application_location,
        configuration_engine=engines.configuration,
    )
    indoor.upsert(IndoorReading("salon", 19.5, NOW))
    assert indoor.read_all()["salon"].celsius == 19.5
    indoor.invalidate("salon")
    assert indoor.read_all() == {}


def test_relay_test_snapshots_config_then_writes_only_application(split_store):
    _paths, engines, repository = split_store
    relay = SqlRelayTestRepository(
        engines.application,
        engines.application_location,
        clock=lambda: NOW,
        configuration_engine=engines.configuration,
    )
    view = relay.claim("owner-digest", NOW, 30)
    assert view["session"]["status"] == "starting"
    assert view["heaters"]

    _, revision = repository.current()
    with pytest.raises(ConfigConflictError, match="relay test"):
        repository.set_field(
            revision, "installation", None, "max_total_power_kw", "6"
        )


def test_independent_schema_version_failure_does_not_modify_the_other_store(split_store):
    _paths, engines, _repository = split_store
    with engines.configuration.begin() as connection:
        connection.execute(
            update(configuration_schema_version).values(
                revision=CONFIGURATION_SCHEMA_REVISION + 1
            )
        )
    with pytest.raises(BootstrapIncompatibleError):
        require_active_schemas(engines.configuration, engines.application)
    with engines.application.connect() as connection:
        assert connection.execute(
            select(application_schema_version.c.revision)
        ).scalar_one() == APPLICATION_SCHEMA_REVISION


def test_active_schema_groups_old_indoor_and_soc_topics_without_inventing_one(
    split_store,
):
    _paths, engines, repository = split_store
    with engines.configuration.begin() as connection:
        connection.execute(text("ALTER TABLE heater ADD COLUMN indoor_topic VARCHAR(512)"))
        connection.execute(
            text(
                "ALTER TABLE heater_charge_config "
                "ADD COLUMN stored_soc_topic VARCHAR(512)"
            )
        )
        connection.execute(
            text(
                "UPDATE heater SET indoor_topic = 'ha/shared' "
                "WHERE heater_id = 'salon'"
            )
        )
        connection.execute(
            text(
                "UPDATE heater_charge_config SET stored_soc_topic = 'ha/shared' "
                "WHERE heater_id = 'salon'"
            )
        )
        connection.execute(
            text(
                "UPDATE heater SET indoor_topic = 'ha/temperature' "
                "WHERE heater_id = 'entrada'"
            )
        )
        connection.execute(
            text(
                "UPDATE heater_charge_config SET stored_soc_topic = 'ha/soc' "
                "WHERE heater_id = 'entrada'"
            )
        )
        connection.execute(
            update(configuration_schema_version).values(revision=10)
        )

    upgrade_active_schemas(engines.configuration, engines.application)
    config, _revision = repository.current()
    topics = {heater.id: heater.telemetry_topic for heater in config.heaters}
    assert topics["salon"] == "ha/shared"
    assert topics["entrada"] is None
    assert "indoor_topic" not in {
        column["name"]
        for column in inspect(engines.configuration).get_columns("heater")
    }
    assert "stored_soc_topic" not in {
        column["name"]
        for column in inspect(engines.configuration).get_columns(
            "heater_charge_config"
        )
    }


def test_postgresql_namespace_names_are_fixed_not_user_controlled():
    assert POSTGRES_CONFIGURATION_SCHEMA == "dtc_config"
    assert POSTGRES_APPLICATION_SCHEMA == "dtc_app"


def test_application_failure_during_relay_claim_does_not_change_configuration(
    split_store, monkeypatch
):
    _paths, engines, repository = split_store
    before = repository.current()
    relay = SqlRelayTestRepository(
        engines.application,
        engines.application_location,
        clock=lambda: NOW,
        configuration_engine=engines.configuration,
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated application commit failure")

    monkeypatch.setattr(relay, "_event", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        relay.claim("owner-digest", NOW, 30)
    assert repository.current() == before
    with engines.application.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM relay_test_session")).scalar_one()
    assert count == 0
