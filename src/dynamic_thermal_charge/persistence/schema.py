"""Core table definitions. See specs/001-config-database/data-model.md.

Two conventions run through the whole schema:

* **Instants** are stored as naive UTC in ``DateTime`` columns. SQLite has no
  native temporal type and discards timezone information while PostgreSQL keeps
  it, so a single rule is the only way FR-002 (identical behaviour on both
  engines) can hold. ``mapping.py`` owns the conversion; nothing above it ever
  sees a naive datetime.
* **Physical quantities** are integers: watts and minutes, never kilowatts or
  fractional hours.

``CHECK`` constraints are restricted to the subset that compiles identically on
SQLite and PostgreSQL. Everything that would need a partial index or an
engine-specific expression is validated in the domain instead, and listed under
"Delegated to the domain" below, so the two engines cannot drift.

Delegated to the domain (see ``config.py``):

* Uniqueness of GPIO pins, which needs a partial unique index (``WHERE kind =
  'gpio'``) that the two engines do not express alike.
* Alignment of ``start_time`` / ``end_time`` with ``slot_minutes``.
* "A thermal profile requires a weather provider", which spans tables.
* Coherence of the schedule quartet: timezone, start, end and weekdays are all
  present or all absent.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)


metadata = MetaData()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

installation = Table(
    "installation",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), nullable=False),
    # Optimistic locking. Grows monotonically; see research.md D9.
    Column("revision", Integer, nullable=False, server_default="1"),
    Column("max_total_power_w", Integer, nullable=False),
    Column("slot_minutes", Integer, nullable=False),
    Column("window_minutes", Integer, nullable=False),
    Column("timezone", String(64), nullable=True),
    # Local rules, not instants: stored as "HH:MM" text.
    Column("start_time", String(5), nullable=True),
    Column("end_time", String(5), nullable=True),
    # Ascending, comma-separated integers 0-6, Monday=0. Format is normative.
    Column("weekdays", String(32), nullable=True),
    Column("log_level", String(8), nullable=False, server_default="INFO"),
    Column("state_file", String(512), nullable=False),
    Column("poll_seconds", Float, nullable=False, server_default="5"),
    # NULL means unlimited retention.
    Column("retention_days", Integer, nullable=True),
    Column("indoor_max_age_minutes", Integer, nullable=False, server_default="30"),
    Column("indoor_min_plausible_c", Float, nullable=False, server_default="-20"),
    Column("indoor_max_plausible_c", Float, nullable=False, server_default="50"),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    CheckConstraint("revision >= 1", name="ck_installation_revision"),
    CheckConstraint("max_total_power_w > 0", name="ck_installation_power"),
    CheckConstraint(
        "slot_minutes > 0 AND slot_minutes <= 60", name="ck_installation_slot"
    ),
    CheckConstraint("window_minutes > 0", name="ck_installation_window"),
    CheckConstraint("poll_seconds > 0", name="ck_installation_poll"),
    CheckConstraint(
        "retention_days IS NULL OR retention_days > 0",
        name="ck_installation_retention",
    ),
    CheckConstraint(
        "indoor_max_age_minutes > 0", name="ck_installation_indoor_max_age"
    ),
    CheckConstraint(
        "indoor_min_plausible_c < indoor_max_plausible_c",
        name="ck_installation_indoor_range",
    ),
)

weather_config = Table(
    "weather_config",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("provider", String(16), nullable=False),
    Column("aemet_municipality_code", String(5), nullable=True),
    # The NAME of the environment variable, never its value.
    Column("aemet_api_key_env", String(64), nullable=True),
    Column("aemet_timeout_seconds", Float, nullable=True),
    Column("simulated_average_temperature_c", Float, nullable=True),
    Column("simulated_minimum_temperature_c", Float, nullable=True),
    Column("fallback_average_temperature_c", Float, nullable=True),
    Column("fallback_minimum_temperature_c", Float, nullable=True),
    Column("watchdog_retry_minutes", Integer, nullable=False, server_default="15"),
    Column("watchdog_refresh_minutes", Integer, nullable=False, server_default="180"),
    CheckConstraint(
        "provider IN ('simulated', 'aemet')", name="ck_weather_provider"
    ),
    CheckConstraint("watchdog_retry_minutes > 0", name="ck_weather_retry"),
    CheckConstraint("watchdog_refresh_minutes > 0", name="ck_weather_refresh"),
    CheckConstraint(
        "aemet_timeout_seconds IS NULL OR aemet_timeout_seconds > 0",
        name="ck_weather_timeout",
    ),
)

heater = Table(
    "heater",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # The domain identifier, as used in plans and logs.
    Column("heater_id", String(64), nullable=False),
    Column("name", String(120), nullable=False),
    Column("model", String(120), nullable=True),
    Column("power_w", Integer, nullable=False),
    Column("full_charge_minutes", Integer, nullable=False),
    Column("target_charge", Float, nullable=False, server_default="1.0"),
    Column("priority", Integer, nullable=False, server_default="0"),
    Column("enabled", Boolean, nullable=False, server_default="1"),
    Column("indoor_topic", String(512), nullable=True),
    Column("position", Integer, nullable=False),
    UniqueConstraint("installation_id", "heater_id", name="uq_heater_domain_id"),
    UniqueConstraint("installation_id", "position", name="uq_heater_position"),
    CheckConstraint("power_w > 0", name="ck_heater_power"),
    CheckConstraint("full_charge_minutes > 0", name="ck_heater_full_charge"),
    CheckConstraint(
        "target_charge >= 0 AND target_charge <= 1", name="ck_heater_target_charge"
    ),
)

output_config = Table(
    "output_config",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "heater_id",
        Integer,
        ForeignKey("heater.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("kind", String(16), nullable=False, server_default="simulated"),
    Column("pin", Integer, nullable=True),
    Column("active_high", Boolean, nullable=False, server_default="1"),
    CheckConstraint("kind IN ('simulated', 'gpio')", name="ck_output_kind"),
    CheckConstraint("pin IS NULL OR (pin >= 0 AND pin <= 27)", name="ck_output_pin"),
    # Pin uniqueness among GPIO outputs is validated in the domain: a partial
    # unique index is not expressed alike on both engines.
    CheckConstraint(
        "kind <> 'gpio' OR pin IS NOT NULL", name="ck_output_gpio_needs_pin"
    ),
)

thermal_profile = Table(
    "thermal_profile",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "heater_id",
        Integer,
        ForeignKey("heater.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("target_temperature_c", Float, nullable=False),
    Column("design_outdoor_temperature_c", Float, nullable=False),
    Column("thermal_factor", Float, nullable=False, server_default="1.0"),
    Column("min_charge", Float, nullable=False, server_default="0.0"),
    Column("max_charge", Float, nullable=False, server_default="1.0"),
    CheckConstraint(
        "design_outdoor_temperature_c < target_temperature_c",
        name="ck_thermal_design_below_target",
    ),
    CheckConstraint("thermal_factor > 0", name="ck_thermal_factor"),
    CheckConstraint(
        "min_charge >= 0 AND min_charge <= max_charge AND max_charge <= 1",
        name="ck_thermal_charge_bounds",
    ),
)


indoor_reading = Table(
    "indoor_reading",
    metadata,
    Column(
        "heater_pk",
        Integer,
        ForeignKey("heater.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("celsius", Float, nullable=False),
    Column("received_at", DateTime, nullable=False),
)


# --------------------------------------------------------------------------- #
# History: append-only. Nothing updates these rows; only retention deletes.
# --------------------------------------------------------------------------- #

forecast = Table(
    "forecast",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("forecast_date", Date, nullable=False),
    Column("average_temperature_c", Float, nullable=False),
    Column("minimum_temperature_c", Float, nullable=True),
    Column("maximum_temperature_c", Float, nullable=True),
    # 'aemet', 'simulated' or 'fallback'. FR-017.
    Column("source", String(16), nullable=False),
    Column("municipality", String(120), nullable=True),
    Column("retrieved_at", DateTime, nullable=False),
    CheckConstraint(
        "source IN ('aemet', 'simulated', 'fallback')", name="ck_forecast_source"
    ),
    Index("ix_forecast_retention", "installation_id", "retrieved_at"),
)

plan = Table(
    "plan",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Answers "which configuration produced this night's plan".
    Column("installation_revision", Integer, nullable=False),
    Column(
        "forecast_id",
        Integer,
        ForeignKey("forecast.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("window_start", DateTime, nullable=False),
    Column("window_end", DateTime, nullable=False),
    Column("slot_minutes", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    CheckConstraint("window_end > window_start", name="ck_plan_window"),
    Index("ix_plan_retention", "installation_id", "created_at"),
    # Retention must find live plans by window_end; see the active-plan rule.
    Index("ix_plan_window_end", "window_end"),
)

plan_slot = Table(
    "plan_slot",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("plan_id", Integer, ForeignKey("plan.id", ondelete="CASCADE"), nullable=False),
    # Text, NOT a foreign key: history must outlive the heater it refers to.
    Column("heater_id", String(64), nullable=False),
    Column("slot_start", DateTime, nullable=False),
    Column("slot_end", DateTime, nullable=False),
    UniqueConstraint("plan_id", "heater_id", "slot_start", name="uq_plan_slot"),
)

plan_allocation = Table(
    "plan_allocation",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("plan_id", Integer, ForeignKey("plan.id", ondelete="CASCADE"), nullable=False),
    Column("heater_id", String(64), nullable=False),
    Column("requested_minutes", Integer, nullable=False),
    Column("allocated_minutes", Integer, nullable=False),
    # No longer lives only in a WARNING log line.
    Column("unmet_minutes", Integer, nullable=False),
    UniqueConstraint("plan_id", "heater_id", name="uq_plan_allocation"),
    CheckConstraint(
        "requested_minutes >= 0 AND allocated_minutes >= 0 AND unmet_minutes >= 0",
        name="ck_plan_allocation_minutes",
    ),
)

output_transition = Table(
    "output_transition",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("heater_id", String(64), nullable=False),
    # The RESULTING state. Only inserted when it changes (FR-018).
    Column("state", Boolean, nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    Column(
        "plan_id", Integer, ForeignKey("plan.id", ondelete="SET NULL"), nullable=True
    ),
    Index("ix_transition_retention", "installation_id", "occurred_at"),
)

config_change = Table(
    "config_change",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("revision_before", Integer, nullable=False),
    Column("revision_after", Integer, nullable=False),
    Column("entity", String(32), nullable=False),
    Column("entity_key", String(64), nullable=True),
    Column("field", String(64), nullable=True),
    Column("old_value", String(512), nullable=True),
    Column("new_value", String(512), nullable=True),
    Column("action", String(16), nullable=False),
    Column("occurred_at", DateTime, nullable=False),
    CheckConstraint("action IN ('set', 'add', 'remove')", name="ck_change_action"),
    CheckConstraint(
        "revision_after = revision_before + 1", name="ck_change_revision"
    ),
    Index("ix_change_installation", "installation_id", "occurred_at"),
)


controller_heartbeat = Table(
    "controller_heartbeat",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "installation_id",
        Integer,
        ForeignKey("installation.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    # Instant of the last heartbeat. This row is UPDATED, never appended to, so
    # it does not grow and is deliberately excluded from the retention policy.
    Column("updated_at", DateTime, nullable=False),
    # When the publishing process started. Moving backwards is the cheap signal
    # that a second controller is alive (FR-053).
    Column("started_at", DateTime, nullable=False),
    Column("degraded", Boolean, nullable=False),
    Column(
        "plan_id", Integer, ForeignKey("plan.id", ondelete="SET NULL"), nullable=True
    ),
    # The cadence the controller is ACTUALLY running with, which may differ from
    # the stored configuration if it started before the last edit. The staleness
    # tolerance derives from this, not from the configuration.
    Column("poll_seconds", Float, nullable=False),
    Column("driver_kind", String(16), nullable=False),
    # Random per-process identifier, stable while the process lives. Two
    # controllers share this single row, so without it they look like one.
    Column("runner_id", String(64), nullable=False),
    CheckConstraint("poll_seconds > 0", name="ck_heartbeat_poll"),
    CheckConstraint(
        "driver_kind IN ('simulated', 'gpio')", name="ck_heartbeat_driver"
    ),
)


# Constraint name -> (field, human explanation). Used to turn an IntegrityError
# into an actionable ConfigValidationError instead of a generic one: a constraint
# violation is invalid *configuration*, never an unavailable database, and the
# distinction matters because only unavailability is retried by the control loop.
CONSTRAINT_FIELDS: dict[str, tuple[str, str]] = {
    "ck_installation_revision": ("revision", "revision must be at least 1"),
    "ck_installation_power": (
        "max_total_power_kw",
        "the maximum simultaneous power must be positive",
    ),
    "ck_installation_slot": (
        "slot_minutes",
        "slot_minutes must be between 1 and 60",
    ),
    "ck_installation_window": ("window_minutes", "the charge window must be positive"),
    "ck_installation_poll": ("poll_seconds", "poll_seconds must be positive"),
    "ck_installation_retention": (
        "retention_days",
        "retention_days must be positive, or unset for unlimited retention",
    ),
    "ck_installation_indoor_max_age": (
        "indoor_max_age_minutes",
        "indoor_max_age_minutes must be positive",
    ),
    "ck_installation_indoor_range": (
        "indoor_min_plausible_c",
        "indoor_min_plausible_c must be lower than indoor_max_plausible_c",
    ),
    "ck_weather_provider": ("provider", "the provider must be simulated or aemet"),
    "ck_weather_retry": ("retry_minutes", "retry_minutes must be positive"),
    "ck_weather_refresh": ("refresh_minutes", "refresh_minutes must be positive"),
    "ck_weather_timeout": ("timeout_seconds", "timeout_seconds must be positive"),
    "ck_heater_power": ("power_kw", "the heater power must be positive"),
    "ck_heater_full_charge": (
        "full_charge_hours",
        "the full charge time must be positive",
    ),
    "ck_heater_target_charge": (
        "target_charge",
        "target_charge must be between 0 and 1",
    ),
    "uq_heater_domain_id": ("heater_id", "heater ids must be unique per installation"),
    "uq_heater_position": ("position", "heater positions must be unique"),
    "ck_output_kind": ("output_type", "the output type must be simulated or gpio"),
    "ck_output_pin": ("pin", "a GPIO pin must be between 0 and 27"),
    "ck_output_gpio_needs_pin": ("pin", "a gpio output requires a BCM pin"),
    "ck_thermal_design_below_target": (
        "design_outdoor_temperature_c",
        "the design outdoor temperature must be below the target temperature",
    ),
    "ck_thermal_factor": ("thermal_factor", "thermal_factor must be positive"),
    "ck_thermal_charge_bounds": (
        "min_charge",
        "the charge limits must satisfy 0 <= min_charge <= max_charge <= 1",
    ),
    "ck_forecast_source": ("source", "the forecast source is not recognised"),
    "ck_plan_window": ("window_end", "the plan window must end after it starts"),
    "ck_plan_allocation_minutes": (
        "allocated_minutes",
        "plan minutes cannot be negative",
    ),
    "uq_plan_slot": (
        "slot_start",
        "a plan cannot record the same heater twice in the same slot",
    ),
    "uq_plan_allocation": (
        "heater_id",
        "a plan cannot record two allocations for the same heater",
    ),
    "ck_change_action": ("action", "the change action is not recognised"),
    "ck_change_revision": ("revision_after", "revisions must advance by exactly one"),
    "ck_heartbeat_poll": ("poll_seconds", "the polling cadence must be positive"),
    "ck_heartbeat_driver": (
        "driver_kind",
        "the driver kind must be simulated or gpio",
    ),
}


# Tables the retention policy may delete from, and the column it filters on.
#
# Two tables are deliberately absent:
#   * config_change     -- the only trace of who changed the configuration.
#   * controller_heartbeat -- a single row that is updated in place, so it never
#     grows. Pruning it would only ever delete the proof that the controller is
#     alive, which is the opposite of what retention is for.
# See data-model.md of both features.
RETAINED_TABLES: tuple[tuple[Table, str], ...] = (
    (output_transition, "occurred_at"),
    (plan, "created_at"),
    (forecast, "retrieved_at"),
)

CONFIG_TABLES = (installation, weather_config, heater, output_config, thermal_profile)
HISTORY_TABLES = (
    forecast,
    plan,
    plan_slot,
    plan_allocation,
    output_transition,
    config_change,
)

__all__ = [
    "CONFIG_TABLES",
    "CONSTRAINT_FIELDS",
    "controller_heartbeat",
    "HISTORY_TABLES",
    "RETAINED_TABLES",
    "config_change",
    "forecast",
    "heater",
    "installation",
    "metadata",
    "output_config",
    "output_transition",
    "plan",
    "plan_allocation",
    "plan_slot",
    "thermal_profile",
    "weather_config",
]
