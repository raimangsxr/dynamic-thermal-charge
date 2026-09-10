"""Allow and persist the canonical automatic-plan status vocabulary."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0022_canonical_plan_statuses"
down_revision = "0021_plan_deviation_tolerances"
branch_labels = None
depends_on = None


STATUS_CONSTRAINT = (
    "status IN ('VALID', 'CONVERGING', 'DEGRADED', 'INVALID', 'FEASIBLE', "
    "'feasible', 'deficit', 'best_effort', 'preview')"
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _constraint_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {
        item["name"]
        for item in inspector.get_check_constraints(table_name)
        if item.get("name")
    }


def _set_status_constraint(expression: str) -> None:
    names = _constraint_names("automatic_plan")
    with op.batch_alter_table("automatic_plan", recreate="always") as batch:
        if "ck_automatic_plan_status" in names:
            batch.drop_constraint("ck_automatic_plan_status", type_="check")
        batch.create_check_constraint("ck_automatic_plan_status", expression)


def upgrade() -> None:
    if _has_table("automatic_plan"):
        _set_status_constraint(STATUS_CONSTRAINT)


def downgrade() -> None:
    if _has_table("automatic_plan"):
        _set_status_constraint(
            "status IN ('FEASIBLE', 'DEGRADED', 'INVALID', 'feasible', "
            "'deficit', 'best_effort', 'preview')"
        )
