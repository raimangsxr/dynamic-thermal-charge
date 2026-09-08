"""Replace point-in-time temperature targets with explicit intervals.

The old rows are intentionally discarded.  A point target did not contain an
end boundary, so carrying it forward would invent a weekly comfort schedule.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_temperature_target_intervals"
down_revision = "0014_room_energy_model"
branch_labels = None
depends_on = None


def _drop_temperature_target() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("temperature_target"):
        return
    indexes = {
        index["name"]
        for index in inspector.get_indexes("temperature_target")
        if index.get("name")
    }
    if "ix_temperature_target_installation_heater" in indexes:
        op.drop_index(
            "ix_temperature_target_installation_heater",
            table_name="temperature_target",
        )
    op.drop_table("temperature_target")


def _create_temperature_target(*, legacy: bool) -> None:
    columns = [
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("heater_id", sa.String(length=64), nullable=False),
        sa.Column("target_temperature_c", sa.Float(), nullable=False),
    ]
    if legacy:
        columns.append(sa.Column("at_time", sa.String(length=5), nullable=False))
    else:
        columns.extend(
            [
                sa.Column("start_time", sa.String(length=5), nullable=False),
                sa.Column("end_time", sa.String(length=5), nullable=False),
            ]
        )
    columns.extend(
        [
            sa.Column("weekdays", sa.String(length=32), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "target_temperature_c >= -50 AND target_temperature_c <= 80",
                name="ck_temperature_target_range",
            ),
            sa.ForeignKeyConstraint(
                ["installation_id"], ["installation.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        ]
    )
    unique_columns = ["installation_id", "heater_id"]
    if legacy:
        unique_columns.append("at_time")
    else:
        unique_columns.extend(["start_time", "end_time"])
    unique_columns.append("weekdays")
    columns.append(
        sa.UniqueConstraint(
            *unique_columns,
            name="uq_temperature_target_rule",
        )
    )
    op.create_table("temperature_target", *columns)
    op.create_index(
        "ix_temperature_target_installation_heater",
        "temperature_target",
        ["installation_id", "heater_id"],
    )


def upgrade() -> None:
    _drop_temperature_target()
    _create_temperature_target(legacy=False)


def downgrade() -> None:
    _drop_temperature_target()
    _create_temperature_target(legacy=True)
