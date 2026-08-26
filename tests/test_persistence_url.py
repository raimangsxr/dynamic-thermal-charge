"""Store location resolution: FR-002, FR-003, FR-004, FR-005."""

from __future__ import annotations

import pytest

from dynamic_thermal_charge.persistence.url import (
    DATABASE_URL_ENV,
    DatabaseUrlError,
    parse_location,
    resolve_location,
)


def test_missing_variable_names_itself_and_shows_how_to_define_it():
    with pytest.raises(DatabaseUrlError) as error:
        resolve_location({})
    message = str(error.value)
    assert DATABASE_URL_ENV in message
    assert "sqlite:" in message
    assert "postgresql+pg8000:" in message


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_variable_is_treated_as_missing(value):
    with pytest.raises(DatabaseUrlError) as error:
        resolve_location({DATABASE_URL_ENV: value})
    assert DATABASE_URL_ENV in str(error.value)


def test_unsupported_backend_lists_the_supported_ones():
    with pytest.raises(DatabaseUrlError) as error:
        parse_location("mysql://user@host/database")
    message = str(error.value)
    assert "mysql" in message
    assert "sqlite" in message and "postgresql" in message


def test_unsupported_postgres_driver_explains_why():
    with pytest.raises(DatabaseUrlError) as error:
        parse_location("postgresql+psycopg2://user@host/database")
    assert "pg8000" in str(error.value)


def test_absolute_sqlite_path_keeps_its_leading_slash():
    location = parse_location("sqlite:////var/lib/dtc/dtc.db")
    assert location.backend == "sqlite"
    assert location.remote is False
    assert location.host is None
    assert location.database == "/var/lib/dtc/dtc.db"


def test_relative_sqlite_path_stays_relative():
    assert parse_location("sqlite:///var/dtc.db").database == "var/dtc.db"


def test_sqlite_url_rejects_a_host():
    with pytest.raises(DatabaseUrlError) as error:
        parse_location("sqlite://server/dtc.db")
    assert "host" in str(error.value)


def test_sqlite_url_requires_a_file():
    with pytest.raises(DatabaseUrlError):
        parse_location("sqlite://")


def test_postgres_url_with_credentials_is_marked_remote():
    location = parse_location("postgresql+pg8000://user:secret@server:5432/dtc")
    assert location.backend == "postgresql"
    assert location.remote is True
    assert location.host == "server:5432"
    assert location.database == "dtc"


def test_postgres_url_without_driver_is_normalised_to_pg8000():
    location = parse_location("postgresql://user:secret@server/dtc")
    assert location.url.startswith("postgresql+pg8000://")


def test_postgres_url_requires_host_and_database():
    with pytest.raises(DatabaseUrlError):
        parse_location("postgresql+pg8000:///dtc")
    with pytest.raises(DatabaseUrlError):
        parse_location("postgresql+pg8000://user@server/")


def test_a_value_without_a_scheme_is_rejected():
    with pytest.raises(DatabaseUrlError):
        parse_location("/var/lib/dtc/dtc.db")


# --- FR-005 and research.md D11: credentials must never be logged ---

SECRET = "tr3m3nd0-s3cr3t0"


def test_description_never_contains_the_url_or_the_password():
    location = parse_location(f"postgresql+pg8000://dtc:{SECRET}@server:5432/dtc")
    described = location.description.describe()
    assert SECRET not in described
    assert "postgresql+pg8000://" not in described
    assert "dtc:" not in described
    # It must still say enough to tell local from remote.
    assert "remote" in described
    assert "server:5432" in described
    assert "postgresql" in described


def test_local_description_says_local():
    described = parse_location("sqlite:////var/lib/dtc/dtc.db").description.describe()
    assert "local" in described
    assert "remote" not in described


def test_parse_errors_do_not_echo_credentials():
    with pytest.raises(DatabaseUrlError) as error:
        parse_location(f"not-a-url-with-user:{SECRET}@host")
    assert SECRET not in str(error.value)


def test_description_fields_are_built_one_by_one_not_rendered_from_the_url():
    """A new URL component must not be able to leak through the description."""
    location = parse_location(
        f"postgresql+pg8000://dtc:{SECRET}@server:5432/dtc?sslmode=require"
    )
    description = location.description
    assert description.backend == "postgresql"
    assert description.host == "server:5432"
    assert description.database == "dtc"
    assert SECRET not in description.describe()
    assert "sslmode" not in description.describe()
