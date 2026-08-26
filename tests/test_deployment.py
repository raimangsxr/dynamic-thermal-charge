"""Deployment artefacts: FR-029, FR-030, FR-031."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]
UNIT = ROOT / "deploy" / "systemd" / "dynamic-thermal-charge.service"
INSTALLER = ROOT / "scripts" / "install-service.sh"
ENVIRONMENT = ROOT / "deploy" / "environment.example"
OVERRIDE = ROOT / "deploy" / "systemd" / "gpio.conf.example"
README = ROOT / "README.md"


def test_installer_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)


def test_systemd_unit_runs_safe_simulated_controller() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    assert "--check-config" in unit
    assert "run --controller" in unit
    assert "KillSignal=SIGTERM" in unit
    assert "Restart=on-failure" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/var/lib/dynamic-thermal-charge" in unit


def test_the_unit_passes_no_configuration_file() -> None:
    """FR-006: the configuration file argument is gone."""
    unit = UNIT.read_text(encoding="utf-8")
    for line in unit.splitlines():
        if line.startswith(("ExecStart=", "ExecStartPre=")) and line.strip() != "ExecStart=":
            assert ".yaml" not in line, f"the unit still passes a config file: {line}"
            assert ".yml" not in line


def test_gpio_override_requires_explicit_real_driver_and_gpio_group() -> None:
    override = OVERRIDE.read_text(encoding="utf-8")
    assert "SupplementaryGroups=gpio" in override
    assert "--driver gpio" in override
    assert ".yaml" not in override


def test_environment_example_contains_no_secret() -> None:
    environment = ENVIRONMENT.read_text(encoding="utf-8")
    assert "AEMET_API_KEY=" in environment
    assert "eyJ" not in environment
    # The connection string is served here, and it is the only place for it.
    assert "DTC_DATABASE_URL=" in environment
    # A commented-out example may name a placeholder, never a real password.
    assert "PASSWORD" in environment


def test_environment_example_documents_both_backends() -> None:
    environment = ENVIRONMENT.read_text(encoding="utf-8")
    assert "sqlite:" in environment
    assert "postgresql+pg8000:" in environment
    assert "0600" in environment


def test_the_installer_installs_the_db_extra() -> None:
    """Without it the service cannot reach its own configuration."""
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "[db]" in installer
    assert "[db,gpio]" in installer


def test_the_installer_never_seeds_over_a_file_based_install() -> None:
    """FR-030: example data must not come between the operator and their config."""
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "config.yaml.pre-database" in installer
    assert "db init --no-seed" in installer
    assert "NOT migrated automatically" in installer


def test_the_installer_prints_the_single_initialisation_command() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "db init" in installer
    assert "config show" in installer


def test_the_installer_does_not_start_or_enable_the_service() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    for line in installer.splitlines():
        stripped = line.strip()
        if stripped.startswith("systemctl start") or stripped.startswith(
            "systemctl enable"
        ):
            raise AssertionError(f"the installer starts the service: {stripped}")


def test_the_readme_warns_that_configuration_is_not_migrated() -> None:
    """FR-031: the upgrade warning is a requirement, not a nicety."""
    readme = README.read_text(encoding="utf-8")
    assert "DTC_DATABASE_URL" in readme
    assert "no se migra" in readme.lower() or "no migra" in readme.lower()
    assert "active_high" in readme
    assert "db init" in readme


def test_the_readme_links_the_constitution() -> None:
    readme = README.read_text(encoding="utf-8")
    assert ".specify/memory/constitution.md" in readme
