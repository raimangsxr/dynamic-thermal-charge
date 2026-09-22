#!/usr/bin/env python3
"""Validate the checked-in production dependency and image build contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "backend" / "requirements.lock"
PYPROJECT = ROOT / "backend" / "pyproject.toml"
BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"
FRONTEND_DOCKERFILE = ROOT / "frontend" / "Dockerfile"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish-docker-release.yml"

LOCKED_PACKAGE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")
BASE_IMAGE = re.compile(r"^ARG [A-Z_]+=.+@sha256:[0-9a-f]{64}$", re.MULTILINE)


def normalise(name: str) -> str:
    return name.replace("_", "-").lower()


def locked_packages() -> tuple[dict[str, str], set[str]]:
    packages: dict[str, str] = {}
    hashed: set[str] = set()
    current: str | None = None
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = LOCKED_PACKAGE.match(line)
        if match:
            current = normalise(match.group(1))
            if current in packages:
                raise AssertionError(f"duplicate lock entry: {current}")
            packages[current] = match.group(2)
        elif current and "--hash=sha256:" in line:
            hashed.add(current)
    return packages, hashed


def check_lock() -> None:
    contents = LOCK.read_text(encoding="utf-8")
    assert "uv pip compile" in contents, "lock must record its generation command"
    assert "--universal" in contents, "lock must be universal across supported platforms"
    assert "--generate-hashes" in contents, "lock must pin distribution hashes"
    build_lock = (ROOT / "backend" / "build-requirements.lock").read_text(encoding="utf-8")
    assert "setuptools==84.0.0" in build_lock
    assert build_lock.count("--hash=sha256:") == 2

    packages, hashed = locked_packages()
    assert packages, "production lock is empty"
    assert set(packages) == hashed, "every locked package must have at least one hash"

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra in ("api", "mqtt", "gpio", "db", "postgres"):
        requirements.extend(project["optional-dependencies"][extra])

    for raw_requirement in requirements:
        requirement = Requirement(raw_requirement)
        name = normalise(requirement.name)
        assert name in packages, f"{requirement.name} is missing from the production lock"
        assert Version(packages[name]) in requirement.specifier, (
            f"locked {requirement.name}={packages[name]} does not satisfy {requirement.specifier}"
        )

    greenlet = next(
        line for line in contents.splitlines() if line.startswith("greenlet==")
    )
    assert "platform_machine" in greenlet and "armv7" not in greenlet


def check_images() -> None:
    backend = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    frontend = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    workflow = PUBLISH_WORKFLOW.read_text(encoding="utf-8")

    assert BASE_IMAGE.search(backend), "backend base image must be pinned by digest"
    assert "COPY pyproject.toml README.md requirements.lock build-requirements.lock ./" in backend
    assert "--no-build-isolation" in backend
    assert "-r build-requirements.lock" in backend
    assert "--require-hashes" in backend
    assert "COINOR_CBC_VERSION=2.10.12+ds-1" in backend
    assert 'coinor-cbc=${COINOR_CBC_VERSION}' in backend
    assert "cbc-package.txt" in backend

    frontend_bases = re.findall(r"^FROM .+@sha256:[0-9a-f]{64}", frontend, re.MULTILINE)
    assert len(frontend_bases) == 2, "frontend build and runtime bases must be pinned by digest"

    assert "platforms: linux/amd64,linux/arm64,linux/arm/v7" in workflow
    assert workflow.count("sbom: true") == 2
    assert workflow.count("provenance: mode=max") == 2
    assert "sha256sum backend/requirements.lock" in workflow
    assert "sha256sum frontend/package-lock.json" in workflow


def main() -> int:
    try:
        check_lock()
        check_images()
    except (AssertionError, KeyError, StopIteration) as error:
        print(f"delivery check failed: {error}", file=sys.stderr)
        return 1
    print("Delivery lock, image pinning, ARMv7 and publication metadata checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
