"""Persistence boundary: the only package allowed to import SQLAlchemy.

Everything outside this package talks to the domain protocols declared here and
to the domain errors declared here. No SQLAlchemy, pg8000 or sqlite3 exception
ever crosses this boundary, the same way ``GpioDriverError`` shields the core
from hardware libraries.

The module itself is deliberately free of SQLAlchemy imports so that declaring a
dependency on the protocols does not pull the driver stack into memory. The
concrete implementations live in sibling modules and are imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from ..models import AppConfig, Heater


class ConfigStoreError(Exception):
    """Root of every configuration-store failure."""


class ConfigStoreUnavailableError(ConfigStoreError):
    """The store cannot be reached: network down, timeout, locked file.

    This is the only error the control loop treats as transient: it retains the
    running plan and retries (constitution principle IV).
    """


class ConfigStoreEmptyError(ConfigStoreError):
    """The schema exists but holds no installation."""


class SchemaVersionError(ConfigStoreError):
    """The schema is absent, behind, or newer than this service understands."""


class ConfigValidationError(ConfigStoreError):
    """Stored or resulting configuration is invalid.

    Carries the offending field and, where applicable, the heater it belongs to,
    so the message is actionable without reading the code (principle III).
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        heater_id: str | None = None,
    ) -> None:
        self.field = field
        self.heater_id = heater_id
        super().__init__(message)

    def __str__(self) -> str:
        message = super().__str__()
        if self.heater_id is not None:
            return f"heater {self.heater_id}: {message}"
        return message


class ConfigConflictError(ConfigStoreError):
    """The configuration changed while an edit was being prepared."""


class SecretRejectedError(ConfigValidationError):
    """A value that looks like a credential was offered as configuration."""


class Liveness(Enum):
    """How much the API may claim about the controller's state.

    Not a health metric: it is the answer to "may I present this as current?".
    """

    #: Heartbeat is recent. The output state may be presented as current.
    LIVE = "live"
    #: Heartbeat is recent but the controller cannot reach something it needs.
    LIVE_DEGRADED = "live_degraded"
    #: Heartbeat is too old, or dated in the future. Nothing may be claimed.
    STALE = "stale"
    #: No heartbeat was ever published against this database.
    NEVER_SEEN = "never_seen"

    @property
    def state_is_current(self) -> bool:
        return self in (Liveness.LIVE, Liveness.LIVE_DEGRADED)


class SchemaStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    BEHIND = "behind"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StoreDescription:
    """What may be logged about the store: never the URL, never credentials."""

    backend: str
    remote: bool
    host: str | None
    database: str

    def describe(self) -> str:
        location = "remote" if self.remote else "local"
        if self.host is None:
            return f"{self.backend} ({location}), database {self.database}"
        return f"{self.backend} ({location}) at {self.host}, database {self.database}"


@dataclass(frozen=True)
class ConfigChange:
    """One applied configuration edit, as reported to the operator."""

    entity: str
    entity_key: str | None
    field: str | None
    old_value: str | None
    new_value: str | None
    action: str
    revision_before: int
    revision_after: int


@dataclass(frozen=True)
class Heartbeat:
    """The controller's proof of life, as stored."""

    updated_at: datetime
    started_at: datetime
    degraded: bool
    poll_seconds: float
    driver_kind: str
    runner_id: str
    plan_id: int | None = None


@dataclass(frozen=True)
class ForecastRef:
    id: int


@dataclass(frozen=True)
class PlanRef:
    id: int


@dataclass(frozen=True)
class PruneReport:
    deleted: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


class ConfigRepository(Protocol):
    def current(self) -> tuple[AppConfig, int]:
        """Return the validated configuration and its revision, or raise."""

    def set_field(
        self,
        revision: int,
        entity: str,
        entity_key: str | None,
        field: str,
        value: str,
    ) -> ConfigChange:
        """Apply one edit on top of ``revision``, atomically."""

    def add_heater(self, revision: int, heater: Heater) -> ConfigChange:
        """Add a heater, validating the whole resulting configuration."""

    def remove_heater(self, revision: int, heater_id: str) -> ConfigChange:
        """Remove a heater and its output and thermal profile, keeping history."""


class HistoryRecorder(Protocol):
    """Append-only audit trail.

    No method may ever propagate an exception. A write failure is logged as an
    error and the call returns an empty result: observability must never be able
    to stop the control loop (constitution principle IV).
    """

    def record_forecast(self, forecast: object) -> ForecastRef | None: ...

    def record_plan(
        self,
        plan: object,
        forecast_ref: ForecastRef | None,
        installation_revision: int,
        requested_minutes: dict[str, int] | None = None,
    ) -> PlanRef | None: ...

    def record_transition(
        self,
        heater_id: str,
        state: bool,
        occurred_at: datetime,
        plan_ref: PlanRef | None = None,
    ) -> None: ...

    def prune(self, now: datetime, retention_days: int | None) -> PruneReport: ...


class HeartbeatPublisher(Protocol):
    """The controller's proof of life.

    ``publish`` may NEVER propagate an exception: a write failure is logged as an
    error and the control loop carries on, exactly like ``HistoryRecorder``. The
    visible consequence is that the API marks the state as not current, which is
    precisely the honest answer -- at that moment it has proof of nothing.
    """

    def publish(
        self,
        now: datetime,
        degraded: bool,
        plan_ref: "PlanRef | None" = None,
    ) -> None: ...

    def read(self) -> Heartbeat | None:
        """The last heartbeat, or None if there has never been one."""


class SchemaGate(Protocol):
    def check(self) -> SchemaStatus:
        """Compare the stored schema revision with the one this service knows."""


__all__ = [
    "ConfigChange",
    "Heartbeat",
    "HeartbeatPublisher",
    "Liveness",
    "ConfigConflictError",
    "ConfigRepository",
    "ConfigStoreEmptyError",
    "ConfigStoreError",
    "ConfigStoreUnavailableError",
    "ConfigValidationError",
    "ForecastRef",
    "HistoryRecorder",
    "PlanRef",
    "PruneReport",
    "SchemaGate",
    "SchemaStatus",
    "SchemaVersionError",
    "SecretRejectedError",
    "StoreDescription",
]
