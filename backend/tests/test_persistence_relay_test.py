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


def test_starting_session_can_renew_but_cannot_activate_without_a_live_runner(initialised_store, clock):
    repo = initialised_store.relay_tests
    digest = relay_test_credential_digest("owner")
    session_id = repo.claim(digest, clock(), 30)["session"]["id"]

    assert repo.renew(session_id, digest, clock(), 30)["session"]["status"] == "starting"
    assert repo.activate(session_id, "runner-a", clock()) is False
    assert repo.get(session_id)["session"]["status"] == "starting"


def test_activation_rechecks_runner_heartbeat_and_lease(initialised_store, clock):
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    publisher = SqlHeartbeatPublisher(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5,
        driver_kind="gpio",
        started_at=clock(),
        runner_id="runner-a",
        location=initialised_store.location,
    )
    publisher.publish(clock(), degraded=False)

    assert repo.activate(session_id, "runner-a", clock()) is True


def test_activation_rejects_an_expired_lease(initialised_store, clock):
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher

    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 1)["session"]["id"]
    publisher = SqlHeartbeatPublisher(
        initialised_store.application_engine or initialised_store.engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5,
        driver_kind="gpio",
        started_at=clock(),
        runner_id="runner-a",
        location=initialised_store.location,
    )
    publisher.publish(clock(), degraded=False)

    clock.advance(seconds=2)

    assert repo.activate(session_id, "runner-a", clock()) is False


def test_activation_rejects_a_changed_installation_revision(initialised_store, clock):
    from dynamic_thermal_charge.persistence.heartbeat import SqlHeartbeatPublisher
    from dynamic_thermal_charge.persistence.schema import installation

    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    engine = initialised_store.application_engine or initialised_store.engine
    with initialised_store.engine.begin() as connection:
        connection.execute(
            installation.update()
            .where(installation.c.id == initialised_store.repository.installation_id())
            .values(revision=installation.c.revision + 1)
        )
    publisher = SqlHeartbeatPublisher(
        engine,
        initialised_store.repository.installation_id(),
        poll_seconds=5,
        driver_kind="gpio",
        started_at=clock(),
        runner_id="runner-a",
        location=initialised_store.location,
    )
    publisher.publish(clock(), degraded=False)

    assert repo.activate(session_id, "runner-a", clock()) is False

def test_terminal_session_remains_readable(initialised_store, clock):
    repo = initialised_store.relay_tests
    digest = relay_test_credential_digest("owner")
    session_id = repo.claim(digest, clock(), 30)["session"]["id"]
    repo.end(session_id, clock())
    assert repo.current() is None
    assert repo.get(session_id)["session"]["status"] == "ended"


def test_terminal_off_sweep_records_confirmed_and_unknown_outputs(initialised_store, clock):
    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    outputs = repo.get(session_id)["heaters"]
    repo.confirm(session_id, outputs[0]["heater_id"], 0, True, clock())

    repo.end(
        session_id,
        clock(),
        off_results={outputs[0]["heater_id"]: True},
    )

    terminal = repo.get(session_id)
    assert terminal["session"]["status"] == "failed"
    by_id = {output["heater_id"]: output for output in terminal["heaters"]}
    assert by_id[outputs[0]["heater_id"]]["confirmed_state"] is False
    assert by_id[outputs[0]["heater_id"]]["result"] == "confirmed"
    assert by_id[outputs[1]["heater_id"]]["confirmed_state"] is None
    assert by_id[outputs[1]["heater_id"]]["result"] == "unknown"


def test_relay_test_events_are_paged_and_terminal_retention_is_bounded(initialised_store, clock):
    repo = initialised_store.relay_tests
    session_id = repo.claim(relay_test_credential_digest("owner"), clock(), 30)["session"]["id"]
    repo.end(session_id, clock())
    installation_id = initialised_store.repository.installation_id()
    page = SqlHistoryReader(initialised_store.engine, installation_id).relay_tests(limit=1)
    assert page.items and page.items[0]["session_id"] == session_id
    report = SqlHistoryRecorder(
        initialised_store.application_engine or initialised_store.engine,
        installation_id,
    ).prune(
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
    engine = initialised_store.application_engine or initialised_store.engine
    with engine.begin() as connection:
        connection.execute(text("CREATE TRIGGER relay_event_failure BEFORE INSERT ON relay_test_event BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"))
    repo.end(session_id, clock())
    assert repo.get(session_id)["session"]["status"] == "ended"
    assert repo.current()["audit"]["degraded"] is True
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER relay_event_failure"))
    repo.arm_latch(session_id, clock(), "off_sweep_failed")
    assert repo.current()["audit"]["degraded"] is False
