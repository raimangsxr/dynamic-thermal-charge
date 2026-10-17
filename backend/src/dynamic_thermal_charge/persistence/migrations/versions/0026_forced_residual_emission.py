"""Persist the residual and controlled heat decomposition per plan slot."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_forced_residual_emission"
down_revision = "0025_automatic_thermal_calibration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("automatic_plan_slot"):
        columns = {column["name"] for column in inspector.get_columns("automatic_plan_slot")}
        if "forced_heat_json" not in columns:
            op.add_column(
                "automatic_plan_slot",
                sa.Column("forced_heat_json", sa.Text(), nullable=False, server_default="{}"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("automatic_plan_slot"):
        columns = {column["name"] for column in inspector.get_columns("automatic_plan_slot")}
        if "forced_heat_json" in columns:
            op.drop_column("automatic_plan_slot", "forced_heat_json")
