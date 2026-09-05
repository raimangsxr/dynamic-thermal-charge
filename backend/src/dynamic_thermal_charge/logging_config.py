"""Application logging setup."""

from __future__ import annotations

import logging


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str) -> None:
    """Configure console logging for the application process."""
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT, force=True)


__all__ = ["configure_logging"]
