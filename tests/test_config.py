from pathlib import Path

import pytest

from dynamic_thermal_charge.config import load_config


def test_loads_example_configuration() -> None:
    config = load_config(Path(__file__).parents[1] / "examples" / "home.yaml")

    assert config.site.max_total_power_w == 5500
    assert config.site.slot_minutes == 30
    assert config.logging.level == "INFO"
    assert [heater.id for heater in config.heaters] == [
        "salon",
        "entrada",
        "habitaciones",
        "buhardilla",
    ]
    assert config.heaters[0].requested_charge_minutes == 360


def test_rejects_duplicate_heater_ids(tmp_path: Path) -> None:
    config_file = tmp_path / "duplicate.yaml"
    config_file.write_text(
        """
site: {max_total_power_kw: 5, slot_minutes: 30, window_hours: 8}
heaters:
  - {id: same, power_kw: 1, full_charge_hours: 8}
  - {id: same, power_kw: 1, full_charge_hours: 8}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_config(config_file)


def test_rejects_unknown_log_level(tmp_path: Path) -> None:
    config_file = tmp_path / "logging.yaml"
    config_file.write_text(
        """
logging: {level: VERBOSE}
site: {max_total_power_kw: 5, slot_minutes: 30, window_hours: 8}
heaters:
  - {id: one, power_kw: 1, full_charge_hours: 8}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported log level"):
        load_config(config_file)


def test_rejects_slots_that_do_not_align_with_the_clock(tmp_path: Path) -> None:
    config_file = tmp_path / "slots.yaml"
    config_file.write_text(
        """
site: {max_total_power_kw: 5, slot_minutes: 45, window_hours: 9}
heaters:
  - {id: one, power_kw: 1, full_charge_hours: 8}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="divisor of 60"):
        load_config(config_file)


def test_loads_raspberry_pi_deployment_configuration() -> None:
    config = load_config(
        Path(__file__).parents[1] / "examples" / "raspberry-pi.yaml"
    )

    assert config.schedule is not None
    assert config.schedule.timezone == "Europe/Madrid"
    assert config.schedule.window_minutes == 480
    assert config.site.window_minutes == 480
    assert config.weather is not None
    assert config.weather.provider == "simulated"
    assert config.weather.average_temperature_c == 8.0
    assert [heater.output.pin for heater in config.heaters] == [17, 18, 22, 23]
    assert all(heater.output.kind == "gpio" for heater in config.heaters)
    assert all(not heater.output.active_high for heater in config.heaters)
    assert all(heater.thermal is not None for heater in config.heaters)


def test_rejects_duplicate_gpio_pins(tmp_path: Path) -> None:
    config_file = tmp_path / "gpio.yaml"
    config_file.write_text(
        """
site: {max_total_power_kw: 5, slot_minutes: 30, window_hours: 8}
heaters:
  - id: one
    power_kw: 1
    full_charge_hours: 8
    output: {type: gpio, pin: 17}
  - id: two
    power_kw: 1
    full_charge_hours: 8
    output: {type: gpio, pin: 17}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="GPIO BCM pins must be unique"):
        load_config(config_file)


def test_rejects_schedule_not_aligned_with_slots(tmp_path: Path) -> None:
    config_file = tmp_path / "schedule.yaml"
    config_file.write_text(
        """
schedule:
  timezone: Europe/Madrid
  start_time: "00:15"
  end_time: "08:15"
  weekdays: [monday]
site: {max_total_power_kw: 5, slot_minutes: 30}
heaters:
  - {id: one, power_kw: 1, full_charge_hours: 8}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="start_time must align"):
        load_config(config_file)


def test_requires_weather_when_thermal_profiles_are_configured(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "thermal.yaml"
    config_file.write_text(
        """
site: {max_total_power_kw: 5, slot_minutes: 30, window_hours: 8}
heaters:
  - id: one
    power_kw: 1
    full_charge_hours: 8
    thermal:
      target_temperature_c: 21
      design_outdoor_temperature_c: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="require a weather provider"):
        load_config(config_file)
