"""Architectural guards over the web panel.

These live here, with the guards that already protect the SQLAlchemy boundary,
because the pattern is the same: a static scan of the sources that fails when a
boundary is crossed. Keeping them in pytest means they run with every other
guard, need no extra frontend dependency, and cannot be skipped by someone who
only runs the Python suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "src" / "app"

pytestmark = pytest.mark.skipif(
    not APP.is_dir(), reason="the web panel is not present in this checkout"
)


def _production_sources() -> list[Path]:
    return [
        path
        for path in APP.rglob("*.ts")
        if not path.name.endswith(".spec.ts")
    ]


def _code_only(text: str) -> str:
    """Strip comments before scanning.

    Every one of these guards documents its own ban in a comment next to the
    code, and a naive substring search matches that prose. The phase-2 guard on
    forbidden dependencies hit exactly this: it failed against the comment
    explaining why uvicorn[standard] is banned. Scan code, not prose.
    """
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(
        line for line in without_block.splitlines() if not line.strip().startswith("//")
    )


# --------------------------------------------------------------------------- #
# FR-016: ages come from the API, never from the browser clock.
#
# `age.ts` formats an age it is GIVEN. Without this guard a future component
# would reach for Date.now(), the panel would show impossible ages when the
# phone and the Raspberry Pi disagree -- the Pi has no battery-backed clock, so a
# fresh boot before time sync is a real scenario -- and nothing would fail.
# Precisely in the indicator the operator uses to decide whether to trust the
# screen.
# --------------------------------------------------------------------------- #

CLOCK_ALLOWED = {
    "shared/age/age.ts",
}


def test_the_guard_finds_sources_so_it_is_not_vacuous() -> None:
    assert len(_production_sources()) > 3


def test_no_module_computes_an_age_from_the_local_clock() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _production_sources():
        key = path.relative_to(APP).as_posix()
        if key in CLOCK_ALLOWED:
            continue
        text = _code_only(path.read_text(encoding="utf-8"))
        hits = []
        if "Date.now(" in text:
            hits.append("Date.now()")
        # `new Date(x)` parses an instant the API gave us and is fine.
        # `new Date()` with no argument reads the local clock and is not.
        if re.search(r"new Date\(\s*\)", text):
            hits.append("new Date()")
        if "performance.now(" in text:
            hits.append("performance.now()")
        if hits:
            offenders[key] = hits
    assert not offenders, (
        "these modules reach for the browser clock; ages must come from the API, "
        f"which computed them against the same clock that wrote the heartbeat: {offenders}"
    )


# --------------------------------------------------------------------------- #
# FR-004 (phase 2 contract): the panel never puts the credential in the URL.
# There it would end up in the browser history and in nginx's logs.
# --------------------------------------------------------------------------- #

def test_the_credential_never_travels_in_a_url() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _production_sources():
        text = _code_only(path.read_text(encoding="utf-8"))
        hits = [
            line.strip()
            for line in text.splitlines()
            if re.search(r"[?&](token|api_key|apikey|auth)=", line, re.IGNORECASE)
        ]
        if hits:
            offenders[path.relative_to(APP).as_posix()] = hits
    assert not offenders, f"the credential leaked into a URL: {offenders}"


def test_the_credential_is_not_written_to_persistent_storage() -> None:
    """FR-002: it must not survive closing the tab."""
    offenders: dict[str, list[str]] = {}
    for path in _production_sources():
        text = _code_only(path.read_text(encoding="utf-8"))
        hits = [
            token
            for token in ("localStorage", "indexedDB", "document.cookie")
            if token in text
        ]
        if hits:
            offenders[path.relative_to(APP).as_posix()] = hits
    assert not offenders, (
        "the panel uses persistent browser storage; the credential must live in "
        f"sessionStorage only, so it dies with the tab: {offenders}"
    )


# --------------------------------------------------------------------------- #
# The panel cannot switch an output. The API offers no such operation, and the
# panel must not suggest one exists.
# --------------------------------------------------------------------------- #

def test_the_panel_calls_no_operation_that_would_switch_an_output() -> None:
    forbidden = ("/override", "/boost", "/switch", "/outputs/", "/force")
    offenders: dict[str, list[str]] = {}
    for path in _production_sources():
        text = _code_only(path.read_text(encoding="utf-8"))
        hits = [name for name in forbidden if name in text]
        if hits:
            offenders[path.relative_to(APP).as_posix()] = hits
    assert not offenders, (
        f"the panel references an output-switching operation: {offenders}"
    )


# --------------------------------------------------------------------------- #
# FR-037, SC-010: built off-device, and neither the dependencies nor the built
# artefact enter the repository.
# --------------------------------------------------------------------------- #

def test_the_repository_ignores_the_dependencies_and_the_build() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("frontend/node_modules", "frontend/dist"):
        assert pattern in ignored, (
            f"{pattern} is not ignored; 253 MB of dependencies or the built "
            "artefact could end up committed"
        )


def test_the_package_manifest_warns_against_building_on_the_device() -> None:
    manifest = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    description = manifest.get("description", "").lower()
    assert "raspberry" in description or "off-device" in description, (
        "the manifest should say where this is built; an npm install on a "
        "Cortex-A7 with 1 GB does not finish"
    )


def test_the_bundle_budget_is_declared_so_the_build_fails_when_exceeded() -> None:
    """Without a declared budget, a dependency added 'just to try' slips in."""
    workspace = json.loads((FRONTEND / "angular.json").read_text(encoding="utf-8"))
    budgets = (
        workspace["projects"]["panel"]["architect"]["build"]["configurations"][
            "production"
        ]["budgets"]
    )
    initial = next(budget for budget in budgets if budget["type"] == "initial")
    assert "maximumError" in initial, "the budget only warns; it must fail the build"
    assert initial["maximumError"] == "500kB"


def test_the_development_proxy_points_at_the_local_api() -> None:
    """So no cross-origin configuration is needed in development either."""
    proxy = json.loads((FRONTEND / "proxy.conf.json").read_text(encoding="utf-8"))
    assert proxy["/api"]["target"] == "http://127.0.0.1:8420"
