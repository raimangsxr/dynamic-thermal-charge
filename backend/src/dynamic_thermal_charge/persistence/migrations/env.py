"""Alembic environment. Driven programmatically, never from an alembic.ini."""

from __future__ import annotations

from alembic import context

from dynamic_thermal_charge.persistence.schema import metadata


target_metadata = metadata


def run_migrations_online() -> None:
    engine = context.config.attributes.get("connection_engine")
    if engine is None:
        raise RuntimeError(
            "migrations must be run through the service, which supplies the engine"
        )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER TABLE in place; batch mode rewrites the table
            # instead, so the same migration script works on both engines.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("offline migrations are not supported")
run_migrations_online()
