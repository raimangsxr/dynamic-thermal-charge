from datetime import datetime, timedelta

from dynamic_thermal_charge.drivers import SimulatedOutputDriver


def test_simulated_driver_records_only_transitions() -> None:
    driver = SimulatedOutputDriver()
    now = datetime(2026, 1, 1)

    driver.set_state("salon", True, now)
    driver.set_state("salon", True, now + timedelta(minutes=1))
    driver.set_state("salon", False, now + timedelta(minutes=2))

    assert [(change.heater_id, change.enabled) for change in driver.changes] == [
        ("salon", True),
        ("salon", False),
    ]
