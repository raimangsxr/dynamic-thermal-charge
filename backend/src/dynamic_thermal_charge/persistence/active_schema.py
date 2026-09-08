"""Independent lifecycle for canonical configuration and application schemas."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import Index, MetaData, Table, inspect, select, text, update
from sqlalchemy.engine import Engine

from .schema import (
    application_metadata,
    application_schema_version,
    configuration_metadata,
    configuration_schema_version,
)
from .topology import BootstrapCorruptError, BootstrapIncompatibleError
from . import SchemaStatus, SchemaVersionError


CONFIGURATION_SCHEMA_REVISION = 9
APPLICATION_SCHEMA_REVISION = 5
POSTGRES_CONFIGURATION_SCHEMA = "dtc_config"
POSTGRES_APPLICATION_SCHEMA = "dtc_app"


@dataclass(frozen=True)
class ActiveSchemaStatus:
    configuration_revision: int
    application_revision: int


class ActiveSchemaGate:
    def __init__(self, configuration_engine: Engine, application_engine: Engine) -> None:
        self._configuration_engine = configuration_engine
        self._application_engine = application_engine

    def check(self) -> SchemaStatus:
        statuses = (
            _status(self._configuration_engine, configuration_schema_version,
                    CONFIGURATION_SCHEMA_REVISION),
            _status(self._application_engine, application_schema_version,
                    APPLICATION_SCHEMA_REVISION),
        )
        if SchemaStatus.UNKNOWN in statuses:
            return SchemaStatus.UNKNOWN
        if SchemaStatus.MISSING in statuses:
            return SchemaStatus.MISSING
        if SchemaStatus.BEHIND in statuses:
            return SchemaStatus.BEHIND
        return SchemaStatus.OK

    def require_ready(self) -> None:
        status = self.check()
        if status is SchemaStatus.OK:
            return
        if status is SchemaStatus.MISSING:
            raise SchemaVersionError("an active schema is missing; ask the administrator to initialise it")
        if status is SchemaStatus.BEHIND:
            raise SchemaVersionError("an active schema needs migration; ask the administrator to migrate it")
        raise SchemaVersionError(
            "an active schema revision is newer or invalid; update the service"
        )


def _status(engine: Engine, table: Table, expected: int) -> SchemaStatus:
    if table.name not in inspect(engine).get_table_names():
        return SchemaStatus.MISSING
    with engine.connect() as connection:
        revisions = connection.execute(select(table.c.revision)).scalars().all()
    if len(revisions) != 1:
        return SchemaStatus.UNKNOWN
    revision = int(revisions[0])
    if revision == expected:
        return SchemaStatus.OK
    if revision < expected:
        return SchemaStatus.BEHIND
    return SchemaStatus.UNKNOWN


def upgrade_active_schemas(
    configuration_engine: Engine, application_engine: Engine
) -> ActiveSchemaStatus:
    config_revision = _upgrade(
        configuration_engine,
        configuration_metadata,
        configuration_schema_version,
        CONFIGURATION_SCHEMA_REVISION,
        "configuration",
    )
    application_revision = _upgrade(
        application_engine,
        application_metadata,
        application_schema_version,
        APPLICATION_SCHEMA_REVISION,
        "application",
    )
    return ActiveSchemaStatus(config_revision, application_revision)


def require_active_schemas(
    configuration_engine: Engine, application_engine: Engine
) -> ActiveSchemaStatus:
    return ActiveSchemaStatus(
        _require(
            configuration_engine,
            configuration_schema_version,
            CONFIGURATION_SCHEMA_REVISION,
            "configuration",
        ),
        _require(
            application_engine,
            application_schema_version,
            APPLICATION_SCHEMA_REVISION,
            "application",
        ),
    )


def _upgrade(
    engine: Engine,
    metadata: MetaData,
    version_table: Table,
    expected: int,
    label: str,
) -> int:
    existing = set(inspect(engine).get_table_names())
    if version_table.name in existing:
        revision = _stored_revision(engine, version_table, label)
        if revision > expected:
            raise BootstrapIncompatibleError(
                f"{label} schema revision {revision} is newer than supported {expected}"
            )
        if revision < expected:
            if label == "application":
                _upgrade_application_schema(engine, revision, expected)
            else:
                _upgrade_configuration_schema(engine, revision, expected)
            with engine.begin() as connection:
                connection.execute(
                    update(version_table).where(version_table.c.id == 1).values(revision=expected)
                )
            revision = expected
        metadata.create_all(engine)
        return revision
    if existing:
        raise BootstrapCorruptError(
            f"{label} store has tables but no independent schema revision"
        )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(version_table.insert().values(id=1, revision=expected))
    return expected


def _require(engine: Engine, table: Table, expected: int, label: str) -> int:
    if table.name not in inspect(engine).get_table_names():
        raise BootstrapCorruptError(f"{label} schema revision is missing")
    revision = _stored_revision(engine, table, label)
    if revision != expected:
        direction = "newer" if revision > expected else "older"
        raise BootstrapIncompatibleError(
            f"{label} schema revision {revision} is {direction} than supported {expected}"
        )
    return revision


def _stored_revision(engine: Engine, table: Table, label: str) -> int:
    with engine.connect() as connection:
        revisions = connection.execute(select(table.c.revision)).scalars().all()
    if len(revisions) != 1:
        raise BootstrapCorruptError(f"{label} schema revision is ambiguous")
    return int(revisions[0])


def _upgrade_application_schema(engine: Engine, revision: int, expected: int) -> None:
    """Apply the small, portable application-schema upgrades in order."""
    if revision == 1 and expected >= 2:
        columns = {
            column["name"] for column in inspect(engine).get_columns("forecast_cycle")
        }
        additions = (
            ("last_attempt_at", "DATETIME"),
            ("last_result", "VARCHAR(16)"),
            ("next_run_at", "DATETIME"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE forecast_cycle ADD COLUMN {name} {definition}"))
        revision = 2
    if revision == 2 and expected >= 3:
        columns = {column["name"] for column in inspect(engine).get_columns("automatic_plan_slot")}
        with engine.begin() as connection:
            for name in ("initial_soc_json", "demand_json", "heater_power_json"):
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE automatic_plan_slot ADD COLUMN {name} TEXT NOT NULL DEFAULT '{{}}'"))
        revision = 3
    if revision == 3 and expected >= 4:
        from .schema import preview_job, preview_job_step
        application_metadata.create_all(engine, tables=[preview_job, preview_job_step])
        revision = 4
    if revision == 4 and expected >= 5:
        columns = {column["name"] for column in inspect(engine).get_columns("automatic_plan_slot")}
        additions = (
            ("stored_energy_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("indoor_temperature_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("target_temperature_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("heat_delivered_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("thermal_loss_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("temperature_shortfall_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("charge_energy_json", "TEXT NOT NULL DEFAULT '{}'"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in columns:
                    connection.execute(
                        text(f"ALTER TABLE automatic_plan_slot ADD COLUMN {name} {definition}")
                    )
        telemetry_columns = {
            column["name"] for column in inspect(engine).get_columns("heater_telemetry")
        }
        if "stored_soc_percent" not in telemetry_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE heater_telemetry ADD COLUMN stored_soc_percent FLOAT")
                )
        telemetry_columns = {
            column["name"] for column in inspect(engine).get_columns("heater_telemetry")
        }
        with engine.begin() as connection:
            if "stored_soc_received_at" not in telemetry_columns:
                connection.execute(
                    text("ALTER TABLE heater_telemetry ADD COLUMN stored_soc_received_at DATETIME")
                )
            if "stored_charge_percent" in telemetry_columns:
                connection.execute(text(
                    "UPDATE heater_telemetry SET stored_soc_percent = COALESCE(stored_soc_percent, stored_charge_percent), "
                    "stored_soc_received_at = COALESCE(stored_soc_received_at, stored_charge_received_at)"
                ))
        _drop_columns(
            engine,
            "heater_telemetry",
            {
                "target_temperature_c",
                "target_received_at",
                "stored_charge_percent",
                "stored_charge_received_at",
            },
        )
        revision = 5
    if revision != expected:
        raise BootstrapIncompatibleError(
            f"application schema revision {revision} has no registered upgrade path to {expected}"
        )


def _upgrade_configuration_schema(engine: Engine, revision: int, expected: int) -> None:
    if revision == 1 and expected >= 2:
        site_columns = {column["name"] for column in inspect(engine).get_columns("charge_planning_site")}
        heater_columns = {column["name"] for column in inspect(engine).get_columns("heater_charge_config")}
        additions = (
            ("contracted_power_w", "INTEGER NOT NULL DEFAULT 5200"),
            ("max_heating_power_w", "INTEGER NOT NULL DEFAULT 5200"),
            ("design_indoor_temperature_c", "FLOAT NOT NULL DEFAULT 21"),
            ("design_outdoor_temperature_c", "FLOAT NOT NULL DEFAULT 0"),
            ("feedback_horizon_hours", "FLOAT NOT NULL DEFAULT 6"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in site_columns:
                    connection.execute(text(f"ALTER TABLE charge_planning_site ADD COLUMN {name} {definition}"))
            if "demand_factor" not in heater_columns:
                connection.execute(text("ALTER TABLE heater_charge_config ADD COLUMN demand_factor FLOAT NOT NULL DEFAULT 1"))
            connection.execute(text(
                "UPDATE charge_planning_site SET "
                "contracted_power_w = (SELECT max_total_power_w FROM installation WHERE installation.id = charge_planning_site.installation_id), "
                "max_heating_power_w = (SELECT max_total_power_w FROM installation WHERE installation.id = charge_planning_site.installation_id)"
            ))
            connection.execute(text(
                "UPDATE heater_charge_config SET demand_factor = COALESCE(("
                "SELECT thermal_profile.thermal_factor FROM thermal_profile "
                "JOIN heater ON heater.id = thermal_profile.heater_id "
                "WHERE heater.heater_id = heater_charge_config.heater_id "
                "AND heater.installation_id = heater_charge_config.installation_id"
                "), 1)"
            ))
        revision = 2
    if revision == 2 and expected >= 3:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        additions = (
            ("mqtt_simulation_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("mqtt_simulation_initial_temperature_c", "FLOAT NOT NULL DEFAULT 45"),
            ("mqtt_simulation_publish_seconds", "FLOAT NOT NULL DEFAULT 30"),
            ("mqtt_simulation_topic_prefix", "VARCHAR(256) NOT NULL DEFAULT 'dtc/sim'"),
            ("mqtt_simulation_thermal_loss_c_per_hour", "FLOAT NOT NULL DEFAULT 2"),
        )
        with engine.begin() as connection:
            for name, definition in additions:
                if name not in site_columns:
                    connection.execute(
                        text(f"ALTER TABLE charge_planning_site ADD COLUMN {name} {definition}")
                    )
        revision = 3
    if revision == 3 and expected >= 4:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        if "base_load_w" not in site_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE charge_planning_site ADD COLUMN base_load_w INTEGER NOT NULL DEFAULT 0")
                )
        revision = 4
    if revision == 4 and expected >= 5:
        with engine.begin() as connection:
            connection.execute(text("UPDATE charge_planning_site SET forecast_horizon_hours = 24"))
        revision = 5
    if revision == 5 and expected >= 6:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        if "planning_window_hours" not in site_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE charge_planning_site ADD COLUMN planning_window_hours INTEGER NOT NULL DEFAULT 12")
                )
        revision = 6
    if revision == 6 and expected >= 7:
        site_columns = {
            column["name"] for column in inspect(engine).get_columns("charge_planning_site")
        }
        if "solver_time_limit_seconds" not in site_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE charge_planning_site ADD COLUMN solver_time_limit_seconds INTEGER NOT NULL DEFAULT 120")
                )
        revision = 7
    if revision == 7 and expected >= 8:
        thermal_columns = {
            column["name"] for column in inspect(engine).get_columns("thermal_profile")
        }
        charge_columns = {
            column["name"] for column in inspect(engine).get_columns("heater_charge_config")
        }
        with engine.begin() as connection:
            if "room_thermal_capacity_kwh_per_c" not in thermal_columns:
                connection.execute(text(
                    "ALTER TABLE thermal_profile ADD COLUMN "
                    "room_thermal_capacity_kwh_per_c FLOAT NOT NULL DEFAULT 2.5"
                ))
            if "room_heat_loss_kw_per_c" not in thermal_columns:
                connection.execute(text(
                    "ALTER TABLE thermal_profile ADD COLUMN "
                    "room_heat_loss_kw_per_c FLOAT NOT NULL DEFAULT 0.12"
                ))
            connection.execute(text(
                "UPDATE thermal_profile SET "
                "room_thermal_capacity_kwh_per_c = COALESCE(room_thermal_capacity_kwh_per_c, 2.5), "
                "room_heat_loss_kw_per_c = COALESCE(room_heat_loss_kw_per_c, 0.12)"
            ))
            if "stored_soc_topic" not in charge_columns:
                connection.execute(text(
                    "ALTER TABLE heater_charge_config ADD COLUMN stored_soc_topic VARCHAR(512)"
                ))
            # Percentage charge constraints have no physical conversion.  The
            # room-energy planner must never silently reuse them after upgrade.
            if inspect(connection).has_table("charge_constraint"):
                connection.execute(text("DELETE FROM charge_constraint"))
        _drop_columns(engine, "heater", {"target_charge"})
        _drop_columns(
            engine,
            "thermal_profile",
            {
                "target_temperature_c",
                "design_outdoor_temperature_c",
                "thermal_factor",
                "min_charge",
                "max_charge",
                "thermal_loss_c_per_hour",
            },
        )
        _drop_columns(
            engine,
            "charge_planning_site",
            {
                "design_indoor_temperature_c",
                "design_outdoor_temperature_c",
                "feedback_horizon_hours",
            },
        )
        _drop_columns(
            engine,
            "heater_charge_config",
            {
                "temperature_topic",
                "target_temperature_topic",
                "stored_charge_topic",
                "reserve_percent",
                "demand_factor",
                "room_inertia_hours",
                "outdoor_loss_per_hour",
                "emission_c_per_hour",
            },
        )
        if inspect(engine).has_table("charge_constraint"):
            with engine.begin() as connection:
                connection.execute(text("DROP TABLE charge_constraint"))
        revision = 8
    if revision == 8 and expected >= 9:
        from .schema import temperature_target

        if inspect(engine).has_table("temperature_target"):
            indexes = {
                index["name"]
                for index in inspect(engine).get_indexes("temperature_target")
                if index.get("name")
            }
            with engine.begin() as connection:
                if "ix_temperature_target_installation_heater" in indexes:
                    connection.execute(
                        text(
                            "DROP INDEX ix_temperature_target_installation_heater"
                        )
                    )
                temperature_target.drop(connection)
        configuration_metadata.create_all(engine, tables=[temperature_target])
        revision = 9
    if revision != expected:
        raise BootstrapIncompatibleError(
            f"configuration schema revision {revision} has no registered upgrade path to {expected}"
        )


def _drop_columns(engine, table_name: str, columns: set[str]) -> None:
    """Drop legacy columns while retaining data and portable constraints.

    SQLite cannot drop a column referenced by a table-level CHECK constraint.
    Rebuilding the table is therefore necessary there; PostgreSQL can use its
    native ``DROP COLUMN`` operation.  This helper is only used during a
    versioned upgrade while the store is exclusively owned by the process.
    """
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    dropped = existing & columns
    if not dropped:
        return
    if engine.dialect.name != "sqlite":
        with engine.begin() as connection:
            constraint_names = [
                item["name"]
                for item in inspect(connection).get_check_constraints(table_name)
                if item.get("name")
                and any(
                    re.search(rf"\b{re.escape(column)}\b", str(item.get("sqltext", "")), re.IGNORECASE)
                    for column in dropped
                )
            ]
            for name in constraint_names:
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{name}"'
                )
            for column in sorted(dropped):
                connection.execute(
                    text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column}"')
                )
        return

    old_metadata = MetaData()
    with engine.connect() as connection:
        old = Table(table_name, old_metadata, autoload_with=connection)
    new_metadata = MetaData()
    for foreign_key in old.foreign_keys:
        referenced_name = foreign_key.target_fullname.split(".", 1)[0]
        if referenced_name not in new_metadata.tables:
            Table(referenced_name, new_metadata, autoload_with=engine)
    temporary_name = f"{table_name}__room_energy_new"
    new = old.to_metadata(new_metadata, name=temporary_name)
    for column in dropped:
        new._columns.remove(new.c[column])

    def mentions_dropped(expression) -> bool:
        rendered = str(expression)
        return any(
            re.search(rf"\b{re.escape(column)}\b", rendered, re.IGNORECASE)
            for column in dropped
        )

    for constraint in list(new.constraints):
        keys = set(getattr(constraint.columns, "keys", lambda: ())())
        if keys & dropped or mentions_dropped(getattr(constraint, "sqltext", constraint)):
            new.constraints.remove(constraint)
    index_specs: list[tuple[str, bool, tuple[str, ...]]] = []
    for index in list(new.indexes):
        if set(index.columns.keys()) & dropped or mentions_dropped(index):
            new.indexes.remove(index)
            continue
        if index.name:
            index_specs.append((index.name, bool(index.unique), tuple(index.columns.keys())))
        new.indexes.remove(index)

    keep = [column.name for column in old.c if column.name not in dropped]
    child_rows: list[tuple[Table, list[dict[str, object]]]] = []
    for child_name in inspector.get_table_names():
        if child_name == table_name:
            continue
        child_foreign_keys = inspect(engine).get_foreign_keys(child_name)
        if not any(item.get("referred_table") == table_name for item in child_foreign_keys):
            continue
        child_table = Table(child_name, MetaData(), autoload_with=engine)
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(select(child_table)).mappings()]
        child_rows.append((child_table, rows))

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            new.create(connection)
            connection.execute(
                new.insert().from_select(keep, select(*(old.c[name] for name in keep)))
            )
            old.drop(connection)
            connection.exec_driver_sql(
                f'ALTER TABLE "{temporary_name}" RENAME TO "{table_name}"'
            )
            rebuilt = Table(table_name, MetaData(), autoload_with=connection)
            for name, unique, keys in index_specs:
                Index(name, *(rebuilt.c[key] for key in keys), unique=unique).create(connection)
            for child_table, rows in child_rows:
                for row in rows:
                    predicates = [
                        child_table.c[key].is_(None)
                        if value is None
                        else child_table.c[key] == value
                        for key, value in row.items()
                    ]
                    connection.execute(child_table.delete().where(*predicates))
                if rows:
                    connection.execute(child_table.insert(), rows)
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


__all__ = [
    "APPLICATION_SCHEMA_REVISION",
    "CONFIGURATION_SCHEMA_REVISION",
    "POSTGRES_APPLICATION_SCHEMA",
    "POSTGRES_CONFIGURATION_SCHEMA",
    "ActiveSchemaStatus",
    "ActiveSchemaGate",
    "require_active_schemas",
    "upgrade_active_schemas",
]
