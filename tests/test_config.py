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
