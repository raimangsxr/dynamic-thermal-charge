"""Persist five-minute measured history used by the analysis charts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_measured_history_and_chart_cues"
down_revision = "0028_global_operator_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("measured_installation_sample"):
        op.create_table(
            "measured_installation_sample",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("installation_id", sa.Integer(), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("outdoor_temperature_c", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "installation_id",
                "observed_at",
                name="uq_measured_installation_sample",
            ),
        )
    names = {
        item.get("name") for item in sa.inspect(bind).get_indexes("measured_installation_sample")
    }
    if "ix_measured_installation_sample_installation_time" not in names:
        op.create_index(
            "ix_measured_installation_sample_installation_time",
            "measured_installation_sample",
            ["installation_id", "observed_at"],
        )

    if not sa.inspect(bind).has_table("measured_heater_sample"):
        op.create_table(
            "measured_heater_sample",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("installation_id", sa.Integer(), nullable=False),
            sa.Column("heater_id", sa.String(length=64), nullable=False),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.Column("indoor_temperature_c", sa.Float(), nullable=True),
            sa.Column("stored_soc_percent", sa.Float(), nullable=True),
            sa.Column("stored_energy_kwh", sa.Float(), nullable=True),
            sa.Column("confirmed_charge_power_w", sa.Integer(), nullable=True),
            sa.Column("discharge_commanded", sa.Boolean(), nullable=True),
            sa.Column("damper_position_percent", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "installation_id",
                "heater_id",
                "observed_at",
                name="uq_measured_heater_sample",
            ),
        )
    names = {
        item.get("name") for item in sa.inspect(bind).get_indexes("measured_heater_sample")
    }
    if "ix_measured_heater_sample_installation_heater_time" not in names:
        op.create_index(
            "ix_measured_heater_sample_installation_heater_time",
            "measured_heater_sample",
            ["installation_id", "heater_id", "observed_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("measured_heater_sample"):
        indexes = {
            item.get("name") for item in inspector.get_indexes("measured_heater_sample")
        }
        if "ix_measured_heater_sample_installation_heater_time" in indexes:
            op.drop_index(
                "ix_measured_heater_sample_installation_heater_time",
                table_name="measured_heater_sample",
            )
        op.drop_table("measured_heater_sample")
    if inspector.has_table("measured_installation_sample"):
        indexes = {
            item.get("name")
            for item in inspector.get_indexes("measured_installation_sample")
        }
        if "ix_measured_installation_sample_installation_time" in indexes:
            op.drop_index(
                "ix_measured_installation_sample_installation_time",
                table_name="measured_installation_sample",
            )
        op.drop_table("measured_installation_sample")
