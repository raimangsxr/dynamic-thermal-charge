"""The configuration repository: read, initialise and edit.

Reads never return a partially valid configuration: either a complete
``AppConfig`` comes back or an error is raised (principle III). Edits validate
the whole resulting configuration inside the transaction, so an edit that would
leave the installation invalid changes nothing at all (FR-034), and use
optimistic locking on ``installation.revision`` so two concurrent edits cannot
silently lose one another (FR-040, research.md D9).
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import delete, insert, inspect, select, update
from sqlalchemy.engine import Connection, Engine

from ..config import validate_config
from ..models import AppConfig, Heater, IndoorReading, OutputConfig, ThermalProfile
from . import (
    ConfigChange,
    ConfigConflictError,
    ConfigStoreEmptyError,
    ConfigValidationError,
    SecretRejectedError,
)
from .engine import store_errors, transaction
from .mapping import (
    config_from_rows,
    format_time,
    format_weekdays,
    heater_params,
    installation_params,
    output_params,
    parse_time,
    parse_weekdays,
    thermal_params,
    from_utc,
    to_utc,
    weather_params,
)
from .schema import (
    config_change,
    heater as heater_table,
    indoor_reading as indoor_reading_table,
    installation as installation_table,
    output_config as output_table,
    thermal_profile as thermal_table,
    weather_config as weather_table,
)
from .url import StoreLocation


logger = logging.getLogger(__name__)

# Values that look like a credential or a connection string are refused in any
# configuration field: secrets are served through the environment (FR-038).
_SECRET_PATTERNS = (
    re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE),
    re.compile(r"\bpassword\s*=", re.IGNORECASE),
    re.compile(r"^[^\s:@/]+:[^\s:@/]+@[^\s/]+"),
)


def _reject_secrets(field: str, value: str, heater_id: str | None = None) -> None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise SecretRejectedError(
                f"the value offered for {field} looks like a credential or a "
                "connection string. Secrets are never stored in the configuration: "
                "serve them through an environment variable named in the "
                "configuration instead",
                field=field,
                heater_id=heater_id,
            )


# --------------------------------------------------------------------------- #
# Editable fields. Explicit so an unknown name can be reported with the list of
# admissible ones (FR-037) instead of silently doing nothing.
# --------------------------------------------------------------------------- #

def _parse_bool(raw: str, field: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("true", "yes", "on", "1"):
        return True
    if lowered in ("false", "no", "off", "0"):
        return False
    raise ConfigValidationError(
        f"{field} must be a boolean (true/false); received {raw!r}", field=field
    )


def _parse_int(raw: str, field: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigValidationError(
            f"{field} must be a whole number; received {raw!r}", field=field
        ) from exc


def _parse_float(raw: str, field: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigValidationError(
            f"{field} must be a number; received {raw!r}", field=field
        ) from exc


def _parse_optional_int(raw: str, field: str) -> int | None:
    if raw.strip().lower() in ("none", "null", "unlimited", ""):
        return None
    return _parse_int(raw, field)


def _parse_optional_str(raw: str, _field: str) -> str | None:
    normalized = raw.strip()
    return normalized or None


def _power_kw_to_w(raw: str, field: str) -> int:
    return round(_parse_float(raw, field) * 1000)


def _hours_to_minutes(raw: str, field: str) -> int:
    return round(_parse_float(raw, field) * 60)


#: field name -> (table, column, parser)
INSTALLATION_FIELDS: dict[str, tuple[str, Callable[[str, str], Any]]] = {
    "name": ("name", lambda raw, field: raw),
    "max_total_power_kw": ("max_total_power_w", _power_kw_to_w),
    "max_total_power_w": ("max_total_power_w", _parse_int),
    "slot_minutes": ("slot_minutes", _parse_int),
    "window_minutes": ("window_minutes", _parse_int),
    "window_hours": ("window_minutes", _hours_to_minutes),
    "timezone": ("timezone", lambda raw, field: raw),
    "start_time": ("start_time", lambda raw, field: format_time(parse_time(raw, field))),
    "end_time": ("end_time", lambda raw, field: format_time(parse_time(raw, field))),
    "weekdays": ("weekdays", lambda raw, field: format_weekdays(parse_weekdays(raw, field))),
    "log_level": ("log_level", lambda raw, field: raw.upper()),
    "state_file": ("state_file", lambda raw, field: raw),
    "poll_seconds": ("poll_seconds", _parse_float),
    "retention_days": ("retention_days", _parse_optional_int),
    "indoor_max_age_minutes": ("indoor_max_age_minutes", _parse_int),
    "indoor_min_plausible_c": ("indoor_min_plausible_c", _parse_float),
    "indoor_max_plausible_c": ("indoor_max_plausible_c", _parse_float),
}

HEATER_FIELDS: dict[str, tuple[str, str, Callable[[str, str], Any]]] = {
    "name": ("heater", "name", lambda raw, field: raw),
    "model": ("heater", "model", lambda raw, field: raw),
    "power_kw": ("heater", "power_w", _power_kw_to_w),
    "power_w": ("heater", "power_w", _parse_int),
    "full_charge_hours": ("heater", "full_charge_minutes", _hours_to_minutes),
    "full_charge_minutes": ("heater", "full_charge_minutes", _parse_int),
    "target_charge": ("heater", "target_charge", _parse_float),
    "priority": ("heater", "priority", _parse_int),
    "enabled": ("heater", "enabled", _parse_bool),
    "indoor_topic": ("heater", "indoor_topic", _parse_optional_str),
    "output_type": ("output", "kind", lambda raw, field: raw),
    "pin": ("output", "pin", _parse_optional_int),
    "active_high": ("output", "active_high", _parse_bool),
    "target_temperature_c": ("thermal", "target_temperature_c", _parse_float),
    "design_outdoor_temperature_c": (
        "thermal",
        "design_outdoor_temperature_c",
        _parse_float,
    ),
    "thermal_factor": ("thermal", "thermal_factor", _parse_float),
    "min_charge": ("thermal", "min_charge", _parse_float),
    "max_charge": ("thermal", "max_charge", _parse_float),
}

WEATHER_FIELDS: dict[str, tuple[str, Callable[[str, str], Any]]] = {
    "provider": ("provider", lambda raw, field: raw),
    "municipality_code": ("aemet_municipality_code", lambda raw, field: raw),
    "api_key_env": ("aemet_api_key_env", lambda raw, field: raw),
    "timeout_seconds": ("aemet_timeout_seconds", _parse_float),
    "simulated_average_temperature_c": ("simulated_average_temperature_c", _parse_float),
    "simulated_minimum_temperature_c": ("simulated_minimum_temperature_c", _parse_float),
    "fallback_average_temperature_c": ("fallback_average_temperature_c", _parse_float),
    "fallback_minimum_temperature_c": ("fallback_minimum_temperature_c", _parse_float),
    "retry_minutes": ("watchdog_retry_minutes", _parse_int),
    "refresh_minutes": ("watchdog_refresh_minutes", _parse_int),
}


class SqlConfigRepository:
    def __init__(
        self,
        engine: Engine,
        location: StoreLocation | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._location = location
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ----------------------------------------------------------------- read

    def current(self) -> tuple[AppConfig, int]:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                return self._read(connection)

    def _read(self, connection: Connection) -> tuple[AppConfig, int]:
        installation_row = connection.execute(
            self._select_present(connection, installation_table)
            .order_by(installation_table.c.id)
            .limit(1)
        ).mappings().first()
        if installation_row is None:
            raise ConfigStoreEmptyError(
                "the configuration database holds no installation; run "
                "'dtc db init' to seed the example installation"
            )
        installation_id = installation_row["id"]
        weather_row = connection.execute(
            select(weather_table).where(
                weather_table.c.installation_id == installation_id
            )
        ).mappings().first()
        heater_rows = connection.execute(
            self._select_present(connection, heater_table)
            .where(heater_table.c.installation_id == installation_id)
            .order_by(heater_table.c.position)
        ).mappings().all()

        combined = []
        for heater_row in heater_rows:
            output_row = connection.execute(
                select(output_table).where(output_table.c.heater_id == heater_row["id"])
            ).mappings().first()
            thermal_row = connection.execute(
                select(thermal_table).where(
                    thermal_table.c.heater_id == heater_row["id"]
                )
            ).mappings().first()
            combined.append((heater_row, output_row, thermal_row))

        config = config_from_rows(installation_row, weather_row, combined)
        return config, int(installation_row["revision"])

    def installation_id(self) -> int:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                row = connection.execute(
                    select(installation_table.c.id)
                    .order_by(installation_table.c.id)
                    .limit(1)
                ).first()
        if row is None:
            raise ConfigStoreEmptyError("the configuration database holds no installation")
        return int(row[0])

    def installation_name(self) -> str:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                name = connection.execute(
                    select(installation_table.c.name)
                    .order_by(installation_table.c.id)
                    .limit(1)
                ).scalar()
        if name is None:
            raise ConfigStoreEmptyError("the configuration database holds no installation")
        return str(name)

    # --------------------------------------------------------------- create

    def is_empty(self) -> bool:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                return (
                    connection.execute(
                        select(installation_table.c.id).limit(1)
                    ).first()
                    is None
                )

    def seed(self, config: AppConfig, name: str) -> bool:
        """Write an installation only if none exists. Returns True if it wrote."""
        validate_config(config)
        now = self._clock()
        with transaction(self._engine, self._location) as connection:
            if connection.execute(select(installation_table.c.id).limit(1)).first():
                logger.info("Configuration already present; seeding skipped")
                return False
            installation_id = connection.execute(
                insert(installation_table).values(
                    **self._compatible_params(
                        connection,
                        installation_table.name,
                        installation_params(config, name, now),
                    )
                )
            ).inserted_primary_key[0]
            if config.weather is not None:
                connection.execute(
                    insert(weather_table).values(
                        **weather_params(config.weather, installation_id)
                    )
                )
            for position, heater in enumerate(config.heaters):
                self._insert_heater(connection, installation_id, heater, position)
        logger.info(
            "Seeded installation %r with %d heaters", name, len(config.heaters)
        )
        return True

    def _insert_heater(
        self,
        connection: Connection,
        installation_id: int,
        heater: Heater,
        position: int,
    ) -> None:
        heater_key = connection.execute(
            insert(heater_table).values(
                **self._compatible_params(
                    connection,
                    heater_table.name,
                    heater_params(heater, installation_id, position),
                )
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(output_table).values(**output_params(heater, heater_key))
        )
        if heater.thermal is not None:
            connection.execute(
                insert(thermal_table).values(
                    **thermal_params(heater.thermal, heater_key)
                )
            )

    @staticmethod
    def _compatible_params(
        connection: Connection, table_name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Allow migration tests to seed an older pinned schema safely."""
        present = {
            column["name"] for column in inspect(connection).get_columns(table_name)
        }
        return {name: value for name, value in params.items() if name in present}

    @staticmethod
    def _select_present(connection: Connection, table):  # noqa: ANN001
        """Select a pinned older schema without asking it for future columns."""
        present = {
            column["name"] for column in inspect(connection).get_columns(table.name)
        }
        return select(*(column for column in table.c if column.name in present))

    # ----------------------------------------------------------------- edit

    def set_field(
        self,
        revision: int,
        entity: str,
        entity_key: str | None,
        field: str,
        value: str,
    ) -> ConfigChange:
        _reject_secrets(field, value, entity_key)
        with transaction(self._engine, self._location) as connection:
            _, current_revision = self._read(connection)
            self._require_revision(current_revision, revision)
            installation_id = self._locked_installation_id(connection)

            if entity == "installation":
                old, new = self._update_installation(
                    connection, installation_id, field, value
                )
            elif entity == "weather":
                old, new = self._update_weather(connection, installation_id, field, value)
            elif entity == "heater":
                if entity_key is None:
                    raise ConfigValidationError(
                        "editing a heater field requires a heater id", field=field
                    )
                old, new = self._update_heater(
                    connection, installation_id, entity_key, field, value
                )
            else:
                raise ConfigValidationError(
                    f"unknown entity {entity!r}; admissible entities: installation, "
                    "weather, heater",
                    field=field,
                )

            change = ConfigChange(
                entity=entity,
                entity_key=entity_key,
                field=field,
                # Both sides in the stored unit, so the audit trail never reads
                # "5200 -> 6.0" for the same quantity.
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
                action="set",
                revision_before=revision,
                revision_after=revision + 1,
            )
            self._commit_revision(connection, installation_id, revision, change)
            # Validating after the write, inside the transaction, is what makes
            # "reject completely, never partially" true: an invalid result raises
            # and the transaction never commits.
            self._read(connection)
        logger.info(
            "Configuration %s.%s changed from %s to %s (revision %d -> %d)",
            entity if entity_key is None else f"{entity}[{entity_key}]",
            field,
            change.old_value,
            change.new_value,
            change.revision_before,
            change.revision_after,
        )
        return change

    def add_heater(self, revision: int, heater: Heater) -> ConfigChange:
        with transaction(self._engine, self._location) as connection:
            config, current_revision = self._read(connection)
            self._require_revision(current_revision, revision)
            if any(existing.id == heater.id for existing in config.heaters):
                raise ConfigValidationError(
                    f"heater {heater.id!r} already exists",
                    field="heater_id",
                    heater_id=heater.id,
                )
            installation_id = self._locked_installation_id(connection)
            position = connection.execute(
                select(heater_table.c.position)
                .where(heater_table.c.installation_id == installation_id)
                .order_by(heater_table.c.position.desc())
                .limit(1)
            ).scalar()
            self._insert_heater(
                connection,
                installation_id,
                heater,
                0 if position is None else int(position) + 1,
            )
            change = ConfigChange(
                entity="heater",
                entity_key=heater.id,
                field=None,
                old_value=None,
                new_value=heater.id,
                action="add",
                revision_before=revision,
                revision_after=revision + 1,
            )
            self._commit_revision(connection, installation_id, revision, change)
            self._read(connection)
        logger.info("Added heater %s", heater.id)
        return change

    def remove_heater(self, revision: int, heater_id: str) -> ConfigChange:
        with transaction(self._engine, self._location) as connection:
            _, current_revision = self._read(connection)
            self._require_revision(current_revision, revision)
            installation_id = self._locked_installation_id(connection)
            heater_key = connection.execute(
                select(heater_table.c.id).where(
                    (heater_table.c.installation_id == installation_id)
                    & (heater_table.c.heater_id == heater_id)
                )
            ).scalar()
            if heater_key is None:
                raise ConfigValidationError(
                    f"heater {heater_id!r} does not exist; existing heaters: "
                    f"{', '.join(self._heater_ids(connection, installation_id)) or 'none'}",
                    field="heater_id",
                )
            # Output and thermal profile follow through ON DELETE CASCADE. History
            # does not: plan_slot.heater_id is text, not a foreign key.
            connection.execute(delete(heater_table).where(heater_table.c.id == heater_key))
            change = ConfigChange(
                entity="heater",
                entity_key=heater_id,
                field=None,
                old_value=heater_id,
                new_value=None,
                action="remove",
                revision_before=revision,
                revision_after=revision + 1,
            )
            self._commit_revision(connection, installation_id, revision, change)
            self._read(connection)
        logger.info("Removed heater %s; its history is retained", heater_id)
        return change

    # ------------------------------------------------------------- internals

    def _require_revision(self, current: int, expected: int) -> None:
        if current != expected:
            raise ConfigConflictError(
                f"the configuration changed while the edit was being prepared: it is "
                f"now at revision {current}, the edit was based on {expected}. Re-read "
                "the configuration and try again"
            )

    def _locked_installation_id(self, connection: Connection) -> int:
        row = connection.execute(
            select(installation_table.c.id).order_by(installation_table.c.id).limit(1)
        ).first()
        if row is None:
            raise ConfigStoreEmptyError("the configuration database holds no installation")
        return int(row[0])

    def _commit_revision(
        self,
        connection: Connection,
        installation_id: int,
        revision: int,
        change: ConfigChange,
    ) -> None:
        now = to_utc(self._clock())
        # The WHERE clause on revision is the optimistic lock: zero affected rows
        # means someone else committed first.
        result = connection.execute(
            update(installation_table)
            .where(
                (installation_table.c.id == installation_id)
                & (installation_table.c.revision == revision)
            )
            .values(revision=revision + 1, updated_at=now)
        )
        if result.rowcount != 1:
            raise ConfigConflictError(
                "another process committed a configuration change first; "
                "re-read the configuration and try again"
            )
        connection.execute(
            insert(config_change).values(
                installation_id=installation_id,
                revision_before=change.revision_before,
                revision_after=change.revision_after,
                entity=change.entity,
                entity_key=change.entity_key,
                field=change.field,
                old_value=change.old_value,
                new_value=change.new_value,
                action=change.action,
                occurred_at=now,
            )
        )

    def _heater_ids(self, connection: Connection, installation_id: int) -> list[str]:
        return [
            str(row[0])
            for row in connection.execute(
                select(heater_table.c.heater_id)
                .where(heater_table.c.installation_id == installation_id)
                .order_by(heater_table.c.position)
            )
        ]

    def _update_installation(
        self, connection: Connection, installation_id: int, field: str, value: str
    ) -> tuple[Any, Any]:
        if field not in INSTALLATION_FIELDS:
            raise ConfigValidationError(
                f"unknown installation field {field!r}; admissible fields: "
                f"{', '.join(sorted(INSTALLATION_FIELDS))}",
                field=field,
            )
        column, parser = INSTALLATION_FIELDS[field]
        parsed = parser(value, field)
        old = connection.execute(
            select(installation_table.c[column]).where(
                installation_table.c.id == installation_id
            )
        ).scalar()
        connection.execute(
            update(installation_table)
            .where(installation_table.c.id == installation_id)
            .values(**{column: parsed})
        )
        return old, parsed


    def _update_weather(
        self, connection: Connection, installation_id: int, field: str, value: str
    ) -> tuple[Any, Any]:
        if field not in WEATHER_FIELDS:
            raise ConfigValidationError(
                f"unknown weather field {field!r}; admissible fields: "
                f"{', '.join(sorted(WEATHER_FIELDS))}",
                field=field,
            )
        column, parser = WEATHER_FIELDS[field]
        parsed = parser(value, field)
        row = connection.execute(
            select(weather_table.c.id, weather_table.c[column]).where(
                weather_table.c.installation_id == installation_id
            )
        ).first()
        if row is None:
            raise ConfigValidationError(
                "this installation has no weather configuration to edit", field=field
            )
        connection.execute(
            update(weather_table)
            .where(weather_table.c.id == row[0])
            .values(**{column: parsed})
        )
        return row[1], parsed

    def _update_heater(
        self,
        connection: Connection,
        installation_id: int,
        heater_id: str,
        field: str,
        value: str,
    ) -> tuple[Any, Any]:
        if field not in HEATER_FIELDS:
            raise ConfigValidationError(
                f"unknown heater field {field!r}; admissible fields: "
                f"{', '.join(sorted(HEATER_FIELDS))}",
                field=field,
                heater_id=heater_id,
            )
        heater_key = connection.execute(
            select(heater_table.c.id).where(
                (heater_table.c.installation_id == installation_id)
                & (heater_table.c.heater_id == heater_id)
            )
        ).scalar()
        if heater_key is None:
            raise ConfigValidationError(
                f"heater {heater_id!r} does not exist; existing heaters: "
                f"{', '.join(self._heater_ids(connection, installation_id)) or 'none'}",
                field=field,
            )
        table_name, column, parser = HEATER_FIELDS[field]
        parsed = parser(value, field)
        table = {
            "heater": heater_table,
            "output": output_table,
            "thermal": thermal_table,
        }[table_name]
        key_column = table.c.id if table_name == "heater" else table.c.heater_id
        key_value = heater_key
        row = connection.execute(
            select(table.c[column]).where(key_column == key_value)
        ).first()
        if row is None:
            raise ConfigValidationError(
                f"heater {heater_id!r} has no {table_name} settings to edit; add them "
                "by recreating the heater with the required options",
                field=field,
                heater_id=heater_id,
            )
        connection.execute(
            update(table).where(key_column == key_value).values(**{column: parsed})
        )
        return row[0], parsed


