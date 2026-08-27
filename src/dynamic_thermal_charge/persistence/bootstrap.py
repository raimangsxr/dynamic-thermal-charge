"""Opening and initialising the store.

The one place that imports the migrations package, and therefore Alembic. The
service start-up path calls :func:`open_store`, which never touches it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Mapping

from sqlalchemy.engine import Engine

from ..models import AppConfig
from . import SchemaStatus
from .engine import build_engine, store_errors
from .gate import EXPECTED_REVISION, SchemaVersionGate
from .repository import SqlConfigRepository, SqlIndoorReadingRepository
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


def open_store(
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
    )


def initialise(
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


def upgrade(store: Store) -> InitReport:
    """Apply pending migrations only. Never seeds."""
    return initialise(store, allow_seed=False)


__all__ = [
    "EXPECTED_REVISION",
    "InitReport",
    "Store",
    "initialise",
    "open_store",
    "upgrade",
]
