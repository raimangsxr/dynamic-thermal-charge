"""Store the configured thermal loss used by the 48-hour reserve projection.

Revision ID: 0007_thermal_loss
Revises: 0006_hourly_forecast
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_thermal_loss"
down_revision = "0006_hourly_forecast"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("thermal_profile") as batch:
        batch.add_column(
            sa.Column(
                "thermal_loss_c_per_hour",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("thermal_profile") as batch:
        batch.drop_column("thermal_loss_c_per_hour")
