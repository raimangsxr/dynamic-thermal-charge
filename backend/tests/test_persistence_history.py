"""The audit trail: FR-016, FR-017, FR-018, SC-004."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from dynamic_thermal_charge.models import SiteConfig
from dynamic_thermal_charge.persistence.mapping import from_utc
from dynamic_thermal_charge.persistence.schema import (
    forecast as forecast_table,
    output_transition,
    plan as plan_table,
    plan_allocation,
    plan_slot,
)
from dynamic_thermal_charge.scheduler import ChargeScheduler
from dynamic_thermal_charge.weather import OutdoorForecast


WINDOW_START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _forecast(source: str = "aemet", from_fallback: bool = False) -> OutdoorForecast:
    return OutdoorForecast(
        date=date(2026, 1, 16),
        average_temperature_c=6.5,
        minimum_temperature_c=2.0,
        maximum_temperature_c=11.0,
        source=source,
        location="A Coruña, A Coruña",
        from_fallback=from_fallback,
    )


def _plan(store, requested=None):
    config, _ = store.repository.current()
    return ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START, requested_charge_minutes=requested
    )


def _rows(store, table):
    with store.engine.connect() as connection:
        return connection.execute(select(table)).mappings().all()


# --------------------------------------------------------------------------- #
# FR-017: the recorded forecast says where it came from
# --------------------------------------------------------------------------- #

def test_a_forecast_is_recorded_with_its_temperatures_and_source(
    initialised_store, recorder
):
    reference = recorder.record_forecast(_forecast())
    assert reference is not None
    rows = _rows(initialised_store, forecast_table)
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "aemet"
    assert row["average_temperature_c"] == 6.5
    assert row["minimum_temperature_c"] == 2.0
    assert row["maximum_temperature_c"] == 11.0
    assert row["municipality"] == "A Coruña, A Coruña"
    assert row["forecast_date"] == date(2026, 1, 16)


def test_a_fallback_forecast_is_recorded_as_fallback(initialised_store, recorder):
    recorder.record_forecast(_forecast(source="simulated", from_fallback=True))
    assert _rows(initialised_store, forecast_table)[0]["source"] == "fallback"


def test_a_simulated_forecast_that_is_not_a_fallback_says_simulated(
    initialised_store, recorder
):
    recorder.record_forecast(_forecast(source="simulated"))
    assert _rows(initialised_store, forecast_table)[0]["source"] == "simulated"


# --------------------------------------------------------------------------- #
# FR-016: the recorded plan carries its window, slots and unmet minutes
# --------------------------------------------------------------------------- #

def test_a_plan_is_recorded_with_its_window_and_configuration_revision(
    initialised_store, recorder
):
    forecast_ref = recorder.record_forecast(_forecast())
    plan = _plan(initialised_store)
    reference = recorder.record_plan(plan, forecast_ref, installation_revision=1)
    assert reference is not None

    rows = _rows(initialised_store, plan_table)
    assert len(rows) == 1
    row = rows[0]
    assert row["installation_revision"] == 1
    assert row["forecast_id"] == forecast_ref.id
    assert row["slot_minutes"] == 30
    assert from_utc(row["window_start"]) == WINDOW_START
    assert from_utc(row["window_end"]) == WINDOW_START + timedelta(hours=8)


def test_the_recorded_slots_match_the_plan(initialised_store, recorder):
    plan = _plan(initialised_store)
    recorder.record_plan(plan, None, installation_revision=1)
    rows = _rows(initialised_store, plan_slot)
    expected = sum(len(slot.heater_ids) for slot in plan.slots)
    assert len(rows) == expected
    assert {row["heater_id"] for row in rows} <= {
        heater.id for heater in initialised_store.repository.current()[0].heaters
    }


def test_unmet_minutes_are_recorded_not_only_warned(initialised_store, recorder):
    """FR-016: the deficit used to live only in a WARNING log line."""
    config, _ = initialised_store.repository.current()
    # Ask for far more charge than the window and the power cap can deliver.
    requested = {heater.id: 480 for heater in config.heaters}
    plan = ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START, requested_charge_minutes=requested
    )
    assert plan.unmet_minutes, "the fixture no longer produces a deficit"
    recorder.record_plan(plan, None, installation_revision=1, requested_minutes=requested)

    rows = {row["heater_id"]: row for row in _rows(initialised_store, plan_allocation)}
    for heater_id, unmet in plan.unmet_minutes.items():
        assert rows[heater_id]["unmet_minutes"] == unmet
        assert rows[heater_id]["requested_minutes"] == requested[heater_id]
        assert rows[heater_id]["allocated_minutes"] == plan.allocated_minutes[heater_id]


def test_an_empty_plan_records_nothing(initialised_store, recorder):
    class _Empty:
        slots = ()
        allocated_minutes: dict = {}
        unmet_minutes: dict = {}

    assert recorder.record_plan(_Empty(), None, 1) is None
    assert _rows(initialised_store, plan_table) == []


# --------------------------------------------------------------------------- #
# FR-018: transitions only when the state actually changes
# --------------------------------------------------------------------------- #

def test_a_transition_records_heater_state_and_instant(initialised_store, recorder):
    at = datetime(2026, 1, 16, 1, 30, tzinfo=timezone.utc)
    recorder.record_transition("salon", True, at)
    rows = _rows(initialised_store, output_transition)
    assert len(rows) == 1
    assert rows[0]["heater_id"] == "salon"
    assert rows[0]["state"] is True
    assert from_utc(rows[0]["occurred_at"]) == at


def test_the_recorder_only_stores_what_it_is_told_to(initialised_store, recorder):
    """It records changes; deciding what is a change belongs to the controller."""
    at = datetime(2026, 1, 16, 1, 30, tzinfo=timezone.utc)
    recorder.record_transition("salon", True, at)
    recorder.record_transition("salon", False, at + timedelta(minutes=30))
    states = [row["state"] for row in _rows(initialised_store, output_transition)]
    assert states == [True, False]


def test_a_transition_can_be_tied_to_the_plan_that_caused_it(
    initialised_store, recorder
):
    plan_ref = recorder.record_plan(_plan(initialised_store), None, 1)
    recorder.record_transition("salon", True, WINDOW_START, plan_ref)
    assert _rows(initialised_store, output_transition)[0]["plan_id"] == plan_ref.id


# --------------------------------------------------------------------------- #
# SC-004: a night can be reconstructed from history alone
# --------------------------------------------------------------------------- #

def test_a_night_can_be_reconstructed_from_history_alone(initialised_store, recorder):
    config, revision = initialised_store.repository.current()
    requested = {heater.id: 480 for heater in config.heaters}
    plan = ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START, requested_charge_minutes=requested
    )
    forecast_ref = recorder.record_forecast(_forecast(source="simulated", from_fallback=True))
    plan_ref = recorder.record_plan(
        plan, forecast_ref, installation_revision=revision, requested_minutes=requested
    )
    for slot in plan.slots:
        for heater_id in slot.heater_ids:
            recorder.record_transition(heater_id, True, slot.start, plan_ref)
            recorder.record_transition(heater_id, False, slot.end, plan_ref)

    # Now answer, from the database only: why did each heater charge or not?
    with initialised_store.engine.connect() as connection:
        stored_plan = connection.execute(
            select(plan_table).where(plan_table.c.id == plan_ref.id)
        ).mappings().one()
        stored_forecast = connection.execute(
            select(forecast_table).where(
                forecast_table.c.id == stored_plan["forecast_id"]
            )
        ).mappings().one()
        allocations = connection.execute(
            select(plan_allocation).where(plan_allocation.c.plan_id == plan_ref.id)
        ).mappings().all()
        transitions = connection.execute(
            select(output_transition).where(
                output_transition.c.plan_id == plan_ref.id
            )
        ).mappings().all()

    # Which configuration produced it.
    assert stored_plan["installation_revision"] == revision
    # Which forecast, and whether the real provider worked.
    assert stored_forecast["source"] == "fallback"
    assert stored_forecast["average_temperature_c"] == 6.5
    # What each heater got, and what it did not get.
    assert {row["heater_id"] for row in allocations} == set(requested)
    assert any(row["unmet_minutes"] > 0 for row in allocations)
    # And what physically happened.
    assert transitions
    for row in allocations:
        switched_on = sum(
            1
            for transition in transitions
            if transition["heater_id"] == row["heater_id"] and transition["state"]
        )
        assert switched_on * stored_plan["slot_minutes"] == row["allocated_minutes"]


def test_history_outlives_the_heater_it_refers_to(initialised_store, recorder):
    """The heater_id columns are text, not foreign keys, precisely for this.

    ``salon`` is used because with the seeded 5.2 kW cap it is the heater that
    actually receives slots; a heater that received none would make the
    plan_slot half of this assertion vacuous.
    """
    plan = _plan(initialised_store)
    plan_ref = recorder.record_plan(plan, None, 1)
    recorder.record_transition("salon", True, WINDOW_START, plan_ref)
    assert any(
        "salon" in slot.heater_ids for slot in plan.slots
    ), "the fixture no longer allocates slots to salon"

    _, revision = initialised_store.repository.current()
    initialised_store.repository.remove_heater(revision, "salon")

    config, _ = initialised_store.repository.current()
    assert "salon" not in {heater.id for heater in config.heaters}
    for table in (plan_slot, plan_allocation, output_transition):
        assert any(
            row["heater_id"] == "salon" for row in _rows(initialised_store, table)
        ), f"{table.name} lost its history when the heater was removed"


# --------------------------------------------------------------------------- #
# Paged reads (FR-032 to FR-036). The previous phase only wrote and pruned.
# --------------------------------------------------------------------------- #

@pytest.fixture
def reader(initialised_store):
    from dynamic_thermal_charge.persistence.history import SqlHistoryReader

    return SqlHistoryReader(
        initialised_store.engine,
        initialised_store.repository.installation_id(),
        initialised_store.location,
    )


def _seed_nights(store, nights: int, end: datetime, heaters=("salon", "entrada")):
    from tests.test_persistence_retention import _seed_history

    _seed_history(store, nights=nights, end=end, heaters=heaters)


SEED_END = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def test_the_default_page_is_bounded(initialised_store, reader):
    _seed_nights(initialised_store, nights=120, end=SEED_END)
    page = reader.plans()
    assert page.limit_applied == 50
    assert len(page.items) == 50
    assert page.has_more is True
    assert page.next_cursor is not None


def test_a_request_never_returns_the_whole_history(initialised_store, reader):
    _seed_nights(initialised_store, nights=200, end=SEED_END)
    assert len(reader.plans().items) < 200
    assert len(reader.transitions().items) < 200


def test_an_oversized_limit_is_capped(initialised_store, reader):
    _seed_nights(initialised_store, nights=10, end=SEED_END)
    page = reader.plans(limit=99999)
    assert page.limit_applied == 500


def test_results_come_newest_first(initialised_store, reader):
    _seed_nights(initialised_store, nights=5, end=SEED_END)
    instants = [item["created_at"] for item in reader.plans().items]
    assert instants == sorted(instants, reverse=True)


def test_the_cursor_walks_the_whole_history_without_repeats_or_gaps(
    initialised_store, reader
):
    _seed_nights(initialised_store, nights=37, end=SEED_END)
    seen: list[int] = []
    cursor = None
    for _ in range(20):  # generous bound; the walk must finish well before this
        page = reader.plans(limit=10, cursor=cursor)
        seen.extend(item["id"] for item in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
    assert len(seen) == 37
    assert len(set(seen)) == 37, "the cursor returned a repeated item"


def test_an_insert_between_pages_does_not_shift_the_walk(initialised_store, reader):
    """The reason the cursor is a (instant, id) pair and not an offset."""
    _seed_nights(initialised_store, nights=20, end=SEED_END)
    first = reader.plans(limit=10)
    # A brand-new plan arrives, as the controller would produce one.
    _seed_nights(initialised_store, nights=1, end=SEED_END + timedelta(days=1))
    second = reader.plans(limit=10, cursor=first.next_cursor)
    assert not (
        {item["id"] for item in first.items} & {item["id"] for item in second.items}
    ), "an insert between pages produced a repeated item"


def test_a_tampered_cursor_is_rejected_not_ignored(reader):
    from dynamic_thermal_charge.persistence.history import CursorError

    with pytest.raises(CursorError):
        reader.plans(cursor="not-a-cursor")


def test_a_range_selects_only_what_it_covers(initialised_store, reader):
    _seed_nights(initialised_store, nights=30, end=SEED_END)
    since = SEED_END - timedelta(days=5)
    page = reader.plans(since=since)
    assert page.items
    assert all(item["created_at"] >= since for item in page.items)


def test_an_empty_range_returns_an_empty_page(initialised_store, reader):
    _seed_nights(initialised_store, nights=5, end=SEED_END)
    page = reader.plans(
        since=SEED_END + timedelta(days=100), until=SEED_END + timedelta(days=200)
    )
    assert page.items == []
    assert page.has_more is False
    assert page.next_cursor is None


def test_transitions_can_be_filtered_by_heater(initialised_store, reader):
    _seed_nights(initialised_store, nights=5, end=SEED_END)
    page = reader.transitions(heater_id="salon")
    assert page.items
    assert {item["heater_id"] for item in page.items} == {"salon"}


def test_a_removed_heater_keeps_its_transitions(initialised_store, reader):
    _seed_nights(initialised_store, nights=3, end=SEED_END)
    _, revision = initialised_store.repository.current()
    initialised_store.repository.remove_heater(revision, "salon")
    page = reader.transitions(heater_id="salon")
    assert page.items, "the history of a removed heater disappeared"


def test_an_unknown_heater_returns_an_empty_page(initialised_store, reader):
    """It may have existed and been removed: absence is not an error."""
    _seed_nights(initialised_store, nights=3, end=SEED_END)
    assert reader.transitions(heater_id="never-existed").items == []


def test_instants_come_back_as_aware_utc(initialised_store, reader):
    _seed_nights(initialised_store, nights=2, end=SEED_END)
    for item in reader.plans().items:
        assert item["created_at"].tzinfo is not None
        assert item["created_at"].utcoffset() == timedelta(0)
