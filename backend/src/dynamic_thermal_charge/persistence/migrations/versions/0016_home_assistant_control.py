"""Add durable control state and optional damper telemetry."""

from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0016_home_assistant_control"
down_revision = "0015_temperature_target_intervals"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    installation_columns = _columns("installation")
    with op.batch_alter_table("installation") as batch:
        if "installation_uuid" not in installation_columns:
            batch.add_column(sa.Column("installation_uuid", sa.String(length=36), nullable=True))
        if "automatic_control_enabled" not in installation_columns:
            batch.add_column(sa.Column("automatic_control_enabled", sa.Boolean(), nullable=False, server_default="1"))
        if "recalculation_requested_generation" not in installation_columns:
            batch.add_column(sa.Column("recalculation_requested_generation", sa.Integer(), nullable=False, server_default="0"))
        if "recalculation_processed_generation" not in installation_columns:
            batch.add_column(sa.Column("recalculation_processed_generation", sa.Integer(), nullable=False, server_default="0"))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, installation_uuid FROM installation")).mappings().all()
    for row in rows:
        if not row["installation_uuid"]:
            connection.execute(
                sa.text("UPDATE installation SET installation_uuid = :value WHERE id = :id"),
                {"value": str(uuid4()), "id": row["id"]},
            )
    op.create_index("uq_installation_uuid", "installation", ["installation_uuid"], unique=True)

    if _has_table("heater_charge_config"):
        charge_columns = _columns("heater_charge_config")
        with op.batch_alter_table("heater_charge_config") as batch:
            if "control_mode" not in charge_columns:
                batch.add_column(sa.Column("control_mode", sa.String(length=8), nullable=False, server_default="AUTO"))
            if "damper_topic" not in charge_columns:
                batch.add_column(sa.Column("damper_topic", sa.String(length=512), nullable=True))
            if "control_mode" not in charge_columns:
                batch.create_check_constraint("ck_heater_control_mode", "control_mode IN ('AUTO', 'OFF')")

    if _has_table("heater_telemetry"):
        telemetry_columns = _columns("heater_telemetry")
        with op.batch_alter_table("heater_telemetry") as batch:
            if "damper_position_percent" not in telemetry_columns:
                batch.add_column(sa.Column("damper_position_percent", sa.Float(), nullable=True))
            if "damper_received_at" not in telemetry_columns:
                batch.add_column(sa.Column("damper_received_at", sa.DateTime(), nullable=True))
            if "damper_position_percent" not in telemetry_columns:
                batch.create_check_constraint(
                    "ck_telemetry_damper",
                    "damper_position_percent IS NULL OR (damper_position_percent >= 0 AND damper_position_percent <= 100)",
                )


def downgrade() -> None:
    if _has_table("heater_telemetry"):
        with op.batch_alter_table("heater_telemetry") as batch:
            batch.drop_constraint("ck_telemetry_damper", type_="check")
            batch.drop_column("damper_received_at")
            batch.drop_column("damper_position_percent")
    if _has_table("heater_charge_config"):
        with op.batch_alter_table("heater_charge_config") as batch:
            batch.drop_constraint("ck_heater_control_mode", type_="check")
            batch.drop_column("damper_topic")
            batch.drop_column("control_mode")
    # The legacy installation table contains column-level CHECK constraints
    # whose SQLite reflection is not round-trippable through a second Alembic
    # batch rewrite.  These four columns have no dependent constraints, so the
    # portable native DROP COLUMN form is both smaller and lossless here.
    connection = op.get_bind()
    connection.execute(sa.text("DROP INDEX IF EXISTS uq_installation_uuid"))
    for column in (
        "recalculation_processed_generation",
        "recalculation_requested_generation",
        "automatic_control_enabled",
        "installation_uuid",
    ):
        if column in _columns("installation"):
            connection.execute(sa.text(f"ALTER TABLE installation DROP COLUMN {column}"))
