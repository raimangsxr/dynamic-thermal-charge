"""Process entrypoints used by the container deployment.

These functions are deliberately called directly by the deployment. There is
no argument parser or user-facing command interface in the application.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os

from .persistence.bootstrap import initialise_at, open_store
from .persistence.paths import StorePaths

logger = logging.getLogger(__name__)


def _configured_store():
    store = open_store()
    store.gate.require_ready()
    return store


def initialise_storage() -> None:
    """Create the stores and seed the administrator token idempotently."""
    from .api.settings import ApiSettings

    token = os.environ.get("DTC_API_TOKEN")
    if not token:
        raise RuntimeError("DTC_API_TOKEN must be set for storage initialisation")
    ApiSettings(token=token)
    _store, report, onboarding_token = initialise_at(
        StorePaths.production(), allow_seed=True, admin_token=token
    )
    logger.info(
        "Storage initialised at revision %s (%d heaters)%s",
        report.revision,
        report.heaters,
        "; onboarding credential created" if onboarding_token else "",
    )


def check_configuration() -> None:
    """Validate that the persisted storage and configuration can be opened."""
    store = _configured_store()
    store.repository.current()
    store.system_configuration.current()


def run_controller() -> None:
    from .logging_config import configure_logging
    from .runtime import _run_controller
    from .weather import build_weather_provider

    store = _configured_store()
    config, revision = store.repository.current()
    system_snapshot = store.system_configuration.current()
    system = system_snapshot.configuration
    configure_logging(system.logging.level)
    provider = build_weather_provider(
        config.weather,
        api_key=(system_snapshot.secrets["aemet_api_key"].value
                 if "aemet_api_key" in system_snapshot.secrets else None),
    ) if config.weather is not None else None
    if config.weather is None or provider is None:
        raise RuntimeError("controller requires weather configuration")
    _run_controller(store, config, revision, provider, system.output.driver, system)


def run_api() -> None:
    import uvicorn

    from .api import create_app
    from .api.settings import settings_from_repository

    store = _configured_store()
    settings = settings_from_repository(store.system_configuration)
    if store.context is not None:
        store.context.publish_process_revision("api")
    app = create_app(settings, store_factory=lambda: store)
    logger.info("Serving the HTTP API on %s:%d", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


def run_mqtt() -> None:
    from .mqtt.client import PahoMqttClient
    from .mqtt.commands import CommandProcessor
    from .mqtt.indoor import IndoorMessageProcessor
    from .mqtt.publisher import MqttPublisher, StoreSnapshotReader
    from .mqtt.service import MqttService
    from .mqtt.settings import settings_from_repository
    from .mqtt.topics import TopicLayout
    from .persistence.heartbeat import read_heartbeat
    from .persistence.history import SqlStatusReader

    store = _configured_store()
    settings = settings_from_repository(store.system_configuration)
    if store.context is not None:
        store.context.publish_process_revision("mqtt")
    installation_id = store.repository.installation_id()
    topics = TopicLayout(settings.prefix, settings.discovery_prefix)
    application_engine = store.application_engine or store.engine
    status_reader = SqlStatusReader(application_engine, installation_id, store.location)
    snapshots = StoreSnapshotReader(
        config_repository=store.repository,
        schema_gate=store.gate,
        heartbeat_reader=lambda: read_heartbeat(application_engine, installation_id, store.location),
        status_reader=status_reader,
        clock=lambda: datetime.now(timezone.utc),
    )
    transport = PahoMqttClient(settings)
    publisher = MqttPublisher(
        transport,
        topics,
        snapshots,
        discovery=lambda: snapshots.discovery(topics, store.repository.installation_name()),
        subscriptions=lambda: snapshots.subscriptions(topics),
    )
    commands = CommandProcessor(store.repository, topics, republish=publisher.republish_heater)
    indoor = IndoorMessageProcessor(
        store.repository,
        store.indoor_readings,
        clock=lambda: datetime.now(timezone.utc),
    )
    service = MqttService(
        transport,
        topics,
        host=settings.host,
        port=settings.port,
        publisher=publisher,
        publish_seconds=settings.publish_seconds,
        command_handler=commands.handle,
        indoor_handler=indoor.handle,
    )
    try:
        service.start()
        service.run()
    except KeyboardInterrupt:
        logger.info("MQTT publisher stopped")
    finally:
        service.stop()


__all__ = [
    "check_configuration",
    "initialise_storage",
    "run_api",
    "run_controller",
    "run_mqtt",
]
