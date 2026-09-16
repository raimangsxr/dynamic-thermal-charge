"""Coordinate automatic and preview planning calculations across processes."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_planning_calculation_coordination"
down_revision = "0023_coherent_mqtt_topics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planning_calculation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("input_token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.String(512), nullable=True),
        sa.UniqueConstraint(
            "installation_id", "input_token", name="uq_planning_calculation_token"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'error')",
            name="ck_planning_calculation_status",
        ),
        sa.CheckConstraint(
            "kind IN ('automatic', 'preview')", name="ck_planning_calculation_kind"
        ),
        sa.Index(
            "ix_planning_calculation_installation_requested",
            "installation_id",
            "requested_at",
        ),
    )
    op.create_table(
        "planning_lease",
        sa.Column("installation_id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("input_token", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('automatic', 'preview')", name="ck_planning_lease_kind"
        ),
    )


def downgrade() -> None:
    op.drop_table("planning_lease")
    op.drop_index(
        "ix_planning_calculation_installation_requested",
        table_name="planning_calculation",
    )
    op.drop_table("planning_calculation")
