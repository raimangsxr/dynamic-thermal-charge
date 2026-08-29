"""Bootstrap-first composition and safe replacement of storage generations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time, timezone
from enum import Enum
import threading
from typing import Iterator
from uuid import uuid4

from .active_schema import require_active_schemas
from .applied_revision import AppliedRevisionRepository
from .bootstrap_store import BootstrapInitResult, BootstrapRepository
from .canonical_engines import (
    CanonicalEngines,
    build_canonical_engines,
    initialise_canonical_schemas,
)
from .fallback_store import FallbackRepository
from .locator import DatabaseLocator
from .paths import StorePaths
from .relay_test import SqlRelayTestRepository
from .repository import SqlConfigRepository, SqlIndoorReadingRepository
from .seed import example_installation
from .system_configuration import SystemConfigurationRepository
from .topology import TopologyMode, TopologyState
from .topology import StorageFailureKind, classify_storage_failure


@dataclass
class StorageGeneration:
    id: str
    locator: DatabaseLocator
    engines: CanonicalEngines
    configuration: SqlConfigRepository
    system_configuration: SystemConfigurationRepository
    indoor_readings: SqlIndoorReadingRepository
    relay_tests: SqlRelayTestRepository
    applied_revisions: AppliedRevisionRepository
    references: int = 0
    retired: bool = False
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.engines.configuration.dispose()
        if self.engines.application is not self.engines.configuration:
            self.engines.application.dispose()
        self.closed = True


@dataclass(frozen=True)
class StorageBootstrapResult:
    context: "StorageContext"
    bootstrap: BootstrapInitResult


class StorageContext:
    def __init__(
        self,
        paths: StorePaths,
        bootstrap: BootstrapRepository,
        fallback: FallbackRepository,
        generation: StorageGeneration,
    ) -> None:
        self.paths = paths
        self.bootstrap = bootstrap
        self.fallback = fallback
        self._generation = generation
        self._lock = threading.RLock()
        self._mode = TopologyMode.NORMAL
        self._last_reconciled_at = None

    @classmethod
    def initialise(
        cls,
        paths: StorePaths | None = None,
        *,
        seed_functional_configuration: bool = True,
    ) -> StorageBootstrapResult:
        resolved = paths or StorePaths.production()
        bootstrap_repository = BootstrapRepository(resolved)
        bootstrap_result = bootstrap_repository.initialise()
        fallback = FallbackRepository(resolved)
        engines = build_canonical_engines(bootstrap_result.locator, resolved)
        initialise_canonical_schemas(engines)
        generation = _build_generation(
            bootstrap_result.locator, engines, fallback
        )
        generation.system_configuration.initialise()
        if seed_functional_configuration:
            generation.configuration.seed(example_installation(), "default")
        context = cls(resolved, bootstrap_repository, fallback, generation)
        if not generation.configuration.is_empty():
            context.refresh_fallback()
        return StorageBootstrapResult(
            context=context,
            bootstrap=bootstrap_result,
        )

    @classmethod
    def open(
        cls, paths: StorePaths | None = None,
        *, engine_timeouts: tuple[float, float] | None = None,
    ) -> "StorageContext":
        resolved = paths or StorePaths.production()
        bootstrap = BootstrapRepository(resolved)
        locator, _revision = bootstrap.locator()
        fallback = FallbackRepository(resolved)
        engines = build_canonical_engines(locator, resolved, timeouts=engine_timeouts)
        require_active_schemas(engines.configuration, engines.application)
        generation = _build_generation(locator, engines, fallback)
        return cls(resolved, bootstrap, fallback, generation)

    @property
    def generation(self) -> StorageGeneration:
        with self._lock:
            return self._generation

    @property
    def topology(self) -> TopologyState:
        generation = self.generation
        try:
            revision = generation.system_configuration.current().revision
        except Exception:
            revision = None
        fallback = self.fallback.snapshot() if self._mode is TopologyMode.FALLBACK else None
        status = self.fallback.reconciliation_status()
        try:
            _locator, locator_revision = self.bootstrap.locator()
        except Exception:
            locator_revision = None
        return TopologyState(
            mode=self._mode,
            canonical_driver=generation.locator.driver.value,
            connected=True,
            locator_revision=locator_revision,
            configuration_revision=revision,
            fallback_captured_at=None if fallback is None else fallback.captured_at,
            last_reconciled_at=self._last_reconciled_at,
            pending_events=int(status["pending_events"]),
        )

    @contextmanager
    def lease(self) -> Iterator[StorageGeneration]:
        with self._lock:
            generation = self._generation
            if generation.closed:
                raise RuntimeError("storage generation is closed")
            generation.references += 1
        try:
            yield generation
        finally:
            with self._lock:
                generation.references -= 1
                if generation.retired and generation.references == 0:
                    generation.close()

    def activate_prepared(
        self,
        locator: DatabaseLocator,
        engines: CanonicalEngines,
        *,
        expected_locator_revision: int,
    ) -> int:
        require_active_schemas(engines.configuration, engines.application)
        prepared = _build_generation(locator, engines, self.fallback)
        # Prove both repositories can be read before committing the locator.
        prepared.system_configuration.current()
        prepared.configuration.current()
        new_revision = self.bootstrap.compare_and_swap_locator(
            expected_locator_revision, locator
        )
        with self._lock:
            previous = self._generation
            self._generation = prepared
            previous.retired = True
            if previous.references == 0:
                previous.close()
        return new_revision

    def close(self) -> None:
        with self._lock:
            current = self._generation
            current.retired = True
            if current.references == 0:
                current.close()

    def enter_fallback(self, error: BaseException) -> None:
        if classify_storage_failure(error) is not StorageFailureKind.UNAVAILABLE:
            raise error
        # Parsing/checksum validation happens here; a corrupt snapshot must not
        # be disguised as a network outage.
        if self.fallback.snapshot() is None:
            raise RuntimeError("canonical store is unavailable and no fallback snapshot exists")
        self._mode = TopologyMode.FALLBACK

    def leave_fallback(self) -> None:
        self._mode = TopologyMode.NORMAL
        self._last_reconciled_at = datetime.now(timezone.utc)

    def begin_migration(self) -> None:
        if self._mode is not TopologyMode.NORMAL:
            raise RuntimeError("storage topology is not available for migration")
        self._mode = TopologyMode.MIGRATING

    def end_migration(self, *, succeeded: bool) -> None:
        self._mode = TopologyMode.NORMAL if succeeded else TopologyMode.NORMAL

    def refresh_fallback(self, plan: dict | None = None) -> None:
        """Replace continuity data only after canonical reads have succeeded."""
        with self.lease() as generation:
            functional, functional_revision = generation.configuration.current()
            system = generation.system_configuration.current()
            admin = system.secrets.get("admin_token_digest")
            self.fallback.replace_snapshot(
                configuration_revision=max(functional_revision, system.revision),
                captured_at=datetime.now(timezone.utc),
                configuration={
                    "functional_revision": functional_revision,
                    "functional": _json_ready(functional),
                    "system_revision": system.revision,
                    "system": system.configuration.documents(),
                },
                plan=_json_ready(plan),
                admin_token_digest=None if admin is None else admin.value,
            )

    def publish_process_revision(self, process: str, *, state: str = "applied") -> None:
        """Publish the revision a long-lived process has loaded."""
        with self.lease() as generation:
            desired = generation.system_configuration.current().revision
            generation.applied_revisions.publish(
                process,
                applied_revision=desired,
                desired_revision=desired,
                state=state,
            )


def _build_generation(
    locator: DatabaseLocator,
    engines: CanonicalEngines,
    fallback: FallbackRepository,
) -> StorageGeneration:
    configuration = SqlConfigRepository(
        engines.configuration,
        engines.configuration_location,
        relay_test_engine=engines.application,
    )
    return StorageGeneration(
        id=str(uuid4()),
        locator=locator,
        engines=engines,
        configuration=configuration,
        system_configuration=SystemConfigurationRepository(
            engines.configuration, engines.configuration_location
        ),
        indoor_readings=SqlIndoorReadingRepository(
            engines.application,
            engines.application_location,
            configuration_engine=engines.configuration,
        ),
        relay_tests=SqlRelayTestRepository(
            engines.application,
            engines.application_location,
            configuration_engine=engines.configuration,
        ),
        applied_revisions=AppliedRevisionRepository(
            engines.application, engines.application_location
        ),
    )


def _json_ready(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"unsupported continuity value {type(value).__name__}")


__all__ = [
    "StorageBootstrapResult",
    "StorageContext",
    "StorageGeneration",
]
