from datetime import datetime
from zoneinfo import ZoneInfo

from dynamic_thermal_charge.config import load_config


def configured_schedule():
    config = load_config("examples/raspberry-pi.yaml")
    assert config.schedule is not None
    return config.schedule


def test_selects_next_midnight_when_window_has_not_started() -> None:
    schedule = configured_schedule()
    now = datetime(2026, 8, 20, 22, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert schedule.next_start(now) == datetime(
        2026, 8, 21, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")
    )


def test_selects_next_day_after_start_time() -> None:
    schedule = configured_schedule()
    now = datetime(2026, 8, 21, 1, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert schedule.next_start(now) == datetime(
        2026, 8, 22, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")
    )


def test_accepts_exact_scheduled_start() -> None:
    schedule = configured_schedule()
    now = datetime(2026, 8, 21, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert schedule.next_start(now) == now
