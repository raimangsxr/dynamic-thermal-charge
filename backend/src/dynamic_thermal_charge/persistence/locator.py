"""Structured, allow-listed canonical database locator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import quote

from .paths import StorePaths


class DatabaseDriver(Enum):
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


@dataclass(frozen=True)
class DatabaseLocator:
    driver: DatabaseDriver
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    tls: bool = True
    trusted_no_tls: bool = False

    def __post_init__(self) -> None:
        if self.driver is DatabaseDriver.SQLITE:
            forbidden = (self.host, self.port, self.database, self.username, self.password)
            if any(value is not None for value in forbidden):
                raise ValueError("a SQLite locator cannot contain remote connection fields")
            return
        if not self.host or not self.host.strip():
            raise ValueError("a PostgreSQL locator requires a host")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("PostgreSQL port must be between 1 and 65535")
        if not self.database or not self.database.strip():
            raise ValueError("a PostgreSQL locator requires a database")
        if not self.username or not self.username.strip():
            raise ValueError("a PostgreSQL locator requires a username")
        if not self.password:
            raise ValueError("a PostgreSQL locator requires a password")
        if not self.tls and not self.trusted_no_tls:
            raise ValueError(
                "PostgreSQL without TLS requires explicit trusted-network confirmation"
            )

    @classmethod
    def sqlite(cls) -> "DatabaseLocator":
        return cls(DatabaseDriver.SQLITE)

    def configuration_url(self, paths: StorePaths) -> str:
        if self.driver is DatabaseDriver.SQLITE:
            return paths.sqlite_url("configuration")
        return self._postgres_url()

    def application_url(self, paths: StorePaths) -> str:
        if self.driver is DatabaseDriver.SQLITE:
            return paths.sqlite_url("application")
        return self._postgres_url()

    def public_dict(self) -> dict[str, object]:
        return {
            "driver": self.driver.value,
            "remote": self.driver is DatabaseDriver.POSTGRESQL,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "tls": self.tls if self.driver is DatabaseDriver.POSTGRESQL else None,
        }

    def _postgres_url(self) -> str:
        username = quote(self.username or "", safe="")
        password = quote(self.password or "", safe="")
        host = self.host or ""
        port = f":{self.port}" if self.port is not None else ""
        database = quote(self.database or "", safe="")
        ssl = "require" if self.tls else "disable"
        return (
            f"postgresql+pg8000://{username}:{password}@{host}{port}/{database}"
            f"?sslmode={ssl}"
        )


__all__ = ["DatabaseDriver", "DatabaseLocator"]
