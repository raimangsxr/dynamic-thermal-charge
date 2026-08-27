"""Configuration validation, whatever its origin: FR-007, FR-008, FR-009."""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Origin-independent validation (FR-007, FR-008, FR-009)
#
# The YAML loader and its file-based cases are gone: configuration now comes from
# the database and these are the invariants that survive, whatever the origin.
# --------------------------------------------------------------------------- #

from datetime import time as _time

import pytest

from dynamic_thermal_charge.config import validate_config, validate_heaters
from dynamic_thermal_charge.models import (
    AppConfig as _AppConfig,
    Heater as _Heater,
    OutputConfig as _OutputConfig,
    ScheduleConfig as _ScheduleConfig,
    SimulatedForecastConfig as _SimulatedForecastConfig,
    SiteConfig as _SiteConfig,
    ThermalProfile as _ThermalProfile,
    WeatherConfig as _WeatherConfig,
)
from dynamic_thermal_charge.persistence import ConfigValidationError


def _validator_heater(
    heater_id="salon",
    *,
    kind="simulated",
    pin=None,
    thermal=None,
):
    return _Heater(
        id=heater_id,
        name=heater_id,
        power_w=1500,
        full_charge_minutes=480,
        target_charge=1.0,
        priority=0,
        thermal=thermal,
        output=_OutputConfig(kind=kind, pin=pin),
    )


def _validator_config(heaters=None, *, schedule=None, weather=None, slot_minutes=30):
    return _AppConfig(
        site=_SiteConfig(
            max_total_power_w=6000,
            slot_minutes=slot_minutes,
            window_minutes=480,
        ),
        heaters=heaters or (_validator_heater(),),
        schedule=schedule,
        weather=weather,
    )


def test_validator_accepts_a_coherent_installation():
    validate_config(_validator_config())


def test_indoor_age_validation_names_the_offending_field():
    config = _validator_config()
    object.__setattr__(config.site, "indoor_max_age_minutes", 0)
    with pytest.raises(ConfigValidationError) as error:
        validate_config(config)
    assert error.value.field == "indoor_max_age_minutes"
    assert "positive" in str(error.value)


def test_indoor_range_validation_names_both_bounds():
    config = _validator_config()
    object.__setattr__(config.site, "indoor_min_plausible_c", 30.0)
    object.__setattr__(config.site, "indoor_max_plausible_c", 20.0)
    with pytest.raises(ConfigValidationError) as error:
        validate_config(config)
    assert error.value.field == "indoor_min_plausible_c"
    assert "indoor_max_plausible_c" in str(error.value)


def test_duplicate_gpio_pin_names_both_heaters():
    heaters = (
        _validator_heater("salon", kind="gpio", pin=17),
        _validator_heater("entrada", kind="gpio", pin=17),
    )
    with pytest.raises(ConfigValidationError) as error:
        validate_heaters(heaters)
    message = str(error.value)
    assert "17" in message
    assert "salon" in message and "entrada" in message
    assert error.value.field == "pin"
    assert error.value.heater_id == "entrada"


def test_distinct_gpio_pins_are_accepted():
    validate_heaters(
        (
            _validator_heater("salon", kind="gpio", pin=17),
            _validator_heater("entrada", kind="gpio", pin=18),
        )
    )


def test_several_simulated_outputs_without_a_pin_do_not_clash():
    validate_heaters((_validator_heater("salon"), _validator_heater("entrada")))


def test_duplicate_heater_id_is_reported_with_the_offending_id():
    with pytest.raises(ConfigValidationError) as error:
        validate_heaters((_validator_heater("salon"), _validator_heater("salon")))
    assert "salon" in str(error.value)
    assert error.value.field == "heater_id"


@pytest.mark.parametrize(
    ("start", "end", "slot_minutes", "offending"),
    [
        (_time(0, 17), _time(8, 0), 30, "start_time"),
        (_time(0, 0), _time(8, 17), 30, "end_time"),
        (_time(0, 20), _time(8, 0), 30, "start_time"),
    ],
)
def test_schedule_must_align_with_slot_minutes(start, end, slot_minutes, offending):
    schedule = _ScheduleConfig(
        timezone="Europe/Madrid",
        start_time=start,
        end_time=end,
        weekdays=(0, 1, 2, 3, 4, 5, 6),
    )
    with pytest.raises(ConfigValidationError) as error:
        validate_config(_validator_config(schedule=schedule, slot_minutes=slot_minutes))
    assert error.value.field == offending
    assert str(slot_minutes) in str(error.value)


def test_an_aligned_schedule_is_accepted():
    schedule = _ScheduleConfig(
        timezone="Europe/Madrid",
        start_time=_time(0, 0),
        end_time=_time(8, 0),
        weekdays=(0, 1, 2, 3, 4, 5, 6),
    )
    validate_config(_validator_config(schedule=schedule))


def test_a_thermal_profile_requires_a_weather_provider():
    thermal = _ThermalProfile(
        target_temperature_c=21.0, design_outdoor_temperature_c=-2.0
    )
    # AppConfig itself refuses to be built without weather, so the cross-table
    # rule is checked on a configuration whose weather was dropped afterwards.
    config = _validator_config(
        heaters=(_validator_heater(thermal=thermal),),
        weather=_WeatherConfig(
            provider="simulated",
            simulated=_SimulatedForecastConfig(
                average_temperature_c=8.0, minimum_temperature_c=3.0
            ),
        ),
    )
    validate_config(config)

    stripped = object.__new__(_AppConfig)
    object.__setattr__(stripped, "site", config.site)
    object.__setattr__(stripped, "heaters", config.heaters)
    object.__setattr__(stripped, "schedule", None)
    object.__setattr__(stripped, "weather", None)
    with pytest.raises(ConfigValidationError) as error:
        validate_config(stripped)
    assert error.value.field == "weather"


def test_validation_error_prefixes_the_heater_when_it_knows_it():
    error = ConfigValidationError("pin 17 is taken", field="pin", heater_id="entrada")
    assert str(error) == "heater entrada: pin 17 is taken"
