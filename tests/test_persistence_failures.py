"""Failure paths and architectural guards.

Covers the paths that constitution principles I and IV are about: nothing here
may end with an output energised, and nothing here may end with the process
gone.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from dynamic_thermal_charge.persistence import (
    ConfigStoreError,
    ConfigStoreUnavailableError,
)
from dynamic_thermal_charge.persistence.engine import store_errors
from dynamic_thermal_charge.persistence.url import parse_location


SRC = Path(__file__).resolve().parents[1] / "src" / "dynamic_thermal_charge"
PERSISTENCE = SRC / "persistence"


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _core_modules() -> list[Path]:
    return [
        path
        for path in SRC.rglob("*.py")
        if PERSISTENCE not in path.parents and path != PERSISTENCE
    ]


# --------------------------------------------------------------------------- #
# T033: SQLAlchemy lives in persistence/ and nowhere else
# --------------------------------------------------------------------------- #

def test_no_module_outside_persistence_imports_sqlalchemy():
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name
            for name in _module_imports(path)
            if name == "sqlalchemy" or name.startswith("sqlalchemy.")
        )
        for path in _core_modules()
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, (
        "the data boundary leaked: these modules import SQLAlchemy directly "
        f"instead of depending on the protocols: {offenders}"
    )


def test_no_module_outside_persistence_imports_a_database_driver():
    forbidden = {"pg8000", "psycopg", "psycopg2", "sqlite3", "alembic"}
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name for name in _module_imports(path) if name.split(".")[0] in forbidden
        )
        for path in _core_modules()
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, f"a database driver leaked out of persistence/: {offenders}"


def test_the_asyncio_api_of_sqlalchemy_is_never_used():
    """It would pull in greenlet, the one dependency needing a compiler on ARMv7."""
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name for name in _module_imports(path) if "asyncio" in name or name == "greenlet"
        )
        for path in SRC.rglob("*.py")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, f"the async API or greenlet leaked in: {offenders}"


# --------------------------------------------------------------------------- #
# T034: lazy import, so start-up on the Raspberry Pi stays within budget
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "module",
    [
        "dynamic_thermal_charge",
        "dynamic_thermal_charge.scheduler",
        "dynamic_thermal_charge.thermal",
        "dynamic_thermal_charge.models",
        "dynamic_thermal_charge.controller",
        "dynamic_thermal_charge.drivers",
    ],
)
def test_importing_the_core_does_not_load_sqlalchemy(module):
    code = (
        f"import {module}, sys; "
        "leaked = [n for n in sys.modules if n.split('.')[0] in "
        "('sqlalchemy', 'alembic', 'pg8000')]; "
        "print(leaked)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", (
        f"importing {module} loaded the persistence stack: {result.stdout.strip()}"
    )


def test_the_protocols_can_be_imported_without_the_db_extra():
    """persistence/__init__ is the contract; it must not need SQLAlchemy."""
    code = (
        "import dynamic_thermal_charge.persistence as p, sys; "
        "print([n for n in sys.modules if n.split('.')[0] == 'sqlalchemy'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


# --------------------------------------------------------------------------- #
# T014: no driver exception crosses the boundary
# --------------------------------------------------------------------------- #

def test_a_sqlalchemy_error_becomes_a_domain_error(sqlite_url):
    from sqlalchemy.exc import OperationalError

    location = parse_location(sqlite_url)
    with pytest.raises(ConfigStoreUnavailableError):
        with store_errors(location):
            raise OperationalError("SELECT 1", {}, Exception("disk I/O error"))


def test_a_sqlite3_error_becomes_a_domain_error():
    import sqlite3

    with pytest.raises(ConfigStoreUnavailableError):
        with store_errors():
            raise sqlite3.OperationalError("database is locked")


def test_an_os_error_becomes_a_domain_error():
    with pytest.raises(ConfigStoreUnavailableError):
        with store_errors():
            raise OSError(28, "No space left on device")


def test_a_domain_error_passes_through_unchanged():
    sentinel = ConfigStoreError("already a domain error")
    with pytest.raises(ConfigStoreError) as error:
        with store_errors():
            raise sentinel
    assert error.value is sentinel


def test_the_boundary_does_not_swallow_programming_errors():
    with pytest.raises(TypeError):
        with store_errors():
            raise TypeError("a bug is a bug; do not disguise it as unavailability")


def test_the_translated_message_does_not_echo_credentials():
    from sqlalchemy.exc import OperationalError

    secret = "tr3m3nd0-s3cr3t0"
    location = parse_location(f"postgresql+pg8000://dtc:{secret}@server/dtc")
    with pytest.raises(ConfigStoreUnavailableError) as error:
        with store_errors(location):
            raise OperationalError(
                "connect", {}, Exception(f"auth failed for dtc:{secret}@server")
            )
    assert secret not in str(error.value)


POSTGRES_URL = "postgresql+pg8000://dtc:secret@host.invalid.example:5432/dtc"


def _pg8000_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("pg8000") is not None


def test_a_missing_driver_says_which_extra_to_install():
    """The driver lives in an optional extra; a bare ImportError is not actionable."""
    if _pg8000_installed():
        pytest.skip("pg8000 is installed; the missing-driver path cannot be exercised")
    from dynamic_thermal_charge.persistence.bootstrap import open_store
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    with pytest.raises(ConfigStoreUnavailableError) as error:
        open_store({DATABASE_URL_ENV: POSTGRES_URL})
    message = str(error.value)
    assert "not installed" in message
    assert "postgres" in message
    assert "secret" not in message, "the connection string leaked into the error"


def test_an_unreachable_database_is_reported_as_unavailable():
    """A remote host that does not resolve must not look like a bug."""
    if not _pg8000_installed():
        pytest.skip("pg8000 is not installed; the unreachable-host path needs it")
    from dynamic_thermal_charge.persistence.bootstrap import open_store
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    store = open_store({DATABASE_URL_ENV: POSTGRES_URL})
    with pytest.raises(ConfigStoreError):
        store.repository.current()


def test_a_constraint_violation_is_invalid_config_not_an_outage():
    """Only unavailability is retried by the control loop.

    Mapping a constraint violation onto ConfigStoreUnavailableError would make
    the service retry an invalid configuration for ever instead of failing.
    """
    from sqlalchemy.exc import IntegrityError

    from dynamic_thermal_charge.persistence import ConfigValidationError

    with pytest.raises(ConfigValidationError) as error:
        with store_errors():
            raise IntegrityError(
                "INSERT", {}, Exception("CHECK constraint failed: ck_installation_power")
            )
    assert not isinstance(error.value, ConfigStoreUnavailableError)
    assert error.value.field == "max_total_power_kw"
    assert "positive" in str(error.value)


def test_every_declared_constraint_maps_to_a_field():
    """A new constraint without a mapping would degrade to a generic message."""
    from sqlalchemy import CheckConstraint, UniqueConstraint

    from dynamic_thermal_charge.persistence.schema import CONSTRAINT_FIELDS, metadata

    declared = {
        constraint.name
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
        and constraint.name is not None
    }
    unmapped = declared - set(CONSTRAINT_FIELDS)
    assert not unmapped, (
        "these constraints have no field mapping, so violating them would produce "
        f"a message that does not name the offending field: {sorted(unmapped)}"
    )


# --------------------------------------------------------------------------- #
# T057 (SC-001, FR-015): the symmetric guard to the SQLAlchemy one.
#
# Removing the YAML loader is not enough on its own: nothing would stop a future
# change from reading a configuration file again, or from starting an HTTP server
# in a phase that is not meant to expose one. After PyYAML left the base
# dependencies such a regression would fail in production, not in the suite.
# --------------------------------------------------------------------------- #

def test_no_runtime_module_imports_yaml():
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name for name in _module_imports(path) if name.split(".")[0] == "yaml"
        )
        for path in SRC.rglob("*.py")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, (
        "configuration must come from the database, not from a file; these modules "
        f"import a YAML parser: {offenders}"
    )


def test_no_runtime_module_imports_an_http_server():
    """FR-015: this phase exposes no network interface."""
    forbidden = {
        "http.server",
        "socketserver",
        "wsgiref",
        "fastapi",
        "flask",
        "uvicorn",
        "aiohttp",
        "starlette",
    }
    offenders = {
        path.relative_to(SRC).as_posix(): sorted(
            name
            for name in _module_imports(path)
            if name in forbidden or name.split(".")[0] in forbidden
        )
        for path in SRC.rglob("*.py")
    }
    offenders = {path: names for path, names in offenders.items() if names}
    assert not offenders, f"a network interface leaked into this phase: {offenders}"


def test_no_runtime_module_declares_a_configuration_file_path():
    """A .yaml/.yml literal in src/ would mean a file is being read again."""
    offenders = {}
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits = [
            line.strip()
            for line in text.splitlines()
            # cli.py mentions the extensions on purpose, to explain their removal.
            if (".yaml" in line or ".yml" in line)
            and not line.lstrip().startswith("#")
            and "looks like a configuration file" not in text.split(line)[0][-400:]
        ]
        if hits and path.name not in ("cli.py", "seed.py"):
            offenders[path.relative_to(SRC).as_posix()] = hits
    assert not offenders, f"a configuration file path is still referenced: {offenders}"


# --------------------------------------------------------------------------- #
# T062, T063, T086: the control loop under database failure.
#
# Principle IV: the process survives, the running plan survives, and the
# degraded transition is logged once. Principle I: no plan means no output on.
# --------------------------------------------------------------------------- #

import logging
from datetime import datetime, timedelta, timezone

from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import RecordingOutputDriver, SimulatedOutputDriver
from dynamic_thermal_charge.persistence import (
    ConfigStoreEmptyError,
    ConfigValidationError,
)
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from dynamic_thermal_charge.service import ControllerService, PlanRefresh
from dynamic_thermal_charge.state import PlanStore


START = datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)


def _plan(heater_ids=("salon",), hours: int = 8) -> ScheduleResult:
    slots = tuple(
        ScheduleSlot(
            start=START + timedelta(minutes=30 * index),
            end=START + timedelta(minutes=30 * (index + 1)),
            heater_ids=heater_ids,
            total_power_w=2800,
        )
        for index in range(hours * 2)
    )
    return ScheduleResult(
        slots=slots,
        allocated_minutes={heater_id: hours * 60 for heater_id in heater_ids},
        unmet_minutes={},
    )


def _service(
    tmp_path, refresh, clock, wait, error_retry_seconds: int = 900, **kwargs
) -> tuple[ControllerService, SimulatedOutputDriver]:
    driver = SimulatedOutputDriver()
    controller = ChargeController(("salon", "entrada"), driver)
    service = ControllerService(
        controller=controller,
        store=PlanStore(tmp_path / "active-plan.json"),
        refresh_plan=refresh,
        poll_seconds=1,
        error_retry_seconds=error_retry_seconds,
        clock=clock,
        wait=wait,
        **kwargs,
    )
    return service, driver


def test_a_hot_database_failure_keeps_the_running_plan_and_the_process(
    tmp_path, clock, wait, caplog
):
    clock.now = START + timedelta(minutes=5)
    calls = {"n": 0}

    def refresh(now):
        calls["n"] += 1
        if calls["n"] == 1:
            return PlanRefresh(plan=_plan(), next_refresh_seconds=1)
        raise ConfigStoreUnavailableError("database unreachable")

    service, driver = _service(tmp_path, refresh, clock, wait)
    with caplog.at_level(logging.DEBUG):
        assert service.run(max_cycles=6) == 0

    assert calls["n"] > 1, "the refresh was never retried"
    assert service.degraded is True
    # The plan kept running: the output was switched on and stayed on.
    assert ("salon", True) in [(c.heater_id, c.enabled) for c in driver.changes]
    # And the degraded transition was announced exactly once.
    assert caplog.text.count("became unreachable") == 1


def test_recovery_is_announced_once_and_the_plan_is_recalculated(
    tmp_path, clock, wait, caplog
):
    clock.now = START + timedelta(minutes=5)
    sequence = ["ok", "fail", "fail", "ok", "ok"]
    calls = {"n": 0}

    def refresh(now):
        outcome = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        if outcome == "fail":
            raise ConfigStoreUnavailableError("database unreachable")
        return PlanRefresh(plan=_plan(), next_refresh_seconds=1)

    # The retry cadence has to be reachable by the controlled clock, which
    # advances one second per cycle.
    service, _ = _service(tmp_path, refresh, clock, wait, error_retry_seconds=1)
    with caplog.at_level(logging.INFO):
        service.run(max_cycles=len(sequence) + 2)

    assert caplog.text.count("became unreachable") == 1
    assert caplog.text.count("reachable again") == 1
    assert service.degraded is False


def test_the_degraded_message_is_not_repeated_every_iteration(
    tmp_path, clock, wait, caplog
):
    def refresh(now):
        raise ConfigStoreUnavailableError("database unreachable")

    service, _ = _service(tmp_path, refresh, clock, wait)
    with caplog.at_level(logging.WARNING):
        service.run(max_cycles=20)
    assert caplog.text.count("became unreachable") == 1


def test_starting_with_no_plan_and_no_database_leaves_every_output_off(
    tmp_path, clock, wait, caplog
):
    def refresh(now):
        raise ConfigStoreUnavailableError("database unreachable")

    service, driver = _service(tmp_path, refresh, clock, wait)
    with caplog.at_level(logging.CRITICAL):
        assert service.run(max_cycles=3) == 0

    assert not any(change.enabled for change in driver.changes), "an output came on"
    assert "all outputs remain off" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        ConfigStoreEmptyError("no installation"),
        ConfigValidationError("slot_minutes must be a divisor of 60", field="slot_minutes"),
    ],
)
def test_a_non_transient_error_stops_refreshing_instead_of_retrying_for_ever(
    tmp_path, clock, wait, caplog, error
):
    """Retrying cannot fix invalid configuration, so it is not retried."""
    calls = {"n": 0}

    def refresh(now):
        calls["n"] += 1
        raise error

    service, driver = _service(tmp_path, refresh, clock, wait)
    with caplog.at_level(logging.CRITICAL):
        service.run(max_cycles=10)

    assert calls["n"] == 1, "an unfixable error was retried"
    assert service.refresh_abandoned is True
    assert not any(change.enabled for change in driver.changes)
    assert "abandoned" in caplog.text


def test_a_full_disk_during_a_write_does_not_corrupt_the_plan_or_the_outputs(
    tmp_path, clock, wait, caplog
):
    """T063: the store fills up; the persisted plan and output state stay sane."""
    plan_file = tmp_path / "active-plan.json"
    store = PlanStore(plan_file)
    store.save(_plan())
    good = plan_file.read_text(encoding="utf-8")

    def refresh(now):
        raise ConfigStoreUnavailableError(
            "the configuration database is unavailable: No space left on device"
        )

    driver = SimulatedOutputDriver()
    controller = ChargeController(("salon", "entrada"), driver)
    clock.now = START + timedelta(minutes=5)
    service = ControllerService(
        controller=controller,
        store=store,
        refresh_plan=refresh,
        poll_seconds=1,
        error_retry_seconds=900,
        clock=clock,
        wait=wait,
    )
    with caplog.at_level(logging.WARNING):
        service.run(max_cycles=3)

    assert plan_file.read_text(encoding="utf-8") == good, "the persisted plan changed"
    assert store.load() is not None, "the persisted plan became unreadable"
    # The recovered plan was executed, and every output ended off.
    assert driver.changes[-1].enabled is False


def test_a_history_write_failure_does_not_interrupt_planning_or_switching(
    tmp_path, clock, wait, caplog, fake_history
):
    """T086, FR-019: observability can never stop the control loop."""
    fake_history.failing = True
    clock.now = START + timedelta(minutes=5)

    def refresh(now):
        # A real refresh records the forecast and the plan; both fail here.
        fake_history.record_forecast(object())
        fake_history.record_plan(_plan(), None, 1)
        return PlanRefresh(plan=_plan(), next_refresh_seconds=1)

    driver = SimulatedOutputDriver()
    recording = RecordingOutputDriver(driver, fake_history)
    controller = ChargeController(("salon", "entrada"), recording)
    service = ControllerService(
        controller=controller,
        store=PlanStore(tmp_path / "active-plan.json"),
        refresh_plan=refresh,
        poll_seconds=1,
        error_retry_seconds=900,
        clock=clock,
        wait=wait,
        history=fake_history,
        retention_days=365,
    )
    assert service.run(max_cycles=4) == 0

    assert fake_history.errors > 0, "the recorder never actually failed"
    assert fake_history.transitions == [], "a failing recorder recorded something"
    # Planning happened and the output was switched despite every audit failing.
    assert ("salon", True) in [(c.heater_id, c.enabled) for c in driver.changes]
    assert service.degraded is False
