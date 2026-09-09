"""Group accumulator MQTT telemetry into one JSON topic."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_group_mqtt_telemetry"
down_revision = "0016_home_assistant_control"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _normalise_topic(value: object) -> str | None:
    if value is None:
        return None
    topic = str(value).strip()
    return topic or None


def _merged_topic(indoor_topic: object, stored_soc_topic: object) -> str | None:
    indoor = _normalise_topic(indoor_topic)
    stored_soc = _normalise_topic(stored_soc_topic)
    if indoor and stored_soc and indoor != stored_soc:
        return None
    return indoor or stored_soc


def upgrade() -> None:
    heater_columns = _columns("heater")
    if "telemetry_topic" not in heater_columns:
        op.add_column(
            "heater", sa.Column("telemetry_topic", sa.String(length=512), nullable=True)
        )

    if "indoor_topic" in heater_columns:
        connection = op.get_bind()
        charge_columns = _columns("heater_charge_config")
        if _has_table("heater_charge_config") and "stored_soc_topic" in charge_columns:
            rows = connection.execute(
                sa.text(
                    "SELECT h.id, h.indoor_topic, c.stored_soc_topic "
                    "FROM heater h LEFT JOIN heater_charge_config c "
                    "ON c.installation_id = h.installation_id "
                    "AND c.heater_id = h.heater_id"
                )
            ).all()
        else:
            rows = connection.execute(
                sa.text(
                    "SELECT id, indoor_topic, NULL AS stored_soc_topic FROM heater"
                )
            ).all()
        for heater_id, indoor_topic, stored_soc_topic in rows:
            connection.execute(
                sa.text(
                    "UPDATE heater SET telemetry_topic = :topic "
                    "WHERE id = :id AND telemetry_topic IS NULL"
                ),
                {
                    "topic": _merged_topic(indoor_topic, stored_soc_topic),
                    "id": heater_id,
                },
            )
        op.get_bind().execute(sa.text("ALTER TABLE heater DROP COLUMN indoor_topic"))

    if _has_table("heater_charge_config") and "stored_soc_topic" in _columns(
        "heater_charge_config"
    ):
        op.get_bind().execute(
            sa.text("ALTER TABLE heater_charge_config DROP COLUMN stored_soc_topic")
        )


def downgrade() -> None:
    heater_columns = _columns("heater")
    if "indoor_topic" not in heater_columns:
        op.add_column(
            "heater", sa.Column("indoor_topic", sa.String(length=512), nullable=True)
        )

    connection = op.get_bind()
    if "telemetry_topic" in _columns("heater"):
        connection.execute(
            sa.text(
                "UPDATE heater SET indoor_topic = telemetry_topic "
                "WHERE indoor_topic IS NULL"
            )
        )

    if _has_table("heater_charge_config"):
        charge_columns = _columns("heater_charge_config")
        if "stored_soc_topic" not in charge_columns:
            op.add_column(
                "heater_charge_config",
                sa.Column("stored_soc_topic", sa.String(length=512), nullable=True),
            )
        if "telemetry_topic" in _columns("heater"):
            connection.execute(
                sa.text(
                    "UPDATE heater_charge_config SET stored_soc_topic = "
                    "(SELECT telemetry_topic FROM heater "
                    "WHERE heater.installation_id = heater_charge_config.installation_id "
                    "AND heater.heater_id = heater_charge_config.heater_id) "
                    "WHERE stored_soc_topic IS NULL"
                )
            )

    if "telemetry_topic" in _columns("heater"):
        op.get_bind().execute(sa.text("ALTER TABLE heater DROP COLUMN telemetry_topic"))
