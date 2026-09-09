"""Add the per-accumulator setpoint topic used by the discharge command."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_discharge_setpoint_topic"
down_revision = "0018_soc_dependent_emission"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if _has_table("heater_charge_config") and "setpoint_topic" not in _columns(
        "heater_charge_config"
    ):
        op.add_column(
            "heater_charge_config",
            sa.Column("setpoint_topic", sa.String(length=512), nullable=True),
        )


def downgrade() -> None:
    if _has_table("heater_charge_config") and "setpoint_topic" in _columns(
        "heater_charge_config"
    ):
        op.drop_column("heater_charge_config", "setpoint_topic")