class SqlIndoorReadingRepository:
    """Persist only the latest accepted indoor reading for each heater."""

    def __init__(
        self,
        engine: Engine,
        location: StoreLocation | None = None,
    ) -> None:
        self._engine = engine
        self._location = location

    def upsert(self, reading: IndoorReading) -> None:
        with transaction(self._engine, self._location) as connection:
            heater_pk = self._heater_pk(connection, reading.heater_id)
            # Delete + insert is portable across SQLite and PostgreSQL and remains
            # one atomic replacement because both statements share a transaction.
            connection.execute(
                delete(indoor_reading_table).where(
                    indoor_reading_table.c.heater_pk == heater_pk
                )
            )
            connection.execute(
                insert(indoor_reading_table).values(
                    heater_pk=heater_pk,
                    celsius=reading.celsius,
                    received_at=to_utc(reading.received_at),
                )
            )

    def invalidate(self, heater_id: str) -> None:
        with transaction(self._engine, self._location) as connection:
            heater_pk = self._heater_pk(connection, heater_id)
            connection.execute(
                delete(indoor_reading_table).where(
                    indoor_reading_table.c.heater_pk == heater_pk
                )
            )

    def read_all(self) -> dict[str, IndoorReading]:
        with store_errors(self._location):
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(
                        heater_table.c.heater_id,
                        indoor_reading_table.c.celsius,
                        indoor_reading_table.c.received_at,
                    ).select_from(
                        indoor_reading_table.join(
                            heater_table,
                            indoor_reading_table.c.heater_pk == heater_table.c.id,
                        )
                    )
                ).all()
        readings: dict[str, IndoorReading] = {}
        for heater_id, celsius, received_at in rows:
            aware_received_at = from_utc(received_at)
            if aware_received_at is None:  # guarded by the NOT NULL schema
                raise ConfigValidationError(
                    "an indoor reading has no received_at timestamp",
                    field="received_at",
                    heater_id=str(heater_id),
                )
            reading = IndoorReading(
                heater_id=str(heater_id),
                celsius=float(celsius),
                received_at=aware_received_at,
            )
            readings[reading.heater_id] = reading
        return readings

    @staticmethod
    def _heater_pk(connection: Connection, heater_id: str) -> int:
        heater_pk = connection.execute(
            select(heater_table.c.id).where(heater_table.c.heater_id == heater_id)
        ).scalar()
        if heater_pk is None:
            raise ConfigValidationError(
                f"heater {heater_id!r} does not exist",
                field="heater_id",
                heater_id=heater_id,
            )
        return int(heater_pk)


__all__ = [
    "HEATER_FIELDS",
    "INSTALLATION_FIELDS",
    "WEATHER_FIELDS",
    "SqlConfigRepository",
    "SqlIndoorReadingRepository",
]
