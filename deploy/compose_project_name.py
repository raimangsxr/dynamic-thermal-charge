#!/usr/bin/env python3
"""Calculate the stable Docker Compose project name for a checkout."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_COMPOSE_NAME_LENGTH = 63
HASH_LENGTH = 12
PROJECT_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


def checkout_path(argument: str | None = None) -> Path:
    if argument:
        return Path(argument).expanduser().resolve()
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd().resolve()
    return Path(root).resolve()


def project_name(root: Path) -> str:
    resolved = str(root.resolve())
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "checkout"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:HASH_LENGTH]
    prefix_length = MAX_COMPOSE_NAME_LENGTH - HASH_LENGTH - 1
    prefix = f"dtc-{slug}"[:prefix_length].rstrip("-")
    return f"{prefix}-{digest}"


def validate_project_name(value: str) -> str:
    if len(value) > MAX_COMPOSE_NAME_LENGTH or not PROJECT_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "COMPOSE_PROJECT_NAME must start with a lowercase letter or number, "
            "contain only lowercase letters, numbers, '_' or '-', and be at most "
            f"{MAX_COMPOSE_NAME_LENGTH} characters"
        )
    return value


def main() -> int:
    override = os.environ.get("COMPOSE_PROJECT_NAME")
    try:
        value = (
            validate_project_name(override)
            if override
            else project_name(checkout_path(sys.argv[1] if len(sys.argv) > 1 else None))
        )
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
