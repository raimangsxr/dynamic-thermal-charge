"""Exact conversion of the legacy AEMET refresh cadence.

The legacy schema stored the automatic cadence in minutes.  This module is
intentionally small and strict because it is used by both the active-schema
upgrade and the compatibility importer: neither path may silently round or
choose a value when the two persisted representations disagree.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_REFRESH_HOURS = 4
LEGACY_REFRESH_COLUMN = "watchdog_refresh_minutes"
CANONICAL_REFRESH_COLUMN = "watchdog_refresh_hours"
LEGACY_REFRESH_FIELD = "refresh_minutes"
CANONICAL_REFRESH_FIELD = "refresh_hours"


def _strict_positive_integer(value: object, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{source} must be a positive integer")
    return value


def refresh_hours_from_minutes(value: object, source: str = LEGACY_REFRESH_FIELD) -> int:
    """Convert legacy minutes only when the conversion is exact."""
    minutes = _strict_positive_integer(value, source)
    if minutes % 60:
        raise ValueError(f"{source} must be divisible by 60; got {minutes}")
    return _strict_positive_integer(minutes // 60, CANONICAL_REFRESH_FIELD)


def canonical_refresh_hours(value: object, source: str = CANONICAL_REFRESH_FIELD) -> int:
    return _strict_positive_integer(value, source)


def canonical_weather_document(
    document: Mapping[str, Any],
    *,
    fallback_hours: int | None = None,
) -> dict[str, Any]:
    """Return one weather document with only the canonical refresh field."""
    result = dict(document)
    has_canonical = CANONICAL_REFRESH_FIELD in result
    has_legacy = LEGACY_REFRESH_FIELD in result
    converted_legacy = (
        refresh_hours_from_minutes(result[LEGACY_REFRESH_FIELD])
        if has_legacy
        else None
    )
    canonical = (
        canonical_refresh_hours(result[CANONICAL_REFRESH_FIELD])
        if has_canonical
        else None
    )
    if canonical is not None and converted_legacy is not None and canonical != converted_legacy:
        raise ValueError(
            "refresh_hours conflicts with refresh_minutes in the persisted weather document"
        )
    if canonical is None:
        canonical = converted_legacy
    if canonical is None:
        canonical = (
            DEFAULT_REFRESH_HOURS
            if fallback_hours is None
            else canonical_refresh_hours(fallback_hours, "fallback refresh_hours")
        )
    result[CANONICAL_REFRESH_FIELD] = canonical
    result.pop(LEGACY_REFRESH_FIELD, None)
    return result


def canonical_weather_row(
    row: Mapping[str, Any],
    *,
    fallback_hours: int = DEFAULT_REFRESH_HOURS,
) -> dict[str, Any]:
    """Convert one legacy ``weather_config`` row for an importer target."""
    result = dict(row)
    has_canonical = CANONICAL_REFRESH_COLUMN in result
    has_legacy = LEGACY_REFRESH_COLUMN in result
    converted_legacy = (
        refresh_hours_from_minutes(result[LEGACY_REFRESH_COLUMN], LEGACY_REFRESH_COLUMN)
        if has_legacy
        else None
    )
    canonical = (
        canonical_refresh_hours(result[CANONICAL_REFRESH_COLUMN], CANONICAL_REFRESH_COLUMN)
        if has_canonical
        else None
    )
    if canonical is not None and converted_legacy is not None and canonical != converted_legacy:
        raise ValueError(
            "watchdog_refresh_hours conflicts with watchdog_refresh_minutes in the persisted weather row"
        )
    if canonical is None:
        canonical = converted_legacy
    if canonical is None:
        canonical = canonical_refresh_hours(fallback_hours, "fallback refresh_hours")
    result[CANONICAL_REFRESH_COLUMN] = canonical
    result.pop(LEGACY_REFRESH_COLUMN, None)
    return result


def migrate_refresh_configuration(connection: Connection) -> None:
    """Migrate table and document values on the caller's transaction.

    All source values are read and validated before the first schema or data
    mutation.  A raised ``ValueError`` therefore leaves both representations
    unchanged when the caller is in a transaction.
    """
    inspector = inspect(connection)
    table_values: list[int] = []
    table_records: list[tuple[int, int]] = []
    weather_columns: set[str] = set()
    if inspector.has_table("weather_config"):
        weather_columns = {
            column["name"] for column in inspector.get_columns("weather_config")
        }
        if CANONICAL_REFRESH_COLUMN not in weather_columns and LEGACY_REFRESH_COLUMN not in weather_columns:
            # A table without either field is an incomplete legacy schema.  It
            # is safe to add the canonical default after validation because no
            # source value exists to convert.
            table_values = []
        else:
            selected = ["id"]
            if CANONICAL_REFRESH_COLUMN in weather_columns:
                selected.append(CANONICAL_REFRESH_COLUMN)
            if LEGACY_REFRESH_COLUMN in weather_columns:
                selected.append(LEGACY_REFRESH_COLUMN)
            query = text(
                "SELECT " + ", ".join(f'\"{name}\"' for name in selected)
                + ' FROM "weather_config" ORDER BY "id"'
            )
            rows = connection.execute(query).mappings().all()
            for row in rows:
                value = _row_refresh_hours(row, weather_columns)
                table_values.append(value)
                table_records.append((int(row["id"]), value))
            if len(set(table_values)) > 1:
                raise ValueError(
                    "weather_config contains conflicting refresh cadence values"
                )

    document_values: list[tuple[int, dict[str, Any], int]] = []
    if inspector.has_table("system_configuration"):
        rows = connection.execute(
            text('SELECT "id", "weather_json" FROM "system_configuration" ORDER BY "id"')
        ).mappings().all()
        for row in rows:
            try:
                raw = json.loads(row["weather_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("persisted weather_json is not valid JSON") from exc
            if not isinstance(raw, dict):
                raise ValueError("persisted weather_json must be an object")
            fallback = table_values[0] if table_values else DEFAULT_REFRESH_HOURS
            document = canonical_weather_document(raw, fallback_hours=fallback)
            document_values.append((int(row["id"]), document, int(document[CANONICAL_REFRESH_FIELD])))

    all_values = table_values + [value for _id, _document, value in document_values]
    if len(set(all_values)) > 1:
        raise ValueError(
            "weather_config and system_configuration contain conflicting refresh cadence values"
        )

    # No source mutation occurs before this point.  Rename the old functional
    # column in place for the common case; if a partially applied schema has
    # both names, remove the duplicate while preserving its rows.  The schema
    # operation also replaces the legacy server default (180 minutes) with the
    # canonical four-hour default.  SQLite performs this as a transactional
    # batch table rewrite; PostgreSQL emits its native ALTER TABLE statements.
    if inspector.has_table("weather_config"):
        if LEGACY_REFRESH_COLUMN in weather_columns:
            _migrate_weather_refresh_column(connection, weather_columns)
        elif CANONICAL_REFRESH_COLUMN not in weather_columns:
            connection.execute(
                text(
                    'ALTER TABLE "weather_config" ADD COLUMN '
                    f'"{CANONICAL_REFRESH_COLUMN}" INTEGER NOT NULL '
                    f'DEFAULT {DEFAULT_REFRESH_HOURS}'
                )
            )

        if LEGACY_REFRESH_COLUMN in weather_columns:
            # A column rename preserves the old minute number verbatim.  Write
            # the already-validated converted value only after all sources have
            # passed validation, still inside the same transaction.
            for row_id, value in table_records:
                connection.execute(
                    text(
                        f'UPDATE "weather_config" SET "{CANONICAL_REFRESH_COLUMN}" = :value '
                        'WHERE "id" = :id'
                    ),
                    {"id": row_id, "value": value},
                )

    for row_id, document, _value in document_values:
        connection.execute(
            text('UPDATE "system_configuration" SET "weather_json" = :weather WHERE "id" = :id'),
            {
                "id": row_id,
                "weather": json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False),
            },
        )


def migrate_refresh_configuration_engine(engine: Engine) -> None:
    """Run :func:`migrate_refresh_configuration` in one database transaction."""
    with engine.begin() as connection:
        migrate_refresh_configuration(connection)


def _row_refresh_hours(row: Mapping[str, Any], columns: set[str]) -> int:
    canonical = (
        canonical_refresh_hours(row[CANONICAL_REFRESH_COLUMN], CANONICAL_REFRESH_COLUMN)
        if CANONICAL_REFRESH_COLUMN in columns
        else None
    )
    converted = (
        refresh_hours_from_minutes(row[LEGACY_REFRESH_COLUMN], LEGACY_REFRESH_COLUMN)
        if LEGACY_REFRESH_COLUMN in columns
        else None
    )
    if canonical is not None and converted is not None and canonical != converted:
        raise ValueError(
            "watchdog_refresh_hours conflicts with watchdog_refresh_minutes in the persisted schema"
        )
    return canonical if canonical is not None else converted  # type: ignore[return-value]


def _migrate_weather_refresh_column(
    connection: Connection, columns: set[str]
) -> None:
    """Rename/remove the legacy cadence and install the canonical default."""
    # Keep Alembic out of normal service startup: this helper is imported by
    # runtime mapping code, while the operation itself is reached only by an
    # explicit schema/import migration.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    check_constraints = inspect(connection).get_check_constraints("weather_config")
    drop_checks = [
        item["name"]
        for item in check_constraints
        if item.get("name")
        and (
            item["name"] == "ck_weather_refresh"
            or LEGACY_REFRESH_COLUMN in str(item.get("sqltext", ""))
        )
    ]
    operations = Operations(MigrationContext.configure(connection))
    with operations.batch_alter_table("weather_config") as batch:
        for name in drop_checks:
            batch.drop_constraint(name, type_="check")
        if CANONICAL_REFRESH_COLUMN in columns:
            if LEGACY_REFRESH_COLUMN in columns:
                batch.drop_column(LEGACY_REFRESH_COLUMN)
            batch.alter_column(
                CANONICAL_REFRESH_COLUMN,
                server_default=text(str(DEFAULT_REFRESH_HOURS)),
            )
        else:
            batch.alter_column(
                LEGACY_REFRESH_COLUMN,
                new_column_name=CANONICAL_REFRESH_COLUMN,
                server_default=text(str(DEFAULT_REFRESH_HOURS)),
            )
        batch.create_check_constraint(
            "ck_weather_refresh", f"{CANONICAL_REFRESH_COLUMN} > 0"
        )


__all__ = [
    "CANONICAL_REFRESH_COLUMN",
    "CANONICAL_REFRESH_FIELD",
    "DEFAULT_REFRESH_HOURS",
    "LEGACY_REFRESH_COLUMN",
    "LEGACY_REFRESH_FIELD",
    "canonical_refresh_hours",
    "canonical_weather_document",
    "canonical_weather_row",
    "migrate_refresh_configuration",
    "migrate_refresh_configuration_engine",
    "refresh_hours_from_minutes",
]
