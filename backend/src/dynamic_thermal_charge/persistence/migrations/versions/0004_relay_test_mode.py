"""Relay-test coordination, results and auditable events.

Revision ID: 0004_relay_test_mode
Revises: 0003_indoor_temperature
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_relay_test_mode"
down_revision = "0003_indoor_temperature"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("relay_test_control", sa.Column("installation_id", sa.Integer(), primary_key=True), sa.Column("session_id", sa.String(36)), sa.Column("fault_latched", sa.Boolean(), nullable=False, server_default="0"), sa.Column("fault_generation", sa.Integer(), nullable=False, server_default="0"), sa.Column("fault_session_id", sa.String(36)), sa.Column("fault_reason", sa.String(64)), sa.Column("fault_latched_at", sa.DateTime()), sa.Column("fault_recovery_attempted_at", sa.DateTime()), sa.Column("fault_recovered_at", sa.DateTime()), sa.Column("audit_degraded", sa.Boolean(), nullable=False, server_default="0"), sa.Column("audit_degraded_since", sa.DateTime()), sa.Column("updated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"), sa.CheckConstraint("fault_generation >= 0", name="ck_relay_test_fault_generation"))
    op.create_table("relay_test_session", sa.Column("id", sa.String(36), primary_key=True), sa.Column("installation_id", sa.Integer(), nullable=False), sa.Column("owner_credential_digest", sa.String(64), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("installation_revision", sa.Integer(), nullable=False), sa.Column("requested_at", sa.DateTime(), nullable=False), sa.Column("activated_at", sa.DateTime()), sa.Column("lease_expires_at", sa.DateTime(), nullable=False), sa.Column("last_owner_seen_at", sa.DateTime(), nullable=False), sa.Column("controller_runner_id", sa.String(64)), sa.Column("ending_requested_at", sa.DateTime()), sa.Column("ended_at", sa.DateTime()), sa.Column("end_reason", sa.String(64)), sa.Column("failure_detail", sa.String(512)), sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"), sa.CheckConstraint("status IN ('starting','active','ending','ended','failed')", name="ck_relay_test_session_status"))
    op.create_index("ix_relay_test_session_installation_requested", "relay_test_session", ["installation_id", "requested_at"])
    op.create_table("relay_test_output", sa.Column("session_id", sa.String(36), primary_key=True), sa.Column("heater_id", sa.String(64), primary_key=True), sa.Column("heater_name", sa.String(120), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("power_w", sa.Integer(), nullable=False), sa.Column("desired_state", sa.Boolean(), nullable=False, server_default="0"), sa.Column("command_seq", sa.Integer(), nullable=False, server_default="0"), sa.Column("requested_at", sa.DateTime()), sa.Column("confirmed_state", sa.Boolean()), sa.Column("confirmed_seq", sa.Integer()), sa.Column("confirmed_at", sa.DateTime()), sa.Column("result", sa.String(16), nullable=False, server_default="idle"), sa.Column("result_code", sa.String(64)), sa.Column("result_detail", sa.String(512)), sa.ForeignKeyConstraint(["session_id"], ["relay_test_session.id"], ondelete="CASCADE"), sa.CheckConstraint("power_w > 0", name="ck_relay_test_output_power"), sa.CheckConstraint("result IN ('idle','pending','confirmed','rejected','unknown')", name="ck_relay_test_output_result"))
    op.create_index("ix_relay_test_output_session_position", "relay_test_output", ["session_id", "position"])
    op.create_table("relay_test_event", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("installation_id", sa.Integer(), nullable=False), sa.Column("session_id", sa.String(36), nullable=False), sa.Column("kind", sa.String(32), nullable=False), sa.Column("heater_id", sa.String(64)), sa.Column("requested_state", sa.Boolean()), sa.Column("result", sa.String(16), nullable=False), sa.Column("code", sa.String(64)), sa.Column("occurred_at", sa.DateTime(), nullable=False), sa.Column("detail", sa.String(512)), sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"))
    op.create_index("ix_relay_test_event_installation_occurred", "relay_test_event", ["installation_id", "occurred_at", "id"])
    op.execute("INSERT INTO relay_test_control (installation_id, fault_latched, fault_generation, audit_degraded, updated_at) SELECT id, 0, 0, 0, CURRENT_TIMESTAMP FROM installation")

def downgrade() -> None:
    # The operator must make the electrical state safe before a schema downgrade;
    # refusing a live/latching control row prevents silently discarding that proof.
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT COUNT(*) FROM relay_test_control WHERE session_id IS NOT NULL OR fault_latched = 1")).scalar_one()
    if row:
        raise RuntimeError("cannot downgrade relay-test schema while a session or safety latch exists")
    for name in ("relay_test_event", "relay_test_output", "relay_test_session", "relay_test_control"):
        op.drop_table(name)
