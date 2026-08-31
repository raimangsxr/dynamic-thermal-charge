"""Store the hourly weather points used by a plan.

Revision ID: 0006_hourly_forecast
Revises: 0005_controller_log_events
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_hourly_forecast"
down_revision = "0005_controller_log_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_hour",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("forecast_id", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=False),
        sa.Column("interpolated", sa.Boolean(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["forecast_id"], ["forecast.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("forecast_id", "observed_at", name="uq_forecast_hour"),
    )
    op.create_index(
        "ix_forecast_hour_forecast_time",
        "forecast_hour",
        ["forecast_id", "observed_at"],
    )
    with op.batch_alter_table("plan_slot") as batch:
        batch.add_column(sa.Column("temperature_c", sa.Float(), nullable=True))
        batch.add_column(
            sa.Column("temperature_interpolated", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("plan_slot") as batch:
        batch.drop_column("temperature_interpolated")
        batch.drop_column("temperature_c")
    op.drop_index("ix_forecast_hour_forecast_time", table_name="forecast_hour")
    op.drop_table("forecast_hour")
