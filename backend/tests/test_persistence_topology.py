from datetime import datetime, timezone

import pytest

from dynamic_thermal_charge.persistence import (
    ConfigStoreUnavailableError,
    ConfigValidationError,
    SchemaVersionError,
)
from dynamic_thermal_charge.persistence.topology import (
    BootstrapCorruptError,
    BootstrapIncompatibleError,
    StorageFailureKind,
    TopologyMode,
    TopologyState,
    classify_storage_failure,
)


def test_topology_state_is_public_and_never_has_a_locator():
    captured = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    state = TopologyState(
        mode=TopologyMode.FALLBACK,
        canonical_driver="postgresql",
        connected=False,
        configuration_revision=7,
        fallback_captured_at=captured,
        pending_events=3,
    )

    body = state.as_public_dict()
    assert body["mode"] == "fallback"
    assert body["fallback_captured_at"] == captured.isoformat()
    assert body["administrative_writes_allowed"] is False
    assert not ({"url", "host", "database", "password"} & body.keys())


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ConfigStoreUnavailableError("down"), StorageFailureKind.UNAVAILABLE),
        (ConfigValidationError("bad"), StorageFailureKind.INVALID),
        (SchemaVersionError("newer"), StorageFailureKind.INCOMPATIBLE),
        (BootstrapCorruptError("bad bootstrap"), StorageFailureKind.INVALID),
        (
            BootstrapIncompatibleError("future bootstrap"),
            StorageFailureKind.INCOMPATIBLE,
        ),
        (RuntimeError("bug"), StorageFailureKind.INTERNAL),
    ],
)
def test_only_unavailability_is_classified_for_fallback(error, kind):
    assert classify_storage_failure(error) is kind


def test_normal_connected_state_allows_administrative_writes():
    state = TopologyState(TopologyMode.NORMAL, "sqlite", True)
    assert state.administrative_writes_allowed is True
