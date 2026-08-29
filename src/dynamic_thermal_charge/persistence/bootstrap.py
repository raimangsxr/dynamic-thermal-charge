"""Opening and initialising the store.

The one place that imports the migrations package, and therefore Alembic. The
service start-up path calls :func:`open_store`, which never touches it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from sqlalchemy.engine import Engine

from ..models import AppConfig
from . import SchemaStatus
from .engine import build_engine, store_errors
from .gate import EXPECTED_REVISION, SchemaVersionGate
from .repository import SqlConfigRepository, SqlIndoorReadingRepository
from .relay_test import SqlRelayTestRepository
from .seed import SEED_INSTALLATION_NAME, example_installation
from .url import StoreLocation, resolve_location


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Store:
    location: StoreLocation
    engine: Engine
    repository: SqlConfigRepository
    indoor_readings: SqlIndoorReadingRepository
    gate: SchemaVersionGate
    relay_tests: SqlRelayTestRepository
    configuration_engine: Engine | None = None
    application_engine: Engine | None = None
    context: object | None = None
    system_configuration: object | None = None
    applied_revisions: object | None = None


@dataclass(frozen=True)
class InitReport:
    schema_created: bool
    migrated_from: str | None
    revision: str
    seeded: bool
    heaters: int

    def describe(self) -> list[str]:
        lines: list[str] = []
        if self.schema_created:
            lines.append(f"Schema created at revision {self.revision}.")
        elif self.migrated_from is not None:
            lines.append(
                f"Schema migrated from {self.migrated_from} to {self.revision}; "
                "existing data preserved."
            )
        else:
            lines.append(f"Schema already at revision {self.revision}; nothing to migrate.")
        if self.seeded:
            lines.append(
                f"Seeded the example installation with {self.heaters} heaters. "
                "Review it with 'dtc config show' before starting the service."
            )
        else:
            lines.append("Configuration already present; seeding skipped.")
        return lines


def open_legacy_store(
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], object] | None = None,
    engine_timeouts: tuple[float, float] | None = None,
) -> Store:
    """Open the store without migrating or seeding anything."""
    location = resolve_location(environ)
    engine = build_engine(location, timeouts=engine_timeouts)
    return Store(
        location=location,
        engine=engine,
        repository=SqlConfigRepository(engine, location, clock=clock),  # type: ignore[arg-type]
        indoor_readings=SqlIndoorReadingRepository(engine, location),
        gate=SchemaVersionGate(engine, location),
        relay_tests=SqlRelayTestRepository(engine, location, clock=clock),
    )


def initialise_legacy(
    store: Store,
    seed_config: AppConfig | None = None,
    seed_name: str = SEED_INSTALLATION_NAME,
    allow_seed: bool = True,
) -> InitReport:
    """Create or migrate the schema, then seed only if there is no configuration."""
    from .migrations import upgrade_to_head

    status_before = store.gate.check()
    revision_before = store.gate.stored_revision()
    with store_errors(store.location):
        revision = upgrade_to_head(store.engine)

    seeded = False
    heaters = 0
    if allow_seed:
        config = seed_config if seed_config is not None else example_installation()
        seeded = store.repository.seed(config, seed_name)
        heaters = len(config.heaters) if seeded else 0
    else:
        logger.info("Seeding disabled for this run; configuration left untouched")

    return InitReport(
        schema_created=status_before is SchemaStatus.MISSING,
        migrated_from=(
            revision_before if status_before is SchemaStatus.BEHIND else None
        ),
        revision=revision,
        seeded=seeded,
        heaters=heaters,
    )


def upgrade_legacy(store: Store) -> InitReport:
    """Apply pending migrations only. Never seeds."""
    return initialise_legacy(store, allow_seed=False)


def store_from_context(context) -> Store:
    from .active_schema import ActiveSchemaGate
    generation = context.generation
    return Store(
        location=generation.engines.application_location,
        # ``engine`` remains the configuration engine for compatibility with
        # the pre-split repository API. Runtime data must use
        # ``application_engine`` explicitly.
        engine=generation.engines.configuration,
        repository=generation.configuration,
        indoor_readings=generation.indoor_readings,
        gate=ActiveSchemaGate(
            generation.engines.configuration, generation.engines.application
        ),  # type: ignore[arg-type]
        relay_tests=generation.relay_tests,
        configuration_engine=generation.engines.configuration,
        application_engine=generation.engines.application,
        context=context,
        system_configuration=generation.system_configuration,
        applied_revisions=generation.applied_revisions,
    )


def open_store(
    paths=None,
    clock: Callable[[], object] | None = None,
    engine_timeouts: tuple[float, float] | None = None,
) -> Store:
    """Open the bootstrap-selected stores; runtime never reads an environment."""
    from .context import StorageContext
    from .paths import StorePaths

    if paths is not None and not isinstance(paths, StorePaths):
        raise TypeError("open_store expects StorePaths, never an environment mapping")
    context = StorageContext.open(paths, engine_timeouts=engine_timeouts)
    return store_from_context(context)


def initialise_at(
    paths=None,
    *,
    allow_seed: bool = True,
) -> tuple[Store, InitReport, str | None]:
    from .context import StorageContext

    result = StorageContext.initialise(
        paths, seed_functional_configuration=allow_seed
    )
    store = store_from_context(result.context)
    heaters = 0
    seeded = False
    if allow_seed:
        config, _revision = store.repository.current()
        heaters = len(config.heaters)
        seeded = result.bootstrap.created
    report = InitReport(
        schema_created=result.bootstrap.created,
        migrated_from=None,
        revision="split-1/1",
        seeded=seeded,
        heaters=heaters,
    )
    return store, report, result.bootstrap.onboarding_token


def initialise(
    store: Store,
    seed_config: AppConfig | None = None,
    seed_name: str = SEED_INSTALLATION_NAME,
    allow_seed: bool = True,
) -> InitReport:
    """Compatibility no-op for an already initialised split Store."""
    if store.context is None:
        return initialise_legacy(store, seed_config, seed_name, allow_seed)
    seeded = False
    heaters = 0
    if allow_seed and store.repository.is_empty():
        config = seed_config if seed_config is not None else example_installation()
        seeded = store.repository.seed(config, seed_name)
        heaters = len(config.heaters) if seeded else 0
    return InitReport(False, None, "split-1/1", seeded, heaters)


def upgrade(store: Store) -> InitReport:
    if store.context is None:
        return upgrade_legacy(store)
    return InitReport(False, None, "split-1/1", False, 0)


__all__ = [
    "EXPECTED_REVISION",
    "InitReport",
    "Store",
    "initialise",
    "initialise_at",
    "open_legacy_store",
    "initialise_legacy",
    "open_store",
    "upgrade",
]
