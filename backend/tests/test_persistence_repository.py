"""Reading and editing configuration: FR-001, FR-007, FR-032 to FR-040."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from dynamic_thermal_charge.models import Heater, OutputConfig, ThermalProfile
from dynamic_thermal_charge.persistence import (
    ConfigConflictError,
    ConfigValidationError,
    SecretRejectedError,
)
from dynamic_thermal_charge.persistence.schema import config_change, heater as heater_table
from dynamic_thermal_charge.scheduler import ChargeScheduler


WINDOW_START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _new_heater(heater_id: str = "cocina", pin: int | None = 24) -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id.capitalize(),
        power_w=1200,
        full_charge_minutes=420,
        target_charge=1.0,
        priority=10,
        thermal=ThermalProfile(
            target_temperature_c=20.0, design_outdoor_temperature_c=-2.0
        ),
        output=OutputConfig(
            kind="gpio" if pin is not None else "simulated",
            pin=pin,
            active_high=False,
        ),
    )


# --------------------------------------------------------------------------- #
# Reading (FR-001, FR-007)
# --------------------------------------------------------------------------- #

def test_the_configuration_read_back_matches_what_was_seeded(initialised_store):
    from dynamic_thermal_charge.persistence.seed import example_installation

    config, revision = initialised_store.repository.current()
    assert revision == 1
    assert config == example_installation()


def test_the_plan_from_the_database_matches_the_plan_from_the_same_values(
    initialised_store,
):
    """SC-002, local half: same installation, same plan."""
    from dynamic_thermal_charge.persistence.seed import example_installation

    stored, _ = initialised_store.repository.current()
    reference = example_installation()
    scheduler = ChargeScheduler()
    from_database = scheduler.build(stored.site, stored.heaters, WINDOW_START)
    from_values = scheduler.build(reference.site, reference.heaters, WINDOW_START)
    assert from_database == from_values


# --------------------------------------------------------------------------- #
# Editing installation and heater fields (FR-032, FR-036)
# --------------------------------------------------------------------------- #

def test_an_installation_field_changes_and_reports_both_values(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    change = repository.set_field(
        revision, "installation", None, "max_total_power_kw", "6.0"
    )
    assert change.old_value == "5200"
    assert change.new_value == "6000", "the audit trail mixed kW and W"
    assert change.revision_after == revision + 1
    config, new_revision = repository.current()
    assert config.site.max_total_power_w == 6000
    assert new_revision == revision + 1


def test_a_heater_field_changes_only_that_heater(initialised_store):
    repository = initialised_store.repository
    before, revision = repository.current()
    repository.set_field(revision, "heater", "entrada", "target_charge", "0.5")
    after, _ = repository.current()
    changed = {heater.id: heater for heater in after.heaters}
    for heater in before.heaters:
        if heater.id == "entrada":
            assert changed[heater.id].target_charge == 0.5
        else:
            assert changed[heater.id] == heater, "an unrelated heater changed"


def test_a_thermal_field_changes_only_that_profile(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "heater", "salon", "target_temperature_c", "22.5")
    config, _ = repository.current()
    profiles = {heater.id: heater.thermal for heater in config.heaters}
    assert profiles["salon"].target_temperature_c == 22.5
    assert profiles["entrada"].target_temperature_c == 18.0


def test_disabling_a_heater_keeps_it_in_the_configuration(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "heater", "buhardilla", "enabled", "false")
    config, _ = repository.current()
    disabled = next(h for h in config.heaters if h.id == "buhardilla")
    assert disabled.enabled is False
    assert len(config.heaters) == 4


def test_retention_can_be_set_to_unlimited(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "installation", None, "retention_days", "none")
    config, _ = repository.current()
    assert config.retention_days is None


def test_every_edit_is_recorded_with_its_revisions(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "installation", None, "poll_seconds", "9")
    with initialised_store.engine.connect() as connection:
        row = connection.execute(select(config_change)).mappings().one()
    assert row["entity"] == "installation"
    assert row["field"] == "poll_seconds"
    assert row["action"] == "set"
    assert row["revision_before"] == revision
    assert row["revision_after"] == revision + 1
    assert row["occurred_at"] is not None


# --------------------------------------------------------------------------- #
# Adding and removing heaters (FR-033)
# --------------------------------------------------------------------------- #

def test_a_heater_can_be_added(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    change = repository.add_heater(revision, _new_heater())
    assert change.action == "add"
    config, new_revision = repository.current()
    assert new_revision == revision + 1
    added = next(h for h in config.heaters if h.id == "cocina")
    assert added.output.pin == 24
    assert added.thermal is not None


def test_removing_a_heater_takes_its_output_and_profile(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.remove_heater(revision, "buhardilla")
    config, _ = repository.current()
    assert "buhardilla" not in {h.id for h in config.heaters}
    with initialised_store.engine.connect() as connection:
        from dynamic_thermal_charge.persistence.schema import (
            output_config,
            thermal_profile,
        )

        assert connection.execute(
            select(func.count()).select_from(output_config)
        ).scalar() == 3
        assert connection.execute(
            select(func.count()).select_from(thermal_profile)
        ).scalar() == 3


def test_removing_the_last_heater_leaves_a_valid_empty_installation(initialised_store):
    repository = initialised_store.repository
    for heater_id in ("salon", "entrada", "habitaciones", "buhardilla"):
        _, revision = repository.current()
        repository.remove_heater(revision, heater_id)
    config, _ = repository.current()
    assert config.heaters == ()
    # A plan over no heaters is empty, and every output is therefore off.
    plan = ChargeScheduler().build(config.site, config.heaters, WINDOW_START)
    assert all(slot.heater_ids == () for slot in plan.slots)
    assert plan.unmet_minutes == {}


# --------------------------------------------------------------------------- #
# Rejections. In every one of these the store must be left exactly as it was.
# --------------------------------------------------------------------------- #

def _snapshot(store):
    config, revision = store.repository.current()
    with store.engine.connect() as connection:
        changes = connection.execute(select(func.count()).select_from(config_change)).scalar()
    return config, revision, changes


@pytest.mark.parametrize(
    ("entity", "key", "field", "value", "expected"),
    [
        ("installation", None, "slot_minutes", "45", ConfigValidationError),
        ("installation", None, "slot_minutes", "7", ConfigValidationError),
        ("installation", None, "start_time", "00:17", ConfigValidationError),
        ("installation", None, "max_total_power_kw", "0", ConfigValidationError),
        ("installation", None, "poll_seconds", "0", ConfigValidationError),
        ("installation", None, "log_level", "CHATTY", ConfigValidationError),
        ("installation", None, "weekdays", "1,0", ConfigValidationError),
        ("installation", None, "retention_days", "0", ConfigValidationError),
        ("heater", "entrada", "pin", "17", ConfigValidationError),
        ("heater", "entrada", "target_charge", "1.5", ConfigValidationError),
        ("heater", "entrada", "power_kw", "-1", ConfigValidationError),
        ("heater", "salon", "max_charge", "1.5", ConfigValidationError),
        ("heater", "salon", "design_outdoor_temperature_c", "30", ConfigValidationError),
        ("installation", None, "nonexistent_field", "1", ConfigValidationError),
        ("heater", "cocina", "priority", "1", ConfigValidationError),
        ("heater", "salon", "nonexistent_field", "1", ConfigValidationError),
    ],
)
def test_a_rejected_edit_changes_nothing(initialised_store, entity, key, field, value, expected):
    before = _snapshot(initialised_store)
    _, revision = initialised_store.repository.current()
    with pytest.raises(expected):
        initialised_store.repository.set_field(revision, entity, key, field, value)
    assert _snapshot(initialised_store) == before, "a rejected edit left a trace"


def test_a_duplicate_pin_names_both_heaters(initialised_store):
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError) as error:
        initialised_store.repository.set_field(revision, "heater", "entrada", "pin", "17")
    message = str(error.value)
    assert "17" in message and "salon" in message and "entrada" in message


def test_an_unknown_field_lists_the_admissible_ones(initialised_store):
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError) as error:
        initialised_store.repository.set_field(
            revision, "installation", None, "maximum_power", "6"
        )
    message = str(error.value)
    assert "maximum_power" in message
    assert "max_total_power_kw" in message and "slot_minutes" in message


def test_an_unknown_heater_lists_the_existing_ones(initialised_store):
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError) as error:
        initialised_store.repository.set_field(revision, "heater", "cocina", "priority", "1")
    message = str(error.value)
    assert "cocina" in message
    assert "salon" in message and "buhardilla" in message


def test_adding_a_duplicate_heater_id_is_refused(initialised_store):
    before = _snapshot(initialised_store)
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError, match="already exists"):
        initialised_store.repository.add_heater(revision, _new_heater("salon", pin=25))
    assert _snapshot(initialised_store) == before


def test_adding_a_heater_on_a_used_pin_is_refused(initialised_store):
    before = _snapshot(initialised_store)
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError):
        initialised_store.repository.add_heater(revision, _new_heater("cocina", pin=17))
    assert _snapshot(initialised_store) == before


def test_removing_a_heater_that_does_not_exist_is_refused(initialised_store):
    before = _snapshot(initialised_store)
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError) as error:
        initialised_store.repository.remove_heater(revision, "cocina")
    assert "salon" in str(error.value)
    assert _snapshot(initialised_store) == before


# --------------------------------------------------------------------------- #
# FR-038: a value that looks like a secret is refused
# --------------------------------------------------------------------------- #

def test_state_file_is_no_longer_an_editable_configuration_field(initialised_store):
    before = _snapshot(initialised_store)
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError) as error:
        initialised_store.repository.set_field(
            revision, "installation", None, "state_file", "/var/lib/dtc/plan.json"
        )
    assert "unknown installation field" in str(error.value)
    assert _snapshot(initialised_store) == before


def test_an_ordinary_path_is_not_mistaken_for_a_secret(initialised_store):
    _, revision = initialised_store.repository.current()
    with pytest.raises(ConfigValidationError):
        initialised_store.repository.set_field(
            revision, "installation", None, "state_file", "/var/lib/dtc/active-plan.json"
        )


# --------------------------------------------------------------------------- #
# FR-035: atomicity
# --------------------------------------------------------------------------- #

def test_an_interrupted_edit_leaves_the_previous_configuration_intact(
    initialised_store, monkeypatch
):
    """The transaction must roll back, not half-apply."""
    repository = initialised_store.repository
    before = _snapshot(initialised_store)
    _, revision = repository.current()

    original = repository._commit_revision

    def _die_midway(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("operator pressed Ctrl+C mid-transaction")

    monkeypatch.setattr(repository, "_commit_revision", _die_midway)
    with pytest.raises(KeyboardInterrupt):
        repository.set_field(revision, "installation", None, "max_total_power_kw", "9.9")

    assert _snapshot(initialised_store) == before, "an interrupted edit half-applied"


# --------------------------------------------------------------------------- #
# FR-040: concurrent edits
# --------------------------------------------------------------------------- #

def test_a_stale_revision_is_refused(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    repository.set_field(revision, "installation", None, "poll_seconds", "6")
    # Second editor still holds the old revision.
    with pytest.raises(ConfigConflictError) as error:
        repository.set_field(revision, "installation", None, "poll_seconds", "7")
    assert "revision" in str(error.value)
    config, _ = repository.current()
    assert config.runtime.poll_seconds == 6.0, "the first edit was silently lost"


def test_two_editors_on_the_same_revision_do_not_both_win(initialised_store):
    repository = initialised_store.repository
    _, revision = repository.current()
    results: list[object] = []

    def edit(value: str) -> None:
        try:
            results.append(
                repository.set_field(
                    revision, "installation", None, "poll_seconds", value
                )
            )
        except Exception as exc:  # noqa: BLE001 - the test inspects the type
            results.append(exc)

    first = threading.Thread(target=edit, args=("11",))
    second = threading.Thread(target=edit, args=("12",))
    first.start()
    first.join()
    second.start()
    second.join()

    conflicts = [item for item in results if isinstance(item, ConfigConflictError)]
    successes = [item for item in results if not isinstance(item, Exception)]
    assert len(successes) == 1, "both edits committed on the same revision"
    assert len(conflicts) == 1, "the losing edit was not told it lost"
    _, final_revision = repository.current()
    assert final_revision == revision + 1


# --------------------------------------------------------------------------- #
# FR-039: an edit does not disturb the running plan
# --------------------------------------------------------------------------- #

def test_an_edit_does_not_alter_an_already_built_plan(initialised_store):
    repository = initialised_store.repository
    config, revision = repository.current()
    running_plan = ChargeScheduler().build(config.site, config.heaters, WINDOW_START)

    repository.set_field(revision, "installation", None, "max_total_power_kw", "2.4")

    # The plan object in flight is untouched...
    assert running_plan == ChargeScheduler().build(
        config.site, config.heaters, WINDOW_START
    )
    # ...and the change only shows up on the next recalculation.
    updated, _ = repository.current()
    recalculated = ChargeScheduler().build(
        updated.site, updated.heaters, WINDOW_START
    )
    assert recalculated != running_plan
    assert max(slot.total_power_w for slot in recalculated.slots) <= 2400
