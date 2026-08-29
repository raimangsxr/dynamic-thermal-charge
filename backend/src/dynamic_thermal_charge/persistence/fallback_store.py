"""Minimal local continuity snapshot repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Mapping
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update

from .bootstrap_store import _ensure_state_permissions, _local_engine, _protect_file
from .local_schema import (
    continuity_snapshot, fallback_outbox, reconciliation_state,
    upgrade_fallback_schema,
)
from .paths import StorePaths
from .topology import FallbackCorruptError


@dataclass(frozen=True)
class ContinuitySnapshot:
    configuration_revision: int
    captured_at: datetime
    configuration: dict
    plan: dict | None
    admin_token_digest: str | None


@dataclass(frozen=True)
class OutboxEvent:
    event_id: str
    event_type: str
    payload_version: int
    aggregate_id: str
    aggregate_order: int
    configuration_revision: int
    occurred_at: datetime
    payload: dict


class FallbackRepository:
    def __init__(self, paths: StorePaths) -> None:
        self.paths = paths
        _ensure_state_permissions(paths.state_directory)
        self.engine = _local_engine(paths.fallback)
        upgrade_fallback_schema(self.engine)
        _protect_file(paths.fallback)

    def replace_snapshot(
        self,
        *,
        configuration_revision: int,
        captured_at: datetime,
        configuration: Mapping[str, object],
        plan: Mapping[str, object] | None,
        admin_token_digest: str | None = None,
    ) -> None:
        configuration_json = _canonical_json(configuration)
        plan_json = None if plan is None else _canonical_json(plan)
        checksum = _checksum(configuration_json, plan_json, configuration_revision)
        timestamp = _aware(captured_at).isoformat()
        with self.engine.begin() as connection:
            connection.execute(delete(continuity_snapshot))
            connection.execute(
                insert(continuity_snapshot).values(
                    id=1,
                    configuration_revision=configuration_revision,
                    captured_at=timestamp,
                    checksum=checksum,
                    configuration_json=configuration_json,
                    plan_json=plan_json,
                    admin_token_digest=admin_token_digest,
                )
            )

    def snapshot(self) -> ContinuitySnapshot | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(continuity_snapshot)).mappings().one_or_none()
        if row is None:
            return None
        revision = int(row["configuration_revision"])
        configuration_json = str(row["configuration_json"])
        plan_json = row["plan_json"]
        expected = _checksum(configuration_json, plan_json, revision)
        if not hmac.compare_digest(expected, str(row["checksum"])):
            raise FallbackCorruptError("fallback snapshot checksum does not match")
        try:
            configuration = json.loads(configuration_json)
            plan = None if plan_json is None else json.loads(plan_json)
            captured_at = _aware(datetime.fromisoformat(str(row["captured_at"])))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FallbackCorruptError("fallback snapshot payload is invalid") from exc
        if not isinstance(configuration, dict) or (
            plan is not None and not isinstance(plan, dict)
        ):
            raise FallbackCorruptError("fallback snapshot has an invalid shape")
        return ContinuitySnapshot(
            configuration_revision=revision,
            captured_at=captured_at,
            configuration=configuration,
            plan=plan,
            admin_token_digest=row["admin_token_digest"],
        )

    def enqueue(
        self, *, event_type: str, aggregate_id: str,
        configuration_revision: int, payload: Mapping[str, object],
        occurred_at: datetime, payload_version: int = 1,
        maximum_pending: int = 10_000,
    ) -> OutboxEvent:
        if payload_version < 1 or configuration_revision < 0:
            raise ValueError("outbox versions cannot be negative")
        event_id = str(uuid4())
        timestamp = _aware(occurred_at)
        payload_json = _canonical_json(payload)
        with self.engine.begin() as connection:
            pending = connection.execute(
                select(func.count()).select_from(fallback_outbox).where(
                    fallback_outbox.c.delivered_at.is_(None)
                )
            ).scalar_one()
            if int(pending) >= maximum_pending:
                raise RuntimeError("fallback outbox capacity reached")
            order = int(connection.execute(
                select(func.max(fallback_outbox.c.aggregate_order)).where(
                    fallback_outbox.c.aggregate_id == aggregate_id
                )
            ).scalar_one_or_none() or 0) + 1
            connection.execute(insert(fallback_outbox).values(
                event_id=event_id, event_type=event_type,
                payload_version=payload_version, aggregate_id=aggregate_id,
                aggregate_order=order,
                configuration_revision=configuration_revision,
                occurred_at=timestamp.isoformat(), payload_json=payload_json,
                delivered_at=None,
            ))
        return OutboxEvent(event_id, event_type, payload_version, aggregate_id,
                           order, configuration_revision, timestamp, dict(payload))

    def pending_events(self, *, limit: int = 100) -> list[OutboxEvent]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(fallback_outbox)
                .where(fallback_outbox.c.delivered_at.is_(None))
                .order_by(fallback_outbox.c.occurred_at, fallback_outbox.c.aggregate_id,
                          fallback_outbox.c.aggregate_order)
                .limit(max(1, min(limit, 1000)))
            ).mappings().all()
        try:
            return [OutboxEvent(
                event_id=str(row["event_id"]), event_type=str(row["event_type"]),
                payload_version=int(row["payload_version"]),
                aggregate_id=str(row["aggregate_id"]),
                aggregate_order=int(row["aggregate_order"]),
                configuration_revision=int(row["configuration_revision"]),
                occurred_at=_aware(datetime.fromisoformat(str(row["occurred_at"]))),
                payload=json.loads(str(row["payload_json"])),
            ) for row in rows]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FallbackCorruptError("fallback outbox payload is invalid") from exc

    def acknowledge(self, event_ids: list[str], *, at: datetime) -> int:
        if not event_ids:
            return 0
        with self.engine.begin() as connection:
            result = connection.execute(
                update(fallback_outbox)
                .where(fallback_outbox.c.event_id.in_(event_ids))
                .where(fallback_outbox.c.delivered_at.is_(None))
                .values(delivered_at=_aware(at).isoformat())
            )
        return int(result.rowcount)

    def reconciliation_status(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            row = connection.execute(select(reconciliation_state)).mappings().one_or_none()
            pending = connection.execute(
                select(func.count()).select_from(fallback_outbox).where(
                    fallback_outbox.c.delivered_at.is_(None)
                )
            ).scalar_one()
        return {
            "pending_events": int(pending),
            "last_attempt_at": None if row is None else row["last_attempt_at"],
            "last_success_at": None if row is None else row["last_success_at"],
            "last_error_code": None if row is None else row["last_error_code"],
        }

    def record_reconciliation(self, *, attempted_at: datetime,
                              succeeded: bool, error_code: str | None = None) -> None:
        """Persist the checkpoint used to resume reconciliation after restart."""
        now = _aware(attempted_at).isoformat()
        with self.engine.begin() as connection:
            existing = connection.execute(select(reconciliation_state.c.id)).first()
            values = {
                "last_attempt_at": now,
                "last_success_at": now if succeeded else None,
                "last_error_code": None if succeeded else (error_code or "unknown"),
            }
            if existing is None:
                connection.execute(insert(reconciliation_state).values(id=1, **values))
            else:
                connection.execute(update(reconciliation_state).where(
                    reconciliation_state.c.id == 1
                ).values(**values))


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _checksum(configuration_json: str, plan_json: str | None, revision: int) -> str:
    material = f"{revision}\n{configuration_json}\n{plan_json or ''}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = ["ContinuitySnapshot", "FallbackRepository", "OutboxEvent"]
