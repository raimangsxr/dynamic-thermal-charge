from datetime import date

import pytest

from dynamic_thermal_charge.models import Heater, OutputConfig, ThermalProfile
from dynamic_thermal_charge.thermal import ThermalDemandEngine
from dynamic_thermal_charge.weather import OutdoorForecast


def thermal_heater(
    *,
    thermal_factor: float = 1.0,
    min_charge: float = 0.1,
    max_charge: float = 0.9,
) -> Heater:
    return Heater(
        id="room",
        name="Room",
        power_w=2400,
        full_charge_minutes=480,
        target_charge=1.0,
        priority=50,
        output=OutputConfig(),
        thermal=ThermalProfile(
            target_temperature_c=21,
            design_outdoor_temperature_c=0,
            thermal_factor=thermal_factor,
            min_charge=min_charge,
            max_charge=max_charge,
        ),
    )


def forecast(average_temperature_c: float) -> OutdoorForecast:
    return OutdoorForecast(
        date=date(2026, 1, 1),
        average_temperature_c=average_temperature_c,
        minimum_temperature_c=average_temperature_c - 3,
        maximum_temperature_c=average_temperature_c + 3,
        source="test",
    )


@pytest.mark.parametrize(
    ("average_temperature_c", "expected_minutes"),
    [
        (21, 48),  # Warm day: configured 10% minimum.
        (10.5, 240),  # Halfway between target and design temperature.
        (0, 432),  # Cold design day: configured 90% maximum.
        (-5, 432),  # Colder days remain capped.
    ],
)
def test_calculates_bounded_linear_demand(
    average_temperature_c: float,
    expected_minutes: int,
) -> None:
    result = ThermalDemandEngine().calculate(
        (thermal_heater(),),
        forecast(average_temperature_c),
    )

    assert result == {"room": expected_minutes}


def test_applies_room_thermal_factor() -> None:
    result = ThermalDemandEngine().calculate(
        (thermal_heater(thermal_factor=0.5, min_charge=0, max_charge=1),),
        forecast(10.5),
    )

    assert result == {"room": 120}


def test_falls_back_to_static_target_without_thermal_profile() -> None:
    heater = Heater(
        id="static",
        name="Static",
        power_w=2400,
        full_charge_minutes=480,
        target_charge=0.25,
        priority=10,
        output=OutputConfig(),
    )

    result = ThermalDemandEngine().calculate((heater,), forecast(10))

    assert result == {"static": 120}
