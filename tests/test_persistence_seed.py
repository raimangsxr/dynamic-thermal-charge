"""Initialisation and seeding: FR-011, FR-012, FR-013."""

from __future__ import annotations

import pytest

from dynamic_thermal_charge.config import validate_config
from dynamic_thermal_charge.persistence import SchemaStatus
from dynamic_thermal_charge.persistence.bootstrap import initialise, upgrade
from dynamic_thermal_charge.persistence.gate import EXPECTED_REVISION
from dynamic_thermal_charge.persistence.migrations import shipped_revisions
from dynamic_thermal_charge.persistence.seed import example_installation


def test_the_example_installation_is_complete_and_valid():
    config = example_installation()
    validate_config(config)
    assert len(config.heaters) == 4
    assert config.weather is not None
    assert config.schedule is not None
    # Every physically consequential value is declared, not defaulted.
    assert config.site.max_total_power_w == 5200
    assert {heater.output.pin for heater in config.heaters} == {17, 18, 22, 23}
    assert all(heater.output.active_high is False for heater in config.heaters)


def test_the_seed_holds_no_secret_only_the_variable_name():
    config = example_installation()
    assert config.weather.aemet is not None
    assert config.weather.aemet.api_key_env == "AEMET_API_KEY"


def test_initialising_an_empty_database_creates_and_seeds(store):
    assert store.gate.check() is SchemaStatus.MISSING
    report = initialise(store)
    assert report.schema_created is True
    assert report.seeded is True
    assert report.heaters == 4
    assert report.revision == EXPECTED_REVISION
    assert store.gate.check() is SchemaStatus.OK
    config, revision = store.repository.current()
    assert revision == 1
    assert [heater.id for heater in config.heaters] == [
        "salon",
        "entrada",
        "habitaciones",
        "buhardilla",
    ]


def test_initialising_twice_changes_nothing(initialised_store):
    before, revision_before = initialised_store.repository.current()
    report = initialise(initialised_store)
    assert report.schema_created is False
    assert report.migrated_from is None
    assert report.seeded is False
    after, revision_after = initialised_store.repository.current()
    assert after == before
    assert revision_after == revision_before


def test_seeding_never_overwrites_an_edited_configuration(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "installation", None, "max_total_power_kw", "3.0")
    report = initialise(initialised_store)
    assert report.seeded is False
    config, _ = repository.current()
    assert config.site.max_total_power_w == 3000, "the seed overwrote real configuration"


def test_upgrade_never_seeds(store):
    report = upgrade(store)
    assert report.seeded is False
    assert store.gate.check() is SchemaStatus.OK
    assert store.repository.is_empty()


def test_the_report_says_what_it_did(store):
    lines = " ".join(initialise(store).describe())
    assert "Schema created" in lines
    assert "Seeded" in lines
    lines = " ".join(initialise(store).describe())
    assert "already at revision" in lines
    assert "seeding skipped" in lines


def test_known_revisions_match_the_shipped_migration_files():
    """Keeps gate.KNOWN_REVISIONS from drifting from persistence/migrations/."""
    from dynamic_thermal_charge.persistence.gate import KNOWN_REVISIONS

    assert KNOWN_REVISIONS == shipped_revisions()
    assert EXPECTED_REVISION == KNOWN_REVISIONS[-1]
