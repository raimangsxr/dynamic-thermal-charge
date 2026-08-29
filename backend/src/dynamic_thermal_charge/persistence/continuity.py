"""Operation-policy routing and idempotent fallback reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Callable, Mapping

from sqlalchemy import insert, select

from .engine import transaction
from .fallback_store import FallbackRepository, OutboxEvent
from .mapping import to_utc
from .schema import reconciled_event
from .topology import StorageFailureKind, classify_storage_failure


class ContinuityUnavailable(RuntimeError):
    pass


class FallbackRouter:
    def __init__(self, context, *, maximum_age_minutes: int) -> None:
        self.context = context
        self.maximum_age = timedelta(minutes=maximum_age_minutes)

    def control_snapshot(self, canonical_read: Callable[[], object], *, now: datetime):
        try:
            value = canonical_read()
            self.context.leave_fallback()
            return value
        except Exception as exc:
            if classify_storage_failure(exc) is not StorageFailureKind.UNAVAILABLE:
                raise
            self.context.enter_fallback(exc)
            snapshot = self.context.fallback.snapshot()
            if snapshot is None or now.astimezone(timezone.utc) - snapshot.captured_at > self.maximum_age:
                raise ContinuityUnavailable("fallback snapshot is missing or expired") from exc
            return snapshot

    def runtime_write(
        self, canonical_write: Callable[[], object], *, event_type: str,
        aggregate_id: str, configuration_revision: int,
        payload: Mapping[str, object], occurred_at: datetime,
    ) -> object | OutboxEvent:
        try:
            return canonical_write()
        except Exception as exc:
            if classify_storage_failure(exc) is not StorageFailureKind.UNAVAILABLE:
                raise
            self.context.enter_fallback(exc)
            return self.context.fallback.enqueue(
                event_type=event_type, aggregate_id=aggregate_id,
                configuration_revision=configuration_revision,
                payload=payload, occurred_at=occurred_at,
            )


class IdempotentEventSink:
    """Durable deduplication boundary for versioned domain events."""

    SUPPORTED_TYPES = frozenset(
        {"plan", "forecast", "heartbeat", "output_transition", "controller_log"}
    )

    def __init__(self, engine, location=None, *, clock=None) -> None:
        self.engine = engine
        self.location = location
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def apply(self, event: OutboxEvent) -> bool:
        if event.event_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"unsupported fallback event type {event.event_type!r}")
        with transaction(self.engine, self.location) as connection:
            if connection.execute(
                select(reconciled_event.c.event_id).where(
                    reconciled_event.c.event_id == event.event_id
                )
            ).first():
                return False
            connection.execute(insert(reconciled_event).values(
                event_id=event.event_id, event_type=event.event_type,
                payload_version=event.payload_version,
                aggregate_id=event.aggregate_id,
                aggregate_order=event.aggregate_order,
                configuration_revision=event.configuration_revision,
                occurred_at=to_utc(event.occurred_at),
                payload_json=json.dumps(event.payload, sort_keys=True, separators=(",", ":")),
                reconciled_at=to_utc(self.clock()),
            ))
        return True


class Reconciler:
    def __init__(self, context, sink: IdempotentEventSink, *, batch_size: int = 100) -> None:
        self.context, self.sink = context, sink
        self.batch_size = max(1, min(batch_size, 1000))

    def run_batch(self, *, now: datetime) -> int:
        events = self.context.fallback.pending_events(limit=self.batch_size)
        acknowledged: list[str] = []
        try:
            for event in events:
                self.sink.apply(event)
                acknowledged.append(event.event_id)
        except Exception as exc:
            self.context.fallback.record_reconciliation(
                attempted_at=now, succeeded=False,
                error_code=exc.__class__.__name__,
            )
            # ACK only the prefix that was durably applied. The failed event and
            # remaining suffix are retried on the next run.
            self.context.fallback.acknowledge(acknowledged, at=now)
            raise
        self.context.fallback.acknowledge(acknowledged, at=now)
        self.context.fallback.record_reconciliation(
            attempted_at=now, succeeded=True,
        )
        if not self.context.fallback.pending_events(limit=1):
            self.context.refresh_fallback()
            self.context.leave_fallback()
        return len(acknowledged)


class FallbackPlanExecutor:
    """Select a bounded local plan and invoke safe-off when continuity is unsafe."""

    def __init__(self, fallback: FallbackRepository, *, maximum_age: timedelta,
                 safe_off: Callable[[], None], clock: Callable[[], datetime] | None = None) -> None:
        self.fallback = fallback
        self.maximum_age = maximum_age
        self.safe_off = safe_off
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def plan(self) -> dict | None:
        snapshot = self.fallback.snapshot()
        now = to_utc(self.clock())
        if snapshot is None or now - snapshot.captured_at > self.maximum_age or snapshot.plan is None:
            self.safe_off()
            return None
        return snapshot.plan


__all__ = ["ContinuityUnavailable", "FallbackRouter", "FallbackPlanExecutor", "IdempotentEventSink", "Reconciler"]
