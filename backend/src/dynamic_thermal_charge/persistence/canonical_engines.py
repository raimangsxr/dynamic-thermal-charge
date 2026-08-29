"""Build isolated configuration/application engines for the canonical driver."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from .active_schema import (
    POSTGRES_APPLICATION_SCHEMA,
    POSTGRES_CONFIGURATION_SCHEMA,
    ActiveSchemaStatus,
    upgrade_active_schemas,
)
from .engine import build_engine
from .locator import DatabaseDriver, DatabaseLocator
from .paths import StorePaths
from .url import StoreLocation, parse_location


@dataclass(frozen=True)
class CanonicalEngines:
    configuration: Engine
    application: Engine
    configuration_location: StoreLocation
    application_location: StoreLocation


def build_canonical_engines(
    locator: DatabaseLocator,
    paths: StorePaths,
    *,
    timeouts: tuple[float, float] | None = None,
) -> CanonicalEngines:
    configuration_location = parse_location(locator.configuration_url(paths))
    application_location = parse_location(locator.application_url(paths))
    if locator.driver is DatabaseDriver.SQLITE:
        configuration = build_engine(configuration_location, timeouts=timeouts)
        application = build_engine(application_location, timeouts=timeouts)
        _sqlite_attach_compatibility_view(configuration, paths.application)
        return CanonicalEngines(
            configuration=configuration,
            application=application,
            configuration_location=configuration_location,
            application_location=application_location,
        )

    admin = build_engine(configuration_location, timeouts=timeouts)
    with admin.begin() as connection:
        connection.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {POSTGRES_CONFIGURATION_SCHEMA}")
        )
        connection.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {POSTGRES_APPLICATION_SCHEMA}")
        )
    admin.dispose()
    configuration = build_engine(configuration_location, timeouts=timeouts)
    application = build_engine(application_location, timeouts=timeouts)
    _postgres_search_path(configuration, POSTGRES_CONFIGURATION_SCHEMA)
    _postgres_search_path(application, POSTGRES_APPLICATION_SCHEMA)
    return CanonicalEngines(
        configuration=configuration,
        application=application,
        configuration_location=configuration_location,
        application_location=application_location,
    )


def initialise_canonical_schemas(engines: CanonicalEngines) -> ActiveSchemaStatus:
    return upgrade_active_schemas(engines.configuration, engines.application)


def _postgres_search_path(engine: Engine, schema: str) -> None:
    # Schema names are constants, never user input.
    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET search_path TO {schema}")
        finally:
            cursor.close()


def _sqlite_attach_compatibility_view(engine: Engine, application_path) -> None:
    """Let legacy Core callers resolve app tables without merging the files.

    Canonical repositories always receive their dedicated engine. This attached,
    namespaced database is a transitional compatibility surface for embedders
    which still use ``Store.engine`` with SQLAlchemy table objects.
    """
    path = str(application_path)

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        rows = dbapi_connection.execute("PRAGMA database_list").fetchall()
        if not any(row[1] == "dtc_app_compat" for row in rows):
            dbapi_connection.execute("ATTACH DATABASE ? AS dtc_app_compat", (path,))


__all__ = [
    "CanonicalEngines",
    "build_canonical_engines",
    "initialise_canonical_schemas",
]
