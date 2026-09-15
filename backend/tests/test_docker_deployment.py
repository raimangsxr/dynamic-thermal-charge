"""Checks for the supported Docker-only deployment."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy" / "compose.yaml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
ENTRYPOINT = ROOT / "backend" / "entrypoint.sh"
RECONCILER = ROOT / "deploy" / "reconcile.sh"


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
    assert 'group_add: ["${DTC_GPIO_GID:?set DTC_GPIO_GID}"]' in compose
    assert "DTC_GPIO_GID:-997" not in compose
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
    reconciler = RECONCILER.read_text(encoding="utf-8")
    assert 'stat -c \'%g\' /dev/gpiochip0' in reconciler
    assert "if [ ! -c /dev/gpiochip0 ]; then" in reconciler
    assert 'configured_gpio_gid=${DTC_GPIO_GID:-}' in reconciler
    assert '"$configured_gpio_gid" != "$detected_gpio_gid"' in reconciler
    assert 'export DTC_GPIO_GID="$detected_gpio_gid"' in reconciler


def test_reconciler_preflights_before_compose_and_reconciles_unchanged_releases() -> None:
    reconciler = RECONCILER.read_text(encoding="utf-8")
    preflight = reconciler.index("if [ ! -c /dev/gpiochip0 ]; then")
    compose_ps = reconciler.index("docker compose -f deploy/compose.yaml ps")
    compose_config = reconciler.index("docker compose -f deploy/compose.yaml config")
    compose_pull = reconciler.index("docker compose -f deploy/compose.yaml pull")
    release_branch = reconciler.index('if [ "$desired" != "$current" ]; then')
    compose_up = "docker compose -f deploy/compose.yaml up -d --remove-orphans --wait --wait-timeout 120"

    assert preflight < compose_ps < compose_config
    assert release_branch < compose_pull
    assert reconciler.count(compose_up) == 2
    assert compose_pull < reconciler.index(compose_up)


def test_compose_check_supplies_a_deterministic_production_gpio_group() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "DTC_GPIO_GID=986 docker compose -f deploy/compose.yaml config --quiet" in makefile


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
