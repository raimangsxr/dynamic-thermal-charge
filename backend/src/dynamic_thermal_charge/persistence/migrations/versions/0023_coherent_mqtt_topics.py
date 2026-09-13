"""Remove MQTT topic overrides and synthetic weather configuration."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "0023_coherent_mqtt_topics"
down_revision = "0022_canonical_plan_statuses"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _check_names(table_name: str) -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_check_constraints(table_name)
        if item.get("name")
    }


def _replace_check(table_name: str, constraint_name: str, expression: str) -> None:
    names = _check_names(table_name)
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        with op.batch_alter_table(table_name, recreate="always") as batch:
            if constraint_name in names:
                batch.drop_constraint(constraint_name, type_="check")
            batch.create_check_constraint(constraint_name, expression)
        return

    # Replacing a SQLite CHECK rebuilds the table. Preserve rows in every
    # dependent table because forecast_hour (and future children) must survive
    # the rebuild of forecast.
    inspector = sa.inspect(connection)
    old_metadata = sa.MetaData()
    old = sa.Table(table_name, old_metadata, autoload_with=connection)
    new_metadata = sa.MetaData()
    for foreign_key in old.foreign_keys:
        referenced_name = foreign_key.target_fullname.split(".", 1)[0]
        if referenced_name not in new_metadata.tables:
            sa.Table(referenced_name, new_metadata, autoload_with=connection)
    temporary_name = f"{table_name}__constraint_new"
    new = old.to_metadata(new_metadata, name=temporary_name)
    for constraint in list(new.constraints):
        if constraint.name == constraint_name:
            new.constraints.remove(constraint)
    new.append_constraint(sa.CheckConstraint(expression, name=constraint_name))

    index_specs: list[tuple[str, bool, tuple[str, ...]]] = []
    for index in list(new.indexes):
        if index.name:
            index_specs.append((index.name, bool(index.unique), tuple(index.columns.keys())))
        new.indexes.remove(index)
    keep = [column.name for column in old.c]

    child_rows: list[tuple[sa.Table, list[dict[str, object]]]] = []
    for child_name in inspector.get_table_names():
        if child_name == table_name:
            continue
        child_foreign_keys = inspector.get_foreign_keys(child_name)
        if not any(item.get("referred_table") == table_name for item in child_foreign_keys):
            continue
        child_table = sa.Table(child_name, sa.MetaData(), autoload_with=connection)
        rows = [dict(row) for row in connection.execute(sa.select(child_table)).mappings()]
        child_rows.append((child_table, rows))

    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        new.create(connection)
        connection.execute(
            new.insert().from_select(keep, sa.select(*(old.c[name] for name in keep)))
        )
        old.drop(connection)
        connection.exec_driver_sql(
            f'ALTER TABLE "{temporary_name}" RENAME TO "{table_name}"'
        )
        rebuilt = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        for name, unique, keys in index_specs:
            sa.Index(name, *(rebuilt.c[key] for key in keys), unique=unique).create(connection)
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


def _drop_columns(table_name: str, columns: set[str]) -> None:
    existing = _columns(table_name)
    dropped = sorted(existing & columns)
    if not dropped:
        return
    # Native SQLite DROP COLUMN preserves rows in child tables (notably
    # output_config and heater_telemetry). Alembic's generic table rebuild can
    # cascade-delete those rows while replacing the parent table.
    if op.get_bind().dialect.name == "sqlite":
        connection = op.get_bind()
        for column in dropped:
            connection.execute(
                sa.text(f'ALTER TABLE "{table_name}" DROP COLUMN "{column}"')
            )
        return
    with op.batch_alter_table(table_name, recreate="always") as batch:
        for column in dropped:
            batch.drop_column(column)


def _normalise_system_documents() -> None:
    if not _has_table("system_configuration"):
        return
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, mqtt_json, weather_json FROM system_configuration")
    ).mappings().all()
    for row in rows:
        mqtt = json.loads(row["mqtt_json"])
        weather = json.loads(row["weather_json"])
        mqtt["prefix"] = "telemetria"
        for field_name in (
            "fixed_temperature_c",
            "fixed_target_temperature_c",
            "fixed_indoor_temperature_c",
            "fixed_stored_soc_percent",
            "fixed_stored_charge_percent",
        ):
            mqtt.pop(field_name, None)
        weather["provider"] = "aemet"
        for field_name in (
            "simulated_average_temperature_c",
            "simulated_minimum_temperature_c",
            "fallback_average_temperature_c",
            "fallback_minimum_temperature_c",
        ):
            weather.pop(field_name, None)
        connection.execute(
            sa.text(
                "UPDATE system_configuration SET mqtt_json = :mqtt, "
                "weather_json = :weather WHERE id = :id"
            ),
            {
                "id": row["id"],
                "mqtt": json.dumps(mqtt, sort_keys=True, separators=(",", ":")),
                "weather": json.dumps(weather, sort_keys=True, separators=(",", ":")),
            },
        )


def upgrade() -> None:
    _normalise_system_documents()

    if _has_table("weather_config"):
        op.get_bind().execute(sa.text("UPDATE weather_config SET provider = 'aemet'"))
        _drop_columns(
            "weather_config",
            {
                "simulated_average_temperature_c",
                "simulated_minimum_temperature_c",
                "fallback_average_temperature_c",
                "fallback_minimum_temperature_c",
            },
        )
        _replace_check("weather_config", "ck_weather_provider", "provider = 'aemet'")

    _drop_columns("heater", {"telemetry_topic"})
    _drop_columns(
        "charge_planning_site",
        {
            "mqtt_simulation_enabled",
            "mqtt_simulation_initial_temperature_c",
            "mqtt_simulation_publish_seconds",
            "mqtt_simulation_topic_prefix",
            "mqtt_simulation_thermal_loss_c_per_hour",
        },
    )
    _drop_columns("heater_charge_config", {"damper_topic", "setpoint_topic"})

    if _has_table("forecast"):
        connection = op.get_bind()
        if _has_table("forecast_hour"):
            connection.execute(sa.text(
                "DELETE FROM forecast_hour WHERE forecast_id IN "
                "(SELECT id FROM forecast WHERE source <> 'aemet')"
            ))
        connection.execute(sa.text("DELETE FROM forecast WHERE source <> 'aemet'"))
        _replace_check("forecast", "ck_forecast_source", "source = 'aemet'")


def downgrade() -> None:
    if _has_table("weather_config"):
        with op.batch_alter_table("weather_config", recreate="always") as batch:
            columns = _columns("weather_config")
            for name in (
                "simulated_average_temperature_c",
                "simulated_minimum_temperature_c",
                "fallback_average_temperature_c",
                "fallback_minimum_temperature_c",
            ):
                if name not in columns:
                    batch.add_column(sa.Column(name, sa.Float(), nullable=True))
        _replace_check(
            "weather_config",
            "ck_weather_provider",
            "provider IN ('simulated', 'aemet')",
        )

    if _has_table("heater") and "telemetry_topic" not in _columns("heater"):
        op.add_column("heater", sa.Column("telemetry_topic", sa.String(length=512), nullable=True))
    if _has_table("charge_planning_site"):
        additions = (
            ("mqtt_simulation_enabled", sa.Boolean(), "0"),
            ("mqtt_simulation_initial_temperature_c", sa.Float(), "45"),
            ("mqtt_simulation_publish_seconds", sa.Float(), "30"),
            ("mqtt_simulation_topic_prefix", sa.String(length=256), "'dtc/sim'"),
            ("mqtt_simulation_thermal_loss_c_per_hour", sa.Float(), "2"),
        )
        columns = _columns("charge_planning_site")
        with op.batch_alter_table("charge_planning_site", recreate="always") as batch:
            for name, column_type, default in additions:
                if name not in columns:
                    batch.add_column(
                        sa.Column(name, column_type, nullable=False, server_default=default)
                    )
    if _has_table("heater_charge_config"):
        columns = _columns("heater_charge_config")
        with op.batch_alter_table("heater_charge_config", recreate="always") as batch:
            if "damper_topic" not in columns:
                batch.add_column(sa.Column("damper_topic", sa.String(length=512), nullable=True))
            if "setpoint_topic" not in columns:
                batch.add_column(sa.Column("setpoint_topic", sa.String(length=512), nullable=True))

    if _has_table("forecast"):
        _replace_check(
            "forecast",
            "ck_forecast_source",
            "source IN ('aemet', 'simulated', 'fallback')",
        )
