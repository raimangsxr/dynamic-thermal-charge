"""Replace percentage demand with the coupled room-energy model.

The percentage charge rules are deliberately not converted: a percentage
constraint has no physical meaning once room comfort is the planning objective.
Historical plan rows are left untouched so old decisions remain readable.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_room_energy_model"
down_revision = "0013_configurable_solver_time_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("thermal_profile") as batch:
        batch.add_column(
            sa.Column(
                "room_thermal_capacity_kwh_per_c",
                sa.Float(),
                nullable=False,
                server_default="2.5",
            )
        )
        batch.add_column(
            sa.Column(
                "room_heat_loss_kw_per_c",
                sa.Float(),
                nullable=False,
                server_default="0.12",
            )
        )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("heater_charge_config"):
        columns = {column["name"] for column in inspector.get_columns("heater_charge_config")}
        if "stored_soc_topic" not in columns:
            with op.batch_alter_table("heater_charge_config") as batch:
                batch.add_column(sa.Column("stored_soc_topic", sa.String(length=512), nullable=True))

    op.create_table(
        "temperature_target",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("target_temperature_c", sa.Float(), nullable=False),
        sa.Column("at_time", sa.String(length=5), nullable=False),
        sa.Column("weekdays", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "target_temperature_c >= -50 AND target_temperature_c <= 80",
            name="ck_temperature_target_range",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["installation.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "installation_id",
            "heater_id",
            "at_time",
            "weekdays",
            name="uq_temperature_target_rule",
        ),
    )
    op.create_index(
        "ix_temperature_target_installation_heater",
        "temperature_target",
        ["installation_id", "heater_id"],
    )

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("heater_telemetry"):
        telemetry_columns = {
            column["name"] for column in inspector.get_columns("heater_telemetry")
        }
        with op.batch_alter_table("heater_telemetry") as batch:
            if "stored_soc_percent" not in telemetry_columns:
                batch.add_column(sa.Column("stored_soc_percent", sa.Float(), nullable=True))
            if "stored_soc_received_at" not in telemetry_columns:
                batch.add_column(sa.Column("stored_soc_received_at", sa.DateTime(), nullable=True))
        if "stored_charge_percent" in telemetry_columns:
            op.execute(sa.text(
                "UPDATE heater_telemetry SET stored_soc_percent = COALESCE(stored_soc_percent, stored_charge_percent), "
                "stored_soc_received_at = COALESCE(stored_soc_received_at, stored_charge_received_at)"
            ))

    if inspector.has_table("automatic_plan_slot"):
        with op.batch_alter_table("automatic_plan_slot") as batch:
            for name in (
                "stored_energy_json",
                "indoor_temperature_json",
                "target_temperature_json",
                "heat_delivered_json",
                "thermal_loss_json",
                "temperature_shortfall_json",
                "charge_energy_json",
            ):
                batch.add_column(
                    sa.Column(name, sa.Text(), nullable=False, server_default="{}")
                )

    op.execute(
        sa.text(
            "INSERT INTO temperature_target "
            "(installation_id, heater_id, target_temperature_c, at_time, weekdays, "
            "enabled, created_at, updated_at) "
            "SELECT h.installation_id, h.heater_id, COALESCE(t.target_temperature_c, 21), "
            "'00:00', '0,1,2,3,4,5,6', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM heater h LEFT JOIN thermal_profile t ON t.heater_id = h.id"
        )
    )

    # The old rows are not convertible.  Delete the table after the new target
    # schedule has been materialised so no percentage requirement survives in
    # the active configuration schema.
    if inspector.has_table("charge_constraint"):
        indexes = {index["name"] for index in inspector.get_indexes("charge_constraint")}
        if "ix_charge_constraint_installation_heater" in indexes:
            op.drop_index(
                "ix_charge_constraint_installation_heater",
                table_name="charge_constraint",
            )
        op.drop_table("charge_constraint")

    _drop_columns(
        "heater",
        {"target_charge"},
    )
    _drop_columns(
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
        "charge_planning_site",
        {
            "design_indoor_temperature_c",
            "design_outdoor_temperature_c",
            "feedback_horizon_hours",
        },
    )
    _drop_columns(
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
    _drop_columns(
        "heater_telemetry",
        {
            "target_temperature_c",
            "target_received_at",
            "stored_charge_percent",
            "stored_charge_received_at",
        },
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    connection = op.get_bind()
    legacy_targets = {}
    if inspector.has_table("temperature_target"):
        legacy_targets = {
            str(row["heater_id"]): float(row["target_temperature_c"])
            for row in connection.execute(
                sa.text(
                    "SELECT heater_id, target_temperature_c "
                    "FROM temperature_target WHERE at_time = '00:00' "
                    "ORDER BY id"
                )
            ).mappings()
        }
    if inspector.has_table("temperature_target"):
        if "ix_temperature_target_installation_heater" in {
            item["name"] for item in inspector.get_indexes("temperature_target")
        }:
            op.drop_index(
                "ix_temperature_target_installation_heater",
                table_name="temperature_target",
            )
        op.drop_table("temperature_target")
    if inspector.has_table("heater_telemetry"):
        columns = {column["name"] for column in inspector.get_columns("heater_telemetry")}
        with op.batch_alter_table("heater_telemetry") as batch:
            if "target_temperature_c" not in columns:
                batch.add_column(sa.Column("target_temperature_c", sa.Float(), nullable=True))
            if "target_received_at" not in columns:
                batch.add_column(sa.Column("target_received_at", sa.DateTime(), nullable=True))
            if "stored_charge_percent" not in columns:
                batch.add_column(sa.Column("stored_charge_percent", sa.Float(), nullable=True))
            if "stored_charge_received_at" not in columns:
                batch.add_column(sa.Column("stored_charge_received_at", sa.DateTime(), nullable=True))
            if "stored_soc_percent" in columns:
                batch.drop_column("stored_soc_percent")
            if "stored_soc_received_at" in columns:
                batch.drop_column("stored_soc_received_at")
    if inspector.has_table("automatic_plan_slot"):
        columns = {column["name"] for column in inspector.get_columns("automatic_plan_slot")}
        with op.batch_alter_table("automatic_plan_slot") as batch:
            for name in (
                "stored_energy_json",
                "indoor_temperature_json",
                "target_temperature_json",
                "heat_delivered_json",
                "thermal_loss_json",
                "temperature_shortfall_json",
                "charge_energy_json",
            ):
                if name in columns:
                    batch.drop_column(name)
    if inspector.has_table("heater"):
        columns = {column["name"] for column in inspector.get_columns("heater")}
        if "target_charge" not in columns:
            # SQLite can add this legacy column in place.  Rebuilding the
            # parent heater table here would cascade-delete output_config rows
            # during a downgrade; the original check is restored by the next
            # full legacy migration cycle where the table is rebuilt safely.
            op.add_column(
                "heater",
                sa.Column("target_charge", sa.Float(), nullable=False, server_default="1.0"),
            )
            if op.get_bind().dialect.name != "sqlite":
                op.create_check_constraint(
                    "ck_heater_target_charge",
                    "heater",
                    "target_charge >= 0 AND target_charge <= 1",
                )

    if inspector.has_table("thermal_profile"):
        _drop_columns(
            "thermal_profile",
            {"room_thermal_capacity_kwh_per_c", "room_heat_loss_kw_per_c"},
        )
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("thermal_profile")}
        with op.batch_alter_table("thermal_profile") as batch:
            if "target_temperature_c" not in columns:
                batch.add_column(sa.Column("target_temperature_c", sa.Float(), nullable=False, server_default="21"))
            if "design_outdoor_temperature_c" not in columns:
                batch.add_column(sa.Column("design_outdoor_temperature_c", sa.Float(), nullable=False, server_default="0"))
            if "thermal_factor" not in columns:
                batch.add_column(sa.Column("thermal_factor", sa.Float(), nullable=False, server_default="1"))
            if "min_charge" not in columns:
                batch.add_column(sa.Column("min_charge", sa.Float(), nullable=False, server_default="0"))
            if "max_charge" not in columns:
                batch.add_column(sa.Column("max_charge", sa.Float(), nullable=False, server_default="1"))
            if "thermal_loss_c_per_hour" not in columns:
                batch.add_column(sa.Column("thermal_loss_c_per_hour", sa.Float(), nullable=False, server_default="0"))
            batch.create_check_constraint(
                "ck_thermal_charge_bounds",
                "min_charge >= 0 AND min_charge <= max_charge AND max_charge <= 1",
            )
            batch.create_check_constraint(
                "ck_thermal_design_below_target",
                "design_outdoor_temperature_c < target_temperature_c",
            )
            batch.create_check_constraint("ck_thermal_factor", "thermal_factor > 0")
        with connection.begin_nested():
            for heater_id, target in legacy_targets.items():
                connection.execute(
                    sa.text(
                        "UPDATE thermal_profile SET "
                        "target_temperature_c = :target, "
                        "design_outdoor_temperature_c = :outdoor "
                        "WHERE heater_id = (SELECT id FROM heater WHERE heater_id = :heater_id)"
                    ),
                    {
                        "target": target,
                        "outdoor": min(0.0, target - 1.0),
                        "heater_id": heater_id,
                    },
                )
    if inspector.has_table("heater_charge_config"):
        columns = {column["name"] for column in inspector.get_columns("heater_charge_config")}
        with op.batch_alter_table("heater_charge_config") as batch:
            for name in (
                "temperature_topic",
                "target_temperature_topic",
                "stored_charge_topic",
                "reserve_percent",
                "demand_factor",
                "room_inertia_hours",
                "outdoor_loss_per_hour",
                "emission_c_per_hour",
            ):
                if name not in columns:
                    batch.add_column(sa.Column(name, sa.Float() if name not in {"temperature_topic", "target_temperature_topic", "stored_charge_topic"} else sa.String(length=512), nullable=True))
            if "stored_soc_topic" in columns:
                batch.drop_column("stored_soc_topic")


def _drop_columns(table_name: str, columns: set[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    present = {column["name"] for column in inspector.get_columns(table_name)}
    to_drop = sorted(present & columns)
    if not to_drop:
        return
    dropped_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
        and any(
            column.lower() in str(constraint.get("sqltext", "")).lower()
            for column in to_drop
        )
    }
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table(table_name) as batch:
            for name in sorted(dropped_constraints):
                batch.drop_constraint(name, type_="check")
            for column in to_drop:
                batch.drop_column(column)
        return

    # SQLite's batch_alter_table drops the old table after creating its copy.
    # With foreign_keys enabled that would cascade-delete child rows (for
    # example output_config rows while changing heater), so rebuild it with
    # referential actions temporarily disabled and restore every unaffected
    # explicit index afterwards.
    old_metadata = sa.MetaData()
    connection = bind
    old = sa.Table(table_name, old_metadata, autoload_with=connection)
    new_metadata = sa.MetaData()
    # ``to_metadata`` copies foreign-key specifications by name.  Reflect the
    # referenced tables into the temporary metadata first so SQLAlchemy can
    # compile the copied table without trying to create those parents again.
    for foreign_key in old.foreign_keys:
        referenced_name = foreign_key.target_fullname.split(".", 1)[0]
        if referenced_name not in new_metadata.tables:
            sa.Table(referenced_name, new_metadata, autoload_with=connection)
    temporary_name = f"{table_name}__room_energy_new"
    new = old.to_metadata(new_metadata, name=temporary_name)
    for column in to_drop:
        new._columns.remove(new.c[column])

    def mentions_dropped(expression) -> bool:
        rendered = str(expression)
        return any(
            column.lower() in rendered.lower() for column in to_drop
        )

    for constraint in list(new.constraints):
        keys = set(getattr(constraint.columns, "keys", lambda: ())())
        if keys & set(to_drop) or mentions_dropped(getattr(constraint, "sqltext", constraint)):
            new.constraints.remove(constraint)

    index_specs = []
    for index in list(new.indexes):
        keys = set(index.columns.keys())
        if keys & set(to_drop) or mentions_dropped(index):
            continue
        if index.name:
            index_specs.append((index.name, bool(index.unique), tuple(index.columns.keys())))
        new.indexes.remove(index)

    keep = [column.name for column in old.c if column.name not in to_drop]
    child_rows = []
    for child_name in inspector.get_table_names():
        if child_name == table_name:
            continue
        child_inspector = sa.inspect(connection)
        foreign_keys = child_inspector.get_foreign_keys(child_name)
        if not any(item.get("referred_table") == table_name for item in foreign_keys):
            continue
        child_table = sa.Table(child_name, sa.MetaData(), autoload_with=connection)
        child_rows.append(
            (
                child_table,
                [dict(row) for row in connection.execute(sa.select(child_table)).mappings()],
            )
        )
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
                connection.execute(sa.delete(child_table).where(sa.and_(*predicates)))
            if rows:
                connection.execute(child_table.insert(), rows)
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
