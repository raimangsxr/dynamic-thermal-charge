"""The CLI contract: exit codes, messages, and never touching hardware."""

from __future__ import annotations

import pytest

from dynamic_thermal_charge import cli
from dynamic_thermal_charge.persistence.url import DATABASE_URL_ENV


SECRET = "tr3m3nd0-s3cr3t0"


@pytest.fixture
def run(monkeypatch, sqlite_url, capsys):
    """Invoke the CLI with the store pointed at a temporary SQLite file."""
    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)

    def _run(*argv: str):
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def initialised(run):
    code, _, _ = run("db", "init")
    assert code == cli.EXIT_OK
    return run


# --------------------------------------------------------------------------- #
# db init / db upgrade (FR-011, FR-012, FR-013)
# --------------------------------------------------------------------------- #

def test_init_creates_and_seeds_an_empty_database(run):
    code, out, _ = run("db", "init")
    assert code == cli.EXIT_OK
    assert "Schema created" in out
    assert "Seeded" in out


def test_init_is_idempotent(initialised):
    code, out, _ = initialised("db", "init")
    assert code == cli.EXIT_OK
    assert "already at revision" in out
    assert "seeding skipped" in out


def test_init_with_no_seed_leaves_the_database_empty(run):
    code, out, _ = run("db", "init", "--no-seed")
    assert code == cli.EXIT_OK
    code, _, err = run("config", "show")
    assert code == cli.EXIT_NO_CONFIGURATION
    assert "db init" in err


def test_upgrade_never_seeds(run):
    code, out, _ = run("db", "upgrade")
    assert code == cli.EXIT_OK
    assert "seeding skipped" in out


# --------------------------------------------------------------------------- #
# config show (FR-014)
# --------------------------------------------------------------------------- #

def test_show_prints_the_whole_installation(initialised):
    code, out, _ = initialised("config", "show")
    assert code == cli.EXIT_OK
    assert "Config revision:  1" in out
    assert "max_total_power_kw          5.2" in out
    assert "retention_days              365" in out
    for heater_id in ("salon", "entrada", "habitaciones", "buhardilla"):
        assert heater_id in out


def test_show_can_be_limited_to_one_heater(initialised):
    code, out, _ = initialised("config", "show", "--heater", "salon")
    assert code == cli.EXIT_OK
    assert "salon" in out
    assert "buhardilla" not in out


def test_show_on_an_unknown_heater_lists_the_existing_ones(initialised):
    code, _, err = initialised("config", "show", "--heater", "cocina")
    assert code == cli.EXIT_UNKNOWN_NAME
    assert "cocina" in err
    assert "salon" in err


# --------------------------------------------------------------------------- #
# T041: no command may reveal a credential
# --------------------------------------------------------------------------- #

