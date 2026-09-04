"""Add MQTT planning simulation settings to charge_planning_site.

Revision ID: 0010_mqtt_planning_simulation
Revises: 0009_remove_state_file
"""

from __future__ import annotations


revision = "0010_mqtt_planning_simulation"
down_revision = "0009_remove_state_file"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy single-database compatibility schema intentionally remains
    # unchanged. Split storage applies the additive planning-site columns from
    # active_schema revision 3.
    pass


def downgrade() -> None:
    pass
