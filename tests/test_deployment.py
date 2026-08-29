"""Deployment artefacts: FR-029, FR-030, FR-031."""

from pathlib import Path
import platform
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


# --------------------------------------------------------------------------- #
# FR-047, SC-011: the whole ARMv7 story rests on these never coming back.
#
# uvicorn[standard] pulls uvloop and httptools; greenlet arrives with
# SQLAlchemy's asyncio API. None of the three publishes a linux_armv7l wheel, so
# any of them would need a compiler on the Raspberry Pi and the deployment would
# break -- silently, because the test suite on a development machine would not
# notice. A comment in pyproject.toml documents the ban; this enforces it.
# --------------------------------------------------------------------------- #

PYPROJECT = ROOT / "pyproject.toml"

FORBIDDEN_DEPENDENCIES = (
    "uvicorn[standard]",
    "uvloop",
    "httptools",
    "greenlet",
    # Would compile from source on armv7: no wheel, and it needs libpq.
    "psycopg2",
    "psycopg2-binary",
)


def _declared_requirements() -> list[str]:
    """Every requirement string, from the base list and from every extra.

    Parsed, not grepped: the comment that explains the ban names the forbidden
    packages, and a substring search over the file text matches its own prose.
    """
    import tomllib

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    return requirements


def test_forbidden_dependencies_never_return() -> None:
    requirements = _declared_requirements()
    offenders = [
        requirement
        for requirement in requirements
        for name in FORBIDDEN_DEPENDENCIES
        if name in requirement.replace(" ", "")
    ]
    assert not offenders, (
        "these dependencies have no linux_armv7l wheel and would require a "
        f"compiler on the deployment target: {offenders}. "
        "See specs/002-config-api/research.md D1."
    )


def test_uvicorn_is_declared_without_any_extra() -> None:
    """The specific mistake worth naming: uvicorn[standard]."""
    uvicorn_requirements = [
        requirement
        for requirement in _declared_requirements()
        if requirement.replace(" ", "").lower().startswith("uvicorn")
    ]
    assert uvicorn_requirements, "uvicorn is no longer declared at all"
    for requirement in uvicorn_requirements:
        assert "[" not in requirement, (
            f"uvicorn must be declared bare, without extras; found {requirement!r}"
        )


def test_the_ban_on_uvicorn_standard_is_explained_where_someone_would_change_it() -> None:
    """A bare ban invites a well-meaning 'fix'. The reason has to be next to it."""
    declared = PYPROJECT.read_text(encoding="utf-8")
    assert "armv7" in declared.lower()
    assert "uvicorn" in declared


def test_the_installed_environment_has_no_forbidden_dependency() -> None:
    """Catches a transitive arrival that the declaration alone would not show."""
    import importlib.util

    # SQLAlchemy publishes a platform-marked greenlet requirement for hosts
    # where greenlet has a wheel (including x86_64 CI runners). The installed
    # environment can therefore only be checked meaningfully on the ARMv7
    # deployment target; declaration-level guards above apply on every host.
    if platform.machine().lower() not in {"armv7l", "armv7"}:
        return

    forbidden_modules = ("uvloop", "httptools", "greenlet")

    for module in forbidden_modules:
        assert importlib.util.find_spec(module) is None, (
            f"{module} got installed transitively; it would need a compiler on "
            "the Raspberry Pi. Find out which dependency pulled it in."
        )


# --------------------------------------------------------------------------- #
# The API service: FR-049, FR-050, FR-051
# --------------------------------------------------------------------------- #

API_UNIT = ROOT / "deploy" / "systemd" / "dynamic-thermal-charge-api.service"
MQTT_UNIT = ROOT / "deploy" / "systemd" / "dynamic-thermal-charge-mqtt.service"


def test_the_api_unit_exists_and_serves_the_api() -> None:
    unit = API_UNIT.read_text(encoding="utf-8")
    assert "ExecStart=" in unit
    assert unit.rstrip().count("ExecStart=") == 1
    assert " api" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/var/lib/dynamic-thermal-charge" in unit


def test_the_api_unit_passes_no_configuration_file() -> None:
    unit = API_UNIT.read_text(encoding="utf-8")
    for line in unit.splitlines():
        if line.startswith(("ExecStart=", "ExecStartPre=")):
            assert ".yaml" not in line and ".yml" not in line


def test_the_api_unit_is_independent_of_the_controller() -> None:
    """The property the whole two-process design exists for."""
    unit = API_UNIT.read_text(encoding="utf-8")
    for coupling in (
        "Requires=dynamic-thermal-charge.service",
        "After=dynamic-thermal-charge.service",
        "BindsTo=dynamic-thermal-charge.service",
        "PartOf=dynamic-thermal-charge.service",
    ):
        assert coupling not in unit, (
            f"the API unit is coupled to the controller via {coupling}; stopping "
            "or restarting one must never touch the other"
        )


