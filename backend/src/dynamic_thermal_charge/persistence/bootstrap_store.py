"""Repository for the mandatory local bootstrap store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import sqlite3
from typing import Callable

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from . import ConfigConflictError
from .engine import build_engine
from .local_schema import (
    BOOTSTRAP_SCHEMA_REVISION,
    active_locator,
    bootstrap_schema_version,
    bootstrap_state,
    upgrade_bootstrap_schema,
)
from .locator import DatabaseDriver, DatabaseLocator
from .paths import StorePaths
from .secret_digest import digest_secret, secret_matches
from .topology import BootstrapCorruptError, BootstrapIncompatibleError
from .url import parse_location


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class BootstrapInitResult:
    created: bool
    onboarding_token: str | None
    locator: DatabaseLocator
    locator_revision: int


@dataclass(frozen=True)
class BootstrapRecord:
    installation_state: str
    locator_revision: int
    onboarding_expires_at: datetime | None
    onboarding_attempts: int


class BootstrapRepository:
    def __init__(
        self,
        paths: StorePaths,
        *,
        clock: Clock | None = None,
        onboarding_lifetime: timedelta = timedelta(hours=24),
    ) -> None:
        self.paths = paths
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._onboarding_lifetime = onboarding_lifetime
        _ensure_state_permissions(paths.state_directory)
        self.engine = _local_engine(paths.bootstrap)
        upgrade_bootstrap_schema(self.engine)
        _protect_file(paths.bootstrap)

    def initialise(self) -> BootstrapInitResult:
        now = _aware(self._clock())
        token = secrets.token_urlsafe(32)
        digest = digest_secret(token)
        expires = now + self._onboarding_lifetime
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(bootstrap_state)
                .prefix_with("OR IGNORE")
                .values(
                    id=1,
                    installation_state="unconfigured",
                    locator_revision=1,
                    onboarding_digest=digest,
                    onboarding_expires_at=expires.isoformat(),
                    onboarding_attempts=0,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
            )
            created = result.rowcount == 1
            if created:
                connection.execute(
                    insert(active_locator).values(
                        id=1,
                        driver=DatabaseDriver.SQLITE.value,
                        host=None,
                        port=None,
                        database_name=None,
                        username=None,
                        password=None,
                        tls=False,
                        trusted_no_tls=False,
                    )
                )
        locator, revision = self.locator()
        return BootstrapInitResult(
            created=created,
            onboarding_token=token if created else None,
            locator=locator,
            locator_revision=revision,
        )

    def state(self) -> BootstrapRecord:
        with self.engine.connect() as connection:
            row = connection.execute(select(bootstrap_state)).mappings().one_or_none()
        if row is None:
            raise BootstrapCorruptError("bootstrap has no installation state")
        return BootstrapRecord(
            installation_state=str(row["installation_state"]),
            locator_revision=int(row["locator_revision"]),
            onboarding_expires_at=_parse_datetime(row["onboarding_expires_at"]),
            onboarding_attempts=int(row["onboarding_attempts"]),
        )

    def locator(self) -> tuple[DatabaseLocator, int]:
        with self.engine.connect() as connection:
            state_row = connection.execute(
                select(bootstrap_state.c.locator_revision)
            ).one_or_none()
            locator_row = connection.execute(select(active_locator)).mappings().one_or_none()
        if state_row is None or locator_row is None:
            raise BootstrapCorruptError(
                "bootstrap locator is missing; ask the administrator to initialize it"
            )
        return _map_locator(locator_row), int(state_row.locator_revision)

    def onboarding_token_matches(self, offered: str) -> bool:
        now = _aware(self._clock())
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    bootstrap_state.c.installation_state,
                    bootstrap_state.c.onboarding_digest,
                    bootstrap_state.c.onboarding_expires_at,
                )
            ).mappings().one_or_none()
        if row is None or row["installation_state"] != "unconfigured":
            return False
        expires = _parse_datetime(row["onboarding_expires_at"])
        digest = row["onboarding_digest"]
        return bool(digest and expires and now <= expires and secret_matches(offered, digest))

    def reserve_onboarding(self, offered: str, *, maximum_attempts: int = 8) -> bool:
        """Atomically reserve the one-use credential for finalisation."""
        now = _aware(self._clock())
        with self.engine.begin() as connection:
            row = connection.execute(select(bootstrap_state)).mappings().one_or_none()
            if row is None:
                raise BootstrapCorruptError("bootstrap has no installation state")
            expires = _parse_datetime(row["onboarding_expires_at"])
            valid = (
                row["installation_state"] == "unconfigured"
                and int(row["onboarding_attempts"]) < maximum_attempts
                and expires is not None and now <= expires
                and bool(row["onboarding_digest"])
                and secret_matches(offered, str(row["onboarding_digest"]))
            )
            values = {
                "onboarding_attempts": int(row["onboarding_attempts"]) + 1,
                "updated_at": now.isoformat(),
            }
            if valid:
                values["installation_state"] = "completing"
            connection.execute(
                update(bootstrap_state).where(bootstrap_state.c.id == 1).values(**values)
            )
            return valid

    def finish_onboarding(self) -> None:
        now = _aware(self._clock()).isoformat()
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(bootstrap_state)
                .where((bootstrap_state.c.id == 1) & (bootstrap_state.c.installation_state == "completing"))
                .values(
                    installation_state="configured", onboarding_digest=None,
                    onboarding_expires_at=None, updated_at=now,
                )
            )
            if changed.rowcount != 1:
                raise ConfigConflictError("onboarding is not reserved")

    def release_onboarding(self) -> None:
        now = _aware(self._clock()).isoformat()
        with self.engine.begin() as connection:
            connection.execute(
                update(bootstrap_state)
                .where((bootstrap_state.c.id == 1) & (bootstrap_state.c.installation_state == "completing"))
                .values(installation_state="unconfigured", updated_at=now)
            )

    def mark_configured(self) -> None:
        """Complete first-run state after an administrator token was seeded."""
        now = _aware(self._clock()).isoformat()
        with self.engine.begin() as connection:
            connection.execute(
                update(bootstrap_state)
                .where(
                    (bootstrap_state.c.id == 1)
                    & (bootstrap_state.c.installation_state != "configured")
                )
                .values(
                    installation_state="configured",
                    onboarding_digest=None,
                    onboarding_expires_at=None,
                    updated_at=now,
                )
            )

    def compare_and_swap_locator(
        self, expected_revision: int, locator: DatabaseLocator
    ) -> int:
        now = _aware(self._clock()).isoformat()
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(bootstrap_state)
                .where(
                    (bootstrap_state.c.id == 1)
                    & (bootstrap_state.c.locator_revision == expected_revision)
                )
                .values(locator_revision=expected_revision + 1, updated_at=now)
            )
            if changed.rowcount != 1:
                raise ConfigConflictError(
                    "bootstrap locator revision changed; reload before switching drivers"
                )
            connection.execute(
                update(active_locator)
                .where(active_locator.c.id == 1)
                .values(**_locator_values(locator))
            )
        return expected_revision + 1


def inspect_bootstrap(paths: StorePaths) -> dict[str, object]:
    """Read-only diagnostics.  Never creates or migrates the store."""

    if not paths.bootstrap.exists():
        return {"status": "missing", "path": str(paths.bootstrap)}
    try:
        connection = sqlite3.connect(
            f"file:{paths.bootstrap}?mode=ro", uri=True, timeout=1
        )
        connection.row_factory = sqlite3.Row
        try:
            version_rows = connection.execute(
                "SELECT revision FROM bootstrap_schema_version"
            ).fetchall()
            if len(version_rows) != 1:
                raise BootstrapCorruptError("bootstrap revision is ambiguous")
            revision = int(version_rows[0]["revision"])
            if revision > BOOTSTRAP_SCHEMA_REVISION:
                raise BootstrapIncompatibleError(
                    f"bootstrap revision {revision} is newer than supported "
                    f"{BOOTSTRAP_SCHEMA_REVISION}"
                )
            if revision < BOOTSTRAP_SCHEMA_REVISION:
                return {"status": "behind", "schema_revision": revision}
            state = connection.execute(
                "SELECT installation_state, locator_revision FROM bootstrap_state"
            ).fetchone()
            locator = connection.execute(
                "SELECT driver, host, port, database_name, tls FROM active_locator"
            ).fetchone()
            if state is None or locator is None:
                raise BootstrapCorruptError("bootstrap state or locator is missing")
            return {
                "status": "ok",
                "schema_revision": revision,
                "installation_state": state["installation_state"],
                "locator_revision": int(state["locator_revision"]),
                "locator": {
                    "driver": locator["driver"],
                    "host": locator["host"],
                    "port": locator["port"],
                    "database": locator["database_name"],
                    "tls": bool(locator["tls"]),
                },
            }
        finally:
            connection.close()
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        raise BootstrapCorruptError(
            f"bootstrap cannot be inspected safely: {exc.__class__.__name__}"
        ) from exc


def _local_engine(path: Path) -> Engine:
    return build_engine(parse_location(f"sqlite:///{path}"))


def _ensure_state_permissions(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)


def _protect_file(path: Path) -> None:
    if path.exists():
        path.chmod(0o600)


def _locator_values(locator: DatabaseLocator) -> dict[str, object]:
    return {
        "driver": locator.driver.value,
        "host": locator.host,
        "port": locator.port,
        "database_name": locator.database,
        "username": locator.username,
        "password": locator.password,
        "tls": locator.tls,
        "trusted_no_tls": locator.trusted_no_tls,
    }


def _map_locator(row) -> DatabaseLocator:
    driver = DatabaseDriver(str(row["driver"]))
    if driver is DatabaseDriver.SQLITE:
        return DatabaseLocator.sqlite()
    try:
        return DatabaseLocator(
            driver=driver,
            host=row["host"],
            port=row["port"],
            database=row["database_name"],
            username=row["username"],
            password=row["password"],
            tls=bool(row["tls"]),
            trusted_no_tls=bool(row["trusted_no_tls"]),
        )
    except ValueError as exc:
        raise BootstrapCorruptError("bootstrap contains an invalid locator") from exc


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _aware(datetime.fromisoformat(value))
    except ValueError as exc:
        raise BootstrapCorruptError("bootstrap contains an invalid timestamp") from exc


__all__ = [
    "BootstrapInitResult",
    "BootstrapRecord",
    "BootstrapRepository",
    "inspect_bootstrap",
]
