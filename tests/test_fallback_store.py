from datetime import datetime, timezone
import sqlite3

import pytest
from sqlalchemy import inspect, text, update

from dynamic_thermal_charge.persistence.fallback_store import FallbackRepository
from dynamic_thermal_charge.persistence.local_schema import (
    FALLBACK_SCHEMA_REVISION,
    continuity_snapshot,
    fallback_metadata,
    fallback_schema_version,
)
from dynamic_thermal_charge.persistence.paths import StorePaths
from dynamic_thermal_charge.persistence.topology import (
    BootstrapIncompatibleError,
    FallbackCorruptError,
)


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def test_fallback_schema_is_minimal_separate_and_protected(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = FallbackRepository(paths)
    assert set(inspect(repository.engine).get_table_names()) == set(fallback_metadata.tables)
    assert "installation" not in fallback_metadata.tables
    assert "forecast" not in fallback_metadata.tables
    assert paths.fallback != paths.bootstrap
    assert oct(paths.fallback.stat().st_mode & 0o777) == "0o600"


def test_snapshot_round_trip_is_canonical_and_complete(tmp_path):
    repository = FallbackRepository(StorePaths.in_directory(tmp_path))
    repository.replace_snapshot(
        configuration_revision=7,
        captured_at=NOW,
        configuration={"site": {"max_total_power_w": 5200}, "heaters": []},
        plan={"id": 11, "slots": []},
        admin_token_digest="scrypt:not-a-clear-token:digest",
    )
    snapshot = repository.snapshot()
    assert snapshot is not None
    assert snapshot.configuration_revision == 7
    assert snapshot.captured_at == NOW
    assert snapshot.plan == {"id": 11, "slots": []}
    assert snapshot.admin_token_digest == "scrypt:not-a-clear-token:digest"


def test_invalid_replacement_preserves_previous_snapshot(tmp_path):
    repository = FallbackRepository(StorePaths.in_directory(tmp_path))
    repository.replace_snapshot(
        configuration_revision=1,
        captured_at=NOW,
        configuration={"valid": True},
        plan=None,
    )
    with pytest.raises(ValueError):
        repository.replace_snapshot(
            configuration_revision=2,
            captured_at=NOW,
            configuration={"invalid": float("nan")},
            plan=None,
        )
    assert repository.snapshot().configuration_revision == 1


def test_snapshot_checksum_detects_tampering(tmp_path):
    repository = FallbackRepository(StorePaths.in_directory(tmp_path))
    repository.replace_snapshot(
        configuration_revision=1,
        captured_at=NOW,
        configuration={"valid": True},
        plan=None,
    )
    with repository.engine.begin() as connection:
        connection.execute(
            update(continuity_snapshot).values(configuration_json='{"valid":false}')
        )
    with pytest.raises(FallbackCorruptError, match="checksum"):
        repository.snapshot()


def test_future_fallback_schema_is_rejected(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = FallbackRepository(paths)
    with repository.engine.begin() as connection:
        connection.execute(
            update(fallback_schema_version).values(
                revision=FALLBACK_SCHEMA_REVISION + 1
            )
        )
    with pytest.raises(BootstrapIncompatibleError):
        FallbackRepository(paths)


def test_outbox_is_ordered_durable_and_acknowledged(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    repository = FallbackRepository(paths)
    first = repository.enqueue(
        event_type="heartbeat", aggregate_id="controller", configuration_revision=4,
        payload={"runner": "a"}, occurred_at=NOW,
    )
    second = repository.enqueue(
        event_type="heartbeat", aggregate_id="controller", configuration_revision=4,
        payload={"runner": "a", "sequence": 2}, occurred_at=NOW,
    )
    pending = FallbackRepository(paths).pending_events()
    assert [event.event_id for event in pending] == [first.event_id, second.event_id]
    assert [event.aggregate_order for event in pending] == [1, 2]
    assert repository.acknowledge([first.event_id], at=NOW) == 1
    assert [event.event_id for event in repository.pending_events()] == [second.event_id]


def test_outbox_enforces_a_pending_capacity(tmp_path):
    repository = FallbackRepository(StorePaths.in_directory(tmp_path))
    repository.enqueue(
        event_type="log", aggregate_id="controller", configuration_revision=1,
        payload={}, occurred_at=NOW, maximum_pending=1,
    )
    with pytest.raises(RuntimeError, match="capacity"):
        repository.enqueue(
            event_type="log", aggregate_id="controller", configuration_revision=1,
            payload={}, occurred_at=NOW, maximum_pending=1,
        )
