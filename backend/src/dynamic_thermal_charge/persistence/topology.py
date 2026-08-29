"""Shared, secret-free storage topology states and failure classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from . import (
    ConfigStoreError,
    ConfigStoreUnavailableError,
    ConfigValidationError,
    SchemaVersionError,
)


class TopologyMode(Enum):
    BOOTSTRAP = "bootstrap"
    NORMAL = "normal"
    FALLBACK = "fallback"
    MIGRATING = "migrating"
    INCOMPATIBLE = "incompatible"


class StorageFailureKind(Enum):
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    INCOMPATIBLE = "incompatible"
    INTERNAL = "internal"


class StorageTopologyError(ConfigStoreError):
    """Base error whose public representation never includes a locator."""

    code = "storage_topology_error"

    def __init__(self, message: str) -> None:
        self.public_message = message
        super().__init__(message)

    def as_public_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.public_message}


class BootstrapCorruptError(StorageTopologyError):
    code = "bootstrap_corrupt"


class BootstrapIncompatibleError(StorageTopologyError):
    code = "bootstrap_incompatible"


class FallbackCorruptError(StorageTopologyError):
    code = "fallback_corrupt"


@dataclass(frozen=True)
class TopologyState:
    mode: TopologyMode
    canonical_driver: str | None
    connected: bool
    locator_revision: int | None = None
    configuration_revision: int | None = None
    fallback_captured_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    pending_events: int = 0
    operation_id: str | None = None

    @property
    def administrative_writes_allowed(self) -> bool:
        return self.mode is TopologyMode.NORMAL and self.connected

    def as_public_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "canonical_driver": self.canonical_driver,
            "connected": self.connected,
            "locator_revision": self.locator_revision,
            "configuration_revision": self.configuration_revision,
            "fallback_captured_at": _iso(self.fallback_captured_at),
            "last_reconciled_at": _iso(self.last_reconciled_at),
            "pending_events": self.pending_events,
            "operation_id": self.operation_id,
            "administrative_writes_allowed": self.administrative_writes_allowed,
        }


def classify_storage_failure(error: BaseException) -> StorageFailureKind:
    """Only true unavailability is eligible for fallback."""

    if isinstance(error, ConfigStoreUnavailableError):
        return StorageFailureKind.UNAVAILABLE
    if isinstance(error, SchemaVersionError):
        return StorageFailureKind.INCOMPATIBLE
    if isinstance(error, ConfigValidationError):
        return StorageFailureKind.INVALID
    if isinstance(error, BootstrapIncompatibleError):
        return StorageFailureKind.INCOMPATIBLE
    if isinstance(error, BootstrapCorruptError):
        return StorageFailureKind.INVALID
    if isinstance(error, FallbackCorruptError):
        return StorageFailureKind.INVALID
    return StorageFailureKind.INTERNAL


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


__all__ = [
    "BootstrapCorruptError",
    "BootstrapIncompatibleError",
    "FallbackCorruptError",
    "StorageFailureKind",
    "StorageTopologyError",
    "TopologyMode",
    "TopologyState",
    "classify_storage_failure",
]
