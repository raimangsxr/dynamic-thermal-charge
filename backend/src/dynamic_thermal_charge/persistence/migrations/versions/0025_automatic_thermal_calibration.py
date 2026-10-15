"""Introduce the one-room-per-accumulator aggregate and calibration state."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0025_automatic_thermal_calibration"
down_revision = "0024_planning_calculation_coordination"
branch_labels = None
depends_on = None


ROOM_STATUSES = (
    "'approximate','estimated','calibrating','calibrated','failed','cancelled','manually_adjusted'"
)


def upgrade() -> None:
    op.create_table(
        "outdoor_temperature",
        sa.Column("installation_id", sa.Integer(), primary_key=True),
        sa.Column("temperature_c", sa.Float(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "temperature_c >= -60 AND temperature_c <= 60",
            name="ck_outdoor_temperature_range",
        ),
    )
    op.create_table(
        "room",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("heater_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("room_thermal_capacity_kwh_per_c", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("room_heat_loss_kw_per_c", sa.Float(), nullable=False, server_default="0.12"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="approximate"),
        sa.Column("terminal_result_json", sa.Text(), nullable=True),
        sa.Column("terminal_cause", sa.String(length=512), nullable=True),
        sa.Column("terminal_at", sa.DateTime(), nullable=True),
        sa.Column("applied_session_id", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["heater_id"], ["heater.id"], ondelete="CASCADE"),
        sa.CheckConstraint("room_thermal_capacity_kwh_per_c > 0", name="ck_room_capacity_positive"),
        sa.CheckConstraint("room_heat_loss_kw_per_c >= 0", name="ck_room_loss_nonnegative"),
        sa.CheckConstraint(f"status IN ({ROOM_STATUSES})", name="ck_room_status"),
        sa.Index("ix_room_heater", "heater_id"),
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("thermal_profile"):
        op.execute(
            sa.text(
                "INSERT INTO room (heater_id, room_thermal_capacity_kwh_per_c, "
                "room_heat_loss_kw_per_c, status, updated_at) "
                "SELECT h.id, COALESCE(t.room_thermal_capacity_kwh_per_c, 2.5), "
                "COALESCE(t.room_heat_loss_kw_per_c, 0.12), "
                "CASE WHEN COALESCE(t.room_thermal_capacity_kwh_per_c, 2.5) = 2.5 "
                "AND COALESCE(t.room_heat_loss_kw_per_c, 0.12) = 0.12 "
                "THEN 'approximate' ELSE 'manually_adjusted' END, CURRENT_TIMESTAMP "
                "FROM heater h LEFT JOIN thermal_profile t ON t.heater_id = h.id"
            )
        )
        op.drop_table("thermal_profile")
    else:
        op.execute(
            sa.text(
                "INSERT INTO room (heater_id, room_thermal_capacity_kwh_per_c, "
                "room_heat_loss_kw_per_c, status, updated_at) "
                "SELECT id, 2.5, 0.12, 'approximate', CURRENT_TIMESTAMP FROM heater"
            )
        )

    op.create_table(
        "thermal_calibration_session",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("phase_deadline_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("missing_since_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("commands_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("terminal_cause", sa.String(length=512), nullable=True),
        sa.UniqueConstraint("installation_id", "heater_id", name="uq_calibration_active_heater"),
        sa.CheckConstraint("status = 'active'", name="ck_calibration_session_status"),
        sa.CheckConstraint(
            "phase IN ('baseline','charge','release','cool','fit','applying')",
            name="ck_calibration_session_phase",
        ),
        sa.Index("ix_calibration_session_installation", "installation_id", "updated_at"),
    )
    op.create_table(
        "thermal_calibration_sample",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("indoor_temperature_c", sa.Float(), nullable=False),
        sa.Column("outdoor_temperature_c", sa.Float(), nullable=False),
        sa.Column("soc_percent", sa.Float(), nullable=False),
        sa.Column("discharge_enabled", sa.Boolean(), nullable=False),
        sa.Column("damper_position_percent", sa.Float(), nullable=True),
        sa.Column("heat_delivered_kwh", sa.Float(), nullable=False, server_default="0"),
        sa.Column("synchronized", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("phase", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["thermal_calibration_session.id"], ondelete="CASCADE"),
        sa.CheckConstraint("soc_percent >= 0 AND soc_percent <= 100", name="ck_calibration_sample_soc"),
        sa.CheckConstraint("heat_delivered_kwh >= 0", name="ck_calibration_sample_heat"),
        sa.Index("ix_calibration_sample_session_time", "session_id", "observed_at"),
    )
    op.create_table(
        "operator_notification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("installation_id", "session_id", name="uq_operator_notification_session"),
        sa.Index("ix_operator_notification_installation", "installation_id", "created_at"),
    )
    op.create_table(
        "web_push_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=160), nullable=False),
        sa.Column("browser_id", sa.String(length=160), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.UniqueConstraint("installation_id", "user_id", "browser_id", name="uq_web_push_browser"),
        sa.UniqueConstraint("installation_id", "endpoint", name="uq_web_push_endpoint"),
        sa.CheckConstraint("status IN ('active','revoked','expired','error')", name="ck_web_push_subscription_status"),
    )
    op.create_table(
        "web_push_attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["subscription_id"], ["web_push_subscription.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("session_id", "subscription_id", name="uq_web_push_attempt_session_browser"),
        sa.CheckConstraint("status IN ('pending','sent','denied','unsupported','expired','error')", name="ck_web_push_attempt_status"),
    )


def downgrade() -> None:
    op.drop_table("outdoor_temperature")
    op.drop_table("web_push_attempt")
    op.drop_table("web_push_subscription")
    op.drop_table("operator_notification")
    op.drop_table("thermal_calibration_sample")
    op.drop_table("thermal_calibration_session")
    op.create_table(
        "thermal_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("heater_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("room_thermal_capacity_kwh_per_c", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("room_heat_loss_kw_per_c", sa.Float(), nullable=False, server_default="0.12"),
        sa.ForeignKeyConstraint(["heater_id"], ["heater.id"], ondelete="CASCADE"),
    )
    op.execute(
        sa.text(
            "INSERT INTO thermal_profile (heater_id, room_thermal_capacity_kwh_per_c, room_heat_loss_kw_per_c) "
            "SELECT heater_id, room_thermal_capacity_kwh_per_c, room_heat_loss_kw_per_c FROM room"
        )
    )
    op.drop_table("room")
