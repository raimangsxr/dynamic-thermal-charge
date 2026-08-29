from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from dynamic_thermal_charge.persistence import ConfigStoreUnavailableError, ConfigValidationError
from dynamic_thermal_charge.persistence.continuity import (
    ContinuityUnavailable, FallbackRouter, IdempotentEventSink, Reconciler,
)
from dynamic_thermal_charge.persistence.context import StorageContext
from dynamic_thermal_charge.persistence.paths import StorePaths
from dynamic_thermal_charge.persistence.schema import reconciled_event


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def _outage():
    raise ConfigStoreUnavailableError("network unavailable")


def test_only_unavailability_enters_fallback_and_snapshot_must_be_fresh(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    router = FallbackRouter(context, maximum_age_minutes=60)
    snapshot = router.control_snapshot(_outage, now=datetime.now(timezone.utc))
    assert snapshot.configuration
    assert context.topology.mode.value == "fallback"
    with pytest.raises(ConfigValidationError):
        router.control_snapshot(lambda: (_ for _ in ()).throw(ConfigValidationError("bad")), now=NOW)

    router = FallbackRouter(context, maximum_age_minutes=1)
    with pytest.raises(ContinuityUnavailable):
        router.control_snapshot(_outage, now=datetime.now(timezone.utc) + timedelta(minutes=2))


def test_runtime_events_replay_in_batches_exactly_once(tmp_path):
    context = StorageContext.initialise(StorePaths.in_directory(tmp_path)).context
    router = FallbackRouter(context, maximum_age_minutes=60)
    event = router.runtime_write(
        _outage, event_type="heartbeat", aggregate_id="controller",
        configuration_revision=1, payload={"runner": "one"}, occurred_at=NOW,
    )
    sink = IdempotentEventSink(context.generation.engines.application, clock=lambda: NOW)
    assert sink.apply(event) is True
    assert sink.apply(event) is False
    # It remains locally pending until the reconciler receives/ACKs the same UUID.
    assert Reconciler(context, sink, batch_size=10).run_batch(now=NOW) == 1
    with context.generation.engines.application.connect() as connection:
        assert connection.execute(select(func.count()).select_from(reconciled_event)).scalar_one() == 1
    assert context.fallback.pending_events() == []
    assert context.topology.mode.value == "normal"
