"""Checks for the supported Docker-only deployment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "compose.yaml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
ENTRYPOINT = ROOT / "backend" / "entrypoint.sh"


def test_docker_compose_contains_the_runtime_services_and_persistent_state() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    for service in ("backend:", "backend-api:", "backend-mqtt:", "frontend:"):
        assert service in compose
    assert "/srv/app/data:/var/lib/dynamic-thermal-charge" in compose
    assert "condition: service_healthy" in compose


def test_backend_image_runs_idempotent_initialisation_before_its_command() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/usr/local/bin/dynamic-thermal-charge-entrypoint"]' in dockerfile
    assert "python -m dynamic_thermal_charge db init --quiet" in entrypoint
    assert '"python", "-m", "dynamic_thermal_charge"' in dockerfile or "python -m dynamic_thermal_charge" in dockerfile
    assert 'exec "$@"' in entrypoint


def test_no_legacy_non_docker_installation_artifacts_remain() -> None:
    assert not (ROOT / "scripts").exists()
    assert not (ROOT / "deploy" / "systemd").exists()
    assert not (ROOT / "deploy" / "install-service.sh").exists()
