"""Add the manufacturer discharge figures and the applied emission limit."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_soc_dependent_emission"
down_revision = "0017_group_mqtt_telemetry"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    heater_columns = _columns("heater")
    # Existing installations take the documented defaults: ten hours of nominal
    # discharge and a 20% residual emission floor.  They change the plan of a
    # configured installation on purpose; the operator has to enter the figures
    # of their own accumulator.
    if "full_discharge_minutes" not in heater_columns:
        op.add_column(
            "heater",
            sa.Column(
                "full_discharge_minutes",
                sa.Integer(),
                nullable=False,
                server_default="600",
            ),
        )
    if "static_emission_percent" not in heater_columns:
        op.add_column(
            "heater",
            sa.Column(
                "static_emission_percent",
                sa.Float(),
                nullable=False,
                server_default="20.0",
            ),
        )

    # The application tables live in their own store, so this migration also
    # runs where the plan slots are absent.
    if _has_table("automatic_plan_slot") and "heat_limit_json" not in _columns(
        "automatic_plan_slot"
    ):
        op.add_column(
            "automatic_plan_slot",
            sa.Column(
                "heat_limit_json", sa.Text(), nullable=False, server_default="{}"
            ),
        )


def downgrade() -> None:
    if _has_table("automatic_plan_slot") and "heat_limit_json" in _columns(
        "automatic_plan_slot"
    ):
        op.drop_column("automatic_plan_slot", "heat_limit_json")
    heater_columns = _columns("heater")
    if "static_emission_percent" in heater_columns:
        op.drop_column("heater", "static_emission_percent")
    if "full_discharge_minutes" in heater_columns:
        op.drop_column("heater", "full_discharge_minutes")