def test_show_never_reveals_the_connection_string(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'dtc.db'}")
    cli.main(["db", "init"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "sqlite:///" not in out, "the connection string was printed"
    assert str(tmp_path / "dtc.db") in out or "dtc.db" in out  # the path is fine


def test_show_prints_the_api_key_variable_name_not_its_value(initialised, monkeypatch):
    monkeypatch.setenv("AEMET_API_KEY", SECRET)
    code, out, _ = initialised("config", "show")
    assert code == cli.EXIT_OK
    assert "AEMET_API_KEY" in out
    assert SECRET not in out, "the AEMET key was printed"


# --------------------------------------------------------------------------- #
# T042: no administrative command constructs an output driver (principle I)
# --------------------------------------------------------------------------- #

ADMIN_COMMANDS = [
    ("db", "init"),
    ("db", "upgrade"),
    ("config", "show"),
    ("config", "set", "poll_seconds", "7"),
    ("config", "add-heater", "cocina", "--power-kw", "1.2", "--full-charge-hours", "7"),
    ("config", "remove-heater", "buhardilla", "--yes"),
    ("history", "prune"),
]


@pytest.mark.parametrize("command", ADMIN_COMMANDS, ids=lambda c: " ".join(c))
def test_an_administrative_command_never_builds_a_driver(
    initialised, monkeypatch, command
):
    built: list[str] = []

    def _forbidden(config, driver_name):
        built.append(driver_name)
        raise AssertionError("an administrative command built an output driver")

    monkeypatch.setattr(cli, "_build_output_driver", _forbidden)
    code, _, _ = initialised(*command)
    assert code == cli.EXIT_OK
    assert built == []


# --------------------------------------------------------------------------- #
# config set / add-heater / remove-heater exit codes
# --------------------------------------------------------------------------- #

def test_set_reports_both_values_and_the_revision(initialised):
    code, out, _ = initialised("config", "set", "max_total_power_kw", "6.0")
    assert code == cli.EXIT_OK
    assert "5200 -> 6000" in out
    assert "revision 1 -> 2" in out


def test_empty_indoor_topic_clears_the_optional_field(initialised):
    code, _, _ = initialised(
        "config", "set", "indoor_topic", "ha/salon", "--heater", "salon"
    )
    assert code == cli.EXIT_OK
    code, out, _ = initialised(
        "config", "set", "indoor_topic", "", "--heater", "salon"
    )
    assert code == cli.EXIT_OK
    assert "ha/salon -> —" in out


def test_set_on_a_heater_field_needs_the_heater(initialised):
    code, _, err = initialised("config", "set", "target_charge", "0.5")
    assert code == cli.EXIT_UNKNOWN_NAME
    assert "--heater" in err


def test_set_on_an_unknown_field_lists_the_admissible_ones(initialised):
    code, _, err = initialised("config", "set", "maximum_power", "6")
    assert code == cli.EXIT_UNKNOWN_NAME
    assert "max_total_power_kw" in err


def test_set_on_an_unknown_heater_lists_the_existing_ones(initialised):
    code, _, err = initialised("config", "set", "priority", "5", "--heater", "cocina")
    assert code == cli.EXIT_UNKNOWN_NAME
    assert "salon" in err


def test_set_to_an_invalid_value_is_refused(initialised):
    code, _, err = initialised("config", "set", "slot_minutes", "45")
    assert code == cli.EXIT_INVALID_RESULT
    assert "divisor of 60" in err
    # And nothing changed.
    _, out, _ = initialised("config", "show")
    assert "slot_minutes                30" in out


def test_set_refuses_a_value_that_looks_like_a_secret(initialised):
    code, _, err = initialised(
        "config", "set", "state_file", f"postgresql://dtc:{SECRET}@host/dtc"
    )
    assert code == cli.EXIT_SECRET_REJECTED
    assert "environment variable" in err


def test_a_stale_edit_reports_a_conflict(initialised, monkeypatch):
    from dynamic_thermal_charge.persistence.repository import SqlConfigRepository

    real_current = SqlConfigRepository.current

    def _stale(self):
        config, revision = real_current(self)
        return config, revision - 1  # pretend we read an older revision

    monkeypatch.setattr(SqlConfigRepository, "current", _stale)
    code, _, err = initialised("config", "set", "poll_seconds", "8")
    assert code == cli.EXIT_CONFLICT
    assert "revision" in err


def test_add_heater_then_show_it(initialised):
    code, out, _ = initialised(
        "config", "add-heater", "cocina",
        "--power-kw", "1.2", "--full-charge-hours", "7",
        "--output", "gpio", "--pin", "24", "--no-active-high",
        "--target-temperature-c", "20", "--design-outdoor-temperature-c", "-2",
    )
    assert code == cli.EXIT_OK
    assert "added heater cocina" in out
    code, out, _ = initialised("config", "show", "--heater", "cocina")
    assert code == cli.EXIT_OK
    assert "pin                       24" in out
    assert "active_high               false" in out


def test_add_heater_with_an_existing_id_is_refused(initialised):
    code, _, err = initialised(
        "config", "add-heater", "salon", "--power-kw", "1", "--full-charge-hours", "7"
    )
    assert code == cli.EXIT_ALREADY_EXISTS
    assert "salon" in err


def test_add_heater_on_a_used_pin_is_refused(initialised):
    code, _, err = initialised(
        "config", "add-heater", "cocina",
        "--power-kw", "1", "--full-charge-hours", "7",
        "--output", "gpio", "--pin", "17",
    )
    assert code == cli.EXIT_INVALID_RESULT
    assert "17" in err and "salon" in err


def test_add_heater_with_half_a_thermal_profile_is_refused(initialised):
    code, _, err = initialised(
        "config", "add-heater", "cocina",
        "--power-kw", "1", "--full-charge-hours", "7",
        "--target-temperature-c", "20",
    )
    assert code == cli.EXIT_INVALID_RESULT
    assert "design-outdoor-temperature-c" in err


def test_remove_heater_needs_confirmation(initialised, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    code, out, _ = initialised("config", "remove-heater", "buhardilla")
    assert code == cli.EXIT_OK
    assert "cancelled" in out
    _, out, _ = initialised("config", "show")
    assert "buhardilla" in out


def test_remove_heater_with_yes_skips_the_prompt(initialised):
    code, out, _ = initialised("config", "remove-heater", "buhardilla", "--yes")
    assert code == cli.EXIT_OK
    assert "history is retained" in out
    _, out, _ = initialised("config", "show")
    assert "buhardilla" not in out


def test_remove_an_unknown_heater_is_refused(initialised):
    code, _, err = initialised("config", "remove-heater", "cocina", "--yes")
    assert code == cli.EXIT_UNKNOWN_NAME
    assert "salon" in err


# --------------------------------------------------------------------------- #
# history prune
# --------------------------------------------------------------------------- #

def test_prune_reports_when_there_is_nothing_to_do(initialised):
    code, out, _ = initialised("history", "prune")
    assert code == cli.EXIT_OK
    assert "nothing older than 365 days" in out


def test_prune_says_retention_is_unlimited(initialised):
    initialised("config", "set", "retention_days", "none")
    code, out, _ = initialised("history", "prune")
    assert code == cli.EXIT_OK
    assert "unlimited" in out


# --------------------------------------------------------------------------- #
# T054: start-up failure paths. In every one, no output is energised.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "command",
    [("run",), ("run", "--controller"), ("config", "show"), ("history", "prune")],
    ids=lambda c: " ".join(c),
)
def test_a_missing_environment_variable_fails_without_touching_hardware(
    monkeypatch, capsys, command
):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a driver was built with no configuration available")

    monkeypatch.setattr(cli, "_build_output_driver", _forbidden)
    code = cli.main(list(command))
    err = capsys.readouterr().err
    assert code == cli.EXIT_STORE_UNAVAILABLE
    assert DATABASE_URL_ENV in err


def test_an_unsupported_backend_lists_the_supported_ones(monkeypatch, capsys):
    monkeypatch.setenv(DATABASE_URL_ENV, "mysql://user@host/db")
    code = cli.main(["config", "show"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_STORE_UNAVAILABLE
    assert "sqlite" in err and "postgresql" in err


def test_a_missing_schema_suggests_db_init(monkeypatch, sqlite_url, capsys):
    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    code = cli.main(["config", "show"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_STORE_UNAVAILABLE
    assert "db init" in err


def test_an_unknown_schema_revision_refuses_to_start(monkeypatch, sqlite_url, capsys):
    from sqlalchemy import text

    from dynamic_thermal_charge.persistence.bootstrap import open_store
    from dynamic_thermal_charge.persistence.gate import VERSION_TABLE

    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    assert cli.main(["db", "init"]) == cli.EXIT_OK
    capsys.readouterr()
    store = open_store()
    with store.engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {VERSION_TABLE}"))
        connection.execute(
            text(f"INSERT INTO {VERSION_TABLE} (version_num) VALUES ('9999_future')")
        )

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a driver was built on an unreadable schema")

    monkeypatch.setattr(cli, "_build_output_driver", _forbidden)
    code = cli.main(["run", "--controller"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_SCHEMA_UNKNOWN
    assert "9999_future" in err
    assert "does not understand" in err


def test_an_empty_database_is_reported_as_no_configuration(
    monkeypatch, sqlite_url, capsys
):
    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    cli.main(["db", "init", "--no-seed"])
    capsys.readouterr()
    code = cli.main(["run"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_NO_CONFIGURATION
    assert "db init" in err


def test_stored_configuration_that_is_invalid_refuses_to_run(
    monkeypatch, sqlite_url, capsys
):
    """External tampering must stop the run, not energise anything."""
    from sqlalchemy import text

    from dynamic_thermal_charge.persistence.bootstrap import open_store

    monkeypatch.setenv(DATABASE_URL_ENV, sqlite_url)
    cli.main(["db", "init"])
    capsys.readouterr()
    store = open_store()
    with store.engine.begin() as connection:
        # Straight SQL, bypassing every validator: a slot that is not a divisor
        # of 60. This is what the CLI refuses to let anyone do.
        connection.execute(text("UPDATE installation SET slot_minutes = 45"))

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("a driver was built on an invalid configuration")

    monkeypatch.setattr(cli, "_build_output_driver", _forbidden)
    code = cli.main(["run", "--controller"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_INVALID_RESULT
    assert "divisor of 60" in err


# --------------------------------------------------------------------------- #
# T047: the removed configuration-file argument explains itself
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "argument",
    ["examples/home.yaml", "/etc/dynamic-thermal-charge/config.yaml", "config.yml"],
)
def test_a_configuration_file_path_explains_the_change(argument):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([argument, "--run-controller"])
    message = str(exit_info.value)
    assert DATABASE_URL_ENV in message
    assert "db init" in message


def test_check_config_validates_without_planning(initialised):
    code, _, _ = initialised("run", "--check-config")
    assert code == cli.EXIT_OK


def test_run_builds_a_plan(initialised, monkeypatch):
    monkeypatch.setenv("AEMET_API_KEY", "")  # forces the configured fallback
    code, out, _ = initialised("run", "--start", "2026-01-16T00:00:00")
    assert code in (cli.EXIT_OK, cli.EXIT_UNMET_DEMAND)
    assert "Charge plan" in out


def test_driver_gpio_is_refused_outside_controller_mode(initialised):
    code, _, err = initialised("run", "--driver", "gpio")
    assert code == cli.EXIT_INVALID_RESULT
    assert "--controller" in err
