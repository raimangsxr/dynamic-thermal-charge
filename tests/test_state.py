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
