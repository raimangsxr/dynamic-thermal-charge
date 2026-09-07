"""Add accelerated accumulator simulation settings and samples."""

from __future__ import annotations

revision = "0014_accelerated_simulation"
down_revision = "0013_configurable_solver_time_limit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy single-database compatibility schema deliberately does not
    # materialise split planning tables. The active configuration/application
    # schemas apply this change through active_schema revisions 8 and 5.
    pass


def downgrade() -> None:
    pass
