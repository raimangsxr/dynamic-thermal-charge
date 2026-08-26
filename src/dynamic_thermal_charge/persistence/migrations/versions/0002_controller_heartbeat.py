"""Controller heartbeat.

Revision ID: 0002_controller_heartbeat
Revises: 0001_initial_schema

Adds one table and touches nothing that already exists, so it needs no batch
table rewrite and is safe on both engines. This is the first migration that will
run against a real installation's data (FR-048b).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_controller_heartbeat"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "controller_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column("poll_seconds", sa.Float(), nullable=False),
        sa.Column("driver_kind", sa.String(length=16), nullable=False),
        sa.Column("runner_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint("poll_seconds > 0", name="ck_heartbeat_poll"),
        sa.CheckConstraint(
            "driver_kind IN ('simulated', 'gpio')", name="ck_heartbeat_driver"
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["installation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )


def downgrade() -> None:
    op.drop_table("controller_heartbeat")
