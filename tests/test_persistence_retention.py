"""Retention: FR-021, FR-022, FR-023, SC-005."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, insert, select

from dynamic_thermal_charge.persistence.mapping import to_utc
from dynamic_thermal_charge.persistence.schema import (
    config_change,
    forecast as forecast_table,
    output_transition,
    plan as plan_table,
    plan_allocation,
    plan_slot,
)


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _seed_history(store, nights: int, end: datetime = NOW, heaters=("salon", "entrada")):
    """Insert `nights` nights of history, the most recent ending at `end`."""
    installation_id = store.repository.installation_id()
    with store.engine.begin() as connection:
        for night in range(nights):
            window_start = end - timedelta(days=night + 1)
            window_end = window_start + timedelta(hours=8)
            forecast_id = connection.execute(
                insert(forecast_table).values(
                    installation_id=installation_id,
                    forecast_date=window_start.date(),
                    average_temperature_c=7.0,
                    minimum_temperature_c=2.0,
                    maximum_temperature_c=12.0,
                    source="aemet",
                    retrieved_at=to_utc(window_start),
                )
            ).inserted_primary_key[0]
            plan_id = connection.execute(
                insert(plan_table).values(
                    installation_id=installation_id,
                    installation_revision=1,
                    forecast_id=forecast_id,
                    window_start=to_utc(window_start),
                    window_end=to_utc(window_end),
                    slot_minutes=30,
                    created_at=to_utc(window_start),
                )
            ).inserted_primary_key[0]
            for index in range(16):
                slot_start = window_start + timedelta(minutes=30 * index)
                for heater_id in heaters:
                    connection.execute(
                        insert(plan_slot).values(
                            plan_id=plan_id,
                            heater_id=heater_id,
                            slot_start=to_utc(slot_start),
                            slot_end=to_utc(slot_start + timedelta(minutes=30)),
                        )
                    )
            for heater_id in heaters:
                connection.execute(
                    insert(plan_allocation).values(
                        plan_id=plan_id,
                        heater_id=heater_id,
                        requested_minutes=480,
                        allocated_minutes=480,
                        unmet_minutes=0,
                    )
                )
                connection.execute(
                    insert(output_transition).values(
                        installation_id=installation_id,
                        heater_id=heater_id,
                        state=True,
                        occurred_at=to_utc(window_start),
                        plan_id=plan_id,
                    )
                )
                connection.execute(
                    insert(output_transition).values(
                        installation_id=installation_id,
                        heater_id=heater_id,
                        state=False,
                        occurred_at=to_utc(window_end),
                        plan_id=plan_id,
                    )
                )


def _count(store, table) -> int:
    with store.engine.connect() as connection:
        return int(
            connection.execute(select(func.count()).select_from(table)).scalar() or 0
        )


# --------------------------------------------------------------------------- #
# FR-022: old history goes, recent history stays
# --------------------------------------------------------------------------- #

def test_rows_older_than_the_limit_are_deleted_and_recent_ones_survive(
    initialised_store, recorder
):
    _seed_history(initialised_store, nights=40)
    assert _count(initialised_store, plan_table) == 40

    report = recorder.prune(NOW, retention_days=10)

    assert report.total > 0
    surviving = _count(initialised_store, plan_table)
    assert surviving == 10, "the cutoff did not fall where the retention says"
    assert report.deleted["plan"] == 30


def test_the_report_says_how_many_rows_went(initialised_store, recorder):
    _seed_history(initialised_store, nights=5)
    report = recorder.prune(NOW, retention_days=2)
    assert set(report.deleted) <= {"plan", "forecast", "output_transition"}
    assert report.total == sum(report.deleted.values())


def test_cascades_take_the_slots_and_allocations_with_the_plan(
    initialised_store, recorder
):
    _seed_history(initialised_store, nights=5)
    assert _count(initialised_store, plan_slot) > 0
    recorder.prune(NOW, retention_days=2)
    with initialised_store.engine.connect() as connection:
        orphan_slots = connection.execute(
            select(func.count())
            .select_from(plan_slot)
            .where(~plan_slot.c.plan_id.in_(select(plan_table.c.id)))
        ).scalar()
        orphan_allocations = connection.execute(
            select(func.count())
            .select_from(plan_allocation)
            .where(~plan_allocation.c.plan_id.in_(select(plan_table.c.id)))
        ).scalar()
    assert orphan_slots == 0
    assert orphan_allocations == 0


# --------------------------------------------------------------------------- #
# FR-023: configuration and the live plan are never touched
# --------------------------------------------------------------------------- #

def test_the_configuration_survives_any_retention(initialised_store, recorder):
    before, revision_before = initialised_store.repository.current()
    _seed_history(initialised_store, nights=30)
    recorder.prune(NOW, retention_days=1)
    after, revision_after = initialised_store.repository.current()
    assert after == before
    assert revision_after == revision_before


def test_a_live_plan_survives_however_old_it_looks(initialised_store, recorder):
    """window_end in the future means live, whatever created_at says."""
    installation_id = initialised_store.repository.installation_id()
    with initialised_store.engine.begin() as connection:
        connection.execute(
            insert(plan_table).values(
                installation_id=installation_id,
                installation_revision=1,
                # Created long ago, but still running.
                window_start=to_utc(NOW - timedelta(days=400)),
                window_end=to_utc(NOW + timedelta(hours=4)),
                slot_minutes=30,
                created_at=to_utc(NOW - timedelta(days=400)),
            )
        )
    report = recorder.prune(NOW, retention_days=1)
    assert _count(initialised_store, plan_table) == 1, "the running plan was pruned"
    assert "plan" not in report.deleted


def test_a_future_plan_survives_too(initialised_store, recorder):
    """A window already calculated for tomorrow must not disappear either."""
    installation_id = initialised_store.repository.installation_id()
    with initialised_store.engine.begin() as connection:
        connection.execute(
            insert(plan_table).values(
                installation_id=installation_id,
                installation_revision=1,
                window_start=to_utc(NOW + timedelta(hours=10)),
                window_end=to_utc(NOW + timedelta(hours=18)),
                slot_minutes=30,
                created_at=to_utc(NOW - timedelta(days=500)),
            )
        )
    recorder.prune(NOW, retention_days=1)
    assert _count(initialised_store, plan_table) == 1


def test_config_change_is_excluded_from_retention(initialised_store, recorder):
    """The only trace of who changed the configuration. Tens of rows a year."""
    _, revision = initialised_store.repository.current()
    initialised_store.repository.set_field(
        revision, "installation", None, "poll_seconds", "7"
    )
    assert _count(initialised_store, config_change) == 1
    # Backdate it far beyond any retention.
    with initialised_store.engine.begin() as connection:
        connection.execute(
            config_change.update().values(
                occurred_at=to_utc(NOW - timedelta(days=5000))
            )
        )
    recorder.prune(NOW, retention_days=1)
    assert _count(initialised_store, config_change) == 1, (
        "the configuration audit trail was pruned"
    )


# --------------------------------------------------------------------------- #
# FR-021: unlimited means nothing is deleted
# --------------------------------------------------------------------------- #

def test_unlimited_retention_deletes_nothing(initialised_store, recorder):
    _seed_history(initialised_store, nights=50)
    before = _count(initialised_store, plan_table)
    report = recorder.prune(NOW, retention_days=None)
    assert report.total == 0
    assert report.deleted == {}
    assert _count(initialised_store, plan_table) == before


def test_a_drastic_reduction_deletes_a_lot_at_once(initialised_store, recorder):
    _seed_history(initialised_store, nights=200)
    report = recorder.prune(NOW, retention_days=1)
    assert report.deleted["plan"] == 199
    assert _count(initialised_store, plan_table) == 1
    # Planning must still work straight afterwards.
    config, _ = initialised_store.repository.current()
    assert config.heaters


# --------------------------------------------------------------------------- #
# SC-005: a year of history stays within a known, bounded size
# --------------------------------------------------------------------------- #

HISTORY_SIZE_LIMIT_MB = 10


def test_a_year_of_history_stays_within_a_known_bound(initialised_store, recorder, tmp_path):
    """research.md D10 estimates ~27 000 rows a year for four heaters."""
    _seed_history(
        initialised_store,
        nights=365,
        heaters=("salon", "entrada", "habitaciones", "buhardilla"),
    )
    counts = recorder.row_counts()
    total_rows = sum(counts.values())
    # The estimate was ~27 000; hold it to the right order of magnitude.
    assert 20_000 <= total_rows <= 40_000, f"row estimate is off: {counts}"

    database = tmp_path / "dtc.db"
    size_mb = sum(
        path.stat().st_size
        for path in tmp_path.glob("dtc.db*")
    ) / (1024 * 1024)
    assert size_mb < HISTORY_SIZE_LIMIT_MB, (
        f"a year of history takes {size_mb:.1f} MB, above the "
        f"{HISTORY_SIZE_LIMIT_MB} MB budget for the deployment SD card"
    )
    # And the default retention keeps it there.
    report = recorder.prune(NOW + timedelta(days=1), retention_days=365)
    assert report.total > 0, "the default retention never trims anything"
