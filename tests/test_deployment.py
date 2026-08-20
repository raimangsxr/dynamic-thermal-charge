from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]


def test_installer_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "install-service.sh")],
        check=True,
    )


def test_systemd_unit_runs_safe_simulated_controller() -> None:
    unit = (
        ROOT / "deploy" / "systemd" / "dynamic-thermal-charge.service"
    ).read_text(encoding="utf-8")

    assert "--check-config" in unit
    assert "--run-controller" in unit
    assert "KillSignal=SIGTERM" in unit
    assert "Restart=on-failure" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/var/lib/dynamic-thermal-charge" in unit


def test_gpio_override_requires_explicit_real_driver_and_gpio_group() -> None:
    override = (
        ROOT / "deploy" / "systemd" / "gpio.conf.example"
    ).read_text(encoding="utf-8")

    assert "SupplementaryGroups=gpio" in override
    assert "--driver gpio" in override


def test_environment_example_contains_no_secret() -> None:
    environment = (ROOT / "deploy" / "environment.example").read_text(
        encoding="utf-8"
    )

    assert "AEMET_API_KEY=" in environment
    assert "eyJ" not in environment
