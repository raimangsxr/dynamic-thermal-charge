from dynamic_thermal_charge.api.security import relay_test_credential_digest
from dynamic_thermal_charge.persistence.history import SqlHistoryReader, SqlHistoryRecorder
from sqlalchemy import text

def test_claim_command_and_owner_are_atomic(initialised_store, clock):
    repo = initialised_store.relay_tests
    owner = relay_test_credential_digest("owner")
    view = repo.claim(owner, clock(), 30)
    session = view["session"]
    assert session["status"] == "starting"
    assert repo.current()["session"]["id"] == session["id"]
    try:
        repo.command(session["id"], view["heaters"][0]["heater_id"], True, relay_test_credential_digest("other"), clock())
    except Exception as exc:
        assert getattr(exc, "code", None) == "relay_test_not_owner"
    else:
        raise AssertionError("a non-owner must never create a GPIO intention")

def test_terminal_session_remains_readable(initialised_store, clock):
    repo = initialised_store.relay_tests
    digest = relay_test_credential_digest("owner")
    session_id = repo.claim(digest, clock(), 30)["session"]["id"]
    repo.end(session_id, clock())
    assert repo.current() is None
    assert repo.get(session_id)["session"]["status"] == "ended"


def test_relay_test_events_are_paged_and_terminal_retention_is_bounded(initialised_store, clock):
    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    repo.end(session_id, clock())
    installation_id = initialised_store.repository.installation_id()
    page = SqlHistoryReader(initialised_store.engine, installation_id).relay_tests(limit=1)
    assert page.items and page.items[0]["session_id"] == session_id
    report = SqlHistoryRecorder(initialised_store.engine, installation_id).prune(
        clock.advance(days=2), retention_days=1
    )
    assert report.deleted["relay_test_session"] == 1
    assert repo.get(session_id) is None


def test_latch_recovery_requires_the_observed_generation(initialised_store, clock):
    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    repo.end(session_id, clock(), failed=True, reason="off_sweep_failed")
    generation = repo.current()["safety"]["fault_generation"]

    assert repo.recover_latch(generation - 1, clock()) is False
    assert repo.current()["safety"]["fault_latched"] is True
    assert repo.recover_latch(generation, clock()) is True
    assert repo.current() is None


def test_audit_failure_degrades_without_blocking_terminal_safety(initialised_store, clock):
    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    with initialised_store.engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER relay_event_failure BEFORE INSERT ON relay_test_event BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"))
    repo.end(session_id, clock())
    assert repo.get(session_id)["session"]["status"] == "ended"
    assert repo.current()["audit"]["degraded"] is True
    with initialised_store.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER relay_event_failure"))
    repo.arm_latch(session_id, clock(), "off_sweep_failed")
    assert repo.current()["audit"]["degraded"] is False
