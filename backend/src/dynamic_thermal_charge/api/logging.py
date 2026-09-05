"""Logging configuration for the HTTP edge."""

from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any


class HealthcheckAccessFilter(logging.Filter):
    """Keep successful liveness probes out of INFO logs.

    Uvicorn emits access records at INFO before the application can classify
    them. The filter changes only the public liveness endpoint: successful
    probes are DEBUG (and shown only when DEBUG logging is enabled), while
    failed responses are ERROR.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args: Any = record.args
        if not isinstance(args, tuple) or len(args) < 5 or args[2] != "/health":
            return True

        try:
            status_code = int(args[4])
        except (TypeError, ValueError):
            return True

        if 200 <= status_code < 400:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
            return logging.getLogger().isEnabledFor(logging.DEBUG)

        record.levelno = logging.ERROR
        record.levelname = "ERROR"
        return True


def uvicorn_log_config() -> dict[str, Any]:
    """Return Uvicorn's config with liveness access-log classification."""
    from uvicorn.config import LOGGING_CONFIG

    config = deepcopy(LOGGING_CONFIG)
    config["filters"] = {
        "healthcheck_access": {
            "()": f"{__name__}.HealthcheckAccessFilter",
        }
    }
    config["handlers"]["access"]["filters"] = ["healthcheck_access"]
    config["loggers"]["uvicorn.access"]["level"] = "DEBUG"
    return config


__all__ = ["HealthcheckAccessFilter", "uvicorn_log_config"]
