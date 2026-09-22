"""Checks for deterministic Compose project isolation."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "compose_project_name.py"


def project_name(path: Path) -> str:
    return subprocess.check_output(
        [sys.executable, str(SCRIPT), str(path)],
        text=True,
    ).strip()


def test_project_name_is_stable_for_the_same_checkout(tmp_path):
    checkout = tmp_path / "Developer1"
    checkout.mkdir()

    assert project_name(checkout) == project_name(checkout / ".").strip()


def test_project_name_is_distinct_and_compose_compatible_for_two_checkouts(tmp_path):
    first = project_name(tmp_path / "Codex-top")
    second = project_name(tmp_path / "Developer2")

    assert first != second
    assert len(first) <= 63
    assert len(second) <= 63
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", first)
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", second)


def test_project_name_accepts_a_valid_explicit_override(tmp_path):
    checkout = tmp_path / "Developer1"
    checkout.mkdir()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "COMPOSE_PROJECT_NAME": "ci-worktree-42"},
    )

    assert result.stdout.strip() == "ci-worktree-42"


def test_project_name_rejects_an_invalid_explicit_override(tmp_path):
    checkout = tmp_path / "Developer1"
    checkout.mkdir()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(checkout)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "COMPOSE_PROJECT_NAME": "Invalid Name"},
    )

    assert result.returncode == 2
    assert "COMPOSE_PROJECT_NAME" in result.stderr


def test_makefile_reuses_the_project_name_for_both_dev_variants():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "deploy/compose_project_name.py" in makefile
    assert "COMPOSE_DEV_POSTGRES = $(COMPOSE_DEV) -f deploy/compose.dev-postgres.yaml" in makefile
    assert "compose-down-postgres:" in makefile
    assert "compose-clean-postgres:" in makefile
