"""Indoor temperature configuration and latest readings.

Revision ID: 0003_indoor_temperature
Revises: 0002_controller_heartbeat
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_indoor_temperature"
down_revision = "0002_controller_heartbeat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "heater", sa.Column("indoor_topic", sa.String(length=512), nullable=True)
    )
    # Plain ADD COLUMN is intentionally used instead of Alembic batch mode:
    # recreating ``installation`` on SQLite can trigger its ON DELETE cascades.
    op.add_column(
        "installation",
        sa.Column(
            "indoor_max_age_minutes",
            sa.Integer(),
            sa.CheckConstraint(
                "indoor_max_age_minutes > 0",
                name="ck_installation_indoor_max_age",
            ),
            server_default="30",
            nullable=False,
        ),
    )
    op.add_column(
        "installation",
        sa.Column(
            "indoor_min_plausible_c",
            sa.Float(),
            server_default="-20",
            nullable=False,
        ),
    )
    op.add_column(
        "installation",
        sa.Column(
            "indoor_max_plausible_c",
            sa.Float(),
            sa.CheckConstraint(
                "indoor_min_plausible_c < indoor_max_plausible_c",
                name="ck_installation_indoor_range",
            ),
            server_default="50",
            nullable=False,
        ),
    )
    op.create_table(
        "indoor_reading",
        sa.Column("heater_pk", sa.Integer(), nullable=False),
        sa.Column("celsius", sa.Float(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["heater_pk"], ["heater.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("heater_pk"),
    )


def downgrade() -> None:
    op.drop_table("indoor_reading")
    op.drop_column("installation", "indoor_max_plausible_c")
    op.drop_column("installation", "indoor_min_plausible_c")
    op.drop_column("installation", "indoor_max_age_minutes")
    op.drop_column("heater", "indoor_topic")