def test_the_api_unit_cannot_reach_the_hardware() -> None:
    """No gpio group: this service must not be able to switch a relay."""
    unit = API_UNIT.read_text(encoding="utf-8")
    assert "SupplementaryGroups=gpio" not in unit
    assert "--driver gpio" not in unit


def test_the_api_unit_allows_for_a_slow_start_on_the_pi() -> None:
    """Importing the web stack takes seconds on an ARMv7 core."""
    unit = API_UNIT.read_text(encoding="utf-8")
    assert "TimeoutStartSec=" in unit
    # And no ExecStartPre, which would pay the interpreter start-up cost twice.
    assert "ExecStartPre=" not in unit


def test_the_installer_offers_the_api_without_forcing_it() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "--with-api" in installer
    assert "[db,api]" in installer
    assert "[db,gpio,api]" in installer
    # Installed, never started or enabled. The unit name is composed from
    # SERVICE_NAME, so the literal to look for is the variable.
    assert "API_SERVICE_NAME" in installer
    assert "API_UNIT_PATH" in installer


def test_the_installer_tells_the_operator_to_generate_a_token() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in installer
    assert "DTC_API_TOKEN" in installer


def test_the_environment_example_declares_the_api_variables() -> None:
    environment = ENVIRONMENT.read_text(encoding="utf-8")
    assert "DTC_API_TOKEN=" in environment
    for optional in ("DTC_API_HOST", "DTC_API_PORT", "DTC_API_CORS_ORIGINS"):
        assert optional in environment


def test_the_example_token_is_empty_not_a_placeholder() -> None:
    """An unedited example file must fail the start-up check, not slip through."""
    for line in ENVIRONMENT.read_text(encoding="utf-8").splitlines():
        if line.startswith("DTC_API_TOKEN="):
            assert line.strip() == "DTC_API_TOKEN=", (
                f"the example ships a token value: {line!r}. An operator who "
                "forgets to edit it would end up listening with it"
            )
            break
    else:
        raise AssertionError("DTC_API_TOKEN is not declared in the example")


def test_mqtt_unit_is_independent_restricted_and_has_no_gpio_access():
    unit = MQTT_UNIT.read_text(encoding="utf-8")
    assert "User=dynamic-thermal-charge" in unit
    assert "ExecStart=" in unit and " mqtt" in unit
    assert "ProtectSystem=strict" in unit
    assert "SupplementaryGroups=gpio" not in unit
    assert "--driver gpio" not in unit
    for other in (
        "dynamic-thermal-charge.service",
        "dynamic-thermal-charge-api.service",
        "nginx.service",
    ):
        assert f"Requires={other}" not in unit
        assert f"BindsTo={other}" not in unit
        assert f"PartOf={other}" not in unit


def test_installer_offers_mqtt_without_starting_migrating_or_compiling():
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "--with-mqtt" in installer
    assert "[db,mqtt]" in installer
    assert "MQTT_SERVICE_NAME" in installer
    assert "MQTT_UNIT_PATH" in installer
    # It installs a unit and a pure-Python extra. Runtime actions remain printed
    # instructions, never commands executed by the installer.
    assert "dynamic-thermal-charge-mqtt.service" in installer
    assert "swig" not in "\n".join(
        line for line in installer.splitlines() if "WITH_MQTT" in line
    )


def test_environment_example_documents_mqtt_and_tls_without_a_secret():
    environment = ENVIRONMENT.read_text(encoding="utf-8")
    for variable in (
        "DTC_MQTT_HOST",
        "DTC_MQTT_PORT",
        "DTC_MQTT_USERNAME",
        "DTC_MQTT_PASSWORD",
        "DTC_MQTT_TLS",
        "DTC_MQTT_PREFIX",
        "DTC_MQTT_DISCOVERY_PREFIX",
        "DTC_MQTT_PUBLISH_SECONDS",
    ):
        assert variable in environment
    for line in environment.splitlines():
        if line.startswith("DTC_MQTT_PASSWORD="):
            assert line == "DTC_MQTT_PASSWORD="


def test_the_environment_example_warns_about_exposing_the_api() -> None:
    """FR-051: the risk has to be stated where the change is made."""
    environment = ENVIRONMENT.read_text(encoding="utf-8").lower()
    assert "clear text" in environment
    assert "0.0.0.0" in environment


def test_the_readme_documents_the_api_and_its_risk() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "DTC_API_TOKEN" in readme
    assert "dtc api" in readme
    lowered = readme.lower()
    assert "en claro" in lowered or "clear text" in lowered
    assert "token_urlsafe" in readme


# --------------------------------------------------------------------------- #
# The web panel's nginx site: FR-038 to FR-043.
# --------------------------------------------------------------------------- #

