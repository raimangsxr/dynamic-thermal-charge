"""Persist the forecast staleness limit and allow indefinite AEMET retries."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_forecast_max_age"
down_revision = "0026_forced_residual_emission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("charge_planning_site"):
        columns = {column["name"] for column in inspector.get_columns("charge_planning_site")}
        if "forecast_max_age_hours" not in columns:
            op.add_column(
                "charge_planning_site",
                sa.Column(
                    "forecast_max_age_hours",
                    sa.Integer(),
                    nullable=False,
                    server_default="30",
                ),
            )
        with op.batch_alter_table("charge_planning_site", recreate="always") as batch:
            names = {
                item.get("name")
                for item in sa.inspect(bind).get_check_constraints("charge_planning_site")
            }
            if "ck_charge_site_forecast_max_age" not in names:
                batch.create_check_constraint(
                    "ck_charge_site_forecast_max_age",
                    "forecast_max_age_hours >= 1 AND forecast_max_age_hours <= 168",
                )
    if inspector.has_table("forecast_cycle"):
        with op.batch_alter_table("forecast_cycle", recreate="always") as batch:
            names = {
                item.get("name")
                for item in sa.inspect(bind).get_check_constraints("forecast_cycle")
            }
            if "ck_forecast_cycle_attempt" in names:
                batch.drop_constraint("ck_forecast_cycle_attempt", type_="check")
            batch.create_check_constraint(
                "ck_forecast_cycle_attempt", "attempt >= 0"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("forecast_cycle"):
        with op.batch_alter_table("forecast_cycle", recreate="always") as batch:
            names = {
                item.get("name")
                for item in sa.inspect(bind).get_check_constraints("forecast_cycle")
            }
            if "ck_forecast_cycle_attempt" in names:
                batch.drop_constraint("ck_forecast_cycle_attempt", type_="check")
            batch.create_check_constraint(
                "ck_forecast_cycle_attempt", "attempt >= 0 AND attempt <= 6"
            )
    if inspector.has_table("charge_planning_site"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns("charge_planning_site")}
        if "forecast_max_age_hours" in columns:
            op.drop_column("charge_planning_site", "forecast_max_age_hours")
