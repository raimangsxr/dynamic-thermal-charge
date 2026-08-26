"""Initial schema: configuration and history.

Revision ID: 0001_initial_schema
Revises: None

The initial revision builds the tables straight from ``schema.py`` so there is a
single source of truth for the starting shape. Later revisions are hand-written
diffs, as usual.
"""

from __future__ import annotations

from alembic import op

from dynamic_thermal_charge.persistence.schema import metadata


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
