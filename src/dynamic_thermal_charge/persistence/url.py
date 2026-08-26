"""Resolve and describe the configuration store location.

Deliberately built on the standard library: the "variable is missing" and
"backend is not supported" errors must be reportable even when the optional
``db`` extra is not installed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import unquote, urlsplit

from . import StoreDescription


logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DTC_DATABASE_URL"
SQLITE_BACKEND = "sqlite"
POSTGRES_BACKEND = "postgresql"
POSTGRES_DRIVER = "pg8000"
SUPPORTED_BACKENDS = (SQLITE_BACKEND, POSTGRES_BACKEND)


class DatabaseUrlError(ValueError):
    """The store location is absent or cannot be used."""


@dataclass(frozen=True)
class StoreLocation:
    """A validated store location, plus what may be logged about it."""

    url: str
    backend: str
    remote: bool
    host: str | None
    database: str

    @property
    def description(self) -> StoreDescription:
        return StoreDescription(
            backend=self.backend,
            remote=self.remote,
            host=self.host,
            database=self.database,
        )


def resolve_location(environ: Mapping[str, str] | None = None) -> StoreLocation:
    """Read and validate the store location from the environment."""
    environment = os.environ if environ is None else environ
    raw = environment.get(DATABASE_URL_ENV, "").strip()
    if not raw:
        raise DatabaseUrlError(
            f"{DATABASE_URL_ENV} is not set. Define it in the service environment "
            f"file, for example {DATABASE_URL_ENV}=sqlite:////var/lib/"
            "dynamic-thermal-charge/dynamic-thermal-charge.db for a local database, "
            f"or {DATABASE_URL_ENV}=postgresql+{POSTGRES_DRIVER}://user:password@host"
            ":5432/database for a remote one"
        )
    return parse_location(raw)


def parse_location(raw: str) -> StoreLocation:
    """Validate a store URL without connecting to it."""
    split = urlsplit(raw)
    scheme = split.scheme.lower()
    if not scheme:
        raise DatabaseUrlError(
            f"{DATABASE_URL_ENV} is not a database URL: {_redact(raw)!r}. "
            f"Supported backends: {', '.join(SUPPORTED_BACKENDS)}"
        )
    backend, _, driver = scheme.partition("+")
    if backend not in SUPPORTED_BACKENDS:
        raise DatabaseUrlError(
            f"unsupported database backend {backend!r}. "
            f"Supported backends: {', '.join(SUPPORTED_BACKENDS)}"
        )

    if backend == SQLITE_BACKEND:
        return _sqlite_location(raw, split)
    return _postgres_location(raw, split, driver)


def _sqlite_location(raw: str, split) -> StoreLocation:
    if split.netloc:
        raise DatabaseUrlError(
            "a sqlite URL cannot carry a host; use sqlite:////absolute/path.db "
            "for an absolute path or sqlite:///relative/path.db for a relative one"
        )
    # SQLAlchemy convention: sqlite:///relative.db, sqlite:////absolute.db.
    # urlsplit yields "/relative.db" and "//absolute.db" respectively.
    raw_path = unquote(split.path)
    path = raw_path[1:] if raw_path.startswith("//") else raw_path.lstrip("/")
    if not path:
        raise DatabaseUrlError("a sqlite URL must name a database file")
    return StoreLocation(
        url=raw,
        backend=SQLITE_BACKEND,
        remote=False,
        host=None,
        database=path,
    )


def _postgres_location(raw: str, split, driver: str) -> StoreLocation:
    if not split.hostname:
        raise DatabaseUrlError("a postgresql URL must name a host")
    database = unquote(split.path).lstrip("/")
    if not database:
        raise DatabaseUrlError("a postgresql URL must name a database")

    url = raw
    if not driver:
        # SQLAlchemy would otherwise reach for psycopg2, which has no armv7l
        # wheel. Normalise explicitly rather than fail on the Raspberry Pi.
        url = f"{POSTGRES_BACKEND}+{POSTGRES_DRIVER}{raw[len(POSTGRES_BACKEND):]}"
        logger.info(
            "No PostgreSQL driver given; using %s, the only driver supported on "
            "the deployment target",
            POSTGRES_DRIVER,
        )
    elif driver != POSTGRES_DRIVER:
        raise DatabaseUrlError(
            f"unsupported PostgreSQL driver {driver!r}; this service only supports "
            f"{POSTGRES_DRIVER}, the only one installable on the deployment target "
            "without a compiler"
        )

    host = split.hostname
    if split.port:
        host = f"{host}:{split.port}"
    return StoreLocation(
        url=url,
        backend=POSTGRES_BACKEND,
        remote=True,
        host=host,
        database=database,
    )


def _redact(raw: str) -> str:
    """Never echo a credential back, not even inside a parse error."""
    if "@" not in raw:
        return raw
    return "***" + raw[raw.index("@") :]


__all__ = [
    "DATABASE_URL_ENV",
    "DatabaseUrlError",
    "POSTGRES_DRIVER",
    "SUPPORTED_BACKENDS",
    "StoreLocation",
    "parse_location",
    "resolve_location",
]
