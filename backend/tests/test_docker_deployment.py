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
    assert "/dev/gpiochip0:/dev/gpiochip0" in compose
    assert "source: /proc/device-tree/model" in compose
    assert "target: /run/dynamic-thermal-charge/raspberry-pi-model" in compose
    assert "read_only: true" in compose
    assert 'user: "${DTC_RUNTIME_UID:-1000}:${DTC_RUNTIME_GID:-1000}"' in compose
    assert 'group_add: ["${DTC_GPIO_GID:-997}"]' in compose
    assert "LG_WD: /tmp" in compose
    assert "condition: service_healthy" in compose
    assert "run_api(bind_host='0.0.0.0', bind_port=8080)" in compose


def test_backend_image_runs_idempotent_initialisation_before_its_process() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/usr/local/bin/dynamic-thermal-charge-entrypoint"]' in dockerfile
    assert "install -d -m 0755 /run/dynamic-thermal-charge" in dockerfile
    assert "from dynamic_thermal_charge.entrypoints import initialise_storage" in entrypoint
    assert 'DTC_API_TOKEN:?set DTC_API_TOKEN in /etc/app/app.env' in entrypoint
    assert "from dynamic_thermal_charge.entrypoints import run_controller" in dockerfile
    assert 'exec "$@"' in entrypoint


def test_reconciler_passes_the_host_gpio_group_to_compose() -> None:
    reconciler = (ROOT / "deploy" / "reconcile.sh").read_text(encoding="utf-8")
    assert 'stat -c \'%g\' /dev/gpiochip0' in reconciler
    assert "DTC_GPIO_GID" in reconciler


def test_deployment_has_no_application_cli_invocations_or_modules() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "python -m dynamic_thermal_charge" not in compose + dockerfile + entrypoint
    assert not (ROOT / "backend" / "src" / "dynamic_thermal_charge" / "cli.py").exists()
    assert not (ROOT / "backend" / "src" / "dynamic_thermal_charge" / "__main__.py").exists()
    assert not (ROOT / "backend" / "tests" / "test_cli_config_commands.py").exists()


def test_no_legacy_non_docker_installation_artifacts_remain() -> None:
    assert not (ROOT / "scripts").exists()
    assert not (ROOT / "deploy" / "systemd").exists()
    assert not (ROOT / "deploy" / "install-service.sh").exists()