NGINX_SITE = ROOT / "deploy" / "nginx" / "dynamic-thermal-charge.conf"


def _nginx() -> str:
    return NGINX_SITE.read_text(encoding="utf-8")


def test_the_nginx_site_exists_and_serves_the_panel() -> None:
    site = _nginx()
    assert "root /var/www/dynamic-thermal-charge;" in site
    assert "index index.html;" in site


def test_reloading_an_internal_route_works() -> None:
    """FR-040: without try_files, reloading /configuracion returns 404."""
    assert "try_files $uri $uri/ /index.html;" in _nginx()


def test_index_html_is_not_cached() -> None:
    """FR-041: caching it is what makes a new version invisible after deploying."""
    site = _nginx()
    assert 'location = /index.html' in site
    index_block = site.split("location = /index.html")[1].split("}")[0]
    assert 'Cache-Control "no-cache"' in index_block


def test_fingerprinted_assets_are_cached_as_immutable() -> None:
    site = _nginx()
    assert "immutable" in site
    assert "max-age=31536000" in site


def test_the_api_is_proxied_to_the_local_interface_only() -> None:
    """FR-039: nginx is the only component exposed on the network."""
    site = _nginx()
    assert "proxy_pass http://127.0.0.1:8080;" in site
    assert "proxy_pass http://0.0.0.0" not in site
    for line in site.splitlines():
        if "proxy_pass" in line and not line.strip().startswith("#"):
            assert "127.0.0.1" in line, f"a proxy_pass leaves the device: {line.strip()}"


def test_the_credential_header_is_propagated() -> None:
    """Without it, everything through nginx would answer 401."""
    assert "proxy_set_header Authorization $http_authorization;" in _nginx()


def test_the_encryption_block_is_present_and_commented_out() -> None:
    """FR-042: the path documented, not activated."""
    site = _nginx()
    assert "ssl_certificate" in site
    for line in site.splitlines():
        if "ssl_certificate" in line or "listen 443" in line:
            assert line.strip().startswith("#"), (
                f"the encryption block is active, not commented: {line.strip()}"
            )
    lowered = site.lower()
    assert "clear text" in lowered
    assert "internet" in lowered


def test_the_site_does_not_serve_the_database_or_the_state() -> None:
    site = _nginx()
    assert "/var/lib" not in site
    assert ".db" not in site


def test_the_api_documentation_is_not_exposed_through_nginx() -> None:
    """It needs the credential anyway, and the panel does not use it."""
    site = _nginx()
    for line in site.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "/openapi.json" not in stripped
        assert "location = /docs" not in stripped


# --------------------------------------------------------------------------- #
# The installer offers the panel without building anything on the device.
# --------------------------------------------------------------------------- #

def test_the_installer_offers_the_panel_without_forcing_it() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "--with-panel" in installer
    assert "PANEL_ROOT" in installer
    assert "NGINX_SITE" in installer


def test_the_installer_installs_no_node_toolchain_on_the_device() -> None:
    """FR-037: an npm install on a Cortex-A7 with 1 GB does not finish."""
    installer = INSTALLER.read_text(encoding="utf-8")
    offenders = []
    for line in installer.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("echo"):
            continue
        for manager in ("npm ", "npx ", "yarn ", "pnpm ", "nodejs", "install -y node"):
            if manager in stripped:
                offenders.append(stripped)
    assert not offenders, (
        f"the installer would build on the device: {offenders}"
    )


def test_the_installer_does_not_enable_the_nginx_site_itself() -> None:
    """FR-043: it leaves the site available and says what to run."""
    installer = INSTALLER.read_text(encoding="utf-8")
    for line in installer.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("echo"):
            continue
        assert "systemctl reload nginx" not in stripped
        assert "sites-enabled" not in stripped


def test_the_installer_tells_the_operator_to_build_off_device() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    assert "npm run build" in installer  # inside an echo, as instructions
    assert "off-device" in installer or "no Node" in installer


def test_the_readme_documents_the_panel_and_where_it_is_built() -> None:
    """FR-042, and the warning that matters most: never build on the device."""
    readme = README.read_text(encoding="utf-8")
    assert "Panel web" in readme
    assert "npm run build" in readme
    lowered = readme.lower()
    # Built off-device, and said plainly.
    assert "no se instala node" in lowered
    assert "cortex-a7" in lowered
    # The encryption gap, stated where the deployment is described.
    assert "en claro" in lowered
    assert "internet no lo es" in lowered
    # And the property the whole nginx choice buys.
    assert "127.0.0.1" in readme


def test_the_readme_explains_what_the_panel_refuses_to_claim() -> None:
    """The single most misusable field in the system, documented for the operator."""
    readme = README.read_text(encoding="utf-8").lower()
    assert "sin confirmar" in readme
    assert "no muestra ninguna cifra de potencia" in readme
