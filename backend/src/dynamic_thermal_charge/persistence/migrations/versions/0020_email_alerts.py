"""Add the email configuration section, the alert catalogue and its queue."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_email_alerts"
down_revision = "0019_discharge_setpoint_topic"
branch_labels = None
depends_on = None


DEFAULT_EMAIL_DOCUMENT = (
    '{"enabled":false,"host":null,"port":587,"recipients":[],'
    '"security":"starttls","sender":null,"timeout_seconds":10.0}'
)


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    # An installation configured before alerts existed reads the default, so
    # sending stays disabled until somebody configures it.
    if _has_table("system_configuration") and "email_json" not in _columns(
        "system_configuration"
    ):
        op.add_column(
            "system_configuration",
            sa.Column(
                "email_json",
                sa.Text(),
                nullable=False,
                server_default=DEFAULT_EMAIL_DOCUMENT,
            ),
        )

    if not _has_table("alert_type_config"):
        op.create_table(
            "alert_type_config",
            sa.Column("name", sa.String(length=64), primary_key=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default="1"
            ),
        )

    if not _has_table("alert_delivery"):
        op.create_table(
            "alert_delivery",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("installation_id", sa.Integer(), nullable=False),
            sa.Column("alert_type", sa.String(length=64), nullable=False),
            sa.Column("subject", sa.String(length=512), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "status", sa.String(length=16), nullable=False, server_default="pending"
            ),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=512), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending', 'sent', 'failed')",
                name="ck_alert_delivery_status",
            ),
            sa.CheckConstraint("attempts >= 0", name="ck_alert_delivery_attempts"),
        )

    if not _has_table("alert_episode"):
        op.create_table(
            "alert_episode",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("installation_id", sa.Integer(), nullable=False),
            sa.Column("alert_type", sa.String(length=64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("since", sa.DateTime(), nullable=True),
            sa.Column("last_enqueued_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "installation_id", "alert_type", name="uq_alert_episode"
            ),
        )


def downgrade() -> None:
    for table_name in ("alert_episode", "alert_delivery", "alert_type_config"):
        if _has_table(table_name):
            op.drop_table(table_name)
    if _has_table("system_configuration") and "email_json" in _columns(
        "system_configuration"
    ):
        op.drop_column("system_configuration", "email_json")
