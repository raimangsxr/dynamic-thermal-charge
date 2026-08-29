"""Guards for the migration away from runtime environment configuration."""

from __future__ import annotations

import re
from pathlib import Path

from dynamic_thermal_charge.runtime_configuration_inventory import (
    ConfigurationDisposition,
    INVENTORY_VERSION,
    LEGACY_ENVIRONMENT_INPUTS,
    LEGACY_RUNTIME_CONFIGURATION_FILES,
)


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "dynamic_thermal_charge"


def test_every_named_runtime_environment_input_is_in_the_versioned_inventory():
    discovered: set[str] = set()
    for source in SOURCE_ROOT.rglob("*.py"):
        if source.name == "runtime_configuration_inventory.py":
            continue
        discovered.update(re.findall(r"\bDTC_[A-Z0-9_]+\b", source.read_text()))

    assert INVENTORY_VERSION >= 1
    assert discovered <= LEGACY_ENVIRONMENT_INPUTS.keys()
    assert all(
        item.disposition is ConfigurationDisposition.PERSISTED
        for item in LEGACY_ENVIRONMENT_INPUTS.values()
    )
    assert "AEMET_API_KEY" in LEGACY_ENVIRONMENT_INPUTS


def test_runtime_has_no_configuration_file_reader_to_inventory():
    assert LEGACY_RUNTIME_CONFIGURATION_FILES == ()
    for source in SOURCE_ROOT.rglob("*.py"):
        text = source.read_text()
        assert "yaml.safe_load" not in text
        assert "yaml.load" not in text


def test_secret_classification_covers_every_current_credential():
    expected = {
        "DTC_DATABASE_URL",
        "DTC_API_TOKEN",
        "DTC_MQTT_USERNAME",
        "DTC_MQTT_PASSWORD",
        "AEMET_API_KEY",
    }
    assert {name for name, item in LEGACY_ENVIRONMENT_INPUTS.items() if item.secret} == expected
