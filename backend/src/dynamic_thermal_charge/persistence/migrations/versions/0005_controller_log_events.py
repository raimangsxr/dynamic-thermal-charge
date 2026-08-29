"""Bounded controller event projection for the operator panel.

Revision ID: 0005_controller_log_events
Revises: 0004_relay_test_mode
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_controller_log_events"
down_revision = "0004_relay_test_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "controller_log_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("logger", sa.String(160), nullable=False),
        sa.Column("message", sa.String(2048), nullable=False),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_controller_log_event_installation_id", "controller_log_event", ["installation_id", "id"])
    op.create_index("ix_controller_log_event_installation_time", "controller_log_event", ["installation_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("controller_log_event")
