"""The HTTP API. The only package allowed to import FastAPI.

That concentration is what makes it verifiable, with a static test, that **no
route can operate an output**: it is enough to check that no module under ``api/``
imports ``drivers``, ``gpio_driver`` or ``controller``. Switching relays stays
exclusively with the fail-safe controller (constitution principle I).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from .settings import ApiSettings, settings_from_repository

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from ..persistence.bootstrap import Store


logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

DESCRIPTION = """\
Read the state of a storage-heater installation and edit its configuration.

Runs as a service independent of the persistent controller, communicating with it
only through the database. **No operation of this API switches an output**: only
the planner decides what charges, and there is no manual override.

Every operation requires `Authorization: Bearer <token>` except `/health`.

The state endpoint distinguishes *what is happening now* from *the last thing
anyone knew*. When the controller has not been seen recently, the output state is
flagged as not current and no instantaneous power is published: an unconfirmable
figure is worse than none.
"""


def create_app(
    settings: ApiSettings | None = None,
    store_factory: "Callable[[], Store] | None" = None,
    clock: Callable[[], datetime] | None = None,
) -> "FastAPI":
    """Build the application. Raises if the credential is unusable.

    FastAPI is imported **here**, not at module level, so that importing
    ``api.settings`` -- which the CLI does, to report a missing token without the
    optional extra -- costs nothing. It also keeps ``import cli`` from loading the
    whole web stack.
    """
    from fastapi import Depends, FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from .errors import register_error_handlers
    from .security import require_token

    default_store = None
    if settings is None:
        default_store = (store_factory or _default_store_factory)()
        if default_store.system_configuration is None:
            raise RuntimeError("system configuration repository is unavailable")
        resolved = settings_from_repository(default_store.system_configuration)
    else:
        resolved = settings

    app = FastAPI(
        title="Dynamic Thermal Charge",
        description=DESCRIPTION,
        version="0.1.0",
        # Documented but behind the credential: the description enumerates the
        # surface of the API and nobody needs it unauthenticated.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = resolved
    app.state.store_factory = store_factory or (
        (lambda: default_store) if default_store is not None else _default_store_factory
    )
    from .dependencies import utc_now

    app.state.clock = clock or utc_now
    app.state.last_heartbeat = None
    if default_store is not None and default_store.context is not None:
        default_store.context.publish_process_revision("api")

    register_error_handlers(app)

    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    from .routes import config as config_routes
    from .routes import controller_log as controller_log_routes
    from .routes import docs as docs_routes
    from .routes import health as health_routes
    from .routes import history as history_routes
    from .routes import onboarding as onboarding_routes
    from .routes import status as status_routes
    from .routes import system as system_routes
    from .routes import relay_test as relay_test_routes

    # No credential: deliberately mute (FR-052).
    app.include_router(health_routes.router, tags=["health"])
    app.include_router(onboarding_routes.router)
    # Everything else, credential required -- documentation included.
    protected = [Depends(require_token)]
    app.include_router(
        status_routes.router, prefix=API_PREFIX, tags=["status"], dependencies=protected
    )
    app.include_router(controller_log_routes.router, prefix=API_PREFIX, tags=["controller-log"], dependencies=protected)
    app.include_router(relay_test_routes.router, prefix=API_PREFIX, tags=["relay-test"], dependencies=protected)
    app.include_router(
        config_routes.router, prefix=API_PREFIX, tags=["config"], dependencies=protected
    )
    app.include_router(
        history_routes.router,
        prefix=API_PREFIX,
        tags=["history"],
        dependencies=protected,
    )
    app.include_router(
        system_routes.router, prefix=API_PREFIX, tags=["system"], dependencies=protected
    )
    app.include_router(docs_routes.router, dependencies=protected, tags=["docs"])

    if resolved.exposed_beyond_localhost:
        logger.warning(
            "The API is listening on %s, beyond this host. It serves in clear "
            "text: anyone on the network can read the token in transit, and "
            "whoever holds it can change the maximum power and the pin "
            "assignments",
            resolved.host,
        )
    return app


def _default_store_factory() -> "Store":
    from ..persistence.bootstrap import open_store
    from .dependencies import CONNECT_TIMEOUT_SECONDS, POOL_TIMEOUT_SECONDS

    return open_store(engine_timeouts=(CONNECT_TIMEOUT_SECONDS, POOL_TIMEOUT_SECONDS))


__all__ = ["API_PREFIX", "create_app"]
