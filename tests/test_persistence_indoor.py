"""Atomic last-reading repository shared by publisher and controller."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.models import IndoorReading


NOW = datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)


def test_upsert_replaces_only_the_same_heater(initialised_store):
    repository = initialised_store.indoor_readings
    repository.upsert(IndoorReading("salon", 19.5, NOW))
    repository.upsert(IndoorReading("entrada", 18.0, NOW))
    repository.upsert(IndoorReading("salon", 20.0, NOW + timedelta(minutes=1)))

    readings = repository.read_all()
    assert readings["salon"].celsius == 20.0
    assert readings["salon"].received_at == NOW + timedelta(minutes=1)
    assert readings["entrada"].celsius == 18.0


def test_invalidate_removes_the_previous_reading(initialised_store):
    repository = initialised_store.indoor_readings
    repository.upsert(IndoorReading("salon", 19.5, NOW))
    repository.invalidate("salon")
    assert "salon" not in repository.read_all()


def test_removing_a_heater_cascades_its_reading(initialised_store):
    repository = initialised_store.indoor_readings
    repository.upsert(IndoorReading("buhardilla", 17.0, NOW))
    _, revision = initialised_store.repository.current()
    initialised_store.repository.remove_heater(revision, "buhardilla")
    assert "buhardilla" not in repository.read_all()


def test_read_all_returns_one_coherent_snapshot(initialised_store):
    repository = initialised_store.indoor_readings
    for index, heater_id in enumerate(("salon", "entrada", "habitaciones")):
        repository.upsert(IndoorReading(heater_id, 18.0 + index, NOW))

    assert repository.read_all() == {
        "salon": IndoorReading("salon", 18.0, NOW),
        "entrada": IndoorReading("entrada", 19.0, NOW),
        "habitaciones": IndoorReading("habitaciones", 20.0, NOW),
    }
