"""Schema migrations.

Alembic is imported **only** from inside this package, and this package is only
imported by the explicit initialization path. The service start-up path never
imports it: ``import alembic.config`` costs ~224 ms on a development machine, so
of the order of seconds on the deployment target, and it would drag Mako and
MarkupSafe into a process that runs for months (research.md D4).
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.engine import Engine


logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent
VERSIONS_DIR = MIGRATIONS_DIR / "versions"


def _config(engine: Engine):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # The URL travels through the attributes, never through a file on disk, so
    # the connection string is not written anywhere (principle III).
    config.attributes["connection_engine"] = engine
    return config


def upgrade_to_head(engine: Engine) -> str:
    """Apply every pending migration in order and return the resulting revision."""
    from alembic import command

    command.upgrade(_config(engine), "head")
    return head_revision()


def head_revision() -> str:
    """The newest revision shipped with this build."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(MIGRATIONS_DIR))
    revision = script.get_current_head()
    if revision is None:
        raise RuntimeError("no migrations are shipped with this build")
    return revision


def shipped_revisions() -> tuple[str, ...]:
    """Every revision this build understands, oldest first."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(MIGRATIONS_DIR))
    return tuple(
        reversed([revision.revision for revision in script.walk_revisions()])
    )


__all__ = ["head_revision", "shipped_revisions", "upgrade_to_head"]
