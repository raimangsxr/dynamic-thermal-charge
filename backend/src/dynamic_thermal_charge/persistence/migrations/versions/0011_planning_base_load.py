"""Add the household base load to automatic charge planning.

Revision ID: 0011_planning_base_load
Revises: 0010_mqtt_planning_simulation
"""

from __future__ import annotations


revision = "0011_planning_base_load"
down_revision = "0010_mqtt_planning_simulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Split configuration storage applies this portable additive column through
    # active_schema revision 4. The compatibility migration remains a no-op.
    pass


def downgrade() -> None:
    pass
