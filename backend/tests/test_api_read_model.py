from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dynamic_thermal_charge.api.read_model import automatic_window, wall_clock_end


def test_wall_clock_window_respects_both_europe_madrid_dst_transitions():
    zone = ZoneInfo("Europe/Madrid")
    spring = datetime(2026, 3, 29, 0, 30, tzinfo=zone)
    autumn = datetime(2026, 10, 25, 0, 30, tzinfo=zone)

    spring_end = wall_clock_end(spring, 4)
    autumn_end = wall_clock_end(autumn, 4)

    assert spring_end.astimezone(zone).replace(tzinfo=None) == datetime(2026, 3, 29, 4, 30)
    assert autumn_end.astimezone(zone).replace(tzinfo=None) == datetime(2026, 10, 25, 4, 30)


def test_automatic_window_uses_the_stored_horizon_as_a_hard_limit():
    start = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 16, 8, 0, tzinfo=timezone.utc)

    window_start, window_end = automatic_window(
        {"horizon_start": start, "horizon_end": end},
        planning_window_hours=12,
        timezone_name="Europe/Madrid",
    )

    assert window_start == start
    assert window_end == end
