"""Remove the obsolete file-backed active-plan setting.

Revision ID: 0009_remove_state_file
Revises: 0008_automatic_charge_planning
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_remove_state_file"
down_revision = "0008_automatic_charge_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("installation", "state_file")


def downgrade() -> None:
    op.add_column(
        "installation",
        sa.Column(
            "state_file",
            sa.String(length=512),
            nullable=False,
            server_default="/var/lib/dynamic-thermal-charge/active-plan.json",
        ),
    )
