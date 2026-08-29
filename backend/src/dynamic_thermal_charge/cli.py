"""Command-line entry point. See specs/001-config-database/contracts/cli.md.

Configuration comes from the bootstrap-selected database. There is no
configuration file or runtime database URL.

Every administrative subcommand -- ``db``, ``config``, ``history`` -- is
guaranteed never to construct an output driver, so no administrative operation
can switch hardware (constitution principle I). Only ``run`` and
``gpio-self-test`` build a driver, and ``--driver gpio`` remains the only way to
reach real hardware.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import logging
from pathlib import Path
import signal
import sys
import time
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from .controller import ChargeController
from .drivers import OutputDriver, RecordingOutputDriver, SimulatedOutputDriver
from .gpio_driver import GpioDriverError, GpioOutputDriver
from .logging_config import configure_logging
from .models import AppConfig, Heater, OutputConfig, ThermalProfile
from .mqtt import MqttError
from .persistence import (
    ConfigConflictError,
    ConfigStoreEmptyError,
    ConfigStoreError,
    ConfigStoreUnavailableError,
    ConfigValidationError,
    PlanRef,
    SchemaVersionError,
    SecretRejectedError,
)
# The URL parser is retained only for the explicit legacy-import boundary;
# normal runtime commands never resolve a URL.
from .persistence.url import DatabaseUrlError as _DatabaseUrlError
from .persistence.topology import BootstrapIncompatibleError

# API validation stays stdlib-only, keeping CLI errors actionable without
# importing the optional web stack.
from .api.settings import ApiSettingsError as _ApiSettingsError
from .scheduler import ChargeScheduler, ScheduleResult
from .service import ControllerService, PlanRefresh
from .state import PlanStore
from .thermal import ThermalDemandEngine, select_indoor_temperatures
from .watchdog import ForecastWatchdog
from .weather import (
    OutdoorForecast,
    WeatherProvider,
    WeatherProviderError,
    build_weather_provider,
)


logger = logging.getLogger(__name__)

# Exit codes, per contracts/cli.md.
EXIT_OK = 0
EXIT_STORE_UNAVAILABLE = 1
EXIT_SCHEMA_UNKNOWN = 2
EXIT_NO_CONFIGURATION = 3
EXIT_UNKNOWN_NAME = 4
EXIT_INVALID_RESULT = 5
EXIT_CONFLICT = 6
EXIT_SECRET_REJECTED = 7
EXIT_ALREADY_EXISTS = 8
EXIT_UNMET_DEMAND = 2  # preserved from the previous CLI for plan output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dynamic-thermal-charge",
        description="Plan and control storage-heater charging",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    database = subcommands.add_parser("db", help="create and migrate the database")
    database_actions = database.add_subparsers(dest="db_command", required=True)
    initialise = database_actions.add_parser(
        "init", help="create or migrate the schema, and seed if there is no config"
    )
    initialise.add_argument(
        "--no-seed",
        action="store_true",
        help="migrate only; never write the example installation",
    )
    initialise.add_argument(
        "--quiet",
        action="store_true",
        help="initialise silently; intended for container startup",
    )
    database_actions.add_parser(
        "upgrade", help="apply pending migrations; never seeds"
    )
    database_actions.add_parser(
        "bootstrap-init",
        help="create the mandatory local bootstrap and print onboarding access once",
    )
    database_actions.add_parser(
        "bootstrap-doctor",
        help="inspect bootstrap read-only; never creates, migrates, or repairs it",
    )
    legacy_import = database_actions.add_parser(
        "import-legacy", help="dry-run or import one pre-bootstrap environment/database"
    )
    legacy_import.add_argument("--environment", type=Path, required=True)
    legacy_import.add_argument("--apply", action="store_true", help="apply after reviewing the default dry-run")

    configuration = subcommands.add_parser("config", help="inspect and edit config")
    configuration_actions = configuration.add_subparsers(
        dest="config_command", required=True
    )
    show = configuration_actions.add_parser("show", help="print the configuration")
    show.add_argument("--heater", default=None, help="limit output to one heater")

    set_field = configuration_actions.add_parser("set", help="change one field")
    set_field.add_argument("field")
    set_field.add_argument("value")
    set_field.add_argument("--heater", default=None, help="edit a heater field")

    add_heater = configuration_actions.add_parser(
        "add-heater", help="add a storage heater"
    )
    add_heater.add_argument("id")
    add_heater.add_argument("--name", default=None)
    add_heater.add_argument("--model", default=None)
    add_heater.add_argument("--power-kw", type=float, required=True)
    add_heater.add_argument("--full-charge-hours", type=float, required=True)
    add_heater.add_argument("--target-charge", type=float, default=1.0)
    add_heater.add_argument("--priority", type=int, default=0)
    add_heater.add_argument(
        "--disabled", action="store_true", help="add it switched off"
    )
    add_heater.add_argument("--output", choices=("simulated", "gpio"), default="simulated")
    add_heater.add_argument("--pin", type=int, default=None, help="BCM pin for gpio")
    active_level = add_heater.add_mutually_exclusive_group()
    active_level.add_argument("--active-high", dest="active_high", action="store_true")
    active_level.add_argument(
        "--no-active-high", dest="active_high", action="store_false"
    )
    add_heater.set_defaults(active_high=True)
    add_heater.add_argument("--target-temperature-c", type=float, default=None)
    add_heater.add_argument("--design-outdoor-temperature-c", type=float, default=None)
    add_heater.add_argument("--thermal-factor", type=float, default=1.0)
    add_heater.add_argument("--min-charge", type=float, default=0.0)
    add_heater.add_argument("--max-charge", type=float, default=1.0)

    remove_heater = configuration_actions.add_parser(
        "remove-heater", help="remove a storage heater, keeping its history"
    )
    remove_heater.add_argument("id")
    remove_heater.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )

    history = subcommands.add_parser("history", help="audit trail maintenance")
    history_actions = history.add_subparsers(dest="history_command", required=True)
    history_actions.add_parser("prune", help="apply the retention policy")

    run = subcommands.add_parser("run", help="build a plan, or run the controller")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument(
        "--controller", action="store_true", help="run the persistent controller"
    )
    mode.add_argument(
        "--watch-weather", action="store_true", help="keep refreshing the forecast"
    )
    mode.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without fetching weather or planning",
    )
    run.add_argument(
        "--start", type=datetime.fromisoformat, default=None,
        help="override the configured window start, ISO format",
    )
    run.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
        help="override the stored log level for this run",
    )

    api = subcommands.add_parser(
        "api", help="serve the HTTP API (a separate service from the controller)"
    )
    api.add_argument("--host", default=None, help="operational bind-host override")
    api.add_argument("--port", type=int, default=None, help="operational bind-port override")
    api.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
    )

    subcommands.add_parser(
        "mqtt", help="publish Home Assistant discovery and state over MQTT"
    )

    self_test = subcommands.add_parser(
        "gpio-self-test", help="activate each GPIO output in turn"
    )
    self_test.add_argument("--driver", choices=("simulated", "gpio"), default="gpio")
    self_test.add_argument(
        "--confirm-hardware-test",
        action="store_true",
        help="confirm the outputs are safely disconnected from mains",
    )
    self_test.add_argument("--test-seconds", type=float, default=1.0)
    self_test.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=None,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    _reject_configuration_path(arguments)
    args = build_parser().parse_args(arguments)
    try:
        return _dispatch(args)
    except SecretRejectedError as exc:
        return _fail(EXIT_SECRET_REJECTED, exc)
    except ConfigConflictError as exc:
        return _fail(EXIT_CONFLICT, exc)
    except _AlreadyExists as exc:
        return _fail(EXIT_ALREADY_EXISTS, exc)
    except _UnknownName as exc:
        return _fail(EXIT_UNKNOWN_NAME, exc)
    except ConfigValidationError as exc:
        return _fail(EXIT_INVALID_RESULT, exc)
    except ConfigStoreEmptyError as exc:
        return _fail(EXIT_NO_CONFIGURATION, exc)
    except SchemaVersionError as exc:
        code = (
            EXIT_SCHEMA_UNKNOWN
            if "does not understand" in str(exc)
            else EXIT_STORE_UNAVAILABLE
        )
        return _fail(code, exc)
    except BootstrapIncompatibleError as exc:
        return _fail(EXIT_SCHEMA_UNKNOWN, exc)
    except ConfigStoreUnavailableError as exc:
        return _fail(EXIT_STORE_UNAVAILABLE, exc)
    except ConfigStoreError as exc:
        return _fail(EXIT_STORE_UNAVAILABLE, exc)
    except _ApiSettingsError as exc:
        # Also a ValueError, so it must be caught before the generic handler.
        return _fail(EXIT_INVALID_RESULT, exc)
    except MqttError as exc:
        return _fail(EXIT_INVALID_RESULT, exc)
    except _DatabaseUrlError as exc:
        # A subclass of ValueError, so it has to be caught before the generic
        # handler: an absent or unsupported store location is "unavailable"
        # (exit 1), not "invalid configuration" (exit 5).
        return _fail(EXIT_STORE_UNAVAILABLE, exc)
    except ValueError as exc:
        return _fail(EXIT_INVALID_RESULT, f"configuration error: {exc}")
    except WeatherProviderError as exc:
        return _fail(EXIT_INVALID_RESULT, f"weather error: {exc}")
    except GpioDriverError as exc:
        return _fail(EXIT_INVALID_RESULT, f"GPIO error: {exc}")


class _UnknownName(Exception):
    """An unknown field or heater was named."""


class _AlreadyExists(Exception):
    """A heater id is already in use."""


def _fail(code: int, message: object) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _reject_configuration_path(arguments: list[str]) -> None:
    """Explain the removal of the configuration file argument (FR-006)."""
    if len(arguments) >= 2 and arguments[:2] == ["db", "import-legacy"]:
        return
    for argument in arguments:
        if argument.startswith("-"):
            continue
        if argument.endswith((".yaml", ".yml")) or "/" in argument:
            raise SystemExit(
                f"error: {argument!r} looks like a configuration file path, but "
                "configuration now lives in the bootstrap-selected database. Run "
                "'dynamic-thermal-charge db init' once; then use the system configuration panel. "
                "See the README for the upgrade procedure."
            )
        return


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def _dispatch(args: argparse.Namespace) -> int:
    configure_logging(getattr(args, "log_level", None) or "INFO")
    if args.command == "db":
        return _run_db(args)
    if args.command == "config":
        return _run_config(args)
    if args.command == "history":
        return _run_history(args)
    if args.command == "run":
        return _run(args)
    if args.command == "api":
        return _run_api(args)
    if args.command == "mqtt":
        return _run_mqtt()
    if args.command == "gpio-self-test":
        return _run_self_test(args)
    raise ValueError(f"unsupported command: {args.command}")


def _open_store():
    """Imported lazily so --help and argument errors never load SQLAlchemy."""
    from .persistence.bootstrap import open_store

    return open_store()


def _configured_store():
    """Open the store and refuse to go on unless the schema is understood."""
    store = _open_store()
    store.gate.require_ready()
    return store


# ------------------------------------------------------------------------- db

def _run_db(args: argparse.Namespace) -> int:
    if args.db_command == "import-legacy":
        import json
        from .persistence.legacy_import import import_legacy
        from .persistence.paths import StorePaths

        report = import_legacy(
            args.environment, StorePaths.production(), apply=args.apply
        )
        print(json.dumps(report.public_dict(), sort_keys=True))
        if not args.apply:
            print("Dry-run only; rerun with --apply after reviewing this sanitized report.")
        return EXIT_OK
    if args.db_command == "bootstrap-init":
        from .persistence.bootstrap_store import BootstrapRepository
        from .persistence.paths import StorePaths

        report = BootstrapRepository(StorePaths.production()).initialise()
        print(f"Bootstrap: {report.locator.public_dict()['driver']}, revision {report.locator_revision}")
        if report.onboarding_token is not None:
            print("One-time onboarding credential:")
            print(report.onboarding_token)
        else:
            print("Bootstrap already initialized; no credential was reissued.")
        return EXIT_OK
    if args.db_command == "bootstrap-doctor":
        import json

        from .persistence.bootstrap_store import inspect_bootstrap
        from .persistence.paths import StorePaths

        print(json.dumps(inspect_bootstrap(StorePaths.production()), sort_keys=True))
        return EXIT_OK

    from .persistence.bootstrap import initialise_at, upgrade
    from .persistence.paths import StorePaths

    if args.db_command == "init":
        _store, report, onboarding_token = initialise_at(
            StorePaths.production(), allow_seed=not args.no_seed
        )
        if args.quiet:
            return EXIT_OK
        for line in report.describe():
            print(line)
        if onboarding_token is not None:
            print("One-time onboarding credential:")
            print(onboarding_token)
        return EXIT_OK

    store, report, onboarding_token = initialise_at(
        StorePaths.production(), allow_seed=False
    )
    for line in report.describe():
        print(line)
    if onboarding_token is not None:
        print("One-time onboarding credential:")
        print(onboarding_token)
    return EXIT_OK


# --------------------------------------------------------------------- config

def _run_config(args: argparse.Namespace) -> int:
    store = _configured_store()
    if args.config_command == "show":
        return _config_show(store, args.heater)
    if args.config_command == "set":
        return _config_set(store, args)
    if args.config_command == "add-heater":
        return _config_add_heater(store, args)
    if args.config_command == "remove-heater":
        return _config_remove_heater(store, args)
    raise ValueError(f"unsupported config command: {args.config_command}")


def _config_show(store, heater_id: str | None) -> int:
    config, revision = store.repository.current()
    if heater_id is not None:
        matches = [heater for heater in config.heaters if heater.id == heater_id]
        if not matches:
            raise _UnknownName(
                f"heater {heater_id!r} does not exist; existing heaters: "
                f"{', '.join(heater.id for heater in config.heaters) or 'none'}"
            )
        _print_heater(matches[0])
        return EXIT_OK

    from .persistence.gate import EXPECTED_REVISION

    print(f"Store:            {store.location.description.describe()}")
    print(f"Schema revision:  {EXPECTED_REVISION}")
    print(f"Config revision:  {revision}")
    print()
    print("Installation")
    print(f"  max_total_power_kw          {config.site.max_total_power_w / 1000:g}")
    print(f"  slot_minutes                {config.site.slot_minutes}")
    print(f"  window_minutes              {config.site.window_minutes}")
    print(f"  log_level                   {config.logging.level}")
    print(f"  state_file                  {config.runtime.state_file}")
    print(f"  poll_seconds                {config.runtime.poll_seconds:g}")
    print(
        "  retention_days              "
        f"{'unlimited' if config.retention_days is None else config.retention_days}"
    )
    if config.schedule is not None:
        print("Schedule")
        print(f"  timezone                    {config.schedule.timezone}")
        print(f"  start_time                  {config.schedule.start_time:%H:%M}")
        print(f"  end_time                    {config.schedule.end_time:%H:%M}")
        print(
            "  weekdays                    "
            f"{','.join(str(day) for day in config.schedule.weekdays)}"
        )
    if config.weather is not None:
        weather = config.weather
        print("Weather")
        print(f"  provider                    {weather.provider}")
        if weather.aemet is not None:
            print(f"  municipality_code           {weather.aemet.municipality_code}")
            # The NAME of the variable, never its value.
            print(f"  api_key_env                 {weather.aemet.api_key_env}")
            print(f"  timeout_seconds             {weather.aemet.timeout_seconds:g}")
        if weather.simulated is not None:
            print(
                "  simulated                   "
                f"avg {weather.simulated.average_temperature_c:g} C, "
                f"min {weather.simulated.minimum_temperature_c:g} C"
            )
        if weather.fallback is not None:
            print(
                "  fallback                    "
                f"avg {weather.fallback.average_temperature_c:g} C, "
                f"min {weather.fallback.minimum_temperature_c:g} C"
            )
        print(f"  retry_minutes               {weather.watchdog.retry_minutes}")
        print(f"  refresh_minutes             {weather.watchdog.refresh_minutes}")
    print(f"Heaters ({len(config.heaters)})")
    for heater in config.heaters:
        _print_heater(heater, indent="  ")
    return EXIT_OK


def _print_heater(heater: Heater, indent: str = "") -> None:
    state = "enabled" if heater.enabled else "disabled"
    print(f"{indent}{heater.id} — {heater.name} ({state})")
    print(f"{indent}  model                     {heater.model or '—'}")
    print(f"{indent}  power_kw                  {heater.power_w / 1000:g}")
    print(f"{indent}  full_charge_hours         {heater.full_charge_minutes / 60:g}")
    print(f"{indent}  target_charge             {heater.target_charge:g}")
    print(f"{indent}  priority                  {heater.priority}")
    print(f"{indent}  output_type               {heater.output.kind}")
    print(f"{indent}  pin                       {heater.output.pin if heater.output.pin is not None else '—'}")
    print(f"{indent}  active_high               {str(heater.output.active_high).lower()}")
    if heater.thermal is not None:
        thermal = heater.thermal
        print(f"{indent}  target_temperature_c      {thermal.target_temperature_c:g}")
        print(
            f"{indent}  design_outdoor_temperature_c "
            f"{thermal.design_outdoor_temperature_c:g}"
        )
        print(f"{indent}  thermal_factor            {thermal.thermal_factor:g}")
        print(f"{indent}  min_charge                {thermal.min_charge:g}")
        print(f"{indent}  max_charge                {thermal.max_charge:g}")


def _config_set(store, args: argparse.Namespace) -> int:
    from .persistence.repository import (
        HEATER_FIELDS,
        INSTALLATION_FIELDS,
        WEATHER_FIELDS,
    )

    _, revision = store.repository.current()
    field = args.field
    if args.heater is not None:
        if field not in HEATER_FIELDS:
            raise _UnknownName(
                f"unknown heater field {field!r}; admissible fields: "
                f"{', '.join(sorted(HEATER_FIELDS))}"
            )
        entity, key = "heater", args.heater
    elif field in INSTALLATION_FIELDS:
        entity, key = "installation", None
    elif field in WEATHER_FIELDS:
        entity, key = "weather", None
    elif field in HEATER_FIELDS:
        raise _UnknownName(
            f"{field!r} is a heater field; name the heater with --heater <id>"
        )
    else:
        raise _UnknownName(
            f"unknown field {field!r}; admissible installation fields: "
            f"{', '.join(sorted(INSTALLATION_FIELDS))}; weather fields: "
            f"{', '.join(sorted(WEATHER_FIELDS))}; heater fields (with --heater): "
            f"{', '.join(sorted(HEATER_FIELDS))}"
        )

    try:
        change = store.repository.set_field(revision, entity, key, field, args.value)
    except ConfigValidationError as exc:
        if "does not exist" in str(exc):
            raise _UnknownName(str(exc)) from exc
        raise
    target = field if key is None else f"{key}.{field}"
    print(
        f"{target}: {change.old_value if change.old_value is not None else '—'} "
        f"-> {change.new_value if change.new_value is not None else '—'}"
    )
    print(f"configuration revision {change.revision_before} -> {change.revision_after}")
    return EXIT_OK


def _config_add_heater(store, args: argparse.Namespace) -> int:
    thermal = None
    if args.target_temperature_c is not None or args.design_outdoor_temperature_c is not None:
        if args.target_temperature_c is None or args.design_outdoor_temperature_c is None:
            raise ConfigValidationError(
                "a thermal profile needs both --target-temperature-c and "
                "--design-outdoor-temperature-c",
                field="target_temperature_c",
                heater_id=args.id,
            )
        thermal = ThermalProfile(
            target_temperature_c=args.target_temperature_c,
            design_outdoor_temperature_c=args.design_outdoor_temperature_c,
            thermal_factor=args.thermal_factor,
            min_charge=args.min_charge,
            max_charge=args.max_charge,
        )
    heater = Heater(
        id=args.id,
        name=args.name or args.id,
        model=args.model,
        power_w=round(args.power_kw * 1000),
        full_charge_minutes=round(args.full_charge_hours * 60),
        target_charge=args.target_charge,
        priority=args.priority,
        enabled=not args.disabled,
        thermal=thermal,
        output=OutputConfig(
            kind=args.output, pin=args.pin, active_high=args.active_high
        ),
    )
    _, revision = store.repository.current()
    try:
        change = store.repository.add_heater(revision, heater)
    except ConfigValidationError as exc:
        if "already exists" in str(exc):
            raise _AlreadyExists(str(exc)) from exc
        raise
    print(f"added heater {heater.id}")
    print(f"configuration revision {change.revision_before} -> {change.revision_after}")
    return EXIT_OK


def _config_remove_heater(store, args: argparse.Namespace) -> int:
    config, revision = store.repository.current()
    if args.id not in {heater.id for heater in config.heaters}:
        raise _UnknownName(
            f"heater {args.id!r} does not exist; existing heaters: "
            f"{', '.join(heater.id for heater in config.heaters) or 'none'}"
        )
    if not args.yes:
        answer = input(
            f"Remove heater {args.id!r} and its output and thermal profile? "
            "Its history is kept. [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("cancelled")
            return EXIT_OK
    change = store.repository.remove_heater(revision, args.id)
    print(f"removed heater {args.id}; its history is retained")
    print(f"configuration revision {change.revision_before} -> {change.revision_after}")
    return EXIT_OK


# -------------------------------------------------------------------- history

def _run_history(args: argparse.Namespace) -> int:
    from .persistence.history import SqlHistoryRecorder

    store = _configured_store()
    config, _ = store.repository.current()
    recorder = SqlHistoryRecorder(
        store.application_engine or store.engine,
        store.repository.installation_id(),
        store.location,
    )
    system = store.system_configuration.current().configuration
    retention_days = system.operations.retention_days
    report = recorder.prune(datetime.now().astimezone(), retention_days)
    if retention_days is None:
        print("retention is unlimited; nothing pruned")
    elif report.total == 0:
        print(f"nothing older than {retention_days} days to prune")
    else:
        print(f"pruned {report.total} rows older than {retention_days} days:")
        for table, count in sorted(report.deleted.items()):
            print(f"  {table}: {count}")
    return EXIT_OK


# ------------------------------------------------------------------------ run

def _run(args: argparse.Namespace) -> int:
    store = _configured_store()
    config, revision = store.repository.current()
    system_snapshot = store.system_configuration.current()
    system = system_snapshot.configuration
    configure_logging(args.log_level or system.logging.level)
    logger.info(
        "Configuration loaded from %s: revision %d, %d heaters",
        store.location.description.describe(),
        revision,
        len(config.heaters),
    )
    if args.check_config:
        logger.info("Configuration validation succeeded")
        return EXIT_OK

    aemet_secret = system_snapshot.secrets.get("aemet_api_key")
    provider = build_weather_provider(
        config.weather,
        api_key=None if aemet_secret is None else aemet_secret.value,
    ) if config.weather is not None else None
    driver_name = system.output.driver
    if args.watch_weather:
        if driver_name != "simulated":
            raise ValueError("--watch-weather does not use an output driver")
        if config.weather is None or provider is None:
            raise ValueError("--watch-weather requires weather configuration")
        if config.weather.provider == "aemet" and config.weather.fallback is None:
            raise ValueError("--watch-weather requires weather fallback values")
        return _run_watchdog(config, args.start, provider)
    if args.controller:
        if args.start is not None:
            raise ValueError("--controller does not accept --start")
        if config.weather is None or provider is None:
            raise ValueError("--controller requires weather configuration")
        return _run_controller(store, config, revision, provider, driver_name, system)

    start = _select_start(config, args.start)
    forecast = provider.forecast_for(start.date()) if provider is not None else None
    result = _build_plan(config, start, forecast)
    _print_plan(config, result)
    return EXIT_UNMET_DEMAND if result.unmet_minutes else EXIT_OK


def _select_start(config: AppConfig, explicit_start: datetime | None) -> datetime:
    if explicit_start is not None:
        if explicit_start.tzinfo is None and config.schedule is not None:
            return explicit_start.replace(tzinfo=ZoneInfo(config.schedule.timezone))
        return explicit_start
    if config.schedule is not None:
        start = config.schedule.next_start(datetime.now().astimezone())
        logger.info(
            "Selected next configured charge window at %s",
            start.isoformat(timespec="minutes"),
        )
        return start
    return datetime.now().replace(second=0, microsecond=0)


def _build_plan(
    config: AppConfig,
    start: datetime,
    forecast: OutdoorForecast | None,
    indoor_temperatures: dict[str, float] | None = None,
) -> ScheduleResult:
    requested_charge_minutes = None
    if forecast is not None:
        logger.info(
            "Weather forecast: date=%s source=%s location=%s min=%.1f C avg=%.1f C "
            "max=%.1f C",
            forecast.date.isoformat(),
            "fallback" if forecast.from_fallback else forecast.source,
            forecast.location or "n/a",
            forecast.minimum_temperature_c,
            forecast.average_temperature_c,
            forecast.maximum_temperature_c,
        )
        requested_charge_minutes = ThermalDemandEngine().calculate(
            config.heaters, forecast, indoor_temperatures=indoor_temperatures
        )
    return ChargeScheduler().build(
        config.site,
        config.heaters,
        start,
        requested_charge_minutes=requested_charge_minutes,
    )


def _run_watchdog(
    config: AppConfig,
    explicit_start: datetime | None,
    provider: WeatherProvider,
    wait: Callable[[float], None] = time.sleep,
) -> int:
    assert config.weather is not None
    watchdog = ForecastWatchdog(
        provider,
        expected_source=config.weather.provider,
        config=config.weather.watchdog,
    )
    try:
        while True:
            start = _select_start(config, explicit_start)
            cycle = watchdog.poll(start.date())
            result = _build_plan(config, start, cycle.forecast)
            _print_plan(config, result)
            wait(cycle.next_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Weather watchdog stopped")
        return EXIT_OK


def _run_controller(
    store,
    config: AppConfig,
    revision: int,
    provider: WeatherProvider,
    driver_name: str = "simulated",
    system=None,
) -> int:
    from .persistence.heartbeat import SqlHeartbeatPublisher
    from .persistence.history import SqlHistoryRecorder
    from .persistence.controller_log import ControllerLogHandler

    assert config.weather is not None
    if store.context is not None:
        store.context.publish_process_revision("controller")
    installation_id = store.repository.installation_id()
    application_engine = store.application_engine or store.engine
    history = SqlHistoryRecorder(application_engine, installation_id, store.location)
    max_events = 1000 if system is None else system.logging.max_events
    web_log_handler = ControllerLogHandler(
        application_engine, installation_id, store.location, max_events=max_events
    )
    logging.getLogger().addHandler(web_log_handler)
    # The controller's proof of life, so a separate API can tell "now" from
    # "the last thing anyone knew". Publishing it can never stop the loop.
    heartbeat = SqlHeartbeatPublisher(
        application_engine,
        installation_id,
        poll_seconds=(config.runtime.poll_seconds if system is None else system.operations.controller_poll_seconds),
        driver_kind=driver_name,
        location=store.location,
    )
    current_plan_ref: list[PlanRef | None] = [None]
    indoor_fallback = _IndoorFallbackTracker()
    driver: OutputDriver | None = None
    with _controlled_termination():
        try:
            driver = RecordingOutputDriver(
                _build_output_driver(config, driver_name),
                history,
                plan_ref=lambda: current_plan_ref[0],
            )
            controller = ChargeController(
                tuple(heater.id for heater in config.heaters if heater.enabled),
                driver,
                relay_tests=store.relay_tests,
                runner_id=heartbeat.runner_id,
            )
            watchdog = ForecastWatchdog(
                provider,
                expected_source=config.weather.provider,
                config=config.weather.watchdog,
            )

            def refresh_plan(now: datetime) -> PlanRefresh:
                # Re-read the configuration each refresh so an edit takes effect
                # on the next recalculation, never mid-plan (FR-039).
                live_config, live_revision = store.repository.current()
                start = (
                    live_config.schedule.active_or_next_start(now)
                    if live_config.schedule is not None
                    else now
                )
                cycle = watchdog.poll(start.date())
                indoor_temperatures = indoor_fallback.select(
                    live_config, store.indoor_readings, now
                )
                plan = _build_plan(
                    live_config,
                    start,
                    cycle.forecast,
                    indoor_temperatures=indoor_temperatures,
                )
                forecast_ref = history.record_forecast(cycle.forecast)
                current_plan_ref[0] = history.record_plan(
                    plan, forecast_ref, live_revision
                )
                if store.context is not None:
                    # The fallback snapshot is refreshed only after the plan
                    # and its source forecast have been accepted by canonical
                    # storage.
                    from .persistence.context import _json_ready
                    store.context.refresh_fallback(plan=_json_ready(plan))
                return PlanRefresh(
                    plan=plan,
                    next_refresh_seconds=cycle.next_poll_seconds,
                    plan_ref=current_plan_ref[0],
                )

            service = ControllerService(
                controller=controller,
                store=PlanStore(config.runtime.state_file),
                refresh_plan=refresh_plan,
                poll_seconds=(config.runtime.poll_seconds if system is None else system.operations.controller_poll_seconds),
                error_retry_seconds=config.weather.watchdog.retry_minutes * 60,
                history=history,
                retention_days=(config.retention_days if system is None else system.operations.retention_days),
                heartbeat=heartbeat,
            )
            return service.run()
        finally:
            logging.getLogger().removeHandler(web_log_handler)
            web_log_handler.close()
            if driver is not None:
                driver.close()


class _IndoorFallbackTracker:
    """Read once per plan and log only fallback state transitions."""

    def __init__(self) -> None:
        self._fallback: set[str] = set()
        self._store_unavailable = False

    def select(self, config: AppConfig, repository, at: datetime) -> dict[str, float]:
        try:
            readings = repository.read_all()
        except ConfigStoreError as exc:
            readings = {}
            if not self._store_unavailable:
                logger.error(
                    "Indoor reading store unavailable; using thermal fallback: %s",
                    exc,
                )
            self._store_unavailable = True
        else:
            if self._store_unavailable:
                logger.info("Indoor reading store recovered")
            self._store_unavailable = False

        selection = select_indoor_temperatures(
            config.heaters,
            readings,
            at=at,
            max_age_minutes=config.site.indoor_max_age_minutes,
            min_plausible_c=config.site.indoor_min_plausible_c,
            max_plausible_c=config.site.indoor_max_plausible_c,
        )
        current = set(selection.fallback_reasons)
        for heater_id in sorted(current - self._fallback):
            logger.warning(
                "Heater %s is using thermal fallback: %s",
                heater_id,
                selection.fallback_reasons[heater_id],
            )
        for heater_id in sorted(self._fallback - current):
            logger.info("Heater %s recovered indoor temperature", heater_id)
        self._fallback = current
        return selection.temperatures


def _build_output_driver(config: AppConfig, driver_name: str) -> OutputDriver:
    if driver_name == "simulated":
        logger.warning("Controller is running with simulated outputs only")
        return SimulatedOutputDriver()
    if driver_name == "gpio":
        logger.warning("Controller is running with REAL GPIO outputs")
        return GpioOutputDriver(
            {heater.id: heater.output for heater in config.heaters if heater.enabled}
        )
    raise ValueError(f"unsupported output driver: {driver_name}")


# ------------------------------------------------------------------------ api

def _run_api(args: argparse.Namespace) -> int:
    """Serve the HTTP API.

    Imported lazily so no other command pays for FastAPI, and so the package
    stays usable without the optional `api` extra installed.

    This command builds NO output driver: like the administrative commands, it
    cannot switch hardware (constitution principle I).
    """
    try:
        import uvicorn

        from .api import create_app
        from .api.settings import settings_from_repository
    except ImportError as exc:
        raise ValueError(
            f"the HTTP API extra is not installed: {exc}. Install it with "
            "python -m pip install 'dynamic-thermal-charge[api]'"
        ) from exc

    store = _configured_store()
    settings = settings_from_repository(store.system_configuration)
    if store.context is not None:
        store.context.publish_process_revision("mqtt")
    host = args.host or settings.host
    port = args.port or settings.port
    app = create_app(settings, store_factory=lambda: store)
    logger.info("Serving the HTTP API on %s:%d", host, port)
    # Bare uvicorn on purpose: uvicorn[standard] would pull uvloop and
    # httptools, neither of which has an armv7l wheel.
    uvicorn.run(app, host=host, port=port, log_level=(args.log_level or "info").lower())
    return EXIT_OK


# ----------------------------------------------------------------------- mqtt

def _run_mqtt() -> int:
    """Compose the independent publisher lazily; never imports a driver."""
    from datetime import timezone

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
    installation_id = store.repository.installation_id()
    topics = TopicLayout(settings.prefix, settings.discovery_prefix)
    application_engine = store.application_engine or store.engine
    status_reader = SqlStatusReader(application_engine, installation_id, store.location)
    snapshots = StoreSnapshotReader(
        config_repository=store.repository,
        schema_gate=store.gate,
        heartbeat_reader=lambda: read_heartbeat(
            application_engine, installation_id, store.location
        ),
        status_reader=status_reader,
        clock=lambda: datetime.now(timezone.utc),
    )
    transport = PahoMqttClient(settings)
    publisher = MqttPublisher(
        transport,
        topics,
        snapshots,
        discovery=lambda: snapshots.discovery(
            topics, store.repository.installation_name()
        ),
        subscriptions=lambda: snapshots.subscriptions(topics),
    )
    commands = CommandProcessor(
        store.repository, topics, republish=publisher.republish_heater
    )
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
    return EXIT_OK


# -------------------------------------------------------------- gpio self test

def _run_self_test(args: argparse.Namespace) -> int:
    store = _configured_store()
    config, _ = store.repository.current()
    configure_logging(args.log_level or config.logging.level)
    if args.driver != "gpio":
        raise ValueError("gpio-self-test requires --driver gpio")
    if not args.confirm_hardware_test:
        raise ValueError("gpio-self-test requires --confirm-hardware-test")
    if args.test_seconds <= 0:
        raise ValueError("--test-seconds must be positive")
    with _controlled_termination():
        driver = _build_output_driver(config, "gpio")
        return _run_output_self_test(config, driver, duration_seconds=args.test_seconds)


def _run_output_self_test(
    config: AppConfig,
    driver: OutputDriver,
    duration_seconds: float,
    wait: Callable[[float], None] = time.sleep,
) -> int:
    enabled_heaters = tuple(heater for heater in config.heaters if heater.enabled)
    now = datetime.now().astimezone()
    try:
        for heater in enabled_heaters:
            driver.set_state(heater.id, False, now)
        for heater in enabled_heaters:
            logger.warning(
                "GPIO self-test activating %s for %.2f seconds",
                heater.id,
                duration_seconds,
            )
            driver.set_state(heater.id, True, datetime.now().astimezone())
            try:
                wait(duration_seconds)
            finally:
                driver.set_state(heater.id, False, datetime.now().astimezone())
    finally:
        for heater in enabled_heaters:
            try:
                driver.set_state(heater.id, False, datetime.now().astimezone())
            except Exception:
                logger.exception("Failed to force self-test output %s OFF", heater.id)
        driver.close()
    logger.info("GPIO self-test completed with every output off")
    return EXIT_OK


# ------------------------------------------------------------------ utilities

def _handle_termination_signal(_signum, _frame) -> None:
    logger.info("Termination signal received")
    raise KeyboardInterrupt


@contextmanager
def _controlled_termination() -> Iterator[None]:
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_termination_signal)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)


def _print_plan(config: AppConfig, result: ScheduleResult) -> None:
    print("Charge plan")
    for slot in result.slots:
        active = ", ".join(slot.heater_ids) or "—"
        print(
            f"{slot.start:%Y-%m-%d %H:%M}–{slot.end:%H:%M}  "
            f"{slot.total_power_w / 1000:.1f} kW  {active}"
        )
    print("\nAllocated:")
    for heater in config.heaters:
        if heater.enabled:
            minutes = result.allocated_minutes[heater.id]
            print(f"- {heater.name}: {minutes / 60:g} h")
    if result.unmet_minutes:
        print("\nUnmet demand:")
        for heater_id, minutes in result.unmet_minutes.items():
            print(f"- {heater_id}: {minutes / 60:g} h")
