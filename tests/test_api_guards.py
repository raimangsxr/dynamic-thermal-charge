"""Architectural guards: SC-003, SC-004, FR-045, FR-046.

These are what make "no API route can operate an output" a verified property
rather than a claim (constitution principle I).
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest


SRC = Path(__file__).resolve().parents[1] / "src" / "dynamic_thermal_charge"
API = SRC / "api"


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def _api_modules() -> list[Path]:
    return sorted(API.rglob("*.py"))


# --------------------------------------------------------------------------- #
# SC-004: no route can operate an output
# --------------------------------------------------------------------------- #

def test_no_api_module_imports_a_driver():
    forbidden = {"drivers", "gpio_driver", "controller", "GpioOutputDriver",
                 "SimulatedOutputDriver", "OutputDriver", "ChargeController"}
    offenders = {}
    for path in _api_modules():
        leaked = sorted(
            name
            for name in _module_imports(path)
            if name.rsplit(".", 1)[-1] in forbidden
        )
        if leaked:
            offenders[path.relative_to(SRC).as_posix()] = leaked
    assert not offenders, (
        "the API gained access to the means of switching a relay; no route may "
        f"be able to operate an output (principle I): {offenders}"
    )


def test_no_api_module_mounts_static_files():
    """FR-045: serving an interface is a later phase."""
    offenders = {}
    for path in _api_modules():
        text = path.read_text(encoding="utf-8")
        if "StaticFiles" in text or "mount(" in text:
            offenders[path.relative_to(SRC).as_posix()] = "static mount"
    assert not offenders, f"static file serving leaked into this phase: {offenders}"


def test_the_api_never_imports_the_async_stack():
    """It would reintroduce greenlet, the one dependency needing a compiler."""
    offenders = {}
    for path in _api_modules():
        leaked = sorted(
            name
            for name in _module_imports(path)
            if "sqlalchemy.ext.asyncio" in name or name == "greenlet"
        )
        if leaked:
            offenders[path.relative_to(SRC).as_posix()] = leaked
    assert not offenders, f"the async stack leaked in: {offenders}"


def test_every_route_handler_is_synchronous():
    """An async handler calling the sync repository would block the event loop.

    While waiting on a remote database the whole API would stop answering, and
    the alternative -- SQLAlchemy's asyncio API -- brings back greenlet.
    """
    from dynamic_thermal_charge.api import create_app
    from dynamic_thermal_charge.api.settings import ApiSettings
    from dynamic_thermal_charge.api.routes import config, docs, health, history, status

    app = create_app(settings=ApiSettings(token="g" * 40))
    # Collected from the routers, because app.routes wraps included routers and
    # iterating it naively finds nothing -- which would make this guard vacuous.
    handlers = [
        route.endpoint
        for module in (status, config, history, health, docs)
        for route in module.router.routes
        if hasattr(route, "endpoint")
    ]
    assert len(handlers) >= 10, (
        f"only {len(handlers)} handlers found; the guard would be vacuous"
    )
    coroutines = [
        handler.__qualname__
        for handler in handlers
        if inspect.iscoroutinefunction(handler)
    ]
    assert not coroutines, (
        f"these handlers are async and would block the event loop: {coroutines}"
    )


# --------------------------------------------------------------------------- #
# FR-046: the core runs without the api extra
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
        "dynamic_thermal_charge.service",
        "dynamic_thermal_charge.cli",
        "dynamic_thermal_charge.api.settings",
    ],
)
def test_importing_this_does_not_load_the_web_stack(module):
    code = (
        f"import {module}, sys; "
        "print([n for n in sys.modules if n.split('.')[0] in "
        "('fastapi', 'uvicorn', 'starlette', 'pydantic')])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", (
        f"importing {module} loaded the web stack: {result.stdout.strip()}"
    )


# --------------------------------------------------------------------------- #
# SC-003: the control loop does not need the API
# --------------------------------------------------------------------------- #

def test_the_control_loop_runs_without_the_api_installed(tmp_path):
    """The automatable half of SC-003.

    Runs a full control cycle in a subprocess that imports nothing from api/, and
    fails if the web stack turns out to be loaded. The other half -- stopping the
    API while a plan is in progress -- is the manual check on the device.
    """
    code = f'''
import sys
from datetime import datetime, timedelta, timezone
from dynamic_thermal_charge.controller import ChargeController
from dynamic_thermal_charge.drivers import SimulatedOutputDriver
from dynamic_thermal_charge.scheduler import ScheduleResult, ScheduleSlot
from dynamic_thermal_charge.service import ControllerService, PlanRefresh
from dynamic_thermal_charge.state import PlanStore

start = datetime(2026, 1, 16, tzinfo=timezone.utc)
slots = tuple(
    ScheduleSlot(
        start=start + timedelta(minutes=30 * i),
        end=start + timedelta(minutes=30 * (i + 1)),
        heater_ids=("salon",),
        total_power_w=2800,
    )
    for i in range(16)
)
plan = ScheduleResult(slots=slots, allocated_minutes={{"salon": 480}}, unmet_minutes={{}})
driver = SimulatedOutputDriver()
now = [start + timedelta(minutes=5)]
service = ControllerService(
    controller=ChargeController(("salon",), driver),
    store=PlanStore(r"{tmp_path}/plan.json"),
    refresh_plan=lambda _n: PlanRefresh(plan=plan, next_refresh_seconds=3600),
    poll_seconds=1,
    error_retry_seconds=60,
    clock=lambda: now[0],
    wait=lambda s: now.__setitem__(0, now[0] + timedelta(seconds=s)),
    # No heartbeat publisher at all: the API is optional for the controller.
)
service.run(max_cycles=3)
switched_on = [c for c in driver.changes if c.enabled]
web = [n for n in sys.modules if n.split(".")[0] in ("fastapi", "uvicorn", "starlette")]
print("ON" if switched_on else "OFF", "WEB" if web else "NOWEB")
'''
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "ON NOWEB", (
        f"the control loop needs the API, or loaded it: {result.stdout.strip()!r} "
        f"{result.stderr[-500:]}"
    )


# --------------------------------------------------------------------------- #
# The api subcommand builds no driver either
# --------------------------------------------------------------------------- #

def test_the_api_subcommand_builds_no_output_driver(monkeypatch, sqlite_url, capsys):
    from dynamic_thermal_charge import cli
    from dynamic_thermal_charge.api.settings import TOKEN_ENV
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    monkeypatch.setenv(TOKEN_ENV, "s" * 40)
    monkeypatch.setattr(
        cli,
        "_build_output_driver",
        lambda *a, **k: pytest.fail("the api subcommand built an output driver"),
    )
    served: dict = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.update(kw))
    assert cli.main(["api"]) == cli.EXIT_OK
    assert served["host"] == "127.0.0.1"
    assert served["port"] == 8420


def test_the_api_subcommand_refuses_an_unusable_token(monkeypatch, sqlite_url, capsys):
    from dynamic_thermal_charge import cli
    from dynamic_thermal_charge.api.settings import TOKEN_ENV
    from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV

    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert cli.main(["api"]) == cli.EXIT_INVALID_RESULT
    assert TOKEN_ENV in capsys.readouterr().err
