"""Add tolerances used by the periodic plan-deviation check."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_plan_deviation_tolerances"
down_revision = "0020_email_alerts"
branch_labels = None
depends_on = None


ADDITIONS = (
    ("deviation_shortfall_tolerance_c", "0.1"),
    ("deviation_surplus_soc_percent", "5"),
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("charge_planning_site"):
        return
    columns = _columns("charge_planning_site")
    for name, default in ADDITIONS:
        if name not in columns:
            op.add_column(
                "charge_planning_site",
                sa.Column(name, sa.Float(), nullable=False, server_default=default),
            )


def downgrade() -> None:
    if not _has_table("charge_planning_site"):
        return
    columns = _columns("charge_planning_site")
    for name, _default in ADDITIONS:
        if name in columns:
            op.drop_column("charge_planning_site", name)
