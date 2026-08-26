"""Engine construction, SQLite PRAGMAs and the exception boundary.

Only the synchronous SQLAlchemy API is used. The asyncio API would pull in
``greenlet``, the one dependency with no ``linux_armv7l`` wheel and therefore the
one that would demand a compiler on the deployment target (research.md D3).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Connection, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import ConfigStoreError, ConfigStoreUnavailableError, ConfigValidationError
from .url import SQLITE_BACKEND, StoreLocation


logger = logging.getLogger(__name__)

# SQLite ships foreign_keys OFF, so half of the schema's integrity guarantees
# would be decorative without this. WAL lets the controller read while the CLI
# edits; synchronous=FULL is what principle IV's durability requirement needs.
SQLITE_PRAGMAS: tuple[tuple[str, str], ...] = (
    ("foreign_keys", "ON"),
    ("journal_mode", "WAL"),
    ("synchronous", "FULL"),
    ("busy_timeout", "5000"),
)


def build_engine(location: StoreLocation, echo: bool = False) -> Engine:
    """Create the engine for a validated store location."""
    if location.backend == SQLITE_BACKEND:
        _ensure_sqlite_directory(location)
    try:
        engine = create_engine(location.url, echo=echo, future=True)
    except ImportError as exc:
        # The driver lives in an optional extra, so a PostgreSQL URL on an install
        # that only has the base package must say what to install, not surface a
        # bare ModuleNotFoundError (FR-004, FR-008).
        raise ConfigStoreUnavailableError(
            f"the driver for {location.backend} is not installed: {exc}. Install the "
            "optional extra, for example "
            "python -m pip install 'dynamic-thermal-charge[postgres]'"
        ) from exc
    except SQLAlchemyError as exc:
        raise ConfigStoreUnavailableError(
            f"cannot use the configured database ({location.description.describe()}): "
            f"{_reason(exc)}"
        ) from exc
    if location.backend == SQLITE_BACKEND:
        _register_sqlite_pragmas(engine)
    logger.info("Configuration store: %s", location.description.describe())
    return engine


def _ensure_sqlite_directory(location: StoreLocation) -> None:
    directory = Path(location.database).expanduser().parent
    if str(directory) in ("", "."):
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigStoreUnavailableError(
            f"cannot create the database directory {directory}: {exc.strerror}"
        ) from exc


def _register_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            for pragma, value in SQLITE_PRAGMAS:
                cursor.execute(f"PRAGMA {pragma} = {value}")
        finally:
            cursor.close()


def read_sqlite_pragmas(engine: Engine) -> dict[str, object]:
    """Read back the PRAGMAs actually in force. Used by the tests."""
    with engine.connect() as connection:
        return {
            pragma: connection.execute(text(f"PRAGMA {pragma}")).scalar()
            for pragma, _ in SQLITE_PRAGMAS
        }


@contextmanager
def store_errors(location: StoreLocation | None = None) -> Iterator[None]:
    """Translate driver exceptions into domain errors.

    No SQLAlchemy, pg8000 or sqlite3 exception may cross this boundary, the same
    rule ``GpioDriverError`` applies to the hardware (constitution principle II).
    """
    where = f" ({location.description.describe()})" if location is not None else ""
    try:
        yield
    except ConfigStoreError:
        raise
    except ImportError as exc:
        raise ConfigStoreUnavailableError(
            f"a required database driver is not installed{where}: {exc}"
        ) from exc
    except IntegrityError as exc:
        # A constraint violation is invalid configuration, not an unavailable
        # database. Getting this wrong would make the control loop retry an
        # invalid edit forever instead of rejecting it.
        raise _validation_error(exc) from exc
    except (SQLAlchemyError, sqlite3.Error) as exc:
        raise ConfigStoreUnavailableError(
            f"the configuration database is unavailable{where}: {_reason(exc)}"
        ) from exc
    except OSError as exc:
        raise ConfigStoreUnavailableError(
            f"the configuration database is unavailable{where}: {exc.strerror or exc}"
        ) from exc


@contextmanager
def transaction(engine: Engine, location: StoreLocation | None = None) -> Iterator[Connection]:
    """A single atomic unit of work, with the exception boundary applied."""
    with store_errors(location):
        with engine.begin() as connection:
            yield connection


def _validation_error(exc: BaseException) -> ConfigValidationError:
    """Name the offending field from the constraint the database rejected."""
    from .schema import CONSTRAINT_FIELDS

    message = str(exc)
    for constraint, (field, explanation) in CONSTRAINT_FIELDS.items():
        if constraint in message:
            return ConfigValidationError(explanation, field=field)
    logger.debug("Unmapped integrity error: %s", message)
    return ConfigValidationError(
        f"the resulting configuration violates a database constraint: "
        f"{_reason(exc)}"
    )


def _reason(exc: BaseException) -> str:
    """A driver message, with any credential the driver echoed removed."""
    message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    if "@" in message:
        message = message.split("@", 1)[0].rsplit(" ", 1)[0] + " <redacted>"
    return message[:300]


__all__ = [
    "SQLITE_PRAGMAS",
    "build_engine",
    "read_sqlite_pragmas",
    "store_errors",
    "transaction",
]
