from datetime import datetime, timedelta

from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from dynamic_thermal_charge.state import PlanStore


def sample_plan() -> ScheduleResult:
    start = datetime.fromisoformat("2026-01-01T00:00:00+01:00")
    return ScheduleResult(
        slots=(
            ScheduleSlot(
                start=start,
                end=start + timedelta(minutes=30),
                heater_ids=("salon",),
                total_power_w=2800,
            ),
        ),
        allocated_minutes={"salon": 30},
        unmet_minutes={},
    )


def test_round_trips_plan_atomically(tmp_path) -> None:
    store = PlanStore(tmp_path / "state" / "plan.json")

    store.save(sample_plan())

    assert store.load() == sample_plan()
    assert not list((tmp_path / "state").glob("*.tmp"))


def test_ignores_corrupt_persisted_plan(tmp_path, caplog) -> None:
    path = tmp_path / "plan.json"
    path.write_text("not-json", encoding="utf-8")

    result = PlanStore(path).load()

    assert result is None
    assert "Ignoring invalid persisted charge plan" in caplog.text


# --------------------------------------------------------------------------- #
# T058 (FR-020): durability of the active plan, now that configuration lives in
# a database. The local copy is the resume cache (research.md D7), so it is what
# lets the service pick up its plan after a reboot when a remote database is
# unreachable. That makes it worth a regression test, not an assumption.
# --------------------------------------------------------------------------- #

import json as _json
import os as _os
import threading as _threading
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone

import pytest as _pytest

from dynamic_thermal_charge.scheduler import (
    ScheduleResult as _ScheduleResult,
    ScheduleSlot as _ScheduleSlot,
)
from dynamic_thermal_charge.state import PlanStore as _PlanStore


_START = _datetime(2026, 1, 16, 0, 0, tzinfo=_timezone.utc)


def _durable_plan(heater_ids=("salon",), slots: int = 4) -> _ScheduleResult:
    return _ScheduleResult(
        slots=tuple(
            _ScheduleSlot(
                start=_START + _timedelta(minutes=30 * index),
                end=_START + _timedelta(minutes=30 * (index + 1)),
                heater_ids=heater_ids,
                total_power_w=2800,
            )
            for index in range(slots)
        ),
        allocated_minutes={heater_id: slots * 30 for heater_id in heater_ids},
        unmet_minutes={},
    )


def test_the_plan_survives_a_simulated_restart(tmp_path):
    path = tmp_path / "active-plan.json"
    plan = _durable_plan()
    _PlanStore(path).save(plan)
    # A brand new store object, as after a process restart.
    assert _PlanStore(path).load() == plan


def test_writing_leaves_no_temporary_file_behind(tmp_path):
    path = tmp_path / "active-plan.json"
    _PlanStore(path).save(_durable_plan())
    leftovers = [entry.name for entry in tmp_path.iterdir() if entry.name != path.name]
    assert leftovers == [], f"the atomic write left files behind: {leftovers}"


def test_the_write_is_atomic_so_a_reader_never_sees_half_a_plan(tmp_path):
    path = tmp_path / "active-plan.json"
    store = _PlanStore(path)
    store.save(_durable_plan(slots=4))
    small = path.read_text(encoding="utf-8")
    store.save(_durable_plan(heater_ids=("salon", "entrada"), slots=16))
    big = path.read_text(encoding="utf-8")
    # Whichever version a reader gets, it is a complete document.
    for content in (small, big):
        payload = _json.loads(content)
        assert payload["version"] == 1
        assert payload["slots"]


@_pytest.mark.parametrize(
    "content",
    [
        "",
        "{",
        "null",
        '{"version": 99, "slots": []}',
        '{"version": 1}',
        '{"version": 1, "slots": [{"start": "not-a-date"}]}',
    ],
)
def test_an_unreadable_or_unknown_plan_is_treated_as_no_plan(tmp_path, content):
    """FR-020: never guess at a plan the service cannot fully understand."""
    path = tmp_path / "active-plan.json"
    path.write_text(content, encoding="utf-8")
    assert _PlanStore(path).load() is None


def test_a_missing_file_is_treated_as_no_plan(tmp_path):
    assert _PlanStore(tmp_path / "never-written.json").load() is None


def test_the_directory_is_created_on_demand(tmp_path):
    path = tmp_path / "nested" / "deep" / "active-plan.json"
    _PlanStore(path).save(_durable_plan())
    assert path.is_file()


# --------------------------------------------------------------------------- #
# T066: two concurrent writers of the local copy.
#
# The guarantee is atomicity of the *read*, not serialisation of the writers:
# os.replace is atomic, so no reader ever sees a truncated or interleaved plan,
# and the last write wins. Both writers derive from the same live plan, so losing
# one is harmless; a mangled file would not be.
# --------------------------------------------------------------------------- #

def test_concurrent_writers_never_produce_a_truncated_or_mixed_plan(tmp_path):
    path = tmp_path / "active-plan.json"
    store = _PlanStore(path)
    small = _durable_plan(heater_ids=("salon",), slots=4)
    big = _durable_plan(heater_ids=("salon", "entrada", "habitaciones"), slots=16)
    store.save(small)

    stop = _threading.Event()
    observations: list[object] = []
    failures: list[BaseException] = []

    def writer(plan, count: int) -> None:
        try:
            for _ in range(count):
                store.save(plan)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            failures.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                observations.append(_PlanStore(path).load())
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [
        _threading.Thread(target=writer, args=(small, 40)),
        _threading.Thread(target=writer, args=(big, 40)),
        _threading.Thread(target=reader),
    ]
    for thread in threads[:2]:
        thread.start()
    threads[2].start()
    for thread in threads[:2]:
        thread.join()
    stop.set()
    threads[2].join()

    assert not failures, f"a concurrent access raised: {failures}"
    # Every observation is one of the two complete plans. Never a hybrid, never
    # a truncated document, and never None from a half-written file.
    assert observations, "the reader never managed to read"
    assert all(
        observed in (small, big) for observed in observations
    ), "a reader observed a plan that was never written whole"
    # The last write wins, and the file is still a complete, loadable plan.
    assert _PlanStore(path).load() in (small, big)
