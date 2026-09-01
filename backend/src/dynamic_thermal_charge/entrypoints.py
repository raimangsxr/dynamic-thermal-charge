"""Process entrypoints used by the container deployment.

These functions are deliberately called directly by the deployment. There is
no argument parser or user-facing command interface in the application.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from dataclasses import replace

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


def initialise_dev_storage() -> None:
    """Initialise an isolated development store from environment settings."""
    from .models import SimulatedForecastConfig
    from .api.settings import ApiSettings
    from .persistence.bootstrap_store import BootstrapRepository
    from .persistence.locator import DatabaseDriver, DatabaseLocator
    from .persistence.seed import example_installation
    from .persistence.secret_digest import digest_secret
    from .persistence.system_configuration import SecretAction, SecretMutation

    token = os.environ.get(
        "DTC_API_TOKEN", "dev-admin-token-local-please-remember-123"
    )
    ApiSettings(token=token)
    paths = StorePaths.production()
    bootstrap = BootstrapRepository(paths)
    result = bootstrap.initialise()
    driver = os.environ.get("DEV_DATABASE", "sqlite").strip().lower()
    if driver == "postgresql" and result.locator.driver is DatabaseDriver.SQLITE:
        locator = _dev_postgres_locator()
        bootstrap.compare_and_swap_locator(result.locator_revision, locator)
    store_result = initialise_at(paths, allow_seed=False, admin_token=token)
    store, _report, _onboarding = store_result
    system = store.system_configuration.current()
    if result.created:
        store.system_configuration.update_section(
            "api", {"host": "0.0.0.0"}, expected_revision=system.revision, actor="dev-init"
        )
        system = store.system_configuration.current()
        store.system_configuration.update_section(
            "mqtt", {"enabled": True, "host": os.environ.get("DEV_MQTT_HOST", "mosquitto")},
            expected_revision=system.revision, actor="dev-init",
        )
        system = store.system_configuration.current()
        store.system_configuration.update_section(
            "weather", {"provider": "simulated"}, expected_revision=system.revision, actor="dev-init"
        )
        system = store.system_configuration.current()
        store.system_configuration.update_section(
            "output", {"driver": "simulated"}, expected_revision=system.revision, actor="dev-init"
        )
    elif "admin_token_digest" not in system.secrets:
        store.system_configuration.update_section(
            "api",
            {},
            expected_revision=system.revision,
            secret_mutations={
                "admin_token_digest": SecretMutation(
                    SecretAction.REPLACE, digest_secret(token)
                )
            },
            actor="dev-init",
        )
    if store.repository.is_empty():
        config = example_installation()
        config = replace(
            config,
            weather=replace(
                config.weather,
                provider="simulated",
                simulated=SimulatedForecastConfig(
                    average_temperature_c=8.0, minimum_temperature_c=3.0
                ),
                aemet=None,
            ),
        )
        store.repository.seed(config, "default")
    bootstrap.mark_configured()


def _dev_postgres_locator():
    from .persistence.locator import DatabaseDriver, DatabaseLocator

    return DatabaseLocator(
        DatabaseDriver.POSTGRESQL,
        host=os.environ.get("DEV_POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("DEV_POSTGRES_PORT", "5432")),
        database=os.environ.get("DEV_POSTGRES_DB", "dtc"),
        username=os.environ.get("DEV_POSTGRES_USER", "dtc"),
        password=os.environ.get("DEV_POSTGRES_PASSWORD", "dtc-dev-password"),
        tls=False,
        trusted_no_tls=True,
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
        timezone_name=(
            config.schedule.timezone if config.schedule is not None else "UTC"
        ),
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
    from .mqtt.indoor import ChargeTelemetryMessageProcessor, IndoorMessageProcessor
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
    charge_telemetry = ChargeTelemetryMessageProcessor(
        store.repository,
        store.planning,
        clock=lambda: datetime.now(timezone.utc),
    )

    def handle_telemetry(message):
        # Preserve the legacy indoor-temperature path while accepting the new
        # three-topic contract. Each processor ignores topics it does not own.
        indoor.handle(message)
        charge_telemetry.handle(message)
    service = MqttService(
        transport,
        topics,
        host=settings.host,
        port=settings.port,
        publisher=publisher,
        publish_seconds=settings.publish_seconds,
        command_handler=commands.handle,
        indoor_handler=handle_telemetry,
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
    "initialise_dev_storage",
    "_dev_postgres_locator",
    "run_api",
    "run_controller",
    "run_mqtt",
]
