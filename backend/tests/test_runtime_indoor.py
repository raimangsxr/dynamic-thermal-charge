"""Controller composition reads indoor state once per recalculation."""

from dataclasses import replace
from datetime import datetime, timezone

from dynamic_thermal_charge import runtime
from dynamic_thermal_charge.models import IndoorReading
from dynamic_thermal_charge.persistence import ConfigStoreUnavailableError
from dynamic_thermal_charge.persistence.seed import example_installation


NOW = datetime(2026, 1, 16, 1, tzinfo=timezone.utc)


def _config():
    config = example_installation()
    return replace(
        config,
        heaters=(replace(config.heaters[0], indoor_topic="ha/salon/temp"),),
    )


class Readings:
    def __init__(self, values=None, error=None):
        self.values = values or {}
        self.error = error
        self.calls = 0

    def read_all(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.values


def test_each_recalculation_reads_once_and_returns_selected_temperatures():
    readings = Readings({"salon": IndoorReading("salon", 19.0, NOW)})
    tracker = runtime._IndoorFallbackTracker()
    assert tracker.select(_config(), readings, NOW) == {"salon": 19.0}
    assert tracker.select(_config(), readings, NOW) == {"salon": 19.0}
    assert readings.calls == 2


def test_store_failure_or_missing_reading_continues_with_fallback(caplog):
    tracker = runtime._IndoorFallbackTracker()
    failed = Readings(error=ConfigStoreUnavailableError("offline"))
    assert tracker.select(_config(), failed, NOW) == {}
    assert tracker.select(_config(), failed, NOW) == {}
    assert caplog.text.count("Indoor reading store unavailable") == 1


def test_fallback_and_recovery_are_logged_once_per_transition(caplog):
    caplog.set_level("INFO")
    readings = Readings()
    tracker = runtime._IndoorFallbackTracker()
    tracker.select(_config(), readings, NOW)
    tracker.select(_config(), readings, NOW)
    readings.values = {"salon": IndoorReading("salon", 20, NOW)}
    tracker.select(_config(), readings, NOW)
    tracker.select(_config(), readings, NOW)
    assert caplog.text.count("using thermal fallback") == 1
    assert caplog.text.count("recovered indoor temperature") == 1
