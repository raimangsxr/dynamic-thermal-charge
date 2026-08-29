"""Atomic repository for typed, database-resident system configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Callable, Mapping

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from ..system_settings import (
    ACTIVATION_POLICIES,
    PUBLIC_SECTION_FIELDS,
    SECTION_TYPES,
    SYSTEM_CONFIGURATION_FORMAT_VERSION,
    SystemConfiguration,
)
from . import ConfigConflictError, ConfigStoreEmptyError, ConfigValidationError
from .engine import store_errors, transaction
from .mapping import from_utc, to_utc
from .schema import system_audit_event, system_configuration, system_secret
from .url import StoreLocation


Clock = Callable[[], datetime]


class SecretAction(Enum):
    KEEP = "keep"
    REPLACE = "replace"
    CLEAR = "clear"


@dataclass(frozen=True)
class SecretMutation:
    action: SecretAction
    value: str | None = None

    def __post_init__(self) -> None:
        if self.action is SecretAction.REPLACE and not self.value:
            raise ValueError("replacing a secret requires a non-empty value")
        if self.action is not SecretAction.REPLACE and self.value is not None:
            raise ValueError("keep/clear secret mutations cannot carry a value")


@dataclass(frozen=True)
class StoredSecret:
    value: str
    kind: str
    rotated_at: datetime


@dataclass(frozen=True)
class SystemConfigurationSnapshot:
    configuration: SystemConfiguration
    revision: int
    secrets: dict[str, StoredSecret]


SECRET_KINDS = {
    "admin_token_digest": "digest",
    "postgres_username": "recoverable",
    "postgres_password": "recoverable",
    "mqtt_username": "recoverable",
    "mqtt_password": "recoverable",
    "aemet_api_key": "recoverable",
}


class SystemConfigurationRepository:
    def __init__(
        self,
        engine: Engine,
        location: StoreLocation | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._engine = engine
        self._location = location
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def initialise(
        self,
        configuration: SystemConfiguration | None = None,
        *,
        secrets: Mapping[str, str] | None = None,
        actor: str = "system",
    ) -> bool:
        candidate = configuration or SystemConfiguration()
        supplied = dict(secrets or {})
        self._validate_secret_names(supplied)
        self._validate_secret_requirements(candidate, supplied, allow_incomplete=True)
        now = to_utc(self._clock())
        documents = candidate.documents()
        with transaction(self._engine, self._location) as connection:
            if connection.execute(select(system_configuration.c.id)).first():
                return False
            connection.execute(
                insert(system_configuration).values(
                    id=1,
                    revision=1,
                    format_version=SYSTEM_CONFIGURATION_FORMAT_VERSION,
                    **_document_values(documents),
                    created_at=now,
                    updated_at=now,
                )
            )
            for name, value in supplied.items():
                connection.execute(
                    insert(system_secret).values(
                        name=name,
                        value=value,
                        kind=SECRET_KINDS[name],
                        rotated_at=now,
                    )
                )
            self._audit(
                connection,
                actor=actor,
                action="initialise",
                section="system",
                fields=tuple(documents),
                before=None,
                after=1,
                result="succeeded",
                now=now,
            )
        return True

    def current(self) -> SystemConfigurationSnapshot:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                return self._read(connection)

    def public_snapshot(self) -> dict[str, object]:
        snapshot = self.current()
        documents = snapshot.configuration.documents()
        return {
            "revision": snapshot.revision,
            "format_version": SYSTEM_CONFIGURATION_FORMAT_VERSION,
            "sections": documents,
            "secrets": {
                name: {
                    "configured": name in snapshot.secrets,
                    "rotated_at": (
                        snapshot.secrets[name].rotated_at.isoformat()
                        if name in snapshot.secrets
                        else None
                    ),
                }
                for name in SECRET_KINDS
            },
            "activation": {
                path: policy.value for path, policy in ACTIVATION_POLICIES.items()
            },
        }

    def update_section(
        self,
        section: str,
        patch: Mapping[str, object],
        *,
        expected_revision: int,
        secret_mutations: Mapping[str, SecretMutation] | None = None,
        actor: str,
    ) -> int:
        if section not in SECTION_TYPES:
            raise ConfigValidationError(
                f"unknown system configuration section {section!r}; allowed: "
                f"{', '.join(sorted(SECTION_TYPES))}",
                field="section",
            )
        unknown = set(patch) - PUBLIC_SECTION_FIELDS[section]
        if unknown:
            raise ConfigValidationError(
                f"unknown fields in {section}: {', '.join(sorted(unknown))}",
                field=sorted(unknown)[0],
            )
        mutations = dict(secret_mutations or {})
        self._validate_secret_names(mutations)
        now = to_utc(self._clock())
        changed_fields = tuple(
            sorted([f"{section}.{name}" for name in patch] + list(mutations))
        )
        try:
            with transaction(self._engine, self._location) as connection:
                snapshot = self._read(connection)
                if snapshot.revision != expected_revision:
                    raise ConfigConflictError(
                        f"system configuration is now at revision {snapshot.revision}; "
                        f"the edit was based on {expected_revision}"
                    )
                documents = snapshot.configuration.documents()
                documents[section] = {**documents[section], **dict(patch)}
                try:
                    candidate = SystemConfiguration.from_documents(documents)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ConfigValidationError(str(exc), field=section) from exc
                candidate_secrets = {
                    name: stored.value for name, stored in snapshot.secrets.items()
                }
                self._apply_secret_mutations(
                    connection, candidate_secrets, mutations, now
                )
                self._validate_secret_requirements(candidate, candidate_secrets)
                result = connection.execute(
                    update(system_configuration)
                    .where(
                        (system_configuration.c.id == 1)
                        & (system_configuration.c.revision == expected_revision)
                    )
                    .values(
                        revision=expected_revision + 1,
                        **_document_values(candidate.documents()),
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    raise ConfigConflictError(
                        "another process committed the system configuration first"
                    )
                self._audit(
                    connection,
                    actor=actor,
                    action="update",
                    section=section,
                    fields=changed_fields,
                    before=expected_revision,
                    after=expected_revision + 1,
                    result="succeeded",
                    now=now,
                )
            return expected_revision + 1
        except Exception:
            self._audit_failure(
                actor=actor,
                section=section,
                fields=changed_fields,
                revision=expected_revision,
                now=now,
            )
            raise

    def audit_events(self) -> list[dict[str, object]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(system_audit_event).order_by(system_audit_event.c.id)
            ).mappings().all()
        return [
            {
                "actor": row["actor"],
                "action": row["action"],
                "section": row["section"],
                "fields": json.loads(row["fields"]),
                "revision_before": row["revision_before"],
                "revision_after": row["revision_after"],
                "result": row["result"],
                "occurred_at": from_utc(row["occurred_at"]),
            }
            for row in rows
        ]

    def record_audit(
        self,
        *,
        actor: str,
        action: str,
        section: str,
        fields: tuple[str, ...] = (),
        revision_before: int | None = None,
        revision_after: int | None = None,
        result: str = "succeeded",
    ) -> None:
        """Record a non-mutating operation without ever persisting its values."""
        now = to_utc(self._clock())
        with self._engine.begin() as connection:
            self._audit(
                connection,
                actor=actor,
                action=action,
                section=section,
                fields=fields,
                before=revision_before,
                after=revision_after,
                result=result,
                now=now,
            )

    def _read(self, connection) -> SystemConfigurationSnapshot:
        row = connection.execute(select(system_configuration)).mappings().one_or_none()
        if row is None:
            raise ConfigStoreEmptyError("system configuration has not been initialized")
        if int(row["format_version"]) != SYSTEM_CONFIGURATION_FORMAT_VERSION:
            raise ConfigValidationError(
                f"unsupported system configuration format {row['format_version']}"
            )
        try:
            documents = {
                section: json.loads(row[f"{section}_json"])
                for section in SECTION_TYPES
            }
            configuration = SystemConfiguration.from_documents(documents)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConfigValidationError(
                "stored system configuration is invalid"
            ) from exc
        secrets = {
            str(secret_row["name"]): StoredSecret(
                value=str(secret_row["value"]),
                kind=str(secret_row["kind"]),
                rotated_at=from_utc(secret_row["rotated_at"]),
            )
            for secret_row in connection.execute(select(system_secret)).mappings()
        }
        return SystemConfigurationSnapshot(
            configuration=configuration,
            revision=int(row["revision"]),
            secrets=secrets,
        )

    @staticmethod
    def _validate_secret_names(values: Mapping[str, object]) -> None:
        unknown = set(values) - SECRET_KINDS.keys()
        if unknown:
            raise ConfigValidationError(
                f"unknown secret fields: {', '.join(sorted(unknown))}",
                field=sorted(unknown)[0],
            )

    @staticmethod
    def _validate_secret_requirements(
        configuration: SystemConfiguration,
        secrets: Mapping[str, str],
        *,
        allow_incomplete: bool = False,
    ) -> None:
        if allow_incomplete:
            return
        missing: list[str] = []
        if configuration.database.driver == "postgresql":
            missing.extend(
                name
                for name in ("postgres_username", "postgres_password")
                if not secrets.get(name)
            )
        mqtt_user = bool(secrets.get("mqtt_username"))
        mqtt_password = bool(secrets.get("mqtt_password"))
        if mqtt_user != mqtt_password:
            missing.append("mqtt_username/mqtt_password pair")
        if configuration.weather.provider == "aemet" and not secrets.get(
            "aemet_api_key"
        ):
            missing.append("aemet_api_key")
        if missing:
            raise ConfigValidationError(
                f"required secrets are missing: {', '.join(missing)}",
                field=missing[0],
            )

    @staticmethod
    def _apply_secret_mutations(
        connection,
        values: dict[str, str],
        mutations: Mapping[str, SecretMutation],
        now: datetime,
    ) -> None:
        for name, mutation in mutations.items():
            if mutation.action is SecretAction.KEEP:
                continue
            connection.execute(delete(system_secret).where(system_secret.c.name == name))
            if mutation.action is SecretAction.CLEAR:
                values.pop(name, None)
                continue
            value = mutation.value or ""
            connection.execute(
                insert(system_secret).values(
                    name=name,
                    value=value,
                    kind=SECRET_KINDS[name],
                    rotated_at=now,
                )
            )
            values[name] = value

    @staticmethod
    def _audit(
        connection,
        *,
        actor: str,
        action: str,
        section: str,
        fields: tuple[str, ...],
        before: int | None,
        after: int | None,
        result: str,
        now: datetime,
    ) -> None:
        connection.execute(
            insert(system_audit_event).values(
                actor=actor[:160],
                action=action,
                section=section,
                fields=json.dumps(sorted(fields), separators=(",", ":")),
                revision_before=before,
                revision_after=after,
                result=result,
                occurred_at=now,
            )
        )

    def _audit_failure(
        self,
        *,
        actor: str,
        section: str,
        fields: tuple[str, ...],
        revision: int,
        now: datetime,
    ) -> None:
        try:
            with self._engine.begin() as connection:
                self._audit(
                    connection,
                    actor=actor,
                    action="update",
                    section=section,
                    fields=fields,
                    before=revision,
                    after=None,
                    result="rejected",
                    now=now,
                )
        except Exception:
            return


def _document_values(documents: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    return {
        f"{section}_json": json.dumps(
            documents[section], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        for section in SECTION_TYPES
    }


__all__ = [
    "SECRET_KINDS",
    "SecretAction",
    "SecretMutation",
    "StoredSecret",
    "SystemConfigurationRepository",
    "SystemConfigurationSnapshot",
]
