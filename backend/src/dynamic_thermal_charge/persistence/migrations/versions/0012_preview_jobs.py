"""Persist asynchronous planning previews and their ordered checks.

The split store applies the same additive tables through ``active_schema``;
this revision keeps the compatibility Alembic database on the same contract.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_preview_jobs"
down_revision = "0011_planning_base_load"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preview_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("constraints_revision", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_detail", sa.String(512)),
        sa.CheckConstraint("status IN ('queued','running','cancelling','completed','error','cancelled','interrupted')", name="ck_preview_job_status"),
    )
    op.create_index("ix_preview_job_installation_requested", "preview_job", ["installation_id", "requested_at"])
    op.create_table(
        "preview_job_step",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("detail", sa.String(512)),
        sa.ForeignKeyConstraint(["job_id"], ["preview_job.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", "name", name="uq_preview_job_step_name"),
        sa.UniqueConstraint("job_id", "position", name="uq_preview_job_step_position"),
        sa.CheckConstraint("status IN ('pending','running','completed','error','cancelled','skipped')", name="ck_preview_job_step_status"),
    )
    op.create_index("ix_preview_job_step_job_position", "preview_job_step", ["job_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_preview_job_step_job_position", table_name="preview_job_step")
    op.drop_table("preview_job_step")
    op.drop_index("ix_preview_job_installation_requested", table_name="preview_job")
    op.drop_table("preview_job")
