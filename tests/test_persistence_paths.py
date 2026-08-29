from pathlib import Path

import pytest

from dynamic_thermal_charge.persistence.paths import (
    PRODUCTION_STATE_DIRECTORY,
    StorePaths,
)


def test_production_paths_are_fixed_and_separate(monkeypatch):
    monkeypatch.setenv("DTC_DATABASE_URL", "postgresql://ignored/ignored")
    paths = StorePaths.production()

    assert paths.state_directory == PRODUCTION_STATE_DIRECTORY
    assert {path.name for path in (
        paths.bootstrap,
        paths.fallback,
        paths.configuration,
        paths.application,
    )} == {"bootstrap.db", "fallback.db", "configuration.db", "application.db"}
    assert paths.sqlite_url("bootstrap") == (
        "sqlite:////var/lib/dynamic-thermal-charge/bootstrap.db"
    )


def test_tests_can_inject_an_explicit_absolute_directory(tmp_path):
    paths = StorePaths.in_directory(tmp_path)
    assert paths.bootstrap == tmp_path / "bootstrap.db"
    assert paths.sqlite_url("application") == f"sqlite:///{tmp_path / 'application.db'}"


def test_relative_and_unknown_paths_are_rejected():
    with pytest.raises(ValueError, match="absolute"):
        StorePaths.in_directory(Path("relative"))
    with pytest.raises(ValueError, match="unknown local store"):
        StorePaths.production().sqlite_url("other")
