"""Convert the AEMET automatic cadence from exact minutes to hours."""

from __future__ import annotations

from alembic import op

from dynamic_thermal_charge.persistence.aemet_refresh_migration import (
    CANONICAL_REFRESH_COLUMN,
    LEGACY_REFRESH_COLUMN,
    migrate_refresh_configuration,
)


revision = "0030_aemet_refresh_hours"
down_revision = "0029_measured_history_and_chart_cues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_refresh_configuration(op.get_bind())


def downgrade() -> None:
    # Downgrading is provided for the repository's migration fixtures.  The
    # active runtime never reads this legacy representation after upgrade.
    bind = op.get_bind()
    from sqlalchemy import inspect, text

    inspector = inspect(bind)
    if inspector.has_table("weather_config"):
        columns = {column["name"] for column in inspector.get_columns("weather_config")}
        if CANONICAL_REFRESH_COLUMN in columns and LEGACY_REFRESH_COLUMN not in columns:
            bind.execute(
                text(
                    f'UPDATE "weather_config" SET "{CANONICAL_REFRESH_COLUMN}" = '
                    f'"{CANONICAL_REFRESH_COLUMN}" * 60'
                )
            )
            bind.execute(
                text(
                    f'ALTER TABLE "weather_config" RENAME COLUMN '
                    f'"{CANONICAL_REFRESH_COLUMN}" TO "{LEGACY_REFRESH_COLUMN}"'
                )
            )
    if inspector.has_table("system_configuration"):
        rows = bind.execute(
            text('SELECT "id", "weather_json" FROM "system_configuration"')
        ).mappings().all()
        import json

        for row in rows:
            document = json.loads(row["weather_json"])
            hours = document.pop("refresh_hours", 4)
            document["refresh_minutes"] = hours * 60
            bind.execute(
                text('UPDATE "system_configuration" SET "weather_json" = :weather WHERE "id" = :id'),
                {
                    "id": row["id"],
                    "weather": json.dumps(document, sort_keys=True, separators=(",", ":")),
                },
            )
