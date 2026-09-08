"""Pure projections of the Home Assistant calendar contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest


def test_calendar_merges_contiguous_intervals_for_one_accumulator():
    pytest.importorskip("homeassistant")
    repository_root = Path(__file__).resolve().parents[2]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    from custom_components.dynamic_thermal_charge.calendar import _events

    start = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)
    snapshot = {
        "installation": {"id": "installation-uuid"},
        "accumulators": [{"id": "salon", "name": "Salón"}],
        "plan": {
            "intervals": [
                {
                    "accumulator_id": "salon",
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=30)).isoformat(),
                    "initial_soc_percent": 20,
                    "target_soc_percent": 30,
                    "planned_energy_kwh": 1.2,
                },
                {
                    "accumulator_id": "salon",
                    "start": (start + timedelta(minutes=30)).isoformat(),
                    "end": (start + timedelta(minutes=60)).isoformat(),
                    "initial_soc_percent": 30,
                    "target_soc_percent": 40,
                    "planned_energy_kwh": 1.3,
                },
            ]
        },
    }

    events = _events(snapshot, start - timedelta(minutes=1), start + timedelta(hours=2))

    assert len(events) == 1
    assert events[0].start == start
    assert events[0].end == start + timedelta(hours=1)
    assert events[0].summary == "Salón"
    assert "SOC 20% → 40%" in events[0].description
    assert "2.50 kWh" in events[0].description
