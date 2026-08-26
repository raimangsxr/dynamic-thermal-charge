"""Domain invariants of the configuration dataclasses."""

from __future__ import annotations

import pytest

from dynamic_thermal_charge.models import (
    DEFAULT_RETENTION_DAYS,
    AppConfig,
    Heater,
    OutputConfig,
    SiteConfig,
)


def _site() -> SiteConfig:
    return SiteConfig(max_total_power_w=6000, slot_minutes=30, window_minutes=480)


def _heater(heater_id: str = "salon") -> Heater:
    return Heater(
        id=heater_id,
        name=heater_id,
        power_w=1500,
        full_charge_minutes=480,
        target_charge=1.0,
        priority=0,
        output=OutputConfig(kind="simulated"),
    )


def test_retention_defaults_to_a_year():
    config = AppConfig(site=_site(), heaters=(_heater(),))
    assert config.retention_days == DEFAULT_RETENTION_DAYS == 365


def test_retention_accepts_an_explicit_number_of_days():
    config = AppConfig(site=_site(), heaters=(_heater(),), retention_days=30)
    assert config.retention_days == 30


def test_none_means_unlimited_retention():
    config = AppConfig(site=_site(), heaters=(_heater(),), retention_days=None)
    assert config.retention_days is None


@pytest.mark.parametrize("value", [0, -1, -365])
def test_non_positive_retention_is_rejected(value):
    with pytest.raises(ValueError, match="retention_days"):
        AppConfig(site=_site(), heaters=(_heater(),), retention_days=value)


def test_retention_does_not_weaken_the_existing_invariants():
    with pytest.raises(ValueError, match="heater ids must be unique"):
        AppConfig(
            site=_site(),
            heaters=(_heater("salon"), _heater("salon")),
            retention_days=10,
        )
