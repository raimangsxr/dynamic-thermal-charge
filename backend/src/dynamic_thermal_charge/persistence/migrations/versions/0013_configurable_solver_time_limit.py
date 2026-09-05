"""Add the persisted solver time budget to planning configuration."""

from __future__ import annotations

revision = "0013_configurable_solver_time_limit"
down_revision = "0012_preview_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Planning configuration belongs to the split configuration store. The
    # compatibility Alembic schema intentionally does not materialise it.
    pass


def downgrade() -> None:
    pass
