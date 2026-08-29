"""Initial schema: configuration and history.

Revision ID: 0001_initial_schema
Revises: None

The DDL is written out explicitly rather than calling ``metadata.create_all()``.

That is not stylistic. A migration that builds from live metadata is not pinned
in time: it creates whatever ``schema.py`` happens to describe today, so the
moment a later revision adds a table or a column, this revision creates it too
and the later one fails with "already exists". That is exactly what happened when
`0002_controller_heartbeat` arrived, and it is why every revision from here on
states its own DDL and never imports the schema module.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_total_power_w", sa.Integer(), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("start_time", sa.String(length=5), nullable=True),
        sa.Column("end_time", sa.String(length=5), nullable=True),
        sa.Column("weekdays", sa.String(length=32), nullable=True),
        sa.Column("log_level", sa.String(length=8), nullable=False, server_default="INFO"),
        sa.Column("state_file", sa.String(length=512), nullable=False),
        sa.Column("poll_seconds", sa.Float(), nullable=False, server_default="5"),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint('poll_seconds > 0', name="ck_installation_poll"),
        sa.CheckConstraint('max_total_power_w > 0', name="ck_installation_power"),
        sa.CheckConstraint('retention_days IS NULL OR retention_days > 0', name="ck_installation_retention"),
        sa.CheckConstraint('revision >= 1', name="ck_installation_revision"),
        sa.CheckConstraint('slot_minutes > 0 AND slot_minutes <= 60', name="ck_installation_slot"),
        sa.CheckConstraint('window_minutes > 0', name="ck_installation_window"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "weather_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("aemet_municipality_code", sa.String(length=5), nullable=True),
        sa.Column("aemet_api_key_env", sa.String(length=64), nullable=True),
        sa.Column("aemet_timeout_seconds", sa.Float(), nullable=True),
        sa.Column("simulated_average_temperature_c", sa.Float(), nullable=True),
        sa.Column("simulated_minimum_temperature_c", sa.Float(), nullable=True),
        sa.Column("fallback_average_temperature_c", sa.Float(), nullable=True),
        sa.Column("fallback_minimum_temperature_c", sa.Float(), nullable=True),
        sa.Column("watchdog_retry_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("watchdog_refresh_minutes", sa.Integer(), nullable=False, server_default="180"),
        sa.CheckConstraint("provider IN ('simulated', 'aemet')", name="ck_weather_provider"),
        sa.CheckConstraint('watchdog_refresh_minutes > 0', name="ck_weather_refresh"),
        sa.CheckConstraint('watchdog_retry_minutes > 0', name="ck_weather_retry"),
        sa.CheckConstraint('aemet_timeout_seconds IS NULL OR aemet_timeout_seconds > 0', name="ck_weather_timeout"),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )

    op.create_table(
        "heater",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("power_w", sa.Integer(), nullable=False),
        sa.Column("full_charge_minutes", sa.Integer(), nullable=False),
        sa.Column("target_charge", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint('full_charge_minutes > 0', name="ck_heater_full_charge"),
        sa.CheckConstraint('power_w > 0', name="ck_heater_power"),
        sa.CheckConstraint('target_charge >= 0 AND target_charge <= 1', name="ck_heater_target_charge"),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", "heater_id", name="uq_heater_domain_id"),
        sa.UniqueConstraint("installation_id", "position", name="uq_heater_position"),
    )

    op.create_table(
        "output_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="simulated"),
        sa.Column("pin", sa.Integer(), nullable=True),
        sa.Column("active_high", sa.Boolean(), nullable=False, server_default="1"),
        sa.CheckConstraint("kind <> 'gpio' OR pin IS NOT NULL", name="ck_output_gpio_needs_pin"),
        sa.CheckConstraint("kind IN ('simulated', 'gpio')", name="ck_output_kind"),
        sa.CheckConstraint('pin IS NULL OR (pin >= 0 AND pin <= 27)', name="ck_output_pin"),
        sa.ForeignKeyConstraint(["heater_id"], ["heater.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("heater_id"),
    )

    op.create_table(
        "thermal_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.Integer(), nullable=False),
        sa.Column("target_temperature_c", sa.Float(), nullable=False),
        sa.Column("design_outdoor_temperature_c", sa.Float(), nullable=False),
        sa.Column("thermal_factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("min_charge", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("max_charge", sa.Float(), nullable=False, server_default="1.0"),
        sa.CheckConstraint('min_charge >= 0 AND min_charge <= max_charge AND max_charge <= 1', name="ck_thermal_charge_bounds"),
        sa.CheckConstraint('design_outdoor_temperature_c < target_temperature_c', name="ck_thermal_design_below_target"),
        sa.CheckConstraint('thermal_factor > 0', name="ck_thermal_factor"),
        sa.ForeignKeyConstraint(["heater_id"], ["heater.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("heater_id"),
    )

    op.create_table(
        "forecast",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("forecast_date", sa.Date(), nullable=False),
        sa.Column("average_temperature_c", sa.Float(), nullable=False),
        sa.Column("minimum_temperature_c", sa.Float(), nullable=True),
        sa.Column("maximum_temperature_c", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("municipality", sa.String(length=120), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source IN ('aemet', 'simulated', 'fallback')", name="ck_forecast_source"),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecast_retention", "forecast", ["installation_id", "retrieved_at"])

    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("installation_revision", sa.Integer(), nullable=False),
        sa.Column("forecast_id", sa.Integer(), nullable=True),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint('window_end > window_start', name="ck_plan_window"),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["forecast_id"], ["forecast.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_retention", "plan", ["installation_id", "created_at"])
    op.create_index("ix_plan_window_end", "plan", ["window_end"])

    op.create_table(
        "plan_slot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("slot_start", sa.DateTime(), nullable=False),
        sa.Column("slot_end", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "heater_id", "slot_start", name="uq_plan_slot"),
    )

    op.create_table(
        "plan_allocation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column("allocated_minutes", sa.Integer(), nullable=False),
        sa.Column("unmet_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint('requested_minutes >= 0 AND allocated_minutes >= 0 AND unmet_minutes >= 0', name="ck_plan_allocation_minutes"),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "heater_id", name="uq_plan_allocation"),
    )

    op.create_table(
        "output_transition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transition_retention", "output_transition", ["installation_id", "occurred_at"])

    op.create_table(
        "config_change",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("entity_key", sa.String(length=64), nullable=True),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column("old_value", sa.String(length=512), nullable=True),
        sa.Column("new_value", sa.String(length=512), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('set', 'add', 'remove')", name="ck_change_action"),
        sa.CheckConstraint('revision_after = revision_before + 1', name="ck_change_revision"),
        sa.ForeignKeyConstraint(["installation_id"], ["installation.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_change_installation", "config_change", ["installation_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("config_change")
    op.drop_table("output_transition")
    op.drop_table("plan_allocation")
    op.drop_table("plan_slot")
    op.drop_table("plan")
    op.drop_table("forecast")
    op.drop_table("thermal_profile")
    op.drop_table("output_config")
    op.drop_table("heater")
    op.drop_table("weather_config")
    op.drop_table("installation")
