"""Generalise operator notifications into the global alert inbox.

The split-store runtime uses the independent active-schema upgrader, while the
legacy compatibility database still follows Alembic. Keep both paths explicit:
existing calibration rows remain readable and are treated as already-resolved
event alerts.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028_global_operator_alerts"
down_revision = "0027_forecast_max_age"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_columns(name)} if inspector.has_table(name) else set()


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table("operator_notification"):
        columns = _columns("operator_notification")
        additions = (
            ("alert_type", sa.Column("alert_type", sa.String(length=64), nullable=False, server_default="thermal_calibration_terminal")),
            ("severity", sa.Column("severity", sa.String(length=16), nullable=False, server_default="info")),
            ("episode_id", sa.Column("episode_id", sa.String(length=36), nullable=True)),
            ("opened_at", sa.Column("opened_at", sa.DateTime(), nullable=True)),
            ("resolved_at", sa.Column("resolved_at", sa.DateTime(), nullable=True)),
        )
        for name, column in additions:
            if name not in columns:
                op.add_column("operator_notification", column)
        op.execute(sa.text("UPDATE operator_notification SET alert_type = kind WHERE alert_type IS NULL OR alert_type = ''"))
        op.execute(sa.text("UPDATE operator_notification SET opened_at = created_at WHERE opened_at IS NULL"))
        op.execute(sa.text("UPDATE operator_notification SET resolved_at = created_at WHERE resolved_at IS NULL AND kind LIKE 'thermal_calibration_%'"))
        inspector = sa.inspect(bind)
        names = {
            item.get("name")
            for item in inspector.get_indexes("operator_notification")
        }
        if "uq_operator_notification_episode" not in names:
            op.create_index(
                "uq_operator_notification_episode",
                "operator_notification",
                ["installation_id", "episode_id"],
                unique=True,
            )

    if _has_table("alert_delivery"):
        columns = _columns("alert_delivery")
        for name, column in (
            ("alert_id", sa.Column("alert_id", sa.Integer(), nullable=True)),
            ("episode_id", sa.Column("episode_id", sa.String(length=36), nullable=True)),
            ("claimed_by", sa.Column("claimed_by", sa.String(length=128), nullable=True)),
            ("claimed_until", sa.Column("claimed_until", sa.DateTime(), nullable=True)),
        ):
            if name not in columns:
                op.add_column("alert_delivery", column)

    if _has_table("web_push_attempt"):
        columns = _columns("web_push_attempt")
        for name, column in (
            ("alert_id", sa.Column("alert_id", sa.Integer(), nullable=True)),
            ("claimed_by", sa.Column("claimed_by", sa.String(length=128), nullable=True)),
            ("claimed_until", sa.Column("claimed_until", sa.DateTime(), nullable=True)),
        ):
            if name not in columns:
                op.add_column("web_push_attempt", column)
        inspector = sa.inspect(bind)
        names = {
            item.get("name") for item in inspector.get_indexes("web_push_attempt")
        }
        if "uq_web_push_attempt_alert_browser" not in names:
            op.create_index(
                "uq_web_push_attempt_alert_browser",
                "web_push_attempt",
                ["alert_id", "subscription_id"],
                unique=True,
            )


def downgrade() -> None:
    if _has_table("web_push_attempt"):
        names = {
            item.get("name")
            for item in sa.inspect(op.get_bind()).get_indexes("web_push_attempt")
        }
        if "uq_web_push_attempt_alert_browser" in names:
            op.drop_index("uq_web_push_attempt_alert_browser", table_name="web_push_attempt")
        if "alert_id" in _columns("web_push_attempt"):
            op.drop_column("web_push_attempt", "alert_id")
        for name in ("claimed_until", "claimed_by"):
            if name in _columns("web_push_attempt"):
                op.drop_column("web_push_attempt", name)
    if _has_table("alert_delivery"):
        for name in ("claimed_until", "claimed_by", "episode_id", "alert_id"):
            if name in _columns("alert_delivery"):
                op.drop_column("alert_delivery", name)
    if _has_table("operator_notification"):
        names = {
            item.get("name")
            for item in sa.inspect(op.get_bind()).get_indexes("operator_notification")
        }
        if "uq_operator_notification_episode" in names:
            op.drop_index("uq_operator_notification_episode", table_name="operator_notification")
        for name in ("resolved_at", "opened_at", "episode_id", "severity", "alert_type"):
            if name in _columns("operator_notification"):
                op.drop_column("operator_notification", name)
