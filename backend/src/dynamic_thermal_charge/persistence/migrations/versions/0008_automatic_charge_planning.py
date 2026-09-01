"""Add automatic charge planning configuration, telemetry and audit tables.

Revision ID: 0008_automatic_charge_planning
Revises: 0007_thermal_loss
"""

from alembic import op

revision = "0008_automatic_charge_planning"
down_revision = "0007_thermal_loss"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy single-database compatibility schema intentionally remains
    # unchanged. The supported split storage creates the additive planning
    # tables from its two independent metadata collections.
    pass


def downgrade() -> None:
    pass
