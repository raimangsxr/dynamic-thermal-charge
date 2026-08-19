from datetime import datetime

from dynamic_thermal_charge.models import Heater, OutputConfig, SiteConfig
from dynamic_thermal_charge.scheduler import ChargeScheduler


def heater(identifier: str, power_w: int, priority: int, target: float = 1) -> Heater:
    return Heater(
        id=identifier,
        name=identifier,
        power_w=power_w,
        full_charge_minutes=60,
        target_charge=target,
        priority=priority,
        output=OutputConfig(),
    )


def test_never_exceeds_site_power_limit() -> None:
    site = SiteConfig(max_total_power_w=5000, slot_minutes=30, window_minutes=60)
    heaters = (
        heater("large", 2800, 100),
        heater("medium-a", 2400, 80),
        heater("medium-b", 2400, 60),
    )

    result = ChargeScheduler().build(site, heaters, datetime(2026, 1, 1))

    assert all(slot.total_power_w <= 5000 for slot in result.slots)
    assert all(len(slot.heater_ids) == 1 for slot in result.slots)


def test_reports_demand_that_does_not_fit() -> None:
    site = SiteConfig(max_total_power_w=3000, slot_minutes=30, window_minutes=60)
    heaters = (
        heater("important", 2400, 100),
        heater("secondary", 2400, 10),
    )

    result = ChargeScheduler().build(site, heaters, datetime(2026, 1, 1))

    assert result.allocated_minutes["important"] == 60
    assert result.allocated_minutes["secondary"] == 0
    assert result.unmet_minutes == {"secondary": 60}


def test_combines_heaters_when_power_allows_it() -> None:
    site = SiteConfig(max_total_power_w=5300, slot_minutes=30, window_minutes=30)
    heaters = (heater("a", 2800, 10, 0.5), heater("b", 2400, 5, 0.5))

    result = ChargeScheduler().build(site, heaters, datetime(2026, 1, 1))

    assert result.slots[0].heater_ids == ("a", "b")
    assert result.slots[0].total_power_w == 5200
