import logging

from dynamic_thermal_charge.api.logging import HealthcheckAccessFilter


def _record(status_code: int, path: str = "/health") -> logging.LogRecord:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1", "GET", path, "1.1", status_code),
        None,
    )
    return record


def test_successful_healthcheck_is_debug_and_hidden_at_info():
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.INFO)
    try:
        record = _record(200)

        assert HealthcheckAccessFilter().filter(record) is False
        assert record.levelno == logging.DEBUG
    finally:
        root.setLevel(previous)


def test_successful_healthcheck_is_visible_at_debug():
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    try:
        record = _record(200)

        assert HealthcheckAccessFilter().filter(record) is True
        assert record.levelno == logging.DEBUG
    finally:
        root.setLevel(previous)


def test_failed_healthcheck_is_error():
    record = _record(503)

    assert HealthcheckAccessFilter().filter(record) is True
    assert record.levelno == logging.ERROR


def test_other_access_records_are_unchanged():
    record = _record(200, "/api/v1/status")

    assert HealthcheckAccessFilter().filter(record) is True
    assert record.levelno == logging.INFO
