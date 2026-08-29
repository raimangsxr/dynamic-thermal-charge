from datetime import datetime
from zoneinfo import ZoneInfo

from dynamic_thermal_charge.persistence.seed import example_installation


def configured_schedule():
    """The schedule of the seeded installation, previously read from YAML."""
    config = example_installation()
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


def test_returns_active_window_after_it_has_started() -> None:
    schedule = configured_schedule()
    now = datetime(2026, 8, 21, 3, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert schedule.active_or_next_start(now) == datetime(
        2026, 8, 21, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")
    )
