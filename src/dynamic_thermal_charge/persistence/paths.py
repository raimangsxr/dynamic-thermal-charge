"""Deterministic local paths for the four logical stores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PRODUCTION_STATE_DIRECTORY = Path("/var/lib/dynamic-thermal-charge")


@dataclass(frozen=True)
class StorePaths:
    """All local stores derived from one explicit state directory.

    Production code uses :meth:`production`; tests and administrative tooling
    inject a directory with :meth:`in_directory`.  Environment variables are
    deliberately not consulted here.
    """

    state_directory: Path

    def __post_init__(self) -> None:
        directory = self.state_directory
        if not directory.is_absolute():
            raise ValueError("the state directory must be an absolute path")

    @classmethod
    def production(cls) -> "StorePaths":
        return cls(PRODUCTION_STATE_DIRECTORY)

    @classmethod
    def in_directory(cls, directory: str | Path) -> "StorePaths":
        return cls(Path(directory))

    @property
    def bootstrap(self) -> Path:
        return self.state_directory / "bootstrap.db"

    @property
    def fallback(self) -> Path:
        return self.state_directory / "fallback.db"

    @property
    def configuration(self) -> Path:
        return self.state_directory / "configuration.db"

    @property
    def application(self) -> Path:
        return self.state_directory / "application.db"

    def sqlite_url(self, store: str) -> str:
        try:
            path = {
                "bootstrap": self.bootstrap,
                "fallback": self.fallback,
                "configuration": self.configuration,
                "application": self.application,
            }[store]
        except KeyError as exc:
            raise ValueError(f"unknown local store {store!r}") from exc
        return f"sqlite:///{path}"


__all__ = ["PRODUCTION_STATE_DIRECTORY", "StorePaths"]
